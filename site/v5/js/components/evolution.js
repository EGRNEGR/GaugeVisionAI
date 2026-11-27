/*
 * GV.components.evolution — лист 09 «От чтения стрелки к плану замен» (1.0 → 2.0 → 3.0).
 * mount(body) → { destroy(), select(i) }
 * Вкладки версий (roving tabindex), вклеенный снимок реального пульта (.gv-plate) со штампом
 * «Снимок реального приложения» и список возможностей строками бланка.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(body) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, E = C.evolution;
    var sc = kit.scope();
    var uidp = u.uid('gv-evo');

    var tabs = E.versions.map(function (v, i) {
      return h('button', {
        class: 'gv-evo__tab',
        role: 'tab',
        type: 'button',
        id: uidp + '-t' + i,
        'aria-controls': uidp + '-p' + i,
        'aria-selected': i === 2 ? 'true' : 'false',
        tabindex: i === 2 ? '0' : '-1'
      },
        h('span', { class: 'gv-evo__ver gv-num' }, v.version),
        h('span', { class: 'gv-evo__verb' }, v.verb),
        h('span', { class: 'gv-evo__vt' }, v.title));
    });
    var tablist = h('div', { class: 'gv-evo__tabs', role: 'tablist', 'aria-label': 'Версии GaugeVision AI' }, tabs);

    var panels = E.versions.map(function (v, i) {
      return h('div', {
        class: 'gv-evo__panel',
        role: 'tabpanel',
        id: uidp + '-p' + i,
        'aria-labelledby': uidp + '-t' + i,
        hidden: i !== 2 ? true : null,
        tabindex: '0'
      },
        h('figure', { class: 'gv-shot gv-evo__shot' },
          h('div', { class: 'gv-shot__frame gv-plate' },
            h('img', { src: v.img, alt: 'Пульт GaugeVision ' + v.version, loading: 'lazy', decoding: 'async', width: 1600, height: 900 })),
          h('figcaption', { class: 'gv-caption' },
            h('span', { class: 'gv-mark', 'data-tone': 'done' }, C.labels.real), ' ', v.caption)),
        h('div', { class: 'gv-evo__copy' },
          h('p', { class: 'gv-evo__big gv-num' }, 'v' + v.version),
          h('h3', { class: 'gv-h3' }, v.title),
          h('ul', { class: 'gv-lines-list', role: 'list' }, v.items.map(function (t) { return h('li', null, t); }))));
    });

    body.appendChild(h('div', { class: 'gv-evo', 'data-reveal': '' }, tablist, h('div', { class: 'gv-evo__panels' }, panels)));

    var roving = u.rovingTabs(tablist, {
      selector: '[role="tab"]',
      initial: 2,
      onSelect: function (i) {
        panels.forEach(function (p, k) { p.hidden = k !== i; });
      }
    });

    return {
      destroy: function () { roving.destroy(); sc.destroy(); body.textContent = ''; },
      select: function (i) { roving.select(i); }
    };
  }

  GV.components.evolution = { mount: mount };
})();
