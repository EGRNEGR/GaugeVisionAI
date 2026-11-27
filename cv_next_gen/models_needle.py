"""
GaugeVision AI 3.1 — Компактные коммерчески чистые нейросети определения стрелки (PyTorch / ONNX).

Две независимые архитектуры (чистый PyTorch, лицензия MIT / BSD-3, без AGPL-зависимостей):
  1. NeedleKeypointNet (Подход B2):
     • вход: RGB кроп циферблата 160×160 (нормализация (x - 0.5) / 0.5);
     • выход: 2D тепловые карты Soft-Argmax для центра вращения (cx, cy) и кончика (tx, ty),
       прямой циклический вектор (sin θ, cos θ) и логит видимости стрелки (vis_logit).
  2. NeedleSegUNet (Подход C2):
     • вход: RGB кроп циферблата 160×160;
     • выход: 3-классовая пиксельная маска 80×80 (0=фон, 1=риски шкалы, 2=стрелка) +
       1-канальная тепловая карта кончика стрелки (разрешение неоднозначности 180° с противовесом).
     • из маски стрелки извлекается ось методом взвешенного PCA / ODR, а направление кончика
       выбирается по карте кончика и радиальной асимметрии.
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

CROP_SIZE = 160


class DWSepConv(nn.Module):
    """Depthwise-Separable Conv + BatchNorm + SiLU (быстрый CPU-инференс)."""

    def __init__(self, in_ch: int, out_ch: int, stride: int = 1) -> None:
        super().__init__()
        self.dw = nn.Conv2d(in_ch, in_ch, 3, stride=stride, padding=1, groups=in_ch, bias=False)
        self.bn1 = nn.BatchNorm2d(in_ch)
        self.pw = nn.Conv2d(in_ch, out_ch, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_ch)
        self.act = nn.SiLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.act(self.bn1(self.dw(x)))
        x = self.act(self.bn2(self.pw(x)))
        return x


class ResDWBlock(nn.Module):
    def __init__(self, ch: int) -> None:
        super().__init__()
        self.conv = DWSepConv(ch, ch, stride=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.conv(x)


def spatial_soft_argmax(logits: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Дифференцируемый 2D Soft-Argmax.
    logits: (B, K, H, W) -> coords: (B, K, 2) в диапазоне [0, 1] (x, y), peak_prob: (B, K).
    """
    b, k, h, w = logits.shape
    flat = logits.view(b, k, -1)
    probs = F.softmax(flat, dim=-1).view(b, k, h, w)
    xs = torch.linspace(0.5 / w, 1.0 - 0.5 / w, w, device=logits.device, dtype=logits.dtype)
    ys = torch.linspace(0.5 / h, 1.0 - 0.5 / h, h, device=logits.device, dtype=logits.dtype)
    exp_x = (probs.sum(dim=2) * xs.view(1, 1, w)).sum(dim=-1)
    exp_y = (probs.sum(dim=3) * ys.view(1, 1, h)).sum(dim=-1)
    coords = torch.stack([exp_x, exp_y], dim=-1)
    peak = probs.view(b, k, -1).max(dim=-1).values
    return coords, peak


