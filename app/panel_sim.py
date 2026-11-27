"""
GaugeVision AI — синтетический щит из нескольких стрелочных приборов.

Используется стендовым источником Multi-Gauge (демонстрационный сценарий) и испытаниями
Multi-Gauge Vision: на кадре N приборов разного размера, у каждого известны положение, шкала
и истинное значение. Сцена поддерживает сдвиг камеры, перекрытие отдельного прибора,
изменение освещённости и шум — эталон пересчитывается вместе со сценой.

Кадры помечаются как синтетические и не выдаются за снимки действующего оборудования.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .stream_manager import render_gauge_frame

# Шкалы приборов щита: (единица, v_min, v_max) — те же 135° → 45° по часовой, 270°
PANEL_SCALES: tuple[tuple[str, float, float], ...] = (
    ("МПа", 0.0, 16.0), ("МПа", 0.0, 1.6), ("кПа", 0.0, 100.0), ("°C", 0.0, 150.0),
    ("МПа", 0.0, 2.5), ("кПа", 0.0, 250.0), ("°C", 0.0, 300.0), ("МПа", 0.0, 6.0),
)


@dataclass
class PanelGauge:
    index: int
    code: str
    unit: str
    v_min: float
    v_max: float
    cx: float          # центр в долях ширины / высоты кадра (без сдвига камеры)
    cy: float
    r: float           # радиус в долях меньшей стороны кадра
    value: float = 0.0

    @property
    def calibration(self) -> dict[str, Any]:
        return {"v_min": self.v_min, "theta_min": 135.0, "v_max": self.v_max, "theta_max": 45.0, "direction": "cw"}


@dataclass
class PanelScene:
    width: int = 1280
    height: int = 720
    gauges: list[PanelGauge] = field(default_factory=list)
    background: tuple[int, int, int] = (58, 62, 66)


def make_panel(n: int, width: int = 1280, height: int = 720, seed: int = 0,
               size_jitter: float = 0.25) -> PanelScene:
    """Щит n приборов в сетке, размеры варьируются на ±size_jitter."""
    rng = random.Random(seed)
    cols = max(1, math.ceil(math.sqrt(n * width / height)))
    rows = max(1, math.ceil(n / cols))
    cell_w, cell_h = width / cols, height / rows
    s = float(min(width, height))
    scene = PanelScene(width=width, height=height)
    for i in range(n):
        row, col = divmod(i, cols)
        unit, lo, hi = PANEL_SCALES[i % len(PANEL_SCALES)]
        k = 1.0 - size_jitter * rng.random()
        r_px = 0.40 * min(cell_w, cell_h) * k
        cx = (col + 0.5) * cell_w + rng.uniform(-0.05, 0.05) * cell_w
        cy = (row + 0.5) * cell_h + rng.uniform(-0.05, 0.05) * cell_h
        scene.gauges.append(PanelGauge(
            index=i, code=f"PI-{101 + i}", unit=unit, v_min=lo, v_max=hi,
            cx=cx / width, cy=cy / height, r=r_px / s,
            value=lo + (hi - lo) * rng.uniform(0.15, 0.85),
        ))
    return scene


def _gauge_tile(g: PanelGauge, r_px: int) -> np.ndarray:
    # render_gauge_frame рисует циферблат радиусом 0.41·min(w, h) и корпус +14 px
    side = int(math.ceil((r_px + 16) / 0.41)) | 1
    tile = render_gauge_frame(code=g.code, name=g.code, unit=g.unit, value=g.value,
                              v_min=g.v_min, v_max=g.v_max, width=side, height=side)
    return tile


def render_panel(scene: PanelScene, shift: tuple[float, float] = (0.0, 0.0),
                 occlude: set[int] | None = None, brightness: float = 1.0,
                 noise_sigma: float = 0.0, seed: int | None = None) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Кадр щита и эталон по каждому прибору (центр и радиус в пикселях этого кадра).

    shift — сдвиг камеры в долях меньшей стороны (изображение щита смещается целиком);
    occlude — индексы приборов, перекрытых наполовину посторонним предметом.
    """
    w, h = scene.width, scene.height
    s = float(min(w, h))
    frame = np.full((h, w, 3), scene.background, np.uint8)
    truth: list[dict[str, Any]] = []
    for g in scene.gauges:
        r_px = max(12, int(round(g.r * s)))
        tile = _gauge_tile(g, r_px)
        k = r_px / (0.41 * tile.shape[0])
        tile = cv2.resize(tile, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        th, tw = tile.shape[:2]
        cx = g.cx * w + shift[0] * s
        cy = g.cy * h + shift[1] * s
        x0, y0 = int(round(cx - tw / 2.0)), int(round(cy - th / 2.0))
        # вставка круглой маской: фон плитки не перекрывает соседей
        mask = np.zeros((th, tw), np.uint8)
        cv2.circle(mask, (tw // 2, th // 2), int(r_px + 14 * k + 1), 255, -1, cv2.LINE_AA)
        fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(w, x0 + tw), min(h, y0 + th)
        if fx1 > fx0 and fy1 > fy0:
            t = tile[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
            m = mask[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0, None].astype(np.float32) / 255.0
            roi = frame[fy0:fy1, fx0:fx1].astype(np.float32)
            frame[fy0:fy1, fx0:fx1] = (roi * (1 - m) + t.astype(np.float32) * m).astype(np.uint8)
        visible = 0 <= cx - r_px and cx + r_px <= w and 0 <= cy - r_px and cy + r_px <= h
        truth.append({"index": g.index, "code": g.code, "cx": cx, "cy": cy, "r": r_px * 1.0,
                      "value": g.value, "span": g.v_max - g.v_min, "visible": visible,
                      "occluded": bool(occlude and g.index in occlude)})
    for t in truth:
        if t["occluded"]:
            # тёмный предмет закрывает левую половину прибора вместе с корпусом
            x0, x1 = int(t["cx"] - t["r"] * 1.25), int(t["cx"] + t["r"] * 0.05)
            y0, y1 = int(t["cy"] - t["r"] * 1.25), int(t["cy"] + t["r"] * 1.25)
            cv2.rectangle(frame, (max(0, x0), max(0, y0)), (min(w - 1, x1), min(h - 1, y1)), (22, 24, 26), -1)
    if brightness != 1.0:
        frame = np.clip(frame.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    if noise_sigma > 0:
        rs = np.random.default_rng(seed)
        frame = np.clip(frame.astype(np.float32) + rs.normal(0, noise_sigma, frame.shape), 0, 255).astype(np.uint8)
    return frame, truth


def step_values(scene: PanelScene, rng: random.Random, rate: float = 0.01) -> None:
    """Независимое случайное блуждание значений приборов в пределах 5–95 % шкалы."""
    for g in scene.gauges:
        span = g.v_max - g.v_min
        g.value = min(g.v_max - 0.05 * span, max(g.v_min + 0.05 * span, g.value + rng.gauss(0, rate * span)))
