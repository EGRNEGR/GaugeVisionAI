/*
 * GV.components.pipeline — кликабельный разбор конвейера 00–08 с панелью деталей.
 * mount(el, { layout: 'rail'|'arc'|'timeline', initial?: id }) → { destroy(), select(id) }
 *   rail     — горизонтальная лента этапов, панель снизу (вариант A);
 *   arc      — этапы как риски на дуге шкалы, стрелка указывает на выбранный;
 *   timeline — вертикальная шкала этапов с формулой у каждого, панель справа.
 * role="tablist", roving tabindex, ←/→/Home/End (в timeline ещё ↑/↓).
 * Детали этапа: что делает, параметры из кода, формула, файл и мини-схема SVG.
 * Этап calibrate — живой слайдер θ → МПа и бар с зоной уставки (GV.kit.angleToValue).
 * Этап stabilize — EMA-симуляция с кнопкой «Вибрация», пауза вне экрана и при reduced motion.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var LAYOUTS = ['rail', 'arc', 'timeline'];
  var EMA_TICK_MS = 400;
  var EMA_POINTS = 60;
  var T = {
    tablist: 'Этапы конвейера',
    on: 'вкл',
    off: 'выкл',
    outOfScale: 'Стрелка в «мёртвой зоне» шкалы: значение ограничено',
    zoneTitle: 'Зона уставки',
    simTitle: 'EMA-симуляция',
    stage: 'Этап'
  };

  /* ---------- мини-схемы этапов (геометрия, без текста) ---------- */

  function miniSvg(id) {
    var s = GV.util.svg;
    var kit = GV.kit;
    var parts = [];
    var cal = GV.content.calibration;

    function frame(x, y, w, hgt, cls) {
      return s('rect', { class: cls || 'gv-mini__line', x: x, y: y, width: w, height: hgt, rx: 3 });
    }
    function arrow(x1, y1, x2, y2) {
      var a = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
      var p1 = kit.polar(x2, y2, 7, a + 150);
      var p2 = kit.polar(x2, y2, 7, a - 150);
      return s('g', { class: 'gv-mini__flow' },
        s('line', { x1: x1, y1: y1, x2: x2, y2: y2 }),
        s('path', { d: 'M' + x2 + ' ' + y2 + ' L' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + ' M' + x2 + ' ' + y2 + ' L' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1) }));
    }
    function dialMark(cx, cy, r, theta, cls) {
      var tip = kit.polar(cx, cy, r * 0.8, theta);
      return s('g', { class: cls || '' },
        s('circle', { class: 'gv-mini__line', cx: cx, cy: cy, r: r }),
        s('line', { class: 'gv-mini__needle', x1: cx, y1: cy, x2: tip[0].toFixed(1), y2: tip[1].toFixed(1) }),
        s('circle', { class: 'gv-mini__dot', cx: cx, cy: cy, r: 2.5 }));
    }

    switch (id) {
      case 'capture':
        parts.push(frame(14, 52, 34, 26), s('circle', { class: 'gv-mini__line', cx: 31, cy: 65, r: 7 }));
        parts.push(arrow(56, 65, 92, 65));
        parts.push(frame(108, 26, 64, 46, 'gv-mini__line gv-mini__faint'), frame(118, 40, 64, 46, 'gv-mini__line gv-mini__faint'));
        parts.push(frame(128, 54, 64, 46, 'gv-mini__accent'), dialMark(160, 77, 14, 300));
        parts.push(arrow(198, 77, 226, 77));
        break;
      case 'locate':
        parts.push(frame(14, 14, 212, 112, 'gv-mini__line gv-mini__faint'));
        parts.push(dialMark(120, 70, 36, 290));
        parts.push(s('rect', { class: 'gv-mini__dash', x: 78, y: 28, width: 84, height: 84 }));
        parts.push(s('ellipse', { class: 'gv-mini__accent', cx: 120, cy: 70, rx: 39, ry: 38 }));
        break;
      case 'normalize':
        parts.push(s('g', { transform: 'rotate(-18 60 70)' },
          s('ellipse', { class: 'gv-mini__line', cx: 60, cy: 70, rx: 40, ry: 24 }),
          s('line', { class: 'gv-mini__needle', x1: 60, y1: 70, x2: 86, y2: 60 })));
        parts.push(arrow(108, 70, 138, 70));
        parts.push(s('circle', { class: 'gv-mini__accent', cx: 186, cy: 70, r: 38 }));
        parts.push(s('line', { class: 'gv-mini__needle', x1: 186, y1: 70, x2: 212, y2: 52 }));
        parts.push(s('line', { class: 'gv-mini__dash', x1: 148, y1: 70, x2: 224, y2: 70 }), s('line', { class: 'gv-mini__dash', x1: 186, y1: 32, x2: 186, y2: 108 }));
        break;
      case 'light':
        [[18, 'dark'], [92, 'light'], [166, 'sat']].forEach(function (cfg, i) {
          var x = cfg[0];
          parts.push(s('rect', { class: 'gv-mini__mask gv-mini__mask--' + cfg[1], x: x, y: 30, width: 58, height: 58, rx: 3 }));
          parts.push(s('line', { class: 'gv-mini__mask-needle gv-mini__mask-needle--' + cfg[1], x1: x + 29, y1: 59, x2: x + 48, y2: 42 }));
          if (i === 0) parts.push(s('rect', { class: 'gv-mini__accent', x: x - 5, y: 25, width: 68, height: 68, rx: 5 }));
        });
        parts.push(s('line', { class: 'gv-mini__dash', x1: 14, y1: 112, x2: 226, y2: 112 }));
        break;
      case 'needle': {
        var cx = 120, cy = 70, R = 56, peak = 305;
        parts.push(s('circle', { class: 'gv-mini__line gv-mini__faint', cx: cx, cy: cy, r: R }));
        parts.push(s('circle', { class: 'gv-mini__ring', cx: cx, cy: cy, r: R * 0.42 }));
        for (var a = 0; a < 360; a += 10) {
          var d = Math.min(Math.abs(a - peak), 360 - Math.abs(a - peak));
          var len = 3 + 16 * Math.exp(-(d * d) / 300);
          var p0 = kit.polar(cx, cy, R * 0.72, a);
          var p1 = kit.polar(cx, cy, R * 0.72 + len, a);
          parts.push(s('line', { class: d < 20 ? 'gv-mini__bar gv-mini__bar--peak' : 'gv-mini__bar', x1: p0[0].toFixed(1), y1: p0[1].toFixed(1), x2: p1[0].toFixed(1), y2: p1[1].toFixed(1) }));
        }
        var tip = kit.polar(cx, cy, R * 0.7, peak);
        parts.push(s('line', { class: 'gv-mini__vector', x1: cx, y1: cy, x2: tip[0].toFixed(1), y2: tip[1].toFixed(1) }));
        parts.push(s('circle', { class: 'gv-mini__dot', cx: cx, cy: cy, r: 3 }));
        break;
      }
      case 'setpoints': {
        var sp = cal.setpoints;
        var edges = [cal.vMin, sp.LL, sp.L, sp.H, sp.HH, cal.vMax];
        var levels = ['alert', 'warning', 'normal', 'warning', 'alert'];
        var x0 = 16, w = 208;
        for (var k = 0; k < 5; k++) {
          var xa = x0 + w * (edges[k] - cal.vMin) / (cal.vMax - cal.vMin);
          var xb = x0 + w * (edges[k + 1] - cal.vMin) / (cal.vMax - cal.vMin);
          parts.push(s('rect', { class: 'gv-mini__zone gv-mini__zone--' + levels[k], x: xa.toFixed(1), y: 56, width: Math.max(0, xb - xa - 1).toFixed(1), height: 18 }));
          parts.push(s('text', { class: 'gv-mini__text', x: ((xa + xb) / 2).toFixed(1), y: 96, 'text-anchor': 'middle' }, cal.zones[k].label));
        }
        parts.push(s('line', { class: 'gv-mini__needle', x1: x0 + w * 0.44, y1: 40, x2: x0 + w * 0.44, y2: 82 }));
        break;
      }
      case 'output':
        parts.push(frame(16, 48, 58, 44, 'gv-mini__accent'));
        parts.push(dialMark(45, 70, 12, 300));
        parts.push(arrow(82, 70, 140, 30), arrow(82, 70, 140, 70), arrow(82, 70, 140, 110));
        parts.push(frame(150, 14, 74, 34), s('polyline', { class: 'gv-mini__needle', points: '158,40 172,30 186,36 200,24 216,30' }));
        parts.push(s('ellipse', { class: 'gv-mini__line', cx: 184, cy: 60, rx: 26, ry: 6 }), s('path', { class: 'gv-mini__line', d: 'M158 60 v20 a26 6 0 0 0 52 0 v-20' }));
        parts.push(frame(164, 96, 42, 32), s('line', { class: 'gv-mini__faint gv-mini__line', x1: 170, y1: 106, x2: 200, y2: 106 }), s('line', { class: 'gv-mini__faint gv-mini__line', x1: 170, y1: 114, x2: 200, y2: 114 }));
        break;
      default:
        parts.push(dialMark(120, 70, 40, 300));
    }
    return s('svg', { class: 'gv-mini', viewBox: '0 0 240 140', 'aria-hidden': 'true', focusable: 'false' }, parts);
  }

  /* ---------- калибровка: θ → МПа и бар, зона уставки ---------- */

  function calibrationWidget(sc) {
    var u = GV.util, kit = GV.kit, h = u.h, fmt = u.formatNumber, NBSP = kit.NBSP;
    var c = GV.content;
    var cal = c.calibration;
    var sp = cal.setpoints;
    var shot = c.screenshotFacts && c.screenshotFacts.calibrationWindow;
    var theta0 = shot && typeof shot.theta === 'number' ? shot.theta : cal.thetaMin;
    var inputId = u.uid('gv-calib-theta');
    var outId = u.uid('gv-calib-out');
    var unitBar = c.labels.units.bar;

    var dialSvg = kit.dial({ className: 'gv-calib__dial', theta: theta0, zones: sp, title: cal.sliderLabel });
    var thetaOut = h('output', { class: 'gv-calib__theta', for: inputId });
    var input = h('input', {
      id: inputId, class: 'gv-calib__range', type: 'range', min: '0', max: '359', step: '0.1',
      value: String(theta0), 'aria-describedby': outId
    });
    var valueEl = h('span', { class: 'gv-calib__value' });
    var barEl = h('span', { class: 'gv-calib__bar' });
    var zoneEl = h('p', { class: 'gv-calib__zone' });
    var calcEl = h('p', { class: 'gv-calib__calc' });
    var clampEl = h('p', { class: 'gv-calib__clamp', hidden: true });

    function bound(v) { return fmt(v, 2); }
    var zoneRange = {
      LL: '≤' + NBSP + bound(sp.LL),
      L: bound(sp.LL) + '–' + bound(sp.L),
      NORMA: bound(sp.L) + '–' + bound(sp.H),
      H: bound(sp.H) + '–' + bound(sp.HH),
      HH: '≥' + NBSP + bound(sp.HH)
    };
    var legendItems = {};
    var legend = h('ol', { class: 'gv-calib__zones', role: 'list', 'aria-label': T.zoneTitle },
      cal.zones.map(function (z) {
        var li = h('li', { class: 'gv-calib__zone-item', 'data-level': z.status, title: z.text },
          h('span', { class: 'gv-calib__zone-label' }, z.label),
          h('span', { class: 'gv-calib__zone-range' }, zoneRange[z.id]));
        legendItems[z.id] = li;
        return li;
      }));

    function update() {
      var theta = parseFloat(input.value);
      if (!isFinite(theta)) return;
      var v = kit.angleToValue(theta, cal);
      var frac = kit.fraction(v, cal);
      var zone = kit.zoneOf(v, sp);
      var level = kit.levelOf(v, sp);
      var zoneData = cal.zones.filter(function (z) { return z.id === zone; })[0];
      thetaOut.textContent = fmt(theta, 1) + '°';
      valueEl.textContent = fmt(v, 2);
      barEl.textContent = fmt(kit.toBar(v, cal), 2) + NBSP + unitBar;
      zoneEl.setAttribute('data-level', level);
      zoneEl.textContent = zoneData ? zoneData.text : c.labels.level[level];
      Object.keys(legendItems).forEach(function (id) {
        if (id === zone) legendItems[id].setAttribute('aria-current', 'true');
        else legendItems[id].removeAttribute('aria-current');
      });
      calcEl.textContent = 'V = ' + fmt(cal.vMin) + ' + ((' + fmt(theta, 1) + '° − ' + fmt(cal.thetaMin) + '°) mod 360) / ' +
        fmt(cal.span) + ' · (' + fmt(cal.vMax) + ' − ' + fmt(cal.vMin) + ') = ' + fmt(v, 2) + NBSP + cal.unit;
      clampEl.hidden = !(frac < -1e-9 || frac > 1 + 1e-9);
      clampEl.textContent = T.outOfScale + ' ±' + NBSP + fmt(cal.clamp * 100) + NBSP + '%';
      kit.setNeedle(dialSvg, theta);
    }

    sc.on(input, 'input', update);
    update();

    return h('div', { class: 'gv-calib' },
      h('div', { class: 'gv-calib__visual' }, dialSvg),
      h('div', { class: 'gv-calib__controls' },
        h('div', { class: 'gv-calib__field' },
          h('label', { class: 'gv-calib__label', for: inputId }, cal.sliderLabel), thetaOut),
        input,
        h('div', { class: 'gv-calib__out', id: outId, 'aria-live': 'polite' },
          h('p', { class: 'gv-calib__reading' }, valueEl, h('span', { class: 'gv-calib__unit' }, cal.unit)),
          h('p', { class: 'gv-calib__reading gv-calib__reading--bar' }, barEl),
          zoneEl),
        legend,
        clampEl,
        calcEl,
        h('p', { class: 'gv-calib__caption' }, cal.caption)));
  }

  /* ---------- стабилизация: EMA гасит вибрацию (симуляция формулы) ---------- */

  function emaWidget(sc) {
    var u = GV.util, kit = GV.kit, h = u.h, s = u.svg;
    var ema = GV.content.ema;
    var W = 320, H = 150, PAD = 14;
    var vibration = true;
    var t = 0;
    var seed = 7;
    var raw = [];
    var smooth = [];
    var last = null;
    var stopTimer = null;

    function rng() {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    }
    /* Иллюстративный уровень: ступень вверх и вниз, чтобы видеть и подавление шума, и запаздывание. */
    function base(i) {
      return Math.floor(i / 36) % 2 === 0 ? 0.42 : 0.62;
    }
    function sample() {
      var noise = vibration ? (rng() - 0.5) * 0.34 : 0;
      var v = Math.max(0.04, Math.min(0.96, base(t) + noise));
      last = kit.emaStep(last, v, ema.alpha);
      raw.push(v);
      smooth.push(last);
      if (raw.length > EMA_POINTS) { raw.shift(); smooth.shift(); }
      t += 1;
    }
    function fill() {
      raw = []; smooth = []; last = null; t = 0; seed = 7;
      for (var i = 0; i < EMA_POINTS; i++) sample();
    }
    function points(arr) {
      return arr.map(function (v, i) {
        var x = PAD + (i * (W - 2 * PAD)) / (EMA_POINTS - 1);
        var y = H - PAD - v * (H - 2 * PAD);
        return x.toFixed(1) + ',' + y.toFixed(1);
      }).join(' ');
    }

    var rawLine = s('polyline', { class: 'gv-ema__raw' });
    var emaLine = s('polyline', { class: 'gv-ema__smooth' });
    var chart = s('svg', { class: 'gv-ema__chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': T.simTitle + ': ' + ema.legendRaw + ' и ' + ema.legendEma, focusable: 'false' },
      s('line', { class: 'gv-ema__axis', x1: PAD, y1: H - PAD, x2: W - PAD, y2: H - PAD }),
      s('line', { class: 'gv-ema__grid', x1: PAD, y1: H / 2, x2: W - PAD, y2: H / 2 }),
      rawLine, emaLine);

    function draw() {
      rawLine.setAttribute('points', points(raw));
      emaLine.setAttribute('points', points(smooth));
    }

    var toggle = h('button', { type: 'button', class: 'gv-ema__toggle', 'aria-pressed': 'true' });
    function syncToggle() {
      toggle.setAttribute('aria-pressed', vibration ? 'true' : 'false');
      toggle.textContent = '';
      toggle.appendChild(h('span', { class: 'gv-ema__toggle-dot', 'aria-hidden': 'true' }));
      toggle.appendChild(document.createTextNode(ema.toggleLabel + ': ' + (vibration ? T.on : T.off)));
    }
    sc.on(toggle, 'click', function () {
      vibration = !vibration;
      syncToggle();
      if (u.prefersReducedMotion()) { fill(); draw(); }
    });

    function start() {
      if (stopTimer || u.prefersReducedMotion()) return;
      stopTimer = sc.interval(function () { sample(); draw(); }, EMA_TICK_MS);
    }
    function stop() {
      if (stopTimer) { stopTimer(); stopTimer = null; }
    }

    fill();
    draw();
    syncToggle();

    var rootEl = h('div', { class: 'gv-ema' },
      h('div', { class: 'gv-ema__visual' }, chart),
      h('div', { class: 'gv-ema__controls' },
        toggle,
        h('ul', { class: 'gv-ema__legend', role: 'list' },
          h('li', { class: 'gv-ema__key gv-ema__key--raw' }, ema.legendRaw),
          h('li', { class: 'gv-ema__key gv-ema__key--smooth' }, ema.legendEma)),
        h('p', { class: 'gv-ema__formula' }, h('code', null, ema.formula)),
        h('p', { class: 'gv-ema__caption' }, ema.caption)));

    sc.observe(u.onVisible(rootEl, function (visible) { if (visible) start(); else stop(); }, { threshold: 0.2 }));
    sc.add(stop);
    return rootEl;
  }

  /* ---------- компонент ---------- */

  function mount(el, options) {
    options = options || {};
    var u = GV.util, kit = GV.kit, h = u.h, s = u.svg;
    var c = GV.content;
    var L = c.labels;
    var steps = c.pipeline;
    var layout = kit.pick(options.layout, LAYOUTS);
    var sc = kit.scope();
    var detailScope = null;
    var baseId = u.uid('gv-pipe');
    var panelId = baseId + '-panel';
    var arcAngles = steps.map(function (_, i) { return 135 + (i * 270) / (steps.length - 1); });

    var tabs = steps.map(function (step, i) {
      var attrs = {
        type: 'button', role: 'tab', id: baseId + '-tab-' + step.id, class: 'gv-pipeline__tab',
        'aria-selected': 'false', 'aria-controls': panelId, tabindex: '-1', 'data-id': step.id
      };
      if (layout === 'arc') {
        var p = kit.polar(50, 50, 33, arcAngles[i]);
        attrs.style = { '--x': p[0].toFixed(2) + '%', '--y': p[1].toFixed(2) + '%' };
      }
      return h('button', attrs,
        h('span', { class: 'gv-pipeline__tab-index' }, step.index),
        h('span', { class: 'gv-pipeline__tab-title' }, step.title),
        layout === 'timeline' ? h('span', { class: 'gv-pipeline__tab-short' }, step.short) : null,
        layout === 'timeline' && step.formula ? h('code', { class: 'gv-pipeline__tab-formula' }, step.formula) : null);
    });

    var tablist = h('div', {
      class: 'gv-pipeline__tabs', role: 'tablist', 'aria-label': T.tablist,
      'aria-orientation': layout === 'timeline' ? 'vertical' : 'horizontal'
    }, tabs);

    var arcNeedle = null;
    var trackChildren = [];
    if (layout === 'arc') {
      var ticks = [];
      for (var k = 0; k <= 48; k++) {
        var a = 135 + (k * 270) / 48;
        var p0 = kit.polar(100, 100, 92, a);
        var p1 = kit.polar(100, 100, k % 6 === 0 ? 84 : 88, a);
        ticks.push(s('line', { class: k % 6 === 0 ? 'gv-pipeline__arc-tick gv-pipeline__arc-tick--major' : 'gv-pipeline__arc-tick', x1: p0[0].toFixed(2), y1: p0[1].toFixed(2), x2: p1[0].toFixed(2), y2: p1[1].toFixed(2) }));
      }
      arcNeedle = s('g', { class: 'gv-pipeline__arc-needle' },
        s('line', { x1: 100, y1: 100, x2: 146, y2: 100 }),
        s('circle', { cx: 100, cy: 100, r: 4 }));
      trackChildren.push(s('svg', { class: 'gv-pipeline__arc', viewBox: '0 0 200 200', 'aria-hidden': 'true', focusable: 'false' },
        s('path', { class: 'gv-pipeline__arc-scale', d: kit.arcPath(100, 100, 92, 135, 45) }), ticks, arcNeedle));
    } else if (layout === 'rail') {
      trackChildren.push(h('span', { class: 'gv-pipeline__rail-line', 'aria-hidden': 'true' }));
    }
    trackChildren.push(tablist);

    var panel = h('div', { class: 'gv-pipeline__panel', role: 'tabpanel', id: panelId, tabindex: '0' });
    var rootEl = h('div', { class: ['gv-pipeline', 'gv-pipeline--' + layout] },
      h('div', { class: 'gv-pipeline__track' }, trackChildren),
      panel);
    el.appendChild(rootEl);

    function detail(step) {
      var extra = null;
      if (step.id === 'calibrate') extra = calibrationWidget(detailScope);
      else if (step.id === 'stabilize') extra = emaWidget(detailScope);
      return h('article', { class: ['gv-pipeline__detail', extra ? 'gv-pipeline__detail--live' : null], 'data-id': step.id },
        h('header', { class: 'gv-pipeline__head' },
          h('p', { class: 'gv-pipeline__index' }, T.stage + ' ' + step.index + ' / ' + steps[steps.length - 1].index),
          h('h3', { class: 'gv-pipeline__title' }, step.title),
          h('p', { class: 'gv-pipeline__aspect' }, step.aspect)),
        h('div', { class: 'gv-pipeline__text' },
          h('p', { class: 'gv-pipeline__short' }, step.short),
          h('p', { class: 'gv-pipeline__what' }, step.what),
          step.formula ? h('div', { class: 'gv-pipeline__formula' },
            h('span', { class: 'gv-pipeline__key' }, L.formula), h('code', null, step.formula)) : null,
          h('p', { class: 'gv-pipeline__file' },
            h('span', { class: 'gv-pipeline__key' }, L.file), h('code', null, step.file))),
        h('div', { class: 'gv-pipeline__params' },
          h('table', { class: 'gv-pipeline__table' },
            h('caption', { class: 'gv-pipeline__key' }, L.params),
            h('tbody', null, step.params.map(function (p) {
              return h('tr', null,
                h('th', { scope: 'row' }, h('code', null, p.name)),
                h('td', null, h('span', { class: 'gv-pipeline__value' }, p.value),
                  p.note ? h('span', { class: 'gv-pipeline__note' }, p.note) : null));
            })))),
        h('figure', { class: 'gv-pipeline__figure' }, extra || miniSvg(step.id)));
    }

    function show(i) {
      if (detailScope) detailScope.destroy();
      detailScope = kit.scope();
      var step = steps[i];
      panel.setAttribute('aria-labelledby', tabs[i].id);
      panel.textContent = '';
      panel.appendChild(detail(step));
      rootEl.setAttribute('data-current', step.id);
      rootEl.style.setProperty('--progress', String(i / (steps.length - 1)));
      if (arcNeedle) arcNeedle.setAttribute('transform', 'rotate(' + arcAngles[i].toFixed(2) + ' 100 100)');
    }

    var initial = 0;
    if (options.initial) {
      steps.forEach(function (st, i) { if (st.id === options.initial) initial = i; });
    }
    var roving = u.rovingTabs(tablist, {
      selector: '[role="tab"]',
      orientation: layout === 'timeline' ? 'both' : 'horizontal',
      initial: initial,
      onSelect: function (i) { show(i); }
    });
    sc.add(roving.destroy);
    sc.add(function () { if (detailScope) detailScope.destroy(); detailScope = null; });

    return {
      destroy: function () {
        sc.destroy();
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      },
      select: function (id) {
        steps.forEach(function (st, i) { if (st.id === id) roving.select(i); });
      }
    };
  }

  GV.components.pipeline = { mount: mount, layouts: LAYOUTS.slice() };
})();
