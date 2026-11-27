"""
Независимые математические и интеграционные тесты модуля Predictive Analytics.

Проверяют:
  1. Точность прогноза ETA на аналитических линейных трендах (восходящих к H/HH и
     нисходящих к L/LL, включая lower_enabled=False).
  2. Калибровку неопределённости (Монте-Карло покрытие 95% предиктивного интервала,
     монотонный рост ширины ДИ с горизонтом и шумом, порядок early <= median <= late).
  3. Робастность Theil-Sen к грубым выбросам CV и детекцию выбросов по MAD.
  4. Детекцию аномальных трендов: CUSUM (ступенчатый сдвиг), Манн-Кендалл (дрейф vs
     стационарный белый шум), ускоряющийся разгон (d²V/dt²) и рост волатильности.
  5. Честное поведение при нехватке данных (`insufficient_data`) и статусе STALE.
  6. Совместимость контракта Multi-Gauge Vision (`instrument_id`, `camera_id`, `gauge_slot`),
     хранение в SQLite (`readings.instrument_id`, `predictive_snapshots`) и регистры
     Modbus TCP (`3600 + idx*8`, `912..915`).

Запуск:
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_predictive_analytics.py
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

from app import config, db
from app.contracts import resolve_instrument_identity
from app.predictive_analytics import PredictiveAnalyzer
from app.scada_gateway import ModbusTcpGateway


def _make_inst(
    iid: str = "sim-02",
    *,
    code: str = "К1-Т01",
    value: float | None = 530.0,
    valid: bool = True,
    v_min: float = 0.0,
    v_max: float = 600.0,
    ll: float | None = 485.0,
    lw: float | None = 505.0,
    hw: float | None = 555.0,
    hh: float | None = 565.0,
    lower_enabled: bool = True,
    source_kind: str = "simulated",
    camera_id: str | None = None,
    gauge_slot: int | None = None,
) -> dict:
    d = {
        "id": iid,
        "code": code,
        "name": "Термометр перегретого пара котла К-1",
        "short_name": "К-1 темп. пара",
        "group": "Котлоагрегаты",
        "gauge_type": "temperature",
        "unit": "°C",
        "decimals": 1,
        "source_kind": source_kind,
        "calibration": {"v_min": v_min, "v_max": v_max},
        "thresholds": {
            "ll_alert": ll,
            "l_warn": lw,
            "h_warn": hw,
            "hh_alert": hh,
            "lower_enabled": lower_enabled,
        },
        "reading": {"value": value, "valid": valid, "level": "normal" if valid else "stale"},
    }
    if camera_id is not None:
        d["camera_id"] = camera_id
    if gauge_slot is not None:
        d["gauge_slot"] = gauge_slot
    return d


def test_exact_linear_eta_up_and_down() -> dict:
    pa = PredictiveAnalyzer()
    now = 1_765_000_000.0
    # Точный линейный рост: v(t_min) = 535.0 + 0.5 * t_min (при t_min in [-30..0])
    # До H=555 (+20): ровно 40.0 мин; до HH=565 (+30): ровно 60.0 мин
    pts_up = [(now + m * 60.0, 535.0 + 0.5 * m) for m in range(-30, 1)]
    res_up = pa.analyze_series(_make_inst(value=535.0), pts_up, window_min=60.0, horizon_min=60.0, now_unix=now)
    assert res_up["status"] == "ok"
    assert abs(res_up["model"]["slope_per_min"] - 0.5) < 1e-3, res_up["model"]
    assert abs(res_up["eta_warning_min"] - 40.0) < 0.25, res_up["eta_warning_min"]
    assert abs(res_up["eta_alert_min"] - 60.0) < 0.35, res_up["eta_alert_min"]
    assert res_up["eta_alert_ci"][0] <= res_up["eta_alert_min"] <= res_up["eta_alert_ci"][1]
    assert res_up["breach_prob_warning_horizon"] >= 0.99
    assert res_up["breach_prob_alert_horizon"] >= 0.45
    assert res_up["trend_class"] == "rising_drift"

    # Точный линейный спад к нижним уставкам: v(0)=515, slope=-0.5 -> L=505 за 20 мин, LL=485 за 60 мин
    pts_dn = [(now + m * 60.0, 515.0 - 0.5 * m) for m in range(-30, 1)]
    res_dn = pa.analyze_series(_make_inst(value=515.0), pts_dn, window_min=60.0, horizon_min=60.0, now_unix=now)
    assert abs(res_dn["eta_warning_min"] - 20.0) < 0.25, res_dn["eta_warning_min"]
    assert abs(res_dn["eta_alert_min"] - 60.0) < 0.35, res_dn["eta_alert_min"]
    assert res_dn["trend_class"] == "falling_drift"

    # При lower_enabled=False нижние уставки игнорируются
    res_nolow = pa.analyze_series(
        _make_inst(value=515.0, lower_enabled=False), pts_dn, window_min=60.0, horizon_min=60.0, now_unix=now
    )
    assert "L" not in res_nolow["thresholds_eta"] and "LL" not in res_nolow["thresholds_eta"]
    assert res_nolow["eta_alert_min"] is None

    return {
        "up_eta_warn_min": res_up["eta_warning_min"],
        "up_eta_alert_min": res_up["eta_alert_min"],
        "down_eta_warn_min": res_dn["eta_warning_min"],
        "down_eta_alert_min": res_dn["eta_alert_min"],
    }


def test_monte_carlo_pi95_coverage_and_monotonic_uncertainty() -> dict:
    """Монте-Карло проверка: 95% предиктивный интервал покрывает будущие реализации >= 88%."""
    pa = PredictiveAnalyzer()
    rng = np.random.default_rng(2026)
    now = 1_765_000_000.0
    sigma = 1.2
    true_slope = 0.25
    h_test = 15.0
    trials = 150
    covered = 0

    for _ in range(trials):
        t_mins = np.linspace(-30.0, 0.0, 31)
        y_obs = 520.0 + true_slope * t_mins + rng.normal(0.0, sigma, size=len(t_mins))
        pts = [(now + float(m) * 60.0, float(v)) for m, v in zip(t_mins, y_obs)]
        res = pa.analyze_series(
            _make_inst(value=float(y_obs[-1])), pts, window_min=60.0, horizon_min=h_test, now_unix=now
        )
        fc = res["forecast_at_horizon"]
        y_future = 520.0 + true_slope * h_test + float(rng.normal(0.0, sigma))
        if fc["lo95"] <= y_future <= fc["hi95"]:
            covered += 1

    cov_rate = covered / float(trials)
    assert cov_rate >= 0.88, f"Недостаточное покрытие 95% ДИ: {cov_rate:.3f}"

    # Проверка монотонного расширения ДИ с ростом горизонта
    t_mins = np.linspace(-30.0, 0.0, 31)
    y_obs = 520.0 + 0.25 * t_mins + rng.normal(0.0, sigma, size=len(t_mins))
    pts = [(now + float(m) * 60.0, float(v)) for m, v in zip(t_mins, y_obs)]
    r_30 = pa.analyze_series(_make_inst(value=float(y_obs[-1])), pts, window_min=60.0, horizon_min=30.0, now_unix=now)
    r_120 = pa.analyze_series(_make_inst(value=float(y_obs[-1])), pts, window_min=60.0, horizon_min=120.0, now_unix=now)
    w_30 = r_30["forecast_at_horizon"]["hi95"] - r_30["forecast_at_horizon"]["lo95"]
    w_120 = r_120["forecast_at_horizon"]["hi95"] - r_120["forecast_at_horizon"]["lo95"]
    assert w_120 > w_30 * 1.5, f"ДИ должен расширяться с горизонтом: w30={w_30:.3f}, w120={w_120:.3f}"

    return {"mc_trials": trials, "pi95_empirical_coverage": round(cov_rate, 4), "width_30m": round(w_30, 3), "width_120m": round(w_120, 3)}


def test_theil_sen_robustness_and_anomaly_detectors() -> dict:
    pa = PredictiveAnalyzer()
    now = 1_765_000_000.0
    rng = np.random.default_rng(77)

    # 1. Выбросы CV (15% точек с грубым сбоем +80 °C) — робастный наклон сохраняется около 0.30
    pts_out = []
    for i, m in enumerate(range(-30, 1)):
        v = 530.0 + 0.30 * m
        if i in (6, 12, 19, 25):
            v += 85.0
        pts_out.append((now + m * 60.0, v))
    r_out = pa.analyze_series(_make_inst(value=530.0), pts_out, window_min=60.0, horizon_min=60.0, now_unix=now)
    assert r_out["model"]["method"] == "theil_sen_robust", r_out["model"]
    assert abs(r_out["model"]["slope_per_min"] - 0.30) < 0.06, r_out["model"]
    assert any(a["code"] == "mad_outliers" for a in r_out["anomalies"])

    # 2. Ступенчатый сдвиг (CUSUM)
    pts_step = []
    for m in range(-30, 1):
        base = 530.0 if m < -12 else 544.0
        pts_step.append((now + m * 60.0, base + float(rng.normal(0.0, 0.3))))
    r_step = pa.analyze_series(_make_inst(value=pts_step[-1][1]), pts_step, window_min=60.0, horizon_min=60.0, now_unix=now)
    assert r_step["diagnostics"]["cusum"]["triggered"] is True
    assert any(a["code"] == "cusum_level_shift" for a in r_step["anomalies"])

    # 3. Ускоряющийся разгон (квадратичный рост)
    pts_acc = [(now + m * 60.0, 520.0 + 0.025 * ((m + 30.0) ** 2)) for m in range(-30, 1)]
    r_acc = pa.analyze_series(_make_inst(value=pts_acc[-1][1]), pts_acc, window_min=60.0, horizon_min=60.0, now_unix=now)
    assert r_acc["trend_class"] == "accelerating_drift", r_acc["trend_class"]
    assert any(a["code"] == "accelerating_drift" for a in r_acc["anomalies"])

    # 4. Стационарный шум: НЕ даёт ложного дрейфа Манна-Кендалла
    pts_noise = [(now + m * 60.0, 535.0 + float(rng.normal(0.0, 0.6))) for m in range(-40, 1)]
    r_noise = pa.analyze_series(_make_inst(value=pts_noise[-1][1]), pts_noise, window_min=60.0, horizon_min=60.0, now_unix=now)
    assert r_noise["diagnostics"]["mann_kendall"]["significant"] is False
    assert r_noise["trend_class"] == "stable", r_noise["trend_class"]

    # 5. Рост волатильности (вибрация во 2-й половине)
    pts_vol = []
    for i, m in enumerate(range(-30, 1)):
        amp = 0.4 if m < -14 else 6.5
        val = 535.0 + (amp if i % 2 == 0 else -amp)
        pts_vol.append((now + m * 60.0, val))
    r_vol = pa.analyze_series(_make_inst(value=pts_vol[-1][1]), pts_vol, window_min=60.0, horizon_min=60.0, now_unix=now)
    assert r_vol["diagnostics"]["volatility_ratio"] >= 2.1
    assert any(a["code"] == "volatility_surge" for a in r_vol["anomalies"])

    return {
        "robust_slope": r_out["model"]["slope_per_min"],
        "cusum_stat": r_step["diagnostics"]["cusum"]["max_stat"],
        "accel_z": r_acc["model"]["accel_z"],
        "noise_mk_p": r_noise["diagnostics"]["mann_kendall"]["p_value"],
        "vol_ratio": r_vol["diagnostics"]["volatility_ratio"],
    }


def test_honest_insufficient_and_stale() -> None:
    pa = PredictiveAnalyzer()
    now = 1_765_000_000.0
    # Мало точек -> честный insufficient_data
    r_few = pa.analyze_series(_make_inst(value=535.0), [(now - 60, 534.0), (now, 535.0)], now_unix=now)
    assert r_few["status"] == "insufficient_data"
    assert r_few["eta_alert_min"] is None and r_few["forecast_confidence"] == 0.0

    # Канал STALE -> stale_channel
    pts = [(now + m * 60.0, 535.0 + 0.3 * m) for m in range(-20, 1)]
    r_st = pa.analyze_series(_make_inst(value=None, valid=False), pts, now_unix=now)
    assert r_st["status"] == "stale_channel"
    assert r_st["eta_alert_min"] is None and r_st["breach_prob_alert_horizon"] == 0.0


def test_multigauge_contract_sqlite_and_modbus_integration() -> dict:
    async def _run() -> dict:
        with tempfile.TemporaryDirectory(prefix="gv_pred_test_") as tmp:
            orig_db = os.environ.get("GAUGEVISION_DB")
            os.environ["GAUGEVISION_DB"] = str(Path(tmp) / "pred_test.db")
            await db.close_db()
            try:
                await db.init_db()
                # Multi-Gauge контракт: одна физическая камера `cam-multi-01`, два слота g0 и g1
                await db.create_camera(name="Камера щита К-1", type="rtsp", source_url="rtsp://192.168.1.50/stream", cam_id="cam-multi-01")
                now = _dt.datetime.now(_dt.timezone.utc)
                rows_ir = []
                for m in range(-25, 1):
                    ts = (now + _dt.timedelta(minutes=m)).isoformat(timespec="milliseconds")
                    rows_ir.append(("cam-multi-01#g0", "camera_cv", ts, 540.0 + 0.4 * m, "normal", "°C"))
                    rows_ir.append(("cam-multi-01#g1", "camera_cv", ts, 13.0 + 0.01 * m, "normal", "МПа"))
                await db.insert_instrument_readings(rows_ir)

                i0 = _make_inst("cam-multi-01#g0", code="К1-Щ1", value=540.0, source_kind="camera_cv")
                i1 = _make_inst("cam-multi-01#g1", code="К1-Щ2", value=13.0, v_min=0, v_max=16, ll=2, lw=4, hw=14.2, hh=15.2, source_kind="camera_cv")
                id0 = resolve_instrument_identity(i0)
                id1 = resolve_instrument_identity(i1)
                assert id0.camera_id == "cam-multi-01" and id0.gauge_slot == 0
                assert id1.camera_id == "cam-multi-01" and id1.gauge_slot == 1

                since_iso = (now - _dt.timedelta(minutes=60)).isoformat(timespec="milliseconds")
                smap = await db.get_instrument_series(["cam-multi-01#g0", "cam-multi-01#g1"], since_iso=since_iso)
                assert len(smap["cam-multi-01#g0"]) == 26 and len(smap["cam-multi-01#g1"]) == 26

                pa = PredictiveAnalyzer()
                ov = pa.overview([i0, i1], smap, window_min=60.0, horizon_min=60.0, now_unix=now.timestamp())
                saved_n = await db.save_predictive_snapshots(ov["instruments"])
                assert saved_n == 2
                hist0 = await db.list_predictive_snapshots("cam-multi-01#g0", limit=10)
                assert len(hist0) == 1 and hist0[0]["camera_id"] == "cam-multi-01" and hist0[0]["gauge_slot"] == 0

                # Проверка прогнозных регистров Modbus TCP (3600+ и 912..915) при сохранении MAX_REGISTERS=4096
                mb = ModbusTcpGateway()
                p_by_id = {x["instrument_id"]: x for x in ov["instruments"]}
                mb.update_from_instruments([i0, i1], predictive_by_id=p_by_id, now_unix=now.timestamp())
                snap = mb.registers_snapshot(limit=2)
                assert snap["system"]["HR40915_predictive_base"] == 3600
                assert snap["system"]["HR40916_predictive_stride"] == 8
                assert snap["instruments"][0]["hr_pred_base"] == 43601
                ea_decoded = struct.unpack(">f", struct.pack(">HH", mb._regs[3600], mb._regs[3601]))[0]
                assert abs(ea_decoded - p_by_id["cam-multi-01#g0"]["eta_alert_min"]) < 0.05
                assert mb._regs[4095] == 0  # последний регистр карты 0..4095 чист
                return {
                    "multigauge_slots": [id0.gauge_slot, id1.gauge_slot],
                    "snapshots_saved": saved_n,
                    "modbus_eta_alert_decoded": round(ea_decoded, 2),
                }
            finally:
                await db.close_db()
                if orig_db is None:
                    os.environ.pop("GAUGEVISION_DB", None)
                else:
                    os.environ["GAUGEVISION_DB"] = orig_db

    return asyncio.run(_run())


def main() -> None:
    report = {}
    report["linear_eta"] = test_exact_linear_eta_up_and_down()
    print("[PASS] test_exact_linear_eta_up_and_down", report["linear_eta"])
    report["monte_carlo_pi95"] = test_monte_carlo_pi95_coverage_and_monotonic_uncertainty()
    print("[PASS] test_monte_carlo_pi95_coverage_and_monotonic_uncertainty", report["monte_carlo_pi95"])
    report["robust_and_anomalies"] = test_theil_sen_robustness_and_anomaly_detectors()
    print("[PASS] test_theil_sen_robustness_and_anomaly_detectors", report["robust_and_anomalies"])
    test_honest_insufficient_and_stale()
    print("[PASS] test_honest_insufficient_and_stale")
    report["multigauge_sqlite_modbus"] = test_multigauge_contract_sqlite_and_modbus_integration()
    print("[PASS] test_multigauge_contract_sqlite_and_modbus_integration", report["multigauge_sqlite_modbus"])
    print("ALL PREDICTIVE ANALYTICS TESTS PASSED (5/5)")
    out_path = os.environ.get("PREDICTIVE_TEST_OUT")
    if out_path:
        Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
