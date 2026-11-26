"""
GaugeVision AI — демонстрационный профиль пульта КТЦ ТЭЦ (36 приборов).

Позиция #01 («К1-Р01», группа «Котлоагрегаты») закреплена за реальным конвейером
компьютерного зрения (`source_kind = "phone_cv"`), принимающим кадры со смартфона
Android по WSS (`/ws/phone/{cam_id}`). Преднастроена под модель `steam-pressure`
(Манометр острого пара МТП-160, 0–16 МПа, круглая дуга 270°).

Позиции #02..#36 (`source_kind = "simulated"`) управляются детерминированным
генератором со сценариями («Смешанный», «Штатный», «Пик / Перегрев», «Аварийный каскад»),
расчётом скорости изменения (Δ/мин) и 15-минутным профилем истории без записи в рабочую БД.
"""
from __future__ import annotations

import datetime as _dt
import math
import time
from typing import Any

from . import config

LIVE_DEMO_SPEC: dict[str, Any] = {
    "id": config.DEMO_LIVE_CAM_ID,
    "grid_pos": 1,
    "code": "К1-Р01",
    "short_name": "К-1 давление острого пара",
    "name": "Манометр острого пара котла К-1 (МТП-160)",
    "model": "МТП-160",
    "simulator_model": "steam-pressure",
    "group": "Котлоагрегаты",
    "type": "phone_ws",
    "source_kind": "phone_cv",
    "gauge_type": "pressure",
    "unit": "МПа",
    "decimals": 2,
    "calibration": {
        "v_min": 0.0,
        "theta_min": 135.0,
        "v_max": 16.0,
        "theta_max": 45.0,
        "direction": "cw",
        "roi": {"mode": "auto", "cx": 0.5, "cy": 0.5, "r": 0.45},
    },
    "thresholds": {
        "ll_alert": 2.0,
        "l_warn": 4.0,
        "h_warn": 14.2,
        "hh_alert": 15.2,
        "lower_enabled": True,
    },
    "lower_defaults": {
        "ll_alert": 2.0,
        "l_warn": 4.0,
    },
    "control_points": {
        "normal": 13.0,
        "nominal": 13.8,
        "warning": 14.7,
        "alert": 15.7,
        "low_warning": 3.0,
        "low_alert": 1.0,
    },
}

DEMO_GROUPS: tuple[str, ...] = (
    "Котлоагрегаты",
    "Турбоагрегаты",
    "Питательный узел",
    "Теплосеть и насосная",
    "Топливо и тяга",
    "ГРУ и генераторы",
)

DEMO_SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "id": "mixed",
        "label": "Смешанный (демо)",
        "description": "Стартовый режим: 2 аварии (К-1, Т-2), 3 предупреждения (Д-6, СН-1, ТГ-1) и 1 обрыв связи (ДС-1)",
    },
    {
        "id": "nominal",
        "label": "Штатный режим",
        "description": "Все 35 синтетических приборов станции работают внутри нормального коридора",
    },
    {
        "id": "peak",
        "label": "Пиковая нагрузка",
        "description": "Режим перегрева (~217 МВт): 2 аварии (К-1, Т-1), 4 предупр. (Д-6, СН-1, ТГ-1, ТГ-2) и 1 обрыв (ПСГ-1)",
    },
    {
        "id": "cascade",
        "label": "Аварийный каскад",
        "description": "Каскад нарушений LL/L/H/HH по всем узлам: 4 аварии, 4 предупр., 2 обрыва связи",
    },
)

