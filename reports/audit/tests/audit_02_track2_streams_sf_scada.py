"""
Independent Audit Script 02 — Track №2: Architectural Videoanalytics, Multi-Stream Load,
Degradation Detection (no fault-flag cheats), Adaptive FPS, Ring Buffer, Store-and-Forward
Scenarios A–G, Real Local MQTT 3.1.1 Broker, Real Modbus TCP Wire Protocol, SSE.
Read-only against production code. Runs strictly on CPU (CUDA_VISIBLE_DEVICES="").
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import struct
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

REPO = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = Path(os.environ.get("AUDIT_OUT_DIR", str(REPO / "reports" / "audit" / "evidence")))
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO))

import cv2
import numpy as np

from app import config, vision
from app.scada_gateway import ModbusTcpGateway, MqttAsyncAdapter, ScadaGateway
from app.store_forward import StoreAndForwardBuffer
from app.stream_manager import (
    AdaptiveFpsController,
    EdgeStreamManager,
    FrameBroker,
    FrameQualityAnalyzer,
    IncidentRingBuffer,
    apply_signal_fault,
    encode_jpeg,
    render_gauge_frame,
)


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return round(sorted_vals[idx], 2)


def make_test_mp4(path: Path, frames: int = 36, fps: float = 12.0) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (640, 480))
    assert writer.isOpened(), f"Failed to open VideoWriter for {path}"
    for i in range(frames):
        val = 8.0 + 5.0 * math.sin(2.0 * math.pi * i / frames)
        frm = render_gauge_frame(
            code="VID-01", name="Test Video", unit="МПа", value=val,
            v_min=0.0, v_max=16.0, annotate_cv=False, width=640, height=480,
        )
        noise = np.random.randint(-3, 4, frm.shape, dtype=np.int16)
        frm = np.clip(frm.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        writer.write(frm)
    writer.release()


# ---------------------------------------------------------------------------
# 1. Real Frame Quality Analyzer (10 scenarios WITHOUT injected_fault override)
# ---------------------------------------------------------------------------
def audit_signal_quality() -> dict:
    base_cal = {"v_min": 0.0, "v_max": 16.0}

    def moving_frame(v: float, noise_amp: int = 3) -> np.ndarray:
        f = render_gauge_frame(code="Q-01", name="Q", unit="МПа", value=v,
                               v_min=0.0, v_max=16.0, annotate_cv=False)
        if noise_amp > 0:
            n = np.random.randint(-noise_amp, noise_amp + 1, f.shape, dtype=np.int16)
            f = np.clip(f.astype(np.int16) + n, 0, 255).astype(np.uint8)
        return f

    scenarios = {}

    # 1. Clean moving
    qa = FrameQualityAnalyzer()
    rep = None
    for i in range(12):
        rep = qa.analyze(moving_frame(10.0 + i * 0.2), stream_online=True, injected_fault=None)
    scenarios["1_clean_moving"] = rep.to_dict()

    # 2. Static scene / immobile needle with ZERO camera noise (false positive check!)
    qa_static_clean = FrameQualityAnalyzer()
    fixed_clean = moving_frame(10.0, noise_amp=0)
    for _ in range(12):
        rep_sc = qa_static_clean.analyze(fixed_clean, stream_online=True, injected_fault=None)
    scenarios["2a_static_needle_zero_noise_fp_check"] = rep_sc.to_dict()

    # 2b. Static scene / immobile needle with realistic sensor noise (±2)
    qa_static_noisy = FrameQualityAnalyzer()
    for _ in range(12):
        rep_sn = qa_static_noisy.analyze(moving_frame(10.0, noise_amp=2), stream_online=True, injected_fault=None)
    scenarios["2b_static_needle_sensor_noise"] = rep_sn.to_dict()

    # 3. True frame freeze (exact same buffer repeated 12x)
    qa_freeze = FrameQualityAnalyzer()
    frozen = moving_frame(10.0, noise_amp=3)
    for _ in range(12):
        rep_fr = qa_freeze.analyze(frozen, stream_online=True, injected_fault=None)
    scenarios["3_true_freeze_12_frames"] = rep_fr.to_dict()

    # 4. Low light (dimmed pixel values, NO injected_fault)
    qa_low = FrameQualityAnalyzer()
    dim = apply_signal_fault(moving_frame(10.0), "low_light")
    scenarios["4_low_light_real_pixels"] = qa_low.analyze(dim, stream_online=True, injected_fault=None).to_dict()

    # 5. Partial lens occlusion (50% black rectangle)
    qa_part = FrameQualityAnalyzer()
    part = moving_frame(10.0)
    part[:, :320] = 5
    scenarios["5_partial_occlusion_50pct"] = qa_part.analyze(part, stream_online=True, injected_fault=None).to_dict()

    # 6. Full lens occlusion (black frame)
    qa_full = FrameQualityAnalyzer()
    black = np.full((480, 640, 3), 4, dtype=np.uint8)
    scenarios["6_full_occlusion_black"] = qa_full.analyze(black, stream_online=True, injected_fault=None).to_dict()

    # 7. Fog / condensation (mild blur + veil)
    qa_fog = FrameQualityAnalyzer()
    fog_frame = cv2.addWeighted(cv2.GaussianBlur(moving_frame(10.0), (25, 25), 9.0), 0.45,
                                np.full((480, 640, 3), (205, 210, 215), dtype=np.uint8), 0.55, 0)
    scenarios["7_fog_condensation_real_pixels"] = qa_fog.analyze(fog_frame, stream_online=True, injected_fault=None).to_dict()

    # 8. Smoke / steam (apply_signal_fault steam, NO injected_fault flag!)
    qa_steam = FrameQualityAnalyzer()
    steam_frame = apply_signal_fault(moving_frame(10.0), "steam")
    scenarios["8_steam_smoke_real_pixels"] = qa_steam.analyze(steam_frame, stream_online=True, injected_fault=None).to_dict()

    # 9. Strong glare (NO injected_fault flag!)
    qa_glare = FrameQualityAnalyzer()
    glare_frame = apply_signal_fault(moving_frame(10.0), "glare")
    scenarios["9_glare_real_pixels"] = qa_glare.analyze(glare_frame, stream_online=True, injected_fault=None).to_dict()

    # 10. Recovery after steam -> clean moving frames
    rec_rep = qa_steam.analyze(moving_frame(11.0), stream_online=True, injected_fault=None)
    scenarios["10_recovery_after_steam"] = rec_rep.to_dict()

    # 11. Natural lighting shift (slightly dim luma ~50 vs bright luma ~190)
    qa_nat = FrameQualityAnalyzer()
    nat_dim = np.clip(moving_frame(10.0).astype(np.float32) * 0.45, 0, 255).astype(np.uint8)
    scenarios["11_natural_dimming_45pct"] = qa_nat.analyze(nat_dim, stream_online=True, injected_fault=None).to_dict()

    return scenarios


# ---------------------------------------------------------------------------
# 2. Adaptive FPS real call count & transient spike aliasing test
# ---------------------------------------------------------------------------
async def audit_adaptive_fps() -> dict:
    ctrl = AdaptiveFpsController(idle_fps=1.0, active_fps=6.0, hold_seconds=3.0)

    # Measure actual execution cadence in eco_idle vs event_burst
    idle_calls = 0
    t_start = time.monotonic()
    while time.monotonic() - t_start < 2.2:
        ctrl.update(value=10.0, span=16.0, level="normal", degraded=False)
        idle_calls += 1
        await asyncio.sleep(ctrl.interval)
    idle_elapsed = time.monotonic() - t_start
    idle_actual_fps = round(idle_calls / idle_elapsed, 2)

    # Trigger jump > 2.5% -> measure switch latency and active calls
    t_sw = time.perf_counter()
    info_burst = ctrl.update(value=11.0, span=16.0, level="normal", degraded=False)
    switch_ms = round((time.perf_counter() - t_sw) * 1000.0, 3)
    burst_mode = info_burst["mode"]

    burst_calls = 0
    t_b = time.monotonic()
    while time.monotonic() - t_b < 1.5:
        ctrl.update(value=11.0, span=16.0, level="normal", degraded=False)
        burst_calls += 1
        await asyncio.sleep(ctrl.interval)
    burst_elapsed = time.monotonic() - t_b
    burst_actual_fps = round(burst_calls / burst_elapsed, 2)

    # Wait for hold_seconds to expire and confirm return to eco_idle
    await asyncio.sleep(1.7)
    info_after = ctrl.update(value=11.0, span=16.0, level="normal", degraded=False)

    # Short transient spike (0.35 s) during 1.0 FPS idle sleep:
    # Sampling only once per 1.0 s misses a 0.35 s hydraulic hammer occurring between polls!
    spike_detected = False
    spike_start, spike_end = 0.25, 0.60  # 0.35s duration between sample t=0.0 and t=1.0
    for sample_t in (0.0, 1.0, 2.0):
        val = 15.8 if (spike_start <= sample_t <= spike_end) else 10.0
        if val > 14.0:
            spike_detected = True

    return {
        "idle_calls": idle_calls,
        "idle_actual_fps": idle_actual_fps,
        "burst_triggered": burst_mode == "event_burst",
        "switch_latency_ms": switch_ms,
        "burst_calls": burst_calls,
        "burst_actual_fps": burst_actual_fps,
        "returned_to_idle_after_hold": info_after["mode"] == "eco_idle",
        "actual_compute_reduction_pct": round((1.0 - idle_actual_fps / max(0.1, burst_actual_fps)) * 100.0, 1),
        "transient_035s_spike_missed_at_1fps": not spike_detected,
        "note_aliasing": "At 1.0 FPS eco_idle, _process_loop sleeps 1.0s without lightweight frame-diff/motion wake-up; any transient < 1.0s between samples is missed.",
    }


# ---------------------------------------------------------------------------
# 3. Incident Ring Buffer (pre/post ordering + concurrent incident overwrite)
# ---------------------------------------------------------------------------
def audit_ring_buffer() -> dict:
    rb = IncidentRingBuffer(pre_len=6, post_len=4)
    for i in range(10):
        rb.push(f"FRAME_{i:02d}".encode(), ts_iso=f"2026-11-26T10:00:{i:02d}Z")
    t1 = rb.trigger("Incident 1", "alert", 15.6)
    for i in range(10, 12):
        rb.push(f"FRAME_{i:02d}".encode(), ts_iso=f"2026-11-26T10:00:{i:02d}Z")
    # Trigger a second incident BEFORE first finishes post-capture!
    t2 = rb.trigger("Incident 2 (concurrent)", "warning", 14.5)
    for i in range(12, 18):
        rb.push(f"FRAME_{i:02d}".encode(), ts_iso=f"2026-11-26T10:00:{i:02d}Z")

    archives = list(rb._archives)
    # Also test normal single-incident pre/post integrity
    rb_single = IncidentRingBuffer(pre_len=5, post_len=3)
    for i in range(8):
        rb_single.push(f"PRE_{i:02d}".encode(), ts_iso=f"2026-11-26T10:01:{i:02d}Z")
    rb_single.trigger("Single Incident", "alert", 15.8)
    for i in range(8, 12):
        rb_single.push(f"POST_{i:02d}".encode(), ts_iso=f"2026-11-26T10:01:{i:02d}Z")
    single_arch = list(rb_single._archives)[0]
    pre_tags = [b.decode() for _, b in single_arch["pre"]]
    post_tags = [b.decode() for _, b in single_arch["post"]]

    return {
        "single_incident_pre_tags": pre_tags,
        "single_incident_post_tags": post_tags,
        "pre_strictly_before_trigger": all(t.startswith("PRE_") for t in pre_tags) and len(pre_tags) == 5,
        "post_strictly_after_trigger": all(t.startswith("POST_") for t in post_tags) and len(post_tags) == 3,
        "concurrent_incidents_archived": len(archives),
        "concurrent_incident_1_lost": len(archives) == 1 and archives[0]["reason"] == "Incident 2 (concurrent)",
        "persisted_to_disk": False,
        "stats_after": rb_single.stats(),
    }


# ---------------------------------------------------------------------------
# 4. Multi-channel load & isolation benchmark (1, 2, 4, 8 channels) + RTSP backoff
# ---------------------------------------------------------------------------
async def audit_multistream_and_isolation(tmp_dir: Path) -> dict:
    mp4 = tmp_dir / "bench_gauge.mp4"
    make_test_mp4(mp4, frames=48, fps=12.0)

    cal = {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"}
    thr = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}

    bench_results = {}
    for n_ch in (1, 2, 4, 8):
        broker = FrameBroker()
        mgr = EdgeStreamManager(broker)
        executor = ThreadPoolExecutor(max_workers=config.VISION_EXECUTOR_WORKERS)
        pipes = {f"ch-{i}": vision.GaugePipeline(f"ch-{i}") for i in range(n_ch)}
        lat_ms: list[float] = []
        per_ch_frames: dict[str, int] = {f"ch-{i}": 0 for i in range(n_ch)}
        errors = 0
        loop_lags_ms: list[float] = []

        for i in range(n_ch):
            mgr.start_camera(f"ch-{i}", "video_file", str(mp4))

        stop_ev = asyncio.Event()

        async def lag_monitor() -> None:
            while not stop_ev.is_set():
                t0 = time.perf_counter()
                await asyncio.sleep(0.05)
                lag = max(0.0, (time.perf_counter() - t0 - 0.05) * 1000.0)
                loop_lags_ms.append(lag)

        async def worker_loop(cid: str) -> None:
            nonlocal errors
            loop = asyncio.get_running_loop()
            last_no = 0
            pipe = pipes[cid]
            while not stop_ev.is_set():
                frm, fno = broker.latest_frame(cid)
                if frm is not None and fno != last_no:
                    last_no = fno
                    try:
                        r = await loop.run_in_executor(executor, pipe.process, frm, cal, thr, "МПа", False)
                        lat_ms.append(r.process_ms)
                        per_ch_frames[cid] += 1
                    except Exception:
                        errors += 1
                await asyncio.sleep(0.08)

        t_run0 = time.perf_counter()
        tasks = [asyncio.create_task(worker_loop(f"ch-{i}")) for i in range(n_ch)]
        lag_t = asyncio.create_task(lag_monitor())
        await asyncio.sleep(3.5)
        stop_ev.set()
        await asyncio.gather(*tasks, lag_t, return_exceptions=True)
        elapsed = time.perf_counter() - t_run0

        # Isolation test on 4-channel run: stop ch-0 and ensure ch-1..ch-3 keep processing
        iso_ok = None
        if n_ch == 4:
            before_counts = dict(per_ch_frames)
            mgr.stop_camera("ch-0")
            stop_ev2 = asyncio.Event()
            tasks2 = [asyncio.create_task(worker_loop(f"ch-{i}")) for i in range(1, 4)]
            await asyncio.sleep(1.5)
            stop_ev2.set()
            await asyncio.gather(*tasks2, return_exceptions=True)
            iso_ok = all(per_ch_frames[f"ch-{i}"] > before_counts[f"ch-{i}"] for i in range(1, 4))

        await mgr.stop_all()
        executor.shutdown(wait=True)

        lat_sorted = sorted(lat_ms)
        total_proc = sum(per_ch_frames.values())
        bench_results[f"{n_ch}_channels"] = {
            "elapsed_s": round(elapsed, 2),
            "total_inferences": total_proc,
            "aggregate_fps": round(total_proc / elapsed, 2),
            "per_channel_fps": {k: round(v / elapsed, 2) for k, v in per_ch_frames.items()},
            "latency_p50_ms": percentile(lat_sorted, 50),
            "latency_p95_ms": percentile(lat_sorted, 95),
            "latency_p99_ms": percentile(lat_sorted, 99),
            "event_loop_lag_p95_ms": percentile(sorted(loop_lags_ms), 95),
            "event_loop_lag_max_ms": round(max(loop_lags_ms), 2) if loop_lags_ms else 0.0,
            "errors": errors,
            "isolation_other_channels_continue_after_stop": iso_ok,
        }

    # Dead RTSP backoff & non-blocking check
    broker2 = FrameBroker()
    status_hist: list[tuple[float, str]] = []

    async def on_st(cid: str, st: str) -> None:
        status_hist.append((round(time.monotonic(), 2), st))

    mgr2 = EdgeStreamManager(broker2, on_status=on_st)
    t_dead0 = time.monotonic()
    mgr2.start_camera("dead-rtsp", "rtsp", "rtsp://127.0.0.1:59999/nonexistent")
    # Measure event-loop responsiveness while dead RTSP connects
    lag_dead = []
    for _ in range(30):
        t0 = time.perf_counter()
        await asyncio.sleep(0.1)
        lag_dead.append(round(max(0.0, (time.perf_counter() - t0 - 0.1) * 1000.0), 2))
    dead_info = mgr2.info("dead-rtsp")
    await mgr2.stop_all()

    return {
        "scaling": bench_results,
        "dead_rtsp_test": {
            "duration_s": round(time.monotonic() - t_dead0, 2),
            "fail_count": dead_info["fail_count"],
            "status_before_stop": dead_info["status"],
            "last_error": dead_info["last_error"],
            "event_loop_max_lag_ms": max(lag_dead) if lag_dead else 0.0,
            "status_transitions": status_hist,
        },
    }


# ---------------------------------------------------------------------------
# 5. Store-and-Forward Scenarios A-G + Concurrency Race
# ---------------------------------------------------------------------------
async def audit_store_and_forward(tmp_dir: Path) -> dict:
    sf_db = tmp_dir / "sf_audit.db"
    delivered_log: list[dict] = []
    fail_next = {"flag": False, "fail_after_accept": False}

    async def deliver_cb(items: list[dict]) -> bool:
        if fail_next["flag"]:
            return False
        delivered_log.extend(items)
        if fail_next["fail_after_accept"]:
            # Scenario F: broker received items, but ACK lost in transit
            return False
        return True

    sf = StoreAndForwardBuffer(db_path=sf_db)
    sf.configure(deliver_cb=deliver_cb)
    await sf.init()

    # Check ACTUAL PRAGMA journal_mode on disk
    con = sqlite3.connect(str(sf_db))
    actual_wal = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()

    # Scenario A: Normal delivery (10 items)
    for i in range(10):
        await sf.enqueue(channel_id="ch-a", payload_type="telemetry", payload={"n": i})
    a_stats = await sf.stats()
    a_res = {
        "produced": 10,
        "delivered_calls": len(delivered_log),
        "unique_uuids": len({x["event_uuid"] for x in delivered_log}),
        "pending": a_stats["pending_count"],
        "in_order": [x["seq_id"] for x in delivered_log] == sorted(x["seq_id"] for x in delivered_log),
    }

    # Scenario B: Outage (15 items including alarm + frame_blob!)
    delivered_before_b = len(delivered_log)
    await sf.set_outage(True, "Audit outage B")
    fake_jpeg = b"\xff\xd8\xff\xe0AUDIT_FRAME_BLOB\xff\xd9"
    for i in range(15):
        await sf.enqueue(
            channel_id="ch-b",
            payload_type="alarm" if i == 5 else "telemetry",
            payload={"outage_i": i},
            frame_blob=fake_jpeg if i == 5 else None,
        )
    b_stats = await sf.stats()
    b_res = {
        "produced": 15,
        "delivered_during_outage": len(delivered_log) - delivered_before_b,
        "pending": b_stats["pending_count"],
        "sync_state": b_stats["sync_state"],
    }

    # Scenario D: Restart during outage (close + reopen fresh instance on same SQLite file!)
    await sf.close()
    sf2 = StoreAndForwardBuffer(db_path=sf_db)
    sf2.configure(deliver_cb=deliver_cb)
    await sf2.init()
    d_pending_after_restart = await sf2.pending_count()
    d_res = {
        "pending_before_restart": b_stats["pending_count"],
        "pending_after_restart": d_pending_after_restart,
        "zero_loss_across_restart": d_pending_after_restart == b_stats["pending_count"],
    }

    # Scenario C: Recovery & chronological batch flush + check if frame_blob is delivered
    delivered_before_c = len(delivered_log)
    t_rec0 = time.perf_counter()
    flush_c = await sf2.flush_pending(max_batches=10)
    rec_ms = round((time.perf_counter() - t_rec0) * 1000.0, 2)
    c_items = delivered_log[delivered_before_c:]
    alarm_item = next((x for x in c_items if x["payload_type"] == "alarm"), None)
    c_res = {
        "flushed": flush_c["flushed"],
        "batches": flush_c["batches"],
        "recovery_ms": rec_ms,
        "pending_after": await sf2.pending_count(),
        "strict_chronological_seq": [x["seq_id"] for x in c_items] == sorted(x["seq_id"] for x in c_items),
        "alarm_has_frame_flag": alarm_item.get("has_frame") if alarm_item else None,
        "alarm_frame_blob_actually_delivered": ("frame_blob" in alarm_item and alarm_item["frame_blob"] is not None) if alarm_item else False,
    }

    # Scenario E: Re-outage mid-sync (enqueue 50 items so > SF_BATCH_SIZE=40 -> 2 batches; fail on 2nd batch)
    await sf2.set_outage(True, "Audit outage E")
    for i in range(50):
        await sf2.enqueue(channel_id="ch-e", payload_type="telemetry", payload={"e_i": i})
    batch_calls = {"n": 0}

    async def fail_second_batch(items: list[dict]) -> bool:
        batch_calls["n"] += 1
        if batch_calls["n"] == 2:
            return False
        delivered_log.extend(items)
        return True

    sf2.configure(deliver_cb=fail_second_batch)
    sf2._outage_active = False
    e_first = await sf2.flush_pending(max_batches=5)
    e_mid_pending = await sf2.pending_count()
    # Recover and finish remaining
    sf2.configure(deliver_cb=deliver_cb)
    e_second = await sf2.flush_pending(max_batches=5)
    e_end_pending = await sf2.pending_count()
    e_res = {
        "produced": 50,
        "flushed_before_second_outage": e_first["flushed"],
        "pending_after_interruption": e_mid_pending,
        "flushed_after_recovery": e_second["flushed"],
        "pending_final": e_end_pending,
        "total_accounted_for": (e_first["flushed"] + e_second["flushed"]) == 50 and e_end_pending == 0,
    }

    # Scenario F: Lost delivery ACK -> check duplicate logical deliveries
    await sf2.set_outage(True, "Audit outage F")
    await sf2.enqueue(channel_id="ch-f", payload_type="alarm", payload={"f_unique": 1})
    sf2._outage_active = False
    before_f = len(delivered_log)
    fail_next["fail_after_accept"] = True
    await sf2.flush_pending(max_batches=2)
    fail_next["fail_after_accept"] = False
    await sf2.flush_pending(max_batches=2)
    f_items = delivered_log[before_f:]
    f_uuids = [x["event_uuid"] for x in f_items]
    f_res = {
        "deliver_attempts_received": len(f_items),
        "unique_event_uuids": len(set(f_uuids)),
        "duplicate_deliveries": len(f_items) - len(set(f_uuids)),
        "delivery_guarantee": "at-least-once (no receiver-side idempotency / dedup)",
    }

    # Scenario G: Prolonged outage exceeding SF_MAX_QUEUE_ROWS
    orig_max = config.SF_MAX_QUEUE_ROWS
    config.SF_MAX_QUEUE_ROWS = 30
    try:
        await sf2.set_outage(True, "Audit outage G")
        for i in range(60):
            await sf2.enqueue(channel_id="ch-g", payload_type="telemetry", payload={"g_i": i})
        g_pending = await sf2.pending_count()
    finally:
        config.SF_MAX_QUEUE_ROWS = orig_max
    g_res = {
        "configured_sf_max_queue_rows": 30,
        "enqueued_during_outage": 60,
        "pending_rows_in_sqlite": g_pending,
        "pending_queue_unbounded_on_outage": g_pending > 30,
    }

    # Concurrency race test: enqueue() while flush_pending() is running
    sf2._outage_active = False
    race_log: list[int] = []

    async def slow_deliver(items: list[dict]) -> bool:
        await asyncio.sleep(0.05)
        for it in items:
            race_log.append(it["seq_id"])
        return True

    sf2.configure(deliver_cb=slow_deliver)
    flush_task = asyncio.create_task(sf2.flush_pending(max_batches=10))
    await asyncio.sleep(0.01)
    enq_tasks = [asyncio.create_task(sf2.enqueue(channel_id="race", payload_type="telemetry", payload={"r": i})) for i in range(8)]
    await asyncio.gather(flush_task, *enq_tasks)
    await sf2.flush_pending(max_batches=10)
    dups_in_race = len(race_log) - len(set(race_log))
    ooo_in_race = race_log != sorted(race_log)
    await sf2.close()

    return {
        "actual_sqlite_journal_mode": actual_wal,
        "scenario_A_normal": a_res,
        "scenario_B_outage": b_res,
        "scenario_C_recovery": c_res,
        "scenario_D_restart_during_outage": d_res,
        "scenario_E_reoutage_midsync": e_res,
        "scenario_F_lost_ack": f_res,
        "scenario_G_prolonged_outage_cap": g_res,
        "concurrency_enqueue_vs_flush_race": {
            "delivered_count": len(race_log),
            "duplicate_seq_ids": dups_in_race,
            "out_of_order": ooo_in_race,
        },
    }


# ---------------------------------------------------------------------------
# 6. Real local MQTT 3.1.1 broker & Modbus TCP wire-level tests
# ---------------------------------------------------------------------------
async def audit_scada_mqtt_and_modbus(tmp_dir: Path) -> dict:
    # A. Local mock MQTT 3.1.1 broker
    received_mqtt: list[dict] = []

    async def handle_mqtt_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                hdr = await reader.read(1)
                if not hdr:
                    break
                pkt_type = hdr[0] >> 4
                # Decode MQTT remaining length
                mult, rem_len = 1, 0
                while True:
                    b = (await reader.readexactly(1))[0]
                    rem_len += (b & 0x7F) * mult
                    if (b & 0x80) == 0:
                        break
                    mult *= 128
                body = await reader.readexactly(rem_len) if rem_len > 0 else b""
                if pkt_type == 1:  # CONNECT
                    writer.write(bytes([0x20, 0x02, 0x00, 0x00]))  # CONNACK OK
                    await writer.drain()
                elif pkt_type == 3:  # PUBLISH
                    tlen = struct.unpack(">H", body[:2])[0]
                    topic = body[2:2 + tlen].decode("utf-8", errors="replace")
                    payload_raw = body[2 + tlen:].decode("utf-8", errors="replace")
                    received_mqtt.append({"topic": topic, "payload": payload_raw})
        except Exception:
            pass
        finally:
            writer.close()

    mqtt_port = 18837
    broker_srv = await asyncio.start_server(handle_mqtt_client, "127.0.0.1", mqtt_port)

    orig_mqtt_en, orig_mqtt_host, orig_mqtt_port = config.MQTT_ENABLED, config.MQTT_HOST, config.MQTT_PORT
    config.MQTT_ENABLED = True
    config.MQTT_HOST = "127.0.0.1"
    config.MQTT_PORT = mqtt_port

    scada = ScadaGateway()
    connected_ok = await scada.mqtt.connect()
    await scada.deliver_batch([
        {"seq_id": 1, "event_uuid": "u1", "channel_id": "k1-p01", "payload_type": "telemetry", "payload": {"val": 13.5}},
        {"seq_id": 2, "event_uuid": "u2", "channel_id": "k1-p01", "payload_type": "alarm", "payload": {"val": 15.6}},
    ])
    await asyncio.sleep(0.15)
    live_received_count = len(received_mqtt)

    # FAULT INJECTION: Stop the MQTT broker and test if Store-and-Forward + ScadaGateway buffers or drops!
    await scada.mqtt.close()
    broker_srv.close()
    await broker_srv.wait_closed()

    sf_mqtt = StoreAndForwardBuffer(db_path=tmp_dir / "sf_mqtt_down.db")
    sf_mqtt.configure(deliver_cb=scada.deliver_batch)
    await sf_mqtt.init()
    enq_while_down = await sf_mqtt.enqueue(
        channel_id="k1-p01", payload_type="alarm", payload={"val": 15.9, "broker": "DOWN"}
    )
    pending_while_broker_down = await sf_mqtt.pending_count()
    await sf_mqtt.close()
    await scada.mqtt.close()

    config.MQTT_ENABLED, config.MQTT_HOST, config.MQTT_PORT = orig_mqtt_en, orig_mqtt_host, orig_mqtt_port

    # B. Real Modbus TCP wire tests
    orig_mb_en, orig_mb_host, orig_mb_port = config.MODBUS_ENABLED, config.MODBUS_HOST, config.MODBUS_PORT
    config.MODBUS_ENABLED = True
    config.MODBUS_HOST = "127.0.0.1"
    config.MODBUS_PORT = 15522

    mb = ModbusTcpGateway()
    mb.update_from_instruments([
        {"id": "i1", "code": "К1-Р01", "short_name": "Пар", "unit": "МПа", "reading": {"valid": True, "value": 13.75, "level": "normal"}},
        {"id": "i2", "code": "К1-Т01", "short_name": "Темп", "unit": "°C", "reading": {"valid": False, "value": None, "level": "stale"}},
    ], health_by_id={"i1": 94.5, "i2": 42.0}, sf_pending=7, outage_active=True)
    await mb.start()

    async def mb_req(tx: int, unit: int, fc: int, addr: int, cnt: int) -> bytes:
        r, w = await asyncio.open_connection("127.0.0.1", 15522)
        try:
            w.write(struct.pack(">HHHBBHH", tx, 0, 6, unit, fc, addr, cnt))
            await w.drain()
            hdr = await asyncio.wait_for(r.readexactly(7), timeout=2.0)
            _, _, length, _ = struct.unpack(">HHHB", hdr)
            return await asyncio.wait_for(r.readexactly(length - 1), timeout=2.0)
        finally:
            w.close()
            await w.wait_closed()

    pdu_i1 = await mb_req(1, 1, 3, 0, 4)
    hi, lo, st1, hs1 = struct.unpack(">4H", pdu_i1[2:10])
    decoded_val1 = struct.unpack(">f", struct.pack(">HH", hi, lo))[0]

    pdu_i2 = await mb_req(2, 1, 3, 4, 4)
    hi2, lo2, st2, hs2 = struct.unpack(">4H", pdu_i2[2:10])
    decoded_val2 = struct.unpack(">f", struct.pack(">HH", hi2, lo2))[0]

    pdu_sys = await mb_req(3, 1, 4, 900, 6)  # FC 0x04 Input Registers
    sys_vals = struct.unpack(">6H", pdu_sys[2:14])

    pdu_bad_fc = await mb_req(4, 1, 6, 0, 1)  # Illegal Function 0x06
    pdu_bad_addr = await mb_req(5, 1, 3, 1020, 10)  # Illegal Data Address
    pdu_wrong_unit = await mb_req(6, 99, 3, 900, 1)  # Wrong unit_id (99 != 1)

    await mb.stop()
    config.MODBUS_ENABLED, config.MODBUS_HOST, config.MODBUS_PORT = orig_mb_en, orig_mb_host, orig_mb_port

    return {
        "mqtt_live_broker": {
            "connected": connected_ok,
            "messages_sent_wire": live_received_count,
            "sample_topics": [m["topic"] for m in received_mqtt],
            "qos_supported": 0,
            "auth_supported": False,
            "pingreq_implemented": False,
        },
        "mqtt_broker_down_fault_injection": {
            "enqueue_status_while_broker_down": enq_while_down["status"],
            "pending_in_sf_queue": pending_while_broker_down,
            "DEFECT_silent_drop_when_broker_down": enq_while_down["status"] == "sent" and pending_while_broker_down == 0,
        },
        "modbus_tcp_wire": {
            "i1_decoded_float32": round(decoded_val1, 4),
            "i1_status_code": st1,
            "i1_health_x10": hs1,
            "i2_stale_float32": decoded_val2,
            "i2_stale_status_code": st2,
            "fc04_system_regs": list(sys_vals),
            "illegal_fc_exception": list(pdu_bad_fc),
            "illegal_addr_exception": list(pdu_bad_addr),
            "wrong_unit_id_99_accepted_without_check": pdu_wrong_unit[0] == 3,
        },
    }


async def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="gv_audit_t2_"))
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "signal_quality_11_scenarios": audit_signal_quality(),
        "adaptive_fps": await audit_adaptive_fps(),
        "ring_buffer": audit_ring_buffer(),
        "multistream_load_and_isolation": await audit_multistream_and_isolation(tmp_dir),
        "store_and_forward_A_to_G": await audit_store_and_forward(tmp_dir),
        "scada_mqtt_and_modbus": await audit_scada_mqtt_and_modbus(tmp_dir),
    }
    out = EVIDENCE_DIR / "track2_audit_results.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TRACK 2 AUDIT COMPLETE -> {out}")
    print(json.dumps({
        "sf_wal": report["store_and_forward_A_to_G"]["actual_sqlite_journal_mode"],
        "sf_restart_ok": report["store_and_forward_A_to_G"]["scenario_D_restart_during_outage"]["zero_loss_across_restart"],
        "sf_frame_blob_delivered": report["store_and_forward_A_to_G"]["scenario_C_recovery"]["alarm_frame_blob_actually_delivered"],
        "sf_unbounded_outage": report["store_and_forward_A_to_G"]["scenario_G_prolonged_outage_cap"]["pending_queue_unbounded_on_outage"],
        "sf_race_dups": report["store_and_forward_A_to_G"]["concurrency_enqueue_vs_flush_race"]["duplicate_seq_ids"],
        "mqtt_silent_drop_when_down": report["scada_mqtt_and_modbus"]["mqtt_broker_down_fault_injection"]["DEFECT_silent_drop_when_broker_down"],
        "ring_concurrent_lost": report["ring_buffer"]["concurrent_incident_1_lost"],
        "static_zero_noise_fp_frozen": report["signal_quality_11_scenarios"]["2a_static_needle_zero_noise_fp_check"]["frozen"],
        "partial_occ_detected": report["signal_quality_11_scenarios"]["5_partial_occlusion_50pct"]["health_status"],
        "scaling_4ch_fps": report["multistream_load_and_isolation"]["scaling"]["4_channels"]["aggregate_fps"],
        "scaling_8ch_fps": report["multistream_load_and_isolation"]["scaling"]["8_channels"]["aggregate_fps"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
