"""
GaugeVision AI 3.1 — Рабочие профили Vision Engine (legacy / eco / balanced / precision).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisionProfileConfig:
    name: str
    label: str
    description: str
    detector: str            # "yolov8n" | "yolo26n" | "yolo26s" | "rfdetr_nano"
    needle_mode: str         # "legacy_opencv" | "opencv_v2" | "keypoint" | "seg" | "fusion"
    use_keypoint: bool
    use_seg: bool
    use_opencv_check: bool
    use_onnx_if_available: bool
    imgsz: int
    redetect_every_n: int
    fusion_max_disagree_deg: float
    min_neural_conf: float


VISION_PROFILES: dict[str, VisionProfileConfig] = {
    "legacy": VisionProfileConfig(
        name="legacy",
        label="Legacy (v3.0)",
        description="Исходный проверенный конвейер GaugeVision AI 3.0 (YOLOv8n + OpenCV v8).",
        detector="yolov8n",
        needle_mode="legacy_opencv",
        use_keypoint=False,
        use_seg=False,
        use_opencv_check=True,
        use_onnx_if_available=False,
        imgsz=640,
        redetect_every_n=15,
        fusion_max_disagree_deg=180.0,
        min_neural_conf=0.0,
    ),
    "eco": VisionProfileConfig(
        name="eco",
        label="Eco (экономичный)",
        description="Минимальная нагрузка CPU: улучшенная геометрия OpenCV v2 (исправленный M1 top-hat) + редкая детекция.",
        detector="yolov8n",
        needle_mode="opencv_v2",
        use_keypoint=False,
        use_seg=False,
        use_opencv_check=True,
        use_onnx_if_available=True,
        imgsz=640,
        redetect_every_n=25,
        fusion_max_disagree_deg=180.0,
        min_neural_conf=0.0,
    ),
    "balanced": VisionProfileConfig(
        name="balanced",
        label="Balanced (рекомендуемый)",
        description="Баланс точности и скорости: пиксельная сегментация стрелки NeedleSegUNet (PCA/ODR) + геометрическая проверка OpenCV v2.",
        detector="yolov8n",
        needle_mode="fusion_seg",
        use_keypoint=False,
        use_seg=True,
        use_opencv_check=True,
        use_onnx_if_available=True,
        imgsz=640,
        redetect_every_n=15,
        fusion_max_disagree_deg=14.0,
        min_neural_conf=0.45,
    ),
    "precision": VisionProfileConfig(
        name="precision",
        label="Precision (высокая точность)",
        description="Полное ансамблевое согласование: NeedleKeypointNet + пиксельная сегментация NeedleSegUNet + OpenCV v2.",
        detector="yolov8n",
        needle_mode="fusion_full",
        use_keypoint=True,
        use_seg=True,
        use_opencv_check=True,
        use_onnx_if_available=True,
        imgsz=640,
        redetect_every_n=10,
        fusion_max_disagree_deg=12.0,
        min_neural_conf=0.50,
    ),
}


def get_profile_config(name: str | None) -> VisionProfileConfig:
    key = (name or "legacy").strip().lower()
    return VISION_PROFILES.get(key, VISION_PROFILES["legacy"])
