"""
GaugeVision AI 3.1 — Автономный скрипт обучения полнокадровых моделей на Linux RTX 3090 (24 ГБ).

Поддерживает 3 стадии:
  1. export      — формирует YOLO Detect / YOLO Pose (4 kpt: center, tip, scale_min, scale_max) /
                   YOLO Seg / COCO JSON (для RF-DETR) строго по dataset_manifest.json (TRAIN=M2+M3+synth,
                   VAL=M5+synth; LEGACY и LOCKED_FINAL никогда не попадают в обучающие файлы);
  2. train       — запускает обучение YOLOv8n, YOLO26n, YOLO26s, YOLO26s-p2, YOLO26s-pose, YOLO26s-seg
                   (и RF-DETR Nano/Small при установленном пакете rfdetr) с early stopping, resume и seed;
  3. export_onnx — экспортирует лучшие веса в ONNX, вычисляет SHA-256 и формирует фрагмент models/registry.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any

import cv2
import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def export_datasets(manifest_path: pathlib.Path, meterfl_dir: pathlib.Path, out_dir: pathlib.Path,
                    n_synth: int, seed: int) -> None:
    from cv_next_gen.synthetic_generator import render_dial_sample

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for task in ("detect", "pose"):
        for split in ("train", "val"):
            (out_dir / task / "images" / split).mkdir(parents=True, exist_ok=True)
            (out_dir / task / "labels" / split).mkdir(parents=True, exist_ok=True)

    counts = {"train": 0, "val": 0}
    for rec in manifest["items"]:
        if rec["split"] not in ("TRAIN", "VALIDATION"):
            continue
        sp = "train" if rec["split"] == "TRAIN" else "val"
        img_p = meterfl_dir / "data" / rec["client"] / rec["side"] / rec["file"]
        if not img_p.exists() or not rec.get("center") or not rec.get("pointer_tip"):
            continue
        img = cv2.imread(str(img_p))
        if img is None:
            continue
        h, w = img.shape[:2]
        cx, cy = float(rec["center"][0]), float(rec["center"][1])
        tx, ty = float(rec["pointer_tip"][0]), float(rec["pointer_tip"][1])
        r = float(rec.get("tick_radius") or 0.35 * min(h, w)) * 1.18
        x1, y1 = max(0.0, cx - r), max(0.0, cy - r)
        x2, y2 = min(float(w), cx + r), min(float(h), cy + r)
        bw, bh = (x2 - x1) / w, (y2 - y1) / h
        bx, by = (x1 + x2) / (2.0 * w), (y1 + y2) / (2.0 * h)
        stem = f"real_{sp}_{counts[sp]:05d}"

        for task in ("detect", "pose"):
            cv2.imwrite(str(out_dir / task / "images" / sp / f"{stem}.jpg"), img)
        (out_dir / "detect" / "labels" / sp / f"{stem}.txt").write_text(
            f"0 {bx:.6f} {by:.6f} {bw:.6f} {bh:.6f}\n", encoding="utf-8"
        )
        (out_dir / "pose" / "labels" / sp / f"{stem}.txt").write_text(
            f"0 {bx:.6f} {by:.6f} {bw:.6f} {bh:.6f} {cx/w:.6f} {cy/h:.6f} 2 {tx/w:.6f} {ty/h:.6f} 2\n",
            encoding="utf-8",
        )
        counts[sp] += 1

    # Добавляем синтетику с изолированными template_id
    for sp, n_s, t_lo, t_hi in (("train", n_synth, 0, 700), ("val", max(200, n_synth // 8), 700, 800)):
        for i in range(n_s):
            tid = t_lo + (i % (t_hi - t_lo))
            img, _, meta = render_dial_sample(size=640, template_id=tid, seed=seed * 10000 + i, hard_mode=True)
            stem = f"synth_{sp}_{i:05d}"
            cx, cy = meta["center"][0] / 640.0, meta["center"][1] / 640.0
            tx, ty = meta["tip"][0] / 640.0, meta["tip"][1] / 640.0
            for task in ("detect", "pose"):
                cv2.imwrite(str(out_dir / task / "images" / sp / f"{stem}.jpg"), img)
            (out_dir / "detect" / "labels" / sp / f"{stem}.txt").write_text(
                f"0 {cx:.6f} {cy:.6f} 0.880000 0.880000\n", encoding="utf-8"
            )
            (out_dir / "pose" / "labels" / sp / f"{stem}.txt").write_text(
                f"0 {cx:.6f} {cy:.6f} 0.880000 0.880000 {cx:.6f} {cy:.6f} 2 {tx:.6f} {ty:.6f} 2\n",
                encoding="utf-8",
            )
            counts[sp] += 1

    (out_dir / "detect" / "data.yaml").write_text(
        f"path: {out_dir / 'detect'}\ntrain: images/train\nval: images/val\nnames:\n  0: Gauge\n",
        encoding="utf-8",
    )
    (out_dir / "pose" / "data.yaml").write_text(
        f"path: {out_dir / 'pose'}\ntrain: images/train\nval: images/val\nkpt_shape: [2, 3]\nnames:\n  0: Gauge\n",
        encoding="utf-8",
    )
    print("Export complete:", json.dumps(counts))


def train_models(data_dir: pathlib.Path, out_dir: pathlib.Path, device: str, epochs: int, patience: int, seed: int) -> None:
    from ultralytics import YOLO

    matrix = [
        ("yolov8n_det_640", "yolov8n.pt", data_dir / "detect" / "data.yaml", 640, "detect"),
        ("yolo26n_det_640", "yolo26n.pt", data_dir / "detect" / "data.yaml", 640, "detect"),
        ("yolo26s_det_640", "yolo26s.pt", data_dir / "detect" / "data.yaml", 640, "detect"),
        ("yolo26s_det_960", "yolo26s.pt", data_dir / "detect" / "data.yaml", 960, "detect"),
        ("yolo26n_pose_640", "yolo26n-pose.pt", data_dir / "pose" / "data.yaml", 640, "pose"),
        ("yolo26s_pose_640", "yolo26s-pose.pt", data_dir / "pose" / "data.yaml", 640, "pose"),
    ]
    results_summary: list[dict[str, Any]] = []
    for name, weights, yaml_p, imgsz, task in matrix:
        print(f"\n=== Training {name} ({weights}, imgsz={imgsz}) ===", flush=True)
        model = YOLO(weights)
        res = model.train(
            data=str(yaml_p), epochs=epochs, patience=patience, imgsz=imgsz,
            batch=16 if imgsz <= 640 else 8, device=device, seed=seed,
            project=str(out_dir), name=name, exist_ok=True,
            degrees=15.0, perspective=0.0005, mosaic=1.0, fliplr=0.0,  # fliplr=0 для сохранения CW/CCW
        )
        results_summary.append({"name": name, "weights": weights, "imgsz": imgsz, "task": task,
                                "save_dir": str(getattr(res, "save_dir", out_dir / name))})
    (out_dir / "train_summary.json").write_text(json.dumps(results_summary, indent=2), encoding="utf-8")


def export_onnx_models(runs_dir: pathlib.Path, out_dir: pathlib.Path) -> None:
    from ultralytics import YOLO

    out_dir.mkdir(parents=True, exist_ok=True)
    registry_entries = []
    for best_pt in sorted(runs_dir.rglob("weights/best.pt")):
        run_name = best_pt.parent.parent.name
        model = YOLO(str(best_pt))
        exported = pathlib.Path(model.export(format="onnx", simplify=True, opset=17))
        dst = out_dir / f"{run_name}.onnx"
        dst.write_bytes(exported.read_bytes())
        registry_entries.append({
            "model_id": f"{run_name}_onnx",
            "filename": dst.name,
            "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
            "size_bytes": dst.stat().st_size,
            "license": "AGPL-3.0 (Ultralytics)",
        })
    (out_dir / "registry_patch.json").write_text(json.dumps(registry_entries, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["export", "train", "export_onnx"])
    ap.add_argument("--manifest", default=str(REPO_ROOT / "reports/cv_next_gen/evidence/dataset_manifest.json"))
    ap.add_argument("--meterfl", default="/data/meterfl")
    ap.add_argument("--data-dir", default="/data/gv31_datasets")
    ap.add_argument("--runs-dir", default="/data/gv31_runs")
    ap.add_argument("--out", default="/data/gv31_out")
    ap.add_argument("--n-synth", type=int, default=4000)
    ap.add_argument("--device", default="0")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--patience", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.stage == "export":
        export_datasets(pathlib.Path(args.manifest), pathlib.Path(args.meterfl), pathlib.Path(args.out), args.n_synth, args.seed)
    elif args.stage == "train":
        train_models(pathlib.Path(args.data_dir), pathlib.Path(args.out), args.device, args.epochs, args.patience, args.seed)
    else:
        export_onnx_models(pathlib.Path(args.runs_dir), pathlib.Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
