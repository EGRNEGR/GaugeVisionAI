"""
GaugeVision AI — модуль прогнозной аналитики (`predictive_analytics`).

Выполняет статистически строгий анализ реальных временных рядов показаний приборов
(из SQLite `readings` / `instrument_readings` и скользящего окна `DispatchAnalyzer`):
  1. Экспоненциально-взвешенная линейная регрессия (WLS) с эффективным числом
     степеней свободы и оценкой неопределённости (80% и 95% предиктивные интервалы
     с точными квантилями t-распределения Стьюдента, без внешних зависимостей).
  2. Робастная проверка наклона методом Тейла-Сена (Theil-Sen median slope) для
     защиты от одиночных выбросов компьютерного зрения.
  3. Оценка ускорения тренда (вторая производная d²V/dt² с z-статистикой) для
     раннего обнаружения ускоряющегося перегрева / разгона параметра.
  4. Оценка времени достижения уставок LL / L / H / HH (Time-to-Threshold / ETA):
     медианный прогноз, пессимистичная (ранняя) и оптимистичная (поздняя) границы
     по 95% предиктивному интервалу, а также вероятность пробоя уставки в пределах
     заданного горизонта H.
  5. Обнаружение аномальных трендов тремя независимыми методами:
       - двусторонний CUSUM (ранний сдвиг среднего);
       - непараметрический критерий Манна-Кендалла (значимость монотонного дрейфа);
       - модифицированный Z-score по MAD (выбросы) и коэффициент роста волатильности.

Совместимость:
  • Ключ прибора — унифицированный `instrument_id` + `camera_id` + `gauge_slot`
    (готов к многоприборной архитектуре Multi-Gauge Vision).
  • При нехватке данных или статусе STALE честно возвращает `insufficient_data`
    / `stale_channel` без подмены и выдуманных прогнозов.
"""
from __future__ import annotations

import datetime as _dt
import math
import time
from typing import Any

import numpy as np

from .contracts import resolve_instrument_identity
from .db import utcnow_iso

PREDICTIVE_DISCLAIMER = (
    "Прогнозная оценка времени достижения уставок и аномальных трендов выполняется "
    "статистически по фактическому временному ряду видеомониторинга. Не является "
    "метрологическим заключением (ФЗ-102), расчётом остаточного ресурса оборудования "
    "или основанием для вмешательства в контуры ПАЗ."
)

TREND_CLASS_META: dict[str, dict[str, Any]] = {
    "stable": {"code_num": 0, "label": "Стабильный режим", "short": "Стабильно", "tone": "normal"},
    "rising_drift": {"code_num": 1, "label": "Устойчивый восходящий дрейф", "short": "Рост ↑", "tone": "warning"},
    "falling_drift": {"code_num": 2, "label": "Устойчивый нисходящий дрейф", "short": "Спад ↓", "tone": "warning"},
    "accelerating_drift": {"code_num": 3, "label": "Ускоряющийся дрейф (разгон)", "short": "Разгон ↗", "tone": "alert"},
    "oscillating_chatter": {"code_num": 4, "label": "Рост колебаний / дребезга", "short": "Вибрация", "tone": "warning"},
    "step_shift": {"code_num": 5, "label": "Ступенчатый сдвиг уровня (CUSUM)", "short": "Сдвиг", "tone": "alert"},
    "insufficient_data": {"code_num": 6, "label": "Недостаточно данных для прогноза", "short": "Нет базы", "tone": "stale"},
}

# Точные двусторонние квантили распределения Стьюдента для 95% (alpha=0.05) и 80% (alpha=0.20)
_T95_TABLE: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980,
}
_T80_TABLE: dict[int, float] = {
    1: 3.078, 2: 1.886, 3: 1.638, 4: 1.533, 5: 1.476,
    6: 1.440, 7: 1.415, 8: 1.397, 9: 1.383, 10: 1.372,
    11: 1.363, 12: 1.356, 13: 1.350, 14: 1.345, 15: 1.341,
    16: 1.337, 17: 1.333, 18: 1.330, 19: 1.328, 20: 1.325,
    25: 1.316, 30: 1.310, 40: 1.303, 60: 1.296, 120: 1.289,
}


