"""
GaugeVision AI — конвейер компьютерного зрения (SOTA Hybrid Pipeline, раздел 5 ТЗ).

Ступень 1. Локализация циферблата и перспективная коррекция (Gauge ROI Extraction):
  • YOLOv8-детекция корпуса прибора (если установлена ultralytics и в models/
    лежат веса) с автоматическим fallback на классический OpenCV:
    CLAHE + cv2.HoughCircles + контурный анализ.
  • Эллиптическая аппроксимация контура (cv2.fitEllipse) и обратная аффинная
    трансформация к правильному кругу диаметром 640 px (устранение перспективы).

Ступень 2. Определение вектора стрелки (Needle Vector Estimation):
  • центр вращения (x0, y0) — геометрический центр нормализованного циферблата;
  • вычитание фона шкалы морфологическим градиентом: Black-Hat (тёмная стрелка
    на светлом фоне) и Top-Hat (светлая стрелка на тёмной шкале);
  • трассировка осевой линии через cv2.HoughLinesP + поиск направления
    максимального радиального момента инерции;
  • θ = atan2(y1−y0, x1−x0)·180/π, нормализация к [0°, 360°).

Двухточечная калибровка шкалы (5.2): Δθ = (θ − θmin) mod 360;
  V = Vmin + Δθ/Δθspan · (Vmax − Vmin), поддержка CW/CCW.
EMA-фильтрация дрожания (5.3): V̄t = α·Vt + (1−α)·V̄t−1, α = 0.25.

Все углы — в системе координат изображения (ось Y направлена вниз):
0° — направление «на 3 часа», 90° — «на 6 часов», 180° — «на 9», 270° — «на 12».
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from . import config

logger = logging.getLogger("gaugevision.vision")

# ---------------------------------------------------------------------------
# Опциональная YOLO-ступень (детекция корпуса прибора)
# ---------------------------------------------------------------------------
_YOLO = None
_YOLO_LOCK = threading.Lock()        # ленивая загрузка
_YOLO_INFER_LOCK = threading.Lock()  # предиктор ultralytics не потокобезопасен
_YOLO_DEVICE = "cpu"
_YOLO_HALF = False
_YOLO_DEVICE_NAME = "CPU"


def _resolve_device() -> tuple[str, bool, str]:
    """(device, half, человекочитаемое имя) по config.YOLO_DEVICE."""
    want = config.YOLO_DEVICE.strip().lower()
    try:
        import torch  # type: ignore
        cuda_ok = torch.cuda.is_available()
    except Exception:
        return "cpu", False, "CPU"
    if want == "cpu" or (want == "auto" and not cuda_ok):
        return "cpu", False, "CPU"
    if not cuda_ok:
        logger.warning("Запрошено устройство %s, но CUDA недоступна — инференс YOLO на CPU", want)
        return "cpu", False, "CPU"
    device = "cuda:0" if want in ("auto", "cuda", "gpu") else want
    idx = int(device.split(":")[1]) if ":" in device else 0
    return device, True, torch.cuda.get_device_name(idx)


def _predict_kwargs() -> dict[str, Any]:
    """Аргументы predict(): устройство, размер входа и точность (FP16 на GPU)."""
    kw: dict[str, Any] = {"device": _YOLO_DEVICE, "imgsz": config.YOLO_IMGSZ, "verbose": False}
    if _YOLO_HALF:
        try:
            from ultralytics.cfg import DEFAULT_CFG_DICT  # type: ignore
            new_api = "quantize" in DEFAULT_CFG_DICT
        except Exception:
            new_api = False
        # новые версии ultralytics: quantize=16; старые: half=True
        kw.update({"quantize": 16} if new_api else {"half": True})
    return kw


def _load_yolo():
    """Ленивая загрузка YOLOv8 из локальных весов (GPU при наличии); при неудаче — None."""
    global _YOLO, _YOLO_DEVICE, _YOLO_HALF, _YOLO_DEVICE_NAME
    with _YOLO_LOCK:
        if _YOLO is None:
            weights = config.YOLO_WEIGHTS
            if not weights.exists():
                logger.info("Веса YOLOv8 не найдены (%s) — используется OpenCV-fallback", weights)
                _YOLO = False
            else:
                try:
                    import os as _os
                    if "YOLO_CONFIG_DIR" not in _os.environ:
                        cfg_dir = config.DATA_DIR / ".ultralytics"
                        try:
                            cfg_dir.mkdir(parents=True, exist_ok=True)
                            _os.environ["YOLO_CONFIG_DIR"] = str(cfg_dir)
                        except OSError:
                            pass
                    # Закрытый контур: без YOLO_OFFLINE ultralytics при импорте проверяет «онлайн»
                    # DNS-запросами к one.one.one.one / dns.google и включает внешнюю телеметрию
                    _os.environ.setdefault("YOLO_OFFLINE", "1")
                    from ultralytics import YOLO  # type: ignore
                    model = YOLO(str(weights))
                    _YOLO_DEVICE, _YOLO_HALF, _YOLO_DEVICE_NAME = _resolve_device()
                    # прогрев: инициализация CUDA-контекста и ядер до первого живого кадра
                    model.predict(np.zeros((config.YOLO_IMGSZ, config.YOLO_IMGSZ, 3), np.uint8),
                                  **_predict_kwargs())
                    _YOLO = model
                    logger.info("YOLOv8 загружена: %s · устройство %s (%s)%s", weights,
                                _YOLO_DEVICE, _YOLO_DEVICE_NAME, " · FP16" if _YOLO_HALF else "")
                except Exception as exc:
                    logger.warning("YOLOv8 недоступна (%s) — используется OpenCV-fallback", exc)
                    _YOLO = False  # маркер «пробовали, не вышло»
    return _YOLO or None


def yolo_available() -> bool:
    return _load_yolo() is not None


def yolo_device() -> str | None:
    """Имя устройства инференса YOLO (None, если YOLO не используется)."""
    return _YOLO_DEVICE_NAME if _load_yolo() is not None else None


# ---------------------------------------------------------------------------
# GaugeVision AI 3.1 — Vision Engine (профили, реестр, нейросети и Fusion)
# ---------------------------------------------------------------------------
_VE_LOCK = threading.Lock()
_VE_PROFILE: str = config.VISION_PROFILE
_VE_KPT = None
_VE_SEG = None
_VE_CV2 = None
_VE_FUSION_BAL = None
_VE_FUSION_PREC = None


def get_vision_profile() -> str:
    return _VE_PROFILE


def set_vision_profile(profile_name: str) -> str:
    global _VE_PROFILE
    from .vision_engine.profiles import VISION_PROFILES
    key = (profile_name or "legacy").strip().lower()
    if key not in VISION_PROFILES:
        raise ValueError(f"Неизвестный профиль Vision Engine: {profile_name}")
    with _VE_LOCK:
        _VE_PROFILE = key
    logger.info("Активный профиль Vision Engine переключён на: %s", key)
    return key


def _get_ve_estimators():
    global _VE_KPT, _VE_SEG, _VE_CV2, _VE_FUSION_BAL, _VE_FUSION_PREC
    with _VE_LOCK:
        if _VE_CV2 is None:
            from .vision_engine.estimators import (
                FusionNeedleEstimator,
                NeuralKeypointEstimator,
                NeuralSegEstimator,
                OpenCVNeedleV2,
            )
            _VE_KPT = NeuralKeypointEstimator()
            _VE_SEG = NeuralSegEstimator()
            _VE_CV2 = OpenCVNeedleV2()
            _VE_FUSION_BAL = FusionNeedleEstimator(kpt=_VE_KPT, seg=_VE_SEG, max_disagree_deg=14.0, min_neural_conf=0.45)
            _VE_FUSION_PREC = FusionNeedleEstimator(kpt=_VE_KPT, seg=_VE_SEG, max_disagree_deg=12.0, min_neural_conf=0.50)
        return _VE_KPT, _VE_SEG, _VE_CV2, _VE_FUSION_BAL, _VE_FUSION_PREC


def vision_engine_status() -> dict[str, Any]:
    from .vision_engine.profiles import VISION_PROFILES, get_profile_config
    from .vision_engine.registry import get_registry
    prof = get_profile_config(_VE_PROFILE)
    return {
        "engine_version": config.VISION_ENGINE_VERSION,
        "profile": prof.name,
        "profile_label": prof.label,
        "profile_description": prof.description,
        "detector": prof.detector,
        "needle_mode": prof.needle_mode,
        "yolo_available": yolo_available(),
        "device": yolo_device() or "CPU",
        "available_profiles": [
            {"name": p.name, "label": p.label, "description": p.description, "needle_mode": p.needle_mode}
            for p in VISION_PROFILES.values()
        ],
        "models": get_registry().list_models(),
    }


def yolo_gauge_boxes(frame_bgr: np.ndarray) -> list[tuple[int, int, int, int, float]] | None:
    """Все приборы кадра за один проход YOLO: [(x, y, w, h, conf)] по убыванию площади.

    None — YOLO недоступна или инференс не удался (не то же, что «приборов нет» — []).
    """
    model = _load_yolo()
    if model is None:
        return None
    try:
        with _YOLO_INFER_LOCK:
            results = model.predict(frame_bgr, conf=config.YOLO_CONF, **_predict_kwargs())
        boxes: list[tuple[int, int, int, int, float]] = []
        for r in results:
            names = r.names or {}
            for box in r.boxes:
                cls_name = str(names.get(int(box.cls), "")).lower()
                if any(k in cls_name for k in config.YOLO_CLASSES):
                    x1, y1, x2, y2 = map(float, box.xyxy[0])
                    boxes.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1), float(box.conf)))
        boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
        return boxes
    except Exception as exc:
        logger.debug("YOLO inference failed: %s", exc)
        return None


def _yolo_gauge_bbox(frame_bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """BBox (x, y, w, h) самого крупного прибора из классов config.YOLO_CLASSES."""
    boxes = yolo_gauge_boxes(frame_bgr)
    return boxes[0][:4] if boxes else None


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------
@dataclass
class DialROI:
    """Локализованный циферблат: эллипс + аффинная матрица к кругу 640 px."""
    center: tuple[float, float]
    axes: tuple[float, float]         # полуоси (a, b), px исходного кадра
    angle_deg: float                  # поворот оси a (как в cv2.fitEllipse)
    matrix: np.ndarray                # 2x3: кадр -> нормализованный циферблат
    inv_matrix: np.ndarray            # 2x3: нормализованный циферблат -> кадр
    score: float = 0.0
    source: str = "opencv"            # "yolo" | "opencv" | "ellipse" | "manual" | "frame"

    def to_json(self) -> dict[str, Any]:
        return {
            "center": [float(v) for v in self.center],
            "axes": [float(v) for v in self.axes],
            "angle_deg": float(self.angle_deg),
            "score": float(self.score),
            "source": self.source,
        }


@dataclass
class NeedleResult:
    angle_deg: float | None           # [0, 360) — направление острия стрелки
    tip: tuple[int, int] | None       # координаты острия (x1, y1) на циферблате 640 px
    confidence: float
    method: str                       # "hough" | "moment" | "hough+moment" | "none"


@dataclass
class GaugeReading:
    """Итог обработки одного кадра."""
    angle: float | None = None        # сырой угол стрелки θ
    value: float | None = None        # мгновенное физическое значение V_t
    ema_value: float | None = None    # сглаженное значение V̄_t
    valid: bool = False               # стрелка уверенно найдена в этом кадре
    needle_confidence: float = 0.0
    dial_found: bool = False
    dial_source: str = "none"
    status_level: str = "normal"
    process_ms: float = 0.0
    overlay: np.ndarray | None = None
    snapshot: np.ndarray | None = None  # стоп-кадр смены уровня: разметка без текста, тот же кадр
    debug: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ступень 1b. Перспективная коррекция: эллипс -> круг 640 px
# ---------------------------------------------------------------------------
def roi_from_ellipse(cx: float, cy: float, a: float, b: float,
                     angle_deg: float, score: float, source: str) -> DialROI:
    """
    Аффинная матрица, переводящая эллипс (cx, cy, a, b, φ) в правильный круг
    диаметром DIAL_SIZE с центром в середине холста:

        M = T(S/2) · R(φ) · diag(R/a, R/b) · R(−φ) · T(−c)

    «Растяжение» выполняется вдоль собственных осей эллипса, а финальный
    обратный поворот сохраняет исходную ориентацию шкалы — углы стрелки и
    калибровочные углы остаются в той же системе координат, что и кадр.
    """
    size = float(config.DIAL_SIZE)
    radius = size / 2.0
    a = max(float(a), 1e-6)
    b = max(float(b), 1e-6)
    phi = math.radians(angle_deg)
    c, s = math.cos(phi), math.sin(phi)
    rot_fwd = np.array([[c, -s], [s, c]], dtype=np.float64)     # R(φ)
    rot_back = np.array([[c, s], [-s, c]], dtype=np.float64)    # R(−φ)
    scale = np.diag([radius / a, radius / b])
    lin = rot_fwd @ scale @ rot_back
    offset = np.array([radius, radius]) - lin @ np.array([cx, cy])
    matrix = np.hstack([lin, offset.reshape(2, 1)])
    inv = cv2.invertAffineTransform(matrix)
    return DialROI(center=(float(cx), float(cy)), axes=(a, b), angle_deg=float(angle_deg),
                   matrix=matrix, inv_matrix=inv, score=score, source=source)


def normalize_dial(frame_bgr: np.ndarray, roi: DialROI) -> np.ndarray:
    """Обратная аффинная трансформация к правильному кругу 640 px."""
    size = config.DIAL_SIZE
    return cv2.warpAffine(
        frame_bgr, roi.matrix, (size, size),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )


# ---------------------------------------------------------------------------
# Ступень 1a. Поиск циферблата
# ---------------------------------------------------------------------------
def _prep_gray(frame_bgr: np.ndarray) -> np.ndarray:
    """Серый канал + адаптивный контраст CLAHE (блики, неравномерный свет цеха)."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _ellipse_candidates(gray: np.ndarray, min_area_frac: float = 0.015,
                        ) -> list[tuple[float, float, float, float, float, float]]:
    """
    Эллиптическая аппроксимация крупных округлых контуров.
    Возвращает [(cx, cy, a, b, φ, score)], a/b — полуоси.
    min_area_frac — минимальная площадь контура в долях кадра (меньше — для щита из многих приборов).
    """
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 130)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    min_area = min_area_frac * h * w
    for cnt in contours:
        if len(cnt) < 20:
            continue
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        peri = cv2.arcLength(cnt, True)
        if peri <= 0:
            continue
        try:
            (ex, ey), (ew, eh), ang = cv2.fitEllipse(cnt)
        except cv2.error:
            continue
        a, b = ew / 2.0, eh / 2.0
        if min(a, b) < 15 or max(a, b) > 0.75 * max(h, w):
            continue
        ratio = min(a, b) / max(a, b)
        if ratio < 0.45:  # слишком сплющен — не циферблат
            continue
        ellipse_area = math.pi * a * b
        fill = area / ellipse_area if ellipse_area else 0.0
        if fill < 0.85 or fill > 1.15:  # контур плохо совпадает с эллипсом (в т. ч. полумесяц при перекрытии)
            continue
        # Проверка радиальной невязки точек контура к аппроксимирующему эллипсу (DEF-15):
        # истинный эллипс (даже при сильной перспективе) имеет p90(|r - 1|) < 0.06,
        # а частично перекрытый циферблат (D-форма с прямой хордой и углами) — > 0.12.
        pts = cnt.reshape(-1, 2).astype(np.float64)
        rad = math.radians(ang)
        ca, sa = math.cos(rad), math.sin(rad)
        dx = pts[:, 0] - ex
        dy = pts[:, 1] - ey
        # OpenCV fitEllipse: ew — ось вдоль угла ang, eh — перпендикулярная ось
        u = (dx * ca + dy * sa) / max(a, 1e-6)
        v = (-dx * sa + dy * ca) / max(b, 1e-6)
        radial_err = np.abs(np.hypot(u, v) - 1.0)
        p90_err = float(np.percentile(radial_err, 90))
        if p90_err > 0.10:
            continue
        score = (area / (h * w)) * (1.0 - abs(1.0 - fill)) * max(0.2, 1.0 - 2.0 * p90_err)
        out.append((float(ex), float(ey), float(a), float(b), float(ang), float(score)))
    out.sort(key=lambda e: e[5], reverse=True)
    return out


