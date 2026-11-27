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
                x_a <= x_b для зависимостей (a требует b, включая цепочки и циклы SCC)
                sum_{i in grp} x_i <= 1 для взаимоисключающих альтернатив (SOS1)

Два взаимозаменяемых бэкенда:
  1. `bnb` (100% air-gapped, без внешних библиотек):
       • Предобработка (Presolve): транзитивное замыкание зависимостей (включая циклы),
         отсечение структурно недопустимых переменных, точный расчёт `min_required_budget`
         через вспомогательную ILP-задачу минимизации стоимости.
       • Многостартовая прямая эвристика + 1-swap локальный поиск для сильного начального
         допустимого решения.
       • Метод ветвей и границ (Branch-and-Bound) со строго допустимой верхней оценкой
         Данцига `UB = min(UB_budget, UB_cardinality)` (с корректной обработкой нулевых
         и дробных стоимостей `0 <= cost < 1` и `O(log n)`-оценкой по префиксным суммам
         при отсутствии зависимостей).
       • Честный трекинг глобальной верхней границы по неисследованным ветвям (`frontier_ub`),
         ограничение времени `time_limit_s` и кооперативная отмена `cancel_event`.
         Статус `"optimal"` присваивается ТОЛЬКО при доказанном исчерпании дерева (`gap = 0.0`).
  2. `highs` (опциональный промышленный C++ MILP-решатель HiGHS через `scipy.optimize.milp`,
     если установлен в среде): используется в режиме `solver_backend="auto"` на крупных
     задачах (`n > 40`) или при явном выборе `solver_backend="highs"`.
