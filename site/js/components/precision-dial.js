/*
 * GV.components.precisionDial — лист 03 «От угла θ к мегапаскалям».
 * Прибор-чертёж тушью с размерными дугами: θmin и θmax, рабочий сектор 270°, текущий угол от θmin.
 * Справа — значение крупно, штамп зоны уставок, формула angle_to_value и та же формула с подставленными
 * числами. Мышь: стрелка следует за курсором по шкале, клик фиксирует, уход курсора возвращает
 * зафиксированное. Палец: касание и ведение ставят стрелку. Клавиатура: ползунок ← → (Shift — шаг 1 МПа).
 * «Записать в журнал» отправляет показание на лист 01 строкой «ваша запись».
 *
 *   mount(body, { reading }) → { destroy }
 *   angleFromPointer(dx, dy) → θ           угол точки относительно центра (0° — «3 часа», по часовой, ось Y вниз)
 *   clampAngle(θ, calib) → θ               угол в «мёртвом» секторе под шкалой прижимается к ближнему краю
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  function mod(a, n) {
    return ((a % n) + n) % n;
  }

  function angleFromPointer(dx, dy) {
    return mod((Math.atan2(dy, dx) * 180) / Math.PI, 360);
  }

  /* Рабочий сектор идёт по часовой от θmin до θmax (CW) или против (CCW). Вне его — ближний край. */
  function clampAngle(theta, calib) {
    var a0 = Number(calib.thetaMin);
    var a1 = Number(calib.thetaMax);
    var ccw = String(calib.direction || 'CW').toLowerCase() === 'ccw';
    var span = ccw ? mod(a0 - a1, 360) : mod(a1 - a0, 360);
    var d = ccw ? mod(a0 - theta, 360) : mod(theta - a0, 360);
    if (d <= span) return mod(theta, 360);
    var toMax = d - span;
    var toMin = 360 - d;
    return toMax <= toMin ? a1 : a0;
  }

  function mount(body, opts) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var s = u.svg;
    var c = GV.content;
    var t = c.reading;
    var calib = c.calibration;
    var reading = opts.reading;
    var sc = kit.scope();
    var fmt = u.formatNumber;
    var fine = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    body.classList.add('gv-dial');

    /* ---------- чертёж ---------- */

    var g = kit.gauge({ kind: 'drawing' });
    var svgEl = g.el;
    var dims = s('g', { class: 'gv-dial__dims' });
    function ray(theta, r0, r1, cls) {
      var p0 = kit.polar(0, 0, r0, theta);
      var p1 = kit.polar(0, 0, r1, theta);
      return s('line', { class: cls, x1: p0[0].toFixed(1), y1: p0[1].toFixed(1), x2: p1[0].toFixed(1), y2: p1[1].toFixed(1) });
    }
    function label(theta, r, text, cls) {
      var p = kit.polar(0, 0, r, theta);
      var anchor = Math.cos((theta * Math.PI) / 180) > 0.2 ? 'start' : (Math.cos((theta * Math.PI) / 180) < -0.2 ? 'end' : 'middle');
      return s('text', { class: cls || 'gv-dial__dim-t', x: p[0].toFixed(1), y: p[1].toFixed(1), 'font-size': 13, 'text-anchor': anchor, 'dominant-baseline': 'central' }, text);
    }
    dims.appendChild(ray(calib.thetaMin, 186, 236, 'gv-dial__ext'));
    dims.appendChild(ray(calib.thetaMax, 186, 236, 'gv-dial__ext'));
    dims.appendChild(s('path', { class: 'gv-dial__span', d: kit.arcPath(0, 0, 226, calib.thetaMin, calib.thetaMax) }));
    dims.appendChild(label(calib.thetaMin, 252, 'θmin ' + calib.thetaMin + '° → ' + calib.vMin));
    dims.appendChild(label(calib.thetaMax, 252, 'θmax ' + calib.thetaMax + '° → ' + calib.vMax));
    dims.appendChild(label(270, 244, t.spanLabel.toLowerCase() + ' ' + calib.span + '°', 'gv-dial__dim-t gv-dial__dim-t--span'));
    var deltaArc = s('path', { class: 'gv-dial__delta' });
    var thetaRay = s('line', { class: 'gv-dial__ray' });
    dims.appendChild(deltaArc);
    dims.appendChild(thetaRay);
    svgEl.insertBefore(dims, g.needle);
    svgEl.setAttribute('viewBox', '-280 -262 560 524');

    var drawing = h('figure', { class: 'gv-dial__drawing' },
      h('div', { class: 'gv-dial__svg' }, svgEl),
      h('figcaption', { class: 'gv-caption gv-dial__cap' }, t.device + '. ' + t.caption));

    /* ---------- показания ---------- */

    var valueEl = h('span', { class: 'gv-dial__v gv-num' });
    var barEl = h('span', { class: 'gv-num' });
    var zone = h('span', { class: 'gv-mark gv-mark--stamp' });
    var thetaEl = h('span', { class: 'gv-num' });
    var deltaEl = h('span', { class: 'gv-num gv-dial__delta-v' });
    var subst = h('code', { class: 'gv-dial__subst' });

    var slider = h('input', {
      class: 'gv-dial__range',
      type: 'range',
      id: u.uid('gv-range'),
      min: String(calib.vMin),
      max: String(calib.vMax),
      step: '0.01'
    });
    var sliderLabel = h('label', { class: 'gv-label', for: slider.id }, t.sliderLabel);

    var writeBtn = h('button', { class: 'gv-dial__write', type: 'button' }, kit.icon('right'), h('span', null, t.write));
    var written = h('p', { class: 'gv-dial__written', role: 'status' });

    var panel = h('div', { class: 'gv-dial__panel' },
      h('p', { class: 'gv-dial__value' }, valueEl, h('span', { class: 'gv-dial__unit' }, calib.unit)),
      h('div', { class: 'gv-dial__meta' },
        h('span', { class: 'gv-dial__bar' }, barEl, h('span', { class: 'gv-label' }, t.barLabel)),
        h('span', { class: 'gv-dial__zone' }, h('span', { class: 'gv-label' }, t.zoneLabel), zone)),
      h('dl', { class: 'gv-dial__f' },
        h('dt', { class: 'gv-label' }, t.formulaLabel),
        h('dd', null, h('code', null, calib.formula)),
        h('dt', { class: 'gv-label' }, t.substitution),
        h('dd', null, subst),
        h('dt', { class: 'gv-label' }, t.angleLabel),
        h('dd', { class: 'gv-dial__angles' }, thetaEl, h('span', { class: 'gv-dial__delta-k' }, '(θ − θmin) mod 360 ='), deltaEl)),
      h('div', { class: 'gv-dial__ctl' }, sliderLabel, slider,
        h('p', { class: 'gv-dial__hint' }, fine ? t.hint : t.hintTouch)),
      h('div', { class: 'gv-dial__act' }, writeBtn, written));

    body.appendChild(drawing);
    body.appendChild(panel);

    /* ---------- рисование по углу ---------- */

    function paint(theta) {
      g.setAngle(theta);
      var v = kit.angleToValue(theta, calib);
      var level = kit.levelOf(v, calib.setpoints);
      var delta = mod(theta - calib.thetaMin, 360);
      valueEl.textContent = fmt(v, 2);
      barEl.textContent = fmt(kit.toBar(v, calib), 1) + kit.NBSP + 'бар';
      if (zone.getAttribute('data-tone') !== level) {
        zone.setAttribute('data-tone', level);
        zone.textContent = t.zones[level];
      }
      thetaEl.textContent = fmt(mod(theta, 360), 1) + '°';
      subst.textContent = 'V = ' + fmt(calib.vMin, 0) + ' + ((' + fmt(mod(theta, 360), 1) + '° − ' + calib.thetaMin + '°) mod 360) / ' +
        calib.span + ' · (' + calib.vMax + ' − ' + calib.vMin + ') = ' + fmt(v, 2);
      deltaArc.setAttribute('d', kit.arcPath(0, 0, 204, calib.thetaMin, calib.thetaMin + Math.max(delta, 0.01)));
      var p0 = kit.polar(0, 0, 18, theta);
      var p1 = kit.polar(0, 0, 212, theta);
      thetaRay.setAttribute('x1', p0[0].toFixed(1));
      thetaRay.setAttribute('y1', p0[1].toFixed(1));
      thetaRay.setAttribute('x2', p1[0].toFixed(1));
      thetaRay.setAttribute('y2', p1[1].toFixed(1));
      deltaEl.textContent = fmt(delta, 1) + '°';
      if (document.activeElement !== slider) slider.value = v.toFixed(2);
      slider.setAttribute('aria-valuetext', fmt(v, 2) + ' ' + calib.unit + ', ' + t.zones[level]);
    }

    var spring = motion.spring({ stiffness: 170, damping: 18, value: reading.get(), precision: 0.02 });
    var offSpring = null;
    function wake() {
      if (offSpring) return;
      offSpring = motion.onFrame(function (dt) {
        paint(spring.step(dt));
        if (spring.settled()) { offSpring(); offSpring = null; }
      });
    }
    sc.add(function () { if (offSpring) offSpring(); });
    function aim(theta) {
      spring.target(theta);
      wake();
    }
    paint(reading.get());
    sc.add(reading.on(function (theta) { aim(theta); }));

    /* ---------- управление ---------- */

    var fixed = reading.get();
    function pointerTheta(e) {
      var box = svgEl.getBoundingClientRect();
      // центр прибора — точка (0, 0) viewBox −280 −262 560 524
      var cx = box.left + (280 / 560) * box.width;
      var cy = box.top + (262 / 524) * box.height;
      return clampAngle(angleFromPointer(e.clientX - cx, e.clientY - cy), calib);
    }
    var pressing = false;
    sc.on(svgEl, 'pointerdown', function (e) {
      pressing = true;
      svgEl.setPointerCapture(e.pointerId);
      fixed = pointerTheta(e);
      reading.set(fixed, 'dial');
    });
    sc.on(svgEl, 'pointermove', function (e) {
      if (pressing) {
        fixed = pointerTheta(e);
        reading.set(fixed, 'dial');
      } else if (e.pointerType === 'mouse') {
        reading.set(pointerTheta(e), 'dial');
      }
    });
    function release() { pressing = false; }
    sc.on(svgEl, 'pointerup', release);
    sc.on(svgEl, 'pointercancel', release);
    sc.on(svgEl, 'pointerleave', function (e) {
      if (!pressing && e.pointerType === 'mouse') reading.set(fixed, 'dial');
    });
    sc.add(reading.on(function (theta, from) {
      if (from !== 'dial') fixed = theta;
    }));

    sc.on(slider, 'input', function () {
      var v = Number(slider.value);
      fixed = kit.valueToAngle(v, calib);
      reading.set(fixed, 'dial');
    });
    sc.on(slider, 'keydown', function (e) {
      if (!e.shiftKey || (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
      e.preventDefault();
      var dir = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1 : -1;
      var v = Math.max(calib.vMin, Math.min(calib.vMax, Number(slider.value) + dir));
      slider.value = String(v);
      fixed = kit.valueToAngle(v, calib);
      reading.set(fixed, 'dial');
    });

    var cancelNote = null;
    sc.on(writeBtn, 'click', function () {
      reading.commit(fixed);
      written.textContent = '';
      written.appendChild(h('a', { href: '#hero' }, t.written));
      written.classList.remove('is-on');
      void written.offsetWidth;
      written.classList.add('is-on');
      if (cancelNote) cancelNote();
      cancelNote = sc.timeout(function () { written.classList.remove('is-on'); }, 6000);
    });

    /* штамп зоны падает, когда лист в кадре */
    sc.observe(u.onVisible(panel, function () { panel.classList.add('gv-stamped'); }, { once: true, threshold: 0.4 }));

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.precisionDial = { mount: mount, angleFromPointer: angleFromPointer, clampAngle: clampAngle };
})();