def _find_dial_opencv(frame_bgr: np.ndarray) -> DialROI | None:
    """
    OpenCV-fallback: CLAHE + HoughCircles, уточнение эллипсом; если окружностей
    нет (сильная перспектива) — чисто контурная эллиптическая аппроксимация.
    """
    gray = _prep_gray(frame_bgr)
    h, w = gray.shape
    short = min(h, w)
    blur = cv2.GaussianBlur(gray, (9, 9), 2)

    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=int(short * 0.35),
        param1=140, param2=45,
        minRadius=int(max(25, short * 0.10)),
        maxRadius=int(short * 0.60),
    )
    ellipses = _ellipse_candidates(gray)

    if ellipses:
        # Эллиптическая аппроксимация контура — основной путь (устойчив к
        # перспективе). Среди концентрических кандидатов (корпус/безель/
        # циферблат) выбираем внутренний — собственно шкалу.
        top = ellipses[0]
        best = top
        top_major = max(top[2], top[3])
        for e in ellipses[1:]:
            major = max(e[2], e[3])
            if (math.hypot(e[0] - top[0], e[1] - top[1]) < 0.06 * top_major
                    and 0.80 * top_major <= major < max(best[2], best[3]) - 2):
                best = e
        ex, ey, a, b, ang, _ = best
        # HoughCircles — подтверждение: совпадение центров повышает доверие
        score = 0.75
        if circles is not None:
            for cx, cy, r in np.asarray(circles).reshape(-1, 3):
                if math.hypot(cx - ex, cy - ey) < 0.10 * max(a, b):
                    score = 0.95
                    break
        return roi_from_ellipse(ex, ey, a, b, ang, score=score, source="ellipse")

    if circles is not None:
        # окружность без контурного подтверждения: крупнейшая в пределах кадра
        cands = [c for c in np.asarray(circles).reshape(-1, 3) if 0 <= c[0] < w and 0 <= c[1] < h]
        if cands:
            cx, cy, r = max(cands, key=lambda c: c[2])
            return roi_from_ellipse(float(cx), float(cy), float(r), float(r), 0.0,
                                    score=0.6, source="opencv")
    return None


