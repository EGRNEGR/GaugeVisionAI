/*
 * GV.components.economics — прозрачный калькулятор двух сценариев цифровизации (развитие compare v2).
 * mount(el) → { destroy() }
 *
 * A — замена всех N приборов на цифровые датчики:
 *     CAPEX_A = N × Cзамены;   OPEX_A = N × Oдатчика в год
 * B — поэтапно: доля q приборов меняется по плану, остальные читают камеры (k приборов на камеру):
 *     Nзам = round(N × q);  камер = ceil((N − Nзам) / k)
 *     CAPEX_B = Nзам × Cзамены + камер × Cкамеры + Cвнедрения;  OPEX_B = Nзам × Oдатчика + камер × Oкамеры
 * За горизонт T лет: ИТОГ = CAPEX + T × OPEX. Разница A − B — потенциальная экономия сценария.
 * Все допущения — поля формы; формулы показаны под результатом. Значения по умолчанию — из каталога и
 * config проекта и оценки команды, они помечены.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function compute(v) {
    var N = Math.max(0, Math.round(v.points));
    var q = Math.max(0, Math.min(1, v.priority / 100));
    var k = Math.max(1, Math.round(v.perCamera));
    var nRep = Math.round(N * q);
    var cams = Math.ceil((N - nRep) / k);
    var capexA = N * v.sensorCost;
    var opexA = N * v.opexSensor;
    var capexB = nRep * v.sensorCost + cams * v.cameraCost + v.serverCost;
    var opexB = nRep * v.opexSensor + cams * v.opexCamera;
    var T = Math.max(1, Math.round(v.years));
    var totalA = capexA + T * opexA;
    var totalB = capexB + T * opexB;
    return { N: N, nRep: nRep, cams: cams, capexA: capexA, opexA: opexA, capexB: capexB, opexB: opexB, totalA: totalA, totalB: totalB, T: T,
      perPointB: N ? capexB / N : 0, perPointA: N ? capexA / N : 0, saving: totalA - totalB };
  }

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, E = C.economics;
    var sc = kit.scope();
    var vals = {};
    var rub = function (n) { return (n < 0 ? '−' : '') + u.formatNumber(Math.round(Math.abs(n)), 0) + ' ₽'; };
    var mln = function (n) { return (n < 0 ? '−' : '') + u.formatNumber(Math.abs(n) / 1e6, 2) + ' млн ₽'; };

    var inputs = E.fields.map(function (f) {
      vals[f.id] = f.value;
      var id = u.uid('gv-eco-' + f.id);
      var num = h('input', { class: 'gv-eco__num', type: 'number', id: id, min: f.min, max: f.max, step: f.step, value: f.value, inputmode: 'numeric' });
      var rng = h('input', { class: 'gv-range gv-range--s', type: 'range', min: f.min, max: f.max, step: f.step, value: f.value, 'aria-label': f.label, tabindex: '-1' });
      function set(v, from) {
        v = Number(v);
        if (!isFinite(v)) return;
        v = Math.max(f.min, Math.min(f.max, v));
        vals[f.id] = v;
        if (from !== num) num.value = v;
        if (from !== rng) rng.value = v;
        update();
      }
      sc.on(num, 'change', function () { set(num.value, num); });
      sc.on(num, 'input', function () { if (num.value !== '' && isFinite(Number(num.value))) { vals[f.id] = Math.max(f.min, Math.min(f.max, Number(num.value))); rng.value = vals[f.id]; update(); } });
      sc.on(rng, 'input', function () { set(rng.value, rng); });
      return h('div', { class: 'gv-eco__field' },
        h('label', { class: 'gv-eco__label', for: id }, f.label, f.note ? h('small', null, f.note) : null),
        h('div', { class: 'gv-eco__ctl' }, num, h('span', { class: 'gv-eco__unit' }, f.unit)),
        rng);
    });

    function bar(cls) { var c = h('span', { class: 'gv-eco__capex' }), o = h('span', { class: 'gv-eco__opex' }); return { el: h('div', { class: 'gv-eco__bar ' + cls }, c, o), c: c, o: o }; }
    var barA = bar('gv-eco__bar--a'), barB = bar('gv-eco__bar--b');
    var tA = h('span', { class: 'gv-eco__total' }), tB = h('span', { class: 'gv-eco__total' });
    var saving = h('p', { class: 'gv-eco__saving' });
    var savingL = h('p', { class: 'gv-eco__saving-l' });
    var rows = h('tbody');
    var phase = h('p', { class: 'gv-eco__phase' });

    el.appendChild(h('div', { class: 'gv-eco' },
      h('form', { class: 'gv-eco__form', 'aria-label': 'Допущения расчёта', on: { submit: function (e) { e.preventDefault(); } } },
        h('p', { class: 'gv-eco__ftitle' }, 'Допущения — меняйте под свой объект'), inputs),
      h('div', { class: 'gv-eco__out', role: 'status', 'aria-live': 'polite' },
        h('div', { class: 'gv-eco__bars' },
          h('div', { class: 'gv-eco__brow' }, h('p', { class: 'gv-eco__bl' }, 'A. Заменить всё сразу'), barA.el, tA),
          h('div', { class: 'gv-eco__brow' }, h('p', { class: 'gv-eco__bl' }, 'B. GaugeVision и замены по плану'), barB.el, tB),
          h('p', { class: 'gv-eco__key' }, h('span', { class: 'gv-eco__k gv-eco__k--c' }, 'капитальные затраты'), h('span', { class: 'gv-eco__k gv-eco__k--o' }, 'эксплуатация за горизонт'))),
        saving, savingL,
        h('table', { class: 'gv-eco__table' },
          h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'A'), h('th', null, 'B'))), rows),
        phase,
        h('details', { class: 'gv-details gv-details--s' }, h('summary', null, 'Формулы расчёта'),
          h('p', null, 'A: CAPEX = N × цена замены; эксплуатация = N × расходы на датчик в год.'),
          h('p', null, 'B: замен = N × доля; камер = ⌈(N − замен) / приборов на камеру⌉; CAPEX = замены × цена + камеры × цена камеры + внедрение; эксплуатация = замены × расходы на датчик + камеры × расходы на камеру.'),
          h('p', null, 'Итог за горизонт = CAPEX + лет × эксплуатация в год.')),
        h('p', { class: 'gv-limit' }, E.disclaimer))));

    function update() {
      var r = compute(vals);
      var max = Math.max(r.totalA, r.totalB, 1);
      barA.c.style.width = (r.capexA / max * 100) + '%'; barA.o.style.width = (r.T * r.opexA / max * 100) + '%';
      barB.c.style.width = (r.capexB / max * 100) + '%'; barB.o.style.width = (r.T * r.opexB / max * 100) + '%';
      tA.textContent = mln(r.totalA);
      tB.textContent = mln(r.totalB);
      saving.textContent = mln(r.saving);
      saving.toggleAttribute('data-neg', r.saving < 0);
      savingL.textContent = r.saving >= 0 ? 'разница сценариев за ' + r.T + ' ' + (r.T === 1 ? 'год' : (r.T < 5 ? 'года' : 'лет')) + ' при этих допущениях' : 'при этих допущениях сценарий B дороже — проверьте долю замен и цену внедрения';
      rows.textContent = '';
      [['Капитальные затраты', rub(r.capexA), rub(r.capexB)],
        ['Цифровизация одной точки', rub(r.perPointA), rub(r.perPointB)],
        ['Эксплуатация в год', rub(r.opexA), rub(r.opexB)],
        ['Датчиков / камер', u.formatNumber(r.N, 0) + ' / 0', u.formatNumber(r.nRep, 0) + ' / ' + u.formatNumber(r.cams, 0)]
      ].forEach(function (row) { rows.appendChild(h('tr', null, h('th', null, row[0]), h('td', null, row[1]), h('td', null, row[2]))); });
      phase.textContent = 'Поэтапно: сейчас — ' + u.formatNumber(r.cams, 0) + ' камер на ' + u.formatNumber(r.N - r.nRep, 0) + ' приборов и ' + u.formatNumber(r.nRep, 0) + ' приоритетных замен по плану оптимизатора; остальные замены — по мере износа, когда мониторинг покажет необходимость.';
    }
    update();

    return { destroy: function () { sc.destroy(); el.textContent = ''; } };
  }

  GV.components.economics = { mount: mount, compute: compute };
})();
