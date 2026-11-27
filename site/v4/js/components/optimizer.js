/*
 * GV.components.optimizer — «Модернизировать то, что действительно нужно».
 * mount(el) → { destroy(), setBudget(rub), setObjective(id) }
 *
 * Пользователь задаёт бюджет (ползунок, поле, пресеты), цель и обязательные позиции. Каждое изменение
 * пересчитывает точный оптимум GV.optimizerCore.solve (полный перебор 256 наборов) и перестраивает план:
 * плитки приборов переезжают между зонами «В плане» и «Отложено» (FLIP: transform от старого места),
 * шкала бюджета делится на сегменты выбранных позиций, при нехватке на обязательные — красный дефицит.
 * Кривая Парето (точный оптимум на сетке бюджетов) отмечает текущую точку.
 * Итог публикуется событием document 'gv:plan' { plan, cands, budget, objective } — его слушает документ ТЗ.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var KIND = { pressure: 'давление', draft: 'давление / разрежение', temperature: 'температура' };

  function mount(el) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit, motion = GV.motion;
    var C = GV.content, O = C.optimizerSection, core = GV.optimizerCore;
    var sc = kit.scope();
    var rub = function (n) { return u.formatNumber(Math.round(n), 0) + ' ₽'; };
    var cands = core.candidates(C.fleet, C.catalog, C.panel);
    var byCode = {};
    cands.forEach(function (c) { byCode[c.code] = c; });
    var state = { budget: O.budget.initial, objective: 'max_risk_reduction', mandatory: {} };
    cands.forEach(function (c) { state.mandatory[c.code] = c.mandatory; });

    /* ---------- управление ---------- */
    var budgetOut = h('output', { class: 'gv-opt__budget-v', 'aria-live': 'polite' }, rub(state.budget));
    var range = h('input', { class: 'gv-range', type: 'range', min: O.budget.min, max: O.budget.max, step: O.budget.step, value: state.budget, 'aria-label': 'Бюджет модернизации, рублей' });
    var presets = [200000, 300000, 450000, 600000, 800000].map(function (b) {
      return h('button', { class: 'gv-chipbtn', type: 'button', 'data-b': b }, u.formatNumber(b / 1000, 0) + ' тыс.');
    });
    var objBtns = O.objectives.map(function (ob) {
      return h('button', { class: 'gv-seg__btn gv-seg__btn--text', type: 'button', 'data-o': ob.id, 'aria-pressed': ob.id === state.objective ? 'true' : 'false' }, ob.label);
    });
    var controls = h('div', { class: 'gv-opt__controls' },
      h('div', { class: 'gv-opt__budget' },
        h('p', { class: 'gv-opt__label' }, 'Бюджет модернизации'), budgetOut, range,
        h('div', { class: 'gv-opt__presets' }, presets)),
      h('div', { class: 'gv-opt__obj' }, h('p', { class: 'gv-opt__label' }, 'Цель'), h('div', { class: 'gv-seg gv-seg--text', role: 'group', 'aria-label': 'Целевая функция' }, objBtns)));

    /* ---------- шкала бюджета ---------- */
    var meterSegs = h('div', { class: 'gv-opt__segs' });
    var meterDeficit = h('div', { class: 'gv-opt__deficit' });
    var meterMark = h('span', { class: 'gv-opt__mark' });
    var meter = h('div', { class: 'gv-opt__meter', 'aria-hidden': 'true' }, meterSegs, meterDeficit, meterMark);

    /* ---------- плитки ---------- */
    var tiles = {};
    cands.forEach(function (c) {
      var box = h('input', { type: 'checkbox', class: 'gv-opt__mand-in', checked: c.mandatory ? true : null });
      var tile = h('li', { class: 'gv-tile', 'data-code': c.code },
        h('div', { class: 'gv-tile__top' }, h('span', { class: 'gv-tile__code' }, c.code), h('span', { class: 'gv-tile__state' })),
        h('p', { class: 'gv-tile__name' }, c.name),
        h('p', { class: 'gv-tile__kind' }, KIND[c.kind]),
        h('div', { class: 'gv-tile__hs' }, h('span', { class: 'gv-tile__hs-bar', style: { '--hs': c.hs / 100 } }), h('span', { class: 'gv-tile__hs-v' }, 'HS ' + c.hs + ' %')),
        h('dl', { class: 'gv-tile__nums' },
          h('div', null, h('dt', null, 'CAPEX'), h('dd', null, u.formatNumber(c.capex / 1000, 1) + ' тыс. ₽')),
          h('div', null, h('dt', null, 'риск'), h('dd', null, u.formatNumber(c.risk, 0) + ' б.'))),
        h('label', { class: 'gv-tile__mand' }, box, h('span', null, 'обязательно')));
      sc.on(box, 'change', function () { state.mandatory[c.code] = box.checked; run(); });
      tiles[c.code] = { el: tile, box: box };
    });
    var zonePlan = h('ul', { class: 'gv-opt__zone-list', role: 'list' });
    var zoneRest = h('ul', { class: 'gv-opt__zone-list', role: 'list' });
    var planTitle = h('span', { class: 'gv-opt__zone-n' }, '0');
    var restTitle = h('span', { class: 'gv-opt__zone-n' }, '0');
    var zones = h('div', { class: 'gv-opt__zones' },
      h('section', { class: 'gv-opt__zone gv-opt__zone--plan', 'aria-label': 'В плане' }, h('p', { class: 'gv-opt__zone-t' }, 'В плане ', planTitle), zonePlan),
      h('section', { class: 'gv-opt__zone gv-opt__zone--rest', 'aria-label': 'Отложено' }, h('p', { class: 'gv-opt__zone-t' }, 'Отложено ', restTitle), zoneRest));

    /* ---------- итоги и Парето ---------- */
    function kpi(label) { var v = h('span', { class: 'gv-kpi__v' }, '—'); return { el: h('div', { class: 'gv-kpi' }, v, h('span', { class: 'gv-kpi__l' }, label)), v: v }; }
    var kStatus = kpi('статус расчёта'), kUsed = kpi('использовано'), kLeft = kpi('остаток'), kRisk = kpi('покрытие риска'), kNet = kpi('чистый эффект в год, условно'), kCombos = kpi('наборов проверено');
    var kpis = h('div', { class: 'gv-opt__kpis', role: 'status', 'aria-live': 'polite' }, kStatus.el, kUsed.el, kLeft.el, kRisk.el, kNet.el, kCombos.el);

    var FW = 520, FH = 200, fpad = { l: 40, r: 12, t: 14, b: 30 };
    var fb = [];
    for (var b = O.budget.min; b <= O.budget.max; b += 25000) fb.push(b);
    function FX(v) { return fpad.l + (v - O.budget.min) / (O.budget.max - O.budget.min) * (FW - fpad.l - fpad.r); }
    function FY(r) { return fpad.t + (1 - r) * (FH - fpad.t - fpad.b); }
    var fLine = s('path', { class: 'gv-par__line' });
    var fDots = s('g', { class: 'gv-par__dots' });
    var fCur = s('circle', { class: 'gv-par__cur', r: 7 });
    var fGuide = s('line', { class: 'gv-par__guide' });
    var frontierSvg = s('svg', { class: 'gv-par', viewBox: '0 0 ' + FW + ' ' + FH, role: 'img', 'aria-label': 'Кривая Парето: доля снижения риска в зависимости от бюджета' },
      s('path', { class: 'gv-par__grid', d: [0, 0.25, 0.5, 0.75, 1].map(function (r) { return 'M' + fpad.l + ' ' + FY(r) + 'H' + (FW - fpad.r); }).join('') }),
      [0, 0.5, 1].map(function (r) { return s('text', { class: 'gv-par__ax', x: fpad.l - 6, y: FY(r) + 4, 'text-anchor': 'end' }, Math.round(r * 100) + '%'); }),
      [100000, 300000, 500000, 800000].map(function (v) { return s('text', { class: 'gv-par__ax', x: FX(v), y: FH - 8, 'text-anchor': 'middle' }, (v / 1000) + ' тыс.'); }),
      fGuide, fLine, fDots, fCur);

    var proof = h('div', { class: 'gv-opt__proof' }, O.proof.map(function (p) {
      var sObj = C.src[p.source];
      return h('div', { class: 'gv-opt__pi' }, h('span', { class: 'gv-opt__piv' }, p.value), h('span', { class: 'gv-opt__pil' }, p.label, ' ', kit.extLink({ class: 'gv-src', href: sObj.href }, sObj.label)));
    }));

    el.appendChild(h('div', { class: 'gv-opt' },
      h('div', { class: 'gv-opt__panel' },
        h('p', { class: 'gv-opt__badge' }, h('span', { class: 'gv-chip gv-chip--sim' }, 'Расчёт в браузере'), h('span', { class: 'gv-opt__badge-t' }, 'упрощённая модель, точный оптимум')),
        controls, meter, kpis, zones),
      h('div', { class: 'gv-opt__side' },
        h('figure', { class: 'gv-opt__frontier' }, frontierSvg, h('figcaption', { class: 'gv-cap' }, 'Кривая Парето: какую долю риска закрывает лучший план при каждом бюджете. Точка — ваш бюджет.')),
        proof,
        h('p', { class: 'gv-limit' }, O.honest),
        h('p', { class: 'gv-cap' }, O.model, ' ', kit.extLink({ class: 'gv-src', href: C.src.optimizer.href }, C.src.optimizer.label)))));

    /* ---------- расчёт и отрисовка ---------- */
    function flip(mutate) {
      var first = {};
      Object.keys(tiles).forEach(function (k) { first[k] = tiles[k].el.getBoundingClientRect(); });
      mutate();
      if (motion.reduced()) return;
      Object.keys(tiles).forEach(function (k) {
        var t = tiles[k].el, last = t.getBoundingClientRect(), f = first[k];
        var dx = f.left - last.left, dy = f.top - last.top;
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
        t.animate([{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }], { duration: 560, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' });
      });
    }

    var lastKey = '';
    function run() {
      var opts = { budget: state.budget, objective: state.objective, mandatory: state.mandatory };
      var res = core.solve(cands, opts);
      budgetOut.textContent = rub(state.budget);
      range.value = state.budget;
      presets.forEach(function (p) { p.setAttribute('aria-pressed', Number(p.getAttribute('data-b')) === state.budget ? 'true' : 'false'); });
      objBtns.forEach(function (bn) { bn.setAttribute('aria-pressed', bn.getAttribute('data-o') === state.objective ? 'true' : 'false'); });
      var picked = {};
      res.picked.forEach(function (c) { picked[c] = true; });

      var key = res.picked.join(',') + '|' + res.status;
      flip(function () {
        var inPlan = 0, rest = 0;
        cands.slice().sort(function (a, b2) { return b2.risk - a.risk; }).forEach(function (c) {
          var t = tiles[c.code];
          var on = !!picked[c.code];
          t.el.toggleAttribute('data-on', on);
          t.el.toggleAttribute('data-mand', !!state.mandatory[c.code]);
          t.el.querySelector('.gv-tile__state').textContent = on ? 'в плане' : (state.mandatory[c.code] ? 'не помещается' : 'отложено');
          (on ? zonePlan : zoneRest).appendChild(t.el);
          if (on) inPlan++; else rest++;
        });
        planTitle.textContent = String(inPlan);
        restTitle.textContent = String(rest);
      });
      if (key !== lastKey) { zones.classList.remove('is-pulse'); void zones.offsetWidth; zones.classList.add('is-pulse'); lastKey = key; }

      // Шкала: сегменты выбранных позиций от бюджета; дефицит — за отметкой бюджета
      var scaleMax = Math.max(state.budget, res.minBudget) * 1.08;
      meterSegs.textContent = '';
      var acc = 0;
      if (res.status === 'optimal') {
        res.picked.forEach(function (code) {
          var c = byCode[code];
          meterSegs.appendChild(h('span', { class: ['gv-opt__seg', state.mandatory[code] ? 'gv-opt__seg--mand' : null], style: { left: (acc / scaleMax * 100) + '%', width: (c.capex / scaleMax * 100) + '%' }, title: code + ': ' + rub(c.capex) }, h('span', null, code)));
          acc += c.capex;
        });
        meterDeficit.style.width = '0';
      } else {
        meterDeficit.style.left = (state.budget / scaleMax * 100) + '%';
        meterDeficit.style.width = (res.deficit / scaleMax * 100) + '%';
      }
      meterMark.style.left = (state.budget / scaleMax * 100) + '%';
      meter.toggleAttribute('data-infeasible', res.status !== 'optimal');

      if (res.status === 'optimal') {
        kStatus.v.textContent = 'оптимум';
        kUsed.v.textContent = rub(res.capex);
        kLeft.v.textContent = rub(state.budget - res.capex);
        kRisk.v.textContent = Math.round(res.riskShare * 100) + ' %';
        kNet.v.textContent = u.formatNumber(res.net / 1000, 0) + ' тыс. ₽';
      } else {
        kStatus.v.textContent = 'дефицит';
        kUsed.v.textContent = '—';
        kLeft.v.textContent = '−' + rub(res.deficit);
        kRisk.v.textContent = '—';
        kNet.v.textContent = '—';
      }
      kStatus.el.toggleAttribute('data-bad', res.status !== 'optimal');
      kCombos.v.textContent = String(res.combos);

      // Парето — точный оптимум на сетке бюджетов при тех же цели и обязательных позициях
      var fr = core.frontier(cands, opts, fb);
      var pts = fr.filter(function (p) { return p.riskShare !== null; });
      fLine.setAttribute('d', pts.length ? 'M' + pts.map(function (p) { return FX(p.budget).toFixed(1) + ' ' + FY(p.riskShare).toFixed(1); }).join('L') : '');
      fDots.textContent = '';
      pts.forEach(function (p) { fDots.appendChild(s('circle', { cx: FX(p.budget), cy: FY(p.riskShare), r: 2.5 })); });
      var cy = res.status === 'optimal' ? FY(res.riskShare) : FY(0);
      fCur.setAttribute('cx', FX(state.budget)); fCur.setAttribute('cy', cy);
      fCur.toggleAttribute('data-bad', res.status !== 'optimal');
      fGuide.setAttribute('x1', FX(state.budget)); fGuide.setAttribute('x2', FX(state.budget));
      fGuide.setAttribute('y1', fpad.t); fGuide.setAttribute('y2', FH - fpad.b);

      GV.state = GV.state || {};
      GV.state.plan = { res: res, cands: cands, budget: state.budget, objective: state.objective };
      document.dispatchEvent(new CustomEvent('gv:plan', { detail: GV.state.plan }));
    }

    var raf = 0;
    sc.on(range, 'input', function () {
      state.budget = Number(range.value);
      budgetOut.textContent = rub(state.budget);
      if (!raf) raf = requestAnimationFrame(function () { raf = 0; run(); });
    });
    presets.forEach(function (p) { sc.on(p, 'click', function () { state.budget = Number(p.getAttribute('data-b')); run(); }); });
    objBtns.forEach(function (bn) { sc.on(bn, 'click', function () { state.objective = bn.getAttribute('data-o'); run(); }); });
    run();

    return {
      destroy: function () { sc.destroy(); el.textContent = ''; },
      setBudget: function (b) { state.budget = b; run(); },
      setObjective: function (o) { state.objective = o; run(); }
    };
  }

  GV.components.optimizer = { mount: mount };
})();
