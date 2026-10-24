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


def _yolo_gauge_bbox(frame_bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """BBox (x, y, w, h) самого крупного прибора из классов config.YOLO_CLASSES."""
    model = _load_yolo()
    if model is None:
        return None
    try:
        with _YOLO_INFER_LOCK:
            results = model.predict(frame_bgr, conf=config.YOLO_CONF, **_predict_kwargs())
        best = None
        best_area = 0.0
        for r in results:
            names = r.names or {}
            for box in r.boxes:
                cls_name = str(names.get(int(box.cls), "")).lower()
                if any(k in cls_name for k in config.YOLO_CLASSES):
                    x1, y1, x2, y2 = map(float, box.xyxy[0])
                    area = (x2 - x1) * (y2 - y1)
                    if area > best_area:
                        best_area = area
                        best = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
        return best
    except Exception as exc:
        logger.debug("YOLO inference failed: %s", exc)
        return None


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


def _ellipse_candidates(gray: np.ndarray) -> list[tuple[float, float, float, float, float, float]]:
    """
    Эллиптическая аппроксимация крупных округлых контуров.
    Возвращает [(cx, cy, a, b, φ, score)], a/b — полуоси.
    """
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 130)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    min_area = 0.015 * h * w
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
        if fill < 0.75 or fill > 1.25:  # контур плохо совпадает с эллипсом
            continue
        score = (area / (h * w)) * (1.0 - abs(1.0 - fill))
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


def detect_dial(frame_bgr: np.ndarray) -> DialROI | None:
    """
    Двухступенчатая детекция: YOLO локализует прибор, контурный эллипс OpenCV
    уточняет геометрию (рамка YOLO бывает смещена/обрезана, эллипс — точнее).

    • эллипс OpenCV с центром внутри рамки YOLO -> эллипс (источник «yolo+ellipse»);
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


def _needle_angle_moment(mask: np.ndarray) -> NeedleResult:
    """
    Поиск направления максимального радиального момента инерции.

    Для каждого угла-кандидата суммируем пиксели маски вдоль луча с весом ~ r
    (дальние точки стрелки дают больший момент, а равномерно распределённые
    по дуге риски шкалы образуют лишь фон гистограммы).
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

    best = int(np.argmax(smooth))
    peak = float(smooth[best])
    if peak <= 0:
        return NeedleResult(None, None, 0.0, "none")
    # подавляем окрестность пика ±25° и смотрим второй максимум
    diff_bins = np.abs((np.arange(360) - best + 180) % 360 - 180)
    second = float(smooth[diff_bins > 25].max()) if (diff_bins > 25).any() else 0.0
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


def _needle_angle_hough(mask: np.ndarray) -> NeedleResult:
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


def estimate_needle(dial_bgr: np.ndarray) -> NeedleResult:
    """
    Комбинированная оценка направления стрелки на нормализованном циферблате.

    Для каждой маски (Black-Hat / Top-Hat / насыщенность) считаем радиальный
    момент; выбираем маску с наибольшей уверенностью. Затем HoughLinesP
    уточняет угол, если согласуется с моментом (расхождение ≤ 12°).
    """
    best_moment: NeedleResult | None = None
    best_mask: np.ndarray | None = None
    best_mode = "none"
    for mode, mask in needle_masks(dial_bgr).items():
        res = _needle_angle_moment(mask)
        if res.angle_deg is None:
            continue
        if best_moment is None or res.confidence > best_moment.confidence:
            best_moment, best_mask, best_mode = res, mask, mode

    if best_moment is None or best_mask is None:
        return NeedleResult(None, None, 0.0, "none")

    hough = _needle_angle_hough(best_mask)
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


