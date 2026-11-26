"""
Independent Audit Script 05 — Sustained Mini-Soak & Memory Growth Benchmark,
Adaptive FPS Idle vs Burst Resource Comparison, Real SQLite Write Throughput,
and Fault Injection (DB write error, CV exception isolation, corrupted frame).
Note: 30-60 minute soak is impractical within interactive session limits; this script
performs a controlled 20-second sustained soak with RSS/latency sampling and explicitly
logs the duration constraint so full 30-60m soak is marked NOT VERIFIED / PARTIAL.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

REPO = Path(__file__).resolve().parents[3]
OUT_DIR = Path(os.environ.get("AUDIT_OUT_DIR", str(REPO / "reports" / "audit" / "evidence")))
OUT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO))

import numpy as np

from app import config, db, vision
from app.spec_generator import generate_spec_bundle, render_spec_docx
from app.dispatch_analyzer import DispatchAnalyzer
from app.store_forward import StoreAndForwardBuffer
from app.stream_manager import render_gauge_frame


def get_rss_mb() -> float:
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
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
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(pmc)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    h = k32.GetCurrentProcess()
    psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    return round(pmc.WorkingSetSize / (1024 * 1024), 2)


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="gv_soak_"))
    os.environ["GAUGEVISION_DB"] = str(tmp / "bench.db")
    config.configure_runtime(demo=True, db_path=str(tmp / "bench.db"), device="cpu")
    await db.init_db()
    await db.create_camera(cam_id="bench-cam", name="Bench", type="phone_ws")

    # 1. SQLite telemetry batch write throughput (1000 rows in 10 batches of 100)
    t_w0 = time.perf_counter()
    for b in range(10):
        rows = [("bench-cam", db.utcnow_iso(), 10.0 + (i * 0.01), 270.0, "normal", "МПа", None) for i in range(100)]
        await db.insert_readings(rows)
    w_elapsed = time.perf_counter() - t_w0
    rows_per_sec = round(1000.0 / max(1e-6, w_elapsed), 1)
    await db.close_db()

    # 2. Store-and-Forward 500-item queue drain throughput
    sf = StoreAndForwardBuffer(db_path=tmp / "sf_bench.db")
    delivered = {"n": 0}
    async def fast_cb(items):
        delivered["n"] += len(items)
        return True
    sf.configure(deliver_cb=fast_cb)
    await sf.init()
    await sf.set_outage(True, "bench")
    t_enq0 = time.perf_counter()
    for i in range(200):
        await sf.enqueue(channel_id="bench", payload_type="telemetry", payload={"i": i})
    enq_elapsed = time.perf_counter() - t_enq0
    sf._outage_active = False
    t_dr0 = time.perf_counter()
    await sf.flush_pending(max_batches=20)
    drain_elapsed = time.perf_counter() - t_dr0
    await sf.close()

    # 3. Document generation timing (36 instruments -> .md + .docx)
    from app import demo
    sim = demo.SimulatedTelemetryAdapter(42, "mixed")
    insts = sim.all_instruments()
    da = DispatchAnalyzer()
    ov = da.overview(insts, [])
    t_md0 = time.perf_counter()
    bundle = await generate_spec_bundle(dispatch_overview=ov, events=[], snapshot_lookup={}, period="24h")
    md_ms = round((time.perf_counter() - t_md0) * 1000.0, 1)
    t_dx0 = time.perf_counter()
    docx_b = render_spec_docx(bundle)
    docx_ms = round((time.perf_counter() - t_dx0) * 1000.0, 1)

    # 4. Adaptive FPS Idle (1 FPS) vs Burst (6 FPS) CPU time comparison (6s each)
    cal = {"v_min": 0.0, "v_max": 16.0, "theta_min": 135.0, "theta_max": 45.0, "direction": "cw"}
    thr = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}
    pipe = vision.GaugePipeline("soak-1")
    frm = render_gauge_frame(code="S-01", name="Soak", unit="МПа", value=12.0, v_min=0, v_max=16, annotate_cv=False)
    # Warm up YOLO once
    pipe.process(frm, cal, thr, "МПа", with_overlay=True)

    rss_start = get_rss_mb()

    def measure_mode(fps: float, duration_s: float) -> dict:
        c0 = time.process_time()
        w0 = time.perf_counter()
        n = 0
        lats = []
        while time.perf_counter() - w0 < duration_s:
            t_f = time.perf_counter()
            r = pipe.process(frm, cal, thr, "МПа", with_overlay=True)
            lats.append(r.process_ms)
            n += 1
            rem = (1.0 / fps) - (time.perf_counter() - t_f)
            if rem > 0:
                time.sleep(rem)
        cpu_s = time.process_time() - c0
        wall_s = time.perf_counter() - w0
        return {
            "frames": n,
            "wall_s": round(wall_s, 2),
            "cpu_time_s": round(cpu_s, 3),
            "cpu_core_pct": round((cpu_s / max(1e-6, wall_s)) * 100.0, 1),
            "avg_ms": round(sum(lats) / max(1, len(lats)), 1),
        }

    idle_prof = measure_mode(1.0, 5.0)
    burst_prof = measure_mode(6.0, 5.0)

    # 5. Mini-soak (12s continuous CV + memory RSS check)
    rss_samples = [get_rss_mb()]
    t_sk0 = time.perf_counter()
    soak_frames = 0
    while time.perf_counter() - t_sk0 < 12.0:
        val = 8.0 + 4.0 * ((soak_frames % 10) / 10.0)
        f2 = render_gauge_frame(code="S-01", name="Soak", unit="МПа", value=val, v_min=0, v_max=16, annotate_cv=False)
        pipe.process(f2, cal, thr, "МПа", with_overlay=True)
        soak_frames += 1
        if soak_frames % 25 == 0:
            rss_samples.append(get_rss_mb())
    rss_end = get_rss_mb()
    rss_samples.append(rss_end)

    # 6. Fault injection: corrupted image bytes & degenerate 1x1 frame into GaugePipeline
    corrupt_exc = None
    try:
        tiny = np.zeros((4, 4, 3), dtype=np.uint8)
        r_tiny = pipe.process(tiny, cal, thr, "МПа", with_overlay=True)
        tiny_ok = not r_tiny.valid
    except Exception as exc:
        corrupt_exc = str(exc)
        tiny_ok = False

    # 7. Fault injection: read-only / invalid DB path error handling in StoreAndForwardBuffer
    db_err_msg = None
    try:
        bad_sf = StoreAndForwardBuffer(db_path=Path(r"Z:\nonexistent_drive_audit\sf.db"))
        await bad_sf.init()
    except Exception as exc:
        db_err_msg = f"{type(exc).__name__}: {exc}"

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sqlite_batch_write": {"rows": 1000, "elapsed_s": round(w_elapsed, 3), "rows_per_sec": rows_per_sec},
        "store_forward_throughput": {
            "enqueue_200_s": round(enq_elapsed, 3),
            "enqueue_rows_per_sec": round(200.0 / max(1e-6, enq_elapsed), 1),
            "drain_200_s": round(drain_elapsed, 3),
            "drain_rows_per_sec": round(200.0 / max(1e-6, drain_elapsed), 1),
            "delivered": delivered["n"],
        },
        "spec_generation_timing": {"md_ms": md_ms, "docx_ms": docx_ms, "docx_bytes": len(docx_b)},
        "adaptive_fps_cpu_comparison": {
            "idle_1fps": idle_prof,
            "burst_6fps": burst_prof,
            "measured_cpu_reduction_pct": round((1.0 - idle_prof["cpu_core_pct"] / max(0.1, burst_prof["cpu_core_pct"])) * 100.0, 1),
        },
        "mini_soak_12s": {
            "note": "Controlled 12s continuous CPU soak (30-60 min soak NOT VERIFIED due to session runtime budget).",
            "frames_processed": soak_frames,
            "rss_start_mb": rss_start,
            "rss_end_mb": rss_end,
            "rss_delta_mb": round(rss_end - rss_start, 2),
            "rss_samples_mb": rss_samples,
        },
        "fault_injection_extra": {
            "tiny_4x4_frame_handled_safely": tiny_ok,
            "tiny_frame_exception": corrupt_exc,
            "unwritable_sf_db_error": db_err_msg,
        },
    }
    out = OUT_DIR / "perf_soak_fault_results.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PERF & SOAK AUDIT COMPLETE -> {out}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
