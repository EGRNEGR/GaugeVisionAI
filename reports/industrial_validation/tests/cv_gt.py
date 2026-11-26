"""
Эталонная разметка для валидации CV-конвейера GaugeVision AI на реальных фотографиях (REQ-CV-05).

Источники:
  • MeterFL (CC BY-SA 4.0, github.com/weidazhaoooo/Meter-FL): LabelMe-полигоны делений (`ticks`)
    и стрелки (`pointer`), растровые маски, человеческие показания для тестовой части;
  • MeasureBench (CC BY-SA 4.0, huggingface.co/datasets/FlagEval/MeasureBench): интервальные
    человеческие показания (`interval_matching`).

Калибровка строится только по геометрии шкалы — так её задаёт инженер при пусконаладке:
первое и последнее деление шкалы (центры полигонов делений) и значения начала и конца шкалы.
Положение стрелки и эталонное показание в калибровку не входят.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

UNIT_NORMALIZE = {
    "megapascals": "МПа", "megapascal": "МПа", "mpa": "МПа",
    "kilopascals": "кПа", "kilopascal": "кПа", "kpa": "кПа",
    "pounds per square inch": "psi", "psi": "psi",
    "kilogram-force per square centimeter": "кгс/см²",
    "amperes": "А", "ampere": "А", "a": "А", "milliampere": "мА", "microamperes": "мкА",
    "millivolt": "мВ", "v": "В", "volt": "В", "volts": "В",
    "mmhg": "мм рт. ст.", "inh2o": "дюйм вод. ст.", "x1000 rpm": "×1000 об/мин", "bar": "бар",
}


def norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    k = u.strip().lower()
    return UNIT_NORMALIZE.get(k, u.strip())


@dataclass
class GaugeGT:
    """Эталон одного снимка в координатах исходного изображения."""
    dataset: str
    file: str
    path: Path
    width: int
    height: int
    client: str | None = None
    side: str | None = None                 # train/test (исходное разбиение датасета)
    source: str | None = None
    series: str | None = None               # серия имён файлов (признак съёмочной сессии)
    tick_centroids: list[tuple[float, float]] = field(default_factory=list)
    pointer_pts: list[tuple[float, float]] = field(default_factory=list)
    center: tuple[float, float] | None = None
    tick_radius: float | None = None
    first_tick: tuple[float, float] | None = None
    last_tick: tuple[float, float] | None = None
    span_deg: float | None = None           # угловой размах шкалы по часовой стрелке (ось Y вниз)
    pointer_tip: tuple[float, float] | None = None
    frac_lin: float | None = None           # доля шкалы по углу стрелки из полигона (линейная шкала)
    frac_decoder: float | None = None       # доля шкалы декодером делений MeterFL (по маскам)
    scale_min: float | None = None
    scale_max: float | None = None
    reading_gt: float | None = None         # человеческое показание (MeterFL test)
    interval: tuple[float, float] | None = None   # интервальный эталон MeasureBench
    unit: str | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def has_scale(self) -> bool:
        return self.scale_min is not None and self.scale_max is not None and self.scale_max != self.scale_min

    @property
    def frac_human(self) -> float | None:
        if self.reading_gt is None or not self.has_scale:
            return None
        return (self.reading_gt - self.scale_min) / (self.scale_max - self.scale_min)

    def to_json(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in (
            "dataset", "file", "width", "height", "client", "side", "source", "series", "center", "tick_radius",
            "first_tick", "last_tick", "span_deg", "pointer_tip", "frac_lin", "frac_decoder", "scale_min",
            "scale_max", "reading_gt", "interval", "unit", "flags")}
        d["n_ticks"] = len(self.tick_centroids)
        d["frac_human"] = self.frac_human
        return d


def series_of(name: str) -> str:
    s = re.sub(r"\.(jpg|jpeg|png)$", "", name, flags=re.I)
    s = re.sub(r"\d{8,}", "#", s)
    return re.sub(r"\d+$", "#", s)


def _ang(p: tuple[float, float], c: tuple[float, float]) -> float:
    return math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360.0


def fit_center(points: list[tuple[float, float]]) -> tuple[tuple[float, float], float] | None:
    """Центр шкалы: эллипс по центрам делений (перспектива), иначе алгебраическая окружность."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 3:
        return None
    if len(pts) >= 6:
        try:
            (cx, cy), (w, h), _ = cv2.fitEllipse(pts.astype(np.float32))
            if min(w, h) > 0 and min(w, h) / max(w, h) > 0.35:
                r = float(np.mean(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)))
                return (float(cx), float(cy)), r
        except cv2.error:
            pass
    x, y = pts[:, 0], pts[:, 1]
    a = np.column_stack([x, y, np.ones_like(x)])
    b = -(x ** 2 + y ** 2)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cy = -sol[0] / 2.0, -sol[1] / 2.0
    r2 = cx ** 2 + cy ** 2 - sol[2]
    if r2 <= 0:
        return None
    return (float(cx), float(cy)), float(math.sqrt(r2))


