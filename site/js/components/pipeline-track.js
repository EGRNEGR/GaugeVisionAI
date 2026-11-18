/*
 * GV.components.pipelineTrack — #pipeline: четыре карточки математики конвейера на закреплённом
 * горизонтальном треке. mount(el, { head }) → { destroy() }
 *
 * Сцена .gv-track высотой (N + 0,5) × 75vh, внутри sticky-сцена: сверху заголовок секции (head от GV.page)
 * и шаги 01–04 с именами, по центру трек, снизу итог конвейера. Прогресс GV.motion.pinProgress
 * переводится в «шаг» s непрерывно: на краях каждого отрезка карточка держится по центру (HOLD), между
 * ними трек переезжает по smoothstep; пружина сглаживает рывки колёсика. По s:
 *   · трек едет translateX так, что точка s трека стоит в центре кадра: на целом s активная карточка
 *     ровно по центру;
 *   · карточка i входит (opacity + translateX) на отрезке s ∈ [i − 1, i], первая видна сразу;
 *   · «фокус» карточки f = 1 − |s − i|: яркий ободок (opacity), полная яркость и схема шага;
 *   · схема шага (SVG) показывает, что делает шаг с кадром, и доигрывает к f = 1:
 *       01 — рамка детектора сжимается на корпусе прибора, циферблат проявляется (CLAHE);
 *       02 — эллипс циферблата аффинно выпрямляется в круг;
 *       03 — стрелка доходит до θ, линия HoughLinesP сходится с ней из 12°;
 *       04 — шумные отсчёты Vₜ и кривая EMA V̄ₜ, рассчитанная kit.emaStep с α из карточки;
 *   · связь между карточками i и i + 1 растёт scaleX вместе со входом карточки i + 1;
 *   · оранжевая черта под шагами перетекает от шага к шагу (translateX + scaleX по s), номер активного
 *     шага — акцентом.
 * Кнопки шагов — нативные <button>: клик прокручивает страницу к шагу.
 * Подписи и формулы — GV.content.pipelineCards, итог — pipelineTotal. Ничего не выдумано:
 * задержка только замеренная; у карточек 02 и 03 своего замера нет — они входят в итог внизу сцены.
 * Двигаются только transform и opacity; геометрия кэшируется на resize (ResizeObserver).
 * reduced motion: вертикальный список без закрепления и шагов, схемы в конечном состоянии.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var ENTER_REM = 3;      // с какого смещения карточка выезжает
  var DIM = 0.85;         // яркость карточки вне фокуса: текст в ней держит контраст ≥ 4,5 : 1
  var HOUGH_SPREAD = 12;  // из скольких градусов линия Hough сходится со стрелкой (согласование ≤ 12°)
  var HOLD = 0.2;         // доля отрезка прокрутки у каждого шага, где карточка стоит по центру
  var T = {
    steps: 'Шаги конвейера',
    step: 'Шаг',
    tag: 'gauge'
  };

  function clamp01(v) {
    return v < 0 ? 0 : (v > 1 ? 1 : v);
  }

  function ease(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  /* ---------- схемы шагов: SVG 200 × 200, центр 100, обновление update(f), f ∈ [0, 1] ---------- */

  function figures() {
    var u = GV.util;
    var s = u.svg;
    var kit = GV.kit;
    var c = GV.content;
    var calib = c.calibration;
    var C = 100;

    function r2(v) { return Math.round(v * 100) / 100; }
    function pt(r, deg) { var p = kit.polar(C, C, r, deg); return r2(p[0]) + ' ' + r2(p[1]); }

    /* Циферблат: дуга шкалы и риски по калибровке, без цифр */
    function face(r, extra) {
      var span = calib.span || 270;
      var ticks = [];
      for (var i = 0; i <= 10; i++) {
        var a = calib.thetaMin + (span * i) / 10;
        ticks.push('M' + pt(r - 2, a) + ' L' + pt(r - (i % 5 === 0 ? 11 : 6), a));
      }
      return s('g', { class: 'gv-fig__face' },
        s('circle', { class: 'gv-fig__rim', cx: C, cy: C, r: r }),
        s('path', { class: 'gv-fig__tick', d: ticks.join(' ') }),
        extra || null);
    }

    function spin(el, deg) {
      el.style.transform = 'rotate(' + deg.toFixed(2) + 'deg)';
    }

    function svgRoot(kind, children) {
      return s('svg', { class: 'gv-fig gv-fig--' + kind, viewBox: '0 0 200 200', 'aria-hidden': 'true', focusable: 'false' }, children);
    }

    var theta = Number(c.reading.theta);

    var build = {
      /* 01: кадр камеры, корпус прибора, рамка YOLOv8n с меткой класса */
      locate: function () {
        var gauge = s('g', { class: 'gv-fig__pivot gv-fig__gauge' },
          face(40, s('path', { class: 'gv-fig__needle-muted', d: 'M' + pt(0, theta) + ' L' + pt(30, theta) })));
        var box = s('g', { class: 'gv-fig__box' },
          s('rect', { class: 'gv-fig__bbox', x: 50, y: 50, width: 100, height: 100 }),
          s('path', { class: 'gv-fig__corners', d: 'M50 64 V50 H64 M136 50 H150 V64 M150 136 V150 H136 M64 150 H50 V136' }),
          s('rect', { class: 'gv-fig__tag', x: 50, y: 38, width: 40, height: 12 }),
          s('text', { class: 'gv-fig__tag-text', x: 54, y: 47, 'font-size': 8 }, T.tag));
        var el = svgRoot('locate', [
          s('rect', { class: 'gv-fig__frame', x: 8, y: 22, width: 184, height: 156, rx: 2 }),
          s('path', { class: 'gv-fig__pipe', d: 'M8 158 H58 M142 158 H192 M100 140 V178 M8 46 H40' }),
          gauge, box]);
        return {
          el: el,
          update: function (f) {
            var e = ease(f);
            gauge.style.opacity = (0.35 + 0.65 * e).toFixed(3);
            box.style.opacity = e.toFixed(3);
            box.style.transform = 'scale(' + (1.35 - 0.35 * e).toFixed(4) + ')';
          }
        };
      },

      /* 02: эллипс циферблата (наклон камеры) выпрямляется в круг; пунктир — целевой круг */
      normalize: function () {
        var PHI = -28;
        var ellipse = s('g', { class: 'gv-fig__pivot' },
          face(64, [
            s('path', { class: 'gv-fig__axis', d: 'M36 100 H164 M100 36 V164' }),
            s('path', { class: 'gv-fig__needle-muted', d: 'M' + pt(0, theta) + ' L' + pt(50, theta) })
          ]));
        var el = svgRoot('normalize', [
          s('circle', { class: 'gv-fig__target', cx: C, cy: C, r: 64 }),
          ellipse]);
        return {
          el: el,
          update: function (f) {
            var sx = 0.56 + 0.44 * ease(f);
            ellipse.style.transform = 'rotate(' + PHI + 'deg) scale(' + sx.toFixed(4) + ',1) rotate(' + (-PHI) + 'deg)';
          }
        };
      },

      /* 03: стрелка доходит от θmin до θ, линия HoughLinesP сходится с ней из HOUGH_SPREAD° */
      needle: function () {
        var needle = s('g', { class: 'gv-fig__pivot' },
          s('path', { class: 'gv-fig__needle', d: 'M' + pt(0, 0) + ' L' + pt(62, 0) }));
        var hough = s('g', { class: 'gv-fig__pivot' },
          s('path', { class: 'gv-fig__hough', d: 'M' + pt(8, 0) + ' L' + pt(70, 0) }));
        var el = svgRoot('needle', [
          face(76),
          s('text', { class: 'gv-fig__label', x: 112, y: 132, 'font-size': 13 }, 'θ'),
          hough, needle,
          s('circle', { class: 'gv-fig__hub', cx: C, cy: C, r: 4 })]);
        var from = Number(calib.thetaMin);
        var to = from + ((theta - from) % 360 + 360) % 360;
        return {
          el: el,
          update: function (f) {
            var e = ease(f);
            var a = from + (to - from) * e;
            spin(needle, a);
            spin(hough, a + HOUGH_SPREAD * (1 - e));
            hough.style.opacity = (0.3 + 0.7 * e).toFixed(3);
          }
        };
      },

      /* 04: скачок показания: шумные отсчёты Vₜ и сглаженная кривая V̄ₜ; кривая проявляется слева направо */
      stabilize: function () {
        var card = c.pipelineCards.filter(function (k) { return k.id === 'stabilize'; })[0];
        var alphaParam = card && card.params.filter(function (p) { return p.name === 'EMA_ALPHA'; })[0];
        var alpha = alphaParam ? parseFloat(String(alphaParam.value).replace(',', '.')) : 0.25;
        var N = 24;
        var X0 = 26;
        var DX = 7;
        function y(v) { return r2(166 - v * 16); }
        var dots = [];
        var line = [];
        var ema = null;
        for (var i = 0; i < N; i++) {
          var level = i < 8 ? 2.5 : 6.5;
          var noise = ((((i * 37) % 11) - 5) / 5) * 0.9;
          var v = level + noise;
          ema = kit.emaStep(ema, v, alpha);
          dots.push(s('circle', { class: 'gv-fig__dot', cx: X0 + i * DX, cy: y(v), r: 2 }));
          line.push((X0 + i * DX) + ',' + y(ema));
        }
        var clipId = u.uid('gv-fig-clip');
        var wipe = s('rect', { class: 'gv-fig__wipe', x: 18, y: 10, width: 176, height: 170 });
        var el = svgRoot('stabilize', [
          s('defs', null, s('clipPath', { id: clipId }, wipe)),
          s('path', { class: 'gv-fig__axis', d: 'M18 22 V176 H192' }),
          s('path', { class: 'gv-fig__level', d: 'M18 ' + y(6.5) + ' H192' }),
          dots,
          s('polyline', { class: 'gv-fig__ema', points: line.join(' '), 'clip-path': 'url(#' + clipId + ')' }),
          s('text', { class: 'gv-fig__label gv-fig__label--muted', x: 170, y: 34, 'font-size': 11 }, 'Vₜ'),
          s('text', { class: 'gv-fig__label gv-fig__label--accent', x: 170, y: 100, 'font-size': 11 }, 'V̄ₜ')]);
        return {
          el: el,
          update: function (f) {
            wipe.style.transform = 'scaleX(' + (0.08 + 0.92 * ease(f)).toFixed(4) + ')';
          }
        };
      }
    };

    return function (id) {
      return build[id] ? build[id]() : null;
    };
  }

  function mount(el, options) {
    options = options || {};
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
    var figureOf = figures();

    /* ---------- разметка ---------- */

    function latency(card) {
      if (!card.latency) return null;
      return h('p', { class: 'gv-track__latency' },
        h('span', { class: 'gv-track__lat-value' }, card.latency.value),
        h('span', { class: 'gv-track__lat-unit' }, card.latency.unit),
        h('span', { class: 'gv-track__lat-note' }, card.latency.note));
    }

    var rims = [];
    var cardEls = [];
    var linkEls = [];
    var figs = [];
    var items = cards.map(function (card, i) {
      var rim = h('span', { class: 'gv-track__rim', 'aria-hidden': 'true' });
      var fig = figureOf(card.id);
      var article = h('article', { class: ['gv-track__card', fig ? 'gv-track__card--fig' : null], 'data-id': card.id },
        rim,
        fig ? h('div', { class: 'gv-track__fig' }, fig.el) : null,
        h('div', { class: 'gv-track__body' },
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
          latency(card)));
      var link = i < N - 1 ? h('span', { class: 'gv-track__link', 'aria-hidden': 'true' }) : null;
      rims.push(rim);
      cardEls.push(article);
      linkEls.push(link);
      figs.push(fig);
      return h('li', { class: 'gv-track__item' }, article, link);
    });

    var rail = h('ol', { class: 'gv-track__rail', role: 'list' }, items);
    var viewport = h('div', { class: 'gv-track__viewport' }, rail);

    var marker = h('span', { class: 'gv-track__marker', 'aria-hidden': 'true' });
    var stepButtons = [];
    var steps = flat ? null : h('nav', { class: 'gv-track__steps', 'aria-label': T.steps },
      marker,
      cards.map(function (card, i) {
        var b = h('button', {
          type: 'button', class: 'gv-track__step',
          'aria-label': T.step + NBSP + (i + 1) + ': ' + card.title
        },
        h('span', { class: 'gv-track__step-index' }, card.index),
        card.step ? h('span', { class: 'gv-track__step-name' }, card.step) : null);
        stepButtons.push(b);
        return b;
      }));

    var totalEl = h('p', { class: 'gv-track__total' },
      h('span', { class: 'gv-track__total-label' }, total.label),
      h('span', { class: 'gv-track__total-value' }, total.value),
      h('span', { class: 'gv-track__total-unit' }, total.unit));

    var top = options.head || steps
      ? h('div', { class: 'gv-container gv-track__top' }, options.head || null, steps)
      : null;

    var rootEl = h('div', { class: ['gv-track', flat ? 'is-flat' : null], style: { '--steps': String(N) } },
      h('div', { class: 'gv-track__stage' },
        top,
        viewport,
        h('div', { class: 'gv-container gv-track__foot' }, totalEl)));
    el.appendChild(rootEl);

    offs.push(motion.spotlight(rail, '.gv-track__card'));

    if (flat) {
      figs.forEach(function (f) { if (f) f.update(1); });
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
    var frameW = 0;     // ширина кадра (окна трека)
    var cardW = 0;      // ширина карточки
    var firstLeft = 0;  // левый край первой карточки на треке без сдвига
    var pitch = 0;      // шаг карточек: ширина + промежуток
    var remPx = 16;
    var stepBoxes = []; // черта под каждым шагом: { x, w } от левого края полосы шагов

    /* Положения шагов читаются в measure и при смене активного (на телефоне у него появляется имя) */
    function measureSteps() {
      stepBoxes = stepButtons.map(function (b) {
        var pad = parseFloat(window.getComputedStyle(b).paddingLeft) || 0;
        return { x: b.offsetLeft + pad, w: Math.max(0, b.offsetWidth - 2 * pad) };
      });
    }

    function measure() {
      remPx = parseFloat(window.getComputedStyle(document.documentElement).fontSize) || 16;
      enterPx = ENTER_REM * remPx;
      measureSteps();
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
    var lastFocus = [];

    function activeOf(s) {
      return Math.round(clamp01(s / last) * last);
    }

    function enterOf(i, s) {
      return i === 0 ? 1 : clamp01(s - (i - 1));
    }

    /* Точка s трека — в центре кадра: на целом шаге активная карточка ровно по центру. */
    function shiftFor(s) {
      return firstLeft + s * pitch + cardW / 2 - frameW / 2;
    }

    function render(s) {
      paint(s);
      rail.style.transform = 'translate3d(' + (-shiftFor(s)).toFixed(2) + 'px,0,0)';
    }

    /* Черта под шагами: между шагами i и i + 1 — смесь их положений и ширин */
    function paintMarker(s) {
      if (!stepBoxes.length) return;
      var i = Math.min(Math.max(0, Math.floor(s)), stepBoxes.length - 1);
      var a = stepBoxes[i];
      var b = stepBoxes[Math.min(i + 1, stepBoxes.length - 1)];
      var t = clamp01(s - i);
      var x = a.x + (b.x - a.x) * t;
      var w = a.w + (b.w - a.w) * t;
      marker.style.transform = 'translate3d(' + x.toFixed(2) + 'px,0,0) scaleX(' + (w / remPx).toFixed(4) + ')';
    }

    function paint(s) {
      for (var i = 0; i < N; i++) {
        var enter = enterOf(i, s);
        var focus = clamp01(1 - Math.abs(s - i));
        cardEls[i].style.opacity = (enter * (DIM + (1 - DIM) * focus)).toFixed(3);
        cardEls[i].style.transform = 'translate3d(' + ((1 - ease(enter)) * enterPx).toFixed(2) + 'px,0,0)';
        rims[i].style.opacity = focus.toFixed(3);
        if (linkEls[i]) linkEls[i].style.transform = 'scaleX(' + clamp01(s - i).toFixed(4) + ')';
        if (figs[i] && Math.abs(focus - (lastFocus[i] === undefined ? -1 : lastFocus[i])) > 1e-4) {
          figs[i].update(focus);
          lastFocus[i] = focus;
        }
      }
      var active = activeOf(s);
      if (active !== lastActive) {
        lastActive = active;
        rootEl.setAttribute('data-step', String(active + 1));
        stepButtons.forEach(function (b, j) {
          if (j === active) b.setAttribute('aria-current', 'step');
          else b.removeAttribute('aria-current');
        });
        measureSteps();
      }
      paintMarker(s);
    }

    /* Прокрутка → шаг: у краёв отрезка карточка стоит, посередине трек переезжает плавно */
    function stepFor(p) {
      var x = p * last;
      var i = Math.min(last - 1, Math.floor(x));
      if (i < 0) return 0;
      var g = clamp01((x - i - HOLD) / (1 - 2 * HOLD));
      return i + g * g * (3 - 2 * g);
    }

    /* ---------- пружина за прокруткой: цель — непрерывный шаг stepFor ---------- */

    var spring = motion.spring({ stiffness: 120, damping: 22, precision: 0.0008, value: 0 });
    var offFrame = null;
    var first = true;

    function tick(dt) {
      render(spring.step(dt));
      if (spring.settled() && offFrame) {
        offFrame();
        offFrame = null;
      }
    }

    offs.push(motion.onScroll(function () {
      var target = stepFor(motion.pinProgress(rootEl));
      if (first) {
        first = false;
        spring.set(target);
        render(target);
        return;
      }
      spring.target(target);
      if (!offFrame && !spring.settled()) offFrame = motion.onFrame(tick);
    }));
    offs.push(function () { if (offFrame) { offFrame(); offFrame = null; } });

    /* ---------- клик по шагу ---------- */

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
