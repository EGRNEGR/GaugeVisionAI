/*
 * GV.components.metrics — подтверждённые метрики с условиями замера.
 * mount(el, { layout: 'strip'|'dial'|'table', ids?: [id…], note?: true }) → { destroy() }
 *   strip — телеметрическая полоса с индексами /01 (вариант A);
 *   dial  — крупные контурные цифры;
 *   table — таблица «показатель · значение · условия · вид».
 * Итоговое значение (metrics[].display) в DOM сразу; счётчик — только визуальный слой
 * (aria-hidden), один раз при первом появлении, до 1,2 с, не при reduced motion.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var LAYOUTS = ['strip', 'dial', 'table'];
  var COUNT_MS = 1100;
  var T = {
    caption: 'Подтверждённые метрики и условия замера',
    colLabel: 'Показатель',
    colValue: 'Значение',
    colCondition: 'Условия замера',
    colKind: 'Вид'
  };

  function easeOut(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  /* Можно ли досчитать до значения так, чтобы итог совпал с display. */
  function counterFor(m) {
    var fmt = GV.util.formatNumber;
    if (typeof m.value !== 'number') return null;
    var digits = typeof m.digits === 'number' ? m.digits : 0;
    if (typeof m.valueTo === 'number') {
      if (m.display !== fmt(m.value, digits) + '–' + fmt(m.valueTo, digits)) return null;
      return function (t) { return fmt(m.value * t, digits) + '–' + fmt(m.valueTo * t, digits); };
    }
    if (m.display !== fmt(m.value, digits)) return null;
    return function (t) { return fmt(m.value * t, digits); };
  }

  function mount(el, options) {
    options = options || {};
    var u = GV.util;
    var kit = GV.kit;
    var h = u.h;
    var c = GV.content;
    var layout = kit.pick(options.layout, LAYOUTS);
    var sc = kit.scope();
    var list = c.metrics.filter(function (m) { return !options.ids || options.ids.indexOf(m.id) >= 0; });
    if (options.ids) list.sort(function (a, b) { return options.ids.indexOf(a.id) - options.ids.indexOf(b.id); });
    var counters = [];

    function index(i) {
      return '/' + (i + 1 < 10 ? '0' : '') + (i + 1);
    }

    function figure(m) {
      var counter = counterFor(m);
      var visible = h('span', { class: ['gv-metrics__digits', m.display.length > 7 ? 'gv-metrics__digits--long' : null], 'aria-hidden': 'true', style: { minWidth: m.display.length + 'ch' } }, m.display);
      if (counter) counters.push({ el: visible, fn: counter, final: m.display });
      return [
        visible,
        h('span', { class: 'gv-visually-hidden' }, m.display + (m.unit ? kit.NBSP + m.unit : '')),
        m.unit ? h('span', { class: 'gv-metrics__unit', 'aria-hidden': 'true' }, m.unit) : null
      ];
    }

    function kindBadge(m) {
      return h('span', { class: 'gv-metrics__kind', 'data-kind': m.kind }, c.labels.kind[m.kind]);
    }

    var rootEl;
    if (layout === 'table') {
      rootEl = h('div', { class: 'gv-metrics gv-metrics--table' },
        h('div', { class: 'gv-metrics__scroll' },
          h('table', { class: 'gv-metrics__table' },
            h('caption', { class: 'gv-visually-hidden' }, T.caption),
            h('thead', null, h('tr', null,
              h('th', { scope: 'col' }, T.colLabel),
              h('th', { scope: 'col', class: 'gv-metrics__th-value' }, T.colValue),
              h('th', { scope: 'col' }, T.colCondition),
              h('th', { scope: 'col' }, T.colKind))),
            h('tbody', null, list.map(function (m, i) {
              return h('tr', { class: 'gv-metrics__row', 'data-kind': m.kind, 'data-group': m.group || '' },
                h('th', { scope: 'row', class: 'gv-metrics__label' },
                  h('span', { class: 'gv-metrics__index' }, index(i)), ' ', m.label),
                h('td', { class: 'gv-metrics__figure' }, figure(m)),
                h('td', { class: 'gv-metrics__condition' }, m.condition),
                h('td', null, kindBadge(m)));
            })))));
    } else {
      rootEl = h('div', { class: ['gv-metrics', 'gv-metrics--' + layout] },
        h('dl', { class: 'gv-metrics__list' }, list.map(function (m, i) {
          return h('div', { class: 'gv-metrics__item', 'data-kind': m.kind, 'data-group': m.group || '' },
            h('dt', { class: 'gv-metrics__label' }, m.label),
            h('dd', { class: 'gv-metrics__figure' }, figure(m)),
            h('dd', { class: 'gv-metrics__condition' }, m.condition),
            h('dd', { class: 'gv-metrics__meta' },
              h('span', { class: 'gv-metrics__index', 'aria-hidden': 'true' }, index(i)),
              kindBadge(m)));
        })));
    }

    if (options.note !== false && c.metricsNote) {
      rootEl.appendChild(h('p', { class: 'gv-metrics__note' }, c.metricsNote));
    }
    el.appendChild(rootEl);

    /* Счётчик: один раз при первом появлении. */
    if (counters.length && !u.prefersReducedMotion()) {
      sc.observe(u.onVisible(rootEl, function () {
        rootEl.classList.add('is-counting');
        sc.frame(COUNT_MS, function (t) {
          var k = easeOut(t);
          counters.forEach(function (cn) { cn.el.textContent = t >= 1 ? cn.final : cn.fn(k); });
        }, function () {
          counters.forEach(function (cn) { cn.el.textContent = cn.final; });
          rootEl.classList.remove('is-counting');
        });
      }, { once: true, threshold: 0.3 }));
    }

    return {
      destroy: function () {
        sc.destroy();
        counters.forEach(function (cn) { cn.el.textContent = cn.final; });
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      }
    };
  }

  GV.components.metrics = { mount: mount, layouts: LAYOUTS.slice() };
})();
