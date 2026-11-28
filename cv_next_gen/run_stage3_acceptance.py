"""
GaugeVision AI 3.1 — Стадия III: Финальная регрессия (15 наборов) и бенчмарк Multi-Gauge 1/2/4/8/16.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import subprocess
import sys
import time

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ.setdefault("YOLO_OFFLINE", "1")

import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
OUT_DIR = REPO_ROOT / "reports" / "comprehensive_improvement" / "evidence"


def run_regression_15() -> dict:
    tests = [
        "tests/test_instruments_db.py",
        "tests/test_multigauge.py",
        "tests/test_multigauge_api.py",
        "tests/test_autocal.py",
        "tests/test_demo_dashboard.py",
        "tests/test_tracks_e2e.py",
        "tests/test_remediation_full.py",
        "tests/test_acceptance_independent.py",
        "tests/test_modbus_register_map.py",
        "tests/test_predictive_analytics.py",
        "tests/test_modernization_optimizer.py",
        "tests/test_next_gen_integration_contract.py",
        "tests/test_final_integration.py",
        "tests/test_cv_next_gen.py",
        "tests/test_security_hardening_v31.py",
    ]
    rows = []
    for t in tests:
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, "-B", t], cwd=str(REPO_ROOT), capture_output=True, text=True)
        dt = round(time.perf_counter() - t0, 2)
        ok = p.returncode == 0
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {t:45s} ({dt:5.1f}s)", flush=True)
        rows.append({
            "test": t,
            "passed": ok,
            "returncode": p.returncode,
            "elapsed_s": dt,
            "tail": (p.stdout + "\n" + p.stderr)[-400:],
        })
    passed = sum(1 for r in rows if r["passed"])
    summary = {"commit": "1de2067", "passed": passed, "total": len(rows), "results": rows}
    (OUT_DIR / "regression_15_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REGRESSION TOTAL: {passed}/{len(rows)} PASS", flush=True)
    return summary


def run_multigauge_bench() -> dict:
    from app import vision
    from cv_next_gen.synthetic_generator import render_dial_sample

    out: dict = {}
    for prof in ("legacy", "eco", "balanced", "precision"):
        vision.set_vision_profile(prof)
        out[prof] = {}
        for n in (1, 2, 4, 8, 16):
            cols = math.ceil(math.sqrt(n))
            rows = math.ceil(n / cols)
            cell = 260
            canvas = np.full((rows * cell, cols * cell, 3), 210, dtype=np.uint8)
            pipes, calibs, rois, gts = [], [], [], []
            for i in range(n):
                img, _, meta = render_dial_sample(size=240, template_id=800 + i, seed=5000 + n * 100 + i, hard_mode=False)
                r, c = divmod(i, cols)
                y0, x0 = r * cell + 10, c * cell + 10
                canvas[y0 : y0 + 240, x0 : x0 + 240] = img
                cx_m, cy_m = meta["center"]
                pmin, pmax = meta["scale_min_pt"], meta["scale_max_pt"]
                th_min = math.degrees(math.atan2(pmin[1] - cy_m, pmin[0] - cx_m)) % 360.0
                th_max = math.degrees(math.atan2(pmax[1] - cy_m, pmax[0] - cx_m)) % 360.0
                rois.append(vision.roi_from_ellipse(x0 + cx_m, y0 + cy_m, 108.0, 108.0, 0.0, 1.0, "manual"))
                calibs.append({
                    "v_min": float(meta["v_min"]),
                    "v_max": float(meta["v_max"]),
                    "theta_min": round(th_min, 2),
                    "theta_max": round(th_max, 2),
                    "direction": str(meta["direction"]),
                })
                gts.append((float(meta["value"]), abs(float(meta["v_max"]) - float(meta["v_min"]))))
                pipes.append(vision.GaugePipeline(f"mg-{n}-{i}"))
            # Прогрев нейросетей на первом проходе
            if n == 1:
                _ = pipes[0].process(canvas, calibs[0], {}, "MPa", with_overlay=False, roi_override=rois[0])
            t0 = time.perf_counter()
            errs, valid = [], 0
            for p, cal, roi, (gt, span) in zip(pipes, calibs, rois, gts):
                rd = p.process(canvas, cal, {}, "MPa", with_overlay=False, roi_override=roi)
                if rd.valid and rd.value is not None:
                    valid += 1
                    errs.append(abs(rd.value - gt) / max(span, 1e-6) * 100.0)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            out[prof][str(n)] = {
                "total_ms": round(dt_ms, 1),
                "per_gauge_ms": round(dt_ms / n, 1),
                "fps_est": round(1000.0 / max(dt_ms, 1.0), 2),
                "valid_n": valid,
                "mae_pct": round(float(np.mean(errs)), 2) if errs else None,
            }
        print(f"MG {prof:10s}: " + ", ".join(f"n={k}:{v['total_ms']:.0f}ms({v['valid_n']}/{k},MAE={v['mae_pct']}%)" for k, v in out[prof].items()), flush=True)
    vision.set_vision_profile("legacy")
    (OUT_DIR / "multigauge_1_2_4_8_16.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_multigauge_bench()
    run_regression_15()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
