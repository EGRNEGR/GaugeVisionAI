"""
Задержка одного детектора YOLOv8 (без геометрии стрелки) на CPU и на CUDA (FP16).

Полный конвейер GaugePipeline тратит большую часть времени кадра на CPU-часть (OpenCV:
эллипс циферблата, стрелка, оверлей), поэтому его задержка на GPU и CPU почти совпадает.
Этот замер отделяет вклад детектора и снимает пиковую видеопамять PyTorch.

  python reports/remediation/tests/yolo_device_microbench.py --n 200 --out reports/remediation/evidence/gpu_rtx5060_laptop
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def bench(vision, img, n: int) -> dict:
    for _ in range(20):
        vision._yolo_gauge_bbox(img)
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        bbox = vision._yolo_gauge_bbox(img)
        ts.append((time.perf_counter() - t) * 1000.0)
    ts.sort()
    return {"n": n, "p50_ms": round(ts[n // 2], 2), "p95_ms": round(ts[int(n * 0.95)], 2),
            "mean_ms": round(statistics.mean(ts), 2), "detector_fps": round(1000.0 / statistics.mean(ts), 1),
            "bbox": list(bbox) if bbox else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "reports" / "remediation" / "evidence" / "gpu_rtx5060_laptop"))
    args = ap.parse_args()
    import torch

    from app import config, vision
    from app.stream_manager import render_gauge_frame

    img = render_gauge_frame(code="GPU", name="", unit="МПа", value=12.0, v_min=0.0, v_max=16.0, width=640, height=480)
    res: dict = {"torch": torch.__version__, "imgsz": config.YOLO_IMGSZ}
    config.YOLO_DEVICE = "cpu"
    vision._YOLO = None
    res["cpu"] = {**bench(vision, img, args.n), "device": vision.yolo_device(), "half": vision._YOLO_HALF}
    if torch.cuda.is_available():
        config.YOLO_DEVICE = "cuda:0"
        vision._YOLO = None
        torch.cuda.reset_peak_memory_stats()
        res["cuda"] = {**bench(vision, img, args.n), "device": vision.yolo_device(), "half": vision._YOLO_HALF,
                       "torch_peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1048576.0, 1),
                       "torch_reserved_vram_mb": round(torch.cuda.memory_reserved() / 1048576.0, 1)}
        res["speedup_p50"] = round(res["cpu"]["p50_ms"] / res["cuda"]["p50_ms"], 2)
        res["bbox_equal"] = res["cpu"]["bbox"] == res["cuda"]["bbox"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "yolo_device_microbench.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
