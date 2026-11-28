"""
GaugeVision AI 3.1 — Парное сравнение локализатора `detect_dial_v31` и Seg-primary Fusion.

Сравнивает:
  1. legacy_v8         — GaugeVision AI 3.0 (исходный detect_dial + OpenCV v8);
  2. v31_eco_newdet    — detect_dial_v31 + OpenCV v2;
  3. v31_prec_olddet   — исходный detect_dial + Seg-primary Fusion;
  4. v31_prec_newdet   — detect_dial_v31 + Seg-primary Fusion;
  5. v31_seg_newdet    — detect_dial_v31 + NeedleSegUNet (быстрый режим).

Дополнительно строит кривую Risk-Coverage (доля принимаемых показаний vs MAE/gross)
и проверяет корректный отказ на `unusable` (n=300) и `LOCKED MeasureBench non-dial` (n=120).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import random
import tempfile
import time
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ.setdefault("YOLO_OFFLINE", "1")

import cv2
import numpy as np

from .eval_compare import (
    LEGACY_MANIFEST_PATH,
    MANIFEST_PATH,
    MB_DIR,
    METERFL_DIR,
    _gt_value,
    _img_path,
    _theta_through_roi,
    summarize_rows,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "reports" / "comprehensive_improvement" / "evidence" / "cv"


def _eval_one_roi(frame, rec, k, roi, vision, config):
    sc = lambda pt: (float(pt[0]) * k, float(pt[1]) * k)
    first, last = sc(rec["first_tick"]), sc(rec["last_tick"])
    gt_c = sc(rec["center"]) if rec.get("center") else None
    r_gt = float(rec["tick_radius"]) * k if rec.get("tick_radius") else (
        0.5 * (math.dist(first, gt_c) + math.dist(last, gt_c)) if gt_c else None
    )
    det_ok = False
    if gt_c and r_gt:
        c_err = math.dist(roi.center, gt_c) / r_gt
        ax_rat = max(roi.axes) / r_gt
        det_ok = bool(roi.source != "frame" and c_err <= 0.25 and 0.7 <= ax_rat <= 2.2)

    v_min = float(rec["scale_min"]) if rec.get("scale_min") is not None else 0.0
    v_max = float(rec["scale_max"]) if rec.get("scale_max") is not None else 1.0
    if rec.get("gt_origin") == "mask_proxy":
        v_min, v_max = 0.0, 1.0
    calib = {
        "v_min": v_min, "v_max": v_max,
        "theta_min": round(_theta_through_roi(roi, first, config.DIAL_SIZE), 2),
        "theta_max": round(_theta_through_roi(roi, last, config.DIAL_SIZE), 2),
        "direction": rec.get("direction") or "cw",
    }
    dial = vision.normalize_dial(frame, roi)
    suitable, inv_reason, _ = vision.assess_dial_suitability(dial)
    arc = vision.needle_search_arc(calib)
    work_arc = vision.needle_search_arc(calib, margin=0.0)
    scale_ok = True
    if suitable and work_arc is not None:
        gap, cov, coh = vision.scale_arc_evidence(dial, work_arc)
        if gap >= vision.SCALE_GAP_MAX or cov < vision.SCALE_COVERAGE_MIN or coh < vision.SCALE_COHERENCE_MIN:
            scale_ok = False
    return det_ok, calib, dial, suitable, inv_reason, arc, scale_ok


def _score_reading(ang, ok, conf, reason, calib, rec, vision, det_ok, needle_ms, det_ms):
    kind, gt = _gt_value(rec)
    span = abs(calib["v_max"] - calib["v_min"])
    val = vision.angle_to_value(ang, calib) if (ok and ang is not None) else None
    valid = val is not None
    err_norm = None
    if valid and kind != "none" and span > 0:
        if kind == "interval":
            lo, hi = gt
            err = 0.0 if lo <= val <= hi else min(abs(val - lo), abs(val - hi))
        else:
            err = abs(val - gt)
        err_norm = err / span
    return {
        "file": rec["file"],
        "model": rec.get("instrument_group"),
        "source": rec.get("source"),
        "det_ok": det_ok,
        "valid": valid,
        "confidence": round(conf, 4),
        "err_norm": None if err_norm is None else round(err_norm, 5),
        "invalid_reason": None if valid else (reason or "out_of_scale"),
        "needle_ms": round(needle_ms, 2),
        "det_ms": round(det_ms, 2),
    }


def risk_coverage_curve(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(rows)
    if n == 0:
        return []
    out = []
    for thr in (0.30, 0.45, 0.55, 0.65, 0.75, 0.85):
        sel = [r for r in rows if r["valid"] and r["err_norm"] is not None and r["confidence"] >= thr]
        errs = [r["err_norm"] for r in sel]
        out.append({
            "conf_thr": thr,
            "coverage_pct": round(100.0 * len(sel) / n, 2),
            "mae_pct": round(100.0 * float(np.mean(errs)), 2) if errs else None,
            "p95_pct": round(100.0 * float(np.percentile(errs, 95)), 2) if errs else None,
            "gross_pct": round(100.0 * float(np.mean(np.array(errs) > 0.10)), 2) if errs else None,
        })
    return out


def eval_subset(items, vision, config, kpt_est, seg_est, fusion_prec, opencv_v2, detect_dial_v31):
    methods = ["legacy_v8", "v31_prec_olddet", "v31_eco_newdet", "v31_seg_newdet", "v31_prec_newdet"]
    results: dict[str, list[dict[str, Any]]] = {m: [] for m in methods}

    for i, rec in enumerate(items):
        frame = cv2.imread(str(_img_path(rec)))
        if frame is None:
            continue
        h0, w0 = frame.shape[:2]
        k = 1.0
        if w0 > config.MAX_PROCESS_WIDTH:
            k = config.MAX_PROCESS_WIDTH / float(w0)
            frame = cv2.resize(frame, (int(w0 * k), int(h0 * k)), interpolation=cv2.INTER_AREA)

        t_d0 = time.perf_counter()
        roi_old = vision.detect_dial(frame) or vision.frame_roi(frame)
        dt_old = (time.perf_counter() - t_d0) * 1000.0

        t_d1 = time.perf_counter()
        roi_new = detect_dial_v31(frame, seg_est=seg_est) or vision.frame_roi(frame)
        dt_new = (time.perf_counter() - t_d1) * 1000.0

        det_ok_o, cal_o, dial_o, suit_o, rsn_o, arc_o, sc_o = _eval_one_roi(frame, rec, k, roi_old, vision, config)
        det_ok_n, cal_n, dial_n, suit_n, rsn_n, arc_n, sc_n = _eval_one_roi(frame, rec, k, roi_new, vision, config)

        # 1. legacy_v8
        t0 = time.perf_counter()
        ang, conf, ok, rsn = None, 0.0, False, rsn_o
        if suit_o and sc_o:
            nr = vision.estimate_needle(dial_o, arc_o)
            conf = nr.confidence
            if nr.angle_deg is not None and conf >= config.MIN_NEEDLE_CONFIDENCE and not (nr.method.startswith("moment/") and conf < 0.45):
                ang, ok = nr.angle_deg, True
        elif suit_o:
            rsn = "scale_not_visible"
        results["legacy_v8"].append(_score_reading(ang, ok, conf, rsn, cal_o, rec, vision, det_ok_o, (time.perf_counter() - t0) * 1000.0, dt_old))

        # 2. v31_prec_olddet
        t0 = time.perf_counter()
        ang, conf, ok, rsn = None, 0.0, False, rsn_o
        if suit_o:
            nr = fusion_prec.estimate(dial_o, arc_o, use_kpt=True, use_seg=True, use_opencv=True)
            conf = nr.confidence
            if nr.valid and nr.angle_deg is not None:
                ang, ok = nr.angle_deg, True
            else:
                rsn = nr.reject_reason or "fusion_rejected"
        results["v31_prec_olddet"].append(_score_reading(ang, ok, conf, rsn, cal_o, rec, vision, det_ok_o, (time.perf_counter() - t0) * 1000.0, dt_old))

        # 3. v31_eco_newdet
        t0 = time.perf_counter()
        ang, conf, ok, rsn = None, 0.0, False, rsn_n
        if suit_n and sc_n:
            nr = opencv_v2.estimate(dial_n, arc_n)
            conf = nr.confidence
            if nr.valid and nr.angle_deg is not None and not (nr.method.startswith("opencv_v2:moment/") and conf < 0.45):
                ang, ok = nr.angle_deg, True
        elif suit_n:
            rsn = "scale_not_visible"
        results["v31_eco_newdet"].append(_score_reading(ang, ok, conf, rsn, cal_n, rec, vision, det_ok_n, (time.perf_counter() - t0) * 1000.0, dt_new))

        # 4. v31_seg_newdet
        t0 = time.perf_counter()
        ang, conf, ok, rsn = None, 0.0, False, rsn_n
        if suit_n:
            nr = seg_est.estimate(dial_n)
            conf = nr.confidence
            if nr.valid and nr.angle_deg is not None and conf >= 0.30:
                ang, ok = nr.angle_deg, True
            else:
                rsn = nr.reject_reason or "seg_low_conf"
        results["v31_seg_newdet"].append(_score_reading(ang, ok, conf, rsn, cal_n, rec, vision, det_ok_n, (time.perf_counter() - t0) * 1000.0, dt_new))

        # 5. v31_prec_newdet
        t0 = time.perf_counter()
        ang, conf, ok, rsn = None, 0.0, False, rsn_n
        if suit_n:
            nr = fusion_prec.estimate(dial_n, arc_n, use_kpt=True, use_seg=True, use_opencv=True)
            conf = nr.confidence
            if nr.valid and nr.angle_deg is not None:
                ang, ok = nr.angle_deg, True
            else:
                rsn = nr.reject_reason or "fusion_rejected"
        results["v31_prec_newdet"].append(_score_reading(ang, ok, conf, rsn, cal_n, rec, vision, det_ok_n, (time.perf_counter() - t0) * 1000.0, dt_new))

        if (i + 1) % 100 == 0:
            print(f"  processed {i+1}/{len(items)}", flush=True)
    return results


def eval_unusable(vision, config, kpt_est, seg_est, fusion_prec, opencv_v2, detect_dial_v31):
    from reports.industrial_validation.tests.eval_cv_pipeline import build_unusable, degrade_frame

    leg_man = json.loads(LEGACY_MANIFEST_PATH.read_text(encoding="utf-8"))
    jobs = build_unusable(leg_man, MB_DIR, n_per_kind=60, seed=0, role="primary")
    rng = random.Random(1)
    methods = ["v31_eco_newdet", "v31_seg_newdet", "v31_prec_newdet"]
    rejects: dict[str, dict[str, list[int]]] = {m: {} for m in methods}

    for rec, kind in jobs:
        p = (METERFL_DIR / "data" / rec["client"] / rec["side"] / rec["file"]) if rec["dataset"] == "MeterFL" else (MB_DIR / "img" / rec["file"])
        frame = cv2.imread(str(p))
        if frame is None:
            continue
        if kind and not kind.startswith("non_dial"):
            frame = degrade_frame(frame, rec, kind, rng)
        h0, w0 = frame.shape[:2]
        k = 1.0
        if w0 > config.MAX_PROCESS_WIDTH:
            k = config.MAX_PROCESS_WIDTH / float(w0)
            frame = cv2.resize(frame, (int(w0 * k), int(h0 * k)), interpolation=cv2.INTER_AREA)
        roi = detect_dial_v31(frame, seg_est=seg_est) or vision.frame_roi(frame)
        sc = lambda pt: (float(pt[0]) * k, float(pt[1]) * k)
        calib = {
            "v_min": 0.0, "v_max": 100.0,
            "theta_min": round(_theta_through_roi(roi, sc(rec["first_tick"]), config.DIAL_SIZE), 2),
            "theta_max": round(_theta_through_roi(roi, sc(rec["last_tick"]), config.DIAL_SIZE), 2),
            "direction": "cw",
        }
        dial = vision.normalize_dial(frame, roi)
        suitable, _, _ = vision.assess_dial_suitability(dial)
        arc = vision.needle_search_arc(calib)
        work_arc = vision.needle_search_arc(calib, margin=0.0)
        scale_ok = True
        if suitable and work_arc is not None:
            gap, cov, coh = vision.scale_arc_evidence(dial, work_arc)
            if gap >= vision.SCALE_GAP_MAX or cov < vision.SCALE_COVERAGE_MIN or coh < vision.SCALE_COHERENCE_MIN:
                scale_ok = False
        for m in methods:
            acc = False
            if suitable and scale_ok:
                if m == "v31_eco_newdet":
                    nr = opencv_v2.estimate(dial, arc)
                    if nr.valid and nr.angle_deg is not None and not (nr.method.startswith("opencv_v2:moment/") and nr.confidence < 0.45):
                        acc = vision.angle_to_value(nr.angle_deg, calib) is not None
                elif m == "v31_seg_newdet":
                    nr = seg_est.estimate(dial)
                    if nr.valid and nr.angle_deg is not None and nr.confidence >= 0.30:
                        acc = vision.angle_to_value(nr.angle_deg, calib) is not None
                elif m == "v31_prec_newdet":
                    nr = fusion_prec.estimate(dial, arc, use_kpt=True, use_seg=True, use_opencv=True)
                    if nr.valid and nr.angle_deg is not None:
                        acc = vision.angle_to_value(nr.angle_deg, calib) is not None
            rejects[m].setdefault(kind, []).append(0 if acc else 1)

    return {
        m: {
            "total_n": sum(len(v) for v in rejects[m].values()),
            "reject_pct": round(100.0 * float(np.mean([x for v in rejects[m].values() for x in v])), 2),
            "by_kind": {k: round(100.0 * float(np.mean(v)), 2) for k, v in rejects[m].items()},
        }
        for m in methods
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subsets", nargs="+", default=["val", "primary", "unusable"])
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_CONFIG_DIR"] = str(pathlib.Path(tempfile.gettempdir()) / "ultralytics_cfg")

    from app import config, vision
    from app.vision_engine.detector import detect_dial_v31
    from app.vision_engine.estimators import (
        FusionNeedleEstimator,
        NeuralKeypointEstimator,
        NeuralSegEstimator,
        OpenCVNeedleV2,
    )

    kpt_est = NeuralKeypointEstimator()
    seg_est = NeuralSegEstimator()
    opencv_v2 = OpenCVNeedleV2()
    fusion_prec = FusionNeedleEstimator(kpt=kpt_est, seg=seg_est, max_disagree_deg=12.0, min_neural_conf=0.50)

    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = man["items"]
    report: dict[str, Any] = {"subsets": {}}

    for sub in args.subsets:
        t0 = time.time()
        if sub == "val":
            sub_items = [r for r in items if r["split"] == "VALIDATION"]
        elif sub == "primary":
            sub_items = [r for r in items if r.get("legacy_primary")]
        elif sub == "final":
            sub_items = [r for r in items if r["split"] == "LEGACY_BENCHMARK"]
        elif sub == "unusable":
            print("\n=== UNUSABLE (n=300) ===", flush=True)
            report["subsets"]["unusable"] = eval_unusable(vision, config, kpt_est, seg_est, fusion_prec, opencv_v2, detect_dial_v31)
            print(json.dumps(report["subsets"]["unusable"], indent=2), flush=True)
            continue
        else:
            continue

        print(f"\n=== {sub.upper()} (n={len(sub_items)}) ===", flush=True)
        raw = eval_subset(sub_items, vision, config, kpt_est, seg_est, fusion_prec, opencv_v2, detect_dial_v31)
        sub_sum = {}
        for m, rows in raw.items():
            s = summarize_rows(rows)
            s["det_ms_mean"] = round(float(np.mean([r["det_ms"] for r in rows])), 2) if rows else 0.0
            s["by_model"] = {
                grp: summarize_rows([r for r in rows if r.get("model") == grp])
                for grp in sorted({r["model"] for r in rows if r.get("model")})
            }
            s["risk_coverage"] = risk_coverage_curve(rows)
            sub_sum[m] = s
            misc_loc = s["by_model"].get("misc", {}).get("loc_pct")
            print(
                f"  {m:18s}: loc={s['loc_pct']:5.1f}% (misc={misc_loc}%) valid={s['valid_pct']:5.1f}% "
                f"MAE={s['mae_pct']:5.2f}% med={s['med_pct']:4.2f}% p95={s['p95_pct']:5.2f}% "
                f"gross={s['gross_pct']:5.2f}% ({s['gross_n']}) det={s['det_ms_mean']:.0f}ms",
                flush=True,
            )
        report["subsets"][sub] = sub_sum
        (OUT_DIR / f"raw_v31_{sub}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        print(f"  Done {sub} in {time.time() - t0:.1f}s", flush=True)

    (OUT_DIR / "v31_detector_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSaved:", OUT_DIR / "v31_detector_comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