SCENARIO_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {
    "nominal": {},
    "mixed": {
        # 2 CRITICAL (котёл К-1, турбоагрегат Т-2)
        "sim-02": {"base": 570.2, "amp": 1.8, "ramp_from": 546.0, "period_s": 28.0},
        # дребезг ±3,2 поверх волны ±1,1: минимум 94,6 − 4,3 = 90,3 > HH 90 — позиция не выходит из CRITICAL
        "sim-12": {"base": 94.6, "amp": 1.1, "ramp_from": 73.5, "period_s": 32.0, "chatter_amp": 3.2},
        # 3 WARNING (деаэратор №1, теплосеть СН-1, турбогенератор ТГ-1)
        "sim-17": {"base": 85.6, "amp": 1.1, "ramp_from": 69.0, "period_s": 34.0},
        "sim-21": {"base": 126.4, "amp": 1.2, "ramp_from": 105.0, "period_s": 31.0},
        "sim-31": {"base": 108.2, "amp": 1.1, "ramp_from": 88.0, "period_s": 30.0},
        # Реалистичный высокочастотный дребезг стрелки в самой модели сигнала (без подмены в dispatch_analyzer)
        "sim-10": {"chatter_amp": 0.022},
        # 1 NO_DATA / STALE (тяга уходящих газов ДС-1)
        "sim-30": {"stale": True, "last_val": -2.18, "last_lv": "normal", "age_s": 44.0},
    },
    "peak": {
        # 2 CRITICAL (котёл К-1, турбоагрегат Т-1)
        "sim-02": {"base": 572.4, "amp": 1.9, "ramp_from": 548.0, "period_s": 24.0},
        "sim-08": {"base": 563.5, "amp": 1.4, "ramp_from": 536.0, "period_s": 27.0},
        # 4 WARNING (деаэратор №1, теплосеть СН-1, турбогенераторы ТГ-1 и ТГ-2)
        "sim-16": {"base": 0.678, "amp": 0.006, "ramp_from": 0.592, "period_s": 26.0},
        "sim-21": {"base": 127.8, "amp": 1.1, "ramp_from": 104.5, "period_s": 29.0},
        "sim-31": {"base": 109.4, "amp": 1.0, "ramp_from": 88.0, "period_s": 28.0},
        "sim-34": {"base": 107.6, "amp": 0.9, "ramp_from": 83.0, "period_s": 33.0},
        # 1 NO_DATA / STALE (теплосеть ПСГ-1 — обрыв канала)
        "sim-24": {"stale": True, "last_val": 0.245, "last_lv": "normal", "age_s": 52.0},
    },
    "cascade": {
        # 4 CRITICAL (котёл К-1 верхняя HH и нижняя LL, турбоагрегат Т-2 HH, деаэратор №1 HH)
        "sim-02": {"base": 574.5, "amp": 2.1, "ramp_from": 542.0, "period_s": 21.0},
        "sim-03": {"base": -136.0, "amp": 5.0, "ramp_from": -15.0, "period_s": 23.0},
        "sim-12": {"base": 95.6, "amp": 1.3, "ramp_from": 68.0, "period_s": 26.0},
        "sim-17": {"base": 93.4, "amp": 1.1, "ramp_from": 69.0, "period_s": 25.0},
        # 4 WARNING (турбина Т-1 масло L, питат. узел ПЭН-1 L, теплосеть СН-1 H, турбогенератор ТГ-1 H)
        "sim-10": {"base": 0.083, "amp": 0.003, "ramp_from": 0.148, "period_s": 22.0},
        "sim-13": {"base": 15.05, "amp": 0.18, "ramp_from": 18.40, "period_s": 27.0},
        "sim-19": {"base": 1.375, "amp": 0.014, "ramp_from": 1.124, "period_s": 24.0},
        "sim-31": {"base": 108.8, "amp": 1.1, "ramp_from": 87.0, "period_s": 29.0},
        # 2 NO_DATA / STALE (теплосеть СН-1 обратная вода, дымосос ДС-1)
        "sim-22": {"stale": True, "last_val": 56.8, "last_lv": "normal", "age_s": 68.0},
        "sim-30": {"stale": True, "last_val": -2.18, "last_lv": "warning", "age_s": 95.0},
    },
}


def _sim(
    pos: int,
    code: str,
    short_name: str,
    name: str,
    group: str,
    gauge_type: str,
    unit: str,
    decimals: int,
    v_min: float,
    v_max: float,
    ll: float | None,
    lw: float | None,
    hw: float | None,
    hh: float | None,
    base: float,
    amp: float,
    period_s: float,
) -> dict[str, Any]:
    return {
        "id": f"sim-{pos:02d}",
        "grid_pos": pos,
        "code": code,
        "short_name": short_name,
        "name": name,
        "group": group,
        "gauge_type": gauge_type,
        "unit": unit,
        "decimals": decimals,
        "source_kind": "simulated",
        "camera_id": None,
        "calibration": {
            "v_min": float(v_min),
            "theta_min": 135.0,
            "v_max": float(v_max),
            "theta_max": 45.0,
            "direction": "cw",
        },
        "thresholds": {
            "ll_alert": ll,
            "l_warn": lw,
            "h_warn": hw,
            "hh_alert": hh,
            "lower_enabled": ll is not None or lw is not None,
        },
        "base": float(base),
        "amp": float(amp),
        "period_s": float(period_s),
    }


