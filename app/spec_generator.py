"""
GaugeVision AI — Трек №1: Автоматическая генерация проекта проектной документации и ТЗ (`spec_generator`).

Формирует инженерный проект комплекта документов по обследованию технологических
узлов энергообъекта в форматах `.md` (предпросмотр в HMI) и `.docx` (корпоративная
вёрстка, штампы, таблицы, встроенные доказательные кадры):
  1. Паспорт обследуемого технологического узла и реестр аналоговых КИПиА.
  2. Сводный протокол инструментального видеомониторинга за выбранный период
     (на базе реальной истории `readings` и `events` SQLite с явным указанием охвата).
  3. Дефектная ведомость с доказательными кадрами и классификацией причин
     (без фабрикации дефектов на исправном оборудовании, DEF-04).
  4. Проект технического задания на модернизацию КИПиА с техническими требованиями
     и примерами ориентировочных аналогов цифровых датчиков (подбор по опросным листам).
  5. Предварительное ТЭО с конфигурируемыми исходными параметрами, учётом OPEX,
     прозрачными формулами и явными допущениями (обработка CAPEX=0 / эффекта<=0).

Правовое и метрологическое разграничение (DEF-22):
  • GaugeVision AI — информационно-аналитическая система вспомогательного мониторинга,
    НЕ является сертифицированным средством измерений (ФЗ-102) и НЕ применяется в ПАЗ.
  • Сформированный документ является инженерным проектом (черновиком), подлежащим
    экспертной проверке и официальному утверждению.
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
from typing import Any

import httpx

from . import config
from .docx_builder import DocxBuilder
from .stream_manager import encode_jpeg, render_gauge_frame

logger = logging.getLogger("gaugevision.spec_generator")

LEGAL_DISCLAIMER = (
    "ВАЖНОЕ ПРИМЕЧАНИЕ: GaugeVision AI является информационно-аналитической системой "
    "вспомогательного видеомониторинга, НЕ является средством измерений утверждённого типа "
    "(ФЗ-102 «Об обеспечении единства измерений») и НЕ подлежит применению в контурах "
    "противоаварийной автоматической защиты (ПАЗ) и непосредственного управления технологическим процессом. "
    "Настоящий документ сформирован автоматически как ИНЖЕНЕРНЫЙ ПРОЕКТ (черновик) и подлежит "
    "обязательной экспертной проверке, уточнению по опросным листам и утверждению в установленном порядке."
)

# ---------------------------------------------------------------------------
# Справочник ориентировочных технических требований и примеров аналогов
# (НЕ является предписанием конкретного бренда; цены — ориентировочные стендовые оценки)
# ---------------------------------------------------------------------------
DIGITAL_SENSOR_CATALOG: dict[str, dict[str, Any]] = {
    "pressure": {
        "requirement_class": "Цифровой преобразователь избыточного давления",
        "model": "Пример аналога: Метран-150TG / Элемер АИР-20/М2-Н (подбор по опросному листу)",
        "signal": "4–20 мА + HART (rev. 7)",
        "accuracy": "Не хуже ±0,075% (предел осн. погр.)",
        "ip": "Не ниже IP66 / IP67",
        "ex": "Общепромышленное (для взрывоопасных зон — 1Ex d/ia IIC T6)",
        "integration": "Аналоговый ввод AI 4–20 мА + HART-диагностика в ПТК АСУ ТП (Modbus TCP / OPC UA)",
        "unit_cost_rub": 68_000,
        "install_cost_rub": 24_000,
        "downtime_risk_k_rub_yr": 195_000,
    },
    "pressure_ex": {
        "requirement_class": "Цифровой преобразователь давления во взрывозащищённом исполнении",
        "model": "Пример аналога: Метран-150TG Ex / Rosemount 3051S Ex (подбор по опросному листу)",
        "signal": "4–20 мА + HART (искробезопасная цепь)",
        "accuracy": "Не хуже ±0,075%",
        "ip": "Не ниже IP67",
        "ex": "1Ex ia IIC T6 Ga (ТР ТС 012/2011)",
        "integration": "Через барьер искрозащиты (БИЗ) в модуль AI 4–20 мА АСУ ТП + диагностика HART",
        "unit_cost_rub": 94_000,
        "install_cost_rub": 32_000,
        "downtime_risk_k_rub_yr": 260_000,
    },
    "temperature": {
        "requirement_class": "Цифровой термопреобразователь с унифицированным выходом (Pt100, класс A)",
        "model": "Пример аналога: Метран-276 / Элемер ТСПУ-0104 (подбор по опросному листу)",
        "signal": "4–20 мА + HART / RS-485 Modbus RTU",
        "accuracy": "Не хуже ±0,15 °C (класс A по ГОСТ 6651)",
        "ip": "Не ниже IP65 / IP67",
        "ex": "Общепромышленное / 1Ex d IIC T5 (для мазутопроводов и газовых зон)",
        "integration": "Ввод в контроллер АСУ ТП (AI 4–20 мА / RS-485 Modbus RTU) с контролем обрыва линии",
        "unit_cost_rub": 54_000,
        "install_cost_rub": 22_000,
        "downtime_risk_k_rub_yr": 220_000,
    },
    "draft": {
        "requirement_class": "Цифровой преобразователь давления/разрежения (тягонапоромер)",
        "model": "Пример аналога: Метран-150CD / ОВЕН ПД150-ДИВ (подбор по опросному листу)",
        "signal": "4–20 мА + HART / RS-485 Modbus RTU",
        "accuracy": "Не хуже ±0,15%",
        "ip": "Не ниже IP65",
        "ex": "1Ex ia IIC T6 Ga (для газовоздушного тракта котла)",
        "integration": "Шина RS-485 Modbus RTU / AI 4–20 мА в шкаф УСО котельного агрегата",
        "unit_cost_rub": 62_000,
        "install_cost_rub": 25_000,
        "downtime_risk_k_rub_yr": 170_000,
    },
    "level": {
        "requirement_class": "Цифровой преобразователь уровня (гидростатический / дифманометр)",
        "model": "Пример аналога: Метран-150CD / Элемер АИР-30 (подбор по опросному листу)",
        "signal": "4–20 мА + HART (резервированный канал)",
        "accuracy": "Не хуже ±0,1%",
        "ip": "Не ниже IP67",
        "ex": "Общепромышленное (высокотемпературное исполнение по опросному листу)",
        "integration": "Двухпроводная линия 4–20 мА + HART в контур контроля барабана / деаэратора",
        "unit_cost_rub": 82_000,
        "install_cost_rub": 28_000,
        "downtime_risk_k_rub_yr": 240_000,
    },
    "flow": {
        "requirement_class": "Цифровой преобразователь расхода / перепада давления",
        "model": "Пример аналога: Метран-150CD / Взлёт ПР (подбор по опросному листу)",
        "signal": "4–20 мА + HART / RS-485 Modbus RTU",
        "accuracy": "Не хуже ±0,15% по перепаду давления",
        "ip": "Не ниже IP66 / IP67",
        "ex": "1Ex ia IIC T6 Ga (для контура природного газа)",
        "integration": "Вычислитель расхода → Modbus TCP / МЭК 60870-5-104 в SCADA верхнего уровня",
        "unit_cost_rub": 96_000,
        "install_cost_rub": 34_000,
        "downtime_risk_k_rub_yr": 210_000,
    },
    "electrical": {
        "requirement_class": "Цифровой многофункциональный измерительный преобразователь",
        "model": "Пример аналога: ЭНИП-2 / СЭТ-4ТМ.03М (подбор по опросному листу)",
        "signal": "RS-485 Modbus RTU + Ethernet МЭК 60870-5-104",
        "accuracy": "Не хуже класса 0,2S",
        "ip": "Не ниже IP54 (щитовое исполнение передней панели)",
        "ex": "Не требуется (щитовое помещение ГРУ/РУ-6 кВ)",
        "integration": "Оптоволоконная / RS-485 шина в АСУ ТП ГРУ и АИИС КУЭ станции",
        "unit_cost_rub": 49_000,
        "install_cost_rub": 18_000,
        "downtime_risk_k_rub_yr": 160_000,
    },
}

PERIOD_LABELS: dict[str, tuple[str, float]] = {
    "12h": ("Текущая смена (12 часов)", 12.0),
    "24h": ("Суточный цикл (24 часа)", 24.0),
    "7d": ("Недельный мониторинг (7 суток)", 168.0),
    "30d": ("Месячный цикл обследования (30 суток)", 720.0),
}


def pick_digital_replacement(item: dict[str, Any], price_overrides: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    """Подбор технических требований и ориентировочного аналога цифрового датчика."""
    gtype = item.get("gauge_type") or "pressure"
    group = (item.get("group") or "").lower()
    is_hazardous = any(k in group for k in ("топлив", "газ", "мазут"))
    key = "pressure_ex" if (gtype == "pressure" and is_hazardous) else gtype
    spec = dict(DIGITAL_SENSOR_CATALOG.get(key, DIGITAL_SENSOR_CATALOG["pressure"]))
    if price_overrides and key in price_overrides:
        for pk in ("unit_cost_rub", "install_cost_rub", "downtime_risk_k_rub_yr"):
            if pk in price_overrides[key]:
                spec[pk] = max(0, int(price_overrides[key][pk]))
    cal = item.get("calibration") or {}
    v_min, v_max = cal.get("v_min", 0), cal.get("v_max", 16)
    spec["meas_range"] = f"{v_min}–{v_max} {item.get('unit', '')}".strip()
    if is_hazardous and "1Ex" not in spec["ex"]:
        spec["ex"] = "1Ex ia IIC T6 Ga (ТР ТС 012/2011)"
    spec["catalog_key"] = key
    return spec


def llm_status() -> dict[str, Any]:
    configured = bool(config.LLM_BASE_URL)
    return {
        "configured": configured,
        "base_url": config.LLM_BASE_URL or None,
        "model": config.LLM_MODEL if configured else None,
        "mode_default": "deterministic",
        "airgapped_ready": True,
    }


def _fmt_num(val: float | None, decimals: int = 2) -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        if not math.isfinite(f):
            return "—"
    except (TypeError, ValueError):
        return "—"
    return f"{f:.{decimals}f}".replace(".", ",").replace("-", "−")


def _fmt_thr_range(thr: dict[str, Any], decimals: int = 2) -> str:
    parts = []
    for k, lbl in (("ll_alert", "LL"), ("l_warn", "L"), ("h_warn", "H"), ("hh_alert", "HH")):
        v = thr.get(k)
        if v is not None:
            parts.append(f"{lbl}={_fmt_num(float(v), decimals)}")
    return ", ".join(parts) if parts else "не заданы"


def _parse_iso(ts: Any) -> float | None:
    if not ts:
        return None
    try:
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


async def _try_llm_enrichment(summary_prompt: str) -> tuple[str | None, str]:
    """Опциональное стилистическое обогащение выводов через Ollama/vLLM/OpenAI-compatible API."""
    if not config.LLM_BASE_URL:
        return None, "deterministic (LLM URL не задан)"
    endpoint = config.LLM_BASE_URL.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    body = {
        "model": config.LLM_MODEL,
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты инженер-проектировщик АСУ ТП энергетической компании. "
                    "Сформулируй краткое, строгое, технически грамотное резюме (3–5 предложений) "
                    "проекта обследования аналоговых КИПиА исключительно по приведённым фактам без выдумывания чисел."
                ),
            },
            {"role": "user", "content": summary_prompt},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            if text:
                return text, f"llm_enhanced ({config.LLM_MODEL})"
    except Exception as exc:
        logger.info("LLM enrichment unavailable, using deterministic mode: %s", exc)
    return None, "deterministic (fallback: LLM недоступна)"


def build_evidence_frame_jpeg(item: dict[str, Any], real_snapshot: bytes | None = None) -> bytes:
    """Возвращает реальный стоп-кадр события или явно маркированный синтетический кадр (без фиктивного CONF)."""
    if real_snapshot:
        return real_snapshot
    cal = item.get("calibration") or {}
    raw_conf = item.get("cv_confidence_pct")
    conf_01 = (float(raw_conf) / 100.0) if (raw_conf is not None and math.isfinite(float(raw_conf))) else None
    frame = render_gauge_frame(
        code=item.get("code") or item["id"],
        name=item.get("name") or "",
        unit=item.get("unit") or "",
        value=item.get("value"),
        v_min=float(cal.get("v_min", 0.0)),
        v_max=float(cal.get("v_max", 10.0)),
        thresholds=item.get("thresholds"),
        level=item.get("level") or "normal",
        annotate_cv=True,
        confidence=conf_01,
        is_synthetic=True,
        width=640,
        height=440,
    )
    return encode_jpeg(frame, 86) or b""


async def generate_spec_bundle(
    *,
    dispatch_overview: dict[str, Any],
    events: list[dict[str, Any]],
    snapshot_lookup: dict[str, bytes],
    period: str = "12h",
    group_filter: str = "all",
    instrument_id: str = "all",
    requisites: dict[str, str] | None = None,
    mode: str = "deterministic",
    history_stats: dict[str, dict[str, Any]] | None = None,
    economics_config: dict[str, Any] | None = None,
    strict_scope: bool = False,
    now_utc: _dt.datetime | None = None,
) -> dict[str, Any]:
    """
    Собирает единую структуру инженерного проекта ТЗ, Markdown-предпросмотр и данные для `.docx`.

    Ключевые гарантии достоверности (DEF-03, DEF-04, DEF-17):
      • Фильтрует `events` и использует `history_stats` из SQLite `readings` строго за
        интервал `[now - period_hours, now]`.
      • Не подменяет неизвестный фильтр на `all_items[:6]` (при `strict_scope=True`
        выбрасывает `ValueError`, иначе возвращает пустой скоуп с явным предупреждением).
      • Не включает исправные приборы в дефектную ведомость и ТЗ.
      • Не включает чисто оптические проблемы камеры в CAPEX замены манометров.
      • При `capex_rub == 0` или `net_annual_effect <= 0` срок окупаемости = `None` («—»).
    """
    if period not in PERIOD_LABELS:
        raise ValueError(f"Недопустимый период обследования: {period}. Допустимо: {', '.join(PERIOD_LABELS)}")

    req = requisites or {}
    eco_cfg = economics_config or {}
    plant_name = (req.get("plant_name") or config.PLANT_NAME).strip()
    branch_name = (req.get("branch_name") or config.PLANT_BRANCH).strip()
    workshop = (req.get("workshop") or ("Котлотурбинный цех (КТЦ)" if group_filter == "all" else group_filter)).strip()
    customer = (req.get("customer") or "ПАО «Интер РАО»").strip()
    contractor = (req.get("contractor") or "Служба КИПиА, АСУ ТП и видеоаналитики GaugeVision AI").strip()

    now_dt = now_utc or _dt.datetime.now(_dt.timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)
    date_str = now_dt.strftime("%d.%m.%Y")
    doc_number = (req.get("doc_number") or f"ТЗ-КИП-{now_dt.strftime('%Y%m%d')}-01").strip()
    period_label, period_hours = PERIOD_LABELS[period]
    window_start_dt = now_dt - _dt.timedelta(hours=period_hours)
    window_start_ts = window_start_dt.timestamp()
    window_end_ts = now_dt.timestamp()

    all_items: list[dict[str, Any]] = list(dispatch_overview.get("instruments") or [])
    filter_applied = (bool(instrument_id) and instrument_id != "all") or (bool(group_filter) and group_filter != "all")
    scoped = all_items
    if instrument_id and instrument_id != "all":
        scoped = [x for x in all_items if x["id"] == instrument_id]
    elif group_filter and group_filter != "all":
        scoped = [x for x in all_items if x["group"] == group_filter]

    filter_matched = bool(scoped) or not filter_applied
    if filter_applied and not scoped and strict_scope:
        raise ValueError(
            f"По заданному фильтру (group='{group_filter}', instrument_id='{instrument_id}') приборы не найдены"
        )

    # Фильтрация событий строго по выбранному временному диапазону [now - period_hours, now] (DEF-03)
    scoped_ids = {x["id"] for x in scoped}
    period_events: list[dict[str, Any]] = []
    events_by_inst: dict[str, list[dict[str, Any]]] = {}
    for ev in events or []:
        cid = ev.get("cam_id")
        if cid not in scoped_ids:
            continue
        ev_ts = _parse_iso(ev.get("ts"))
        if ev_ts is not None and (ev_ts < window_start_ts or ev_ts > window_end_ts + 60.0):
            continue
        period_events.append(ev)
        events_by_inst.setdefault(str(cid), []).append(ev)

    # Обогащаем каждую позицию реальной исторической статистикой за выбранный период
    hstats_map = history_stats or {}
    enriched_scoped: list[dict[str, Any]] = []
    max_cov_min = 0.0
    total_db_samples = 0
    for raw_x in scoped:
        x = dict(raw_x)
        hs = hstats_map.get(x["id"])
        inst_evs = events_by_inst.get(x["id"], [])
        alarm_evs = [e for e in inst_evs if e.get("kind") == "alarm" and e.get("level") in ("warning", "alert")]
        x["period_trips"] = len(alarm_evs)
        x["period_events_count"] = len(inst_evs)
        if hs and hs.get("samples_count", 0) > 0:
            total_db_samples += int(hs["samples_count"])
            max_cov_min = max(max_cov_min, float(hs.get("coverage_min") or 0.0))
            x["period_samples"] = int(hs["samples_count"])
            x["period_min"] = hs.get("min_val")
            x["period_max"] = hs.get("max_val")
            x["period_avg"] = hs.get("avg_val")
            x["period_peak_ts"] = hs.get("peak_ts")
            x["period_first_ts"] = hs.get("first_ts")
            x["period_last_ts"] = hs.get("last_ts")
            x["period_coverage_min"] = float(hs.get("coverage_min") or 0.0)
            x["overload_min"] = float(hs.get("overload_min") or 0.0)
            if hs.get("peak_rate_per_min") is not None:
                x["peak_rate_per_min"] = max(float(x.get("peak_rate_per_min") or 0.0), float(hs["peak_rate_per_min"]))
        else:
            x["period_samples"] = 0
            x["period_min"] = x.get("value")
            x["period_max"] = x.get("value")
            x["period_avg"] = x.get("value")
            x["period_peak_ts"] = None
            x["period_first_ts"] = None
            x["period_last_ts"] = None
            x["period_coverage_min"] = 0.0
            # Если исторических строк в БД за период нет — оставляем фактический live-накопитель
            x["overload_min"] = float(x.get("overload_min") or 0.0)
        enriched_scoped.append(x)

    coverage_hours = round(max_cov_min / 60.0, 2)
    coverage_sufficient = total_db_samples > 0 and (coverage_hours >= period_hours * 0.5)

    # Строгий отбор дефектных позиций (DEF-04): НИКАКОГО принудительного fallback на исправные приборы!
    defective = [
        x for x in enriched_scoped
        if x.get("modernization_needed")
        or float(x.get("health_score", 100.0)) < 85.0
        or x.get("root_cause", "nominal") != "nominal"
        or int(x.get("period_trips", 0)) > 0
    ]
    defective.sort(key=lambda x: (float(x.get("health_score", 100.0)), -int(x.get("period_trips", 0))))

    # Позиции, требующие модернизации датчика (исключаем чисто оптические проблемы камеры!)
    modernize_candidates = [
        x for x in defective
        if x.get("root_cause") in ("process_anomaly", "instrument_degradation")
        or x.get("modernization_needed")
        or int(x.get("period_trips", 0)) > 0
    ]

    # Конфигурируемые экономические параметры (DEF-04)
    comm_rate = float(eco_cfg.get("commissioning_rate", config.ECO_COMMISSIONING_RATE))
    comm_rate = max(0.0, min(1.0, comm_rate)) if math.isfinite(comm_rate) else config.ECO_COMMISSIONING_RATE
    rounds_per_unit = int(eco_cfg.get("rounds_savings_per_unit_rub", config.ECO_ROUNDS_SAVINGS_RUB_YR))
    rounds_per_unit = max(0, rounds_per_unit)
    opex_per_unit = int(eco_cfg.get("opex_per_sensor_rub_yr", config.ECO_OPEX_PER_SENSOR_RUB_YR))
    opex_per_unit = max(0, opex_per_unit)
    risk_mult = float(eco_cfg.get("downtime_risk_multiplier", 1.0))
    risk_mult = max(0.0, risk_mult) if math.isfinite(risk_mult) else 1.0
    price_overrides = eco_cfg.get("price_overrides") if isinstance(eco_cfg.get("price_overrides"), dict) else None
    is_demo_pricing = bool(eco_cfg.get("demo_pricing", config.is_demo_mode()))

    tz_items: list[dict[str, Any]] = []
    total_hw_rub = 0
    total_smr_rub = 0
    total_risk_avoided_rub = 0
    for item in modernize_candidates:
        repl = pick_digital_replacement(item, price_overrides=price_overrides)
        hs_val = float(item.get("health_score", 100.0))
        severity_k = 1.25 if hs_val < 50.0 else (1.0 if hs_val < 75.0 else 0.72)
        risk_saved = int(round(repl["downtime_risk_k_rub_yr"] * severity_k * risk_mult))
        total_hw_rub += int(repl["unit_cost_rub"])
        total_smr_rub += int(repl["install_cost_rub"])
        total_risk_avoided_rub += risk_saved
        tz_items.append({
            "item": item,
            "replacement": repl,
            "risk_saved_rub": risk_saved,
        })

    commissioning_rub = int(round((total_hw_rub + total_smr_rub) * comm_rate))
    total_capex_rub = total_hw_rub + total_smr_rub + commissioning_rub
    rounds_savings_rub = len(tz_items) * rounds_per_unit
    gross_annual_effect_rub = total_risk_avoided_rub + rounds_savings_rub
    opex_rub_yr = len(tz_items) * opex_per_unit
    annual_effect_rub = max(0, gross_annual_effect_rub - opex_rub_yr)

    # Корректная обработка нулевых инвестиций или отсутствия чистого экономического эффекта (DEF-04)
    if total_capex_rub > 0 and annual_effect_rub > 0:
        payback_years: float | None = round(total_capex_rub / float(annual_effect_rub), 2)
        payback_months: int | None = max(1, int(round(payback_years * 12.0)))
    else:
        payback_years = None
        payback_months = None

    avg_hs = round(sum(float(x.get("health_score", 100.0)) for x in enriched_scoped) / max(1, len(enriched_scoped)), 1) if enriched_scoped else 0.0
    crit_cnt = sum(1 for x in enriched_scoped if float(x.get("health_score", 100.0)) < 50.0)
    warn_cnt = sum(1 for x in enriched_scoped if 50.0 <= float(x.get("health_score", 100.0)) < 75.0)
    optical_only_items = [x for x in defective if x not in modernize_candidates]

    # Формирование объективного резюме без фабрикации
    if not filter_matched:
        base_summary = (
            f"По заданному фильтру (цех «{group_filter}», прибор «{instrument_id}») "
            f"приборы в реестре не найдены. Проверьте параметры отбора."
        )
    elif not enriched_scoped:
        base_summary = (
            f"За период «{period_label}» исходные данные телеметрии отсутствуют (обследовано 0 приборов). "
            f"Формирование дефектной ведомости и расчёт модернизации невозможны из-за недостатка данных."
        )
    elif not defective:
        base_summary = (
            f"По результатам видеомониторинга за период «{period_label}» обследовано {len(enriched_scoped)} "
            f"аналоговых приборов КИПиА (средний индекс техсостояния — {_fmt_num(avg_hs, 1)}%, "
            f"зарегистрировано инцидентов в периоде — {len(period_events)}). "
            f"Дефектов оборудования, систематических перегрузок и показаний к замене/модернизации КИПиА не выявлено."
        )
    elif not tz_items:
        base_summary = (
            f"За период «{period_label}» обследовано {len(enriched_scoped)} приборов. "
            f"Выявлено {len(optical_only_items)} замечаний к условиям видеоконтроля/связи (обслуживание камер), "
            f"технологических дефектов самих КИПиА и оснований для капитальной модернизации датчиков не установлено."
        )
    else:
        pb_txt = (
            f"{payback_months} мес. ({_fmt_num(payback_years, 2)} года)"
            if payback_months is not None and payback_years is not None
            else "не рассчитывается (недостаточно экономического эффекта)"
        )
        base_summary = (
            f"По результатам видеомониторинга за период «{period_label}» обследовано {len(enriched_scoped)} "
            f"аналоговых приборов КИПиА (средний индекс техсостояния — {_fmt_num(avg_hs, 1)}%, "
            f"инцидентов за период — {len(period_events)}). Выявлено {len(defective)} позиций с замечаниями "
            f"(критическое состояние — {crit_cnt}, деградация — {warn_cnt}, только оптика/связь — {len(optical_only_items)}). "
            f"Предварительная оценка модернизации {len(tz_items)} приоритетных позиций: "
            f"ориентировочный CAPEX {total_capex_rub / 1000:.1f} тыс. ₽, чистый годовой эффект {annual_effect_rub / 1000:.1f} тыс. ₽/год "
            f"(с учётом OPEX {opex_rub_yr / 1000:.1f} тыс. ₽/год), ориентировочный срок окупаемости — {pb_txt}."
        )

    if enriched_scoped and not coverage_sufficient:
        cov_note = (
            f" Примечание по охвату данных: в архиве SQLite за запрошенные {int(period_hours)} ч "
            f"зафиксировано {total_db_samples} отсчётов (фактический охват {coverage_hours:.2f} ч); "
            f"для окончательного ТЗ требуется накопление полной истории за весь период обследования."
        )
        base_summary += cov_note

    engine_used = "deterministic"
    executive_summary = base_summary
    if mode == "llm_enhanced":
        llm_text, engine_used = await _try_llm_enrichment(base_summary)
        if llm_text:
            executive_summary = llm_text

    # Формирование Markdown-документа (все 5 обязательных разделов + правовой дисклеймер)
    md_lines: list[str] = [
        f"# Проект дефектной ведомости и Технического задания на модернизацию КИПиА № {doc_number}",
        "",
        f"> **{LEGAL_DISCLAIMER}**",
        "",
        f"**Энергообъект:** {plant_name} ({branch_name})  ",
        f"**Цех / узел:** {workshop}  ",
        f"**Заказчик:** {customer}  ",
        f"**Исполнитель:** {contractor}  ",
        f"**Период обследования:** {period_label} ({window_start_dt.strftime('%d.%m.%Y %H:%M UTC')} — {now_dt.strftime('%d.%m.%Y %H:%M UTC')})  ",
        f"**Фактический охват БД SQLite:** {total_db_samples} записей ({coverage_hours:.2f} ч из {int(period_hours)} ч), событий в окне: {len(period_events)}  ",
        f"**Дата формирования:** {date_str}  ",
        f"**Режим генерации:** `{engine_used}`",
        "",
        "> **Резюме обследования:** " + executive_summary,
        "",
        "## 1. Паспорт обследуемого технологического узла и реестр аналоговых КИПиА",
        "",
    ]
    if not enriched_scoped:
        md_lines.append("*Данные по выбранному фильтру отсутствуют.*")
    else:
        md_lines += [
            "| Поз. (код) | Наименование прибора | Узел / цех | Шкала | Уставки (LL / L / H / HH) | Канал контроля |",
            "|---|---|---|---|---|---|",
        ]
        for x in enriched_scoped:
            cal = x.get("calibration") or {}
            rng = f"{_fmt_num(cal.get('v_min'), x['decimals'])}–{_fmt_num(cal.get('v_max'), x['decimals'])} {x['unit']}"
            ch_lbl = "Камера CV (живой поток)" if x["source_kind"] != "simulated" else f"Стендовая симуляция ({config.EDGE_NODE_ID})"
            md_lines.append(
                f"| `{x['code']}` | {x['name']} | {x['group']} | {rng} | {_fmt_thr_range(x['thresholds'], x['decimals'])} | {ch_lbl} |"
            )

    md_lines += [
        "",
        "## 2. Сводный протокол инструментального видеомониторинга за период",
        "",
    ]
    if not enriched_scoped:
        md_lines.append("*Протокол пуст: за выбранный период и фильтр приборы не найдены.*")
    else:
        md_lines += [
            "| Код | Текущее знач. | Мин / Макс за период | Пик скорости | Дребезг | Перегр., мин | Инцид. за период | Тех. Health / Оптика |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for x in enriched_scoped:
            val_s = f"{_fmt_num(x['value'], x['decimals'])} {x['unit']}" if x["valid"] else "НЕТ ДАННЫХ"
            mm_s = (
                f"{_fmt_num(x.get('period_min'), x['decimals'])} / {_fmt_num(x.get('period_max'), x['decimals'])}"
                if x.get("period_samples", 0) > 0
                else f"текущ. {val_s}"
            )
            rate_s = f"{x['rate_symbol']}={_fmt_num(x['peak_rate_per_min'], 2)} {x['unit']}/мин"
            chat_s = f"{_fmt_num(x['chatter_pct'], 1)}%"
            opt_h = x.get("optical_health", x.get("optical_score", 0.0))
            md_lines.append(
                f"| `{x['code']}` | {val_s} | {mm_s} | {rate_s} | {chat_s} | {_fmt_num(x['overload_min'], 2)} | "
                f"{x['period_trips']} (12ч: {x['trips_shift']}/24ч: {x['trips_24h']}) | "
                f"**{_fmt_num(x['health_score'], 1)}%** / {_fmt_num(opt_h, 0)}% |"
            )

    md_lines += [
        "",
        "## 3. Дефектная ведомость и диагностика причин",
        "",
    ]
    if not defective:
        md_lines.append(
            "По результатам обследования за выбранный период **дефектов оборудования и нарушений технологических уставок не выявлено**. "
            "Все обследованные приборы находятся в штатном состоянии."
        )
    else:
        md_lines += [
            "| Код | Узел | Тех. Health | Оптика | Класс первопричины | Зафиксированное отклонение и гипотеза |",
            "|---|---|---:|---:|---|---|",
        ]
        for x in defective:
            opt_h = x.get("optical_health", x.get("optical_score", 0.0))
            md_lines.append(
                f"| `{x['code']}` | {x['group']} | **{_fmt_num(x['health_score'], 1)}%** | {_fmt_num(opt_h, 0)}% | "
                f"{x['root_cause_meta']['label']} | {x['recommendation']} |"
            )
        md_lines += [
            "",
            "*Примечание: доказательные кадры (реальные стоп-кадры при наличии или маркированные иллюстрации при отсутствии живого кадра) встроены в файл `.docx` (раздел 3).*",
        ]

    md_lines += [
        "",
        "## 4. Техническое задание на модернизацию узла КИПиА (проект)",
        "",
    ]
    if not tz_items:
        md_lines.append(
            "По результатам обследования **обоснованных показаний к замене аналоговых КИПиА на цифровые датчики не выявлено**. "
            + ("Замечания раздела 3 относятся исключительно к обслуживанию контура видеоконтроля/связи." if optical_only_items else "")
        )
    else:
        md_lines += [
            "Настоящий проект Технического задания определяет ориентировочные технические требования к замене проблемных аналоговых стрелочных КИПиА на промышленные цифровые средства измерений. Окончательный выбор марок и исполнений выполняется по опросным листам технологического процесса и результатам конкурсных процедур.",
            "",
            "| Заменяемый прибор | Требуемый класс СИ и ориентировочный аналог | Диапазон | Выходной сигнал | Класс точности | Защита IP / Ex | Схема интеграции в АСУ ТП |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in tz_items:
            it = row["item"]
            rp = row["replacement"]
            md_lines.append(
                f"| `{it['code']}` {it['short_name']} | **{rp['requirement_class']}** ({rp['model']}) | {rp['meas_range']} | "
                f"{rp['signal']} | {rp['accuracy']} | {rp['ip']}; {rp['ex']} | {rp['integration']} |"
            )
        md_lines += [
            "",
            "### Обязательные технические требования к модернизации",
            "- Средства измерений должны быть внесены в Государственный реестр СИ РФ (ФЗ-102) и поставляться с действующей первичной поверкой.",
            "- Исполнение приборов для топливного, газового и мазутного хозяйства — взрывозащищённое не ниже `1Ex ia IIC T6 Ga` согласно ТР ТС 012/2011.",
            "- Обеспечить гальваническую развязку измерительных каналов, диагностику обрыва/КЗ токовой петли (NAMUR NE43) и передачу статусов достоверности в АСУ ТП (Modbus TCP / OPC UA / МЭК 60870-5-104).",
            "- Контур видеоаналитики GaugeVision AI сохраняется исключительно как вспомогательный информационный канал на период ПНР.",
        ]

    pb_md = (
        f"**{payback_months} мес. ({_fmt_num(payback_years, 2)} года)**"
        if payback_months is not None and payback_years is not None
        else "**— (не рассчитывается: инвестиции не требуются или чистый эффект ≤ 0)**"
    )
    pricing_badge = "Стендовые ориентировочные расценки (подлежат уточнению по КП)" if is_demo_pricing else "Параметризованная оценка по входным ставкам"

    md_lines += [
        "",
        "## 5. Технико-экономическое обоснование (предварительная оценка)",
        "",
        f"*Статус расчёта: {pricing_badge}. Ставка ПНР: {comm_rate * 100:.0f}%, экономия обходов: {rounds_per_unit / 1000:.1f} тыс. ₽/год на ед., OPEX цифровых СИ: {opex_per_unit / 1000:.1f} тыс. ₽/год на ед.*",
        "",
        "| Показатель | Значение | Основание расчёта |",
        "|---|---:|---|",
        f"| Ориентировочная стоимость цифровых датчиков ({len(tz_items)} шт.) | **{total_hw_rub / 1000:.1f} тыс. ₽** | Справочная оценка (уточняется по КП) |",
        f"| Строительно-монтажные работы (СМР и кабельные трассы) | **{total_smr_rub / 1000:.1f} тыс. ₽** | Укрупнённый норматив монтажа |",
        f"| Пусконаладочные работы (ПНР и привязка тегов АСУ ТП) | **{commissioning_rub / 1000:.1f} тыс. ₽** | {comm_rate * 100:.0f}% от оборудования и СМР |",
        f"| **Итого капитальные затраты (CAPEX)** | **{total_capex_rub / 1000:.1f} тыс. ₽** | Оборудование + СМР + ПНР |",
        f"| Оценочное снижение риска аварийного простоя | **{total_risk_avoided_rub / 1000:.1f} тыс. ₽/год** | Справочная модель ущерба × коэф. риска ({risk_mult:.2f}) |",
        f"| Экономия на ручных обходах и внеплановых проверках | **{rounds_savings_rub / 1000:.1f} тыс. ₽/год** | {rounds_per_unit / 1000:.1f} тыс. ₽/год × {len(tz_items)} ед. |",
        f"| Ежегодные эксплуатационные затраты (OPEX цифровых СИ) | **−{opex_rub_yr / 1000:.1f} тыс. ₽/год** | Поверка и обслуживание: {opex_per_unit / 1000:.1f} тыс. ₽/год × {len(tz_items)} ед. |",
        f"| **Чистый годовой экономический эффект** | **{annual_effect_rub / 1000:.1f} тыс. ₽/год** | Валовой эффект − OPEX |",
        f"| **Простой срок окупаемости модернизации** | {pb_md} | CAPEX / чистый годовой эффект |",
    ]

    markdown_text = "\n".join(md_lines)
    return {
        "doc_number": doc_number,
        "date_str": date_str,
        "plant_name": plant_name,
        "branch_name": branch_name,
        "workshop": workshop,
        "customer": customer,
        "contractor": contractor,
        "period": period,
        "period_label": period_label,
        "period_hours": period_hours,
        "window_start_utc": window_start_dt.isoformat(timespec="seconds"),
        "window_end_utc": now_dt.isoformat(timespec="seconds"),
        "db_samples_count": total_db_samples,
        "coverage_hours": coverage_hours,
        "coverage_sufficient": coverage_sufficient,
        "period_events_count": len(period_events),
        "filter_matched": filter_matched,
        "engine_used": engine_used,
        "executive_summary": executive_summary,
        "disclaimer": LEGAL_DISCLAIMER,
        "scoped_items": enriched_scoped,
        "defective_items": defective,
        "tz_items": tz_items,
        "economics": {
            "hw_rub": total_hw_rub,
            "smr_rub": total_smr_rub,
            "commissioning_rub": commissioning_rub,
            "commissioning_rate": comm_rate,
            "capex_rub": total_capex_rub,
            "risk_avoided_rub": total_risk_avoided_rub,
            "rounds_savings_rub": rounds_savings_rub,
            "gross_annual_effect_rub": gross_annual_effect_rub,
            "opex_rub_yr": opex_rub_yr,
            "annual_effect_rub": annual_effect_rub,
            "payback_months": payback_months,
            "payback_years": payback_years,
            "demo_pricing": is_demo_pricing,
        },
        "markdown": markdown_text,
        "snapshot_lookup": snapshot_lookup,
    }


def render_spec_docx(bundle: dict[str, Any]) -> bytes:
    """Формирует валидный OpenXML `.docx` проект документа из собранного `bundle`."""
    doc = DocxBuilder(
        doc_title=f"Проект ТЗ на модернизацию КИПиА № {bundle['doc_number']}",
        header_text=f"{bundle['customer']}  |  {bundle['plant_name']}  |  ПРОЕКТ № {bundle['doc_number']}",
        footer_left=f"GaugeVision AI (проект, не СИ ФЗ-102, не для ПАЗ) — {bundle['date_str']}",
    )

    doc.add_title_block(
        org_line=f"{bundle['customer']} — {bundle['branch_name']}",
        doc_kind="Инженерный проект: Дефектная ведомость и Техническое задание на модернизацию КИПиА",
        title=f"{bundle['plant_name']} — {bundle['workshop']}",
        subtitle=f"По результатам вспомогательного видеомониторинга за период: {bundle['period_label']}",
        doc_number=bundle["doc_number"],
        date_str=bundle["date_str"],
    )

    doc.add_callout("Статус документа и метрологическое разграничение", bundle.get("disclaimer") or LEGAL_DISCLAIMER)

    doc.add_table(
        [
            ["Реквизит", "Значение"],
            ["Наименование энергообъекта", f"{bundle['plant_name']} ({bundle['branch_name']})"],
            ["Обследуемый цех / узел", bundle["workshop"]],
            ["Заказчик", bundle["customer"]],
            ["Исполнитель обследования", bundle["contractor"]],
            ["Период видеомониторинга", f"{bundle['period_label']} ({bundle.get('window_start_utc', '')} — {bundle.get('window_end_utc', '')})"],
            ["Фактический охват данных БД", f"{bundle.get('db_samples_count', 0)} отсчётов ({bundle.get('coverage_hours', 0.0):.2f} ч), событий: {bundle.get('period_events_count', 0)}"],
            ["Контур формирования", f"GaugeVision AI ({bundle['engine_used']})"],
        ],
        col_widths_dxa=[3100, 6100],
    )

    doc.add_callout("Резюме обследования", bundle["executive_summary"])

    # Раздел 1
    doc.add_heading("1. Паспорт обследуемого технологического узла и реестр аналоговых КИПиА", level=1)
    if not bundle["scoped_items"]:
        doc.add_paragraph("По выбранному фильтру приборы в реестре не найдены.")
    else:
        passport_rows = [["Код", "Наименование КИПиА", "Узел / цех", "Шкала", "Уставки (LL/L/H/HH)", "Канал"]]
        for x in bundle["scoped_items"]:
            cal = x.get("calibration") or {}
            rng = f"{_fmt_num(cal.get('v_min'), x['decimals'])}–{_fmt_num(cal.get('v_max'), x['decimals'])} {x['unit']}"
            ch_lbl = "Камера CV" if x["source_kind"] != "simulated" else f"Стенд ({config.EDGE_NODE_ID})"
            passport_rows.append([
                x["code"], x["name"], x["group"], rng,
                _fmt_thr_range(x["thresholds"], x["decimals"]), ch_lbl,
            ])
        doc.add_table(passport_rows, col_widths_dxa=[950, 2450, 1550, 1100, 2150, 1000], font_half_pt=15)

    # Раздел 2
    doc.add_heading("2. Сводный протокол инструментального видеомониторинга", level=1)
    if not bundle["scoped_items"]:
        doc.add_paragraph("Данные за выбранный период отсутствуют.")
    else:
        proto_rows = [["Код", "Значение", "Мин/Макс", "Пик dV/dt", "Дребезг", "Перегр., мин", "Инцид.", "Тех. HS / Оптика"]]
        for x in bundle["scoped_items"]:
            val_s = f"{_fmt_num(x['value'], x['decimals'])} {x['unit']}" if x["valid"] else "НЕТ ДАННЫХ"
            mm_s = (
                f"{_fmt_num(x.get('period_min'), x['decimals'])}/{_fmt_num(x.get('period_max'), x['decimals'])}"
                if x.get("period_samples", 0) > 0
                else "текущ."
            )
            opt_h = x.get("optical_health", x.get("optical_score", 0.0))
            proto_rows.append([
                x["code"],
                val_s,
                mm_s,
                f"{_fmt_num(x['peak_rate_per_min'], 2)}/мин",
                f"{_fmt_num(x['chatter_pct'], 1)}%",
                _fmt_num(x["overload_min"], 2),
                str(x.get("period_trips", 0)),
                f"{_fmt_num(x['health_score'], 1)}% / {_fmt_num(opt_h, 0)}%",
            ])
        doc.add_table(proto_rows, col_widths_dxa=[850, 1250, 1200, 1200, 850, 950, 800, 2100], font_half_pt=15)

    # Раздел 3
    doc.add_heading("3. Дефектная ведомость и доказательные кадры нарушений", level=1)
    if not bundle["defective_items"]:
        doc.add_paragraph(
            "По результатам обследования за выбранный период дефектов оборудования и нарушений технологических уставок не выявлено."
        )
    else:
        def_rows = [["Код", "Узел / цех", "Тех. HS", "Первопричина", "Выявленное отклонение и гипотеза"]]
        for x in bundle["defective_items"]:
            def_rows.append([
                x["code"],
                x["group"],
                f"{_fmt_num(x['health_score'], 1)}%",
                x["root_cause_meta"]["label"],
                x["recommendation"],
            ])
        doc.add_table(def_rows, col_widths_dxa=[950, 1500, 1000, 1850, 3900], font_half_pt=16)

        snaps: dict[str, bytes] = bundle.get("snapshot_lookup") or {}
        for fig_idx, x in enumerate(bundle["defective_items"][:4], start=1):
            has_real = bool(snaps.get(x["id"]))
            img_bytes = build_evidence_frame_jpeg(x, snaps.get(x["id"]))
            if img_bytes:
                val_txt = f"{_fmt_num(x['value'], x['decimals'])} {x['unit']}" if x["valid"] else "поток прерван"
                src_note = "живой стоп-кадр CV" if has_real else "синтетическая иллюстрация (живой снимок отсутствует)"
                doc.add_image(
                    img_bytes,
                    caption=(
                        f"Рисунок {fig_idx} — Кадр КИПиА {x['code']} ({x['short_name']}, {src_note}): "
                        f"{val_txt}, Тех. Health Score {_fmt_num(x['health_score'], 1)}%, класс: {x['root_cause_meta']['short']}"
                    ),
                    width_cm=12.6,
                )

    # Раздел 4
    doc.add_heading("4. Техническое задание на модернизацию узла КИПиА (проект)", level=1)
    if not bundle["tz_items"]:
        doc.add_paragraph("Показаний к замене или модернизации аналоговых КИПиА за выбранный период не выявлено.")
    else:
        doc.add_paragraph(
            "Ниже приведены ориентировочные технические требования к замене проблемных аналоговых приборов на "
            "цифровые преобразователи (примеры аналогов не ограничивают конкуренцию и уточняются по опросным листам):"
        )
        tz_rows = [["Прибор", "Класс СИ и ориентир. аналог", "Диапазон", "Сигнал", "Точность", "IP / Ex", "Интеграция АСУ ТП"]]
        for row in bundle["tz_items"]:
            it = row["item"]
            rp = row["replacement"]
            tz_rows.append([
                f"{it['code']}\n{it['short_name']}",
                f"{rp['requirement_class']}\n({rp['model']})",
                rp["meas_range"],
                rp["signal"],
                rp["accuracy"],
                f"{rp['ip']}\n{rp['ex']}",
                rp["integration"],
            ])
        doc.add_table(tz_rows, col_widths_dxa=[1150, 1750, 900, 1100, 950, 1450, 1900], font_half_pt=14)

        doc.add_heading("4.1. Общие требования к поставке, монтажу и интеграции", level=2)
        doc.add_bullet("Метрологическое обеспечение: ", "наличие свидетельства об утверждении типа СИ РФ (ФЗ-102) и первичной поверки.")
        doc.add_bullet("Взрывозащита и климатика: ", "для позиций газового и мазутного хозяйства — 1Ex ia IIC T6 Ga (ТР ТС 012/2011), степень защиты не ниже IP65/IP67.")
        doc.add_bullet("Интеграция с АСУ ТП: ", "подключение в шкафы УСО / ПТК с поддержкой диагностики цепи (NAMUR NE43) и передачи статусов достоверности в SCADA.")
        doc.add_bullet("Резервирование на период ПНР: ", "использование GaugeVision AI исключительно в качестве вспомогательного информационного мониторинга.")

    # Раздел 5
    eco = bundle["economics"]
    pb_str = (
        f"{eco['payback_months']} мес. ({_fmt_num(eco['payback_years'], 2)} года)"
        if eco.get("payback_months") is not None and eco.get("payback_years") is not None
        else "— (не рассчитывается)"
    )
    doc.add_heading("5. Технико-экономическое обоснование и предварительная оценка окупаемости", level=1)
    eco_rows = [
        ["Статья расчёта", "Сумма / показатель", "Комментарий / допущения"],
        [f"Цифровые датчики ({len(bundle['tz_items'])} шт.)", f"{eco['hw_rub'] / 1000:.1f} тыс. ₽", "Ориентировочная оценка (уточняется по КП)"],
        ["Строительно-монтажные работы (СМР)", f"{eco['smr_rub'] / 1000:.1f} тыс. ₽", "Укрупнённый норматив монтажа"],
        ["Пусконаладочные работы (ПНР и АСУ ТП)", f"{eco['commissioning_rub'] / 1000:.1f} тыс. ₽", f"{eco.get('commissioning_rate', 0.14) * 100:.0f}% от оборудования и СМР"],
        ["Итого капитальные вложения (CAPEX)", f"{eco['capex_rub'] / 1000:.1f} тыс. ₽", "Оборудование + СМР + ПНР"],
        ["Оценка снижения риска простоя", f"{eco['risk_avoided_rub'] / 1000:.1f} тыс. ₽/год", "Справочная оценка предотвращённого ущерба"],
        ["Экономия на обходах и проверках", f"{eco['rounds_savings_rub'] / 1000:.1f} тыс. ₽/год", "Снижение затрат на ручные обходы"],
        ["Ежегодный OPEX цифровых датчиков", f"−{eco.get('opex_rub_yr', 0) / 1000:.1f} тыс. ₽/год", "Поверка и регламентное обслуживание"],
        ["Чистый годовой экономический эффект", f"{eco['annual_effect_rub'] / 1000:.1f} тыс. ₽/год", "Валовой эффект − OPEX"],
        ["Простой срок окупаемости", pb_str, "CAPEX / чистый годовой эффект"],
    ]
    doc.add_table(eco_rows, col_widths_dxa=[3300, 2100, 3800], font_half_pt=17)

    doc.add_paragraph(
        f"Проект документа сформирован автоматически платформой GaugeVision AI ({bundle['date_str']}) в автономном промышленном контуре. "
        f"Подлежит обязательной инженерной проверке и утверждению.",
        italic=True,
        color="64748B",
        size_half_pt=17,
    )
    return doc.build_bytes()
