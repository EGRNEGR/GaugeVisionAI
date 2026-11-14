/*
 * GV.kit — общий инструментарий компонентов (подключается первым из components/*.js).
 *
 * Расчёты (чистые функции, без DOM; повторяют app/vision.py, notes.md §1.6–1.8):
 *   angleToValue(θ, calib) → V            angle_to_value: CW/CCW, «мёртвая зона», clamp ±5 %
 *   valueToAngle(V, calib) → θ            value_to_angle: для дуг уставок
 *   toBar(V, calib) → бар                 1 МПа = calib.barPerMpa бар
 *   zoneOf(V, setpoints) → 'LL'|'L'|'NORMA'|'H'|'HH'
 *   levelOf(V, setpoints) → 'alert'|'warning'|'normal'   classify_level, границы включены
 *   emaStep(prev, v, α) → V̄              EmaFilter: первое значение берётся как есть
 *
 * DOM-хелперы (только в браузере):
 *   scope() → { on, add, timeout, interval, frame, observe, destroy }  — всё, что снимается в destroy()
 *   pick(value, allowed) → value из списка или первый элемент
 *   media() → 'shots'|'schematic'          onTweaks(scope, cb(state))
 *   crop(media, className) → кадрированный CSS скриншот
 *   dial(opts) → SVG-циферблат шкалы calibration (риски, стрелка, оверлей распознавания, зоны уставок)
 *   icon(name) → SVG-иконка (external, github, arrow)
 *   extLink(attrs, ...children) → <a target="_blank" rel="noopener">
 *   demoLink(label, className) → <a href="#hero-stage">: плавно прокручивает к hero-stage и ставит на него фокус
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  var NBSP = ' ';

  /* ---------- Расчёты ---------- */

  function mod(a, n) {
    return ((a % n) + n) % n;
  }

  function calibParts(calib) {
    var c = calib || (GV.content && GV.content.calibration) || {};
    return {
      vMin: Number(c.vMin), vMax: Number(c.vMax),
      thetaMin: Number(c.thetaMin), thetaMax: Number(c.thetaMax),
      ccw: String(c.direction || 'CW').toLowerCase() === 'ccw',
      clamp: c.clamp === undefined ? 0.05 : Number(c.clamp),
      barPerMpa: c.barPerMpa === undefined ? 10 : Number(c.barPerMpa)
    };
  }

  function angleToValue(theta, calib) {
    var c = calibParts(calib);
    var delta, span;
    if (!c.ccw) {
      delta = mod(theta - c.thetaMin, 360);
      span = mod(c.thetaMax - c.thetaMin, 360);
    } else {
      delta = mod(c.thetaMin - theta, 360);
      span = mod(c.thetaMin - c.thetaMax, 360);
    }
    if (span < 1e-6) span = 360;
    if (delta > span) {
      var over = delta - span;   // перелёт за максимум
      var under = 360 - delta;   // недолёт до минимума
      delta = over <= under ? span + over : -under;
    }
    var frac = Math.max(-c.clamp, Math.min(1 + c.clamp, delta / span));
    return c.vMin + frac * (c.vMax - c.vMin);
  }

  function valueToAngle(value, calib) {
    var c = calibParts(calib);
    if (c.vMax === c.vMin) return null;
    var frac = (value - c.vMin) / (c.vMax - c.vMin);
    if (!c.ccw) return mod(c.thetaMin + frac * (mod(c.thetaMax - c.thetaMin, 360) || 360), 360);
    return mod(c.thetaMin - frac * (mod(c.thetaMin - c.thetaMax, 360) || 360), 360);
  }

  /* Доля шкалы без ограничения: < 0 или > 1 — стрелка за пределами шкалы. */
  function fraction(value, calib) {
    var c = calibParts(calib);
    return (value - c.vMin) / (c.vMax - c.vMin);
  }

  function toBar(value, calib) {
    return value * calibParts(calib).barPerMpa;
  }

  function num(v) {
    return typeof v === 'number' && isFinite(v) ? v : null;
  }

  function zoneOf(value, sp) {
    sp = sp || {};
    var ll = num(sp.LL), l = num(sp.L), h = num(sp.H), hh = num(sp.HH);
    if (ll !== null && value <= ll) return 'LL';
    if (hh !== null && value >= hh) return 'HH';
    if (l !== null && value <= l) return 'L';
    if (h !== null && value >= h) return 'H';
    return 'NORMA';
  }

  function levelOf(value, sp) {
    var zone = zoneOf(value, sp);
    if (zone === 'LL' || zone === 'HH') return 'alert';
    if (zone === 'L' || zone === 'H') return 'warning';
    return 'normal';
  }

  function emaStep(prev, value, alpha) {
    if (prev === null || prev === undefined) return value;
    return alpha * value + (1 - alpha) * prev;
  }

  var kit = {
    angleToValue: angleToValue,
    valueToAngle: valueToAngle,
    fraction: fraction,
    toBar: toBar,
    zoneOf: zoneOf,
    levelOf: levelOf,
    emaStep: emaStep,
    mod: mod,
    NBSP: NBSP
  };
  GV.kit = kit;

  if (typeof document === 'undefined' || !GV.util) return;

  /* ---------- Жизненный цикл: всё, что нужно снять в destroy() ---------- */

  function scope() {
    var cleanups = [];
    var timers = {};
    var timerSeq = 0;
    var dead = false;

    function add(fn) {
      if (dead) { fn(); return fn; }
      cleanups.push(fn);
      return fn;
    }
    function on(target, type, fn, opts) {
      if (!target) return fn;
      target.addEventListener(type, fn, opts);
      add(function () { target.removeEventListener(type, fn, opts); });
      return fn;
    }
    function timeout(fn, ms) {
      if (dead) return 0;
      var key = ++timerSeq;
      timers[key] = window.setTimeout(function () { delete timers[key]; fn(); }, ms);
      return function cancel() {
        if (timers[key] !== undefined) { window.clearTimeout(timers[key]); delete timers[key]; }
      };
    }
    function interval(fn, ms) {
      if (dead) return function () {};
      var id = window.setInterval(fn, ms);
      var stopped = false;
      var stop = function () { if (!stopped) { stopped = true; window.clearInterval(id); } };
      add(stop);
      return stop;
    }
    /* Анимация по кадрам: step(t от 0 до 1); возвращает cancel. */
    function frame(duration, step, done) {
      var id = 0;
      var start = 0;
      var cancelled = false;
      function tick(now) {
        if (cancelled) return;
        if (!start) start = now;
        var t = Math.min(1, (now - start) / duration);
        step(t);
        if (t < 1) id = window.requestAnimationFrame(tick);
        else if (done) done();
      }
      id = window.requestAnimationFrame(tick);
      var cancel = function () { cancelled = true; window.cancelAnimationFrame(id); };
      add(cancel);
      return cancel;
    }
    function observe(unsubscribe) {
      return add(unsubscribe);
    }
    function destroy() {
      dead = true;
      Object.keys(timers).forEach(function (k) { window.clearTimeout(timers[k]); });
      timers = {};
      while (cleanups.length) {
        var fn = cleanups.pop();
        try { fn(); } catch (e) { console.error('GV.kit: ошибка при очистке компонента', e); }
      }
    }
    return { on: on, add: add, timeout: timeout, interval: interval, frame: frame, observe: observe, destroy: destroy };
  }

  function pick(value, allowed) {
    return allowed.indexOf(value) >= 0 ? value : allowed[0];
  }

  function media() {
    return document.documentElement.getAttribute('data-media') === 'schematic' ? 'schematic' : 'shots';
  }

  function onTweaks(sc, cb) {
    return sc.on(document, 'gv:tweaks', function (e) { cb((e && e.detail) || {}); });
  }

  /* ---------- Кадрирование скриншота CSS-обёрткой ---------- */

  function pct(v) {
    return (Math.round(v * 100000) / 1000) + '%';
  }

  /*
   * media = { src, alt, crop:{x,y,w,h} } — доли исходника.
   * Картинка шириной 100%/w сдвигается на −x и −y собственного размера: пропорции не искажаются,
   * а точное соотношение сторон обёртки ставится по naturalWidth/naturalHeight после загрузки.
   */
  function crop(m, className) {
    var h = GV.util.h;
    var c = m.crop || { x: 0, y: 0, w: 1, h: 1 };
    var img = h('img', {
      src: m.src,
      alt: m.alt || '',
      draggable: 'false',
      class: 'gv-crop__img',
      style: {
        width: pct(1 / c.w),
        transform: 'translate(' + pct(-c.x) + ', ' + pct(-c.y) + ')'
      }
    });
    var box = h('div', { class: ['gv-crop', className], style: { '--crop-ar': String(Math.round((c.w / c.h) * 1000) / 1000) } }, img);
    function fit() {
      if (img.naturalWidth && img.naturalHeight) {
        box.style.setProperty('--crop-ar', String((c.w * img.naturalWidth) / (c.h * img.naturalHeight)));
        box.classList.add('is-loaded');
      }
    }
    if (img.complete) fit();
    else img.addEventListener('load', fit, { once: true });
    img.addEventListener('error', function () { box.classList.add('is-broken'); }, { once: true });
    return box;
  }

  /* ---------- SVG-циферблат ---------- */

  function polar(cx, cy, r, deg) {
    var a = (deg * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }
  function fx(n) {
    return Math.round(n * 100) / 100;
  }
  /* Дуга по часовой (в координатах экрана, ось Y вниз) от a0 до a1. */
  function arcPath(cx, cy, r, a0, a1) {
    var sweep = mod(a1 - a0, 360);
    if (sweep < 0.01) sweep = 0.01;
    var p0 = polar(cx, cy, r, a0);
    var p1 = polar(cx, cy, r, a0 + sweep);
    return 'M' + fx(p0[0]) + ' ' + fx(p0[1]) + ' A' + r + ' ' + r + ' 0 ' + (sweep > 180 ? 1 : 0) + ' 1 ' + fx(p1[0]) + ' ' + fx(p1[1]);
  }
  /* Дуга шкалы между двумя значениями с учётом направления калибровки. */
  function valueArc(cx, cy, r, v0, v1, calib) {
    var a0 = valueToAngle(v0, calib);
    var a1 = valueToAngle(v1, calib);
    return calibParts(calib).ccw ? arcPath(cx, cy, r, a1, a0) : arcPath(cx, cy, r, a0, a1);
  }

  /*
   * opts: { theta, overlay:bool, zones:setpoints|null, title, value, unit, roi, className, ticks:true }
   * Рисует шкалу GV.content.calibration (vMin…vMax, θmin → θmax), стрелку под углом θ
   * (система координат кадра: 0° — «3 часа», по часовой). overlay — эллипс ROI, вектор и подпись θ.
   * Возвращает SVG; стрелка — g.gv-dial__needle (поворачивается setNeedle).
   */
  function dial(opts) {
    opts = opts || {};
    var s = GV.util.svg;
    var fmt = GV.util.formatNumber;
    var calib = opts.calib || GV.content.calibration;
    var cp = calibParts(calib);
    var C = 100;
    var R = 72;
    var children = [];
    var titleId = GV.util.uid('gv-dial');

    children.push(s('title', { id: titleId }, opts.title || ''));
    children.push(s('circle', { class: 'gv-dial__bezel', cx: C, cy: C, r: R + 8 }));
    children.push(s('circle', { class: 'gv-dial__face', cx: C, cy: C, r: R }));

    if (opts.zones) {
      var z = opts.zones;
      var edges = [cp.vMin, z.LL, z.L, z.H, z.HH, cp.vMax];
      var levels = ['alert', 'warning', 'normal', 'warning', 'alert'];
      for (var i = 0; i < 5; i++) {
        if (edges[i + 1] > edges[i]) {
          children.push(s('path', { class: 'gv-dial__zone gv-dial__zone--' + levels[i], d: valueArc(C, C, R - 6, edges[i], edges[i + 1], calib) }));
        }
      }
    }

    children.push(s('path', { class: 'gv-dial__scale', d: valueArc(C, C, R - 2, cp.vMin, cp.vMax, calib) }));

    var range = cp.vMax - cp.vMin;
    var steps = 20;
    for (var k = 0; k <= steps; k++) {
      var v = cp.vMin + (range * k) / steps;
      var a = valueToAngle(v, calib);
      var major = k % 2 === 0;
      var p0 = polar(C, C, R - 2, a);
      var p1 = polar(C, C, R - (major ? 12 : 7), a);
      children.push(s('line', { class: major ? 'gv-dial__tick gv-dial__tick--major' : 'gv-dial__tick', x1: fx(p0[0]), y1: fx(p0[1]), x2: fx(p1[0]), y2: fx(p1[1]) }));
      if (k % 4 === 0) {
        var pt = polar(C, C, R - 22, a);
        children.push(s('text', { class: 'gv-dial__num', x: fx(pt[0]), y: fx(pt[1]), 'text-anchor': 'middle', 'dominant-baseline': 'central' }, fmt(v)));
      }
    }

    var theta = typeof opts.theta === 'number' ? opts.theta : cp.thetaMin;
    var needle = s('g', { class: 'gv-dial__needle', transform: 'rotate(' + fx(theta) + ' ' + C + ' ' + C + ')' },
      s('line', { class: 'gv-dial__needle-tail', x1: C - 12, y1: C, x2: C, y2: C }),
      s('line', { class: 'gv-dial__needle-body', x1: C, y1: C, x2: C + R - 10, y2: C }));
    children.push(needle);
    children.push(s('circle', { class: 'gv-dial__hub', cx: C, cy: C, r: 4.5 }));

    if (opts.overlay) {
      var tip = polar(C, C, R - 6, theta);
      var head1 = polar(tip[0], tip[1], 7, theta + 155);
      var head2 = polar(tip[0], tip[1], 7, theta - 155);
      var ref = polar(C, C, 34, 0);
      children.push(s('g', { class: 'gv-dial__overlay' },
        s('ellipse', { class: 'gv-dial__roi', cx: C, cy: C, rx: R + 13, ry: R + 11 }),
        s('line', { class: 'gv-dial__ref', x1: C, y1: C, x2: fx(ref[0]), y2: fx(ref[1]) }),
        s('path', { class: 'gv-dial__theta', d: arcPath(C, C, 18, 0, theta) }),
        s('line', { class: 'gv-dial__vector', x1: C, y1: C, x2: fx(tip[0]), y2: fx(tip[1]) }),
        s('path', { class: 'gv-dial__arrow', d: 'M' + fx(tip[0]) + ' ' + fx(tip[1]) + ' L' + fx(head1[0]) + ' ' + fx(head1[1]) + ' L' + fx(head2[0]) + ' ' + fx(head2[1]) + ' Z' }),
        opts.thetaLabel ? s('text', { class: 'gv-dial__label', x: C, y: C + 30, 'text-anchor': 'middle' }, opts.thetaLabel) : null,
        opts.roi ? s('text', { class: 'gv-dial__label gv-dial__label--roi', x: 8, y: 12 }, opts.roi) : null,
        opts.valueLabel ? s('text', { class: 'gv-dial__value', x: C, y: C + 60, 'text-anchor': 'middle' }, opts.valueLabel) : null));
    }

    return s('svg', {
      class: ['gv-dial', opts.className],
      viewBox: '0 0 200 200',
      role: 'img',
      'aria-labelledby': titleId,
      focusable: 'false'
    }, children);
  }

  function setNeedle(svgEl, theta) {
    var needle = svgEl && svgEl.querySelector('.gv-dial__needle');
    if (needle) needle.setAttribute('transform', 'rotate(' + fx(theta) + ' 100 100)');
  }

  /* ---------- Иконки (свои SVG, одна толщина линии) ---------- */

  var ICONS = {
    external: ['M7 13L13 7', 'M8 7h5v5'],
    arrow: ['M10 4v12', 'M5 11l5 5 5-5'],
    right: ['M4 10h12', 'M11 5l5 5-5 5']
  };
  var GITHUB = 'M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z';

  function icon(name) {
    var s = GV.util.svg;
    if (name === 'github') {
      return s('svg', { class: 'gv-icon gv-icon--fill', viewBox: '0 0 16 16', 'aria-hidden': 'true', focusable: 'false' }, s('path', { d: GITHUB }));
    }
    return s('svg', { class: 'gv-icon', viewBox: '0 0 20 20', 'aria-hidden': 'true', focusable: 'false' },
      (ICONS[name] || ICONS.right).map(function (d) { return s('path', { d: d }); }));
  }

  function extLink(attrs) {
    var a = Object.assign({ target: '_blank', rel: 'noopener' }, attrs || {});
    var args = ['a', a].concat(Array.prototype.slice.call(arguments, 1));
    return GV.util.h.apply(null, args);
  }

  /* «Смотреть демо»: прокрутка к hero-stage и фокус на нём (история 6). */
  function scrollToStage(id) {
    var target = document.getElementById(id || 'hero-stage');
    if (!target) return false;
    target.scrollIntoView({ behavior: GV.util.prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); }
    return true;
  }

  function demoLink(label, className) {
    var target = (GV.content.hero.ctaSecondary && GV.content.hero.ctaSecondary.target) || '#hero-stage';
    return GV.util.h('a', {
      href: target,
      class: className,
      on: {
        click: function (e) {
          if (scrollToStage(target.replace(/^#/, ''))) e.preventDefault();
        }
      }
    }, label || GV.content.hero.ctaSecondary.label, icon('arrow'));
  }

  kit.scope = scope;
  kit.pick = pick;
  kit.media = media;
  kit.onTweaks = onTweaks;
  kit.crop = crop;
  kit.dial = dial;
  kit.setNeedle = setNeedle;
  kit.arcPath = arcPath;
  kit.polar = polar;
  kit.icon = icon;
  kit.extLink = extLink;
  kit.demoLink = demoLink;
  kit.scrollToStage = scrollToStage;
})();
