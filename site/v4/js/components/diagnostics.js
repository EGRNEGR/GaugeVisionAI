/*
 * GV.components.diagnostics — «Понимание, что происходит с оборудованием».
 * mount(el) → { destroy() }
 * Три класса причин (процесс / прибор / оптика) и настоящий экран «Диспетчеризация и ТЗ» с метками:
 * метка — кнопка поверх скриншота (позиции в долях кадра), её описание — в списке справа; выбор метки
 * подсвечивает пункт и наоборот. ←/→ по меткам, одна активна всегда.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var C = GV.content, D = C.diagnostics;
    var sc = kit.scope();
    var active = 0;

    var causes = h('ul', { class: 'gv-causes', role: 'list' }, D.causes.map(function (cz, i) {
      return h('li', { class: 'gv-cause gv-cause--' + cz.tone, 'data-reveal': '', style: { '--i': i } },
        h('span', { class: 'gv-cause__dot', 'aria-hidden': 'true' }),
        h('p', { class: 'gv-cause__t' }, cz.title), h('p', { class: 'gv-cause__x' }, cz.text));
    }));

    var marks = D.hotspots.map(function (hs, i) {
      return h('button', { class: 'gv-hot', type: 'button', style: { left: (hs.x * 100) + '%', top: (hs.y * 100) + '%' }, 'aria-label': hs.title, 'data-i': i },
        h('span', { class: 'gv-hot__n' }, String(i + 1)));
    });
    var notes = D.hotspots.map(function (hs, i) {
      return h('li', { class: 'gv-hotlist__item', 'data-i': i },
        h('button', { class: 'gv-hotlist__btn', type: 'button' },
          h('span', { class: 'gv-hotlist__n' }, String(i + 1)),
          h('span', null, h('span', { class: 'gv-hotlist__t' }, hs.title), h('span', { class: 'gv-hotlist__x' }, hs.text))));
    });

    var shot = h('figure', { class: 'gv-shot gv-diag__shot' },
      h('div', { class: 'gv-shot__frame gv-diag__frame' },
        h('img', { src: D.shot.img, alt: 'Экран диспетчеризации GaugeVision: матрица Health Score, причины, очередь рекомендаций и прогноз', loading: 'lazy', decoding: 'async', width: 1600, height: 900 }),
        marks),
      h('figcaption', null, h('span', { class: 'gv-chip gv-chip--real' }, C.labels.record), ' ', D.shot.caption));

    el.appendChild(h('div', { class: 'gv-diag' }, causes,
      h('div', { class: 'gv-diag__grid' }, shot, h('ol', { class: 'gv-hotlist', role: 'list' }, notes))));

    function select(i) {
      active = (i + marks.length) % marks.length;
      marks.forEach(function (m, k) { m.toggleAttribute('data-on', k === active); m.setAttribute('aria-pressed', k === active ? 'true' : 'false'); });
      notes.forEach(function (n, k) { n.toggleAttribute('data-on', k === active); });
    }
    marks.forEach(function (m, i) {
      sc.on(m, 'click', function () { select(i); });
      sc.on(m, 'keydown', function (e) {
        if (e.key === 'ArrowRight') { select(active + 1); marks[active].focus(); e.preventDefault(); }
        if (e.key === 'ArrowLeft') { select(active - 1); marks[active].focus(); e.preventDefault(); }
      });
    });
    notes.forEach(function (n, i) { sc.on(n.querySelector('button'), 'click', function () { select(i); }); sc.on(n, 'mouseenter', function () { select(i); }); });
    select(0);

    return { destroy: function () { sc.destroy(); el.textContent = ''; } };
  }

  GV.components.diagnostics = { mount: mount };
})();
