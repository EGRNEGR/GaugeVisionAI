"""
Auto Calibration (NG-AC-01, экспериментальный модуль): предложение калибровки шкалы по кадру.

Протокол испытаний и критерии допуска — reports/next_generation/AUTO_CALIBRATION_PROTOCOL.md,
результаты — AUTO_CALIBRATION_REPORT.md. Критерии допуска не выполнены, поэтому модуль в продукт не
подключён (ни API, ни интерфейс его не вызывают) и остаётся исследовательским; флаг
GAUGEVISION_AUTOCAL по умолчанию выключен. Модуль ничего не применяет сам: он возвращает предложение
{v_min, theta_min, v_max, theta_max, direction} с обоснованием или отказ с причиной. Поле confidence —
эвристическая оценка, а не вероятность правильности. OCR (rapidocr-onnxruntime) — необязательная
зависимость: без неё модуль отвечает отказом.

Ступени (всё локально, CPU):
  1. «широкий» нормализованный циферблат — та же ROI, но до 1,2 её радиуса, чтобы риски у края
     не обрезались; система углов та же, что у vision.angle_to_value (0° — «на 3 часа», по часовой);
  2. подписи шкалы — локальное OCR (RapidOCR, ONNX Runtime): числа в кольце 0,35–1,15 радиуса ROI,
     угол центра подписи относительно оси;
  3. риски — полярная развёртка с шагом 0,25°, тонкие радиальные штрихи выделяются морфологическим
     black-hat (тёмные риски) или top-hat (светлые) поперёк радиуса; кольцо рисок (0,7–1,15 радиуса
     ROI) — радиальное окно, где пики углового профиля образуют самую длинную регулярную цепочку;
  4. решётка рисок: индексы рисок и модель θ = θ0 + s·i + A·sin θ + B·cos θ (эксцентриситет ROI);
  5. робастная линейная аппроксимация «угол → значение» по подписям (RANSAC по парам и по разрезам
     окружности); подписи переносятся на решётку — шаг подписей равен целому числу рисок;
  6. концы шкалы — концы решётки, округлённые к сетке подписей; углы — по рискам решётки;
  7. отказ: мало согласованных подписей, неоднозначная аппроксимация, нерегулярные риски, подписи не
     легли на решётку.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from . import config, vision

log = logging.getLogger("gaugevision.autocal")

WIDE = 1.2                     # «широкий» циферблат: радиус ROI → size / 2 / WIDE
LABEL_RHO = (0.35, 1.15)       # кольцо подписей, доли радиуса ROI
LABEL_MIN_SCORE = 0.6          # уверенность OCR
FIT_TOL_DEG = 7.0              # допуск подписи относительно прямой (положение подписи неточно)
LATTICE_MAX_RMS_DEG = 0.8      # разброс рисок относительно решётки с эксцентриситетом
LABEL_TICK_TOL = 1.5           # подпись дальше этого числа рисок от своей риски решётки — не согласована
END_TICK_TOL = 2.0             # конец решётки дальше от значения сетки подписей — конец внутри
MIN_INLIERS = 3
MIN_LABEL_SPAN_DEG = 60.0
MIN_SNAPPED_FRAC = 0.75        # доля согласованных подписей, легших на решётку рисок
ANG_STEP = 0.25                # шаг полярной развёртки, градусы

_NUM_RE = re.compile(r"^[-−]?\d+(?:[.,]\d+)?$")


@dataclass
class Label:
    text: str
    value: float
    angle: float          # градусы, система vision
    rho: float            # доли радиуса ROI
    score: float
    xy: tuple[int, int]   # центр на «широком» циферблате


@dataclass
class Proposal:
    ok: bool
    calibration: dict[str, Any] | None = None
    confidence: float = 0.0
    reason: str | None = None
    labels: list[Label] = field(default_factory=list)
    inliers: list[int] = field(default_factory=list)
    ticks: list[float] = field(default_factory=list)
    ms: float = 0.0
    debug: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "calibration": self.calibration, "confidence": round(self.confidence, 3),
            "reason": self.reason, "ms": round(self.ms, 1),
            "ticks": [round(a, 2) for a in self.ticks],
            "labels": [{"text": lb.text, "value": lb.value, "angle": round(lb.angle, 1), "rho": round(lb.rho, 3),
                        "score": round(lb.score, 2), "inlier": i in self.inliers}
                       for i, lb in enumerate(self.labels)],
            "debug": self.debug,
        }


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
_ocr = None
_ocr_lock = threading.Lock()
_ocr_error: str | None = None


def _engine():
    global _ocr, _ocr_error
    if _ocr is not None or _ocr_error is not None:
        return _ocr
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR(det_limit_side_len=480, intra_op_num_threads=config.AUTOCAL_OCR_THREADS,
                        inter_op_num_threads=1)
    except Exception as exc:  # noqa: BLE001 — модуль необязательный, без OCR работает отказом
        _ocr_error = f"{type(exc).__name__}: {exc}"
        log.warning("Auto Calibration: OCR недоступно (%s)", _ocr_error)
    return _ocr


def available() -> bool:
    return _engine() is not None


def parse_number(text: str) -> float | None:
    t = text.strip().replace(" ", "").replace("−", "-").replace(",", ".")
    if not _NUM_RE.match(t) or sum(ch.isdigit() for ch in t) > 5:   # заводские и серийные номера
        return None
    # «02», «025» — OCR потеряло десятичную точку у подписи вида 0.2 / 0.25
    if len(t) >= 2 and t[0] == "0" and t[1].isdigit():
        t = "0." + t[1:]
    try:
        return float(t)
    except ValueError:
        return None


def read_labels(wide_bgr: np.ndarray) -> list[Label]:
    eng = _engine()
    if eng is None:
        return []
    with _ocr_lock:
        res, _ = eng(wide_bgr, use_cls=False)
    c = wide_bgr.shape[1] / 2.0
    r_roi = c / WIDE
    out: list[Label] = []
    for box, text, score in res or []:
        if float(score) < LABEL_MIN_SCORE:
            continue
        v = parse_number(str(text))
        if v is None:
            continue
        x = float(np.mean([p[0] for p in box]))
        y = float(np.mean([p[1] for p in box]))
        rho = math.hypot(x - c, y - c) / r_roi
        if not LABEL_RHO[0] <= rho <= LABEL_RHO[1]:
            continue
        out.append(Label(str(text), v, math.degrees(math.atan2(y - c, x - c)) % 360.0, rho, float(score),
                         (int(round(x)), int(round(y)))))
    return out


# ---------------------------------------------------------------------------
# Риски шкалы
# ---------------------------------------------------------------------------
def wide_dial(frame_bgr: np.ndarray, roi: vision.DialROI) -> np.ndarray:
    """Нормализованный циферблат с полем до WIDE радиусов ROI (масштаб относительно центра)."""
    size = config.DIAL_SIZE
    c = size / 2.0
    k = 1.0 / WIDE
    m = roi.matrix.copy()
    m[:, :2] *= k
    m[:, 2] = k * (m[:, 2] - c) + c
    return cv2.warpAffine(frame_bgr, m, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def tick_evidence(wide_bgr: np.ndarray) -> dict[str, Any]:
    """Радиальные штрихи рисок: длина штриха по углу (доли радиуса ROI) и основные риски."""
    size = wide_bgr.shape[1]
    c = size / 2.0
    r_roi = c / WIDE
    n_ang = int(round(360.0 / ANG_STEP))
    gray = cv2.cvtColor(wide_bgr, cv2.COLOR_BGR2GRAY)
    polar = cv2.warpPolar(gray, (int(c), n_ang), (c, c), c, cv2.WARP_POLAR_LINEAR)  # строки — угол
    # отклик — с 0,5 радиуса (длина основных рисок), кольцо рисок ищется только с 0,7 радиуса
    lo, hi = int(0.50 * r_roi), min(int(c) - 1, int(1.15 * r_roi))
    j_min = int(0.70 * r_roi) - lo
    band = polar[:, lo:hi]
    # штрих поперёк угла: ядро ~3° по углу; развёртка циклическая — дополняем строками с другого края
    kh = max(3, int(round(3.0 / ANG_STEP)) | 1)
    pad = kh
    ext = np.vstack([band[-pad:], band, band[:pad]])
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kh))
    resp = {"dark": cv2.morphologyEx(ext, cv2.MORPH_BLACKHAT, kern)[pad:-pad].astype(np.float32),
            "light": cv2.morphologyEx(ext, cv2.MORPH_TOPHAT, kern)[pad:-pad].astype(np.float32)}

    # кольцо рисок — радиальное окно, в котором пики углового профиля складываются в самую длинную
    # цепочку с постоянным шагом: так выглядят только риски (надписи, стрелка и ободок регулярного
    # «гребня» не образуют)
    win_cols = max(4, int(0.06 * r_roi))
    stride = max(2, int(0.02 * r_roi))
    best = None
    for pol, r in resp.items():
        for j0 in range(j_min, r.shape[1] - win_cols + 1, stride):
            pk = _profile_peaks(r[:, j0:j0 + win_cols].mean(axis=1))
            ch = tick_chain(pk)
            if ch is not None and (best is None or ch["n"] > best[0]):
                best = (ch["n"], pol, j0, ch, pk)
    if best is None:
        return {"polarity": None, "coverage": 0, "n_peaks": 0, "spacing": None, "band": None,
                "arc": None, "peaks": [], "lengths": []}
    _, polarity, j0, ch, band_peaks = best
    r = resp[polarity]
    # все риски кольца (цепочку может прерывать стрелка) с длиной штриха по радиусу
    peaks: list[tuple[float, float]] = []
    for a in band_peaks:
        i = int(round(a / ANG_STEP)) % n_ang
        rows = r[[(i - 1) % n_ang, i, (i + 1) % n_ang]].max(axis=0)
        seg = rows[j0:j0 + win_cols]
        level = 0.4 * float(seg.max())
        jj = int(j0 + np.argmax(seg))
        lo_j = jj
        while lo_j > 0 and rows[lo_j - 1] > level:
            lo_j -= 1
        hi_j = jj
        while hi_j < len(rows) - 1 and rows[hi_j + 1] > level:
            hi_j += 1
        peaks.append((a, (hi_j - lo_j + 1) / r_roi))
    return {"polarity": polarity, "coverage": ch["n"], "n_peaks": len(peaks), "spacing": ch["spacing"],
            "band": [round((lo + j0) / r_roi, 3), round((lo + j0 + win_cols) / r_roi, 3)],
            "arc": (ch["start"], ch["end"]), "peaks": [p[0] for p in peaks],
            "lengths": [round(p[1], 3) for p in peaks]}


def _profile_peaks(prof: np.ndarray) -> np.ndarray:
    """Локальные максимумы углового профиля (окно ±0,6°) выше фона, градусы."""
    w = max(1, int(round(0.6 / ANG_STEP)))
    ext_p = np.concatenate([prof[-w:], prof, prof[:w]])
    win = np.lib.stride_tricks.sliding_window_view(ext_p, 2 * w + 1).max(axis=1)
    med, p95 = float(np.median(prof)), float(np.percentile(prof, 95))
    idx = np.where((prof >= win) & (prof > med + 0.3 * (p95 - med)))[0]
    return np.array([float(g.mean()) * ANG_STEP for g in np.split(idx, np.where(np.diff(idx) > 1)[0] + 1) if len(g)])


def tick_chain(peaks: np.ndarray) -> dict[str, Any] | None:
    """Самая длинная цепочка пиков с постоянным шагом (допускается одна пропущенная риска подряд)."""
    pk = np.sort(np.asarray(peaks, float) % 360.0)
    n = len(pk)
    if n < 6:
        return None
    diffs = (np.roll(pk, -1) - pk) % 360.0
    cand = diffs[(diffs >= 1.0) & (diffs <= 15.0)]
    if len(cand) < 5:
        return None
    hist, edges = np.histogram(cand, bins=np.arange(1.0, 15.5, 0.5))
    k = int(np.argmax(hist))
    sel = cand[(cand >= edges[k] - 0.5) & (cand <= edges[k + 1] + 0.5)]
    s = float(np.median(sel))
    ok = (np.abs(diffs - s) <= 0.2 * s) | (np.abs(diffs - 2 * s) <= 0.2 * s)
    if ok.all():
        return None                       # сплошная шкала по кругу — разрыв не найден
    start = (int(np.argmin(ok)) + 1) % n  # обход начинается сразу после разрыва
    best_len, best_i0, run, run_i0 = 0, start, 0, start
    for j in range(n):
        i = (start + j) % n
        if ok[i]:
            if run == 0:
                run_i0 = i
            run += 1
            if run > best_len:
                best_len, best_i0 = run, run_i0
        else:
            run = 0
    if best_len < 5:
        return None
    idx = [(best_i0 + t) % n for t in range(best_len + 1)]
    chain = pk[idx]
    if (chain[0] - chain[-1]) % 360.0 < 20.0:
        return None
    return {"start": float(chain[0]), "end": float(chain[-1]), "spacing": round(s, 2), "n": len(chain),
            "peaks": chain.tolist()}


# ---------------------------------------------------------------------------
# Аппроксимация «угол → значение»
# ---------------------------------------------------------------------------
def _cut_angles(labels: list[Label]) -> list[float]:
    """Кандидаты разреза окружности — середины промежутков между соседними подписями.
    Разрыв шкалы — один из них, но не обязательно самый большой: посторонняя числовая надпись
    в разрыве делит его пополам."""
    angs = sorted(lb.angle for lb in labels)
    return [(angs[i] + ((angs[(i + 1) % len(angs)] - angs[i]) % 360.0) / 2.0) % 360.0 for i in range(len(angs))]


def _ransac(u: np.ndarray, v: np.ndarray, tol: float) -> tuple[float, float, list[int], bool] | None:
    """v = a + b·u по парам подписей, допуск по углу. Возвращает (a, b, inliers, ambiguous)."""
    n = len(u)
    cands: list[tuple[int, float, float, float, list[int]]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if v[i] == v[j] or abs(u[i] - u[j]) < 5.0:
                continue
            b = (v[j] - v[i]) / (u[j] - u[i])
            a = v[i] - b * u[i]
            res = np.abs(u - (v - a) / b)
            inl = [k for k in range(n) if res[k] <= tol]
            if len({float(v[k]) for k in inl}) < len(inl):
                continue
            cands.append((len(inl), -float(res[inl].sum()), a, b, inl))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    cnt, _, a, b, inl = cands[0]
    ambiguous = any(c2 >= cnt and len(set(inl2) & set(inl)) <= 1 for c2, _, _, _, inl2 in cands[1:]
                    if c2 >= MIN_INLIERS)
    return a, b, inl, ambiguous


def _label_step(values: list[float]) -> float | None:
    vs = sorted(set(values))
    diffs = [b - a for a, b in zip(vs, vs[1:]) if b - a > 0]
    return min(diffs) if diffs else None


def propose_wide(wide_bgr: np.ndarray) -> Proposal:
    t0 = time.perf_counter()
    if not available():
        return Proposal(False, reason="ocr_unavailable", debug={"error": _ocr_error})
    labels = read_labels(wide_bgr)
    ticks = tick_evidence(wide_bgr)
    pr = Proposal(False, labels=labels, ticks=ticks["peaks"],
                  debug={"polarity": ticks["polarity"], "tick_chain": ticks["coverage"], "tick_band": ticks["band"],
                         "n_peaks": ticks["n_peaks"], "tick_spacing": ticks["spacing"]})

    def done(reason: str | None = None) -> Proposal:
        pr.reason = reason
        pr.ms = (time.perf_counter() - t0) * 1000.0
        return pr

    if len(labels) < MIN_INLIERS:
        return done("few_labels" if labels else "no_labels")
    v = np.array([lb.value for lb in labels])
    best = None
    for cut_c in _cut_angles(labels):
        u_c = np.array([(lb.angle - cut_c) % 360.0 for lb in labels])
        f = _ransac(u_c, v, FIT_TOL_DEG)
        if f is None:
            continue
        a_c, b_c, inl_c, _amb = f
        res = float(np.abs(u_c[inl_c] - (v[inl_c] - a_c) / b_c).sum())
        key = (len(inl_c), -res)
        if best is None or key > best[0]:
            best = (key, cut_c, u_c, f)
    if best is None:
        return done("inconsistent_labels")
    _, cut, u, fit = best
    a, b, inl, ambiguous = fit
    pr.inliers = inl
    pr.debug.update({"n_labels": len(labels), "n_inliers": len(inl)})
    if ambiguous:
        return done("ambiguous_fit")
    if len(inl) < MIN_INLIERS:
        return done("few_consistent_labels")
    if float(u[inl].max() - u[inl].min()) < MIN_LABEL_SPAN_DEG:
        return done("narrow_label_span")
    # решётка рисок: риски равномерны по истинному углу, наблюдаемые углы искажены эксцентриситетом ROI
    lat = tick_lattice(ticks)
    if lat is None:
        return done("no_tick_lattice")
    pr.debug.update({"lattice_ticks": lat["n"], "lattice_rms_deg": lat["rms"], "ecc_deg": lat["ecc"],
                     "tick_spacing": lat["s"]})
    if lat["rms"] > LATTICE_MAX_RMS_DEG:
        return done("irregular_ticks")
    # дробный индекс риски для каждой согласованной подписи; подписи стоят на рисках, шаг подписей —
    # целое число рисок m
    f = np.array([lat["index_of"](labels[k].angle) for k in inl])
    vin = np.array([v[k] for k in inl])
    step = _label_step([float(x) for x in vin])
    if not step:
        return done("few_consistent_labels")
    t_raw = np.polyfit(vin, f, 1)[0]                   # рисок на единицу значения
    m = int(round(abs(t_raw) * step))
    if not 1 <= m <= 60:
        return done("bad_label_spacing")
    t = math.copysign(m / step, t_raw)
    c0 = float(np.round(np.median(f - t * vin) + t * vin.min())) - t * vin.min()
    resid = f - (c0 + t * vin)
    pr.debug.update({"ticks_per_label": m, "label_resid_ticks": round(float(np.abs(resid).max()), 2)})
    if np.mean(np.abs(resid) <= LABEL_TICK_TOL) < MIN_SNAPPED_FRAC:
        return done("labels_off_ticks")
    # концы шкалы — концы решётки, округлённые к сетке подписей (не дальше 2 рисок), иначе ближайшее
    # значение сетки внутри решётки
    def grid_end(i_end: float, inward: float) -> float:
        val = (i_end - c0) / t
        g = round((val - vin.min()) / step) * step + vin.min()
        if abs((c0 + t * g) - i_end) <= END_TICK_TOL:
            return g
        g_in = g + math.copysign(step, inward * t) if (c0 + t * g - i_end) * inward < 0 else g
        return g_in
    v_a = grid_end(lat["i_min"], +1.0)
    v_b = grid_end(lat["i_max"], -1.0)
    v_lo, v_hi = min(v_a, v_b), max(v_a, v_b)
    if v_hi - v_lo < step:
        return done("narrow_scale")
    th_lo = lat["angle_of"](c0 + t * v_lo)
    th_hi = lat["angle_of"](c0 + t * v_hi)
    direction = "cw" if t > 0 else "ccw"
    sweep = (th_hi - th_lo) % 360.0 if direction == "cw" else (th_lo - th_hi) % 360.0
    if not 30.0 <= sweep <= 350.0:
        return done("bad_sweep")
    pr.calibration = {"v_min": float(round(v_lo, 9)), "theta_min": float(round(th_lo, 2)), "v_max": float(round(v_hi, 9)),
                      "theta_max": float(round(th_hi, 2)), "direction": direction}
    pr.confidence = (min(1.0, len(inl) / 5.0) * max(0.0, 1.0 - lat["rms"] / (2 * LATTICE_MAX_RMS_DEG))
                     * float(np.mean(np.abs(resid) <= LABEL_TICK_TOL)))
    pr.ok = True
    return done(None)


def tick_lattice(ticks: dict[str, Any]) -> dict[str, Any] | None:
    """Индексация рисок и модель θ = θ0 + s·i + A·sin θ + B·cos θ (эксцентриситет ROI), МНК.

    Опора — самая длинная регулярная цепочка; риски вне её (за стрелкой, у концов шкалы) добавляются,
    если ложатся на решётку с точностью 0,25 шага."""
    pk = np.array(ticks["peaks"], float)
    s0 = ticks["spacing"]
    if s0 is None or len(pk) < 10:
        return None
    ch = tick_chain(pk)
    if ch is None or ch["n"] < 10:
        return None
    chain = np.array(ch["peaks"])
    un = np.concatenate([[0.0], np.cumsum((np.diff(chain) + 360.0) % 360.0)]) + chain[0]   # развёрнутые углы
    idx = np.concatenate([[0], np.cumsum(np.round(np.diff(un) / s0))]).astype(float)

    def fit(th_un: np.ndarray, ii: np.ndarray):
        r = np.radians(th_un % 360.0)
        x = np.stack([np.ones_like(ii), ii, np.sin(r), np.cos(r)], axis=1)
        prm, *_ = np.linalg.lstsq(x, th_un, rcond=None)
        return prm, th_un - x @ prm

    prm, res = fit(un, idx)
    base = chain[0]

    def index_of(angle: float) -> float:
        a_un = (angle - base) % 360.0 + base
        r = math.radians(angle % 360.0)
        return (a_un - prm[0] - prm[2] * math.sin(r) - prm[3] * math.cos(r)) / prm[1]

    def angle_of(i: float) -> float:
        a = prm[0] + prm[1] * i
        for _ in range(8):
            r = math.radians(a % 360.0)
            a = prm[0] + prm[1] * i + prm[2] * math.sin(r) + prm[3] * math.cos(r)
        return a % 360.0

    # дополнение рисками вне цепочки: обход в обе стороны от концов, пока риски ложатся на решётку
    known = {int(i): float(a) for i, a in zip(idx, un)}
    for _ in range(2):
        for a in pk:
            fi = index_of(a)
            ii = int(round(fi))
            if abs(fi - ii) <= 0.25 and ii not in known:
                lo_i, hi_i = min(known), max(known)
                if lo_i - 3 <= ii <= hi_i + 3:            # без скачков через разрыв шкалы
                    known[ii] = (a - base) % 360.0 + base
        ii_arr = np.array(sorted(known), float)
        prm, res = fit(np.array([known[int(i)] for i in ii_arr]), ii_arr)
    if (ii_arr.max() - ii_arr.min()) * abs(prm[1]) > 355.0:
        return None

    def tick_angle(i: float) -> float:
        """Угол риски с индексом i: найденная риска, если она есть, иначе по модели решётки."""
        ii = int(round(i))
        return known[ii] % 360.0 if abs(i - ii) < 0.05 and ii in known else angle_of(i)

    return {"n": len(known), "s": round(float(prm[1]), 3), "rms": round(float(np.sqrt(np.mean(res ** 2))), 3),
            "ecc": round(math.hypot(prm[2], prm[3]), 2), "i_min": float(ii_arr.min()), "i_max": float(ii_arr.max()),
            "index_of": index_of, "angle_of": tick_angle}


def propose(frame_bgr: np.ndarray, roi: vision.DialROI) -> Proposal:
    """Предложение калибровки для прибора с ROI `roi` на кадре `frame_bgr`."""
    return propose_wide(wide_dial(frame_bgr, roi))