class NeedleKeypointNet(nn.Module):
    """Подход B2: компактная нейросеть ключевых точек (центр + кончик) и циклического угла."""

    def __init__(self, base_ch: int = 24) -> None:
        super().__init__()
        c1, c2, c3, c4 = base_ch, base_ch * 2, base_ch * 4, base_ch * 6
        self.stem = nn.Sequential(
            nn.Conv2d(3, c1, 3, stride=2, padding=1, bias=False),  # 80×80
            nn.BatchNorm2d(c1),
            nn.SiLU(inplace=True),
        )
        self.stage1 = nn.Sequential(DWSepConv(c1, c2, stride=2), ResDWBlock(c2))  # 40×40
        self.stage2 = nn.Sequential(DWSepConv(c2, c3, stride=2), ResDWBlock(c3), ResDWBlock(c3))  # 20×20
        self.stage3 = nn.Sequential(DWSepConv(c3, c4, stride=2), ResDWBlock(c4), ResDWBlock(c4))  # 10×10

        # FPN-слияние stage3 (10×10) -> stage2 (20×20) для точной 2D локализации кончика и центра
        self.lat3 = nn.Conv2d(c4, c3, 1, bias=False)
        self.kpt_head = nn.Sequential(
            DWSepConv(c3, c3, stride=1),
            nn.Conv2d(c3, 2, 1),  # 0: center, 1: tip
        )
        # Глобальная голова: (sin θ, cos θ, vis_logit)
        self.global_head = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(c4, 64),
            nn.SiLU(inplace=True),
            nn.Linear(64, 3),
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        f1 = self.stem(x)
        f2 = self.stage1(f1)
        f3 = self.stage2(f2)
        f4 = self.stage3(f3)
        fpn = f3 + F.interpolate(self.lat3(f4), size=f3.shape[-2:], mode="bilinear", align_corners=False)
        kpt_logits = self.kpt_head(fpn)  # (B, 2, 20, 20)
        coords, _ = spatial_soft_argmax(kpt_logits)  # (B, 2, 2)
        glob = self.global_head(f4)  # (B, 3): sin, cos, vis_logit
        sincos = F.normalize(glob[:, :2], dim=-1, eps=1e-6)
        vis_logit = glob[:, 2]
        return coords, sincos, vis_logit


class NeedleSegUNet(nn.Module):
    """Подход C2: компактный Depthwise-Separable U-Net для пиксельной сегментации стрелки и рисок."""

    def __init__(self, base_ch: int = 20) -> None:
        super().__init__()
        c1, c2, c3, c4 = base_ch, base_ch * 2, base_ch * 4, base_ch * 6
        self.stem = nn.Sequential(
            nn.Conv2d(3, c1, 3, stride=2, padding=1, bias=False),  # 80×80
            nn.BatchNorm2d(c1),
            nn.SiLU(inplace=True),
        )
        self.enc1 = nn.Sequential(DWSepConv(c1, c2, stride=2), ResDWBlock(c2))  # 40×40
        self.enc2 = nn.Sequential(DWSepConv(c2, c3, stride=2), ResDWBlock(c3))  # 20×20
        self.enc3 = nn.Sequential(DWSepConv(c3, c4, stride=2), ResDWBlock(c4))  # 10×10

        self.up2 = DWSepConv(c4 + c3, c3)
        self.up1 = DWSepConv(c3 + c2, c2)
        self.up0 = DWSepConv(c2 + c1, c1)
        self.seg_head = nn.Conv2d(c1, 3, 1)  # 0=bg, 1=ticks, 2=pointer (80×80)
        self.tip_head = nn.Conv2d(c1, 1, 1)  # тепловая карта кончика (80×80)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        s0 = self.stem(x)   # 80
        s1 = self.enc1(s0)  # 40
        s2 = self.enc2(s1)  # 20
        s3 = self.enc3(s2)  # 10
        u2 = self.up2(torch.cat([F.interpolate(s3, size=s2.shape[-2:], mode="bilinear", align_corners=False), s2], dim=1))
        u1 = self.up1(torch.cat([F.interpolate(u2, size=s1.shape[-2:], mode="bilinear", align_corners=False), s1], dim=1))
        u0 = self.up0(torch.cat([F.interpolate(u1, size=s0.shape[-2:], mode="bilinear", align_corners=False), s0], dim=1))
        return self.seg_head(u0), self.tip_head(u0)


def preprocess_crop(dial_bgr: np.ndarray, size: int = CROP_SIZE) -> np.ndarray:
    """BGR uint8 -> NCHW float32 RGB в диапазоне [-1, 1]."""
    resized = cv2.resize(dial_bgr, (size, size), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - 0.5) / 0.5
    return np.transpose(rgb, (2, 0, 1))[None, ...]


