/*
 * GV.components.limits — лист 10 «Готовность и ограничения».
 *   1. Таблица 5 уровней готовности версии v3.0.0 со штампами READY / CONDITIONAL / NOT READY.
 *   2. Таблица 6 известных ограничений с источниками тега v3.0.0.
 *   3. Официальная двойная графа бланка (.gv-untested.gv-box) о границах применения.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(body) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, R = C.readiness;
    var sc = kit.scope();
    var sAcc = C.src.acceptance, sLim = C.src.limits;

    body.classList.add('gv-limits');

    /* ---------- 1. Уровни готовности ---------- */
    var readyTable = h('table', { class: 'gv-env gv-ready-table' },
      h('caption', { class: 'gv-visually-hidden' }, R.levelsTitle),
      h('thead', null, h('tr', null,
        h('th', { scope: 'col' }, 'Уровень'),
        h('th', { scope: 'col' }, 'Статус'),
        h('th', { scope: 'col' }, 'Основание по приёмке v3.0.0'))),
      h('tbody', null, R.levels.map(function (lv, i) {
        return h('tr', { class: 'gv-env__row' + (lv.tone === 'alert' ? ' is-alert' : '') },
          h('th', { scope: 'row', class: 'gv-env__cond' },
            h('span', { class: 'gv-trade__n gv-num' }, '0' + (i + 1) + ' '),
            h('span', { class: 'gv-env__name' }, lv.name)),
          h('td', { class: 'gv-ready-table__st' },
            h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': lv.tone }, lv.verdict)),
          h('td', { class: 'gv-env__resp' }, lv.text));
      })));

    var readyWrap = h('div', { class: 'gv-readywrap', 'data-reveal': '' },
      h('div', { class: 'gv-envwrap__head' },
        h('h3', { class: 'gv-h3' }, R.levelsTitle),
        h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: sAcc.href }, sAcc.label))),
      readyTable);
    body.appendChild(readyWrap);
    sc.observe(u.onVisible(readyTable, function () { readyTable.classList.add('gv-stamped'); }, { once: true, threshold: 0.2 }));

    /* ---------- 2. Известные ограничения ---------- */
    var limTable = h('table', { class: 'gv-env' },
      h('caption', { class: 'gv-visually-hidden' }, R.limitsTitle),
      h('thead', null, h('tr', null,
        h('th', { scope: 'col' }, 'Ограничение'),
        h('th', { scope: 'col' }, 'Фактическое состояние'),
        h('th', { scope: 'col' }, 'Источник'))),
      h('tbody', null, R.limits.map(function (lm) {
        var sObj = C.src[lm.source];
        return h('tr', { class: 'gv-env__row' },
          h('th', { scope: 'row', class: 'gv-env__cond' },
            h('span', { class: 'gv-env__name' }, lm.title),
            h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': lm.status }, lm.statusText)),
          h('td', { class: 'gv-env__resp' }, lm.text),
          h('td', { class: 'gv-env__src' }, kit.extLink({ class: 'gv-src', href: sObj.href }, sObj.label)));
      })));

    var env = h('div', { class: 'gv-envwrap', 'data-reveal': '' },
      h('div', { class: 'gv-envwrap__head' },
        h('h3', { class: 'gv-h3' }, R.limitsTitle),
        kit.extLink({ class: 'gv-filter__b', href: sLim.href }, R.limitsLink)),
      limTable);
    body.appendChild(env);
    sc.observe(u.onVisible(limTable, function () { limTable.classList.add('gv-stamped'); }, { once: true, threshold: 0.2 }));

    /* ---------- 3. Официальная граница применения ---------- */
    body.appendChild(h('aside', { class: 'gv-untested gv-box', 'data-reveal': '' },
      h('h3', { class: 'gv-untested__t' }, R.untested.title),
      h('p', { class: 'gv-note' }, R.untested.text)));

    return { destroy: sc.destroy };
  }

  GV.components.limits = { mount: mount };
})();