SIMULATED_CATALOG: tuple[dict[str, Any], ...] = (
    # Группа 1: Котлоагрегаты (позиции 2–6; позиция 1 — живая камера К1-Р01)
    _sim(2, "К1-Т01", "К-1 темп. перегретого пара", "Термометр перегретого пара котла К-1", "Котлоагрегаты",
         "temperature", "°C", 1, 0, 600, 485, 505, 555, 565, 538.4, 2.2, 46),
    _sim(3, "К1-У01", "К-1 уровень в барабане", "Уровнемер барабана котла К-1", "Котлоагрегаты",
         "level", "мм", 0, -200, 200, -120, -75, 75, 120, -12.0, 6.0, 34),
    _sim(4, "К1-ТН1", "К-1 разрежение в топке", "Тягонапоромер топки котла К-1", "Котлоагрегаты",
         "draft", "Па", 0, -500, 100, -360, -240, -15, 20, -48.0, 7.0, 22),
    _sim(5, "К2-Р01", "К-2 давление острого пара", "Манометр острого пара котла К-2", "Котлоагрегаты",
         "pressure", "МПа", 2, 0, 16, 2.0, 4.0, 14.2, 15.2, 13.56, 0.09, 39),
    _sim(6, "К2-F01", "К-2 расход острого пара", "Расходомер острого пара котла К-2", "Котлоагрегаты",
         "flow", "т/ч", 0, 0, 400, 80, 120, 340, 370, 268.0, 4.5, 52),

    # Группа 2: Турбоагрегаты (позиции 7–12)
    _sim(7, "ТА1-Р01", "Т-1 пар перед стоп. клапаном", "Манометр пара перед стопорным клапаном Т-1", "Турбоагрегаты",
         "pressure", "МПа", 2, 0, 16, 9.5, 11.0, 14.0, 14.8, 12.84, 0.08, 41),
    _sim(8, "ТА1-Т01", "Т-1 темп. свежего пара ЦВД", "Термометр свежего пара ЦВД турбины Т-1", "Турбоагрегаты",
         "temperature", "°C", 1, 0, 600, 480, 500, 550, 560, 534.6, 1.8, 58),
    _sim(9, "ТА1-Р02", "Т-1 вакуум в конденсаторе", "Вакуумметр конденсатора турбины Т-1", "Турбоагрегаты",
         "pressure", "кПа", 1, -100, 0, -98.0, -96.5, -84.0, -78.0, -92.4, 0.4, 63),
    _sim(10, "ТА1-Р03", "Т-1 давление масла смазки", "Манометр масла смазки подшипников Т-1", "Турбоагрегаты",
         "pressure", "МПа", 3, 0, 0.6, 0.070, 0.095, 0.220, 0.260, 0.148, 0.004, 29),
    _sim(11, "ТА2-Р01", "Т-2 давление свежего пара", "Манометр свежего пара турбины Т-2", "Турбоагрегаты",
         "pressure", "МПа", 2, 0, 16, 9.5, 11.0, 14.0, 14.8, 12.92, 0.07, 47),
    _sim(12, "ТА2-Т02", "Т-2 баббит упорного подшипн.", "Термометр баббита упорного подшипника Т-2", "Турбоагрегаты",
         "temperature", "°C", 1, 0, 120, 25.0, 35.0, 80.0, 90.0, 64.5, 0.9, 71),

    # Группа 3: Питательный узел (позиции 13–18)
    _sim(13, "ПЭН1-Р1", "ПЭН-1 напор питат. воды", "Манометр напора питательного насоса ПЭН-1", "Питательный узел",
         "pressure", "МПа", 2, 0, 25, 14.0, 15.8, 21.0, 22.5, 18.45, 0.12, 33),
    _sim(14, "ПЭН2-Р1", "ПЭН-2 напор питат. воды", "Манометр напора питательного насоса ПЭН-2", "Питательный узел",
         "pressure", "МПа", 2, 0, 25, 14.0, 15.8, 21.0, 22.5, 18.32, 0.11, 37),
    _sim(15, "К1-F01", "К-1 расход острого пара", "Расходомер острого пара котла К-1", "Питательный узел",
         "flow", "т/ч", 0, 0, 400, 80, 120, 340, 370, 276.0, 5.0, 44),
    _sim(16, "Д6-Р01", "Деаэратор №1 давление", "Манометр деаэратора 0,6 МПа №1", "Питательный узел",
         "pressure", "МПа", 3, 0, 1.0, 0.480, 0.520, 0.660, 0.700, 0.588, 0.006, 51),
    _sim(17, "Д6-У01", "Деаэратор №1 уровень в баке", "Уровнемер аккумуляторного бака деаэратора №1", "Питательный узел",
         "level", "%", 1, 0, 100, 25.0, 40.0, 82.0, 90.0, 68.4, 0.8, 66),
    _sim(18, "ПВД-Т01", "ПВД-3 темп. питат. воды", "Термометр питательной воды за ПВД-3", "Питательный узел",
         "temperature", "°C", 1, 0, 300, 175.0, 190.0, 240.0, 255.0, 218.2, 1.4, 59),

    # Группа 4: Теплосеть и насосная (позиции 19–24)
    _sim(19, "СН1-Р01", "СН-1 давление прямой воды", "Манометр прямой сетевой воды СН-1", "Теплосеть и насосная",
         "pressure", "МПа", 3, 0, 1.6, 0.750, 0.900, 1.320, 1.450, 1.124, 0.012, 38),
    _sim(20, "СН1-Р02", "СН-1 давление обратной воды", "Манометр обратной сетевой воды СН-1", "Теплосеть и насосная",
         "pressure", "МПа", 3, 0, 1.0, 0.200, 0.260, 0.520, 0.600, 0.382, 0.008, 43),
    _sim(21, "СН1-Т01", "СН-1 темп. прямой воды", "Термометр прямой сетевой магистрали СН-1", "Теплосеть и насосная",
         "temperature", "°C", 1, 0, 150, 70.0, 82.0, 122.0, 132.0, 104.2, 0.7, 78),
    _sim(22, "СН1-Т02", "СН-1 темп. обратной воды", "Термометр обратной сетевой магистрали СН-1", "Теплосеть и насосная",
         "temperature", "°C", 1, 0, 100, 35.0, 42.0, 68.0, 75.0, 56.8, 0.5, 84),
    _sim(23, "СН1-F01", "СН-1 расход прямой магистр.", "Расходомер сетевой воды прямой магистрали №1", "Теплосеть и насосная",
         "flow", "м³/ч", 0, 0, 4000, 900, 1300, 3300, 3650, 2460.0, 26.0, 49),
    _sim(24, "ПСГ-Р01", "ПСГ-1 давление греющего пара", "Манометр греющего пара подогревателя ПСГ-1", "Теплосеть и насосная",
         "pressure", "МПа", 3, 0, 1.0, 0.090, 0.140, 0.380, 0.450, 0.245, 0.006, 55),

    # Группа 5: Топливо и тяга (позиции 25–30)
    _sim(25, "ГРП-Р01", "ГРП давление природного газа", "Манометр природного газа за ГРП", "Топливо и тяга",
         "pressure", "МПа", 3, 0, 1.0, 0.250, 0.310, 0.540, 0.620, 0.412, 0.007, 31),
    _sim(26, "ГРП-F01", "К-1 расход природного газа", "Расходомер природного газа котла К-1", "Топливо и тяга",
         "flow", "м³/ч", 0, 0, 30000, 5000, 8500, 24500, 27000, 18450.0, 140.0, 42),
    _sim(27, "МН-Р01", "Мазутопровод давление напора", "Манометр мазутопровода рециркуляции", "Топливо и тяга",
         "pressure", "МПа", 2, 0, 4.0, 1.60, 2.00, 3.30, 3.65, 2.64, 0.03, 61),
    _sim(28, "МН-Т01", "Мазут темп. после подогрева", "Термометр мазута после подогревателей", "Топливо и тяга",
         "temperature", "°C", 1, 0, 160, 90.0, 100.0, 132.0, 142.0, 116.5, 0.8, 74),
    _sim(29, "ДВ1-Р01", "ДВ-1 напор дутьевого воздуха", "Напоромер воздуха дутьевого вентилятора ДВ-1", "Топливо и тяга",
         "draft", "кПа", 2, 0, 6.0, 1.20, 1.80, 4.60, 5.20, 3.42, 0.05, 27),
    _sim(30, "ДС1-ТН1", "ДС-1 тяга уходящих газов", "Тягомер уходящих газов перед дымососом ДС-1", "Топливо и тяга",
         "draft", "кПа", 2, -4.0, 0.0, -3.50, -3.00, -0.90, -0.50, -2.18, 0.04, 25),

    # Группа 6: ГРУ и генераторы (позиции 31–36)
    _sim(31, "ТГ1-РВт", "ТГ-1 активная мощность", "Ваттметр активной мощности генератора ТГ-1", "ГРУ и генераторы",
         "electrical", "МВт", 1, 0, 120, 20.0, 35.0, 105.0, 114.0, 86.4, 0.9, 53),
    _sim(32, "ТГ1-U01", "ТГ-1 напряжение статора", "Вольтметр статора генератора ТГ-1", "ГРУ и генераторы",
         "electrical", "кВ", 2, 0, 15, 9.80, 10.05, 10.95, 11.20, 10.52, 0.03, 67),
    _sim(33, "ТГ1-I01", "ТГ-1 ток ротора возбуждения", "Амперметр тока возбуждения генератора ТГ-1", "ГРУ и генераторы",
         "electrical", "А", 0, 0, 1000, 220, 320, 820, 900, 615.0, 6.0, 36),
    _sim(34, "ТГ2-РВт", "ТГ-2 активная мощность", "Ваттметр активной мощности генератора ТГ-2", "ГРУ и генераторы",
         "electrical", "МВт", 1, 0, 120, 20.0, 35.0, 105.0, 114.0, 82.0, 0.8, 57),
    _sim(35, "РУ6-U01", "РУ-6 кВ напряжение СН-1", "Вольтметр секции 6 кВ собственных нужд СН-1", "ГРУ и генераторы",
         "electrical", "кВ", 2, 0, 10, 5.70, 5.85, 6.45, 6.60, 6.18, 0.02, 72),
    _sim(36, "КМП-Р01", "Коллектор воздуха КИПиА", "Манометр коллектора осушенного воздуха КИПиА", "ГРУ и генераторы",
         "pressure", "МПа", 3, 0, 1.0, 0.500, 0.560, 0.800, 0.860, 0.685, 0.005, 48),
)

