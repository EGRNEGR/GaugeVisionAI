"""
GaugeVision AI 3.1 — Независимая видеовалидация на LOCKED_FINAL_TEST:
  1) IGVD (Zenodo 20147961, CC BY 4.0) — реальное 30 fps промышленное видео круглого
     индикатора часового типа (0–10 мм, 0,01 мм/дел, 1 оборот = 1,00 мм, 0 на 12 часах = 270°, CW).
     Оценивается считывание дробной части показания (value mod 1,00) на 6 скоростях движения стрелки.
  2) MeasureBench unused non-dial (digital + linear, n=120) — независимая проверка корректного отказа.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import tempfile
import time
import zipfile
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ.setdefault("YOLO_OFFLINE", "1")

import cv2
import numpy as np

from .build_dataset_manifest import parse_igvd_xlsx

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "reports" / "cv_next_gen" / "evidence" / "dataset_manifest.json"
IGVD_ZIP = pathlib.Path(r"C:\Hakatons\gv_cv_validation\datasets\igvd\Dataset.zip")
MB_DIR = pathlib.Path(r"C:\Hakatons\gv_cv_validation\datasets\measurebench\export")
OUT_PATH = REPO_ROOT / "reports" / "cv_next_gen" / "evidence" / "eval" / "locked_final_test.json"


def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def main() -> int:
    os.environ["YOLO_CONFIG_DIR"] = str(pathlib.Path(tempfile.gettempdir()) / "ultralytics_cfg")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

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
    per_method: dict[str, list[dict[str, Any]]] = {m: [] for m in methods}

    # 1. IGVD: берём 6 видео (UP и DOWN на скоростях V1, V3, V6), шаг 3000 мс (~120 реальных видеокадров)
    selected_videos = [
        ("Dataset/1.- Analog Dial Gauge/DOWN/DOWN_V1_5 divisions_per_second.mp4", "Dataset/1_label/DOWN_DOWN_V1_5 divisions_per_second.xlsx"),
        ("Dataset/1.- Analog Dial Gauge/DOWN/DOWN_V3_17 divisions_per_second.mp4", "Dataset/1_label/DOWN_DOWN_V3_17 divisions_per_second.xlsx"),
        ("Dataset/1.- Analog Dial Gauge/DOWN/DOWN_V6_100 divisions_per_second.mp4", "Dataset/1_label/DOWN_DOWN_V6_100 divisions_per_second.xlsx"),
        ("Dataset/1.- Analog Dial Gauge/UP/UP_V1_5 divisions_per_second.mp4", "Dataset/1_label/UP_UP_V1_5 divisions_per_second.xlsx"),
        ("Dataset/1.- Analog Dial Gauge/UP/UP_V3_17 divisions_per_second.mp4", "Dataset/1_label/UP_UP_V3_17 divisions_per_second.xlsx"),
        ("Dataset/1.- Analog Dial Gauge/UP/UP_V6_100 divisions_per_second.mp4", "Dataset/1_label/UP_UP_V6_100 divisions_per_second.xlsx"),
    ]

    with zipfile.ZipFile(IGVD_ZIP) as z:
        for vid_p, xls_p in selected_videos:
            if vid_p not in z.namelist() or xls_p not in z.namelist():
                continue
            labels = parse_igvd_xlsx(z.read(xls_p))
            # Берём ~25 равномерных меток с видео (исключая самый старт/конец)
            step = max(1, len(labels) // 25)
            sampled = labels[2:-2:step][:25]
            tmp_mp4 = pathlib.Path(tempfile.gettempdir()) / "igvd_eval_cur.mp4"
            tmp_mp4.write_bytes(z.read(vid_p))
            cap = cv2.VideoCapture(str(tmp_mp4))
            roi_cached = None

            for ts_ms, gt_mm in sampled:
                cap.set(cv2.CAP_PROP_POS_MSEC, float(ts_ms))
                ok_r, frame = cap.read()
                if not ok_r or frame is None:
                    continue
                h0, w0 = frame.shape[:2]
                if w0 > config.MAX_PROCESS_WIDTH:
                    k = config.MAX_PROCESS_WIDTH / float(w0)
                    frame = cv2.resize(frame, (int(w0 * k), int(h0 * k)), interpolation=cv2.INTER_AREA)
                if roi_cached is None:
                    roi_cached = vision.detect_dial(frame) or vision.frame_roi(frame)
                dial = vision.normalize_dial(frame, roi_cached)
                suitable, _, _ = vision.assess_dial_suitability(dial)

                # Истинный угол для дробной части (0.00 мм = 270°, по часовой стрелке 360°/мм)
                gt_frac = gt_mm % 1.0
                gt_ang = (270.0 + gt_frac * 360.0) % 360.0

                for m in methods:
                    t0 = time.perf_counter()
                    ang = None
                    valid = False
                    if suitable:
                        if m == "legacy_v8":
                            nr = vision.estimate_needle(dial, None)
                            if nr.angle_deg is not None and nr.confidence >= config.MIN_NEEDLE_CONFIDENCE:
                                ang, valid = nr.angle_deg, True
                        elif m == "opencv_v2":
                            nr = opencv_v2.estimate(dial, None)
                            if nr.valid and nr.angle_deg is not None:
                                ang, valid = nr.angle_deg, True
                        elif m == "neural_kpt":
                            nr = kpt_est.estimate(dial)
                            if nr.valid and nr.angle_deg is not None and nr.confidence >= 0.42:
                                ang, valid = nr.angle_deg, True
                        elif m == "neural_seg":
                            nr = seg_est.estimate(dial)
                            if nr.valid and nr.angle_deg is not None and nr.confidence >= 0.30:
                                ang, valid = nr.angle_deg, True
                        elif m == "fusion_balanced":
                            nr = fusion_bal.estimate(dial, None, use_kpt=False, use_seg=True, use_opencv=True)
                            if nr.valid and nr.angle_deg is not None:
                                ang, valid = nr.angle_deg, True
                        elif m == "fusion_precision":
                            nr = fusion_prec.estimate(dial, None, use_kpt=True, use_seg=True, use_opencv=True)
                            if nr.valid and nr.angle_deg is not None:
                                ang, valid = nr.angle_deg, True
                    ms = (time.perf_counter() - t0) * 1000.0
                    err_deg = _ang_diff(ang, gt_ang) if (valid and ang is not None) else None
                    err_norm = (err_deg / 360.0) if err_deg is not None else None
                    per_method[m].append({
                        "video": pathlib.Path(vid_p).name,
                        "ts_ms": ts_ms,
                        "gt_mm": gt_mm,
                        "valid": valid,
                        "err_deg": None if err_deg is None else round(err_deg, 2),
                        "err_norm": None if err_norm is None else round(err_norm, 5),
                        "ms": round(ms, 2),
                    })
            cap.release()
            tmp_mp4.unlink(missing_ok=True)

    igvd_summary: dict[str, Any] = {}
    for m in methods:
        rows = per_method[m]
        v_rows = [r for r in rows if r["valid"] and r["err_norm"] is not None]
        errs = [r["err_norm"] for r in v_rows]
        igvd_summary[m] = {
            "n_frames": len(rows),
            "valid_pct": round(100.0 * len(v_rows) / max(1, len(rows)), 2),
            "mae_pct": round(100.0 * float(np.mean(errs)), 2) if errs else None,
            "med_pct": round(100.0 * float(np.median(errs)), 2) if errs else None,
            "p95_pct": round(100.0 * float(np.percentile(errs, 95)), 2) if errs else None,
            "gross_10pct": round(100.0 * float(np.mean(np.array(errs) > 0.10)), 2) if errs else None,
            "ms_mean": round(float(np.mean([r["ms"] for r in rows])), 2) if rows else 0.0,
        }

    # 2. MeasureBench unused non-dial (120 реальных цифровых/линейных приборов — корректный отказ)
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    nondial = [r for r in man["items"] if r["split"] == "LOCKED_FINAL_TEST" and r.get("annotation_type") == "unusable_non_dial"][:120]
    nd_rej: dict[str, list[int]] = {m: [] for m in methods}
    for rec in nondial:
        frame = cv2.imread(str(MB_DIR / "img" / rec["file"]))
        if frame is None:
            continue
        h, w = frame.shape[:2]
        roi = vision.detect_dial(frame) or vision.frame_roi(frame)
        dial = vision.normalize_dial(frame, roi)
        suitable, _, _ = vision.assess_dial_suitability(dial)
        calib = {"v_min": 0.0, "v_max": 100.0, "theta_min": 135.0, "theta_max": 45.0, "direction": "cw"}
        work_arc = vision.needle_search_arc(calib, margin=0.0)
        scale_ok = True
        if suitable and work_arc is not None:
            gap, cov, coh = vision.scale_arc_evidence(dial, work_arc)
            if gap >= vision.SCALE_GAP_MAX or cov < vision.SCALE_COVERAGE_MIN or coh < vision.SCALE_COHERENCE_MIN:
                scale_ok = False
        arc = vision.needle_search_arc(calib)
        for m in methods:
            acc = False
            if suitable and scale_ok:
                if m == "legacy_v8":
                    nr = vision.estimate_needle(dial, arc)
                    acc = nr.angle_deg is not None and nr.confidence >= config.MIN_NEEDLE_CONFIDENCE and not (nr.method.startswith("moment/") and nr.confidence < 0.45)
                elif m == "opencv_v2":
                    nr = opencv_v2.estimate(dial, arc)
                    acc = nr.valid and nr.angle_deg is not None and not (nr.method.startswith("opencv_v2:moment/") and nr.confidence < 0.45)
                elif m == "neural_kpt":
                    nr = kpt_est.estimate(dial)
                    acc = nr.valid and nr.angle_deg is not None and nr.confidence >= 0.42
                elif m == "neural_seg":
                    nr = seg_est.estimate(dial)
                    acc = nr.valid and nr.angle_deg is not None and nr.confidence >= 0.30
                elif m == "fusion_balanced":
                    nr = fusion_bal.estimate(dial, arc, use_kpt=False, use_seg=True, use_opencv=True)
                    acc = nr.valid and nr.angle_deg is not None
                elif m == "fusion_precision":
                    nr = fusion_prec.estimate(dial, arc, use_kpt=True, use_seg=True, use_opencv=True)
                    acc = nr.valid and nr.angle_deg is not None
            nd_rej[m].append(0 if acc else 1)

    nondial_summary = {m: {"n": len(v), "reject_pct": round(100.0 * float(np.mean(v)), 2)} for m, v in nd_rej.items()}

    out = {"igvd_video": igvd_summary, "mb_unused_nondial": nondial_summary}
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LOCKED_FINAL_TEST RESULTS ===")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
