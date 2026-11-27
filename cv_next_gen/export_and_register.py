"""
GaugeVision AI 3.1 — Экспорт обученных моделей стрелки в ONNX (если доступно)
и формирование models/registry.json с SHA-256 и метаданными лицензий.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

import torch

from .models_needle import CROP_SIZE, NeedleKeypointNet, NeedleSegUNet

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"


def sha256_of(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def try_export_onnx(model: torch.nn.Module, onnx_path: pathlib.Path, output_names: list[str]) -> bool:
    dummy = torch.zeros((1, 3, CROP_SIZE, CROP_SIZE), dtype=torch.float32)
    try:
        torch.onnx.export(
            model,
            dummy,
            str(onnx_path),
            input_names=["input"],
            output_names=output_names,
            dynamic_axes={"input": {0: "batch"}, **{n: {0: "batch"} for n in output_names}},
            opset_version=17,
            dynamo=False,
        )
        # Проверка загрузки в onnxruntime
        import onnxruntime as ort
        sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        _ = sess.run(None, {"input": dummy.numpy()})
        return True
    except Exception as exc:
        print(f"ONNX export skipped for {onnx_path.name}: {exc}")
        if onnx_path.exists():
            onnx_path.unlink(missing_ok=True)
        return False


def main() -> int:
    models_list = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Legacy YOLOv8n
    yolo_p = MODELS_DIR / "gauge_yolov8.pt"
    if yolo_p.exists():
        models_list.append({
            "model_id": "gauge_yolov8_legacy",
            "architecture": "YOLOv8n",
            "task": "detect",
            "version": "3.0.0",
            "filename": yolo_p.name,
            "format": "pt",
            "sha256": sha256_of(yolo_p),
            "input_size": 640,
            "classes": ["Gauge", "Needle"],
            "license": "AGPL-3.0 (Ultralytics)",
            "backends": ["ultralytics_cpu", "ultralytics_cuda"],
            "trained_date": "2026-10-20",
            "data_sources": "Analog-Gauge-Meter-1 (Colab/Roboflow, точный состав не зафиксирован)",
            "notes": "Базовый детектор GaugeVision AI 3.0",
        })

    # 2. NeedleKeypointNet
    kpt_pt = MODELS_DIR / "needle_keypoint_v31.pt"
    if kpt_pt.exists():
        ckpt = torch.load(str(kpt_pt), map_location="cpu", weights_only=True)
        kpt_m = NeedleKeypointNet(base_ch=int(ckpt.get("base_ch", 24)))
        kpt_m.load_state_dict(ckpt["state_dict"])
        kpt_m.eval()
        models_list.append({
            "model_id": "needle_keypoint_v31_pt",
            "architecture": "NeedleKeypointNet",
            "task": "needle_keypoint",
            "version": "3.1.0",
            "filename": kpt_pt.name,
            "format": "pt",
            "sha256": sha256_of(kpt_pt),
            "input_size": CROP_SIZE,
            "classes": ["center", "tip", "sin_cos", "visibility"],
            "license": "MIT / BSD-3-Clause (PyTorch)",
            "backends": ["pytorch_cpu"],
            "trained_date": today,
            "data_sources": "MeterFL dev (M2, M3; CC BY-SA 4.0) + GaugeVision Synthetic (MIT)",
            "notes": "Компактная нейросеть ключевых точек и циклического угла стрелки",
        })
        kpt_onnx = MODELS_DIR / "needle_keypoint_v31.onnx"
        if try_export_onnx(kpt_m, kpt_onnx, ["coords", "sincos", "vis_logit"]):
            models_list.append({
                "model_id": "needle_keypoint_v31_onnx",
                "architecture": "NeedleKeypointNet",
                "task": "needle_keypoint",
                "version": "3.1.0",
                "filename": kpt_onnx.name,
                "format": "onnx",
                "sha256": sha256_of(kpt_onnx),
                "input_size": CROP_SIZE,
                "classes": ["center", "tip", "sin_cos", "visibility"],
                "license": "MIT (ONNX Runtime)",
                "backends": ["onnxruntime_cpu"],
                "trained_date": today,
                "data_sources": "MeterFL dev (M2, M3; CC BY-SA 4.0) + GaugeVision Synthetic (MIT)",
                "notes": "ONNX-экспорт NeedleKeypointNet (безопасная загрузка без pickle)",
            })

    # 3. NeedleSegUNet
    seg_pt = MODELS_DIR / "needle_seg_v31.pt"
    if seg_pt.exists():
        ckpt = torch.load(str(seg_pt), map_location="cpu", weights_only=True)
        seg_m = NeedleSegUNet(base_ch=int(ckpt.get("base_ch", 20)))
        seg_m.load_state_dict(ckpt["state_dict"])
        seg_m.eval()
        models_list.append({
            "model_id": "needle_seg_v31_pt",
            "architecture": "NeedleSegUNet",
            "task": "needle_seg",
            "version": "3.1.0",
            "filename": seg_pt.name,
            "format": "pt",
            "sha256": sha256_of(seg_pt),
            "input_size": CROP_SIZE,
            "classes": ["background", "ticks", "pointer"],
            "license": "MIT / BSD-3-Clause (PyTorch)",
            "backends": ["pytorch_cpu"],
            "trained_date": today,
            "data_sources": "MeterFL dev (M2, M3; CC BY-SA 4.0) + GaugeVision Synthetic (MIT)",
            "notes": "Компактная U-Net сегментация стрелки и рисок + PCA/ODR",
        })
        seg_onnx = MODELS_DIR / "needle_seg_v31.onnx"
        if try_export_onnx(seg_m, seg_onnx, ["seg_logits", "tip_logits"]):
            models_list.append({
                "model_id": "needle_seg_v31_onnx",
                "architecture": "NeedleSegUNet",
                "task": "needle_seg",
                "version": "3.1.0",
                "filename": seg_onnx.name,
                "format": "onnx",
                "sha256": sha256_of(seg_onnx),
                "input_size": CROP_SIZE,
                "classes": ["background", "ticks", "pointer"],
                "license": "MIT (ONNX Runtime)",
                "backends": ["onnxruntime_cpu"],
                "trained_date": today,
                "data_sources": "MeterFL dev (M2, M3; CC BY-SA 4.0) + GaugeVision Synthetic (MIT)",
                "notes": "ONNX-экспорт NeedleSegUNet (безопасная загрузка без pickle)",
            })

    reg_path = MODELS_DIR / "registry.json"
    reg_path.write_text(json.dumps({"schema": "gv.model_registry/1", "models": models_list}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Registered {len(models_list)} models in {reg_path}")
    for m in models_list:
        print(f"  - {m['model_id']:28s} {m['format']:4s} sha256={m['sha256'][:12]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
