"""
GaugeVision AI — Трек №1: Умная система диспетчеризации (`dispatch_analyzer`).

Анализирует реальную телеметрию и историю событий приборов:
  • первая производная dP/dt, dT/dt, dV/dt и пиковая скорость по фактическим
    временным меткам (устойчивость к неравномерной дискретизации и дубликатам ts);
  • амплитуда высокочастотного «дребезга» стрелки строго по временному ряду
    (без скрытых захардкоженных профилей и подмешиваний, DEF-08);
  • суммарное время нахождения в зоне перегрузки (WARNING / CRITICAL) строго по
    фактическому накопленному времени (без фантомных добавок, DEF-08);
  • частота срабатываний уставок по реальным скользящим окнам 12 ч и 24 ч;
  • раздельная оценка 4 независимых индексов состояния (0–100%):
      - `equipment_health`      — технологическая нагрузка / режим оборудования;
      - `instrument_health`     — техническое состояние стрелочного прибора;
      - `optical_health`        — качество видеосигнала и достоверность CV;
      - `communication_health`  — доступность и стабильность канала связи;
    с сохранением совместимого `health_score` (отражает техсостояние узла/КИП
    и НЕ занижается из-за запотевания объектива камеры);
  • диагностические гипотезы с явным обоснованием, ссылками на измерения и
    уровнем уверенности (без выдачи эвристики за прогнозирование ресурса).
"""
from __future__ import annotations

import datetime as _dt
import math
import time
from collections import deque
from typing import Any

from . import config
from .db import utcnow_iso

ROOT_CAUSE_META: dict[str, dict[str, str]] = {
    "process_anomaly": {
        "code": "process_anomaly",
        "label": "Технологическое отклонение / перегрузка процесса",
        "short": "Техпроцесс",
        "tone": "alert",
    },
    "instrument_degradation": {
        "code": "instrument_degradation",
        "label": "Возможная деградация стрелочного прибора",
        "short": "Прибор КИП",
        "tone": "warning",
    },
    "optical_degradation": {
        "code": "optical_degradation",
        "label": "Ухудшение условий видеоконтроля / канала связи",
        "short": "Оптика / связь",
        "tone": "stale",
    },
    "nominal": {
        "code": "nominal",
        "label": "Штатное состояние",
        "short": "Норма",
        "tone": "normal",
    },
}


def _finite_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _parse_iso_ts(ts: Any) -> float | None:
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        return float(ts) if math.isfinite(float(ts)) else None
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


def _health_band(score: float) -> str:
    if score < 50.0:
        return "CRITICAL"
    if score < 75.0:
        return "DEGRADED"
    if score < 90.0:
        return "ATTENTION"
    return "HEALTHY"


def _rate_label(gauge_type: str) -> str:
    return {
        "pressure": "dP/dt",
        "temperature": "dT/dt",
        "draft": "dP/dt",
        "level": "dH/dt",
        "flow": "dQ/dt",
        "electrical": "dW/dt",
    }.get(gauge_type, "dV/dt")


def _compute_chatter(values: list[float], span: float) -> tuple[float, float]:
    """
    Оценивает высокочастотный «дребезг» стрелки: средняя невязка относительно
    локального 3-точечного сглаживания (устойчива к NaN и выбросам).
    Возвращает (амплитуда_в_ед, процент_от_шкалы).
    """
    clean = [v for v in values if math.isfinite(v)]
    if len(clean) < 4 or not math.isfinite(span) or span <= 1e-9:
        return 0.0, 0.0
    residuals: list[float] = []
    for i in range(1, len(clean) - 1):
        smooth = (clean[i - 1] + clean[i] + clean[i + 1]) / 3.0
        residuals.append(abs(clean[i] - smooth))
    if not residuals:
        return 0.0, 0.0
    amp = float(sum(residuals) / len(residuals)) * 2.0
    pct = min(25.0, (amp / span) * 100.0)
    return round(amp, 4), round(pct, 2)