def scale_endpoints(ticks: list[tuple[float, float]], center: tuple[float, float]):
    """Первое и последнее деление: дуга шкалы обходится по часовой стрелке от самого большого разрыва."""
    angs = sorted((_ang(p, center), p) for p in ticks)
    if len(angs) < 3:
        return None
    vals = [a for a, _ in angs]
    gaps = [((vals[(i + 1) % len(vals)] - vals[i]) % 360.0, i) for i in range(len(vals))]
    gap, i = max(gaps)
    first = angs[(i + 1) % len(angs)]
    last = angs[i]
    span = (last[0] - first[0]) % 360.0
    return first[1], last[1], span, gap


def _polygon_points(shape: dict[str, Any]) -> list[tuple[float, float]]:
    pts = [(float(x), float(y)) for x, y in shape.get("points", [])]
    if shape.get("shape_type") == "rectangle" and len(pts) == 2:
        (x0, y0), (x1, y1) = pts
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return pts


def _centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    a = np.asarray(pts, dtype=np.float64)
    return float(a[:, 0].mean()), float(a[:, 1].mean())


# ---------------------------------------------------------------------------
# Декодер делений MeterFL (переписан по tools/tick_reading.py, CC BY-SA 4.0 / код MIT):
# доля шкалы = номер деления под стрелкой / (число делений − 1) по растровой маске.
# ---------------------------------------------------------------------------
def _runs(binary: np.ndarray) -> list[tuple[int, int, float]]:
    delta = np.diff(np.concatenate([[0], binary, [0]]))
    starts = np.where(delta == 1)[0]
    ends = np.where(delta == -1)[0] - 1
    return [(int(s), int(e), (s + e) / 2.0) for s, e in zip(starts, ends)]


def decode_mask(mask: np.ndarray, min_ticks: int = 5) -> float | None:
    tick_ys, tick_xs = np.where(mask == 1)
    if len(tick_xs) < 20 or not (mask == 2).any():
        return None
    cx, cy = tick_xs.mean(), tick_ys.mean()
    outer = np.percentile(np.hypot(tick_xs - cx, tick_ys - cy), 98) * 1.15
    theta = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    radius = np.linspace(outer, outer * 0.15, 96)
    xs = np.clip((cx + np.outer(radius, np.cos(theta)) + 0.5).astype(int), 0, mask.shape[1] - 1)
    ys = np.clip((cy + np.outer(radius, np.sin(theta)) + 0.5).astype(int), 0, mask.shape[0] - 1)
    polar = mask[ys, xs]
    tick_line = (polar == 1).sum(0).astype(float)
    ptr_line = (polar == 2).sum(0).astype(float)
    tick_b = (tick_line > tick_line.mean()).astype(int)
    ptr_b = (ptr_line > ptr_line.mean()).astype(int)
    if not np.where(tick_b == 0)[0].size:
        return None
    gaps = _runs(1 - tick_b)
    largest = max(gaps, key=lambda r: r[1] - r[0])
    shift = -(largest[1] + 1) % 720
    tick_b, ptr_b = np.roll(tick_b, shift), np.roll(ptr_b, shift)
    ticks = [r[2] for r in _runs(tick_b)]
    if len(ticks) < min_ticks:
        return None
    pruns = _runs(ptr_b)
    if not pruns:
        return None
    p = max(pruns, key=lambda r: r[1] - r[0])[2]
    if p < ticks[0]:
        pointed = 0.0
    elif p >= ticks[-1]:
        pointed = float(len(ticks) - 1)
    else:
        i = int(np.searchsorted(ticks, p)) - 1
        pointed = i + (p - ticks[i]) / (ticks[i + 1] - ticks[i] + 1e-9)
    return pointed / (len(ticks) - 1)


def ellipse_to_circle(points: list[tuple[float, float]]) -> np.ndarray | None:
    """
    Аффинное приведение эллипса делений к окружности (снимок под углом): 2×3-матрица
    M = R(φ)·diag(1/a, 1/b)·R(−φ)·T(−c). Независимая от кода конвейера реализация.
    """
    pts = np.asarray(points, dtype=np.float32)
    if len(pts) < 6:
        return None
    try:
        (cx, cy), (w, h), ang = cv2.fitEllipse(pts)
    except cv2.error:
        return None
    a, b = w / 2.0, h / 2.0
    if min(a, b) <= 0 or min(a, b) / max(a, b) < 0.35:
        return None
    phi = math.radians(ang)
    c, s = math.cos(phi), math.sin(phi)
    rot_f = np.array([[c, -s], [s, c]])
    rot_b = np.array([[c, s], [-s, c]])
    lin = rot_f @ np.diag([1.0 / a, 1.0 / b]) @ rot_b
    off = -lin @ np.array([cx, cy])
    return np.hstack([lin, off.reshape(2, 1)])


def _apply(m: np.ndarray, p: tuple[float, float]) -> tuple[float, float]:
    q = m @ np.array([p[0], p[1], 1.0])
    return float(q[0]), float(q[1])


