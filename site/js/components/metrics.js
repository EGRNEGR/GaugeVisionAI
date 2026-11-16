/*
 * GV.components.metrics — подтверждённые метрики с условиями замера, по группам.
 * mount(el, { ids?: [id…], note?: true }) → { destroy() }
 *
 * Группы — labels.metricGroups по порядку (точность · скорость · масштаб); у каждой слева метка группы
 * и вид данных («замер» / «расчёт»), справа записи группы. Точность и скорость — карточки с крупной
 * моноширинной цифрой. Масштаб — горизонтальные столбцы в одной шкале (к/с): замер залит акцентом,
 * расчёт заштрихован, у каждой строки метка «замер» или «расчёт» — 50 и 100 камер не выдаются за замер.
 * Столбцы вырастают scaleX при первом показе (data-reveal → .is-in, css/components.css).
 * Цифры докручиваются от нуля GV.motion.counter (≈ 1,2 с); конечный текст — точная строка
 * metrics[].display. Для диапазона «30–100» и пары «1,00 / 1,00» растут все числа записи.
 * Ободок карточки ловит свет курсора (GV.motion.spotlight). Читающим экран — готовая запись без счётчика.
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
    var L = c.labels;
    var sc = kit.scope();
    var offs = [];
    var list = c.metrics.filter(function (m) { return !options.ids || options.ids.indexOf(m.id) >= 0; });
    if (options.ids) list.sort(function (a, b) { return options.ids.indexOf(a.id) - options.ids.indexOf(b.id); });

    var digitEls = [];

    function digits(m) {
      var d = h('span', {
        class: ['gv-metrics__digits', m.display.length > 7 ? 'gv-metrics__digits--long' : null],
        'aria-hidden': 'true',
        style: { minWidth: m.display.length + 'ch' }
      }, m.display);
      digitEls.push({ el: d, display: m.display });
      return d;
    }

    function figure(m, extra) {
      return h('dd', { class: 'gv-metrics__figure' },
        digits(m),
        h('span', { class: 'gv-visually-hidden' }, m.display + (m.unit ? kit.NBSP + m.unit : '') + ', ' + L.kind[m.kind]),
        m.unit ? h('span', { class: 'gv-metrics__unit', 'aria-hidden': 'true' }, m.unit) : null,
        extra || null);
    }

    function kindTag(kind) {
      return h('span', { class: 'gv-metrics__kind', 'data-kind': kind, 'aria-hidden': 'true' }, L.kind[kind]);
    }

    function card(m) {
      // dt идёт первым (порядок dl), цифра встаёт наверх через order в css
      return h('div', { class: 'gv-metrics__item', 'data-kind': m.kind, 'data-id': m.id },
        h('dt', { class: 'gv-metrics__label' }, m.label),
        figure(m),
        h('dd', { class: 'gv-metrics__condition' }, m.condition));
    }

    /* Столбцы масштаба: доля от наибольшего значения группы задаёт ширину, рост — scaleX */
    function bars(items) {
      var max = items.reduce(function (a, m) { return Math.max(a, Number(m.value) || 0); }, 0) || 1;
      return h('dl', { class: 'gv-metrics__bars', 'data-reveal': '' }, items.map(function (m, i) {
        var share = Math.max(0.02, (Number(m.value) || 0) / max);
        return h('div', { class: 'gv-metrics__row', 'data-kind': m.kind, 'data-id': m.id, style: { '--i': String(i) } },
          h('dt', { class: 'gv-metrics__label' }, m.label),
          figure(m, kindTag(m.kind)),
          h('dd', { class: 'gv-metrics__bar', 'aria-hidden': 'true' },
            h('span', { class: 'gv-metrics__bar-fill', style: { width: (share * 100).toFixed(2) + '%' } })),
          h('dd', { class: 'gv-metrics__condition' }, m.condition));
      }));
    }

    var groupIds = Object.keys(L.metricGroups || {});
    var leftovers = list.filter(function (m) { return groupIds.indexOf(m.group) < 0; });
    var groups = groupIds.map(function (gid) {
      var items = list.filter(function (m) { return m.group === gid; });
      if (!items.length) return null;
      var kinds = [];
      items.forEach(function (m) { if (kinds.indexOf(m.kind) < 0) kinds.push(m.kind); });
      var isScale = gid === 'scale';
      return h('section', { class: ['gv-metrics__group', 'gv-metrics__group--' + gid], 'aria-labelledby': 'gv-metrics-' + gid },
        h('header', { class: 'gv-metrics__group-head' },
          h('h3', { class: 'gv-metrics__group-title', id: 'gv-metrics-' + gid }, L.metricGroups[gid]),
          h('p', { class: 'gv-metrics__group-kinds' }, kinds.map(kindTag))),
        isScale ? bars(items) : h('dl', { class: 'gv-metrics__list' }, items.map(card)));
    });
    if (leftovers.length) groups.push(h('dl', { class: 'gv-metrics__list' }, leftovers.map(card)));

    var rootEl = h('div', { class: 'gv-metrics gv-metrics--dial' }, groups);
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
