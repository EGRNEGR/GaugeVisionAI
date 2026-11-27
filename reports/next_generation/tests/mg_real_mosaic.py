"""
Multi-Gauge Vision на реальных фотографиях: мозаики из N = 1, 2, 4, 8, 16 снимков MeterFL.

Каждый снимок с человеческим эталоном показания вырезается вокруг размеченного центра шкалы, масштабируется
до размера ячейки и ставится на общий кадр 1280×720 (щит из реальных приборов). Эталонные центр и крайние
деления пересчитываются в координаты мозаики. Протокол тот же, что в REQ-CV-05:

  1. регистрация — детектор Multi-Gauge на первом кадре (как кнопка «Найти приборы», с плитками), кандидат
     сопоставляется с прибором по центру (≤ 0,3 радиуса шкалы). Пропущенные детектором приборы инженер
     обводит вручную — это моделируется кругом радиусом 1,15 радиуса шкалы вокруг эталонного центра;
     такие приборы считаются отдельно. Калибровка θmin/θmax — эталонные крайние деления через ROI прибора;
  2. 4 кадра с дрожанием камеры ±0,3 % и шумом — отсчёты MultiGaugeProcessor;
  3. сравнение — тот же прибор отдельно (одна ячейка на кадре того же размера) однокамерным GaugePipeline.

Эталон и положение стрелки для настройки не используются.

  python mg_real_mosaic.py --manifest ../../industrial_validation/data/dataset_manifest.json
                           --meterfl <dir> --role dev|final --out <json>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("GAUGEVISION_DEVICE", "cpu")
_TMP = Path(tempfile.mkdtemp(prefix="gv_mg_real_"))
os.environ["GAUGEVISION_DB"] = str(_TMP / "x.db")
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app import config, multigauge, vision  # noqa: E402

W, H = 1280, 720
GROUPS = {1: 40, 2: 20, 4: 10, 8: 6, 16: 3}
FRAMES = 4


def load_items(manifest: Path, meterfl: Path, role: str) -> list[dict]:
    man = json.loads(manifest.read_text(encoding="utf-8"))
    out = []
    for r in man["items"]:
        if r["dataset"] != "MeterFL" or r.get("role") != role or r.get("excluded"):
            continue
        if r.get("reading_gt") is None or not r.get("center") or r.get("scope") == "arc_panel":
            continue
        if r.get("scale_min") is None or r.get("scale_max") is None:
            continue
        r = dict(r)
        r["path"] = str(meterfl / "data" / r["client"] / r["side"] / r["file"])
        out.append(r)
    return out


def crop_tile(rec: dict, size: int) -> tuple[np.ndarray, dict] | None:
    img = cv2.imread(rec["path"])
    if img is None:
        return None
    c = np.array(rec["center"], float)
    f, l = np.array(rec["first_tick"], float), np.array(rec["last_tick"], float)
    r = float(rec.get("tick_radius") or 0.5 * (np.linalg.norm(f - c) + np.linalg.norm(l - c)))
    half = 1.45 * r
    x0, y0 = c - half
    side = int(round(2 * half))
    m = np.float32([[1, 0, -x0], [0, 1, -y0]])
    crop = cv2.warpAffine(img, m, (side, side), borderMode=cv2.BORDER_REPLICATE)
    k = size / float(side)
    tile = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    tr = lambda p: ((p[0] - x0) * k, (p[1] - y0) * k)  # noqa: E731
    return tile, {"center": tr(c), "first": tr(f), "last": tr(l), "r": r * k}


def theta_through(roi, pt) -> float:
    q = roi.matrix @ np.array([pt[0], pt[1], 1.0])
    cc = config.DIAL_SIZE / 2.0
    return math.degrees(math.atan2(q[1] - cc, q[0] - cc)) % 360.0


def make_mosaic(recs: list[dict], rng: random.Random):
    n = len(recs)
    cols = max(1, math.ceil(math.sqrt(n * W / H)))
    rows = max(1, math.ceil(n / cols))
    cw, ch = W / cols, H / rows
    canvas = np.full((H, W, 3), (70, 72, 74), np.uint8)
    gauges = []
    for i, rec in enumerate(recs):
        row, col = divmod(i, cols)
        size = int(min(cw, ch) * rng.uniform(0.82, 0.96))
        got = crop_tile(rec, size)
        if got is None:
            continue
        tile, geo = got
        ox = int((col + 0.5) * cw - size / 2 + rng.uniform(-0.03, 0.03) * cw)
        oy = int((row + 0.5) * ch - size / 2 + rng.uniform(-0.03, 0.03) * ch)
        ox, oy = max(0, min(W - size, ox)), max(0, min(H - size, oy))
        canvas[oy:oy + size, ox:ox + size] = tile
        sh = lambda p: (p[0] + ox, p[1] + oy)  # noqa: E731
        gauges.append({"rec": rec, "center": sh(geo["center"]), "first": sh(geo["first"]), "last": sh(geo["last"]),
                       "r": geo["r"], "tile": (ox, oy, size)})
    return canvas, gauges


def jitter(frame: np.ndarray, dx: float, dy: float, k: int) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    out = cv2.warpAffine(frame, m, (W, H), borderMode=cv2.BORDER_REPLICATE)
    noise = np.random.default_rng(k).normal(0, 2.0, out.shape)
    return np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def calib_for(g: dict, roi) -> dict:
    rec = g["rec"]
    return {"v_min": float(rec["scale_min"]), "v_max": float(rec["scale_max"]),
            "theta_min": round(theta_through(roi, g["first"]), 2), "theta_max": round(theta_through(roi, g["last"]), 2),
            "direction": rec.get("direction") or "cw"}


def err_of(rec: dict, value: float | None) -> float | None:
    if value is None:
        return None
    return abs(value - float(rec["reading_gt"])) / (float(rec["scale_max"]) - float(rec["scale_min"]))


def single_alone(g: dict, canvas: np.ndarray) -> float | None:
    """Тот же прибор один на кадре того же размера: однокамерный конвейер, та же процедура калибровки."""
    ox, oy, size = g["tile"]
    frame = np.full_like(canvas, (70, 72, 74))
    frame[oy:oy + size, ox:ox + size] = canvas[oy:oy + size, ox:ox + size]
    roi = vision.detect_dial(frame)
    if roi is None or math.dist(roi.center, g["center"]) > 0.3 * g["r"]:
        return None
    pipe = vision.GaugePipeline("single")
    r = pipe.process(frame, calib_for(g, roi), {}, "", with_overlay=False)
    return err_of(g["rec"], r.value) if r.valid else None


def run(items: list[dict], seed: int) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for n, groups in GROUPS.items():
        st = {"n": n, "gauges": 0, "registered": 0, "manual": 0, "manual_valid": 0, "manual_errs": [],
              "valid": 0, "errs": [], "single_valid": 0, "single_errs": [],
              "id_switches": 0, "lat": [], "detect_frames": 0}
        for gi in range(groups):
            recs = rng.sample(items, n)
            canvas, gauges = make_mosaic(recs, rng)
            dets, _ = multigauge.detect_dials_multi(canvas, tiled=True)  # как при регистрации на пульте
            instruments, own = [], {}
            for d in dets:
                g = min(gauges, key=lambda q: math.dist(q["center"], d.center))
                if math.dist(g["center"], d.center) > 0.3 * g["r"] or id(g) in [id(x) for x in own.values()]:
                    continue
                iid = f"g{len(own)}"
                own[iid] = g
                instruments.append({"id": iid, "unit": g["rec"].get("unit") or "", "calibration": calib_for(g, d),
                                    "thresholds": {}, "roi": multigauge.roi_to_anchor(d, canvas.shape)})
            st["gauges"] += len(gauges)
            st["registered"] += len(instruments)
            manual_ids = set()
            for g in gauges:
                if any(own_g is g for own_g in own.values()):
                    continue
                roi = vision.roi_from_ellipse(g["center"][0], g["center"][1], 1.15 * g["r"], 1.15 * g["r"], 0.0,
                                              score=1.0, source="manual")
                iid = f"m{len(own)}"
                own[iid] = g
                manual_ids.add(iid)
                instruments.append({"id": iid, "unit": g["rec"].get("unit") or "", "calibration": calib_for(g, roi),
                                    "thresholds": {}, "roi": multigauge.roi_to_anchor(roi, canvas.shape)})
            st["manual"] += len(manual_ids)
            proc = multigauge.MultiGaugeProcessor(f"m{n}-{gi}")
            last_ok: dict[str, bool] = {}
            for k in range(FRAMES):
                fr = jitter(canvas, rng.uniform(-0.003, 0.003) * H, rng.uniform(-0.003, 0.003) * H, k)
                t0 = time.perf_counter()
                res = proc.process(fr, instruments, with_overlay=False)
                st["lat"].append((time.perf_counter() - t0) * 1000.0)
                st["detect_frames"] += int(res.detected)
                for iid, g in own.items():
                    tr = proc.tracker.tracks.get(iid)
                    if tr is not None and tr.roi is not None:
                        near = min(gauges, key=lambda q: math.dist(q["center"], tr.roi.center))
                        if near is not g and math.dist(near["center"], tr.roi.center) < near["r"]:
                            st["id_switches"] += 1
                    if k == FRAMES - 1:
                        r = res.readings[iid]
                        last_ok[iid] = bool(r.valid)
                        if r.valid and iid in manual_ids:
                            st["manual_valid"] += 1
                            st["manual_errs"].append(err_of(g["rec"], r.value))
                        elif r.valid:
                            st["valid"] += 1
                            st["errs"].append(err_of(g["rec"], r.value))
            for g in gauges:
                e = single_alone(g, canvas)
                if e is not None:
                    st["single_valid"] += 1
                    st["single_errs"].append(e)
        rows.append(st)
        print(summary(st), flush=True)
    return rows


def _pct(v):
    return None if v is None else round(100.0 * v, 2)


def summary(st: dict) -> dict:
    def stats(errs):
        if not errs:
            return {"mean": None, "median": None, "p95": None, "gross": None}
        e = sorted(errs)
        return {"mean": _pct(statistics.fmean(e)), "median": _pct(statistics.median(e)),
                "p95": _pct(e[int(0.95 * (len(e) - 1))]), "gross": _pct(sum(x > 0.10 for x in e) / len(e))}
    return {
        "gauges_per_frame": st["n"], "gauges_total": st["gauges"],
        "registered_pct": _pct(st["registered"] / max(1, st["gauges"])),
        "valid_pct_of_all": _pct(st["valid"] / max(1, st["gauges"])),
        "multi": stats(st["errs"]),
        "manual_registered": st["manual"],
        "manual_valid_pct": _pct(st["manual_valid"] / max(1, st["manual"])) if st["manual"] else None,
        "manual": stats(st["manual_errs"]),
        "single_alone_valid_pct": _pct(st["single_valid"] / max(1, st["gauges"])),
        "single_alone": stats(st["single_errs"]),
        "id_switches": st["id_switches"],
        "latency_ms_mean": round(statistics.fmean(st["lat"]), 1) if st["lat"] else None,
        "detect_frames": st["detect_frames"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--meterfl", required=True)
    ap.add_argument("--role", choices=("dev", "final"), required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    items = load_items(Path(a.manifest), Path(a.meterfl), a.role)
    vision._load_yolo()
    rows = run(items, a.seed)
    out = {"role": a.role, "items_pool": len(items), "seed": a.seed, "frame": [W, H], "frames_per_mosaic": FRAMES,
           "device": "cpu", "yolo": vision.yolo_available(), "results": [summary(r) for r in rows]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