SIMULATED_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in SIMULATED_CATALOG}


def classify_sim_level(value: float | None, thresholds: dict[str, Any]) -> str:
    if value is None:
        return "normal"
    lower_on = thresholds.get("lower_enabled") is not False
    ll = thresholds.get("ll_alert") if lower_on else None
    lw = thresholds.get("l_warn") if lower_on else None
    hw = thresholds.get("h_warn")
    hh = thresholds.get("hh_alert")
    if (ll is not None and value <= float(ll)) or (hh is not None and value >= float(hh)):
        return "alert"
    if (lw is not None and value <= float(lw)) or (hw is not None and value >= float(hw)):
        return "warning"
    return "normal"


def decimals_for_scale(calibration: dict[str, Any] | None, explicit: int | None = None) -> int:
    if explicit is not None:
        return int(explicit)
    c = calibration or {}
    try:
        span = abs(float(c.get("v_max", 10.0)) - float(c.get("v_min", 0.0))) or 10.0
    except (TypeError, ValueError):
        span = 10.0
    if span <= 2.5:
        return 3
    if span <= 25.0:
        return 2
    if span <= 250.0:
        return 1
    return 0


class SimulatedTelemetryAdapter:
    """
    Генератор телеметрии для 35 позиций пульта с поддержкой предельных сценариев
    (WARNING / CRITICAL / STALE), динамического дрейфа, расчёта Δ/мин и 15-минутного спарклайна.
    """

    def __init__(self, seed: int = config.DEMO_SEED, scenario: str = "mixed") -> None:
        self.seed = int(seed)
        self.scenario = scenario if scenario in SCENARIO_OVERRIDES else "mixed"
        self.anchor_ts = time.time()

    def set_scenario(self, scenario: str) -> str:
        if scenario not in SCENARIO_OVERRIDES:
            raise ValueError(f"Неизвестный сценарий симуляции: {scenario}")
        self.scenario = scenario
        self.anchor_ts = time.time()
        return self.scenario

    def _override(self, inst_id: str) -> dict[str, Any]:
        return SCENARIO_OVERRIDES.get(self.scenario, {}).get(inst_id, {})

    def is_stale(self, spec: dict[str, Any]) -> bool:
        return bool(self._override(spec["id"]).get("stale"))

    def value_at(self, spec: dict[str, Any], t_unix: float) -> float:
        ov = self._override(spec["id"])
        pos = int(spec["grid_pos"])
        target_base = float(ov.get("base", spec["base"]))
        amp = float(ov.get("amp", spec["amp"]))
        period = max(10.0, float(ov.get("period_s", spec["period_s"])))

        # Плавный 15-минутный выход на целевой режим для реалистичного спарклайна и тренда
        ramp_from = ov.get("ramp_from")
        if ramp_from is not None and t_unix < self.anchor_ts:
            frac = max(0.0, min(1.0, (t_unix - (self.anchor_ts - 900.0)) / 900.0))
            smooth = frac * frac * (3.0 - 2.0 * frac)
            eff_base = float(ramp_from) + (target_base - float(ramp_from)) * smooth
        else:
            eff_base = target_base

        phase = ((self.seed * 31 + pos * 97) % 360) * (math.pi / 180.0)
        omega = 2.0 * math.pi / period
        wave = (
            0.68 * math.sin(omega * t_unix + phase)
            + 0.22 * math.sin(omega * 2.13 * t_unix + phase * 1.7)
            + 0.10 * math.cos(omega * 0.47 * t_unix + phase * 0.6)
        )
        val = eff_base + amp * wave
        chatter_amp = float(ov.get("chatter_amp", 0.0))
        if chatter_amp > 0.0:
            # Детерминированная высокочастотная осцилляция (вибрация/дребезг стрелки в самом сигнале)
            val += chatter_amp * (1.0 if int(round(t_unix * 1.5 + pos)) % 2 == 0 else -1.0)
        cal = spec["calibration"]
        lo, hi = min(cal["v_min"], cal["v_max"]), max(cal["v_min"], cal["v_max"])
        val = max(lo, min(hi, val))
        nd = int(spec["decimals"]) + 1
        return round(val, nd)

    def rate_per_min(self, spec: dict[str, Any], t_unix: float) -> float:
        """Мгновенная скорость изменения параметра за последнюю минуту (Δ/мин)."""
        v_now = self.value_at(spec, t_unix)
        v_prev = self.value_at(spec, t_unix - 30.0)
        return round((v_now - v_prev) * 2.0, int(spec["decimals"]) + 1)

    def sparkline(self, spec: dict[str, Any], t_unix: float, points: int = 24, window_s: float = 900.0) -> list[float]:
        step = window_s / max(1, points - 1)
        t_start = t_unix - window_s
        return [self.value_at(spec, t_start + i * step) for i in range(points)]

    def instrument(self, spec: dict[str, Any], t_unix: float | None = None) -> dict[str, Any]:
        now = time.time() if t_unix is None else float(t_unix)
        ov = self._override(spec["id"])
        if ov.get("stale"):
            age_s = float(ov.get("age_s", 45.0)) + max(0.0, now - self.anchor_ts)
            stale_dt = _dt.datetime.fromtimestamp(now - age_s, tz=_dt.timezone.utc).isoformat(timespec="milliseconds")
            last_val = float(ov.get("last_val", spec["base"]))
            last_lv = str(ov.get("last_lv", "normal"))
            hist = self.sparkline(spec, now - age_s, points=18, window_s=720.0)
            return {
                "id": spec["id"],
                "grid_pos": spec["grid_pos"],
                "code": spec["code"],
                "short_name": spec["short_name"],
                "name": spec["name"],
                "group": spec["group"],
                "type": "simulated",
                "source_kind": "simulated",
                "camera_id": None,
                "gauge_type": spec["gauge_type"],
                "unit": spec["unit"],
                "decimals": spec["decimals"],
                "source_url": None,
                "calibration": spec["calibration"],
                "thresholds": spec["thresholds"],
                "status": "offline",
                "conn_state": "disconnected",
                "meas_state": "no_fresh_data",
                "quality": "no_fresh_data",
                "phone_stage": None,
                "stream": {"status": "offline", "fps": 0.0, "frames_total": 0, "fail_count": 3,
                           "last_error": "Обрыв линии опроса датчика", "online_since": None, "frame_age": round(age_s, 1)},
                "reading": {
                    "ts": stale_dt,
                    "last_valid_ts": stale_dt,
                    "last_frame_ts": None,
                    "value": None,
                    "raw_value": None,
                    "last_valid_value": last_val,
                    "angle": None,
                    "valid": False,
                    "confidence": None,
                    "level": "stale",
                    "last_valid_level": last_lv,
                    "rate_per_min": None,
                    "age_s": round(age_s, 1),
                    "sparkline": hist,
                    "source_kind": "simulated",
                },
            }

        iso = _dt.datetime.fromtimestamp(math.floor(now), tz=_dt.timezone.utc).isoformat(timespec="milliseconds")
        val = self.value_at(spec, now)
        lv = classify_sim_level(val, spec["thresholds"])
        rate = self.rate_per_min(spec, now)
        spark = self.sparkline(spec, now)
        return {
            "id": spec["id"],
            "grid_pos": spec["grid_pos"],
            "code": spec["code"],
            "short_name": spec["short_name"],
            "name": spec["name"],
            "group": spec["group"],
            "type": "simulated",
            "source_kind": "simulated",
            "camera_id": None,
            "gauge_type": spec["gauge_type"],
            "unit": spec["unit"],
            "decimals": spec["decimals"],
            "source_url": None,
            "calibration": spec["calibration"],
            "thresholds": spec["thresholds"],
            "status": "online",
            "conn_state": "simulated",
            "meas_state": "valid",
            "quality": "ok",
            "phone_stage": None,
            "stream": {"status": "online", "fps": 1.0, "frames_total": 0, "fail_count": 0,
                       "last_error": None, "online_since": None, "frame_age": 0.0},
            "reading": {
                "ts": iso,
                "last_valid_ts": iso,
                "last_frame_ts": None,
                "value": val,
                "raw_value": val,
                "last_valid_value": val,
                "angle": None,
                "valid": True,
                "confidence": None,
                "level": lv,
                "last_valid_level": lv,
                "rate_per_min": rate,
                "sparkline": spark,
                "source_kind": "simulated",
            },
        }

    def all_instruments(self, t_unix: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if t_unix is None else float(t_unix)
        return [self.instrument(s, now) for s in SIMULATED_CATALOG]

    def tick_payload(self, t_unix: float | None = None) -> dict[str, Any]:
        now = time.time() if t_unix is None else float(t_unix)
        iso = _dt.datetime.fromtimestamp(math.floor(now), tz=_dt.timezone.utc).isoformat(timespec="milliseconds")
        items: list[dict[str, Any]] = []
        for s in SIMULATED_CATALOG:
            ov = self._override(s["id"])
            if ov.get("stale"):
                age_s = float(ov.get("age_s", 45.0)) + max(0.0, now - self.anchor_ts)
                items.append({
                    "id": s["id"],
                    "status": "offline",
                    "valid": False,
                    "value": None,
                    "last_valid_value": float(ov.get("last_val", s["base"])),
                    "level": "stale",
                    "last_valid_level": str(ov.get("last_lv", "normal")),
                    "rate_per_min": None,
                    "age_s": round(age_s, 1),
                })
            else:
                val = self.value_at(s, now)
                lv = classify_sim_level(val, s["thresholds"])
                items.append({
                    "id": s["id"],
                    "status": "online",
                    "valid": True,
                    "value": val,
                    "last_valid_value": val,
                    "level": lv,
                    "last_valid_level": lv,
                    "rate_per_min": self.rate_per_min(s, now),
                })
        return {"type": "sim_tick", "ts": iso, "scenario": self.scenario, "items": items}

    def history_rows(self, inst_id: str, limit: int = 120, window_s: float = 900.0) -> list[dict[str, Any]]:
        """15-минутная история отсчётов синтетического прибора для вкладки «История» и CSV."""
        spec = SIMULATED_BY_ID.get(inst_id)
        if spec is None:
            return []
        ov = self._override(inst_id)
        now = time.time()
        end_t = now - (float(ov.get("age_s", 45.0)) + max(0.0, now - self.anchor_ts)) if ov.get("stale") else now
        count = max(12, min(int(limit), 180))
        step = max(5.0, window_s / max(1, count - 1))
        t0 = end_t - step * (count - 1)
        out: list[dict[str, Any]] = []
        for idx in range(count):
            t_cur = t0 + idx * step
            val = self.value_at(spec, t_cur)
            lv = classify_sim_level(val, spec["thresholds"])
            iso = _dt.datetime.fromtimestamp(t_cur, tz=_dt.timezone.utc).isoformat(timespec="milliseconds")
            out.append({
                "id": idx + 1,
                "timestamp_iso8601": iso,
                "instrument_id": spec["code"],
                "source_kind": "simulated",
                "value": val,
                "unit": spec["unit"],
                "raw_angle_deg": None,
                "status_level": lv,
            })
        return out

    def trend(self, inst_id: str, since: _dt.datetime, step_s: float,
              until: _dt.datetime | None = None) -> list[dict[str, Any]]:
        spec = SIMULATED_BY_ID.get(inst_id)
        if spec is None:
            return []
        ov = self._override(inst_id)
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        end_dt = (until or now_utc).astimezone(_dt.timezone.utc)
        if ov.get("stale"):
            age_s = float(ov.get("age_s", 45.0)) + max(0.0, time.time() - self.anchor_ts)
            cutoff = now_utc - _dt.timedelta(seconds=age_s)
            end_dt = min(end_dt, cutoff)
        start_dt = since.astimezone(_dt.timezone.utc)
        t0 = start_dt.timestamp()
        t1 = end_dt.timestamp()
        if t1 < t0:
            return []
        step = max(1.0, float(step_s))
        out: list[dict[str, Any]] = []
        cur = t0
        max_pts = config.TREND_BUCKETS_MAX
        if (t1 - t0) / step > max_pts:
            step = (t1 - t0) / max_pts
        while cur <= t1 + 1e-6 and len(out) < max_pts:
            samples = [self.value_at(spec, cur + off * (step / 3.0)) for off in (0, 1, 2)]
            avg_val = round(sum(samples) / len(samples), int(spec["decimals"]) + 1)
            dt_iso = _dt.datetime.fromtimestamp(cur, tz=_dt.timezone.utc).isoformat(timespec="seconds")
            out.append({
                "t": dt_iso,
                "min": min(samples),
                "max": max(samples),
                "avg": avg_val,
                "n": len(samples),
                "level": classify_sim_level(avg_val, spec["thresholds"]),
            })
            cur += step
        return out


def compute_live_states(
    cam: dict[str, Any],
    stream_info: dict[str, Any],
    reading: dict[str, Any] | None,
    stale_seconds: float = config.READING_STALE_SECONDS,
) -> dict[str, Any]:
    """
    Вычисляет раздельные состояния соединения, измерения и этапа Android
    для живого прибора (без смешивания свежести кадра и валидности CV).
    """
    cam_type = cam.get("type", "phone_ws")
    st_status = stream_info.get("status", cam.get("status", "offline"))
    frame_age = stream_info.get("frame_age")
    frames_total = int(stream_info.get("frames_total") or 0)
    ws_connected = bool(stream_info.get("ws_connected", False))
    client_state = stream_info.get("client_state") or "waiting_phone"

    has_fresh_frame = st_status == "online" and frame_age is not None and frame_age <= config.PHONE_TIMEOUT

    now_utc = _dt.datetime.now(_dt.timezone.utc)
    valid_age: float | None = None
    last_valid_ts = reading.get("last_valid_ts") if reading else None
    if last_valid_ts:
        try:
            dt = _dt.datetime.fromisoformat(last_valid_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            valid_age = max(0.0, round((now_utc - dt).total_seconds(), 2))
        except ValueError:
            valid_age = None

    is_currently_valid = bool(reading and reading.get("valid") and reading.get("value") is not None)
    has_fresh_reading = bool(
        has_fresh_frame and is_currently_valid and valid_age is not None and valid_age <= stale_seconds
    )

    if has_fresh_frame:
        conn_state = "connected"
    elif frames_total > 0 or st_status == "reconnecting":
        conn_state = "interrupted" if frames_total > 0 else ("connecting" if ws_connected else "disconnected")
    elif ws_connected:
        conn_state = "connecting"
    else:
        conn_state = "disconnected"

    out_of_scale = bool(reading and reading.get("out_of_scale"))
    awaiting_post_cal = bool(reading and reading.get("awaiting_post_cal"))
    if has_fresh_reading:
        meas_state = "valid"
        quality = "ok"
    elif has_fresh_frame:
        if out_of_scale:
            meas_state = "needs_calibration"
            quality = "needs_calibration"
        elif last_valid_ts and not awaiting_post_cal:
            if valid_age is not None and valid_age <= stale_seconds:
                meas_state = "hold"
                quality = "hold"
            else:
                meas_state = "no_fresh_data"
                quality = "no_fresh_data"
        else:
            meas_state = "awaiting_reading"
            quality = "awaiting_reading"
    else:
        if last_valid_ts and not awaiting_post_cal:
            meas_state = "no_fresh_data"
            quality = "no_fresh_data"
        else:
            meas_state = "no_data"
            quality = "disconnected"

    phone_stage: str | None = None
    if cam_type == "phone_ws":
        if client_state == "permission_denied":
            phone_stage = "permission_denied"
        elif client_state == "camera_error":
            phone_stage = "camera_error"
        elif has_fresh_reading:
            phone_stage = "reading_received"
        elif has_fresh_frame:
            phone_stage = "no_reading_yet"
        elif frames_total > 0:
            phone_stage = "stream_interrupted"
        elif ws_connected:
            phone_stage = "awaiting_permission"
        else:
            phone_stage = "waiting_phone"

    return {
        "conn_state": conn_state,
        "meas_state": meas_state,
        "quality": quality,
        "phone_stage": phone_stage,
        "frame_age_s": frame_age,
        "reading_age_s": valid_age,
        "has_fresh_frame": has_fresh_frame,
        "has_fresh_reading": has_fresh_reading,
    }


def unify_camera(
    public_cam: dict[str, Any],
    *,
    grid_pos: int = 1,
    is_primary_demo: bool = False,
) -> dict[str, Any]:
    """Приводит реальную камеру сервера к единой модели приборов пульта."""
    cam_type = public_cam.get("type", "phone_ws")
    source_kind = "phone_cv" if cam_type == "phone_ws" else "camera_cv"
    stream_info = public_cam.get("stream") or {}
    reading = public_cam.get("reading")
    states = compute_live_states(public_cam, stream_info, reading)

    if is_primary_demo:
        code = LIVE_DEMO_SPEC["code"]
        short_name = public_cam.get("name") or LIVE_DEMO_SPEC["short_name"]
        if short_name in (LIVE_DEMO_SPEC["name"], "Манометр острого пара К-1 (МТП-160)"):
            short_name = LIVE_DEMO_SPEC["short_name"]
        group = LIVE_DEMO_SPEC["group"]
        decimals = decimals_for_scale(public_cam.get("calibration"), LIVE_DEMO_SPEC["decimals"])
    else:
        code = f"КМ-{grid_pos:02d}"
        short_name = public_cam.get("name") or code
        group = "Дополнительные камеры"
        decimals = decimals_for_scale(public_cam.get("calibration"))

    return {
        **public_cam,
        "grid_pos": grid_pos,
        "code": code,
        "short_name": short_name,
        "group": group,
        "decimals": decimals,
        "source_kind": source_kind,
        "camera_id": public_cam["id"],
        **states,
    }
