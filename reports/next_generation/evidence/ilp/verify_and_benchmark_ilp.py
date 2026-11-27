"""
Независимая математическая верификация и нагрузочный бенчмарк решателя `app/ilp_solver.py`.

Выполняет:
  1. 1500 воспроизводимых случайных малых задач (N = 5..12): `bnb` vs Brute-Force 2^N vs HiGHS
     (включая точную проверку `min_required_budget` на всех неразрешимых задачах).
  2. Матрица 14 граничных и некорректных случаев (нулевые/дробные стоимости, отрицательная
     полезность, транзитивные цепочки, циклы SCC, неразрешимость, некорректный ввод,
     жёсткий таймаут с доказанной UB и gap, кооперативная отмена `cancel_event`).
  3. Сравнение `bnb` и промышленного C++ решателя `HiGHS` (scipy.optimize.milp) на масштабах
     N = 36, 100, 250, 500, 1000 по 4 семействам задач (типовые промышленные, сильно
     коррелированные, subset-sum, плотно ограниченные с зависимостями и квотами).
     Замеры: время решения (мс), пиковая RAM (tracemalloc КБ), узлы, точность, optimality gap.
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
import threading
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.ilp_solver import HIGHS_AVAILABLE, IlpItem, solve_binary_ilp  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent


def solve_bruteforce_exact(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None = None,
    min_per_group: dict[str, int] | None = None,
    max_per_group: dict[str, int] | None = None,
) -> dict:
    n = len(items)
    id_to_idx = {it.item_id: i for i, it in enumerate(items)}
    min_g = {k: int(v) for k, v in (min_per_group or {}).items() if int(v) > 0}
    max_g = {k: int(v) for k, v in (max_per_group or {}).items()}

    valid_dep_idx: list[list[int] | None] = []
    for it in items:
        reqs = []
        ok = True
        for r in it.requires_ids:
            if r == it.item_id:
                continue
            if r not in id_to_idx:
                ok = False
                break
            reqs.append(id_to_idx[r])
        valid_dep_idx.append(reqs if ok else None)

    best_u = -1e300
    best_c = 1e300
    best_mask = -1
    min_req_budget = 1e300
    any_struct_feasible = False

    for mask in range(1 << n):
        ok = True
        cost = 0.0
        util = 0.0
        cnt = 0
        gcnt: dict[str, int] = {}
        mut: set[str] = set()

        for i in range(n):
            bit = (mask >> i) & 1
            it = items[i]
            if it.mandatory and not bit:
                ok = False
                break
            if it.excluded and bit:
                ok = False
                break
            if bit:
                if valid_dep_idx[i] is None:
                    ok = False
                    break
                for r in valid_dep_idx[i]:
                    if not ((mask >> r) & 1):
                        ok = False
                        break
                if not ok:
                    break
                if it.mutex_group:
                    if it.mutex_group in mut:
                        ok = False
                        break
                    mut.add(it.mutex_group)
                cost += it.cost
                util += it.utility
                cnt += 1
                gcnt[it.group] = gcnt.get(it.group, 0) + 1
        if not ok:
            continue
        if max_items is not None and cnt > max_items:
            continue
        if any(gcnt.get(g, 0) < mn for g, mn in min_g.items()):
            continue
        if any(gcnt.get(g, 0) > mx for g, mx in max_g.items()):
            continue

        any_struct_feasible = True
        if cost < min_req_budget:
            min_req_budget = cost

        if cost <= budget + 1e-9:
            if (util > best_u + 1e-9) or (abs(util - best_u) <= 1e-9 and cost < best_c - 1e-9):
                best_u = util
                best_c = cost
                best_mask = mask

    if best_mask < 0:
        return {
            "status": "infeasible",
            "objective_value": None,
            "total_cost": None,
            "selected_ids": [],
            "min_required_budget": round(min_req_budget, 6) if any_struct_feasible else None,
        }
    return {
        "status": "optimal",
        "objective_value": best_u,
        "total_cost": best_c,
        "selected_ids": [items[i].item_id for i in range(n) if (best_mask >> i) & 1],
        "min_required_budget": round(min_req_budget, 6) if any_struct_feasible else None,
    }


def verify_solution_constraints(
    items: list[IlpItem],
    selected_ids: list[str],
    *,
    budget: float,
    max_items: int | None = None,
    min_per_group: dict[str, int] | None = None,
    max_per_group: dict[str, int] | None = None,
) -> tuple[bool, str]:
    sel = set(selected_ids)
    if len(sel) != len(selected_ids):
        return False, "duplicate selected_ids"
    by_id = {it.item_id: it for it in items}
    for sid in sel:
        if sid not in by_id:
            return False, f"unknown id {sid}"
    cost = 0.0
    gcnt: dict[str, int] = {}
    mut: set[str] = set()
    for it in items:
        take = it.item_id in sel
        if it.mandatory and not take:
            return False, f"mandatory missing: {it.item_id}"
        if it.excluded and take:
            return False, f"excluded chosen: {it.item_id}"
        if take:
            cost += it.cost
            gcnt[it.group] = gcnt.get(it.group, 0) + 1
            if it.mutex_group:
                if it.mutex_group in mut:
                    return False, f"mutex violated: {it.mutex_group}"
                mut.add(it.mutex_group)
            for req in it.requires_ids:
                if req != it.item_id and req not in sel:
                    return False, f"dep violated: {it.item_id}->{req}"
    if cost > budget + 1e-5:
        return False, f"budget exceeded: {cost} > {budget}"
    if max_items is not None and len(sel) > max_items:
        return False, f"max_items exceeded: {len(sel)} > {max_items}"
    for g, mn in (min_per_group or {}).items():
        if gcnt.get(g, 0) < mn:
            return False, f"min_per_group violated: {g}"
    for g, mx in (max_per_group or {}).items():
        if gcnt.get(g, 0) > mx:
            return False, f"max_per_group violated: {g}"
    return True, "ok"


def gen_random_small(rng: random.Random, idx: int) -> tuple[list[IlpItem], dict]:
    n = rng.randint(5, 11)
    groups = ["G1", "G2", "G3"]
    mode = idx % 5
    items: list[IlpItem] = []
    ids = [f"it_{i}" for i in range(n)]

    for i in range(n):
        if mode == 1:
            # Нулевые и дробные (< 1) стоимости
            cost = rng.choice([0.0, 0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0])
            util = round(rng.uniform(-5.0, 30.0), 3)
        elif mode == 2:
            # Отрицательные и нулевые полезности
            cost = round(rng.uniform(0.0, 100.0), 2)
            util = round(rng.uniform(-25.0, 40.0), 3)
        elif mode == 3:
            # Циклы и плотные зависимости
            cost = round(rng.uniform(5.0, 80.0), 2)
            util = round(rng.uniform(-10.0, 60.0), 3)
        elif mode == 4:
            # Сильно коррелированные веса и полезности
            cost = round(rng.uniform(20.0, 120.0), 2)
            util = round(cost + 15.0 + rng.uniform(-0.5, 0.5), 3)
        else:
            cost = round(rng.uniform(10.0, 150.0), 2)
            util = round(rng.uniform(1.0, 120.0), 3)

        mand = rng.random() < 0.14
        excl = (not mand) and (rng.random() < 0.12)
        if rng.random() < 0.02:
            excl = True
        mut = rng.choice(["M1", "M2"]) if rng.random() < 0.25 else None
        reqs: list[str] = []
        if rng.random() < (0.45 if mode == 3 else 0.28):
            cand = [ids[j] for j in range(n) if j != i] if mode == 3 else [ids[j] for j in range(i)]
            if cand:
                reqs = rng.sample(cand, k=rng.randint(1, min(2, len(cand))))
        items.append(IlpItem(
            item_id=ids[i],
            cost=cost,
            utility=util,
            group=rng.choice(groups),
            mandatory=mand,
            excluded=excl,
            mutex_group=mut,
            requires_ids=tuple(reqs),
        ))

    total_c = sum(it.cost for it in items)
    budget = round(total_c * rng.uniform(0.10, 0.85), 2)
    max_items = rng.randint(2, n) if rng.random() < 0.55 else None
    min_g = {g: rng.randint(1, 2) for g in groups if rng.random() < 0.30}
    max_g = {g: rng.randint(1, 4) for g in groups if rng.random() < 0.45}
    return items, {
        "budget": budget,
        "max_items": max_items,
        "min_per_group": min_g or None,
        "max_per_group": max_g or None,
        "mode": mode,
    }


def run_part_a_small_verification(total: int = 1500) -> dict:
    rng = random.Random(20261127)
    t0 = time.perf_counter()
    bnb_matches = 0
    highs_matches = 0
    min_budget_checked = 0
    min_budget_matches = 0
    infeasible_total = 0
    feasible_total = 0
    mismatches: list[dict] = []

    for idx in range(total):
        items, kw = gen_random_small(rng, idx)
        mode = kw.pop("mode")
        bf = solve_bruteforce_exact(items, **kw)
        sol_bnb = solve_binary_ilp(items, **kw, time_limit_s=3.0, solver_backend="bnb")
        sol_hi = solve_binary_ilp(items, **kw, time_limit_s=3.0, solver_backend="highs") if HIGHS_AVAILABLE else None

        if bf["status"] == "optimal":
            feasible_total += 1
            ok_c, msg_c = verify_solution_constraints(items, sol_bnb.selected_ids, **kw)
            ok_b = (
                sol_bnb.status == "optimal"
                and sol_bnb.optimality_gap == 0.0
                and ok_c
                and abs(sol_bnb.objective_value - bf["objective_value"]) <= 1e-4
            )
            if ok_b:
                bnb_matches += 1
            elif len(mismatches) < 10:
                mismatches.append({"trial": idx, "mode": mode, "where": "bnb", "msg": msg_c, "bf": bf, "sol": sol_bnb.to_dict()})

            if sol_hi is not None:
                ok_hc, msg_hc = verify_solution_constraints(items, sol_hi.selected_ids, **kw)
                ok_h = (
                    sol_hi.status == "optimal"
                    and ok_hc
                    and abs(sol_hi.objective_value - bf["objective_value"]) <= 1e-4
                )
                if ok_h:
                    highs_matches += 1
                elif len(mismatches) < 10:
                    mismatches.append({"trial": idx, "mode": mode, "where": "highs", "msg": msg_hc, "bf": bf, "sol": sol_hi.to_dict()})
        else:
            infeasible_total += 1
            ok_b = (sol_bnb.status == "infeasible")
            if ok_b:
                bnb_matches += 1
            elif len(mismatches) < 10:
                mismatches.append({"trial": idx, "mode": mode, "where": "bnb_inf", "bf": bf, "sol": sol_bnb.to_dict()})

            # Точность min_required_budget на всех неразрешимых задачах
            min_budget_checked += 1
            bf_mb = bf["min_required_budget"]
            sol_mb = sol_bnb.min_required_budget
            if bf_mb is None and sol_mb is None:
                min_budget_matches += 1
            elif bf_mb is not None and sol_mb is not None and abs(bf_mb - sol_mb) <= 1e-2:
                min_budget_matches += 1
            elif len(mismatches) < 10:
                mismatches.append({
                    "trial": idx, "mode": mode, "where": "min_budget",
                    "bf_min_budget": bf_mb, "sol_min_budget": sol_mb,
                })

            if sol_hi is not None and sol_hi.status == "infeasible":
                highs_matches += 1

    return {
        "trials": total,
        "feasible_instances": feasible_total,
        "infeasible_instances": infeasible_total,
        "bnb_exact_matches": bnb_matches,
        "bnb_exact_match_pct": round(bnb_matches / total * 100.0, 4),
        "highs_exact_matches": highs_matches if HIGHS_AVAILABLE else None,
        "highs_exact_match_pct": round(highs_matches / total * 100.0, 4) if HIGHS_AVAILABLE else None,
        "min_required_budget_checked": min_budget_checked,
        "min_required_budget_exact_matches": min_budget_matches,
        "min_required_budget_exact_pct": round(min_budget_matches / max(1, min_budget_checked) * 100.0, 4),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "mismatches": mismatches,
    }


def run_part_b_edge_cases() -> dict:
    checks: list[dict] = []

    def _rec(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # 1. Нулевая стоимость + дробные стоимости (регрессия найденного дефекта Trial 697)
    items_z = [
        IlpItem("z0", cost=0.0, utility=12.0, group="G1"),
        IlpItem("z1", cost=0.0, utility=-5.0, group="G1"),
        IlpItem("f1", cost=0.2, utility=10.0, group="G1"),
        IlpItem("f2", cost=0.5, utility=15.0, group="G1"),
        IlpItem("f3", cost=0.4, utility=14.0, group="G2"),
    ]
    bf_z = solve_bruteforce_exact(items_z, budget=0.6)
    s_z = solve_binary_ilp(items_z, budget=0.6, solver_backend="bnb")
    _rec(
        "zero_and_subunit_costs",
        s_z.status == "optimal" and abs(s_z.objective_value - bf_z["objective_value"]) < 1e-6 and "z0" in s_z.selected_ids and "z1" not in s_z.selected_ids,
        f"bf={bf_z['objective_value']}, bnb={s_z.objective_value}, sel={s_z.selected_ids}",
    )

    # 2. Отрицательная полезность, необходимая как зависимость прибыльного элемента
    items_neg_dep = [
        IlpItem("base", cost=20.0, utility=-10.0, group="G1"),
        IlpItem("addon", cost=30.0, utility=55.0, group="G1", requires_ids=("base",)),
        IlpItem("solo", cost=45.0, utility=35.0, group="G1"),
    ]
    s_nd = solve_binary_ilp(items_neg_dep, budget=50.0, solver_backend="bnb")
    _rec(
        "negative_utility_as_dependency",
        s_nd.status == "optimal" and set(s_nd.selected_ids) == {"base", "addon"} and abs(s_nd.objective_value - 45.0) < 1e-6,
        f"sel={s_nd.selected_ids}, obj={s_nd.objective_value}",
    )

    # 3. Отрицательная полезность, вынужденная квотой min_per_group
    items_neg_q = [
        IlpItem("neg_g1", cost=10.0, utility=-8.0, group="G1"),
        IlpItem("pos_g2", cost=20.0, utility=40.0, group="G2"),
    ]
    s_nq = solve_binary_ilp(items_neg_q, budget=35.0, min_per_group={"G1": 1}, solver_backend="bnb")
    _rec(
        "negative_utility_for_min_quota",
        s_nq.status == "optimal" and set(s_nq.selected_ids) == {"neg_g1", "pos_g2"} and abs(s_nq.objective_value - 32.0) < 1e-6,
        f"sel={s_nq.selected_ids}, obj={s_nq.objective_value}",
    )

    # 4. Транзитивная цепочка 4-го порядка с обязательным элементом (A->B->C->D)
    items_chain = [
        IlpItem("D", cost=10.0, utility=5.0, group="G1"),
        IlpItem("C", cost=15.0, utility=5.0, group="G1", requires_ids=("D",)),
        IlpItem("B", cost=20.0, utility=5.0, group="G1", requires_ids=("C",)),
        IlpItem("A", cost=25.0, utility=50.0, group="G1", mandatory=True, requires_ids=("B",)),
    ]
    s_ch_ok = solve_binary_ilp(items_chain, budget=70.0, solver_backend="bnb")
    s_ch_inf = solve_binary_ilp(items_chain, budget=50.0, solver_backend="bnb")
    _rec(
        "transitive_4hop_mandatory_closure",
        s_ch_ok.status == "optimal" and len(s_ch_ok.selected_ids) == 4 and s_ch_inf.status == "infeasible" and abs((s_ch_inf.min_required_budget or 0) - 70.0) < 1e-4,
        f"ok_sel={s_ch_ok.selected_ids}, inf_min_req={s_ch_inf.min_required_budget}",
    )

    # 5. Циклическая зависимость (A <-> B <-> C) среди свободных элементов: должна браться целиком (SCC) или не браться вообще
    items_cyc = [
        IlpItem("A", cost=20.0, utility=35.0, group="G1", requires_ids=("B",)),
        IlpItem("B", cost=20.0, utility=-5.0, group="G1", requires_ids=("C",)),
        IlpItem("C", cost=20.0, utility=30.0, group="G1", requires_ids=("A",)),
        IlpItem("D", cost=50.0, utility=45.0, group="G2"),
    ]
    s_cyc_60 = solve_binary_ilp(items_cyc, budget=60.0, solver_backend="bnb")
    s_cyc_50 = solve_binary_ilp(items_cyc, budget=50.0, solver_backend="bnb")
    _rec(
        "cyclic_dependency_scc",
        s_cyc_60.status == "optimal" and set(s_cyc_60.selected_ids) == {"A", "B", "C"} and abs(s_cyc_60.objective_value - 60.0) < 1e-6
        and s_cyc_50.status == "optimal" and set(s_cyc_50.selected_ids) == {"D"},
        f"b60={s_cyc_60.selected_ids}({s_cyc_60.objective_value}), b50={s_cyc_50.selected_ids}({s_cyc_50.objective_value})",
    )

    # 6. Цикл с mutex внутри цикла: ни один элемент цикла не может быть выбран
    items_cmut = [
        IlpItem("A", cost=10.0, utility=50.0, group="G1", mutex_group="M1", requires_ids=("B",)),
        IlpItem("B", cost=10.0, utility=50.0, group="G1", mutex_group="M1", requires_ids=("A",)),
        IlpItem("C", cost=10.0, utility=12.0, group="G2"),
    ]
    s_cm = solve_binary_ilp(items_cmut, budget=100.0, solver_backend="bnb")
    _rec(
        "cyclic_dependency_with_mutex_conflict",
        s_cm.status == "optimal" and set(s_cm.selected_ids) == {"C"},
        f"sel={s_cm.selected_ids}",
    )

    # 7. Точный min_required_budget при min_per_group + зависимости (G1 требует элемент, зависящий от дорогого G2)
    items_mb = [
        IlpItem("dep_hi", cost=100.0, utility=10.0, group="G2"),
        IlpItem("g1_cheap_but_dep", cost=10.0, utility=50.0, group="G1", requires_ids=("dep_hi",)),
        IlpItem("g1_direct", cost=45.0, utility=20.0, group="G1"),
    ]
    s_mb = solve_binary_ilp(items_mb, budget=30.0, min_per_group={"G1": 1}, solver_backend="bnb")
    _rec(
        "exact_min_budget_with_deps_and_quota",
        s_mb.status == "infeasible" and abs((s_mb.min_required_budget or 0) - 45.0) < 1e-4 and abs((s_mb.budget_deficit or 0) - 15.0) < 1e-4,
        f"min_req={s_mb.min_required_budget}, deficit={s_mb.budget_deficit}",
    )

    # 8. Структурная неразрешимость (min_per_group > max_per_group): min_required_budget == None
    s_struct = solve_binary_ilp(items_mb, budget=500.0, min_per_group={"G1": 2}, max_per_group={"G1": 1}, solver_backend="bnb")
    _rec(
        "structurally_infeasible_no_fake_budget",
        s_struct.status == "infeasible" and s_struct.min_required_budget is None,
        f"status={s_struct.status}, min_req={s_struct.min_required_budget}, reason={s_struct.infeasibility_reason}",
    )

    # 9-12. Некорректные входные данные: отрицательная стоимость, NaN, дубликат ID, отрицательный бюджет
    bad_cases = [
        ("negative_cost_rejected", lambda: solve_binary_ilp([IlpItem("a", -5.0, 10.0)], budget=100.0)),
        ("nan_utility_rejected", lambda: solve_binary_ilp([IlpItem("a", 10.0, float("nan"))], budget=100.0)),
        ("inf_cost_rejected", lambda: solve_binary_ilp([IlpItem("a", float("inf"), 10.0)], budget=100.0)),
        ("duplicate_item_id_rejected", lambda: solve_binary_ilp([IlpItem("a", 10.0, 5.0), IlpItem("a", 20.0, 6.0)], budget=100.0)),
    ]
    for cname, fn in bad_cases:
        try:
            fn()
            _rec(cname, False, "expected ValueError but succeeded")
        except ValueError as exc:
            _rec(cname, True, f"raised ValueError: {exc}")

    # 13. Жёсткий time_limit на трудной strongly-correlated задаче N=250: статус НЕ OPTIMAL, честная UB и gap
    rng_hard = random.Random(999)
    hard_items = []
    for i in range(250):
        c = float(rng_hard.randint(100, 1000))
        hard_items.append(IlpItem(f"h_{i}", cost=c, utility=c + 100.0, group=f"G{i%5}"))
    hard_b = sum(it.cost for it in hard_items) * 0.5
    s_tl = solve_binary_ilp(hard_items, budget=hard_b, time_limit_s=0.03, solver_backend="bnb")
    s_hi_ref = solve_binary_ilp(hard_items, budget=hard_b, time_limit_s=5.0, solver_backend="highs") if HIGHS_AVAILABLE else None
    ub_valid = (s_hi_ref is None) or (s_tl.upper_bound >= s_hi_ref.objective_value - 1e-4)
    _rec(
        "hard_timeout_returns_non_optimal_with_valid_ub_and_gap",
        s_tl.status == "time_limit" and s_tl.has_feasible_solution and s_tl.upper_bound >= s_tl.objective_value and ub_valid and s_tl.optimality_gap >= 0.0,
        f"status={s_tl.status}, obj={s_tl.objective_value:.2f}, ub={s_tl.upper_bound:.2f}, highs_opt={s_hi_ref.objective_value if s_hi_ref else None}, gap={s_tl.optimality_gap:.6f}",
    )

    # 14. Кооперативная отмена через threading.Event
    ev = threading.Event()
    ev.set()
    s_can = solve_binary_ilp(hard_items, budget=hard_b, time_limit_s=5.0, cancel_event=ev, solver_backend="bnb")
    _rec(
        "cooperative_cancellation_event",
        s_can.status == "cancelled" and s_can.solve_time_ms < 50.0,
        f"status={s_can.status}, solve_time_ms={s_can.solve_time_ms:.3f}, has_feas={s_can.has_feasible_solution}",
    )

    passed_n = sum(1 for c in checks if c["passed"])
    return {"total": len(checks), "passed": passed_n, "all_passed": passed_n == len(checks), "checks": checks}


def gen_scale_instance(n: int, family: str, seed: int) -> tuple[list[IlpItem], dict]:
    rng = random.Random(seed)
    groups = [f"Цех-{k+1}" for k in range(6)]
    items: list[IlpItem] = []

    for i in range(n):
        if family == "typical_industrial":
            cost = float(rng.randint(55, 220) * 1000)
            util = round(rng.uniform(20.0, 140.0), 3)
            mand = (i < max(2, n // 15))
            excl = (not mand) and (rng.random() < 0.05)
            mut = f"M{i // 4}" if (i % 9 == 0) else None
            reqs = (f"obj_{i-1}",) if (i >= 5 and i % 13 == 0 and not excl) else ()
        elif family == "strongly_correlated":
            cost = float(rng.randint(50, 500) * 1000)
            util = round(cost / 1000.0 + 100.0, 3)
            mand = False
            excl = False
            mut = None
            reqs = ()
        elif family == "subset_sum":
            cost = float(rng.randint(40, 400) * 1000)
            util = round(cost / 1000.0, 3)
            mand = False
            excl = False
            mut = None
            reqs = ()
        else:  # dense_constrained
            cost = float(rng.randint(60, 250) * 1000)
            util = round(rng.uniform(30.0, 180.0), 3)
            mand = (i < max(2, n // 20))
            excl = (not mand) and (rng.random() < 0.08)
            mut = f"M{i // 3}" if (i % 6 < 2 and not mand) else None
            reqs = (f"obj_{i-2}",) if (i >= 4 and i % 5 == 0 and not mand and not excl) else ()

        items.append(IlpItem(
            item_id=f"obj_{i}",
            cost=cost,
            utility=util,
            group=groups[i % len(groups)],
            mandatory=mand,
            excluded=excl,
            mutex_group=mut,
            requires_ids=reqs,
        ))

    tot_cost = sum(it.cost for it in items if not it.excluded)
    budget = round(tot_cost * (0.48 if family in ("strongly_correlated", "subset_sum") else 0.42), 2)
    if family == "dense_constrained":
        min_g = {groups[0]: max(1, n // 25), groups[1]: max(1, n // 25)}
        max_g = {groups[2]: max(2, n // 8), groups[3]: max(2, n // 8)}
        max_items = max(5, int(n * 0.45))
    elif family == "typical_industrial":
        min_g = {groups[0]: 1}
        max_g = {groups[1]: max(3, n // 5)}
        max_items = None
    else:
        min_g = None
        max_g = None
        max_items = None

    return items, {
        "budget": budget,
        "max_items": max_items,
        "min_per_group": min_g,
        "max_per_group": max_g,
    }


def run_part_c_scalability() -> list[dict]:
    sizes = [36, 100, 250, 500, 1000]
    families = ["typical_industrial", "strongly_correlated", "subset_sum", "dense_constrained"]
    rows: list[dict] = []

    for n in sizes:
        for f_idx, fam in enumerate(families):
            items, kw = gen_scale_instance(n, fam, seed=10000 + n * 10 + f_idx)
            # 1. HiGHS reference
            hi_row: dict = {}
            if HIGHS_AVAILABLE:
                tracemalloc.start()
                sol_hi = solve_binary_ilp(items, **kw, time_limit_s=5.0, solver_backend="highs")
                _, hi_peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                ok_hi, _ = verify_solution_constraints(items, sol_hi.selected_ids, **kw) if sol_hi.has_feasible_solution else (True, "na")
                hi_row = {
                    "highs_status": sol_hi.status,
                    "highs_time_ms": round(sol_hi.solve_time_ms, 3),
                    "highs_ram_kb": round(hi_peak / 1024.0, 1),
                    "highs_obj": round(sol_hi.objective_value, 4),
                    "highs_ub": round(sol_hi.upper_bound, 4),
                    "highs_gap_pct": round(sol_hi.optimality_gap * 100.0, 4),
                    "highs_feasible_ok": ok_hi,
                }

            # 2. Custom air-gapped B&B (1.0s limit per test)
            tracemalloc.start()
            sol_bnb = solve_binary_ilp(items, **kw, time_limit_s=1.0, solver_backend="bnb")
            _, bnb_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            ok_bnb, _ = verify_solution_constraints(items, sol_bnb.selected_ids, **kw) if sol_bnb.has_feasible_solution else (True, "na")

            rel_err_pct = None
            ub_sound = True
            if HIGHS_AVAILABLE and hi_row.get("highs_status") == "optimal":
                hi_obj = hi_row["highs_obj"]
                if sol_bnb.has_feasible_solution and abs(hi_obj) > 1e-9:
                    rel_err_pct = round(max(0.0, (hi_obj - sol_bnb.objective_value) / abs(hi_obj) * 100.0), 5)
                if sol_bnb.status in ("optimal", "time_limit") and sol_bnb.has_feasible_solution:
                    ub_sound = (sol_bnb.upper_bound >= hi_obj - 1e-3)

            row = {
                "n": n,
                "family": fam,
                "bnb_status": sol_bnb.status,
                "bnb_time_ms": round(sol_bnb.solve_time_ms, 3),
                "bnb_ram_kb": round(bnb_peak / 1024.0, 1),
                "bnb_nodes": sol_bnb.nodes_explored,
                "bnb_obj": round(sol_bnb.objective_value, 4),
                "bnb_ub": round(sol_bnb.upper_bound, 4),
                "bnb_gap_pct": round(sol_bnb.optimality_gap * 100.0, 4),
                "bnb_feasible_ok": ok_bnb,
                "bnb_rel_err_vs_highs_pct": rel_err_pct,
                "bnb_ub_sound": ub_sound,
                **hi_row,
            }
            rows.append(row)
            print(
                f"N={n:4d} | {fam:20s} | BnB: {sol_bnb.status:10s} {sol_bnb.solve_time_ms:7.2f}ms gap={row['bnb_gap_pct']:6.3f}% err={rel_err_pct} | "
                f"HiGHS: {hi_row.get('highs_status','na'):10s} {hi_row.get('highs_time_ms',0):7.2f}ms",
                flush=True,
            )

    return rows


def main() -> None:
    print(f"HIGHS_AVAILABLE={HIGHS_AVAILABLE}")
    part_a = run_part_a_small_verification(1500)
    print("PART A:", json.dumps({k: v for k, v in part_a.items() if k != "mismatches"}, ensure_ascii=False))
    if part_a["mismatches"]:
        print("MISMATCHES:", json.dumps(part_a["mismatches"][:3], ensure_ascii=False, indent=2))

    part_b = run_part_b_edge_cases()
    print(f"PART B: {part_b['passed']}/{part_b['total']} passed")
    for c in part_b["checks"]:
        if not c["passed"]:
            print("  FAIL:", c)

    part_c = run_part_c_scalability()

    full = {
        "highs_available": HIGHS_AVAILABLE,
        "part_a_small_1500": part_a,
        "part_b_edge_cases": part_b,
        "part_c_scalability": part_c,
    }
    (OUT_DIR / "ilp_verification_and_scalability.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (OUT_DIR / "ilp_scalability.csv").open("w", newline="", encoding="utf-8") as f:
        if part_c:
            w = csv.DictWriter(f, fieldnames=list(part_c[0].keys()))
            w.writeheader()
            w.writerows(part_c)
    print("SAVED evidence to", OUT_DIR)


if __name__ == "__main__":
    main()
