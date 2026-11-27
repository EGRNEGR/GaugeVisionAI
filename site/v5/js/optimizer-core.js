/*
 * GV.optimizerCore — расчёт демонстрационного оптимизатора модернизации без DOM.
 * Экономика кандидата повторяет app/modernization_optimizer.py (build_modernization_candidates,
 * _compute_utility): CAPEX = цена + монтаж + пусконаладка 14 %, предотвращённый ущерб с поправкой на
 * состояние, критичность и прогноз, баллы снижения риска по той же линейной формуле.
 * Оптимум — полный перебор всех 2^n наборов (n ≤ 16): результат точный по построению.
 *
 *   candidates(fleet, catalog, panel, eco) → [{ code, kind, capex, risk, effect, net, mandatory, ... }]
 *   solve(cands, { budget, objective, mandatory:{code:true}, excluded:{code:true} })
 *     → { status: 'optimal'|'infeasible', picked:[codes], capex, utility, risk, net, deficit, minBudget, combos }
 *   frontier(cands, opts, budgets[]) → [{ budget, risk, status }]
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});

  var ECO = { commissioning: 0.14, rounds: 38000, opex: 8000 };

  function candidates(fleet, catalog, panel, eco) {
    eco = Object.assign({}, ECO, eco || {});
    var byCode = {};
    panel.forEach(function (p) { byCode[p.code] = p; });
    return fleet.map(function (f) {
      var p = byCode[f.code];
      var c = catalog[p.kind];
      var hw = c.unit;
      var smr = c.install;
      var comm = Math.round((hw + smr) * eco.commissioning);
      var capex = hw + smr + comm;
      var sev = f.hs < 50 ? 1.25 : (f.hs < 75 ? 1.0 : (f.hs < 90 ? 0.72 : 0.35));
      var boost = 1 + 0.45 * f.prob + 0.15 * f.warnP + 0.25 * (f.anom / 100);
      var riskRub = Math.round(c.risk * sev * f.crit * boost);
      var net = riskRub + eco.rounds - eco.opex;
      var wearGap = Math.max(5, 100 - f.hs);
      var predPts = 35 * f.prob + 12 * f.warnP + 0.28 * f.anom;
      var tripPts = Math.min(15, f.trips * 2.5);
      var risk = Math.round((wearGap * 0.65 + predPts + tripPts) * f.crit * (f.ex ? 1.15 : 1) * 100) / 100;
      return {
        code: f.code, name: p.name, kind: p.kind, unit: p.unit, hs: f.hs, prob: f.prob,
        capex: capex, hw: hw, smr: smr, comm: comm,
        riskRub: riskRub, net: net, risk: risk, mandatory: !!f.mandatory,
        payback: net > 0 ? capex / net : null
      };
    });
  }

  function utilities(cands, objective) {
    var maxRisk = 1, maxNet = 1;
    cands.forEach(function (c) { maxRisk = Math.max(maxRisk, c.risk); maxNet = Math.max(maxNet, c.net); });
    return cands.map(function (c) {
      if (objective === 'max_risk_reduction') return c.risk;
      if (objective === 'max_net_effect') return c.net;
      return 0.65 * (c.risk / maxRisk) * 100 + 0.35 * (Math.max(0, c.net) / maxNet) * 100;
    });
  }

  function solve(cands, opts) {
    var n = cands.length;
    if (n > 16) throw new Error('optimizerCore: полный перебор рассчитан на n ≤ 16');
    var budget = opts.budget;
    var mand = opts.mandatory || {};
    var excl = opts.excluded || {};
    var util = utilities(cands, opts.objective || 'weighted_utility');
    var mandMask = 0, exclMask = 0, mandCost = 0;
    cands.forEach(function (c, i) {
      var isMand = mand[c.code] === undefined ? c.mandatory : !!mand[c.code];
      if (isMand && !excl[c.code]) { mandMask |= (1 << i); mandCost += c.capex; }
      if (excl[c.code]) exclMask |= (1 << i);
    });
    var best = -1, bestMask = -1, bestCost = 0, combos = 0;
    for (var m = 0; m < (1 << n); m++) {
      if ((m & mandMask) !== mandMask || (m & exclMask)) continue;
      combos++;
      var cost = 0, u = 0;
      for (var i = 0; i < n; i++) if (m & (1 << i)) { cost += cands[i].capex; u += util[i]; }
      if (cost > budget) continue;
      // При равной полезности — дешевле; при равной цене — меньше позиций
      if (u > best + 1e-9 || (Math.abs(u - best) <= 1e-9 && cost < bestCost)) { best = u; bestMask = m; bestCost = cost; }
    }
    if (bestMask < 0) {
      return { status: 'infeasible', picked: [], capex: 0, utility: 0, risk: 0, net: 0, deficit: mandCost - budget, minBudget: mandCost, combos: combos };
    }
    var picked = [], risk = 0, net = 0;
    for (var j = 0; j < n; j++) if (bestMask & (1 << j)) { picked.push(cands[j].code); risk += cands[j].risk; net += cands[j].net; }
    var totalRisk = cands.reduce(function (a, c) { return a + c.risk; }, 0);
    return {
      status: 'optimal', picked: picked, capex: bestCost, utility: best, risk: risk, net: net,
      riskShare: totalRisk ? risk / totalRisk : 0, deficit: 0, minBudget: mandCost, combos: combos
    };
  }

  function frontier(cands, opts, budgets) {
    return budgets.map(function (b) {
      var r = solve(cands, Object.assign({}, opts, { budget: b }));
      return { budget: b, riskShare: r.status === 'optimal' ? r.riskShare : null, status: r.status, capex: r.capex };
    });
  }

  GV.optimizerCore = { candidates: candidates, solve: solve, frontier: frontier, ECO: ECO };
})();
