"""
Группировка снимков по физическому прибору (модель/экземпляр), чтобы кадры одного прибора
не попали одновременно в разработочную и финальную выборки.

Признак: эмбеддинг ResNet-18 (ImageNet) кропа циферблата вокруг эталонного центра шкалы,
стрелка закрашена по своему полигону (кадры одного прибора с разными показаниями сближаются).
Кластеры — сферический k-means (k=16, 10 перезапусков, лучшая сумма близостей), затем ручная
визуальная проверка контактных листов: кластер → модель прибора (MODEL_OF_CLUSTER в build_split.py).
Связные компоненты по порогу близости проверялись и отвергнуты: цепочки склеивают все манометры в один кластер.

  python group_instruments.py --meterfl <dir> --out <dir>
CPU-only: CUDA_VISIBLE_DEVICES="".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv_gt  # noqa: E402


def dial_crop(g: cv_gt.GaugeGT, size: int = 224) -> np.ndarray | None:
    im = cv2.imread(str(g.path))
    if im is None:
        return None
    if g.center is None or not g.tick_radius:
        h, w = im.shape[:2]
        c, r = (w / 2.0, h / 2.0), 0.45 * min(h, w)
    else:
        c, r = g.center, 1.35 * g.tick_radius
    if g.pointer_pts:
        mask = np.zeros(im.shape[:2], np.uint8)
        cv2.fillPoly(mask, [np.asarray(g.pointer_pts, np.int32)], 255)
        mask = cv2.dilate(mask, np.ones((9, 9), np.uint8))
        im = cv2.inpaint(im, mask, 5, cv2.INPAINT_TELEA)
    x0, y0 = int(c[0] - r), int(c[1] - r)
    s = int(2 * r)
    pad = s
    big = cv2.copyMakeBorder(im, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    crop = big[y0 + pad:y0 + pad + s, x0 + pad:x0 + pad + s]
    if crop.size == 0:
        return None
    return cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)


def embed(crops: list[np.ndarray]) -> np.ndarray:
    import torch
    import torchvision
    w = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
    model = torchvision.models.resnet18(weights=w)
    model.fc = torch.nn.Identity()
    model.eval()
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    out = []
    with torch.no_grad():
        for i in range(0, len(crops), 64):
            batch = np.stack([cv2.cvtColor(c, cv2.COLOR_BGR2RGB) for c in crops[i:i + 64]]).astype(np.float32) / 255.0
            x = (torch.from_numpy(batch).permute(0, 3, 1, 2) - mean) / std
            out.append(model(x).numpy())
    e = np.concatenate(out)
    return e / np.linalg.norm(e, axis=1, keepdims=True)


def spherical_kmeans(x: np.ndarray, k: int = 16, restarts: int = 10) -> np.ndarray:
    best, best_score = None, -1.0
    for seed in range(restarts):
        rng = np.random.default_rng(seed)
        c = x[rng.choice(len(x), k, replace=False)]
        for _ in range(60):
            lab = np.argmax(x @ c.T, 1)
            nc = np.stack([x[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
            nc /= np.linalg.norm(nc, axis=1, keepdims=True)
            if np.allclose(nc, c):
                break
            c = nc
        score = float((x * c[lab]).sum())
        if score > best_score:
            best, best_score = lab, score
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meterfl", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=16)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    gts = cv_gt.load_meterfl(Path(args.meterfl))
    crops, keep = [], []
    for g in gts:
        c = dial_crop(g)
        if c is not None:
            crops.append(c)
            keep.append(g)
    cache = out / "embeddings.npy"
    if cache.is_file() and len(np.load(cache)) == len(keep):
        e = np.load(cache)
    else:
        e = embed(crops)
        np.save(cache, e)
    labels = [int(v) for v in spherical_kmeans(e, args.k)]
    rows = [{"file": g.file, "series": g.series, "side": g.side, "client": g.client, "cluster": int(l),
             "scale": [g.scale_min, g.scale_max] if g.has_scale else None}
            for g, l in zip(keep, labels)]
    (out / "clusters.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    cnt = Counter(labels)
    (out / "labels.json").write_text(json.dumps({g.file: l for g, l in zip(keep, labels)}), encoding="utf-8")
    print(f"{len(keep)} снимков, {len(cnt)} кластеров; размеры: {cnt.most_common()}")
    # контактные листы кластеров с ≥ 3 снимками
    for cl, n in cnt.most_common():
        if n < 3:
            continue
        idx = [i for i, l in enumerate(labels) if l == cl]
        pick = idx[:: max(1, len(idx) // 12)][:12]
        tiles = [cv2.resize(crops[i], (150, 150)) for i in pick]
        while len(tiles) < 12:
            tiles.append(np.zeros((150, 150, 3), np.uint8))
        sheet = np.vstack([np.hstack(tiles[r * 6:(r + 1) * 6]) for r in range(2)])
        cv2.putText(sheet, f"cluster {cl}: n={n}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        cv2.imwrite(str(out / f"cluster_{cl:03d}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return 0


if __name__ == "__main__":
    sys.exit(main())