def _compute_derivatives(
    timed_pts: list[tuple[float, float]],
    fallback_vals: list[float],
    fallback_window_min: float = 15.0,
) -> tuple[float, float, list[float]]:
    """
    Рассчитывает текущую производную (ед/мин), пиковую производную (ед/мин) и
    серию производных строго по фактическим разностям временных меток (DEF-14).
    Пропускает дублирующиеся или немонотонные метки (dt <= 1e-3 с).
    """
    if len(timed_pts) >= 2:
        pts = [(t, v) for t, v in timed_pts if math.isfinite(t) and math.isfinite(v)]
        if len(pts) < 2:
            return 0.0, 0.0, []
        rate_series: list[float] = [0.0]
        peak_rate = 0.0
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            dt_s = t1 - t0
            if dt_s <= 1e-3:
                rate_series.append(0.0)
                continue
            r_min = (v1 - v0) / (dt_s / 60.0)
            if math.isfinite(r_min):
                rate_series.append(round(r_min, 3))
                peak_rate = max(peak_rate, abs(r_min))
            else:
                rate_series.append(0.0)

        # Текущая производная по последним 5–6 точкам (или последнему валидному интервалу)
        ref_idx = max(0, len(pts) - 6)
        dt_tail = pts[-1][0] - pts[ref_idx][0]
        if dt_tail > 1e-3:
            curr_rate = (pts[-1][1] - pts[ref_idx][1]) / (dt_tail / 60.0)
        else:
            curr_rate = 0.0
            for i in range(len(pts) - 1, 0, -1):
                dti = pts[i][0] - pts[i - 1][0]
                if dti > 1e-3:
                    curr_rate = (pts[i][1] - pts[i - 1][1]) / (dti / 60.0)
                    break
        if not math.isfinite(curr_rate):
            curr_rate = 0.0
        peak_rate = max(peak_rate, abs(curr_rate))
        return curr_rate, peak_rate, rate_series

    # Fallback по спарклайну (если временных меток ещё нет): равномерный шаг окна fallback_window_min
    clean = [v for v in fallback_vals if math.isfinite(v)]
    if len(clean) < 2:
        return 0.0, 0.0, []
    step_min = max(0.05, fallback_window_min / max(1, len(clean) - 1))
    rate_series = [0.0]
    peak_rate = 0.0
    for a, b in zip(clean, clean[1:]):
        r_min = (b - a) / step_min
        rate_series.append(round(r_min, 3))
        peak_rate = max(peak_rate, abs(r_min))
    curr_rate = (clean[-1] - clean[-2]) / step_min
    return curr_rate, peak_rate, rate_series


