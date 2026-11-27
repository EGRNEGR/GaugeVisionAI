"""
GaugeVision AI 3.1 — Модульный Vision Engine (Next Generation CV).

Компоненты:
  • ModelRegistry — реестр моделей с проверкой SHA-256, контролем путей и лицензиями;
  • OpenCVNeedleV2 — улучшенный геометрический оценщик стрелки (исправление M1 top-hat);
  • NeuralKeypointEstimator — нейросеть ключевых точек (центр + кончик + sin/cos + видимость);
  • NeuralSegEstimator — пиксельная сегментация стрелки и рисок + PCA/ODR;
  • FusionNeedleEstimator — интеллектуальное согласование нейросетевых и геометрических оценок;
  • VisionProfile — рабочие профили производительности (legacy / eco / balanced / precision).
"""
from .estimators import (
    FusionNeedleEstimator,
    NeuralKeypointEstimator,
    NeuralSegEstimator,
    OpenCVNeedleV2,
    estimate_needle_opencv_v2,
)
from .profiles import VISION_PROFILES, VisionProfileConfig, get_profile_config
from .registry import ModelRecord, ModelRegistry, get_registry

__all__ = [
    "FusionNeedleEstimator",
    "ModelRecord",
    "ModelRegistry",
    "NeuralKeypointEstimator",
    "NeuralSegEstimator",
    "OpenCVNeedleV2",
    "VISION_PROFILES",
    "VisionProfileConfig",
    "estimate_needle_opencv_v2",
    "get_profile_config",
    "get_registry",
]
