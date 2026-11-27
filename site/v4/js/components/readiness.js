/*
 * GV.components.readiness — пять уровней готовности (лестница: высота ступени — уровень, цвет — вердикт)
 * и известные ограничения карточками с ссылкой на полный список KNOWN_LIMITATIONS.
 * mount(el) → { destroy() }
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, R = C.readiness;
    var sAcc = C.src.acceptance, sLim = C.src.limits;

    var ladder = h('ol', { class: 'gv-ladder', role: 'list', 'data-reveal': '' }, R.levels.map(function (lv, i) {
      return h('li', { class: 'gv-ladder__step gv-ladder__step--' + lv.tone, style: { '--i': i, '--lv': (i + 1) / R.levels.length } },
        h('span', { class: 'gv-ladder__bar', 'aria-hidden': 'true' }),
        h('span', { class: 'gv-ladder__n' }, String(i + 1)),
        h('p', { class: 'gv-ladder__name' }, lv.name),
        h('p', { class: 'gv-ladder__verdict' }, lv.verdict),
        h('p', { class: 'gv-ladder__text' }, lv.text));
    }));

    var limits = h('ul', { class: 'gv-limits', role: 'list' }, R.limits.map(function (lm, i) {
      return h('li', { class: 'gv-limits__item', style: { '--i': i }, 'data-reveal': '' },
        h('p', { class: 'gv-limits__t' }, lm.title), h('p', { class: 'gv-limits__x' }, lm.text));
    }));

    el.appendChild(h('div', { class: 'gv-ready' }, ladder,
      h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: sAcc.href }, sAcc.label)),
      h('div', { class: 'gv-ready__limits' },
        h('div', { class: 'gv-ready__lhead' },
          h('h3', { class: 'gv-ready__lt' }, 'Известные ограничения'),
          kit.extLink({ class: 'gv-btn gv-btn--ghost gv-btn--s', href: sLim.href }, R.limitsLink)),
        limits)));

    return { destroy: function () { el.textContent = ''; } };
  }

  GV.components.readiness = { mount: mount };
})();
