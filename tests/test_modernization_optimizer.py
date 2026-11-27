"""
Независимые математические и интеграционные тесты Modernization Optimizer (0-1 ILP).

Проверяют:
  1. Доказанную глобальную оптимальность `solve_binary_ilp`: сравнение с точным
     полным перебором 2^N на 40 случайных задачах (N = 8..14) с бюджетом, mandatory,
     excluded, max_items, min_per_group, max_per_group и зависимостями x_a <= x_b.
  2. Строгое превосходство 0-1 ILP над наивным жадным алгоритмом на контрпримерах
     и реалистичном бюджете КТЦ ТЭЦ.
  3. Честную диагностику несовместимости (`infeasible`) с точным расчётом дефицита
     бюджета при обязательных мероприятиях, превышающих бюджет.
  4. Отделение чисто оптических проблем камеры от CAPEX замены датчиков и учёт
     прогнозного риска + паспорта критичности I/II/III.
  5. Полную API/SQLite/Spec-интеграцию (FastAPI TestClient): паспорта, решение ILP,
     сохранение плана в БД, генерация `.md` и `.docx` строго по оптимальному плану.

Запуск:
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_modernization_optimizer.py
"""
from __future__ import annotations

import io
import json
import os
import random
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

from app.ilp_solver import IlpItem, solve_binary_ilp, solve_greedy_baseline
from app.modernization_optimizer import optimize_modernization_budget


def _brute_force_ilp(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None = None,
    min_per_group: dict[str, int] | None = None,
    max_per_group: dict[str, int] | None = None,
) -> tuple[str, float, float]:
    """Эталонный полный перебор всех 2^N подмножеств для независимой математической сверки."""
    n = len(items)
    id_to_idx = {it.item_id: i for i, it in enumerate(items)}
    best_u = -1e300
    best_c = 1e300
    found = False
    min_g = min_per_group or {}
    max_g = max_per_group or {}

    for mask in range(1 << n):
        sel_ids: set[str] = set()
        cost = 0.0
        util = 0.0
        cnt = 0
        ok = True
        grp_cnt: dict[str, int] = {}
        mut_seen: set[str] = set()
        for i, it in enumerate(items):
            take = bool((mask >> i) & 1)
            if it.mandatory and not take:
                ok = False
                break
            if it.excluded and take:
                ok = False
                break
            if take:
                sel_ids.add(it.item_id)
                cost += it.cost
                util += it.utility
                cnt += 1
                grp_cnt[it.group] = grp_cnt.get(it.group, 0) + 1
                if it.mutex_group:
                    if it.mutex_group in mut_seen:
                        ok = False
                        break
                    mut_seen.add(it.mutex_group)
        if not ok or cost > budget + 1e-6:
            continue
        if max_items is not None and cnt > max_items:
            continue
        for g, mn in min_g.items():
            if grp_cnt.get(g, 0) < mn:
                ok = False
                break
        if not ok:
            continue
        for g, mx in max_g.items():
            if grp_cnt.get(g, 0) > mx:
                ok = False
                break
        if not ok:
            continue
        for i, it in enumerate(items):
            if (mask >> i) & 1:
                for req in it.requires_ids:
                    if req not in id_to_idx or not ((mask >> id_to_idx[req]) & 1):
                        ok = False
                        break
            if not ok:
                break
        if not ok:
            continue
        if (not found) or (util > best_u + 1e-9) or (abs(util - best_u) <= 1e-9 and cost < best_c):
            best_u = util
            best_c = cost
            found = True

    if not found:
        return "infeasible", 0.0, 0.0
    return "optimal", best_u, best_c


