/*
 * GV.components.metrics — подтверждённые метрики с условиями замера: карточки с крупными цифрами.
 * mount(el, { ids?: [id…], note?: true }) → { destroy() }
 * Цифры докручиваются от нуля GV.motion.counter (≈ 1,2 с, при первом показе карточки); конечный текст —
 * точная строка metrics[].display. Для диапазона «30–100» и пары «1,00 / 1,00» растут все числа записи.
 * Рядом с числом всегда метка «замер» или «расчёт» (kind). Ободок карточки ловит свет курсора
 * (GV.motion.spotlight: слой двигается transform). Читающим экран отдаётся готовая запись без счётчика.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var NUMBER_RE = /\d+(?:,\d+)?/g;

  /* Параметры счётчика для записи display: каждое число растёт с нулевой доли до своего значения. */
  function counterOptions(display) {
    var fmt = GV.util.formatNumber;
    var tokens = display.match(NUMBER_RE);
    if (!tokens) return null;
    var spec = tokens.map(function (t) {
      var comma = t.indexOf(',');
      return { value: parseFloat(t.replace(',', '.')), digits: comma >= 0 ? t.length - comma - 1 : 0 };
    });
    return {
      to: 1,
      display: display,
      format: function (t) {
        var i = 0;
        return display.replace(NUMBER_RE, function () {
          var s = spec[i++];
          return fmt(s.value * t, s.digits);
        });
      }
    };
  }

  function mount(el, options) {
    options = options || {};
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var sc = kit.scope();
    var offs = [];
    var list = c.metrics.filter(function (m) { return !options.ids || options.ids.indexOf(m.id) >= 0; });
    if (options.ids) list.sort(function (a, b) { return options.ids.indexOf(a.id) - options.ids.indexOf(b.id); });

    function index(i) {
      return '/' + (i + 1 < 10 ? '0' : '') + (i + 1);
    }

    var digitEls = [];
    var items = list.map(function (m, i) {
      var digits = h('span', {
        class: ['gv-metrics__digits', m.display.length > 7 ? 'gv-metrics__digits--long' : null],
        'aria-hidden': 'true',
        style: { minWidth: m.display.length + 'ch' }
      }, m.display);
      digitEls.push({ el: digits, display: m.display });
      return h('div', { class: 'gv-metrics__item', 'data-kind': m.kind, 'data-group': m.group || '' },
        h('dt', { class: 'gv-metrics__label' }, m.label),
        h('dd', { class: 'gv-metrics__figure' },
          digits,
          h('span', { class: 'gv-visually-hidden' }, m.display + (m.unit ? kit.NBSP + m.unit : '')),
          m.unit ? h('span', { class: 'gv-metrics__unit', 'aria-hidden': 'true' }, m.unit) : null),
        h('dd', { class: 'gv-metrics__condition' }, m.condition),
        h('dd', { class: 'gv-metrics__meta' },
          h('span', { class: 'gv-metrics__index', 'aria-hidden': 'true' }, index(i)),
          h('span', { class: 'gv-metrics__kind', 'data-kind': m.kind }, c.labels.kind[m.kind])));
    });

    var rootEl = h('div', { class: 'gv-metrics gv-metrics--dial' },
      h('dl', { class: 'gv-metrics__list' }, items));
    if (options.note !== false && c.metricsNote) {
      rootEl.appendChild(h('p', { class: 'gv-metrics__note' }, c.metricsNote));
    }
    el.appendChild(rootEl);

    digitEls.forEach(function (d) {
      var opts = counterOptions(d.display);
      if (opts) offs.push(motion.counter(d.el, opts));
    });
    offs.push(motion.spotlight(rootEl, '.gv-metrics__item'));

    return {
      destroy: function () {
        sc.destroy();
        offs.forEach(function (off) { off(); });
        digitEls.forEach(function (d) { d.el.textContent = d.display; });
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      }
    };
  }

  GV.components.metrics = { mount: mount };
})();
