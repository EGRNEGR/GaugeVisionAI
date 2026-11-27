/*
 * GV.components.evidence — доказательная база: пять главных доказательств крупно (счётчик докручивает
 * число при появлении) и полный реестр по группам в раскрывающихся блоках; у каждой строки — контекст
 * испытания и ссылка на отчёт тега v3.0.0.
 * mount(el) → { destroy() }
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit, motion = GV.motion;
    var C = GV.content, E = C.evidence;
    var offs = [];

    var key = h('ol', { class: 'gv-proofs', role: 'list' }, E.key.map(function (k, i) {
      var sObj = C.src[k.source];
      var v = h('span', { class: 'gv-proof__v' }, k.value);
      var raw = Number(String(k.value).replace(/\s| /g, ''));
      if (isFinite(raw) && raw > 0) offs.push(motion.counter(v, { to: raw, digits: 0 }));
      return h('li', { class: 'gv-proof', style: { '--i': i }, 'data-reveal': '' },
        h('p', { class: 'gv-proof__num' }, v, h('span', { class: 'gv-proof__u' }, k.unit)),
        h('p', { class: 'gv-proof__l' }, k.label),
        kit.extLink({ class: 'gv-src', href: sObj.href }, sObj.label));
    }));

    var groups = h('div', { class: 'gv-reg' }, E.groups.map(function (g, gi) {
      return h('details', { class: 'gv-reg__group', open: gi === 0 ? true : null },
        h('summary', null, h('span', { class: 'gv-reg__gt' }, g.title), h('span', { class: 'gv-reg__gn' }, String(g.rows.length))),
        h('table', { class: 'gv-reg__table' },
          h('thead', { class: 'gv-visually-hidden' }, h('tr', null, h('th', null, 'Значение'), h('th', null, 'Что измерено'), h('th', null, 'Контекст'), h('th', null, 'Источник'))),
          h('tbody', null, g.rows.map(function (r) {
            var sObj = C.src[r.source];
            return h('tr', null,
              h('td', { class: 'gv-reg__v' }, r.value),
              h('td', { class: 'gv-reg__t' }, r.text),
              h('td', { class: 'gv-reg__c' }, r.ctx),
              h('td', { class: 'gv-reg__s' }, kit.extLink({ class: 'gv-src', href: sObj.href }, sObj.label)));
          }))));
    }));

    el.appendChild(h('div', { class: 'gv-ev' }, key,
      h('div', { class: 'gv-ev__reg' },
        h('div', { class: 'gv-ev__reg-head' },
          h('p', { class: 'gv-ev__reg-t' }, 'Полный реестр показателей'),
          kit.extLink({ class: 'gv-btn gv-btn--ghost gv-btn--s', href: C.src.acceptance.href }, 'Итоговый отчёт приёмки')),
        groups)));

    return { destroy: function () { offs.forEach(function (o) { o(); }); el.textContent = ''; } };
  }

  GV.components.evidence = { mount: mount };
})();
