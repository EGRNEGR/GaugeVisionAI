"""
GaugeVision AI — точный решатель 0-1 целочисленного линейного программирования (ILP/MILP).

Решает задачу оптимизации портфеля мероприятий модернизации:
    maximize    sum_i utility_i * x_i
    subject to  sum_i cost_i * x_i <= budget
                x_i in {0, 1}
                x_i = 1  для i in mandatory
                x_i = 0  для i in excluded
                sum_i x_i <= max_items (если задано)
                min_group[g] <= sum_{i in g} x_i <= max_group[g] (если задано)
                x_a <= x_b для зависимостей (a требует b)
                sum_{i in grp} x_i <= 1 для взаимоисключающих альтернатив (SOS1)

Работает в полностью автономном (air-gapped) контуре без внешних библиотек:
  • Предобработка (Presolve): фиксация обязательных/исключённых переменных и
    честная диагностика несовместимости ограничений (`infeasible`) с точным
    дефицитом бюджета.
  • Метод ветвей и границ (Branch-and-Bound) с допустимой LP-релаксацией
    (верхняя граница Данцига с учётом кардинальности `max_items`) и начальным
    допустимым решением — гарантирует доказанный глобальный оптимум (`gap = 0.0`).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IlpItem:
    """Одна бинарная переменная решения x_i in {0, 1}."""

    item_id: str
    cost: float
    utility: float
    group: str = ""
    mandatory: bool = False
    excluded: bool = False
    mutex_group: str | None = None
    requires_ids: tuple[str, ...] = ()


@dataclass
class IlpSolution:
    status: str  # "optimal" | "infeasible" | "empty" | "time_limit"
    selected_ids: list[str] = field(default_factory=list)
    objective_value: float = 0.0
    upper_bound: float = 0.0
    optimality_gap: float = 0.0
    total_cost: float = 0.0
    remaining_budget: float = 0.0
    nodes_explored: int = 0
    solve_time_ms: float = 0.0
    solver_name: str = "exact_branch_and_bound_ilp"
    infeasibility_reason: str | None = None
    min_required_budget: float | None = None
    budget_deficit: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selected_ids": list(self.selected_ids),
            "objective_value": round(self.objective_value, 6),
            "upper_bound": round(self.upper_bound, 6),
            "optimality_gap": round(self.optimality_gap, 6),
            "total_cost": round(self.total_cost, 2),
            "remaining_budget": round(self.remaining_budget, 2),
            "nodes_explored": self.nodes_explored,
            "solve_time_ms": round(self.solve_time_ms, 3),
            "solver_name": self.solver_name,
            "infeasibility_reason": self.infeasibility_reason,
            "min_required_budget": round(self.min_required_budget, 2) if self.min_required_budget is not None else None,
            "budget_deficit": round(self.budget_deficit, 2) if self.budget_deficit is not None else None,
        }


def _expand_mandatory_closure(items: list[IlpItem]) -> tuple[set[str], str | None]:
    """Транзитивно замыкает зависимости x_a <= x_b для обязательных мероприятий."""
    by_id = {it.item_id: it for it in items}
    mand = {it.item_id for it in items if it.mandatory}
    changed = True
    while changed:
        changed = False
        for iid in list(mand):
            it = by_id[iid]
            for req in it.requires_ids:
                if req not in by_id:
                    return mand, f"Обязательное мероприятие «{iid}» требует отсутствующую позицию «{req}»."
                if req not in mand:
                    mand.add(req)
                    changed = True
    return mand, None


def solve_binary_ilp(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None = None,
    min_per_group: dict[str, int] | None = None,
    max_per_group: dict[str, int] | None = None,
    time_limit_s: float = 2.0,
) -> IlpSolution:
    """
    Находит доказанный глобальный оптимум задачи 0-1 ILP методом ветвей и границ.
    """
    t0 = time.perf_counter()
    if not items:
        return IlpSolution(status="empty", remaining_budget=max(0.0, float(budget)))

    budget_f = float(budget)
    if not math.isfinite(budget_f) or budget_f < 0.0:
        return IlpSolution(
            status="infeasible",
            infeasibility_reason="Задан некорректный отрицательный или нечисловой бюджет.",
            min_required_budget=0.0,
            budget_deficit=abs(budget_f) if math.isfinite(budget_f) else None,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    min_grp = {k: max(0, int(v)) for k, v in (min_per_group or {}).items() if int(v) > 0}
    max_grp = {k: max(0, int(v)) for k, v in (max_per_group or {}).items()}
    k_limit = None if max_items is None else max(0, int(max_items))

    # 1. Предобработка: замыкание обязательных зависимостей и проверка противоречий
    mand_ids, dep_err = _expand_mandatory_closure(items)
    if dep_err is not None:
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=dep_err,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    excluded_ids = {it.item_id for it in items if it.excluded}
    conflict_me = mand_ids & excluded_ids
    if conflict_me:
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=f"Противоречие ограничений: позиции {sorted(conflict_me)} одновременно обязательны и исключены.",
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    # Проверка взаимоисключающих групп среди обязательных
    mand_mutex: dict[str, list[str]] = {}
    for it in items:
        if it.item_id in mand_ids and it.mutex_group:
            mand_mutex.setdefault(it.mutex_group, []).append(it.item_id)
    for mg, mlist in mand_mutex.items():
        if len(mlist) > 1:
            return IlpSolution(
                status="infeasible",
                infeasibility_reason=f"Взаимоисключающая группа «{mg}» содержит несколько обязательных позиций: {mlist}.",
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

    fixed_items = [it for it in items if it.item_id in mand_ids]
    fixed_cost = sum(max(0.0, float(it.cost)) for it in fixed_items)
    fixed_util = sum(float(it.utility) for it in fixed_items)
    fixed_count = len(fixed_items)

    fixed_grp_counts: dict[str, int] = {}
    for it in fixed_items:
        fixed_grp_counts[it.group] = fixed_grp_counts.get(it.group, 0) + 1

    # Несовместимость по бюджету для обязательных позиций
    if fixed_cost > budget_f + 1e-6:
        deficit = fixed_cost - budget_f
        b_s = f"{budget_f:,.0f}".replace(",", " ")
        req_s = f"{fixed_cost:,.0f}".replace(",", " ")
        def_s = f"{deficit:,.0f}".replace(",", " ")
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=(
                f"Бюджет {b_s} ₽ недостаточен для покрытия {fixed_count} обязательных мероприятий "
                f"(требуется минимум {req_s} ₽, дефицит {def_s} ₽)."
            ),
            min_required_budget=fixed_cost,
            budget_deficit=deficit,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    if k_limit is not None and fixed_count > k_limit:
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=f"Число обязательных мероприятий ({fixed_count}) превышает лимит позиций за этап ({k_limit}).",
            min_required_budget=fixed_cost,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    for g, cnt in fixed_grp_counts.items():
        if g in max_grp and cnt > max_grp[g]:
            return IlpSolution(
                status="infeasible",
                infeasibility_reason=f"В группе «{g}» обязательных позиций ({cnt}) больше лимита ({max_grp[g]}).",
                min_required_budget=fixed_cost,
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

    rem_budget = budget_f - fixed_cost
    rem_k = None if k_limit is None else (k_limit - fixed_count)

    # Оставшиеся свободные переменные
    used_mutex = set(mand_mutex.keys())
    free_raw: list[IlpItem] = []
    for it in items:
        if it.item_id in mand_ids or it.item_id in excluded_ids:
            continue
        if it.mutex_group and it.mutex_group in used_mutex:
            continue
        # Если какая-то зависимость исключена — сама переменная тоже не может быть выбрана
        if any(req in excluded_ids for req in it.requires_ids):
            continue
        if it.cost > rem_budget + 1e-6:
            continue
        if it.group in max_grp and fixed_grp_counts.get(it.group, 0) >= max_grp[it.group]:
            continue
        # Отрицательная или нулевая полезность может понадобиться ТОЛЬКО для выполнения min_per_group или как зависимость
        free_raw.append(it)

    # Проверка достижимости min_per_group по количеству и минимальному бюджету
    min_grp_rem: dict[str, int] = {}
    min_extra_budget = 0.0
    for g, req_n in min_grp.items():
        need = max(0, req_n - fixed_grp_counts.get(g, 0))
        if need > 0:
            min_grp_rem[g] = need
            g_cands = sorted([it.cost for it in free_raw if it.group == g])
            if len(g_cands) < need:
                return IlpSolution(
                    status="infeasible",
                    infeasibility_reason=f"В группе «{g}» недостаточно доступных кандидатов для квоты min={req_n}.",
                    solve_time_ms=(time.perf_counter() - t0) * 1000.0,
                )
            min_extra_budget += sum(g_cands[:need])

    if min_extra_budget > rem_budget + 1e-6:
        req_tot = fixed_cost + min_extra_budget
        b_s = f"{budget_f:,.0f}".replace(",", " ")
        req_s = f"{req_tot:,.0f}".replace(",", " ")
        def_s = f"{(req_tot - budget_f):,.0f}".replace(",", " ")
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=(
                f"Бюджет {b_s} ₽ недостаточен для выполнения минимальных квот по группам "
                f"(минимум {req_s} ₽, дефицит {def_s} ₽)."
            ),
            min_required_budget=req_tot,
            budget_deficit=req_tot - budget_f,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    # Убираем свободные переменные с utility <= 0, если они не требуются квотами/зависимостями
    needed_as_dep: set[str] = set()
    for it in free_raw:
        for req in it.requires_ids:
            needed_as_dep.add(req)
    free_items = [
        it for it in free_raw
        if it.utility > 0.0 or (it.group in min_grp_rem) or (it.item_id in needed_as_dep)
    ]

    # Сортируем свободные переменные по убыванию удельной эффективности (utility / cost)
    # Если есть зависимости, ставим базовые зависимости ближе к началу для раннего ветвления
    free_items.sort(
        key=lambda it: (
            0 if it.item_id in needed_as_dep else 1,
            -(it.utility / max(it.cost, 1.0)),
            -it.utility,
            it.cost,
            it.item_id,
        )
    )

    n = len(free_items)
    id_to_free_idx = {it.item_id: idx for idx, it in enumerate(free_items)}
    costs = [float(it.cost) for it in free_items]
    utils = [float(it.utility) for it in free_items]
    groups = [it.group for it in free_items]
    mutexes = [it.mutex_group for it in free_items]

    # Для каждой свободной переменной — список свободных индексов, от которых она зависит
    # и список свободных индексов, которые зависят от неё
    req_free: list[tuple[int, ...]] = []
    for it in free_items:
        r_idx: list[int] = []
        valid_deps = True
        for rid in it.requires_ids:
            if rid in mand_ids:
                continue
            if rid in id_to_free_idx:
                r_idx.append(id_to_free_idx[rid])
            else:
                valid_deps = False
                break
        req_free.append(tuple(r_idx) if valid_deps else (-1,))

    # Остаточные счётчики доступных элементов по группам для раннего отсечения по min_per_group
    suffix_grp_avail: list[dict[str, int]] = [{} for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        d = dict(suffix_grp_avail[i + 1])
        g = groups[i]
        d[g] = d.get(g, 0) + 1
        suffix_grp_avail[i] = d

    # Предсортированные индексы:
    # 1) по убыванию удельной полезности u/c (для бюджетной LP-релаксации UB_budget)
    # 2) по убыванию абсолютной полезности u (для кардинальной релаксации UB_card при max_items)
    ratio_order = sorted(range(n), key=lambda i: (-(utils[i] / max(costs[i], 1.0)), -utils[i]))
    util_order = sorted(range(n), key=lambda i: (-utils[i], costs[i]))

    def _upper_bound(idx: int, cur_u: float, b_rem: float, k_rem: int | None) -> float:
        """
        Математически строгая допустимая верхняя граница:
            UB = min(UB_budget, UB_cardinality) >= true_integer_optimum.
        UB_budget — дробная LP-релаксация рюкзака по бюджету (без отсечения по слотам).
        UB_cardinality — сумма k_rem наибольших полезностей (без учёта бюджета).
        """
        if k_rem is not None and k_rem <= 0:
            return cur_u

        # 1. Бюджетная LP-релаксация (дробный рюкзак Данцига)
        ub_budget = cur_u
        rem_b = b_rem
        for j in ratio_order:
            if j < idx:
                continue
            uj = utils[j]
            if uj <= 0.0:
                continue
            cj = costs[j]
            if cj <= 1e-9:
                ub_budget += uj
            elif cj <= rem_b:
                ub_budget += uj
                rem_b -= cj
            else:
                ub_budget += uj * (rem_b / cj)
                break

        if k_rem is None:
            return ub_budget

        # 2. Кардинальная релаксация (не более k_rem оставшихся элементов)
        ub_card = cur_u
        taken = 0
        for j in util_order:
            if j < idx:
                continue
            uj = utils[j]
            if uj <= 0.0:
                break
            ub_card += uj
            taken += 1
            if taken >= k_rem:
                break

        return ub_budget if ub_budget <= ub_card else ub_card

    best_u = -1e300
    best_cost = 0.0
    best_chosen: list[int] = []
    has_feasible = False
    nodes = 0
    timed_out = False
    deadline = t0 + max(0.05, float(time_limit_s))

    # Проверка допустимости завершённого набора по min_per_group и зависимостям
    def _is_leaf_feasible(chosen_mask: list[int], grp_cnt: dict[str, int]) -> bool:
        for g, need in min_grp_rem.items():
            if grp_cnt.get(g, 0) < need:
                return False
        for i in range(n):
            if chosen_mask[i]:
                for r in req_free[i]:
                    if r < 0 or not chosen_mask[r]:
                        return False
        return True

    # Если нет min_per_group и нет зависимостей, сразу пробуем жадное начальное решение
    chosen = [0] * n
    grp_cnt: dict[str, int] = {}
    mutex_used: set[str] = set()

    if not min_grp_rem and all(not r for r in req_free):
        g_b = rem_budget
        g_u = fixed_util
        g_c = fixed_cost
        g_k = 0
        g_sel: list[int] = []
        g_grp: dict[str, int] = {}
        g_mut: set[str] = set()
        for j in ratio_order:
            if utils[j] <= 0.0:
                continue
            if rem_k is not None and g_k >= rem_k:
                break
            if costs[j] > g_b + 1e-9:
                continue
            gj = groups[j]
            if gj in max_grp and fixed_grp_counts.get(gj, 0) + g_grp.get(gj, 0) >= max_grp[gj]:
                continue
            mj = mutexes[j]
            if mj and mj in g_mut:
                continue
            g_b -= costs[j]
            g_u += utils[j]
            g_c += costs[j]
            g_k += 1
            g_sel.append(j)
            g_grp[gj] = g_grp.get(gj, 0) + 1
            if mj:
                g_mut.add(mj)
        best_u = g_u
        best_cost = g_c
        best_chosen = g_sel
        has_feasible = True

    root_ub = _upper_bound(0, fixed_util, rem_budget, rem_k)

    def _dfs(idx: int, cur_u: float, cur_c: float, b_rem: float, k_rem: int | None) -> None:
        nonlocal best_u, best_cost, best_chosen, has_feasible, nodes, timed_out
        nodes += 1
        if (nodes & 1023) == 0 and time.perf_counter() >= deadline:
            timed_out = True
            return
        if timed_out:
            return

        # Проверка достижимости min_per_group на оставшемся хвосте
        for g, need in min_grp_rem.items():
            if grp_cnt.get(g, 0) + suffix_grp_avail[idx].get(g, 0) < need:
                return

        if idx == n:
            if _is_leaf_feasible(chosen, grp_cnt):
                if (not has_feasible) or (cur_u > best_u + 1e-9) or (
                    abs(cur_u - best_u) <= 1e-9 and cur_c < best_cost - 1e-6
                ):
                    best_u = cur_u
                    best_cost = cur_c
                    best_chosen = [i for i in range(n) if chosen[i]]
                    has_feasible = True
            return

        # Отсечение по допустимой верхней границе
        if has_feasible:
            ub = _upper_bound(idx, cur_u, b_rem, k_rem)
            if ub <= best_u + 1e-9:
                return

        # Ветвь 1: x_idx = 1 (если допустимо локальными ограничениями)
        can_take = True
        if req_free[idx] == (-1,):
            can_take = False
        elif costs[idx] > b_rem + 1e-9:
            can_take = False
        elif k_rem is not None and k_rem <= 0:
            can_take = False
        else:
            g = groups[idx]
            if g in max_grp and fixed_grp_counts.get(g, 0) + grp_cnt.get(g, 0) >= max_grp[g]:
                can_take = False
            m = mutexes[idx]
            if can_take and m and m in mutex_used:
                can_take = False
            # Проверка уже пройденных зависимостей: если зависимость j < idx не взята — эту брать нельзя
            if can_take:
                for r in req_free[idx]:
                    if r < idx and not chosen[r]:
                        can_take = False
                        break

        if can_take:
            chosen[idx] = 1
            g = groups[idx]
            m = mutexes[idx]
            grp_cnt[g] = grp_cnt.get(g, 0) + 1
            if m:
                mutex_used.add(m)
            _dfs(
                idx + 1,
                cur_u + utils[idx],
                cur_c + costs[idx],
                b_rem - costs[idx],
                None if k_rem is None else (k_rem - 1),
            )
            chosen[idx] = 0
            grp_cnt[g] -= 1
            if m:
                mutex_used.discard(m)

        # Ветвь 2: x_idx = 0
        # Если какая-то уже взятая переменная (< idx) требует idx, то пропускать idx нельзя
        dep_violated = False
        for prev in range(idx):
            if chosen[prev] and idx in req_free[prev]:
                dep_violated = True
                break
        if not dep_violated:
            _dfs(idx + 1, cur_u, cur_c, b_rem, k_rem)

    _dfs(0, fixed_util, fixed_cost, rem_budget, rem_k)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if not has_feasible:
        return IlpSolution(
            status="infeasible",
            nodes_explored=nodes,
            solve_time_ms=elapsed_ms,
            infeasibility_reason="Не найдено допустимого портфеля, удовлетворяющего всем ограничениям бюджета, квот и зависимостей.",
            min_required_budget=fixed_cost + min_extra_budget,
        )

    selected_ids = [it.item_id for it in fixed_items] + [free_items[i].item_id for i in best_chosen]
    if timed_out:
        gap = max(0.0, (root_ub - best_u) / max(abs(best_u), 1e-9))
        return IlpSolution(
            status="time_limit",
            selected_ids=selected_ids,
            objective_value=best_u,
            upper_bound=max(best_u, root_ub),
            optimality_gap=gap,
            total_cost=best_cost,
            remaining_budget=max(0.0, budget_f - best_cost),
            nodes_explored=nodes,
            solve_time_ms=elapsed_ms,
        )

    return IlpSolution(
        status="optimal",
        selected_ids=selected_ids,
        objective_value=best_u,
        upper_bound=best_u,
        optimality_gap=0.0,
        total_cost=best_cost,
        remaining_budget=max(0.0, budget_f - best_cost),
        nodes_explored=nodes,
        solve_time_ms=elapsed_ms,
    )


def solve_greedy_baseline(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None = None,
    max_per_group: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Наивный жадный базовый алгоритм (сортировка по убыванию utility/cost)
    для честного количественного сравнения выигрыша точного 0-1 ILP.
    """
    mand_ids, err = _expand_mandatory_closure(items)
    if err is not None:
        return {"status": "infeasible", "selected_ids": [], "objective_value": 0.0, "total_cost": 0.0}
    excluded = {it.item_id for it in items if it.excluded}
    max_grp = {k: max(0, int(v)) for k, v in (max_per_group or {}).items()}

    fixed = [it for it in items if it.item_id in mand_ids and it.item_id not in excluded]
    cost = sum(it.cost for it in fixed)
    util = sum(it.utility for it in fixed)
    if cost > budget + 1e-6 or (max_items is not None and len(fixed) > max_items):
        return {"status": "infeasible", "selected_ids": [], "objective_value": 0.0, "total_cost": 0.0}

    sel_set = {it.item_id for it in fixed}
    grp_cnt: dict[str, int] = {}
    mut_used: set[str] = set()
    for it in fixed:
        grp_cnt[it.group] = grp_cnt.get(it.group, 0) + 1
        if it.mutex_group:
            mut_used.add(it.mutex_group)

    free = [it for it in items if it.item_id not in sel_set and it.item_id not in excluded and it.utility > 0.0]
    free.sort(key=lambda it: (-(it.utility / max(it.cost, 1.0)), -it.utility, it.cost))

    for it in free:
        if max_items is not None and len(sel_set) >= max_items:
            break
        if cost + it.cost > budget + 1e-6:
            continue
        if it.group in max_grp and grp_cnt.get(it.group, 0) >= max_grp[it.group]:
            continue
        if it.mutex_group and it.mutex_group in mut_used:
            continue
        if any(req not in sel_set for req in it.requires_ids):
            continue
        sel_set.add(it.item_id)
        cost += it.cost
        util += it.utility
        grp_cnt[it.group] = grp_cnt.get(it.group, 0) + 1
        if it.mutex_group:
            mut_used.add(it.mutex_group)

    return {
        "status": "feasible",
        "selected_ids": list(sel_set),
        "objective_value": round(util, 6),
        "total_cost": round(cost, 2),
        "remaining_budget": round(max(0.0, budget - cost), 2),
    }
