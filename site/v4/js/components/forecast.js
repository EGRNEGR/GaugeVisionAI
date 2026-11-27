/*
 * GV.components.forecast — «Видеть, куда идёт показание».
 * mount(el) → { destroy(), play() }
 * Крупный график GV.draw.forecastChart по параметрам E2E прогона 5. При первом появлении прогноз
 * проявляется слева направо за 2,4 с (наблюдения → линия прогноза → область неопределённости → ETA),
 * затем появляется событие «скоро уставка». Кнопка «Повторить». Легенда, три цифры, контекст испытания
 * и раскрываемый экспертный блок с валидацией на реальных данных и её ограничениями.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var W = 1100, H = 520, DUR = 2400;

  function mount(el) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit, motion = GV.motion;
    var C = GV.content, F = C.forecastSection;
    var sc = kit.scope();

    var chart = GV.draw.forecastChart({ w: W, h: H, f: C.forecast, compact: false, reveal: motion.reduced() ? 1 : 0 });
    var svg = s('svg', { class: 'gv-fcw__svg', viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Прогноз давления PI-102: наблюдения, линия прогноза, область неопределённости, аварийная уставка, ожидаемое время ' + u.formatNumber(C.forecast.eta, 2) + ' мин при фактическом ' + u.formatNumber(C.forecast.etaTrue, 1) + ' мин' }, chart.el);
    var event = h('div', { class: 'gv-fcw__event', role: 'status' },
      h('span', { class: 'gv-fcw__event-dot', 'aria-hidden': 'true' }),
      h('span', null, h('strong', null, 'PI-102: скоро аварийная уставка. '), F.event));
    var replay = h('button', { class: 'gv-btn gv-btn--ghost gv-btn--s', type: 'button' }, 'Повторить');
    var legend = h('ul', { class: 'gv-legend', role: 'list' },
      [['obs', F.legend.observed], ['model', F.legend.model], ['band', F.legend.band], ['alert', F.legend.alert], ['warn', F.legend.warn], ['eta', F.legend.eta], ['fact', F.legend.fact]].map(function (l) {
        return h('li', { class: 'gv-legend__i gv-legend__i--' + l[0] }, l[1]);
      }));
    var stats = h('dl', { class: 'gv-fcw__stats' }, F.stats.map(function (st) {
      return h('div', null, h('dt', null, st.value), h('dd', null, st.label));
    }));
    var srcE = C.src.e2e, srcP = C.src[F.expert.source];
    var expert = h('details', { class: 'gv-details' },
      h('summary', null, F.expert.title),
      h('ul', { role: 'list' }, F.expert.items.map(function (t) { return h('li', null, t); })),
      h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: srcP.href }, srcP.label)));

    var box = h('div', { class: 'gv-fcw', 'data-done': motion.reduced() ? '' : null },
      h('div', { class: 'gv-fcw__chart' },
        h('div', { class: 'gv-fcw__bar' }, h('span', { class: 'gv-chip gv-chip--evidence' }, 'E2E прогон 5'), h('span', { class: 'gv-fcw__code' }, 'PI-102, 0–1,6 МПа'), replay),
        svg, legend, event),
      h('div', { class: 'gv-fcw__side' }, stats,
        h('p', { class: 'gv-cap' }, F.context, ' ', kit.extLink({ class: 'gv-src', href: srcE.href }, srcE.label)),
        expert));
    el.appendChild(box);

    var stop = null;
    function play() {
      if (stop) stop();
      box.removeAttribute('data-done');
      if (motion.reduced()) { chart.setReveal(1); box.setAttribute('data-done', ''); return; }
      chart.setReveal(0);
      var t0 = null;
      stop = motion.onFrame(function (dt, now) {
        t0 = t0 || now;
        var k = Math.min(1, (now - t0) / DUR);
        chart.setReveal(1 - Math.pow(1 - k, 2.2));
        if (k >= 1) { stop(); stop = null; box.setAttribute('data-done', ''); }
      });
    }
    sc.on(replay, 'click', play);
    sc.add(u.onVisible(svg, function (vis) { if (vis) play(); }, { once: true, threshold: 0.45 }));
    sc.add(function () { if (stop) stop(); });

    return { destroy: function () { sc.destroy(); el.textContent = ''; }, play: play };
  }

  GV.components.forecast = { mount: mount };
})();
