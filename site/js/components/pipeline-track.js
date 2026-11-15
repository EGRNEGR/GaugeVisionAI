/*
 * GV.components.pipelineTrack — #pipeline: четыре карточки математики конвейера на закреплённом
 * горизонтальном треке. mount(el) → { destroy() }
 *
 * Сцена .gv-track высотой (N + 1) × 100vh, внутри sticky-сцена. Прогресс GV.motion.pinProgress
 * превращается в «шаг» s = p × (N − 1), который идёт за прокруткой на пружине. По s:
 *   · трек едет translateX так, что точка s трека стоит в центре кадра (на шаге i — карточка i по центру),
 *     но не дальше, чем позволяет активная карточка: она всегда целиком в кадре. Где две карточки
 *     в кадр не помещаются (телефон, 85vw), трек перескакивает к новой активной — сдвиг идёт на своей
 *     пружине, поэтому перескок плавный;
 *   · карточка i входит (opacity + translateX) на отрезке s ∈ [i − 1, i], первая видна сразу;
 *   · «фокус» карточки f = 1 − |s − i|: яркий ободок (opacity) и полная яркость у активной;
 *   · связь между карточками i и i + 1 растёт scaleX вместе со входом карточки i + 1;
 *   · линия под индикатором 01–04 растёт scaleX, кнопка активного шага подсвечена.
 * Кнопки 01–04 — нативные <button>: клик прокручивает страницу к шагу.
 * Подписи и формулы — GV.content.pipelineCards, итог — pipelineTotal. Ничего не выдумано:
 * задержка только замеренная, у карточек 02 и 03 — «в составе» общего итога.
 * Двигаются только transform и opacity; геометрия кэшируется на resize (ResizeObserver).
 * reduced motion: вертикальный список без закрепления и индикатора, всё видно сразу.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var ENTER_REM = 3;      // с какого смещения карточка выезжает
  var EDGE_REM = 0.5;     // наименьший зазор активной карточки до края кадра
  var DIM = 0.42;         // яркость карточки вне фокуса
  var T = {
    steps: 'Шаги конвейера',
    step: 'Шаг',
    within: 'в составе'
  };

  function clamp01(v) {
    return v < 0 ? 0 : (v > 1 ? 1 : v);
  }

  function ease(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function mount(el) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var cards = c.pipelineCards;
    var total = c.pipelineTotal;
    var N = cards.length;
    var flat = motion.reduced();
    var NBSP = kit.NBSP;
    var sc = kit.scope();
    var offs = [];

    /* ---------- разметка ---------- */

    function latency(card) {
      if (card.latency) {
        return h('p', { class: 'gv-track__latency' },
          h('span', { class: 'gv-track__lat-value' }, card.latency.value),
          h('span', { class: 'gv-track__lat-unit' }, card.latency.unit),
          h('span', { class: 'gv-track__lat-note' }, card.latency.note));
      }
      return h('p', { class: 'gv-track__latency gv-track__latency--shared' },
        h('span', { class: 'gv-track__lat-unit' }, T.within),
        h('span', { class: 'gv-track__lat-value gv-track__lat-value--small' }, total.value),
        h('span', { class: 'gv-track__lat-unit' }, total.unit));
    }

    var rims = [];
    var cardEls = [];
    var linkEls = [];
    var items = cards.map(function (card, i) {
      var rim = h('span', { class: 'gv-track__rim', 'aria-hidden': 'true' });
      var article = h('article', { class: 'gv-track__card', 'data-id': card.id },
        rim,
        h('header', { class: 'gv-track__head' },
          h('span', { class: 'gv-track__index' }, card.index),
          h('h3', { class: 'gv-track__title' }, card.title)),
        h('div', { class: 'gv-track__formula' }, card.formula.map(function (line) {
          return h('code', { class: 'gv-track__code' }, line);
        })),
        h('dl', { class: 'gv-track__params' }, card.params.map(function (p) {
          return h('div', { class: 'gv-track__param' },
            h('dt', null, p.name),
            h('dd', null, p.value));
        })),
        latency(card));
      var link = i < N - 1 ? h('span', { class: 'gv-track__link', 'aria-hidden': 'true' }) : null;
      rims.push(rim);
      cardEls.push(article);
      linkEls.push(link);
      return h('li', { class: 'gv-track__item' }, article, link);
    });

    var rail = h('ol', { class: 'gv-track__rail', role: 'list' }, items);
    var viewport = h('div', { class: 'gv-track__viewport' }, rail);

    var meter = h('span', { class: 'gv-track__meter', 'aria-hidden': 'true' });
    var stepButtons = [];
    var steps = flat ? null : h('nav', { class: 'gv-track__steps', 'aria-label': T.steps },
      h('span', { class: 'gv-track__meter-track', 'aria-hidden': 'true' }, meter),
      cards.map(function (card, i) {
        var b = h('button', {
          type: 'button', class: 'gv-track__step',
          'aria-label': T.step + NBSP + (i + 1) + ': ' + card.title
        }, card.index);
        stepButtons.push(b);
        return b;
      }));

    var totalEl = h('p', { class: 'gv-track__total' },
      h('span', { class: 'gv-track__total-label' }, total.label),
      h('span', { class: 'gv-track__total-value' }, total.value),
      h('span', { class: 'gv-track__total-unit' }, total.unit));

    var rootEl = h('div', { class: ['gv-track', flat ? 'is-flat' : null], style: { '--steps': String(N) } },
      h('div', { class: 'gv-track__stage' },
        steps ? h('div', { class: 'gv-container gv-track__top' }, steps) : null,
        viewport,
        h('div', { class: 'gv-container gv-track__foot' }, totalEl)));
    el.appendChild(rootEl);

    offs.push(motion.spotlight(rail, '.gv-track__card'));

    if (flat) {
      return {
        destroy: function () {
          sc.destroy();
          offs.forEach(function (off) { off(); });
          if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
        }
      };
    }

    /* ---------- геометрия: считается на resize, не в кадре ---------- */

    var enterPx = 0;
    var edgePx = 0;
    var frameW = 0;     // ширина кадра (окна трека)
    var cardW = 0;      // ширина карточки
    var firstLeft = 0;  // левый край первой карточки на треке без сдвига
    var pitch = 0;      // шаг карточек: ширина + промежуток

    function measure() {
      var rem = parseFloat(window.getComputedStyle(document.documentElement).fontSize) || 16;
      enterPx = ENTER_REM * rem;
      edgePx = EDGE_REM * rem;
      frameW = viewport.clientWidth;
      // Разность прямоугольников не зависит от текущего сдвига трека: он у обоих одинаковый.
      var railBox = rail.getBoundingClientRect();
      var a = items[0].getBoundingClientRect();
      firstLeft = a.left - railBox.left;
      cardW = a.width;
      pitch = N > 1 ? items[1].getBoundingClientRect().left - a.left : 0;
      render(spring.value());
    }

    /* ---------- отрисовка шага s ∈ [0, N − 1] ---------- */

    var lastActive = -1;
    var last = N - 1;

    function activeOf(s) {
      return Math.round(clamp01(s / last) * last);
    }

    function enterOf(i, s) {
      return i === 0 ? 1 : clamp01(s - (i - 1));
    }

    /* Сдвиг трека для шага s: точка s — в центре кадра, но активная карточка a целиком в кадре. */
    function shiftFor(s) {
      var a = activeOf(s);
      var centered = firstLeft + s * pitch + cardW / 2 - frameW / 2;
      var left = firstLeft + a * pitch;
      var entering = (1 - ease(enterOf(a, s))) * enterPx;
      var edge = Math.min(edgePx, Math.max(0, (frameW - cardW - entering) / 2));
      var lo = left + cardW + entering - (frameW - edge);   // правый край не дальше края кадра
      var hi = left - edge;                                  // левый край не левее края кадра
      if (lo > hi) return (lo + hi) / 2;
      return Math.min(Math.max(centered, lo), hi);
    }

    /* dt не задан — сдвиг ставится сразу (первый кадр, resize), иначе догоняет цель на пружине. */
    function render(s, dt) {
      paint(s);
      var goal = shiftFor(s);
      var x;
      if (dt === undefined) { shift.set(goal); x = goal; }
      else { shift.target(goal); x = shift.step(dt); }
      rail.style.transform = 'translate3d(' + (-x).toFixed(2) + 'px,0,0)';
    }

    function paint(s) {
      var k = clamp01(s / last);
      meter.style.transform = 'scaleX(' + k.toFixed(4) + ')';
      for (var i = 0; i < N; i++) {
        var enter = enterOf(i, s);
        var focus = clamp01(1 - Math.abs(s - i));
        cardEls[i].style.opacity = (enter * (DIM + (1 - DIM) * focus)).toFixed(3);
        cardEls[i].style.transform = 'translate3d(' + ((1 - ease(enter)) * enterPx).toFixed(2) + 'px,0,0)';
        rims[i].style.opacity = focus.toFixed(3);
        if (linkEls[i]) linkEls[i].style.transform = 'scaleX(' + clamp01(s - i).toFixed(4) + ')';
      }
      var active = activeOf(s);
      if (active !== lastActive) {
        lastActive = active;
        rootEl.setAttribute('data-step', String(active + 1));
        stepButtons.forEach(function (b, j) {
          if (j === active) b.setAttribute('aria-current', 'step');
          else b.removeAttribute('aria-current');
        });
      }
    }

    /* ---------- пружина за прокруткой ---------- */

    var spring = motion.spring({ stiffness: 120, damping: 22, precision: 0.0008, value: 0 });
    // Сдвиг трека в px: критическое демпфирование, без перелёта; плавно проводит перескок к новой карточке.
    var shift = motion.spring({ stiffness: 260, damping: 32, precision: 0.3, value: 0 });
    var offFrame = null;
    var first = true;

    function tick(dt) {
      render(spring.step(dt), dt);
      if (spring.settled() && shift.settled() && offFrame) {
        offFrame();
        offFrame = null;
      }
    }

    offs.push(motion.onScroll(function () {
      var target = motion.pinProgress(rootEl) * last;
      if (first) {
        first = false;
        spring.set(target);
        render(target);
        return;
      }
      spring.target(target);
      if (!offFrame && (!spring.settled() || !shift.settled())) offFrame = motion.onFrame(tick);
    }));
    offs.push(function () { if (offFrame) { offFrame(); offFrame = null; } });

    /* ---------- клик по индикатору ---------- */

    stepButtons.forEach(function (b, i) {
      sc.on(b, 'click', function () {
        var m = motion.measure(rootEl);
        var range = Math.max(0, m.height - motion.viewport().height);
        window.scrollTo({ top: m.top + (i / last) * range, behavior: 'smooth' });
      });
    });

    if ('ResizeObserver' in window) {
      var ro = new window.ResizeObserver(measure);
      ro.observe(viewport);
      ro.observe(rail);
      offs.push(function () { ro.disconnect(); });
    } else {
      sc.on(window, 'resize', measure);
    }
    kit.onTweaks(sc, measure);
    measure();

    return {
      destroy: function () {
        sc.destroy();
        offs.forEach(function (off) { off(); });
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      }
    };
  }

  GV.components.pipelineTrack = { mount: mount };
})();
