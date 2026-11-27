"""
GaugeVision AI — оптимизатор бюджета модернизации КИПиА (`modernization_optimizer`).

Формирует портфель мероприятий модернизации на основе реальных данных:
  • диспетчерский анализ (`dispatch_overview`: Health Score, root_cause, перегрузки, дребезг);
  • прогнозная аналитика (`predictive_overview`: ETA до уставок, breach_prob_alert, anomaly_score);
  • инженерные паспорта приборов (`instrument_passports`: категория критичности I/II/III,
    взрывоопасность, обязательные предписания, индивидуальные CAPEX / ущерб простоя);
  • справочник цифровых преобразователей (`spec_generator.DIGITAL_SENSOR_CATALOG`).

Математическое ядро — точное 0-1 целочисленное линейное программирование
(`app/ilp_solver.py`, метод ветвей и границ с доказанной глобальной оптимальностью).
"""
from __future__ import annotations

import math
from typing import Any

from . import config
from .contracts import default_passport_for_instrument, resolve_instrument_identity
from .db import utcnow_iso
from .ilp_solver import IlpItem, solve_binary_ilp, solve_greedy_baseline
from .spec_generator import pick_digital_replacement

OBJECTIVE_META: dict[str, str] = {
    "weighted_utility": "Сбалансированный оптимум (снижение риска + чистый экономический эффект)",
    "max_risk_reduction": "Максимизация снижения технологического риска",
    "max_net_effect": "Максимизация чистого годового экономического эффекта (₽/год)",
}


