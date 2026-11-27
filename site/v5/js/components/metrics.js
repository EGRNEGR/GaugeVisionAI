/*
 * GV.components.metrics — лист 08 «Протокол испытаний».
 * Пять главных доказательств v3.0.0 крупно и полный протокол по шести группам строками бланка
 * (ledger.css): №, показатель, условия и контекст, значение и ссылка на отчёт тега v3.0.0.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(body) {
    var u = GV.util, h = u.h, kit = GV.kit, motion = GV.motion;
    var C = GV.content, E = C.evidence;
    var sc = kit.scope();

    body.classList.add('gv-proto-wrap');

    var keyList = h('ol', { class: 'gv-proofs', role: 'list', 'data-reveal': '' }, E.key.map(function (k) {
      var sObj = C.src[k.source];
      var v = h('span', { class: 'gv-proof__v gv-num' }, k.value);
      var raw = Number(String(k.value).replace(/\s|\u00A0/g, ''));
      if (isFinite(raw) && raw > 0) sc.add(motion.counter(v, { to: raw, digits: 0, display: k.value, duration: 1100 }));
      return h('li', { class: 'gv-proof' },
        h('p', { class: 'gv-proof__num' }, v, h('span', { class: 'gv-proof__u' }, k.unit)),
        h('p', { class: 'gv-proof__l' }, k.label),
        kit.extLink({ class: 'gv-src', href: sObj.href }, sObj.label));
    }));

    var n = 0;
    var table = h('table', { class: 'gv-proto' },
      h('caption', { class: 'gv-visually-hidden' }, 'Полный протокол испытаний GaugeVision AI 3.0'),
      h('thead', null, h('tr', null, E.columns.map(function (col, i) {
        return h('th', { scope: 'col', class: 'gv-proto__h gv-proto__h--' + i }, col);
      }))));

    E.groups.forEach(function (g) {
      var tbody = h('tbody', { class: 'gv-proto__group' });
      tbody.appendChild(h('tr', { class: 'gv-proto__gh' }, h('th', { scope: 'colgroup', colspan: '5' }, g.title)));
      g.rows.forEach(function (r) {
        n += 1;
        var sObj = C.src[r.source];
        tbody.appendChild(h('tr', { class: r.key ? 'gv-proto__row is-key' : 'gv-proto__row' },
          h('td', { class: 'gv-proto__n gv-num' }, (n < 10 ? '0' : '') + n),
          h('th', { scope: 'row', class: 'gv-proto__label' }, r.text),
          h('td', { class: 'gv-proto__cond' }, r.ctx),
          h('td', { class: 'gv-proto__value' }, h('span', { class: 'gv-proto__v gv-num' }, r.value)),
          h('td', { class: 'gv-proto__kind' }, kit.extLink({ class: 'gv-src', href: sObj.href }, sObj.label))));
      });
      table.appendChild(tbody);
    });

    var regHead = h('div', { class: 'gv-proto__head', 'data-reveal': '' },
      h('h3', { class: 'gv-h3' }, 'Полный реестр показателей'),
      kit.extLink({ class: 'gv-filter__b', href: C.src.acceptance.href }, 'Итоговый отчёт приёмки'));

    body.appendChild(keyList);
    body.appendChild(regHead);
    body.appendChild(h('div', { class: 'gv-proto__scroll', 'data-reveal': '' }, table));

    return { destroy: sc.destroy };
  }

  GV.components.metrics = { mount: mount };
})();
