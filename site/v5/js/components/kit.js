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
 *   createReading(θ) → { get, set, commit, on, onCommit }   общее показание страницы (лист 01 ↔ лист 03)
 *   clockText(мс) → '08:00:00,333'         время строки журнала
 *   mathTree(строка) → узлы формулы        разбор линейной записи: дроби a / b, индексы Vmin и θmin, слоты {имя}
 *
 * Углы сайта отсчитываются от «6 часов» по часовой: θ = (θкадра − 90°) mod 360. Шов 0° / 360° лежит
 * в пустом секторе под шкалой, поэтому стрелка между θmin и θmax никогда его не пересекает.
 *
 * DOM-хелперы (только в браузере):
 *   scope() → { on, add, timeout, interval, frame, observe, destroy }  — всё, что снимается в destroy()
 *   math(строка, { label }) → { el, slots }  формула вёрсткой: дробь в два этажа, индексы, слоты для живых чисел
 *   polar(cx, cy, r, θ) → [x, y]           точка на окружности (0° — «6 часов», по часовой)
 *   arcPath(cx, cy, r, θ0, θ1) → d          SVG-дуга по часовой от θ0 до θ1
 *   gauge({ kind: 'enamel'|'drawing', caption }) → { el, needle, setAngle(θ) }   прибор 0–10 МПа
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

  /*
   * Общее показание страницы: угол стрелки θ, который двигают прибор первого листа и чертёж листа 03.
   * set(θ, from) — новое положение (from — кто подвинул, чтобы не отвечать самому себе);
   * commit(θ) — «Записать в журнал»: журнал первого листа добавляет строку с отметкой «вы».
   * on(fn(θ, from)) и onCommit(fn(θ)) возвращают отписку.
   */
  function createReading(theta) {
    var current = theta;
    var subs = [];
    var commits = [];
    function off(list, fn) {
      return function () {
        var i = list.indexOf(fn);
        if (i >= 0) list.splice(i, 1);
      };
    }
    return {
      get: function () { return current; },
      set: function (next, from) {
        if (typeof next !== 'number' || !isFinite(next) || next === current) return;
        current = next;
        subs.slice().forEach(function (fn) { fn(current, from); });
      },
      commit: function (value) {
        var v = typeof value === 'number' ? value : current;
        commits.slice().forEach(function (fn) { fn(v); });
      },
      on: function (fn) { subs.push(fn); return off(subs, fn); },
      onCommit: function (fn) { commits.push(fn); return off(commits, fn); }
    };
  }

  /* «08:00:00,333» — время строки журнала от начала смены (мс). */
  function clockText(ms) {
    var total = Math.max(0, Math.round(ms));
    var h = Math.floor(total / 3600000) % 24;
    var m = Math.floor(total / 60000) % 60;
    var s = Math.floor(total / 1000) % 60;
    var f = total % 1000;
    function p(n, w) { var t = String(n); while (t.length < w) t = '0' + t; return t; }
    return p(h, 2) + ':' + p(m, 2) + ':' + p(s, 2) + ',' + p(f, 3);
  }

  /*
   * Формула линейной записью → дерево узлов. «a / b» становится дробью: числитель и знаменатель — ближайшие
   * слева и справа атомы, у скобочной группы внешние скобки снимаются. Vmin, θmax, y₁ → основа с индексом.
   * {имя} — слот для числа, которое меняется на лету. Узлы: { t: 'text'|'op'|'sp'|'sub'|'group'|'frac'|'slot' }.
   */
  var MATH_SPLIT = /(\{\w+\}|[Vθ](?:min|max)|[a-z][₀-₉]|\s+|[()\/·−+=])/;
  var SUB_DIGITS = '₀₁₂₃₄₅₆₇₈₉';
  function mathTree(src) {
    var parts = String(src).split(MATH_SPLIT).filter(function (p) { return p !== ''; });
    var stack = [[]];
    parts.forEach(function (p) {
      var top = stack[stack.length - 1];
      var m;
      if (p === '(') stack.push([]);
      else if (p === ')' && stack.length > 1) {
        var items = stack.pop();
        stack[stack.length - 1].push({ t: 'group', items: items });
      } else if (/^\s+$/.test(p)) top.push({ t: 'sp' });
      else if (/^[\/·−+=]$/.test(p)) top.push({ t: 'op', v: p });
      else if ((m = /^\{(\w+)\}$/.exec(p))) top.push({ t: 'slot', name: m[1] });
      else if ((m = /^([Vθ])(min|max)$/.exec(p))) top.push({ t: 'sub', base: m[1], sub: m[2] });
      else if ((m = /^([a-z])([₀-₉])$/.exec(p))) top.push({ t: 'sub', base: m[1], sub: String(SUB_DIGITS.indexOf(m[2])) });
      else top.push({ t: 'text', v: p });
    });
    while (stack.length > 1) {
      // незакрытая скобка — оставляем её текстом
      var open = stack.pop();
      stack[stack.length - 1].push.apply(stack[stack.length - 1], [{ t: 'text', v: '(' }].concat(open));
    }
    return fractions(stack[0]);
  }
  function fractions(items) {
    var out = [];
    function unwrap(n) { return n.t === 'group' ? n.items : [n]; }
    for (var i = 0; i < items.length; i++) {
      var n = items[i];
      if (n.t === 'group') n = { t: 'group', items: fractions(n.items) };
      if (n.t === 'op' && n.v === '/') {
        while (out.length && out[out.length - 1].t === 'sp') out.pop();
        var j = i + 1;
        while (j < items.length && items[j].t === 'sp') j++;
        if (out.length && j < items.length) {
          var right = items[j];
          if (right.t === 'group') right = { t: 'group', items: fractions(right.items) };
          out.push({ t: 'frac', num: unwrap(out.pop()), den: unwrap(right) });
          i = j;
          continue;
        }
      }
      out.push(n);
    }
    return out;
  }

  var kit = {
    angleToValue: angleToValue,
    valueToAngle: valueToAngle,
    toBar: toBar,
    zoneOf: zoneOf,
    levelOf: levelOf,
    emaStep: emaStep,
    createReading: createReading,
    clockText: clockText,
    mathTree: mathTree,
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

  /* ---------- SVG-геометрия ---------- */

  /* θ сайта → экранный угол SVG: 0° смотрит вниз, рост по часовой */
  var ZERO = 90;
  function polar(cx, cy, r, deg) {
    var a = ((deg + ZERO) * Math.PI) / 180;
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
   * Строка с пометкой маркером: accent — дословная часть text (совпадение сверяет tests/check.js).
   * → [до, <mark class="gv-hl">, после] для GV.util.h; без accent или без совпадения — [text].
   */
  function marked(text, accent) {
    var at = accent ? String(text).indexOf(accent) : -1;
    if (at < 0) return [text];
    return [text.slice(0, at) || null, GV.util.h('mark', { class: 'gv-hl' }, accent), text.slice(at + accent.length) || null];
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

  /*
   * Прибор 0–10 МПа одним SVG: шкала 270° от θmin до θmax по часовой, деления 0,2 и 1 МПа, цифры,
   * дуги уставок LL / L / H / HH, стрелка поворачивается transform rotate (0° — «6 часов»).
   *   opts.kind: 'enamel' — эмалевый циферблат в кадре камеры; 'drawing' — чертёж тушью на бумаге
   *   → { el, needle, setAngle(θ) }
   * Координаты: viewBox −200…200, центр в нуле; кегли цифр — в единицах viewBox.
   */
  function gauge(opts) {
    opts = opts || {};
    var s = GV.util.svg;
    var c = (GV.content && GV.content.calibration) || {};
    var kind = opts.kind || 'enamel';
    var R = 168;
    var a0 = Number(c.thetaMin);
    var a1 = Number(c.thetaMax);
    var span = mod(a1 - a0, 360) || 360;
    var vMin = Number(c.vMin);
    var vMax = Number(c.vMax);
    var sp = c.setpoints || {};
    function ang(v) { return a0 + ((v - vMin) / (vMax - vMin)) * span; }

    var root = s('svg', {
      class: 'gv-gauge gv-gauge--' + kind,
      viewBox: '-200 -200 400 400',
      'aria-hidden': 'true',
      focusable: 'false'
    });
    if (kind === 'enamel') {
      root.appendChild(s('circle', { class: 'gv-gauge__case', r: 196 }));
      root.appendChild(s('circle', { class: 'gv-gauge__face', r: 184 }));
    } else {
      root.appendChild(s('circle', { class: 'gv-gauge__case', r: 196 }));
      root.appendChild(s('circle', { class: 'gv-gauge__face', r: 184 }));
      root.appendChild(s('line', { class: 'gv-gauge__axis', x1: -208, y1: 0, x2: 208, y2: 0 }));
      root.appendChild(s('line', { class: 'gv-gauge__axis', x1: 0, y1: -208, x2: 0, y2: 208 }));
    }

    var zones = s('g', { class: 'gv-gauge__zones' });
    [['LL', vMin, sp.LL, 'alert'], ['L', sp.LL, sp.L, 'warning'], ['H', sp.H, sp.HH, 'warning'], ['HH', sp.HH, vMax, 'alert']]
      .forEach(function (z) {
        if (typeof z[1] !== 'number' || typeof z[2] !== 'number' || z[2] <= z[1]) return;
        zones.appendChild(s('path', { class: 'gv-gauge__zone gv-gauge__zone--' + z[3], d: arcPath(0, 0, R - 9, ang(z[1]), ang(z[2])) }));
      });
    root.appendChild(zones);
    root.appendChild(s('path', { class: 'gv-gauge__arc', d: arcPath(0, 0, R, a0, a1) }));

    var ticks = s('g', { class: 'gv-gauge__ticks' });
    var steps = Math.round((vMax - vMin) / 0.2);
    for (var i = 0; i <= steps; i++) {
      var v = vMin + i * 0.2;
      var major = i % 5 === 0;
      var p0 = polar(0, 0, R, ang(v));
      var p1 = polar(0, 0, R - (major ? 22 : 11), ang(v));
      ticks.appendChild(s('line', { class: major ? 'gv-gauge__tick is-major' : 'gv-gauge__tick', x1: fx(p0[0]), y1: fx(p0[1]), x2: fx(p1[0]), y2: fx(p1[1]) }));
      if (major) {
        var pt = polar(0, 0, R - 46, ang(v));
        ticks.appendChild(s('text', { class: 'gv-gauge__num', x: fx(pt[0]), y: fx(pt[1]), 'font-size': 34, 'text-anchor': 'middle', 'dominant-baseline': 'central' },
          String(Math.round(v))));
      }
    }
    root.appendChild(ticks);
    root.appendChild(s('text', { class: 'gv-gauge__unit', x: 0, y: 70, 'font-size': 15, 'text-anchor': 'middle' }, c.unit || 'МПа'));
    if (opts.caption) root.appendChild(s('text', { class: 'gv-gauge__cap', x: 0, y: 98, 'font-size': 12, 'text-anchor': 'middle' }, opts.caption));

    var needle = s('g', { class: 'gv-gauge__needle' },
      s('path', { d: 'M -34 -5 L 150 -1.4 L 156 0 L 150 1.4 L -34 5 Z' }),
      s('circle', { class: 'gv-gauge__hub', r: 13 }),
      s('circle', { class: 'gv-gauge__pin', r: 4 }));
    root.appendChild(needle);
    if (kind === 'enamel') root.appendChild(s('ellipse', { class: 'gv-gauge__glass', cx: -54, cy: -88, rx: 96, ry: 44, transform: 'rotate(-28 -54 -88)' }));

    function setAngle(theta) {
      // стрелка нарисована вдоль +x («3 часа»), отсчёт сайта — от «6 часов»
      needle.setAttribute('transform', 'rotate(' + fx(theta + ZERO) + ')');
    }
    return { el: root, needle: needle, setAngle: setAngle };
  }

  /*
   * Формула вёрсткой из линейной записи (mathTree): дробь — два этажа с чертой, индексы min / max мельче
   * и ниже, знаки операций с воздухом. Экранный диктор читает label (по умолчанию — исходная строка).
   * На телефоне формула рвётся один раз — на первом «·» верхнего уровня, а если его нет, на первом знаке
   * внутри внешней скобки; знак по правилам набора повторяется в начале второй строки. На широком экране
   * разрыв скрыт, и формула идёт одной строкой.
   * slots[имя] — пустые <span> на месте {имя}: числа подставляются в них без перерисовки формулы.
   */
  function math(src, opts) {
    var h = GV.util.h;
    var slots = {};
    var visual = h('span', { class: 'gv-math__v', 'aria-hidden': 'true' });
    var tree = mathTree(src);
    function binary(list, j) {
      var k = j - 1;
      while (k >= 0 && list[k].t === 'sp') k--;
      return k >= 0 && list[k].t !== 'op';
    }
    function firstOp(list, signs) {
      for (var j = 0; j < list.length; j++) {
        if (list[j].t === 'op' && signs.indexOf(list[j].v) >= 0 && binary(list, j)) return list[j];
      }
      return null;
    }
    // короткой записи разрыв не нужен: «(θ − θmin) mod 360 =» и так входит в строку
    var brk = String(src).length > 32 ? firstOp(tree, '·') : null;
    for (var g = 0; !brk && String(src).length > 32 && g < tree.length; g++) if (tree[g].t === 'group') brk = firstOp(tree[g].items, '·−+');
    function render(items, parent) {
      items.forEach(function (n, i) {
        var prev = items[i - 1];
        var next = items[i + 1];
        if (n.t === 'sp') {
          // пробел у знака операции не нужен: у знака свой воздух
          if ((prev && prev.t === 'op') || (next && next.t === 'op')) return;
          parent.appendChild(document.createTextNode(' '));
        } else if (n.t === 'text') parent.appendChild(document.createTextNode(n.v));
        else if (n.t === 'op') {
          // минус в начале скобки или после знака — унарный, без воздуха: R(−φ)
          var unary = !binary(items, i);
          parent.appendChild(h('span', { class: unary ? 'gv-math__op gv-math__op--u' : 'gv-math__op' }, n.v));
          if (n === brk) {
            parent.appendChild(h('span', { class: 'gv-math__br' }));
            parent.appendChild(h('span', { class: 'gv-math__op gv-math__rep' }, n.v));
          }
        }
        else if (n.t === 'sub') parent.appendChild(h('span', { class: 'gv-math__id' }, n.base, h('sub', { class: 'gv-math__sub' }, n.sub)));
        else if (n.t === 'slot') parent.appendChild((slots[n.name] = h('span', { class: 'gv-math__slot' })));
        else if (n.t === 'group') {
          parent.appendChild(document.createTextNode('('));
          render(n.items, parent);
          parent.appendChild(document.createTextNode(')'));
        } else if (n.t === 'frac') {
          var num = h('span', { class: 'gv-math__num' });
          var den = h('span', { class: 'gv-math__den' });
          render(n.num, num);
          render(n.den, den);
          parent.appendChild(h('span', { class: 'gv-math__frac' }, num, den));
        }
      });
    }
    render(tree, visual);
    var label = h('span', { class: 'gv-visually-hidden' }, (opts && opts.label) || src);
    var el = h('span', { class: 'gv-math' }, label, visual);
    return { el: el, slots: slots, label: label };
  }

  kit.math = math;
  kit.gauge = gauge;
  kit.scope = scope;
  kit.sectionNav = sectionNav;
  kit.arcPath = arcPath;
  kit.polar = polar;
  kit.icon = icon;
  kit.extLink = extLink;
  kit.marked = marked;
})();