def _find_dial_yolo(frame_bgr: np.ndarray) -> DialROI | None:
    """YOLO bbox -> вписанный эллипс, уточняемый контуром внутри bbox."""
    bbox = _yolo_gauge_bbox(frame_bgr)
    if bbox is None:
        return None
    return _roi_from_yolo_bbox(frame_bgr, bbox)


def _roi_from_yolo_bbox(frame_bgr: np.ndarray, bbox: tuple[int, int, int, int]) -> DialROI:
    x, y, w, h = bbox
    pad = int(0.08 * max(w, h))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    crop = frame_bgr[y0:y + h + pad, x0:x + w + pad]
    if crop.size:
        for ex, ey, a, b, ang, _ in _ellipse_candidates(_prep_gray(crop)):
            if max(a, b) > 0.35 * max(w, h):
                return roi_from_ellipse(ex + x0, ey + y0, a, b, ang, score=0.95, source="yolo")
    return roi_from_ellipse(x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0, 0.0,
                            score=0.9, source="yolo")


def frame_roi(frame_bgr: np.ndarray) -> DialROI:
    """Крайний fallback: прибор занимает центр кадра (крупный план со смартфона)."""
    h, w = frame_bgr.shape[:2]
    r = 0.47 * min(h, w)
    return roi_from_ellipse(w / 2.0, h / 2.0, r, r, 0.0, score=0.3, source="frame")


def manual_roi(frame_bgr: np.ndarray, roi_cfg: dict[str, Any]) -> DialROI | None:
    """Ручная ROI из калибровки: cx, cy, r в долях кадра (0..1)."""
    try:
        h, w = frame_bgr.shape[:2]
        cx = float(roi_cfg["cx"]) * w
        cy = float(roi_cfg["cy"]) * h
        r = float(roi_cfg["r"]) * min(h, w)
        if r < 10:
            return None
        return roi_from_ellipse(cx, cy, r, r, 0.0, score=1.0, source="manual")
    except (KeyError, TypeError, ValueError):
        return None


def detect_all_dials(frame_bgr: np.ndarray) -> list[DialROI]:
    """
    Возвращает все найденные приборы на кадре (YOLO + контурные эллипсы OpenCV).
    Примечание: GaugePipeline.process() обрабатывает один целевой прибор (ручной ROI
    или наиболее достоверный корпус); для многоприборных сцен каждый прибор привязывается
    к отдельному каналу через ручной ROI или выбирается из detect_all_dials().
    """
    found: list[DialROI] = []
    primary = detect_dial(frame_bgr)
    if primary is not None:
        found.append(primary)
    for ex, ey, a, b, ang, score in _ellipse_candidates(_prep_gray(frame_bgr)):
        if all(math.hypot(ex - r.center[0], ey - r.center[1]) > 0.5 * max(r.axes) for r in found):
            found.append(roi_from_ellipse(ex, ey, a, b, ang, score=score, source="ellipse"))
    return found


def assess_dial_suitability(dial_bgr: np.ndarray) -> tuple[bool, str | None, float]:
    """
    Оценивает пригодность нормализованного циферблата (640×640) для измерения (DEF-15):
      • выявляет частичное перекрытие сектора/половины циферблата тёмным объектом;
      • выявляет критическое затемнение, засветку или отсутствие контраста (пар/пустой кадр).
    Возвращает (suitable, reason_code, suitability_score_0_100).
    """
    if dial_bgr is None or dial_bgr.size == 0:
        return False, "empty_dial", 0.0
    gray = cv2.cvtColor(dial_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    cy, cx = h // 2, w // 2
    inside = _RR < (_SIZE * 0.43)
    if not np.any(inside):
        return False, "empty_dial", 0.0

    # Проверка общей яркости и контраста внутри циферблата
    vals_all = gray[inside]
    mean_all = float(np.mean(vals_all))
    std_all = float(np.std(vals_all))
    glare_all = float(np.mean(vals_all >= 248))
    if mean_all < 22.0 or std_all < 8.0:
        return False, "unreadable_dial", 10.0
    if glare_all > 0.65:
        return False, "severe_glare", 15.0

    # Квадрантный и полусферный анализ на частичное перекрытие (тёмный непрозрачный объект)
    halves = (
        gray[:, :cx][inside[:, :cx]],
        gray[:, cx:][inside[:, cx:]],
        gray[:cy, :][inside[:cy, :]],
        gray[cy:, :][inside[cy:, :]],
    )
    half_means = [float(np.mean(hv)) for hv in halves if hv.size > 0]
    half_dark = [float(np.mean(hv < 30)) for hv in halves if hv.size > 0]
    half_stds = [float(np.std(hv)) for hv in halves if hv.size > 0]
    max_hm = max(half_means) if half_means else 0.0
    if max_hm >= 105.0:
        for hm, hd, hs in zip(half_means, half_dark, half_stds):
            if hd >= 0.42 and (max_hm - hm) >= 55.0:
                return False, "partial_occlusion", round(max(0.0, 100.0 - hd * 100.0), 1)
            if hd >= 0.32 and hs < 32.0 and (max_hm - hm) >= 65.0:
                return False, "partial_occlusion", round(max(0.0, 100.0 - hd * 100.0), 1)

    # Проверка по 8 угловым секторам циферблата (выявляет узкое боковое/верхнее перекрытие)
    yy, xx = np.mgrid[0:h, 0:w]
    ang = (np.degrees(np.arctan2(yy - cy, xx - cx)) + 360.0) % 360.0
    occluded_sectors = 0
    sector_means: list[float] = []
    for k in range(8):
        sec_mask = inside & (ang >= k * 45.0) & (ang < (k + 1) * 45.0)
        if not np.any(sec_mask):
            continue
        sv = gray[sec_mask]
        sm = float(np.mean(sv))
        sector_means.append(sm)
        if float(np.mean(sv < 28)) >= 0.65 and float(np.std(sv)) < 25.0:
            occluded_sectors += 1
    if occluded_sectors >= 2 and (max(sector_means) if sector_means else 0.0) >= 105.0:
        return False, "partial_occlusion", round(max(0.0, (1.0 - occluded_sectors / 8.0) * 100.0), 1)

    score = min(100.0, max(20.0, 100.0 - glare_all * 80.0))
    return True, None, round(score, 1)


def _inside_ellipse(roi: DialROI, px: float, py: float) -> bool:
    """Точка кадра внутри эллипса ROI (нормализованный радиус ≤ 1)."""
    q = roi.matrix @ np.array([px, py, 1.0])
    half = config.DIAL_SIZE / 2.0
    return math.hypot(q[0] - half, q[1] - half) <= half


def detect_dial(frame_bgr: np.ndarray) -> DialROI | None:
    """
    Двухступенчатая детекция: YOLO локализует прибор, контурный эллипс OpenCV
    уточняет геометрию (рамка YOLO бывает смещена/обрезана, эллипс — точнее).

    • эллипс OpenCV с центром внутри рамки YOLO -> эллипс (источник «yolo+ellipse»);
    • рамка YOLO — фрагмент крупного эллипса (её центр внутри эллипса) -> эллипс;
    • иначе — эллипс, уточнённый внутри рамки, либо вписанный в рамку эллипс;
    • YOLO недоступна / прибор не найден -> чистый OpenCV fallback.
    """
    bbox = _yolo_gauge_bbox(frame_bgr)
    cv_roi = _find_dial_opencv(frame_bgr)
    if bbox is None:
        return cv_roi
    x, y, w, h = bbox
    pad_x, pad_y = 0.15 * w, 0.15 * h
    if cv_roi is not None:
        cx, cy = cv_roi.center
        major = max(cv_roi.axes)
        if (x - pad_x <= cx <= x + w + pad_x and y - pad_y <= cy <= y + h + pad_y
                and 0.25 * max(w, h) <= major <= 1.6 * max(w, h)):
            cv_roi.source = "yolo+ellipse"
            cv_roi.score = max(cv_roi.score, 0.97)
            return cv_roi
        # Крупный план: циферблат занимает почти весь кадр, и YOLO (обучена на сценах с прибором
        # целиком) выделяет лишь часть лицевой панели — например, нижнюю половину с надписями.
        # Если центр рамки лежит внутри найденного эллипса, а рамка заметно меньше его, рамка —
        # фрагмент того же прибора, и эллипс точнее.
        if (_inside_ellipse(cv_roi, x + w / 2.0, y + h / 2.0)
                and w * h < 0.8 * math.pi * cv_roi.axes[0] * cv_roi.axes[1]):
            cv_roi.source = "ellipse"
            cv_roi.score = max(cv_roi.score, 0.9)
            return cv_roi
    return _roi_from_yolo_bbox(frame_bgr, bbox)


# ---------------------------------------------------------------------------
# Ступень 2. Определение вектора стрелки
# ---------------------------------------------------------------------------
_SIZE = config.DIAL_SIZE
_YY, _XX = np.mgrid[0:_SIZE, 0:_SIZE]
_RR = np.hypot(_XX - _SIZE / 2.0, _YY - _SIZE / 2.0)
_ANNULUS = (_RR > _SIZE * 0.04) & (_RR < _SIZE * 0.46)
_HAT_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
_CLOSE_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))


