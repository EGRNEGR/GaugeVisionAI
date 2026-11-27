/*
 * GV.components.forecast — лист 06 «Причины отклонений и прогноз».
 * mount(body) → { destroy(), play() }
 *   1. Диагностика: 3 класса причин строками бланка + вклеенный снимок «Диспетчеризация и ТЗ»
 *      с 5 интерактивными метками (Health Score, скорость, причина, очередь, прогноз).
 *   2. Прогноз: чертёж графика GV.draw.forecastChart на миллиметровке (E2E прогон 5: 13,18 против 12,7 мин),
 *      кнопка «Повторить», три показателя, строка события и раскрываемая научная валидация
 *      на реальных данных (полнота 4,65 %, ложные срабатывания 36,1 %).
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var W = 1100, H = 520, DUR = 2400;

  function mount(body) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit, motion = GV.motion;
    var C = GV.content, D = C.diagnostics, F = C.forecastSection;
    var sc = kit.scope();

    /* ---------- 1. Диагностика ---------- */

    var active = 0;
    var causes = h('table', { class: 'gv-causes-table', 'data-reveal': '' },
      h('caption', { class: 'gv-visually-hidden' }, D.title),
      h('tbody', null, D.causes.map(function (cz) {
        return h('tr', null,
          h('td', { class: 'gv-causes-table__stamp' }, h('span', { class: 'gv-mark', 'data-tone': cz.tone }, cz.label)),
          h('th', { scope: 'row', class: 'gv-causes-table__t' }, cz.title),
          h('td', { class: 'gv-causes-table__x' }, cz.text));
      })));

    var marks = D.hotspots.map(function (hs, i) {
      return h('button', {
        class: 'gv-hot',
        type: 'button',
        style: { left: (hs.x * 100) + '%', top: (hs.y * 100) + '%' },
        'aria-label': hs.title,
        'data-i': i
      }, h('span', { class: 'gv-hot__n gv-num' }, String(i + 1)));
    });
    var notes = D.hotspots.map(function (hs, i) {
      return h('li', { class: 'gv-hotlist__item', 'data-i': i },
        h('button', { class: 'gv-hotlist__btn', type: 'button' },
          h('span', { class: 'gv-hotlist__n gv-num' }, '0' + (i + 1)),
          h('span', { class: 'gv-hotlist__body' },
            h('span', { class: 'gv-hotlist__t' }, hs.title),
            h('span', { class: 'gv-hotlist__x' }, hs.text))));
    });

    var shot = h('figure', { class: 'gv-shot gv-diag__shot' },
      h('div', { class: 'gv-shot__frame gv-plate gv-diag__frame' },
        h('img', { src: D.shot.img, alt: 'Вкладка «Диспетчеризация и ТЗ» пульта GaugeVision 3.0', loading: 'lazy', decoding: 'async', width: 1600, height: 900 }),
        marks),
      h('figcaption', { class: 'gv-caption' },
        h('span', { class: 'gv-mark', 'data-tone': 'done' }, C.labels.real), ' ', D.shot.caption));

    var diagBlock = h('div', { class: 'gv-diag', id: 'diagnostics' },
      h('h3', { class: 'gv-h3 gv-subhead' }, D.title),
      causes,
      h('div', { class: 'gv-diag__grid', 'data-reveal': '' }, shot, h('ol', { class: 'gv-hotlist', role: 'list' }, notes)));

    function select(i) {
      active = (i + marks.length) % marks.length;
      marks.forEach(function (m, k) {
        m.toggleAttribute('data-on', k === active);
        m.setAttribute('aria-pressed', k === active ? 'true' : 'false');
      });
      notes.forEach(function (n, k) { n.toggleAttribute('data-on', k === active); });
    }
    marks.forEach(function (m, i) {
      sc.on(m, 'click', function () { select(i); });
      sc.on(m, 'keydown', function (e) {
        if (e.key === 'ArrowRight') { select(active + 1); marks[active].focus(); e.preventDefault(); }
        if (e.key === 'ArrowLeft') { select(active - 1); marks[active].focus(); e.preventDefault(); }
      });
    });
    notes.forEach(function (n, i) {
      sc.on(n.querySelector('button'), 'click', function () { select(i); });
      sc.on(n, 'mouseenter', function () { select(i); });
    });
    select(0);

    /* ---------- 2. Прогноз ---------- */

    var chart = GV.draw.forecastChart({ w: W, h: H, f: C.forecast, compact: false, reveal: motion.reduced() ? 1 : 0 });
    var svg = s('svg', {
      class: 'gv-fcw__svg',
      viewBox: '0 0 ' + W + ' ' + H,
      role: 'img',
      'aria-label': 'Прогноз давления PI-102: 13,18 мин до аварийной уставки HH при фактических 12,7 мин'
    }, chart.el);
    var event = h('div', { class: 'gv-fcw__event', role: 'status' },
      h('span', { class: 'gv-mark', 'data-tone': 'warning' }, 'Предупреждение'),
      h('span', null, h('strong', null, 'PI-102: скоро аварийная уставка HH. '), F.event));
    var replay = h('button', { class: 'gv-filter__b', type: 'button' }, 'Повторить');
    var legend = h('ul', { class: 'gv-legend', role: 'list' },
      [['obs', F.legend.observed], ['model', F.legend.model], ['band', F.legend.band], ['alert', F.legend.alert], ['warn', F.legend.warn], ['eta', F.legend.eta], ['fact', F.legend.fact]].map(function (l) {
        return h('li', { class: 'gv-legend__i gv-legend__i--' + l[0] }, l[1]);
      }));
    var stats = h('dl', { class: 'gv-fcw__stats' }, F.stats.map(function (st) {
      return h('div', { class: 'gv-fcw__st' }, h('dt', { class: 'gv-num' }, st.value), h('dd', null, st.label));
    }));
    var srcE = C.src.e2e, srcP = C.src[F.expert.source];
    var expert = h('details', { class: 'gv-details', open: true },
      h('summary', null, F.expert.title),
      h('ul', { class: 'gv-lines-list', role: 'list' }, F.expert.items.map(function (t) { return h('li', null, t); })),
      h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: srcP.href }, srcP.label)));

    var fcBox = h('div', { class: 'gv-fcw', 'data-done': motion.reduced() ? '' : null, 'data-reveal': '' },
      h('h3', { class: 'gv-h3 gv-subhead' }, F.title),
      h('div', { class: 'gv-fcw__grid' },
        h('div', { class: 'gv-fcw__chart gv-graph-sheet' },
          h('div', { class: 'gv-fcw__bar' },
            h('span', { class: 'gv-mark', 'data-tone': 'done' }, C.labels.evidence),
            h('span', { class: 'gv-label' }, 'E2E прогон 5, PI-102 (0–1,6 МПа)'),
            replay),
          svg, legend, event),
        h('div', { class: 'gv-fcw__side' },
          stats,
          h('p', { class: 'gv-caption' }, F.context, ' ', kit.extLink({ class: 'gv-src', href: srcE.href }, srcE.label)),
          expert)));

    body.appendChild(diagBlock);
    body.appendChild(fcBox);

    var stop = null;
    function play() {
      if (stop) stop();
      fcBox.removeAttribute('data-done');
      if (motion.reduced()) { chart.setReveal(1); fcBox.setAttribute('data-done', ''); return; }
      chart.setReveal(0);
      var t0 = null;
      stop = motion.onFrame(function (dt, now) {
        t0 = t0 || now;
        var k = Math.min(1, (now - t0) / DUR);
        chart.setReveal(1 - Math.pow(1 - k, 2.2));
        if (k >= 1) { stop(); stop = null; fcBox.setAttribute('data-done', ''); }
      });
    }
    sc.on(replay, 'click', play);
    sc.add(u.onVisible(svg, function (vis) { if (vis) play(); }, { once: true, threshold: 0.35 }));
    sc.add(function () { if (stop) stop(); });

    return { destroy: function () { sc.destroy(); body.textContent = ''; }, play: play };
  }

  GV.components.forecast = { mount: mount };
})();
