/*
 * GV.components.optimizer — лист 07 «Бюджет, план и готовое ТЗ».
 * mount(body) → { destroy(), setBudget(rub), setObjective(id), assembleDoc() }
 *
 * Часть 1: оптимизатор модернизации (GV.optimizerCore — точный перебор 256 наборов по формулам
 * app/modernization_optimizer.py), бюджет 100–800 тыс. ₽, пресеты, цели, обязательные позиции,
 * шкала бюджета, строки двух зон «В плане» и «Отложено» с FLIP-переходом, KPI, кривая Парето
 * на миллиметровке и 3 доказательства ILP.
 * Часть 2 (#document): черновик технического задания ТЗ-КИП-20261127-01, собираемый из плана выше,
 * и вклеенный снимок реального конструктора ТЗ пульта 3.0 (hmi-spec.jpg).
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var KIND = { pressure: 'давление', draft: 'давление / разрежение', temperature: 'температура' };

  function mount(body) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit, motion = GV.motion;
    var C = GV.content, O = C.optimizerSection, D = C.documentSection, F = C.forecast;
    var core = GV.optimizerCore;
    var sc = kit.scope();
    var NBSP = kit.NBSP;
    var rub = function (n) { return u.formatNumber(Math.round(n), 0) + NBSP + '₽'; };

    var cands = core.candidates(C.fleet, C.catalog, C.panel);
    var byCode = {};
    cands.forEach(function (c) { byCode[c.code] = c; });
    var state = { budget: O.budget.initial, objective: 'max_risk_reduction', mandatory: {} };
    cands.forEach(function (c) { state.mandatory[c.code] = c.mandatory; });

    /* ---------- управление ---------- */
    var budgetOut = h('output', { class: 'gv-opt__budget-v gv-num', 'aria-live': 'polite' }, rub(state.budget));
    var range = h('input', {
      class: 'gv-opt__range',
      type: 'range',
      min: O.budget.min,
      max: O.budget.max,
      step: O.budget.step,
      value: state.budget,
      'aria-label': 'Бюджет модернизации, рублей'
    });
    var presets = [200000, 300000, 450000, 600000, 800000].map(function (b) {
      return h('button', { class: 'gv-filter__b gv-opt__preset', type: 'button', 'data-b': b }, u.formatNumber(b / 1000, 0) + NBSP + 'тыс.');
    });
    var objBtns = O.objectives.map(function (ob) {
      return h('button', { class: 'gv-filter__b gv-opt__objbtn', type: 'button', 'data-o': ob.id, 'aria-pressed': ob.id === state.objective ? 'true' : 'false' }, ob.label);
    });
    var controls = h('div', { class: 'gv-opt__controls' },
      h('div', { class: 'gv-opt__budget' },
        h('div', { class: 'gv-opt__bhead' }, h('span', { class: 'gv-label' }, 'Бюджет модернизации'), budgetOut),
        range,
        h('div', { class: 'gv-filter gv-opt__presets' }, presets)),
      h('div', { class: 'gv-opt__obj' },
        h('p', { class: 'gv-label' }, 'Целевая функция'),
        h('div', { class: 'gv-filter', role: 'group', 'aria-label': 'Целевая функция' }, objBtns)));

    /* ---------- шкала бюджета ---------- */
    var meterSegs = h('div', { class: 'gv-opt__segs' });
    var meterDeficit = h('div', { class: 'gv-opt__deficit' });
    var meterMark = h('span', { class: 'gv-opt__mark' });
    var meter = h('div', { class: 'gv-opt__meter', 'aria-hidden': 'true' }, meterSegs, meterDeficit, meterMark);

    /* ---------- строки приборов (в плане / отложено) ---------- */
    var tiles = {};
    cands.forEach(function (c) {
      var box = h('input', { type: 'checkbox', class: 'gv-opt__mand-in', checked: c.mandatory ? true : null });
      var tile = h('li', { class: 'gv-tile', 'data-code': c.code },
        h('div', { class: 'gv-tile__main' },
          h('span', { class: 'gv-tile__code gv-mono' }, c.code),
          h('span', { class: 'gv-tile__name' }, c.name, h('span', { class: 'gv-caption' }, ' (' + KIND[c.kind] + ')')),
          h('span', { class: 'gv-tile__state gv-label' })),
        h('div', { class: 'gv-tile__meta' },
          h('span', { class: 'gv-tile__hs gv-num' }, 'HS ' + c.hs + NBSP + '%'),
          h('span', { class: 'gv-tile__capex gv-num' }, u.formatNumber(c.capex / 1000, 1) + NBSP + 'тыс.' + NBSP + '₽'),
          h('span', { class: 'gv-tile__risk gv-num' }, 'риск ' + u.formatNumber(c.risk, 0) + NBSP + 'б.'),
          h('label', { class: 'gv-tile__mand' }, box, h('span', null, 'обяз.'))));
      sc.on(box, 'change', function () { state.mandatory[c.code] = box.checked; run(); });
      tiles[c.code] = { el: tile, box: box };
    });

    var zonePlan = h('ul', { class: 'gv-opt__zone-list', role: 'list' });
    var zoneRest = h('ul', { class: 'gv-opt__zone-list', role: 'list' });
    var planTitle = h('span', { class: 'gv-opt__zone-n gv-num' }, '0');
    var restTitle = h('span', { class: 'gv-opt__zone-n gv-num' }, '0');
    var zones = h('div', { class: 'gv-opt__zones' },
      h('section', { class: 'gv-opt__zone gv-opt__zone--plan', 'aria-label': 'В плане' },
        h('p', { class: 'gv-opt__zone-t' }, 'В плане ', planTitle), zonePlan),
      h('section', { class: 'gv-opt__zone gv-opt__zone--rest', 'aria-label': 'Отложено' },
        h('p', { class: 'gv-opt__zone-t' }, 'Отложено ', restTitle), zoneRest));

    /* ---------- KPI ---------- */
    function kpi(label) {
      var v = h('span', { class: 'gv-kpi__v gv-num' }, '—');
      return { el: h('div', { class: 'gv-kpi' }, v, h('span', { class: 'gv-kpi__l gv-label' }, label)), v: v };
    }
    var kStatus = kpi('статус');
    var kUsed = kpi('использовано');
    var kLeft = kpi('остаток');
    var kRisk = kpi('покрытие риска');
    var kNet = kpi('эффект в год, усл.');
    var kCombos = kpi('наборов');
    var kpis = h('div', { class: 'gv-opt__kpis', role: 'status', 'aria-live': 'polite' },
      kStatus.el, kUsed.el, kLeft.el, kRisk.el, kNet.el, kCombos.el);

    /* ---------- Парето ---------- */
    var FW = 520, FH = 200, fpad = { l: 44, r: 28, t: 16, b: 30 };
    var fb = [];
    for (var b = O.budget.min; b <= O.budget.max; b += 25000) fb.push(b);
    function FX(v) { return fpad.l + (v - O.budget.min) / (O.budget.max - O.budget.min) * (FW - fpad.l - fpad.r); }
    function FY(r) { return fpad.t + (1 - r) * (FH - fpad.t - fpad.b); }
    var fLine = s('path', { class: 'gv-par__line' });
    var fDots = s('g', { class: 'gv-par__dots' });
    var fCur = s('circle', { class: 'gv-par__cur', r: 6.5 });
    var fGuide = s('line', { class: 'gv-par__guide' });
    var frontierSvg = s('svg', {
      class: 'gv-par',
      viewBox: '0 0 ' + FW + ' ' + FH,
      role: 'img',
      'aria-label': 'Кривая Парето: доля снижения риска в зависимости от бюджета'
    },
      s('path', { class: 'gv-par__grid', d: [0, 0.25, 0.5, 0.75, 1].map(function (r) { return 'M' + fpad.l + ' ' + FY(r) + 'H' + (FW - fpad.r); }).join('') }),
      [0, 0.5, 1].map(function (r) { return s('text', { class: 'gv-par__ax', x: fpad.l - 6, y: FY(r) + 4, 'text-anchor': 'end' }, Math.round(r * 100) + ' %'); }),
      [100000, 300000, 500000, 800000].map(function (v) { return s('text', { class: 'gv-par__ax', x: FX(v), y: FH - 8, 'text-anchor': 'middle' }, (v / 1000) + ' тыс.'); }),
      fGuide, fLine, fDots, fCur);

    var proof = h('dl', { class: 'gv-opt__proof' }, O.proof.map(function (p) {
      var sObj = C.src[p.source];
      return h('div', { class: 'gv-opt__pi' },
        h('dt', { class: 'gv-num' }, p.value),
        h('dd', null, p.label, ' ', kit.extLink({ class: 'gv-src', href: sObj.href }, sObj.label)));
    }));

    var optWrap = h('div', { class: 'gv-opt', 'data-reveal': '' },
      h('div', { class: 'gv-opt__panel' },
        h('p', { class: 'gv-opt__badge' },
          h('span', { class: 'gv-mark', 'data-tone': 'warning' }, C.labels.sim),
          h('span', { class: 'gv-label' }, 'Расчёт в браузере: точный перебор 256 наборов')),
        controls, meter, kpis, zones),
      h('div', { class: 'gv-opt__side' },
        h('figure', { class: 'gv-opt__frontier gv-graph-sheet' },
          frontierSvg,
          h('figcaption', { class: 'gv-caption' }, 'Кривая Парето: доля снижения риска при каждом бюджете. Точка — выбранный бюджет.')),
        proof,
        h('p', { class: 'gv-caption' }, O.honest),
        h('p', { class: 'gv-caption' }, O.model, ' ', kit.extLink({ class: 'gv-src', href: C.src.optimizer.href }, C.src.optimizer.label))));

    /* ---------- Часть 2: Черновик ТЗ (#document) ---------- */

    var planBody = h('tbody');
    var reqList = h('ul', { class: 'gv-doc__req', role: 'list' });
    var totalCell = h('td', { class: 'gv-doc__num gv-num' });
    var basis = h('p', { class: 'gv-doc__p' });
    var docPage = h('article', { class: 'gv-doc gv-box', 'aria-label': 'Предпросмотр технического задания' },
      h('span', { class: 'gv-box__legend' }, D.docNumber),
      h('header', { class: 'gv-doc__head' },
        h('p', { class: 'gv-label' }, 'Служба КИПиА и видеоаналитики GaugeVision AI'),
        h('h4', { class: 'gv-doc__title' }, 'Техническое задание на модернизацию КИПиА'),
        h('p', { class: 'gv-caption' }, 'Черновик инженерного проекта, выгрузка DOCX и Markdown')),
      h('section', { class: 'gv-doc__sec' },
        h('h5', null, '1. Результаты мониторинга'),
        h('p', { class: 'gv-doc__p' }, 'PI-102, давление питательной воды, шкала 0–1,6 МПа: рост ' + u.formatNumber(F.slopeModel, 3) + ' МПа/мин, уставка H ' + u.formatNumber(F.warn, 1) + ' МПа пройдена.'),
        h('p', { class: 'gv-doc__p' }, 'Прогноз достижения HH ' + u.formatNumber(F.alert, 3) + ' МПа — через ' + u.formatNumber(F.eta, 2) + ' мин, интервал ' + u.formatNumber(F.ciLo, 2) + '–' + u.formatNumber(F.ciHi, 2) + ' мин.')),
      h('section', { class: 'gv-doc__sec' },
        h('h5', null, '2. План модернизации'),
        basis,
        h('table', { class: 'gv-doc__table' },
          h('thead', null, h('tr', null, h('th', null, 'Позиция'), h('th', null, 'Мероприятие'), h('th', { class: 'gv-doc__num' }, 'CAPEX'))),
          planBody,
          h('tfoot', null, h('tr', null, h('td', { colspan: '2' }, 'Итого'), totalCell)))),
      h('section', { class: 'gv-doc__sec' },
        h('h5', null, '3. Требования к оборудованию'),
        reqList),
      h('footer', { class: 'gv-doc__foot gv-caption' }, 'Документ сформирован автоматически и подлежит экспертной проверке. GaugeVision AI не является средством измерений и системой ПАЗ.'));

    var docWrap = h('div', { class: 'gv-docw', id: 'document', 'data-reveal': '' },
      h('h3', { class: 'gv-h3 gv-subhead' }, D.title),
      h('div', { class: 'gv-docw__grid' },
        h('div', { class: 'gv-docw__page' },
          h('p', { class: 'gv-docw__badge' },
            h('span', { class: 'gv-mark', 'data-tone': 'warning' }, C.labels.sim),
            h('span', { class: 'gv-label' }, 'Собрано из вашего плана выше')),
          docPage,
          h('p', { class: 'gv-caption' }, D.note)),
        h('figure', { class: 'gv-shot gv-docw__shot' },
          h('div', { class: 'gv-shot__frame gv-plate' },
            h('img', { src: D.shot.img, alt: 'Конструктор дефектной ведомости и ТЗ в пульте GaugeVision 3.0', loading: 'lazy', decoding: 'async', width: 1600, height: 900 })),
          h('figcaption', { class: 'gv-caption' },
            h('span', { class: 'gv-mark', 'data-tone': 'done' }, C.labels.real), ' ', D.shot.caption))));

    body.appendChild(optWrap);
    body.appendChild(docWrap);

    function renderDoc(plan) {
      var res = plan.res;
      planBody.textContent = '';
      reqList.textContent = '';
      if (res.status !== 'optimal') {
        basis.textContent = 'Бюджет ' + rub(plan.budget) + ' не покрывает обязательные позиции: дефицит ' + rub(res.deficit) + '. План не сформирован.';
        totalCell.textContent = '—';
        return;
      }
      basis.textContent = 'Бюджет ' + rub(plan.budget) + ', выбрано ' + res.picked.length + ' из ' + plan.cands.length + ' позиций; оптимум найден точным перебором.';
      var kinds = {};
      res.picked.forEach(function (code) {
        var c = plan.cands.filter(function (x) { return x.code === code; })[0];
        var cat = C.catalog[c.kind];
        kinds[c.kind] = cat;
        planBody.appendChild(h('tr', null,
          h('td', { class: 'gv-mono' }, code),
          h('td', null, 'Замена на: ' + cat.label.toLowerCase()),
          h('td', { class: 'gv-doc__num gv-num' }, rub(c.capex))));
      });
      totalCell.textContent = rub(res.capex);
      Object.keys(kinds).forEach(function (k) {
        var cat = kinds[k];
        reqList.appendChild(h('li', null, h('strong', null, cat.label), ': сигнал ' + cat.signal + ', погрешность ' + cat.accuracy + ', защита ' + cat.ip + '.'));
      });
    }

    function assembleDoc() {
      docPage.setAttribute('data-built', '');
    }

    function flip(mutate) {
      var first = {};
      Object.keys(tiles).forEach(function (k) { first[k] = tiles[k].el.getBoundingClientRect(); });
      mutate();
      if (motion.reduced()) return;
      Object.keys(tiles).forEach(function (k) {
        var t = tiles[k].el, last = t.getBoundingClientRect(), f = first[k];
        var dx = f.left - last.left, dy = f.top - last.top;
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
        t.animate([{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }], { duration: 480, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' });
      });
    }

    function run() {
      var opts = { budget: state.budget, objective: state.objective, mandatory: state.mandatory };
      var res = core.solve(cands, opts);
      budgetOut.textContent = rub(state.budget);
      range.value = state.budget;
      presets.forEach(function (p) { p.setAttribute('aria-pressed', Number(p.getAttribute('data-b')) === state.budget ? 'true' : 'false'); });
      objBtns.forEach(function (bn) { bn.setAttribute('aria-pressed', bn.getAttribute('data-o') === state.objective ? 'true' : 'false'); });
      var picked = {};
      res.picked.forEach(function (c) { picked[c] = true; });

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

      var scaleMax = Math.max(state.budget, res.minBudget) * 1.08;
      meterSegs.textContent = '';
      var acc = 0;
      if (res.status === 'optimal') {
        res.picked.forEach(function (code) {
          var c = byCode[code];
          meterSegs.appendChild(h('span', {
            class: ['gv-opt__seg', state.mandatory[code] ? 'gv-opt__seg--mand' : null],
            style: { left: (acc / scaleMax * 100) + '%', width: (c.capex / scaleMax * 100) + '%' },
            title: code + ': ' + rub(c.capex)
          }, h('span', null, code)));
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
        kRisk.v.textContent = Math.round(res.riskShare * 100) + NBSP + '%';
        kNet.v.textContent = u.formatNumber(res.net / 1000, 0) + NBSP + 'тыс.' + NBSP + '₽';
      } else {
        kStatus.v.textContent = 'дефицит';
        kUsed.v.textContent = '—';
        kLeft.v.textContent = '−' + rub(res.deficit);
        kRisk.v.textContent = '—';
        kNet.v.textContent = '—';
      }
      kStatus.el.toggleAttribute('data-bad', res.status !== 'optimal');
      kCombos.v.textContent = String(res.combos);

      var fr = core.frontier(cands, opts, fb);
      var pts = fr.filter(function (p) { return p.riskShare !== null; });
      fLine.setAttribute('d', pts.length ? 'M' + pts.map(function (p) { return FX(p.budget).toFixed(1) + ' ' + FY(p.riskShare).toFixed(1); }).join('L') : '');
      fDots.textContent = '';
      pts.forEach(function (p) { fDots.appendChild(s('circle', { cx: FX(p.budget), cy: FY(p.riskShare), r: 2.5 })); });
      var cy = res.status === 'optimal' ? FY(res.riskShare) : FY(0);
      fCur.setAttribute('cx', FX(state.budget));
      fCur.setAttribute('cy', cy);
      fCur.toggleAttribute('data-bad', res.status !== 'optimal');
      fGuide.setAttribute('x1', FX(state.budget));
      fGuide.setAttribute('x2', FX(state.budget));
      fGuide.setAttribute('y1', fpad.t);
      fGuide.setAttribute('y2', FH - fpad.b);

      var plan = { res: res, cands: cands, budget: state.budget, objective: state.objective };
      GV.state = GV.state || {};
      GV.state.plan = plan;
      renderDoc(plan);
      document.dispatchEvent(new CustomEvent('gv:plan', { detail: plan }));
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
    assembleDoc();

    return {
      destroy: function () { sc.destroy(); body.textContent = ''; },
      setBudget: function (b) { state.budget = b; run(); },
      setObjective: function (o) { state.objective = o; run(); },
      assembleDoc: assembleDoc
    };
  }

  GV.components.optimizer = { mount: mount };
})();