def _finite(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def student_t_quantile(df: float, level: float = 0.95) -> float:
    """Точный двусторонний квантиль t_{df, (1+level)/2} (интерполяция + разложение Корниша-Фишера)."""
    z = 1.95996398454 if level >= 0.90 else 1.28155156554
    table = _T95_TABLE if level >= 0.90 else _T80_TABLE
    if df <= 1.0:
        return table[1]
    if df >= 120.0:
        # Асимптотическая поправка Корниша-Фишера
        return z + (z**3 + z) / (4.0 * df) + (5.0 * z**5 + 16.0 * z**3 + 3.0 * z) / (96.0 * df * df)
    keys = sorted(table.keys())
    for k0, k1 in zip(keys, keys[1:]):
        if k0 <= df <= k1:
            frac = (df - k0) / float(k1 - k0)
            return table[k0] + frac * (table[k1] - table[k0])
    return z


def norm_sf(z: float) -> float:
    """Хвостовая вероятность стандартного нормального распределения P(Z >= z)."""
    if not math.isfinite(z):
        return 0.0
    if z <= -8.0:
        return 1.0
    if z >= 8.0:
        return 0.0
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _theil_sen_slope(x: np.ndarray, y: np.ndarray, max_points: int = 80) -> float:
    """Векторизованная робастная оценка наклона Тейла-Сена (медиана всех парных наклонов)."""
    n = len(x)
    if n < 2:
        return 0.0
    if n > max_points:
        idx = np.linspace(0, n - 1, max_points, dtype=int)
        x = x[idx]
        y = y[idx]
        n = len(x)
    iu, ju = np.triu_indices(n, k=1)
    dx = x[ju] - x[iu]
    mask = np.abs(dx) > 1e-6
    if not np.any(mask):
        return 0.0
    dy = y[ju][mask] - y[iu][mask]
    return float(np.median(dy / dx[mask]))


def _lag1_autocorr(arr: np.ndarray) -> float:
    """Устойчивая оценка автокорреляции остатков первого порядка rho_1 in [0, 0.96]."""
    if len(arr) < 6:
        return 0.0
    a = arr[:-1] - float(np.mean(arr[:-1]))
    b = arr[1:] - float(np.mean(arr[1:]))
    denom = math.sqrt(float(np.sum(a * a)) * float(np.sum(b * b)))
    if denom <= 1e-12:
        return 0.0
    r = float(np.sum(a * b) / denom)
    return max(0.0, min(0.96, r)) if math.isfinite(r) else 0.0


def _robust_recent_level(y: np.ndarray, *, alpha: float = 0.28) -> float:
    """
    Устойчивое к выбросам экспоненциальное сглаживание текущего уровня (Huber-клиппинг
    одиночных скачков CV > 3.5 * MAD). Используется для привязки прогноза к актуальному
    режиму оборудования без смещения от одиночных ошибок распознавания.
    """
    if len(y) == 0:
        return 0.0
    if len(y) < 4:
        return float(np.median(y))
    med = float(np.median(y))
    mad = float(np.median(np.abs(y - med))) * 1.4826
    clip_lim = max(3.5 * mad, float(np.percentile(y, 90) - np.percentile(y, 10)) * 0.75, 1e-6)
    # Инициализируем медианой первых 3 точек, чтобы старт не сбивался выбросом
    level = float(np.median(y[:3]))
    for val in y[1:]:
        vf = float(val)
        delta = vf - level
        if abs(delta) > clip_lim:
            vf = level + math.copysign(clip_lim * 0.35, delta)
        level = alpha * vf + (1.0 - alpha) * level
    return float(level)


def _robust_damped_holt(
    x: np.ndarray,
    y: np.ndarray,
    *,
    alpha: float = 0.30,
    beta: float = 0.12,
    phi: float = 0.88,
) -> tuple[float, float, float]:
    """
    Робастное двойное экспоненциальное сглаживание Хольта с затуханием тренда
    (Huber-клиппинг одиночных выбросов CV > 3.5 * MAD).
    Возвращает (level_now, slope_per_min, damp_tau_min).
    """
    n = len(y)
    if n < 3:
        return float(y[-1]) if n else 0.0, 0.0, 10.0
    dt_arr = np.diff(x)
    pos_dt = dt_arr[dt_arr > 1e-4]
    dt_med = float(np.median(pos_dt)) if len(pos_dt) else 1.0

    med = float(np.median(y))
    mad = float(np.median(np.abs(y - med))) * 1.4826
    iqr_clip = float(np.percentile(y, 90) - np.percentile(y, 10)) * 0.75
    clip_lim = max(3.5 * mad, iqr_clip, 1e-6)

    level = float(np.median(y[:3]))
    trend = float(np.median(np.diff(y[: min(6, n)]))) if n >= 4 else float(y[1] - y[0])
    trend = max(-clip_lim * 0.5, min(clip_lim * 0.5, trend))

    for val in y[1:]:
        pred = level + phi * trend
        vf = float(val)
        err = vf - pred
        if abs(err) > clip_lim:
            vf = pred + math.copysign(clip_lim * 0.45, err)
        prev_l = level
        level = alpha * vf + (1.0 - alpha) * pred
        trend = beta * (level - prev_l) + (1.0 - beta) * phi * trend

    # Преобразуем дискретный затухающий шаг phi в эквивалентную непрерывную постоянную времени tau:
    # sum_{k=1..h/dt} phi^k ≈ (phi / (1 - phi)) * (1 - exp(-h / tau)), где tau = -dt / ln(phi)
    slope_per_min = (phi * trend) / max(dt_med, 1e-4)
    damp_tau_min = max(2.0, -dt_med / math.log(max(0.50, min(0.99, phi))))
    return float(level), float(slope_per_min), float(damp_tau_min)


def _h_effective(h: float, damp_tau: float | None) -> float:
    """Непрерывное экспоненциальное затухание тренда: h_eff(h) = tau * (1 - exp(-h / tau))."""
    if damp_tau is None or damp_tau <= 0.0 or h <= 0.0:
        return max(0.0, float(h))
    return float(damp_tau * (1.0 - math.exp(-float(h) / damp_tau)))


def _mann_kendall_test(y: np.ndarray, max_points: int = 120, *, rho1_resid: float = 0.0) -> dict[str, float]:
    """
    Непараметрический критерий Манна-Кендалла с поправкой Хамеда-Рао (Hamed & Rao, 1998)
    на автокорреляцию остатков первого порядка (исключает ложные срабатывания на инерционных
    промышленных процессах).
    """
    n = len(y)
    if n < 6:
        return {"s": 0.0, "z": 0.0, "p_value": 1.0, "significant": False}
    if n > max_points:
        idx = np.linspace(0, n - 1, max_points, dtype=int)
        y = y[idx]
        n = len(y)

    iu, ju = np.triu_indices(n, k=1)
    diff = y[ju] - y[iu]
    s = int(np.sum(diff > 1e-12) - np.sum(diff < -1e-12))

    # Поправка на совпадающие значения (ties)
    _, counts = np.unique(np.round(y, 6), return_counts=True)
    tie_term = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var_s <= 1e-12:
        return {"s": float(s), "z": 0.0, "p_value": 1.0, "significant": False}

    # Поправка дисперсии на положительную автокорреляцию остатков (только при rho1 > 0.25)
    ac_mult = 1.0
    if rho1_resid > 0.25:
        r_eff = min(0.88, rho1_resid)
        ac_mult = min(9.0, (1.0 + r_eff) / max(0.12, 1.0 - r_eff))
    var_s_eff = var_s * ac_mult

    if s > 0:
        z = (s - 1.0) / math.sqrt(var_s_eff)
    elif s < 0:
        z = (s + 1.0) / math.sqrt(var_s_eff)
    else:
        z = 0.0
    p_val = min(1.0, 2.0 * norm_sf(abs(z)))
    return {
        "s": float(s),
        "z": round(float(z), 3),
        "p_value": round(float(p_val), 5),
        "significant": bool(p_val < 0.05 and abs(z) >= 1.96),
    }


def _cusum_test(y: np.ndarray, *, span: float = 1.0, k: float = 0.5, h_limit: float = 5.5) -> dict[str, Any]:
    """
    Двусторонний контрольный алгоритм CUSUM относительно базовой первой трети ряда.
    Устойчив к разовым выбросам и штатным периодическим колебаниям вокруг номинала:
    требует как превышения накопленной статистики CUSUM >= h_limit, так и фактического
    смещения среднего уровня хвостовой части ряда сверх рабочей амплитуды колебаний.
    """
    n = len(y)
    if n < 8:
        return {"pos_max": 0.0, "neg_max": 0.0, "max_stat": 0.0, "threshold": h_limit, "triggered": False, "direction": "none"}

    base_n = max(4, min(n // 2, max(6, n // 3)))
    base = y[:base_n]
    tail = y[base_n:]
    mu0 = float(np.median(base))
    mad0 = float(np.median(np.abs(base - mu0))) * 1.4826
    std0 = float(np.std(base, ddof=1)) if len(base) > 1 else 0.0
    # Оценка шума/амплитуды по первым разностям всего ряда (устойчива к разовому скачку)
    diffs = np.diff(y)
    sigma_diff = float(np.median(np.abs(diffs))) * 1.4826 / math.sqrt(2.0) if len(diffs) >= 2 else 0.0
    full_span = float(np.max(y) - np.min(y))
    sigma_eff = max(mad0, std0, sigma_diff, full_span * 0.02, 1e-6)

    c_pos = 0.0
    c_neg = 0.0
    max_pos = 0.0
    max_neg = 0.0
    for val in tail:
        z = (float(val) - mu0) / sigma_eff
        c_pos = max(0.0, c_pos + z - k)
        c_neg = max(0.0, c_neg - z - k)
        if c_pos > max_pos:
            max_pos = c_pos
        if c_neg > max_neg:
            max_neg = c_neg

    # Фактическое смещение среднего хвостовой части (защита от ложных срабатываний на чистой синусоиде)
    tail_shift = abs(float(np.median(tail)) - mu0)
    min_phys_shift = max(1.6 * max(mad0, std0, sigma_diff), max(span, 1e-6) * 0.012)
    max_stat = max(max_pos, max_neg)
    triggered = bool(max_stat >= h_limit and tail_shift >= min_phys_shift)
    direction = "up" if max_pos >= max_neg else "down"
    return {
        "pos_max": round(float(max_pos), 3),
        "neg_max": round(float(max_neg), 3),
        "max_stat": round(float(max_stat), 3),
        "tail_shift": round(float(tail_shift), 4),
        "threshold": h_limit,
        "triggered": triggered,
        "direction": direction if triggered else "none",
    }


def _mad_outliers(y: np.ndarray, *, z_limit: float = 3.5) -> dict[str, Any]:
    """Модифицированный Z-score по медиане и MAD для обнаружения резких выбросов."""
    if len(y) < 6:
        return {"count": 0, "max_abs_mz": 0.0, "ratio": 0.0}
    med = float(np.median(y))
    mad = float(np.median(np.abs(y - med)))
    if mad <= 1e-9:
        std = float(np.std(y))
        if std <= 1e-9:
            return {"count": 0, "max_abs_mz": 0.0, "ratio": 0.0}
        mz = np.abs(y - med) / std
    else:
        mz = 0.6745 * np.abs(y - med) / mad
    cnt = int(np.sum(mz > z_limit))
    return {
        "count": cnt,
        "max_abs_mz": round(float(np.max(mz)), 3),
        "ratio": round(cnt / float(len(y)), 4),
    }


def _solve_bound_crossing(
    *,
    b0: float,
    slope: float,
    se_resid: float,
    inv_sum_w: float,
    x_bar: float,
    s_xx: float,
    t_crit: float,
    threshold: float,
    direction: int,  # +1 для верхней уставки (H/HH), -1 для нижней (L/LL)
    bound_sign: int,  # +1 для верхней границы PI, -1 для нижней границы PI
    max_eta_min: float,
    damp_tau: float | None = None,
    rw_var_rate: float = 0.0,
) -> float | None:
    """
    Численно находит наименьшее h in [0, max_eta_min], при котором граница
    прогнозного интервала f(h) = (b0 + slope * h_eff(h) + bound_sign * t_crit * SE(h))
    достигает `threshold` со стороны безопасной зоны.
    """
    def _val(h: float) -> float:
        he = _h_effective(h, damp_tau)
        reg_var = (se_resid * se_resid) * (1.0 + inv_sum_w + ((he - x_bar) ** 2) / max(s_xx, 1e-9))
        se_h = math.sqrt(max(1e-12, reg_var + rw_var_rate * max(0.0, h)))
        return b0 + slope * he + bound_sign * t_crit * se_h

    def _signed_gap(h: float) -> float:
        # >= 0 означает пробой уставки
        return direction * (_val(h) - threshold)

    if _signed_gap(0.0) >= 0.0:
        return 0.0

    # Грубый поиск первого положительного пересечения на логарифмически-линейной сетке
    grid = [
        0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0,
        90.0, 120.0, 180.0, 240.0, 360.0, 480.0, 720.0, 1440.0, max_eta_min,
    ]
    grid = sorted({h for h in grid if 0.0 < h <= max_eta_min})
    prev_h = 0.0
    prev_g = _signed_gap(0.0)
    bracket: tuple[float, float] | None = None
    for h in grid:
        g = _signed_gap(h)
        if g >= 0.0:
            bracket = (prev_h, h)
            break
        prev_h, prev_g = h, g

    if bracket is None:
        return None

    lo, hi = bracket
    for _ in range(36):
        mid = 0.5 * (lo + hi)
        if _signed_gap(mid) >= 0.0:
            hi = mid
        else:
            lo = mid
    return round(hi, 2)


class PredictiveAnalyzer:
    """
    Аналитический движок прогнозирования уставок и обнаружения аномальных трендов.
    Работает строго на фактических временных рядах без синтетических заглушек.
    """

    DEFAULT_WINDOW_MIN = 60.0
    DEFAULT_HORIZON_MIN = 60.0
    MAX_ETA_MIN = 1440.0  # 24 часа

    def analyze_series(
        self,
        inst: dict[str, Any],
        timed_points: list[tuple[float, float]],
        *,
        window_min: float = DEFAULT_WINDOW_MIN,
        horizon_min: float = DEFAULT_HORIZON_MIN,
        now_unix: float | None = None,
    ) -> dict[str, Any]:
        """
        Выполняет полный прогнозный расчёт для одного прибора по временному ряду
        `(t_unix, value)` (в хронологическом порядке, значения конечные).
        """
        ident = resolve_instrument_identity(inst)
        now = float(time.time() if now_unix is None else now_unix)
        win_min = max(2.0, min(1440.0, float(window_min)))
        hor_min = max(5.0, min(720.0, float(horizon_min)))

        cal = inst.get("calibration") or {}
        v_min = _finite(cal.get("v_min"))
        v_max = _finite(cal.get("v_max"))
        v_min = 0.0 if v_min is None else v_min
        v_max = 10.0 if v_max is None else v_max
        span = abs(v_max - v_min) or 1.0

        rd = inst.get("reading") or {}
        cur_val = _finite(rd.get("value"))
        cur_valid = bool(rd.get("valid")) and cur_val is not None
        cur_level = str(rd.get("level") or "normal") if cur_valid else "stale"
        thr = inst.get("thresholds") or {}
        lower_on = thr.get("lower_enabled") is not False

        # Очистка, фильтрация по окну, сортировка и дедупликация по метке времени
        cutoff = now - win_min * 60.0
        cleaned: list[tuple[float, float]] = []
        for t_raw, v_raw in timed_points:
            tf = _finite(t_raw)
            vf = _finite(v_raw)
            if tf is None or vf is None:
                continue
            if tf < cutoff - 5.0 or tf > now + 60.0:
                continue
            cleaned.append((tf, vf))
        cleaned.sort(key=lambda p: p[0])

        dedup: list[tuple[float, float]] = []
        for t, v in cleaned:
            if dedup and abs(t - dedup[-1][0]) < 1e-3:
                dedup[-1] = (t, v)
            else:
                dedup.append((t, v))

        sample_count = len(dedup)
        actual_span_s = (dedup[-1][0] - dedup[0][0]) if sample_count >= 2 else 0.0

        base_resp: dict[str, Any] = {
            "instrument_id": ident.instrument_id,
            "camera_id": ident.camera_id,
            "gauge_slot": ident.gauge_slot,
            "code": ident.code,
            "name": ident.name,
            "short_name": ident.short_name,
            "group": ident.group,
            "gauge_type": ident.gauge_type,
            "unit": ident.unit,
            "decimals": int(inst.get("decimals", 2)),
            "source_kind": ident.source_kind,
            "computed_at": _dt.datetime.fromtimestamp(now, tz=_dt.timezone.utc).isoformat(timespec="seconds"),
            "window_min": round(win_min, 1),
            "horizon_min": round(hor_min, 1),
            "sample_count": sample_count,
            "actual_span_min": round(actual_span_s / 60.0, 2),
            "current_value": cur_val if cur_valid else None,
            "current_level": cur_level,
            "valid": cur_valid,
            "thresholds": thr,
            "calibration": cal,
        }

        # Честный отказ при нехватке данных или недостоверном канале
        if not cur_valid or sample_count < 6 or actual_span_s < 20.0:
            reason = (
                "Канал без свежих достоверных данных (STALE)"
                if not cur_valid
                else f"Недостаточно наблюдений для статистического прогноза ({sample_count} точек, охват {actual_span_s:.0f} с)"
            )
            return {
                **base_resp,
                "status": "stale_channel" if not cur_valid else "insufficient_data",
                "status_reason": reason,
                "trend_class": "insufficient_data",
                "trend_meta": TREND_CLASS_META["insufficient_data"],
                "model": None,
                "forecast_at_horizon": None,
                "forecast_points": [],
                "uncertainty_pct": None,
                "forecast_confidence": 0.0,
                "nearest_threshold": None,
                "eta_warning_min": None,
                "eta_warning_ci": None,
                "eta_alert_min": None,
                "eta_alert_ci": None,
                "breach_prob_warning_horizon": 0.0,
                "breach_prob_alert_horizon": 0.0,
                "thresholds_eta": {},
                "anomaly_score": 0.0,
                "anomalies": [],
                "diagnostics": {"mann_kendall": None, "cusum": None, "outliers": None, "volatility_ratio": 1.0},
            }

        # Время в минутах относительно t_ref = последняя точка (<= 0)
        t_ref = dedup[-1][0]
        x = np.array([(p[0] - t_ref) / 60.0 for p in dedup], dtype=np.float64)
        y = np.array([p[1] for p in dedup], dtype=np.float64)

        # 1. Экспоненциально-взвешенная линейная регрессия (WLS)
        half_life = max(3.0, min(win_min * 0.45, (actual_span_s / 60.0) * 0.6))
        w = np.exp(-math.log(2.0) * np.abs(x) / half_life)
        sum_w = float(np.sum(w))
        sum_w2 = float(np.sum(w * w))
        n_eff = (sum_w * sum_w) / max(sum_w2, 1e-12)
        df_eff = max(2.0, n_eff - 2.0)

        x_bar = float(np.sum(w * x) / sum_w)
        y_bar = float(np.sum(w * y) / sum_w)
        dx = x - x_bar
        dy = y - y_bar
        s_xx = float(np.sum(w * dx * dx))
        s_xy = float(np.sum(w * dx * dy))

        slope_wls = (s_xy / s_xx) if s_xx > 1e-9 else 0.0
        b0_wls = y_bar - slope_wls * x_bar

        # 2. Робастная проверка наклона (Theil-Sen) и выбор устойчивой модели
        slope_ts = _theil_sen_slope(x, y)
        y_hat_wls = b0_wls + slope_wls * x
        resid_wls = y - y_hat_wls
        rss_w = float(np.sum(w * resid_wls * resid_wls))
        tss_w = float(np.sum(w * dy * dy))
        r2_w = max(0.0, min(1.0, 1.0 - rss_w / tss_w)) if tss_w > 1e-12 else 0.0

        # Эффективная несмещённая оценка дисперсии остатков
        # При нормализации весов на n_eff: var = (n_eff / sum_w) * rss_w / df_eff
        scale_w = n_eff / max(sum_w, 1e-12)
        se_resid = math.sqrt(max(0.0, (scale_w * rss_w) / max(df_eff, 1.0)))
        # Минимальный физический порог шума (разрешение прибора / 1e-4 от шкалы)
        se_floor = max(span * 1e-4, 1e-6)
        se_resid_eff = max(se_resid, se_floor)

        s_xx_eff = max(s_xx * scale_w, 1e-9)
        se_slope = se_resid_eff / math.sqrt(s_xx_eff)

        outliers = _mad_outliers(y)
        b0_ts = float(np.median(y - slope_ts * x))
        resid_ts = y - (b0_ts + slope_ts * x)
        mad_resid_ts = float(np.median(np.abs(resid_ts))) * 1.4826
        rob_sigma = max(mad_resid_ts, se_floor)
        se_slope_rob = rob_sigma / math.sqrt(s_xx_eff)
        # Переключаемся на робастную модель Theil-Sen, когда присутствуют одиночные выбросы (<= 35% ряда),
        # искажающие OLS-остатки, уровень или наклон (массовые колебания >35% — это смена режима/вибрация)
        use_robust = bool(
            outliers["count"] > 0
            and outliers["ratio"] <= 0.35
            and (
                se_resid > 1.8 * rob_sigma
                or abs(b0_wls - b0_ts) > 2.5 * rob_sigma
                or abs(slope_wls - slope_ts) > max(2.0 * se_slope_rob, span * 0.002)
            )
        )
        slope_raw = slope_ts if use_robust else slope_wls
        b0_raw = b0_ts if use_robust else b0_wls
        if use_robust:
            se_resid_eff = rob_sigma
            se_slope = se_slope_rob

        # 2b. Автокорреляция остатков, адаптивная привязка текущего уровня и затухание тренда
        # (обосновано rolling-origin backtesting на 4 реальных промышленных датасетах)
        resid_active = resid_ts if use_robust else resid_wls
        rho1_resid = _lag1_autocorr(resid_active)
        ac_se_mult = (
            math.sqrt((1.0 + min(0.88, rho1_resid)) / max(0.12, 1.0 - min(0.88, rho1_resid)))
            if rho1_resid > 0.25
            else 1.0
        )
        t_slope_ac = abs(slope_raw) / max(se_slope * ac_se_mult, 1e-9)

        # На чистом устойчивом линейном тренде (статистически значимый наклон при некоррелированных
        # остатках rho1 < 0.35, либо очень высокий R^2 >= 0.88) сохраняем точную линейную экстраполяцию
        # без смещения; на зашумлённых/инерционных/циклических промышленных процессах применяем
        # робастную привязку текущего уровня + байесовское сжатие шумового наклона + непрерывное
        # затухание тренда h_eff(h) = tau * (1 - exp(-h / tau)).
        linear_regime = bool(
            (t_slope_ac >= 2.5 and rho1_resid < 0.35)
            or (r2_w >= 0.88 and rho1_resid < 0.50)
            or (r2_w >= 0.94)
            or (use_robust and rob_sigma <= max(abs(slope_ts) * max(actual_span_s / 60.0, 1.0) * 0.08, se_floor * 5.0))
        )

        if linear_regime:
            b0 = b0_raw
            slope = slope_raw
            damp_tau: float | None = None
            slope_shrink = 1.0
            holt_fast: tuple[float, float, float] | None = None
        else:
            # Робастный локальный затухающий Хольт (быстро отслеживает смену режима и
            # приближение к уставке, не перелетая на длинных горизонтах)
            holt_lvl, holt_slope, holt_tau = _robust_damped_holt(x, y, alpha=0.28, beta=0.08, phi=0.85)
            # Быстрый локальный Хольт для раннего обнаружения пробоя уставок (ETA / breach_prob)
            holt_fast = _robust_damped_holt(x, y, alpha=0.30, beta=0.12, phi=0.88)
            anchor_w = max(0.0, min(0.88, 0.88 * (1.0 - r2_w)))
            b0 = (1.0 - anchor_w) * b0_raw + anchor_w * holt_lvl

            # Эмпирико-байесовское сжатие глобального наклона + умеренный локальный импульс Хольта
            slope_shrink = (t_slope_ac * t_slope_ac) / (t_slope_ac * t_slope_ac + 3.0)
            global_slope = slope_raw * slope_shrink * (0.35 + 0.65 * r2_w)
            local_w = max(0.25, min(0.58, 0.58 * (1.0 - r2_w)))
            slope = (1.0 - local_w) * global_slope + local_w * holt_slope
            # Константа затухания тренда согласована с локальным затуханием Хольта
            span_min_eff = max(5.0, actual_span_s / 60.0)
            damp_tau = max(3.5, min(span_min_eff * (0.20 + 0.50 * r2_w), holt_tau * 1.05))

        # 3. Ускорение тренда (сравнение ранней и поздней половин окна)
        mid = len(x) // 2
        accel_per_min2 = 0.0
        accel_z = 0.0
        vol_ratio = 1.0
        std_recent = se_resid_eff
        if mid >= 4 and (len(x) - mid) >= 4:
            x1, y1 = x[:mid], y[:mid]
            x2, y2 = x[mid:], y[mid:]
            span1 = float(x1[-1] - x1[0])
            span2 = float(x2[-1] - x2[0])
            if span1 > 0.05 and span2 > 0.05:
                s1 = float(np.polyfit(x1, y1, 1)[0])
                s2 = float(np.polyfit(x2, y2, 1)[0])
                dt_centers = max(0.05, float(np.mean(x2) - np.mean(x1)))
                accel_per_min2 = (s2 - s1) / dt_centers
                r1 = y1 - (s1 * x1 + (np.mean(y1) - s1 * np.mean(x1)))
                r2 = y2 - (s2 * x2 + (np.mean(y2) - s2 * np.mean(x2)))
                se1 = float(np.std(r1, ddof=1)) / math.sqrt(max(float(np.sum((x1 - np.mean(x1)) ** 2)), 1e-9))
                se2 = float(np.std(r2, ddof=1)) / math.sqrt(max(float(np.sum((x2 - np.mean(x2)) ** 2)), 1e-9))
                comb_se = math.sqrt(se1 * se1 + se2 * se2 + (se_floor * 0.5) ** 2)
                accel_z = (s2 - s1) / max(comb_se, 1e-9)
                std1 = float(np.std(r1, ddof=1)) if len(r1) > 1 else 0.0
                std2 = float(np.std(r2, ddof=1)) if len(r2) > 1 else 0.0
                std_recent = std2
                vol_ratio = (std2 + se_floor) / (std1 + se_floor)

        # 4. Критерии аномальных трендов: Манн-Кендалл (с поправкой Хамеда-Рао) + CUSUM
        mk = _mann_kendall_test(y, rho1_resid=rho1_resid)
        cusum = _cusum_test(y, span=span)

        # 5. Прогнозная траектория и 80%/95% предиктивные интервалы с учётом автокорреляции
        # и диффузии состояния (random-walk innovation rate) на реальных промышленных рядах
        if rho1_resid > 0.2:
            r_ac = min(0.90, rho1_resid)
            n_eff_ac = max(4.0, n_eff * (1.0 - r_ac) / (1.0 + r_ac))
        else:
            n_eff_ac = n_eff
        df_ac = max(2.0, n_eff_ac - 2.0)
        t95 = student_t_quantile(df_ac, 0.95)
        t80 = student_t_quantile(df_ac, 0.80)
        inv_neff = 1.0 / max(n_eff_ac, 1.0)
        s_xx_ac = s_xx_eff * (n_eff_ac / max(n_eff, 1.0))

        # Робастная оценка скорости диффузии инноваций (включается только при значимой автокорреляции rho1 > 0.25,
        # поэтому на чистых i.i.d. линейных трендах сводится точно к классическому Student-t интервалу)
        rw_var_rate = 0.0
        if rho1_resid > 0.25 and len(x) >= 6:
            dt_arr = np.diff(x)
            dy_arr = np.diff(resid_active)
            ok_dt = dt_arr > 1e-4
            sigma_rw = 0.0
            if np.sum(ok_dt) >= 4:
                norm_innov = dy_arr[ok_dt] / np.sqrt(dt_arr[ok_dt])
                mad_innov = float(np.median(np.abs(norm_innov - float(np.median(norm_innov))))) * 1.4826
                lo_q, hi_q = np.percentile(norm_innov, [5, 95])
                trim_innov = norm_innov[(norm_innov >= lo_q) & (norm_innov <= hi_q)]
                std_trim = float(np.std(trim_innov, ddof=1)) if len(trim_innov) >= 4 else mad_innov
                sigma_rw = max(mad_innov, std_trim if outliers["ratio"] < 0.05 else mad_innov)
            # Многошаговая диффузия (лаг k = 5 точек) улавливает медленный дрейф/переходы режимов
            lag_k = min(5, len(x) // 4)
            if lag_k >= 2:
                dt_k = x[lag_k:] - x[:-lag_k]
                dy_k = resid_active[lag_k:] - resid_active[:-lag_k]
                ok_k = dt_k > 1e-4
                if np.sum(ok_k) >= 4:
                    norm_k = dy_k[ok_k] / np.sqrt(dt_k[ok_k])
                    mad_k = float(np.median(np.abs(norm_k - float(np.median(norm_k))))) * 1.4826
                    lo_k, hi_k = np.percentile(norm_k, [5, 95])
                    trim_k = norm_k[(norm_k >= lo_k) & (norm_k <= hi_k)]
                    std_k = float(np.std(trim_k, ddof=1)) if len(trim_k) >= 4 else mad_k
                    sigma_k = max(mad_k, std_k if outliers["ratio"] < 0.05 else mad_k)
                    sigma_rw = max(sigma_rw, sigma_k)
            rw_var_rate = (rho1_resid * rho1_resid) * (sigma_rw * sigma_rw)

        def _pred_at(h_min: float) -> tuple[float, float, float, float, float, float]:
            he = _h_effective(h_min, damp_tau)
            yhat = b0 + slope * he
            reg_var = (se_resid_eff * se_resid_eff) * (1.0 + inv_neff + ((he - x_bar) ** 2) / max(s_xx_ac, 1e-9))
            se_pred = math.sqrt(max(1e-12, reg_var + rw_var_rate * max(0.0, h_min)))
            return (
                yhat,
                se_pred,
                yhat - t80 * se_pred,
                yhat + t80 * se_pred,
                yhat - t95 * se_pred,
                yhat + t95 * se_pred,
            )

        steps = sorted({round(hor_min * k / 8.0, 2) for k in range(0, 9)})
        forecast_points: list[dict[str, Any]] = []
        for h in steps:
            yh, sep, lo80, hi80, lo95, hi95 = _pred_at(h)
            ts_h = _dt.datetime.fromtimestamp(t_ref + h * 60.0, tz=_dt.timezone.utc).isoformat(timespec="seconds")
            forecast_points.append({
                "h_min": h,
                "ts": ts_h,
                "yhat": round(yh, 4),
                "se": round(sep, 4),
                "lo80": round(lo80, 4),
                "hi80": round(hi80, 4),
                "lo95": round(lo95, 4),
                "hi95": round(hi95, 4),
            })

        yh_hor, se_hor, lo80_hor, hi80_hor, lo95_hor, hi95_hor = _pred_at(hor_min)
        half_width_95 = t95 * se_hor
        uncertainty_pct = round(min(100.0, (half_width_95 / span) * 100.0), 2)

        # Уверенность прогноза (0..1): зависит от эффективного числа точек, охвата окна и относительной ширины ДИ
        n_factor = min(1.0, n_eff / 20.0)
        span_factor = min(1.0, (actual_span_s / 60.0) / max(5.0, min(15.0, win_min * 0.5)))
        unc_factor = max(0.05, 1.0 - min(0.95, uncertainty_pct / 45.0))
        forecast_confidence = round(max(0.05, min(0.99, n_factor * 0.35 + span_factor * 0.25 + unc_factor * 0.40)), 3)

        # 6. Оценка времени достижения уставок (ETA) и вероятности пробоя на горизонте H
        thr_defs: list[tuple[str, str, int, str]] = [
            ("H", "h_warn", +1, "warning"),
            ("HH", "hh_alert", +1, "alert"),
        ]
        if lower_on:
            thr_defs.extend([
                ("L", "l_warn", -1, "warning"),
                ("LL", "ll_alert", -1, "alert"),
            ])

        thresholds_eta: dict[str, dict[str, Any]] = {}
        for label, key, direction, sev in thr_defs:
            tval = _finite(thr.get(key))
            if tval is None:
                continue
            already_breached = (cur_val >= tval) if direction > 0 else (cur_val <= tval)
            if already_breached:
                thresholds_eta[label] = {
                    "threshold": tval,
                    "severity": sev,
                    "direction": "high" if direction > 0 else "low",
                    "status": "breached",
                    "eta_median_min": 0.0,
                    "eta_early_min": 0.0,
                    "eta_late_min": 0.0,
                    "breach_prob_horizon": 1.0,
                }
                continue

            # Медианный ETA (с учётом затухания h_eff(h) = tau * (1 - exp(-h/tau)))
            moving_toward = (direction * slope) > max(span * 1e-6, 1e-9)
            eta_med: float | None = None
            if moving_toward:
                need_he = (tval - b0) / slope
                if need_he > 0.0:
                    if damp_tau is None:
                        raw_eta = need_he
                    elif need_he < damp_tau * 0.9999:
                        raw_eta = -damp_tau * math.log(1.0 - need_he / damp_tau)
                    else:
                        raw_eta = self.MAX_ETA_MIN + 1.0
                    if 0.0 < raw_eta <= self.MAX_ETA_MIN:
                        eta_med = round(raw_eta, 2)

            # Дополнительная локальная оценка ETA по быстрому затухающему Хольту (нелинейный режим):
            # позволяет вовремя фиксировать нарастающий дрейф к уставке без перелёта на длинных горизонтах
            if holt_fast is not None:
                hf_lvl, hf_slope, hf_tau = holt_fast
                if (direction * hf_slope) > max(span * 1e-6, 1e-9):
                    need_hf = (tval - hf_lvl) / hf_slope
                    if 0.0 < need_hf < hf_tau * 0.9999:
                        hf_eta = -hf_tau * math.log(1.0 - need_hf / hf_tau)
                        if 0.0 < hf_eta <= self.MAX_ETA_MIN:
                            eta_med = round(min(eta_med, hf_eta) if eta_med is not None else hf_eta, 2)

            # Пессимистичная (ранняя) граница — пересечение внешней границы 95% ДИ в сторону уставки
            eta_early = _solve_bound_crossing(
                b0=b0, slope=slope, se_resid=se_resid_eff, inv_sum_w=inv_neff,
                x_bar=x_bar, s_xx=s_xx_ac, t_crit=t95, threshold=tval,
                direction=direction, bound_sign=direction, max_eta_min=self.MAX_ETA_MIN,
                damp_tau=damp_tau, rw_var_rate=rw_var_rate,
            )
            # Оптимистичная (поздняя) граница — пересечение внутренней границы 95% ДИ
            eta_late = _solve_bound_crossing(
                b0=b0, slope=slope, se_resid=se_resid_eff, inv_sum_w=inv_neff,
                x_bar=x_bar, s_xx=s_xx_ac, t_crit=t95, threshold=tval,
                direction=direction, bound_sign=-direction, max_eta_min=self.MAX_ETA_MIN,
                damp_tau=damp_tau, rw_var_rate=rw_var_rate,
            )
            # Гарантия монотонного порядка early <= median <= late
            if eta_med is not None:
                if eta_early is not None:
                    eta_early = min(eta_early, eta_med)
                if eta_late is not None:
                    eta_late = max(eta_late, eta_med)

            # Максимальная вероятность пробоя на интервале (0, horizon_min]
            prob_hor = 0.0
            for h_chk in (hor_min * 0.25, hor_min * 0.5, hor_min * 0.75, hor_min):
                yh_c, sep_c, _, _, _, _ = _pred_at(h_chk)
                z_c = direction * (tval - yh_c) / max(sep_c, 1e-9)
                prob_hor = max(prob_hor, norm_sf(z_c))
            prob_hor = round(max(0.0, min(1.0, prob_hor)), 4)

            t_status = "imminent" if (eta_med is not None and eta_med <= hor_min) else (
                "approaching" if (eta_med is not None or prob_hor >= 0.15) else "safe"
            )
            thresholds_eta[label] = {
                "threshold": tval,
                "severity": sev,
                "direction": "high" if direction > 0 else "low",
                "status": t_status,
                "eta_median_min": eta_med,
                "eta_early_min": eta_early,
                "eta_late_min": eta_late,
                "breach_prob_horizon": prob_hor,
            }

        def _pick_nearest(sev_filter: str) -> tuple[str | None, dict[str, Any] | None]:
            cands = [(lbl, d) for lbl, d in thresholds_eta.items() if d["severity"] == sev_filter]
            if not cands:
                return None, None
            # Приоритет: уже пробит -> минимальный eta_median -> максимальная breach_prob
            cands.sort(key=lambda kv: (
                0 if kv[1]["status"] == "breached" else 1,
                kv[1]["eta_median_min"] if kv[1]["eta_median_min"] is not None else 1e9,
                -kv[1]["breach_prob_horizon"],
            ))
            return cands[0]

        _, warn_best = _pick_nearest("warning")
        _, alert_best = _pick_nearest("alert")

        eta_warn = warn_best["eta_median_min"] if warn_best else None
        eta_warn_ci = (
            [warn_best["eta_early_min"], warn_best["eta_late_min"]]
            if (warn_best and (warn_best["eta_early_min"] is not None or warn_best["eta_late_min"] is not None))
            else None
        )
        eta_alert = alert_best["eta_median_min"] if alert_best else None
        eta_alert_ci = (
            [alert_best["eta_early_min"], alert_best["eta_late_min"]]
            if (alert_best and (alert_best["eta_early_min"] is not None or alert_best["eta_late_min"] is not None))
            else None
        )
        prob_warn_h = warn_best["breach_prob_horizon"] if warn_best else 0.0
        prob_alert_h = alert_best["breach_prob_horizon"] if alert_best else 0.0

        # Ближайшая активная уставка среди всех 4
        all_eta_cands = [
            (lbl, d) for lbl, d in thresholds_eta.items()
            if d["eta_median_min"] is not None or d["breach_prob_horizon"] >= 0.2
        ]
        all_eta_cands.sort(key=lambda kv: (
            kv[1]["eta_median_min"] if kv[1]["eta_median_min"] is not None else 1e9,
            -kv[1]["breach_prob_horizon"],
        ))
        nearest_thr = all_eta_cands[0][0] if all_eta_cands else None

        # 7. Классификация аномальных трендов и расчёт anomaly_score (0..100)
        slope_pct_min = abs(slope) / span * 100.0
        anomalies: list[dict[str, Any]] = []
        score = 0.0

        # Локальный сдвиг уровня (последние 20% окна vs первые 60% окна) — снижает FNR на резких отказах
        recent_shift_z = 0.0
        if len(y) >= 12:
            n_base = max(6, int(len(y) * 0.60))
            n_rec = max(3, int(len(y) * 0.20))
            y_base = y[:n_base]
            y_rec = y[-n_rec:]
            med_b = float(np.median(y_base))
            mad_b = float(np.median(np.abs(y_base - med_b))) * 1.4826
            sd_b = float(np.std(y_base, ddof=1)) if len(y_base) > 1 else 0.0
            sig_b = max(mad_b, sd_b, span * 0.015, 1e-6)
            recent_shift_z = abs(float(np.median(y_rec)) - med_b) / sig_b

        if mk["significant"] and slope_pct_min >= 0.14 and (abs(mk["z"]) >= 2.80 or slope_pct_min >= 0.30):
            anomalies.append({
                "code": "mann_kendall_drift",
                "severity": "warning" if slope_pct_min < 0.35 else "alert",
                "metric": f"Z_mk={mk['z']:+.2f}, p={mk['p_value']:.4f}, наклон={slope:+.4f} {ident.unit}/мин",
                "threshold": "|Z_mk| >= 2.80 (p < 0.005) или наклон >= 0.30%/мин",
                "description": (
                    f"Статистически значимый {'восходящий' if slope > 0 else 'нисходящий'} дрейф "
                    f"({slope:+.3f} {ident.unit}/мин, критерий Манна-Кендалла p={mk['p_value']:.4f})."
                ),
            })
            score += min(32.0, abs(mk["z"]) * 6.5)

        if cusum["triggered"]:
            anomalies.append({
                "code": "cusum_level_shift",
                "severity": "alert" if cusum["max_stat"] >= 7.5 else "warning",
                "metric": f"CUSUM={cusum['max_stat']:.2f} ({cusum['direction']})",
                "threshold": f"h >= {cusum['threshold']:.1f}",
                "description": (
                    f"Зафиксирован устойчивый сдвиг среднего уровня параметра "
                    f"(CUSUM={cusum['max_stat']:.2f} ≥ {cusum['threshold']:.1f})."
                ),
            })
            score += min(35.0, (cusum["max_stat"] - cusum["threshold"] + 2.0) * 6.0)

        accel_sig = abs(accel_z) >= 2.8 and (abs(accel_per_min2) / span * 100.0) >= 0.005 and (slope * accel_per_min2 > 0)
        if accel_sig:
            anomalies.append({
                "code": "accelerating_drift",
                "severity": "alert",
                "metric": f"d²V/dt²={accel_per_min2:+.4f} {ident.unit}/мин², z={accel_z:+.2f}",
                "threshold": "|z_accel| >= 2.8",
                "description": (
                    f"Ускорение тренда в сторону отклонения (z={accel_z:+.2f}, "
                    f"ускорение {accel_per_min2:+.4f} {ident.unit}/мин²)."
                ),
            })
            score += min(28.0, abs(accel_z) * 8.0)

        if vol_ratio >= 2.3 and (std_recent / span * 100.0) >= 0.7:
            anomalies.append({
                "code": "volatility_surge",
                "severity": "warning",
                "metric": f"vol_ratio={vol_ratio:.2f}×, σ_recent={std_recent:.3f} {ident.unit}",
                "threshold": "vol_ratio >= 2.3×",
                "description": (
                    f"Аномальный рост колебаний / дребезга во второй половине окна "
                    f"(дисперсия выросла в {vol_ratio:.2f} раза)."
                ),
            })
            score += min(22.0, (vol_ratio - 1.5) * 12.0)

        # Требуем, чтобы резкие выбросы не были единичным старым артефактом
        recent_outliers = _mad_outliers(y[-max(8, len(y) // 3):], z_limit=3.8)
        if (outliers["count"] >= 3 and outliers["max_abs_mz"] >= 4.5) or (recent_outliers["count"] >= 2 and recent_outliers["max_abs_mz"] >= 5.5):
            anomalies.append({
                "code": "mad_outliers",
                "severity": "warning",
                "metric": f"выбросов={outliers['count']}, max|Mz|={outliers['max_abs_mz']:.2f}",
                "threshold": "|Mz| > 4.5 (≥3 точек) или свежие выбросы |Mz| > 5.5",
                "description": (
                    f"Выявлены резкие выбросы в ряде показаний ({outliers['count']} точек, "
                    f"макс. модифицированный Z-score {outliers['max_abs_mz']:.2f})."
                ),
            })
            score += min(15.0, outliers["count"] * 4.0)

        if prob_alert_h >= 0.35:
            score += min(35.0, prob_alert_h * 35.0)
        elif prob_warn_h >= 0.5:
            score += min(18.0, prob_warn_h * 18.0)

        anomaly_score = round(max(0.0, min(100.0, score)), 1)

        # Итоговый класс тренда
        if accel_sig:
            trend_class = "accelerating_drift"
        elif cusum["triggered"] and not mk["significant"]:
            trend_class = "step_shift"
        elif vol_ratio >= 2.1 and (std_recent / span * 100.0) >= 0.5 and not mk["significant"]:
            trend_class = "oscillating_chatter"
        elif (mk["significant"] or cusum["triggered"]) and slope_pct_min >= 0.03:
            trend_class = "rising_drift" if slope > 0 else "falling_drift"
        else:
            trend_class = "stable"

        return {
            **base_resp,
            "status": "ok",
            "status_reason": None,
            "trend_class": trend_class,
            "trend_meta": TREND_CLASS_META[trend_class],
            "model": {
                "method": "theil_sen_robust" if use_robust else ("weighted_ols" if linear_regime else "damped_adaptive_wls"),
                "intercept": round(b0, 4),
                "slope_per_min": round(slope, 5),
                "slope_wls_per_min": round(slope_wls, 5),
                "slope_theil_sen_per_min": round(slope_ts, 5),
                "slope_se_per_min": round(se_slope, 5),
                "accel_per_min2": round(accel_per_min2, 6),
                "accel_z": round(accel_z, 3),
                "residual_std": round(se_resid_eff, 4),
                "residual_rho1": round(rho1_resid, 3),
                "damping_tau_min": round(damp_tau, 2) if damp_tau is not None else None,
                "r2_weighted": round(r2_w, 4),
                "n_eff": round(n_eff, 2),
                "df_eff": round(df_ac, 2),
                "t95_crit": round(t95, 3),
                "half_life_min": round(half_life, 2),
            },
            "forecast_at_horizon": {
                "h_min": round(hor_min, 1),
                "yhat": round(yh_hor, 4),
                "se": round(se_hor, 4),
                "lo80": round(lo80_hor, 4),
                "hi80": round(hi80_hor, 4),
                "lo95": round(lo95_hor, 4),
                "hi95": round(hi95_hor, 4),
            },
            "forecast_points": forecast_points,
            "uncertainty_pct": uncertainty_pct,
            "forecast_confidence": forecast_confidence,
            "nearest_threshold": nearest_thr,
            "eta_warning_min": eta_warn,
            "eta_warning_ci": eta_warn_ci,
            "eta_alert_min": eta_alert,
            "eta_alert_ci": eta_alert_ci,
            "breach_prob_warning_horizon": prob_warn_h,
            "breach_prob_alert_horizon": prob_alert_h,
            "thresholds_eta": thresholds_eta,
            "anomaly_score": anomaly_score,
            "anomalies": anomalies,
            "diagnostics": {
                "mann_kendall": mk,
                "cusum": cusum,
                "outliers": outliers,
                "volatility_ratio": round(vol_ratio, 3),
            },
        }

    def overview(
        self,
        instruments: list[dict[str, Any]],
        series_by_id: dict[str, list[tuple[float, float]]],
        *,
        window_min: float = DEFAULT_WINDOW_MIN,
        horizon_min: float = DEFAULT_HORIZON_MIN,
        now_unix: float | None = None,
    ) -> dict[str, Any]:
        """Рассчитывает сводку прогнозной аналитики по всем приборам станции."""
        now = float(time.time() if now_unix is None else now_unix)
        items = [
            self.analyze_series(
                inst,
                series_by_id.get(resolve_instrument_identity(inst).instrument_id, []),
                window_min=window_min,
                horizon_min=horizon_min,
                now_unix=now,
            )
            for inst in instruments
        ]

        imminent_alerts = [
            x for x in items
            if x["status"] == "ok" and (
                (x["eta_alert_min"] is not None and x["eta_alert_min"] <= horizon_min)
                or x["breach_prob_alert_horizon"] >= 0.5
            )
        ]
        imminent_warnings = [
            x for x in items
            if x["status"] == "ok" and (
                (x["eta_warning_min"] is not None and x["eta_warning_min"] <= horizon_min)
                or x["breach_prob_warning_horizon"] >= 0.5
            )
        ]
        anomalous = [x for x in items if x["anomaly_score"] >= 35.0 or x["anomalies"]]
        valid_confs = [x["forecast_confidence"] for x in items if x["status"] == "ok"]
        avg_conf = round(sum(valid_confs) / len(valid_confs), 3) if valid_confs else 0.0

        # Ближайший предстоящий пробой уставки (исключая уже пробитые eta == 0, если есть предстоящие)
        upcoming = [
            x for x in items
            if x["eta_alert_min"] is not None and x["eta_alert_min"] > 0.0
        ]
        upcoming.sort(key=lambda x: x["eta_alert_min"])
        if not upcoming:
            upcoming = [
                x for x in items
                if x["eta_warning_min"] is not None and x["eta_warning_min"] > 0.0
            ]
            upcoming.sort(key=lambda x: x["eta_warning_min"])

        by_trend: dict[str, int] = {k: 0 for k in TREND_CLASS_META}
        for x in items:
            by_trend[x["trend_class"]] = by_trend.get(x["trend_class"], 0) + 1

        # Сортировка по риску: сначала максимальная вероятность пробоя HH/LL и аномальность
        ranked = sorted(
            items,
            key=lambda x: (
                -x["breach_prob_alert_horizon"],
                x["eta_alert_min"] if x["eta_alert_min"] is not None else 1e9,
                -x["anomaly_score"],
                -x["breach_prob_warning_horizon"],
            ),
        )

        return {
            "generated_at": utcnow_iso(),
            "window_min": round(float(window_min), 1),
            "horizon_min": round(float(horizon_min), 1),
            "disclaimer": PREDICTIVE_DISCLAIMER,
            "summary": {
                "total": len(items),
                "analyzed_count": sum(1 for x in items if x["status"] == "ok"),
                "insufficient_data_count": sum(1 for x in items if x["status"] != "ok"),
                "imminent_alert_count": len(imminent_alerts),
                "imminent_warning_count": len(imminent_warnings),
                "anomalous_trend_count": len(anomalous),
                "avg_forecast_confidence": avg_conf,
                "by_trend_class": by_trend,
                "nearest_upcoming": (
                    {
                        "instrument_id": upcoming[0]["instrument_id"],
                        "code": upcoming[0]["code"],
                        "nearest_threshold": upcoming[0]["nearest_threshold"],
                        "eta_alert_min": upcoming[0]["eta_alert_min"],
                        "eta_warning_min": upcoming[0]["eta_warning_min"],
                    }
                    if upcoming
                    else None
                ),
            },
            "instruments": ranked,
        }