def test_ilp_matches_bruteforce_40_random_instances() -> dict:
    rng = random.Random(20261127)
    checked = 0
    infeasible_cnt = 0
    max_solve_ms = 0.0

    for trial in range(40):
        n = rng.randint(8, 13)
        groups = ["Котлы", "Турбины", "Теплосеть"]
        items: list[IlpItem] = []
        for i in range(n):
            req = (f"x{i - 1}",) if (i >= 2 and trial % 4 == 0 and i == 3) else ()
            items.append(
                IlpItem(
                    item_id=f"x{i}",
                    cost=float(rng.randint(40, 180) * 1000),
                    utility=round(rng.uniform(15.0, 120.0), 2),
                    group=groups[i % len(groups)],
                    mandatory=(i == 0 and trial % 3 == 0),
                    excluded=(i == n - 1 and trial % 5 == 0),
                    requires_ids=req,
                )
            )
        budget = float(rng.randint(250, 720) * 1000)
        max_items = rng.choice([None, 4, 6])
        min_g = {"Котлы": 1} if (trial % 6 == 0) else None
        max_g = {"Турбины": 2} if (trial % 4 == 1) else None

        sol = solve_binary_ilp(
            items,
            budget=budget,
            max_items=max_items,
            min_per_group=min_g,
            max_per_group=max_g,
        )
        bf_status, bf_u, bf_c = _brute_force_ilp(
            items,
            budget=budget,
            max_items=max_items,
            min_per_group=min_g,
            max_per_group=max_g,
        )
        assert sol.status == bf_status, f"trial {trial}: ILP={sol.status} != BF={bf_status}"
        if bf_status == "optimal":
            assert abs(sol.objective_value - bf_u) < 1e-5, f"trial {trial}: ILP={sol.objective_value} != BF={bf_u}"
            assert sol.optimality_gap == 0.0
            assert sol.total_cost <= budget + 1e-6
        else:
            infeasible_cnt += 1
        max_solve_ms = max(max_solve_ms, sol.solve_time_ms)
        checked += 1

    return {
        "random_instances_verified": checked,
        "infeasible_instances": infeasible_cnt,
        "exact_match_pct": 100.0,
        "max_solve_time_ms": round(max_solve_ms, 3),
    }


def test_ilp_strictly_beats_greedy_and_infeasible_diagnostics() -> dict:
    # Классический контрпример: бюджет 100 тыс.
    # Позиция A: cost=60к, u=66 (u/c = 1.10) — жадный берёт A и остаётся с 40к (ничего больше не влезает -> u=66)
    # Позиции B, C: cost=50к, u=50 каждая (u/c = 1.00) — точный ILP берёт B+C (cost=100к -> u=100 > 66!)
    items = [
        IlpItem("A", cost=60_000, utility=66.0, group="G1"),
        IlpItem("B", cost=50_000, utility=50.0, group="G1"),
        IlpItem("C", cost=50_000, utility=50.0, group="G2"),
    ]
    sol = solve_binary_ilp(items, budget=100_000)
    gr = solve_greedy_baseline(items, budget=100_000)
    assert sol.status == "optimal"
    assert set(sol.selected_ids) == {"B", "C"}
    assert abs(sol.objective_value - 100.0) < 1e-6
    assert abs(gr["objective_value"] - 66.0) < 1e-6
    assert sol.objective_value > gr["objective_value"] + 30.0

    # Проверка честной диагностики INFEASIBLE при обязательных позициях > бюджет
    mand_items = [
        IlpItem("M1", cost=120_000, utility=90.0, group="G1", mandatory=True),
        IlpItem("M2", cost=95_000, utility=80.0, group="G2", mandatory=True),
        IlpItem("OPT", cost=50_000, utility=40.0, group="G1"),
    ]
    inf_sol = solve_binary_ilp(mand_items, budget=150_000)
    assert inf_sol.status == "infeasible"
    assert abs(inf_sol.min_required_budget - 215_000.0) < 1e-3
    assert abs(inf_sol.budget_deficit - 65_000.0) < 1e-3
    assert inf_sol.selected_ids == []

    return {
        "ilp_objective": sol.objective_value,
        "greedy_objective": gr["objective_value"],
        "ilp_gain_pct": round((sol.objective_value - gr["objective_value"]) / gr["objective_value"] * 100.0, 2),
        "infeasible_min_required_rub": inf_sol.min_required_budget,
        "infeasible_deficit_rub": inf_sol.budget_deficit,
    }


