"""
GaugeVision AI — менеджер видеопотоков (раздел 2 ТЗ).

• CaptureWorker: выделенный поток захвата для RTSP (CAP_FFMPEG,
  CAP_PROP_BUFFERSIZE=1 — Zero Latency Mode), HTTP/MJPEG и локальных
  устройств (device). Поток читает кадры непрерывно и хранит только самый
  свежий — анализ никогда не работает с «застоявшимся» буфером.
• PhoneWorker: смартфон-нода (phone_ws) — кадры приходят по WSS извне,
  воркер следит за таймаутом и статусом.
• FrameBroker: потокобезопасное хранилище последнего кадра каждой камеры,
  ленивое JPEG-сжатие, оверлей с результатами анализа для MJPEG-раздачи.
• Exponential Backoff Reconnection: 1с, 2с, 4с, 8с, максимум 15с.
• Статусы: online / reconnecting / offline; при обрыве сохраняются последний
  достоверный кадр и показание.

Любой сбой одной камеры изолирован внутри её воркера и не затрагивает
event-loop сервера и другие камеры.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import cv2
import numpy as np

from . import config

logger = logging.getLogger("gaugevision.streamer")

# RTSP поверх TCP (устойчивее UDP в цеховых Wi-Fi), таймаут сокета 5 с
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")

StatusCallback = Callable[[str, str], Awaitable[None]]


# ---------------------------------------------------------------------------
# Брокер кадров
# ---------------------------------------------------------------------------
def encode_jpeg(frame: np.ndarray, quality: int = config.SNAPSHOT_JPEG_QUALITY) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else None


@dataclass
class FrameSnapshot:
    frame: np.ndarray | None = None       # BGR
    ts: float = 0.0                       # time.monotonic() получения кадра
    frame_no: int = 0
    jpeg: bytes | None = None             # лениво сжатая копия сырого кадра
    overlay_jpeg: bytes | None = None     # кадр с разметкой конвейера зрения
    overlay_no: int = 0


class FrameBroker:
    """Последний кадр каждой камеры (запись из потоков захвата и WS-хендлеров)."""

    def __init__(self) -> None:
        self._snaps: dict[str, FrameSnapshot] = {}
        self._lock = threading.Lock()

    def publish(self, cam_id: str, frame: np.ndarray) -> None:
        with self._lock:
            snap = self._snaps.get(cam_id)
            if snap is None:
                snap = self._snaps[cam_id] = FrameSnapshot()
            snap.frame = frame
            snap.ts = time.monotonic()
            snap.frame_no += 1
            snap.jpeg = None

    def publish_overlay(self, cam_id: str, jpeg: bytes) -> None:
        with self._lock:
            snap = self._snaps.get(cam_id)
            if snap is None:
                snap = self._snaps[cam_id] = FrameSnapshot()
            snap.overlay_jpeg = jpeg
            snap.overlay_no += 1

    def latest_frame(self, cam_id: str) -> tuple[np.ndarray | None, int]:
        with self._lock:
            snap = self._snaps.get(cam_id)
            return (snap.frame, snap.frame_no) if snap else (None, 0)

    def latest_jpeg(self, cam_id: str, overlay: bool = True) -> tuple[bytes | None, int]:
        """JPEG последнего кадра: оверлей (если есть) либо сырой кадр."""
        with self._lock:
            snap = self._snaps.get(cam_id)
            if snap is None:
                return None, 0
            if overlay and snap.overlay_jpeg is not None:
                return snap.overlay_jpeg, snap.overlay_no
            if snap.jpeg is None and snap.frame is not None:
                frame = snap.frame
            else:
                return snap.jpeg, snap.frame_no
        jpeg = encode_jpeg(frame)
        with self._lock:
            snap = self._snaps.get(cam_id)
            if snap is not None and snap.frame is frame:
                snap.jpeg = jpeg
            return jpeg, snap.frame_no if snap else 0

    def age(self, cam_id: str) -> float:
        """Возраст последнего кадра в секундах (inf, если кадров не было)."""
        with self._lock:
            snap = self._snaps.get(cam_id)
            return (time.monotonic() - snap.ts) if snap and snap.ts else float("inf")

    def remove(self, cam_id: str) -> None:
        with self._lock:
            self._snaps.pop(cam_id, None)


# ---------------------------------------------------------------------------
# Базовый воркер
# ---------------------------------------------------------------------------
class BaseWorker(ABC):
    def __init__(self, cam_id: str, cam_type: str, source_url: str | None,
                 broker: FrameBroker, loop: asyncio.AbstractEventLoop,
                 on_status: StatusCallback | None) -> None:
        self.cam_id = cam_id
        self.cam_type = cam_type
        self.source_url = source_url
        self.broker = broker
        self.loop = loop
        self._on_status = on_status
        self.status = "offline"
        self.fail_count = 0
        self.last_error: str | None = None
        self.frames_total = 0
        self.fps = 0.0
        self._fps_t0 = time.monotonic()
        self._fps_n = 0
        self._stop = threading.Event()

    def _count_frame(self) -> None:
        self.frames_total += 1
        self._fps_n += 1
        now = time.monotonic()
        dt = now - self._fps_t0
        if dt >= 2.0:
            self.fps = round(self._fps_n / dt, 1)
            self._fps_t0, self._fps_n = now, 0

    def _set_status(self, status: str) -> None:
        """Потокобезопасная смена статуса с уведомлением event-loop."""
        if self.status == status:
            return
        self.status = status
        logger.info("[%s] статус: %s", self.cam_id[:8], status)
        if self._on_status is None:
            return
        try:
            if self._in_loop_thread():
                self.loop.create_task(self._safe_notify(status))
            else:
                asyncio.run_coroutine_threadsafe(self._safe_notify(status), self.loop)
        except RuntimeError:
            pass  # event-loop уже закрыт (остановка сервера)

    def _in_loop_thread(self) -> bool:
        try:
            return asyncio.get_running_loop() is self.loop
        except RuntimeError:
            return False

    async def _safe_notify(self, status: str) -> None:
        try:
            await self._on_status(self.cam_id, status)  # type: ignore[misc]
        except Exception as exc:
            logger.debug("on_status callback error: %s", exc)

    def info(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fps": self.fps,
            "frames_total": self.frames_total,
            "fail_count": self.fail_count,
            "last_error": self.last_error,
            "frame_age": None if self.broker.age(self.cam_id) == float("inf")
            else round(self.broker.age(self.cam_id), 2),
        }

    @abstractmethod
    def start(self) -> None:
        """Запуск захвата (поток OpenCV или сторож смартфон-ноды)."""

    def stop(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------------------
# RTSP / HTTP-MJPEG / device — поток захвата
# ---------------------------------------------------------------------------
class CaptureWorker(BaseWorker):
    """Выделенный поток OpenCV-захвата с exponential backoff reconnection."""

    READ_FAILS_BEFORE_RECONNECT = 5

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"capture-{self.cam_id[:8]}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 3.0) -> None:
        if self._thread:
            self._thread.join(timeout)

    # -- открытие источника ---------------------------------------------------
    def _open_capture(self) -> cv2.VideoCapture | None:
        url = (self.source_url or "").strip()
        timeouts: list[int] = []
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            timeouts = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000]
        cap: cv2.VideoCapture | None = None
        try:
            if self.cam_type == "device":
                # source_url — индекс локальной камеры ("0", "1", …) или путь устройства
                try:
                    src: int | str = int(url) if url else 0
                except ValueError:
                    src = url
                backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else (
                    cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY)
                cap = cv2.VideoCapture(src, backend)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(src, cv2.CAP_ANY)
            else:
                # rtsp:// и http(s):// MJPEG — бэкенд FFMPEG
                try:
                    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, timeouts) if timeouts \
                        else cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                except TypeError:
                    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if cap is not None and cap.isOpened():
                # Zero Latency Mode: буфер захвата ограничен 1 кадром
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, config.CAPTURE_BUFFERSIZE)
                except Exception:
                    pass
                return cap
            if cap is not None:
                cap.release()
            self.last_error = "источник не открывается"
        except Exception as exc:
            self.last_error = str(exc)
            logger.debug("open %s failed: %s", url, exc)
        return None

    def _wait_backoff(self, attempt: int) -> bool:
        """Пауза перед повторным подключением. True — если запрошена остановка."""
        seq = config.RECONNECT_BACKOFF
        delay = seq[min(attempt, len(seq) - 1)]
        logger.info("[%s] переподключение через %dс (попытка %d)",
                    self.cam_id[:8], delay, attempt + 1)
        return self._stop.wait(delay)

    # -- основной цикл --------------------------------------------------------
    def _run(self) -> None:
        attempt = 0
        self._set_status("reconnecting")
        while not self._stop.is_set():
            try:
                cap = self._open_capture()
            except Exception as exc:  # страховка: сбой одной камеры не роняет сервер
                cap = None
                self.last_error = str(exc)
            if cap is None:
                self.fail_count += 1
                self._set_status("offline" if self.fail_count >= config.OFFLINE_AFTER_FAILS
                                 else "reconnecting")
                if self._wait_backoff(attempt):
                    break
                attempt += 1
                continue

            logger.info("[%s] поток подключён: %s", self.cam_id[:8], self.source_url)
            got_frame = False
            read_fails = 0
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None or frame.size == 0:
                        read_fails += 1
                        if read_fails >= self.READ_FAILS_BEFORE_RECONNECT:
                            self.last_error = "поток оборвался"
                            break
                        time.sleep(0.1)
                        continue
                    read_fails = 0
                    if not got_frame:
                        got_frame = True
                        attempt = 0
                        self.fail_count = 0
                        self.last_error = None
                        self._set_status("online")
                    self.broker.publish(self.cam_id, frame)
                    self._count_frame()
                    if self.cam_type == "device":
                        time.sleep(0.01)  # локальная камера — не загружаем CPU впустую
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("[%s] ошибка чтения: %s", self.cam_id[:8], exc)
            finally:
                try:
                    cap.release()
                except Exception:
                    pass

            if self._stop.is_set():
                break
            self.fail_count += 1
            self._set_status("offline" if self.fail_count >= config.OFFLINE_AFTER_FAILS
                             else "reconnecting")
            if self._wait_backoff(attempt):
                break
            attempt += 1

        self._set_status("offline")


# ---------------------------------------------------------------------------
# Смартфон как Wi-Fi камера (phone_ws)
# ---------------------------------------------------------------------------
class PhoneWorker(BaseWorker):
    """Кадры приходят по WSS (push_frame); асинхронный сторож таймаутов."""

    OFFLINE_AFTER = 30.0  # с без кадров -> «Офлайн»

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._task: asyncio.Task | None = None
        self.connected_clients = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = self.loop.create_task(self._watchdog(), name=f"phone-{self.cam_id[:8]}")

    def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()

    def push_frame(self, frame: np.ndarray) -> None:
        self.broker.publish(self.cam_id, frame)
        self._count_frame()
        self.fail_count = 0
        self.last_error = None
        self._set_status("online")

    def client_connected(self) -> None:
        self.connected_clients += 1
        if self.status == "offline":
            self._set_status("reconnecting")

    def client_disconnected(self) -> None:
        self.connected_clients = max(0, self.connected_clients - 1)

    async def _watchdog(self) -> None:
        try:
            while not self._stop.is_set():
                await asyncio.sleep(1.0)
                age = self.broker.age(self.cam_id)
                if age <= config.PHONE_TIMEOUT:
                    continue
                if self.status == "online":
                    self.fail_count += 1
                    self.last_error = "нет кадров от смартфона"
                    self._set_status("reconnecting")
                elif self.status == "reconnecting" and age > self.OFFLINE_AFTER \
                        and self.connected_clients == 0:
                    self._set_status("offline")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("[%s] phone watchdog: %s", self.cam_id[:8], exc)


# ---------------------------------------------------------------------------
# Диспетчер воркеров
# ---------------------------------------------------------------------------
class StreamManager:
    """Реестр воркеров всех камер: запуск/остановка/перезапуск/токены смартфонов."""

    def __init__(self, broker: FrameBroker, on_status: StatusCallback | None = None) -> None:
        self.broker = broker
        self._on_status = on_status
        self._workers: dict[str, BaseWorker] = {}
        self._phone_tokens: dict[str, str] = {}   # cam_id -> token

    def start_camera(self, cam_id: str, cam_type: str, source_url: str | None) -> BaseWorker:
        self.stop_camera(cam_id, drop_frames=False)
        loop = asyncio.get_running_loop()
        cls = PhoneWorker if cam_type == "phone_ws" else CaptureWorker
        worker = cls(cam_id, cam_type, source_url, self.broker, loop, self._on_status)
        self._workers[cam_id] = worker
        worker.start()
        return worker

    def stop_camera(self, cam_id: str, drop_frames: bool = True) -> None:
        worker = self._workers.pop(cam_id, None)
        if worker:
            try:
                worker.stop()
            except Exception as exc:
                logger.debug("stop %s: %s", cam_id, exc)
        if drop_frames:
            self.broker.remove(cam_id)

    async def stop_all(self) -> None:
        workers = list(self._workers.values())
        for cam_id in list(self._workers):
            self.stop_camera(cam_id)
        loop = asyncio.get_running_loop()
        for w in workers:
            if isinstance(w, CaptureWorker):
                await loop.run_in_executor(None, w.join, 2.0)

    def worker(self, cam_id: str) -> BaseWorker | None:
        return self._workers.get(cam_id)

    def phone_worker(self, cam_id: str) -> PhoneWorker | None:
        w = self._workers.get(cam_id)
        return w if isinstance(w, PhoneWorker) else None

    def status_of(self, cam_id: str) -> str:
        w = self._workers.get(cam_id)
        return w.status if w else "offline"

    def info(self, cam_id: str) -> dict[str, Any]:
        w = self._workers.get(cam_id)
        return w.info() if w else {"status": "offline", "fps": 0.0, "frames_total": 0,
                                   "fail_count": 0, "last_error": None, "frame_age": None}

    # -- смартфон-нода: токены сессий ------------------------------------------
    def issue_phone_token(self, cam_id: str) -> str:
        token = secrets.token_urlsafe(24)
        self._phone_tokens[cam_id] = token
        return token

    def verify_phone_token(self, cam_id: str, token: str | None) -> bool:
        expected = self._phone_tokens.get(cam_id)
        return bool(expected and token) and secrets.compare_digest(expected, token or "")

    def revoke_phone_token(self, cam_id: str) -> None:
        self._phone_tokens.pop(cam_id, None)
