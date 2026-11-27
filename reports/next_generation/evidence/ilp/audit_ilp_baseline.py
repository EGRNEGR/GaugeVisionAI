"""
Независимый аудит исходного решателя `app/ilp_solver.py` против точного полного перебора (2^N)
на 1200 воспроизводимых случайных малых задачах + матрице граничных случаев.
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.ilp_solver import IlpItem, solve_binary_ilp  # noqa: E402


def solve_bruteforce_exact(
    items: list[IlpItem],
    *,
    budget: float,
    max_items: int | None = None,
    min_per_group: dict[str, int] | None = None,
    max_per_group: dict[str, int] | None = None,
) -> dict:
    """Эталонный оракул полного перебора 2^N с проверкой всех ограничений и точного min_required_budget."""
    n = len(items)
    id_to_idx = {it.item_id: i for i, it in enumerate(items)}
    min_g = {k: int(v) for k, v in (min_per_group or {}).items() if int(v) > 0}
    max_g = {k: int(v) for k, v in (max_per_group or {}).items()}

    # Проверка базовой корректности ссылок зависимостей
    valid_dep_idx: list[list[int] | None] = []
    for it in items:
        reqs = []
        ok = True
        for r in it.requires_ids:
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
        for g, mn in min_g.items():
            if gcnt.get(g, 0) < mn:
                ok = False
                break
        if not ok:
            continue
        for g, mx in max_g.items():
            if gcnt.get(g, 0) > mx:
                ok = False
                break
        if not ok:
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


def gen_random_instance(rng: random.Random, idx: int) -> tuple[list[IlpItem], dict]:
    n = rng.randint(5, 11)
    groups = ["G1", "G2", "G3"]
    # Режимы генерации: 0-обычный, 1-нулевые/дробные стоимости, 2-отрицательные полезности, 3-циклы/цепочки
    mode = idx % 4
    items: list[IlpItem] = []
    ids = [f"it_{i}" for i in range(n)]

    for i in range(n):
        if mode == 1:
            cost = rng.choice([0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0])
            util = round(rng.uniform(-5.0, 30.0), 3)
        elif mode == 2:
            cost = round(rng.uniform(0.0, 100.0), 2)
            util = round(rng.uniform(-25.0, 40.0), 3)
        else:
            cost = round(rng.uniform(10.0, 150.0), 2)
            util = round(rng.uniform(1.0, 120.0), 3)

        mand = rng.random() < 0.14
        excl = (not mand) and (rng.random() < 0.12)
        if rng.random() < 0.02:
            excl = True  # умышленный конфликт mandatory + excluded
        mut = rng.choice(["M1", "M2"]) if rng.random() < 0.25 else None
        reqs: list[str] = []
        if rng.random() < 0.30:
            if mode == 3:
                # допускаем произвольные зависимости, включая возможные циклы
                cand = [ids[j] for j in range(n) if j != i]
            else:
                cand = [ids[j] for j in range(i)]
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
    budget = round(total_c * rng.uniform(0.15, 0.85), 2)
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


def main() -> None:
    rng = random.Random(20261127)
    total = 1200
    exact_matches = 0
    mismatches: list[dict] = []
    min_budget_mismatches = 0
    t0 = time.perf_counter()

    for idx in range(total):
        items, kw = gen_random_instance(rng, idx)
        mode = kw.pop("mode")
        bf = solve_bruteforce_exact(items, **kw)
        sol = solve_binary_ilp(items, **kw, time_limit_s=2.0)

        ok = True
        reason = ""
        if bf["status"] != sol.status:
            ok = False
            reason = f"status mismatch: bf={bf['status']} vs sol={sol.status}"
        elif bf["status"] == "optimal":
            if abs(bf["objective_value"] - sol.objective_value) > 1e-4:
                ok = False
                reason = f"obj mismatch: bf={bf['objective_value']:.6f} vs sol={sol.objective_value:.6f}"
        else:
            # Для infeasible проверим точность min_required_budget
            if bf["min_required_budget"] is not None and sol.min_required_budget is not None:
                if abs(bf["min_required_budget"] - sol.min_required_budget) > 1e-2:
                    min_budget_mismatches += 1

        if ok:
            exact_matches += 1
        elif len(mismatches) < 25:
            mismatches.append({
                "trial": idx,
                "mode": mode,
                "reason": reason,
                "bf": bf,
                "sol": sol.to_dict(),
                "budget": kw["budget"],
                "max_items": kw["max_items"],
                "min_per_group": kw["min_per_group"],
                "max_per_group": kw["max_per_group"],
            })

    elapsed = time.perf_counter() - t0
    out = {
        "trials": total,
        "exact_matches": exact_matches,
        "mismatch_count": total - exact_matches,
        "min_budget_mismatches_on_infeasible": min_budget_mismatches,
        "elapsed_s": round(elapsed, 2),
        "sample_mismatches": mismatches[:10],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
