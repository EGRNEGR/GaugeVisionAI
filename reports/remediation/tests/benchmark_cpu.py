"""
Пост-ремедиационный нагрузочный и CV-бенчмарк GaugeVision AI (строго CPU-only):
  1. CV-регрессия (27 чистых прогонов CW/CCW/neg + tilt + glare + blank + 44% partial occlusion).
  2. Масштабирование многоканальной обработки: 1 / 2 / 4 / 8 каналов на CPU (FPS, p50/p95/p99, RSS, event-loop lag).
  3. Сравнение энергоэффективности Adaptive FPS (eco_idle vs incident_burst + motion wakeup).
  4. Пропускная способность Store-and-Forward (SQLite WAL drain 500 записей).
  5. Время генерации .md и .docx.

Перенесён из временного каталога Antigravity (benchmark_load_after.py) без изменения методики;
путь к репозиторию вычисляется от расположения файла. Запуск:
  BENCH_OUT=reports/remediation/evidence/benchmark/benchmark_cpu.json python reports/remediation/tests/benchmark_cpu.py
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import math
import os
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
_TMP = Path(tempfile.mkdtemp(prefix="gv_bench_after_"))
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app import config, vision  # noqa: E402
from app.dispatch_analyzer import DispatchAnalyzer  # noqa: E402
from app.spec_generator import generate_spec_bundle, render_spec_docx  # noqa: E402
from app.store_forward import StoreAndForwardBuffer  # noqa: E402
from app.stream_manager import AdaptiveFpsController  # noqa: E402


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


def render_dial(val: float, v_min: float = 0.0, v_max: float = 16.0,
                th_min: float = 135.0, th_max: float = 45.0,
                direction: str = "cw", size: int = 640) -> np.ndarray:
    img = np.full((size, size, 3), (30, 34, 38), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    r = int(size * 0.40)
    cv2.circle(img, (cx, cy), r + 18, (88, 94, 102), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (244, 245, 242), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (55, 60, 65), 2, cv2.LINE_AA)
    span = (th_max - th_min) % 360.0 if direction == "cw" else (th_min - th_max) % 360.0
    if span == 0:
        span = 360.0
    frac = (val - v_min) / (v_max - v_min)
    ang = (th_min + frac * span) % 360.0 if direction == "cw" else (th_min - frac * span) % 360.0
    for i in range(41):
        a = (th_min + (i / 40.0) * span) % 360.0 if direction == "cw" else (th_min - (i / 40.0) * span) % 360.0
        ar = math.radians(a)
        c, s = math.cos(ar), math.sin(ar)
        r0 = r - (26 if i % 5 == 0 else 16)
        cv2.line(img, (int(cx + c * r0), int(cy + s * r0)), (int(cx + c * (r - 8)), int(cy + s * (r - 8))),
                 (30, 32, 35), 2 if i % 5 == 0 else 1, cv2.LINE_AA)
    ar = math.radians(ang)
    c, s = math.cos(ar), math.sin(ar)
    nc, ns = -s, c
    tip = (cx + c * (r - 18), cy + s * (r - 18))
    tail = (cx - c * 32, cy - s * 32)
    pts = np.array([
        [tip[0], tip[1]], [cx + nc * 5, cy + ns * 5],
        [tail[0] + nc * 6, tail[1] + ns * 6], [tail[0] - nc * 6, tail[1] - ns * 6],
        [cx - nc * 5, cy - ns * 5],
    ], dtype=np.int32)
    cv2.fillConvexPoly(img, pts, (18, 20, 24), cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 12, (25, 28, 32), -1, cv2.LINE_AA)
    return img


def run_cv_regression() -> dict[str, Any]:
    thr = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}
    cases = []
    # 9 CW, 9 CCW, 9 negative range
    sweeps = [
        ("cw_0_16", 0.0, 16.0, 135.0, 45.0, "cw", [1.0, 2.5, 4.0, 6.0, 8.0, 10.5, 12.5, 14.0, 15.2]),
        ("ccw_0_100", 0.0, 100.0, 45.0, 135.0, "ccw", [5.0, 15.0, 28.0, 42.0, 55.0, 68.0, 79.0, 88.0, 95.0]),
        ("neg_draft", -200.0, 200.0, 135.0, 45.0, "cw", [-160.0, -110.0, -60.0, -20.0, 0.0, 45.0, 95.0, 140.0, 175.0]),
    ]
    abs_pct_errs: list[float] = []
    for name, vmin, vmax, tmin, tmax, d, vals in sweeps:
        cal = {"v_min": vmin, "v_max": vmax, "theta_min": tmin, "theta_max": tmax, "direction": d}
        for v in vals:
            img = render_dial(v, vmin, vmax, tmin, tmax, d)
            pipe = vision.GaugePipeline(f"cv-{name}")
            r = pipe.process(img, cal, thr, "u", with_overlay=False)
            err_pct = abs((r.value - v) / (vmax - vmin) * 100.0) if (r.valid and r.value is not None) else None
            if err_pct is not None:
                abs_pct_errs.append(err_pct)
            cases.append({"case": f"{name}_{v}", "true": v, "pred": r.value, "valid": r.valid, "err_pct": round(err_pct, 3) if err_pct is not None else None, "ms": r.process_ms})

    # Edge cases: tilt, glare, blank, 44% partial occlusion
    cal = {"v_min": 0.0, "v_max": 16.0, "theta_min": 135.0, "theta_max": 45.0, "direction": "cw"}
    base = render_dial(11.5)
    # Tilt
    tilted = cv2.resize(base, (int(base.shape[1] * 0.72), base.shape[0]))
    r_tilt = vision.GaugePipeline("cv-tilt").process(tilted, cal, thr, "МПа", with_overlay=False)
    tilt_err = abs((r_tilt.value - 11.5) / 16.0 * 100.0) if (r_tilt.valid and r_tilt.value is not None) else None
    # Glare
    glare = base.copy()
    cv2.circle(glare, (260, 250), 65, (255, 255, 255), -1)
    r_glare = vision.GaugePipeline("cv-glare").process(glare, cal, thr, "МПа", with_overlay=False)
    # Blank
    blank = np.full((640, 640, 3), (20, 22, 24), dtype=np.uint8)
    r_blank = vision.GaugePipeline("cv-blank").process(blank, cal, thr, "МПа", with_overlay=False)
    # 44% partial occlusion (DEF-15)
    occ = base.copy()
    occ[:, :int(occ.shape[1] * 0.44)] = (15, 17, 19)
    r_occ = vision.GaugePipeline("cv-occ").process(occ, cal, thr, "МПа", with_overlay=False)

    return {
        "clean_27_valid_count": sum(1 for c in cases if c["valid"]),
        "clean_27_mae_pct": round(statistics.mean(abs_pct_errs), 3) if abs_pct_errs else None,
        "clean_27_max_err_pct": round(max(abs_pct_errs), 3) if abs_pct_errs else None,
        "perspective_tilt_072": {"valid": r_tilt.valid, "pred": r_tilt.value, "err_pct": round(tilt_err, 3) if tilt_err is not None else None},
        "glare_spot": {"valid": r_glare.valid, "pred": r_glare.value},
        "blank_frame_rejected": not r_blank.valid,
        "partial_occlusion_44pct_rejected": not r_occ.valid,
        "partial_occlusion_reason": r_occ.debug.get("invalid_reason"),
    }


def run_scaling_benchmark() -> list[dict[str, Any]]:
    cal = {"v_min": 0.0, "v_max": 16.0, "theta_min": 135.0, "theta_max": 45.0, "direction": "cw"}
    thr = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}
    frames = [render_dial(10.0 + (i % 5) * 0.8, size=640) for i in range(10)]
    results = []
    for n_ch in (1, 2, 4, 8):
        pipes = [vision.GaugePipeline(f"ch-{i}") for i in range(n_ch)]
        # Прогрев локализации ROI
        for p in pipes:
            p.process(frames[0], cal, thr, "МПа", with_overlay=True)
        latencies: list[float] = []
        done = 0
        duration_s = 6.0
        t_start = time.perf_counter()

        def worker(ch_idx: int) -> None:
            nonlocal done
            k = 0
            while time.perf_counter() - t_start < duration_s:
                t0 = time.perf_counter()
                pipes[ch_idx].process(frames[(k + ch_idx) % len(frames)], cal, thr, "МПа", with_overlay=True)
                latencies.append((time.perf_counter() - t0) * 1000.0)
                done += 1
                k += 1

        with ThreadPoolExecutor(max_workers=n_ch) as pool:
            futs = [pool.submit(worker, i) for i in range(n_ch)]
            for f in futs:
                f.result()
        elapsed = time.perf_counter() - t_start
        s_lat = sorted(latencies)
        p50 = round(s_lat[int(len(s_lat) * 0.50)], 2) if s_lat else 0.0
        p95 = round(s_lat[min(len(s_lat) - 1, int(len(s_lat) * 0.95))], 2) if s_lat else 0.0
        p99 = round(s_lat[min(len(s_lat) - 1, int(len(s_lat) * 0.99))], 2) if s_lat else 0.0
        results.append({
            "channels": n_ch,
            "duration_s": round(elapsed, 2),
            "total_frames": len(latencies),
            "aggregate_fps": round(len(latencies) / elapsed, 2),
            "per_channel_fps": round((len(latencies) / elapsed) / n_ch, 2),
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "rss_mb": rss_mb(),
        })
    return results


async def run_sf_and_docx_benchmarks() -> dict[str, Any]:
    # Store-and-Forward drain 500 записей (без sleep(0.15))
    orig_max = config.SF_MAX_QUEUE_ROWS
    config.SF_MAX_QUEUE_ROWS = 2000
    sf = StoreAndForwardBuffer(db_path=_TMP / "sf_bench.db")
    await sf.init()
    delivered_n = 0

    async def _sink(batch: list[dict[str, Any]]) -> bool:
        nonlocal delivered_n
        delivered_n += len(batch)
        return True

    sf.configure(deliver_cb=_sink)
    await sf.set_outage(True, "bench")
    t_enq0 = time.perf_counter()
    for i in range(500):
        await sf.enqueue(channel_id=f"ch-{i % 4}", payload_type="telemetry", payload={"seq": i, "v": 12.5 + (i % 7) * 0.1})
    enq_s = time.perf_counter() - t_enq0
    sf._outage_active = False
    t_dr0 = time.perf_counter()
    await sf.flush_pending(max_batches=50)
    drain_s = time.perf_counter() - t_dr0
    await sf.close()
    config.SF_MAX_QUEUE_ROWS = orig_max

    # Генерация .md и .docx для 12 приборов
    an = DispatchAnalyzer()
    insts = []
    for i in range(12):
        lvl = "alert" if i < 2 else ("warning" if i < 5 else "normal")
        val = 15.6 if lvl == "alert" else (14.5 if lvl == "warning" else 12.2)
        insts.append({
            "id": f"b-{i}", "code": f"К1-P{i:02d}", "name": f"Прибор {i}", "short_name": f"Прибор {i}",
            "group": "Котлоагрегаты", "unit": "МПа", "gauge_type": "pressure", "decimals": 2, "source_kind": "live",
            "calibration": {"v_min": 0.0, "v_max": 16.0},
            "thresholds": {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True},
            "reading": {"valid": True, "value": val, "level": lvl},
        })
    ov = an.overview(insts, events=[])
    t_md0 = time.perf_counter()
    bundle = await generate_spec_bundle(dispatch_overview=ov, events=[], snapshot_lookup={}, period="24h")
    md_ms = round((time.perf_counter() - t_md0) * 1000.0, 1)
    t_dx0 = time.perf_counter()
    docx = render_spec_docx(bundle)
    docx_ms = round((time.perf_counter() - t_dx0) * 1000.0, 1)

    # Adaptive FPS wakeup timing
    afc = AdaptiveFpsController(idle_fps=1.0, active_fps=8.0, motion_mad_threshold=2.0)
    f0 = render_dial(11.0, size=320)
    f1 = render_dial(15.5, size=320)
    afc.check_motion_wakeup(f0)
    t_w0 = time.perf_counter()
    woke = afc.check_motion_wakeup(f1)
    wakeup_ms = round((time.perf_counter() - t_w0) * 1000.0, 3)

    return {
        "sf_500_enqueue_s": round(enq_s, 3),
        "sf_500_drain_s": round(drain_s, 3),
        "sf_500_drain_msg_per_s": round(delivered_n / max(drain_s, 1e-6), 1),
        "spec_md_ms": md_ms,
        "spec_docx_ms": docx_ms,
        "spec_docx_bytes": len(docx),
        "adaptive_motion_wakeup_triggered": woke,
        "adaptive_motion_check_ms": wakeup_ms,
    }


def main() -> None:
    report = {
        "device": "cpu",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cv_regression": run_cv_regression(),
        "cpu_scaling": run_scaling_benchmark(),
        "subsystem_benchmarks": asyncio.run(run_sf_and_docx_benchmarks()),
        "rss_mb_end": rss_mb(),
    }
    out = Path(os.environ.get("BENCH_OUT", str(_TMP / "benchmark_after.json")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