def angle_to_value(angle_deg: float, calib: dict[str, Any], clamp: float = 0.05) -> float | None:
    """
    CW:  Δθ = (θ − θmin) mod 360;  Δθspan = (θmax − θmin) mod 360;
    CCW: Δθ = (θmin − θ) mod 360;  Δθspan = (θmin − θmax) mod 360;
    V = Vmin + Δθ/Δθspan · (Vmax − Vmin).

    Положения стрелки в «мёртвой зоне» шкалы относятся к ближайшему краю
    (небольшой заход ниже нуля не превращается в максимум шкалы).
    """
    parts = _calib_parts(calib)
    if parts is None:
        return None
    v_min, th_min, v_max, th_max, direction = parts
    if direction == "cw":
        delta = (angle_deg - th_min) % 360.0
        span = (th_max - th_min) % 360.0
    else:
        delta = (th_min - angle_deg) % 360.0
        span = (th_min - th_max) % 360.0
    if span < 1e-6:
        span = 360.0
    if delta > span:
        over = delta - span           # перелёт за максимум
        under = 360.0 - delta         # недолёт до минимума
        delta = span + over if over <= under else -under
    frac = delta / span
    frac = max(-clamp, min(1.0 + clamp, frac))
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
      V ≤ LL или V ≥ HH  -> alert   (красная зона)
      V ≤ L  или V ≥ H   -> warning (жёлтая зона)
      L < V < H          -> normal  (зелёный доверительный интервал)
    """
    if value is None:
        return "normal"
    ll = _num(thresholds.get("ll_alert"))
    lw = _num(thresholds.get("l_warn"))
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
_LEVEL_COLORS = {"normal": (90, 200, 80), "warning": (0, 200, 255), "alert": (50, 50, 240)}


def _dial_to_frame(roi: DialROI, pts: np.ndarray) -> np.ndarray:
    return cv2.transform(pts.reshape(-1, 1, 2).astype(np.float32), roi.inv_matrix).reshape(-1, 2)


def _ray_points(roi: DialROI, angle_deg: float, r0: float, r1: float) -> tuple[tuple[int, int], tuple[int, int]]:
    c = config.DIAL_SIZE / 2.0
    rad = math.radians(angle_deg)
    pts = np.array([[c + math.cos(rad) * r0, c + math.sin(rad) * r0],
                    [c + math.cos(rad) * r1, c + math.sin(rad) * r1]])
    p = _dial_to_frame(roi, pts)
    return (int(p[0][0]), int(p[0][1])), (int(p[1][0]), int(p[1][1]))


def _draw_zone_arc(out: np.ndarray, roi: DialROI, calib: dict[str, Any],
                   v_from: float, v_to: float, color: tuple[int, int, int]) -> None:
    """Дуга зоны уставок вдоль шкалы (в координатах исходного кадра)."""
    a0 = value_to_angle(v_from, calib)
    a1 = value_to_angle(v_to, calib)
    if a0 is None or a1 is None:
        return
    parts = _calib_parts(calib)
    if parts is None:
        return
    direction = parts[4]
    sweep = (a1 - a0) % 360.0 if direction == "cw" else -((a0 - a1) % 360.0)
    if abs(sweep) < 0.5:
        return
    steps = max(4, int(abs(sweep) / 3))
    c = config.DIAL_SIZE / 2.0
    rr = c * 0.93
    angs = np.radians(a0 + np.linspace(0, sweep, steps))
    pts = np.stack([c + np.cos(angs) * rr, c + np.sin(angs) * rr], axis=1)
    p = _dial_to_frame(roi, pts).astype(np.int32)
    cv2.polylines(out, [p], False, color, 4, cv2.LINE_AA)


def draw_overlay(frame_bgr: np.ndarray, roi: DialROI | None, needle: NeedleResult | None,
                 value: float | None, unit: str, level: str,
                 calib: dict[str, Any] | None = None,
                 thresholds: dict[str, Any] | None = None) -> np.ndarray:
    """Рисует контур циферблата, зоны уставок, стрелку и значение на кадре."""
    out = frame_bgr.copy()
    color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["normal"])
    scale = max(0.5, min(out.shape[0], out.shape[1]) / 720.0)

    if roi is not None:
        c = (int(roi.center[0]), int(roi.center[1]))
        ax = (int(roi.axes[0]), int(roi.axes[1]))
        cv2.ellipse(out, c, ax, roi.angle_deg, 0, 360, (200, 200, 200), 1, cv2.LINE_AA)

        if calib:
            parts = _calib_parts(calib)
            if parts:
                v_min, th_min, v_max, th_max, _ = parts
                lo, hi = min(v_min, v_max), max(v_min, v_max)
                thr = thresholds or {}
                ll, lw = _num(thr.get("ll_alert")), _num(thr.get("l_warn"))
                hw, hh = _num(thr.get("h_warn")), _num(thr.get("hh_alert"))
                zones = []
                n_lo = lw if lw is not None else ll
                n_hi = hw if hw is not None else hh
                zones.append((n_lo if n_lo is not None else lo, n_hi if n_hi is not None else hi,
                              _LEVEL_COLORS["normal"]))
                if ll is not None:
                    zones.append((lo, ll, _LEVEL_COLORS["alert"]))
                if lw is not None:
                    zones.append((ll if ll is not None else lo, lw, _LEVEL_COLORS["warning"]))
                if hw is not None:
                    zones.append((hw, hh if hh is not None else hi, _LEVEL_COLORS["warning"]))
                if hh is not None:
                    zones.append((hh, hi, _LEVEL_COLORS["alert"]))
                for z0, z1, zc in zones:
                    z0, z1 = max(lo, min(hi, z0)), max(lo, min(hi, z1))
                    if z1 > z0:
                        _draw_zone_arc(out, roi, calib, z0, z1, zc)
                # калибровочные лучи θmin / θmax
                for th in (th_min, th_max):
                    p0, p1 = _ray_points(roi, th, config.DIAL_SIZE * 0.40, config.DIAL_SIZE * 0.49)
                    cv2.line(out, p0, p1, (255, 160, 60), 2, cv2.LINE_AA)

        if needle is not None and needle.angle_deg is not None:
            size = config.DIAL_SIZE
            cc = size / 2.0
            if needle.tip:
                px, py = float(needle.tip[0]), float(needle.tip[1])
            else:
                rad = math.radians(needle.angle_deg)
                px, py = cc + math.cos(rad) * size * 0.42, cc + math.sin(rad) * size * 0.42
            p = _dial_to_frame(roi, np.array([[cc, cc], [px, py]]))
            cv2.arrowedLine(out, (int(p[0][0]), int(p[0][1])), (int(p[1][0]), int(p[1][1])),
                            color, max(2, int(3 * scale)), cv2.LINE_AA, tipLength=0.12)
            cv2.circle(out, (int(p[0][0]), int(p[0][1])), max(3, int(5 * scale)), color, -1)

    unit_txt = UNIT_ASCII.get(unit, unit.encode("ascii", "ignore").decode() or "")
    label = f"{value:.2f} {unit_txt}" if value is not None else "NO READING"
    fs = 0.9 * scale
    th = max(1, int(2 * scale))
    (tw, tht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
    cv2.rectangle(out, (8, 8), (8 + tw + 20, 8 + tht + 22), (20, 20, 20), -1)
    cv2.putText(out, label, (18, 8 + tht + 10), cv2.FONT_HERSHEY_SIMPLEX, fs, color, th, cv2.LINE_AA)
    if level != "normal":
        badge = "CRITICAL" if level == "alert" else "WARNING"
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

    def reset(self, keep_roi: bool = False) -> None:
        with self._lock:
            self.ema.reset()
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
                with_overlay: bool = True) -> GaugeReading:
        t0 = time.perf_counter()
        with self._lock:
            frame = frame_bgr
            h, w = frame.shape[:2]
            if w > config.MAX_PROCESS_WIDTH:
                k = config.MAX_PROCESS_WIDTH / float(w)
                frame = cv2.resize(frame, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)

            # смена калибровки -> сбрасываем EMA, чтобы не тянуть старую шкалу
            sig = repr(sorted((k, v) for k, v in calibration.items() if k != "roi"))
            if sig != self._calib_sig:
                self.ema.reset()
                self._calib_sig = sig

            roi = self._locate(frame, calibration)
            dial = normalize_dial(frame, roi)
            needle = estimate_needle(dial)

            reading = GaugeReading(dial_found=roi.source != "frame", dial_source=roi.source)
            reading.needle_confidence = round(float(needle.confidence), 3)
            reading.debug = {"needle_method": needle.method, "roi": roi.to_json()}

            if needle.angle_deg is not None and needle.confidence >= config.MIN_NEEDLE_CONFIDENCE:
                self._miss_streak = 0
                reading.angle = round(float(needle.angle_deg), 2)
                reading.value = angle_to_value(needle.angle_deg, calibration)
                reading.valid = reading.value is not None
            else:
                self._miss_streak += 1

            reading.ema_value = self.ema.update(reading.value if reading.valid else None)
            reading.status_level = classify_level(reading.ema_value, thresholds)

            if with_overlay:
                reading.overlay = draw_overlay(
                    frame, roi, needle if reading.valid else None, reading.ema_value,
                    unit, reading.status_level, calibration, thresholds,
                )
            reading.process_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return reading
