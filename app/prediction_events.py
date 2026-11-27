"""
Прогнозные события (kind = "prediction"): переходы состояния прогноза прибора без дублей.

Источник — сводка PredictiveAnalyzer (поля `status`, `current_level`, `eta_alert_min`,
`breach_prob_alert_horizon`, `thresholds_eta`). Прогноз — инженерная подсказка, а не срабатывание
уставки: событие не требует квитирования и не заменяет `alarm`.

Жизненный цикл прибора: idle → imminent → idle.
- Вход в imminent: прогноз `ok`, уставка HH/LL ещё не пробита, и ETA до неё ≤ ENTER_ETA_MIN либо
  вероятность пробоя на горизонте ≥ ENTER_PROB — в CONFIRM_EVALS оценках подряд.
- Выход: ETA > EXIT_ETA_MIN (или нет) и вероятность < EXIT_PROB в CONFIRM_EVALS оценках подряд
  (`cleared`); фактический пробой уставки — сразу (`realized`, дальше ведёт журнал тревог); прогноз
  стал недоступен (нет данных, канал недостоверен, смена калибровки) — сразу (`withdrawn`).
Гистерезис между порогами входа и выхода исключает дребезг событий.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

ENTER_ETA_MIN = 30.0
ENTER_PROB = 0.7
EXIT_ETA_MIN = 45.0
EXIT_PROB = 0.5
CONFIRM_EVALS = 2


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _alert_threshold(pred: dict[str, Any]) -> tuple[str | None, float | None]:
    """Аварийная уставка (HH/LL) с ближайшим прогнозным ETA."""
    best: tuple[float, str, float | None] | None = None
    for label, t in (pred.get("thresholds_eta") or {}).items():
        if t.get("severity") != "alert":
            continue
        eta = _num(t.get("eta_median_min"))
        key = eta if eta is not None else math.inf
        if best is None or key < best[0]:
            best = (key, label, _num(t.get("threshold")))
    return (best[1], best[2]) if best else (None, None)


@dataclass
class _State:
    active: bool = False
    enter_streak: int = 0
    exit_streak: int = 0
    since_ts: float | None = None
    rev: Any = None


@dataclass
class PredictionEventTracker:
    """Отслеживает прогнозы по приборам и возвращает только переходы состояния."""
    _st: dict[str, _State] = field(default_factory=dict)

    @staticmethod
    def _qualifies_enter(p: dict[str, Any]) -> bool:
        eta, prob = _num(p.get("eta_alert_min")), _num(p.get("breach_prob_alert_horizon")) or 0.0
        return (eta is not None and 0.0 < eta <= ENTER_ETA_MIN) or prob >= ENTER_PROB

    @staticmethod
    def _qualifies_exit(p: dict[str, Any]) -> bool:
        eta, prob = _num(p.get("eta_alert_min")), _num(p.get("breach_prob_alert_horizon")) or 0.0
        return (eta is None or eta > EXIT_ETA_MIN) and prob < EXIT_PROB

    def active_ids(self) -> set[str]:
        return {k for k, s in self._st.items() if s.active}

    def update(self, preds: dict[str, dict[str, Any]], now_ts: float,
               calibration_revs: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Одна оценка по всем приборам; возвращает список переходов
        `{"instrument_id", "text", "level", "pred", "setpoint", "setpoint_value"}`."""
        out: list[dict[str, Any]] = []
        revs = calibration_revs or {}
        for iid in list(self._st):
            if iid not in preds:
                st = self._st.pop(iid)
                if st.active:
                    out.append({"instrument_id": iid, "text": "withdrawn", "level": "normal", "pred": {},
                                "setpoint": None, "setpoint_value": None})
        for iid, p in preds.items():
            st = self._st.setdefault(iid, _State(rev=revs.get(iid)))
            rev = revs.get(iid)
            rev_changed = rev != st.rev
            st.rev = rev
            ok = p.get("status") == "ok" and bool(p.get("valid"))
            breached = p.get("current_level") == "alert"
            sp, sp_val = _alert_threshold(p)
            if st.active:
                reason = None
                if rev_changed or not ok:
                    reason = "withdrawn"
                elif breached:
                    reason = "realized"
                elif self._qualifies_exit(p):
                    st.exit_streak += 1
                    if st.exit_streak >= CONFIRM_EVALS:
                        reason = "cleared"
                else:
                    st.exit_streak = 0
                if reason:
                    st.active, st.enter_streak, st.exit_streak, st.since_ts = False, 0, 0, None
                    out.append({"instrument_id": iid, "text": reason, "level": "normal", "pred": p,
                                "setpoint": sp, "setpoint_value": sp_val})
                continue
            if rev_changed:
                st.enter_streak = 0
            if ok and not breached and self._qualifies_enter(p):
                st.enter_streak += 1
                if st.enter_streak >= CONFIRM_EVALS:
                    st.active, st.exit_streak, st.since_ts = True, 0, now_ts
                    out.append({"instrument_id": iid, "text": "imminent", "level": "warning", "pred": p,
                                "setpoint": sp, "setpoint_value": sp_val})
            else:
                st.enter_streak = 0
        return out
