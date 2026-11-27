"""
Профилирование вычислительной эффективности Predictive Analytics, Modernization Optimizer,
генерации DOCX и неблокирующей работы asyncio event loop при масштабах 36, 100, 500 и 1000
логических приборов (CPU only).
"""
from __future__ import annotations

import asyncio
import csv
import datetime as _dt
import json
import math
import os
import random
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

from app.dispatch_analyzer import DispatchAnalyzer  # noqa: E402
from app.modernization_optimizer import optimize_modernization_budget  # noqa: E402
from app.predictive_analytics import PredictiveAnalyzer  # noqa: E402
from app.scada_gateway import ModbusTcpGateway  # noqa: E402
from app.spec_generator import generate_spec_bundle, render_spec_docx  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent


def make_synthetic_fleet(n: int, *, points_per_inst: int = 60, seed: int = 2026) -> tuple[list[dict], dict[str, list[tuple[float, float]]], list[dict]]:
    rng = random.Random(seed + n)
    np_rng = np.random.default_rng(seed + n)
    now = time.time()
    groups = ["Котлоагрегаты", "Турбоагрегаты", "Питательный тракт", "ГРУ", "Теплосеть", "Топливное хозяйство"]
    gtypes = [("pressure", "МПа", 0.0, 16.0, 4.0, 12.0, 13.5, 14.8),
              ("temperature", "°C", 0.0, 600.0, 200.0, 480.0, 540.0, 560.0),
              ("level", "%", 0.0, 100.0, 20.0, 35.0, 75.0, 88.0),
              ("flow", "т/ч", 0.0, 400.0, 50.0, 100.0, 320.0, 360.0)]

    instruments: list[dict] = []
    series_map: dict[str, list[tuple[float, float]]] = {}
    events: list[dict] = []
    t_grid = np.linspace(-points_per_inst, 0.0, points_per_inst) * 60.0 + now

    for i in range(n):
        gt, unit, vmin, vmax, ll, lw, hw, hh = gtypes[i % len(gtypes)]
        span = vmax - vmin
        iid = f"inst-{i:04d}"
        cam_id = f"cam-{i // 3:04d}"
        slot = i % 3
        grp = groups[i % len(groups)]
        # ~20% с выраженным дрейфом, ~10% в warning/alert
        drifting = (i % 5 == 0)
        base_v = vmin + 0.55 * span + (0.20 * span if (i % 10 == 0) else 0.0)
        slope_per_min = (0.004 * span) if drifting else 0.0
        vals = base_v + slope_per_min * ((t_grid - now) / 60.0) + np_rng.normal(0.0, 0.008 * span, size=points_per_inst)
        vals = np.clip(vals, vmin, vmax)
        cur_v = float(vals[-1])
        lv = "alert" if cur_v >= hh else ("warning" if cur_v >= hw else "normal")

        instruments.append({
            "id": iid,
            "instrument_id": iid,
            "camera_id": cam_id,
            "source_id": cam_id,
            "gauge_slot": slot,
            "modbus_slot": i if i < 200 else None,
            "code": f"P-{i+1:04d}",
            "name": f"Прибор #{i+1:04d} ({grp})",
            "short_name": f"Поз. {i+1:04d}",
            "group": grp,
            "gauge_type": gt,
            "unit": unit,
            "decimals": 2,
            "source_kind": "camera_cv",
            "status": "online",
            "calibration": {"v_min": vmin, "v_max": vmax},
            "thresholds": {"ll_alert": ll, "l_warn": lw, "h_warn": hw, "hh_alert": hh, "lower_enabled": True},
            "reading": {
                "value": cur_v,
                "valid": True,
                "level": lv,
                "confidence": 0.92,
                "ts": _dt.datetime.fromtimestamp(now, tz=_dt.timezone.utc).isoformat(timespec="milliseconds"),
                "sparkline": [round(float(v), 3) for v in vals[-24:]],
            },
        })
        series_map[iid] = list(zip(t_grid.tolist(), vals.tolist()))
        if lv in ("warning", "alert"):
            events.append({
                "id": i + 1,
                "ts": _dt.datetime.fromtimestamp(now - 600, tz=_dt.timezone.utc).isoformat(timespec="milliseconds"),
                "kind": "alarm",
                "cam_id": iid,
                "level": lv,
                "value": cur_v,
                "unit": unit,
                "text": "setpoint",
                "has_frame": False,
            })
    return instruments, series_map, events


