/*
 * GV.components.operations — лист 04 «Четыре операции над одним кадром».
 * Один синтетический кадр (прибор снят под углом, на стекле блик) проходит четыре операции кода:
 *   01 бокс YOLOv8n и контур эллипса → 02 эллипс аффинно выпрямляется в круг 640 px →
 *   03 кольцо радиального момента, линия Hough через ось и угол θ, гистограмма → 04 сырые отсчёты
 *   с вибрацией и кривая EMA α = 0,25.
 * Десктоп: сцена закреплена, шаг задаёт прокрутка; список шагов — кнопки (переносят к своему шагу).
 * Окно уже 900 px и «уменьшить движение»: без закрепления, шаг выбирают кнопками.
 * Подписи и параметры — content.pipelineCards; задержка только замеренная.
 *
 *   mount(body) → { destroy }
 *   stepFor(progress, count) → индекс шага для прогресса прокрутки 0..1
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  function stepFor(progress, count) {
    var p = Math.max(0, Math.min(0.9999, progress));
    return Math.floor(p * count);
  }

  function mount(body) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var s = u.svg;
    var c = GV.content;
    var L = c.labels;
    var F = L.opsFrame;
    var cards = c.pipelineCards;
    var calib = c.calibration;
    var sc = kit.scope();
    var fmt = u.formatNumber;

    body.classList.add('gv-ops');

    /* ---------- кадр ---------- */

    var CX = 300;
    var CY = 196;
    var R = 112;
    var theta = c.reading.theta;

    function dialFace() {
      var g = s('g', { class: 'gv-ops__face' });
      g.appendChild(s('circle', { class: 'gv-ops__case', cx: CX, cy: CY, r: R + 12 }));
      g.appendChild(s('circle', { class: 'gv-ops__enamel', cx: CX, cy: CY, r: R }));
      for (var i = 0; i <= 50; i++) {
        var a = calib.thetaMin + (i / 50) * calib.span;
        var major = i % 5 === 0;
        var p0 = kit.polar(CX, CY, R - 6, a);
        var p1 = kit.polar(CX, CY, R - (major ? 20 : 12), a);
        g.appendChild(s('line', { class: major ? 'gv-ops__tick is-major' : 'gv-ops__tick', x1: p0[0].toFixed(1), y1: p0[1].toFixed(1), x2: p1[0].toFixed(1), y2: p1[1].toFixed(1) }));
        if (major) {
          var pt = kit.polar(CX, CY, R - 36, a);
          g.appendChild(s('text', { class: 'gv-ops__n', x: pt[0].toFixed(1), y: pt[1].toFixed(1), 'font-size': 17, 'text-anchor': 'middle', 'dominant-baseline': 'central' }, String(i / 5)));
        }
      }
      var tip = kit.polar(CX, CY, R - 14, theta);
      var tail = kit.polar(CX, CY, 22, theta + 180);
      g.appendChild(s('line', { class: 'gv-ops__needle', x1: tail[0].toFixed(1), y1: tail[1].toFixed(1), x2: tip[0].toFixed(1), y2: tip[1].toFixed(1) }));
      g.appendChild(s('circle', { class: 'gv-ops__hub', cx: CX, cy: CY, r: 8 }));
      g.appendChild(s('ellipse', { class: 'gv-ops__glare', cx: CX - 40, cy: CY - 54, rx: 48, ry: 20, transform: 'rotate(-30 ' + (CX - 40) + ' ' + (CY - 54) + ')' }));
      return g;
    }

    /* кольцо момента и линия Hough живут внутри циферблата: после шага 02 они на круге */
    var ring = s('path', {
      class: 'gv-ops__ring',
      'fill-rule': 'evenodd',
      d: 'M' + (CX + R * 0.72) + ' ' + CY + ' a' + (R * 0.72) + ' ' + (R * 0.72) + ' 0 1 0 ' + (-R * 1.44) + ' 0 a' + (R * 0.72) + ' ' + (R * 0.72) + ' 0 1 0 ' + (R * 1.44) + ' 0 Z ' +
        'M' + (CX + R * 0.12) + ' ' + CY + ' a' + (R * 0.12) + ' ' + (R * 0.12) + ' 0 1 0 ' + (-R * 0.24) + ' 0 a' + (R * 0.12) + ' ' + (R * 0.12) + ' 0 1 0 ' + (R * 0.24) + ' 0 Z'
    });
    var h0 = kit.polar(CX, CY, R + 34, theta + 180);
    var h1 = kit.polar(CX, CY, R + 34, theta);
    var hough = s('line', { class: 'gv-ops__hough', x1: h0[0].toFixed(1), y1: h0[1].toFixed(1), x2: h1[0].toFixed(1), y2: h1[1].toFixed(1) });
    var zeroRay = kit.polar(CX, CY, R + 26, 0);
    var thetaArc = s('path', { class: 'gv-ops__theta', d: kit.arcPath(CX, CY, 46, 0, theta) });
    var thetaLbl = kit.polar(CX, CY, 62, theta / 2);
    var stage3 = s('g', { class: 'gv-ops__o gv-ops__o--3' },
      ring,
      s('line', { class: 'gv-ops__zero', x1: CX, y1: CY, x2: zeroRay[0].toFixed(1), y2: zeroRay[1].toFixed(1) }),
      thetaArc,
      hough,
      s('text', { class: 'gv-ops__t gv-ops__t--accent', x: (thetaLbl[0] + 8).toFixed(1), y: (thetaLbl[1] + 20).toFixed(1), 'font-size': 13 }, 'θ = ' + fmt(theta, 1) + '°'),
      s('text', { class: 'gv-ops__t', x: (h1[0] + 6).toFixed(1), y: (h1[1] - 6).toFixed(1), 'font-size': 12 }, F.hough));

    var contour = s('circle', { class: 'gv-ops__contour gv-ops__o gv-ops__o--1', cx: CX, cy: CY, r: R + 12 });
    var dial = s('g', { class: 'gv-ops__dial' }, dialFace(), contour, stage3);

    /* шаг 01: бокс корпуса — уголки и метка */
    var bx = CX - 96;
    var by = CY - 136;
    var bw = 192;
    var bh = 272;
    function corner(x, y, dx, dy) {
      return s('path', { d: 'M' + x + ' ' + (y + dy) + ' V' + y + ' H' + (x + dx) });
    }
    var box = s('g', { class: 'gv-ops__o gv-ops__o--1 gv-ops__box' },
      corner(bx, by, 22, 22), corner(bx + bw, by, -22, 22), corner(bx, by + bh, 22, -22), corner(bx + bw, by + bh, -22, -22),
      s('rect', { class: 'gv-ops__tag', x: bx, y: by - 24, width: 176, height: 20 }),
      s('text', { class: 'gv-ops__t gv-ops__t--tag', x: bx + 6, y: by - 10, 'font-size': 12 }, F.box),
      s('text', { class: 'gv-ops__t', x: bx + bw + 12, y: CY - 8, 'font-size': 12 }, F.ellipse));

    /* шаг 02: квадрат нормализации */
    var square = s('g', { class: 'gv-ops__o gv-ops__o--2' },
      s('rect', { class: 'gv-ops__square', x: CX - R - 16, y: CY - R - 16, width: (R + 16) * 2, height: (R + 16) * 2 }),
      s('text', { class: 'gv-ops__t', x: CX + R + 24, y: CY - R - 6, 'font-size': 12 }, F.square));

    /* шаг 03: гистограмма момента — 72 столбца по 5°, пик у θ */
    var hist = s('g', { class: 'gv-ops__o gv-ops__o--3 gv-ops__hist' });
    var hx = 470;
    var hy = 352;
    var hw = 150;
    for (var k = 0; k < 72; k++) {
      var deg = k * 5;
      var d = Math.min(Math.abs(deg - theta), 360 - Math.abs(deg - theta));
      var v = 4 + 52 * Math.exp(-(d * d) / (2 * 9 * 9)) + 6 * Math.exp(-((Math.min(Math.abs(deg - 70), 360 - Math.abs(deg - 70))) ** 2) / 200);
      hist.appendChild(s('rect', { class: d < 5 ? 'gv-ops__bin is-peak' : 'gv-ops__bin', x: (hx + (k / 72) * hw).toFixed(1), y: (hy - v).toFixed(1), width: (hw / 72 - 0.4).toFixed(2), height: v.toFixed(1) }));
    }
    hist.appendChild(s('line', { class: 'gv-ops__axis', x1: hx, y1: hy, x2: hx + hw, y2: hy }));
    hist.appendChild(s('text', { class: 'gv-ops__t', x: hx, y: hy + 16, 'font-size': 11 }, F.hist));

    /* шаг 04: сырые отсчёты и EMA — скачок 4,39 → 6,0 МПа на 10-м кадре */
    var ema = s('g', { class: 'gv-ops__o gv-ops__o--4 gv-ops__ema' });
    var ex = 452;
    var ey = 96;
    var ew = 168;
    var eh = 210;
    ema.appendChild(s('rect', { class: 'gv-ops__panel', x: ex - 14, y: ey - 34, width: ew + 28, height: eh + 70, rx: 4 }));
    var vLo = 3.6;
    var vHi = 6.6;
    function px(i) { return ex + (i / 30) * ew; }
    function py(val) { return ey + eh - ((val - vLo) / (vHi - vLo)) * eh; }
    var smooth = null;
    var pts = '';
    var noise = [0.12, -0.18, 0.05, 0.2, -0.1, -0.22, 0.15, 0.02, -0.14, 0.19, -0.06, 0.24, -0.2, 0.08, 0.16, -0.12, -0.24, 0.1, 0.21, -0.04, -0.16, 0.13, 0.06, -0.21, 0.18, -0.09, 0.03, 0.22, -0.15, 0.11, -0.02];
    for (var f = 0; f <= 30; f++) {
      var truth = f < 10 ? 4.39 : 6.0;
      var raw = truth + noise[f];
      smooth = kit.emaStep(smooth, raw, 0.25);
      ema.appendChild(s('circle', { class: 'gv-ops__raw', cx: px(f).toFixed(1), cy: py(raw).toFixed(1), r: 2.6 }));
      pts += (f ? ' L' : 'M') + px(f).toFixed(1) + ' ' + py(smooth).toFixed(1);
    }
    ema.appendChild(s('path', { class: 'gv-ops__curve', d: pts }));
    ema.appendChild(s('line', { class: 'gv-ops__mark', x1: px(18), y1: ey, x2: px(18), y2: ey + eh }));
    ema.appendChild(s('line', { class: 'gv-ops__axis', x1: ex, y1: ey + eh, x2: ex + ew, y2: ey + eh }));
    ema.appendChild(s('text', { class: 'gv-ops__t gv-ops__t--accent', x: ex, y: ey - 14, 'font-size': 12 }, F.ema));
    ema.appendChild(s('text', { class: 'gv-ops__t', x: ex, y: ey + eh + 18, 'font-size': 11 }, F.raw));
    ema.appendChild(s('text', { class: 'gv-ops__t', x: px(18) + 4, y: ey + 12, 'font-size': 11 }, F.catchUp));

    /* сцена котельной за прибором: трубы и поручень — геометрия, без рисунка */
    var scene = s('g', { class: 'gv-ops__scene' },
      s('rect', { x: 0, y: 330, width: 640, height: 34, rx: 6 }),
      s('rect', { x: 560, y: 0, width: 40, height: 400, rx: 6 }),
      s('rect', { x: 284, y: 318, width: 32, height: 40 }),
      s('line', { x1: 0, y1: 270, x2: 640, y2: 250 }),
      s('line', { x1: 0, y1: 298, x2: 640, y2: 280 }));

    var svgEl = s('svg', { class: 'gv-ops__svg', viewBox: '0 0 640 400', role: 'img', 'aria-label': c.pipelineFrame },
      scene, box, dial, square, hist, ema);

    var frameNote = h('p', { class: 'gv-ops__frame-note' });
    var frame = h('figure', { class: 'gv-ops__frame gv-plate' }, svgEl,
      h('figcaption', { class: 'gv-ops__cap' }, h('span', null, c.pipelineFrame), frameNote));

    /* ---------- шаги ---------- */

    var buttons = [];
    var panels = [];
    var list = h('ol', { class: 'gv-ops__list', role: 'list', 'aria-label': L.opsList });
    cards.forEach(function (card, i) {
      var btn = h('button', { class: 'gv-ops__step', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'gv-ops-p' + i },
        h('span', { class: 'gv-ops__idx gv-num' }, card.index),
        h('span', { class: 'gv-ops__name' }, card.step));
      var lat = card.latency
        ? h('p', { class: 'gv-ops__lat' }, h('span', { class: 'gv-label' }, L.latency),
          h('span', { class: 'gv-ops__lat-v gv-num' }, card.latency.value, h('span', { class: 'gv-ops__lat-u' }, ' ' + card.latency.unit)),
          card.latency.note ? h('span', { class: 'gv-caption' }, card.latency.note) : null)
        : h('p', { class: 'gv-ops__lat gv-ops__lat--none' }, h('span', { class: 'gv-label' }, L.latency), h('span', { class: 'gv-caption' }, L.inTotal));
      var panel = h('div', { class: 'gv-ops__panel-text', id: 'gv-ops-p' + i, hidden: true },
        h('h3', { class: 'gv-ops__title' }, card.title.indexOf(card.step) === 0 ? card.title.slice(card.step.length).replace(/^[:\s]+/, '') : card.title),
        h('div', { class: 'gv-ops__formula' }, card.formula.map(function (f) { return kit.math(f).el; })),
        h('dl', { class: 'gv-ops__params' }, card.params.map(function (p) {
          return [h('dt', null, p.name), h('dd', { class: 'gv-num' }, p.value)];
        })),
        lat);
      buttons.push(btn);
      panels.push(panel);
      list.appendChild(h('li', { class: 'gv-ops__item' }, btn, panel));
    });

    var total = h('p', { class: 'gv-ops__total' },
      h('span', { class: 'gv-label' }, c.pipelineTotal.label),
      h('span', { class: 'gv-ops__total-v gv-num' }, c.pipelineTotal.value, h('span', { class: 'gv-ops__lat-u' }, ' ' + c.pipelineTotal.unit)),
      h('span', { class: 'gv-caption' }, c.pipelineTotal.condition));

    var pinned = h('div', { class: 'gv-ops__pin' }, h('div', { class: 'gv-ops__col' }, list, total), frame);
    var scroller = h('div', { class: 'gv-ops__scroll' }, pinned);
    body.appendChild(scroller);

    /* ---------- переключение ---------- */

    var current = -1;
    function show(i) {
      if (i === current) return;
      current = i;
      body.setAttribute('data-step', String(i + 1));
      buttons.forEach(function (b, j) {
        var on = j === i;
        b.setAttribute('aria-expanded', on ? 'true' : 'false');
        b.classList.toggle('is-on', on);
        panels[j].hidden = !on;
      });
      frameNote.textContent = cards[i].index + '. ' + cards[i].frame;
    }
    show(0);

    var narrow = window.matchMedia ? window.matchMedia('(max-width: 900px)') : null;
    function isPinned() {
      return !motion.reduced() && !(narrow && narrow.matches);
    }
    function sync() {
      body.classList.toggle('is-pinned', isPinned());
    }
    sync();
    if (narrow) {
      if (narrow.addEventListener) narrow.addEventListener('change', sync);
      sc.add(function () { if (narrow.removeEventListener) narrow.removeEventListener('change', sync); });
    }

    sc.add(motion.onScroll(function () {
      if (!isPinned()) return;
      show(stepFor(motion.pinProgress(scroller), cards.length));
    }));

    buttons.forEach(function (b, i) {
      sc.on(b, 'click', function () {
        if (!isPinned()) { show(i); return; }
        var m = motion.measure(scroller);
        var range = m.height - motion.viewport().height;
        var y = m.top + range * ((i + 0.5) / cards.length);
        window.scrollTo({ top: y, behavior: motion.reduced() ? 'auto' : 'smooth' });
        show(i);
      });
    });

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.operations = { mount: mount, stepFor: stepFor };
})();