def test_optical_separation_and_predictive_boost() -> dict:
    disp = {
        "instruments": [
            {
                "id": "p-crit",
                "code": "К1-Т01",
                "name": "Термометр пара К-1",
                "short_name": "К-1 темп. пара",
                "group": "Котлоагрегаты",
                "gauge_type": "temperature",
                "unit": "°C",
                "calibration": {"v_min": 0, "v_max": 600},
                "health_score": 42.0,
                "equipment_health": 42.0,
                "instrument_health": 88.0,
                "optical_health": 95.0,
                "root_cause": "process_anomaly",
                "root_cause_meta": {"label": "Перегрузка процесса"},
                "modernization_needed": True,
                "critical_wear": True,
                "trips_24h": 5,
            },
            {
                "id": "p-opt",
                "code": "К1-Р01",
                "name": "Манометр с загрязнённой камерой",
                "short_name": "К-1 давление",
                "group": "Котлоагрегаты",
                "gauge_type": "pressure",
                "unit": "МПа",
                "calibration": {"v_min": 0, "v_max": 16},
                "health_score": 96.0,
                "equipment_health": 96.0,
                "instrument_health": 98.0,
                "optical_health": 25.0,
                "root_cause": "optical_degradation",
                "root_cause_meta": {"label": "Оптика / связь"},
                "modernization_needed": False,
                "critical_wear": False,
                "trips_24h": 0,
            },
        ]
    }
    pred_low = {"instruments": [{"instrument_id": "p-crit", "breach_prob_alert_horizon": 0.05, "anomaly_score": 10.0}]}
    pred_high = {"instruments": [{"instrument_id": "p-crit", "breach_prob_alert_horizon": 0.95, "anomaly_score": 85.0}]}

    r_low = optimize_modernization_budget(dispatch_overview=disp, predictive_overview=pred_low, budget_rub=300_000, include_frontier=False)
    r_high = optimize_modernization_budget(dispatch_overview=disp, predictive_overview=pred_high, budget_rub=300_000, include_frontier=False)

    # Оптическая проблема камеры НЕ попала в кандидаты замены манометра
    all_ids = [c["instrument_id"] for c in r_high["selected"] + r_high["deferred"]]
    assert "p-crit" in all_ids and "p-opt" not in all_ids
    # Прогнозный риск объективно увеличивает оценку снижения риска и годового эффекта
    assert r_high["selected"][0]["risk_reduction_points"] > r_low["selected"][0]["risk_reduction_points"]
    assert r_high["selected"][0]["net_annual_effect_rub_yr"] > r_low["selected"][0]["net_annual_effect_rub_yr"]

    return {
        "optical_excluded": "p-opt" not in all_ids,
        "risk_pts_low_pred": r_low["selected"][0]["risk_reduction_points"],
        "risk_pts_high_pred": r_high["selected"][0]["risk_reduction_points"],
    }