def _finite(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def build_modernization_candidates(
    *,
    dispatch_overview: dict[str, Any],
    predictive_overview: dict[str, Any] | None = None,
    passports_by_id: dict[str, dict[str, Any]] | None = None,
    economics_config: dict[str, Any] | None = None,
    group_filter: str = "all",
    include_healthy: bool = False,
    mandatory_ids: set[str] | None = None,
    excluded_ids: set[str] | None = None,
    auto_mandatory_critical: bool = False,
) -> list[dict[str, Any]]:
    """
    Собирает список реальных кандидатов на модернизацию с прозрачной калькуляцией
    CAPEX, OPEX, снижения риска и чистого экономического эффекта.
    Чисто оптические проблемы камеры (`optical_degradation`) честно отделяются от замены КИП.
    """
    eco_cfg = economics_config or {}
    comm_rate = _finite(eco_cfg.get("commissioning_rate"), config.ECO_COMMISSIONING_RATE)
    comm_rate = max(0.0, min(1.0, comm_rate))
    rounds_per_unit = max(0, int(_finite(eco_cfg.get("rounds_savings_per_unit_rub"), config.ECO_ROUNDS_SAVINGS_RUB_YR)))
    opex_per_unit = max(0, int(_finite(eco_cfg.get("opex_per_sensor_rub_yr"), config.ECO_OPEX_PER_SENSOR_RUB_YR)))
    risk_mult = max(0.0, _finite(eco_cfg.get("downtime_risk_multiplier"), 1.0))
    price_overrides = eco_cfg.get("price_overrides") if isinstance(eco_cfg.get("price_overrides"), dict) else None

    pred_by_id: dict[str, dict[str, Any]] = {}
    for p in (predictive_overview or {}).get("instruments") or []:
        pred_by_id[str(p.get("instrument_id") or p.get("id"))] = p

    passports = passports_by_id or {}
    mand_req = set(mandatory_ids or set())
    excl_req = set(excluded_ids or set())

    candidates: list[dict[str, Any]] = []
    for raw_item in dispatch_overview.get("instruments") or []:
        ident = resolve_instrument_identity(raw_item)
        iid = ident.instrument_id
        if group_filter and group_filter != "all" and ident.group != group_filter:
            continue

        passport = {**default_passport_for_instrument(raw_item), **(passports.get(iid) or {})}
        pred = pred_by_id.get(iid) or {}

        hs = _finite(raw_item.get("health_score"), 100.0)
        eq_h = _finite(raw_item.get("equipment_health"), hs)
        inst_h = _finite(raw_item.get("instrument_health"), hs)
        opt_h = _finite(raw_item.get("optical_health"), 100.0)
        rc = str(raw_item.get("root_cause") or "nominal")
        mod_needed = bool(raw_item.get("modernization_needed"))
        crit_wear = bool(raw_item.get("critical_wear"))
        trips_24h = int(_finite(raw_item.get("trips_24h"), 0.0))

        prob_alert = _finite(pred.get("breach_prob_alert_horizon"), 0.0)
        prob_warn = _finite(pred.get("breach_prob_warning_horizon"), 0.0)
        eta_alert = pred.get("eta_alert_min")
        anom_score = _finite(pred.get("anomaly_score"), 0.0)
        trend_class = str(pred.get("trend_class") or "insufficient_data")

        # Обязательность: явный запрос, флаг предписания в паспорте или критический износ (если включено)
        is_mandatory = (
            (iid in mand_req)
            or bool(passport.get("mandatory_regulation"))
            or (auto_mandatory_critical and crit_wear and rc in ("process_anomaly", "instrument_degradation"))
        )
        mandatory_reasons: list[str] = []
        if iid in mand_req:
            mandatory_reasons.append("обязательно по заданию пользователя")
        if passport.get("mandatory_regulation"):
            mandatory_reasons.append("обязательное предписание паспорта КИПиА")
        if auto_mandatory_critical and crit_wear and rc in ("process_anomaly", "instrument_degradation"):
            mandatory_reasons.append(f"критический тех. износ (Health {hs:.1f}% < 50%)")

        # Чисто оптическая проблема камеры не требует капитальной замены манометра
        optical_only = (rc == "optical_degradation") and not mod_needed and not is_mandatory
        predictive_risk = (prob_alert >= 0.30) or (anom_score >= 45.0) or (
            eta_alert is not None and _finite(eta_alert, 1e9) <= 120.0
        )
        eligible = (
            is_mandatory
            or (not optical_only and (mod_needed or hs < 85.0 or trips_24h >= config.SPEC_REGULAR_TRIPS_MIN or predictive_risk))
            or (include_healthy and not optical_only)
        )
        if not eligible:
            continue

        repl = pick_digital_replacement(raw_item, price_overrides=price_overrides)
        if passport.get("hazardous_zone") and "1Ex" not in repl["ex"]:
            repl["ex"] = "1Ex ia IIC T6 Ga (ТР ТС 012/2011)"

        hw_rub = int(repl["unit_cost_rub"])
        smr_rub = int(repl["install_cost_rub"])
        comm_rub = int(round((hw_rub + smr_rub) * comm_rate))
        capex_rub = int(passport["custom_capex_rub"]) if passport.get("custom_capex_rub") is not None else (hw_rub + smr_rub + comm_rub)
        capex_rub = max(1_000, capex_rub)

        crit_class = int(passport.get("criticality_class") or 2)
        crit_weight = _finite(passport.get("criticality_weight"), 1.15)

        # Реальная оценка предотвращённого ущерба простоя на базе техсостояния + прогноза + паспорта
        base_risk_rub = (
            int(passport["custom_downtime_risk_rub_yr"])
            if passport.get("custom_downtime_risk_rub_yr") is not None
            else int(repl["downtime_risk_k_rub_yr"])
        )
        # Фактор текущего состояния согласован со spec_generator, дополнен прогнозной компонентой
        tech_severity = 1.25 if hs < 50.0 else (1.0 if hs < 75.0 else (0.72 if hs < 90.0 else 0.35))
        pred_boost = 1.0 + 0.45 * prob_alert + 0.15 * prob_warn + 0.25 * (anom_score / 100.0)
        risk_avoided_rub = int(round(base_risk_rub * tech_severity * crit_weight * pred_boost * risk_mult))
        gross_effect_rub = risk_avoided_rub + rounds_per_unit
        net_annual_effect_rub = gross_effect_rub - opex_per_unit
        payback_years = round(capex_rub / float(net_annual_effect_rub), 2) if net_annual_effect_rub > 0 else None

        # Интегральный балл снижения технологического риска (прозрачная линейная формула)
        wear_gap = max(5.0, 100.0 - min(eq_h, inst_h))
        pred_pts = 35.0 * prob_alert + 12.0 * prob_warn + 0.28 * anom_score
        trip_pts = min(15.0, trips_24h * 2.5)
        ex_bonus = 1.15 if passport.get("hazardous_zone") else 1.0
        risk_reduction_points = round((wear_gap * 0.65 + pred_pts + trip_pts) * crit_weight * ex_bonus, 2)

        candidates.append({
            "instrument_id": iid,
            "camera_id": ident.camera_id,
            "gauge_slot": ident.gauge_slot,
            "code": ident.code,
            "name": ident.name,
            "short_name": ident.short_name,
            "group": ident.group,
            "gauge_type": ident.gauge_type,
            "unit": ident.unit,
            "criticality_class": crit_class,
            "criticality_weight": round(crit_weight, 2),
            "hazardous_zone": bool(passport.get("hazardous_zone")),
            "mandatory": is_mandatory,
            "mandatory_reasons": mandatory_reasons,
            "excluded": iid in excl_req,
            "root_cause": rc,
            "root_cause_label": (raw_item.get("root_cause_meta") or {}).get("label") or rc,
            "health_score": round(hs, 1),
            "equipment_health": round(eq_h, 1),
            "instrument_health": round(inst_h, 1),
            "optical_health": round(opt_h, 1),
            "trips_24h": trips_24h,
            "trend_class": trend_class,
            "eta_alert_min": eta_alert,
            "breach_prob_alert_horizon": round(prob_alert, 4),
            "anomaly_score": round(anom_score, 1),
            "replacement": repl,
            "hw_rub": hw_rub,
            "smr_rub": smr_rub,
            "commissioning_rub": comm_rub,
            "capex_rub": capex_rub,
            "opex_rub_yr": opex_per_unit,
            "rounds_savings_rub_yr": rounds_per_unit,
            "risk_avoided_rub_yr": risk_avoided_rub,
            "net_annual_effect_rub_yr": net_annual_effect_rub,
            "payback_years": payback_years,
            "risk_reduction_points": risk_reduction_points,
        })

    candidates.sort(key=lambda c: (-int(c["mandatory"]), -c["risk_reduction_points"], c["capex_rub"]))
    return candidates


def _compute_utility(
    cand: dict[str, Any],
    *,
    objective: str,
    alpha_risk: float,
    beta_economics: float,
    max_risk: float,
    max_effect: float,
) -> float:
    if objective == "max_risk_reduction":
        return float(cand["risk_reduction_points"])
    if objective == "max_net_effect":
        return float(cand["net_annual_effect_rub_yr"])
    # Сбалансированная взвешенная полезность в нормированной шкале [0..100]
    r_norm = (float(cand["risk_reduction_points"]) / max(max_risk, 1.0)) * 100.0
    e_norm = (max(0.0, float(cand["net_annual_effect_rub_yr"])) / max(max_effect, 1.0)) * 100.0
    return round(alpha_risk * r_norm + beta_economics * e_norm, 4)


def optimize_modernization_budget(
    *,
    dispatch_overview: dict[str, Any],
    predictive_overview: dict[str, Any] | None = None,
    passports_by_id: dict[str, dict[str, Any]] | None = None,
    budget_rub: int,
    objective: str = "weighted_utility",
    alpha_risk: float = 0.65,
    beta_economics: float = 0.35,
    max_items: int | None = None,
    group_filter: str = "all",
    min_per_group: dict[str, int] | None = None,
    max_per_group: dict[str, int] | None = None,
    mandatory_ids: list[str] | None = None,
    excluded_ids: list[str] | None = None,
    dependencies: dict[str, list[str]] | None = None,
    auto_mandatory_critical: bool = False,
    include_healthy: bool = False,
    economics_config: dict[str, Any] | None = None,
    include_frontier: bool = True,
) -> dict[str, Any]:
    """
    Решает задачу оптимального распределения бюджета модернизации КИПиА методом
    точного 0-1 целочисленного линейного программирования (Branch-and-Bound ILP).
    """
    if objective not in OBJECTIVE_META:
        raise ValueError(f"Неизвестная целевая функция: {objective}. Допустимо: {', '.join(OBJECTIVE_META)}")

    a_w = max(0.0, float(alpha_risk))
    b_w = max(0.0, float(beta_economics))
    if a_w + b_w <= 1e-9:
        a_w, b_w = 0.65, 0.35
    else:
        s_w = a_w + b_w
        a_w, b_w = a_w / s_w, b_w / s_w

    candidates = build_modernization_candidates(
        dispatch_overview=dispatch_overview,
        predictive_overview=predictive_overview,
        passports_by_id=passports_by_id,
        economics_config=economics_config,
        group_filter=group_filter,
        include_healthy=include_healthy,
        mandatory_ids=set(mandatory_ids or []),
        excluded_ids=set(excluded_ids or []),
        auto_mandatory_critical=auto_mandatory_critical,
    )

    if not candidates:
        return {
            "computed_at": utcnow_iso(),
            "status": "empty",
            "objective": objective,
            "objective_label": OBJECTIVE_META[objective],
            "budget_rub": int(budget_rub),
            "solver": {"status": "empty", "solver_name": "exact_branch_and_bound_ilp", "optimality_gap": 0.0},
            "summary": {
                "candidates_total": 0,
                "selected_count": 0,
                "deferred_count": 0,
                "mandatory_count": 0,
                "total_capex_rub": 0,
                "remaining_budget_rub": max(0, int(budget_rub)),
                "budget_utilization_pct": 0.0,
                "total_risk_reduction": 0.0,
                "risk_coverage_pct": 0.0,
                "total_net_annual_effect_rub": 0,
                "total_opex_rub_yr": 0,
                "payback_years": None,
                "payback_months": None,
            },
            "selected": [],
            "deferred": [],
            "greedy_comparison": None,
            "budget_frontier": [],
        }

    max_risk = max((float(c["risk_reduction_points"]) for c in candidates), default=1.0)
    max_effect = max((max(0.0, float(c["net_annual_effect_rub_yr"])) for c in candidates), default=1.0)
    dep_map = dependencies or {}

    ilp_items: list[IlpItem] = []
    for c in candidates:
        u = _compute_utility(
            c,
            objective=objective,
            alpha_risk=a_w,
            beta_economics=b_w,
            max_risk=max_risk,
            max_effect=max_effect,
        )
        c["utility_score"] = round(u, 4)
        c["utility_per_100k_rub"] = round(u / (float(c["capex_rub"]) / 100_000.0), 3)
        ilp_items.append(
            IlpItem(
                item_id=c["instrument_id"],
                cost=float(c["capex_rub"]),
                utility=u,
                group=c["group"],
                mandatory=bool(c["mandatory"]),
                excluded=bool(c["excluded"]),
                requires_ids=tuple(dep_map.get(c["instrument_id"], [])),
            )
        )

    sol = solve_binary_ilp(
        ilp_items,
        budget=float(budget_rub),
        max_items=max_items,
        min_per_group=min_per_group,
        max_per_group=max_per_group,
    )

    by_id = {c["instrument_id"]: c for c in candidates}
    total_all_risk = sum(float(c["risk_reduction_points"]) for c in candidates if not c["excluded"])
    total_all_capex = sum(int(c["capex_rub"]) for c in candidates if not c["excluded"])
    mandatory_capex = sum(int(c["capex_rub"]) for c in candidates if c["mandatory"])

    sel_set = set(sol.selected_ids)
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for c in candidates:
        row = {**c, "selected": c["instrument_id"] in sel_set}
        if row["selected"]:
            selected.append(row)
        else:
            deferred.append(row)

    selected.sort(key=lambda r: (-int(r["mandatory"]), -r["utility_score"], r["capex_rub"]))
    deferred.sort(key=lambda r: (-r["utility_score"], r["capex_rub"]))

    tot_capex = sum(int(r["capex_rub"]) for r in selected)
    tot_hw = sum(int(r["hw_rub"]) for r in selected)
    tot_smr = sum(int(r["smr_rub"]) for r in selected)
    tot_comm = sum(int(r["commissioning_rub"]) for r in selected)
    tot_opex = sum(int(r["opex_rub_yr"]) for r in selected)
    tot_rounds = sum(int(r["rounds_savings_rub_yr"]) for r in selected)
    tot_risk_rub = sum(int(r["risk_avoided_rub_yr"]) for r in selected)
    tot_net_eff = sum(int(r["net_annual_effect_rub_yr"]) for r in selected)
    tot_risk_pts = round(sum(float(r["risk_reduction_points"]) for r in selected), 2)

    pb_years = round(tot_capex / float(tot_net_eff), 2) if (tot_capex > 0 and tot_net_eff > 0) else None
    pb_months = max(1, int(round(pb_years * 12.0))) if pb_years is not None else None

    # Сравнение с жадным базовым алгоритмом (только если ILP нашёл допустимое решение)
    greedy_comp: dict[str, Any] | None = None
    if sol.status in ("optimal", "time_limit"):
        gr = solve_greedy_baseline(
            ilp_items,
            budget=float(budget_rub),
            max_items=max_items,
            max_per_group=max_per_group,
        )
        gr_sel = [by_id[i] for i in gr["selected_ids"] if i in by_id]
        gr_eff = sum(int(r["net_annual_effect_rub_yr"]) for r in gr_sel)
        gr_risk = round(sum(float(r["risk_reduction_points"]) for r in gr_sel), 2)
        gr_obj = float(gr["objective_value"])
        gain_obj = round(sol.objective_value - gr_obj, 4)
        gain_pct = round((gain_obj / max(abs(gr_obj), 1e-9)) * 100.0, 2) if gr_obj > 0 else 0.0
        greedy_comp = {
            "greedy_status": gr["status"],
            "greedy_selected_count": len(gr_sel),
            "greedy_capex_rub": int(round(gr["total_cost"])),
            "greedy_objective": round(gr_obj, 4),
            "greedy_risk_reduction": gr_risk,
            "greedy_net_annual_effect_rub": gr_eff,
            "ilp_gain_objective": gain_obj,
            "ilp_gain_pct": gain_pct,
            "ilp_gain_risk_points": round(tot_risk_pts - gr_risk, 2),
            "ilp_gain_net_effect_rub": int(tot_net_eff - gr_eff),
        }

    # Построение кривой Парето (Budget Frontier) по сетке бюджетов
    frontier: list[dict[str, Any]] = []
    if include_frontier and total_all_capex > 0:
        min_b = max(mandatory_capex, min((int(c["capex_rub"]) for c in candidates if not c["excluded"]), default=0))
        grid_set = {
            int(budget_rub),
            mandatory_capex,
            min_b,
            total_all_capex,
        }
        for frac in (0.20, 0.35, 0.50, 0.65, 0.80, 1.0):
            grid_set.add(int(round(total_all_capex * frac / 10_000.0) * 10_000))
        for b_pt in sorted(b for b in grid_set if b >= 0):
            f_sol = solve_binary_ilp(
                ilp_items,
                budget=float(b_pt),
                max_items=max_items,
                min_per_group=min_per_group,
                max_per_group=max_per_group,
                time_limit_s=0.4,
            )
            if f_sol.status in ("optimal", "time_limit"):
                f_rows = [by_id[i] for i in f_sol.selected_ids if i in by_id]
                f_cap = sum(int(r["capex_rub"]) for r in f_rows)
                f_risk = round(sum(float(r["risk_reduction_points"]) for r in f_rows), 2)
                f_eff = sum(int(r["net_annual_effect_rub_yr"]) for r in f_rows)
                frontier.append({
                    "budget_rub": b_pt,
                    "status": f_sol.status,
                    "selected_count": len(f_rows),
                    "total_capex_rub": f_cap,
                    "objective_value": round(f_sol.objective_value, 4),
                    "total_risk_reduction": f_risk,
                    "risk_coverage_pct": round((f_risk / max(total_all_risk, 1e-9)) * 100.0, 1),
                    "total_net_annual_effect_rub": f_eff,
                    "is_current_budget": (b_pt == int(budget_rub)),
                })
            else:
                frontier.append({
                    "budget_rub": b_pt,
                    "status": "infeasible",
                    "selected_count": 0,
                    "total_capex_rub": 0,
                    "objective_value": 0.0,
                    "total_risk_reduction": 0.0,
                    "risk_coverage_pct": 0.0,
                    "total_net_annual_effect_rub": 0,
                    "is_current_budget": (b_pt == int(budget_rub)),
                })

    return {
        "computed_at": utcnow_iso(),
        "status": sol.status,
        "objective": objective,
        "objective_label": OBJECTIVE_META[objective],
        "weights": {"alpha_risk": round(a_w, 3), "beta_economics": round(b_w, 3)},
        "budget_rub": int(budget_rub),
        "constraints": {
            "max_items": max_items,
            "group_filter": group_filter,
            "min_per_group": min_per_group or {},
            "max_per_group": max_per_group or {},
            "auto_mandatory_critical": auto_mandatory_critical,
        },
        "solver": sol.to_dict(),
        "summary": {
            "candidates_total": len(candidates),
            "selected_count": len(selected),
            "deferred_count": len(deferred),
            "mandatory_count": sum(1 for c in candidates if c["mandatory"]),
            "mandatory_capex_rub": mandatory_capex,
            "all_candidates_capex_rub": total_all_capex,
            "hw_rub": tot_hw,
            "smr_rub": tot_smr,
            "commissioning_rub": tot_comm,
            "total_capex_rub": tot_capex,
            "remaining_budget_rub": max(0, int(budget_rub) - tot_capex) if sol.status != "infeasible" else 0,
            "budget_utilization_pct": round((tot_capex / max(float(budget_rub), 1.0)) * 100.0, 1) if budget_rub > 0 else 0.0,
            "total_risk_reduction": tot_risk_pts,
            "total_available_risk": round(total_all_risk, 2),
            "risk_coverage_pct": round((tot_risk_pts / max(total_all_risk, 1e-9)) * 100.0, 1) if total_all_risk > 0 else 0.0,
            "risk_avoided_rub_yr": tot_risk_rub,
            "rounds_savings_rub_yr": tot_rounds,
            "total_opex_rub_yr": tot_opex,
            "total_net_annual_effect_rub": tot_net_eff,
            "payback_years": pb_years,
            "payback_months": pb_months,
        },
        "selected": selected,
        "deferred": deferred,
        "greedy_comparison": greedy_comp,
        "budget_frontier": frontier,
    }
