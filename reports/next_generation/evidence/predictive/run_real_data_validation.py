"""
Независимая воспроизводимая валидация модуля Predictive Analytics на 4 открытых
научных датасетах реальных промышленных временных рядов:
  1. SKAB (Skoltech Water Pump / Valve Loop, 1 Гц, AGPL-3.0): Pressure, Thermocouple, Volume Flow.
  2. UCI 447 Hydraulic Systems (ZeMA Hydraulic Test Rig, 60 с/цикл, CC BY 4.0): TS1..TS4, PS1..PS5, FS1..FS2.
  3. UCI 791 MetroPT-3 Air Compressor APU (Porto Metro, агрегация 1 мин, CC BY 4.0): TP3, Reservoirs, Oil_temperature.
  4. UCI 551 Gas Turbine Power Plant (2011–2015, 1 ч/шаг, CC BY 4.0): TIT, TAT, CDP, GTEP.

Методология:
  • Жёсткое разделение DEV vs LOCKED TEST по времени и физическим объектам/датчикам,
    зафиксированное ДО любых улучшений модели.
  • Rolling-origin backtesting на нескольких горизонтах (5, 15, 30, 60 шагов).
  • Сравнение с 5 честными baseline: Naive Persistence, OLS Linear, SES, Holt Linear, Damped Holt.
  • Метрики: MAE, RMSE, NMAE (% шкалы), NRMSE (% шкалы), фактическое покрытие PI80 / PI95,
    ширина PI95 (% шкалы), точность ETA до уставок, FAR, FNR (пропущенные события), Lead Time.
  • Стресс-тесты: шум (+3% шкалы), пропуски 30%, выбросы CV (10% × +25% шкалы), неравномерный шаг.

Запуск:
  python run_real_data_validation.py --split dev --tag baseline_dev
  python run_real_data_validation.py --split test --tag final_locked_test
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.predictive_analytics import PredictiveAnalyzer, norm_sf  # noqa: E402

DATA_ROOT = Path(r"C:\Hakatons\gv_analytics_datasets\extracted")
OUT_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Baseline-модели (строго на окне истории [t_0 .. t_now], без утечки будущего)
# ---------------------------------------------------------------------------
def _baseline_naive(x: np.ndarray, y: np.ndarray, h: float) -> tuple[float, float, float, float, float]:
    """Наивный прогноз последнего значения + PI по дифференциальному шуму sqrt(h / dt)."""
    yhat = float(y[-1])
    diffs = np.diff(y)
    dt = np.diff(x)
    valid = dt > 1e-6
    if np.sum(valid) >= 3:
        # Случайное блуждание: std(dy / sqrt(dt)) * sqrt(h)
        step_sigma = float(np.std(diffs[valid] / np.sqrt(dt[valid]), ddof=1))
        se = max(step_sigma * math.sqrt(max(h, 1e-3)), float(np.std(y)) * 0.05, 1e-6)
    else:
        se = max(float(np.std(y)), 1e-6)
    return yhat, yhat - 1.2816 * se, yhat + 1.2816 * se, yhat - 1.96 * se, yhat + 1.96 * se


def _baseline_ols(x: np.ndarray, y: np.ndarray, h: float) -> tuple[float, float, float, float, float]:
    """Классическая невзвешенная линейная регрессия OLS."""
    n = len(x)
    xm = float(np.mean(x))
    ym = float(np.mean(y))
    dx = x - xm
    sxx = float(np.sum(dx * dx))
    slope = float(np.sum(dx * (y - ym)) / sxx) if sxx > 1e-9 else 0.0
    b0 = ym - slope * xm
    resid = y - (b0 + slope * x)
    se_r = math.sqrt(float(np.sum(resid * resid)) / max(1, n - 2))
    se = max(se_r * math.sqrt(1.0 + 1.0 / n + ((h - xm) ** 2) / max(sxx, 1e-9)), 1e-6)
    yhat = b0 + slope * h
    return yhat, yhat - 1.2816 * se, yhat + 1.2816 * se, yhat - 1.96 * se, yhat + 1.96 * se


def _baseline_ses(x: np.ndarray, y: np.ndarray, h: float, alpha: float = 0.25) -> tuple[float, float, float, float, float]:
    """Простое экспоненциальное сглаживание (SES)."""
    level = float(y[0])
    errs: list[float] = []
    for val in y[1:]:
        errs.append(float(val) - level)
        level = alpha * float(val) + (1.0 - alpha) * level
    s1 = float(np.std(errs, ddof=1)) if len(errs) > 2 else max(float(np.std(y)), 1e-6)
    dt_med = max(float(np.median(np.diff(x))), 1e-3) if len(x) > 1 else 1.0
    steps_h = max(1.0, h / dt_med)
    se = max(s1 * math.sqrt(1.0 + (alpha * alpha) * max(0.0, steps_h - 1.0)), 1e-6)
    return level, level - 1.2816 * se, level + 1.2816 * se, level - 1.96 * se, level + 1.96 * se


def _baseline_holt(
    x: np.ndarray, y: np.ndarray, h: float, *, alpha: float = 0.30, beta: float = 0.10, phi: float = 1.0
) -> tuple[float, float, float, float, float]:
    """Двойное экспоненциальное сглаживание Хольта (линейное при phi=1.0 или затухающее при phi<1.0)."""
    dt_med = max(float(np.median(np.diff(x))), 1e-3) if len(x) > 1 else 1.0
    level = float(y[0])
    trend = float(y[1] - y[0]) if len(y) > 1 else 0.0
    errs: list[float] = []
    for val in y[1:]:
        pred = level + phi * trend
        errs.append(float(val) - pred)
        prev_l = level
        level = alpha * float(val) + (1.0 - alpha) * pred
        trend = beta * (level - prev_l) + (1.0 - beta) * phi * trend
    steps_h = max(1.0, h / dt_med)
    if abs(1.0 - phi) < 1e-6:
        phi_sum = steps_h
    else:
        phi_sum = phi * (1.0 - (phi ** steps_h)) / (1.0 - phi)
    yhat = level + phi_sum * trend
    s1 = float(np.std(errs, ddof=1)) if len(errs) > 2 else max(float(np.std(y)), 1e-6)
    # Асимптотический рост дисперсии с горизонтом
    var_mult = 1.0
    acc = 0.0
    for j in range(1, int(min(200, max(1, round(steps_h))))):
        acc += (phi ** j)
        cj = alpha + alpha * beta * acc
        var_mult += cj * cj
    se = max(s1 * math.sqrt(var_mult), 1e-6)
    return yhat, yhat - 1.2816 * se, yhat + 1.2816 * se, yhat - 1.96 * se, yhat + 1.96 * se


# ---------------------------------------------------------------------------
# Загрузчики реальных датасетов (строгое разделение DEV / LOCKED TEST)
# ---------------------------------------------------------------------------
def load_skab_series(split: str) -> list[dict[str, Any]]:
    """
    SKAB: 1 Гц -> перемасштабируем 1 с -> 1 шаг анализа (эквивалентно 1 мин для API окна),
    с сохранением физической последовательности и точных меток `anomaly` / `changepoint`.
    """
    base = DATA_ROOT / "skab" / "SKAB-master" / "data"
    files: list[tuple[str, Path]] = []
    if split == "dev":
        for i in range(0, 8):
            p = base / "valve1" / f"{i}.csv"
            if p.is_file():
                files.append((f"skab_v1_{i}", p))
        for i in range(1, 8):
            p = base / "other" / f"{i}.csv"
            if p.is_file():
                files.append((f"skab_oth_{i}", p))
        af = base / "anomaly-free" / "anomaly-free.csv"
        if af.is_file():
            files.append(("skab_norm_dev", af))
    else:
        for i in range(8, 16):
            p = base / "valve1" / f"{i}.csv"
            if p.is_file():
                files.append((f"skab_v1_{i}", p))
        for i in range(0, 4):
            p = base / "valve2" / f"{i}.csv"
            if p.is_file():
                files.append((f"skab_v2_{i}", p))
        for i in range(8, 15):
            p = base / "other" / f"{i}.csv"
            if p.is_file():
                files.append((f"skab_oth_{i}", p))
        af = base / "anomaly-free" / "anomaly-free.csv"
        if af.is_file():
            files.append(("skab_norm_test", af))

    sensors = [
        ("Pressure", "pressure", "бар"),
        ("Thermocouple", "temperature", "°C"),
        ("Volume Flow RateRMS", "flow", "л/мин"),
    ]
    out: list[dict[str, Any]] = []
    for run_id, fp in files:
        with fp.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f, delimiter=";")
            rows = list(rdr)
        if run_id == "skab_norm_dev":
            rows = rows[: len(rows) // 2]
        elif run_id == "skab_norm_test":
            rows = rows[len(rows) // 2 :]
        if len(rows) < 160:
            continue
        anoms = np.array([float(r.get("anomaly", 0.0) or 0.0) for r in rows], dtype=float)
        # 1 шаг = 60 с в модельном времени (реальный интервал SKAB = 1 с -> горизонт 5..60 с)
        ts = np.arange(len(rows), dtype=float) * 60.0 + 1_700_000_000.0
        for col, gtype, unit in sensors:
            vals = np.array([float(r[col]) for r in rows], dtype=float)
            if not np.all(np.isfinite(vals)):
                continue
            v_lo, v_hi = float(np.percentile(vals, 1)), float(np.percentile(vals, 99))
            span = max(v_hi - v_lo, 1e-3)
            # Уставки на основе первых 200 нормальных точек запуска (или q92/q96)
            norm_mask = anoms < 0.5
            ref = vals[norm_mask] if np.sum(norm_mask) >= 50 else vals[:200]
            mu_ref = float(np.median(ref))
            sd_ref = max(float(np.std(ref)), span * 0.05)
            out.append({
                "dataset": "SKAB",
                "series_id": f"{run_id}:{col}",
                "sensor": col,
                "gauge_type": gtype,
                "unit": unit,
                "native_step_label": "1 s",
                "ts": ts,
                "values": vals,
                "anomaly": anoms,
                "v_min": float(np.min(vals)) - 0.1 * span,
                "v_max": float(np.max(vals)) + 0.1 * span,
                "thresholds": {
                    "ll_alert": mu_ref - 3.0 * sd_ref,
                    "l_warn": mu_ref - 2.0 * sd_ref,
                    "h_warn": mu_ref + 2.0 * sd_ref,
                    "hh_alert": mu_ref + 3.0 * sd_ref,
                    "lower_enabled": True,
                },
            })
    return out


def load_hydraulic_series(split: str) -> list[dict[str, Any]]:
    """
    UCI 447 Hydraulic Systems: 2205 последовательных циклов по 60 с (реальный шаг = 1 мин!).
    DEV: циклы 0..1099 на TS1, TS2, PS1, PS2, FS1.
    TEST: циклы 1100..2204 на TS3, TS4, PS3, PS5, FS2 (другое время + другие датчики!).
    """
    base = DATA_ROOT / "uci_447_hydraulic"
    prof = np.loadtxt(base / "profile.txt")
    # Аномалия = любая деградация компонента (cooler < 100 или valve < 100 или pump > 0 или accum < 130)
    anom_all = ((prof[:, 0] < 100) | (prof[:, 1] < 100) | (prof[:, 2] > 0) | (prof[:, 3] < 130)).astype(float)

    if split == "dev":
        c0, c1 = 0, 1100
        specs = [
            ("TS1", "temperature", "°C"),
            ("TS2", "temperature", "°C"),
            ("PS1", "pressure", "бар"),
            ("PS2", "pressure", "бар"),
            ("FS1", "flow", "л/мин"),
        ]
    else:
        c0, c1 = 1100, len(prof)
        specs = [
            ("TS3", "temperature", "°C"),
            ("TS4", "temperature", "°C"),
            ("PS3", "pressure", "бар"),
            ("PS5", "pressure", "бар"),
            ("FS2", "flow", "л/мин"),
        ]

    out: list[dict[str, Any]] = []
    for fname, gtype, unit in specs:
        # Среднее значение физического параметра за каждый 60-секундный цикл
        vals_list = []
        with (base / f"{fname}.txt").open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if idx < c0:
                    continue
                if idx >= c1:
                    break
                arr = np.fromstring(line, sep="\t")
                vals_list.append(float(np.mean(arr)))
        vals = np.array(vals_list, dtype=float)
        anoms = anom_all[c0:c1]
        ts = np.arange(len(vals), dtype=float) * 60.0 + 1_700_000_000.0
        span = max(float(np.max(vals) - np.min(vals)), 1e-3)
        q10, q20, q80, q90 = np.percentile(vals, [10, 20, 80, 90])
        out.append({
            "dataset": "UCI_447_Hydraulic",
            "series_id": f"hyd_{fname}_{split}",
            "sensor": fname,
            "gauge_type": gtype,
            "unit": unit,
            "native_step_label": "1 min (cycle mean)",
            "ts": ts,
            "values": vals,
            "anomaly": anoms,
            "v_min": float(np.min(vals)) - 0.1 * span,
            "v_max": float(np.max(vals)) + 0.1 * span,
            "thresholds": {
                "ll_alert": float(q10),
                "l_warn": float(q20),
                "h_warn": float(q80),
                "hh_alert": float(q90),
                "lower_enabled": True,
            },
        })
    return out


def load_metropt3_series(split: str) -> list[dict[str, Any]]:
    """
    UCI 791 MetroPT-3 (Porto Metro Air Compressor APU, 2020):
    Агрегируем до 1-минутных средних вокруг реальных рабочих окон + 4 официальных отказов Air Leak.
    DEV: февраль–май 2020 (отказы #1 2020-04-18, #2 2020-05-29..30).
    TEST: июнь–август 2020 (отказы #3 2020-06-05..07, #4 2020-07-15).
    """
    csv_path = DATA_ROOT / "uci_791_metropt3" / "MetroPT3(AirCompressor).csv"
    # Фиксированные временные окна (по 48 часов: штатные + предаварийные/аварийные периоды)
    if split == "dev":
        windows = [
            ("metro_dev_norm1", "2020-03-10 00:00:00", "2020-03-12 00:00:00"),
            ("metro_dev_fail1", "2020-04-17 12:00:00", "2020-04-19 06:00:00"),
            ("metro_dev_fail2", "2020-05-29 12:00:00", "2020-05-30 12:00:00"),
        ]
    else:
        windows = [
            ("metro_test_norm1", "2020-06-20 00:00:00", "2020-06-22 00:00:00"),
            ("metro_test_fail3", "2020-06-05 00:00:00", "2020-06-06 18:00:00"),
            ("metro_test_fail4", "2020-07-15 06:00:00", "2020-07-16 00:00:00"),
        ]

    fail_ranges = [
        ("2020-04-18 00:00:00", "2020-04-18 23:59:59"),
        ("2020-05-29 23:30:00", "2020-05-30 06:00:00"),
        ("2020-06-05 10:00:00", "2020-06-07 14:30:00"),
        ("2020-07-15 14:30:00", "2020-07-15 19:00:00"),
    ]

    buckets: dict[str, dict[str, list[tuple[float, float, float, float]]]] = {w[0]: {} for w in windows}
    with csv_path.open("r", encoding="utf-8") as f:
        hdr = f.readline().strip().split(",")
        idx_ts = hdr.index("timestamp")
        idx_tp3 = hdr.index("TP3")
        idx_res = hdr.index("Reservoirs")
        idx_oil = hdr.index("Oil_temperature")
        for line in f:
            parts = line.split(",")
            ts_s = parts[idx_ts]
            # Быстрая строковая фильтрация ISO-формата YYYY-MM-DD HH:MM:SS
            matched = None
            for wname, w0, w1 in windows:
                if w0 <= ts_s <= w1:
                    matched = wname
                    break
            if matched is None:
                continue
            minute_key = ts_s[:16]  # YYYY-MM-DD HH:MM
            is_fail = 1.0 if any(f0 <= ts_s <= f1 for f0, f1 in fail_ranges) else 0.0
            buckets[matched].setdefault(minute_key, []).append((
                float(parts[idx_tp3]),
                float(parts[idx_res]),
                float(parts[idx_oil]),
                is_fail,
            ))

    out: list[dict[str, Any]] = []
    for wname, _, _ in windows:
        mkeys = sorted(buckets[wname].keys())
        if len(mkeys) < 150:
            continue
        ts_arr = np.array([
            _dt.datetime.strptime(k, "%Y-%m-%d %H:%M").replace(tzinfo=_dt.timezone.utc).timestamp()
            for k in mkeys
        ], dtype=float)
        tp3 = np.array([np.mean([r[0] for r in buckets[wname][k]]) for k in mkeys], dtype=float)
        res = np.array([np.mean([r[1] for r in buckets[wname][k]]) for k in mkeys], dtype=float)
        oil = np.array([np.mean([r[2] for r in buckets[wname][k]]) for k in mkeys], dtype=float)
        anm = np.array([1.0 if any(r[3] > 0.5 for r in buckets[wname][k]) else 0.0 for k in mkeys], dtype=float)

        # Официальные промышленные уставки MetroPT-3 из Data Description_Metro.pdf:
        # TP3 / Reservoirs: L=8.2 bar (MPG), LL=7.0 bar (LPS); Oil_temperature: H=72 °C, HH=78 °C
        for sname, arr, gtype, unit, vmin, vmax, thr in [
            ("TP3", tp3, "pressure", "бар", 0.0, 12.0, {"ll_alert": 7.0, "l_warn": 8.2, "h_warn": 10.2, "hh_alert": 10.6, "lower_enabled": True}),
            ("Reservoirs", res, "pressure", "бар", 0.0, 12.0, {"ll_alert": 7.0, "l_warn": 8.2, "h_warn": 10.2, "hh_alert": 10.6, "lower_enabled": True}),
            ("Oil_temperature", oil, "temperature", "°C", 30.0, 100.0, {"ll_alert": 45.0, "l_warn": 50.0, "h_warn": 72.0, "hh_alert": 78.0, "lower_enabled": True}),
        ]:
            out.append({
                "dataset": "UCI_791_MetroPT3",
                "series_id": f"{wname}:{sname}",
                "sensor": sname,
                "gauge_type": gtype,
                "unit": unit,
                "native_step_label": "1 min (from 10 s)",
                "ts": ts_arr,
                "values": arr,
                "anomaly": anm,
                "v_min": vmin,
                "v_max": vmax,
                "thresholds": thr,
            })
    return out


def load_gas_turbine_series(split: str) -> list[dict[str, Any]]:
    """
    UCI 551 Gas Turbine Power Plant (2011–2015, 1 ч/шаг -> 1 шаг = 1 мин в модельном окне).
    DEV: 2011–2013 (gt_2011..2013.csv).
    TEST: 2014–2015 (gt_2014..2015.csv).
    """
    base = DATA_ROOT / "uci_551_gas_turbine"
    years = ["2011", "2012", "2013"] if split == "dev" else ["2014", "2015"]
    cols = [
        ("TIT", "temperature", "°C"),
        ("TAT", "temperature", "°C"),
        ("CDP", "pressure", "мбар"),
        ("GTEP", "pressure", "мбар"),
    ]
    out: list[dict[str, Any]] = []
    for yr in years:
        with (base / f"gt_{yr}.csv").open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        # Берём первые 2500 последовательных часов года для быстрого воспроизводимого rolling-origin
        rows = rows[:2500]
        ts = np.arange(len(rows), dtype=float) * 60.0 + 1_700_000_000.0
        for col, gtype, unit in cols:
            vals = np.array([float(r[col]) for r in rows], dtype=float)
            span = max(float(np.max(vals) - np.min(vals)), 1e-3)
            q05, q12, q88, q95 = np.percentile(vals, [5, 12, 88, 95])
            out.append({
                "dataset": "UCI_551_GasTurbine",
                "series_id": f"gt_{yr}:{col}",
                "sensor": col,
                "gauge_type": gtype,
                "unit": unit,
                "native_step_label": "1 hour",
                "ts": ts,
                "values": vals,
                "anomaly": np.zeros(len(vals), dtype=float),
                "v_min": float(np.min(vals)) - 0.05 * span,
                "v_max": float(np.max(vals)) + 0.05 * span,
                "thresholds": {
                    "ll_alert": float(q05),
                    "l_warn": float(q12),
                    "h_warn": float(q88),
                    "hh_alert": float(q95),
                    "lower_enabled": True,
                },
            })
    return out


# ---------------------------------------------------------------------------
# Rolling-Origin Backtesting Engine
# ---------------------------------------------------------------------------
def evaluate_series_collection(
    series_list: list[dict[str, Any]],
    *,
    horizons: tuple[int, ...] = (5, 15, 30, 60),
    window_steps: int = 60,
    max_origins_per_series: int = 45,
    stress_mode: str = "clean",
    seed: int = 20261127,
) -> dict[str, Any]:
    pa = PredictiveAnalyzer()
    rng = np.random.default_rng(seed)
    models = ("current_gv", "naive_last", "ols_linear", "ses", "holt_linear", "holt_damped")

    # Накопители ошибок по (dataset, horizon, model) и агрегированные по (horizon, model)
    acc: dict[tuple[str, int, str], dict[str, list[float]]] = {}
    # ETA & Threshold breach detection (на горизонте H = 30 и H = 60)
    eta_stats: dict[str, dict[str, Any]] = {
        m: {
            "tp": 0, "fp": 0, "fn": 0, "tn": 0,
            "eta_abs_errs": [], "lead_times": [],
        }
        for m in ("current_gv", "ols_linear", "holt_damped", "naive_last")
    }
    # Anomaly detection vs SKAB / MetroPT3 ground truth
    anom_eval = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "lead_times": []}

    def _bucket(ds: str, h: int, m: str) -> dict[str, list[float]]:
        key = (ds, h, m)
        if key not in acc:
            acc[key] = {"ae": [], "se": [], "nae": [], "cov80": [], "cov95": [], "w95": []}
        return acc[key]

    max_h = max(horizons)

    for s in series_list:
        ts_full = s["ts"]
        y_clean = s["values"]
        n = len(y_clean)
        span = max(float(s["v_max"] - s["v_min"]), 1e-6)
        if n < window_steps + max_h + 10:
            continue

        # Выбираем равномерно распределённые rolling origins без утечки будущего
        start_i = window_steps
        end_i = n - max_h - 1
        step_i = max(1, (end_i - start_i) // max_origins_per_series)
        origins = list(range(start_i, end_i, step_i))[:max_origins_per_series]

        inst_base = {
            "id": s["series_id"],
            "code": s["sensor"],
            "name": s["series_id"],
            "short_name": s["sensor"],
            "group": s["dataset"],
            "gauge_type": s["gauge_type"],
            "unit": s["unit"],
            "decimals": 3,
            "source_kind": "camera_cv",
            "calibration": {"v_min": s["v_min"], "v_max": s["v_max"]},
            "thresholds": s["thresholds"],
        }
        thr = s["thresholds"]

        for idx in origins:
            t_win = ts_full[idx - window_steps : idx + 1].copy()
            y_win = y_clean[idx - window_steps : idx + 1].copy()

            # Стресс-воздействия применяются ТОЛЬКО к входному окну (истина будущего y_clean не портится!)
            if stress_mode == "noise_3pct":
                y_win = y_win + rng.normal(0.0, 0.03 * span, size=len(y_win))
            elif stress_mode == "missing_30pct":
                keep = rng.random(len(y_win)) > 0.30
                keep[0] = True
                keep[-1] = True
                t_win = t_win[keep]
                y_win = y_win[keep]
            elif stress_mode == "cv_outliers_10pct":
                k_out = max(1, int(0.10 * len(y_win)))
                out_pos = rng.choice(np.arange(1, len(y_win) - 1), size=k_out, replace=False)
                signs = rng.choice([-1.0, 1.0], size=k_out)
                y_win[out_pos] += signs * (0.25 * span)
            elif stress_mode == "irregular_sampling":
                # Нерегулярные интервалы: прореживаем в неравномерные пачки
                keep = np.zeros(len(y_win), dtype=bool)
                keep[0] = True
                keep[-1] = True
                pos = 0
                while pos < len(y_win) - 1:
                    pos += int(rng.choice([1, 1, 2, 4, 6]))
                    if pos < len(y_win):
                        keep[pos] = True
                t_win = t_win[keep]
                y_win = y_win[keep]

            if len(t_win) < 8:
                continue

            now_u = float(t_win[-1])
            x_rel = (t_win - now_u) / 60.0  # минуты <= 0
            pts = list(zip(t_win.tolist(), y_win.tolist()))
            inst = {**inst_base, "reading": {"value": float(y_win[-1]), "valid": True, "level": "normal"}}

            # Запускаем нашу модель один раз на max_h и снимаем прогнозы на нужных горизонтах
            res_gv = pa.analyze_series(inst, pts, window_min=float(window_steps + 5), horizon_min=float(max_h), now_unix=now_u)
            if res_gv["status"] != "ok":
                continue

            # Извлекаем параметры модели GV для точного расчёта на каждом горизонте h
            gv_m = res_gv["model"]
            gv_b0 = float(gv_m["intercept"])
            gv_sl = float(gv_m["slope_per_min"])
            gv_se_r = float(gv_m["residual_std"])
            gv_neff = float(gv_m["n_eff"])
            gv_t95 = float(gv_m["t95_crit"])
            # Восстановим x_bar / s_xx_eff через _pred_at или прямо по forecast_points / analyze_series
            gv_by_h: dict[int, tuple[float, float, float, float, float]] = {}
            for h in horizons:
                res_h = pa.analyze_series(inst, pts, window_min=float(window_steps + 5), horizon_min=float(h), now_unix=now_u)
                fc = res_h["forecast_at_horizon"]
                gv_by_h[h] = (fc["yhat"], fc["lo80"], fc["hi80"], fc["lo95"], fc["hi95"])

            for h in horizons:
                y_true = float(y_clean[idx + h])
                h_f = float(h)
                preds = {
                    "current_gv": gv_by_h[h],
                    "naive_last": _baseline_naive(x_rel, y_win, h_f),
                    "ols_linear": _baseline_ols(x_rel, y_win, h_f),
                    "ses": _baseline_ses(x_rel, y_win, h_f),
                    "holt_linear": _baseline_holt(x_rel, y_win, h_f, phi=1.0),
                    "holt_damped": _baseline_holt(x_rel, y_win, h_f, phi=0.88),
                }
                for mname, (yh, lo80, hi80, lo95, hi95) in preds.items():
                    err = y_true - yh
                    b = _bucket(s["dataset"], h, mname)
                    b["ae"].append(abs(err))
                    b["se"].append(err * err)
                    b["nae"].append(abs(err) / span * 100.0)
                    b["cov80"].append(1.0 if lo80 <= y_true <= hi80 else 0.0)
                    b["cov95"].append(1.0 if lo95 <= y_true <= hi95 else 0.0)
                    b["w95"].append((hi95 - lo95) / span * 100.0)

            # Оценка обнаружения пробоя уставок (H / L) и ETA на горизонте H_eval = 30 шагов
            h_eval = 30
            y_now = float(y_clean[idx])
            hw, lw = thr.get("h_warn"), thr.get("l_warn")
            already_out = (hw is not None and y_now >= hw) or (lw is not None and y_now <= lw)
            if not already_out:
                fut = y_clean[idx + 1 : idx + h_eval + 1]
                true_eta: float | None = None
                for step_k, vf in enumerate(fut, start=1):
                    if (hw is not None and vf >= hw) or (lw is not None and vf <= lw):
                        true_eta = float(step_k)
                        break

                # Прогноз пробоя для current_gv
                res_30 = pa.analyze_series(inst, pts, window_min=float(window_steps + 5), horizon_min=float(h_eval), now_unix=now_u)
                gv_eta = res_30["eta_warning_min"]
                gv_prob = float(res_30["breach_prob_warning_horizon"])
                gv_warn = bool((gv_eta is not None and gv_eta <= h_eval) or gv_prob >= 0.5)

                # Прогноз пробоя для OLS, Holt Damped, Naive
                yh_ols, _, _, _, _ = _baseline_ols(x_rel, y_win, float(h_eval))
                ols_warn = bool((hw is not None and yh_ols >= hw) or (lw is not None and yh_ols <= lw))
                yh_hd, _, _, _, _ = _baseline_holt(x_rel, y_win, float(h_eval), phi=0.88)
                hd_warn = bool((hw is not None and yh_hd >= hw) or (lw is not None and yh_hd <= lw))
                yh_nv, _, _, _, _ = _baseline_naive(x_rel, y_win, float(h_eval))
                nv_warn = bool((hw is not None and yh_nv >= hw) or (lw is not None and yh_nv <= lw))

                for mname, pred_flag, pred_eta in [
                    ("current_gv", gv_warn, gv_eta),
                    ("ols_linear", ols_warn, None),
                    ("holt_damped", hd_warn, None),
                    ("naive_last", nv_warn, None),
                ]:
                    st = eta_stats[mname]
                    if true_eta is not None:
                        if pred_flag:
                            st["tp"] += 1
                            st["lead_times"].append(true_eta)
                            if pred_eta is not None:
                                st["eta_abs_errs"].append(abs(pred_eta - true_eta))
                        else:
                            st["fn"] += 1
                    else:
                        if pred_flag:
                            st["fp"] += 1
                        else:
                            st["tn"] += 1

            # Оценка детектора аномальных трендов на размеченных датасетах (SKAB, MetroPT3)
            if s["dataset"] in ("SKAB", "UCI_791_MetroPT3"):
                win_anom = bool(np.any(s["anomaly"][max(0, idx - 15) : idx + 1] > 0.5))
                det_anom = bool(res_gv["anomaly_score"] >= 35.0 or len(res_gv["anomalies"]) > 0)
                if win_anom:
                    if det_anom:
                        anom_eval["tp"] += 1
                    else:
                        anom_eval["fn"] += 1
                else:
                    if det_anom:
                        anom_eval["fp"] += 1
                    else:
                        anom_eval["tn"] += 1

    # Сводка метрик
    per_ds_rows: list[dict[str, Any]] = []
    overall_by_hm: dict[tuple[int, str], dict[str, list[float]]] = {}
    for (ds, h, m), d in sorted(acc.items()):
        n_obs = len(d["ae"])
        if n_obs == 0:
            continue
        row = {
            "dataset": ds,
            "horizon": h,
            "model": m,
            "n_origins": n_obs,
            "mae": round(float(np.mean(d["ae"])), 5),
            "rmse": round(math.sqrt(float(np.mean(d["se"]))), 5),
            "nmae_pct": round(float(np.mean(d["nae"])), 3),
            "nrmse_pct": round(math.sqrt(float(np.mean(np.array(d["nae"]) ** 2))), 3),
            "pi80_cov_pct": round(float(np.mean(d["cov80"])) * 100.0, 2),
            "pi95_cov_pct": round(float(np.mean(d["cov95"])) * 100.0, 2),
            "pi95_width_pct": round(float(np.mean(d["w95"])), 2),
        }
        per_ds_rows.append(row)
        ov = overall_by_hm.setdefault((h, m), {"nae": [], "cov80": [], "cov95": [], "w95": []})
        ov["nae"].extend(d["nae"])
        ov["cov80"].extend(d["cov80"])
        ov["cov95"].extend(d["cov95"])
        ov["w95"].extend(d["w95"])

    overall_rows: list[dict[str, Any]] = []
    for (h, m), d in sorted(overall_by_hm.items()):
        overall_rows.append({
            "horizon": h,
            "model": m,
            "n_origins": len(d["nae"]),
            "nmae_pct": round(float(np.mean(d["nae"])), 3),
            "nrmse_pct": round(math.sqrt(float(np.mean(np.array(d["nae"]) ** 2))), 3),
            "pi80_cov_pct": round(float(np.mean(d["cov80"])) * 100.0, 2),
            "pi95_cov_pct": round(float(np.mean(d["cov95"])) * 100.0, 2),
            "pi95_width_pct": round(float(np.mean(d["w95"])), 2),
        })

    eta_summary: dict[str, Any] = {}
    for m, st in eta_stats.items():
        tp, fp, fn, tn = st["tp"], st["fp"], st["fn"], st["tn"]
        eta_summary[m] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "recall_pct": round(tp / max(1, tp + fn) * 100.0, 2),
            "fnr_missed_pct": round(fn / max(1, tp + fn) * 100.0, 2),
            "far_false_alarm_pct": round(fp / max(1, fp + tn) * 100.0, 2),
            "precision_pct": round(tp / max(1, tp + fp) * 100.0, 2),
            "eta_mae_steps": round(float(np.mean(st["eta_abs_errs"])), 2) if st["eta_abs_errs"] else None,
            "eta_median_ae_steps": round(float(np.median(st["eta_abs_errs"])), 2) if st["eta_abs_errs"] else None,
            "mean_lead_time_steps": round(float(np.mean(st["lead_times"])), 2) if st["lead_times"] else None,
        }

    atp, afp, afn, atn = anom_eval["tp"], anom_eval["fp"], anom_eval["fn"], anom_eval["tn"]
    anom_summary = {
        "tp": atp, "fp": afp, "fn": afn, "tn": atn,
        "recall_pct": round(atp / max(1, atp + afn) * 100.0, 2),
        "far_pct": round(afp / max(1, afp + atn) * 100.0, 2),
        "precision_pct": round(atp / max(1, atp + afp) * 100.0, 2),
        "f1_pct": round(2 * atp / max(1, 2 * atp + afp + afn) * 100.0, 2),
    }

    return {
        "stress_mode": stress_mode,
        "series_count": len(series_list),
        "overall_by_horizon": overall_rows,
        "per_dataset": per_ds_rows,
        "threshold_breach_eta_h30": eta_summary,
        "anomaly_detection_labeled": anom_summary,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--with-stress", action="store_true")
    args = ap.parse_args()

    t0 = time.perf_counter()
    series = (
        load_skab_series(args.split)
        + load_hydraulic_series(args.split)
        + load_metropt3_series(args.split)
        + load_gas_turbine_series(args.split)
    )
    print(f"Loaded {len(series)} real industrial series for split={args.split} in {time.perf_counter()-t0:.2f}s", flush=True)
    by_ds: dict[str, int] = {}
    for s in series:
        by_ds[s["dataset"]] = by_ds.get(s["dataset"], 0) + 1
    print("Series per dataset:", by_ds, flush=True)

    clean_res = evaluate_series_collection(series, stress_mode="clean")
    stress_results: dict[str, Any] = {}
    if args.with_stress:
        for sm in ("noise_3pct", "missing_30pct", "cv_outliers_10pct", "irregular_sampling"):
            print(f"Running stress={sm} ...", flush=True)
            stress_results[sm] = evaluate_series_collection(series, horizons=(15, 30), max_origins_per_series=25, stress_mode=sm)

    payload = {
        "split": args.split,
        "tag": args.tag,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "series_per_dataset": by_ds,
        "clean": clean_res,
        "stress": stress_results,
    }
    out_json = OUT_DIR / f"predictive_validation_{args.tag}.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV сводка по горизонтам и моделям
    out_csv = OUT_DIR / f"predictive_summary_{args.tag}.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        rows = clean_res["overall_by_horizon"]
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n=== OVERALL BY HORIZON (clean) ===")
    for r in clean_res["overall_by_horizon"]:
        print(
            f"H={r['horizon']:2d} | {r['model']:12s} | NMAE={r['nmae_pct']:6.3f}% | NRMSE={r['nrmse_pct']:6.3f}% | "
            f"PI80={r['pi80_cov_pct']:5.1f}% | PI95={r['pi95_cov_pct']:5.1f}% (w={r['pi95_width_pct']:5.1f}%)"
        )
    print("\n=== THRESHOLD BREACH & ETA (H=30) ===")
    print(json.dumps(clean_res["threshold_breach_eta_h30"], ensure_ascii=False, indent=2))
    print("\n=== ANOMALY DETECTION (SKAB + MetroPT3) ===")
    print(json.dumps(clean_res["anomaly_detection_labeled"], ensure_ascii=False, indent=2))
    print(f"\nSaved to {out_json}")


if __name__ == "__main__":
    main()