async def measure_event_loop_isolation(
    *,
    instruments: list[dict],
    series_map: dict[str, list[tuple[float, float]]],
    disp_ov: dict[str, Any],
    pred_ov: dict[str, Any],
    mode: str,  # "blocking_sync" vs "nonblocking_executor"
) -> dict[str, Any]:
    """
    Измеряет задержку asyncio event loop (целевой тик 10 мс) во время тяжёлой оптимизации
    и прогнозного пересчёта 500–1000 приборов.
    """
    pa = PredictiveAnalyzer()
    lags_ms: list[float] = []
    done = False
    mb = ModbusTcpGateway()

    async def monitor_loop() -> None:
        nonlocal done
        period = 0.010
        expected = time.perf_counter() + period
        while not done:
            await asyncio.sleep(period)
            now_p = time.perf_counter()
            lag = max(0.0, (now_p - expected) * 1000.0)
            lags_ms.append(lag)
            expected = now_p + period

    async def telemetry_heartbeat() -> int:
        ticks = 0
        while not done:
            mb.update_from_instruments(instruments[:200], advance_heartbeat=True)
            ticks += 1
            await asyncio.sleep(0.05)
        return ticks

    mon_task = asyncio.create_task(monitor_loop())
    tel_task = asyncio.create_task(telemetry_heartbeat())
    await asyncio.sleep(0.05)

    t0 = time.perf_counter()
    if mode == "blocking_sync":
        _ = pa.overview(instruments, series_map, window_min=60.0, horizon_min=60.0)
        _ = optimize_modernization_budget(
            dispatch_overview=disp_ov,
            predictive_overview=pred_ov,
            budget_rub=5_000_000,
            include_frontier=True,
            time_limit_s=0.6,
            solver_backend="bnb",
        )
    else:
        ex = ThreadPoolExecutor(max_workers=2, thread_name_prefix="perf-analytics")
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                ex,
                lambda: pa.overview(instruments, series_map, window_min=60.0, horizon_min=60.0),
            )
            await loop.run_in_executor(
                ex,
                lambda: optimize_modernization_budget(
                    dispatch_overview=disp_ov,
                    predictive_overview=pred_ov,
                    budget_rub=5_000_000,
                    include_frontier=True,
                    time_limit_s=0.6,
                    solver_backend="bnb",
                ),
            )
        finally:
            ex.shutdown(wait=True)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    await asyncio.sleep(0.05)
    done = True
    await mon_task
    mb_ticks = await tel_task

    arr = np.array(lags_ms, dtype=float) if lags_ms else np.array([0.0])
    return {
        "mode": mode,
        "wall_ms": round(wall_ms, 2),
        "samples": len(lags_ms),
        "modbus_ticks_during_job": mb_ticks,
        "lag_p50_ms": round(float(np.percentile(arr, 50)), 2),
        "lag_p95_ms": round(float(np.percentile(arr, 95)), 2),
        "lag_max_ms": round(float(np.max(arr)), 2),
    }