class DispatchAnalyzer:
    """Аналитический контур диагностики и ранжирования инцидентов без синтетических подмен."""

    def __init__(self) -> None:
        self._series: dict[str, deque[tuple[float, float, str]]] = {}
        self._overload_sec: dict[str, float] = {}
        self._last_tick_ts: dict[str, float] = {}
        self._auto_spec_triggers: dict[str, dict[str, Any]] = {}

    def ingest_instruments(self, instruments: list[dict[str, Any]]) -> None:
        """Обновляет скользящие окна показаний и накопители фактического времени перегрузки."""
        now = time.time()
        for inst in instruments:
            iid = inst["id"]
            rd = inst.get("reading") or {}
            val = _finite_float(rd.get("value"))
            valid = bool(rd.get("valid")) and val is not None
            lv = (rd.get("level") or "normal") if valid else "stale"
            prev_t = self._last_tick_ts.get(iid)
            dt = max(0.0, min(10.0, now - prev_t)) if prev_t is not None else 0.0
            self._last_tick_ts[iid] = now

            if lv in ("warning", "alert"):
                self._overload_sec[iid] = self._overload_sec.get(iid, 0.0) + dt

            buf = self._series.setdefault(iid, deque(maxlen=120))
            if valid and val is not None:
                buf.append((now, val, lv))
            elif not buf and isinstance(rd.get("sparkline"), list):
                pts = [v for x in rd["sparkline"] if (v := _finite_float(x)) is not None]
                n = len(pts)
                for idx, v in enumerate(pts):
                    buf.append((now - (n - 1 - idx) * 35.0, v, "normal"))

    def rate_series_for(self, inst_id: str, fallback_vals: list[float] | None = None) -> list[float]:
        """Возвращает серию производных dV/dt (ед/мин) по фактическим временным меткам."""
        mem_pts = [(p[0], p[1]) for p in self._series.get(inst_id, ())]
        _, _, series = _compute_derivatives(mem_pts, fallback_vals or [])
        return series[-24:]

    def analyze_instrument(
        self,
        inst: dict[str, Any],
        events: list[dict[str, Any]],
        stream_telemetry: dict[str, Any] | None = None,
        *,
        now_unix: float | None = None,
    ) -> dict[str, Any]:
        now = time.time() if now_unix is None else float(now_unix)
        iid = inst["id"]
        cal = inst.get("calibration") or {}
        v_min = _finite_float(cal.get("v_min"))
        v_max = _finite_float(cal.get("v_max"))
        v_min = 0.0 if v_min is None else v_min
        v_max = 10.0 if v_max is None else v_max
        span = abs(v_max - v_min) or 1.0

        rd = inst.get("reading") or {}
        value = _finite_float(rd.get("value"))
        valid = bool(rd.get("valid")) and value is not None
        if not valid:
            value = None
        level = (rd.get("level") or "normal") if valid else "stale"
        is_sim = inst.get("source_kind") == "simulated"

        # Временной ряд с реальными временными метками
        mem_pts = list(self._series.get(iid, ()))
        timed_pts: list[tuple[float, float]] = [(p[0], p[1]) for p in mem_pts if math.isfinite(p[0]) and math.isfinite(p[1])]
        if len(timed_pts) >= 2:
            vals = [p[1] for p in timed_pts]
        else:
            raw_sp = rd.get("sparkline") or []
            vals = [v for x in raw_sp if (v := _finite_float(x)) is not None]
            if value is not None and (not vals or abs(vals[-1] - value) > 1e-9):
                vals.append(value)

        # 1. Производные dV/dt строго по фактическим dt (DEF-14)
        calc_rate, peak_rate, rate_series = _compute_derivatives(timed_pts, vals)
        explicit_rate = _finite_float(rd.get("rate_per_min"))
        rate_val = explicit_rate if (explicit_rate is not None and len(timed_pts) < 2) else calc_rate
        peak_rate = max(peak_rate, abs(rate_val))
        rate_pct_min = min(100.0, abs(rate_val) / span * 100.0)
        peak_rate_pct = min(100.0, peak_rate / span * 100.0)

        hydraulic_shock = (inst.get("gauge_type") == "pressure" and peak_rate_pct >= 9.0)
        thermal_runaway = (inst.get("gauge_type") == "temperature" and rate_val > 0 and peak_rate_pct >= 4.0)

        # 2. Высокочастотный «дребезг» стрелки строго по фактическому ряду (без _BENCH_DIAGNOSTIC_PROFILES)
        chatter_amp, chatter_pct = _compute_chatter(vals, span)

        # 3. Срабатывания уставок по реальным скользящим окнам 12 ч и 24 ч (DEF-08)
        cutoff_12h = now - 12.0 * 3600.0
        cutoff_24h = now - 24.0 * 3600.0
        inst_events = [e for e in events if e.get("cam_id") == iid]
        trips_shift = 0
        trips_24h = 0
        link_drops_24h = 0
        recent_incident_ids: list[int] = []

        for e in inst_events:
            ev_ts = _parse_iso_ts(e.get("ts"))
            # Если ts не указан в синтетическом unit-вызове — считаем текущим окном
            if ev_ts is None:
                ev_ts = now
            if ev_ts < cutoff_24h or ev_ts > now + 60.0:
                continue
            if e.get("kind") == "alarm" and e.get("level") in ("warning", "alert"):
                trips_24h += 1
                if ev_ts >= cutoff_12h:
                    trips_shift += 1
                if e.get("id") is not None:
                    try:
                        recent_incident_ids.append(int(e["id"]))
                    except (TypeError, ValueError):
                        pass
            elif e.get("kind") == "link" and e.get("text") in ("offline", "reconnecting"):
                link_drops_24h += 1

        # Фактическое накопленное время перегрузки (без фантомных +6.5/+2.5 мин, DEF-08)
        overload_min = round(self._overload_sec.get(iid, 0.0) / 60.0, 2)
        overload_pct_shift = round(min(100.0, overload_min / 720.0 * 100.0), 2)

        # 4. Независимые оценки: оптическое качество и доступность связи (DEF-08)
        st_q = (stream_telemetry or {}).get("quality") or {}
        st_health = str((stream_telemetry or {}).get("health_status") or "").upper()
        has_stream_diag = bool(
            st_q.get("updated_at")
            or st_q.get("quality_score") is not None
            or st_q.get("steam_occlusion")
            or st_q.get("partial_occlusion")
            or st_q.get("frozen")
            or st_q.get("low_light")
            or st_health in ("DEGRADED", "OFFLINE")
        )
        if not is_sim or has_stream_diag:
            raw_conf = _finite_float(rd.get("confidence"))
            cv_conf = raw_conf if raw_conf is not None else (0.0 if not valid else 0.85)
            cv_conf = max(0.0, min(1.0, cv_conf))
            q_score = _finite_float(st_q.get("quality_score"))
            if q_score is not None:
                optical_health = max(0.0, min(100.0, q_score))
                if raw_conf is not None:
                    optical_health = min(optical_health, cv_conf * 100.0)
            elif has_stream_diag:
                pen = 0.0
                if st_health == "OFFLINE":
                    pen = 100.0
                else:
                    if st_q.get("steam_occlusion"):
                        pen += 55.0
                    if st_q.get("partial_occlusion"):
                        pen += 50.0
                    if st_q.get("frozen"):
                        pen += 45.0
                    if st_q.get("low_light"):
                        pen += 35.0
                    if st_health == "DEGRADED" and pen == 0.0:
                        pen = 45.0
                optical_health = max(0.0, min(100.0, 100.0 - pen))
            else:
                optical_health = cv_conf * 100.0 if valid else 0.0
            optical_issues = list(st_q.get("degradation_reasons") or [])
            if st_q.get("steam_occlusion") and not optical_issues:
                optical_issues.append("Перекрытие объектива паром / задымлением")
            if st_q.get("partial_occlusion") and not optical_issues:
                optical_issues.append("Частичное перекрытие объектива")
            if not valid and not optical_issues:
                optical_issues.append("Нет достоверного кадра с камеры")
        else:
            cv_conf = 0.95 if valid else 0.0
            optical_health = 95.0 if valid else 0.0
            optical_issues = [] if valid else ["Потеря канала опроса датчика (стенд)"]

        optical_health = round(max(0.0, min(100.0, optical_health)), 1)
        optical_score = optical_health  # алиас обратной совместимости

        if not valid:
            communication_health = 0.0
        else:
            communication_health = round(max(20.0, 100.0 - min(60.0, link_drops_24h * 12.0)), 1)

        # 5. Раздельный расчёт: equipment_health и instrument_health (НЕ смешиваются с оптикой/связью!)
        p_overload = 0.0
        if level == "alert":
            p_overload = 34.0 + min(18.0, overload_min * 0.30)
        elif level == "warning":
            p_overload = 18.0 + min(12.0, overload_min * 0.25)
        elif overload_min > 1.0:
            p_overload = min(12.0, overload_min * 0.20)

        p_rate = min(18.0, peak_rate_pct * 1.15)
        if hydraulic_shock or thermal_runaway:
            p_rate = max(p_rate, 14.0)

        p_chatter = min(38.0, max(0.0, (chatter_pct - 0.8) * 6.0))
        p_trips = min(18.0, trips_shift * 3.0 + max(0, trips_24h - trips_shift) * 1.2)

        # Оптический и коммуникационный штрафы учитываются отдельно (только в optical/communication_health)
        p_optical = round(max(0.0, 100.0 - optical_health), 1)
        p_link = round(max(0.0, 100.0 - communication_health), 1)

        equipment_health = round(max(5.0, min(100.0, 100.0 - (p_overload + p_rate + p_trips))), 1)
        instrument_health = round(max(5.0, min(100.0, 100.0 - (p_chatter + p_trips * 0.6))), 1)
        monitoring_readiness = round(min(optical_health, communication_health), 1)

        # Интегральный Health Score технического состояния узла и прибора (без искажения туманом/камерой)
        worst_tech = min(equipment_health, instrument_health)
        other_tech = max(equipment_health, instrument_health)
        health_score = round(max(5.0, min(100.0, worst_tech - 0.15 * (100.0 - other_tech))), 1)
        band = _health_band(health_score)

        # 6. Классификация первопричины (3 диагностических класса + норма)
        optical_degraded = (optical_health < 70.0) or (communication_health < 60.0) or (not valid)
        if level in ("alert", "warning") or hydraulic_shock or thermal_runaway:
            root_cause = "process_anomaly"
        elif p_chatter >= 10.0 or (trips_shift >= 3 and level == "normal"):
            root_cause = "instrument_degradation"
        elif optical_degraded:
            root_cause = "optical_degradation"
        else:
            root_cause = "nominal"

        # 7. Диспетчерская рекомендация (гипотеза с обоснованием и степенью уверенности)
        rec_info = self._build_recommendation(
            inst=inst,
            root_cause=root_cause,
            level=level,
            value=value,
            health_score=health_score,
            equipment_health=equipment_health,
            instrument_health=instrument_health,
            optical_health=optical_health,
            communication_health=communication_health,
            chatter_pct=chatter_pct,
            peak_rate=peak_rate,
            overload_min=overload_min,
            trips_shift=trips_shift,
            hydraulic_shock=hydraulic_shock,
            thermal_runaway=thermal_runaway,
            optical_issues=optical_issues,
        )

        # Автотриггер критического состояния оборудования/прибора (только по техсостоянию, не по оптике)
        critical_wear = (health_score <= config.CRITICAL_WEAR_HEALTH_THRESHOLD) and (
            root_cause in ("process_anomaly", "instrument_degradation")
        )
        if critical_wear and iid not in self._auto_spec_triggers:
            self._auto_spec_triggers[iid] = {
                "instrument_id": iid,
                "code": inst.get("code") or iid,
                "name": inst.get("name") or "",
                "group": inst.get("group") or "",
                "health_score": health_score,
                "root_cause": root_cause,
                "triggered_at": utcnow_iso(),
                "reason": ROOT_CAUSE_META[root_cause]["label"],
                "incident_ids": recent_incident_ids[:10],
            }

        return {
            "id": iid,
            "code": inst.get("code") or iid,
            "short_name": inst.get("short_name") or inst.get("name") or "",
            "name": inst.get("name") or "",
            "group": inst.get("group") or "Общие",
            "gauge_type": inst.get("gauge_type") or "pressure",
            "unit": inst.get("unit") or "",
            "decimals": inst.get("decimals", 2),
            "source_kind": inst.get("source_kind") or "simulated",
            "value": value,
            "level": level,
            "valid": valid,
            "thresholds": inst.get("thresholds") or {},
            "calibration": cal,
            # Независимые индексы состояния (DEF-08)
            "health_score": health_score,
            "equipment_health": equipment_health,
            "instrument_health": instrument_health,
            "optical_health": optical_health,
            "communication_health": communication_health,
            "monitoring_readiness": monitoring_readiness,
            "health_band": band,
            "critical_wear": critical_wear,
            "rate_symbol": _rate_label(inst.get("gauge_type") or "pressure"),
            "rate_per_min": round(rate_val, 3),
            "rate_pct_min": round(rate_pct_min, 2),
            "peak_rate_per_min": round(peak_rate, 3),
            "rate_series": rate_series[-24:],
            "hydraulic_shock_risk": hydraulic_shock,
            "thermal_runaway_risk": thermal_runaway,
            "chatter_amp": chatter_amp,
            "chatter_pct": chatter_pct,
            "overload_min": overload_min,
            "overload_pct_shift": overload_pct_shift,
            "trips_shift": trips_shift,
            "trips_24h": trips_24h,
            "cv_confidence_pct": round(cv_conf * 100.0, 1),
            "optical_score": optical_score,
            "optical_issues": optical_issues,
            "root_cause": root_cause,
            "root_cause_meta": ROOT_CAUSE_META[root_cause],
            "penalties": {
                "overload": round(p_overload, 1),
                "rate": round(p_rate, 1),
                "chatter": round(p_chatter, 1),
                "trips": round(p_trips, 1),
                "optical": p_optical,
                "link": p_link,
            },
            "urgency": rec_info["urgency"],
            "recommendation": rec_info["recommendation"],
            "hypothesis_confidence": rec_info["confidence"],
            "evidence_basis": rec_info["evidence"],
            "modernization_needed": rec_info["modernization_needed"],
            "sparkline": vals[-24:],
        }

    @staticmethod
    def _build_recommendation(
        *,
        inst: dict[str, Any],
        root_cause: str,
        level: str,
        value: float | None,
        health_score: float,
        equipment_health: float,
        instrument_health: float,
        optical_health: float,
        communication_health: float,
        chatter_pct: float,
        peak_rate: float,
        overload_min: float,
        trips_shift: int,
        hydraulic_shock: bool,
        thermal_runaway: bool,
        optical_issues: list[str],
    ) -> dict[str, Any]:
        code = inst.get("code") or inst["id"]
        unit = inst.get("unit") or ""
        rate_sym = _rate_label(inst.get("gauge_type") or "pressure")
        val_txt = f"{value:.2f} {unit}".strip() if value is not None else "нет данных"

        if root_cause == "process_anomaly":
            evidence = (
                f"показание={val_txt}, уровень={level.upper()}, пик {rate_sym}={peak_rate:.2f} {unit}/мин, "
                f"перегрузка={overload_min:.1f} мин, срабатываний (12ч)={trips_shift}"
            )
            if thermal_runaway:
                return {
                    "recommendation": (
                        f"{code}: зафиксирован ускоренный рост температуры ({evidence}). "
                        f"Гипотеза (высокая уверенность по тренду): возможен риск перегрева узла; "
                        f"рекомендуется проверка режима охлаждения и оценка включения позиции в проект ТЗ на цифровой датчик."
                    ),
                    "urgency": "КРИТИЧНО",
                    "confidence": "высокая (прямое измерение тренда)",
                    "evidence": evidence,
                    "modernization_needed": True,
                }
            if hydraulic_shock:
                return {
                    "recommendation": (
                        f"{code}: выявлен резкий скачок давления ({evidence}). "
                        f"Гипотеза (высокая уверенность по dP/dt): возможны гидроудар или резкая перекладка арматуры; "
                        f"рекомендуется проверка арматуры и оценка установки цифрового преобразователя с демпфированием."
                    ),
                    "urgency": "КРИТИЧНО",
                    "confidence": "высокая (прямое измерение dP/dt)",
                    "evidence": evidence,
                    "modernization_needed": True,
                }
            if level == "alert":
                return {
                    "recommendation": (
                        f"{code}: зафиксировано превышение аварийной уставки ({evidence}). "
                        f"Рекомендуется проверка технологического режима дежурным персоналом и включение позиции "
                        f"в проект дефектной ведомости для экспертной оценки модернизации КИПиА."
                    ),
                    "urgency": "КРИТИЧНО",
                    "confidence": "высокая (превышение уставки HH/LL)",
                    "evidence": evidence,
                    "modernization_needed": True,
                }
            return {
                "recommendation": (
                    f"{code}: работа в зоне предупреждения ({evidence}). "
                    f"Гипотеза (средняя уверенность): отклонение технологического режима; "
                    f"рекомендуется контроль динамики и проверка уставок."
                ),
                "urgency": "ВЫСОКИЙ",
                "confidence": "средняя (превышение уставки H/L)",
                "evidence": evidence,
                "modernization_needed": equipment_health < 75.0,
            }

        if root_cause == "instrument_degradation":
            evidence = f"дребезг={chatter_pct:.1f}% шкалы, срабатываний (12ч)={trips_shift}, instrument_health={instrument_health:.0f}%"
            return {
                "recommendation": (
                    f"{code}: эвристическая гипотеза (требуется инструментальная проверка службой КИПиА) — "
                    f"повышенные высокочастотные колебания стрелки ({evidence}) могут указывать на вибрацию узла, "
                    f"пульсацию среды или люфт механизма прибора. Рекомендуется осмотр и рассмотрение замены на цифровой датчик."
                ),
                "urgency": "ВЫСОКИЙ" if instrument_health < 65.0 else "СРЕДНИЙ",
                "confidence": "средняя (эвристическая оценка по колебаниям ряда)",
                "evidence": evidence,
                "modernization_needed": True,
            }

        if root_cause == "optical_degradation":
            issue_txt = "; ".join(optical_issues) if optical_issues else "снижение достоверности видеоканала или обрыв связи"
            evidence = f"optical_health={optical_health:.0f}%, communication_health={communication_health:.0f}%, причины: {issue_txt}"
            return {
                "recommendation": (
                    f"{code}: проблема контура видеоконтроля/связи ({evidence}) — не свидетельствует об износе "
                    f"технологического оборудования. Рекомендуется обслуживание камеры (очистка оптики, освещение) "
                    f"и диагностика канала передачи данных."
                ),
                "urgency": "ВЫСОКИЙ" if communication_health < 30.0 else "СРЕДНИЙ",
                "confidence": "высокая (диагностика видеосигнала/канала)",
                "evidence": evidence,
                "modernization_needed": False,  # Загрязнение камеры не является основанием для замены манометра!
            }

        return {
            "recommendation": (
                f"{code}: показания ({val_txt}) и видеоканал стабильны, отклонений не выявлено."
            ),
            "urgency": "НОРМА",
            "confidence": "высокая (штатный коридор)",
            "evidence": f"показание={val_txt}, equipment_health={equipment_health:.0f}%, optical_health={optical_health:.0f}%",
            "modernization_needed": False,
        }

    def overview(
        self,
        instruments: list[dict[str, Any]],
        events: list[dict[str, Any]],
        stream_telemetry_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.ingest_instruments(instruments)
        st_map = stream_telemetry_map or {}
        now = time.time()
        items = [
            self.analyze_instrument(inst, events, st_map.get(inst["id"]), now_unix=now)
            for inst in instruments
        ]

        avg_health = round(sum(x["health_score"] for x in items) / max(1, len(items)), 1)
        avg_equipment = round(sum(x["equipment_health"] for x in items) / max(1, len(items)), 1)
        avg_optical = round(sum(x["optical_health"] for x in items) / max(1, len(items)), 1)
        avg_comm = round(sum(x["communication_health"] for x in items) / max(1, len(items)), 1)
        critical_wear_items = [x for x in items if x["critical_wear"]]
        degraded_items = [x for x in items if x["health_score"] < 75.0]
        modernize_items = [x for x in items if x["modernization_needed"]]

        by_cause = {"process_anomaly": 0, "instrument_degradation": 0, "optical_degradation": 0, "nominal": 0}
        for x in items:
            by_cause[x["root_cause"]] = by_cause.get(x["root_cause"], 0) + 1

        groups_map: dict[str, list[dict[str, Any]]] = {}
        for x in items:
            groups_map.setdefault(x["group"], []).append(x)
        groups_summary = []
        for gname, gitems in groups_map.items():
            g_avg = round(sum(i["health_score"] for i in gitems) / max(1, len(gitems)), 1)
            groups_summary.append({
                "group": gname,
                "count": len(gitems),
                "avg_health": g_avg,
                "min_health": min(i["health_score"] for i in gitems),
                "critical_wear": sum(1 for i in gitems if i["critical_wear"]),
                "modernization_candidates": sum(1 for i in gitems if i["modernization_needed"]),
            })
        groups_summary.sort(key=lambda g: g["avg_health"])

        urg_rank = {"КРИТИЧНО": 0, "ВЫСОКИЙ": 1, "СРЕДНИЙ": 2, "НОРМА": 3}
        recs = [
            {
                "instrument_id": x["id"],
                "code": x["code"],
                "name": x["short_name"],
                "group": x["group"],
                "health_score": x["health_score"],
                "equipment_health": x["equipment_health"],
                "instrument_health": x["instrument_health"],
                "optical_health": x["optical_health"],
                "communication_health": x["communication_health"],
                "urgency": x["urgency"],
                "root_cause": x["root_cause"],
                "root_cause_label": x["root_cause_meta"]["label"],
                "recommendation": x["recommendation"],
                "hypothesis_confidence": x["hypothesis_confidence"],
                "evidence_basis": x["evidence_basis"],
                "modernization_needed": x["modernization_needed"],
                "rate_symbol": x["rate_symbol"],
                "rate_per_min": x["rate_per_min"],
                "unit": x["unit"],
                "chatter_pct": x["chatter_pct"],
            }
            for x in items
            if x["root_cause"] != "nominal" or x["health_score"] < 85.0
        ]
        recs.sort(key=lambda r: (urg_rank.get(r["urgency"], 9), r["health_score"]))

        return {
            "generated_at": utcnow_iso(),
            "wear_threshold": config.CRITICAL_WEAR_HEALTH_THRESHOLD,
            "diagnostic_disclaimer": (
                "Информационно-аналитическая оценка на базе эвристических правил видеомониторинга. "
                "Не является метрологическим заключением (ФЗ-102) и прогнозом остаточного ресурса; "
                "подлежит проверке службой КИПиА."
            ),
            "summary": {
                "total": len(items),
                "avg_health_score": avg_health,
                "avg_equipment_health": avg_equipment,
                "avg_optical_health": avg_optical,
                "avg_communication_health": avg_comm,
                "critical_wear_count": len(critical_wear_items),
                "degraded_count": len(degraded_items),
                "modernization_candidates": len(modernize_items),
                "by_root_cause": by_cause,
            },
            "groups": groups_summary,
            "recommendations": recs,
            "auto_spec_triggers": list(self._auto_spec_triggers.values()),
            "instruments": items,
        }