def complete_geometry(g: GaugeGT) -> GaugeGT:
    """
    Центр, первое/последнее деление, остриё стрелки и доля шкалы по полигону стрелки.
    Доля считается в кадре, где эллипс делений приведён к окружности (без перспективного
    искажения углов), при линейной шкале — геометрический эталон положения стрелки.
    """
    if len(g.tick_centroids) < 5:
        g.flags.append("too_few_ticks")
        return g
    fc = fit_center(g.tick_centroids)
    if fc is None:
        g.flags.append("center_fit_failed")
        return g
    g.center, g.tick_radius = fc
    m = ellipse_to_circle(g.tick_centroids)
    if m is not None:
        norm_ticks = [_apply(m, p) for p in g.tick_centroids]
        c0 = (0.0, 0.0)
    else:
        norm_ticks, c0 = list(g.tick_centroids), g.center
    ep = scale_endpoints(norm_ticks, c0)
    if ep is None:
        g.flags.append("endpoints_failed")
        return g
    nf, nl, g.span_deg, _gap = ep
    idx = {id(p): i for i, p in enumerate(norm_ticks)}
    g.first_tick = g.tick_centroids[idx[id(nf)]]
    g.last_tick = g.tick_centroids[idx[id(nl)]]
    if g.span_deg < 60.0:
        g.flags.append("short_arc")
    if g.pointer_pts:
        norm_ptr = [_apply(m, p) for p in g.pointer_pts] if m is not None else list(g.pointer_pts)
        k = max(range(len(norm_ptr)), key=lambda i: math.hypot(norm_ptr[i][0] - c0[0], norm_ptr[i][1] - c0[1]))
        g.pointer_tip = g.pointer_pts[k]
        d = (_ang(norm_ptr[k], c0) - _ang(nf, c0)) % 360.0
        if d > g.span_deg:   # в мёртвой зоне: ближе к какому краю
            d = d if (d - g.span_deg) < (360.0 - d) else d - 360.0
        g.frac_lin = d / g.span_deg if g.span_deg else None
    else:
        g.flags.append("no_pointer")
    return g


def load_meterfl(root: Path) -> list[GaugeGT]:
    """Все снимки MeterFL с LabelMe-разметкой; human GT — для тестовой части (readings/)."""
    data = root / "data"
    sources = {}
    src_csv = data / "metadata" / "sources.csv"
    for line in src_csv.read_text(encoding="utf-8").splitlines()[1:]:
        f, client, side, src = line.split(",")[:4]
        sources[f] = (client, side, src)
    out: list[GaugeGT] = []
    for js in sorted(data.glob("*/*/*.json")):
        if js.parent.parent.name in ("metadata", "readings", "masks"):
            continue
        ann = json.loads(js.read_text(encoding="utf-8"))
        img = js.with_name(ann.get("imagePath") or js.stem)
        if not img.is_file():
            cands = [p for p in js.parent.glob(js.stem + ".*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
            if not cands:
                continue
            img = cands[0]
        client, side, src = sources.get(img.name, (js.parent.parent.name, js.parent.name, None))
        g = GaugeGT(dataset="MeterFL", file=img.name, path=img, width=int(ann["imageWidth"]),
                    height=int(ann["imageHeight"]), client=client, side=side, source=src, series=series_of(img.name))
        for sh in ann.get("shapes", []):
            lab = str(sh.get("label", "")).lower()
            pts = _polygon_points(sh)
            if not pts:
                continue
            if lab in ("tick", "ticks"):
                g.tick_centroids.append(_centroid(pts))
            elif lab == "pointer":
                g.pointer_pts.extend(pts)
        mpath = data / "masks" / (img.stem + ".png")
        if mpath.is_file():
            m = cv2.imread(str(mpath), cv2.IMREAD_GRAYSCALE)
            if m is not None:
                g.frac_decoder = decode_mask(m)
        rpath = data / "readings" / (img.stem + ".json")
        if rpath.is_file():
            r = json.loads(rpath.read_text(encoding="utf-8"))
            g.scale_min, g.scale_max = r.get("scale_min"), r.get("scale_max")
            g.reading_gt = r.get("reading_gt")
            g.unit = norm_unit(r.get("unit"))
            if r.get("seg_anomaly"):
                g.flags.append("seg_anomaly")
            if r.get("annot_issue"):
                g.flags.append("annot_issue")
        out.append(complete_geometry(g))
    return out


def load_measurebench(export_dir: Path) -> dict[str, dict[str, Any]]:
    """Манифест выгрузки MeasureBench real_world (scripts/mb_export.py) по question_id."""
    out = {}
    for line in (export_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        kw = json.loads(r["evaluator_kwargs"]) if r.get("evaluator_kwargs") else {}
        r["kw"] = kw
        out[r["question_id"]] = r
    return out


def dhash(img_bgr: np.ndarray, size: int = 8) -> int:
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
