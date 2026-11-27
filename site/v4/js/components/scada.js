/*
 * GV.components.scada — «Данные там, где работает инженер».
 * mount(el) → { destroy() }
 * Цепочка «Камера → … → инженер» с бегущим импульсом (CSS), крупное доказательство 19 / 19,
 * возможности, компактный ряд протоколов, реальный скриншот Ignition Perspective и честная граница.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, S = C.scada;
    var srcE2e = C.src.e2e, srcScada = C.src.scada;

    var chain = h('ol', { class: 'gv-chain', role: 'list', 'data-reveal': '' }, S.chain.map(function (t, i) {
      return h('li', { class: ['gv-chain__node', i === 3 ? 'gv-chain__node--key' : null], style: { '--i': i } },
        h('span', { class: 'gv-chain__n' }, String(i + 1).padStart(2, '0')), h('span', { class: 'gv-chain__t' }, t));
    }));

    el.appendChild(h('div', { class: 'gv-scada' },
      chain,
      h('div', { class: 'gv-scada__grid' },
        h('div', { class: 'gv-scada__copy' },
          h('p', { class: 'gv-scada__big' }, h('span', { class: 'gv-scada__bigv', 'data-count': '' }, S.big.value)),
          h('p', { class: 'gv-scada__bigl' }, S.big.label, ' ', kit.extLink({ class: 'gv-src', href: srcE2e.href }, srcE2e.label)),
          h('ul', { class: 'gv-ticks', role: 'list' }, S.features.map(function (f) { return h('li', null, f); })),
          h('div', { class: 'gv-scada__proto' },
            h('p', { class: 'gv-scada__proto-l' }, 'Протоколы'),
            h('ul', { class: 'gv-chips', role: 'list' }, S.protocols.map(function (p) { return h('li', { class: 'gv-chip' }, p); }))),
          h('p', { class: 'gv-limit' }, S.limit, ' ', kit.extLink({ class: 'gv-src', href: srcScada.href }, srcScada.label))),
        h('figure', { class: 'gv-shot gv-shot--lift gv-scada__shot' },
          h('div', { class: 'gv-shot__frame' },
            h('img', { src: S.shot.img, alt: 'Окно Ignition Perspective с показаниями GaugeVision и трендом Tag Historian', loading: 'lazy', decoding: 'async', width: 1600, height: 900 })),
          h('figcaption', null, h('span', { class: 'gv-chip gv-chip--real' }, C.labels.real), ' ', S.shot.caption)))));

    return { destroy: function () { el.textContent = ''; } };
  }

  GV.components.scada = { mount: mount };
})();
