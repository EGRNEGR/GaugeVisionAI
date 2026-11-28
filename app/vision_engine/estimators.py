"""
GaugeVision AI 3.1 — Оценщики положения стрелки и Intelligent Fusion.

Реализует 4 независимых метода:
  • OpenCVNeedleV2 (Подход A+) — геометрический конвейер с проверкой контраста луча
    (устраняет ложные срабатывания top-hat на бликах/надписях модели M1);
  • NeuralKeypointEstimator (Подход B2) — NeedleKeypointNet (ONNX Runtime или PyTorch)
    с пакетным инференсом для Multi-Gauge;
  • NeuralSegEstimator (Подход C2) — NeedleSegUNet (ONNX Runtime или PyTorch) + PCA/ODR;
  • FusionNeedleEstimator (Подходы G/H) — циклическое согласование без наивного усреднения
    несовместимых углов и калиброванная оценка достоверности.
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

from .. import config
from .registry import get_registry

logger = logging.getLogger("gaugevision.vision_engine.estimators")

CROP_SIZE = 160


def ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def circular_weighted_mean(angles_deg: list[float], weights: list[float]) -> float:
    sx = sum(w * math.cos(math.radians(a)) for a, w in zip(angles_deg, weights))
    sy = sum(w * math.sin(math.radians(a)) for a, w in zip(angles_deg, weights))
    return math.degrees(math.atan2(sy, sx)) % 360.0


@dataclass
class DetailedNeedleEstimate:
    angle_deg: float | None = None
    center_px: tuple[float, float] | None = None   # в координатах нормализованного циферблата (640 px)
    tip_px: tuple[float, float] | None = None      # в координатах нормализованного циферблата (640 px)
    confidence: float = 0.0
    visibility: float = 1.0
    method: str = "none"
    valid: bool = False
    reject_reason: str | None = None
    infer_ms: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Подход A+: Улучшенный геометрический оценщик OpenCV (исправление M1 top-hat)
# ---------------------------------------------------------------------------
def _ray_polarity_contrast(gray: np.ndarray, angle_deg: float) -> float:
    """
    Проверяет локальный профиль яркости вдоль луча (r = 0.12..0.38 диаметра)
    относительно соседних лучей ±8°.
    > 0 -> луч СВЕТЛЕЕ окружения (светлая стрелка на тёмном фоне);
    < 0 -> луч ТЕМНЕЕ окружения (тёмная стрелка на светлом/сером фоне).
    """
    h, w = gray.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    radii = np.linspace(0.12 * w, 0.36 * w, 24)

    def sample_ray(deg: float) -> float:
        rad = math.radians(deg)
        xs = np.clip(np.round(cx + np.cos(rad) * radii).astype(int), 0, w - 1)
        ys = np.clip(np.round(cy + np.sin(rad) * radii).astype(int), 0, h - 1)
        return float(np.median(gray[ys, xs]))

    c_val = sample_ray(angle_deg)
    flank = 0.5 * (sample_ray(angle_deg - 8.0) + sample_ray(angle_deg + 8.0))
    return c_val - flank


def estimate_needle_opencv_v2(dial_bgr: np.ndarray, allowed: np.ndarray | None = None) -> DetailedNeedleEstimate:
    """
    Улучшенная геометрия OpenCV (Подход A+):
    в отличие от v8, для каждого кандидата из blackhat/tophat проверяет реальный
    профиль яркости вдоль луча (_ray_polarity_contrast), отсекая ложные блики top-hat
    на светлых и средне-серых циферблатах (основная причина 74/77 грубых ошибок M1).
    """
    from .. import vision  # локальный импорт без циклической зависимости

    t0 = time.perf_counter()
    gray = cv2.cvtColor(dial_bgr, cv2.COLOR_BGR2GRAY)
    masks = vision.needle_masks(dial_bgr)
    face_level = float(np.median(gray[vision._ANNULUS]))
    if face_level >= vision.FACE_LIGHT_LEVEL:
        masks.pop("tophat", None)
    elif face_level <= vision.FACE_DARK_LEVEL:
        masks.pop("blackhat", None)

    candidates: list[tuple[float, str, Any]] = []
    for mode, mask in masks.items():
        mom = vision._needle_angle_moment(mask, allowed)
        if mom.angle_deg is None:
            continue
        contrast = _ray_polarity_contrast(gray, mom.angle_deg)
        # Проверка согласованности полярности луча с типом маски!
        if mode == "tophat" and (contrast < 10.0 or face_level > 95.0 and contrast < 26.0):
            continue
        if mode == "blackhat" and contrast > 8.0:
            continue

        hough = vision._needle_angle_hough(mask, allowed)
        if hough.angle_deg is not None and ang_diff(hough.angle_deg, mom.angle_deg) <= 12.0:
            ang = circular_weighted_mean([hough.angle_deg, mom.angle_deg],
                                         [max(hough.confidence, 1e-3), max(mom.confidence, 1e-3)])
            conf = min(1.0, 0.6 * mom.confidence + 0.4 * hough.confidence + 0.1)
            candidates.append((conf, f"hough+moment/{mode}", (ang, hough.tip or mom.tip, contrast)))
        else:
            candidates.append((mom.confidence * 0.9, f"moment/{mode}", (mom.angle_deg, mom.tip, contrast)))
            if hough.angle_deg is not None and hough.confidence >= vision.HOUGH_ALONE_MIN:
                hc = _ray_polarity_contrast(gray, hough.angle_deg)
                ok_h = not (mode == "tophat" and (hc < 10.0 or (face_level > 95.0 and hc < 26.0)))
                if ok_h:
                    candidates.append((0.8 * hough.confidence, f"hough/{mode}", (hough.angle_deg, hough.tip, hc)))

    elapsed = (time.perf_counter() - t0) * 1000.0
    if not candidates:
        return DetailedNeedleEstimate(method="opencv_v2/none", infer_ms=round(elapsed, 2), reject_reason="no_needle_candidate")

    candidates.sort(key=lambda c: c[0], reverse=True)
    conf, method, (ang, tip, contrast) = candidates[0]
    s = float(dial_bgr.shape[0])
    return DetailedNeedleEstimate(
        angle_deg=round(float(ang), 2),
        center_px=(s / 2.0, s / 2.0),
        tip_px=(float(tip[0]), float(tip[1])) if tip else None,
        confidence=round(float(conf), 4),
        visibility=1.0,
        method=f"opencv_v2:{method}",
        valid=conf >= config.MIN_NEEDLE_CONFIDENCE,
        infer_ms=round(elapsed, 2),
        diagnostics={"ray_contrast": round(contrast, 2), "face_level": round(face_level, 1)},
    )


class OpenCVNeedleV2:
    def estimate(self, dial_bgr: np.ndarray, allowed: np.ndarray | None = None) -> DetailedNeedleEstimate:
        return estimate_needle_opencv_v2(dial_bgr, allowed)


# ---------------------------------------------------------------------------
# Подход B2: Нейросеть ключевых точек (NeedleKeypointNet — ONNX / PyTorch)
# ---------------------------------------------------------------------------
def _prep_batch(dials_bgr: list[np.ndarray], size: int = CROP_SIZE) -> np.ndarray:
    arr = np.empty((len(dials_bgr), 3, size, size), dtype=np.float32)
    for i, img in enumerate(dials_bgr):
        res = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(res, cv2.COLOR_BGR2RGB).astype(np.float32) * (1.0 / 127.5) - 1.0
        arr[i] = np.transpose(rgb, (2, 0, 1))
    return arr


class NeuralKeypointEstimator:
    """Потокобезопасный загрузчик и инференс NeedleKeypointNet (ONNX Runtime приоритетно, иначе PyTorch)."""

    def __init__(self, model_id_onnx: str = "needle_keypoint_v31_onnx", model_id_pt: str = "needle_keypoint_v31_pt") -> None:
        self.model_id_onnx = model_id_onnx
        self.model_id_pt = model_id_pt
        self._lock = threading.Lock()
        self._backend: str | None = None
        self._session: Any = None
        self._pt_model: Any = None
        self._load_error: str | None = None

    def _ensure_loaded(self) -> bool:
        if self._backend is not None:
            return self._backend != "failed"
        with self._lock:
            if self._backend is not None:
                return self._backend != "failed"
            reg = get_registry()
            # 1. Пробуем ONNX Runtime (быстрее на CPU, без pickle)
            p_onnx, err_onnx = reg.verify_and_resolve(self.model_id_onnx)
            if p_onnx is not None:
                try:
                    import onnxruntime as ort  # type: ignore
                    so = ort.SessionOptions()
                    so.intra_op_num_threads = max(1, min(4, config.MG_WORKERS))
                    so.inter_op_num_threads = 1
                    self._session = ort.InferenceSession(str(p_onnx), sess_options=so, providers=["CPUExecutionProvider"])
                    self._backend = "onnxruntime"
                    logger.info("NeedleKeypointNet загружена (ONNX Runtime CPU): %s", p_onnx.name)
                    return True
                except Exception as exc:
                    err_onnx = str(exc)
            # 2. Fallback на PyTorch (.pt с проверкой SHA-256)
            p_pt, err_pt = reg.verify_and_resolve(self.model_id_pt)
            if p_pt is not None:
                try:
                    import torch
                    from cv_next_gen.models_needle import NeedleKeypointNet
                    ckpt = torch.load(str(p_pt), map_location="cpu", weights_only=True)
                    m = NeedleKeypointNet(base_ch=int(ckpt.get("base_ch", 24)))
                    m.load_state_dict(ckpt["state_dict"])
                    m.eval()
                    self._pt_model = m
                    self._backend = "pytorch_cpu"
                    logger.info("NeedleKeypointNet загружена (PyTorch CPU): %s", p_pt.name)
                    return True
                except Exception as exc:
                    err_pt = str(exc)
            self._backend = "failed"
            self._load_error = f"onnx={err_onnx}; pt={err_pt}"
            logger.warning("NeedleKeypointNet недоступна: %s", self._load_error)
            return False

    @property
    def backend_name(self) -> str:
        self._ensure_loaded()
        return self._backend or "failed"

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def estimate_batch(self, dials_bgr: list[np.ndarray]) -> list[DetailedNeedleEstimate]:
        if not dials_bgr:
            return []
        if not self._ensure_loaded():
            return [DetailedNeedleEstimate(method="kpt/unavailable", reject_reason=self._load_error) for _ in dials_bgr]
        t0 = time.perf_counter()
        x_np = _prep_batch(dials_bgr, CROP_SIZE)
        if self._backend == "onnxruntime":
            coords, sincos, vis_logit = self._session.run(None, {"input": x_np})
        else:
            import torch
            with torch.no_grad():
                c_t, sc_t, v_t = self._pt_model(torch.from_numpy(x_np))
                coords, sincos, vis_logit = c_t.numpy(), sc_t.numpy(), v_t.numpy()
        elapsed_each = (time.perf_counter() - t0) * 1000.0 / len(dials_bgr)

        out: list[DetailedNeedleEstimate] = []
        for i, dial in enumerate(dials_bgr):
            s = float(dial.shape[0])
            cx_n, cy_n = float(coords[i, 0, 0]), float(coords[i, 0, 1])
            tx_n, ty_n = float(coords[i, 1, 0]), float(coords[i, 1, 1])
            ang_kpt = math.degrees(math.atan2(ty_n - cy_n, tx_n - cx_n)) % 360.0
            ang_sc = math.degrees(math.atan2(float(sincos[i, 0]), float(sincos[i, 1]))) % 360.0
            vis_prob = float(1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, float(vis_logit[i]))))))
            vec_len = math.hypot(tx_n - cx_n, ty_n - cy_n)
            internal_diff = ang_diff(ang_kpt, ang_sc)

            # Уверенность учитывает видимость, длину вектора и внутреннее согласие голов (kpt vs sincos)
            agree_factor = max(0.0, 1.0 - internal_diff / 45.0)
            len_factor = min(1.0, vec_len / 0.22)
            conf = float(np.clip(vis_prob * (0.55 + 0.45 * agree_factor) * len_factor, 0.0, 1.0))

            # Финальный угол: kpt (при согласии с sincos — круговое взвешенное 0.75/0.25)
            ang = circular_weighted_mean([ang_kpt, ang_sc], [0.75, 0.25]) if internal_diff <= 15.0 else ang_kpt
            out.append(DetailedNeedleEstimate(
                angle_deg=round(ang, 2),
                center_px=(round(cx_n * s, 1), round(cy_n * s, 1)),
                tip_px=(round(tx_n * s, 1), round(ty_n * s, 1)),
                confidence=round(conf, 4),
                visibility=round(vis_prob, 4),
                method=f"neural_kpt/{self._backend}",
                valid=vis_prob >= 0.45 and vec_len >= 0.10,
                reject_reason=None if (vis_prob >= 0.45 and vec_len >= 0.10) else "neural_low_visibility",
                infer_ms=round(elapsed_each, 2),
                diagnostics={
                    "ang_kpt": round(ang_kpt, 2),
                    "ang_sincos": round(ang_sc, 2),
                    "internal_diff_deg": round(internal_diff, 2),
                    "vec_len_norm": round(vec_len, 4),
                    "vis_prob": round(vis_prob, 4),
                },
            ))
        return out

    def estimate(self, dial_bgr: np.ndarray) -> DetailedNeedleEstimate:
        return self.estimate_batch([dial_bgr])[0]


# ---------------------------------------------------------------------------
# Подход C2: Пиксельная сегментация (NeedleSegUNet — ONNX / PyTorch)
# ---------------------------------------------------------------------------
class NeuralSegEstimator:
    """Потокобезопасный загрузчик и инференс NeedleSegUNet + PCA/ODR."""

    def __init__(self, model_id_onnx: str = "needle_seg_v31_onnx", model_id_pt: str = "needle_seg_v31_pt") -> None:
        self.model_id_onnx = model_id_onnx
        self.model_id_pt = model_id_pt
        self._lock = threading.Lock()
        self._backend: str | None = None
        self._session: Any = None
        self._pt_model: Any = None
        self._load_error: str | None = None

    def _ensure_loaded(self) -> bool:
        if self._backend is not None:
            return self._backend != "failed"
        with self._lock:
            if self._backend is not None:
                return self._backend != "failed"
            reg = get_registry()
            p_onnx, err_onnx = reg.verify_and_resolve(self.model_id_onnx)
            if p_onnx is not None:
                try:
                    import onnxruntime as ort  # type: ignore
                    so = ort.SessionOptions()
                    so.intra_op_num_threads = max(1, min(4, config.MG_WORKERS))
                    so.inter_op_num_threads = 1
                    self._session = ort.InferenceSession(str(p_onnx), sess_options=so, providers=["CPUExecutionProvider"])
                    self._backend = "onnxruntime"
                    logger.info("NeedleSegUNet загружена (ONNX Runtime CPU): %s", p_onnx.name)
                    return True
                except Exception as exc:
                    err_onnx = str(exc)
            p_pt, err_pt = reg.verify_and_resolve(self.model_id_pt)
            if p_pt is not None:
                try:
                    import torch
                    from cv_next_gen.models_needle import NeedleSegUNet
                    ckpt = torch.load(str(p_pt), map_location="cpu", weights_only=True)
                    m = NeedleSegUNet(base_ch=int(ckpt.get("base_ch", 20)))
                    m.load_state_dict(ckpt["state_dict"])
                    m.eval()
                    self._pt_model = m
                    self._backend = "pytorch_cpu"
                    logger.info("NeedleSegUNet загружена (PyTorch CPU): %s", p_pt.name)
                    return True
                except Exception as exc:
                    err_pt = str(exc)
            self._backend = "failed"
            self._load_error = f"onnx={err_onnx}; pt={err_pt}"
            logger.warning("NeedleSegUNet недоступна: %s", self._load_error)
            return False

    def estimate_batch(self, dials_bgr: list[np.ndarray],
                       centers_norm: list[tuple[float, float]] | None = None) -> list[DetailedNeedleEstimate]:
        if not dials_bgr:
            return []
        if not self._ensure_loaded():
            return [DetailedNeedleEstimate(method="seg/unavailable", reject_reason=self._load_error) for _ in dials_bgr]
        from cv_next_gen.models_needle import extract_angle_from_seg

        t0 = time.perf_counter()
        x_np = _prep_batch(dials_bgr, CROP_SIZE)
        if self._backend == "onnxruntime":
            seg_logits, tip_logits = self._session.run(None, {"input": x_np})
        else:
            import torch
            with torch.no_grad():
                sl, tl = self._pt_model(torch.from_numpy(x_np))
                seg_logits, tip_logits = sl.numpy(), tl.numpy()
        elapsed_each = (time.perf_counter() - t0) * 1000.0 / len(dials_bgr)

        # Softmax по оси классов (B, 3, H, W)
        ex = np.exp(seg_logits - seg_logits.max(axis=1, keepdims=True))
        probs = ex / np.clip(ex.sum(axis=1, keepdims=True), 1e-8, None)

        out: list[DetailedNeedleEstimate] = []
        for i, dial in enumerate(dials_bgr):
            s = float(dial.shape[0])
            c_norm = centers_norm[i] if centers_norm and i < len(centers_norm) else (0.5, 0.5)
            info = extract_angle_from_seg(probs[i], tip_logits[i, 0], center_norm=c_norm)
            ang = info.get("angle_deg")
            tip_n = info.get("tip_norm")
            out.append(DetailedNeedleEstimate(
                angle_deg=ang,
                center_px=(round(c_norm[0] * s, 1), round(c_norm[1] * s, 1)),
                tip_px=(round(tip_n[0] * s, 1), round(tip_n[1] * s, 1)) if tip_n else None,
                confidence=float(info.get("confidence", 0.0)),
                visibility=1.0 if info.get("ptr_pixels", 0) >= 12 else 0.0,
                method=f"neural_seg/{self._backend}",
                valid=ang is not None and float(info.get("confidence", 0.0)) >= 0.25,
                reject_reason=None if (ang is not None and float(info.get("confidence", 0.0)) >= 0.25) else "seg_no_needle",
                infer_ms=round(elapsed_each, 2),
                diagnostics=info,
            ))
        return out

    def estimate(self, dial_bgr: np.ndarray, center_norm: tuple[float, float] = (0.5, 0.5)) -> DetailedNeedleEstimate:
        return self.estimate_batch([dial_bgr], [center_norm])[0]


# ---------------------------------------------------------------------------
# Подходы G/H: Intelligent Fusion & Validation
# ---------------------------------------------------------------------------
class FusionNeedleEstimator:
    """
    Интеллектуальное согласование нейросетевых и геометрических оценок стрелки:
      • не усредняет несовместимые углы (расхождение > max_disagree_deg);
      • учитывает циклическую природу углов;
      • различает высокую внутреннюю согласованность нейросети (kpt + seg) и
        геометрическое подтверждение OpenCV v2;
      • при сильном расхождении и пограничной уверенности возвращает безопасный отказ.
    """

    def __init__(
        self,
        kpt: NeuralKeypointEstimator | None = None,
        seg: NeuralSegEstimator | None = None,
        max_disagree_deg: float = 14.0,
        min_neural_conf: float = 0.45,
    ) -> None:
        self.kpt = kpt
        self.seg = seg
        self.max_disagree_deg = max_disagree_deg
        self.min_neural_conf = min_neural_conf

    def estimate(
        self,
        dial_bgr: np.ndarray,
        allowed: np.ndarray | None = None,
        use_kpt: bool = True,
        use_seg: bool = True,
        use_opencv: bool = True,
    ) -> DetailedNeedleEstimate:
        t0 = time.perf_counter()
        s = float(dial_bgr.shape[0])

        r_kpt = self.kpt.estimate(dial_bgr) if (use_kpt and self.kpt is not None) else None
        # Используем геометрический центр (0.5, 0.5) для SegUNet, если kpt смещён > 10%
        c_norm = (0.5, 0.5)
        if r_kpt and r_kpt.center_px:
            kx, ky = r_kpt.center_px[0] / s, r_kpt.center_px[1] / s
            if math.hypot(kx - 0.5, ky - 0.5) <= 0.10:
                c_norm = (0.5 * kx + 0.25, 0.5 * ky + 0.25)
        r_seg = self.seg.estimate(dial_bgr, center_norm=c_norm) if (use_seg and self.seg is not None) else None
        r_cv = estimate_needle_opencv_v2(dial_bgr, allowed) if use_opencv else None

        diag: dict[str, Any] = {
            "kpt": None if r_kpt is None else {"angle": r_kpt.angle_deg, "conf": r_kpt.confidence, "vis": r_kpt.visibility, "ms": r_kpt.infer_ms},
            "seg": None if r_seg is None else {"angle": r_seg.angle_deg, "conf": r_seg.confidence, "ticks_frac": r_seg.diagnostics.get("ticks_frac"), "ms": r_seg.infer_ms},
            "opencv_v2": None if r_cv is None else {"angle": r_cv.angle_deg, "conf": r_cv.confidence, "method": r_cv.method, "ms": r_cv.infer_ms},
        }

        # Проверка видимости стрелки нейросетью (защита от перекрытых/пустых кадров)
        if r_kpt is not None and r_kpt.method != "kpt/unavailable" and r_kpt.visibility < 0.35:
            return DetailedNeedleEstimate(
                method="fusion/rejected", valid=False, reject_reason="neural_not_visible",
                confidence=r_kpt.confidence, visibility=r_kpt.visibility,
                infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
            )

        # Собираем валидных кандидатов с учётом рабочей дуги allowed (если задана)
        def in_allowed(ang: float | None) -> bool:
            if ang is None:
                return False
            if allowed is None:
                return True
            return bool(allowed[int(round(ang)) % 360])

        k_ok = r_kpt is not None and r_kpt.valid and in_allowed(r_kpt.angle_deg)
        s_ok = r_seg is not None and r_seg.valid and in_allowed(r_seg.angle_deg)
        c_ok = r_cv is not None and r_cv.valid and in_allowed(r_cv.angle_deg)

        # Случай 1: kpt + seg согласны (главный нейросетевой консенсус; приоритет у SegUNet!)
        if k_ok and s_ok:
            d_ks = ang_diff(r_kpt.angle_deg, r_seg.angle_deg)
            diag["diff_kpt_seg_deg"] = round(d_ks, 2)
            if d_ks <= self.max_disagree_deg:
                angles = [r_seg.angle_deg, r_kpt.angle_deg]
                weights = [0.75 * max(r_seg.confidence, 0.15), 0.25 * max(r_kpt.confidence, 0.10)]
                tag = "fusion/seg+kpt"
                if c_ok and ang_diff(r_cv.angle_deg, r_seg.angle_deg) <= self.max_disagree_deg:
                    angles.append(r_cv.angle_deg)
                    weights.append(0.30 * max(r_cv.confidence, 0.10))
                    tag = "fusion/seg+kpt+cv"
                ang = circular_weighted_mean(angles, weights)
                conf = min(1.0, 0.55 * r_seg.confidence + 0.30 * r_kpt.confidence + 0.18)
                return DetailedNeedleEstimate(
                    angle_deg=round(ang, 2), center_px=r_seg.center_px, tip_px=r_seg.tip_px or r_kpt.tip_px,
                    confidence=round(conf, 4), visibility=r_kpt.visibility, method=tag, valid=True,
                    infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                )
            # kpt и seg разошлись: проверяем, кого поддерживает OpenCV v2 (голосование 2 из 3!)
            if c_ok:
                d_kc = ang_diff(r_kpt.angle_deg, r_cv.angle_deg)
                d_sc = ang_diff(r_seg.angle_deg, r_cv.angle_deg)
                diag["diff_kpt_cv_deg"] = round(d_kc, 2)
                diag["diff_seg_cv_deg"] = round(d_sc, 2)
                if d_sc <= self.max_disagree_deg and d_sc <= d_kc:
                    ang = circular_weighted_mean([r_seg.angle_deg, r_cv.angle_deg], [0.70, 0.30])
                    return DetailedNeedleEstimate(
                        angle_deg=round(ang, 2), center_px=r_seg.center_px, tip_px=r_seg.tip_px,
                        confidence=round(min(1.0, 0.7 * r_seg.confidence + 0.3 * r_cv.confidence), 4),
                        visibility=r_kpt.visibility, method="fusion/seg+cv_tiebreak", valid=True,
                        infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                    )
                if d_kc <= self.max_disagree_deg and d_kc < d_sc:
                    ang = circular_weighted_mean([r_kpt.angle_deg, r_cv.angle_deg], [0.65, 0.35])
                    return DetailedNeedleEstimate(
                        angle_deg=round(ang, 2), center_px=r_kpt.center_px, tip_px=r_kpt.tip_px,
                        confidence=round(min(1.0, 0.65 * r_kpt.confidence + 0.35 * r_cv.confidence), 4),
                        visibility=r_kpt.visibility, method="fusion/kpt+cv_tiebreak", valid=True,
                        infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                    )
            # Никто не согласен: доверяем только исключительно уверенной пиксельной сегментации
            if r_seg.confidence >= 0.78 and float(r_seg.diagnostics.get("elongation", 0.0)) >= 0.86:
                return DetailedNeedleEstimate(
                    angle_deg=r_seg.angle_deg, center_px=r_seg.center_px, tip_px=r_seg.tip_px,
                    confidence=round(r_seg.confidence * 0.85, 4), visibility=r_kpt.visibility,
                    method="fusion/seg_high_conf", valid=True,
                    infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                )
            return DetailedNeedleEstimate(
                method="fusion/disagreement", valid=False, reject_reason="fusion_angle_disagreement",
                confidence=round(min(r_kpt.confidence, r_seg.confidence) * 0.5, 4),
                visibility=r_kpt.visibility, infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
            )

        # Случай 2: режим balanced (только kpt + opencv_v2) или seg не сработала
        if k_ok:
            if c_ok:
                d_kc = ang_diff(r_kpt.angle_deg, r_cv.angle_deg)
                diag["diff_kpt_cv_deg"] = round(d_kc, 2)
                if d_kc <= self.max_disagree_deg:
                    ang = circular_weighted_mean([r_kpt.angle_deg, r_cv.angle_deg], [0.7, 0.3])
                    conf = min(1.0, 0.65 * r_kpt.confidence + 0.35 * r_cv.confidence + 0.1)
                    return DetailedNeedleEstimate(
                        angle_deg=round(ang, 2), center_px=r_kpt.center_px, tip_px=r_kpt.tip_px,
                        confidence=round(conf, 4), visibility=r_kpt.visibility, method="fusion/kpt+cv", valid=True,
                        infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                    )
            # Если OpenCV не подтвердил (например, блик M1!), доверяем уверенной нейросети
            if r_kpt.confidence >= self.min_neural_conf and r_kpt.diagnostics.get("internal_diff_deg", 99.0) <= 15.0:
                return DetailedNeedleEstimate(
                    angle_deg=r_kpt.angle_deg, center_px=r_kpt.center_px, tip_px=r_kpt.tip_px,
                    confidence=round(r_kpt.confidence * 0.9, 4), visibility=r_kpt.visibility,
                    method="fusion/kpt_only", valid=True,
                    infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                )
            return DetailedNeedleEstimate(
                method="fusion/low_conf", valid=False, reject_reason="fusion_low_confidence",
                confidence=r_kpt.confidence, visibility=r_kpt.visibility,
                infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
            )

        # Случай 3: только seg + cv
        if s_ok:
            if c_ok and ang_diff(r_seg.angle_deg, r_cv.angle_deg) <= self.max_disagree_deg:
                ang = circular_weighted_mean([r_seg.angle_deg, r_cv.angle_deg], [0.65, 0.35])
                return DetailedNeedleEstimate(
                    angle_deg=round(ang, 2), center_px=r_seg.center_px, tip_px=r_seg.tip_px,
                    confidence=round(min(1.0, 0.6 * r_seg.confidence + 0.4 * r_cv.confidence), 4),
                    method="fusion/seg+cv", valid=True,
                    infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                )
            if r_seg.confidence >= 0.45:
                return DetailedNeedleEstimate(
                    angle_deg=r_seg.angle_deg, center_px=r_seg.center_px, tip_px=r_seg.tip_px,
                    confidence=round(r_seg.confidence * 0.85, 4), method="fusion/seg_only", valid=True,
                    infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
                )

        # Случай 4: резервный OpenCV v2 (только если нейросети не загружены!)
        if c_ok and (r_kpt is None or r_kpt.method == "kpt/unavailable"):
            r_cv.diagnostics["fallback_reason"] = r_kpt.reject_reason if r_kpt else "neural_disabled"
            return r_cv

        return DetailedNeedleEstimate(
            method="fusion/none", valid=False, reject_reason="no_valid_needle",
            infer_ms=round((time.perf_counter() - t0) * 1000.0, 2), diagnostics=diag,
        )