def _hat_mask(hat: np.ndarray) -> np.ndarray:
    """Бинаризация Otsu по пикселям кольца (фон вне циферблата не влияет на порог)."""
    vals = hat[_ANNULUS].reshape(-1, 1)
    t, _ = cv2.threshold(vals, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = max(float(t), 18.0)
    m = np.zeros_like(hat)
    m[(hat > t) & _ANNULUS] = 255
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, _CLOSE_KERNEL)


def needle_masks(dial_bgr: np.ndarray) -> dict[str, np.ndarray]:
    """
    Вычитание фона шкалы и выделение стрелки морфологическими «шляпами»:
    Black-Hat — тёмная стрелка на светлом фоне; Top-Hat — светлая на тёмном.
    """
    gray = cv2.cvtColor(dial_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, _HAT_KERNEL)
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, _HAT_KERNEL)
    # красные/цветные стрелки: насыщенность как дополнительный признак
    hsv = cv2.cvtColor(dial_bgr, cv2.COLOR_BGR2HSV)
    sat = cv2.GaussianBlur(hsv[:, :, 1], (5, 5), 0)
    sat_hat = cv2.morphologyEx(sat, cv2.MORPH_TOPHAT, _HAT_KERNEL)
    return {
        "blackhat": _hat_mask(blackhat),
        "tophat": _hat_mask(tophat),
        "saturation": _hat_mask(sat_hat),
    }


def _needle_angle_moment(mask: np.ndarray, allowed: np.ndarray | None = None) -> NeedleResult:
    """
    Поиск направления максимального радиального момента инерции.

    Для каждого угла-кандидата суммируем пиксели маски вдоль луча с весом ~ r
    (дальние точки стрелки дают больший момент, а равномерно распределённые
    по дуге риски шкалы образуют лишь фон гистограммы).
    allowed — булев массив 360 градусов: направления, куда стрелка может указывать
    при заданной калибровке (рабочая дуга шкалы с запасом); остальные пики не рассматриваются.
    """
    size = mask.shape[0]
    center = size / 2.0
    ys, xs = np.nonzero(mask)
    if len(xs) < 25:
        return NeedleResult(None, None, 0.0, "none")

    dx = xs - center
    dy = ys - center
    r = np.hypot(dx, dy)
    # внешнее кольцо рисок/цифр шкалы исключаем из момента
    valid = (r > size * 0.06) & (r < size * 0.36)
    if valid.sum() < 15:
        return NeedleResult(None, None, 0.0, "none")
    dxv, dyv, rv = dx[valid], dy[valid], r[valid]

    theta = np.degrees(np.arctan2(dyv, dxv)) % 360.0
    weights = rv / (size / 2.0)

    # гистограмма радиального момента с шагом 1°, круговое сглаживание ±4°
    bins = np.bincount(theta.astype(int) % 360, weights=weights, minlength=360)
    kernel = np.ones(9) / 9.0
    padded = np.concatenate([bins[-4:], bins, bins[:4]])
    smooth = np.convolve(padded, kernel, mode="valid")
    if allowed is not None:
        smooth = np.where(allowed, smooth, 0.0)

    best = int(np.argmax(smooth))
    peak = float(smooth[best])
    if peak <= 0:
        return NeedleResult(None, None, 0.0, "none")
    # подавляем окрестность пика ±25° и противоположный сектор ±25° (хвост-противовес той же
    # стрелки, а не конкурирующий объект) и смотрим второй максимум
    diff_bins = np.abs((np.arange(360) - best + 180) % 360 - 180)
    rivals = (diff_bins > 25) & (diff_bins < 155)
    second = float(smooth[rivals].max()) if rivals.any() else 0.0
    # «радиальная протяжённость» пика: стрелка — длинный луч от центра
    in_peak = np.abs((theta - best + 180) % 360 - 180) < 6
    radial_extent = float((rv[in_peak].max() - rv[in_peak].min()) / (size * 0.30)) if in_peak.any() else 0.0
    confidence = float(np.clip((1.0 - second / peak) * min(1.0, radial_extent), 0.0, 1.0))

    # уточнение угла: взвешенное круговое среднее в секторе ±6° вокруг пика
    if in_peak.any():
        ang = np.radians(theta[in_peak])
        wv = weights[in_peak]
        refined = math.degrees(math.atan2(float((np.sin(ang) * wv).sum()),
                                          float((np.cos(ang) * wv).sum()))) % 360.0
    else:
        refined = float(best)

    # остриё — самая дальняя точка маски в секторе ±6° (с учётом внешнего кольца)
    theta_all = np.degrees(np.arctan2(dy, dx)) % 360.0
    sector = (np.abs((theta_all - refined + 180) % 360 - 180) < 6) & (r < size * 0.46)
    if sector.any():
        idx = int(np.argmax(np.where(sector, r, -1)))
        tip = (int(xs[idx]), int(ys[idx]))
    else:
        tip = None
    return NeedleResult(refined, tip, confidence, "moment")


