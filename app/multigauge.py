"""
GaugeVision AI — Multi-Gauge Vision: несколько приборов в кадре одного видеоисточника.

  • detect_dials_multi — все циферблаты кадра за один проход YOLO; каждая рамка уточняется
    контурным эллипсом внутри неё, контурные кандидаты вне рамок добавляются отдельно;
  • InstrumentTracker — сопоставляет найденные циферблаты с зарегистрированными приборами по
    якорным ROI (SHARED_DATA_CONTRACT § 1.1). Приборы на щите неподвижны относительно друг друга,
    поэтому общий сдвиг камеры оценивается по медиане смещений всех сопоставленных приборов;
    неоднозначное сопоставление не разрешается догадкой — прибор получает состояние ambiguous;
  • MultiGaugeProcessor — один кадр источника → отсчёты всех его приборов. Детектор запускается
    один раз на кадр (и не на каждом кадре), ROI приборов обрабатываются параллельно, у каждого
    прибора свой GaugePipeline: своя EMA, калибровка, уставки и уровень.

Координаты якорей — доли кадра: cx, cy — от ширины и высоты, r и axes — от меньшей стороны.
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from . import config, vision
from .vision import DialROI, GaugePipeline, GaugeReading

TRACK_STATES = ("locked", "reacquired", "coasting", "predicted", "ambiguous", "lost", "manual", "init")
# состояния, в которых ROI прибора подтверждён текущим или недавним кадром
_CONFIRMED = ("locked", "reacquired", "manual")

_POOL = ThreadPoolExecutor(max_workers=config.MG_WORKERS, thread_name_prefix="mg-roi")


# ---------------------------------------------------------------------------
# Детекция всех циферблатов кадра
# ---------------------------------------------------------------------------
def _radius(roi: DialROI) -> float:
    return float(math.sqrt(roi.axes[0] * roi.axes[1]))


def _refine_in_box(frame_bgr: np.ndarray, box: tuple[int, int, int, int]) -> DialROI:
    """Эллипс циферблата внутри рамки YOLO; без подтверждения — эллипс, вписанный в рамку."""
    x, y, w, h = box
    hh, ww = frame_bgr.shape[:2]
    pad = 0.12 * max(w, h)
    x0, y0 = max(0, int(x - pad)), max(0, int(y - pad))
    x1, y1 = min(ww, int(x + w + pad)), min(hh, int(y + h + pad))
    crop = frame_bgr[y0:y1, x0:x1]
    if crop.size and min(crop.shape[:2]) >= 40:
        cv_roi = vision._find_dial_opencv(crop)
        if cv_roi is not None:
            gx, gy = cv_roi.center[0] + x0, cv_roi.center[1] + y0
            major = max(cv_roi.axes)
            if x <= gx <= x + w and y <= gy <= y + h and 0.30 * max(w, h) <= major <= 0.75 * max(w, h):
                return vision.roi_from_ellipse(gx, gy, cv_roi.axes[0], cv_roi.axes[1], cv_roi.angle_deg,
                                               score=0.97, source="yolo+ellipse")
    return vision.roi_from_ellipse(x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0, 0.0, score=0.9, source="yolo")


def _overlaps(cx: float, cy: float, r: float, roi: DialROI) -> bool:
    return math.hypot(cx - roi.center[0], cy - roi.center[1]) < 0.8 * max(r, _radius(roi))


def detect_dials_multi(frame_bgr: np.ndarray) -> tuple[list[DialROI], dict[str, Any]]:
    """Все циферблаты кадра: [DialROI] по убыванию размера и сведения о проходе детектора."""
    t0 = time.perf_counter()
    boxes = vision.yolo_gauge_boxes(frame_bgr)
    found: list[DialROI] = []
    refined = []
    for x, y, w, h, conf in boxes or []:
        roi = _refine_in_box(frame_bgr, (x, y, w, h))
        roi.score = round(min(roi.score, 0.5 + 0.5 * conf), 3)
        refined.append((roi.source != "yolo", conf, roi, (x, y, w, h)))
    # Сначала рамки, подтверждённые эллипсом. Неподтверждённая рамка на плотном щите часто
    # охватывает два соседних прибора — она принимается, только если внутри нет подтверждённого.
    refined.sort(key=lambda t: (t[0], t[1]), reverse=True)
    for confirmed, _, roi, (x, y, w, h) in refined:
        cx, cy = roi.center
        if any(_overlaps(cx, cy, _radius(roi), r) for r in found):
            continue  # уточнение двух рамок сошлось к одному циферблату
        if not confirmed and any(x <= f.center[0] <= x + w and y <= f.center[1] <= y + h for f in found):
            continue
        found.append(roi)
    n_yolo = len(found)
    # контурные кандидаты вне рамок: приборы, пропущенные YOLO, или единственный путь без YOLO
    for ex, ey, a, b, ang, sc in vision._ellipse_candidates(vision._prep_gray(frame_bgr),
                                                            config.MG_MIN_ELLIPSE_AREA_FRAC):
        r = math.sqrt(a * b)
        if any(_overlaps(ex, ey, r, f) for f in found):
            continue
        found.append(vision.roi_from_ellipse(ex, ey, a, b, ang, score=round(min(0.85, 0.5 + 10 * sc), 3),
                                             source="ellipse"))
    found.sort(key=_radius, reverse=True)
    info = {
        "yolo": boxes is not None, "yolo_boxes": len(boxes or []), "from_yolo": n_yolo,
        "from_ellipse": len(found) - n_yolo, "detect_ms": round((time.perf_counter() - t0) * 1000.0, 1),
    }
    return found, info


def roi_to_anchor(roi: DialROI, frame_shape: tuple[int, ...], mode: str = "auto") -> dict[str, Any]:
    """DialROI в пикселях кадра → якорь прибора в долях кадра (формат instruments.roi)."""
    h, w = frame_shape[:2]
    s = float(min(h, w))
    return {
        "mode": mode,
        "cx": round(roi.center[0] / w, 5), "cy": round(roi.center[1] / h, 5),
        "r": round(_radius(roi) / s, 5),
        "axes": [round(roi.axes[0] / s, 5), round(roi.axes[1] / s, 5)],
        "angle": round(float(roi.angle_deg), 2),
    }


def anchor_to_roi(anchor: dict[str, Any], frame_shape: tuple[int, ...],
                  shift: tuple[float, float] = (0.0, 0.0), source: str = "anchor") -> DialROI | None:
    """Якорь (доли кадра) → DialROI в пикселях, со сдвигом камеры shift (доли меньшей стороны)."""
    try:
        h, w = frame_shape[:2]
        s = float(min(h, w))
        cx = float(anchor["cx"]) * w + shift[0] * s
        cy = float(anchor["cy"]) * h + shift[1] * s
        axes = anchor.get("axes")
        if isinstance(axes, (list, tuple)) and len(axes) == 2:
            a, b = float(axes[0]) * s, float(axes[1]) * s
        else:
            a = b = float(anchor["r"]) * s
        if min(a, b) < 10:
            return None
        return vision.roi_from_ellipse(cx, cy, a, b, float(anchor.get("angle") or 0.0),
                                       score=1.0 if source == "manual" else 0.6, source=source)
    except (KeyError, TypeError, ValueError):
        return None


def _shift_roi(roi: DialROI, dx: float, dy: float, source: str) -> DialROI:
    return vision.roi_from_ellipse(roi.center[0] + dx, roi.center[1] + dy, roi.axes[0], roi.axes[1],
                                   roi.angle_deg, score=roi.score, source=source)


# ---------------------------------------------------------------------------
# Сопоставление «найденный циферблат → прибор»
# ---------------------------------------------------------------------------
@dataclass
class TrackState:
    roi: DialROI | None = None
    state: str = "init"
    misses: int = 0                  # подряд проходов детектора без сопоставления
    center_shift: float | None = None  # смещение от предсказанной позиции, доли радиуса якоря
    radius_ratio: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "state": self.state, "misses": self.misses,
            "center_shift": None if self.center_shift is None else round(self.center_shift, 3),
            "radius_ratio": None if self.radius_ratio is None else round(self.radius_ratio, 3),
        }


class InstrumentTracker:
    """Трекер неподвижных приборов одного источника по якорным ROI."""

    def __init__(self) -> None:
        self.anchors: dict[str, dict[str, Any]] = {}
        self.tracks: dict[str, TrackState] = {}
        self.shift: tuple[float, float] = (0.0, 0.0)  # общий сдвиг камеры, доли меньшей стороны
        self.shift_support: int = 0                    # сколько приборов подтвердили сдвиг

    def set_anchors(self, anchors: dict[str, dict[str, Any]]) -> None:
        for iid in list(self.tracks):
            if iid not in anchors:
                del self.tracks[iid]
        for iid, a in anchors.items():
            if self.anchors.get(iid) != a:
                self.tracks[iid] = TrackState()
        self.anchors = {k: dict(v) for k, v in anchors.items()}

    def apply_motion(self, frame_shape: tuple[int, ...], motion: tuple[float, float]) -> None:
        """Межкадровый сдвиг камеры: смещает ROI всех автоматических приборов и оценку сдвига."""
        s = float(min(frame_shape[:2]))
        dx, dy = motion
        self.shift = (self.shift[0] + dx / s, self.shift[1] + dy / s)
        for iid, tr in self.tracks.items():
            if tr.roi is not None and self.anchors.get(iid, {}).get("mode") != "manual":
                tr.roi = _shift_roi(tr.roi, dx, dy, tr.roi.source)

    def _estimate_shift(self, frame_shape: tuple[int, ...], dets: list[DialROI],
                        auto_ids: list[str]) -> tuple[tuple[float, float], int]:
        """Медиана смещений взаимно ближайших пар «якорь — циферблат» с проверкой согласия."""
        s = float(min(frame_shape[:2]))
        lo, hi = config.MG_RADIUS_RATIO
        preds = {iid: anchor_to_roi(self.anchors[iid], frame_shape, self.shift) for iid in auto_ids}
        preds = {k: v for k, v in preds.items() if v is not None}
        if not preds or not dets:
            return self.shift, 0
        nearest_det: dict[str, tuple[int, float]] = {}
        for iid, p in preds.items():
            near = []
            for j, d in enumerate(dets):
                ratio = _radius(d) / _radius(p)
                dist = math.hypot(d.center[0] - p.center[0], d.center[1] - p.center[1])
                if lo * 0.85 <= ratio <= hi / 0.85 and dist < 2.5 * _radius(p):
                    near.append((dist, j))
            near.sort()
            # два почти равноудалённых кандидата: по этому прибору сдвиг не оценивается
            if near and (len(near) == 1 or near[1][0] - near[0][0] >= config.MG_AMBIGUITY_MARGIN * _radius(p)):
                nearest_det[iid] = (near[0][1], near[0][0])
        vecs = []
        for iid, (j, _) in nearest_det.items():
            d = dets[j]
            back = min(preds, key=lambda k: math.hypot(preds[k].center[0] - d.center[0],
                                                       preds[k].center[1] - d.center[1]))
            if back == iid:  # взаимно ближайшие
                p = preds[iid]
                vecs.append(((d.center[0] - p.center[0]) / s, (d.center[1] - p.center[1]) / s, _radius(p) / s))
        if not vecs:
            return self.shift, 0
        mx = float(np.median([v[0] for v in vecs]))
        my = float(np.median([v[1] for v in vecs]))
        inl = [v for v in vecs if math.hypot(v[0] - mx, v[1] - my) <= 0.25 * v[2]]
        # один прибор не подтверждает сдвиг камеры: перемещение могло быть у самого прибора
        need = 1 if len(auto_ids) == 1 else max(2, math.ceil(0.5 * len(vecs)))
        if len(inl) < need:
            return self.shift, 0
        ix = float(np.median([v[0] for v in inl]))
        iy = float(np.median([v[1] for v in inl]))
        return (self.shift[0] + ix, self.shift[1] + iy), len(inl)

    def update(self, frame_shape: tuple[int, ...], dets: list[DialROI] | None) -> dict[str, TrackState]:
        """dets = None — на этом кадре детектор не запускался: ROI сохраняются без изменений."""
        h, w = frame_shape[:2]
        s = float(min(h, w))
        for iid, a in self.anchors.items():
            if a.get("mode") == "manual":
                tr = self.tracks.setdefault(iid, TrackState())
                tr.roi, tr.state, tr.misses = anchor_to_roi(a, frame_shape, source="manual"), "manual", 0
        auto_ids = [iid for iid, a in self.anchors.items() if a.get("mode") != "manual"]
        if dets is None or not auto_ids:
            return self.tracks
        prev_shift = self.shift
        self.shift, self.shift_support = self._estimate_shift(frame_shape, dets, auto_ids)
        lo, hi = config.MG_RADIUS_RATIO
        cands: list[tuple[float, str, int]] = []
        per_inst: dict[str, list[float]] = {iid: [] for iid in auto_ids}
        preds: dict[str, DialROI] = {}
        for iid in auto_ids:
            p = anchor_to_roi(self.anchors[iid], frame_shape, self.shift)
            if p is None:
                continue
            preds[iid] = p
            pr = _radius(p)
            for j, d in enumerate(dets):
                ratio = _radius(d) / pr
                cost = math.hypot(d.center[0] - p.center[0], d.center[1] - p.center[1]) / pr
                if cost <= config.MG_MATCH_GATE and lo <= ratio <= hi:
                    cost += 0.5 * abs(math.log(ratio))
                    cands.append((cost, iid, j))
                    per_inst[iid].append(cost)
        ambiguous = {iid for iid, cs in per_inst.items()
                     if len(cs) >= 2 and sorted(cs)[1] - sorted(cs)[0] < config.MG_AMBIGUITY_MARGIN}
        # циферблат, подходящий двум приборам одинаково хорошо, тоже неоднозначен
        by_det: dict[int, list[tuple[float, str]]] = {}
        for cost, iid, j in cands:
            by_det.setdefault(j, []).append((cost, iid))
        for lst in by_det.values():
            lst.sort()
            if len(lst) >= 2 and lst[1][0] - lst[0][0] < config.MG_AMBIGUITY_MARGIN:
                ambiguous.update(i for _, i in lst[:2])
        cands.sort()
        used_d: set[int] = set()
        matched: dict[str, tuple[int, float]] = {}
        for cost, iid, j in cands:
            if iid in matched or j in used_d or iid in ambiguous:
                continue
            matched[iid] = (j, cost)
            used_d.add(j)
        dx, dy = (self.shift[0] - prev_shift[0]) * s, (self.shift[1] - prev_shift[1]) * s
        for iid in auto_ids:
            tr = self.tracks.setdefault(iid, TrackState())
            p = preds.get(iid)
            if iid in matched:
                j, cost = matched[iid]
                d = dets[j]
                was = tr.state
                tr.roi = d
                tr.state = "reacquired" if was in ("lost", "predicted", "ambiguous", "coasting") and tr.misses else "locked"
                tr.misses = 0
                tr.center_shift = math.hypot(d.center[0] - p.center[0], d.center[1] - p.center[1]) / _radius(p)
                tr.radius_ratio = _radius(d) / _radius(p)
                continue
            tr.misses += 1
            tr.center_shift = tr.radius_ratio = None
            if iid in ambiguous:
                tr.roi, tr.state = None, "ambiguous"
            elif self.shift_support >= 2 and p is not None:
                # положение подтверждено соседями по щиту: проверка пригодности ROI — в конвейере
                base = tr.roi if tr.roi is not None and tr.misses < config.MG_LOST_AFTER else None
                tr.roi = _shift_roi(base, dx, dy, "predicted") if base is not None else \
                    anchor_to_roi(self.anchors[iid], frame_shape, self.shift, source="predicted")
                tr.state = "predicted"
            elif tr.roi is not None and tr.misses < config.MG_LOST_AFTER:
                tr.state = "coasting"
            else:
                tr.roi, tr.state = None, "lost"
        return self.tracks


# ---------------------------------------------------------------------------
# Обработка кадра источника
# ---------------------------------------------------------------------------
@dataclass
class MultiGaugeResult:
    readings: dict[str, GaugeReading] = field(default_factory=dict)
    tracks: dict[str, dict[str, Any]] = field(default_factory=dict)
    detected: bool = False
    detections: list[dict[str, Any]] = field(default_factory=list)
    detect_info: dict[str, Any] = field(default_factory=dict)
    frame_shape: tuple[int, int] = (0, 0)
    overlay: np.ndarray | None = None
    total_ms: float = 0.0
    camera_shift: tuple[float, float] = (0.0, 0.0)   # общий сдвиг камеры, доли меньшей стороны
    camera_motion_px: tuple[float, float] | None = None  # сдвиг относительно предыдущего кадра


def _track_reading(pipe: GaugePipeline, reason: str, track: TrackState) -> GaugeReading:
    """Отсчёт прибора без ROI: показание не считывается, последнее достоверное значение удерживается."""
    pipe._miss_streak += 1
    ema = pipe.ema.value
    r = GaugeReading(dial_found=False, dial_source="track", ema_value=ema)
    r.status_level = pipe._last_level if ema is not None else "normal"
    r.debug = {"needle_method": None, "invalid_reason": reason, "geom": None, "roi": None,
               "track": track.to_json()}
    return r


class MultiGaugeProcessor:
    """Все приборы одного источника: один детектор на кадр, свой конвейер на каждый прибор."""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self.tracker = InstrumentTracker()
        self.pipelines: dict[str, GaugePipeline] = {}
        self._frames_since_detect = 10 ** 6
        self._lock = threading.Lock()
        self._prev_small: np.ndarray | None = None
        self._window: np.ndarray | None = None

    def _camera_motion(self, frame: np.ndarray) -> tuple[float, float] | None:
        """Сдвиг кадра относительно предыдущего (пиксели), фазовая корреляция по уменьшенной копии.

        Между проходами детектора ROI приборов иначе стоят на месте, пока камера смещается.
        """
        h, w = frame.shape[:2]
        k = 320.0 / w
        small = cv2.cvtColor(cv2.resize(frame, (320, max(8, int(h * k))), interpolation=cv2.INTER_AREA),
                             cv2.COLOR_BGR2GRAY).astype(np.float32)
        prev, self._prev_small = self._prev_small, small
        if prev is None or prev.shape != small.shape:
            return None
        if self._window is None or self._window.shape != small.shape:
            self._window = cv2.createHanningWindow((small.shape[1], small.shape[0]), cv2.CV_32F)
        (dx, dy), response = cv2.phaseCorrelate(prev, small, self._window)
        if response < 0.15 or math.hypot(dx, dy) < 0.3:
            return None
        return dx / k, dy / k

    def configure(self, instruments: list[dict[str, Any]]) -> None:
        with self._lock:
            anchors = {i["id"]: dict(i.get("roi") or {}) for i in instruments if i.get("enabled", True)}
            for iid in list(self.pipelines):
                if iid not in anchors:
                    del self.pipelines[iid]
            for iid in anchors:
                self.pipelines.setdefault(iid, GaugePipeline(iid))
            if anchors != self.tracker.anchors:
                self.tracker.set_anchors(anchors)
                self._frames_since_detect = 10 ** 6

    def request_redetect(self) -> None:
        self._frames_since_detect = 10 ** 6

    def _need_detect(self) -> bool:
        tracks = self.tracker.tracks
        auto = [i for i, a in self.tracker.anchors.items() if a.get("mode") != "manual"]
        if not auto:
            return False
        if any(tracks.get(i) is None or tracks[i].state not in _CONFIRMED for i in auto):
            return self._frames_since_detect >= config.MG_REDETECT_UNLOCKED
        if any(self.pipelines[i]._miss_streak >= 3 for i in auto if i in self.pipelines):
            return self._frames_since_detect >= config.MG_REDETECT_UNLOCKED
        return self._frames_since_detect >= config.REDETECT_EVERY_N_FRAMES

    def process(self, frame_bgr: np.ndarray, instruments: list[dict[str, Any]],
                with_overlay: bool = True) -> MultiGaugeResult:
        t0 = time.perf_counter()
        self.configure(instruments)
        frame = frame_bgr
        h, w = frame.shape[:2]
        if w > config.MAX_PROCESS_WIDTH:
            k = config.MAX_PROCESS_WIDTH / float(w)
            frame = cv2.resize(frame, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        res = MultiGaugeResult(frame_shape=(frame.shape[0], frame.shape[1]))
        with self._lock:
            motion = self._camera_motion(frame)
            if motion is not None:
                self.tracker.apply_motion(frame.shape, motion)
                radii = [_radius(t.roi) for t in self.tracker.tracks.values() if t.roi is not None]
                if radii and math.hypot(*motion) > 0.15 * min(radii):
                    self._frames_since_detect = 10 ** 6   # камера заметно сместилась — переуточнить ROI
            res.camera_motion_px = None if motion is None else (round(motion[0], 2), round(motion[1], 2))
            dets: list[DialROI] | None = None
            if self._need_detect():
                dets, res.detect_info = detect_dials_multi(frame)
                self._frames_since_detect = 0
                res.detected = True
                res.detections = [{**d.to_json(), "anchor": roi_to_anchor(d, frame.shape)} for d in dets]
            else:
                self._frames_since_detect += 1
            tracks = self.tracker.update(frame.shape, dets)
            by_id = {i["id"]: i for i in instruments if i["id"] in self.pipelines}
            jobs = {}
            for iid, inst in by_id.items():
                tr = tracks.get(iid) or TrackState()
                pipe = self.pipelines[iid]
                if tr.roi is None:
                    reason = "track_ambiguous" if tr.state == "ambiguous" else "track_lost"
                    res.readings[iid] = _track_reading(pipe, reason, tr)
                    continue
                jobs[iid] = _POOL.submit(pipe.process, frame, inst.get("calibration") or {},
                                         inst.get("thresholds") or {}, inst.get("unit") or "",
                                         False, tr.roi)
            for iid, fut in jobs.items():
                r = fut.result()
                r.dial_source = f"track/{tracks[iid].roi.source}" if tracks[iid].roi is not None else r.dial_source
                r.debug["track"] = tracks[iid].to_json()
                res.readings[iid] = r
            res.tracks = {iid: tracks[iid].to_json() for iid in by_id if iid in tracks}
            res.camera_shift = self.tracker.shift
        if with_overlay:
            res.overlay = draw_multi_overlay(frame, instruments, res, tracks)
        res.total_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return res


_LEVEL_BGR = {"normal": (80, 200, 80), "warning": (0, 190, 255), "alert": (60, 60, 230)}


def draw_multi_overlay(frame: np.ndarray, instruments: list[dict[str, Any]], res: MultiGaugeResult,
                       tracks: dict[str, TrackState]) -> np.ndarray:
    """Общий кадр источника с разметкой всех приборов: контур, зоны, стрелка, код и значение."""
    out = frame.copy()
    scale = max(0.45, min(out.shape[:2]) / 900.0)
    for inst in instruments:
        iid = inst["id"]
        r = res.readings.get(iid)
        tr = tracks.get(iid)
        if r is None:
            continue
        geom = r.debug.get("geom")
        color = _LEVEL_BGR.get(r.status_level, (180, 180, 180)) if r.valid else (150, 150, 150)
        if geom:
            for z in geom.get("zones") or []:
                pts = np.array(z["points"], dtype=np.int32)
                cv2.polylines(out, [pts], False, _LEVEL_BGR.get(z["level"], (80, 200, 80)), 2, cv2.LINE_AA)
            ex, ey, a, b, ang = geom["ellipse"]
            cv2.ellipse(out, (int(ex), int(ey)), (int(a), int(b)), ang, 0, 360, color, 2, cv2.LINE_AA)
            if geom.get("needle") and r.valid:
                (x0, y0), (x1, y1) = geom["needle"]
                cv2.arrowedLine(out, (int(x0), int(y0)), (int(x1), int(y1)), color, max(2, int(3 * scale)),
                                cv2.LINE_AA, tipLength=0.12)
            bx, by = int(geom["bbox"][0]), int(geom["bbox"][1])
        elif tr is not None and inst.get("roi"):
            p = anchor_to_roi(inst["roi"], out.shape, res.camera_shift)
            if p is None:
                continue
            cv2.ellipse(out, (int(p.center[0]), int(p.center[1])), (int(p.axes[0]), int(p.axes[1])),
                        p.angle_deg, 0, 360, (150, 150, 150), 1, cv2.LINE_AA)
            bx, by = int(p.center[0] - p.axes[0]), int(p.center[1] - p.axes[1])
        else:
            continue
        code = str(inst.get("code") or inst.get("name") or iid)[:12]
        code = code.encode("ascii", "ignore").decode() or iid[:6]
        val = f"{r.ema_value:.2f}" if (r.valid and r.ema_value is not None) else (tr.state.upper() if tr else "--")
        label = f"{code} {val}"
        fs, th = 0.55 * scale * 1.6, max(1, int(2 * scale))
        (tw, tht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        y_top = max(0, by - tht - 10)
        cv2.rectangle(out, (bx, y_top), (bx + tw + 10, y_top + tht + 10), (20, 20, 20), -1)
        cv2.putText(out, label, (bx + 5, y_top + tht + 4), cv2.FONT_HERSHEY_SIMPLEX, fs, color, th, cv2.LINE_AA)
    return out


# ---------------------------------------------------------------------------
# Регистрация приборов: защита от дубликатов
# ---------------------------------------------------------------------------
def anchor_overlap(a: dict[str, Any], b: dict[str, Any], frame_shape: tuple[int, ...]) -> float:
    """Смещение центров двух якорей в долях большего радиуса (меньше MG_REGISTER_OVERLAP — один прибор)."""
    ra = anchor_to_roi(a, frame_shape)
    rb = anchor_to_roi(b, frame_shape)
    if ra is None or rb is None:
        return float("inf")
    return math.hypot(ra.center[0] - rb.center[0], ra.center[1] - rb.center[1]) / max(_radius(ra), _radius(rb))


def match_candidates(candidates: list[dict[str, Any]], instruments: list[dict[str, Any]],
                     frame_shape: tuple[int, ...]) -> list[dict[str, Any]]:
    """Кандидаты детектора с пометкой, каким зарегистрированным прибором они уже являются."""
    out = []
    for c in candidates:
        anchor = c["anchor"]
        best_id, best = None, float("inf")
        for inst in instruments:
            if not inst.get("roi"):
                continue
            d = anchor_overlap(anchor, inst["roi"], frame_shape)
            if d < best:
                best_id, best = inst["id"], d
        out.append({**c, "registered_instrument_id": best_id if best < config.MG_REGISTER_OVERLAP else None})
    return out
