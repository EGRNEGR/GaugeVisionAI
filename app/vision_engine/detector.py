"""
GaugeVision AI 3.1 — Каскадный локализатор циферблата с нейросетевой верификацией (`detect_dial_v31`).

Принцип работы (нулевая регрессия на штатных кадрах + спасение сложных/крупноплановых приборов):
  1. Выполняет базовую двухступенчатую локализацию `vision.detect_dial(frame_bgr)`.
  2. Если `NeedleSegUNet` подтверждает «приборность» (наличие шкалы `ticks_frac >= 0.035`
     и уверенной стрелки `conf >= 0.35`), сразу возвращает `roi_base` (0 лишних проходов YOLO).
  3. Только если базовый детектор не нашёл прибор или кроп не подтверждён `NeedleSegUNet`,
     запускает каскадный резерв:
       • YOLO при пониженном пороге (`conf = 0.10`);
       • YOLO на кадре с нейтральной рамкой +28 % (`padded`, спасает крупные планы MeasureBench);
       • все кандидаты сравниваются пакетно через `NeedleSegUNet` (6,6 мс/кроп), выбирается
         кандидат с наибольшей достоверностью шкалы и стрелки.
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from .. import config


def _box_circularity(w: float, h: float) -> float:
    if w <= 1.0 or h <= 1.0:
        return 0.0
    return float(min(w, h) / max(w, h))


def _yolo_boxes_with_conf(frame_bgr: np.ndarray, conf_thr: float) -> list[tuple[int, int, int, int, float]] | None:
    from .. import vision

    model = vision._load_yolo()
    if model is None:
        return None
    try:
        with vision._YOLO_INFER_LOCK:
            results = model.predict(frame_bgr, conf=conf_thr, **vision._predict_kwargs())
        boxes: list[tuple[int, int, int, int, float]] = []
        for r in results:
            names = r.names or {}
            for box in r.boxes:
                cls_name = str(names.get(int(box.cls), "")).lower()
                if any(k in cls_name for k in config.YOLO_CLASSES):
                    x1, y1, x2, y2 = map(float, box.xyxy[0])
                    bw, bh = x2 - x1, y2 - y1
                    if bw >= 16.0 and bh >= 16.0:
                        boxes.append((int(round(x1)), int(round(y1)), int(round(bw)), int(round(bh)), float(box.conf)))
        return boxes
    except Exception:
        return None


def _rank_boxes(boxes: list[tuple[int, int, int, int, float]], frame_h: int, frame_w: int) -> list[tuple[float, tuple[int, int, int, int, float]]]:
    frame_area = float(max(1, frame_h * frame_w))
    ranked: list[tuple[float, tuple[int, int, int, int, float]]] = []
    for b in boxes:
        x, y, w, h, conf = b
        circ = _box_circularity(w, h)
        area_frac = (w * h) / frame_area
        circ_w = circ if circ >= 0.55 else circ * 0.35
        size_w = 1.0 if area_frac >= 0.015 else max(0.35, area_frac / 0.015)
        score = conf * (0.45 + 0.55 * circ_w) * size_w
        ranked.append((score, b))
    ranked.sort(key=lambda t: t[0], reverse=True)
    return ranked


def _safe_refine_yolo_box(frame_bgr: np.ndarray, box: tuple[int, int, int, int, float], source: str = "yolo_v31") -> Any:
    from .. import vision

    x, y, w, h, conf = box
    fh, fw = frame_bgr.shape[:2]
    x1 = max(0.0, float(x))
    y1 = max(0.0, float(y))
    x2 = min(float(fw), float(x + w))
    y2 = min(float(fh), float(y + h))
    bw, bh = max(16.0, x2 - x1), max(16.0, y2 - y1)
    bx_c, by_c = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    max_dim = max(bw, bh)

    pad = int(0.08 * max_dim)
    cx0, cy0 = max(0, int(x1) - pad), max(0, int(y1) - pad)
    cx1, cy1 = min(fw, int(x2) + pad), min(fh, int(y2) + pad)
    crop = frame_bgr[cy0:cy1, cx0:cx1]
    if crop.size and min(crop.shape[:2]) >= 40:
        for ex, ey, a, b_ax, ang, _ in vision._ellipse_candidates(vision._prep_gray(crop)):
            gx, gy = ex + cx0, ey + cy0
            major = max(a, b_ax)
            shift = math.hypot(gx - bx_c, gy - by_c)
            if shift <= 0.22 * max_dim and 0.36 * max_dim <= major <= 0.72 * max_dim:
                return vision.roi_from_ellipse(gx, gy, a, b_ax, ang, score=min(0.98, 0.55 + 0.45 * conf), source=f"{source}+ellipse")

    return vision.roi_from_ellipse(bx_c, by_c, bw / 2.0, bh / 2.0, 0.0, score=min(0.94, 0.50 + 0.45 * conf), source=source)


def _dedup_candidates(cands: list[tuple[float, Any]]) -> list[tuple[float, Any]]:
    kept: list[tuple[float, Any]] = []
    for sc, roi in sorted(cands, key=lambda t: t[0], reverse=True):
        r_cur = math.sqrt(roi.axes[0] * roi.axes[1])
        dup = False
        for _, prev in kept:
            r_prev = math.sqrt(prev.axes[0] * prev.axes[1])
            if math.hypot(roi.center[0] - prev.center[0], roi.center[1] - prev.center[1]) < 0.18 * max(r_cur, r_prev):
                if 0.78 <= (r_cur / max(r_prev, 1e-6)) <= 1.28:
                    dup = True
                    break
        if not dup:
            kept.append((sc, roi))
    return kept


def _dialness_score(sr: Any) -> float:
    ticks_f = float(sr.diagnostics.get("ticks_frac", 0.0))
    ptr_c = float(sr.confidence) if sr.valid else 0.0
    elong = float(sr.diagnostics.get("elongation", 0.0)) if sr.valid else 0.0
    return min(1.0, ticks_f * 9.0) * 0.45 + ptr_c * 0.40 + elong * 0.15


def detect_dial_v31(frame_bgr: np.ndarray, seg_est: Any = None) -> Any | None:
    """
    Каскадный локализатор циферблата GaugeVision AI 3.1.
    """
    from .. import vision

    fh, fw = frame_bgr.shape[:2]
    roi_base = vision.detect_dial(frame_bgr)

    # 1. Быстрая проверка базового ROI через NeedleSegUNet
    base_dialness = 0.0
    if roi_base is not None and seg_est is not None:
        dial_b = vision.normalize_dial(frame_bgr, roi_base)
        sr_b = seg_est.estimate(dial_b)
        base_dialness = _dialness_score(sr_b)
        # Если базовый ROI уже уверенно подтверждён нейросетью -> возвращаем без доп. проходов
        if sr_b.valid and sr_b.confidence >= 0.40 and float(sr_b.diagnostics.get("ticks_frac", 0.0)) >= 0.035:
            return roi_base
    elif roi_base is not None and seg_est is None:
        return roi_base

    # 2. Каскадный резерв (только когда базовый ROI отсутствует или не подтверждён)
    candidates: list[tuple[float, Any]] = []
    if roi_base is not None:
        candidates.append((0.50 * roi_base.score, roi_base))

    boxes_lo = _yolo_boxes_with_conf(frame_bgr, 0.10)
    if boxes_lo is not None:
        for sc, b in _rank_boxes(boxes_lo, fh, fw)[:3]:
            candidates.append((sc, _safe_refine_yolo_box(frame_bgr, b, source="yolo_lowconf")))

        bh_pad, bw_pad = int(fh * 0.28), int(fw * 0.28)
        padded = cv2.copyMakeBorder(frame_bgr, bh_pad, bh_pad, bw_pad, bw_pad, cv2.BORDER_CONSTANT, value=(128, 128, 128))
        boxes_pad = _yolo_boxes_with_conf(padded, 0.10) or []
        mapped_pad: list[tuple[int, int, int, int, float]] = []
        for x, y, w, h, conf in boxes_pad:
            mx, my = x - bw_pad, y - bh_pad
            cx_m, cy_m = mx + w / 2.0, my + h / 2.0
            if 0 <= cx_m <= fw and 0 <= cy_m <= fh:
                mapped_pad.append((mx, my, w, h, conf))
        for sc, b in _rank_boxes(mapped_pad, fh, fw)[:3]:
            candidates.append((sc + 0.05, _safe_refine_yolo_box(frame_bgr, b, source="yolo_padded")))

    if not candidates:
        return roi_base

    dedup = _dedup_candidates(candidates)[:5]
    if seg_est is None or len(dedup) == 1:
        return dedup[0][1]

    # 3. Пакетная оценка кандидатов через NeedleSegUNet
    dials = [vision.normalize_dial(frame_bgr, roi) for _, roi in dedup]
    seg_res = seg_est.estimate_batch(dials)
    best_roi = roi_base if roi_base is not None else dedup[0][1]
    best_score = base_dialness + (0.12 if roi_base is not None else -1.0)
    for (base_sc, roi), sr in zip(dedup, seg_res):
        d_sc = _dialness_score(sr)
        total = d_sc + 0.25 * min(1.0, base_sc)
        if total > best_score:
            best_score = total
            best_roi = roi
    return best_roi
