"""
Испытание Auto Calibration (NG-AC-01) по протоколу reports/next_generation/AUTO_CALIBRATION_PROTOCOL.md.

Эталон — первое и последнее размеченные деления MeterFL (углы через ту же ROI) и значения начала и
конца шкалы, шкала по часовой стрелке (как в REQ-CV-05). Положение стрелки и показание не используются.

  python autocal_eval.py --manifest ../../industrial_validation/data/dataset_manifest.json
                         --meterfl <dir> --role dev|final --mode manual|auto --out <json>

manual — ROI как у инженера: окружность по размеченному центру и радиусу делений с ошибкой
(сдвиг центра до 5 % радиуса, радиус ×U(0,90; 1,10), seed 0); auto — ROI детектора конвейера.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import statistics
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("GAUGEVISION_DEVICE", "cpu")
_TMP = Path(tempfile.mkdtemp(prefix="gv_autocal_"))
os.environ["GAUGEVISION_DB"] = str(_TMP / "x.db")
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app import autocal, config, vision  # noqa: E402

N_ARC = 50
OK_ERR, GROSS_ERR = 0.02, 0.10


def load_items(manifest: Path, meterfl: Path, role: str) -> list[dict]:
    man = json.loads(manifest.read_text(encoding="utf-8"))
    out = []
    for r in man["items"]:
        if r["dataset"] != "MeterFL" or r.get("role") != role or r.get("excluded"):
            continue
        if r.get("scope") != "round_dial" or not (r.get("center") and r.get("first_tick") and r.get("last_tick")):
            continue
        if r.get("scale_min") is None or r.get("scale_max") is None:
            continue
        r = dict(r)
        r["path"] = str(meterfl / "data" / r["client"] / r["side"] / r["file"])
        out.append(r)
    return out


def theta_through(roi, pt) -> float:
    q = roi.matrix @ np.array([pt[0], pt[1], 1.0])
    cc = config.DIAL_SIZE / 2.0
    return math.degrees(math.atan2(q[1] - cc, q[0] - cc)) % 360.0


def manual_roi(rec: dict, rng: random.Random):
    c = np.array(rec["center"], float)
    f, l = np.array(rec["first_tick"], float), np.array(rec["last_tick"], float)
    r = float(rec.get("tick_radius") or 0.5 * (np.linalg.norm(f - c) + np.linalg.norm(l - c)))
    ang = rng.uniform(0, 2 * math.pi)
    off = rng.uniform(0, 0.05) * r
    cx, cy = c[0] + off * math.cos(ang), c[1] + off * math.sin(ang)
    rr = r * rng.uniform(0.90, 1.10)
    return vision.roi_from_ellipse(cx, cy, rr, rr, 0.0, score=1.0, source="manual")


def calib_error(auto_cal: dict, ref_cal: dict) -> float:
    span = ref_cal["v_max"] - ref_cal["v_min"]
    th0 = ref_cal["theta_min"]
    sweep = (ref_cal["theta_max"] - th0) % 360.0
    worst = 0.0
    for k in range(N_ARC):
        th = (th0 + sweep * k / (N_ARC - 1)) % 360.0
        v_ref = vision.angle_to_value(th, ref_cal, clamp=1.0, max_overshoot=1.0)
        v_auto = vision.angle_to_value(th, auto_cal, clamp=1.0, max_overshoot=0.08)
        if v_auto is None or v_ref is None:
            return 1.0
        worst = max(worst, abs(v_auto - v_ref) / abs(span))
    return worst


def _pct(x: float) -> float:
    return round(100.0 * x, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--meterfl", type=Path, required=True)
    ap.add_argument("--role", choices=["dev", "final"], required=True)
    ap.add_argument("--mode", choices=["manual", "auto"], default="manual")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if not autocal.available():
        print("OCR недоступно", file=sys.stderr)
        return 2
    items = load_items(args.manifest, args.meterfl, args.role)
    rng = random.Random(0)
    rows = []
    warm = None
    for rec in items:
        img = cv2.imread(rec["path"])
        if img is None:
            continue
        if warm is None:     # первый вызов OCR прогревает сессии ONNX — в замер времени не входит
            warm = autocal.propose_wide(np.full((config.DIAL_SIZE, config.DIAL_SIZE, 3), 255, np.uint8))
        roi = manual_roi(rec, rng) if args.mode == "manual" else vision.detect_dial(img)
        row = {"file": rec["file"], "group": rec["group"], "model": rec.get("model"),
               "scale": [rec["scale_min"], rec["scale_max"]], "n_ticks": rec.get("n_ticks")}
        if roi is None:
            row.update({"ok": False, "reason": "no_dial", "ms": None})
            rows.append(row)
            continue
        ref = {"v_min": float(rec["scale_min"]), "v_max": float(rec["scale_max"]), "direction": "cw",
               "theta_min": theta_through(roi, rec["first_tick"]), "theta_max": theta_through(roi, rec["last_tick"])}
        pr = autocal.propose(img, roi)
        row.update({"ok": pr.ok, "reason": pr.reason, "ms": round(pr.ms, 1), "confidence": round(pr.confidence, 3),
                    "calibration": pr.calibration, "reference": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in ref.items()},
                    "labels": [(lb.text, round(lb.angle, 1)) for lb in pr.labels], "inliers": pr.inliers, "debug": pr.debug})
        if pr.ok:
            row["err"] = round(calib_error(pr.calibration, ref), 4)
            row["limits_ok"] = (math.isclose(pr.calibration["v_min"], ref["v_min"], abs_tol=1e-9)
                                and math.isclose(pr.calibration["v_max"], ref["v_max"], abs_tol=1e-9))
        rows.append(row)
        if args.verbose:
            print(rec["group"], rec["file"], row["reason"] or f"err={row['err']:.3f}", row.get("calibration"),
                  "ref", row["reference"], flush=True)

    n = len(rows)
    acc = [r for r in rows if r["ok"]]
    good = [r for r in acc if r["err"] <= OK_ERR]
    gross = [r for r in acc if r["err"] > GROSS_ERR]
    lim = [r for r in acc if r["limits_ok"]]
    ms = [r["ms"] for r in rows if r.get("ms") is not None]
    by_model = collections.defaultdict(lambda: {"n": 0, "accepted": 0, "good": 0, "gross": 0})
    for r in rows:
        m = by_model[r["group"].split(":")[0] if r["group"].startswith("M") and not r["group"].startswith("MB") else r["group"]]
        m["n"] += 1
        if r["ok"]:
            m["accepted"] += 1
            m["good"] += r["err"] <= OK_ERR
            m["gross"] += r["err"] > GROSS_ERR
    summary = {
        "role": args.role, "mode": args.mode, "images": n, "models": len({r["group"] for r in rows}),
        "coverage_pct": _pct(len(acc) / max(1, n)),
        "accurate_of_accepted_pct": _pct(len(good) / max(1, len(acc))),
        "gross_of_all_pct": _pct(len(gross) / max(1, n)),
        "gross_of_accepted_pct": _pct(len(gross) / max(1, len(acc))),
        "limits_ok_of_accepted_pct": _pct(len(lim) / max(1, len(acc))),
        "median_ms": round(statistics.median(ms), 1) if ms else None,
        "p95_ms": round(sorted(ms)[int(0.95 * (len(ms) - 1))], 1) if ms else None,
        "err_median_pct": _pct(statistics.median([r["err"] for r in acc])) if acc else None,
        "refusals": dict(collections.Counter(r["reason"] for r in rows if not r["ok"])),
    }
    gates = {
        "G1": summary["gross_of_all_pct"] <= 1.0 and summary["gross_of_accepted_pct"] <= 2.0,
        "G2": summary["accurate_of_accepted_pct"] >= 90.0,
        "G3": summary["coverage_pct"] >= 50.0,
        "G4": summary["limits_ok_of_accepted_pct"] >= 95.0,
        "G5": summary["median_ms"] is not None and summary["median_ms"] <= 3000.0,
    }
    summary["gates"] = gates
    summary["admitted"] = all(gates.values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "by_group": by_model, "rows": rows}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
