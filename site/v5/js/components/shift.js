/*
 * GV.components.shift — лист 02 «Двенадцать часов против трети секунды».
 *   1. Закреплённая сцена с роликом смены (shift.scrub.mp4 / shift.scrub-m.mp4) и штампом «Иллюстрация».
 *   2. Интерактивная шкала смены 12 ч + лупа 1 с (три кадра камеры).
 *   3. Графа бланка со стендовой оценкой замены точки 104 880 ₽ и две колонки «Сегодня / С GaugeVision 3.0».
 *   4. Калькулятор экономики сценария (строки бланка с изменяемыми допущениями).
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});

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

  function computeEconomics(v) {
    var N = Math.max(0, Math.round(v.points));
    var q = Math.max(0, Math.min(1, v.priority / 100));
    var k = Math.max(1, Math.round(v.perCamera));
    var nRep = Math.round(N * q);
    var cams = Math.ceil((N - nRep) / k);
    var capexA = N * v.sensorCost;
    var opexA = N * v.opexSensor;
    var capexB = nRep * v.sensorCost + cams * v.cameraCost + v.serverCost;
    var opexB = nRep * v.opexSensor + cams * v.opexCamera;
    var T = Math.max(1, Math.round(v.years));
    var totalA = capexA + T * opexA;
    var totalB = capexB + T * opexB;
    return {
      N: N, nRep: nRep, cams: cams,
      capexA: capexA, opexA: opexA, capexB: capexB, opexB: opexB,
      totalA: totalA, totalB: totalB, T: T,
      perPointA: N ? capexA / N : 0, perPointB: N ? capexB / N : 0,
      saving: totalA - totalB
    };
  }

  function mount(body) {
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

    /* ---------- 1. сцена с роликом ---------- */

    var reduced = motion.reduced();
    var small = window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
    var stage = h('div', { class: 'gv-shift__stage' + (reduced ? ' is-still' : '') });
    var capBefore = h('p', { class: 'gv-shift__cap gv-shift__cap--before' }, t.captions.before);
    var capAfter = h('p', { class: 'gv-shift__cap gv-shift__cap--after' }, t.captions.after);
    var marker = h('span', { class: 'gv-shift__marker' });
    var clockRuler = h('div', { class: 'gv-shift__clock', 'aria-hidden': 'true' },
      h('span', { class: 'gv-shift__clock-line' }), marker);
    var illusStamp = h('p', { class: 'gv-shift__illus' },
      h('span', { class: 'gv-mark', 'data-tone': 'planned' }, c.labels.illustration), ' ', t.video.note);

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
        var isAfter = progress > 0.55;
        capBefore.classList.toggle('is-on', !isAfter);
        capAfter.classList.toggle('is-on', isAfter);
        stage.classList.toggle('is-after', isAfter);
        marker.style.transform = 'translate3d(' + (progress * 100).toFixed(2) + 'cqw, 0, 0)';
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
    body.appendChild(illusStamp);

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
      h('p', { class: 'gv-ruler__head' },
        h('span', null, h('span', { class: 'gv-mark', 'data-tone': 'warning' }, c.labels.sim), ' ', h('span', { class: 'gv-label' }, tl.caption)),
        h('span', { class: 'gv-ruler__drag' }, tl.drag)),
      field, readout);
    body.appendChild(ruler);

    function hm(x) {
      var hh = Math.floor(x + 1e-9);
      var mm = Math.round((x - hh) * 60);
      if (mm === 60) { hh += 1; mm = 0; }
      return hh + NBSP + 'ч ' + (mm < 10 ? '0' : '') + mm + NBSP + 'мин';
    }
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

    /* ---------- 3. было / стало и графа стендовой цены точки ---------- */

    function list(side, cls) {
      return h('div', { class: 'gv-points gv-points--' + cls, 'data-reveal': '' },
        h('h3', { class: 'gv-points__title' }, side.title),
        h('ul', { class: 'gv-points__list', role: 'list' }, side.points.map(function (p) { return h('li', null, p); })));
    }
    body.appendChild(list(t.before, 'before'));
    body.appendChild(list(t.after, 'after'));

    var srcCat = c.src[t.cost.source];
    var costBox = h('div', { class: 'gv-shift__cost gv-box', 'data-reveal': '' },
      h('span', { class: 'gv-box__legend' }, t.cost.legend),
      h('p', { class: 'gv-cost__head' },
        h('span', { class: 'gv-cost__giant gv-num' }, t.cost.value),
        h('span', { class: 'gv-cost__label' }, t.cost.unit)),
      h('p', { class: 'gv-cost__qual' }, t.cost.text, ' ',
        kit.extLink({ class: 'gv-src', href: srcCat.href }, srcCat.label)));
    body.appendChild(costBox);

    /* ---------- 4. экономика сценария (прозрачный расчёт на бланке) ---------- */

    var E = t.economics;
    var vals = {};
    var rub = function (n) { return (n < 0 ? '−' : '') + fmt(Math.round(Math.abs(n)), 0) + NBSP + '₽'; };
    var mln = function (n) { return (n < 0 ? '−' : '') + fmt(Math.abs(n) / 1e6, 2) + NBSP + 'млн' + NBSP + '₽'; };

    var inputs = E.fields.map(function (f) {
      vals[f.id] = f.value;
      var id = u.uid('gv-eco-' + f.id);
      var num = h('input', { class: 'gv-eco__num gv-num', type: 'number', id: id, min: f.min, max: f.max, step: f.step, value: f.value, inputmode: 'numeric' });
      var rng = h('input', { class: 'gv-eco__rng', type: 'range', min: f.min, max: f.max, step: f.step, value: f.value, 'aria-label': f.label, tabindex: '-1' });
      function set(v, from) {
        v = Number(v);
        if (!isFinite(v)) return;
        v = Math.max(f.min, Math.min(f.max, v));
        vals[f.id] = v;
        if (from !== num) num.value = v;
        if (from !== rng) rng.value = v;
        updateEco();
      }
      sc.on(num, 'change', function () { set(num.value, num); });
      sc.on(num, 'input', function () {
        if (num.value !== '' && isFinite(Number(num.value))) {
          vals[f.id] = Math.max(f.min, Math.min(f.max, Number(num.value)));
          rng.value = vals[f.id];
          updateEco();
        }
      });
      sc.on(rng, 'input', function () { set(rng.value, rng); });
      return h('div', { class: 'gv-eco__field' },
        h('label', { class: 'gv-eco__label', for: id }, f.label, f.note ? h('span', { class: 'gv-caption' }, f.note) : null),
        h('div', { class: 'gv-eco__ctl' }, num, h('span', { class: 'gv-eco__unit' }, f.unit)),
        rng);
    });

    var barAC = h('span', { class: 'gv-eco__capex' }), barAO = h('span', { class: 'gv-eco__opex' });
    var barBC = h('span', { class: 'gv-eco__capex' }), barBO = h('span', { class: 'gv-eco__opex' });
    var tA = h('span', { class: 'gv-eco__total gv-num' });
    var tB = h('span', { class: 'gv-eco__total gv-num' });
    var savingEl = h('p', { class: 'gv-eco__saving gv-num' });
    var savingL = h('p', { class: 'gv-eco__saving-l' });
    var ecoRows = h('tbody');
    var phaseEl = h('p', { class: 'gv-eco__phase' });

    var ecoWrap = h('div', { class: 'gv-eco', id: 'economics', 'data-reveal': '' },
      h('div', { class: 'gv-eco__head' },
        h('h3', { class: 'gv-h3' }, E.title),
        h('span', { class: 'gv-mark', 'data-tone': 'calculated' }, 'Расчёт сценария')),
      h('p', { class: 'gv-eco__sub' }, E.subtitle),
      h('div', { class: 'gv-eco__grid' },
        h('form', { class: 'gv-eco__form', 'aria-label': 'Допущения расчёта', on: { submit: function (e) { e.preventDefault(); } } }, inputs),
        h('div', { class: 'gv-eco__out', role: 'status', 'aria-live': 'polite' },
          h('div', { class: 'gv-eco__bars' },
            h('div', { class: 'gv-eco__brow' }, h('p', { class: 'gv-eco__bl' }, 'A. Заменить всё сразу'), h('div', { class: 'gv-eco__bar gv-eco__bar--a' }, barAC, barAO), tA),
            h('div', { class: 'gv-eco__brow' }, h('p', { class: 'gv-eco__bl' }, 'B. GaugeVision и замены по плану'), h('div', { class: 'gv-eco__bar gv-eco__bar--b' }, barBC, barBO), tB),
            h('p', { class: 'gv-eco__key' }, h('span', { class: 'gv-eco__k gv-eco__k--c' }, 'капитальные затраты'), h('span', { class: 'gv-eco__k gv-eco__k--o' }, 'эксплуатация за горизонт'))),
          savingEl, savingL,
          h('table', { class: 'gv-eco__table' },
            h('thead', null, h('tr', null, h('th', null, 'Показатель'), h('th', null, 'Сценарий A'), h('th', null, 'Сценарий B'))),
            ecoRows),
          phaseEl,
          h('p', { class: 'gv-caption' }, E.disclaimer))));
    body.appendChild(ecoWrap);

    function updateEco() {
      var r = computeEconomics(vals);
      var max = Math.max(r.totalA, r.totalB, 1);
      barAC.style.transform = 'scaleX(' + (r.capexA / max).toFixed(4) + ')';
      barAO.style.transform = 'translateX(' + (r.capexA / max * 100).toFixed(2) + '%) scaleX(' + (r.T * r.opexA / max).toFixed(4) + ')';
      barBC.style.transform = 'scaleX(' + (r.capexB / max).toFixed(4) + ')';
      barBO.style.transform = 'translateX(' + (r.capexB / max * 100).toFixed(2) + '%) scaleX(' + (r.T * r.opexB / max).toFixed(4) + ')';
      tA.textContent = mln(r.totalA);
      tB.textContent = mln(r.totalB);
      savingEl.textContent = mln(r.saving);
      savingEl.toggleAttribute('data-neg', r.saving < 0);
      savingL.textContent = r.saving >= 0
        ? 'разница сценариев за ' + r.T + ' ' + (r.T === 1 ? 'год' : (r.T < 5 ? 'года' : 'лет')) + ' при заданных допущениях'
        : 'при этих допущениях сценарий B дороже — проверьте долю замен и стоимость внедрения';
      ecoRows.textContent = '';
      [
        ['Капитальные затраты', rub(r.capexA), rub(r.capexB)],
        ['Цифровизация одной точки', rub(r.perPointA), rub(r.perPointB)],
        ['Эксплуатация в год', rub(r.opexA), rub(r.opexB)],
        ['Датчиков / камер', fmt(r.N, 0) + ' / 0', fmt(r.nRep, 0) + ' / ' + fmt(r.cams, 0)]
      ].forEach(function (row) {
        ecoRows.appendChild(h('tr', null, h('th', { scope: 'row' }, row[0]), h('td', { class: 'gv-num' }, row[1]), h('td', { class: 'gv-num' }, row[2])));
      });
      phaseEl.textContent = 'Поэтапно: сейчас — ' + fmt(r.cams, 0) + ' камер на ' + fmt(r.N - r.nRep, 0) + ' приборов и ' + fmt(r.nRep, 0) + ' приоритетных замен по плану оптимизатора.';
    }
    updateEco();

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.shift = { mount: mount, timeFor: timeFor, delayHours: delayHours, computeEconomics: computeEconomics };
})();