def _needle_angle_hough(mask: np.ndarray, allowed: np.ndarray | None = None) -> NeedleResult:
    """Трассировка осевой линии стрелки вероятностным преобразованием Хафа."""
    size = mask.shape[0]
    center = size / 2.0
    lines = cv2.HoughLinesP(
        mask, rho=1, theta=np.pi / 360, threshold=int(size * 0.08),
        minLineLength=int(size * 0.15), maxLineGap=10,
    )
    if lines is None:
        return NeedleResult(None, None, 0.0, "none")

    best_line = None
    best_score = 0.0
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4).astype(np.float64):
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1:
            continue
        # расстояние от центра вращения до прямой — стрелка проходит через ось
        d_line = abs((y2 - y1) * center - (x2 - x1) * center + x2 * y1 - y2 * x1) / length
        if d_line > size * 0.06:
            continue
        # ближний к центру конец отрезка должен начинаться недалеко от оси
        d1 = math.hypot(x1 - center, y1 - center)
        d2 = math.hypot(x2 - center, y2 - center)
        if min(d1, d2) > size * 0.22:
            continue
        score = length * (1.0 - d_line / (size * 0.06) * 0.5)
        if allowed is not None:
            ex, ey = (x1, y1) if d1 >= d2 else (x2, y2)
            if not allowed[int(math.degrees(math.atan2(ey - center, ex - center)) % 360.0) % 360]:
                continue
        if score > best_score:
            best_score = score
            best_line = (x1, y1, x2, y2, d1, d2)

    if best_line is None:
        return NeedleResult(None, None, 0.0, "none")

    x1, y1, x2, y2, d1, d2 = best_line
    # остриё — конец, дальний от центра (хвост-противовес короче)
    tx, ty = (x1, y1) if d1 >= d2 else (x2, y2)
    angle = math.degrees(math.atan2(ty - center, tx - center)) % 360.0
    confidence = float(min(1.0, best_score / (size * 0.30)))
    return NeedleResult(angle, (int(tx), int(ty)), confidence, "hough")


def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def needle_search_arc(calib: dict[str, Any], margin: float = 0.08) -> np.ndarray | None:
    """
    Допустимые направления стрелки по калибровке: рабочая дуга θmin → θmax (с учётом
    направления) плюс запас margin от размаха с каждой стороны — тот же допуск, что у
    angle_to_value (max_overshoot). Без калибровки — None (поиск по всему кругу).
    """
    parts = _calib_parts(calib or {})
    if parts is None:
        return None
    _, th_min, _, th_max, direction = parts
    span = (th_max - th_min) % 360.0 if direction == "cw" else (th_min - th_max) % 360.0
    if span < 1.0:
        return None
    deg = np.arange(360, dtype=np.float64) + 0.5
    delta = (deg - th_min) % 360.0 if direction == "cw" else (th_min - deg) % 360.0
    over = span * margin
    allowed = (delta <= span + over) | (delta >= 360.0 - over)
    return allowed if allowed.any() and not allowed.all() else None


HOUGH_ALONE_MIN = 0.70     # уверенность отрезка Хафа, достаточная без согласия момента
FACE_LIGHT_LEVEL = 140.0   # медиана яркости кольца циферблата: светлое поле
FACE_DARK_LEVEL = 90.0     # тёмное поле
SCALE_GAP_MAX = 0.10       # доля рабочей дуги: самый длинный участок без рисок (перекрытие предметом)
SCALE_COVERAGE_MIN = 0.30  # доля 5°-секторов рабочей дуги с текстурой рисок
SCALE_COHERENCE_MIN = 0.55 # радиальная когерентность рисок (см. scale_arc_evidence)