def extract_angle_from_seg(
    seg_probs: np.ndarray,
    tip_logits: np.ndarray,
    center_norm: tuple[float, float] = (0.5, 0.5),
    prob_thr: float = 0.35,
) -> dict[str, Any]:
    """
    Извлечение оси стрелки (взвешенный PCA / ODR) и разрешения направления кончика
    по 3-классовой вероятностной маске (3, H, W) и карте кончика (H, W).
    """
    _, h, w = seg_probs.shape
    p_ticks = seg_probs[1]
    p_ptr = seg_probs[2]
    ticks_frac = float((p_ticks > 0.35).mean())

    ys, xs = np.where(p_ptr >= prob_thr)
    if len(xs) < 12:
        return {"angle_deg": None, "confidence": 0.0, "ticks_frac": ticks_frac, "ptr_pixels": int(len(xs))}

    weights = p_ptr[ys, xs].astype(np.float64)
    w_sum = float(weights.sum())
    cx_m = float((xs * weights).sum() / w_sum)
    cy_m = float((ys * weights).sum() / w_sum)

    dx = xs.astype(np.float64) - cx_m
    dy = ys.astype(np.float64) - cy_m
    cov_xx = float((weights * dx * dx).sum() / w_sum)
    cov_xy = float((weights * dx * dy).sum() / w_sum)
    cov_yy = float((weights * dy * dy).sum() / w_sum)

    # Главная ось PCA (эквивалент ODR в 2D)
    vals, vecs = np.linalg.eigh(np.array([[cov_xx, cov_xy], [cov_xy, cov_yy]]))
    lam_min, lam_max = float(max(vals[0], 1e-8)), float(max(vals[1], 1e-8))
    elongation = 1.0 - math.sqrt(lam_min / lam_max)  # 1.0 = идеальная тонкая линия
    vx, vy = float(vecs[0, 1]), float(vecs[1, 1])

    # Разрешение направления (vx, vy) vs (-vx, -vy) по карте кончика и удалённости от центра
    t_flat = tip_logits.reshape(-1)
    t_max_idx = int(np.argmax(t_flat))
    ty_pred, tx_pred = divmod(t_max_idx, w)
    cx_ref, cy_ref = center_norm[0] * w, center_norm[1] * h

    # Вектор от центра к предсказанному кончику
    dot_tip = (tx_pred - cx_ref) * vx + (ty_pred - cy_ref) * vy
    # Проекция пикселей стрелки на ось от центра (кончик длиннее противовеса)
    proj = (xs - cx_ref) * vx + (ys - cy_ref) * vy
    pos_ext = float(np.percentile(proj, 95))
    neg_ext = float(-np.percentile(proj, 5))

    if abs(dot_tip) > 2.0:
        sign = 1.0 if dot_tip > 0 else -1.0
    else:
        sign = 1.0 if pos_ext >= neg_ext else -1.0

    vx *= sign
    vy *= sign
    angle_deg = math.degrees(math.atan2(vy, vx)) % 360.0

    # Координата кончика на нормализованном кропе [0, 1]
    proj_s = (xs - cx_ref) * vx + (ys - cy_ref) * vy
    tip_i = int(np.argmax(proj_s))
    tip_xy = (float(xs[tip_i]) / w, float(ys[tip_i]) / h)

    mean_prob = float(weights.mean())
    length_score = min(1.0, max(pos_ext, neg_ext) / (0.28 * w))
    conf = float(np.clip(mean_prob * elongation * length_score, 0.0, 1.0))

    return {
        "angle_deg": round(angle_deg, 2),
        "confidence": round(conf, 4),
        "elongation": round(elongation, 4),
        "ticks_frac": round(ticks_frac, 4),
        "ptr_pixels": int(len(xs)),
        "tip_norm": tip_xy,
    }
