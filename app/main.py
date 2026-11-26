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
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import __app_name__, __version__, auth, config, db, demo, discovery, vision
from .dispatch_analyzer import DispatchAnalyzer
from .events import EventLog, crossed_setpoint
from .scada_gateway import ScadaGateway
from .security import (
    mask_url_credentials,
    sanitize_non_finite,
    validate_network_stream_url,
    validate_video_file_path,
)
from .spec_generator import (
    DIGITAL_SENSOR_CATALOG,
    LEGAL_DISCLAIMER,
    PERIOD_LABELS,
    build_evidence_frame_jpeg,
    generate_spec_bundle,
    llm_status,
    render_spec_docx,
)
from .store_forward import StoreAndForwardBuffer
from .stream_manager import EdgeStreamManager, FrameBroker, apply_signal_fault, encode_jpeg

logger = logging.getLogger("gaugevision.main")


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------
GaugeType = Literal["pressure", "temperature", "draft", "level", "electrical", "flow"]
CameraType = Literal["device", "rtsp", "http_mjpeg", "phone_ws", "video_file"]


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


class OutageToggleRequest(BaseModel):
    active: bool
    reason: str = Field("Симуляция обрыва канала АСУ ТП", max_length=200)


class DegradeRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, max_length=120)
    mode: Literal["freeze", "steam", "low_light", "glare", "packet_loss", "offline", "partial_occlusion", "recover", "none"]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class EconomicsConfigModel(BaseModel):
    commissioning_rate: float | None = Field(None, ge=0.0, le=1.0)
    rounds_savings_per_unit_rub: int | None = Field(None, ge=0, le=10_000_000)
    opex_per_sensor_rub_yr: int | None = Field(None, ge=0, le=10_000_000)
    downtime_risk_multiplier: float | None = Field(None, ge=0.0, le=20.0)
    demo_pricing: bool | None = None

    @field_validator("commissioning_rate", "downtime_risk_multiplier")
    @classmethod
    def _finite_eco(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("экономический параметр должен быть конечным числом")
        return v


class SpecGenerateRequest(BaseModel):
    period: Literal["12h", "24h", "7d", "30d"] = "12h"
    group: str = "all"
    instrument_id: str = "all"
    mode: Literal["deterministic", "llm_enhanced"] = "deterministic"
    format: Literal["docx", "md"] = "docx"
    plant_name: str | None = Field(None, max_length=200)
    branch_name: str | None = Field(None, max_length=200)
    workshop: str | None = Field(None, max_length=200)
    customer: str | None = Field(None, max_length=200)
    contractor: str | None = Field(None, max_length=200)
    doc_number: str | None = Field(None, max_length=80)
    economics_config: EconomicsConfigModel | None = None


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
    if cam_type in ("rtsp", "http_mjpeg"):
        try:
            return validate_network_stream_url(cam_type, url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if cam_type == "video_file":
        try:
            return validate_video_file_path(url, allowed_root=config.get_videos_dir())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
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
        self.streams = EdgeStreamManager(self.broker, on_status=self._on_status)
        self.store_forward = StoreAndForwardBuffer()
        self.scada = ScadaGateway()
        self.dispatch = DispatchAnalyzer()
        self._sse_clients: set[asyncio.Queue[str]] = set()
        self.bench_channels: dict[str, dict[str, Any]] = {}
        self.bench_last: dict[str, dict[str, Any]] = {}
        self._bench_tasks: dict[str, asyncio.Task] = {}
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

    def _broadcast_sse(self, event_name: str, payload: dict[str, Any]) -> None:
        if not self._sse_clients:
            return
        msg = f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=_json_default)}\n\n"
        for q in list(self._sse_clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(msg)

    def _on_sf_change(self, sf_stats: dict[str, Any]) -> None:
        msg = {"type": "store_forward", "store_forward": sf_stats}
        self.hub.broadcast(msg)
        self._broadcast_sse("store_forward", sf_stats)

    def emit(self, kind: str, **fields: Any) -> dict[str, Any]:
        """Запись в журнал событий (RAM + SQLite) и рассылка всем пультам + буфер Store-and-Forward."""
        ev = self.events.add(kind, **fields)
        snap = self.events.snapshot(ev["id"]) if ev.get("has_frame") else None
        self.hub.broadcast({"type": "event", "event": ev})
        self._broadcast_sse("event", ev)
        try:
            loop = asyncio.get_running_loop()
            # Персистентное сохранение события и стоп-кадра в SQLite (DEF-20)
            loop.create_task(db.save_event(ev, snap))
            if kind in ("alarm", "link"):
                sev = ev.get("level") or ("warning" if ev.get("text") in ("offline", "reconnecting") else "info")
                loop.create_task(self.store_forward.enqueue(
                    channel_id=str(ev.get("cam_id") or "station"),
                    payload_type="alarm" if kind == "alarm" else "health",
                    severity=str(sev),
                    payload={k: v for k, v in ev.items() if k != "has_frame"},
                    frame_blob=snap,
                ))
        except RuntimeError:
            pass
        return ev

    # -- жизненный цикл ------------------------------------------------------
    async def start(self) -> None:
        self.cameras.clear()
        self.pipelines.clear()
        self.last.clear()
        self.bench_channels.clear()
        self.bench_last.clear()
        self._db_buffer.clear()
        self._last_db_write.clear()
        self.active_run = None
        await db.init_db()
        await auth.bootstrap_default_users()
        persisted_evs, persisted_snaps = await db.load_persisted_events(limit=config.EVENTS_MAX)
        if persisted_evs:
            self.events.restore(persisted_evs, persisted_snaps)
        self.store_forward.configure(deliver_cb=self.scada.deliver_batch, on_change=self._on_sf_change)
        await self.store_forward.start()
        await self.scada.start()
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
            self._start_demo_bench_streams()
            self._bg.append(asyncio.create_task(self._demo_sim_loop(), name="demo-sim"))
        self._bg.append(asyncio.create_task(self._architecture_sync_loop(), name="arch-sync"))
        self._bg.append(asyncio.create_task(self._db_writer(), name="db-writer"))
        self._bg.append(asyncio.create_task(self._housekeeping(), name="housekeeping"))
        logger.info("Загружено камер: %d (деморежим: %s, Edge-узел: %s)",
                    len(self.cameras), config.is_demo_mode(), config.EDGE_NODE_ID)

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

    def _start_demo_bench_streams(self) -> None:
        """
        Запускает 2 лёгких стендовых Edge-видеопотока OpenCV (К1-Т01 и ТА2-Т02),
        проходящих реальный CV-конвейер, анализ качества, Adaptive FPS и Ring Buffer.
        Не меняет состав 36 приборов /api/instruments.
        """
        bench_specs = [
            ("edge-bench-k1t01", "sim-02", "Edge-камера №2 — Котёл К-1 (перегретый пар)"),
            ("edge-bench-ta2t02", "sim-12", "Edge-камера №3 — Турбина Т-2 (подшипник)"),
        ]
        for bid, sim_id, label in bench_specs:
            spec = demo.SIMULATED_BY_ID.get(sim_id)
            if not spec:
                continue
            ch = {
                "id": bid,
                "linked_inst_id": sim_id,
                "code": spec["code"],
                "name": label,
                "group": spec["group"],
                "type": "video_file",
                "source_kind": "edge_bench_cv",
                "source_url": f"rtsp://edge-ktc-01.local:554/stream/{spec['code'].lower()}",
                "unit": spec["unit"],
                "calibration": spec["calibration"],
                "thresholds": spec["thresholds"],
            }
            self.bench_channels[bid] = ch
            self.pipelines[bid] = vision.GaugePipeline(bid)
            self.streams.start_bench_stream(
                bid,
                spec,
                lambda s=spec: self.sim_adapter.value_at(s, time.time()),
            )
            self._bench_tasks[bid] = asyncio.create_task(
                self._bench_process_loop(bid), name=f"bench-cv-{bid[:10]}"
            )

    async def _sleep_with_motion_wakeup(self, stream_id: str, adaptive: Any, last_no: int, budget_s: float) -> None:
        """
        Ожидает до следующего цикла CV, периодически (~8 Гц) проверяя межкадровую
        разницу (`check_motion_wakeup`, < 0,3 мс) в режиме `eco_idle` (DEF-12).
        """
        if budget_s <= 0.05:
            await asyncio.sleep(0.05)
            return
        if adaptive.mode != "eco_idle":
            await asyncio.sleep(budget_s)
            return
        deadline = time.monotonic() + budget_s
        step = max(0.05, min(0.15, float(config.ADAPTIVE_WAKE_CHECK_INTERVAL)))
        seen_no = last_no
        while time.monotonic() < deadline:
            rem = deadline - time.monotonic()
            await asyncio.sleep(min(step, max(0.02, rem)))
            frm, fno = self.broker.latest_frame(stream_id)
            if frm is not None and fno != seen_no:
                seen_no = fno
                if adaptive.check_motion_wakeup(frm):
                    break

    async def _bench_process_loop(self, bench_id: str) -> None:
        """Обработка кадров стендового Edge-потока с Adaptive FPS, motion wake-up, анализом качества и Ring Buffer."""
        loop = asyncio.get_running_loop()
        last_no = 0
        adaptive = self.streams.adaptive_controller(bench_id)
        qa = self.streams.quality_analyzer(bench_id)
        ring = self.streams.ring_buffer(bench_id)
        while True:
            t0 = time.monotonic()
            try:
                ch = self.bench_channels.get(bench_id)
                pipeline = self.pipelines.get(bench_id)
                if ch is None or pipeline is None:
                    return
                fault = self.streams.get_fault(bench_id)
                frame, frame_no = self.broker.latest_frame(bench_id)
                if fault == "offline":
                    qa.set_offline("Симуляция обрыва канала", injected_fault="offline")
                    adaptive.update(value=None, span=1.0, level=None, degraded=True)
                elif frame is not None and frame_no != last_no:
                    last_no = frame_no
                    qrep = qa.analyze(frame, stream_online=True, injected_fault=fault)
                    reading, jpeg, _ = await loop.run_in_executor(
                        self.executor, self._run_pipeline, pipeline, frame, ch
                    )
                    if jpeg:
                        self.broker.publish_overlay(bench_id, jpeg)
                        ring.push(jpeg)
                    cal = ch["calibration"]
                    span = abs(float(cal.get("v_max", 10.0)) - float(cal.get("v_min", 0.0))) or 1.0
                    prev_lv = (self.bench_last.get(bench_id) or {}).get("level")
                    adaptive.update(
                        value=reading.ema_value if reading.valid else None,
                        span=span,
                        level=reading.status_level if reading.valid else None,
                        degraded=(qrep.health_status == "DEGRADED"),
                        process_ms=reading.process_ms,
                    )
                    if reading.valid and reading.status_level in ("warning", "alert") and reading.status_level != prev_lv:
                        ring.trigger(f"Выход за уставку ({reading.status_level})", reading.status_level, reading.ema_value)
                    self.bench_last[bench_id] = {
                        "ts": db.utcnow_iso(),
                        "value": _round(reading.ema_value) if reading.valid else None,
                        "angle": _round(reading.angle, 2),
                        "valid": reading.valid,
                        "level": reading.status_level if reading.valid else "stale",
                        "confidence": reading.needle_confidence,
                        "process_ms": reading.process_ms,
                    }
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("[%s] bench loop: %s", bench_id, exc)
            await self._sleep_with_motion_wakeup(bench_id, adaptive, last_no, max(0.08, adaptive.interval - (time.monotonic() - t0)))

    async def _process_auto_spec_triggers(self, disp: dict[str, Any], events: list[dict[str, Any]]) -> None:
        """
        Персистентный механизм автогенерации проектов ТЗ при критическом состоянии (DEF-20, REQ-DA-09).
        Предотвращает дубликаты через fingerprint (инструмент + первопричина + временной бакет cooldown),
        автоматически формирует .md/.docx, фиксирует статус/попытки и сохраняет на диск.
        """
        bucket = int(time.time() // max(60.0, config.AUTO_SPEC_COOLDOWN_SECONDS))
        snaps: dict[str, bytes] | None = None
        for item in disp.get("instruments") or []:
            if not item.get("critical_wear"):
                continue
            iid = str(item["id"])
            rc = str(item.get("root_cause") or "process_anomaly")
            fp = f"{iid}:{rc}:{bucket}"
            inc_ids = [
                int(e["id"]) for e in events
                if e.get("cam_id") == iid and e.get("kind") == "alarm" and e.get("id") is not None
            ][:10]
            trig, created = await db.create_or_get_auto_spec_trigger(
                fingerprint=fp,
                instrument_id=iid,
                code=str(item.get("code") or iid),
                name=str(item.get("name") or ""),
                group_name=str(item.get("group") or ""),
                health_score=float(item.get("health_score") or 0.0),
                root_cause=rc,
                reason=str((item.get("root_cause_meta") or {}).get("label") or rc),
                incident_ids=inc_ids,
            )
            if not created and trig.get("status") == "completed":
                continue
            if int(trig.get("attempts") or 0) >= 3:
                continue
            attempts = int(trig.get("attempts") or 0) + 1
            try:
                if snaps is None:
                    snaps = _collect_snapshots_by_inst(events)
                now_utc = _dt.datetime.now(_dt.timezone.utc)
                since_iso = (now_utc - _dt.timedelta(hours=24)).isoformat(timespec="milliseconds")
                hstats = await db.get_period_reading_stats(since_iso, now_utc.isoformat(timespec="milliseconds"), [iid])
                doc_num = f"АВТО-ТЗ-{str(item.get('code') or iid).replace(' ', '')}-{now_utc.strftime('%Y%m%d')}-{trig['id']:03d}"
                bundle = await generate_spec_bundle(
                    dispatch_overview=disp,
                    events=events,
                    snapshot_lookup=snaps,
                    period="24h",
                    instrument_id=iid,
                    requisites={"doc_number": doc_num},
                    mode="deterministic",
                    history_stats=hstats,
                    strict_scope=False,
                )
                docx_bytes = await asyncio.get_running_loop().run_in_executor(None, render_spec_docx, bundle)
                out_dir = config.get_auto_specs_dir()
                out_dir.mkdir(parents=True, exist_ok=True)
                safe_name = f"auto_spec_{trig['id']:04d}_{iid[:24]}"
                md_path = out_dir / f"{safe_name}.md"
                docx_path = out_dir / f"{safe_name}.docx"
                md_path.write_text(bundle["markdown"], encoding="utf-8")
                docx_path.write_bytes(docx_bytes)
                await db.update_auto_spec_trigger(
                    int(trig["id"]),
                    status="completed",
                    attempts=attempts,
                    doc_number=doc_num,
                    md_path=str(md_path),
                    docx_path=str(docx_path),
                    error=None,
                )
            except Exception as exc:
                await db.update_auto_spec_trigger(
                    int(trig["id"]),
                    status="failed",
                    attempts=attempts,
                    error=str(exc)[:300],
                )

    async def _architecture_sync_loop(self) -> None:
        """Периодическая синхронизация Modbus TCP, Store-and-Forward и аналитики треков 1 и 2."""
        tick_n = 0
        while True:
            try:
                await asyncio.sleep(2.0)
                tick_n += 1
                instruments = self.public_instruments()
                events = self.events.list(limit=300)
                st_map = self.stream_telemetry_map()
                disp = self.dispatch.overview(instruments, events, st_map)
                health_by_id = {x["id"]: x["health_score"] for x in disp["instruments"]}
                sf_pending = await self.store_forward.pending_count()
                self.scada.modbus.update_from_instruments(
                    instruments,
                    health_by_id=health_by_id,
                    sf_pending=sf_pending,
                    outage_active=self.store_forward.outage_active,
                )
                if tick_n % 3 == 1:
                    await self._process_auto_spec_triggers(disp, events)
                # Каждые 2 с кладём телеметрический пакет в Store-and-Forward (при обрыве — копится на диске!)
                crit_codes = [x["code"] for x in disp["instruments"] if x["level"] == "alert"]
                warn_codes = [x["code"] for x in disp["instruments"] if x["level"] == "warning"]
                await self.store_forward.enqueue(
                    channel_id="ktc-telemetry" if (tick_n % 2 == 0) else config.DEMO_LIVE_CAM_ID,
                    payload_type="telemetry",
                    severity="alert" if crit_codes else ("warning" if warn_codes else "info"),
                    payload={
                        "avg_health_score": disp["summary"]["avg_health_score"],
                        "critical_count": len(crit_codes),
                        "warning_count": len(warn_codes),
                        "critical_codes": crit_codes[:6],
                        "scenario": self.sim_adapter.scenario if config.is_demo_mode() else "live",
                    },
                )
                if self.hub.count > 0 or self._sse_clients:
                    sf_st = await self.store_forward.stats(recent_limit=6)
                    pkt = {
                        "type": "architecture_tick",
                        "ts": db.utcnow_iso(),
                        "store_forward": sf_st,
                        "scada": self.scada.status(),
                        "avg_health_score": disp["summary"]["avg_health_score"],
                    }
                    self.hub.broadcast(pkt)
                    self._broadcast_sse("architecture", pkt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("architecture sync loop: %s", exc)

    def stream_telemetry_map(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cid in self.cameras:
            out[cid] = self.streams.channel_telemetry(cid)
        for bid, ch in self.bench_channels.items():
            tel = self.streams.channel_telemetry(bid)
            out[bid] = tel
            if ch.get("linked_inst_id"):
                out[ch["linked_inst_id"]] = tel
        return out

    async def architecture_status(self) -> dict[str, Any]:
        streams_list = self.architecture_streams()
        sf = await self.store_forward.stats()
        sc = self.scada.status()
        online_n = sum(1 for s in streams_list if s["health_status"] == "ONLINE")
        degraded_n = sum(1 for s in streams_list if s["health_status"] == "DEGRADED")
        offline_n = sum(1 for s in streams_list if s["health_status"] == "OFFLINE")
        avg_lat = [s["inference_ms"] for s in streams_list if s.get("inference_ms")]
        avg_savings = [s["adaptive"]["cpu_savings_pct"] for s in streams_list if s.get("adaptive")]
        return {
            "ts": db.utcnow_iso(),
            "edge_node": {
                "id": config.EDGE_NODE_ID,
                "plant_name": config.PLANT_NAME,
                "uptime_s": int(time.time() - self.started_at),
                "yolo_available": vision.yolo_available(),
                "yolo_device": vision.yolo_device(),
                "channels_total": len(streams_list),
                "channels_online": online_n,
                "channels_degraded": degraded_n,
                "channels_offline": offline_n,
                "avg_inference_ms": round(sum(avg_lat) / max(1, len(avg_lat)), 1) if avg_lat else 0.0,
                "avg_cpu_savings_pct": round(sum(avg_savings) / max(1, len(avg_savings)), 1) if avg_savings else 0.0,
            },
            "streams": streams_list,
            "store_forward": sf,
            "scada": sc,
        }

    def architecture_streams(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for cid, cam in self.cameras.items():
            tel = self.streams.channel_telemetry(cid)
            rd = self.last.get(cid) or {}
            pub = self.public_camera(cam)
            out.append({
                "id": cid,
                "code": pub.get("code") or cid[:8],
                "name": cam["name"],
                "group": pub.get("group") or "Котлоагрегаты",
                "type": cam["type"],
                "source_url": mask_url_credentials(cam.get("source_url")) or ("wss://android-phone" if cam["type"] == "phone_ws" else "local"),
                "is_bench": False,
                "status": tel.get("status", "offline"),
                "health_status": tel["quality"]["health_status"],
                "fps": tel.get("fps", 0.0),
                "frames_total": tel.get("frames_total", 0),
                "fail_count": tel.get("fail_count", 0),
                "last_error": tel.get("last_error"),
                "inference_ms": rd.get("process_ms") or tel["adaptive"]["inference_ms"],
                "value": rd.get("value"),
                "unit": cam["unit"],
                "level": rd.get("level") or "stale",
                "confidence": rd.get("confidence"),
                "quality": tel["quality"],
                "adaptive": tel["adaptive"],
                "ring_buffer": tel["ring_buffer"],
                "injected_fault": tel.get("injected_fault"),
                "frame_url": f"/api/architecture/streams/{cid}/frame.jpg",
            })
        for bid, ch in self.bench_channels.items():
            tel = self.streams.channel_telemetry(bid)
            rd = self.bench_last.get(bid) or {}
            out.append({
                "id": bid,
                "code": ch["code"],
                "name": ch["name"],
                "group": ch["group"],
                "type": "rtsp_bench",
                "source_url": ch["source_url"],
                "is_bench": True,
                "status": tel.get("status", "offline"),
                "health_status": tel["quality"]["health_status"],
                "fps": tel.get("fps", 0.0),
                "frames_total": tel.get("frames_total", 0),
                "fail_count": tel.get("fail_count", 0),
                "last_error": tel.get("last_error"),
                "inference_ms": rd.get("process_ms") or tel["adaptive"]["inference_ms"],
                "value": rd.get("value"),
                "unit": ch["unit"],
                "level": rd.get("level") or "normal",
                "confidence": rd.get("confidence"),
                "quality": tel["quality"],
                "adaptive": tel["adaptive"],
                "ring_buffer": tel["ring_buffer"],
                "injected_fault": tel.get("injected_fault"),
                "frame_url": f"/api/architecture/streams/{bid}/frame.jpg",
            })
        return out

    async def stop(self) -> None:
        all_tasks = list(self._tasks.values()) + list(self._bench_tasks.values()) + self._bg
        for t in all_tasks:
            t.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)
        self._tasks.clear()
        self._bench_tasks.clear()
        self._bg.clear()
        await self.streams.stop_all()
        await self.scada.stop()
        await self.store_forward.close()
        await self._flush_db()
        await db.close_db()

    def _start_camera(self, cam: dict[str, Any]) -> None:
        cam_id = cam["id"]
        self.pipelines[cam_id] = vision.GaugePipeline(cam_id)
        try:
            self.streams.start_camera(
                cam_id, cam["type"], cam.get("source_url"),
                allowed_video_root=config.get_videos_dir() if cam["type"] == "video_file" else None,
            )
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
        """Анализ свежих кадров камеры с Adaptive FPS, контролем качества и Ring Buffer."""
        loop = asyncio.get_running_loop()
        adaptive = self.streams.adaptive_controller(cam_id)
        qa = self.streams.quality_analyzer(cam_id)
        ring = self.streams.ring_buffer(cam_id)
        last_no = 0
        while True:
            t0 = time.monotonic()
            try:
                cam = self.cameras.get(cam_id)
                pipeline = self.pipelines.get(cam_id)
                if cam is None or pipeline is None:
                    return
                fault = self.streams.get_fault(cam_id)
                frame, frame_no = self.broker.latest_frame(cam_id)
                if fault == "offline":
                    qa.set_offline("Симуляция обрыва канала", injected_fault="offline")
                    adaptive.update(value=None, span=1.0, level=None, degraded=True)
                elif frame is not None and frame_no != last_no:
                    last_no = frame_no
                    eff_frame = apply_signal_fault(frame, fault) if fault in ("steam", "low_light", "glare", "partial_occlusion") else frame
                    qrep = qa.analyze(eff_frame, stream_online=True, injected_fault=fault)
                    reading, jpeg, snap = await loop.run_in_executor(
                        self.executor, self._run_pipeline, pipeline, eff_frame, cam)
                    if jpeg:
                        self.broker.publish_overlay(cam_id, jpeg)
                        ring.push(jpeg)
                    cal = cam.get("calibration") or {}
                    span = abs(float(cal.get("v_max", 10.0)) - float(cal.get("v_min", 0.0))) or 1.0
                    adaptive.update(
                        value=reading.ema_value if reading.valid else None,
                        span=span,
                        level=reading.status_level if reading.valid else None,
                        degraded=(qrep.health_status == "DEGRADED"),
                        process_ms=reading.process_ms,
                    )
                    self._on_reading(cam_id, cam, reading, snap)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[%s] ошибка конвейера: %s", cam_id[:8], exc)
            await self._sleep_with_motion_wakeup(cam_id, adaptive, last_no, max(0.05, adaptive.interval - (time.monotonic() - t0)))

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
                if r.status_level in ("warning", "alert"):
                    self.streams.ring_buffer(cam_id).trigger(
                        f"Превышение уставки {sp or r.status_level}", r.status_level, state["value"]
                    )
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
            "source_url": mask_url_credentials(cam.get("source_url")),
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


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Санитизирует NaN/Infinity в ошибках валидации FastAPI/Pydantic, исключая HTTP 500 (DEF-09)."""
    safe_errors = sanitize_non_finite(exc.errors())
    return JSONResponse({"detail": safe_errors}, status_code=422)


@app.middleware("http")
async def _security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self'; connect-src 'self' wss: ws:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    # Строгий CORS: только явно разрешённые origins (никогда не '*')
    origin = request.headers.get("origin")
    if origin and config.CORS_ORIGINS:
        allowed = {o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()}
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
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


# -- аутентификация и RBAC (DEF-07) ------------------------------------------
@app.post("/api/auth/login")
async def api_auth_login(req: LoginRequest, request: Request) -> JSONResponse:
    sess = await auth.authenticate_user(req.username, req.password)
    ip = request.client.host if request.client else None
    if sess is None:
        await db.log_audit(username=req.username, role=None, action="LOGIN_FAILED", target="/api/auth/login", status_code=401, ip=ip)
        raise HTTPException(401, "Неверное имя пользователя или пароль")
    await db.log_audit(username=sess["username"], role=sess["role"], action="LOGIN_OK", target="/api/auth/login", status_code=200, ip=ip)
    resp = JSONResponse({
        "ok": True,
        "username": sess["username"],
        "role": sess["role"],
        "permissions": sess["permissions"],
        "expires_at": sess["expires_at"],
        "token": sess["token"],
    })
    resp.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=sess["token"],
        httponly=True,
        samesite="strict",
        secure=(request.url.scheme == "https"),
        max_age=config.SESSION_TTL_SECONDS,
        path="/",
    )
    return resp


@app.post("/api/auth/logout")
async def api_auth_logout(request: Request) -> JSONResponse:
    tok = auth.extract_token_from_request(request)
    if tok:
        sess = await auth.resolve_session(tok)
        await db.delete_session(auth.hash_token(tok))
        if sess:
            await db.log_audit(
                username=sess.get("username"),
                role=sess.get("role"),
                action="LOGOUT",
                target="/api/auth/logout",
                status_code=200,
                ip=request.client.host if request.client else None,
            )
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.SESSION_COOKIE_NAME, path="/")
    return resp


@app.get("/api/auth/me")
async def api_auth_me(request: Request) -> dict[str, Any]:
    sess = await auth.get_optional_user(request)
    if sess is None:
        return {
            "authenticated": False,
            "auth_required": auth.is_auth_required(),
            "username": None,
            "role": None,
            "permissions": [],
        }
    return {
        "authenticated": True,
        "auth_required": auth.is_auth_required(),
        "username": sess["username"],
        "role": sess["role"],
        "permissions": auth.ROLE_PERMISSIONS.get(sess["role"], []),
        "expires_at": sess["expires_at"],
    }


@app.get("/api/auth/users")
async def api_auth_users(_user: dict[str, Any] = Depends(auth.require_role("admin"))) -> list[dict[str, Any]]:
    return await db.list_users()


@app.get("/api/auth/audit")
async def api_auth_audit(
    limit: int = Query(100, ge=1, le=500),
    _user: dict[str, Any] = Depends(auth.require_role("admin")),
) -> list[dict[str, Any]]:
    return await db.list_audit_log(limit=limit)


# -- справочники и сервис -----------------------------------------------------
@app.get("/api/meta")
async def api_meta(request: Request) -> dict[str, Any]:
    from .cert_gen import cert_fingerprint
    fingerprint = None
    with contextlib.suppress(Exception):
        fingerprint = cert_fingerprint()
    sess = await auth.get_optional_user(request)
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
        "auth_required": auth.is_auth_required(),
        "authenticated": sess is not None,
        "user": {"username": sess["username"], "role": sess["role"], "permissions": auth.ROLE_PERMISSIONS.get(sess["role"], [])} if sess else None,
        "fault_injection_allowed": auth.is_fault_injection_allowed(),
        "disclaimer": LEGAL_DISCLAIMER,
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
async def api_cameras(_user: dict[str, Any] = Depends(auth.require_role("operator"))) -> list[dict[str, Any]]:
    return service.public_cameras()


@app.get("/api/instruments")
async def api_instruments(_user: dict[str, Any] = Depends(auth.require_role("operator"))) -> list[dict[str, Any]]:
    return service.public_instruments()


@app.get("/api/instruments/{inst_id}/history")
async def api_instrument_history(
    inst_id: str,
    limit: int = Query(120, ge=1, le=5000),
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
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
async def api_instrument_export_csv(
    inst_id: str,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> Response:
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
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
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
async def api_create_camera(
    data: CameraCreate,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    res = await service.add_camera(data)
    await db.log_audit(username=user["username"], role=user["role"], action="CREATE_CAMERA",
                       target=res["id"], status_code=201, ip=request.client.host if request.client else None)
    return res


def _get_cam(cam_id: str) -> dict[str, Any]:
    cam = service.cameras.get(cam_id)
    if cam is None:
        raise HTTPException(404, "Прибор не найден")
    return cam


@app.get("/api/cameras/{cam_id}")
async def api_camera(
    cam_id: str,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    return service.public_camera(_get_cam(cam_id))


@app.patch("/api/cameras/{cam_id}")
async def api_update_camera(
    cam_id: str,
    data: CameraUpdate,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    res = await service.update_camera(cam_id, data)
    await db.log_audit(username=user["username"], role=user["role"], action="UPDATE_CAMERA",
                       target=cam_id, status_code=200, ip=request.client.host if request.client else None)
    return res


@app.delete("/api/cameras/{cam_id}", status_code=204)
async def api_delete_camera(
    cam_id: str,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("admin")),
) -> Response:
    await service.delete_camera(cam_id)
    await db.log_audit(username=user["username"], role=user["role"], action="DELETE_CAMERA",
                       target=cam_id, status_code=204, ip=request.client.host if request.client else None)
    return Response(status_code=204)


@app.post("/api/cameras/{cam_id}/restart")
async def api_restart_camera(
    cam_id: str,
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    return await service.restart_camera(cam_id)


@app.post("/api/cameras/{cam_id}/redetect")
async def api_redetect(
    cam_id: str,
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    _get_cam(cam_id)
    pipeline = service.pipelines.get(cam_id)
    if pipeline:
        pipeline.reset()
    return {"ok": True}


@app.get("/api/cameras/{cam_id}/frame.jpg")
async def api_frame(
    cam_id: str,
    overlay: int = 1,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> Response:
    _get_cam(cam_id)
    jpeg, _ = await asyncio.get_running_loop().run_in_executor(
        None, service.broker.latest_jpeg, cam_id, bool(overlay))
    return Response(jpeg or NO_SIGNAL, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/cameras/{cam_id}/mjpeg")
async def api_mjpeg(
    cam_id: str,
    request: Request,
    overlay: int = 1,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> StreamingResponse:
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
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
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
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
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
async def api_events(
    limit: int = Query(300, ge=1, le=config.EVENTS_MAX),
    cam_id: str | None = None,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> list[dict[str, Any]]:
    return service.events.list(limit, cam_id)


@app.get("/api/events/{ev_id}/frame.jpg")
async def api_event_frame(
    ev_id: int,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> Response:
    jpeg = service.events.snapshot(ev_id)
    if jpeg is None:
        raise HTTPException(404, "Стоп-кадр не сохранён")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/events/{ev_id}/ack")
async def api_ack_event(
    ev_id: int,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    """Адресное идемпотентное квитирование конкретного события журнала."""
    actor = f"{user['username']} ({request.client.host if request.client else '?'})"
    ts = db.utcnow_iso()
    ev, changed = service.events.acknowledge_one(ev_id, ts, actor)
    if ev is None:
        raise HTTPException(404, "Событие не найдено")
    ids = [ev_id] if changed else []
    if changed:
        await db.update_events_ack(ids, ts, actor)
        service.hub.broadcast({"type": "ack", "ts": ts, "by": actor, "ids": ids})
        service.emit("ack", cam_id=ev.get("cam_id"), cam_name=ev.get("cam_name"),
                     text=actor, value=1.0, ref_event_id=ev_id)
    return {"ok": True, "already_acked": not changed, "ts": ev.get("acked_ts") or ts, "ids": ids, "event": ev}


@app.delete("/api/cameras/{cam_id}/history", status_code=204)
async def api_clear_history(
    cam_id: str,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("admin")),
) -> Response:
    _get_cam(cam_id)
    await service._flush_db()
    await db.clear_history(cam_id)
    await db.log_audit(username=user["username"], role=user["role"], action="CLEAR_HISTORY",
                       target=cam_id, status_code=204, ip=request.client.host if request.client else None)
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
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
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
async def api_demo_state(_user: dict[str, Any] = Depends(auth.require_role("operator"))) -> dict[str, Any]:
    return await service.demo_state()


@app.get("/api/demo/scenarios")
async def api_demo_scenarios(_user: dict[str, Any] = Depends(auth.require_role("operator"))) -> dict[str, Any]:
    return {"scenario": service.sim_adapter.scenario, "scenarios": list(demo.DEMO_SCENARIOS)}


@app.post("/api/demo/scenario")
async def api_set_demo_scenario(
    req: DemoScenarioRequest,
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    return await service.set_demo_scenario(req.scenario)


@app.get("/api/demo/runs")
async def api_demo_runs(
    cam_id: str | None = None,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> list[dict[str, Any]]:
    await service._flush_db()
    target = cam_id or (config.DEMO_LIVE_CAM_ID if config.is_demo_mode() else None)
    return await db.list_demo_runs(target, limit=30)


@app.post("/api/demo/runs/start")
async def api_demo_run_start(
    req: DemoRunStartRequest | None = None,
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    body = req or DemoRunStartRequest()
    return await service.start_demo_run(body.cam_id, body.label)


@app.post("/api/demo/runs/stop")
async def api_demo_run_stop(
    req: DemoRunStopRequest | None = None,
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    body = req or DemoRunStopRequest()
    return await service.stop_demo_run(body.run_id)


@app.get("/api/demo/runs/{run_id}/readings")
async def api_demo_run_readings(
    run_id: str,
    limit: int = Query(5000, ge=1, le=100_000),
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
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
async def api_demo_run_export_csv(
    run_id: str,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> Response:
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
async def api_phone_session(
    req: PhoneSessionRequest,
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
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
    sess = await auth.authorize_ws(ws, min_role="operator")
    if sess is None:
        await ws.close(code=4401, reason="unauthorized or invalid origin")
        return
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
async def api_ack(
    request: Request,
    body: AckRequest | None = None,
    user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    actor = f"{user['username']} ({request.client.host if request.client else '?'})"
    ts = db.utcnow_iso()
    ev_id = body.event_id if body else None
    cam_id = body.cam_id if body else None
    if ev_id is not None:
        ev, changed = service.events.acknowledge_one(ev_id, ts, actor)
        if ev is None:
            raise HTTPException(404, "Событие не найдено")
        ids = [ev_id] if changed else []
        if changed:
            await db.update_events_ack(ids, ts, actor)
            service.hub.broadcast({"type": "ack", "ts": ts, "by": actor, "ids": ids})
            service.emit("ack", cam_id=ev.get("cam_id"), cam_name=ev.get("cam_name"),
                         text=actor, value=1.0, ref_event_id=ev_id)
        return {"ok": True, "already_acked": not changed, "ts": ev.get("acked_ts") or ts, "ids": ids}
    ids = service.events.acknowledge(ts, actor, cam_id=cam_id)
    logger.info("Аварии квитированы оператором (%s): %d", actor, len(ids))
    if ids:
        await db.update_events_ack(ids, ts, actor)
        service.hub.broadcast({"type": "ack", "ts": ts, "by": actor, "ids": ids})
        service.emit("ack", cam_id=cam_id, text=actor, value=float(len(ids)))
    return {"ok": True, "ts": ts, "ids": ids}


# -- сетевое обнаружение -----------------------------------------------------------
_discover_lock = asyncio.Lock()


@app.get("/api/discover")
async def api_discover(
    request: Request,
    subnet: str | None = Query(None, description="IP из подсети /24 для сканирования"),
    user: dict[str, Any] = Depends(auth.require_role("admin")),
) -> dict[str, Any]:
    if _discover_lock.locked():
        raise HTTPException(409, "Сканирование уже выполняется")
    async with _discover_lock:
        t0 = time.monotonic()
        base = subnet or service.lan_ip
        await db.log_audit(username=user["username"], role=user["role"], action="NETWORK_DISCOVER",
                           target=base, status_code=200, ip=request.client.host if request.client else None)
        devices = await discovery.discover_all(timeout=config.ONVIF_PROBE_TIMEOUT, base_ip=base)
        known = {(c.get("source_url") or "") for c in service.cameras.values()}
        for d in devices:
            d["already_added"] = bool(d.get("suggested_url")) and d["suggested_url"] in known
        return {"subnet": f"{'.'.join(base.split('.')[:3])}.0/24", "devices": devices,
                "elapsed_s": round(time.monotonic() - t0, 2)}


# ---------------------------------------------------------------------------
# Трек №2: Архитектурная видеоаналитика, Store-and-Forward, SCADA, SSE
# ---------------------------------------------------------------------------
@app.get("/api/events/stream")
async def api_events_sse(
    request: Request,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> StreamingResponse:
    """Server-Sent Events (SSE) поток событий, телеметрии и статуса Store-and-Forward."""
    q: asyncio.Queue[str] = asyncio.Queue(100)
    service._sse_clients.add(q)

    async def gen() -> AsyncIterator[bytes]:
        try:
            init_payload = {
                "edge_node": config.EDGE_NODE_ID,
                "ts": db.utcnow_iso(),
                "store_forward": await service.store_forward.stats(recent_limit=4),
            }
            yield f"event: connected\ndata: {json.dumps(init_payload, ensure_ascii=False)}\n\n".encode("utf-8")
            while True:
                if await request.is_disconnected():
                    break
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield chunk.encode("utf-8")
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
        finally:
            service._sse_clients.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/architecture/status")
async def api_architecture_status(
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    return await service.architecture_status()


@app.get("/api/architecture/streams")
async def api_architecture_streams(
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> list[dict[str, Any]]:
    return service.architecture_streams()


@app.get("/api/architecture/streams/{stream_id}/frame.jpg")
async def api_architecture_stream_frame(
    stream_id: str,
    overlay: int = 1,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> Response:
    if stream_id not in service.cameras and stream_id not in service.bench_channels:
        raise HTTPException(404, "Видеоканал не найден")
    jpeg, _ = await asyncio.get_running_loop().run_in_executor(
        None, service.broker.latest_jpeg, stream_id, bool(overlay)
    )
    return Response(jpeg or NO_SIGNAL, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/architecture/outage")
async def api_architecture_outage(
    req: OutageToggleRequest,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("admin")),
) -> dict[str, Any]:
    if not auth.is_fault_injection_allowed():
        raise HTTPException(403, "Симуляция отказов отключена вне демонстрационного/стендового профиля")
    sf = await service.store_forward.set_outage(req.active, req.reason)
    await db.log_audit(username=user["username"], role=user["role"], action="FAULT_OUTAGE_TOGGLE",
                       target=f"active={req.active}", status_code=200, ip=request.client.host if request.client else None)
    service.emit(
        "link",
        cam_id=config.EDGE_NODE_ID,
        cam_name="Шлюз АСУ ТП (Store-and-Forward)",
        text="offline" if req.active else "online",
    )
    return {"ok": True, "store_forward": sf}


@app.post("/api/architecture/degrade")
async def api_architecture_degrade(
    req: DegradeRequest,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("admin")),
) -> dict[str, Any]:
    if not auth.is_fault_injection_allowed():
        raise HTTPException(403, "Симуляция деградации видеосигнала отключена вне демонстрационного/стендового профиля")
    if req.stream_id not in service.cameras and req.stream_id not in service.bench_channels:
        raise HTTPException(404, "Видеоканал не найден")
    try:
        applied = service.streams.set_fault(req.stream_id, req.mode)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.log_audit(username=user["username"], role=user["role"], action="FAULT_DEGRADE",
                       target=f"{req.stream_id}:{req.mode}", status_code=200, ip=request.client.host if request.client else None)
    return {
        "ok": True,
        "stream_id": req.stream_id,
        "injected_fault": applied,
        "telemetry": service.streams.channel_telemetry(req.stream_id),
    }


@app.get("/api/architecture/store-forward")
async def api_store_forward_stats(
    limit: int = Query(20, ge=1, le=200),
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    return await service.store_forward.stats(recent_limit=limit)


@app.post("/api/architecture/store-forward/flush")
async def api_store_forward_flush(
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    res = await service.store_forward.flush_pending(max_batches=20)
    return {"ok": True, **res, "store_forward": await service.store_forward.stats()}


@app.get("/api/scada/status")
async def api_scada_status(
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    return service.scada.status()


@app.get("/api/scada/modbus/registers")
async def api_scada_modbus_registers(
    limit: int = Query(36, ge=1, le=100),
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    instruments = service.public_instruments()
    events = service.events.list(limit=300)
    disp = service.dispatch.overview(instruments, events, service.stream_telemetry_map())
    health_by_id = {x["id"]: x["health_score"] for x in disp["instruments"]}
    sf_pending = await service.store_forward.pending_count()
    service.scada.modbus.update_from_instruments(
        instruments,
        health_by_id=health_by_id,
        sf_pending=sf_pending,
        outage_active=service.store_forward.outage_active,
    )
    return service.scada.modbus.registers_snapshot(limit=limit)


@app.get("/api/scada/mqtt/messages")
async def api_scada_mqtt_messages(
    limit: int = Query(30, ge=1, le=100),
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    return {
        "status": service.scada.mqtt.status(),
        "messages": service.scada.mqtt.recent_messages(limit=limit),
    }


# ---------------------------------------------------------------------------
# Трек №1: Умная диспетчеризация, Health Score и автогенерация ТЗ (.md / .docx)
# ---------------------------------------------------------------------------
def _collect_snapshots_by_inst(events: list[dict[str, Any]]) -> dict[str, bytes]:
    snaps: dict[str, bytes] = {}
    for ev in events:
        cid = ev.get("cam_id")
        if cid and cid not in snaps and ev.get("has_frame"):
            raw = service.events.snapshot(ev["id"])
            if raw:
                snaps[cid] = raw
    for bid, ch in service.bench_channels.items():
        linked = ch.get("linked_inst_id")
        if linked and linked not in snaps:
            kf = service.streams.ring_buffer(bid).latest_keyframe()
            if kf:
                snaps[linked] = kf
    return snaps


@app.get("/api/dispatch/overview")
async def api_dispatch_overview(
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    instruments = service.public_instruments()
    events = service.events.list(limit=500)
    ov = service.dispatch.overview(instruments, events, service.stream_telemetry_map())
    ov["auto_spec_triggers"] = await db.list_auto_spec_triggers(limit=30)
    return ov


@app.get("/api/dispatch/instrument/{inst_id}")
async def api_dispatch_instrument(
    inst_id: str,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    instruments = service.public_instruments()
    target = next((x for x in instruments if x["id"] == inst_id), None)
    if target is None:
        raise HTTPException(404, "Прибор не найден")
    events = service.events.list(limit=500)
    item = service.dispatch.analyze_instrument(target, events, service.stream_telemetry_map().get(inst_id))
    return {
        **item,
        "rate_series": item.get("rate_series") or service.dispatch.rate_series_for(inst_id, item.get("sparkline") or []),
        "evidence_url": f"/api/dispatch/evidence/{inst_id}/frame.jpg",
    }


@app.get("/api/dispatch/incidents")
async def api_dispatch_incidents(
    limit: int = Query(30, ge=1, le=200),
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> list[dict[str, Any]]:
    instruments = service.public_instruments()
    by_id = {x["id"]: x for x in instruments}
    events = service.events.list(limit=500)
    disp = service.dispatch.overview(instruments, events, service.stream_telemetry_map())
    disp_by_id = {x["id"]: x for x in disp["instruments"]}
    out: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("kind") not in ("alarm", "link"):
            continue
        cid = ev.get("cam_id")
        if not cid or cid not in by_id:
            continue
        d = disp_by_id.get(cid)
        frame_url = f"/api/events/{ev['id']}/frame.jpg" if ev.get("has_frame") else f"/api/dispatch/evidence/{cid}/frame.jpg"
        out.append({
            **ev,
            "code": by_id[cid].get("code") or cid,
            "group": by_id[cid].get("group") or "",
            "health_score": d["health_score"] if d else None,
            "equipment_health": d["equipment_health"] if d else None,
            "optical_health": d["optical_health"] if d else None,
            "root_cause": d["root_cause"] if d else "nominal",
            "root_cause_label": d["root_cause_meta"]["label"] if d else "Штатно",
            "evidence_url": frame_url,
        })
        if len(out) >= limit:
            break
    return out


@app.get("/api/dispatch/evidence/{inst_id}/frame.jpg")
async def api_dispatch_evidence_frame(
    inst_id: str,
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> Response:
    instruments = service.public_instruments()
    target = next((x for x in instruments if x["id"] == inst_id), None)
    if target is None:
        raise HTTPException(404, "Прибор не найден")
    events = service.events.list(limit=300)
    snaps = _collect_snapshots_by_inst(events)
    item = service.dispatch.analyze_instrument(target, events, service.stream_telemetry_map().get(inst_id))
    jpeg = await asyncio.get_running_loop().run_in_executor(
        None, build_evidence_frame_jpeg, item, snaps.get(inst_id)
    )
    return Response(jpeg or NO_SIGNAL, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/specs/catalog")
async def api_specs_catalog(
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> dict[str, Any]:
    return {
        "catalog": DIGITAL_SENSOR_CATALOG,
        "llm": llm_status(),
        "disclaimer": LEGAL_DISCLAIMER,
        "economics_defaults": {
            "commissioning_rate": config.ECO_COMMISSIONING_RATE,
            "rounds_savings_per_unit_rub": config.ECO_ROUNDS_SAVINGS_RUB_YR,
            "opex_per_sensor_rub_yr": config.ECO_OPEX_PER_SENSOR_RUB_YR,
        },
        "defaults": {
            "plant_name": config.PLANT_NAME,
            "branch_name": config.PLANT_BRANCH,
            "workshop": "Котлотурбинный цех (КТЦ)",
            "customer": "ПАО «Интер РАО»",
            "contractor": "Служба КИПиА, АСУ ТП и видеоаналитики GaugeVision AI",
        },
    }


@app.get("/api/specs/auto")
async def api_auto_specs_list(
    limit: int = Query(30, ge=1, le=200),
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> list[dict[str, Any]]:
    """Персистентный реестр автоматически сформированных проектов ТЗ (DEF-20)."""
    return await db.list_auto_spec_triggers(limit=limit)


@app.get("/api/specs/auto/{trigger_id}/download")
async def api_auto_spec_download(
    trigger_id: int,
    format: Literal["docx", "md"] = "docx",
    _user: dict[str, Any] = Depends(auth.require_role("operator")),
) -> Response:
    trig = await db.get_auto_spec_trigger(trigger_id)
    if trig is None:
        raise HTTPException(404, "Автоматически сформированный документ не найден")
    path_str = trig.get("docx_path") if format == "docx" else trig.get("md_path")
    if not path_str:
        raise HTTPException(404, "Файл документа ещё не сформирован")
    p = config.Path(path_str).resolve()
    if not p.is_relative_to(config.get_auto_specs_dir().resolve()) or not p.is_file():
        raise HTTPException(404, "Файл документа недоступен")
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx" else "text/markdown; charset=utf-8"
    )
    return Response(
        p.read_bytes(),
        media_type=media,
        headers={
            "Content-Disposition": f"attachment; filename=\"{p.name}\"",
            "Cache-Control": "no-store",
        },
    )


async def _load_period_history_and_events(period: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], _dt.datetime]:
    """Загружает фактическую историю из SQLite `readings` и `events` строго за выбранный период (DEF-03)."""
    await service._flush_db()
    _, period_hours = PERIOD_LABELS.get(period, PERIOD_LABELS["12h"])
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    since_iso = (now_utc - _dt.timedelta(hours=period_hours)).isoformat(timespec="milliseconds")
    until_iso = now_utc.isoformat(timespec="milliseconds")
    hstats = await db.get_period_reading_stats(since_iso, until_iso)
    db_evs = await db.list_events_in_period(since_iso, until_iso, limit=5000)
    # Объединяем персистентные события БД с ещё не записанными в БД событиями из памяти без дубликатов
    by_id = {int(e["id"]): e for e in db_evs if e.get("id") is not None}
    for e in service.events.list(limit=1000):
        eid = e.get("id")
        if eid is not None and int(eid) not in by_id:
            by_id[int(eid)] = e
    merged_evs = list(by_id.values())
    return hstats, merged_evs, now_utc


@app.post("/api/specs/preview")
async def api_specs_preview(
    req: SpecGenerateRequest,
    _user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> dict[str, Any]:
    instruments = service.public_instruments()
    hstats, events, now_utc = await _load_period_history_and_events(req.period)
    disp = service.dispatch.overview(instruments, events, service.stream_telemetry_map())
    try:
        bundle = await generate_spec_bundle(
            dispatch_overview=disp,
            events=events,
            snapshot_lookup={},
            period=req.period,
            group_filter=req.group,
            instrument_id=req.instrument_id,
            requisites=req.model_dump(exclude_none=True, exclude={"economics_config"}),
            mode=req.mode,
            history_stats=hstats,
            economics_config=req.economics_config.model_dump(exclude_none=True) if req.economics_config else None,
            strict_scope=True,
            now_utc=now_utc,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "doc_number": bundle["doc_number"],
        "date_str": bundle["date_str"],
        "period": bundle["period"],
        "period_hours": bundle["period_hours"],
        "db_samples_count": bundle["db_samples_count"],
        "coverage_hours": bundle["coverage_hours"],
        "coverage_sufficient": bundle["coverage_sufficient"],
        "period_events_count": bundle["period_events_count"],
        "engine_used": bundle["engine_used"],
        "executive_summary": bundle["executive_summary"],
        "scoped_count": len(bundle["scoped_items"]),
        "defective_count": len(bundle["defective_items"]),
        "tz_count": len(bundle["tz_items"]),
        "economics": bundle["economics"],
        "markdown": bundle["markdown"],
    }


@app.post("/api/specs/generate")
async def api_specs_generate(
    req: SpecGenerateRequest,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_role("engineer")),
) -> Response:
    instruments = service.public_instruments()
    hstats, events, now_utc = await _load_period_history_and_events(req.period)
    disp = service.dispatch.overview(instruments, events, service.stream_telemetry_map())
    snaps = _collect_snapshots_by_inst(events)
    try:
        bundle = await generate_spec_bundle(
            dispatch_overview=disp,
            events=events,
            snapshot_lookup=snaps,
            period=req.period,
            group_filter=req.group,
            instrument_id=req.instrument_id,
            requisites=req.model_dump(exclude_none=True, exclude={"economics_config"}),
            mode=req.mode,
            history_stats=hstats,
            economics_config=req.economics_config.model_dump(exclude_none=True) if req.economics_config else None,
            strict_scope=True,
            now_utc=now_utc,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.log_audit(username=user["username"], role=user["role"], action="GENERATE_SPEC",
                       target=f"{bundle['doc_number']}:{req.period}:{req.format}", status_code=200,
                       ip=request.client.host if request.client else None)
    safe_doc = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in bundle["doc_number"])[:50] or "TZ_KIP"
    if req.format == "md":
        fname = f"{safe_doc}_TZ_GaugeVision.md"
        return Response(
            bundle["markdown"].encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=\"TZ_GaugeVision.md\"; filename*=UTF-8''{quote(fname)}",
                "Cache-Control": "no-store",
            },
        )
    docx_bytes = await asyncio.get_running_loop().run_in_executor(None, render_spec_docx, bundle)
    fname = f"{safe_doc}_Дефектная_ведомость_и_ТЗ.docx"
    return Response(
        docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"TZ_GaugeVision.docx\"; filename*=UTF-8''{quote(fname)}",
            "Cache-Control": "no-store",
        },
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Необработанная ошибка %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)
