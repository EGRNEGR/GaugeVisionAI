/*
 * GV.components.metrics — лист 05 «Протокол испытаний».
 * Таблица протокола: № · показатель · условия замера · значение · вид (штамп «замер» или «расчёт»).
 * Строки сгруппированы «Точность · Скорость · Масштаб»; у масштаба в колонке условий — полоса
 * в одной шкале (к/с): замер залит, расчёт заштрихован. Цифры докручиваются при первом показе,
 * диапазоны (30–100, 3–4) печатаются сразу. Пометка о стенде — рукой на полях.
 *
 *   mount(body) → { destroy }
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  var GROUPS = ['quality', 'speed', 'scale'];

  function mount(body) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var L = c.labels;
    var cols = c.metricsColumns;
    var sc = kit.scope();
    var fmt = u.formatNumber;

    body.classList.add('gv-proto-wrap');

    var scaleMax = 0;
    c.metrics.forEach(function (m) { if (m.group === 'scale') scaleMax = Math.max(scaleMax, m.value); });

    var n = 0;
    var table = h('table', { class: 'gv-proto' },
      h('caption', { class: 'gv-visually-hidden' }, c.sections.filter(function (s) { return s.id === 'metrics'; })[0].title),
      h('thead', null, h('tr', null, cols.map(function (col, i) {
        return h('th', { scope: 'col', class: 'gv-proto__h gv-proto__h--' + i }, col);
      }))));

    GROUPS.forEach(function (g) {
      var rows = c.metrics.filter(function (m) { return m.group === g; });
      if (!rows.length) return;
      var tbody = h('tbody', { class: 'gv-proto__group gv-proto__group--' + g });
      tbody.appendChild(h('tr', { class: 'gv-proto__gh' },
        h('th', { scope: 'colgroup', colspan: '5' }, L.metricGroups[g])));
      if (g === 'scale') {
        tbody.firstChild.firstChild.appendChild(h('span', { class: 'gv-proto__axis' }, c.metricsAxis));
      }
      rows.forEach(function (m) {
        n += 1;
        var parts = String(m.display).split(' / ');
        var valueEl = h('span', { class: 'gv-proto__v gv-num' }, parts[0]);
        var value = [valueEl];
        if (parts.length > 1) {
          value = parts.map(function (p) { return h('span', { class: 'gv-proto__v gv-proto__v--pair gv-num' }, p); });
        }
        if (m.unit) value.push(h('span', { class: 'gv-proto__u' }, m.unit));
        if (g === 'scale') {
          value.push(h('span', { class: 'gv-proto__bar gv-proto__bar--' + m.kind, title: c.metricsAxis },
            h('span', { class: 'gv-proto__fill', style: { '--w': (m.value / scaleMax).toFixed(4) } })));
        }
        var cond = [h('span', { class: 'gv-proto__cond-t' }, m.condition)];
        tbody.appendChild(h('tr', { class: m.key ? 'gv-proto__row is-key' : 'gv-proto__row' },
          h('td', { class: 'gv-proto__n gv-num' }, (n < 10 ? '0' : '') + n),
          h('th', { scope: 'row', class: 'gv-proto__label' }, m.label),
          h('td', { class: 'gv-proto__cond' }, cond),
          h('td', { class: 'gv-proto__value' }, value),
          h('td', { class: 'gv-proto__kind' }, h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': m.kind }, L.kind[m.kind]))));
        if (m.valueTo === undefined && parts.length === 1) {
          sc.add(motion.counter(valueEl, { to: m.value, digits: m.digits, display: m.display, duration: 1200 }));
        }
      });
      table.appendChild(tbody);
    });

    body.appendChild(h('div', { class: 'gv-proto__scroll', 'data-reveal': '' }, table));

    sc.observe(u.onVisible(table, function () { table.classList.add('gv-stamped', 'is-drawn'); }, { once: true, threshold: 0.15 }));
    Array.prototype.forEach.call(table.querySelectorAll('.gv-mark--stamp'), function (el, i) {
      el.style.setProperty('--gv-stamp-delay', Math.min(i, 10) * 70 + 'ms');
    });

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.metrics = { mount: mount };
})();
