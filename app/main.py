"""
GaugeVision AI — FastAPI-приложение: REST API, WebSocket-эндпоинты, оркестрация
конвейера зрения для всех камер.

WebSocket:
  /ws/dashboard              — живая телеметрия, статусы, события для дашборда
  /ws/phone/{cam_id}?token=  — бинарные JPEG/WebP-кадры со смартфона (WSS)

REST (основное):
  GET    /api/meta                      справочники, LAN IP, ссылки, версия
  GET    /api/cameras                   список приборов с живым состоянием
  POST   /api/cameras                   добавить прибор/камеру
  PATCH  /api/cameras/{id}              изменить (имя, тип, шкала, уставки…)
  DELETE /api/cameras/{id}              удалить
  POST   /api/cameras/{id}/restart      перезапустить поток
  POST   /api/cameras/{id}/redetect     повторная локализация циферблата
  GET    /api/cameras/{id}/frame.jpg    последний кадр (с оверлеем анализа)
  GET    /api/cameras/{id}/mjpeg        MJPEG-поток кадров с оверлеем
  GET    /api/cameras/{id}/history      история телеметрии
  GET    /api/cameras/{id}/trend        агрегированный тренд (min/max/среднее) с момента since
  GET    /api/events                    журнал событий пульта (срабатывания, связь, действия)
  GET    /api/events/{id}/frame.jpg     стоп-кадр распознавания в момент срабатывания
  GET    /api/cameras/{id}/export.csv   экспорт истории в CSV (ISO 8601)
  POST   /api/phone/session             «Смартфон как камера»: токен + QR-код
  GET    /api/discover                  ONVIF WS-Discovery + скан подсети /24
  POST   /api/alarms/ack                квитирование аварий на всех дашбордах
  GET    /api/cert.pem                  самоподписный сертификат (для смартфона)
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import io
import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Literal
from urllib.parse import quote

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import __app_name__, __version__, config, db, demo, discovery, vision
from .events import EventLog, crossed_setpoint
from .streamer import FrameBroker, StreamManager, encode_jpeg

logger = logging.getLogger("gaugevision.main")


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------
GaugeType = Literal["pressure", "temperature", "draft", "level", "electrical", "flow"]
CameraType = Literal["device", "rtsp", "http_mjpeg", "phone_ws"]


class RoiModel(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    cx: float = Field(0.5, ge=0.05, le=0.95)
    cy: float = Field(0.5, ge=0.05, le=0.95)
    r: float = Field(0.45, ge=0.05, le=1.0)


class CalibrationModel(BaseModel):
    v_min: float = 0.0
    theta_min: float = 135.0
    v_max: float = 10.0
    theta_max: float = 45.0
    direction: Literal["cw", "ccw"] = "cw"
    roi: RoiModel | None = None

    @field_validator("v_min", "v_max")
    @classmethod
    def _finite_val(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("значение шкалы должно быть конечным числом")
        return float(v)

    @field_validator("theta_min", "theta_max")
    @classmethod
    def _norm_angle(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("угол должен быть числом")
        return v % 360.0

    @field_validator("v_max")
    @classmethod
    def _span(cls, v: float, info: Any) -> float:
        if "v_min" in info.data and abs(v - info.data["v_min"]) < 1e-9:
            raise ValueError("V_max должен отличаться от V_min (нулевой диапазон шкалы)")
        return v

    def check_geometry(self) -> None:
        if self.direction == "cw":
            ang_span = (self.theta_max - self.theta_min) % 360.0
        else:
            ang_span = (self.theta_min - self.theta_max) % 360.0
        if ang_span < 5.0 or ang_span > 355.0:
            raise HTTPException(
                422,
                "Нулевой или вырожденный угловой размах шкалы: задайте две различимые отметки θmin и θmax",
            )
        if self.roi and self.roi.mode == "manual":
            if self.roi.cx - self.roi.r < -0.15 or self.roi.cx + self.roi.r > 1.15 \
                    or self.roi.cy - self.roi.r < -0.15 or self.roi.cy + self.roi.r > 1.15:
                raise HTTPException(422, "Область ROI выходит за пределы кадра")


class ThresholdsModel(BaseModel):
    ll_alert: float | None = None
    l_warn: float | None = None
    h_warn: float | None = None
    hh_alert: float | None = None
    lower_enabled: bool | None = None

    @field_validator("ll_alert", "l_warn", "h_warn", "hh_alert")
    @classmethod
    def _finite_thr(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("уставка должна быть конечным числом")
        return v

    def check_order(self, scale_lo: float | None = None, scale_hi: float | None = None) -> None:
        """MIN ≤ LL < L < H < HH ≤ MAX (незаданные или отключённые нижние уставки пропускаются)."""
        keys = ("h_warn", "hh_alert") if self.lower_enabled is False else (
            "ll_alert", "l_warn", "h_warn", "hh_alert"
        )
        seq = [(n, getattr(self, n)) for n in keys]
        seq = [(n, v) for n, v in seq if v is not None]
        for (n1, v1), (n2, v2) in zip(seq, seq[1:]):
            if v1 >= v2:
                raise HTTPException(
                    422,
                    f"Уставки должны строго возрастать без равных границ: {n1} ({v1}) ≥ {n2} ({v2})",
                )
        if scale_lo is not None and scale_hi is not None:
            lo, hi = min(scale_lo, scale_hi), max(scale_lo, scale_hi)
            for name, val in seq:
                if val < lo - 1e-9 or val > hi + 1e-9:
                    raise HTTPException(
                        422,
                        f"Уставка {name} ({val}) выходит за границы шкалы [{lo}…{hi}]",
                    )


class CameraCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: CameraType
    gauge_type: GaugeType = "pressure"
    unit: str | None = None
    source_url: str | None = Field(None, max_length=2000)
    calibration: CalibrationModel | None = None
    thresholds: ThresholdsModel | None = None


class CameraUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    type: CameraType | None = None
    gauge_type: GaugeType | None = None
    unit: str | None = None
    source_url: str | None = Field(None, max_length=2000)
    calibration: CalibrationModel | None = None
    thresholds: ThresholdsModel | None = None


class PhoneSessionRequest(BaseModel):
    cam_id: str | None = None
    name: str | None = Field(None, max_length=200)
    gauge_type: GaugeType = "pressure"
    unit: str | None = None
    regenerate: bool = False


class DemoRunStartRequest(BaseModel):
    cam_id: str | None = None
    label: str | None = Field(None, max_length=120)


class DemoRunStopRequest(BaseModel):
    run_id: str | None = None


class DemoScenarioRequest(BaseModel):
    scenario: Literal["mixed", "nominal", "peak", "cascade"]


class AckRequest(BaseModel):
    event_id: int | None = None
    cam_id: str | None = None


def _validate_unit(gauge_type: str, unit: str | None) -> str:
    units = config.GAUGE_TYPES[gauge_type]["units"]
    if unit is None:
        return units[0]
    if unit not in units:
        raise HTTPException(422, f"Единица «{unit}» недопустима для типа «{gauge_type}». "
                                 f"Допустимо: {', '.join(units)}")
    return unit


def _validate_source(cam_type: str, url: str | None) -> str | None:
    url = (url or "").strip() or None
    if cam_type == "device":
        return url or "0"
    if cam_type == "phone_ws":
        return None
    if not url:
        raise HTTPException(422, "Не указан адрес потока (source_url)")
    low = url.lower()
    if cam_type == "rtsp" and not low.startswith(("rtsp://", "rtsps://")):
        raise HTTPException(422, "RTSP-адрес должен начинаться с rtsp://")
    if cam_type == "http_mjpeg" and not low.startswith(("http://", "https://")):
        raise HTTPException(422, "HTTP/MJPEG-адрес должен начинаться с http:// или https://")
    return url


# ---------------------------------------------------------------------------
# Хаб WebSocket-клиентов дашборда
# ---------------------------------------------------------------------------
class DashboardHub:
    """
    Рассылка событий всем дашбордам. У каждого клиента своя очередь и
    задача-отправитель: медленный клиент (смартфон в плохом Wi-Fi) не
    тормозит остальных, а конкурентные send() не перемешиваются.
    """

    QUEUE_SIZE = 300

    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Queue[str]] = {}

    @property
    def count(self) -> int:
        return len(self._clients)

    def add(self, ws: WebSocket) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(self.QUEUE_SIZE)
        self._clients[ws] = q
        return q

    def remove(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    def broadcast(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False, default=_json_default)
        for ws, q in list(self._clients.items()):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                # клиент не успевает — отбрасываем самое старое сообщение
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(data)


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return str(o)


# ---------------------------------------------------------------------------
# Сервис мониторинга: камеры, конвейеры зрения, телеметрия
# ---------------------------------------------------------------------------
def _round(v: float | None, nd: int = 4) -> float | None:
    return None if v is None else round(float(v), nd)


class GaugeService:
    def __init__(self) -> None:
        self.hub = DashboardHub()
        self.broker = FrameBroker()
        self.streams = StreamManager(self.broker, on_status=self._on_status)
        self.executor = ThreadPoolExecutor(max_workers=config.VISION_EXECUTOR_WORKERS,
                                           thread_name_prefix="vision")
        self.cameras: dict[str, dict[str, Any]] = {}
        self.pipelines: dict[str, vision.GaugePipeline] = {}
        self.last: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._db_buffer: list[tuple[Any, ...]] = []
        self._last_db_write: dict[str, float] = {}
        self._bg: list[asyncio.Task] = []
        self.lan_ip = config.get_lan_ip()
        self.started_at = time.time()
        self.events = EventLog()
        self.sim_adapter = demo.SimulatedTelemetryAdapter(config.DEMO_SEED)
        self._sim_prev_levels: dict[str, str] = {}
        self._live_spark: dict[str, list[float]] = {}
        self.active_run: dict[str, Any] | None = None

    def emit(self, kind: str, **fields: Any) -> dict[str, Any]:
        """Запись в журнал событий и рассылка её всем пультам."""
        ev = self.events.add(kind, **fields)
        self.hub.broadcast({"type": "event", "event": ev})
        return ev

    # -- жизненный цикл ------------------------------------------------------
    async def start(self) -> None:
        self.cameras.clear()
        self.pipelines.clear()
        self.last.clear()
        self._db_buffer.clear()
        self._last_db_write.clear()
        self.active_run = None
        await db.init_db()
        if config.is_demo_mode():
            await self._ensure_demo_camera()
        # загрузка и прогрев YOLO (torch/CUDA) — вне event-loop, до старта конвейеров
        await asyncio.get_running_loop().run_in_executor(self.executor, vision.yolo_available)
        for cam in await db.list_cameras():
            self.cameras[cam["id"]] = cam
            self._start_camera(cam)
        if config.is_demo_mode():
            self._sim_prev_levels.clear()
            self._sync_simulated_events()
            live_cam = self.cameras.get(config.DEMO_LIVE_CAM_ID)
            if live_cam:
                self.active_run = await db.create_demo_run(
                    camera_id=live_cam["id"],
                    unit=live_cam["unit"],
                    calibration=live_cam["calibration"],
                    thresholds=live_cam["thresholds"],
                )
            self._bg.append(asyncio.create_task(self._demo_sim_loop(), name="demo-sim"))
        self._bg.append(asyncio.create_task(self._db_writer(), name="db-writer"))
        self._bg.append(asyncio.create_task(self._housekeeping(), name="housekeeping"))
        logger.info("Загружено камер: %d (деморежим: %s)", len(self.cameras), config.is_demo_mode())

    async def _ensure_demo_camera(self) -> None:
        """Идемпотентно создаёт основной прибор МТП-160 в демо-БД без дубликатов."""
        spec = demo.LIVE_DEMO_SPEC
        existing = await db.get_camera(spec["id"])
        if existing is None:
            await db.create_camera(
                cam_id=spec["id"],
                name=spec["name"],
                type="phone_ws",
                gauge_type=spec["gauge_type"],
                unit=spec["unit"],
                calibration=spec["calibration"],
                thresholds=spec["thresholds"],
            )
        else:
            th = existing.get("thresholds") or {}
            if (
                th.get("lower_enabled") is False
                and th.get("ll_alert") is None
                and th.get("l_warn") is None
                and th.get("h_warn") == spec["thresholds"]["h_warn"]
                and th.get("hh_alert") == spec["thresholds"]["hh_alert"]
            ):
                await db.update_camera(spec["id"], {"thresholds": spec["thresholds"]})

    def _sync_simulated_events(self) -> None:
        """Регистрирует переходы зон уставок и обрывы связи для синтетических приборов сценария."""
        for inst in self.sim_adapter.all_instruments():
            iid = inst["id"]
            rd = inst.get("reading") or {}
            cam_label = f"{inst['code']} {inst['short_name']}"
            if not rd.get("valid"):
                if self._sim_prev_levels.get(iid) != "offline":
                    self._sim_prev_levels[iid] = "offline"
                    self.emit("link", cam_id=iid, cam_name=cam_label, text="reconnecting")
                continue
            lv = rd.get("level") or "normal"
            prev_lv = self._sim_prev_levels.get(iid, "normal")
            if prev_lv == "offline":
                self.emit("link", cam_id=iid, cam_name=cam_label, text="online")
                prev_lv = "normal"
            self._sim_prev_levels[iid] = lv
            if lv != prev_lv:
                sp = crossed_setpoint(rd.get("value"), inst["thresholds"])
                sp_val = vision._num(
                    inst["thresholds"].get(
                        {"LL": "ll_alert", "L": "l_warn", "H": "h_warn", "HH": "hh_alert"}.get(sp or "", ""),
                    )
                )
                self.emit(
                    "alarm",
                    cam_id=iid,
                    cam_name=cam_label,
                    level=lv,
                    prev_level=prev_lv,
                    value=rd.get("value"),
                    unit=inst["unit"],
                    setpoint=sp,
                    setpoint_value=sp_val,
                )

    async def set_demo_scenario(self, scenario: str) -> dict[str, Any]:
        if not config.is_demo_mode():
            raise HTTPException(409, "Сценарии симуляции доступны только в деморежиме")
        try:
            self.sim_adapter.set_scenario(scenario)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        self._sync_simulated_events()
        st = await self.demo_state()
        self.hub.broadcast({
            "type": "snapshot",
            "cameras": self.public_cameras(),
            "instruments": self.public_instruments(),
            "demo": st,
        })
        return st

    async def _demo_sim_loop(self) -> None:
        """Плавное обновление 35 синтетических приборов (1 Гц, без CV-воркеров)."""
        while True:
            await asyncio.sleep(config.DEMO_SIM_INTERVAL)
            if config.is_demo_mode():
                self._sync_simulated_events()
                if self.hub.count > 0:
                    self.hub.broadcast(self.sim_adapter.tick_payload())

    async def stop(self) -> None:
        for t in list(self._tasks.values()) + self._bg:
            t.cancel()
        await asyncio.gather(*self._tasks.values(), *self._bg, return_exceptions=True)
        self._tasks.clear()
        self._bg.clear()
        await self.streams.stop_all()
        await self._flush_db()
        await db.close_db()

    def _start_camera(self, cam: dict[str, Any]) -> None:
        cam_id = cam["id"]
        self.pipelines[cam_id] = vision.GaugePipeline(cam_id)
        try:
            self.streams.start_camera(cam_id, cam["type"], cam.get("source_url"))
        except Exception as exc:  # сбой одной камеры не должен мешать остальным
            logger.error("Не удалось запустить поток %s: %s", cam_id, exc)
        old = self._tasks.pop(cam_id, None)
        if old:
            old.cancel()
        self._tasks[cam_id] = asyncio.create_task(self._process_loop(cam_id),
                                                  name=f"process-{cam_id[:8]}")

    async def _stop_camera(self, cam_id: str, drop_frames: bool = True) -> None:
        task = self._tasks.pop(cam_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.streams.stop_camera(cam_id, drop_frames=drop_frames)

    # -- статусы потоков -----------------------------------------------------
    async def _on_status(self, cam_id: str, status: str) -> None:
        cam = self.cameras.get(cam_id)
        if cam is None:
            return
        cam["status"] = status
        try:
            await db.set_camera_status(cam_id, status)
        except Exception as exc:
            logger.warning("DB status %s: %s", cam_id, exc)
        self.hub.broadcast({"type": "status", "cam_id": cam_id, "status": status,
                            "stream": self.streams.info(cam_id)})
        self.emit("link", cam_id=cam_id, cam_name=cam["name"], text=status)

    # -- конвейер зрения ------------------------------------------------------
    @staticmethod
    def _run_pipeline(pipeline: vision.GaugePipeline, frame: np.ndarray,
                      cam: dict[str, Any]) -> tuple[vision.GaugeReading, bytes | None, bytes | None]:
        reading = pipeline.process(frame, cam["calibration"], cam["thresholds"], cam["unit"])
        jpeg = None
        if reading.overlay is not None:
            ov = reading.overlay
            h, w = ov.shape[:2]
            if w > config.PREVIEW_MAX_WIDTH:
                k = config.PREVIEW_MAX_WIDTH / float(w)
                ov = cv2.resize(ov, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
            jpeg = encode_jpeg(ov, 78)
            reading.overlay = None
        snap = None
        if reading.snapshot is not None:
            snap = encode_jpeg(reading.snapshot, config.SNAPSHOT_JPEG_QUALITY)
            reading.snapshot = None
        return reading, jpeg, snap

    async def _process_loop(self, cam_id: str) -> None:
        """Анализ свежих кадров камеры с частотой PROCESS_FPS."""
        loop = asyncio.get_running_loop()
        interval = 1.0 / max(0.2, config.PROCESS_FPS)
        last_no = 0
        while True:
            t0 = time.monotonic()
            try:
                cam = self.cameras.get(cam_id)
                pipeline = self.pipelines.get(cam_id)
                if cam is None or pipeline is None:
                    return
                frame, frame_no = self.broker.latest_frame(cam_id)
                if frame is not None and frame_no != last_no:
                    last_no = frame_no
                    reading, jpeg, snap = await loop.run_in_executor(
                        self.executor, self._run_pipeline, pipeline, frame, cam)
                    if jpeg:
                        self.broker.publish_overlay(cam_id, jpeg)
                    self._on_reading(cam_id, cam, reading, snap)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[%s] ошибка конвейера: %s", cam_id[:8], exc)
            await asyncio.sleep(max(0.02, interval - (time.monotonic() - t0)))

    def _on_reading(self, cam_id: str, cam: dict[str, Any], r: vision.GaugeReading,
                    snap: bytes | None = None) -> None:
        ts = db.utcnow_iso()
        prev = self.last.get(cam_id) or {}
        stream_info = self.streams.info(cam_id)
        out_of_scale = bool(r.debug.get("out_of_scale"))

        last_valid_ts = ts if r.valid else prev.get("last_valid_ts")
        last_valid_value = _round(r.ema_value) if r.valid else prev.get("last_valid_value")
        last_valid_level = r.status_level if r.valid else prev.get("last_valid_level")
        awaiting_post_cal = False if r.valid else bool(prev.get("awaiting_post_cal"))

        shown_val = None if awaiting_post_cal else _round(r.ema_value)
        shown_level = r.status_level if r.valid else (None if awaiting_post_cal else last_valid_level)

        state: dict[str, Any] = {
            "ts": ts,
            "last_frame_ts": stream_info.get("last_frame_utc") or ts,
            "value": shown_val,
            "raw_value": _round(r.value),
            "angle": _round(r.angle, 2),
            "valid": r.valid,
            "out_of_scale": out_of_scale,
            "awaiting_post_cal": awaiting_post_cal,
            "confidence": r.needle_confidence,
            "level": shown_level,
            "last_valid_value": last_valid_value,
            "last_valid_level": last_valid_level,
            "dial_found": r.dial_found,
            "dial_source": r.dial_source,
            "method": r.debug.get("needle_method"),
            "process_ms": r.process_ms,
            "geom": r.debug.get("geom"),
            "last_valid_ts": last_valid_ts,
        }
        state.update(demo.compute_live_states(cam, stream_info, state))
        if r.valid and shown_val is not None:
            buf = self._live_spark.setdefault(cam_id, [])
            buf.append(float(shown_val))
            if len(buf) > 24:
                del buf[:-24]
            state["sparkline"] = list(buf)
        elif cam_id in self._live_spark:
            state["sparkline"] = list(self._live_spark[cam_id])
        self.last[cam_id] = state
        self.hub.broadcast({"type": "reading", "cam_id": cam_id, **state})

        # Переходы зон уставок фиксируются только по достоверному измерению CV
        if r.valid and r.ema_value is not None:
            prev_valid_level = prev.get("last_valid_level") or "normal"
            if r.status_level != prev_valid_level:
                sp = crossed_setpoint(state["value"], cam["thresholds"])
                self.emit(
                    "alarm",
                    cam_id=cam_id,
                    cam_name=cam["name"],
                    level=r.status_level,
                    prev_level=prev_valid_level,
                    value=state["value"],
                    unit=cam["unit"],
                    setpoint=sp,
                    setpoint_value=vision._num(
                        cam["thresholds"].get(
                            {"LL": "ll_alert", "L": "l_warn", "H": "h_warn", "HH": "hh_alert"}.get(sp or "", ""),
                        )
                    ),
                    snapshot=snap if r.status_level != "normal" else None,
                )

        now = time.monotonic()
        if r.valid and r.ema_value is not None and \
                now - self._last_db_write.get(cam_id, 0.0) >= config.DB_WRITE_INTERVAL:
            self._last_db_write[cam_id] = now
            active_run_id: str | None = None
            if self.active_run and self.active_run.get("camera_id") == cam_id \
                    and self.active_run.get("ended_at") is None:
                active_run_id = self.active_run["id"]
                self.active_run["readings_count"] = int(self.active_run.get("readings_count") or 0) + 1
            self._db_buffer.append((
                cam_id,
                ts,
                float(r.ema_value),
                None if r.angle is None else float(r.angle),
                r.status_level,
                cam["unit"],
                active_run_id,
            ))

    # -- фоновые задачи -------------------------------------------------------
    async def _flush_db(self) -> None:
        if not self._db_buffer:
            return
        rows, self._db_buffer = self._db_buffer, []
        rows = [r for r in rows if r[0] in self.cameras]
        try:
            await db.insert_readings(rows)
        except Exception as exc:
            logger.error("Ошибка записи телеметрии (%d строк): %s", len(rows), exc)

    async def _db_writer(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            await self._flush_db()

    async def _housekeeping(self) -> None:
        """Раз в час: актуализация LAN IP, раз в сутки — очистка старой истории."""
        last_prune = 0.0
        while True:
            try:
                self.lan_ip = config.get_lan_ip()
                if time.time() - last_prune > 86400:
                    removed = await db.prune_history(config.HISTORY_KEEP_DAYS)
                    last_prune = time.time()
                    if removed:
                        logger.info("Удалено устаревших отсчётов: %d", removed)
            except Exception as exc:
                logger.warning("housekeeping: %s", exc)
            await asyncio.sleep(3600)

    # -- CRUD и единая модель приборов --------------------------------------
    def public_camera(self, cam: dict[str, Any]) -> dict[str, Any]:
        cam_id = cam["id"]
        st_info = self.streams.info(cam_id)
        rd = self.last.get(cam_id)
        if rd is not None:
            rd = {**rd, **demo.compute_live_states(cam, st_info, rd)}
        raw_cam = {
            **cam,
            "status": self.streams.status_of(cam_id),
            "stream": st_info,
            "reading": rd,
        }
        is_demo_primary = config.is_demo_mode() and cam_id == config.DEMO_LIVE_CAM_ID
        pos = 1 if is_demo_primary else (list(self.cameras.keys()).index(cam_id) + 1 if cam_id in self.cameras else 1)
        return demo.unify_camera(raw_cam, grid_pos=pos, is_primary_demo=is_demo_primary)

    def public_cameras(self) -> list[dict[str, Any]]:
        return [self.public_camera(c) for c in self.cameras.values()]

    def public_instruments(self) -> list[dict[str, Any]]:
        """Единый список приборов пульта (в демопрофиле: 36 позиций — 1 живая + 35 симуляция)."""
        if not config.is_demo_mode():
            return [
                demo.unify_camera(self.public_camera(c), grid_pos=i + 1, is_primary_demo=False)
                for i, c in enumerate(self.cameras.values())
            ]
        out: list[dict[str, Any]] = []
        primary = self.cameras.get(config.DEMO_LIVE_CAM_ID)
        if primary:
            out.append(self.public_camera(primary))
        out.extend(self.sim_adapter.all_instruments())
        extra_pos = len(out) + 1
        for cid, cam in self.cameras.items():
            if cid == config.DEMO_LIVE_CAM_ID:
                continue
            out.append(demo.unify_camera(self.public_camera(cam), grid_pos=extra_pos, is_primary_demo=False))
            extra_pos += 1
        return out

    async def demo_state(self) -> dict[str, Any]:
        if not config.is_demo_mode():
            return {"enabled": False, "db_path": str(config.get_db_path()), "active_run": None, "runs": []}
        await self._flush_db()
        if self.active_run:
            fresh = await db.get_demo_run(self.active_run["id"])
            if fresh:
                self.active_run = fresh
        runs = await db.list_demo_runs(config.DEMO_LIVE_CAM_ID, limit=20)
        return {
            "enabled": True,
            "live_cam_id": config.DEMO_LIVE_CAM_ID,
            "total_positions": config.DEMO_TOTAL_POSITIONS,
            "simulator_url": config.SIMULATOR_URL,
            "stale_seconds": config.READING_STALE_SECONDS,
            "db_path": str(config.get_db_path()),
            "scenario": self.sim_adapter.scenario,
            "scenarios": list(demo.DEMO_SCENARIOS),
            "groups": list(demo.DEMO_GROUPS),
            "preset": demo.LIVE_DEMO_SPEC,
            "active_run": self.active_run,
            "runs": runs,
        }

    async def start_demo_run(self, cam_id: str | None = None, label: str | None = None) -> dict[str, Any]:
        await self._flush_db()
        target_id = cam_id or (config.DEMO_LIVE_CAM_ID if config.is_demo_mode() else next(iter(self.cameras), None))
        if not target_id or target_id not in self.cameras:
            raise HTTPException(404, "Живой прибор для записи прогона не найден")
        cam = self.cameras[target_id]
        self.active_run = await db.create_demo_run(
            camera_id=target_id,
            label=(label or "").strip() or None,
            unit=cam["unit"],
            calibration=cam["calibration"],
            thresholds=cam["thresholds"],
        )
        self.hub.broadcast({"type": "demo_run", "run": self.active_run})
        return self.active_run

    async def stop_demo_run(self, run_id: str | None = None) -> dict[str, Any]:
        await self._flush_db()
        rid = run_id or (self.active_run["id"] if self.active_run else None)
        if not rid:
            raise HTTPException(404, "Активный прогон не найден")
        stopped = await db.finish_demo_run(rid)
        if stopped is None:
            raise HTTPException(404, "Прогон не найден")
        if self.active_run and self.active_run["id"] == rid:
            self.active_run = stopped
        self.hub.broadcast({"type": "demo_run", "run": stopped})
        return stopped

    async def add_camera(self, data: CameraCreate) -> dict[str, Any]:
        unit = _validate_unit(data.gauge_type, data.unit)
        source = _validate_source(data.type, data.source_url)
        cal_dict = None
        if data.calibration:
            data.calibration.check_geometry()
            cal_dict = data.calibration.model_dump()
        scale_lo = cal_dict["v_min"] if cal_dict else db.DEFAULT_CALIBRATION["v_min"]
        scale_hi = cal_dict["v_max"] if cal_dict else db.DEFAULT_CALIBRATION["v_max"]
        if data.thresholds:
            data.thresholds.check_order(scale_lo, scale_hi)
        cam = await db.create_camera(
            name=data.name.strip(), type=data.type, gauge_type=data.gauge_type, unit=unit,
            source_url=source,
            calibration=cal_dict,
            thresholds=data.thresholds.model_dump() if data.thresholds else None,
        )
        self.cameras[cam["id"]] = cam
        self._start_camera(cam)
        out = self.public_camera(cam)
        self.hub.broadcast({"type": "camera_added", "camera": out})
        self.emit("config", cam_id=cam["id"], cam_name=cam["name"], text="added")
        return out

    async def update_camera(self, cam_id: str, data: CameraUpdate) -> dict[str, Any]:
        cam = self.cameras.get(cam_id)
        if cam is None:
            raise HTTPException(404, "Прибор не найден")
        patch = data.model_dump(exclude_unset=True)
        gauge_type = patch.get("gauge_type", cam["gauge_type"])
        if "unit" in patch or "gauge_type" in patch:
            unit = patch.get("unit")
            if unit is None and cam["unit"] in config.GAUGE_TYPES[gauge_type]["units"]:
                unit = cam["unit"]
            patch["unit"] = _validate_unit(gauge_type, unit)
        new_type = patch.get("type", cam["type"])
        restart = False
        if "type" in patch or "source_url" in patch:
            patch["source_url"] = _validate_source(new_type, patch.get("source_url", cam.get("source_url")))
            restart = (new_type != cam["type"]) or (patch["source_url"] != cam.get("source_url"))

        reset_roi = False
        scale_changed = False
        eff_cal = cam["calibration"]
        if data.calibration is not None:
            data.calibration.check_geometry()
            patch["calibration"] = data.calibration.model_dump()
            eff_cal = patch["calibration"]
            reset_roi = eff_cal.get("roi") != cam["calibration"].get("roi")
            scale_keys = ("v_min", "v_max", "theta_min", "theta_max", "direction")
            scale_changed = any(eff_cal.get(k) != cam["calibration"].get(k) for k in scale_keys)

        unit_changed = "unit" in patch and patch["unit"] != cam["unit"]

        if data.thresholds is not None:
            data.thresholds.check_order(eff_cal.get("v_min"), eff_cal.get("v_max"))
            thr_dump = data.thresholds.model_dump()
            if thr_dump.get("lower_enabled") is False:
                thr_dump["ll_alert"] = None
                thr_dump["l_warn"] = None
            patch["thresholds"] = thr_dump
        elif scale_changed:
            # Если меняются границы шкалы, проверяем совместимость сохранённых уставок
            cur_thr = ThresholdsModel(**cam["thresholds"])
            cur_thr.check_order(eff_cal.get("v_min"), eff_cal.get("v_max"))

        updated = await db.update_camera(cam_id, patch)
        if updated is None:
            raise HTTPException(404, "Прибор не найден")
        self.cameras[cam_id] = updated
        if restart:
            await self._stop_camera(cam_id)
            self.last.pop(cam_id, None)
            self._start_camera(updated)
        elif (reset_roi or scale_changed or unit_changed) and cam_id in self.pipelines:
            self.pipelines[cam_id].reset(keep_roi=not reset_roi)
            prev_last = self.last.get(cam_id)
            if prev_last and (scale_changed or unit_changed):
                # Не наследуем сглаженное значение старой шкалы как новое измерение
                prev_last["value"] = None
                prev_last["raw_value"] = None
                prev_last["valid"] = False
                prev_last["level"] = None
                prev_last["awaiting_post_cal"] = True
        elif "thresholds" in patch and cam_id in self.last:
            prev_last = self.last[cam_id]
            if prev_last.get("valid") and prev_last.get("value") is not None:
                new_lv = vision.classify_level(prev_last["value"], updated["thresholds"])
                prev_lv = prev_last.get("last_valid_level") or "normal"
                prev_last["level"] = new_lv
                prev_last["last_valid_level"] = new_lv
                if new_lv != prev_lv:
                    sp = crossed_setpoint(prev_last["value"], updated["thresholds"])
                    self.emit(
                        "alarm", cam_id=cam_id, cam_name=updated["name"],
                        level=new_lv, prev_level=prev_lv, value=prev_last["value"], unit=updated["unit"],
                        setpoint=sp,
                        setpoint_value=vision._num(updated["thresholds"].get(
                            {"LL": "ll_alert", "L": "l_warn", "H": "h_warn", "HH": "hh_alert"}.get(sp or "", ""),
                        )),
                    )

        # Синхронизация активного демопрогона при смене конфигурации
        if self.active_run and self.active_run.get("camera_id") == cam_id and self.active_run.get("ended_at") is None:
            await self._flush_db()
            fresh_run = await db.get_demo_run(self.active_run["id"])
            has_rows = int((fresh_run or {}).get("readings_count") or 0) > 0
            if (scale_changed or unit_changed) and has_rows:
                # Смена шкалы или единицы во время записи открывает новый чистый прогон
                self.active_run = await db.create_demo_run(
                    camera_id=cam_id,
                    unit=updated["unit"],
                    calibration=updated["calibration"],
                    thresholds=updated["thresholds"],
                )
            else:
                self.active_run = await db.update_demo_run_config(
                    self.active_run["id"],
                    unit=updated["unit"],
                    calibration=updated["calibration"],
                    thresholds=updated["thresholds"],
                    reset_start=not has_rows,
                )
            self.hub.broadcast({"type": "demo_run", "run": self.active_run})

        out = self.public_camera(updated)
        self.hub.broadcast({"type": "camera_updated", "camera": out})
        changed = [k for k in ("name", "type", "source_url", "gauge_type", "unit", "calibration", "thresholds")
                   if k in patch and patch[k] != cam.get(k)]
        if changed:
            self.emit("config", cam_id=cam_id, cam_name=updated["name"], text=",".join(changed))
        return out

    async def delete_camera(self, cam_id: str) -> None:
        if config.is_demo_mode() and cam_id == config.DEMO_LIVE_CAM_ID:
            raise HTTPException(409, "Основной прибор демонстрации закреплён за позицией 01 и не удаляется в демопрофиле")
        cam = self.cameras.get(cam_id)
        if cam is None:
            raise HTTPException(404, "Прибор не найден")
        await self._stop_camera(cam_id)
        self.streams.revoke_phone_token(cam_id)
        self.cameras.pop(cam_id, None)
        self.pipelines.pop(cam_id, None)
        self.last.pop(cam_id, None)
        self._last_db_write.pop(cam_id, None)
        self._db_buffer = [r for r in self._db_buffer if r[0] != cam_id]
        await db.delete_camera(cam_id)
        self.hub.broadcast({"type": "camera_deleted", "cam_id": cam_id})
        self.events.forget_camera(cam_id)
        self.emit("config", cam_id=cam_id, cam_name=cam["name"], text="deleted")

    async def restart_camera(self, cam_id: str) -> dict[str, Any]:
        cam = self.cameras.get(cam_id)
        if cam is None:
            raise HTTPException(404, "Прибор не найден")
        await self._stop_camera(cam_id, drop_frames=False)
        self._start_camera(cam)
        return self.public_camera(cam)


service = GaugeService()


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------
@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    loop = asyncio.get_running_loop()
    default_handler = loop.get_exception_handler()

    def _quiet_resets(lp: asyncio.AbstractEventLoop, ctx: dict[str, Any]) -> None:
        # Windows Proactor: клиент закрыл вкладку/потерял Wi-Fi -> WinError 10054. Не авария.
        if isinstance(ctx.get("exception"), (ConnectionResetError, ConnectionAbortedError)):
            logger.debug("Соединение сброшено клиентом: %s", ctx.get("exception"))
            return
        if default_handler:
            default_handler(lp, ctx)
        else:
            lp.default_exception_handler(ctx)

    loop.set_exception_handler(_quiet_resets)
    await service.start()
    try:
        yield
    finally:
        await service.stop()


app = FastAPI(title=__app_name__, version=__version__, lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.middleware("http")
async def _security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path in ("/", "/index.html", "/capture", "/capture.html") \
            or request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


def _no_signal_jpeg() -> bytes:
    img = np.full((360, 640, 3), (32, 28, 24), np.uint8)
    cv2.putText(img, "NO SIGNAL", (190, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (90, 90, 90), 3, cv2.LINE_AA)
    return encode_jpeg(img, 70) or b""


NO_SIGNAL = _no_signal_jpeg()


# -- страницы ----------------------------------------------------------------
@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def page_index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/capture", include_in_schema=False)
@app.get("/capture.html", include_in_schema=False)
async def page_capture() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "capture.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" '
           'fill="#0f172a" stroke="#22c55e" stroke-width="5"/><line x1="32" y1="32" x2="48" y2="18" '
           'stroke="#f59e0b" stroke-width="5" stroke-linecap="round"/></svg>')
    return Response(svg, media_type="image/svg+xml")


# -- справочники и сервис -----------------------------------------------------
@app.get("/api/meta")
async def api_meta() -> dict[str, Any]:
    from .cert_gen import cert_fingerprint
    fingerprint = None
    with contextlib.suppress(Exception):
        fingerprint = cert_fingerprint()
    return {
        "app": __app_name__,
        "version": __version__,
        "lan_ip": service.lan_ip,
        "port": config.HTTPS_PORT,
        "urls": [f"https://localhost:{config.HTTPS_PORT}", f"https://{service.lan_ip}:{config.HTTPS_PORT}"],
        "gauge_types": config.GAUGE_TYPES,
        "camera_types": list(config.CAMERA_TYPES),
        "trend_windows": list(config.TREND_WINDOWS),
        "trend_default": config.TREND_WINDOW_DEFAULT,
        "ema_alpha": config.EMA_ALPHA,
        "process_fps": config.PROCESS_FPS,
        "phone_fps": config.PHONE_CAPTURE_FPS,
        "yolo": vision.yolo_available(),
        "yolo_device": vision.yolo_device(),
        "cert_sha256": fingerprint,
        "dashboards": service.hub.count,
        "uptime_s": int(time.time() - service.started_at),
        "demo_mode": config.is_demo_mode(),
        "db_path": str(config.get_db_path()),
        "stale_seconds": config.READING_STALE_SECONDS,
        "simulator_url": config.SIMULATOR_URL,
        "demo": await service.demo_state(),
    }


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    counts: dict[str, int] = {"online": 0, "reconnecting": 0, "offline": 0}
    for cam_id in service.cameras:
        st = service.streams.status_of(cam_id)
        counts[st] = counts.get(st, 0) + 1
    return {"ok": True, "cameras": len(service.cameras), "status": counts}


@app.get("/api/cert.pem", include_in_schema=False)
async def api_cert() -> FileResponse:
    if not config.CERT_FILE.exists():
        raise HTTPException(404, "Сертификат не найден")
    return FileResponse(config.CERT_FILE, media_type="application/x-x509-ca-cert",
                        filename="gaugevision-cert.pem")


# -- камеры и единый реестр приборов ------------------------------------------
@app.get("/api/cameras")
async def api_cameras() -> list[dict[str, Any]]:
    return service.public_cameras()


@app.get("/api/instruments")
async def api_instruments() -> list[dict[str, Any]]:
    return service.public_instruments()


@app.get("/api/instruments/{inst_id}/history")
async def api_instrument_history(
    inst_id: str,
    limit: int = Query(120, ge=1, le=5000),
) -> list[dict[str, Any]]:
    if inst_id in demo.SIMULATED_BY_ID:
        if not config.is_demo_mode():
            raise HTTPException(404, "Симулируемый прибор доступен только в демопрофиле")
        return service.sim_adapter.history_rows(inst_id, limit=limit)
    cam = _get_cam(inst_id)
    await service._flush_db()
    pub = service.public_camera(cam)
    rows = await db.get_history(inst_id, limit)
    return [
        {
            "id": r["id"],
            "timestamp_iso8601": r["timestamp"],
            "instrument_id": pub.get("code") or inst_id,
            "source_kind": pub.get("source_kind", "phone_cv"),
            "value": r["value"],
            "unit": r.get("unit") or cam["unit"],
            "raw_angle_deg": r["raw_angle"],
            "status_level": r["status_level"],
        }
        for r in rows
        if r["value"] is not None
    ]


@app.get("/api/instruments/{inst_id}/export.csv")
async def api_instrument_export_csv(inst_id: str) -> Response:
    if inst_id in demo.SIMULATED_BY_ID:
        if not config.is_demo_mode():
            raise HTTPException(404, "Симулируемый прибор доступен только в демопрофиле")
        spec = demo.SIMULATED_BY_ID[inst_id]
        rows = service.sim_adapter.history_rows(inst_id, limit=120)
        lines = ["timestamp_iso8601;instrument_id;source_kind;value;unit;raw_angle_deg;status_level"]
        for r in rows:
            lines.append(
                f"{r['timestamp_iso8601']};{r['instrument_id']};simulated;{r['value']:.4f};{r['unit']};;{r['status_level']}"
            )
        return _csv_response("\n".join(lines) + "\n", f"{spec['code']}_{spec['short_name']}", f"sim_{inst_id}")
    return await api_export_csv(inst_id, format="demo")


@app.get("/api/instruments/{inst_id}/trend")
async def api_instrument_trend(
    inst_id: str,
    since: _dt.datetime,
    until: _dt.datetime | None = None,
    step: float = Query(60.0, gt=0, description="ширина корзины, с"),
) -> list[dict[str, Any]]:
    if since.tzinfo is None:
        raise HTTPException(422, "since: нужна метка времени с часовым поясом (ISO 8601)")
    if until is not None and until.tzinfo is None:
        raise HTTPException(422, "until: нужна метка времени с часовым поясом (ISO 8601)")
    if inst_id in demo.SIMULATED_BY_ID:
        if not config.is_demo_mode():
            raise HTTPException(404, "Симулируемый прибор доступен только в демопрофиле")
        return service.sim_adapter.trend(inst_id, since, step, until)
    _get_cam(inst_id)
    await service._flush_db()
    end_ref = until or _dt.datetime.now(_dt.timezone.utc)
    span = max(1.0, (end_ref - since).total_seconds())
    step = max(step, config.DB_WRITE_INTERVAL, span / config.TREND_BUCKETS_MAX)
    return await db.get_trend(inst_id, since, step, until)


@app.post("/api/cameras", status_code=201)
async def api_create_camera(data: CameraCreate) -> dict[str, Any]:
    return await service.add_camera(data)


def _get_cam(cam_id: str) -> dict[str, Any]:
    cam = service.cameras.get(cam_id)
    if cam is None:
        raise HTTPException(404, "Прибор не найден")
    return cam


@app.get("/api/cameras/{cam_id}")
async def api_camera(cam_id: str) -> dict[str, Any]:
    return service.public_camera(_get_cam(cam_id))


@app.patch("/api/cameras/{cam_id}")
async def api_update_camera(cam_id: str, data: CameraUpdate) -> dict[str, Any]:
    return await service.update_camera(cam_id, data)


@app.delete("/api/cameras/{cam_id}", status_code=204)
async def api_delete_camera(cam_id: str) -> Response:
    await service.delete_camera(cam_id)
    return Response(status_code=204)


@app.post("/api/cameras/{cam_id}/restart")
async def api_restart_camera(cam_id: str) -> dict[str, Any]:
    return await service.restart_camera(cam_id)


@app.post("/api/cameras/{cam_id}/redetect")
async def api_redetect(cam_id: str) -> dict[str, Any]:
    _get_cam(cam_id)
    pipeline = service.pipelines.get(cam_id)
    if pipeline:
        pipeline.reset()
    return {"ok": True}


@app.get("/api/cameras/{cam_id}/frame.jpg")
async def api_frame(cam_id: str, overlay: int = 1) -> Response:
    _get_cam(cam_id)
    jpeg, _ = await asyncio.get_running_loop().run_in_executor(
        None, service.broker.latest_jpeg, cam_id, bool(overlay))
    return Response(jpeg or NO_SIGNAL, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/cameras/{cam_id}/mjpeg")
async def api_mjpeg(cam_id: str, request: Request, overlay: int = 1) -> StreamingResponse:
    _get_cam(cam_id)
    boundary = "gaugevisionframe"

    async def gen() -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        last_no = -1
        sent_placeholder = False
        period = 1.0 / config.MJPEG_FPS
        while cam_id in service.cameras:
            if await request.is_disconnected():
                break
            jpeg, no = await loop.run_in_executor(None, service.broker.latest_jpeg, cam_id, bool(overlay))
            if jpeg is None and not sent_placeholder:
                jpeg, no, sent_placeholder = NO_SIGNAL, -2, True
            if jpeg is not None and no != last_no:
                last_no = no
                yield (f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                       f"Content-Length: {len(jpeg)}\r\n\r\n").encode() + jpeg + b"\r\n"
            await asyncio.sleep(period)

    return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}",
                             headers={"Cache-Control": "no-store"})


@app.get("/api/cameras/{cam_id}/history")
async def api_history(
    cam_id: str,
    limit: int = Query(config.HISTORY_DEFAULT_LIMIT, ge=1, le=100_000),
    run_id: str | None = None,
    since: _dt.datetime | None = None,
    until: _dt.datetime | None = None,
) -> list[dict[str, Any]]:
    _get_cam(cam_id)
    await service._flush_db()
    since_iso = since.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds") if since else None
    until_iso = until.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds") if until else None
    if run_id:
        run_obj = await db.get_demo_run(run_id)
        if run_obj is None or run_obj["camera_id"] != cam_id:
            raise HTTPException(404, "Прогон не найден для выбранного прибора")
        since_iso = since_iso or run_obj["started_at"]
        until_iso = until_iso or run_obj["ended_at"]
    return await db.get_history(cam_id, limit, since=since_iso, until=until_iso, run_id=run_id)


@app.get("/api/cameras/{cam_id}/trend")
async def api_trend(
    cam_id: str,
    since: _dt.datetime,
    until: _dt.datetime | None = None,
    step: float = Query(60.0, gt=0, description="ширина корзины, с"),
) -> list[dict[str, Any]]:
    _get_cam(cam_id)
    if since.tzinfo is None:
        raise HTTPException(422, "since: нужна метка времени с часовым поясом (ISO 8601)")
    if until is not None and until.tzinfo is None:
        raise HTTPException(422, "until: нужна метка времени с часовым поясом (ISO 8601)")
    await service._flush_db()
    end_ref = until or _dt.datetime.now(_dt.timezone.utc)
    span = max(1.0, (end_ref - since).total_seconds())
    step = max(step, config.DB_WRITE_INTERVAL, span / config.TREND_BUCKETS_MAX)
    return await db.get_trend(cam_id, since, step, until)


@app.get("/api/events")
async def api_events(limit: int = Query(300, ge=1, le=config.EVENTS_MAX),
                     cam_id: str | None = None) -> list[dict[str, Any]]:
    return service.events.list(limit, cam_id)


@app.get("/api/events/{ev_id}/frame.jpg")
async def api_event_frame(ev_id: int) -> Response:
    jpeg = service.events.snapshot(ev_id)
    if jpeg is None:
        raise HTTPException(404, "Стоп-кадр не сохранён")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/events/{ev_id}/ack")
async def api_ack_event(ev_id: int, request: Request) -> dict[str, Any]:
    """Адресное идемпотентное квитирование конкретного события журнала."""
    client = request.client.host if request.client else "?"
    ts = db.utcnow_iso()
    ev, changed = service.events.acknowledge_one(ev_id, ts, client)
    if ev is None:
        raise HTTPException(404, "Событие не найдено")
    ids = [ev_id] if changed else []
    if changed:
        service.hub.broadcast({"type": "ack", "ts": ts, "by": client, "ids": ids})
        service.emit("ack", cam_id=ev.get("cam_id"), cam_name=ev.get("cam_name"),
                     text=client, value=1.0, ref_event_id=ev_id)
    return {"ok": True, "already_acked": not changed, "ts": ev.get("acked_ts") or ts, "ids": ids, "event": ev}


@app.delete("/api/cameras/{cam_id}/history", status_code=204)
async def api_clear_history(cam_id: str) -> Response:
    _get_cam(cam_id)
    await service._flush_db()
    await db.clear_history(cam_id)
    return Response(status_code=204)


def _csv_response(csv_text: str, prefix: str, ascii_prefix: str, stamp: str | None = None) -> Response:
    st = stamp or time.strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in prefix)[:60] or "gauge"
    filename = f"{safe}_{st}.csv"
    ascii_name = f"{ascii_prefix}_{st}.csv"
    return Response(
        "\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/cameras/{cam_id}/export.csv")
async def api_export_csv(
    cam_id: str,
    run_id: str | None = None,
    since: _dt.datetime | None = None,
    until: _dt.datetime | None = None,
    format: Literal["legacy", "demo"] = "legacy",
) -> Response:
    cam = _get_cam(cam_id)
    await service._flush_db()
    since_iso = since.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds") if since else None
    until_iso = until.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds") if until else None
    unit_ov: str | None = None
    stamp: str | None = None
    if run_id:
        run_obj = await db.get_demo_run(run_id)
        if run_obj is None or run_obj["camera_id"] != cam_id:
            raise HTTPException(404, "Прогон не найден для выбранного прибора")
        since_iso = since_iso or run_obj["started_at"]
        until_iso = until_iso or run_obj["ended_at"]
        unit_ov = run_obj.get("unit")
        stamp = run_obj["started_at"][:19].replace(":", "").replace("-", "").replace("T", "_")
    pub = service.public_camera(cam)
    csv_text = await db.export_csv(
        cam_id,
        since=since_iso,
        until=until_iso,
        run_id=run_id,
        demo_format=(format == "demo"),
        instrument_id=pub.get("code") or cam_id,
        source_kind=pub.get("source_kind", "phone_cv"),
        unit_override=unit_ov,
    )
    code_prefix = f"{pub.get('code', 'gauge')}_{cam['name']}" if format == "demo" else cam["name"]
    return _csv_response(csv_text, code_prefix, f"gauge_{cam_id[:8]}", stamp)


# -- демопрогоны и выгрузка текущего показа ------------------------------------
@app.get("/api/demo/state")
async def api_demo_state() -> dict[str, Any]:
    return await service.demo_state()


@app.get("/api/demo/scenarios")
async def api_demo_scenarios() -> dict[str, Any]:
    return {"scenario": service.sim_adapter.scenario, "scenarios": list(demo.DEMO_SCENARIOS)}


@app.post("/api/demo/scenario")
async def api_set_demo_scenario(req: DemoScenarioRequest) -> dict[str, Any]:
    return await service.set_demo_scenario(req.scenario)


@app.get("/api/demo/runs")
async def api_demo_runs(cam_id: str | None = None) -> list[dict[str, Any]]:
    await service._flush_db()
    target = cam_id or (config.DEMO_LIVE_CAM_ID if config.is_demo_mode() else None)
    return await db.list_demo_runs(target, limit=30)


@app.post("/api/demo/runs/start")
async def api_demo_run_start(req: DemoRunStartRequest | None = None) -> dict[str, Any]:
    body = req or DemoRunStartRequest()
    return await service.start_demo_run(body.cam_id, body.label)


@app.post("/api/demo/runs/stop")
async def api_demo_run_stop(req: DemoRunStopRequest | None = None) -> dict[str, Any]:
    body = req or DemoRunStopRequest()
    return await service.stop_demo_run(body.run_id)


@app.get("/api/demo/runs/{run_id}/readings")
async def api_demo_run_readings(
    run_id: str,
    limit: int = Query(5000, ge=1, le=100_000),
) -> dict[str, Any]:
    await service._flush_db()
    run_obj = await db.get_demo_run(run_id)
    if run_obj is None:
        raise HTTPException(404, "Прогон не найден")
    cam = service.cameras.get(run_obj["camera_id"])
    pub = service.public_camera(cam) if cam else {}
    rows = await db.get_history(
        run_obj["camera_id"],
        limit,
        since=run_obj["started_at"],
        until=run_obj["ended_at"],
        run_id=run_id,
    )
    inst_code = pub.get("code") or run_obj["camera_id"]
    src_kind = pub.get("source_kind", "phone_cv")
    items = [
        {
            "id": r["id"],
            "timestamp_iso8601": r["timestamp"],
            "instrument_id": inst_code,
            "source_kind": src_kind,
            "value": r["value"],
            "unit": r.get("unit") or run_obj["unit"],
            "raw_angle_deg": r["raw_angle"],
            "status_level": r["status_level"],
        }
        for r in rows
        if r["value"] is not None
    ]
    return {"run": run_obj, "count": len(items), "readings": items}


@app.get("/api/demo/runs/{run_id}/export.csv")
async def api_demo_run_export_csv(run_id: str) -> Response:
    await service._flush_db()
    run_obj = await db.get_demo_run(run_id)
    if run_obj is None:
        raise HTTPException(404, "Прогон не найден")
    cam_id = run_obj["camera_id"]
    cam = service.cameras.get(cam_id)
    pub = service.public_camera(cam) if cam else {}
    inst_code = pub.get("code") or cam_id
    csv_text = await db.export_csv(
        cam_id,
        since=run_obj["started_at"],
        until=run_obj["ended_at"],
        run_id=run_id,
        demo_format=True,
        instrument_id=inst_code,
        source_kind=pub.get("source_kind", "phone_cv"),
        unit_override=run_obj["unit"],
    )
    stamp = run_obj["started_at"][:19].replace(":", "").replace("-", "").replace("T", "_")
    return _csv_response(csv_text, f"{inst_code}_{run_obj['label']}", f"demo_{cam_id[:8]}", stamp)


# -- смартфон как камера ---------------------------------------------------------
def _qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


@app.post("/api/phone/session")
async def api_phone_session(req: PhoneSessionRequest) -> dict[str, Any]:
    target_id = req.cam_id
    if not target_id and config.is_demo_mode() and config.DEMO_LIVE_CAM_ID in service.cameras:
        # В демопрофиле повторная выдача QR всегда привязана к закреплённому прибору #01
        target_id = config.DEMO_LIVE_CAM_ID
    if target_id:
        cam = _get_cam(target_id)
        if cam["type"] != "phone_ws":
            raise HTTPException(422, "Прибор не является смартфон-камерой")
    else:
        n = sum(1 for c in service.cameras.values() if c["type"] == "phone_ws") + 1
        cam = await service.add_camera(CameraCreate(
            name=(req.name or f"Смартфон-камера №{n}"), type="phone_ws",
            gauge_type=req.gauge_type, unit=req.unit))
    cam_id = cam["id"]
    if service.streams.phone_worker(cam_id) is None:
        service._start_camera(service.cameras[cam_id])
    worker = service.streams.phone_worker(cam_id)
    token, regenerated = service.streams.get_or_issue_phone_token(cam_id, regenerate=req.regenerate)
    if regenerated and worker and worker.active_ws is not None:
        old_ws = worker.active_ws
        worker.detach_ws(old_ws)
        with contextlib.suppress(Exception):
            await old_ws.close(code=4401, reason="session regenerated")
        service.hub.broadcast({
            "type": "status", "cam_id": cam_id, "status": worker.status, "stream": worker.info(),
        })
    url = config.capture_url(cam_id, token, service.lan_ip)
    return {
        "cam_id": cam_id,
        "token": token,
        "regenerated": regenerated,
        "url": url,
        "qr_svg": _qr_svg(url),
        "camera": service.public_camera(service.cameras[cam_id]),
    }


def _decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return frame if frame is not None and frame.size else None


@app.websocket("/ws/phone/{cam_id}")
async def ws_phone(ws: WebSocket, cam_id: str, token: str = "") -> None:
    cam = service.cameras.get(cam_id)
    if cam is None or cam["type"] != "phone_ws" or not service.streams.verify_phone_token(cam_id, token):
        await ws.close(code=4401, reason="invalid session")
        return
    await ws.accept()
    worker = service.streams.phone_worker(cam_id)
    if worker is None:
        service._start_camera(cam)
        worker = service.streams.phone_worker(cam_id)
    assert worker is not None
    prev_ws = worker.attach_ws(ws)
    if prev_ws is not None:
        with contextlib.suppress(Exception):
            await prev_ws.close(code=4401, reason="superseded by new phone connection")
    service.hub.broadcast({"type": "status", "cam_id": cam_id, "status": worker.status, "stream": worker.info()})
    loop = asyncio.get_running_loop()
    await ws.send_json({"type": "hello", "cam_id": cam_id, "name": cam["name"],
                        "unit": cam["unit"], "gauge_type": cam["gauge_type"],
                        "fps": config.PHONE_CAPTURE_FPS})
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            payload = msg.get("bytes")
            if payload:
                if len(payload) > 8 * 1024 * 1024:
                    await ws.send_json({"type": "error", "message": "кадр слишком большой"})
                    continue
                try:
                    frame = await loop.run_in_executor(None, _decode_image, payload)
                except Exception:
                    frame = None
                accepted = False
                if frame is not None:
                    accepted = worker.push_frame(frame, ws=ws)
                current = service.cameras.get(cam_id)
                await ws.send_json({"type": "ack", "ok": accepted, "status": worker.status,
                                    "unit": current["unit"] if current else cam["unit"],
                                    "reading": service.last.get(cam_id)})
                continue
            text = msg.get("text")
            if text:
                with contextlib.suppress(json.JSONDecodeError):
                    data = json.loads(text)
                    mtype = data.get("type")
                    if mtype == "ping":
                        await ws.send_json({"type": "pong", "t": data.get("t")})
                    elif mtype == "client_state":
                        c_state = str(data.get("state") or "")[:40]
                        c_err = str(data.get("error") or "")[:200] or None
                        if worker.set_client_state(ws, c_state, c_err):
                            service.hub.broadcast({
                                "type": "status", "cam_id": cam_id,
                                "status": worker.status, "stream": worker.info(),
                            })
            if cam_id not in service.cameras:
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        logger.warning("[%s] phone ws: %s", cam_id[:8], exc)
    finally:
        was_active = worker.detach_ws(ws)
        if was_active and cam_id in service.cameras:
            service.hub.broadcast({
                "type": "status", "cam_id": cam_id, "status": worker.status, "stream": worker.info(),
            })


# -- дашборд -------------------------------------------------------------------
@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket) -> None:
    await ws.accept()
    queue = service.hub.add(ws)

    async def sender() -> None:
        while True:
            data = await queue.get()
            await ws.send_text(data)

    send_task = asyncio.create_task(sender())
    try:
        snapshot_msg = {
            "type": "snapshot",
            "cameras": service.public_cameras(),
            "instruments": service.public_instruments(),
            "demo": await service.demo_state(),
        }
        await ws.send_text(json.dumps(snapshot_msg, ensure_ascii=False, default=_json_default))
        while True:
            text = await ws.receive_text()
            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(text)
                if data.get("type") == "ping":
                    queue.put_nowait(json.dumps({"type": "pong", "t": data.get("t")}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        logger.debug("dashboard ws: %s", exc)
    finally:
        service.hub.remove(ws)
        send_task.cancel()


@app.post("/api/alarms/ack")
async def api_ack(request: Request, body: AckRequest | None = None) -> dict[str, Any]:
    client = request.client.host if request.client else "?"
    ts = db.utcnow_iso()
    ev_id = body.event_id if body else None
    cam_id = body.cam_id if body else None
    if ev_id is not None:
        ev, changed = service.events.acknowledge_one(ev_id, ts, client)
        if ev is None:
            raise HTTPException(404, "Событие не найдено")
        ids = [ev_id] if changed else []
        if changed:
            service.hub.broadcast({"type": "ack", "ts": ts, "by": client, "ids": ids})
            service.emit("ack", cam_id=ev.get("cam_id"), cam_name=ev.get("cam_name"),
                         text=client, value=1.0, ref_event_id=ev_id)
        return {"ok": True, "already_acked": not changed, "ts": ev.get("acked_ts") or ts, "ids": ids}
    ids = service.events.acknowledge(ts, client, cam_id=cam_id)
    logger.info("Аварии квитированы оператором (%s): %d", client, len(ids))
    if ids:
        service.hub.broadcast({"type": "ack", "ts": ts, "by": client, "ids": ids})
        service.emit("ack", cam_id=cam_id, text=client, value=float(len(ids)))
    return {"ok": True, "ts": ts, "ids": ids}


# -- сетевое обнаружение -----------------------------------------------------------
_discover_lock = asyncio.Lock()


@app.get("/api/discover")
async def api_discover(subnet: str | None = Query(None, description="IP из подсети /24 для сканирования")
                       ) -> dict[str, Any]:
    if _discover_lock.locked():
        raise HTTPException(409, "Сканирование уже выполняется")
    async with _discover_lock:
        t0 = time.monotonic()
        base = subnet or service.lan_ip
        devices = await discovery.discover_all(timeout=config.ONVIF_PROBE_TIMEOUT, base_ip=base)
        known = {(c.get("source_url") or "") for c in service.cameras.values()}
        for d in devices:
            d["already_added"] = bool(d.get("suggested_url")) and d["suggested_url"] in known
        return {"subnet": f"{'.'.join(base.split('.')[:3])}.0/24", "devices": devices,
                "elapsed_s": round(time.monotonic() - t0, 2)}


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Необработанная ошибка %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)
