/*
 * GV.components.journal — лист 01 «Прибор пишет журнал сам» (GaugeVision AI 3.0).
 * Слева h1 плакатом, слоган, суть с маркером, действия (штамп GitHub v3.0.0, режим демонстрации,
 * переход вниз) и живой журнал смены (рука обходчика + машинные строки камеры 3 к/с).
 * Справа — вклеенный кадр камеры (.gv-plate) с интерактивным эмалевым прибором 0–10 МПа.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});

  var SHIFT_START = 8 * 3600000;
  var FRAME_MS = 1000 / 3;
  var ROWS = 6;
  var KEEP = 360;
  var SPARE = 180;
  var IDLE_MS = 4000;
  var INTENT_MS = 400;
  var TAG = 'МН-1';
  var JITTER = 0.6;
  var ALPHA = 0.25;

  function mod(a, n) {
    return ((a % n) + n) % n;
  }

  function angleFromPointer(dx, dy) {
    return mod((Math.atan2(dy, dx) * 180) / Math.PI - 90, 360);
  }

  function clampAngle(theta, calib, prev) {
    var a0 = Number(calib.thetaMin);
    var a1 = Number(calib.thetaMax);
    var ccw = String(calib.direction || 'CW').toLowerCase() === 'ccw';
    var span = ccw ? mod(a0 - a1, 360) : mod(a1 - a0, 360);
    var d = ccw ? mod(a0 - theta, 360) : mod(theta - a0, 360);
    if (d <= span) return mod(theta, 360);
    if (typeof prev === 'number') {
      var dp = ccw ? mod(a0 - prev, 360) : mod(prev - a0, 360);
      if (dp <= span) return dp > span / 2 ? a1 : a0;
    }
    var toMax = d - span;
    var toMin = 360 - d;
    return toMax <= toMin ? a1 : a0;
  }

  function mount(body, opts) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var t = c.hero;
    var calib = c.calibration;
    var reading = opts.reading;
    var sc = kit.scope();
    var fmt = u.formatNumber;
    var fine = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    body.classList.add('gv-hero');

    /* ---------- заголовок, слоган, суть, действия ---------- */

    var words = t.title.split(' ');
    var cut = Math.ceil(words.length / 2);
    var title = h('h1', { class: 'gv-hero__title', id: opts.headId, 'data-reveal': 'words' },
      h('span', { class: 'gv-hero__l1' }, words.slice(0, cut).join(' ')), ' ',
      h('span', { class: 'gv-hero__l2' }, words.slice(cut).join(' ')));
    var slogan = h('p', { class: 'gv-hero__slogan', 'data-reveal': '' }, t.slogan);
    var line = h('p', { class: 'gv-hero__line', 'data-reveal': '' }, kit.marked(t.line, t.lineAccent));

    var cta = kit.extLink({ class: 'gv-stamp gv-hero__cta', href: c.meta.tagUrl }, kit.icon('github'), h('span', null, t.cta));
    var demoBtn = h('button', { class: 'gv-btn-paper gv-hero__demo-btn', type: 'button', 'data-showcase-open': '' }, h('span', null, t.ctaDemo));
    var next = h('a', { class: 'gv-arrow-link', href: '#compare' }, h('span', null, t.ctaNext), kit.icon('arrow'));
    var actions = h('div', { class: 'gv-hero__actions', 'data-reveal': '' }, cta, demoBtn, next);
    sc.add(motion.magnet(cta, { pull: 0.2, max: 0.375 }));

    /* ---------- журнал ---------- */

    function cell(cls, content) {
      return h('span', { class: 'gv-log__c gv-log__c--' + cls, role: 'cell' }, content);
    }
    var head = h('div', { class: 'gv-log__row gv-log__row--head', role: 'row' },
      t.columns.map(function (col, i) {
        return h('span', { class: 'gv-log__c gv-log__c--' + ['time', 'tag', 'value', 'who'][i], role: 'columnheader' }, col);
      }));

    function handWrite(text, delay) {
      return h('span', { class: 'gv-write gv-hand', style: { '--gv-write-delay': delay + 'ms' } }, text);
    }
    var handVal = fmt(kit.angleToValue(reading.get(), calib), 1);
    var handRow = h('div', { class: 'gv-log__row gv-log__row--hand', role: 'row' },
      cell('time', handWrite('08:00', 300)),
      cell('tag', handWrite(TAG, 700)),
      cell('value', handWrite(handVal, 1000)),
      cell('who', handWrite(t.hand, 1400)));

    var stream = h('div', { class: 'gv-log__stream', 'aria-hidden': 'true' });
    var scroller = h('div', { class: 'gv-log__scroll' });
    var track = h('div', { class: 'gv-log__track' });
    scroller.appendChild(track);
    stream.appendChild(scroller);
    var freshCount = h('span', { class: 'gv-log__fresh-n gv-num' });
    var fresh = h('button', { class: 'gv-log__fresh', type: 'button', hidden: true },
      kit.icon('arrow'), h('span', null, t.fresh), freshCount);

    var latest = h('p', { class: 'gv-visually-hidden', 'aria-live': 'polite' });
    var log = h('div', { class: 'gv-log', 'data-reveal': '' },
      h('div', { class: 'gv-log__table', role: 'table', 'aria-label': c.meta.form },
        h('div', { role: 'rowgroup' }, head),
        h('div', { role: 'rowgroup' }, handRow),
        stream),
      fresh);
    var demo = h('p', { class: 'gv-hero__demo gv-caption' },
      h('span', { class: 'gv-mark', 'data-tone': 'warning' }, c.labels.sim), ' ',
      t.demo, '. ', t.rate, '.');

    /* ---------- кадр камеры ---------- */

    var g = kit.gauge({ kind: 'enamel' });
    var dialBox = h('div', {
      class: 'gv-hero__dial',
      role: 'slider',
      tabindex: '0',
      'aria-label': c.reading.sliderLabel,
      'aria-valuemin': String(calib.vMin),
      'aria-valuemax': String(calib.vMax)
    }, g.el);
    var thetaOut = h('span', { class: 'gv-num' });
    var valueOut = h('span', { class: 'gv-num' });
    var dot = h('span', { class: 'gv-hero__dot', 'aria-hidden': 'true' });
    var frame = h('figure', { class: 'gv-hero__frame gv-plate', 'data-reveal': '' },
      h('div', { class: 'gv-hero__frame-bar' },
        h('span', null, t.dialLabel),
        h('span', { class: 'gv-hero__rec' }, dot, TAG)),
      dialBox,
      h('figcaption', { class: 'gv-hero__read' },
        h('span', { class: 'gv-hero__read-k' }, 'θ'), thetaOut,
        h('span', { class: 'gv-hero__read-k' }, 'V'), valueOut),
      h('p', { class: 'gv-hero__hint' }, fine ? t.dialHint : t.dialHintTouch));

    body.appendChild(title);
    body.appendChild(frame);
    body.appendChild(slogan);
    body.appendChild(line);
    body.appendChild(actions);
    body.appendChild(log);
    body.appendChild(demo);
    body.appendChild(latest);

    sc.observe(u.onVisible(log, function () {
      Array.prototype.forEach.call(handRow.querySelectorAll('.gv-write'), function (el) { el.classList.add('is-written'); });
    }, { once: true, threshold: 0.3 }));

    /* ---------- стрелка: пружина, указатель, клавиатура ---------- */

    var spring = motion.spring({ stiffness: 170, damping: 18, value: kit.valueToAngle(calib.vMin, calib), precision: 0.02 });
    var shown = spring.value();

    function paintNeedle(theta) {
      theta = clampAngle(theta, calib);
      g.setAngle(theta);
      var v = kit.angleToValue(theta, calib);
      thetaOut.textContent = fmt(mod(theta, 360), 1) + '°';
      valueOut.textContent = fmt(v, 2) + kit.NBSP + calib.unit;
      dialBox.setAttribute('aria-valuenow', v.toFixed(2));
      dialBox.setAttribute('aria-valuetext', fmt(v, 2) + ' ' + calib.unit);
    }

    var offSpring = null;
    function wakeSpring() {
      if (offSpring) return;
      offSpring = motion.onFrame(function (dt) {
        shown = spring.step(dt);
        paintNeedle(shown);
        if (spring.settled()) { offSpring(); offSpring = null; }
      });
    }
    sc.add(function () { if (offSpring) offSpring(); });

    function aim(theta) {
      spring.target(theta);
      wakeSpring();
    }
    sc.add(reading.on(function (theta) { aim(theta); }));

    function pointerTheta(e, follow) {
      var box = g.el.getBoundingClientRect();
      return clampAngle(
        angleFromPointer(e.clientX - (box.left + box.width / 2), e.clientY - (box.top + box.height / 2)),
        calib,
        follow ? reading.get() : undefined
      );
    }
    var dragging = false;
    sc.on(dialBox, 'pointerdown', function (e) {
      dragging = true;
      dialBox.setPointerCapture(e.pointerId);
      dialBox.classList.add('is-dragging');
      reading.set(pointerTheta(e), 'hero');
    });
    sc.on(dialBox, 'pointermove', function (e) {
      if (dragging) reading.set(pointerTheta(e, true), 'hero');
    });
    function stop() {
      dragging = false;
      dialBox.classList.remove('is-dragging');
    }
    sc.on(dialBox, 'pointerup', stop);
    sc.on(dialBox, 'pointercancel', stop);
    sc.on(dialBox, 'keydown', function (e) {
      var v = kit.angleToValue(reading.get(), calib);
      var step = e.shiftKey ? 1 : 0.1;
      var nextV = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowUp') nextV = v + step;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') nextV = v - step;
      else if (e.key === 'Home') nextV = calib.vMin;
      else if (e.key === 'End') nextV = calib.vMax;
      if (nextV === null) return;
      e.preventDefault();
      nextV = Math.max(calib.vMin, Math.min(calib.vMax, nextV));
      reading.set(kit.valueToAngle(nextV, calib), 'hero');
    });

    /* ---------- машинные строки ---------- */

    var ema = null;
    var clock = SHIFT_START;
    var rows = [];
    var lastLevel = 'normal';
    var seed = Math.random() * 10;

    function shakeAt(ms) {
      var p = seed + ((ms - SHIFT_START) / 1000) * 5.1;
      return JITTER * (Math.sin(p) * 0.6 + Math.sin(p * 2.3 + 1) * 0.4);
    }
    function measure() {
      var raw = kit.angleToValue(clampAngle(shown + shakeAt(clock), calib), calib);
      ema = kit.emaStep(ema, raw, ALPHA);
      return ema;
    }

    function rowFor(ms, value, mine, quiet) {
      var level = kit.levelOf(value, calib.setpoints);
      var changed = level !== lastLevel;
      lastLevel = level;
      var who = [h('span', { class: 'gv-log__machine' }, t.machine)];
      if (level !== 'normal') who.push(h('span', { class: 'gv-mark' + (changed && !quiet ? ' is-new' : ''), 'data-tone': level }, c.reading.zones[level]));
      if (mine) who.push(h('span', { class: 'gv-hand gv-log__mine' }, 'ваша запись'));
      return h('div', { class: 'gv-log__row gv-log__row--machine' + (mine ? ' is-mine' : '') + (quiet ? '' : ' is-in') },
        h('span', { class: 'gv-log__c gv-log__c--time' }, kit.clockText(ms)),
        h('span', { class: 'gv-log__c gv-log__c--tag' }, TAG),
        h('span', { class: 'gv-log__c gv-log__c--value gv-num' }, fmt(value, 2)),
        h('span', { class: 'gv-log__c gv-log__c--who' }, who));
    }

    var following = true;
    var unseen = 0;
    var intentAt = -Infinity;
    var lastTop = 0;
    var touchY = null;
    var cancelIdle = null;
    var cancelSettle = null;
    var offset = 0;
    var rowH = 0;
    function now() { return window.performance ? performance.now() : Date.now(); }
    function atEnd() {
      var row = rows.length ? rows[rows.length - 1].offsetHeight : 0;
      return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < row * 1.5 + 2;
    }
    function toEnd() { scroller.scrollTop = scroller.scrollHeight; }
    function glide(px) {
      offset = Math.max(0, px);
      track.style.transform = offset > 0.05 ? 'translate3d(0, ' + offset.toFixed(2) + 'px, 0)' : '';
    }
    function showFresh() {
      freshCount.textContent = unseen ? '+' + unseen : '';
      fresh.hidden = following;
    }
    function idle() {
      if (cancelIdle) cancelIdle();
      cancelIdle = sc.timeout(resume, IDLE_MS);
    }
    function follow() {
      if (cancelIdle) { cancelIdle(); cancelIdle = null; }
      if (cancelSettle) { cancelSettle(); cancelSettle = null; }
      following = true;
      unseen = 0;
      glide(0);
      toEnd();
      showFresh();
    }
    function resume() {
      if (cancelIdle) { cancelIdle(); cancelIdle = null; }
      if (motion.reduced()) { follow(); return; }
      scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
      if (cancelSettle) cancelSettle();
      cancelSettle = sc.timeout(follow, 700);
    }
    function pause() {
      if (following && offset) scroller.scrollTop -= offset;
      glide(0);
      following = false;
      if (cancelSettle) { cancelSettle(); cancelSettle = null; }
      idle();
      showFresh();
    }
    function intent() { intentAt = now(); }
    sc.on(scroller, 'wheel', function (e) { intent(); if (e.deltaY < 0) pause(); else if (!following) idle(); }, { passive: true });
    sc.on(scroller, 'touchstart', function (e) { intent(); touchY = e.touches[0].clientY; }, { passive: true });
    sc.on(scroller, 'touchmove', function (e) {
      intent();
      var y = e.touches[0].clientY;
      if (touchY !== null && y > touchY + 1) pause();
      else if (!following) idle();
      touchY = y;
    }, { passive: true });
    sc.on(scroller, 'touchend', function () { intent(); touchY = null; }, { passive: true });
    sc.on(scroller, 'pointerdown', function (e) { intent(); if (e.offsetX > scroller.clientWidth) pause(); });
    sc.on(scroller, 'scroll', function () {
      var top = scroller.scrollTop;
      var dir = top - lastTop;
      lastTop = top;
      if (now() - intentAt > INTENT_MS) return;
      intent();
      if (following) return;
      if (dir > 0 && atEnd()) follow();
      else idle();
    }, { passive: true });
    sc.on(fresh, 'click', resume);

    var logInView = false;
    var unlit = [];
    function light() {
      unlit.forEach(function (row) { row.classList.add('is-lit'); });
      unlit = [];
    }
    sc.observe(u.onVisible(log, function (isIn) {
      logInView = isIn;
      if (isIn) light();
    }, { threshold: 0.6 }));

    function push(mine, exact, quiet) {
      clock += FRAME_MS;
      var value = typeof exact === 'number' ? exact : measure();
      var row = rowFor(clock, value, mine, quiet);
      track.appendChild(row);
      rows.push(row);
      if (mine) {
        unlit.push(row);
        if (logInView) light();
      }
      if (!following) {
        unseen += 1;
        if (rows.length > KEEP + SPARE) {
          var gone = rows.shift();
          var lost = gone.offsetHeight;
          track.removeChild(gone);
          scroller.scrollTop -= lost;
        }
        showFresh();
        return;
      }
      while (rows.length > KEEP) track.removeChild(rows.shift());
      toEnd();
      if (!quiet && !motion.reduced()) {
        if (!rowH) rowH = row.offsetHeight;
        glide(Math.min(offset + rowH, rowH * 3));
      }
    }

    shown = kit.valueToAngle(calib.vMin, calib);
    paintNeedle(shown);
    var startTheta = reading.get();
    shown = startTheta;
    for (var i = 0; i < ROWS; i++) push(false, undefined, true);
    shown = spring.value();
    paintNeedle(shown);

    var visible = false;
    var acc = 0;
    var offTick = null;
    function flash() {
      dot.classList.add('is-frame');
      sc.timeout(function () { dot.classList.remove('is-frame'); }, 90);
    }
    function tick(dt) {
      if (offset > 0 && rowH) glide(offset - dt * 1000 * (rowH / FRAME_MS) * Math.max(1, offset / rowH));
      acc += dt * 1000;
      while (acc >= FRAME_MS) {
        acc -= FRAME_MS;
        push(false);
        flash();
      }
      if (!offSpring && !dragging) g.setAngle(clampAngle(shown + shakeAt(clock + acc), calib));
    }
    function syncStream() {
      var run = visible && !document.hidden && !motion.reduced();
      if (run && !offTick) {
        glide(0);
        if (following) toEnd();
        offTick = motion.onFrame(tick);
      }
      if (!run && offTick) { offTick(); offTick = null; acc = 0; }
    }
    sc.observe(u.onVisible(body, function (isIn) { visible = isIn; syncStream(); }, { threshold: 0.05 }));
    sc.on(document, 'visibilitychange', syncStream);
    sc.add(function () { if (offTick) offTick(); });

    sc.timeout(function () { aim(startTheta); }, motion.reduced() ? 0 : 450);
    sc.add(reading.on(function () { if (motion.reduced()) push(false); }));
    sc.add(reading.onCommit(function (theta) {
      shown = theta;
      spring.set(theta);
      paintNeedle(theta);
      ema = kit.angleToValue(theta, calib);
      push(true, ema);
      latest.textContent = c.reading.written + ': ' + fmt(ema, 2) + ' ' + calib.unit;
    }));

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.journal = { mount: mount, angleFromPointer: angleFromPointer, clampAngle: clampAngle };
})();
