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
  GET    /api/cameras/{id}/export.csv   экспорт истории в CSV (ISO 8601)
  POST   /api/phone/session             «Смартфон как камера»: токен + QR-код
  GET    /api/discover                  ONVIF WS-Discovery + скан подсети /24
  POST   /api/alarms/ack                квитирование аварий на всех дашбордах
  GET    /api/cert.pem                  самоподписный сертификат (для смартфона)
"""
from __future__ import annotations

import asyncio
import contextlib
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

from . import __app_name__, __version__, config, db, discovery, vision
from .streamer import FrameBroker, StreamManager, encode_jpeg

logger = logging.getLogger("gaugevision.main")


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------
GaugeType = Literal["pressure", "temperature", "draft", "level", "electrical", "flow"]
CameraType = Literal["device", "rtsp", "http_mjpeg", "phone_ws"]


class RoiModel(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    cx: float = Field(0.5, ge=0.0, le=1.0)
    cy: float = Field(0.5, ge=0.0, le=1.0)
    r: float = Field(0.45, gt=0.0, le=1.0)


class CalibrationModel(BaseModel):
    v_min: float = 0.0
    theta_min: float = 135.0
    v_max: float = 10.0
    theta_max: float = 45.0
    direction: Literal["cw", "ccw"] = "cw"
    roi: RoiModel | None = None

    @field_validator("theta_min", "theta_max")
    @classmethod
    def _norm_angle(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("угол должен быть числом")
        return v % 360.0

    @field_validator("v_max")
    @classmethod
    def _span(cls, v: float, info: Any) -> float:
        if "v_min" in info.data and v == info.data["v_min"]:
            raise ValueError("V_max должен отличаться от V_min")
        return v


class ThresholdsModel(BaseModel):
    ll_alert: float | None = None
    l_warn: float | None = None
    h_warn: float | None = None
    hh_alert: float | None = None

    def check_order(self) -> None:
        """LL ≤ L < H ≤ HH (незаданные уставки пропускаются)."""
        seq = [(n, getattr(self, n)) for n in ("ll_alert", "l_warn", "h_warn", "hh_alert")]
        seq = [(n, v) for n, v in seq if v is not None]
        for (n1, v1), (n2, v2) in zip(seq, seq[1:]):
            if v1 > v2:
                raise HTTPException(422, f"Уставки должны идти по возрастанию: {n1} ({v1}) > {n2} ({v2})")


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
        self._db_buffer: list[tuple[str, str, float | None, float | None, str]] = []
        self._last_db_write: dict[str, float] = {}
        self._bg: list[asyncio.Task] = []
        self.lan_ip = config.get_lan_ip()
        self.started_at = time.time()

    # -- жизненный цикл ------------------------------------------------------
    async def start(self) -> None:
        await db.init_db()
        # загрузка и прогрев YOLO (torch/CUDA) — вне event-loop, до старта конвейеров
        await asyncio.get_running_loop().run_in_executor(self.executor, vision.yolo_available)
        for cam in await db.list_cameras():
            self.cameras[cam["id"]] = cam
            self._start_camera(cam)
        self._bg.append(asyncio.create_task(self._db_writer(), name="db-writer"))
        self._bg.append(asyncio.create_task(self._housekeeping(), name="housekeeping"))
        logger.info("Загружено приборов: %d", len(self.cameras))

    async def stop(self) -> None:
        for t in list(self._tasks.values()) + self._bg:
            t.cancel()
        await asyncio.gather(*self._tasks.values(), *self._bg, return_exceptions=True)
        await self.streams.stop_all()
        await self._flush_db()
        self.executor.shutdown(wait=False, cancel_futures=True)
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

    # -- конвейер зрения ------------------------------------------------------
    @staticmethod
    def _run_pipeline(pipeline: vision.GaugePipeline, frame: np.ndarray,
                      cam: dict[str, Any]) -> tuple[vision.GaugeReading, bytes | None]:
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
        return reading, jpeg

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
                    reading, jpeg = await loop.run_in_executor(
                        self.executor, self._run_pipeline, pipeline, frame, cam)
                    if jpeg:
                        self.broker.publish_overlay(cam_id, jpeg)
                    self._on_reading(cam_id, cam, reading)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[%s] ошибка конвейера: %s", cam_id[:8], exc)
            await asyncio.sleep(max(0.02, interval - (time.monotonic() - t0)))

    def _on_reading(self, cam_id: str, cam: dict[str, Any], r: vision.GaugeReading) -> None:
        ts = db.utcnow_iso()
        prev = self.last.get(cam_id) or {}
        state = {
            "ts": ts,
            "value": _round(r.ema_value),
            "raw_value": _round(r.value),
            "angle": _round(r.angle, 2),
            "valid": r.valid,
            "confidence": r.needle_confidence,
            "level": r.status_level,
            "dial_found": r.dial_found,
            "dial_source": r.dial_source,
            "method": r.debug.get("needle_method"),
            "process_ms": r.process_ms,
            # последнее достоверное значение и его время сохраняются при сбоях
            "last_valid_ts": ts if r.valid else prev.get("last_valid_ts"),
        }
        self.last[cam_id] = state
        self.hub.broadcast({"type": "reading", "cam_id": cam_id, **state})

        now = time.monotonic()
        if r.valid and r.ema_value is not None and \
                now - self._last_db_write.get(cam_id, 0.0) >= config.DB_WRITE_INTERVAL:
            self._last_db_write[cam_id] = now
            self._db_buffer.append((cam_id, ts, float(r.ema_value),
                                    None if r.angle is None else float(r.angle),
                                    r.status_level))

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

    # -- CRUD ----------------------------------------------------------------
    def public_camera(self, cam: dict[str, Any]) -> dict[str, Any]:
        cam_id = cam["id"]
        return {
            **cam,
            "status": self.streams.status_of(cam_id),
            "stream": self.streams.info(cam_id),
            "reading": self.last.get(cam_id),
        }

    def public_cameras(self) -> list[dict[str, Any]]:
        return [self.public_camera(c) for c in self.cameras.values()]

    async def add_camera(self, data: CameraCreate) -> dict[str, Any]:
        unit = _validate_unit(data.gauge_type, data.unit)
        source = _validate_source(data.type, data.source_url)
        if data.thresholds:
            data.thresholds.check_order()
        cam = await db.create_camera(
            name=data.name.strip(), type=data.type, gauge_type=data.gauge_type, unit=unit,
            source_url=source,
            calibration=data.calibration.model_dump() if data.calibration else None,
            thresholds=data.thresholds.model_dump() if data.thresholds else None,
        )
        self.cameras[cam["id"]] = cam
        self._start_camera(cam)
        out = self.public_camera(cam)
        self.hub.broadcast({"type": "camera_added", "camera": out})
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
        if data.thresholds is not None:
            data.thresholds.check_order()
            patch["thresholds"] = data.thresholds.model_dump()
        reset_roi = False
        if data.calibration is not None:
            patch["calibration"] = data.calibration.model_dump()
            reset_roi = patch["calibration"].get("roi") != cam["calibration"].get("roi")

        updated = await db.update_camera(cam_id, patch)
        if updated is None:
            raise HTTPException(404, "Прибор не найден")
        self.cameras[cam_id] = updated
        if restart:
            await self._stop_camera(cam_id)
            self.last.pop(cam_id, None)
            self._start_camera(updated)
        elif reset_roi and cam_id in self.pipelines:
            self.pipelines[cam_id].reset()
        out = self.public_camera(updated)
        self.hub.broadcast({"type": "camera_updated", "camera": out})
        return out

    async def delete_camera(self, cam_id: str) -> None:
        if cam_id not in self.cameras:
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


# -- камеры --------------------------------------------------------------------
@app.get("/api/cameras")
async def api_cameras() -> list[dict[str, Any]]:
    return service.public_cameras()


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
async def api_history(cam_id: str, limit: int = Query(config.TREND_WINDOW_DEFAULT, ge=1, le=100_000)
                      ) -> list[dict[str, Any]]:
    _get_cam(cam_id)
    return await db.get_history(cam_id, limit)


@app.delete("/api/cameras/{cam_id}/history", status_code=204)
async def api_clear_history(cam_id: str) -> Response:
    _get_cam(cam_id)
    await db.clear_history(cam_id)
    return Response(status_code=204)


@app.get("/api/cameras/{cam_id}/export.csv")
async def api_export_csv(cam_id: str) -> Response:
    cam = _get_cam(cam_id)
    csv_text = await db.export_csv(cam_id)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in cam["name"])[:60] or "gauge"
    filename = f"{safe}_{stamp}.csv"
    ascii_name = f"gauge_{cam_id[:8]}_{stamp}.csv"
    return Response(
        "\ufeff" + csv_text,  # BOM (U+FEFF) — корректная кириллица в Excel
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"},
    )


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
    if req.cam_id:
        cam = _get_cam(req.cam_id)
        if cam["type"] != "phone_ws":
            raise HTTPException(422, "Прибор не является смартфон-камерой")
    else:
        n = sum(1 for c in service.cameras.values() if c["type"] == "phone_ws") + 1
        cam = await service.add_camera(CameraCreate(
            name=(req.name or f"Смартфон-камера №{n}"), type="phone_ws",
            gauge_type=req.gauge_type, unit=req.unit))
    cam_id = cam["id"]
    token = service.streams.issue_phone_token(cam_id)
    if service.streams.phone_worker(cam_id) is None:
        service._start_camera(service.cameras[cam_id])
    url = config.capture_url(cam_id, token, service.lan_ip)
    return {"cam_id": cam_id, "token": token, "url": url, "qr_svg": _qr_svg(url),
            "camera": service.public_camera(service.cameras[cam_id])}


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
    worker.client_connected()
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
                if frame is not None:
                    worker.push_frame(frame)
                # подтверждение кадра (управление потоком) + текущее показание
                current = service.cameras.get(cam_id)
                await ws.send_json({"type": "ack", "ok": frame is not None, "status": worker.status,
                                    "unit": current["unit"] if current else cam["unit"],
                                    "reading": service.last.get(cam_id)})
                continue
            text = msg.get("text")
            if text:
                with contextlib.suppress(json.JSONDecodeError):
                    data = json.loads(text)
                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong", "t": data.get("t")})
            if cam_id not in service.cameras:
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        logger.warning("[%s] phone ws: %s", cam_id[:8], exc)
    finally:
        worker.client_disconnected()


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
        await ws.send_text(json.dumps({"type": "snapshot", "cameras": service.public_cameras()},
                                      ensure_ascii=False, default=_json_default))
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
async def api_ack(request: Request) -> dict[str, Any]:
    client = request.client.host if request.client else "?"
    ts = db.utcnow_iso()
    logger.info("Аварии квитированы оператором (%s)", client)
    service.hub.broadcast({"type": "ack", "ts": ts, "by": client})
    return {"ok": True, "ts": ts}


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
