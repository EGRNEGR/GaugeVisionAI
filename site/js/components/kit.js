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
 *   onTweaks(scope, cb(state))             событие gv:tweaks (масштаб, шрифт)
 *   polar(cx, cy, r, θ) → [x, y]           точка на окружности (0° — «3 часа», по часовой)
 *   arcPath(cx, cy, r, θ0, θ1) → d          SVG-дуга по часовой от θ0 до θ1
 *   icon(name) → SVG-иконка (external, github, arrow, right)
 *   extLink(attrs, ...children) → <a target="_blank" rel="noopener"> + иконка и скрытое «откроется в новой вкладке»
 *   sectionNav(scope, {container, links, ids, rootMargin, keepLast, onChange}) → { setCurrent }
 *                                          якоря шапки и aria-current текущей секции
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
    toBar: toBar,
    zoneOf: zoneOf,
    levelOf: levelOf,
    emaStep: emaStep,
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

  function onTweaks(sc, cb) {
    return sc.on(document, 'gv:tweaks', function (e) { cb((e && e.detail) || {}); });
  }

  /* ---------- SVG-геометрия ---------- */

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

  /* Ссылка в новой вкладке всегда помечена: иконка «наружу» и визуально скрытый текст для чтения с экрана. */
  function extLink(attrs) {
    var h = GV.util.h;
    var note = (GV.content && GV.content.labels && GV.content.labels.newTab) || 'откроется в новой вкладке';
    var a = Object.assign({ target: '_blank', rel: 'noopener' }, attrs || {});
    var children = Array.prototype.slice.call(arguments, 1);
    children.push(icon('external'), h('span', { class: 'gv-visually-hidden' }, ' (' + note + ')'));
    return h.apply(null, ['a', a].concat(children));
  }

  /*
   * Навигация шапки страницы.
   * opts: { container, links:{id: <a>}, ids:[…], rootMargin, keepLast, onChange(id|null) }
   *   — клик по якорю «#id» внутри container: плавная прокрутка к секции и фокус на ней;
   *   — IntersectionObserver: aria-current="true" у ссылки первой из ids, попавшей в полосу rootMargin;
   *     keepLast — если в полосе нет ни одной секции, отметка остаётся на прежней (иначе снимается).
   * Слушатели и наблюдатель снимаются через sc.destroy(). → { setCurrent(id|null) }
   */
  function sectionNav(sc, opts) {
    var links = opts.links || {};
    var ids = opts.ids || Object.keys(links);
    var currentId;

    sc.on(opts.container, 'click', function (e) {
      var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
      if (!a) return;
      var target = document.getElementById(a.getAttribute('href').slice(1));
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: GV.util.prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
      if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      try { target.focus({ preventScroll: true }); } catch (err) { target.focus(); }
    });

    function setCurrent(id) {
      if (id === currentId) return;
      currentId = id;
      ids.forEach(function (key) {
        if (!links[key]) return;
        if (key === id) links[key].setAttribute('aria-current', 'true');
        else links[key].removeAttribute('aria-current');
      });
      if (opts.onChange) opts.onChange(id);
    }

    if ('IntersectionObserver' in window) {
      var visible = {};
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
        var current = null;
        ids.forEach(function (id) { if (!current && visible[id]) current = id; });
        if (current || !opts.keepLast) setCurrent(current);
      }, { rootMargin: opts.rootMargin || '-35% 0px -55% 0px' });
      ids.forEach(function (id) {
        var el = document.getElementById(id);
        if (el) io.observe(el);
      });
      sc.add(function () { io.disconnect(); });
    }

    return { setCurrent: setCurrent };
  }

  kit.scope = scope;
  kit.sectionNav = sectionNav;
  kit.onTweaks = onTweaks;
  kit.arcPath = arcPath;
  kit.polar = polar;
  kit.icon = icon;
  kit.extLink = extLink;
})();
