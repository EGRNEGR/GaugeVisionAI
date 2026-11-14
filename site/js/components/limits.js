/*
 * GV.components.limits — инженерные компромиссы и ограничения среды цеха.
 * mount(el, { layout: 'cards'|'rows' }) → { destroy() }
 *   cards — карточки ограничений в сетке (вариант A);
 *   rows  — строки протокола с волосяными линиями.
 * Состав: «Компромиссы» (выбрали → платим; клик раскрывает «почему так» и источник в коде),
 * «Ограничения» (5 условий со статусом и фильтром по статусу), «Не проверено в поле», Roadmap.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var LAYOUTS = ['cards', 'rows'];
  var T = {
    filter: 'Фильтр по статусу',
    shown: function (n, total) { return 'Показано ограничений: ' + n + ' из ' + total; },
    arrow: '→',
    note: 'Оговорка'
  };

  function mount(el, options) {
    options = options || {};
    var u = GV.util, kit = GV.kit, h = u.h;
    var c = GV.content;
    var L = c.labels;
    var layout = kit.pick(options.layout, LAYOUTS);
    var sc = kit.scope();

    /* ---------- компромиссы ---------- */

    var tradeItems = c.tradeoffs.map(function (t, i) {
      var bodyId = u.uid('gv-trade');
      var btn = h('button', { type: 'button', class: 'gv-limits__trade-btn', 'aria-expanded': 'false', 'aria-controls': bodyId },
        h('span', { class: 'gv-limits__trade-index', 'aria-hidden': 'true' }, (i + 1 < 10 ? '0' : '') + (i + 1)),
        h('span', { class: 'gv-limits__trade-chose' },
          h('span', { class: 'gv-limits__trade-key' }, L.chose), t.chose),
        h('span', { class: 'gv-limits__trade-arrow', 'aria-hidden': 'true' }, T.arrow),
        h('span', { class: 'gv-limits__trade-cost' },
          h('span', { class: 'gv-limits__trade-key' }, L.cost), t.cost),
        h('span', { class: 'gv-limits__trade-toggle', 'aria-hidden': 'true' }));
      var body = h('div', { class: 'gv-limits__trade-body', id: bodyId, hidden: true },
        h('p', { class: 'gv-limits__trade-why' }, h('span', { class: 'gv-limits__trade-key' }, L.why), t.why),
        h('p', { class: 'gv-limits__trade-source' }, h('span', { class: 'gv-limits__trade-key' }, L.source), h('code', null, t.source)));
      sc.on(btn, 'click', function () {
        var open = btn.getAttribute('aria-expanded') !== 'true';
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        body.hidden = !open;
      });
      return h('li', { class: 'gv-limits__trade', 'data-id': t.id }, btn, body);
    });

    var trades = h('div', { class: 'gv-limits__block gv-limits__block--trades' },
      h('div', { class: 'gv-limits__block-head' },
        h('h3', { class: 'gv-limits__block-title' }, L.tradeoffsTitle),
        h('p', { class: 'gv-limits__block-lead' }, L.tradeoffsLead)),
      h('ol', { class: 'gv-limits__trades', role: 'list' }, tradeItems));

    /* ---------- ограничения с фильтром ---------- */

    var statuses = [];
    c.limits.forEach(function (l) { if (statuses.indexOf(l.status) < 0) statuses.push(l.status); });
    var filters = [{ id: 'all', label: L.filterAll }].concat(statuses.map(function (st) { return { id: st, label: L.status[st] }; }));

    var limitEls = c.limits.map(function (l) {
      return h('li', { class: 'gv-limits__item', 'data-status': l.status, 'data-id': l.id },
        h('div', { class: 'gv-limits__item-head' },
          h('h4', { class: 'gv-limits__condition' }, l.condition),
          h('span', { class: 'gv-limits__status', 'data-status': l.status }, L.status[l.status])),
        h('dl', { class: 'gv-limits__facts' },
          h('div', { class: 'gv-limits__fact' }, h('dt', null, L.risk), h('dd', null, l.risk)),
          h('div', { class: 'gv-limits__fact gv-limits__fact--response' }, h('dt', null, L.response), h('dd', null, l.response)),
          l.note ? h('div', { class: 'gv-limits__fact gv-limits__fact--note' }, h('dt', { class: 'gv-visually-hidden' }, T.note), h('dd', null, l.note)) : null));
    });

    var counts = {};
    c.limits.forEach(function (l) { counts[l.status] = (counts[l.status] || 0) + 1; });
    var filterBtns = filters.map(function (f) {
      var n = f.id === 'all' ? c.limits.length : counts[f.id];
      return h('button', { type: 'button', class: 'gv-limits__filter', 'aria-pressed': 'false', 'data-filter': f.id },
        f.label, h('span', { class: 'gv-limits__filter-count' }, String(n)));
    });
    var filterBar = h('div', { class: 'gv-limits__filters', role: 'group', 'aria-label': T.filter }, filterBtns);
    var shown = h('p', { class: 'gv-visually-hidden', 'aria-live': 'polite' });

    var limitsList = h('ul', { class: 'gv-limits__list', role: 'list' }, limitEls);
    var limitsBlock = h('div', { class: 'gv-limits__block gv-limits__block--limits' },
      h('div', { class: 'gv-limits__block-head' },
        h('h3', { class: 'gv-limits__block-title' }, L.limitsTitle),
        filterBar),
      limitsList,
      shown);

    var ready = false;
    var roving = u.rovingTabs(filterBar, {
      selector: '.gv-limits__filter',
      attr: 'aria-pressed',
      onSelect: function (i) {
        var f = filters[i].id;
        var n = 0;
        limitEls.forEach(function (li) {
          var match = f === 'all' || li.getAttribute('data-status') === f;
          li.hidden = !match;
          if (match) n += 1;
        });
        limitsList.setAttribute('data-filter', f);
        if (ready) shown.textContent = T.shown(n, limitEls.length);
      }
    });
    ready = true;
    sc.add(roving.destroy);

    /* ---------- не проверено в поле и Roadmap ---------- */

    var untested = h('div', { class: 'gv-limits__untested' },
      h('h3', { class: 'gv-limits__untested-title' }, c.untested.title),
      h('p', { class: 'gv-limits__untested-text' }, c.untested.text));

    var roadmap = h('div', { class: 'gv-limits__roadmap' },
      h('h3', { class: 'gv-limits__block-title' }, L.roadmapTitle),
      h('ol', { class: 'gv-limits__stages', role: 'list' }, c.roadmap.map(function (r) {
        return h('li', { class: 'gv-limits__stage', 'data-status': r.status },
          h('p', { class: 'gv-limits__stage-head' },
            h('span', { class: 'gv-limits__stage-index' }, r.index),
            h('span', { class: 'gv-limits__stage-title' }, r.title),
            h('span', { class: 'gv-limits__status', 'data-status': r.status }, L.status[r.status])),
          h('ul', { class: 'gv-limits__stage-items', role: 'list' }, r.items.map(function (it) { return h('li', null, it); })));
      })));

    var rootEl = h('div', { class: ['gv-limits', 'gv-limits--' + layout] },
      trades,
      limitsBlock,
      h('div', { class: 'gv-limits__after' }, untested, roadmap));
    el.appendChild(rootEl);

    return {
      destroy: function () {
        sc.destroy();
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      }
    };
  }

  GV.components.limits = { mount: mount, layouts: LAYOUTS.slice() };
})();
