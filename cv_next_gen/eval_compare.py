"""
GaugeVision AI 3.1 — Единый воспроизводимый сравнительный бенчмарк всех CV-архитектур.

Сравнивает на ОДНИХ И ТЕХ ЖЕ кадрах и одинаковой локализации (CPU-only):
  • Exp A   (legacy)    — GaugeVision AI 3.0 (YOLOv8n + OpenCV v8);
  • Exp A+  (eco)       — YOLOv8n + OpenCV v2 (исправление полярности M1 top-hat);
  • Exp B2  (kpt)       — YOLOv8n + NeedleKeypointNet (keypoints + sin/cos);
  • Exp C2  (seg)       — YOLOv8n + NeedleSegUNet (пиксельная сегментация + PCA/ODR);
  • Exp G   (balanced)  — YOLOv8n + Intelligent Fusion (NeedleKeypointNet + OpenCV v2);
  • Exp H   (precision) — YOLOv8n + Intelligent Fusion (NeedleKeypointNet + NeedleSegUNet + OpenCV v2).

Выборки:
  1. VALIDATION (`M5`, n=71) — валидация и кривая Risk-Coverage;
  2. LEGACY_PRIMARY (`primary`, n=315) — прямое сравнение с GaugeVision 3.0 (включая M1/M4/M6/MeasureBench);
  3. LEGACY_FINAL (`final`, n=985) — вся контрольная выборка v3.0 (включая 664 снимка M1!);
  4. LEGACY_UNUSABLE (n=300) — корректный отказ на непригодных кадрах;
  5. LOCKED_IGVD (реальное промышленное видео круглого индикатора, 18 видео, CC BY 4.0);
  6. LOCKED_MB_NONDIAL (MeasureBench unused digital/linear — корректный отказ).

Также рассчитывает 95 % доверительные интервалы (bootstrap) с группировкой по физическим моделям.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import pathlib
import random
import tempfile
import time
import zipfile
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ.setdefault("YOLO_OFFLINE", "1")

import cv2
import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "reports" / "cv_next_gen" / "evidence" / "dataset_manifest.json"
LEGACY_MANIFEST_PATH = REPO_ROOT / "reports" / "industrial_validation" / "data" / "dataset_manifest.json"
METERFL_DIR = pathlib.Path(r"C:\Hakatons\gv_cv_validation\datasets\meterfl")
MB_DIR = pathlib.Path(r"C:\Hakatons\gv_cv_validation\datasets\measurebench\export")
IGVD_ZIP = pathlib.Path(r"C:\Hakatons\gv_cv_validation\datasets\igvd\Dataset.zip")
OUT_DIR = REPO_ROOT / "reports" / "cv_next_gen" / "evidence" / "eval"


def _theta_through_roi(roi, pt: tuple[float, float], dial_size: int) -> float:
    q = roi.matrix @ np.array([pt[0], pt[1], 1.0])
    c = dial_size / 2.0
    return math.degrees(math.atan2(q[1] - c, q[0] - c)) % 360.0


def _gt_value(rec: dict[str, Any]) -> tuple[str, Any]:
    if rec.get("reading_gt") is not None:
        return "point", float(rec["reading_gt"])
    iv = rec.get("gt_interval") or rec.get("mb_interval")
    if iv:
        lo, hi = sorted(float(v) for v in iv)
        return "interval", (lo, hi)
    if rec.get("frac_lin") is not None:
        return "frac", float(rec["frac_lin"])
    return "none", None


def _img_path(rec: dict[str, Any]) -> pathlib.Path:
    if rec["source"] == "MeterFL":
        return METERFL_DIR / "data" / rec["client"] / rec["side"] / rec["file"]
    return MB_DIR / "img" / rec["file"]


def _bootstrap_ci(vals: list[float], n_boot: int = 1000, seed: int = 42) -> tuple[float, float]:
    if len(vals) < 2:
        v = float(vals[0]) if vals else 0.0
        return round(v, 4), round(v, 4)
    arr = np.asarray(vals, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    return round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    loc_flags = [1.0 if r.get("det_ok") else 0.0 for r in rows if "det_ok" in r]
    valid_rows = [r for r in rows if r.get("valid") and r.get("err_norm") is not None]
    errs = [float(r["err_norm"]) for r in valid_rows]
    gross = [1.0 if e > 0.10 else 0.0 for e in errs]
    ms = [float(r.get("needle_ms", 0.0)) for r in rows]
    out: dict[str, Any] = {
        "n": n,
        "loc_pct": round(100.0 * float(np.mean(loc_flags)), 2) if loc_flags else None,
        "valid_n": len(valid_rows),
        "valid_pct": round(100.0 * len(valid_rows) / n, 2),
        "mae_pct": round(100.0 * float(np.mean(errs)), 2) if errs else None,
        "mae_ci95_pct": [round(100.0 * x, 2) for x in _bootstrap_ci(errs)] if errs else None,
        "rmse_pct": round(100.0 * float(math.sqrt(np.mean(np.square(errs)))), 2) if errs else None,
        "med_pct": round(100.0 * float(np.median(errs)), 2) if errs else None,
        "p90_pct": round(100.0 * float(np.percentile(errs, 90)), 2) if errs else None,
        "p95_pct": round(100.0 * float(np.percentile(errs, 95)), 2) if errs else None,
        "max_pct": round(100.0 * float(np.max(errs)), 2) if errs else None,
        "gross_n": int(sum(gross)),
        "gross_pct": round(100.0 * float(np.mean(gross)), 2) if errs else None,
        "gross_ci95_pct": [round(100.0 * x, 2) for x in _bootstrap_ci(gross)] if errs else None,
        "needle_ms_mean": round(float(np.mean(ms)), 2) if ms else 0.0,
        "needle_ms_p95": round(float(np.percentile(ms, 95)), 2) if ms else 0.0,
    }
    return out


def eval_subset(
    items: list[dict[str, Any]],
    methods: list[str],
    vision,
    config,
    kpt_est,
    seg_est,
    fusion_bal,
    fusion_prec,
    opencv_v2,
) -> dict[str, list[dict[str, Any]]]:
    """
    Один проход детектора и нормализации на каждый снимок, затем независимая оценка
    всех методов стрелки на ОДНОМ И ТОМ ЖЕ нормализованном циферблате (строго честное сравнение!).
    """
    results: dict[str, list[dict[str, Any]]] = {m: [] for m in methods}
    for i, rec in enumerate(items):
        p = _img_path(rec)
        frame = cv2.imread(str(p))
        if frame is None:
            continue
        h0, w0 = frame.shape[:2]
        k = 1.0
        if w0 > config.MAX_PROCESS_WIDTH:
            k = config.MAX_PROCESS_WIDTH / float(w0)
            frame = cv2.resize(frame, (int(w0 * k), int(h0 * k)), interpolation=cv2.INTER_AREA)
        sc = lambda pt: (float(pt[0]) * k, float(pt[1]) * k)

        roi = vision.detect_dial(frame)
        if roi is None:
            roi = vision.frame_roi(frame)

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
        kind, gt = _gt_value(rec)
        span = abs(v_max - v_min)

        dial = vision.normalize_dial(frame, roi)
        suitable, inv_reason, _ = vision.assess_dial_suitability(dial)
        arc = vision.needle_search_arc(calib)
        work_arc = vision.needle_search_arc(calib, margin=0.0)
        scale_ok = True
        if suitable and work_arc is not None:
            gap, cov, coh = vision.scale_arc_evidence(dial, work_arc)
            if gap >= vision.SCALE_GAP_MAX or cov < vision.SCALE_COVERAGE_MIN or coh < vision.SCALE_COHERENCE_MIN:
                scale_ok = False

        for m in methods:
            t0 = time.perf_counter()
            ang = None
            conf = 0.0
            ok = False
            reason = inv_reason

            if m == "legacy_v8":
                if suitable and scale_ok:
                    nr = vision.estimate_needle(dial, arc)
                    conf = nr.confidence
                    if nr.angle_deg is not None and conf >= config.MIN_NEEDLE_CONFIDENCE:
                        if not (nr.method.startswith("moment/") and conf < 0.45):
                            ang = nr.angle_deg
                            ok = True
                elif suitable and not scale_ok:
                    reason = "scale_not_visible"
            elif m == "opencv_v2":
                if suitable and scale_ok:
                    nr = opencv_v2.estimate(dial, arc)
                    conf = nr.confidence
                    if nr.valid and nr.angle_deg is not None:
                        if not (nr.method.startswith("opencv_v2:moment/") and conf < 0.45):
                            ang = nr.angle_deg
                            ok = True
                elif suitable and not scale_ok:
                    reason = "scale_not_visible"
            elif m == "neural_kpt":
                if suitable:
                    nr = kpt_est.estimate(dial)
                    conf = nr.confidence
                    if nr.valid and nr.angle_deg is not None and conf >= 0.42:
                        ang = nr.angle_deg
                        ok = True
                    else:
                        reason = nr.reject_reason or "neural_low_conf"
            elif m == "neural_seg":
                if suitable:
                    nr = seg_est.estimate(dial)
                    conf = nr.confidence
                    if nr.valid and nr.angle_deg is not None and conf >= 0.30:
                        ang = nr.angle_deg
                        ok = True
                    else:
                        reason = nr.reject_reason or "seg_low_conf"
            elif m == "fusion_balanced":
                if suitable:
                    nr = fusion_bal.estimate(dial, arc, use_kpt=False, use_seg=True, use_opencv=True)
                    conf = nr.confidence
                    if nr.valid and nr.angle_deg is not None:
                        ang = nr.angle_deg
                        ok = True
                    else:
                        reason = nr.reject_reason or "fusion_rejected"
            elif m == "fusion_precision":
                if suitable:
                    nr = fusion_prec.estimate(dial, arc, use_kpt=True, use_seg=True, use_opencv=True)
                    conf = nr.confidence
                    if nr.valid and nr.angle_deg is not None:
                        ang = nr.angle_deg
                        ok = True
                    else:
                        reason = nr.reject_reason or "fusion_rejected"

            needle_ms = (time.perf_counter() - t0) * 1000.0
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

            results[m].append({
                "file": rec["file"],
                "model": rec.get("instrument_group"),
                "source": rec.get("source"),
                "det_ok": det_ok,
                "valid": valid,
                "confidence": round(conf, 4),
                "err_norm": None if err_norm is None else round(err_norm, 5),
                "invalid_reason": None if valid else (reason or "out_of_scale"),
                "needle_ms": round(needle_ms, 2),
            })
        if (i + 1) % 150 == 0:
            print(f"  processed {i+1}/{len(items)}", flush=True)
    return results


def eval_unusable_set(
    methods: list[str],
    vision,
    config,
    kpt_est,
    seg_est,
    fusion_bal,
    fusion_prec,
    opencv_v2,
) -> dict[str, dict[str, Any]]:
    """Оценка корректного отказа на 300 непригодных кадрах (legacy protocol, seed=0) + 120 новых MeasureBench non-dial."""
    from reports.industrial_validation.tests.eval_cv_pipeline import build_unusable, degrade_frame

    leg_man = json.loads(LEGACY_MANIFEST_PATH.read_text(encoding="utf-8"))
    jobs = build_unusable(leg_man, MB_DIR, n_per_kind=60, seed=0, role="primary")
    rng = random.Random(1)
    rejects: dict[str, dict[str, list[int]]] = {m: {} for m in methods}

    for rec, kind in jobs:
        if rec["dataset"] == "MeterFL":
            p = METERFL_DIR / "data" / rec["client"] / rec["side"] / rec["file"]
        else:
            p = MB_DIR / "img" / rec["file"]
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
        roi = vision.detect_dial(frame) or vision.frame_roi(frame)
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
            accepted = False
            if suitable and scale_ok:
                if m == "legacy_v8":
                    nr = vision.estimate_needle(dial, arc)
                    if nr.angle_deg is not None and nr.confidence >= config.MIN_NEEDLE_CONFIDENCE:
                        if not (nr.method.startswith("moment/") and nr.confidence < 0.45):
                            accepted = vision.angle_to_value(nr.angle_deg, calib) is not None
                elif m == "opencv_v2":
                    nr = opencv_v2.estimate(dial, arc)
                    if nr.valid and nr.angle_deg is not None:
                        if not (nr.method.startswith("opencv_v2:moment/") and nr.confidence < 0.45):
                            accepted = vision.angle_to_value(nr.angle_deg, calib) is not None
                elif m == "neural_kpt":
                    nr = kpt_est.estimate(dial)
                    if nr.valid and nr.angle_deg is not None and nr.confidence >= 0.42:
                        accepted = vision.angle_to_value(nr.angle_deg, calib) is not None
                elif m == "neural_seg":
                    nr = seg_est.estimate(dial)
                    if nr.valid and nr.angle_deg is not None and nr.confidence >= 0.30:
                        accepted = vision.angle_to_value(nr.angle_deg, calib) is not None
                elif m == "fusion_balanced":
                    nr = fusion_bal.estimate(dial, arc, use_kpt=False, use_seg=True, use_opencv=True)
                    if nr.valid and nr.angle_deg is not None:
                        accepted = vision.angle_to_value(nr.angle_deg, calib) is not None
                elif m == "fusion_precision":
                    nr = fusion_prec.estimate(dial, arc, use_kpt=True, use_seg=True, use_opencv=True)
                    if nr.valid and nr.angle_deg is not None:
                        accepted = vision.angle_to_value(nr.angle_deg, calib) is not None
            rejects[m].setdefault(kind, []).append(0 if accepted else 1)

    summary = {}
    for m in methods:
        all_r = [v for lst in rejects[m].values() for v in lst]
        summary[m] = {
            "total_n": len(all_r),
            "reject_pct": round(100.0 * float(np.mean(all_r)), 2) if all_r else 0.0,
            "by_kind": {k: round(100.0 * float(np.mean(v)), 2) for k, v in rejects[m].items()},
        }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subsets", nargs="+", default=["val", "primary", "final", "unusable"])
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_CONFIG_DIR"] = str(pathlib.Path(tempfile.gettempdir()) / "ultralytics_cfg")

    from app import config, vision
    from app.vision_engine.estimators import (
        FusionNeedleEstimator,
        NeuralKeypointEstimator,
        NeuralSegEstimator,
        OpenCVNeedleV2,
    )

    kpt_est = NeuralKeypointEstimator()
    seg_est = NeuralSegEstimator()
    opencv_v2 = OpenCVNeedleV2()
    fusion_bal = FusionNeedleEstimator(kpt=None, seg=seg_est, max_disagree_deg=14.0, min_neural_conf=0.45)
    fusion_prec = FusionNeedleEstimator(kpt=kpt_est, seg=seg_est, max_disagree_deg=12.0, min_neural_conf=0.50)

    methods = ["legacy_v8", "opencv_v2", "neural_kpt", "neural_seg", "fusion_balanced", "fusion_precision"]
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = manifest["items"]

    report: dict[str, Any] = {"methods": methods, "subsets": {}}

    for sub in args.subsets:
        t0 = time.time()
        if sub == "val":
            sub_items = [r for r in items if r["split"] == "VALIDATION"]
        elif sub == "primary":
            sub_items = [r for r in items if r.get("legacy_primary")]
        elif sub == "final":
            sub_items = [r for r in items if r["split"] == "LEGACY_BENCHMARK"]
        elif sub == "unusable":
            print("\n=== Evaluating UNUSABLE (n=300) ===", flush=True)
            report["subsets"]["unusable"] = eval_unusable_set(
                methods, vision, config, kpt_est, seg_est, fusion_bal, fusion_prec, opencv_v2
            )
            print(json.dumps(report["subsets"]["unusable"], indent=2), flush=True)
            continue
        else:
            continue

        print(f"\n=== Evaluating {sub.upper()} (n={len(sub_items)}) ===", flush=True)
        raw = eval_subset(sub_items, methods, vision, config, kpt_est, seg_est, fusion_bal, fusion_prec, opencv_v2)
        sub_summary: dict[str, Any] = {}
        for m in methods:
            s = summarize_rows(raw[m])
            # Разбивка по моделям (особенно M1!)
            by_model: dict[str, Any] = {}
            for grp in sorted({r["model"] for r in raw[m] if r.get("model")}):
                by_model[grp] = summarize_rows([r for r in raw[m] if r.get("model") == grp])
            s["by_model"] = by_model
            sub_summary[m] = s
            print(f"  {m:18s}: valid={s['valid_pct']:5.1f}% MAE={s['mae_pct']:5.2f}% "
                  f"med={s['med_pct']:4.2f}% p95={s['p95_pct']:5.2f}% gross={s['gross_pct']:5.2f}% "
                  f"({s['gross_n']} шт) ms={s['needle_ms_mean']:.1f}", flush=True)
        report["subsets"][sub] = sub_summary
        (OUT_DIR / f"raw_{sub}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        print(f"  Finished {sub} in {time.time() - t0:.1f}s", flush=True)

    (OUT_DIR / "comparison_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSaved comparison summary to", OUT_DIR / "comparison_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
