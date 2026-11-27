"""
Оценка ПРОИЗВОДСТВЕННОГО CV-конвейера GaugeVision AI (vision.GaugePipeline) на реальных фотографиях.

Протокол одного снимка повторяет пусконаладку на пульте:
  1. кадр масштабируется так же, как в GaugePipeline.process (ширина ≤ MAX_PROCESS_WIDTH);
  2. конвейер сам локализует циферблат (vision.detect_dial, при неудаче — frame_roi);
  3. «инженер» отмечает первое и последнее деление шкалы: точки переводятся в углы θmin/θmax через
     найденный эллипс — ровно как static/js/console/control.js (кнопки «θmin/θmax по кадру»);
  4. GaugePipeline.process() выдаёт показание; используется мгновенное значение одного кадра.
Эталонное показание и положение стрелки в калибровку и в работу конвейера не передаются.

  python eval_cv_pipeline.py --code-root <repo> --manifest data/dataset_manifest.json --meterfl <dir>
         --measurebench <export_dir> --subset primary|arc|final|dev|all --label baseline --out <dir>
  python eval_cv_pipeline.py ... --unusable          # набор заведомо непригодных кадров (оценка отказов)
CPU-only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ.setdefault("YOLO_OFFLINE", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def setup_code(code_root: Path):
    tmp = Path(tempfile.mkdtemp(prefix="gv_cv_eval_"))
    os.environ["GAUGEVISION_DB"] = str(tmp / "eval.db")
    os.environ["YOLO_CONFIG_DIR"] = str(tmp / "yolo_cfg")
    sys.path.insert(0, str(code_root))
    from app import config, vision  # noqa: WPS433
    return config, vision


def image_path(rec: dict[str, Any], meterfl: Path, mb: Path) -> Path:
    if rec["dataset"] == "MeterFL":
        return meterfl / "data" / rec["client"] / rec["side"] / rec["file"]
    return mb / "img" / rec["file"]


def theta_through_roi(roi, pt: tuple[float, float], dial_size: int) -> float:
    q = roi.matrix @ np.array([pt[0], pt[1], 1.0])
    c = dial_size / 2.0
    return math.degrees(math.atan2(q[1] - c, q[0] - c)) % 360.0


def gt_value(rec: dict[str, Any]) -> tuple[str, Any]:
    if rec.get("reading_gt") is not None:
        return "point", float(rec["reading_gt"])
    iv = rec.get("gt_interval") or rec.get("mb_interval")
    if iv:
        lo, hi = sorted(float(v) for v in iv)
        return "interval", (lo, hi)
    if rec.get("frac_lin") is not None:
        return "frac", float(rec["frac_lin"])
    return "none", None


def evaluate_item(rec: dict[str, Any], frame: np.ndarray, config, vision, degrade: str | None = None) -> dict[str, Any]:
    h0, w0 = frame.shape[:2]
    k = 1.0
    if w0 > config.MAX_PROCESS_WIDTH:
        k = config.MAX_PROCESS_WIDTH / float(w0)
        frame = cv2.resize(frame, (int(w0 * k), int(h0 * k)), interpolation=cv2.INTER_AREA)
    sc = lambda p: (float(p[0]) * k, float(p[1]) * k)  # noqa: E731
    out: dict[str, Any] = {"file": rec["file"], "dataset": rec["dataset"], "model": rec.get("model"),
                           "client": rec.get("client"), "gt_type": rec.get("gt_type"), "tags": rec.get("tags") or [],
                           "degrade": degrade, "width": int(frame.shape[1]), "height": int(frame.shape[0])}
    t0 = time.perf_counter()
    roi = vision.detect_dial(frame)
    if roi is None:
        roi = vision.frame_roi(frame)
    t_det = (time.perf_counter() - t0) * 1000.0
    first, last = sc(rec["first_tick"]), sc(rec["last_tick"])
    gt_c = sc(rec["center"]) if rec.get("center") else None
    if rec.get("tick_radius"):
        r_gt = float(rec["tick_radius"]) * k
    elif gt_c:
        r_gt = 0.5 * (math.dist(first, gt_c) + math.dist(last, gt_c))
    else:
        r_gt = None
    out["roi_source"] = roi.source
    out["roi_center"] = [round(roi.center[0], 1), round(roi.center[1], 1)]
    out["roi_axes"] = [round(roi.axes[0], 1), round(roi.axes[1], 1)]
    if gt_c and r_gt:
        out["center_err_rel"] = round(math.dist(roi.center, gt_c) / r_gt, 4)
        out["axis_ratio_to_ticks"] = round(max(roi.axes) / r_gt, 3)
        # для стрелочных щитовых приборов (ось вне дуги) критерий «эллипс циферблата» неприменим
        if rec.get("scope") != "arc_panel":
            out["det_ok"] = bool(roi.source != "frame" and out["center_err_rel"] <= 0.25
                                 and 0.7 <= out["axis_ratio_to_ticks"] <= 2.2)
    v_min = float(rec["scale_min"]) if rec.get("scale_min") is not None else 0.0
    v_max = float(rec["scale_max"]) if rec.get("scale_max") is not None else 1.0
    if rec.get("gt_type") == "mask_proxy":
        v_min, v_max = 0.0, 1.0
    calib = {"v_min": v_min, "v_max": v_max,
             "theta_min": round(theta_through_roi(roi, first, config.DIAL_SIZE), 2),
             "theta_max": round(theta_through_roi(roi, last, config.DIAL_SIZE), 2),
             "direction": rec.get("direction") or "cw"}
    out["calibration"] = calib
    if rec.get("pointer_tip"):
        tip = sc(rec["pointer_tip"])
        out["gt_needle_theta"] = round(theta_through_roi(roi, tip, config.DIAL_SIZE), 2)
        out["oracle_value"] = vision.angle_to_value(out["gt_needle_theta"], calib)
    pipe = vision.GaugePipeline("cv-eval")
    t1 = time.perf_counter()
    reading = pipe.process(frame, calib, {}, rec.get("unit") or "", with_overlay=False)
    out["process_ms"] = round((time.perf_counter() - t1) * 1000.0, 1)
    out["detect_ms"] = round(t_det, 1)
    dbg = reading.debug or {}
    rc = (dbg.get("roi") or {}).get("center")
    out["roi_consistent"] = bool(rc and math.dist(rc, roi.center) < 1.0)
    out["valid"] = bool(reading.valid)
    out["value"] = reading.value
    out["angle"] = reading.angle
    out["needle_conf"] = reading.needle_confidence
    out["needle_method"] = dbg.get("needle_method")
    out["invalid_reason"] = None if reading.valid else (dbg.get("invalid_reason") or "invalid")
    out["dial_quality"] = dbg.get("dial_quality")
    if out.get("gt_needle_theta") is not None and reading.angle is not None:
        out["angle_err"] = round(vision._ang_diff(float(reading.angle), out["gt_needle_theta"]), 2)
    kind, gt = gt_value(rec)
    span = abs(v_max - v_min)
    out["gt_kind"], out["span"] = kind, span
    if kind == "point":
        out["gt"] = gt
    elif kind == "interval":
        out["gt"] = list(gt)
    elif kind == "frac":
        out["gt"] = gt
    if reading.valid and reading.value is not None and kind != "none":
        v = float(reading.value)
        if kind == "interval":
            lo, hi = gt
            err = 0.0 if lo <= v <= hi else min(abs(v - lo), abs(v - hi))
            out["in_interval"] = bool(lo <= v <= hi)
        else:
            err = abs(v - gt)
        out["err_abs"] = err
        out["err_norm"] = err / span if span else None
    if out.get("oracle_value") is not None and kind == "interval":
        lo, hi = gt
        ov = float(out["oracle_value"])
        out["oracle_err_norm"] = (0.0 if lo <= ov <= hi else min(abs(ov - lo), abs(ov - hi))) / span if span else None
    if out.get("oracle_value") is not None and kind in ("point", "frac"):
        out["oracle_err_norm"] = abs(out["oracle_value"] - gt) / span if span else None
    return out


# ---------------------------------------------------------------------------
# Заведомо непригодные кадры (корректный ответ — отказ от считывания)
# ---------------------------------------------------------------------------
def degrade_frame(frame: np.ndarray, rec: dict[str, Any], kind: str, rng: random.Random) -> np.ndarray:
    h, w = frame.shape[:2]
    c = rec.get("center") or (w / 2.0, h / 2.0)
    r = float(rec.get("tick_radius") or 0.0) or 0.5 * (math.dist(rec["first_tick"], c) + math.dist(rec["last_tick"], c))
    f = frame.astype(np.float32)
    if kind == "dark":            # почти полная темнота (ночь, выключенное освещение)
        out = f * 0.04 + np.random.default_rng(rng.randint(0, 10**6)).normal(0, 2.0, f.shape)
    elif kind == "overexposed":   # засветка прожектором/солнцем
        out = 235.0 + f * 0.08
    elif kind == "occluded":      # 70 % циферблата перекрыто непрозрачным предметом
        out = f.copy()
        mask = np.zeros((h, w), np.uint8)
        ang = rng.uniform(0, 360)
        pts = [(c[0] + 1.6 * r * math.cos(math.radians(ang + a)), c[1] + 1.6 * r * math.sin(math.radians(ang + a)))
               for a in np.linspace(0, 252, 30)]
        cv2.fillPoly(mask, [np.asarray([c] + pts, np.int32)], 255)
        out[mask > 0] = (38.0, 36.0, 34.0)
    elif kind == "blur":          # расфокус: размытие Гаусса σ = 0,2 радиуса шкалы
        s = max(3.0, 0.2 * r)
        out = cv2.GaussianBlur(f, (0, 0), s)
    else:
        raise ValueError(kind)
    return np.clip(out, 0, 255).astype(np.uint8)


def build_unusable(manifest: dict[str, Any], mb_dir: Path, n_per_kind: int, seed: int = 0) -> list[tuple[dict, str]]:
    rng = random.Random(seed)
    prim = [r for r in manifest["items"] if r.get("primary")]
    jobs: list[tuple[dict, str]] = []
    for kind in ("dark", "overexposed", "occluded", "blur"):
        for rec in rng.sample(prim, min(n_per_kind, len(prim))):
            jobs.append((rec, kind))
    # реальные снимки неподходящих приборов: цифровые индикаторы и линейные шкалы MeasureBench
    mb = [json.loads(l) for l in (mb_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    other = [r for r in mb if r["design"] in ("digital", "linear")]
    for r in rng.sample(other, min(n_per_kind, len(other))):
        rec = {"dataset": "MeasureBench", "file": r["file"], "model": "non_dial", "client": r["image_type"],
               "gt_type": "unusable", "center": [r["width"] / 2.0, r["height"] / 2.0],
               "first_tick": [r["width"] * 0.3, r["height"] * 0.75], "last_tick": [r["width"] * 0.7, r["height"] * 0.75],
               "scale_min": 0.0, "scale_max": 100.0, "tags": [r["design"]]}
        jobs.append((rec, f"non_dial_{r['design']}"))
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-root", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--meterfl", required=True)
    ap.add_argument("--measurebench", required=True)
    ap.add_argument("--subset", default="primary", choices=["primary", "arc", "final", "dev", "all"])
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--out", required=True)
    ap.add_argument("--unusable", action="store_true")
    ap.add_argument("--n-per-kind", type=int, default=60)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    config, vision = setup_code(Path(args.code_root))
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    meterfl, mb = Path(args.meterfl), Path(args.measurebench)
    if args.unusable:
        jobs = build_unusable(manifest, mb, args.n_per_kind)
        name = f"{args.label}_unusable"
    else:
        items = [r for r in manifest["items"] if not r.get("excluded")]
        if args.subset == "primary":
            items = [r for r in items if r.get("primary")]
        elif args.subset == "arc":
            items = [r for r in items if r.get("arc_scope_eval")]
        elif args.subset in ("final", "dev"):
            items = [r for r in items if r["role"] == args.subset]
        jobs = [(r, None) for r in items]
        name = f"{args.label}_{args.subset}"
    if args.limit:
        jobs = jobs[:args.limit]
    yolo = vision.yolo_available()
    rng = random.Random(1)
    t_start = time.time()
    path = out_dir / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i, (rec, kind) in enumerate(jobs):
            frame = cv2.imread(str(image_path(rec, meterfl, mb)))
            if frame is None:
                fh.write(json.dumps({"file": rec["file"], "error": "unreadable"}, ensure_ascii=False) + "\n")
                continue
            if kind and not kind.startswith("non_dial"):
                frame = degrade_frame(frame, rec, kind, rng)
            try:
                res = evaluate_item(rec, frame, config, vision, degrade=kind)
            except Exception as exc:  # фиксируем, но не прерываем прогон
                res = {"file": rec["file"], "dataset": rec["dataset"], "error": f"{type(exc).__name__}: {exc}"}
            fh.write(json.dumps(res, ensure_ascii=False, default=float) + "\n")
            if (i + 1) % 100 == 0:
                print(f"{i + 1}/{len(jobs)} за {time.time() - t_start:.0f} с", flush=True)
    meta = {"label": args.label, "subset": args.subset, "unusable": args.unusable, "n": len(jobs),
            "yolo": yolo, "yolo_device": vision.yolo_device(), "code_root": str(Path(args.code_root).resolve()),
            "seconds": round(time.time() - t_start, 1)}
    (out_dir / f"{name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
