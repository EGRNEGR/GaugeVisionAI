/*
 * GV.components.evolution — «Видеть. Понимать. Помогать решать.»
 * mount(el) → { destroy(), select(i) }
 * Три версии — вкладки (role="tablist", ←/→, Home/End). Над вкладками — шкала эволюции: глагол версии
 * и линия прогресса, которая доходит до выбранной версии. Панель: скриншот этой версии пульта
 * (из истории репозитория) и пять возможностей; при смене версии кадр сменяется перекрёстно.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, E = C.evolution;
    var sc = kit.scope();
    var uidp = u.uid('gv-evo');

    var tabs = E.versions.map(function (v, i) {
      return h('button', { class: 'gv-evo__tab', role: 'tab', type: 'button', id: uidp + '-t' + i, 'aria-controls': uidp + '-p' + i, 'aria-selected': i === 2 ? 'true' : 'false', tabindex: i === 2 ? '0' : '-1' },
        h('span', { class: 'gv-evo__ver' }, v.version),
        h('span', { class: 'gv-evo__verb' }, v.verb),
        h('span', { class: 'gv-evo__vt' }, v.title));
    });
    var line = h('span', { class: 'gv-evo__line-fill' });
    var tablist = h('div', { class: 'gv-evo__tabs', role: 'tablist', 'aria-label': 'Версии GaugeVision AI' }, h('span', { class: 'gv-evo__line', 'aria-hidden': 'true' }, line), tabs);
    var panels = E.versions.map(function (v, i) {
      return h('div', { class: 'gv-evo__panel', role: 'tabpanel', id: uidp + '-p' + i, 'aria-labelledby': uidp + '-t' + i, hidden: i !== 2 ? true : null, tabindex: '0' },
        h('figure', { class: 'gv-shot gv-evo__shot' },
          h('div', { class: 'gv-shot__frame' }, h('img', { src: v.img, alt: 'Пульт GaugeVision ' + v.version, loading: 'lazy', decoding: 'async' })),
          h('figcaption', null, v.caption)),
        h('div', { class: 'gv-evo__copy' },
          h('p', { class: 'gv-evo__big' }, v.version),
          h('p', { class: 'gv-evo__ptitle' }, v.title),
          h('ul', { class: 'gv-ticks', role: 'list' }, v.items.map(function (t) { return h('li', null, t); }))));
    });

    el.appendChild(h('div', { class: 'gv-evo' }, tablist, h('div', { class: 'gv-evo__panels' }, panels)));

    var roving = u.rovingTabs(tablist, {
      selector: '[role="tab"]',
      initial: 2,
      onSelect: function (i) {
        panels.forEach(function (p, k) { p.hidden = k !== i; });
        line.style.transform = 'scaleX(' + (i / (tabs.length - 1)).toFixed(3) + ')';
        tablist.setAttribute('data-sel', String(i));
      }
    });
    line.style.transform = 'scaleX(1)';
    tablist.setAttribute('data-sel', '2');

    return { destroy: function () { roving.destroy(); sc.destroy(); el.textContent = ''; }, select: function (i) { roving.select(i); } };
  }

  GV.components.evolution = { mount: mount };
})();