def scale_arc_evidence(dial_bgr: np.ndarray, allowed: np.ndarray) -> tuple[float, float, float]:
    """
    Видна ли шкала вдоль рабочей дуги. Полоса 0,55–0,98 радиуса нормализованного циферблата
    разворачивается в полярные координаты; тангенциальный градиент (поперёк радиальных рисок)
    усредняется по 5°-секторам дуги θmin → θmax.
    Возвращает (gap, coverage, coherence): gap — самый длинный подряд участок «гладких» секторов
    (средний градиент < 1 уровня яркости) в долях дуги; coverage — доля секторов с градиентом > 2;
    coherence — радиальная когерентность рисок: наибольшая корреляция угловых профилей градиента
    двух соседних подполос кольца (риски шкалы радиальны и совпадают по углу на разных радиусах,
    а надписи, цифровые индикаторы и прямые края линеек — нет).
    Риски, нанесённые узким кольцом у края, в среднем по всей полосе «растворяются», поэтому gap и
    coverage дополнительно считаются по каждому кольцу с когерентностью ≥ SCALE_COHERENCE_MIN и
    берётся кольцо с наибольшим покрытием.
    """
    size = config.DIAL_SIZE
    gray = cv2.cvtColor(dial_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    polar = cv2.warpPolar(gray, (size // 2, 720), (size / 2.0, size / 2.0), size / 2.0,
                          cv2.WARP_POLAR_LINEAR)                      # строки — угол с шагом 0,5°
    band = polar[:, int(0.55 * size / 2):int(0.98 * size / 2)]
    profile = np.abs(np.diff(band, axis=0, append=band[:1])).mean(axis=1)
    idx = np.where(np.repeat(allowed, 2))[0]
    # дуга может проходить через 0°: начинаем обход с первого индекса после разрыва
    if len(idx) and idx[0] == 0 and idx[-1] == 719:
        brk = np.where(np.diff(idx) > 1)[0]
        if len(brk):
            idx = np.concatenate([idx[brk[0] + 1:], idx[:brk[0] + 1]])
    def gap_coverage(prof: np.ndarray) -> tuple[float, float] | None:
        sectors = np.array([prof[idx[i:i + 10]].mean() for i in range(0, len(idx) - 9, 10)])
        if not len(sectors):
            return None
        run = best = 0
        for flat in sectors < 1.0:
            run = run + 1 if flat else 0
            best = max(best, run)
        return best / len(sectors), float(np.mean(sectors > 2.0))

    whole = gap_coverage(profile)
    if whole is None:
        return 1.0, 0.0, 0.0
    gap, coverage = whole
    coherence = 0.0
    rings: list[tuple[int, int]] = []   # кольца с радиально когерентными рисками
    step = 0.03 * size / 2.0
    for r0 in np.arange(0.55, 0.95, 0.03) * size / 2.0:
        prof = []
        for lo in (r0, r0 + step):
            sub = polar[:, int(lo):int(lo + step)]
            g = np.abs(np.diff(sub, axis=0, append=sub[:1])).mean(axis=1)[idx].astype(np.float32)
            prof.append(g - cv2.GaussianBlur(g.reshape(-1, 1), (1, 21), 0).ravel())
        if prof[0].std() > 0.3 and prof[1].std() > 0.3:
            c = float(np.corrcoef(prof[0], prof[1])[0, 1])
            coherence = max(coherence, c)
            if c >= SCALE_COHERENCE_MIN:
                rings.append((int(r0), int(r0 + 2 * step)))
    for lo, hi in rings:
        sub = polar[:, lo:hi]
        in_ring = gap_coverage(np.abs(np.diff(sub, axis=0, append=sub[:1])).mean(axis=1))
        if in_ring is not None and in_ring[1] > coverage:
            gap, coverage = in_ring
    return gap, coverage, coherence


def estimate_needle(dial_bgr: np.ndarray, allowed: np.ndarray | None = None) -> NeedleResult:
    """
    Комбинированная оценка направления стрелки на нормализованном циферблате.

    Для каждой маски (Black-Hat / Top-Hat / насыщенность) считаем радиальный
    момент; выбираем маску с наибольшей уверенностью. Затем HoughLinesP
    уточняет угол, если согласуется с моментом (расхождение ≤ 12°).
    allowed (needle_search_arc) ограничивает поиск рабочей дугой шкалы: блик, надпись или
    стойка в «мёртвой зоне» под осью не перехватывают выбор у настоящей стрелки.
    """
    best_moment: NeedleResult | None = None
    best_mask: np.ndarray | None = None
    best_mode = "none"
    masks = needle_masks(dial_bgr)
    # полярность циферблата: на светлом поле стрелка тёмная (Top-Hat ловит просветы между
    # надписями), на тёмном — светлая; маска насыщенности (цветные стрелки) остаётся всегда
    face = cv2.cvtColor(dial_bgr, cv2.COLOR_BGR2GRAY)[_ANNULUS]
    face_level = float(np.median(face))
    if face_level >= FACE_LIGHT_LEVEL:
        masks.pop("tophat", None)
    elif face_level <= FACE_DARK_LEVEL:
        masks.pop("blackhat", None)
    for mode, mask in masks.items():
        res = _needle_angle_moment(mask, allowed)
        if res.angle_deg is None:
            continue
        if best_moment is None or res.confidence > best_moment.confidence:
            best_moment, best_mask, best_mode = res, mask, mode

    if best_moment is None or best_mask is None:
        return NeedleResult(None, None, 0.0, "none")

    hough = _needle_angle_hough(best_mask, allowed)
    if hough.angle_deg is None or _ang_diff(hough.angle_deg, best_moment.angle_deg) > 12:
        # Момент «засорён» цифрами и надписями внутри шкалы. Длинный прямой отрезок через ось —
        # почти всегда сама стрелка: ищем его во всех масках и принимаем, если он уверенный.
        lines = [(_needle_angle_hough(m, allowed), mode) for mode, m in masks.items()]
        lines = [(h, mode) for h, mode in lines if h.angle_deg is not None]
        if lines:
            line, mode = max(lines, key=lambda hm: hm[0].confidence)
            if line.confidence >= HOUGH_ALONE_MIN:
                return NeedleResult(line.angle_deg, line.tip, 0.8 * line.confidence, f"hough/{mode}")
    if hough.angle_deg is not None and _ang_diff(hough.angle_deg, best_moment.angle_deg) <= 12:
        # согласованные оценки — взвешенное круговое среднее
        w_h = max(hough.confidence, 1e-3)
        w_m = max(best_moment.confidence, 1e-3)
        ah, am = math.radians(hough.angle_deg), math.radians(best_moment.angle_deg)
        angle = math.degrees(math.atan2(w_h * math.sin(ah) + w_m * math.sin(am),
                                        w_h * math.cos(ah) + w_m * math.cos(am))) % 360.0
        conf = min(1.0, 0.6 * best_moment.confidence + 0.4 * hough.confidence + 0.1)
        return NeedleResult(angle, hough.tip or best_moment.tip, conf, f"hough+moment/{best_mode}")
    return NeedleResult(best_moment.angle_deg, best_moment.tip,
                        best_moment.confidence * 0.9, f"moment/{best_mode}")


# ---------------------------------------------------------------------------
# Двухточечная калибровка шкалы (раздел 5.2 ТЗ)
# ---------------------------------------------------------------------------
def _calib_parts(calib: dict[str, Any]) -> tuple[float, float, float, float, str] | None:
    try:
        v_min = float(calib["v_min"])
        v_max = float(calib["v_max"])
        th_min = float(calib["theta_min"]) % 360.0
        th_max = float(calib["theta_max"]) % 360.0
    except (KeyError, TypeError, ValueError):
        return None
    direction = str(calib.get("direction", "cw")).lower()
    return v_min, th_min, v_max, th_max, ("ccw" if direction == "ccw" else "cw")


def angle_to_value(angle_deg: float, calib: dict[str, Any], clamp: float = 0.05,
                   max_overshoot: float = 0.08) -> float | None:
    """
    CW:  Δθ = (θ − θmin) mod 360;  Δθspan = (θmax − θmin) mod 360;
    CCW: Δθ = (θmin − θ) mod 360;  Δθspan = (θmin − θmax) mod 360;
    V = Vmin + Δθ/Δθspan · (Vmax − Vmin).

    Положения стрелки в глубокой «мёртвой зоне» (за пределами ±max_overshoot
    от рабочей дуги шкалы — например, при перепутанном направлении CW/CCW или
    перевёрнутой камере) возвращают None (недостоверный отсчёт), не маскируясь
    под корректный край шкалы.
    """
    parts = _calib_parts(calib)
    if parts is None:
        return None
    v_min, th_min, v_max, th_max, direction = parts
    if v_max == v_min:
        return None
    if direction == "cw":
        delta = (angle_deg - th_min) % 360.0
        span = (th_max - th_min) % 360.0
    else:
        delta = (th_min - angle_deg) % 360.0
        span = (th_min - th_max) % 360.0
    if span < 1.0:
        return None
    if delta > span:
        over = delta - span           # перелёт за максимум
        under = 360.0 - delta         # недолёт до минимума
        delta = span + over if over <= under else -under
    raw_frac = delta / span
    if raw_frac < -max_overshoot or raw_frac > 1.0 + max_overshoot:
        return None
    frac = max(-clamp, min(1.0 + clamp, raw_frac))
    return v_min + frac * (v_max - v_min)


def value_to_angle(value: float, calib: dict[str, Any]) -> float | None:
    """Обратное преобразование V -> θ (для отрисовки зон уставок на оверлее)."""
    parts = _calib_parts(calib)
    if parts is None:
        return None
    v_min, th_min, v_max, th_max, direction = parts
    if v_max == v_min:
        return None
    frac = (value - v_min) / (v_max - v_min)
    if direction == "cw":
        span = (th_max - th_min) % 360.0 or 360.0
        return (th_min + frac * span) % 360.0
    span = (th_min - th_max) % 360.0 or 360.0
    return (th_min - frac * span) % 360.0


# ---------------------------------------------------------------------------
# Пятизонная модель уставок (раздел 6.1 ТЗ, ISA-18.2 / ГОСТ Р МЭК 62682)
# ---------------------------------------------------------------------------
def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def classify_level(value: float | None, thresholds: dict[str, Any]) -> str:
    """
    normal | warning | alert:
      V ≤ LL или V ≥ HH  -> alert   (красная зона, проверяется первой)
      V ≤ L  или V ≥ H   -> warning (янтарная зона)
      L < V < H          -> normal  (нормальная зона)
    При lower_enabled=False нижние уставки (LL и L) отключены.
    """
    if value is None:
        return "normal"
    lower_on = thresholds.get("lower_enabled")
    ll = None if lower_on is False else _num(thresholds.get("ll_alert"))
    lw = None if lower_on is False else _num(thresholds.get("l_warn"))
    hw = _num(thresholds.get("h_warn"))
    hh = _num(thresholds.get("hh_alert"))
    if (ll is not None and value <= ll) or (hh is not None and value >= hh):
        return "alert"
    if (lw is not None and value <= lw) or (hw is not None and value >= hw):
        return "warning"
    return "normal"


# ---------------------------------------------------------------------------
# EMA-фильтр (раздел 5.3 ТЗ)
# ---------------------------------------------------------------------------
class EmaFilter:
    """Экспоненциальное сглаживание: V̄t = α·Vt + (1−α)·V̄t−1."""

    def __init__(self, alpha: float = config.EMA_ALPHA):
        self.alpha = alpha
        self._value: float | None = None

    def update(self, v: float | None) -> float | None:
        if v is None:
            return self._value  # сохраняем последнее достоверное значение
        if self._value is None:
            self._value = v
        else:
            self._value = self.alpha * v + (1.0 - self.alpha) * self._value
        return self._value

    def reset(self) -> None:
        self._value = None

    @property
    def value(self) -> float | None:
        return self._value


# ---------------------------------------------------------------------------
# Оверлей-визуализация (снапшоты/MJPEG-превью дашборда)
# ---------------------------------------------------------------------------
# cv2.putText не умеет кириллицу — для оверлея используем латинские эквиваленты
UNIT_ASCII = {
    "МПа": "MPa", "бар": "bar", "кгс/см²": "kgf/cm2", "кПа": "kPa", "°C": "C",
    "Па": "Pa", "кгс/м²": "kgf/m2", "%": "%", "мм": "mm", "м": "m",
    "А": "A", "кА": "kA", "В": "V", "кВ": "kV", "МВт": "MW",
    "т/ч": "t/h", "м³/ч": "m3/h",
}
_LEVEL_COLORS = {
    "normal": (90, 200, 80),
    "warning": (0, 200, 255),
    "alert": (50, 50, 240),
    "invalid": (140, 148, 156),
    "degraded": (0, 165, 255),
}


def _dial_to_frame(roi: DialROI, pts: np.ndarray) -> np.ndarray:
    return cv2.transform(pts.reshape(-1, 1, 2).astype(np.float32), roi.inv_matrix).reshape(-1, 2)


def _ray_points(roi: DialROI, angle_deg: float, r0: float, r1: float) -> tuple[tuple[int, int], tuple[int, int]]:
    c = config.DIAL_SIZE / 2.0
    rad = math.radians(angle_deg)
    pts = np.array([[c + math.cos(rad) * r0, c + math.sin(rad) * r0],
                    [c + math.cos(rad) * r1, c + math.sin(rad) * r1]])
    p = _dial_to_frame(roi, pts)
    return (int(p[0][0]), int(p[0][1])), (int(p[1][0]), int(p[1][1]))


def _zone_arc_points(roi: DialROI, calib: dict[str, Any],
                     v_from: float, v_to: float) -> np.ndarray | None:
    """Точки дуги зоны уставок вдоль шкалы (в координатах исходного кадра)."""
    a0 = value_to_angle(v_from, calib)
    a1 = value_to_angle(v_to, calib)
    if a0 is None or a1 is None:
        return None
    parts = _calib_parts(calib)
    if parts is None:
        return None
    direction = parts[4]
    sweep = (a1 - a0) % 360.0 if direction == "cw" else -((a0 - a1) % 360.0)
    if abs(sweep) < 0.5:
        return None
    steps = max(4, int(abs(sweep) / 3))
    c = config.DIAL_SIZE / 2.0
    rr = c * 0.93
    angs = np.radians(a0 + np.linspace(0, sweep, steps))
    pts = np.stack([c + np.cos(angs) * rr, c + np.sin(angs) * rr], axis=1)
    return _dial_to_frame(roi, pts)


def _zone_segments(calib: dict[str, Any],
                   thresholds: dict[str, Any] | None) -> list[tuple[float, float, str]]:
    """Зоны шкалы (от, до, уровень) по пятизонной модели, обрезанные по Vmin…Vmax."""
    parts = _calib_parts(calib)
    if parts is None:
        return []
    v_min, _, v_max, _, _ = parts
    lo, hi = min(v_min, v_max), max(v_min, v_max)
    thr = thresholds or {}
    lower_on = thr.get("lower_enabled")
    ll = None if lower_on is False else _num(thr.get("ll_alert"))
    lw = None if lower_on is False else _num(thr.get("l_warn"))
    hw, hh = _num(thr.get("h_warn")), _num(thr.get("hh_alert"))
    n_lo = lw if lw is not None else ll
    n_hi = hw if hw is not None else hh
    zones = [(n_lo if n_lo is not None else lo, n_hi if n_hi is not None else hi, "normal")]
    if ll is not None:
        zones.append((lo, ll, "alert"))
    if lw is not None:
        zones.append((ll if ll is not None else lo, lw, "warning"))
    if hw is not None:
        zones.append((hw, hh if hh is not None else hi, "warning"))
    if hh is not None:
        zones.append((hh, hi, "alert"))
    out = []
    for z0, z1, level in zones:
        z0, z1 = max(lo, min(hi, z0)), max(lo, min(hi, z1))
        if z1 > z0:
            out.append((z0, z1, level))
    return out


def _needle_points(roi: DialROI, needle: NeedleResult) -> np.ndarray:
    """Ось вращения и острие стрелки в координатах исходного кадра."""
    size = config.DIAL_SIZE
    cc = size / 2.0
    if needle.tip:
        px, py = float(needle.tip[0]), float(needle.tip[1])
    else:
        rad = math.radians(needle.angle_deg or 0.0)
        px, py = cc + math.cos(rad) * size * 0.42, cc + math.sin(rad) * size * 0.42
    return _dial_to_frame(roi, np.array([[cc, cc], [px, py]]))


def overlay_geometry(frame_shape: tuple[int, ...], roi: DialROI | None,
                     needle: NeedleResult | None, calib: dict[str, Any] | None,
                     thresholds: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Геометрия распознавания для векторной разметки на пульте — в пикселях
    обработанного кадра (w × h): эллипс ROI и его габаритная рамка, дуги зон
    уставок, лучи θmin / θmax, вектор стрелки. Пульт масштабирует её на кадр
    любого разрешения с тем же соотношением сторон.
    """
    if roi is None:
        return None
    h, w = frame_shape[:2]
    r1 = lambda v: round(float(v), 1)  # noqa: E731
    cx, cy = roi.center
    a, b = roi.axes
    phi = math.radians(roi.angle_deg)
    # габариты повёрнутого эллипса
    hw_ = math.sqrt((a * math.cos(phi)) ** 2 + (b * math.sin(phi)) ** 2)
    hh_ = math.sqrt((a * math.sin(phi)) ** 2 + (b * math.cos(phi)) ** 2)
    geom: dict[str, Any] = {
        "w": int(w), "h": int(h),
        "source": roi.source, "score": round(float(roi.score), 3),
        "ellipse": [r1(cx), r1(cy), r1(a), r1(b), r1(roi.angle_deg)],
        "bbox": [r1(cx - hw_), r1(cy - hh_), r1(2 * hw_), r1(2 * hh_)],
        "zones": [], "rays": [], "needle": None,
    }
    if calib:
        parts = _calib_parts(calib)
        if parts:
            for z0, z1, level in _zone_segments(calib, thresholds):
                pts = _zone_arc_points(roi, calib, z0, z1)
                if pts is not None:
                    geom["zones"].append({"level": level,
                                          "points": [[r1(x), r1(y)] for x, y in pts]})
            for name, th in (("min", parts[1]), ("max", parts[3])):
                p0, p1 = _ray_points(roi, th, config.DIAL_SIZE * 0.40, config.DIAL_SIZE * 0.49)
                geom["rays"].append({"name": name, "theta": round(th, 2),
                                     "points": [list(p0), list(p1)]})
    if needle is not None and needle.angle_deg is not None:
        p = _needle_points(roi, needle)
        geom["needle"] = [[r1(p[0][0]), r1(p[0][1])], [r1(p[1][0]), r1(p[1][1])]]
    return geom


def draw_overlay(frame_bgr: np.ndarray, roi: DialROI | None, needle: NeedleResult | None,
                 value: float | None, unit: str, level: str,
                 calib: dict[str, Any] | None = None,
                 thresholds: dict[str, Any] | None = None,
                 labels: bool = True) -> np.ndarray:
    """
    Рисует контур циферблата, зоны уставок, стрелку и значение на кадре.
    Цвет, текст и плашка статуса формируются из единого достоверного источника
    состояния (без затенения переменной `level`, DEF-02).
    """
    out = frame_bgr.copy()
    # Единый источник состояния: при отсутствии достоверного значения — статус invalid/degraded
    state_level = level if (value is not None and level in ("normal", "warning", "alert")) else (
        level if level in ("invalid", "degraded") else "invalid"
    )
    color = _LEVEL_COLORS.get(state_level, _LEVEL_COLORS["invalid"])
    scale = max(0.5, min(out.shape[0], out.shape[1]) / 720.0)

    if roi is not None:
        c = (int(roi.center[0]), int(roi.center[1]))
        ax = (int(roi.axes[0]), int(roi.axes[1]))
        cv2.ellipse(out, c, ax, roi.angle_deg, 0, 360, (200, 200, 200), 1, cv2.LINE_AA)

        if calib:
            parts = _calib_parts(calib)
            if parts:
                for z0, z1, z_level in _zone_segments(calib, thresholds):
                    pts = _zone_arc_points(roi, calib, z0, z1)
                    if pts is not None:
                        cv2.polylines(out, [pts.astype(np.int32)], False,
                                      _LEVEL_COLORS.get(z_level, _LEVEL_COLORS["normal"]), 4, cv2.LINE_AA)
                # калибровочные лучи θmin / θmax
                for th in (parts[1], parts[3]):
                    p0, p1 = _ray_points(roi, th, config.DIAL_SIZE * 0.40, config.DIAL_SIZE * 0.49)
                    cv2.line(out, p0, p1, (255, 160, 60), 2, cv2.LINE_AA)

        if needle is not None and needle.angle_deg is not None and value is not None:
            p = _needle_points(roi, needle)
            cv2.arrowedLine(out, (int(p[0][0]), int(p[0][1])), (int(p[1][0]), int(p[1][1])),
                            color, max(2, int(3 * scale)), cv2.LINE_AA, tipLength=0.12)
            cv2.circle(out, (int(p[0][0]), int(p[0][1])), max(3, int(5 * scale)), color, -1)

    if not labels:
        return out
    unit_txt = UNIT_ASCII.get(unit, unit.encode("ascii", "ignore").decode() or "")
    label = f"{value:.2f} {unit_txt}" if value is not None else "INVALID / NO READING"
    fs = 0.9 * scale
    th = max(1, int(2 * scale))
    (tw, tht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
    cv2.rectangle(out, (8, 8), (8 + tw + 20, 8 + tht + 22), (20, 20, 20), -1)
    cv2.putText(out, label, (18, 8 + tht + 10), cv2.FONT_HERSHEY_SIMPLEX, fs, color, th, cv2.LINE_AA)
    if state_level != "normal":
        badge_map = {"alert": "CRITICAL", "warning": "WARNING", "degraded": "DEGRADED", "invalid": "INVALID"}
        badge = badge_map.get(state_level, "INVALID")
        (bw, bh), _ = cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        x0 = out.shape[1] - bw - 28
        cv2.rectangle(out, (x0, 8), (out.shape[1] - 8, 8 + bh + 22), color, -1)
        cv2.putText(out, badge, (x0 + 10, 8 + bh + 10), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (255, 255, 255), th, cv2.LINE_AA)
    return out


# ---------------------------------------------------------------------------
# Сквозной конвейер одной камеры
# ---------------------------------------------------------------------------
class GaugePipeline:
    """
    Состояние конвейера одного прибора: кэш ROI циферблата (повторная
    локализация каждые REDETECT_EVERY_N_FRAMES кадров), EMA-фильтр,
    последнее достоверное значение.

    Метод process() — синхронный и CPU-bound; вызывается в пуле потоков.
    Для одного экземпляра вызовы сериализуются внутренним Lock.
    """

    def __init__(self, cam_id: str) -> None:
        self.cam_id = cam_id
        self.ema = EmaFilter(config.EMA_ALPHA)
        self.roi: DialROI | None = None
        self._frames_since_detect = 0
        self._miss_streak = 0
        self._lock = threading.Lock()
        self._calib_sig: str | None = None
        self._last_level = "normal"

    def reset(self, keep_roi: bool = False) -> None:
        with self._lock:
            self.ema.reset()
            self._last_level = "normal"
            if not keep_roi:
                self.roi = None
            self._frames_since_detect = 0
            self._miss_streak = 0

    def _locate(self, frame: np.ndarray, calib: dict[str, Any]) -> DialROI:
        roi_cfg = calib.get("roi") if isinstance(calib.get("roi"), dict) else None
        if roi_cfg and roi_cfg.get("mode") == "manual":
            roi = manual_roi(frame, roi_cfg)
            if roi is not None:
                return roi
        need = (self.roi is None or self.roi.source == "frame"
                or self._frames_since_detect >= config.REDETECT_EVERY_N_FRAMES
                or self._miss_streak >= 3)
        if need:
            found = detect_dial(frame)
            self._frames_since_detect = 0
            if found is not None:
                if self.roi is not None and self.roi.source != "frame":
                    # гистерезис: не «прыгаем» между близкими кандидатами
                    shift = math.hypot(found.center[0] - self.roi.center[0],
                                       found.center[1] - self.roi.center[1])
                    if shift < 0.05 * max(self.roi.axes) and self._miss_streak < 3:
                        found = self.roi
                self.roi = found
            elif self.roi is None or self._miss_streak >= 3:
                self.roi = frame_roi(frame)
        else:
            self._frames_since_detect += 1
        return self.roi if self.roi is not None else frame_roi(frame)

    def process(self, frame_bgr: np.ndarray, calibration: dict[str, Any],
                thresholds: dict[str, Any], unit: str,
                with_overlay: bool = True, roi_override: DialROI | None = None) -> GaugeReading:
        """Один кадр одного прибора.

        roi_override — циферблат, уже найденный трекером Multi-Gauge в координатах этого кадра
        (кадр тогда не масштабируется: трекер работает на кадре ширины ≤ MAX_PROCESS_WIDTH).
        """
        t0 = time.perf_counter()
        with self._lock:
            frame = frame_bgr
            h, w = frame.shape[:2]
            if w > config.MAX_PROCESS_WIDTH and roi_override is None:
                k = config.MAX_PROCESS_WIDTH / float(w)
                frame = cv2.resize(frame, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)

            # смена калибровки -> сбрасываем EMA, чтобы не тянуть старую шкалу
            sig = repr(sorted((k, v) for k, v in calibration.items() if k != "roi"))
            if sig != self._calib_sig:
                self.ema.reset()
                self._calib_sig = sig

            roi = roi_override if roi_override is not None else self._locate(frame, calibration)
            dial = normalize_dial(frame, roi)
            suitable, invalid_reason, dial_quality = assess_dial_suitability(dial)
            arc = needle_search_arc(calibration)
            work_arc = needle_search_arc(calibration, margin=0.0)   # сама рабочая дуга, без запаса
            reading_scale = None
            if suitable and work_arc is not None:
                # шкала должна быть видна вдоль рабочей дуги (защита от перекрытия и «не того» прибора)
                gap, coverage, coherence = scale_arc_evidence(dial, work_arc)
                reading_scale = {"gap": round(gap, 3), "coverage": round(coverage, 3), "coherence": round(coherence, 3)}
                if gap >= SCALE_GAP_MAX or coverage < SCALE_COVERAGE_MIN or coherence < SCALE_COHERENCE_MIN:
                    suitable, invalid_reason = False, "scale_not_visible"
            active_profile = get_vision_profile()
            ve_diag: dict[str, Any] | None = None
            needle_ms: float | None = None
            if suitable:
                if active_profile == "legacy":
                    needle = estimate_needle(dial, arc)
                else:
                    kpt_e, seg_e, cv2_e, fus_bal, fus_prec = _get_ve_estimators()
                    if active_profile == "eco":
                        det = cv2_e.estimate(dial, arc)
                    elif active_profile == "balanced":
                        det = fus_bal.estimate(dial, arc, use_kpt=False, use_seg=True, use_opencv=True)
                    else:  # precision
                        det = fus_prec.estimate(dial, arc, use_kpt=True, use_seg=True, use_opencv=True)
                    ve_diag = det.diagnostics
                    needle_ms = det.infer_ms
                    if det.valid and det.angle_deg is not None:
                        tip_int = (int(round(det.tip_px[0])), int(round(det.tip_px[1]))) if det.tip_px else None
                        needle = NeedleResult(det.angle_deg, tip_int, det.confidence, det.method)
                    else:
                        needle = NeedleResult(None, None, det.confidence, det.method)
                        if det.reject_reason:
                            invalid_reason = invalid_reason or det.reject_reason
            else:
                needle = NeedleResult(None, None, 0.0, "rejected")

            reading = GaugeReading(dial_found=roi.source != "frame", dial_source=roi.source)
            reading.needle_confidence = round(float(needle.confidence), 3)
            reading.debug = {
                "vision_engine": config.VISION_ENGINE_VERSION,
                "vision_profile": active_profile,
                "needle_method": needle.method,
                "needle_ms": needle_ms,
                "fusion_diagnostics": ve_diag,
                "roi": roi.to_json(),
                "dial_suitable": suitable,
                "dial_quality": dial_quality,
                "invalid_reason": invalid_reason,
                "scale_evidence": reading_scale,
            }

            # Дополнительная защита от ложных показаний при низкой уверенности без согласования Hough (DEF-15)
            min_conf = config.MIN_NEEDLE_CONFIDENCE
            if needle.method.startswith("moment/") and needle.confidence < max(min_conf, 0.45):
                suitable = False
                reading.debug["invalid_reason"] = reading.debug["invalid_reason"] or "low_confidence_unconfirmed"

            if suitable and needle.angle_deg is not None and needle.confidence >= min_conf:
                self._miss_streak = 0
                reading.angle = round(float(needle.angle_deg), 2)
                reading.value = angle_to_value(needle.angle_deg, calibration)
                reading.valid = reading.value is not None
                if not reading.valid:
                    reading.debug["out_of_scale"] = True
                    reading.debug["invalid_reason"] = "out_of_scale"
            else:
                self._miss_streak += 1
                if not reading.debug.get("invalid_reason"):
                    reading.debug["invalid_reason"] = "low_confidence"

            reading.ema_value = self.ema.update(reading.value if reading.valid else None)
            reading.status_level = classify_level(reading.ema_value, thresholds) if reading.ema_value is not None else "normal"
            reading.debug["geom"] = overlay_geometry(
                frame.shape, roi,
                needle if (reading.valid and needle.angle_deg is not None) else None,
                calibration, thresholds)

            if with_overlay:
                ov_level = reading.status_level if reading.valid else ("degraded" if invalid_reason == "partial_occlusion" else "invalid")
                reading.overlay = draw_overlay(
                    frame, roi,
                    needle if (reading.valid and needle.angle_deg is not None) else None,
                    reading.ema_value if reading.valid else None,
                    unit, ov_level, calibration, thresholds,
                )
            if reading.valid and reading.ema_value is not None and reading.status_level != self._last_level:
                if reading.status_level != "normal":
                    reading.snapshot = draw_overlay(
                        frame, roi, needle, reading.ema_value,
                        unit, reading.status_level, calibration, thresholds, labels=False,
                    )
                self._last_level = reading.status_level
            reading.process_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return reading
