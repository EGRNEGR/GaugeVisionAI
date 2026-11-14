/*
 * GV.components.precisionDial — #reading: прецизионный манометр по GV.content.calibration.
 * mount(el, { interactive = true }) → { destroy(), setValue(v) }
 *
 * Сцена .gv-pd закреплена на ≈ 200vh. На входе прибор проявляется из темноты (opacity + scale),
 * стрелка на пружине GV.motion.spring (жёсткость 170, демпфирование 18) идёт за прокруткой
 * от θmin к reading.theta (4,39 МПа), при наведении — к углу курсора, зажатому в шкалу;
 * ушёл курсор — возвращается. Прибор — role="slider": ←/→ (↓/↑) шаг 0,1 МПа, PageUp/PageDown — 1 МПа,
 * Home/End — край шкалы. Значение МПа, бары, θ и зона пересчитываются из угла стрелки на каждом
 * кадре (GV.kit.angleToValue, toBar, zoneOf, levelOf), цифры tabular-nums.
 * Шкала: 0–10 МПа на 270°, 100 мелких делений (0,1), 20 средних (0,5), 11 главных рисок с цифрами;
 * риски 1px (vector-effect: non-scaling-stroke). Ободок — два металлических кольца и стеклянный блик.
 * Движение — только transform (поворот стрелки, масштаб входа) и opacity (вход, подсветка зоны).
 *
 * Чистые функции (для тестов, без DOM):
 *   angleFromPointer(dx, dy) → θ°         0° — «3 часа», по часовой (ось Y вниз), [0, 360)
 *   clampAngle(θ, calib) → θ°             угол за шкалой зажимается к ближнему краю [θmin, θmax]
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var SPRING = { stiffness: 170, damping: 18, precision: 0.02 };
  var ARRIVE = 0.6;          // доля закрепления, за которую стрелка доходит до показания
  var STEP = 0.1;            // шаг клавиш ←/→, МПа
  var PAGE_STEP = 1;         // PageUp/PageDown, МПа
  var FINE = '(hover: hover) and (pointer: fine)';

  var T = {
    bar: 'бар',
    theta: 'угол θ',
    zone: 'зона уставок'
  };

  function mod(a, n) {
    return ((a % n) + n) % n;
  }

  function clamp(v, lo, hi) {
    return v < lo ? lo : (v > hi ? hi : v);
  }

  function parts(calib) {
    var ccw = String(calib.direction || 'CW').toLowerCase() === 'ccw';
    var span = ccw ? mod(calib.thetaMin - calib.thetaMax, 360) : mod(calib.thetaMax - calib.thetaMin, 360);
    return { ccw: ccw, span: span || 360, thetaMin: Number(calib.thetaMin) };
  }

  /* Смещение по шкале от θmin в сторону роста значения: 0…span; за шкалой — к ближнему краю. */
  function offsetOf(theta, calib) {
    var c = parts(calib);
    var delta = c.ccw ? mod(c.thetaMin - theta, 360) : mod(theta - c.thetaMin, 360);
    if (delta <= c.span) return delta;
    var over = delta - c.span;
    var under = 360 - delta;
    return over <= under ? c.span : 0;
  }

  /* Угол по смещению; смещение может выйти за 0…span (перелёт пружины), угол не заворачивается. */
  function angleOf(offset, calib) {
    var c = parts(calib);
    return c.ccw ? c.thetaMin - offset : c.thetaMin + offset;
  }

  function clampAngle(theta, calib) {
    return mod(angleOf(offsetOf(theta, calib), calib), 360);
  }

  function angleFromPointer(dx, dy) {
    return mod((Math.atan2(dy, dx) * 180) / Math.PI, 360);
  }

  function ease(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function mount(el, options) {
    options = options || {};
    var interactive = options.interactive !== false;
    var u = GV.util;
    var h = u.h;
    var s = u.svg;
    var kit = GV.kit;
    var motion = GV.motion;
    var fmt = u.formatNumber;
    var c = GV.content;
    var calib = c.calibration;
    var reading = c.reading;
    var sp = calib.setpoints;
    var cp = parts(calib);
    var vMin = Number(calib.vMin);
    var vMax = Number(calib.vMax);
    var NBSP = kit.NBSP;
    var sc = kit.scope();
    var offs = [];

    /* ---------- SVG прибора: viewBox 400 × 400, центр 200 ---------- */

    var C = 200;
    var R_TICK = 162;
    var R_ZONE = 170;
    var R_NUM = 134;
    var R_BAR = 118;
    var id = u.uid('gv-pd');

    function pt(r, deg) {
      var p = kit.polar(C, C, r, deg);
      return Math.round(p[0] * 100) / 100 + ' ' + Math.round(p[1] * 100) / 100;
    }
    function arc(r, offA, offB) {
      var a = angleOf(Math.min(offA, offB), calib);
      var b = angleOf(Math.max(offA, offB), calib);
      return cp.ccw ? kit.arcPath(C, C, r, b, a) : kit.arcPath(C, C, r, a, b);
    }
    function offsetOfValue(v) {
      return ((v - vMin) / (vMax - vMin)) * cp.span;
    }
    function stop(offset, color, opacity) {
      return s('stop', { offset: offset, 'stop-color': color, 'stop-opacity': opacity === undefined ? 1 : opacity });
    }
    function grad(name, x1, y1, x2, y2, stops) {
      return s('linearGradient', { id: id + '-' + name, x1: x1, y1: y1, x2: x2, y2: y2 }, stops);
    }
    function url(name) {
      return 'url(#' + id + '-' + name + ')';
    }

    var defs = s('defs', null,
      grad('bezel', 0, 0, 1, 1, [stop(0, '#6A7079'), stop(0.28, '#2A2E34'), stop(0.55, '#0D0F12'), stop(0.8, '#1E2227'), stop(1, '#4A5058')]),
      grad('chamfer', 0, 0, 1, 1, [stop(0, '#08090B'), stop(0.5, '#23272D'), stop(1, '#767D86')]),
      grad('rim', 0.1, 0, 0.9, 1, [stop(0, '#FFFFFF', 0.7), stop(0.38, '#FFFFFF', 0), stop(0.72, '#FFFFFF', 0), stop(1, '#FFFFFF', 0.18)]),
      grad('glass', 0.15, 0.05, 0.55, 0.6, [stop(0, '#FFFFFF', 0.13), stop(0.6, '#FFFFFF', 0.03), stop(1, '#FFFFFF', 0)]),
      grad('needle', 0, 0, 0, 1, [stop(0, '#FF8A57'), stop(0.5, '#FF5A1F'), stop(1, '#C93D0B')]),
      s('radialGradient', { id: id + '-face', cx: 0.5, cy: 0.4, r: 0.62 }, [stop(0, '#161B21'), stop(0.7, '#0E1115'), stop(1, '#090B0E')]),
      s('radialGradient', { id: id + '-hub', cx: 0.35, cy: 0.3, r: 0.8 }, [stop(0, '#7A818A'), stop(0.45, '#2B3036'), stop(1, '#101215')]));

    /* Ободок: внешнее кольцо (металл, свет сверху слева), фаска (свет снизу справа), блик по контуру */
    var bezel = s('g', { class: 'gv-pd__bezel' },
      s('circle', { cx: C, cy: C, r: 190, fill: 'none', stroke: url('bezel'), 'stroke-width': 16 }),
      s('circle', { cx: C, cy: C, r: 180, fill: 'none', stroke: url('chamfer'), 'stroke-width': 4 }),
      s('circle', { class: 'gv-pd__hair', cx: C, cy: C, r: 197.5, stroke: url('rim') }),
      s('circle', { class: 'gv-pd__hair', cx: C, cy: C, r: 181.5, stroke: url('rim') }),
      s('circle', { class: 'gv-pd__hair gv-pd__hair--dark', cx: C, cy: C, r: 178 }));

    var face = s('circle', { class: 'gv-pd__face', cx: C, cy: C, r: 178, fill: url('face') });

    /* Зоны уставок: CRITICAL · предупреждение · НОРМА · предупреждение · CRITICAL */
    var edges = [vMin, sp.LL, sp.L, sp.H, sp.HH, vMax];
    var zoneIds = ['LL', 'L', 'NORMA', 'H', 'HH'];
    var zoneLevels = ['alert', 'warning', 'normal', 'warning', 'alert'];
    var GAP = 0.8;
    var zoneEls = {};
    var zones = s('g', { class: 'gv-pd__zones' }, zoneIds.map(function (zid, i) {
      var a = offsetOfValue(edges[i]) + (i ? GAP / 2 : 0);
      var b = offsetOfValue(edges[i + 1]) - (i < 4 ? GAP / 2 : 0);
      if (!(b > a)) return null;
      var d = arc(R_ZONE, a, b);
      var g = s('g', { class: 'gv-pd__zone gv-pd__zone--' + zoneLevels[i] },
        s('path', { class: 'gv-pd__zone-glow', d: d, 'stroke-width': 12 }),
        s('path', { class: 'gv-pd__zone-band', d: d, 'stroke-width': 4 }));
      zoneEls[zid] = g;
      return g;
    }));

    /* Риски: 100 мелких делений по 0,1 МПа, средние каждые 0,5, главные каждый 1 МПа с цифрами */
    var range = vMax - vMin;
    var minor = [];
    var medium = [];
    var major = [];
    var numbers = [];
    for (var i = 0; i <= 100; i++) {
      var off = (cp.span * i) / 100;
      var ang = angleOf(off, calib);
      var len = i % 10 === 0 ? 17 : (i % 5 === 0 ? 11 : 6);
      var seg = 'M' + pt(R_TICK, ang) + ' L' + pt(R_TICK - len, ang);
      if (i % 10 === 0) {
        major.push(seg);
        var p = kit.polar(C, C, R_NUM, ang);
        numbers.push(s('text', { class: 'gv-pd__num', 'font-size': 17, x: Math.round(p[0] * 10) / 10, y: Math.round(p[1] * 10) / 10, 'text-anchor': 'middle', 'dominant-baseline': 'central' },
          fmt(vMin + (range * i) / 100)));
      } else if (i % 5 === 0) medium.push(seg);
      else minor.push(seg);
    }

    /* Внутренняя шкала в барах (1 МПа = barPerMpa бар): риска каждые 10 бар, цифры через 20 */
    var barMax = kit.toBar(vMax, calib);
    var barMin = kit.toBar(vMin, calib);
    var barTicks = [];
    var barNums = [];
    var barStep = (barMax - barMin) / 10;
    for (var j = 0; j <= 10; j++) {
      var bOff = (cp.span * j) / 10;
      var bAng = angleOf(bOff, calib);
      barTicks.push('M' + pt(R_BAR, bAng) + ' L' + pt(R_BAR - 5, bAng));
      if (j % 2 === 0) {
        var bp = kit.polar(C, C, R_BAR - 15, bAng);
        barNums.push(s('text', { class: 'gv-pd__bar-num', 'font-size': 10, x: Math.round(bp[0] * 10) / 10, y: Math.round(bp[1] * 10) / 10, 'text-anchor': 'middle', 'dominant-baseline': 'central' },
          fmt(barMin + barStep * j)));
      }
    }

    var scale = s('g', { class: 'gv-pd__scale' },
      s('path', { class: 'gv-pd__line', d: arc(R_TICK, 0, cp.span) }),
      s('path', { class: 'gv-pd__tick gv-pd__tick--minor', d: minor.join(' ') }),
      s('path', { class: 'gv-pd__tick gv-pd__tick--medium', d: medium.join(' ') }),
      s('path', { class: 'gv-pd__tick gv-pd__tick--major', d: major.join(' ') }),
      numbers,
      s('path', { class: 'gv-pd__line gv-pd__line--bar', d: arc(R_BAR, 0, cp.span) }),
      s('path', { class: 'gv-pd__tick gv-pd__tick--bar', d: barTicks.join(' ') }),
      barNums,
      s('text', { class: 'gv-pd__unit', x: C, y: 262, 'font-size': 14, 'text-anchor': 'middle' }, calib.unit),
      s('text', { class: 'gv-pd__unit gv-pd__unit--bar', x: C, y: 283, 'font-size': 11, 'text-anchor': 'middle' }, T.bar));

    /* Стрелка вдоль оси 0° («3 часа»): узкое лезвие, противовес; поворачивается только transform */
    var NEEDLE = 'M356 200 L207 196.6 L184 195.8 Q171 195.8 171 200 Q171 204.2 184 204.2 L207 203.4 Z';
    var needle = s('g', { class: 'gv-pd__needle' },
      s('path', { class: 'gv-pd__needle-body', d: NEEDLE, fill: url('needle') }),
      s('path', { class: 'gv-pd__needle-ridge', d: 'M212 200 L344 200' }));
    var shadow = s('g', { class: 'gv-pd__needle gv-pd__needle--shadow' },
      s('path', { d: NEEDLE }));
    var hub = s('g', { class: 'gv-pd__hub' },
      s('circle', { cx: C, cy: C, r: 15, fill: url('hub') }),
      s('circle', { class: 'gv-pd__hair', cx: C, cy: C, r: 15 }),
      s('circle', { class: 'gv-pd__hub-cap', cx: C, cy: C, r: 5.5 }),
      s('circle', { class: 'gv-pd__hub-pin', cx: C, cy: C, r: 1.8 }));

    /* Стекло: линза блика сверху слева и тонкий блик по внутреннему контуру */
    var glass = s('g', { class: 'gv-pd__glass' },
      s('path', { d: 'M' + pt(176, 158) + ' A176 176 0 0 1 ' + pt(176, 302) + ' A232 232 0 0 0 ' + pt(176, 158) + ' Z', fill: url('glass') }),
      s('path', { class: 'gv-pd__glint', d: kit.arcPath(C, C, 173, 196, 252), 'stroke-width': 1.5 }));

    var svgEl = s('svg', { class: 'gv-pd__svg', viewBox: '0 0 400 400', 'aria-hidden': 'true', focusable: 'false' },
      defs, bezel, face, zones, scale,
      s('g', { transform: 'translate(2.5 4.5)' }, shadow),
      needle, hub, glass);

    /* ---------- показания ---------- */

    var numEl = h('span', { class: 'gv-pd__value-num' });
    var barEl = h('dd', { class: 'gv-pd__cell-value' });
    var thetaEl = h('dd', { class: 'gv-pd__cell-value' });
    var zoneDot = h('span', { class: 'gv-pd__dot', 'aria-hidden': 'true' });
    var zoneText = h('span', null);
    var captionId = u.uid('gv-pd-caption');

    var readout = h('div', { class: 'gv-pd__readout' },
      h('p', { class: 'gv-pd__device' }, reading.device),
      h('p', { class: 'gv-pd__value' }, numEl, h('span', { class: 'gv-pd__value-unit' }, calib.unit)),
      h('dl', { class: 'gv-pd__cells' },
        h('div', { class: 'gv-pd__cell' }, h('dt', { class: 'gv-pd__cell-label' }, T.bar), barEl),
        h('div', { class: 'gv-pd__cell' }, h('dt', { class: 'gv-pd__cell-label' }, T.theta), thetaEl),
        h('div', { class: 'gv-pd__cell gv-pd__cell--zone' }, h('dt', { class: 'gv-pd__cell-label' }, T.zone), h('dd', { class: 'gv-pd__cell-value' }, zoneDot, zoneText))),
      h('p', { class: 'gv-pd__formula' }, calib.formula),
      h('p', { class: 'gv-pd__caption', id: captionId }, reading.caption));

    var dialEl = h('div', {
      class: 'gv-pd__dial',
      role: 'slider',
      tabindex: '0',
      'aria-label': reading.sliderLabel,
      'aria-valuemin': String(vMin),
      'aria-valuemax': String(vMax),
      'aria-describedby': captionId
    }, svgEl);

    var instrument = h('div', { class: 'gv-pd__instrument' },
      h('span', { class: 'gv-pd__glow', 'aria-hidden': 'true' }),
      dialEl);
    var stage = h('div', { class: 'gv-pd__stage' },
      h('div', { class: 'gv-container gv-pd__layout' }, instrument, readout));
    var scene = h('div', { class: 'gv-pd', 'data-level': 'normal' }, stage);
    el.appendChild(scene);

    /* ---------- состояние стрелки ---------- */

    var readingOffset = offsetOf(reading.theta, calib);
    var spring = motion.spring({ stiffness: SPRING.stiffness, damping: SPRING.damping, precision: SPRING.precision, value: motion.reduced() ? readingOffset : 0 });
    var scrollOffset = motion.reduced() ? readingOffset : 0;
    var hoverOffset = null;
    var manualValue = null;
    var shown = { num: '', bar: '', theta: '', zone: '', level: '' };

    function valueAt(offset) {
      return kit.angleToValue(mod(angleOf(offset, calib), 360), calib);
    }
    function targetOffset() {
      if (hoverOffset !== null) return hoverOffset;
      if (manualValue !== null) return offsetOfValue(manualValue);
      return scrollOffset;
    }

    function render(offset) {
      var theta = angleOf(offset, calib);
      var rot = 'rotate(' + theta.toFixed(2) + 'deg)';
      needle.style.transform = rot;
      shadow.style.transform = rot;
      var v = valueAt(offset);
      var num = fmt(v, 2);
      if (num !== shown.num) { numEl.textContent = num; shown.num = num; }
      var bar = fmt(kit.toBar(v, calib), 1);
      if (bar !== shown.bar) { barEl.textContent = bar; shown.bar = bar; }
      var th = fmt(mod(theta, 360), 1) + '°';
      if (th !== shown.theta) { thetaEl.textContent = th; shown.theta = th; }
      var zone = kit.zoneOf(v, sp);
      if (zone !== shown.zone) {
        if (zoneEls[shown.zone]) zoneEls[shown.zone].classList.remove('is-active');
        if (zoneEls[zone]) zoneEls[zone].classList.add('is-active');
        shown.zone = zone;
      }
      var level = kit.levelOf(v, sp);
      if (level !== shown.level) {
        zoneText.textContent = reading.zones[level];
        scene.setAttribute('data-level', level);
        shown.level = level;
      }
    }

    function syncAria() {
      var v = valueAt(targetOffset());
      var shownV = clamp(Math.round(v * 100) / 100, vMin, vMax);
      dialEl.setAttribute('aria-valuenow', String(shownV));
      dialEl.setAttribute('aria-valuetext', fmt(shownV, 2) + NBSP + calib.unit + ', ' + reading.zones[kit.levelOf(shownV, sp)]);
    }

    var offFrame = null;
    var visible = true;
    function frame(dt) {
      render(spring.step(dt));
      if (spring.settled()) {
        sleep();
        syncAria();
      }
    }
    function sleep() {
      if (offFrame) { offFrame(); offFrame = null; }
    }
    function retarget() {
      spring.target(targetOffset());
      if (!offFrame && visible) offFrame = motion.onFrame(frame);
    }

    /* ---------- прокрутка: вход сцены и цель стрелки ---------- */

    var lastProgress = -1;
    var lastEnter = -1;
    var dialRect = null;

    function onScroll(y) {
      dialRect = null;
      if (!visible) return;
      var enter = 1;
      if (!motion.reduced()) {
        var m = motion.measure(scene);
        var vh = motion.viewport().height;
        enter = clamp((y + vh - m.top) / (vh * 0.85), 0, 1);
      }
      if (Math.abs(enter - lastEnter) > 1e-4) {
        var e = ease(enter);
        instrument.style.opacity = e.toFixed(3);
        instrument.style.transform = 'scale(' + (0.9 + 0.1 * e).toFixed(4) + ')';
        readout.style.opacity = ease(clamp((enter - 0.35) / 0.65, 0, 1)).toFixed(3);
        lastEnter = enter;
      }
      var p = motion.pinProgress(scene);
      if (Math.abs(p - lastProgress) > 1e-5) {
        if (lastProgress >= 0) manualValue = null;
        lastProgress = p;
        scrollOffset = readingOffset * clamp(p / ARRIVE, 0, 1);
        retarget();
      }
    }
    offs.push(motion.onScroll(onScroll));

    if ('IntersectionObserver' in root) {
      var io = new root.IntersectionObserver(function (entries) {
        visible = entries.some(function (en) { return en.isIntersecting; });
        if (visible) {
          lastEnter = -1;
          onScroll(root.pageYOffset || 0);
          retarget();
        } else {
          sleep();
        }
      });
      io.observe(scene);
      offs.push(function () { io.disconnect(); });
    }

    /* ---------- наведение и клавиши ---------- */

    function setValue(v) {
      if (typeof v !== 'number' || !isFinite(v)) return;
      manualValue = clamp(Math.round(v * 100) / 100, vMin, vMax);
      retarget();
      syncAria();
    }

    if (interactive) {
      var fine = typeof root.matchMedia === 'function' ? root.matchMedia(FINE) : null;
      sc.on(dialEl, 'pointermove', function (e) {
        if (e.pointerType === 'touch' || (fine && !fine.matches)) return;
        if (!dialRect) dialRect = dialEl.getBoundingClientRect();
        var dx = e.clientX - (dialRect.left + dialRect.width / 2);
        var dy = e.clientY - (dialRect.top + dialRect.height / 2);
        if (Math.sqrt(dx * dx + dy * dy) < dialRect.width * 0.06) return;
        hoverOffset = offsetOf(angleFromPointer(dx, dy), calib);
        retarget();
      }, { passive: true });
      sc.on(dialEl, 'pointerleave', function () {
        dialRect = null;
        if (hoverOffset === null) return;
        hoverOffset = null;
        retarget();
      }, { passive: true });
      sc.on(dialEl, 'keydown', function (e) {
        var base = manualValue !== null ? manualValue : Math.round(valueAt(targetOffset()) * 10) / 10;
        var next = null;
        if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = base + STEP;
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = base - STEP;
        else if (e.key === 'PageUp') next = base + PAGE_STEP;
        else if (e.key === 'PageDown') next = base - PAGE_STEP;
        else if (e.key === 'Home') next = vMin;
        else if (e.key === 'End') next = vMax;
        if (next === null) return;
        e.preventDefault();
        setValue(next);
      });
    }

    render(spring.value());
    syncAria();

    return {
      setValue: setValue,
      destroy: function () {
        sleep();
        offs.forEach(function (off) { off(); });
        offs = [];
        sc.destroy();
        if (scene.parentNode) scene.parentNode.removeChild(scene);
      }
    };
  }

  GV.components.precisionDial = { mount: mount, angleFromPointer: angleFromPointer, clampAngle: clampAngle };
})();
