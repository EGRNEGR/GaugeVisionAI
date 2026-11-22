/*
 * GV.components.limits — лист 07 «Компромиссы, ограничения и план».
 *   Компромиссы — строки журнала «выбрали → платим»; строка раскрывается: почему так и где в коде.
 *   Раскрытие без скачка — GV.motion.shiftBelow: строки ниже доезжают transform.
 *   Ограничения среды — таблица «условие и штамп статуса · риск · ответ в коде»; фильтр по статусу.
 *   «Не проверено в поле» — пометка рукой; план — три листа 01–03 со штампами статуса.
 *
 *   mount(body) → { destroy }
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  function mount(body) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var L = c.labels;
    var sc = kit.scope();

    body.classList.add('gv-limits');

    /* ---------- компромиссы ---------- */

    var trade = h('div', { class: 'gv-trade', 'data-reveal': '' },
      h('div', { class: 'gv-trade__head' },
        h('h3', { class: 'gv-h3' }, L.tradeoffsTitle),
        h('p', { class: 'gv-label' }, L.tradeoffsLead)),
      h('div', { class: 'gv-trade__cols', 'aria-hidden': 'true' },
        h('span', { class: 'gv-label' }, L.chose), h('span', { class: 'gv-label' }, L.cost)));
    var tradeList = h('ol', { class: 'gv-trade__list', role: 'list' });
    c.tradeoffs.forEach(function (t, i) {
      var id = 'gv-trade-' + t.id;
      var detail = h('div', { class: 'gv-trade__detail', id: id, hidden: true },
        h('p', null, h('span', { class: 'gv-label' }, L.why), t.why),
        h('p', null, h('span', { class: 'gv-label' }, L.source), h('code', null, t.source)));
      var btn = h('button', { class: 'gv-trade__row', type: 'button', 'aria-expanded': 'false', 'aria-controls': id },
        h('span', { class: 'gv-trade__n gv-num' }, (i < 9 ? '0' : '') + (i + 1)),
        h('span', { class: 'gv-trade__chose' }, h('span', { class: 'gv-visually-hidden' }, L.chose + ': '), t.chose),
        h('span', { class: 'gv-trade__cost' }, h('span', { class: 'gv-visually-hidden' }, L.cost + ': '), t.cost),
        h('span', { class: 'gv-trade__pm', 'aria-hidden': 'true' }));
      sc.on(btn, 'click', function () {
        var open = btn.getAttribute('aria-expanded') !== 'true';
        motion.shiftBelow(btn.parentNode, function () {
          btn.setAttribute('aria-expanded', open ? 'true' : 'false');
          detail.hidden = !open;
        }, body);
      });
      tradeList.appendChild(h('li', { class: 'gv-trade__item' }, btn, detail));
    });
    trade.appendChild(tradeList);
    body.appendChild(trade);

    /* ---------- ограничения среды ---------- */

    var counts = { all: c.limits.length, done: 0, partial: 0 };
    c.limits.forEach(function (l) { counts[l.status] += 1; });
    var filters = h('div', { class: 'gv-filter', role: 'group', 'aria-label': L.filterLabel },
      [['all', L.filterAll], ['done', L.status.done], ['partial', L.status.partial]].map(function (f) {
        return h('button', { class: 'gv-filter__b', type: 'button', 'data-filter': f[0], 'aria-pressed': 'false' },
          f[1], h('span', { class: 'gv-filter__n gv-num' }, String(counts[f[0]])));
      }));

    var rows = [];
    var table = h('table', { class: 'gv-env' },
      h('caption', { class: 'gv-visually-hidden' }, L.limitsTitle),
      h('thead', null, h('tr', null,
        h('th', { scope: 'col' }, L.condition), h('th', { scope: 'col' }, L.risk), h('th', { scope: 'col' }, L.response))),
      h('tbody', null, c.limits.map(function (l) {
        var tr = h('tr', { class: 'gv-env__row', 'data-status': l.status },
          h('th', { scope: 'row', class: 'gv-env__cond' }, h('span', { class: 'gv-env__name' }, l.condition),
            h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': l.status }, L.status[l.status])),
          h('td', { class: 'gv-env__risk' }, l.risk),
          h('td', { class: 'gv-env__resp' }, l.response, l.note ? h('span', { class: 'gv-env__note' }, l.note) : null));
        rows.push(tr);
        return tr;
      })));

    var env = h('div', { class: 'gv-envwrap', 'data-reveal': '' },
      h('div', { class: 'gv-envwrap__head' }, h('h3', { class: 'gv-h3' }, L.limitsTitle), filters),
      table);
    body.appendChild(env);

    u.rovingTabs(filters, {
      selector: '.gv-filter__b',
      attr: 'aria-pressed',
      onSelect: function (i, el) {
        var f = el.getAttribute('data-filter');
        rows.forEach(function (tr) { tr.hidden = f !== 'all' && tr.getAttribute('data-status') !== f; });
      }
    });
    sc.observe(u.onVisible(table, function () { table.classList.add('gv-stamped'); }, { once: true, threshold: 0.2 }));

    /* ---------- не проверено в поле ---------- */

    body.appendChild(h('aside', { class: 'gv-untested', 'data-reveal': '' },
      h('h3', { class: 'gv-untested__t' }, c.untested.title),
      h('p', { class: 'gv-note' }, c.untested.text)));

    /* ---------- план ---------- */

    var plan = h('div', { class: 'gv-plan', 'data-reveal': '' },
      h('h3', { class: 'gv-h3 gv-plan__title' }, L.roadmapTitle),
      h('ol', { class: 'gv-plan__list', role: 'list' }, c.roadmap.map(function (r) {
        return h('li', { class: 'gv-plan__item gv-plan__item--' + r.status },
          h('p', { class: 'gv-plan__head' },
            h('span', { class: 'gv-plan__i gv-num' }, r.index),
            h('span', { class: 'gv-plan__name' }, r.title),
            h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': r.status }, L.status[r.status])),
          h('ul', { class: 'gv-plan__items', role: 'list' }, r.items.map(function (it) { return h('li', null, it); })));
      })));
    body.appendChild(plan);
    sc.observe(u.onVisible(plan, function () { plan.classList.add('gv-stamped'); }, { once: true, threshold: 0.3 }));

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.limits = { mount: mount };
})();