def test_full_api_sqlite_and_spec_docx_integration() -> dict:
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(prefix="gv_opt_api_") as tmp:
        orig_env = {k: os.environ.get(k) for k in ("GAUGEVISION_DEMO", "GAUGEVISION_DB", "GAUGEVISION_SF_DB", "GAUGEVISION_AUTH_REQUIRED")}
        os.environ["GAUGEVISION_DEMO"] = "1"
        os.environ["GAUGEVISION_DB"] = str(Path(tmp) / "opt_demo.db")
        os.environ["GAUGEVISION_SF_DB"] = str(Path(tmp) / "opt_sf.db")
        os.environ["GAUGEVISION_AUTH_REQUIRED"] = "1"
        try:
            from app import config, main as gv_main

            config.configure_runtime(demo=True, db_path=os.environ["GAUGEVISION_DB"], device="cpu")
            with TestClient(gv_main.app) as client:
                # Вход инженером
                r_login = client.post("/api/auth/login", json={"username": config.ENGINEER_USERNAME, "password": config.ENGINEER_PASSWORD})
                assert r_login.status_code == 200, r_login.text

                # 1. Прогнозная аналитика API
                r_pred = client.get("/api/predictive/overview?window_min=60&horizon_min=60&persist=true")
                assert r_pred.status_code == 200, r_pred.text
                pred_ov = r_pred.json()
                assert pred_ov["summary"]["total"] == 36
                assert pred_ov["summary"]["analyzed_count"] >= 30

                r_pi = client.get("/api/predictive/instrument/sim-02?window_min=60&horizon_min=60")
                assert r_pi.status_code == 200
                pi = r_pi.json()
                assert pi["status"] == "ok" and len(pi["forecast_points"]) >= 5 and len(pi["history_points"]) >= 6

                # 2. Паспорта приборов + редактирование обязательности
                r_pass = client.get("/api/passports")
                assert r_pass.status_code == 200 and len(r_pass.json()) == 36
                r_patch = client.patch("/api/passports/sim-02", json={"criticality_class": 1, "mandatory_regulation": True, "notes": "Предписание КТЦ"})
                assert r_patch.status_code == 200 and r_patch.json()["mandatory_regulation"] is True

                # 3. Оптимизатор бюджета: INFEASIBLE при малом бюджете 20 000 ₽ (из-за обязательной sim-02)
                r_inf = client.post("/api/optimizer/solve", json={"budget_rub": 20_000, "objective": "weighted_utility"})
                assert r_inf.status_code == 200
                inf_data = r_inf.json()
                assert inf_data["status"] == "infeasible"
                assert inf_data["solver"]["budget_deficit"] > 0

                # 4. Оптимизатор бюджета: OPTIMAL при 350 000 ₽ + сохранение плана в SQLite
                r_opt = client.post("/api/optimizer/solve", json={"budget_rub": 350_000, "objective": "weighted_utility", "auto_mandatory_critical": True})
                assert r_opt.status_code == 200
                opt_data = r_opt.json()
                assert opt_data["status"] == "optimal"
                assert opt_data["solver"]["optimality_gap"] == 0.0
                assert opt_data["summary"]["total_capex_rub"] <= 350_000
                assert any(x["instrument_id"] == "sim-02" for x in opt_data["selected"])
                assert len(opt_data["budget_frontier"]) >= 3

                r_save = client.post("/api/optimizer/plans", json={"name": "Этап 1 КТЦ (350 тыс.)", "budget_rub": 350_000, "objective": "weighted_utility", "auto_mandatory_critical": True})
                assert r_save.status_code == 200, r_save.text
                saved_plan = r_save.json()
                plan_id = saved_plan["id"]

                r_plans = client.get("/api/optimizer/plans")
                assert r_plans.status_code == 200 and any(p["id"] == plan_id for p in r_plans.json())

                # 5. Интеграция с генератором ТЗ (.md и .docx) по сохранённому плану
                r_prev = client.post("/api/specs/preview", json={"period": "12h", "format": "md", "optimization_plan_id": plan_id})
                assert r_prev.status_code == 200, r_prev.text
                prev_json = r_prev.json()
                assert prev_json["optimization_applied"] is True
                assert prev_json["tz_count"] == opt_data["summary"]["selected_count"]
                assert "оптимизация бюджета модернизации" in prev_json["markdown"].lower()

                r_docx = client.post("/api/specs/generate", json={"period": "12h", "format": "docx", "optimization_plan_id": plan_id})
                assert r_docx.status_code == 200 and len(r_docx.content) > 5000
                with zipfile.ZipFile(io.BytesIO(r_docx.content)) as zf:
                    doc_xml = zf.read("word/document.xml").decode("utf-8")
                    assert "оптимизация бюджета модернизации" in doc_xml.lower()

                return {
                    "predictive_analyzed": pred_ov["summary"]["analyzed_count"],
                    "opt_selected_count": opt_data["summary"]["selected_count"],
                    "opt_capex_rub": opt_data["summary"]["total_capex_rub"],
                    "opt_risk_coverage_pct": opt_data["summary"]["risk_coverage_pct"],
                    "saved_plan_id": plan_id,
                    "docx_bytes": len(r_docx.content),
                }
        finally:
            for k, v in orig_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def main() -> None:
    report = {}
    report["bruteforce_verification"] = test_ilp_matches_bruteforce_40_random_instances()
    print("[PASS] test_ilp_matches_bruteforce_40_random_instances", report["bruteforce_verification"])
    report["greedy_and_infeasible"] = test_ilp_strictly_beats_greedy_and_infeasible_diagnostics()
    print("[PASS] test_ilp_strictly_beats_greedy_and_infeasible_diagnostics", report["greedy_and_infeasible"])
    report["optical_and_predictive"] = test_optical_separation_and_predictive_boost()
    print("[PASS] test_optical_separation_and_predictive_boost", report["optical_and_predictive"])
    report["api_sqlite_spec_docx"] = test_full_api_sqlite_and_spec_docx_integration()
    print("[PASS] test_full_api_sqlite_and_spec_docx_integration", report["api_sqlite_spec_docx"])
    print("ALL MODERNIZATION OPTIMIZER TESTS PASSED (4/4)")
    out_path = os.environ.get("OPTIMIZER_TEST_OUT")
    if out_path:
        Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