async def run_all() -> None:
    proc = psutil.Process(os.getpid())
    pa = PredictiveAnalyzer()
    da = DispatchAnalyzer()
    scales = [36, 100, 500, 1000]
    rows: list[dict[str, Any]] = []

    for n in scales:
        instruments, series_map, events = make_synthetic_fleet(n, points_per_inst=60)
        da.ingest_instruments(instruments)

        # 1. Dispatch overview
        t0 = time.perf_counter()
        disp_ov = da.overview(instruments, events, {})
        disp_ms = (time.perf_counter() - t0) * 1000.0

        # 2. Predictive overview (cold) + RAM + CPU
        tracemalloc.start()
        cpu0 = proc.cpu_times()
        t0 = time.perf_counter()
        pred_ov = pa.overview(instruments, series_map, window_min=60.0, horizon_min=60.0)
        pred_ms = (time.perf_counter() - t0) * 1000.0
        cpu1 = proc.cpu_times()
        _, pred_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        pred_cpu_ms = ((cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)) * 1000.0

        # 3. Optimizer (без frontier и с frontier, air-gapped bnb, 0.8 s limit)
        tracemalloc.start()
        t0 = time.perf_counter()
        opt_nof = optimize_modernization_budget(
            dispatch_overview=disp_ov,
            predictive_overview=pred_ov,
            budget_rub=n * 35_000,
            include_frontier=False,
            time_limit_s=0.8,
            solver_backend="bnb",
        )
        opt_nof_ms = (time.perf_counter() - t0) * 1000.0
        _, opt_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        t0 = time.perf_counter()
        opt_wf = optimize_modernization_budget(
            dispatch_overview=disp_ov,
            predictive_overview=pred_ov,
            budget_rub=n * 35_000,
            include_frontier=True,
            time_limit_s=0.8,
            solver_backend="bnb",
        )
        opt_wf_ms = (time.perf_counter() - t0) * 1000.0

        # 4. Spec Bundle + DOCX generation (для выбранного оптимального плана)
        sel_ids = [x["instrument_id"] for x in opt_nof.get("selected") or []][:25]
        t0 = time.perf_counter()
        bundle = await generate_spec_bundle(
            dispatch_overview=disp_ov,
            events=events,
            snapshot_lookup={},
            period="12h",
            mode="deterministic",
            predictive_overview=pred_ov,
            optimization_result=opt_nof,
            selected_instrument_ids=sel_ids or None,
            strict_scope=False,
        )
        docx_bytes = render_spec_docx(bundle)
        spec_docx_ms = (time.perf_counter() - t0) * 1000.0

        rss_mb = proc.memory_info().rss / (1024.0 * 1024.0)
        row = {
            "instruments": n,
            "dispatch_ms": round(disp_ms, 2),
            "predictive_ms": round(pred_ms, 2),
            "predictive_per_inst_ms": round(pred_ms / n, 3),
            "predictive_cpu_ms": round(pred_cpu_ms, 2),
            "predictive_peak_ram_kb": round(pred_peak / 1024.0, 1),
            "opt_candidates": opt_nof["summary"]["candidates_total"],
            "opt_no_frontier_ms": round(opt_nof_ms, 2),
            "opt_no_frontier_status": opt_nof["status"],
            "opt_no_frontier_gap_pct": round(opt_nof["solver"]["optimality_gap"] * 100.0, 4),
            "opt_with_frontier_ms": round(opt_wf_ms, 2),
            "opt_peak_ram_kb": round(opt_peak / 1024.0, 1),
            "spec_and_docx_ms": round(spec_docx_ms, 2),
            "docx_kb": round(len(docx_bytes) / 1024.0, 1),
            "process_rss_mb": round(rss_mb, 1),
        }
        rows.append(row)
        print(
            f"N={n:4d} | disp={row['dispatch_ms']:6.1f}ms | pred={row['predictive_ms']:7.1f}ms ({row['predictive_per_inst_ms']:.2f}ms/inst) | "
            f"opt={row['opt_no_frontier_ms']:6.1f}ms ({row['opt_no_frontier_status']}) | docx={row['spec_and_docx_ms']:6.1f}ms ({row['docx_kb']}KB) | RSS={row['process_rss_mb']}MB",
            flush=True,
        )

    # 5. Event loop isolation test at N = 500 (BEFORE sync vs AFTER ThreadPoolExecutor)
    inst500, smap500, ev500 = make_synthetic_fleet(500, points_per_inst=60)
    da.ingest_instruments(inst500)
    disp500 = da.overview(inst500, ev500, {})
    pred500 = pa.overview(inst500, smap500, window_min=60.0, horizon_min=60.0)
    el_blocking = await measure_event_loop_isolation(
        instruments=inst500, series_map=smap500, disp_ov=disp500, pred_ov=pred500, mode="blocking_sync"
    )
    el_nonblock = await measure_event_loop_isolation(
        instruments=inst500, series_map=smap500, disp_ov=disp500, pred_ov=pred500, mode="nonblocking_executor"
    )
    print("EVENT LOOP BLOCKING (sync):", el_blocking, flush=True)
    print("EVENT LOOP NON-BLOCKING (executor):", el_nonblock, flush=True)

    # 6. API Latency & Predictive Cache Speedup test (FastAPI TestClient on real 36-gauge demo)
    import tempfile
    from fastapi.testclient import TestClient

    api_bench: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="gv_perf_api_") as tmp:
        orig_env = {k: os.environ.get(k) for k in ("GAUGEVISION_DEMO", "GAUGEVISION_DB", "GAUGEVISION_SF_DB", "GAUGEVISION_AUTH_REQUIRED")}
        os.environ["GAUGEVISION_DEMO"] = "1"
        os.environ["GAUGEVISION_DB"] = str(Path(tmp) / "perf.db")
        os.environ["GAUGEVISION_SF_DB"] = str(Path(tmp) / "perf_sf.db")
        os.environ["GAUGEVISION_AUTH_REQUIRED"] = "0"
        try:
            from app import config, main as gv_main
            config.configure_runtime(demo=True, db_path=os.environ["GAUGEVISION_DB"], device="cpu")
            with TestClient(gv_main.app) as client:
                gv_main.service._predictive_cache.clear()
                t0 = time.perf_counter()
                r1 = client.get("/api/predictive/overview?window_min=60&horizon_min=60")
                cold_ms = (time.perf_counter() - t0) * 1000.0
                assert r1.status_code == 200

                warm_times = []
                for _ in range(10):
                    tw = time.perf_counter()
                    rw = client.get("/api/predictive/overview?window_min=60&horizon_min=60")
                    warm_times.append((time.perf_counter() - tw) * 1000.0)
                    assert rw.status_code == 200

                to = time.perf_counter()
                ro = client.post("/api/optimizer/solve", json={"budget_rub": 350_000, "objective": "weighted_utility"})
                opt_api_ms = (time.perf_counter() - to) * 1000.0
                assert ro.status_code == 200

                th = time.perf_counter()
                rh = client.get("/api/health")
                health_ms = (time.perf_counter() - th) * 1000.0
                assert rh.status_code == 200

                api_bench = {
                    "predictive_overview_cold_ms": round(cold_ms, 2),
                    "predictive_overview_cached_p50_ms": round(float(np.median(warm_times)), 2),
                    "predictive_cache_speedup_x": round(cold_ms / max(0.01, float(np.median(warm_times))), 1),
                    "optimizer_solve_api_ms": round(opt_api_ms, 2),
                    "health_api_ms": round(health_ms, 2),
                }
        finally:
            for k, v in orig_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    print("API BENCH:", api_bench, flush=True)

    payload = {
        "scales": rows,
        "event_loop_isolation_n500": {
            "before_blocking_sync": el_blocking,
            "after_nonblocking_executor": el_nonblock,
        },
        "api_benchmark_36_gauges": api_bench,
    }
    (OUT_DIR / "performance_profile.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT_DIR / "performance_scales.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("SAVED performance evidence to", OUT_DIR)


if __name__ == "__main__":
    asyncio.run(run_all())
