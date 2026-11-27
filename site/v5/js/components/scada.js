/*
 * GV.components.scada — лист 05 «Данные в SCADA предприятия».
 * Цепочка прохождения сигнала, крупный показатель 19 / 19 (Ignition 8.3.10), список возможностей
 * строками бланка, протоколы, графа лабораторных ограничений и вклеенный снимок Ignition Perspective.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(body) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, S = C.scada;
    var srcE2e = C.src.e2e, srcScada = C.src.scada;

    var chain = h('ol', { class: 'gv-chain', role: 'list', 'data-reveal': '' }, S.chain.map(function (t, i) {
      return h('li', { class: ['gv-chain__node', i === 3 ? 'gv-chain__node--key' : null] },
        h('span', { class: 'gv-chain__n gv-num' }, String(i + 1).padStart(2, '0')),
        h('span', { class: 'gv-chain__t' }, t));
    }));

    var grid = h('div', { class: 'gv-scada__grid', 'data-reveal': '' },
      h('div', { class: 'gv-scada__copy' },
        h('p', { class: 'gv-scada__big' },
          h('span', { class: 'gv-scada__bigv gv-num' }, S.big.value),
          h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': 'done' }, C.labels.evidence)),
        h('p', { class: 'gv-scada__bigl' }, S.big.label, ' ', kit.extLink({ class: 'gv-src', href: srcE2e.href }, srcE2e.label)),
        h('ul', { class: 'gv-lines-list', role: 'list' }, S.features.map(function (f) { return h('li', null, f); })),
        h('div', { class: 'gv-scada__proto' },
          h('p', { class: 'gv-label' }, 'Протоколы обмена'),
          h('ul', { class: 'gv-tags', role: 'list' }, S.protocols.map(function (p) { return h('li', { class: 'gv-tag' }, p); }))),
        h('aside', { class: 'gv-box gv-scada__limit' },
          h('span', { class: 'gv-box__legend' }, 'Ограничение стенда'),
          h('p', null, S.limit, ' ', kit.extLink({ class: 'gv-src', href: srcScada.href }, srcScada.label)))),
      h('figure', { class: 'gv-shot gv-scada__shot' },
        h('div', { class: 'gv-shot__frame gv-plate' },
          h('img', { src: S.shot.img, alt: 'Окно Ignition Perspective с показаниями GaugeVision и трендом Tag Historian', loading: 'lazy', decoding: 'async', width: 1600, height: 900 })),
        h('figcaption', { class: 'gv-caption' },
          h('span', { class: 'gv-mark', 'data-tone': 'done' }, C.labels.real), ' ', S.shot.caption)));

    body.appendChild(h('div', { class: 'gv-scada' }, chain, grid));
    var off = u.onVisible(grid, function () { grid.classList.add('gv-stamped'); }, { once: true, threshold: 0.2 });

    return { destroy: function () { off(); body.textContent = ''; } };
  }

  GV.components.scada = { mount: mount };
})();
