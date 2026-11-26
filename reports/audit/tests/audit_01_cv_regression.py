"""
Independent Audit Script 01 — Computer Vision Regression & Accuracy Verification (Section 7).
Read-only against production code. Runs strictly on CPU (CUDA_VISIBLE_DEVICES="").
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
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

config.configure_runtime(demo=True, device="cpu")


def make_synthetic_gauge(
    value: float | None,
    v_min: float = 0.0,
    v_max: float = 16.0,
    theta_min: float = 135.0,
    theta_max: float = 45.0,
    direction: str = "cw",
    width: int = 800,
    height: int = 600,
    cx: int | None = None,
    cy: int | None = None,
    r_dial: int = 200,
    tilt_x: float = 1.0,
    glare: bool = False,
    partial_occlude: bool = False,
    blank: bool = False,
    second_gauge: bool = False,
) -> np.ndarray:
    img = np.full((height, width, 3), (32, 36, 40), dtype=np.uint8)
    if blank:
        return img

    def draw_one(ccx: int, ccy: int, rr: int, val: float | None) -> None:
        cv2.circle(img, (ccx, ccy), rr + 18, (86, 92, 100), -1, cv2.LINE_AA)
        cv2.circle(img, (ccx, ccy), rr, (238, 240, 238), -1, cv2.LINE_AA)
        cv2.circle(img, (ccx, ccy), rr, (45, 50, 55), 2, cv2.LINE_AA)

        span_deg = ((theta_max - theta_min) % 360.0) if direction == "cw" else ((theta_min - theta_max) % 360.0)
        for i in range(51):
            f = i / 50.0
            deg = (theta_min + f * span_deg) % 360.0 if direction == "cw" else (theta_min - f * span_deg) % 360.0
            rad = math.radians(deg)
            r1 = rr - 10
            r0 = rr - (26 if i % 5 == 0 else 16)
            cv2.line(
                img,
                (int(ccx + r0 * math.cos(rad)), int(ccy + r0 * math.sin(rad))),
                (int(ccx + r1 * math.cos(rad)), int(ccy + r1 * math.sin(rad))),
                (30, 32, 35),
                2 if i % 5 == 0 else 1,
                cv2.LINE_AA,
            )

        if val is not None:
            frac = (val - v_min) / (v_max - v_min)
            deg = (theta_min + frac * span_deg) % 360.0 if direction == "cw" else (theta_min - frac * span_deg) % 360.0
            rad = math.radians(deg)
            c, s = math.cos(rad), math.sin(rad)
            nc, ns = -s, c
            tip = (ccx + c * (rr - 22), ccy + s * (rr - 22))
            tail = (ccx - c * 32, ccy - s * 32)
            pts = np.array([
                [tip[0], tip[1]],
                [ccx + nc * 4.5, ccy + ns * 4.5],
                [tail[0] + nc * 6.0, tail[1] + ns * 6.0],
                [tail[0] - nc * 6.0, tail[1] - ns * 6.0],
                [ccx - nc * 4.5, ccy - ns * 4.5],
            ], dtype=np.int32)
            cv2.fillConvexPoly(img, pts, (16, 18, 22), cv2.LINE_AA)
            cv2.circle(img, (ccx, ccy), 10, (24, 28, 32), -1, cv2.LINE_AA)

    if second_gauge:
        draw_one(int(width * 0.28), height // 2, int(r_dial * 0.72), value)
        draw_one(int(width * 0.72), height // 2, int(r_dial * 0.72), (v_min + v_max) * 0.25)
    else:
        draw_one(cx if cx is not None else width // 2, cy if cy is not None else height // 2, r_dial, value)

    if tilt_x < 0.99:
        # Simulate perspective foreshortening along X
        src = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
        dx = width * (1.0 - tilt_x) * 0.5
        dst = np.float32([[dx, 20], [width - dx, 0], [width - dx * 0.7, height], [dx * 0.7, height - 20]])
        M = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(img, M, (width, height), borderValue=(32, 36, 40))

    if glare:
        cv2.circle(img, (int(width * 0.54), int(height * 0.45)), int(r_dial * 0.42), (253, 253, 253), -1)
        img = cv2.GaussianBlur(img, (15, 15), 5.0)

    if partial_occlude:
        cv2.rectangle(img, (0, 0), (int(width * 0.44), height), (14, 16, 18), -1)

    return img


def run_audit() -> dict:
    results: dict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device_policy": "cpu_only (hardware safety)",
        "weights_path": str(config.YOLO_WEIGHTS),
        "weights_exists": config.YOLO_WEIGHTS.exists(),
    }

    t0 = time.perf_counter()
    yolo_ok = vision.yolo_available()
    results["yolo_load_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    results["yolo_available"] = yolo_ok
    results["yolo_device"] = vision.yolo_device()

    # Check git diff vs baseline dd25bde for app/vision.py
    try:
        diff = subprocess.check_output(
            ["git", "-C", str(REPO), "diff", "--stat", "dd25bde", "--", "app/vision.py"],
            text=True,
        ).strip()
        results["vision_git_diff_vs_baseline"] = diff or "no diff"
    except Exception as exc:
        results["vision_git_diff_vs_baseline"] = f"error: {exc}"

    # 1. CW sweep (0..16 MPa, crossing 0/360)
    cal_cw = {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"}
    thr_cw = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}
    sweep_vals = [0.0, 1.0, 2.0, 3.0, 4.0, 5.5, 7.0, 8.0, 9.5, 11.0, 12.5, 13.0, 14.0, 14.7, 15.2, 15.7, 16.0]
    cw_rows = []
    errors = []
    latencies = []
    missed = 0
    for v_true in sweep_vals:
        pipe = vision.GaugePipeline("audit-cw")  # fresh pipe to measure raw non-EMA accuracy
        frame = make_synthetic_gauge(v_true, **cal_cw)
        r = pipe.process(frame, cal_cw, thr_cw, "МПа", with_overlay=True)
        latencies.append(r.process_ms)
        err = None if r.value is None else abs(r.value - v_true)
        if not r.valid or r.value is None:
            missed += 1
        else:
            errors.append(err)
        cw_rows.append({
            "true": v_true,
            "pred": None if r.value is None else round(r.value, 4),
            "abs_err": None if err is None else round(err, 4),
            "angle": r.angle,
            "valid": r.valid,
            "conf": r.needle_confidence,
            "dial_source": r.dial_source,
            "method": r.debug.get("needle_method"),
            "level": r.status_level,
            "process_ms": r.process_ms,
        })

    mae_cw = round(sum(errors) / len(errors), 4) if errors else None
    rmse_cw = round(math.sqrt(sum(e * e for e in errors) / len(errors)), 4) if errors else None
    results["cw_sweep_0_16_mpa"] = {
        "n_total": len(sweep_vals),
        "n_valid": len(errors),
        "n_missed": missed,
        "mae_mpa": mae_cw,
        "rmse_mpa": rmse_cw,
        "mae_pct_fs": round(mae_cw / 16.0 * 100.0, 3) if mae_cw is not None else None,
        "max_err_mpa": round(max(errors), 4) if errors else None,
        "avg_ms": round(sum(latencies) / len(latencies), 1),
        "p95_ms": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1),
        "samples": cw_rows,
    }

    # 2. CCW scale (0..100 %)
    cal_ccw = {"v_min": 0.0, "theta_min": 45.0, "v_max": 100.0, "theta_max": 135.0, "direction": "ccw"}
    thr_ccw = {"ll_alert": 10.0, "l_warn": 20.0, "h_warn": 80.0, "hh_alert": 90.0, "lower_enabled": True}
    ccw_errs = []
    ccw_rows = []
    for v_true in (10.0, 35.0, 50.0, 75.0, 92.0):
        pipe = vision.GaugePipeline("audit-ccw")
        frame = make_synthetic_gauge(v_true, **cal_ccw)
        r = pipe.process(frame, cal_ccw, thr_ccw, "%", with_overlay=False)
        err = None if r.value is None else abs(r.value - v_true)
        if err is not None:
            ccw_errs.append(err)
        ccw_rows.append({"true": v_true, "pred": r.value, "err": err, "valid": r.valid, "conf": r.needle_confidence})
    results["ccw_scale"] = {
        "n_valid": len(ccw_errs),
        "mae_pct": round(sum(ccw_errs) / len(ccw_errs), 3) if ccw_errs else None,
        "samples": ccw_rows,
    }

    # 3. Negative range (-100..0 kPa)
    cal_neg = {"v_min": -100.0, "theta_min": 135.0, "v_max": 0.0, "theta_max": 45.0, "direction": "cw"}
    thr_neg = {"ll_alert": -96.0, "l_warn": -92.0, "h_warn": -15.0, "hh_alert": -8.0, "lower_enabled": True}
    neg_errs = []
    neg_rows = []
    for v_true in (-95.0, -75.0, -50.0, -25.0, -5.0):
        pipe = vision.GaugePipeline("audit-neg")
        frame = make_synthetic_gauge(v_true, **cal_neg)
        r = pipe.process(frame, cal_neg, thr_neg, "кПа", with_overlay=False)
        err = None if r.value is None else abs(r.value - v_true)
        if err is not None:
            neg_errs.append(err)
        neg_rows.append({"true": v_true, "pred": r.value, "err": err, "valid": r.valid, "level": r.status_level})
    results["negative_range"] = {
        "n_valid": len(neg_errs),
        "mae_kpa": round(sum(neg_errs) / len(neg_errs), 3) if neg_errs else None,
        "samples": neg_rows,
    }

    # 4. Robustness edge cases (blank, dead zone, perspective tilt, glare, partial occlusion, multi-gauge)
    edge_cases = {}

    # 4a. Blank frame
    pipe = vision.GaugePipeline("audit-blank")
    r_blank = pipe.process(make_synthetic_gauge(None, blank=True), cal_cw, thr_cw, "МПа", with_overlay=False)
    edge_cases["blank_frame"] = {
        "valid": r_blank.valid,
        "dial_found": r_blank.dial_found,
        "value": r_blank.value,
        "conf": r_blank.needle_confidence,
    }

    # 4b. Dead zone (angle 90 deg = bottom dead zone between 45 deg and 135 deg)
    dead_val = vision.angle_to_value(90.0, cal_cw)
    edge_cases["dead_zone_90deg"] = {"value": dead_val, "rejected_as_none": dead_val is None}

    # 4c. Perspective tilt (0.72 aspect)
    pipe = vision.GaugePipeline("audit-tilt")
    r_tilt = pipe.process(make_synthetic_gauge(12.0, tilt_x=0.72, **cal_cw), cal_cw, thr_cw, "МПа", with_overlay=False)
    edge_cases["perspective_tilt_072"] = {
        "true": 12.0,
        "pred": r_tilt.value,
        "abs_err": None if r_tilt.value is None else round(abs(r_tilt.value - 12.0), 3),
        "valid": r_tilt.valid,
        "dial_source": r_tilt.dial_source,
        "conf": r_tilt.needle_confidence,
    }

    # 4d. Strong glare
    pipe = vision.GaugePipeline("audit-glare")
    r_glare = pipe.process(make_synthetic_gauge(12.0, glare=True, **cal_cw), cal_cw, thr_cw, "МПа", with_overlay=False)
    edge_cases["glare"] = {
        "true": 12.0,
        "pred": r_glare.value,
        "abs_err": None if r_glare.value is None else round(abs(r_glare.value - 12.0), 3),
        "valid": r_glare.valid,
        "dial_source": r_glare.dial_source,
        "conf": r_glare.needle_confidence,
    }

    # 4e. Partial occlusion (44% left side blocked)
    pipe = vision.GaugePipeline("audit-occ")
    r_occ = pipe.process(make_synthetic_gauge(12.0, partial_occlude=True, **cal_cw), cal_cw, thr_cw, "МПа", with_overlay=False)
    edge_cases["partial_occlusion_44pct"] = {
        "true": 12.0,
        "pred": r_occ.value,
        "abs_err": None if r_occ.value is None else round(abs(r_occ.value - 12.0), 3),
        "valid": r_occ.valid,
        "dial_source": r_occ.dial_source,
        "conf": r_occ.needle_confidence,
    }

    # 4f. Multiple gauges in one frame
    pipe = vision.GaugePipeline("audit-multi")
    frame_multi = make_synthetic_gauge(12.0, second_gauge=True, **cal_cw)
    r_multi = pipe.process(frame_multi, cal_cw, thr_cw, "МПа", with_overlay=False)
    edge_cases["two_gauges_in_single_frame"] = {
        "note": "GaugePipeline returns a single GaugeReading (largest bbox/ellipse); multi-gauge-per-frame is NOT supported.",
        "pred": r_multi.value,
        "valid": r_multi.valid,
        "dial_source": r_multi.dial_source,
        "roi_center": r_multi.debug.get("roi", {}).get("center"),
    }

    # 4g. EMA smoothing check across step 8.0 -> 14.0
    pipe = vision.GaugePipeline("audit-ema")
    ema_seq = []
    for v in (8.0, 8.0, 14.0, 14.0, 14.0, 14.0):
        r = pipe.process(make_synthetic_gauge(v, **cal_cw), cal_cw, thr_cw, "МПа", with_overlay=False)
        ema_seq.append({"true": v, "raw": r.value, "ema": None if r.ema_value is None else round(r.ema_value, 3)})
    edge_cases["ema_step_response"] = ema_seq

    results["edge_cases"] = edge_cases

    out_path = EVIDENCE_DIR / "cv_regression_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CV AUDIT COMPLETE -> {out_path}")
    print(json.dumps({
        "yolo_available": results["yolo_available"],
        "yolo_load_ms": results["yolo_load_ms"],
        "cw_mae_mpa": results["cw_sweep_0_16_mpa"]["mae_mpa"],
        "cw_rmse_mpa": results["cw_sweep_0_16_mpa"]["rmse_mpa"],
        "cw_missed": results["cw_sweep_0_16_mpa"]["n_missed"],
        "ccw_mae_pct": results["ccw_scale"]["mae_pct"],
        "neg_mae_kpa": results["negative_range"]["mae_kpa"],
        "tilt_err": edge_cases["perspective_tilt_072"]["abs_err"],
        "glare_err": edge_cases["glare"]["abs_err"],
        "occ_err": edge_cases["partial_occlusion_44pct"]["abs_err"],
        "blank_valid": edge_cases["blank_frame"]["valid"],
    }, ensure_ascii=False, indent=2))
    return results


if __name__ == "__main__":
    run_audit()