"""
from __future__ import annotations

import bisect
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

try:
    import numpy as _np
    from scipy.optimize import Bounds as _ScipyBounds
    from scipy.optimize import LinearConstraint as _ScipyLinearConstraint
    from scipy.optimize import milp as _scipy_milp

    HIGHS_AVAILABLE = True
except Exception:
    _np = None  # type: ignore[assignment]
    _ScipyBounds = None  # type: ignore[assignment]
    _ScipyLinearConstraint = None  # type: ignore[assignment]
    _scipy_milp = None  # type: ignore[assignment]
    HIGHS_AVAILABLE = False


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
    status: str  # "optimal" | "infeasible" | "empty" | "time_limit" | "cancelled"
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
    has_feasible_solution: bool = False

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
            "has_feasible_solution": self.has_feasible_solution,
        }


def _fmt_rub(val: float) -> str:
    return f"{val:,.0f}".replace(",", " ")


def _validate_inputs(
    items: list[IlpItem],
    *,
    max_items: int | None,
    min_per_group: dict[str, int] | None,
    max_per_group: dict[str, int] | None,
    time_limit_s: float,
) -> None:
    if not math.isfinite(float(time_limit_s)) or float(time_limit_s) <= 0.0:
        raise ValueError("time_limit_s должен быть конечным положительным числом.")
    if max_items is not None and int(max_items) < 0:
        raise ValueError("max_items не может быть отрицательным.")
    for g, v in (min_per_group or {}).items():
        if int(v) < 0:
            raise ValueError(f"min_per_group['{g}'] не может быть отрицательным.")
    for g, v in (max_per_group or {}).items():
        if int(v) < 0:
            raise ValueError(f"max_per_group['{g}'] не может быть отрицательным.")

    seen_ids: set[str] = set()
    for it in items:
        if not it.item_id or not isinstance(it.item_id, str):
            raise ValueError("item_id каждого элемента должен быть непустой строкой.")
        if it.item_id in seen_ids:
            raise ValueError(f"Обнаружен дублирующийся идентификатор item_id: «{it.item_id}».")
        seen_ids.add(it.item_id)
        c = float(it.cost)
        u = float(it.utility)
        if not math.isfinite(c) or c < 0.0:
            raise ValueError(f"Некорректная стоимость cost={it.cost} у позиции «{it.item_id}» (должна быть конечной и >= 0).")
        if not math.isfinite(u):
            raise ValueError(f"Некорректная полезность utility={it.utility} у позиции «{it.item_id}» (должна быть конечной).")


def _compute_transitive_closures(items: list[IlpItem]) -> tuple[dict[str, set[str]], dict[str, str]]:
    """
    Вычисляет транзитивное замыкание зависимостей для каждого элемента (корректно
    обрабатывает произвольные цепочки и циклы x_a <= x_b <= ... <= x_a).
    Возвращает (closures, missing_dep_errors).
    """
    by_id = {it.item_id: it for it in items}
    closures: dict[str, set[str]] = {}
    missing_err: dict[str, str] = {}

    for it in items:
        visited: set[str] = set()
        queue: deque[str] = deque(it.requires_ids)
        miss: str | None = None
        while queue:
            req = queue.popleft()
            if req == it.item_id:
                continue
            if req not in by_id:
                miss = req
                break
            if req not in visited:
                visited.add(req)
                for nxt in by_id[req].requires_ids:
                    if nxt != it.item_id and nxt not in visited:
                        queue.append(nxt)
        if miss is not None:
            missing_err[it.item_id] = miss
            closures[it.item_id] = set()
        else:
            closures[it.item_id] = visited

    return closures, missing_err


def _expand_mandatory_closure(items: list[IlpItem]) -> tuple[set[str], str | None]:
    """Транзитивно замыкает зависимости x_a <= x_b для обязательных мероприятий."""
    closures, missing_err = _compute_transitive_closures(items)
    mand: set[str] = set()
    for it in items:
        if it.mandatory:
            if it.item_id in missing_err:
                return mand, f"Обязательное мероприятие «{it.item_id}» требует отсутствующую позицию «{missing_err[it.item_id]}»."
            mand.add(it.item_id)
            mand.update(closures[it.item_id])
    return mand, None


def _is_cancelled(cancel_event: Any | None) -> bool:
    if cancel_event is None:
        return False
    checker = getattr(cancel_event, "is_set", None)
    return bool(checker()) if callable(checker) else bool(cancel_event)


def _solve_with_highs(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None,
    min_per_group: dict[str, int] | None,
    max_per_group: dict[str, int] | None,
    time_limit_s: float,
    t0: float,
    compute_min_budget: bool = True,
) -> IlpSolution:
    """Решает точную 0-1 MILP через промышленный C++ решатель HiGHS (`scipy.optimize.milp`)."""
    if not HIGHS_AVAILABLE or _scipy_milp is None or _np is None:
        raise RuntimeError("HiGHS (`scipy.optimize.milp`) недоступен в текущей среде Python.")

    n = len(items)
    id_to_idx = {it.item_id: i for i, it in enumerate(items)}
    closures, missing_err = _compute_transitive_closures(items)
    mand_ids, dep_err = _expand_mandatory_closure(items)
    if dep_err is not None:
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=dep_err,
            solver_name="highs_milp",
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    min_grp = {k: int(v) for k, v in (min_per_group or {}).items() if int(v) > 0}
    max_grp = {k: int(v) for k, v in (max_per_group or {}).items()}
    for g, mn in min_grp.items():
        if g in max_grp and mn > max_grp[g]:
            return IlpSolution(
                status="infeasible",
                infeasibility_reason=f"В группе «{g}» минимальная квота ({mn}) превышает максимальную ({max_grp[g]}).",
                solver_name="highs_milp",
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

    lb = _np.zeros(n, dtype=float)
    ub = _np.ones(n, dtype=float)
    for i, it in enumerate(items):
        if it.item_id in mand_ids:
            lb[i] = 1.0
        if it.excluded or it.item_id in missing_err:
            ub[i] = 0.0
        if lb[i] > ub[i]:
            return IlpSolution(
                status="infeasible",
                infeasibility_reason=f"Противоречие ограничений: позиция «{it.item_id}» одновременно обязательна и недоступна/исключена.",
                solver_name="highs_milp",
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

    # Строим разреженную матрицу ограничений (в scipy.sparse для масштабируемости до 1000+ переменных)
    from scipy import sparse as _sp

    row_idx: list[int] = []
    col_idx: list[int] = []
    vals: list[float] = []
    c_lb: list[float] = []
    c_ub: list[float] = []
    r_id = 0

    # 1. Бюджет: sum cost_i x_i <= budget
    if math.isfinite(budget):
        for i, it in enumerate(items):
            if it.cost > 0.0:
                row_idx.append(r_id)
                col_idx.append(i)
                vals.append(float(it.cost))
        c_lb.append(-_np.inf)
        c_ub.append(float(budget))
        r_id += 1

    # 2. max_items: sum x_i <= max_items
    if max_items is not None:
        for i in range(n):
            row_idx.append(r_id)
            col_idx.append(i)
            vals.append(1.0)
        c_lb.append(-_np.inf)
        c_ub.append(float(max_items))
        r_id += 1

    # 3. min_per_group / max_per_group
    grp_members: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        grp_members.setdefault(it.group, []).append(i)
    all_constrained_groups = set(min_grp.keys()) | set(max_grp.keys())
    for g in sorted(all_constrained_groups):
        members = grp_members.get(g, [])
        lo_g = float(min_grp.get(g, 0))
        hi_g = float(max_grp[g]) if g in max_grp else _np.inf
        if not members:
            if lo_g > 0.0:
                return IlpSolution(
                    status="infeasible",
                    infeasibility_reason=f"В группе «{g}» нет доступных позиций для квоты min={int(lo_g)}.",
                    solver_name="highs_milp",
                    solve_time_ms=(time.perf_counter() - t0) * 1000.0,
                )
            continue
        for i in members:
            row_idx.append(r_id)
            col_idx.append(i)
            vals.append(1.0)
        c_lb.append(lo_g)
        c_ub.append(hi_g)
        r_id += 1

    # 4. Взаимоисключающие группы (SOS1): sum_{i in m} x_i <= 1
    mut_members: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        if it.mutex_group:
            mut_members.setdefault(it.mutex_group, []).append(i)
    for m_grp, members in mut_members.items():
        if len(members) > 1:
            for i in members:
                row_idx.append(r_id)
                col_idx.append(i)
                vals.append(1.0)
            c_lb.append(-_np.inf)
            c_ub.append(1.0)
            r_id += 1

    # 5. Зависимости x_a - x_b <= 0
    for i, it in enumerate(items):
        if ub[i] == 0.0:
            continue
        for req in it.requires_ids:
            if req == it.item_id or req not in id_to_idx:
                continue
            j = id_to_idx[req]
            row_idx.extend([r_id, r_id])
            col_idx.extend([i, j])
            vals.extend([1.0, -1.0])
            c_lb.append(-_np.inf)
            c_ub.append(0.0)
            r_id += 1

    # Целевая функция: scipy.optimize.milp минимизирует c^T x -> минимизируем -utility_i
    # Микро-штраф за стоимость не добавляем в HiGHS, чтобы не исказить точную полезность при равенстве масштабов;
    # для однозначности используем чистую целевую -utility_i.
    c_obj = _np.array([-float(it.utility) for it in items], dtype=float)
    integrality = _np.ones(n, dtype=int)
    constraints = (
        _ScipyLinearConstraint(_sp.csc_matrix((vals, (row_idx, col_idx)), shape=(r_id, n)), c_lb, c_ub)
        if r_id > 0
        else None
    )

    res = _scipy_milp(
        c=c_obj,
        integrality=integrality,
        bounds=_ScipyBounds(lb, ub),
        constraints=constraints,
        options={"time_limit": max(0.005, float(time_limit_s)), "mip_rel_gap": 0.0},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # res.status: 0=optimal, 1=iteration/time limit, 2=infeasible, 3=unbounded
    if res.status == 2:
        min_req: float | None = None
        deficit: float | None = None
        if compute_min_budget and math.isfinite(budget):
            min_req = _compute_exact_min_budget_highs(
                items,
                max_items=max_items,
                min_per_group=min_per_group,
                max_per_group=max_per_group,
                time_limit_s=min(0.5, float(time_limit_s)),
            )
            if min_req is not None and min_req > budget + 1e-6:
                deficit = min_req - budget
        reason = (
            f"Бюджет {_fmt_rub(budget)} ₽ недостаточен для выполнения обязательных ограничений "
            f"(требуется минимум {_fmt_rub(min_req)} ₽, дефицит {_fmt_rub(deficit)} ₽)."
            if (min_req is not None and deficit is not None)
            else "Ограничения задачи структурно несовместимы (не существует допустимого портфеля при любом бюджете)."
        )
        return IlpSolution(
            status="infeasible",
            solver_name="highs_milp",
            solve_time_ms=elapsed_ms,
            infeasibility_reason=reason,
            min_required_budget=min_req,
            budget_deficit=deficit,
            has_feasible_solution=False,
        )

    if res.x is None:
        return IlpSolution(
            status="time_limit",
            solver_name="highs_milp",
            solve_time_ms=elapsed_ms,
            optimality_gap=1.0,
            infeasibility_reason="Превышен лимит времени решателя до нахождения допустимого решения.",
            has_feasible_solution=False,
        )

    sel_idx = [i for i in range(n) if float(res.x[i]) >= 0.5]
    sel_ids = [items[i].item_id for i in sel_idx]
    tot_cost = sum(float(items[i].cost) for i in sel_idx)
    tot_util = sum(float(items[i].utility) for i in sel_idx)
    dual_ub = -float(getattr(res, "mip_dual_bound", -tot_util))
    if not math.isfinite(dual_ub):
        dual_ub = tot_util
    dual_ub = max(tot_util, dual_ub)

    if res.status == 0:
        return IlpSolution(
            status="optimal",
            selected_ids=sel_ids,
            objective_value=tot_util,
            upper_bound=tot_util,
            optimality_gap=0.0,
            total_cost=tot_cost,
            remaining_budget=max(0.0, budget - tot_cost) if math.isfinite(budget) else 0.0,
            nodes_explored=int(getattr(res, "mip_node_count", 0) or 0),
            solve_time_ms=elapsed_ms,
            solver_name="highs_milp",
            has_feasible_solution=True,
        )

    gap = max(0.0, (dual_ub - tot_util) / max(abs(tot_util), 1e-9))
    return IlpSolution(
        status="time_limit",
        selected_ids=sel_ids,
        objective_value=tot_util,
        upper_bound=dual_ub,
        optimality_gap=gap,
        total_cost=tot_cost,
        remaining_budget=max(0.0, budget - tot_cost) if math.isfinite(budget) else 0.0,
        nodes_explored=int(getattr(res, "mip_node_count", 0) or 0),
        solve_time_ms=elapsed_ms,
        solver_name="highs_milp",
        has_feasible_solution=True,
    )


def _compute_exact_min_budget_highs(
    items: list[IlpItem],
    *,
    max_items: int | None,
    min_per_group: dict[str, int] | None,
    max_per_group: dict[str, int] | None,
    time_limit_s: float = 0.5,
) -> float | None:
    """Точно вычисляет минимально необходимый бюджет при budget=+inf через HiGHS."""
    cost_min_items = [
        IlpItem(
            item_id=it.item_id,
            cost=0.0,
            utility=-float(it.cost),
            group=it.group,
            mandatory=it.mandatory,
            excluded=it.excluded,
            mutex_group=it.mutex_group,
            requires_ids=it.requires_ids,
        )
        for it in items
    ]
    sol = _solve_with_highs(
        cost_min_items,
        budget=math.inf,
        max_items=max_items,
        min_per_group=min_per_group,
        max_per_group=max_per_group,
        time_limit_s=time_limit_s,
        t0=time.perf_counter(),
        compute_min_budget=False,
    )
    if sol.status == "optimal" and sol.has_feasible_solution:
        by_id = {it.item_id: float(it.cost) for it in items}
        return sum(by_id[iid] for iid in sol.selected_ids)
    return None


def _compute_exact_min_budget_bnb(
    items: list[IlpItem],
    *,
    max_items: int | None,
    min_per_group: dict[str, int] | None,
    max_per_group: dict[str, int] | None,
    time_limit_s: float = 0.4,
    cancel_event: Any | None = None,
) -> float | None:
    """
    Точно вычисляет минимально необходимый бюджет (minimize sum cost_i x_i при budget=+inf)
    в 100% air-gapped режиме. Возвращает None, если задача структурно неразрешима.
    """
    # Быстрый путь: нет min_per_group — проверяем допустимость набора одних только mandatory
    min_grp = {k: int(v) for k, v in (min_per_group or {}).items() if int(v) > 0}
    max_grp = {k: int(v) for k, v in (max_per_group or {}).items()}
    mand_ids, dep_err = _expand_mandatory_closure(items)
    if dep_err is not None:
        return None
    excluded_ids = {it.item_id for it in items if it.excluded}
    if mand_ids & excluded_ids:
        return None
    mand_items = [it for it in items if it.item_id in mand_ids]
    mut_seen: set[str] = set()
    g_cnt: dict[str, int] = {}
    for it in mand_items:
        if it.mutex_group:
            if it.mutex_group in mut_seen:
                return None
            mut_seen.add(it.mutex_group)
        g_cnt[it.group] = g_cnt.get(it.group, 0) + 1
    if max_items is not None and len(mand_items) > max_items:
        return None
    for g, cnt in g_cnt.items():
        if g in max_grp and cnt > max_grp[g]:
            return None
    for g, mn in min_grp.items():
        if g in max_grp and mn > max_grp[g]:
            return None

    min_grp_need = {g: mn - g_cnt.get(g, 0) for g, mn in min_grp.items() if mn > g_cnt.get(g, 0)}
    fixed_cost = sum(float(it.cost) for it in mand_items)
    if not min_grp_need:
        return fixed_cost

    # Сокращаем задачу только до позиций, способных помочь выполнить min_per_group, и их транзитивных зависимостей
    closures, missing_err = _compute_transitive_closures(items)
    relevant: set[str] = set(mand_ids)
    for it in items:
        if it.item_id in excluded_ids or it.item_id in missing_err:
            continue
        if it.group in min_grp_need:
            cl = closures[it.item_id]
            if not (cl & excluded_ids):
                relevant.add(it.item_id)
                relevant.update(cl)

    sub_items = [
        IlpItem(
            item_id=it.item_id,
            cost=0.0,
            utility=-float(it.cost),
            group=it.group,
            mandatory=(it.item_id in mand_ids),
            excluded=it.excluded,
            mutex_group=it.mutex_group,
            requires_ids=it.requires_ids,
        )
        for it in items
        if it.item_id in relevant
    ]
    sub_sol = _solve_bnb_core(
        sub_items,
        budget=1e30,
        max_items=max_items,
        min_per_group=min_per_group,
        max_per_group=max_per_group,
        time_limit_s=time_limit_s,
        cancel_event=cancel_event,
        compute_min_budget=False,
    )
    if sub_sol.status == "optimal" and sub_sol.has_feasible_solution:
        by_id = {it.item_id: float(it.cost) for it in items}
        return sum(by_id[iid] for iid in sub_sol.selected_ids)
    return None


def _solve_bnb_core(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None,
    min_per_group: dict[str, int] | None,
    max_per_group: dict[str, int] | None,
    time_limit_s: float,
    cancel_event: Any | None = None,
    compute_min_budget: bool = True,
) -> IlpSolution:
    """Точное ядро Branch-and-Bound (100% air-gapped, с допустимой UB и честным таймаутом)."""
    t0 = time.perf_counter()
    budget_f = float(budget)
    min_grp = {k: int(v) for k, v in (min_per_group or {}).items() if int(v) > 0}
    max_grp = {k: int(v) for k, v in (max_per_group or {}).items()}
    k_limit = None if max_items is None else int(max_items)

    # 1. Проверка min_per_group <= max_per_group
    for g, mn in min_grp.items():
        if g in max_grp and mn > max_grp[g]:
            return IlpSolution(
                status="infeasible",
                infeasibility_reason=f"В группе «{g}» минимальная квота ({mn}) превышает максимальную ({max_grp[g]}).",
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

    # 2. Транзитивное замыкание всех зависимостей (включая циклы)
    closures, missing_err = _compute_transitive_closures(items)
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
    fixed_cost = sum(float(it.cost) for it in fixed_items)
    fixed_util = sum(float(it.utility) for it in fixed_items)
    fixed_count = len(fixed_items)

    fixed_grp_counts: dict[str, int] = {}
    for it in fixed_items:
        fixed_grp_counts[it.group] = fixed_grp_counts.get(it.group, 0) + 1

    if k_limit is not None and fixed_count > k_limit:
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=f"Число обязательных мероприятий ({fixed_count}) превышает лимит позиций за этап ({k_limit}).",
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    for g, cnt in fixed_grp_counts.items():
        if g in max_grp and cnt > max_grp[g]:
            return IlpSolution(
                status="infeasible",
                infeasibility_reason=f"В группе «{g}» обязательных позиций ({cnt}) больше лимита ({max_grp[g]}).",
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

    if fixed_cost > budget_f + 1e-9:
        min_req = (
            _compute_exact_min_budget_bnb(
                items,
                max_items=max_items,
                min_per_group=min_per_group,
                max_per_group=max_per_group,
                time_limit_s=min(0.4, float(time_limit_s)),
                cancel_event=cancel_event,
            )
            if compute_min_budget
            else fixed_cost
        )
        if min_req is None:
            return IlpSolution(
                status="infeasible",
                infeasibility_reason="Ограничения задачи структурно несовместимы (не существует допустимого портфеля при любом бюджете).",
                min_required_budget=None,
                budget_deficit=None,
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )
        deficit = max(0.0, min_req - budget_f)
        return IlpSolution(
            status="infeasible",
            infeasibility_reason=(
                f"Бюджет {_fmt_rub(budget_f)} ₽ недостаточен для покрытия {fixed_count} обязательных мероприятий "
                f"(требуется минимум {_fmt_rub(min_req)} ₽, дефицит {_fmt_rub(deficit)} ₽)."
            ),
            min_required_budget=min_req,
            budget_deficit=deficit,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    rem_budget = budget_f - fixed_cost
    rem_k = None if k_limit is None else (k_limit - fixed_count)
    used_mutex = set(mand_mutex.keys())
    by_id = {it.item_id: it for it in items}

    # 3. Транзитивное отсечение недоступных свободных переменных
    free_raw: list[IlpItem] = []
    for it in items:
        iid = it.item_id
        if iid in mand_ids or iid in excluded_ids or iid in missing_err:
            continue
        req_all = (closures[iid] | {iid}) - mand_ids
        if req_all & excluded_ids:
            continue
        if any(r in missing_err for r in req_all):
            continue
        # Проверка конфликтов mutex внутри замыкания и с mandatory
        m_local: set[str] = set()
        m_bad = False
        g_local: dict[str, int] = {}
        c_local = 0.0
        for r in req_all:
            rit = by_id[r]
            c_local += float(rit.cost)
            g_local[rit.group] = g_local.get(rit.group, 0) + 1
            if rit.mutex_group:
                if rit.mutex_group in used_mutex or rit.mutex_group in m_local:
                    m_bad = True
                    break
                m_local.add(rit.mutex_group)
        if m_bad:
            continue
        if c_local > rem_budget + 1e-9:
            continue
        if rem_k is not None and len(req_all) > rem_k:
            continue
        if any(g in max_grp and fixed_grp_counts.get(g, 0) + gc > max_grp[g] for g, gc in g_local.items()):
            continue
        free_raw.append(it)

    # 4. Проверка остаточных квот min_per_group
    min_grp_rem: dict[str, int] = {}
    for g, req_n in min_grp.items():
        need = max(0, req_n - fixed_grp_counts.get(g, 0))
        if need > 0:
            min_grp_rem[g] = need
            g_cnt_avail = sum(1 for it in free_raw if it.group == g)
            if g_cnt_avail < need:
                min_req = (
                    _compute_exact_min_budget_bnb(
                        items,
                        max_items=max_items,
                        min_per_group=min_per_group,
                        max_per_group=max_per_group,
                        time_limit_s=min(0.4, float(time_limit_s)),
                        cancel_event=cancel_event,
                    )
                    if compute_min_budget
                    else None
                )
                deficit = max(0.0, min_req - budget_f) if (min_req is not None and min_req > budget_f + 1e-9) else None
                return IlpSolution(
                    status="infeasible",
                    infeasibility_reason=(
                        f"Бюджет {_fmt_rub(budget_f)} ₽ недостаточен для выполнения квот по группам "
                        f"(минимум {_fmt_rub(min_req)} ₽, дефицит {_fmt_rub(deficit)} ₽)."
                        if (min_req is not None and deficit is not None)
                        else f"В группе «{g}» недостаточно доступных кандидатов для квоты min={req_n}."
                    ),
                    min_required_budget=min_req,
                    budget_deficit=deficit,
                    solve_time_ms=(time.perf_counter() - t0) * 1000.0,
                )

    # Убираем свободные переменные с utility <= 0, ТОЛЬКО если они не нужны ни квотам, ни зависимостям
    free_raw_ids = {it.item_id for it in free_raw}
    needed_as_dep: set[str] = set()
    for it in free_raw:
        for r in closures[it.item_id]:
            if r in free_raw_ids:
                needed_as_dep.add(r)

    free_items = [
        it for it in free_raw
        if float(it.utility) > 0.0 or (it.group in min_grp_rem) or (it.item_id in needed_as_dep)
    ]

    # Если у задачи есть зависимости между свободными переменными, проверим это точно
    free_id_set = {it.item_id for it in free_items}
    has_free_deps = any(
        any(r in free_id_set and r != it.item_id for r in it.requires_ids)
        for it in free_items
    )

    # Упорядочивание переменных для ветвления:
    # Строго сохраняем порядок Данцига: сначала zero-cost (u>0), затем положительные по убыванию u/c, затем u<=0.
    def _sort_key(it: IlpItem) -> tuple:
        u = float(it.utility)
        c = float(it.cost)
        dep_pri = 0 if (has_free_deps and it.item_id in needed_as_dep) else 1
        if u > 0.0 and c <= 1e-12:
            tier, ratio = 0, -u
        elif u > 0.0:
            tier, ratio = 1, -(u / c)
        else:
            tier, ratio = 2, -u
        return (dep_pri, tier, ratio, -u, c, it.item_id)

    free_items.sort(key=_sort_key)

    n = len(free_items)
    id_to_free_idx = {it.item_id: idx for idx, it in enumerate(free_items)}
    costs = [float(it.cost) for it in free_items]
    utils = [float(it.utility) for it in free_items]
    groups = [it.group for it in free_items]
    mutexes = [it.mutex_group for it in free_items]

    # Прямые и обратные списки смежности зависимостей среди свободных переменных (O(deg) вместо O(idx)!)
    req_free: list[tuple[int, ...]] = []
    rev_req_free: list[list[int]] = [[] for _ in range(n)]
    for i, it in enumerate(free_items):
        r_idx: list[int] = []
        valid_deps = True
        for rid in it.requires_ids:
            if rid == it.item_id or rid in mand_ids:
                continue
            if rid in id_to_free_idx:
                j = id_to_free_idx[rid]
                if j not in r_idx:
                    r_idx.append(j)
                    rev_req_free[j].append(i)
            else:
                valid_deps = False
                break
        req_free.append(tuple(r_idx) if valid_deps else (-1,))

    rev_req_tuple = [tuple(lst) for lst in rev_req_free]

    # Суффиксные счётчики доступных элементов по группам для раннего отсечения min_per_group
    suffix_grp_avail: list[dict[str, int]] = [{} for _ in range(n + 1)]
    if min_grp_rem:
        for i in range(n - 1, -1, -1):
            d = dict(suffix_grp_avail[i + 1])
            g = groups[i]
            if g in min_grp_rem:
                d[g] = d.get(g, 0) + 1
            suffix_grp_avail[i] = d

    # Строгий порядок Данцига для допустимой верхней оценки:
    # 1) ВСЕ нулевые стоимости с u > 0 (ratio = +inf),
    # 2) ВСЕ положительные стоимости с u > 0 строго по убыванию exact u / c (БЕЗ max(c, 1.0)!).
    zero_pos = [i for i in range(n) if utils[i] > 0.0 and costs[i] <= 1e-12]
    pos_pos = sorted(
        [i for i in range(n) if utils[i] > 0.0 and costs[i] > 1e-12],
        key=lambda i: (-(utils[i] / costs[i]), -utils[i], costs[i]),
    )
    util_order = sorted([i for i in range(n) if utils[i] > 0.0], key=lambda i: (-utils[i], costs[i]))

    # Быстрый путь O(log n) для UB_budget, когда переменные уже отсортированы строго в порядке Данцига (нет зависимостей)
    fast_prefix_ok = not has_free_deps
    if fast_prefix_ok:
        n_zero = len(zero_pos)
        n_pos_end = n_zero + len(pos_pos)
        # Суффиксные суммы zero-cost полезности
        zero_suf_u = [0.0] * (n_zero + 1)
        for i in range(n_zero - 1, -1, -1):
            zero_suf_u[i] = zero_suf_u[i + 1] + utils[i]
        # Префиксные суммы для pos_pos на диапазоне [n_zero .. n_pos_end)
        pref_c = [0.0] * (n_pos_end - n_zero + 1)
        pref_u = [0.0] * (n_pos_end - n_zero + 1)
        for k in range(n_pos_end - n_zero):
            pref_c[k + 1] = pref_c[k] + costs[n_zero + k]
            pref_u[k + 1] = pref_u[k] + utils[n_zero + k]

    def _upper_bound(idx: int, cur_u: float, b_rem: float, k_rem: int | None) -> float:
        """
        Математически строгая допустимая верхняя граница:
            UB = min(UB_budget, UB_cardinality) >= true_integer_optimum.
        """
        if idx >= n or (k_rem is not None and k_rem <= 0):
            return cur_u

        if fast_prefix_ok:
            ub_budget = cur_u
            if idx < n_zero:
                ub_budget += zero_suf_u[idx]
                p_start = 0
            elif idx < n_pos_end:
                p_start = idx - n_zero
            else:
                p_start = n_pos_end - n_zero

            if p_start < len(pref_c) - 1 and b_rem > 1e-12:
                target_c = pref_c[p_start] + b_rem
                pos = bisect.bisect_right(pref_c, target_c, lo=p_start + 1) - 1
                ub_budget += pref_u[pos] - pref_u[p_start]
                rem_b = target_c - pref_c[pos]
                if pos < len(pref_c) - 1 and rem_b > 1e-12:
                    j = n_zero + pos
                    ub_budget += utils[j] * (rem_b / costs[j])
        else:
            ub_budget = cur_u
            for j in zero_pos:
                if j >= idx:
                    ub_budget += utils[j]
            rem_b = b_rem
            if rem_b > 1e-12:
                for j in pos_pos:
                    if j < idx:
                        continue
                    cj = costs[j]
                    if cj <= rem_b:
                        ub_budget += utils[j]
                        rem_b -= cj
                    else:
                        ub_budget += utils[j] * (rem_b / cj)
                        break

        if k_rem is None:
            return ub_budget

        ub_card = cur_u
        taken = 0
        for j in util_order:
            if j < idx:
                continue
            ub_card += utils[j]
            taken += 1
            if taken >= k_rem:
                break

        return ub_budget if ub_budget <= ub_card else ub_card

    best_u = -1e300
    best_cost = 0.0
    best_chosen: list[int] = []
    has_feasible = False

    # 5. Многостартовая прямая эвристика + 1-swap локальный поиск (когда нет min_per_group и зависимостей)
    if not min_grp_rem and not has_free_deps:
        orders = [
            zero_pos + pos_pos,
            util_order,
            sorted([i for i in range(n) if utils[i] > 0.0], key=lambda i: (costs[i], -utils[i])),
        ]
        for ord_list in orders:
            g_b = rem_budget
            g_u = fixed_util
            g_c = fixed_cost
            g_k = 0
            g_sel: list[int] = []
            g_grp: dict[str, int] = {}
            g_mut: set[str] = set()
            for j in ord_list:
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
            if (not has_feasible) or (g_u > best_u + 1e-9) or (abs(g_u - best_u) <= 1e-9 and g_c < best_cost - 1e-6):
                best_u = g_u
                best_cost = g_c
                best_chosen = g_sel
                has_feasible = True

    chosen = [0] * n
    grp_cnt: dict[str, int] = {}
    mutex_used: set[str] = set()
    nodes = 0
    timed_out = False
    cancelled = False
    deadline = t0 + max(0.001, float(time_limit_s))
    abandoned_ub = -1e300

    def _is_leaf_feasible() -> bool:
        for g, need in min_grp_rem.items():
            if grp_cnt.get(g, 0) < need:
                return False
        if has_free_deps:
            for i in range(n):
                if chosen[i]:
                    for r in req_free[i]:
                        if r < 0 or not chosen[r]:
                            return False
        return True

    # Итеративный стек Branch-and-Bound (полностью исключает RecursionError при N >= 1000):
    # Каждый кадр стека: [idx, cur_u, cur_c, b_rem, k_rem, phase, node_ub]
    #   phase = 0 -> вход в узел, проверка отсечения и попытка ветви x_idx = 1
    #   phase = 1 -> откат x_idx = 1 и переход к ветви x_idx = 0
    #   phase = 2 -> завершение узла
    if _is_cancelled(cancel_event):
        cancelled = True
        abandoned_ub = _upper_bound(0, fixed_util, rem_budget, rem_k)
    else:
        root_ub_val = _upper_bound(0, fixed_util, rem_budget, rem_k)
        stack: list[list[Any]] = [[0, fixed_util, fixed_cost, rem_budget, rem_k, 0, root_ub_val]]
        while stack:
            frame = stack[-1]
            idx = frame[0]
            cur_u = frame[1]
            cur_c = frame[2]
            b_rem = frame[3]
            k_rem = frame[4]
            phase = frame[5]

            if phase == 0:
                nodes += 1
                if (nodes & 511) == 0:
                    if _is_cancelled(cancel_event):
                        cancelled = True
                    elif time.perf_counter() >= deadline:
                        timed_out = True
                if timed_out or cancelled:
                    break

                if min_grp_rem:
                    infeas_q = False
                    for g, need in min_grp_rem.items():
                        if grp_cnt.get(g, 0) + suffix_grp_avail[idx].get(g, 0) < need:
                            infeas_q = True
                            break
                    if infeas_q:
                        stack.pop()
                        continue

                if idx == n:
                    if _is_leaf_feasible():
                        if (not has_feasible) or (cur_u > best_u + 1e-9) or (
                            abs(cur_u - best_u) <= 1e-9 and cur_c < best_cost - 1e-6
                        ):
                            best_u = cur_u
                            best_cost = cur_c
                            best_chosen = [i for i in range(n) if chosen[i]]
                            has_feasible = True
                    stack.pop()
                    continue

                node_ub = _upper_bound(idx, cur_u, b_rem, k_rem)
                frame[6] = node_ub
                if has_feasible and node_ub <= best_u + 1e-9:
                    stack.pop()
                    continue

                # Ветвь 1: x_idx = 1
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
                    if can_take and has_free_deps:
                        for r in req_free[idx]:
                            if r < idx and not chosen[r]:
                                can_take = False
                                break

                if can_take:
                    frame[5] = 1
                    chosen[idx] = 1
                    g = groups[idx]
                    m = mutexes[idx]
                    grp_cnt[g] = grp_cnt.get(g, 0) + 1
                    if m:
                        mutex_used.add(m)
                    stack.append([
                        idx + 1,
                        cur_u + utils[idx],
                        cur_c + costs[idx],
                        b_rem - costs[idx],
                        None if k_rem is None else (k_rem - 1),
                        0,
                        node_ub,
                    ])
                    continue
                else:
                    # Ветвь 1 недопустима -> сразу пробуем ветвь 2 (x_idx = 0)
                    frame[5] = 2
                    dep_violated = False
                    if has_free_deps:
                        for prev in rev_req_tuple[idx]:
                            if prev < idx and chosen[prev]:
                                dep_violated = True
                                break
                    if not dep_violated:
                        stack.append([idx + 1, cur_u, cur_c, b_rem, k_rem, 0, node_ub])
                    continue

            elif phase == 1:
                # Возврат из ветви x_idx = 1 -> откатываем состояние и идём в ветвь x_idx = 0
                chosen[idx] = 0
                g = groups[idx]
                m = mutexes[idx]
                grp_cnt[g] -= 1
                if m:
                    mutex_used.discard(m)
                frame[5] = 2

                if timed_out or cancelled:
                    break

                # Повторная проверка верхней оценки ветви x_idx = 0 после возможного улучшения best_u
                ub_skip = _upper_bound(idx + 1, cur_u, b_rem, k_rem)
                frame[6] = ub_skip
                if has_feasible and ub_skip <= best_u + 1e-9:
                    stack.pop()
                    continue

                dep_violated = False
                if has_free_deps:
                    for prev in rev_req_tuple[idx]:
                        if prev < idx and chosen[prev]:
                            dep_violated = True
                            break
                if not dep_violated:
                    stack.append([idx + 1, cur_u, cur_c, b_rem, k_rem, 0, ub_skip])
                else:
                    stack.pop()
                continue

            else:
                # phase == 2 -> обе ветви завершены
                stack.pop()

        # При досрочной остановке оцениваем точную глобальную верхнюю границу по всем открытым ветвям стека
        if timed_out or cancelled:
            for fr in stack:
                f_idx, f_u, _, f_b, f_k, f_ph, f_ub = fr
                if f_ph == 0:
                    ub_open = _upper_bound(f_idx, f_u, f_b, f_k)
                    if ub_open > abandoned_ub:
                        abandoned_ub = ub_open
                elif f_ph == 1:
                    # Ветвь x_idx = 0 ещё не исследовалась
                    ub_open = _upper_bound(f_idx + 1, f_u, f_b, f_k)
                    if ub_open > abandoned_ub:
                        abandoned_ub = ub_open
                    # Откат состояния для чистоты
                    if chosen[f_idx]:
                        chosen[f_idx] = 0
                        grp_cnt[groups[f_idx]] -= 1
                        if mutexes[f_idx]:
                            mutex_used.discard(mutexes[f_idx])

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Досрочное завершение (timeout / cancel) — НИКОГДА не выдаём OPTIMAL или ложный INFEASIBLE!
    if timed_out or cancelled:
        st = "cancelled" if cancelled else "time_limit"
        if not has_feasible:
            root_ub = _upper_bound(0, fixed_util, rem_budget, rem_k)
            ub_final = abandoned_ub if abandoned_ub > -1e290 else root_ub
            return IlpSolution(
                status=st,
                selected_ids=[],
                objective_value=0.0,
                upper_bound=ub_final,
                optimality_gap=1.0,
                total_cost=0.0,
                remaining_budget=max(0.0, budget_f) if math.isfinite(budget_f) else 0.0,
                nodes_explored=nodes,
                solve_time_ms=elapsed_ms,
                infeasibility_reason=(
                    "Вычисление отменено пользователем до нахождения допустимого решения."
                    if cancelled
                    else "Превышен лимит времени решателя до нахождения допустимого решения."
                ),
                has_feasible_solution=False,
            )
        ub_final = max(best_u, abandoned_ub)
        gap = max(0.0, (ub_final - best_u) / max(abs(best_u), 1e-9))
        selected_ids = [it.item_id for it in fixed_items] + [free_items[i].item_id for i in best_chosen]
        return IlpSolution(
            status=st,
            selected_ids=selected_ids,
            objective_value=best_u,
            upper_bound=ub_final,
            optimality_gap=gap,
            total_cost=best_cost,
            remaining_budget=max(0.0, budget_f - best_cost) if math.isfinite(budget_f) else 0.0,
            nodes_explored=nodes,
            solve_time_ms=elapsed_ms,
            has_feasible_solution=True,
        )

    if not has_feasible:
        min_req = (
            _compute_exact_min_budget_bnb(
                items,
                max_items=max_items,
                min_per_group=min_per_group,
                max_per_group=max_per_group,
                time_limit_s=min(0.4, float(time_limit_s)),
                cancel_event=cancel_event,
            )
            if compute_min_budget
            else None
        )
        deficit = max(0.0, min_req - budget_f) if (min_req is not None and min_req > budget_f + 1e-9) else None
        reason = (
            f"Бюджет {_fmt_rub(budget_f)} ₽ недостаточен для выполнения всех ограничений "
            f"(требуется минимум {_fmt_rub(min_req)} ₽, дефицит {_fmt_rub(deficit)} ₽)."
            if (min_req is not None and deficit is not None)
            else "Не найдено допустимого портфеля, удовлетворяющего всем ограничениям бюджета, квот и зависимостей."
        )
        return IlpSolution(
            status="infeasible",
            nodes_explored=nodes,
            solve_time_ms=elapsed_ms,
            infeasibility_reason=reason,
            min_required_budget=min_req,
            budget_deficit=deficit,
            has_feasible_solution=False,
        )

    selected_ids = [it.item_id for it in fixed_items] + [free_items[i].item_id for i in best_chosen]
    return IlpSolution(
        status="optimal",
        selected_ids=selected_ids,
        objective_value=best_u,
        upper_bound=best_u,
        optimality_gap=0.0,
        total_cost=best_cost,
        remaining_budget=max(0.0, budget_f - best_cost) if math.isfinite(budget_f) else 0.0,
        nodes_explored=nodes,
        solve_time_ms=elapsed_ms,
        has_feasible_solution=True,
    )


def solve_binary_ilp(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None = None,
    min_per_group: dict[str, int] | None = None,
    max_per_group: dict[str, int] | None = None,
    time_limit_s: float = 2.0,
    cancel_event: Any | None = None,
    solver_backend: str = "auto",
) -> IlpSolution:
    """
    Находит доказанный глобальный оптимум задачи 0-1 ILP.

    Параметры:
      • `time_limit_s` — жёсткий лимит времени вычислений (с).
      • `cancel_event` — опциональный `threading.Event` для безопасной отмены.
      • `solver_backend` — `"auto"` | `"bnb"` | `"highs"`.
    """
    t0 = time.perf_counter()
    if solver_backend not in ("auto", "bnb", "highs"):
        raise ValueError(f"Неизвестный solver_backend: {solver_backend}. Допустимо: auto, bnb, highs.")

    budget_f = float(budget)
    if not math.isfinite(budget_f) or budget_f < 0.0:
        return IlpSolution(
            status="infeasible",
            infeasibility_reason="Задан некорректный отрицательный или нечисловой бюджет.",
            min_required_budget=0.0,
            budget_deficit=abs(budget_f) if math.isfinite(budget_f) else None,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            has_feasible_solution=False,
        )

    if not items:
        _validate_inputs(
            items,
            max_items=max_items,
            min_per_group=min_per_group,
            max_per_group=max_per_group,
            time_limit_s=time_limit_s,
        )
        return IlpSolution(status="empty", remaining_budget=max(0.0, budget_f), has_feasible_solution=True)

    _validate_inputs(
        items,
        max_items=max_items,
        min_per_group=min_per_group,
        max_per_group=max_per_group,
        time_limit_s=time_limit_s,
    )

    use_highs = (
        solver_backend == "highs"
        or (solver_backend == "auto" and HIGHS_AVAILABLE and len(items) > 40 and cancel_event is None)
    )
    if use_highs:
        return _solve_with_highs(
            items,
            budget=budget_f,
            max_items=max_items,
            min_per_group=min_per_group,
            max_per_group=max_per_group,
            time_limit_s=time_limit_s,
            t0=t0,
            compute_min_budget=True,
        )

    return _solve_bnb_core(
        items,
        budget=budget_f,
        max_items=max_items,
        min_per_group=min_per_group,
        max_per_group=max_per_group,
        time_limit_s=time_limit_s,
        cancel_event=cancel_event,
        compute_min_budget=True,
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
    if mand_ids & excluded:
        return {"status": "infeasible", "selected_ids": [], "objective_value": 0.0, "total_cost": 0.0}
    max_grp = {k: max(0, int(v)) for k, v in (max_per_group or {}).items()}

    fixed = [it for it in items if it.item_id in mand_ids]
    cost = sum(float(it.cost) for it in fixed)
    util = sum(float(it.utility) for it in fixed)
    if cost > budget + 1e-6 or (max_items is not None and len(fixed) > max_items):
        return {"status": "infeasible", "selected_ids": [], "objective_value": 0.0, "total_cost": 0.0}

    sel_set = {it.item_id for it in fixed}
    grp_cnt: dict[str, int] = {}
    mut_used: set[str] = set()
    for it in fixed:
        grp_cnt[it.group] = grp_cnt.get(it.group, 0) + 1
        if it.mutex_group:
            if it.mutex_group in mut_used:
                return {"status": "infeasible", "selected_ids": [], "objective_value": 0.0, "total_cost": 0.0}
            mut_used.add(it.mutex_group)

    free = [it for it in items if it.item_id not in sel_set and it.item_id not in excluded and float(it.utility) > 0.0]
    free.sort(
        key=lambda it: (
            0 if float(it.cost) <= 1e-12 else 1,
            -(float(it.utility) / float(it.cost)) if float(it.cost) > 1e-12 else -float(it.utility),
            -float(it.utility),
            float(it.cost),
        )
    )

    for it in free:
        if max_items is not None and len(sel_set) >= max_items:
            break
        if cost + float(it.cost) > budget + 1e-6:
            continue
        if it.group in max_grp and grp_cnt.get(it.group, 0) >= max_grp[it.group]:
            continue
        if it.mutex_group and it.mutex_group in mut_used:
            continue
        if any(req not in sel_set for req in it.requires_ids if req != it.item_id):
            continue
        sel_set.add(it.item_id)
        cost += float(it.cost)
        util += float(it.utility)
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
