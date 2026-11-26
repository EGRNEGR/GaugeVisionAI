"""
GaugeVision AI — Трек №2: Архитектурная видеоаналитика (`stream_manager`).

Расширяет базовый захват потоков до отказоустойчивого Edge-узла:
  • изолированные воркеры для RTSP, HTTP-MJPEG, USB-камер, смартфонов WSS,
    локальных видеофайлов (video_file) и стендовых видеопотоков (demo_bench);
  • автоматическое переподключение с экспоненциальной задержкой (1–15 с);
  • честный контроль целостности и качества видеосигнала по реальным пикселям
    и реальным пропускам кадров (заморозка, низкая освещённость, блик/пересвет,
    пар/запотевание, частичное и полное перекрытие объектива, frame_drop_pct);
  • адаптивное управление частотой инференса (Adaptive FPS / Event-Driven) с
    лёгким межкадровым детектором изменений (`check_motion_wakeup`, ~8 Гц) в
    режиме `eco_idle` для перехвата кратковременных (< 1 с) скачков;
  • потокобезопасный многозахватный кольцевой буфер инцидента с сохранением
    pre/post-кадров на диск (персистентность после перезапуска).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from . import config
from .db import utcnow_iso
from .security import validate_video_file_path
from .streamer import (
    BaseWorker,
    CaptureWorker,
    FrameBroker,
    PhoneWorker,
    StatusCallback,
    StreamManager,
    encode_jpeg,
)

logger = logging.getLogger("gaugevision.stream_manager")


# ---------------------------------------------------------------------------
# Анализ качества видеосигнала и детекция деградации (только по реальным кадрам)
# ---------------------------------------------------------------------------
@dataclass
class SignalQualityReport:
    health_status: str = "OFFLINE"       # ONLINE | DEGRADED | OFFLINE
    quality_score: float = 0.0           # 0..100
    mean_luma: float = 0.0               # 0..255
    sharpness: float = 0.0               # дисперсия Лапласиана
    glare_pct: float = 0.0               # % пересвеченных пикселей
    frame_diff: float = 0.0              # MAD между соседними кадрами
    frozen: bool = False
    low_light: bool = False
    glare: bool = False
    steam_occlusion: bool = False
    partial_occlusion: bool = False
    frame_drop_pct: float = 0.0          # реально измеренный % пропусков чтения кадров
    packet_loss_pct: float | None = None  # None, если транспорт не отдаёт счётчик RTP-пакетов
    packet_loss_available: bool = False
    degradation_reasons: list[str] = field(default_factory=list)
    injected_fault: str | None = None
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "health_status": self.health_status,
            "quality_score": round(self.quality_score, 1),
            "mean_luma": round(self.mean_luma, 1),
            "sharpness": round(self.sharpness, 1),
            "glare_pct": round(self.glare_pct, 1),
            "frame_diff": round(self.frame_diff, 2),
            "frozen": self.frozen,
            "low_light": self.low_light,
            "glare": self.glare,
            "steam_occlusion": self.steam_occlusion,
            "partial_occlusion": self.partial_occlusion,
            "frame_drop_pct": round(self.frame_drop_pct, 1),
            "packet_loss_pct": None if self.packet_loss_pct is None else round(self.packet_loss_pct, 1),
            "packet_loss_available": self.packet_loss_available,
            "degradation_reasons": list(self.degradation_reasons),
            "injected_fault": self.injected_fault,
            "updated_at": self.updated_at,
        }


class FrameQualityAnalyzer:
    """
    Потокобезопасный детектор деградации видеосигнала для одного канала.
    Все флаги деградации вычисляются строго по реальным пикселям кадра и
    фактическим вызовам record_drop() — без обходов через injected_fault (DEF-11).
    """

    FREEZE_THRESHOLD_MAD = 0.05          # близко к побитовой идентичности (не срабатывает на малом шуме сенсора)
    FREEZE_CONSECUTIVE_LIMIT = 10
    LOW_LIGHT_LUMA = 36.0
    GLARE_PCT_LIMIT = 24.0
    STEAM_SHARPNESS_LIMIT = 22.0
    FRAME_DROP_WARN_PCT = 10.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prev_thumb: np.ndarray | None = None
        self._same_frames = 0
        # Скользящее окно последних 100 попыток чтения (1=успех, 0=пропуск кадра)
        self._read_window: deque[int] = deque(maxlen=100)
        self._dropped_total = 0
        self._last_report = SignalQualityReport()

    def record_drop(self) -> None:
        """Фиксирует реальный пропуск кадра (сбой cap.read() или пропуск в воркере)."""
        with self._lock:
            self._dropped_total += 1
            self._read_window.append(0)

    @staticmethod
    def _detect_partial_occlusion(gray: np.ndarray) -> bool:
        """
        Выявляет частичное перекрытие объектива (например, 35–60% кадра закрыто
        тёмным предметом / шторой / рукой), анализируя квадранты и половины кадра.
        """
        h, w = gray.shape[:2]
        hy, hx = h // 2, w // 2
        regions = (
            gray[:, :hx],        # левая половина
            gray[:, hx:],        # правая половина
            gray[:hy, :],        # верхняя половина
            gray[hy:, :],        # нижняя половина
            gray[:hy, :hx],      # Q1
            gray[:hy, hx:],      # Q2
            gray[hy:, :hx],      # Q3
            gray[hy:, hx:],      # Q4
        )
        means = [float(np.mean(r)) for r in regions]
        stds = [float(np.std(r)) for r in regions]
        dark_fracs = [float(np.mean(r < 18)) for r in regions]

        max_mean = max(means)
        # Если весь кадр равномерно тёмный, это low_light, а не частичное перекрытие
        if max_mean < 55.0:
            return False

        # Половина кадра почти полностью чёрная и без текстуры, при этом остальная часть освещена
        for idx in range(4):
            if dark_fracs[idx] >= 0.72 and stds[idx] < 10.0 and (max_mean - means[idx]) >= 45.0:
                return True

        # Два и более квадранта глухо перекрыты
        occluded_quads = sum(
            1 for idx in range(4, 8)
            if dark_fracs[idx] >= 0.75 and stds[idx] < 10.0 and (max_mean - means[idx]) >= 45.0
        )
        return occluded_quads >= 2

    def analyze(
        self,
        frame: np.ndarray,
        *,
        stream_online: bool = True,
        injected_fault: str | None = None,
        packet_loss_pct: float | None = None,
    ) -> SignalQualityReport:
        small = cv2.resize(frame, (160, 120), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        mean_luma = float(np.mean(gray))
        glare_pct = float(np.mean(gray >= 252) * 100.0)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        partial_occ = self._detect_partial_occlusion(gray)

        with self._lock:
            self._read_window.append(1)
            if self._prev_thumb is not None and self._prev_thumb.shape == gray.shape:
                mad = float(np.mean(np.abs(gray.astype(np.float32) - self._prev_thumb.astype(np.float32))))
            else:
                mad = 8.0
            self._prev_thumb = gray

            if mad < self.FREEZE_THRESHOLD_MAD:
                self._same_frames += 1
            else:
                self._same_frames = 0

            frozen = self._same_frames >= self.FREEZE_CONSECUTIVE_LIMIT
            low_light = mean_luma < self.LOW_LIGHT_LUMA
            glare = glare_pct > self.GLARE_PCT_LIMIT
            steam_occlusion = (sharpness < self.STEAM_SHARPNESS_LIMIT) and not low_light and not partial_occ

            win_n = len(self._read_window)
            drops_in_win = sum(1 for x in self._read_window if x == 0)
            frame_drop_pct = min(100.0, (drops_in_win / max(1, win_n)) * 100.0)
            pkt_avail = packet_loss_pct is not None and math.isfinite(float(packet_loss_pct))
            eff_pkt_loss = float(packet_loss_pct) if pkt_avail else None

            reasons: list[str] = []
            penalty = 0.0
            if not stream_online:
                reasons.append("Потеря видеопотока")
                penalty = 100.0
            else:
                if frozen:
                    reasons.append("Заморозка кадра (поток отдаёт идентичные кадры)")
                    penalty += 42.0
                if partial_occ:
                    reasons.append("Частичное перекрытие объектива (затемнение сектора кадра)")
                    penalty += 40.0
                if steam_occlusion:
                    reasons.append("Перекрытие объектива паром / задымлением")
                    penalty += 38.0
                if low_light:
                    reasons.append(f"Критически низкая освещённость ({mean_luma:.0f}/255)")
                    penalty += 32.0
                if glare:
                    reasons.append(f"Засветка / блик на стекле ({glare_pct:.0f}%)")
                    penalty += 18.0
                if frame_drop_pct >= self.FRAME_DROP_WARN_PCT:
                    reasons.append(f"Пропуск кадров видеопотока ({frame_drop_pct:.1f}%)")
                    penalty += min(35.0, frame_drop_pct)
                if eff_pkt_loss is not None and eff_pkt_loss >= self.FRAME_DROP_WARN_PCT:
                    reasons.append(f"Потеря сетевых пакетов RTP ({eff_pkt_loss:.1f}%)")
                    penalty += min(35.0, eff_pkt_loss)

            score = max(0.0, min(100.0, 100.0 - penalty))
            if not stream_online:
                health = "OFFLINE"
            elif reasons or score < 70.0:
                health = "DEGRADED"
            else:
                health = "ONLINE"

            rep = SignalQualityReport(
                health_status=health,
                quality_score=score,
                mean_luma=mean_luma,
                sharpness=sharpness,
                glare_pct=glare_pct,
                frame_diff=mad,
                frozen=frozen,
                low_light=low_light,
                glare=glare,
                steam_occlusion=steam_occlusion,
                partial_occlusion=partial_occ,
                frame_drop_pct=frame_drop_pct,
                packet_loss_pct=eff_pkt_loss,
                packet_loss_available=pkt_avail,
                degradation_reasons=reasons,
                injected_fault=injected_fault,
                updated_at=utcnow_iso(),
            )
            self._last_report = rep
            return rep

    def set_offline(self, reason: str = "Нет входного видеосигнала", injected_fault: str | None = None) -> SignalQualityReport:
        with self._lock:
            rep = SignalQualityReport(
                health_status="OFFLINE",
                quality_score=0.0,
                degradation_reasons=[reason],
                injected_fault=injected_fault,
                updated_at=utcnow_iso(),
            )
            self._last_report = rep
            return rep

    def latest(self) -> SignalQualityReport:
        with self._lock:
            return self._last_report


# ---------------------------------------------------------------------------
# Адаптивное управление частотой опроса (Adaptive FPS + Motion Pre-Trigger)
# ---------------------------------------------------------------------------
class AdaptiveFpsController:
    """
    В штатном стабильном режиме снижает частоту CV-инференса до ADAPTIVE_FPS_IDLE
    для экономии CPU/GPU Edge-узла.

    Для исключения пропуска кратковременных (< 1 с) переходных процессов в режиме
    `eco_idle` (DEF-12) встроен облегчённый детектор изменений `check_motion_wakeup()`
    (< 0,3 мс на кадр 96×72), который мгновенно переводит канал в `event_burst`
    до окончания 1-секундной паузы.
    """

    def __init__(
        self,
        idle_fps: float = config.ADAPTIVE_FPS_IDLE,
        active_fps: float = config.ADAPTIVE_FPS_ACTIVE,
        hold_seconds: float = config.ADAPTIVE_HOLD_SECONDS,
        motion_mad_threshold: float = config.ADAPTIVE_MOTION_MAD,
    ) -> None:
        self.idle_fps = max(0.3, float(idle_fps))
        self.active_fps = max(self.idle_fps, float(active_fps))
        self.hold_seconds = max(3.0, float(hold_seconds))
        self.motion_mad_threshold = max(0.5, float(motion_mad_threshold))
        self.mode: str = "eco_idle"
        self.target_fps: float = self.idle_fps
        self.reason: str = "Стабильный технологический режим"
        self._boost_until: float = 0.0
        self._prev_value: float | None = None
        self._prev_motion_thumb: np.ndarray | None = None
        self.triggers_total: int = 0
        self.motion_wakeups_total: int = 0
        self._last_latency_ms: float = 0.0

    def check_motion_wakeup(self, frame: np.ndarray) -> bool:
        """
        Лёгкий межкадровый претриггер (~0,2–0,4 мс): при резком изменении
        сцены/стрелки в режиме `eco_idle` мгновенно пробуждает `event_burst`.
        """
        if frame is None or frame.size == 0:
            return False
        small = cv2.resize(frame, (96, 72), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        prev = self._prev_motion_thumb
        self._prev_motion_thumb = gray
        if prev is None or prev.shape != gray.shape:
            return False
        mad = float(np.mean(np.abs(gray.astype(np.float32) - prev.astype(np.float32))))
        if mad >= self.motion_mad_threshold:
            now = time.monotonic()
            if self.mode != "event_burst":
                self.triggers_total += 1
            self.motion_wakeups_total += 1
            self.mode = "event_burst"
            self.target_fps = self.active_fps
            self.reason = f"Быстрое изменение в кадре (motion MAD={mad:.1f})"
            self._boost_until = now + self.hold_seconds
            return True
        return False

    def update(self, *, value: float | None, span: float, level: str | None,
               degraded: bool = False, process_ms: float | None = None) -> dict[str, Any]:
        now = time.monotonic()
        if process_ms is not None and math.isfinite(float(process_ms)):
            self._last_latency_ms = float(process_ms)

        trigger_reason: str | None = None
        if level in ("warning", "alert"):
            trigger_reason = f"Выход за уставку ({'АВАРИЯ' if level == 'alert' else 'ПРЕДУПР.'})"
        elif degraded:
            trigger_reason = "Деградация видеосигнала"
        elif value is not None and self._prev_value is not None and span > 1e-6:
            if math.isfinite(value) and math.isfinite(self._prev_value):
                jump_pct = abs(value - self._prev_value) / span * 100.0
                if jump_pct >= config.ADAPTIVE_DELTA_PCT:
                    trigger_reason = f"Скачок показания ({jump_pct:.1f}% шкалы)"

        if value is not None and math.isfinite(value):
            self._prev_value = value

        if trigger_reason:
            if self.mode != "event_burst":
                self.triggers_total += 1
            self.mode = "event_burst"
            self.target_fps = self.active_fps
            self.reason = trigger_reason
            self._boost_until = now + self.hold_seconds
        elif now < self._boost_until:
            self.mode = "event_burst"
            self.target_fps = self.active_fps
        else:
            self.mode = "eco_idle"
            self.target_fps = self.idle_fps
            self.reason = "Стабильный режим — экономия Edge-ресурсов"

        return self.info()

    @property
    def interval(self) -> float:
        return 1.0 / max(0.25, self.target_fps)

    def info(self) -> dict[str, Any]:
        savings = max(0.0, (1.0 - self.target_fps / max(0.1, self.active_fps)) * 100.0)
        return {
            "mode": self.mode,
            "mode_label": "ТРЕВОГА / ВЫСОКАЯ ЧАСТОТА" if self.mode == "event_burst" else "ЭКОНОМ / ШТАТНЫЙ",
            "target_fps": round(self.target_fps, 2),
            "idle_fps": round(self.idle_fps, 2),
            "active_fps": round(self.active_fps, 2),
            "reason": self.reason,
            "triggers_total": self.triggers_total,
            "motion_wakeups_total": self.motion_wakeups_total,
            "cpu_savings_pct": round(savings, 1),
            "inference_ms": round(self._last_latency_ms, 1),
        }


# ---------------------------------------------------------------------------
# Кольцевой буфер инцидентов (многозахватный + персистентность на диск, DEF-10)
# ---------------------------------------------------------------------------
class IncidentRingBuffer:
    """
    Потокобезопасный кольцевой буфер:
      • хранит последние `pre_len` кадров до инцидента;
      • поддерживает до `max_active` параллельных незавершённых захватов
        (второй инцидент НЕ перезаписывает первый!);
      • при завершении добора `post_len` кадров сохраняет архив на диск
        (если задан `storage_dir`) с ограничением числа клипов.
    """

    def __init__(
        self,
        pre_len: int = config.RING_BUFFER_PRE_FRAMES,
        post_len: int = config.RING_BUFFER_POST_FRAMES,
        *,
        max_archives: int = config.RING_BUFFER_MAX_CLIPS,
        max_active: int = 8,
        storage_dir: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._pre: deque[tuple[str, bytes]] = deque(maxlen=max(4, pre_len))
        self._post_len = max(2, post_len)
        self._max_active = max(1, max_active)
        self._max_archives = max(2, max_archives)
        self._active_captures: list[dict[str, Any]] = []
        self._archives: deque[dict[str, Any]] = deque(maxlen=self._max_archives)
        self._storage_dir = storage_dir
        self._persisted_count = 0
        if self._storage_dir is not None:
            self._load_persisted_index()

    def _load_persisted_index(self) -> None:
        if self._storage_dir is None or not self._storage_dir.is_dir():
            return
        meta_files = sorted(self._storage_dir.glob("clip_*.json"))[-self._max_archives:]
        for mf in meta_files:
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
                kf_path = self._storage_dir / str(meta.get("keyframe_file") or "")
                kf_bytes = kf_path.read_bytes() if kf_path.is_file() else b""
                self._archives.append({
                    "clip_id": meta.get("clip_id", mf.stem),
                    "triggered_at": meta.get("triggered_at"),
                    "completed_at": meta.get("completed_at"),
                    "reason": meta.get("reason", ""),
                    "level": meta.get("level", "alert"),
                    "value": meta.get("value"),
                    "pre": [(meta.get("triggered_at", ""), kf_bytes)] if kf_bytes else [],
                    "post": [],
                    "pre_count": int(meta.get("pre_count", 0)),
                    "post_count": int(meta.get("post_count", 0)),
                    "persisted_path": str(mf),
                })
                self._persisted_count += 1
            except Exception as exc:
                logger.debug("ring buffer load %s: %s", mf, exc)

    def _persist_clip(self, clip: dict[str, Any]) -> None:
        if self._storage_dir is None:
            return
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            cid = clip["clip_id"]
            clip_dir = self._storage_dir / cid
            clip_dir.mkdir(parents=True, exist_ok=True)
            pre_files: list[str] = []
            for idx, (_, raw) in enumerate(clip["pre"]):
                fn = f"pre_{idx:02d}.jpg"
                (clip_dir / fn).write_bytes(raw)
                pre_files.append(f"{cid}/{fn}")
            post_files: list[str] = []
            for idx, (_, raw) in enumerate(clip["post"]):
                fn = f"post_{idx:02d}.jpg"
                (clip_dir / fn).write_bytes(raw)
                post_files.append(f"{cid}/{fn}")
            keyframe_file = pre_files[-1] if pre_files else (post_files[0] if post_files else None)
            meta = {
                "clip_id": cid,
                "triggered_at": clip["triggered_at"],
                "completed_at": clip["completed_at"],
                "reason": clip["reason"],
                "level": clip["level"],
                "value": clip["value"],
                "pre_count": len(clip["pre"]),
                "post_count": len(clip["post"]),
                "keyframe_file": keyframe_file,
                "pre_files": pre_files,
                "post_files": post_files,
            }
            meta_path = self._storage_dir / f"{cid}.json"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            clip["persisted_path"] = str(meta_path)
            self._persisted_count += 1

            # Ограничение дискового архива на канал (FIFO старых клипов)
            existing = sorted(self._storage_dir.glob("clip_*.json"))
            while len(existing) > self._max_archives:
                oldest = existing.pop(0)
                old_dir = self._storage_dir / oldest.stem
                try:
                    oldest.unlink(missing_ok=True)
                    if old_dir.is_dir():
                        for child in old_dir.iterdir():
                            child.unlink(missing_ok=True)
                        old_dir.rmdir()
                except OSError:
                    pass
        except OSError as exc:
            logger.warning("Не удалось сохранить клип инцидента на диск: %s", exc)

    def push(self, jpeg: bytes, ts_iso: str | None = None) -> None:
        ts = ts_iso or utcnow_iso()
        completed: list[dict[str, Any]] = []
        with self._lock:
            self._pre.append((ts, jpeg))
            still_active: list[dict[str, Any]] = []
            for cap in self._active_captures:
                cap["post"].append((ts, jpeg))
                if len(cap["post"]) >= self._post_len:
                    cap["completed_at"] = ts
                    cap["pre_count"] = len(cap["pre"])
                    cap["post_count"] = len(cap["post"])
                    self._archives.append(cap)
                    completed.append(cap)
                else:
                    still_active.append(cap)
            self._active_captures = still_active
        for cap in completed:
            self._persist_clip(cap)

    def trigger(self, reason: str, level: str, value: float | None = None) -> dict[str, Any]:
        ts = utcnow_iso()
        clip_id = f"clip_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        with self._lock:
            clip = {
                "clip_id": clip_id,
                "triggered_at": ts,
                "reason": reason,
                "level": level,
                "value": value,
                "pre": list(self._pre),
                "post": [],
                "completed_at": None,
                "persisted_path": None,
            }
            if len(self._active_captures) >= self._max_active:
                # Сохраняем завершённую на текущий момент часть самого старого захвата, не теряя его
                evicted = self._active_captures.pop(0)
                evicted["completed_at"] = ts
                self._archives.append(evicted)
            self._active_captures.append(clip)
            return {
                "clip_id": clip_id,
                "triggered_at": ts,
                "pre_frames": len(clip["pre"]),
                "post_target": self._post_len,
                "active_captures": len(self._active_captures),
            }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_bytes = sum(len(b) for _, b in self._pre)
            for cap in self._active_captures:
                total_bytes += sum(len(b) for _, b in cap["pre"]) + sum(len(b) for _, b in cap["post"])
            for arch in self._archives:
                total_bytes += sum(len(b) for _, b in arch["pre"]) + sum(len(b) for _, b in arch["post"])
            return {
                "pre_buffered": len(self._pre),
                "pre_capacity": self._pre.maxlen,
                "post_target": self._post_len,
                "capturing_post": len(self._active_captures) > 0,
                "active_captures": len(self._active_captures),
                "archived_clips": len(self._archives),
                "persisted_to_disk": self._storage_dir is not None,
                "persisted_clips": self._persisted_count,
                "buffer_kb": round(total_bytes / 1024.0, 1),
            }

    def latest_keyframe(self) -> bytes | None:
        with self._lock:
            for cap in reversed(self._active_captures):
                if cap["pre"]:
                    return cap["pre"][-1][1]
            if self._archives and self._archives[-1]["pre"]:
                return self._archives[-1]["pre"][-1][1]
            if self._pre:
                return self._pre[-1][1]
            return None


# ---------------------------------------------------------------------------
# Вспомогательный рендер реалистичного манометра (стендовый поток и кадры ТЗ)
# ---------------------------------------------------------------------------
def apply_signal_fault(frame: np.ndarray, fault: str | None) -> np.ndarray:
    """Применяет контролируемую деградацию видеосигнала на уровне пикселей для проверки детектора."""
    if not fault or fault == "recover":
        return frame
    out = frame.copy()
    if fault == "steam":
        blurred = cv2.GaussianBlur(out, (35, 35), 14.0)
        fog = np.full_like(out, (212, 218, 222))
        out = cv2.addWeighted(blurred, 0.32, fog, 0.68, 0)
    elif fault == "low_light":
        out = np.clip(out.astype(np.float32) * 0.14, 0, 255).astype(np.uint8)
    elif fault == "glare":
        h, w = out.shape[:2]
        cv2.circle(out, (int(w * 0.52), int(h * 0.44)), int(min(w, h) * 0.34), (252, 252, 252), -1)
        out = cv2.GaussianBlur(out, (21, 21), 8.0)
    elif fault == "partial_occlusion":
        h, w = out.shape[:2]
        out[:, : w // 2] = (5, 5, 5)
    return out


def render_gauge_frame(
    *,
    code: str,
    name: str,
    unit: str,
    value: float | None,
    v_min: float,
    v_max: float,
    thresholds: dict[str, Any] | None = None,
    level: str = "normal",
    timestamp: str | None = None,
    annotate_cv: bool = False,
    confidence: float | None = None,
    is_synthetic: bool = True,
    width: int = 640,
    height: int = 480,
) -> np.ndarray:
    """
    Генерирует чёткий кадр промышленного стрелочного прибора (для стендового
    видеопотока OpenCV и иллюстративных кадров в дефектной ведомости / .docx).
    Никогда не подставляет фиктивное значение CONF (DEF-04).
    """
    img = np.full((height, width, 3), (24, 28, 32), np.uint8)
    cx, cy = width // 2, height // 2 + (8 if annotate_cv else 0)
    r = int(min(width, height) * (0.37 if annotate_cv else 0.41))

    cv2.circle(img, (cx, cy), r + 14, (64, 70, 78), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r + 14, (118, 126, 134), 2, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (224, 227, 230), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (40, 44, 50), 3, cv2.LINE_AA)

    span = (v_max - v_min) or 1.0
    theta_min = 135.0
    arc_span = 270.0

    def val_to_deg(v: float) -> float:
        frac = max(0.0, min(1.0, (v - v_min) / span))
        return (theta_min + frac * arc_span) % 360.0

    thr = thresholds or {}
    if annotate_cv:
        def draw_arc(v0: float, v1: float, color: tuple[int, int, int], thickness: int = 8) -> None:
            f0 = max(0.0, min(1.0, (v0 - v_min) / span))
            f1 = max(0.0, min(1.0, (v1 - v_min) / span))
            if f1 <= f0:
                return
            a0 = theta_min + f0 * arc_span
            a1 = theta_min + f1 * arc_span
            cv2.ellipse(img, (cx, cy), (r - 12, r - 12), 0.0, a0, a1, color, thickness, cv2.LINE_AA)

        draw_arc(v_min, v_max, (85, 176, 115), 7)
        if thr.get("l_warn") is not None:
            draw_arc(v_min, float(thr["l_warn"]), (58, 168, 231), 8)
        if thr.get("ll_alert") is not None:
            draw_arc(v_min, float(thr["ll_alert"]), (70, 68, 232), 9)
        if thr.get("h_warn") is not None:
            draw_arc(float(thr["h_warn"]), v_max, (58, 168, 231), 8)
        if thr.get("hh_alert") is not None:
            draw_arc(float(thr["hh_alert"]), v_max, (70, 68, 232), 9)

    for i in range(51):
        deg = theta_min + (i / 50.0) * arc_span
        rad = math.radians(deg)
        major = (i % 5 == 0)
        r0 = r - (24 if major else 13)
        r1 = r - 4
        p0 = (int(cx + r0 * math.cos(rad)), int(cy + r0 * math.sin(rad)))
        p1 = (int(cx + r1 * math.cos(rad)), int(cy + r1 * math.sin(rad)))
        cv2.line(img, p0, p1, (26, 30, 36), 3 if major else 1, cv2.LINE_AA)
        if major and (i % 10 == 0):
            tick_v = v_min + (i / 50.0) * span
            lbl = f"{tick_v:.0f}" if abs(span) >= 10 else f"{tick_v:.1f}"
            rt = r - 42
            tx = int(cx + rt * math.cos(rad)) - 12
            ty = int(cy + rt * math.sin(rad)) + 5
            cv2.putText(img, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (32, 36, 42), 1, cv2.LINE_AA)

    angle_deg: float | None = None
    if value is not None and math.isfinite(float(value)):
        angle_deg = val_to_deg(float(value))
        rad = math.radians(angle_deg)
        tip = (int(cx + (r - 28) * math.cos(rad)), int(cy + (r - 28) * math.sin(rad)))
        tail = (int(cx - 28 * math.cos(rad)), int(cy - 28 * math.sin(rad)))
        cv2.line(img, tail, tip, (18, 20, 24), 5, cv2.LINE_AA)
        if annotate_cv:
            ov_col = (70, 68, 240) if level == "alert" else ((58, 168, 231) if level == "warning" else (85, 196, 122))
            cv2.line(img, (cx, cy), tip, ov_col, 2, cv2.LINE_AA)
            cv2.circle(img, tip, 5, ov_col, -1, cv2.LINE_AA)

    cv2.circle(img, (cx, cy), 11, (26, 30, 36), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 5, (145, 152, 160), -1, cv2.LINE_AA)

    ascii_unit = (
        unit.replace("МПа", "MPa").replace("кПа", "kPa").replace("Па", "Pa")
        .replace("°C", "C").replace("т/ч", "t/h").replace("м³/ч", "m3/h")
        .replace("МВт", "MW").replace("кВ", "kV").replace("мм", "mm").replace("А", "A")
    )
    cv2.putText(img, ascii_unit, (cx - 20, cy + 44), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (55, 62, 70), 1, cv2.LINE_AA)

    if annotate_cv:
        cv2.rectangle(img, (cx - r - 18, cy - r - 18), (cx + r + 18, cy + r + 18), (85, 196, 122), 1, cv2.LINE_AA)
        cv2.rectangle(img, (0, 0), (width, 34), (15, 18, 21), -1)
        val_s = "N/A" if value is None else f"{float(value):.2f}"
        ang_s = "--" if angle_deg is None else f"{angle_deg:.1f} deg"
        lv_tag = "CRITICAL" if level == "alert" else ("WARNING" if level == "warning" else ("NO DATA" if value is None else "NORMAL"))
        lv_col = (95, 90, 240) if level == "alert" else ((58, 168, 231) if level == "warning" else ((145, 152, 160) if value is None else (115, 176, 82)))
        ascii_code = code.encode("ascii", "ignore").decode("ascii") or "GAUGE"
        ts_short = (timestamp or utcnow_iso())[:19].replace("T", " ")
        cv2.putText(img, f"GaugeVision | {ascii_code} | {val_s} {ascii_unit} | theta={ang_s}",
                    (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (225, 229, 233), 1, cv2.LINE_AA)
        cv2.putText(img, lv_tag, (width - 106, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, lv_col, 2, cv2.LINE_AA)
        cv2.rectangle(img, (0, height - 24), (width, height), (15, 18, 21), -1)
        if is_synthetic:
            footer_txt = f"UTC {ts_short} | SYNTHETIC / NO LIVE SNAPSHOT | EDGE={config.EDGE_NODE_ID}"
        else:
            conf_s = f"CONF={confidence:.2f}" if (confidence is not None and math.isfinite(confidence)) else "CONF=N/A"
            footer_txt = f"UTC {ts_short} | LIVE CV | {conf_s} | EDGE={config.EDGE_NODE_ID}"
        cv2.putText(img, footer_txt,
                    (12, height - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (169, 178, 186), 1, cv2.LINE_AA)
    return img


# ---------------------------------------------------------------------------
# Расширенный воркер для видеофайлов (video_file) и стендового потока
# ---------------------------------------------------------------------------
class VideoFileWorker(BaseWorker):
    """Захват локального видеофайла по кругу с поддержкой ограничения каталога allowed_root."""

    def __init__(
        self,
        *args: Any,
        allowed_root: Path | None = None,
        on_drop: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._thread: threading.Thread | None = None
        self._allowed_root = allowed_root
        self._on_drop = on_drop

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"vfile-{self.cam_id[:8]}", daemon=True)
        self._thread.start()

    def join(self, timeout: float = 2.0) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _resolve_path(self) -> Path | None:
        raw = (self.source_url or "").strip()
        if not raw:
            return None
        if self._allowed_root is not None:
            try:
                rel = validate_video_file_path(raw, allowed_root=self._allowed_root)
                return (self._allowed_root.resolve() / rel).resolve()
            except ValueError as exc:
                self.last_error = str(exc)
                return None
        p = Path(raw)
        if not p.is_absolute():
            p = (config.BASE_DIR / p).resolve()
        return p

    def _run(self) -> None:
        attempt = 0
        self._set_status("reconnecting")
        while not self._stop.is_set():
            path = self._resolve_path()
            if path is None or not path.is_file():
                self.fail_count += 1
                self.last_error = self.last_error or f"Файл не найден: {self.source_url}"
                self._set_status("offline" if self.fail_count >= 3 else "reconnecting")
                if self._stop.wait(config.RECONNECT_BACKOFF[min(attempt, len(config.RECONNECT_BACKOFF) - 1)]):
                    break
                attempt += 1
                continue

            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                self.fail_count += 1
                self.last_error = "Не удалось декодировать видеофайл"
                self._set_status("offline")
                if self._stop.wait(2.0):
                    break
                continue

            fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
            fps = max(2.0, min(30.0, float(fps)))
            period = 1.0 / fps
            self.fail_count = 0
            self.last_error = None
            attempt = 0
            self._set_status("online")
            try:
                while not self._stop.is_set():
                    t0 = time.monotonic()
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, frame = cap.read()
                        if not ok or frame is None:
                            if self._on_drop is not None:
                                self._on_drop()
                            break
                    self.broker.publish(self.cam_id, frame)
                    self._count_frame()
                    dt = time.monotonic() - t0
                    if dt < period:
                        self._stop.wait(period - dt)
            finally:
                cap.release()
        self._set_status("offline")


class BenchSyntheticWorker(BaseWorker):
    """
    Встроенный стендовый видеогенератор OpenCV: отдаёт живые кадры стрелочного
    манометра в FrameBroker, которые проходят реальный CV-конвейер GaugePipeline.
    """

    def __init__(
        self,
        cam_id: str,
        spec: dict[str, Any],
        value_fn: Callable[[], float],
        broker: FrameBroker,
        loop: asyncio.AbstractEventLoop,
        on_status: StatusCallback | None,
        fault_fn: Callable[[str], str | None],
        on_drop: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(cam_id, "video_file", "bench://synthetic-gauge", broker, loop, on_status)
        self._spec = spec
        self._value_fn = value_fn
        self._fault_fn = fault_fn
        self._on_drop = on_drop
        self._thread: threading.Thread | None = None
        self._frozen_frame: np.ndarray | None = None
        self._tick_counter = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"bench-{self.cam_id[:8]}", daemon=True)
        self._thread.start()

    def join(self, timeout: float = 2.0) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        self._set_status("online")
        cal = self._spec.get("calibration") or {}
        v_min = float(cal.get("v_min", 0.0))
        v_max = float(cal.get("v_max", 16.0))
        while not self._stop.is_set():
            t0 = time.monotonic()
            self._tick_counter += 1
            fault = self._fault_fn(self.cam_id)
            if fault == "offline":
                self._set_status("offline")
                self.last_error = "Симуляция обрыва видеоканала"
                self._stop.wait(0.5)
                continue
            if self.status != "online":
                self.last_error = None
                self._set_status("online")
            if fault == "packet_loss" and (self._tick_counter % 3 == 1):
                if self._on_drop is not None:
                    self._on_drop()
                self._stop.wait(0.18)
                continue
            if fault == "freeze" and self._frozen_frame is not None:
                frame = self._frozen_frame
            else:
                val = self._value_fn()
                raw = render_gauge_frame(
                    code=self._spec.get("code", "BENCH"),
                    name=self._spec.get("name", "Стенд"),
                    unit=self._spec.get("unit", "МПа"),
                    value=val,
                    v_min=v_min,
                    v_max=v_max,
                    thresholds=self._spec.get("thresholds"),
                    annotate_cv=False,
                )
                noise = np.random.randint(-3, 4, raw.shape, dtype=np.int16)
                raw = np.clip(raw.astype(np.int16) + noise, 0, 255).astype(np.uint8)
                frame = apply_signal_fault(raw, fault)
                if fault == "freeze":
                    self._frozen_frame = frame.copy()
                else:
                    self._frozen_frame = None
            self.broker.publish(self.cam_id, frame)
            self._count_frame()
            dt = time.monotonic() - t0
            self._stop.wait(max(0.05, 0.16 - dt))  # ~6 FPS входного потока
        self._set_status("offline")


# ---------------------------------------------------------------------------
# Расширенный менеджер видеоисточников (EdgeStreamManager)
# ---------------------------------------------------------------------------
class EdgeStreamManager(StreamManager):
    """
    Управляет всеми видеоворкерами (RTSP, HTTP-MJPEG, USB, Phone WSS, VideoFile,
    BenchSynthetic), анализаторами качества, Adaptive FPS и персистентными кольцевыми буферами.
    """

    def __init__(self, broker: FrameBroker, on_status: StatusCallback | None = None,
                 *, persist_incidents: bool = True) -> None:
        super().__init__(broker, on_status=on_status)
        self._quality: dict[str, FrameQualityAnalyzer] = {}
        self._adaptive: dict[str, AdaptiveFpsController] = {}
        self._rings: dict[str, IncidentRingBuffer] = {}
        self._faults: dict[str, str | None] = {}
        self._persist_incidents = persist_incidents

    def _ring_storage_dir(self, cam_id: str) -> Path | None:
        if not self._persist_incidents:
            return None
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in cam_id)[:48] or "channel"
        return config.get_incidents_dir() / safe

    def start_camera(
        self,
        cam_id: str,
        cam_type: str,
        source_url: str | None,
        *,
        allowed_video_root: Path | None = None,
    ) -> BaseWorker:
        qa = self._quality.setdefault(cam_id, FrameQualityAnalyzer())
        self._adaptive.setdefault(cam_id, AdaptiveFpsController())
        self._rings.setdefault(cam_id, IncidentRingBuffer(storage_dir=self._ring_storage_dir(cam_id)))
        self.stop_camera(cam_id, drop_frames=False)
        loop = asyncio.get_running_loop()
        if cam_type == "video_file":
            worker: BaseWorker = VideoFileWorker(
                cam_id, cam_type, source_url, self.broker, loop, self._on_status,
                allowed_root=allowed_video_root,
                on_drop=qa.record_drop,
            )
        elif cam_type == "phone_ws":
            worker = PhoneWorker(cam_id, cam_type, source_url, self.broker, loop, self._on_status)
        else:
            worker = CaptureWorker(
                cam_id, cam_type, source_url, self.broker, loop, self._on_status,
                on_drop=qa.record_drop,
            )
        self._workers[cam_id] = worker
        worker.start()
        return worker

    def start_bench_stream(self, cam_id: str, spec: dict[str, Any], value_fn: Callable[[], float]) -> BaseWorker:
        qa = self._quality.setdefault(cam_id, FrameQualityAnalyzer())
        self._adaptive.setdefault(cam_id, AdaptiveFpsController())
        self._rings.setdefault(cam_id, IncidentRingBuffer(storage_dir=self._ring_storage_dir(cam_id)))
        self.stop_camera(cam_id, drop_frames=False)
        loop = asyncio.get_running_loop()
        worker = BenchSyntheticWorker(
            cam_id, spec, value_fn, self.broker, loop, self._on_status, self.get_fault,
            on_drop=qa.record_drop,
        )
        self._workers[cam_id] = worker
        worker.start()
        return worker

    def stop_camera(self, cam_id: str, drop_frames: bool = True) -> None:
        super().stop_camera(cam_id, drop_frames=drop_frames)
        if drop_frames:
            self._quality.pop(cam_id, None)
            self._adaptive.pop(cam_id, None)
            self._rings.pop(cam_id, None)
            self._faults.pop(cam_id, None)

    async def stop_all(self) -> None:
        workers = list(self._workers.values())
        await super().stop_all()
        loop = asyncio.get_running_loop()
        for w in workers:
            if isinstance(w, (VideoFileWorker, BenchSyntheticWorker)):
                await loop.run_in_executor(None, w.join, 2.0)

    def set_fault(self, cam_id: str, mode: str | None) -> str | None:
        if not mode or mode in ("none", "recover", "normal"):
            self._faults.pop(cam_id, None)
            return None
        allowed = {"freeze", "steam", "low_light", "glare", "packet_loss", "offline", "partial_occlusion"}
        if mode not in allowed:
            raise ValueError(f"Неизвестный режим деградации: {mode}")
        self._faults[cam_id] = mode
        if mode == "offline":
            qa = self._quality.setdefault(cam_id, FrameQualityAnalyzer())
            qa.set_offline("Симуляция обрыва канала оператором", injected_fault="offline")
        return mode

    def get_fault(self, cam_id: str) -> str | None:
        return self._faults.get(cam_id)

    def quality_analyzer(self, cam_id: str) -> FrameQualityAnalyzer:
        return self._quality.setdefault(cam_id, FrameQualityAnalyzer())

    def adaptive_controller(self, cam_id: str) -> AdaptiveFpsController:
        return self._adaptive.setdefault(cam_id, AdaptiveFpsController())

    def ring_buffer(self, cam_id: str) -> IncidentRingBuffer:
        return self._rings.setdefault(cam_id, IncidentRingBuffer(storage_dir=self._ring_storage_dir(cam_id)))

    def channel_telemetry(self, cam_id: str) -> dict[str, Any]:
        base = self.info(cam_id)
        qa = self._quality.get(cam_id)
        ad = self._adaptive.get(cam_id)
        rb = self._rings.get(cam_id)
        qrep = qa.latest().to_dict() if qa else SignalQualityReport().to_dict()
        if base.get("status") != "online" and qrep["health_status"] != "OFFLINE":
            qrep["health_status"] = "OFFLINE"
        return {
            **base,
            "quality": qrep,
            "adaptive": ad.info() if ad else AdaptiveFpsController().info(),
            "ring_buffer": rb.stats() if rb else IncidentRingBuffer().stats(),
            "injected_fault": self._faults.get(cam_id),
        }
