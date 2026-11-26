"""
Реальный непрерывный 60-минутный CPU soak-тест GaugeVision AI (3600 секунд, строго CPU-only).

Сценарий нагрузки:
  • 4 одновременных канала CV-обработки (GaugePipeline) с Adaptive FPS и motion wakeup;
  • IncidentRingBuffer с записью на диск и ротацией клипов;
  • StoreAndForwardBuffer (SQLite WAL) с циклическими обрывами связи каждые 5 мин
    (2 мин буферизация -> восстановление -> досылка в локальный MQTT 3.1.1 QoS 1 брокер);
  • DispatchAnalyzer (непрерывный расчёт dV/dt, Health Score, разделение optical/equipment);
  • Ежеминутный снимок метрик (RSS MB, потоки, глубина S&F pending, общее число инференсов,
    p50/p95 латентность CV, event-loop lag, ошибки) с сохранением контрольных точек в JSON.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import math
import os
import statistics
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\Hakatons\GaugeVisionAIDesign DashBoard")
sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

DURATION_SECONDS = int(os.environ.get("SOAK_DURATION_SECONDS", "3600"))
SAMPLE_INTERVAL_SECONDS = int(os.environ.get("SOAK_SAMPLE_INTERVAL", "60"))
OUT_PATH = Path(os.environ.get("SOAK_OUT", str(Path(tempfile.gettempdir()) / "soak_60min_results.json")))

_TMP = Path(tempfile.mkdtemp(prefix="gv_soak_60m_"))
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app import config, vision  # noqa: E402
from app.dispatch_analyzer import DispatchAnalyzer  # noqa: E402
from app.scada_gateway import MqttAsyncAdapter, ScadaGateway  # noqa: E402
from app.store_forward import StoreAndForwardBuffer  # noqa: E402
from app.stream_manager import AdaptiveFpsController, FrameQualityAnalyzer, IncidentRingBuffer  # noqa: E402


def rss_mb() -> float:
    class PMC(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    h = k32.GetCurrentProcess()
    if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
        return round(pmc.WorkingSetSize / (1024.0 * 1024.0), 2)
    return 0.0


def render_dial(val: float, size: int = 480) -> np.ndarray:
    img = np.full((size, size, 3), (30, 34, 38), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    r = int(size * 0.40)
    cv2.circle(img, (cx, cy), r + 14, (88, 94, 102), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (244, 245, 242), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (55, 60, 65), 2, cv2.LINE_AA)
    frac = max(0.0, min(1.0, val / 16.0))
    ang = (135.0 + frac * 270.0) % 360.0
    for i in range(33):
        ar = math.radians((135.0 + (i / 32.0) * 270.0) % 360.0)
        c, s = math.cos(ar), math.sin(ar)
        r0 = r - (20 if i % 4 == 0 else 12)
        cv2.line(img, (int(cx + c * r0), int(cy + s * r0)), (int(cx + c * (r - 6)), int(cy + s * (r - 6))),
                 (30, 32, 35), 2 if i % 4 == 0 else 1, cv2.LINE_AA)
    ar = math.radians(ang)
    c, s = math.cos(ar), math.sin(ar)
    nc, ns = -s, c
    tip = (cx + c * (r - 14), cy + s * (r - 14))
    tail = (cx - c * 24, cy - s * 24)
    pts = np.array([
        [tip[0], tip[1]], [cx + nc * 4, cy + ns * 4],
        [tail[0] + nc * 5, tail[1] + ns * 5], [tail[0] - nc * 5, tail[1] - ns * 5],
        [cx - nc * 4, cy - ns * 4],
    ], dtype=np.int32)
    cv2.fillConvexPoly(img, pts, (18, 20, 24), cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 9, (25, 28, 32), -1, cv2.LINE_AA)
    return img


class SoakMqttBroker:
    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.writers: list[asyncio.StreamWriter] = []
        self.received_count: int = 0
        self.port: int = 0

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        for w in list(self.writers):
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        self.writers.clear()
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), timeout=2.0)
            except Exception:
                pass
            self.server = None

    async def _read_rem(self, reader: asyncio.StreamReader) -> int:
        mult, val = 1, 0
        for _ in range(4):
            b = (await reader.readexactly(1))[0]
            val += (b & 0x7F) * mult
            if (b & 0x80) == 0:
                return val
            mult *= 128
        return val

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        try:
            while True:
                hdr = await reader.readexactly(1)
                ptype = hdr[0] & 0xF0
                flags = hdr[0] & 0x0F
                rem = await self._read_rem(reader)
                body = await reader.readexactly(rem) if rem else b""
                if ptype == 0x10:
                    writer.write(b"\x20\x02\x00\x00")
                    await writer.drain()
                elif ptype == 0x30:
                    qos = (flags >> 1) & 0x03
                    self.received_count += 1
                    if qos == 1:
                        t_len = struct.unpack(">H", body[0:2])[0]
                        pid = struct.unpack(">H", body[2 + t_len:4 + t_len])[0]
                        writer.write(struct.pack("!BBH", 0x40, 2, pid))
                        await writer.drain()
                elif ptype == 0xC0:
                    writer.write(b"\xD0\x00")
                    await writer.drain()
                elif ptype == 0xE0:
                    break
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if writer in self.writers:
                self.writers.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def run_soak() -> None:
    broker = SoakMqttBroker()
    port = await broker.start()

    config.MQTT_ENABLED = True
    config.MQTT_HOST = "127.0.0.1"
    config.MQTT_PORT = port
    config.MQTT_QOS = 1
    config.MQTT_USERNAME = ""
    config.MQTT_PASSWORD = ""
    config.SF_BATCH_DELAY_S = 0.0
    config.SF_MAX_QUEUE_ROWS = 5000

    sf = StoreAndForwardBuffer(db_path=_TMP / "soak_sf.db")
    await sf.init()
    gw = ScadaGateway()
    gw.mqtt = MqttAsyncAdapter()
    sf.configure(deliver_cb=gw.deliver_batch)

    cal = {"v_min": 0.0, "v_max": 16.0, "theta_min": 135.0, "theta_max": 45.0, "direction": "cw"}
    thr = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}

    # Предгенерируем набор эталонных кадров (экономим CPU на рендеринге, нагружая именно CV-конвейер)
    frame_bank = [render_dial(11.0 + i * 0.25) for i in range(21)]  # 11.0 .. 16.0 МПа
    jpeg_bank = [cv2.imencode(".jpg", f, [int(cv2.IMWRITE_JPEG_QUALITY), 75])[1].tobytes() for f in frame_bank]

    pipes = [vision.GaugePipeline(f"soak-ch-{i}") for i in range(4)]
    fqas = [FrameQualityAnalyzer() for _ in range(4)]
    afcs = [AdaptiveFpsController(idle_fps=1.0, active_fps=6.0) for _ in range(4)]
    rbs = [IncidentRingBuffer(pre_len=6, post_len=4, max_archives=8, storage_dir=_TMP / f"inc_{i}") for i in range(4)]
    analyzer = DispatchAnalyzer()

    # Прогрев
    for i, p in enumerate(pipes):
        p.process(frame_bank[4], cal, thr, "МПа", with_overlay=True)

    started_at = time.time()
    start_mono = time.monotonic()
    next_sample_mono = start_mono + SAMPLE_INTERVAL_SECONDS
    rss_start = rss_mb()

    total_inferences = 0
    valid_inferences = 0
    errors_total = 0
    outage_cycles = 0
    window_lats: list[float] = []
    window_lags: list[float] = []
    samples: list[dict[str, Any]] = []
    step = 0
    last_outage_state = False

    def flush_checkpoint(final: bool = False) -> None:
        elapsed = round(time.monotonic() - start_mono, 1)
        rss_vals = [s["rss_mb"] for s in samples] or [rss_start]
        payload = {
            "status": "completed" if final else "running",
            "device": "cpu",
            "target_duration_s": DURATION_SECONDS,
            "elapsed_s": elapsed,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "channels": 4,
            "rss_start_mb": rss_start,
            "rss_end_mb": rss_mb(),
            "rss_max_mb": max(rss_vals),
            "rss_delta_mb": round(rss_mb() - rss_start, 2),
            "total_inferences": total_inferences,
            "valid_inferences": valid_inferences,
            "errors_total": errors_total,
            "outage_cycles_completed": outage_cycles,
            "mqtt_broker_received": broker.received_count,
            "samples_count": len(samples),
            "samples": samples,
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Начальный сэмпл t=0
    samples.append({
        "minute": 0,
        "elapsed_s": 0.0,
        "rss_mb": rss_start,
        "threads": threading.active_count(),
        "inferences_total": 0,
        "sf_pending": 0,
        "sf_delivered_total": 0,
        "mqtt_received": 0,
        "cv_p50_ms": 0.0,
        "cv_p95_ms": 0.0,
        "loop_lag_p95_ms": 0.0,
        "errors_total": 0,
    })
    flush_checkpoint(final=False)
    print(f"[SOAK START] target={DURATION_SECONDS}s rss_start={rss_start}MB out={OUT_PATH}", flush=True)

    try:
        while True:
            now_m = time.monotonic()
            elapsed = now_m - start_mono
            if elapsed >= DURATION_SECONDS:
                break

            # Цикл обрыва связи: 300с период, из них 60с буферизация, 240с штатная доставка
            in_outage = (int(elapsed) % 300) >= 240
            if in_outage != last_outage_state:
                await sf.set_outage(in_outage, "soak_periodic_outage" if in_outage else "soak_recovered")
                if not in_outage:
                    await sf.flush_pending(max_batches=40)
                    outage_cycles += 1
                last_outage_state = in_outage

            # Выбираем 1 канал за итерацию (round-robin с паузой, чтобы 4 канала держали реалистичный ритм ~2 FPS суммарно и не перегревали CPU)
            ch = step % 4
            # Периодический всплеск уставки для проверки Adaptive FPS + Ring Buffer
            is_spike = (step % 45 == ch)
            f_idx = 19 if is_spike else (4 + ((step + ch * 3) % 8))
            frame = frame_bank[f_idx]

            try:
                t_loop0 = time.perf_counter()
                await asyncio.sleep(0.05)
                lag_ms = max(0.0, (time.perf_counter() - t_loop0 - 0.05) * 1000.0)
                window_lags.append(lag_ms)

                # Проверка движения + CV-обработка в потоке (как в боевом event-loop)
                afcs[ch].check_motion_wakeup(frame)
                fqas[ch].analyze(frame)
                rbs[ch].push(jpeg_bank[f_idx])

                t_cv0 = time.perf_counter()
                reading = await asyncio.to_thread(pipes[ch].process, frame, cal, thr, "МПа", True)
                cv_ms = (time.perf_counter() - t_cv0) * 1000.0
                window_lats.append(cv_ms)
                total_inferences += 1
                if reading.valid:
                    valid_inferences += 1

                afcs[ch].update(value=reading.value, span=16.0, level=reading.status_level, degraded=not reading.valid, process_ms=cv_ms)
                if reading.status_level == "alert" and step % 45 == ch:
                    rbs[ch].trigger(f"soak-{step}-ch-{ch}", "alert", reading.value)

                # Запись в Store-and-Forward + MQTT QoS 1
                await sf.enqueue(
                    channel_id=f"soak-ch-{ch}",
                    payload_type="alarm" if reading.status_level == "alert" else "telemetry",
                    payload={"value": reading.value, "level": reading.status_level, "step": step},
                    severity=reading.status_level,
                )

                # Каждые 8 шагов обновляем DispatchAnalyzer
                if step % 8 == 0:
                    insts = [{
                        "id": f"soak-ch-{i}", "code": f"S-{i}", "name": f"Soak {i}", "short_name": f"Soak {i}",
                        "group": "Стенд", "unit": "МПа", "gauge_type": "pressure", "decimals": 2, "source_kind": "live",
                        "calibration": cal, "thresholds": thr,
                        "reading": {"valid": True, "value": reading.value or 12.0, "level": reading.status_level},
                    } for i in range(4)]
                    analyzer.overview(insts, events=[])
            except Exception as exc:
                errors_total += 1
                print(f"[SOAK ERR step={step}] {type(exc).__name__}: {exc}", flush=True)

            step += 1

            # Небольшой троттлинг (~150 мс цикл -> ~6.5 инференсов/с в сумме на 4 канала)
            await asyncio.sleep(0.10)

            now_m = time.monotonic()
            if now_m >= next_sample_mono:
                sf_st = await sf.stats()
                s_lat = sorted(window_lats) or [0.0]
                s_lag = sorted(window_lags) or [0.0]
                minute_idx = len(samples)
                cur_rss = rss_mb()
                snap = {
                    "minute": minute_idx,
                    "elapsed_s": round(now_m - start_mono, 1),
                    "rss_mb": cur_rss,
                    "threads": threading.active_count(),
                    "inferences_total": total_inferences,
                    "sf_pending": sf_st["pending_count"],
                    "sf_delivered_total": sf_st["delivered_total"],
                    "mqtt_received": broker.received_count,
                    "cv_p50_ms": round(s_lat[int(len(s_lat) * 0.50)], 2),
                    "cv_p95_ms": round(s_lat[min(len(s_lat) - 1, int(len(s_lat) * 0.95))], 2),
                    "loop_lag_p95_ms": round(s_lag[min(len(s_lag) - 1, int(len(s_lag) * 0.95))], 2),
                    "errors_total": errors_total,
                }
                samples.append(snap)
                window_lats.clear()
                window_lags.clear()
                flush_checkpoint(final=False)
                print(
                    f"[SOAK min={minute_idx:02d}] rss={cur_rss}MB thr={snap['threads']} "
                    f"inf={total_inferences} pend={snap['sf_pending']} mqtt={broker.received_count} "
                    f"cv_p95={snap['cv_p95_ms']}ms lag_p95={snap['loop_lag_p95_ms']}ms err={errors_total}",
                    flush=True,
                )
                next_sample_mono += SAMPLE_INTERVAL_SECONDS

        # Финальная досылка если тест закончился внутри окна обрыва
        if sf.outage_active:
            await sf.set_outage(False, "soak_final_flush")
        await sf.flush_pending(max_batches=80)
        flush_checkpoint(final=True)
        print(f"[SOAK DONE] elapsed={round(time.monotonic()-start_mono,1)}s inf={total_inferences} rss_end={rss_mb()}MB err={errors_total}", flush=True)
    finally:
        await sf.close()
        await gw.mqtt.close()
        await broker.stop()


if __name__ == "__main__":
    asyncio.run(run_soak())
