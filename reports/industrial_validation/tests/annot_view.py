"""
Вид для ручной разметки калибровки: кроп изображения с координатной сеткой,
подписанной в пикселях ИСХОДНОГО изображения (разметчик читает координаты напрямую).

  python annot_view.py <image> <out.jpg> [x0 y0 x1 y1] [--max 900]
  python annot_view.py --sheet <out.jpg> <img1> <img2> ...   # обзорный лист с сеткой (поиск рамки циферблата)
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np


def nice_step(span: float, target: int = 24) -> int:
    raw = span / target
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500):
        if s >= raw:
            return s
    return 1000


def grid_view(img: np.ndarray, box: tuple[int, int, int, int] | None, max_dim: int = 900, label: str = "") -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box if box else (0, 0, w, h)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    crop = img[y0:y1, x0:x1]
    k = max_dim / max(crop.shape[:2])
    view = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    margin = 34
    canvas = np.full((view.shape[0] + margin, view.shape[1] + margin, 3), 255, np.uint8)
    canvas[margin:, margin:] = view
    step = nice_step(max(x1 - x0, y1 - y0))
    for gx in range((x0 // step + 1) * step, x1, step):
        vx = int((gx - x0) * k) + margin
        major = (gx // step) % 2 == 0
        cv2.line(canvas, (vx, margin), (vx, canvas.shape[0]), (0, 255, 255) if major else (255, 255, 0), 1)
        if major:
            cv2.putText(canvas, str(gx), (vx - 12, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 200), 1)
    for gy in range((y0 // step + 1) * step, y1, step):
        vy = int((gy - y0) * k) + margin
        major = (gy // step) % 2 == 0
        cv2.line(canvas, (margin, vy), (canvas.shape[1], vy), (0, 255, 255) if major else (255, 255, 0), 1)
        if major:
            cv2.putText(canvas, str(gy), (1, vy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 0, 200), 1)
    if label:
        cv2.putText(canvas, label, (margin + 4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    return canvas


def main() -> int:
    a = sys.argv[1:]
    if a and a[0] == "--sheet":
        out, files = a[1], a[2:]
        tiles = []
        for f in files:
            img = cv2.imread(f)
            t = grid_view(img, None, 440, Path(f).stem)
            pad = np.full((480, 480, 3), 255, np.uint8)
            pad[:t.shape[0], :t.shape[1]] = t
            tiles.append(pad)
        while len(tiles) % 3:
            tiles.append(np.full((480, 480, 3), 255, np.uint8))
        rows = [np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]
        cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 82])
        return 0
    img = cv2.imread(a[0])
    box = tuple(int(v) for v in a[2:6]) if len(a) >= 6 else None
    cv2.imwrite(a[1], grid_view(img, box, label=f"{Path(a[0]).stem} {img.shape[1]}x{img.shape[0]}"),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    return 0


if __name__ == "__main__":
    sys.exit(main())
