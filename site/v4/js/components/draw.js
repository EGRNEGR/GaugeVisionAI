/*
 * GV.draw — общая векторная графика страницы (SVG, без DOM-состояния).
 *   valueToAngle(v, min, max, θmin=135, sweep=270) → градусы экрана (0° — «3 часа», по часовой)
 *   gauge({ r, min, max, value, unit, ticks, label, warn, alert, face }) → <g> прибора с центром в (0,0)
 *     .setValue(v) — повернуть стрелку
 *   forecastModel(f) → { observed:[[t,v]], model(t), band80(t), band95(t), tEnd }  по параметрам E2E прогона 5
 *   forecastChart({ w, h, f, compact }) → { el, setReveal(p) }  — тренд, прогноз, область неопределённости,
 *     уставки и отметки ETA; setReveal(0..1) проявляет прогноз слева направо
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});

  function valueToAngle(v, min, max, a0, sweep) {
    a0 = a0 === undefined ? 135 : a0;
    sweep = sweep === undefined ? 270 : sweep;
    var t = (v - min) / (max - min);
    t = t < 0 ? 0 : (t > 1 ? 1 : t);
    return a0 + t * sweep;
  }

  function fmt(v, d) { return GV.util.formatNumber(v, d); }

  function niceStep(span) {
    var raw = span / 8;
    var p = Math.pow(10, Math.floor(Math.log10(raw)));
    var m = raw / p;
    return (m < 1.5 ? 1 : (m < 3.5 ? 2 : (m < 7.5 ? 5 : 10))) * p;
  }

  function gauge(o) {
    var s = GV.util.svg, kit = GV.kit;
    var r = o.r || 100;
    var min = o.min, max = o.max;
    var major = o.major || niceStep(max - min);
    var minor = major / 5;
    var g = s('g', { class: ['gv-g', o.cls || null] });
    g.appendChild(s('circle', { class: 'gv-g__rim', r: r }));
    g.appendChild(s('circle', { class: 'gv-g__rim-in', r: r * 0.94 }));
    g.appendChild(s('circle', { class: 'gv-g__face', r: r * 0.9 }));
    // Зоны уставок: H (предупреждение) и HH (авария) — дуги у края шкалы
    if (o.warn !== undefined) {
      g.appendChild(s('path', { class: 'gv-g__zone gv-g__zone--warn', d: kit.arcPath(0, 0, r * 0.8, valueToAngle(o.warn, min, max), valueToAngle(o.alert !== undefined ? o.alert : max, min, max)) , 'stroke-width': r * 0.05 }));
    }
    if (o.alert !== undefined) {
      g.appendChild(s('path', { class: 'gv-g__zone gv-g__zone--alert', d: kit.arcPath(0, 0, r * 0.8, valueToAngle(o.alert, min, max), valueToAngle(max, min, max)), 'stroke-width': r * 0.05 }));
    }
    var n = Math.round((max - min) / minor);
    var ticks = [];
    for (var i = 0; i <= n; i++) {
      var v = min + i * minor;
      var a = valueToAngle(v, min, max) * Math.PI / 180;
      var isMajor = Math.abs((v - min) / major - Math.round((v - min) / major)) < 1e-6;
      var r0 = r * (isMajor ? 0.7 : 0.76);
      var r1 = r * 0.84;
      ticks.push('M' + (Math.cos(a) * r0).toFixed(2) + ' ' + (Math.sin(a) * r0).toFixed(2) + 'L' + (Math.cos(a) * r1).toFixed(2) + ' ' + (Math.sin(a) * r1).toFixed(2));
      if (isMajor && o.labels !== false) {
        var rl = r * 0.56;
        var digits = major < 1 ? (major < 0.1 ? 2 : 1) : 0;
        g.appendChild(s('text', { class: 'gv-g__num', x: (Math.cos(a) * rl).toFixed(1), y: (Math.sin(a) * rl).toFixed(1), 'font-size': (r * 0.12).toFixed(1) }, fmt(v, digits)));
      }
    }
    g.appendChild(s('path', { class: 'gv-g__ticks', d: ticks.join(''), 'stroke-width': Math.max(1, r * 0.012) }));
    if (o.unit) g.appendChild(s('text', { class: 'gv-g__unit', x: 0, y: (r * 0.36).toFixed(1), 'font-size': (r * 0.12).toFixed(1) }, o.unit));
    if (o.label) g.appendChild(s('text', { class: 'gv-g__label', x: 0, y: (r * 0.56).toFixed(1), 'font-size': (r * 0.09).toFixed(1) }, o.label));
    var needle = s('g', { class: 'gv-g__needle' },
      s('path', { d: 'M' + (-r * 0.14) + ' ' + (-r * 0.025) + 'L' + (r * 0.74) + ' -1L' + (r * 0.74) + ' 1L' + (-r * 0.14) + ' ' + (r * 0.025) + 'Z' }));
    g.appendChild(needle);
    g.appendChild(s('circle', { class: 'gv-g__hub', r: r * 0.07 }));
    g.appendChild(s('circle', { class: 'gv-g__glass', r: r * 0.9 }));
    g.setValue = function (val) {
      needle.setAttribute('transform', 'rotate(' + valueToAngle(val, min, max).toFixed(2) + ')');
    };
    g.angleFor = function (val) { return valueToAngle(val, min, max); };
    g.setValue(o.value === undefined ? min : o.value);
    return g;
  }

  /* Детерминированный шум: одинаковый рисунок при каждой загрузке. */
  function noise(i) {
    var x = Math.sin(i * 12.9898 + 78.233) * 43758.5453;
    return (x - Math.floor(x)) - 0.5;
  }

  function forecastModel(f) {
    var obsStart = -(f.now - f.start) / f.slopeTrue;
    var observed = [];
    var n = 16;
    for (var i = 0; i <= n; i++) {
      var t = obsStart + (i / n) * (0 - obsStart);
      observed.push([t, f.start + f.slopeTrue * (t - obsStart) + noise(i) * 0.006]);
    }
    observed[observed.length - 1][1] = f.now;
    var k80 = f.pi80Half60 / Math.sqrt(60);
    var k95 = f.pi95Half60 / Math.sqrt(60);
    return {
      obsStart: obsStart,
      observed: observed,
      model: function (t) { return f.now + f.slopeModel * t; },
      band80: function (t) { return k80 * Math.sqrt(Math.max(0, t)); },
      band95: function (t) { return k95 * Math.sqrt(Math.max(0, t)); },
      tEnd: 17
    };
  }

  function forecastChart(o) {
    var s = GV.util.svg;
    var f = o.f;
    var M = forecastModel(f);
    var W = o.w, H = o.h;
    var pad = o.compact ? { l: 46, r: 16, t: 18, b: 30 } : { l: 64, r: 28, t: 28, b: 46 };
    var t0 = Math.floor(M.obsStart) - 1, t1 = M.tEnd;
    var v0 = 1.15, v1 = 1.46;
    function X(t) { return pad.l + (t - t0) / (t1 - t0) * (W - pad.l - pad.r); }
    function Y(v) { return pad.t + (1 - (v - v0) / (v1 - v0)) * (H - pad.t - pad.b); }
    var g = s('g', { class: ['gv-fc', o.compact ? 'gv-fc--compact' : null] });

    var grid = [];
    for (var v = 1.2; v <= 1.45 + 1e-9; v += 0.05) grid.push('M' + pad.l + ' ' + Y(v).toFixed(1) + 'H' + (W - pad.r));
    g.appendChild(s('path', { class: 'gv-fc__grid', d: grid.join('') }));
    for (var vv = 1.2; vv <= 1.45 + 1e-9; vv += 0.1) {
      g.appendChild(s('text', { class: 'gv-fc__axis', x: pad.l - 8, y: Y(vv) + 4, 'text-anchor': 'end' }, fmt(vv, 1)));
    }
    for (var t = 0; t <= t1; t += o.compact ? 5 : 2) {
      g.appendChild(s('text', { class: 'gv-fc__axis', x: X(t), y: H - pad.b + (o.compact ? 18 : 24), 'text-anchor': 'middle' }, t === 0 ? 'сейчас' : '+' + t));
    }
    if (!o.compact) g.appendChild(s('text', { class: 'gv-fc__axis gv-fc__axis--title', x: W - pad.r, y: H - 6, 'text-anchor': 'end' }, 'минуты от момента прогноза'));
    if (!o.compact) g.appendChild(s('text', { class: 'gv-fc__axis gv-fc__axis--title', x: pad.l - 8, y: pad.t - 10, 'text-anchor': 'end' }, 'МПа'));

    // Уставки
    g.appendChild(s('line', { class: 'gv-fc__sp gv-fc__sp--warn', x1: pad.l, x2: W - pad.r, y1: Y(f.warn), y2: Y(f.warn) }));
    g.appendChild(s('line', { class: 'gv-fc__sp gv-fc__sp--alert', x1: pad.l, x2: W - pad.r, y1: Y(f.alert), y2: Y(f.alert) }));
    g.appendChild(s('text', { class: 'gv-fc__sp-label gv-fc__sp-label--alert', x: W - pad.r - 4, y: Y(f.alert) - 7, 'text-anchor': 'end' }, 'HH ' + fmt(f.alert, 3)));
    g.appendChild(s('text', { class: 'gv-fc__sp-label gv-fc__sp-label--warn', x: W - pad.r - 4, y: Y(f.warn) + 16, 'text-anchor': 'end' }, 'H ' + fmt(f.warn, 1)));

    // Прогноз, полосы и ETA — в группе, которая проявляется маской
    var clipId = 'fc-clip-' + Math.random().toString(36).slice(2, 8);
    var clipRect = s('rect', { x: X(0), y: 0, width: 0, height: H });
    var defs = s('defs', null, s('clipPath', { id: clipId }, clipRect));
    g.appendChild(defs);
    var fut = s('g', { 'clip-path': 'url(#' + clipId + ')' });
    function band(fn, cls) {
      var up = [], dn = [];
      for (var tt = 0; tt <= t1; tt += 0.25) { up.push(X(tt).toFixed(1) + ' ' + Y(M.model(tt) + fn(tt)).toFixed(1)); dn.push(X(tt).toFixed(1) + ' ' + Y(M.model(tt) - fn(tt)).toFixed(1)); }
      return s('path', { class: cls, d: 'M' + up.join('L') + 'L' + dn.reverse().join('L') + 'Z' });
    }
    fut.appendChild(band(M.band95, 'gv-fc__band gv-fc__band--95'));
    fut.appendChild(band(M.band80, 'gv-fc__band gv-fc__band--80'));
    fut.appendChild(s('line', { class: 'gv-fc__model', x1: X(0), y1: Y(M.model(0)), x2: X(t1), y2: Y(M.model(t1)) }));
    // Интервал ETA на линии HH
    fut.appendChild(s('rect', { class: 'gv-fc__ci', x: X(f.ciLo), y: Y(f.alert) - 7, width: X(f.ciHi) - X(f.ciLo), height: 14, rx: 2 }));
    fut.appendChild(s('line', { class: 'gv-fc__fact', x1: X(f.etaTrue), x2: X(f.etaTrue), y1: Y(f.alert) - 26, y2: H - pad.b }));
    fut.appendChild(s('line', { class: 'gv-fc__eta', x1: X(f.eta), x2: X(f.eta), y1: Y(f.alert), y2: H - pad.b }));
    fut.appendChild(s('circle', { class: 'gv-fc__eta-dot', cx: X(f.eta), cy: Y(f.alert), r: o.compact ? 4 : 6 }));
    if (!o.compact) {
      fut.appendChild(s('text', { class: 'gv-fc__eta-label', x: X(f.eta) + 10, y: Y(f.alert) - 34 }, 'ETA ' + fmt(f.eta, 2) + ' мин'));
      fut.appendChild(s('text', { class: 'gv-fc__fact-label', x: X(f.etaTrue) - 10, y: Y(f.alert) - 34, 'text-anchor': 'end' }, 'факт ' + fmt(f.etaTrue, 1)));
    }
    g.appendChild(fut);

    // Наблюдения
    var pts = M.observed.map(function (p) { return X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); });
    g.appendChild(s('path', { class: 'gv-fc__obs', d: 'M' + pts.join('L') }));
    M.observed.forEach(function (p, i) { if (i % 2 === 0) g.appendChild(s('circle', { class: 'gv-fc__obs-dot', cx: X(p[0]), cy: Y(p[1]), r: o.compact ? 2 : 3 })); });
    g.appendChild(s('line', { class: 'gv-fc__now', x1: X(0), x2: X(0), y1: pad.t, y2: H - pad.b }));

    function setReveal(p) {
      p = p < 0 ? 0 : (p > 1 ? 1 : p);
      clipRect.setAttribute('width', ((W - pad.r - X(0)) * p + 2).toFixed(1));
    }
    setReveal(o.reveal === undefined ? 1 : o.reveal);
    return { el: g, setReveal: setReveal, X: X, Y: Y };
  }

  GV.draw = { valueToAngle: valueToAngle, gauge: gauge, forecastModel: forecastModel, forecastChart: forecastChart, niceStep: niceStep };
})();
