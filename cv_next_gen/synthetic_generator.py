"""
GaugeVision AI 3.1 — Воспроизводимый генератор синтетических аналоговых приборов
с точной согласованной разметкой (bbox, pixel mask, keypoints, angle, value).

Целенаправленно воспроизводит все режимы отказов исторического CV-конвейера v7/v8:
  • боковое освещение с медианой лица 90–140 (проблема top-hat на модели M1);
  • блики на защитном стекле и яркие светлые надписи на циферблате;
  • стрелки с массивными противовесами (исключение переворота на 180°);
  • тонкие, толстые, цветные, светлые и тёмные стрелки;
  • редкие и плотные шкалы, CW/CCW, отрицательные диапазоны;
  • перспективные искажения, смещение центра, размытие, шум, JPEG-компрессия;
  • частичные перекрытия, крупные планы и многоприборные щиты (1–16 приборов).

Шаблоны приборов (template_id) строго разделяются между train (0..699) и test (700..999).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np


@dataclass
class GaugeTemplate:
    template_id: int
    face_mode: str           # "light" | "mid_sidelit" | "dark" | "cream"
    face_bgr: tuple[int, int, int]
    bezel_bgr: tuple[int, int, int]
    tick_bgr: tuple[int, int, int]
    needle_bgr: tuple[int, int, int]
    needle_style: str        # "tapered" | "thin" | "thick" | "sword"
    counterweight_len: float # 0.0 .. 0.35 of radius
    counterweight_w: float   # 0.03 .. 0.09 of radius
    hub_radius_frac: float   # 0.05 .. 0.12
    theta_min: float         # degrees, image coords (0=3h, 90=6h, 135=7:30)
    theta_max: float
    direction: str           # "cw" | "ccw"
    v_min: float
    v_max: float
    n_major: int
    n_minor_per_major: int
    unit: str
    label_text: str
    has_color_zones: bool
    has_bright_text: bool


UNITS_POOL = ("MPa", "bar", "kPa", "C", "%", "A", "V", "mm")
LABELS_POOL = ("ELECALL", "GOST 2405", "KL 1.5", "WIKA", "MANOMETER", "IP65", "BAR / PSI", "MTP-160")


def sample_template(template_id: int) -> GaugeTemplate:
    """Детерминированный шаблон прибора по template_id (исключает пересечение train/test)."""
    rng = random.Random(template_id * 7919 + 13)
    face_mode = rng.choices(
        ["light", "mid_sidelit", "dark", "cream"],
        weights=[0.35, 0.30, 0.20, 0.15],
        k=1,
    )[0]
    if face_mode == "light":
        v = rng.randint(210, 245)
        face_bgr = (v, v, v)
        tick_bgr = (rng.randint(15, 45),) * 3
        needle_bgr = rng.choice([(18, 18, 22), (25, 25, 30), (30, 30, 190), (20, 40, 210)])
        has_bright_text = rng.random() < 0.25
    elif face_mode == "mid_sidelit":
        # Ключевой домен M1: серое/затенённое поле 100..145 с тёмной стрелкой и белыми бликами/надписями
        v = rng.randint(105, 148)
        face_bgr = (v, v + rng.randint(-5, 5), v + rng.randint(-5, 5))
        tick_bgr = (rng.randint(15, 40),) * 3
        needle_bgr = rng.choice([(12, 12, 16), (20, 20, 28), (25, 25, 180)])
        has_bright_text = rng.random() < 0.70
    elif face_mode == "dark":
        v = rng.randint(22, 58)
        face_bgr = (v, v + rng.randint(-3, 4), v + rng.randint(-3, 4))
        tick_bgr = (rng.randint(205, 245),) * 3
        needle_bgr = rng.choice([(235, 235, 240), (60, 190, 245), (50, 70, 240), (220, 235, 240)])
        has_bright_text = rng.random() < 0.50
    else:  # cream / aged industrial dial
        face_bgr = (rng.randint(185, 215), rng.randint(215, 238), rng.randint(225, 246))
        tick_bgr = (rng.randint(25, 55),) * 3
        needle_bgr = rng.choice([(20, 20, 24), (25, 30, 175)])
        has_bright_text = rng.random() < 0.30

    bezel_v = rng.randint(25, 155)
    bezel_bgr = (bezel_v, bezel_v + rng.randint(-6, 6), bezel_v + rng.randint(-6, 6))

    direction = "ccw" if rng.random() < 0.15 else "cw"
    span_deg = rng.uniform(210.0, 300.0)
    if direction == "cw":
        theta_min = rng.uniform(110.0, 160.0)
        theta_max = (theta_min + span_deg) % 360.0
    else:
        theta_min = rng.uniform(20.0, 70.0)
        theta_max = (theta_min - span_deg) % 360.0

    ranges = [
        (0.0, 0.1), (0.0, 1.0), (0.0, 1.6), (0.0, 2.5), (0.0, 6.0),
        (0.0, 10.0), (0.0, 16.0), (-0.1, 0.9), (-1.0, 1.5), (-50.0, 150.0), (0.0, 100.0),
    ]
    v_min, v_max = rng.choice(ranges)

    return GaugeTemplate(
        template_id=template_id,
        face_mode=face_mode,
        face_bgr=face_bgr,
        bezel_bgr=bezel_bgr,
        tick_bgr=tick_bgr,
        needle_bgr=needle_bgr,
        needle_style=rng.choice(["tapered", "thin", "thick", "sword"]),
        counterweight_len=rng.uniform(0.08, 0.34),
        counterweight_w=rng.uniform(0.025, 0.075),
        hub_radius_frac=rng.uniform(0.055, 0.11),
        theta_min=round(theta_min, 2),
        theta_max=round(theta_max, 2),
        direction=direction,
        v_min=v_min,
        v_max=v_max,
        n_major=rng.choice([5, 6, 8, 10, 12]),
        n_minor_per_major=rng.choice([2, 4, 5]),
        unit=rng.choice(UNITS_POOL),
        label_text=rng.choice(LABELS_POOL),
        has_color_zones=rng.random() < 0.35,
        has_bright_text=has_bright_text,
    )


def _angle_for_frac(tpl: GaugeTemplate, frac: float) -> float:
    if tpl.direction == "cw":
        span = (tpl.theta_max - tpl.theta_min) % 360.0
        return (tpl.theta_min + frac * span) % 360.0
    span = (tpl.theta_min - tpl.theta_max) % 360.0
    return (tpl.theta_min - frac * span) % 360.0


def render_dial_sample(
    size: int = 256,
    template_id: int = 0,
    seed: int = 0,
    hard_mode: bool = True,
    occlude: bool = False,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """
    Генерирует нормализованный/слегка смещённый кроп циферблата + 3-классовую маску
    (0=фон, 1=риски, 2=стрелка) + точные метаданные (center, tip, angle_deg, value, visibility).
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    tpl = sample_template(template_id)

    # 1. Холст с фоном
    bg_v = rng.randint(25, 195)
    img = np.full((size, size, 3), (bg_v, bg_v, bg_v), dtype=np.uint8)
    mask = np.zeros((size, size), dtype=np.uint8)

    # Небольшое случайное смещение центра и радиуса (моделирует ошибку локализации детектора!)
    jitter_c = 0.08 if hard_mode else 0.02
    cx = size * (0.5 + rng.uniform(-jitter_c, jitter_c))
    cy = size * (0.5 + rng.uniform(-jitter_c, jitter_c))
    radius = size * rng.uniform(0.39, 0.48)

    # 2. Корпус (bezel) и циферблат (face)
    bezel_r = int(round(radius * rng.uniform(1.04, 1.13)))
    cv2.circle(img, (int(round(cx)), int(round(cy))), bezel_r, tpl.bezel_bgr, -1, cv2.LINE_AA)
    cv2.circle(img, (int(round(cx)), int(round(cy))), int(round(radius)), tpl.face_bgr, -1, cv2.LINE_AA)
    cv2.circle(img, (int(round(cx)), int(round(cy))), int(round(radius)),
               (max(0, tpl.bezel_bgr[0] - 25),) * 3, max(1, int(size * 0.01)), cv2.LINE_AA)

    # Цветные секторы на части приборов
    if tpl.has_color_zones:
        for zf0, zf1, col in ((0.0, 0.65, (80, 175, 80)), (0.65, 0.85, (40, 185, 235)), (0.85, 1.0, (55, 55, 215))):
            a0 = _angle_for_frac(tpl, zf0)
            a1 = _angle_for_frac(tpl, zf1)
            sweep = (a1 - a0) % 360.0 if tpl.direction == "cw" else -((a0 - a1) % 360.0)
            pts = []
            for k in range(25):
                ang = math.radians(a0 + sweep * k / 24.0)
                pts.append([int(round(cx + math.cos(ang) * radius * 0.90)),
                            int(round(cy + math.sin(ang) * radius * 0.90))])
            cv2.polylines(img, [np.array(pts, np.int32)], False, col, max(2, int(size * 0.02)), cv2.LINE_AA)

    # 3. Риски шкалы и числа (класс 1 на маске)
    total_ticks = tpl.n_major * tpl.n_minor_per_major
    r_outer = radius * 0.93
    for i in range(total_ticks + 1):
        frac = i / float(total_ticks)
        ang = math.radians(_angle_for_frac(tpl, frac))
        is_major = (i % tpl.n_minor_per_major == 0)
        r_inner = radius * (0.76 if is_major else 0.84)
        p0 = (int(round(cx + math.cos(ang) * r_inner)), int(round(cy + math.sin(ang) * r_inner)))
        p1 = (int(round(cx + math.cos(ang) * r_outer)), int(round(cy + math.sin(ang) * r_outer)))
        th = max(1, int(round(size * (0.011 if is_major else 0.006))))
        cv2.line(img, p0, p1, tpl.tick_bgr, th, cv2.LINE_AA)
        cv2.line(mask, p0, p1, 1, max(2, th))
        if is_major:
            val = tpl.v_min + frac * (tpl.v_max - tpl.v_min)
            txt = f"{val:.1f}" if abs(tpl.v_max - tpl.v_min) <= 2.5 else f"{int(round(val))}"
            fs = size / 680.0
            (tw, tht), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
            tx = int(round(cx + math.cos(ang) * radius * 0.62 - tw / 2.0))
            ty = int(round(cy + math.sin(ang) * radius * 0.62 + tht / 2.0))
            cv2.putText(img, txt, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, tpl.tick_bgr,
                        max(1, int(size / 220)), cv2.LINE_AA)

    # Внутренние надписи (в т.ч. яркие/белые надписи, сбивающие top-hat!)
    fs_u = size / 560.0
    txt_col = (242, 242, 245) if tpl.has_bright_text else tpl.tick_bgr
    (uw, uh), _ = cv2.getTextSize(tpl.unit, cv2.FONT_HERSHEY_SIMPLEX, fs_u, 1)
    cv2.putText(img, tpl.unit, (int(cx - uw / 2), int(cy - radius * 0.24)),
                cv2.FONT_HERSHEY_SIMPLEX, fs_u, txt_col, max(1, int(size / 200)), cv2.LINE_AA)
    (lw, lh), _ = cv2.getTextSize(tpl.label_text, cv2.FONT_HERSHEY_SIMPLEX, fs_u * 0.8, 1)
    cv2.putText(img, tpl.label_text, (int(cx - lw / 2), int(cy + radius * 0.34)),
                cv2.FONT_HERSHEY_SIMPLEX, fs_u * 0.8, txt_col, max(1, int(size / 220)), cv2.LINE_AA)

    # 4. Стрелка (класс 2 на маске)
    frac_val = rng.uniform(0.0, 1.0)
    angle_deg = _angle_for_frac(tpl, frac_val)
    true_val = tpl.v_min + frac_val * (tpl.v_max - tpl.v_min)
    rad = math.radians(angle_deg)
    ca, sa = math.cos(rad), math.sin(rad)
    px_n, py_n = -sa, ca  # нормаль к оси стрелки

    tip_len = radius * rng.uniform(0.72, 0.90)
    tail_len = radius * tpl.counterweight_len
    tip_x = cx + ca * tip_len
    tip_y = cy + sa * tip_len
    tail_x = cx - ca * tail_len
    tail_y = cy - sa * tail_len

    if tpl.needle_style == "thin":
        w_base, w_tip = radius * 0.022, radius * 0.008
    elif tpl.needle_style == "thick":
        w_base, w_tip = radius * 0.055, radius * 0.022
    elif tpl.needle_style == "sword":
        w_base, w_tip = radius * 0.048, radius * 0.010
    else:  # tapered
        w_base, w_tip = radius * 0.038, radius * 0.012
    w_tail = radius * tpl.counterweight_w

    poly = np.array([
        [tail_x + px_n * w_tail, tail_y + py_n * w_tail],
        [cx + px_n * w_base, cy + py_n * w_base],
        [tip_x + px_n * w_tip, tip_y + py_n * w_tip],
        [tip_x - px_n * w_tip, tip_y - py_n * w_tip],
        [cx - px_n * w_base, cy - py_n * w_base],
        [tail_x - px_n * w_tail, tail_y - py_n * w_tail],
    ], dtype=np.int32)

    # Тень под стрелкой (реалистичный объём)
    if rng.random() < 0.65:
        sh_dx, sh_dy = rng.randint(1, max(2, int(size * 0.015))), rng.randint(1, max(2, int(size * 0.015)))
        sh_poly = poly + np.array([[sh_dx, sh_dy]], dtype=np.int32)
        shadow = img.copy()
        cv2.fillConvexPoly(shadow, sh_poly, (25, 25, 28), cv2.LINE_AA)
        img = cv2.addWeighted(shadow, 0.35, img, 0.65, 0)

    cv2.fillConvexPoly(img, poly, tpl.needle_bgr, cv2.LINE_AA)
    cv2.fillConvexPoly(mask, poly, 2)

    # Противовес-кружок на хвосте
    if tpl.counterweight_len > 0.16 and rng.random() < 0.55:
        cw_r = max(2, int(round(radius * rng.uniform(0.04, 0.085))))
        cv2.circle(img, (int(round(tail_x)), int(round(tail_y))), cw_r, tpl.needle_bgr, -1, cv2.LINE_AA)
        cv2.circle(mask, (int(round(tail_x)), int(round(tail_y))), cw_r, 2, -1)

    # Центральный колпачок (hub)
    hub_r = max(3, int(round(radius * tpl.hub_radius_frac)))
    hub_col = tpl.needle_bgr if rng.random() < 0.7 else (rng.randint(140, 210),) * 3
    cv2.circle(img, (int(round(cx)), int(round(cy))), hub_r, hub_col, -1, cv2.LINE_AA)
    cv2.circle(mask, (int(round(cx)), int(round(cy))), max(2, hub_r // 2), 2, -1)

    # 5. Перспективное / аффинное искажение (синхронно для img, mask и точек!)
    pts_kpt = np.array([
        [cx, cy],
        [tip_x, tip_y],
        [cx + math.cos(math.radians(tpl.theta_min)) * radius * 0.85,
         cy + math.sin(math.radians(tpl.theta_min)) * radius * 0.85],
        [cx + math.cos(math.radians(tpl.theta_max)) * radius * 0.85,
         cy + math.sin(math.radians(tpl.theta_max)) * radius * 0.85],
    ], dtype=np.float32)

    if hard_mode and rng.random() < 0.55:
        d = size * rng.uniform(0.01, 0.06)
        src = np.array([[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]], dtype=np.float32)
        dst = src + np_rng.uniform(-d, d, size=(4, 2)).astype(np.float32)
        H = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(img, H, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        mask = cv2.warpPerspective(mask, H, (size, size), flags=cv2.INTER_NEAREST, borderValue=0)
        pts_kpt = cv2.perspectiveTransform(pts_kpt.reshape(-1, 1, 2), H).reshape(-1, 2)

    cx, cy = float(pts_kpt[0, 0]), float(pts_kpt[0, 1])
    tip_x, tip_y = float(pts_kpt[1, 0]), float(pts_kpt[1, 1])
    angle_deg = math.degrees(math.atan2(tip_y - cy, tip_x - cx)) % 360.0

    # 6. Оптические артефакты (боковое освещение, блики на стекле, шум, размытие, JPEG)
    img_f = img.astype(np.float32)
    if hard_mode:
        # Боковой градиент освещения (как M1 в руке)
        if rng.random() < 0.75:
            gx_ang = rng.uniform(0, 2 * math.pi)
            yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / float(size) - 0.5
            grad = xx * math.cos(gx_ang) + yy * math.sin(gx_ang)
            strength = rng.uniform(0.20, 0.55)
            img_f = img_f * (1.0 + strength * grad[:, :, None]) + rng.uniform(-18, 18)

        # Полосы бликов на защитном стекле (ложные светлые линии!)
        if rng.random() < 0.65:
            glare = np.zeros((size, size), dtype=np.float32)
            for _ in range(rng.randint(1, 3)):
                p0 = (rng.randint(0, size), rng.randint(0, size))
                p1 = (rng.randint(0, size), rng.randint(0, size))
                cv2.line(glare, p0, p1, rng.uniform(55, 135), rng.randint(max(2, size // 32), max(4, size // 10)), cv2.LINE_AA)
            glare = cv2.GaussianBlur(glare, (0, 0), rng.uniform(2.5, 7.0))
            img_f += glare[:, :, None]

        # Загрязнения / пятна
        if rng.random() < 0.30:
            for _ in range(rng.randint(2, 6)):
                sx, sy = rng.randint(0, size - 1), rng.randint(0, size - 1)
                sr = rng.randint(2, max(3, size // 28))
                cv2.circle(img_f, (sx, sy), sr, (rng.uniform(40, 110),) * 3, -1)

    img = np.clip(img_f, 0, 255).astype(np.uint8)

    visibility = 1.0
    if occlude:
        # Непригодный кадр: перекрытие сектора 220..260°
        occ_mask = np.zeros((size, size), dtype=np.uint8)
        a0 = rng.uniform(0, 360)
        pts_o = [(cx + 1.5 * radius * math.cos(math.radians(a0 + a)),
                  cy + 1.5 * radius * math.sin(math.radians(a0 + a)))
                 for a in np.linspace(0, 240, 25)]
        cv2.fillPoly(occ_mask, [np.asarray([(cx, cy)] + pts_o, np.int32)], 255)
        img[occ_mask > 0] = (32, 34, 38)
        mask[occ_mask > 0] = 0
        visibility = 0.0

    if hard_mode and rng.random() < 0.40:
        sigma = rng.uniform(0.5, 1.8)
        img = cv2.GaussianBlur(img, (0, 0), sigma)
    if hard_mode and rng.random() < 0.55:
        noise = np_rng.normal(0, rng.uniform(2.0, 9.0), img.shape)
        img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if hard_mode and rng.random() < 0.45:
        q = rng.randint(35, 85)
        ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if ok:
            img = cv2.imdecode(enc, cv2.IMREAD_COLOR)

    meta = {
        "template_id": template_id,
        "seed": seed,
        "size": size,
        "face_mode": tpl.face_mode,
        "needle_style": tpl.needle_style,
        "center": [round(cx, 2), round(cy, 2)],
        "tip": [round(tip_x, 2), round(tip_y, 2)],
        "scale_min_pt": [round(float(pts_kpt[2, 0]), 2), round(float(pts_kpt[2, 1]), 2)],
        "scale_max_pt": [round(float(pts_kpt[3, 0]), 2), round(float(pts_kpt[3, 1]), 2)],
        "angle_deg": round(angle_deg, 3),
        "value": round(true_val, 4),
        "v_min": tpl.v_min,
        "v_max": tpl.v_max,
        "direction": tpl.direction,
        "visibility": visibility,
    }
    return img, mask, meta
