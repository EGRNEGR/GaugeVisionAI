/*
 * GV.components.shift — лист 02 «Двенадцать часов против трети секунды».
 *   1. Закреплённая сцена во всю ширину: ролик Gemini перематывается прокруткой — обходчик дописывает
 *      журнал и уходит, на поручне остаётся камера. currentTime догоняет прогресс с инерцией;
 *      подписи «было / стало» сменяются на середине. При «уменьшить движение» — два кадра рядом.
 *   2. Шкала смены в масштабе: 12 ч, обходы в 0 и 12 ч. Отклонение тянут по смене (или стрелками):
 *      окно, в котором обходчик его не видит, растёт до следующего обхода; у камеры — ⅓ с,
 *      которую на этой шкале не разглядеть, поэтому рядом лупа на одну секунду с тремя кадрами.
 *   3. Затраты на точку: полосы в точной пропорции 33 000 к 300 000 и итог −89 % (оценка команды).
 *   4. «Было» и «Стало» — две колонки строк.
 *
 *   mount(body, { sheet }) → { destroy }
 *   timeFor(progress, duration) → секунды ролика для прогресса прокрутки 0..1
 *   delayHours(hour, rounds, shiftHours) → часов до следующего обхода
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  function timeFor(progress, duration) {
    if (!isFinite(duration) || duration <= 0) return 0;
    var p = Math.max(0, Math.min(1, progress));
    return p * Math.max(0, duration - 0.05);
  }

  function delayHours(hour, rounds, shiftHours) {
    var next = null;
    rounds.forEach(function (r) {
      if (r > hour && (next === null || r < next)) next = r;
    });
    if (next === null) next = shiftHours + (rounds.length ? Math.min.apply(null, rounds) : 0);
    return next - hour;
  }

  function mount(body, opts) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var t = c.compare;
    var tl = t.timeline;
    var sc = kit.scope();
    var fmt = u.formatNumber;
    var NBSP = kit.NBSP;

    body.classList.add('gv-shift');

    /* ---------- 0. строка-тезис ---------- */
    body.appendChild(h('p', { class: 'gv-shift__lead', 'data-reveal': '' }, t.outside));

    /* ---------- 1. сцена с роликом ---------- */

    var reduced = motion.reduced();
    var small = window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
    var stage = h('div', { class: 'gv-shift__stage' + (reduced ? ' is-still' : '') });
    var capBefore = h('p', { class: 'gv-shift__cap gv-shift__cap--before' }, t.captions.before);
    var capAfter = h('p', { class: 'gv-shift__cap gv-shift__cap--after' }, t.captions.after);
    var marker = h('span', { class: 'gv-shift__marker' });
    var clockRuler = h('div', { class: 'gv-shift__clock', 'aria-hidden': 'true' },
      h('span', { class: 'gv-shift__clock-line' }), marker);

    if (reduced) {
      stage.appendChild(h('div', { class: 'gv-shift__pair' },
        h('figure', { class: 'gv-shift__still gv-plate' },
          h('img', { src: t.video.poster, alt: t.captions.before, width: 1280, height: 720, loading: 'lazy' }), capBefore),
        h('figure', { class: 'gv-shift__still gv-plate' },
          h('img', { src: t.video.posterAfter, alt: t.captions.after, width: 1280, height: 720, loading: 'lazy' }), capAfter)));
    } else {
      var video = h('video', {
        class: 'gv-shift__video',
        muted: true,
        playsinline: true,
        preload: 'auto',
        poster: t.video.poster,
        'aria-label': t.video.label
      });
      video.muted = true;
      video.setAttribute('muted', '');
      video.src = small ? t.video.srcMobile : t.video.src;
      var after = h('img', { class: 'gv-shift__after', src: t.video.posterAfter, alt: '', 'aria-hidden': 'true' });
      var pin = h('div', { class: 'gv-shift__pin gv-plate' }, video, after, h('div', { class: 'gv-shift__shade' }), capBefore, capAfter, clockRuler);
      stage.appendChild(pin);

      var duration = NaN;
      var shownT = 0;
      var progress = 0;
      var offFrame = null;
      var failed = false;
      sc.on(video, 'loadedmetadata', function () { duration = video.duration; wake(); });
      sc.on(video, 'error', function () { failed = true; stage.classList.add('is-fallback'); });
      if (video.readyState >= 1) duration = video.duration;

      function paint() {
        var target = timeFor(progress, duration);
        if (!failed && isFinite(duration)) {
          shownT += (target - shownT) * 0.18;
          if (Math.abs(target - shownT) < 0.01) shownT = target;
          if (Math.abs(video.currentTime - shownT) > 0.02) {
            try { video.currentTime = shownT; } catch (e) { /* ещё не готов к перемотке */ }
          }
        }
        var after = progress > 0.55;
        capBefore.classList.toggle('is-on', !after);
        capAfter.classList.toggle('is-on', after);
        stage.classList.toggle('is-after', after);
        marker.style.transform = 'translate3d(' + (progress * 100).toFixed(2) + 'cqw, 0, 0)';
        // без ролика (ошибка загрузки) второй кадр проявляется opacity поверх первого
        if (failed) stage.style.setProperty('--after', String(Math.max(0, Math.min(1, (progress - 0.5) / 0.3))));
        if (Math.abs(timeFor(progress, duration) - shownT) < 0.01 && offFrame) { offFrame(); offFrame = null; }
      }
      function wake() {
        if (!offFrame) offFrame = motion.onFrame(paint);
      }
      sc.add(motion.onScroll(function () {
        progress = motion.pinProgress(stage);
        wake();
      }));
      sc.add(function () { if (offFrame) offFrame(); });
    }
    body.appendChild(stage);

    /* ---------- 2. шкала смены ---------- */

    var H = tl.shiftHours;
    var hour = tl.deviationHour;
    function pct(x) { return (x / H) * 100; }

    var scale = h('div', { class: 'gv-ruler__scale', 'aria-hidden': 'true' });
    for (var i = 0; i <= H; i++) {
      scale.appendChild(h('span', { class: 'gv-ruler__tick' + (i % 3 === 0 ? ' is-major' : '') + (i === H ? ' is-end' : '') + (i === 0 ? ' is-start' : ''), style: { left: pct(i) + '%' } },
        i % 3 === 0 ? h('span', { class: 'gv-ruler__h' }, i + NBSP + 'ч') : null));
    }

    var blind = h('span', { class: 'gv-ruler__blind' });
    var handTrack = h('div', { class: 'gv-ruler__track gv-ruler__track--hand' },
      tl.rounds.map(function (r) {
        return h('span', { class: 'gv-ruler__round' + (r >= H ? ' is-end' : ''), style: { left: pct(r) + '%' } }, h('span', { class: 'gv-hand' }, tl.roundLabel));
      }), blind);
    var camTick = h('span', { class: 'gv-ruler__cam-hit' });
    var camTrack = h('div', { class: 'gv-ruler__track gv-ruler__track--cam' }, camTick);

    var devLabel = h('span', { class: 'gv-ruler__dev-label' });
    var dev = h('div', {
      class: 'gv-ruler__dev',
      role: 'slider',
      tabindex: '0',
      'aria-label': tl.deviationLabel,
      'aria-valuemin': '0',
      'aria-valuemax': String(H)
    }, h('span', { class: 'gv-ruler__dev-line' }), devLabel);

    var field = h('div', { class: 'gv-ruler__field' },
      scale,
      h('div', { class: 'gv-ruler__row' }, h('span', { class: 'gv-ruler__name' }, tl.handRow), handTrack),
      h('div', { class: 'gv-ruler__row' }, h('span', { class: 'gv-ruler__name' }, tl.cameraRow), camTrack),
      dev);

    var beforeOut = h('span', { class: 'gv-num' });
    var loupe = h('figure', { class: 'gv-loupe', 'aria-hidden': 'true' },
      h('div', { class: 'gv-loupe__box' },
        h('span', { class: 'gv-loupe__f', style: { left: '0%' } }),
        h('span', { class: 'gv-loupe__f', style: { left: '33.333%' } }),
        h('span', { class: 'gv-loupe__f', style: { left: '66.667%' } }),
        h('span', { class: 'gv-loupe__f', style: { left: '100%' } }),
        h('span', { class: 'gv-loupe__hit' })),
      h('figcaption', { class: 'gv-label' }, tl.loupe));

    var readout = h('div', { class: 'gv-ruler__out' },
      h('p', { class: 'gv-ruler__res gv-ruler__res--hand' },
        h('span', { class: 'gv-label' }, tl.beforeLead), beforeOut),
      h('div', { class: 'gv-ruler__res gv-ruler__res--cam' },
        h('p', null, h('span', { class: 'gv-label' }, tl.afterLead), h('span', { class: 'gv-num' }, tl.afterValue)),
        loupe),
      h('p', { class: 'gv-ruler__ema gv-caption' }, tl.emaNote));

    var ruler = h('div', { class: 'gv-ruler', 'data-reveal': '' },
      h('p', { class: 'gv-ruler__head' }, h('span', { class: 'gv-label' }, tl.caption), h('span', { class: 'gv-ruler__drag' }, tl.drag)),
      field, readout);
    body.appendChild(ruler);

    function hm(x) {
      var hh = Math.floor(x + 1e-9);
      var mm = Math.round((x - hh) * 60);
      if (mm === 60) { hh += 1; mm = 0; }
      return hh + NBSP + 'ч ' + (mm < 10 ? '0' : '') + mm + NBSP + 'мин';
    }
    /* «Отклонение примерно в 5 часов»: подпись округляет до часа, точное время — в aria-valuetext */
    function aboutHour(x) {
      var n = Math.round(x);
      if (n === 0) return tl.deviationStart;
      var f = tl.hourForms;
      var form = n % 10 === 1 && n % 100 !== 11 ? f[0] : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? f[1] : f[2]);
      return tl.deviationAt + ' ' + n + NBSP + form;
    }
    function setHour(x) {
      hour = Math.max(0, Math.min(H, Math.round(x * 4) / 4));
      var d = delayHours(hour, tl.rounds, H);
      var next = hour + d;
      dev.style.setProperty('--x', String(hour / H));
      blind.style.left = pct(hour) + '%';
      blind.style.width = Math.max(0, pct(Math.min(next, H)) - pct(hour)) + '%';
      camTick.style.left = pct(hour) + '%';
      devLabel.textContent = aboutHour(hour);
      beforeOut.textContent = hm(d);
      dev.setAttribute('aria-valuenow', String(hour));
      dev.setAttribute('aria-valuetext', hm(hour) + ' от начала смены; ' + tl.beforeLead.toLowerCase() + ' ' + hm(d));
    }
    setHour(hour);

    function hourFromEvent(e) {
      var trackBox = handTrack.getBoundingClientRect();
      return ((e.clientX - trackBox.left) / trackBox.width) * H;
    }
    var dragging = false;
    sc.on(field, 'pointerdown', function (e) {
      dragging = true;
      field.setPointerCapture(e.pointerId);
      setHour(hourFromEvent(e));
      dev.focus({ preventScroll: true });
    });
    sc.on(field, 'pointermove', function (e) { if (dragging) setHour(hourFromEvent(e)); });
    sc.on(field, 'pointerup', function () { dragging = false; });
    sc.on(field, 'pointercancel', function () { dragging = false; });
    sc.on(dev, 'keydown', function (e) {
      var step = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowUp') step = 0.25;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') step = -0.25;
      else if (e.key === 'PageUp') step = 1;
      else if (e.key === 'PageDown') step = -1;
      else if (e.key === 'Home') { e.preventDefault(); setHour(0); return; }
      else if (e.key === 'End') { e.preventDefault(); setHour(H); return; }
      if (step === null) return;
      e.preventDefault();
      setHour(hour + step);
    });

    /* ---------- 3. затраты ---------- */

    function num(str) { return Number(String(str).replace(/[^\d]/g, '')); }
    var vb = num(t.before.cost.value);
    var va = num(t.after.cost.value);
    var giant = h('span', { class: 'gv-cost__giant gv-num' }, t.saving.value);
    var cost = h('div', { class: 'gv-cost', 'data-reveal': '' },
      h('div', { class: 'gv-cost__total' },
        h('p', { class: 'gv-cost__head' }, giant, h('span', { class: 'gv-cost__label' }, t.saving.label)),
        h('p', { class: 'gv-cost__qual' }, t.savingNote)),
      h('div', { class: 'gv-cost__rows' },
        [[t.before, vb, 'before'], [t.after, va, 'after']].map(function (row) {
          return h('div', { class: 'gv-cost__row gv-cost__row--' + row[2] },
            h('p', { class: 'gv-cost__name' }, row[0].title, h('span', { class: 'gv-caption' }, row[0].cost.note)),
            h('span', { class: 'gv-cost__bar' }, h('span', { class: 'gv-cost__fill', style: { '--w': (row[1] / vb).toFixed(4) } })),
            h('p', { class: 'gv-cost__value gv-num' }, row[0].cost.value, h('span', { class: 'gv-cost__unit' }, ' ' + row[0].cost.unit)));
        })));
    body.appendChild(cost);
    sc.observe(u.onVisible(cost, function () { cost.classList.add('is-drawn'); }, { once: true, threshold: 0.35 }));
    var pctNum = Number(String(t.saving.value).replace(/[^\d]/g, ''));
    sc.add(motion.counter(giant, { to: pctNum, digits: 0, display: t.saving.value, duration: 1400, format: function (v) { return '−' + fmt(v, 0) + NBSP + '%'; } }));

    /* ---------- 4. было и стало ---------- */

    function list(side, cls) {
      return h('div', { class: 'gv-points gv-points--' + cls, 'data-reveal': '' },
        h('h3', { class: 'gv-points__title' }, side.title),
        h('ul', { class: 'gv-points__list', role: 'list' }, side.points.map(function (p) { return h('li', null, p); })));
    }
    body.appendChild(list(t.before, 'before'));
    body.appendChild(list(t.after, 'after'));

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.shift = { mount: mount, timeFor: timeFor, delayHours: delayHours };
})();
