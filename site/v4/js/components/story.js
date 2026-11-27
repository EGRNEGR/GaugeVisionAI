/*
 * GV.components.story — «Один прибор — весь инженерный цикл»: закреплённая сцена из восьми этапов.
 * mount(el, { head }) → { destroy(), goTo(i) }
 *
 * Один SVG 1200×760. Манометр PI-102 — один и тот же элемент на всех этапах: его положение и масштаб
 * задаёт CSS по data-scene (переход transform), поэтому зритель видит, как физический прибор становится
 * каналом щита, строкой телеметрии, тегом SCADA, точкой тренда, позицией плана и строкой ТЗ.
 * Прокрутка: высота секции = этапы × 68vh + экран; активный этап = floor(p × N), внутри — доля этапа
 * (--sp) для мелких движений. Колонка слева: список этапов (щелчок — прокрутка к этапу), доказательство
 * и источник активного этапа. Вне desktop — та же сцена, стек: прибор сверху, текст снизу.
 * reduced motion: без закрепления, все этапы списком, сцена показывает выбранный этап.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var VW = 1200, VH = 760;
  var PER = 0.68; // доля экрана на этап

  function mount(el, opts) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit, motion = GV.motion, draw = GV.draw;
    var C = GV.content;
    var st = C.story;
    var hero = C.hero;
    var panel = C.panel;
    var N = st.scenes.length;
    var offs = [];
    var sc = kit.scope();
    var fmt = u.formatNumber;

    /* ---------- SVG-сцена ---------- */
    var svg = s('svg', { class: 'gv-st', viewBox: '0 0 ' + VW + ' ' + VH, role: 'img', 'aria-labelledby': 'gv-st-desc', focusable: 'false', 'data-scene': '0' });
    var desc = s('desc', { id: 'gv-st-desc' }, '');
    svg.appendChild(desc);

    // Труба физического мира
    var pipe = s('g', { class: 'gv-st__layer gv-st__pipe', 'data-for': '0 1' },
      s('rect', { class: 'gv-st__pipe-body', x: -20, y: 560, width: VW + 40, height: 70, rx: 6 }),
      s('rect', { class: 'gv-st__pipe-stem', x: 586, y: 520, width: 28, height: 50 }),
      s('rect', { class: 'gv-st__pipe-plate', x: 900, y: 470, width: 150, height: 54, rx: 3 }),
      s('text', { class: 'gv-st__plate-text', x: 975, y: 494 }, 'МН 0–1,6'),
      s('text', { class: 'gv-st__plate-text gv-st__plate-text--s', x: 975, y: 512 }, 'кл. т. 1,5'));
    svg.appendChild(pipe);

    // Остальные семь приборов щита (этап 2): сетка 4×2
    function slot(i) { return { x: 165 + (i % 4) * 290, y: 225 + Math.floor(i / 4) * 300 }; }
    var panelLayer = s('g', { class: 'gv-st__layer gv-st__panel', 'data-for': '2' });
    var tags = s('g', { class: 'gv-st__layer gv-st__tags', 'data-for': '2' });
    panel.forEach(function (p, i) {
      var pos = slot(i);
      if (!p.hero) {
        var g = draw.gauge({ r: 95, min: p.min, max: p.max, value: p.value, unit: p.unit, labels: true });
        g.setAttribute('transform', 'translate(' + pos.x + ' ' + pos.y + ')');
        panelLayer.appendChild(g);
      }
      var tw = 170;
      tags.appendChild(s('g', { class: ['gv-st__tag', p.hero ? 'gv-st__tag--hero' : null], transform: 'translate(' + (pos.x - 95) + ' ' + (pos.y - 128) + ')' },
        s('rect', { width: tw, height: 24, rx: 2 }),
        s('text', { x: 8, y: 17 }, p.code + '  ' + fmt(p.value, p.max < 10 ? 2 : 1) + ' ' + p.unit)));
    });
    svg.appendChild(panelLayer);

    // Прибор-герой: один элемент на все этапы
    var heroG = draw.gauge({ r: 260, min: hero.min, max: hero.max, value: hero.value, unit: hero.unit, warn: hero.warn, alert: hero.alert, major: 0.2, label: 'PI-102' });
    var heroWrap = s('g', { class: 'gv-st__hero' }, heroG);
    svg.appendChild(heroWrap);
    svg.appendChild(tags);

    // CV-разметка поверх героя (этап 1)
    var heroAngle = draw.valueToAngle(hero.value, hero.min, hero.max) * Math.PI / 180;
    var cv = s('g', { class: 'gv-st__layer gv-st__cv', 'data-for': '1' },
      s('path', { class: 'gv-st__cv-box', d: 'M310 150V120H340M860 120H890V150M890 610V640H860M340 640H310V610' }),
      s('ellipse', { class: 'gv-st__cv-ell', cx: 600, cy: 380, rx: 236, ry: 236 }),
      s('line', { class: 'gv-st__cv-needle', x1: 600, y1: 380, x2: (600 + 200 * Math.cos(heroAngle)).toFixed(1), y2: (380 + 200 * Math.sin(heroAngle)).toFixed(1) }),
      s('path', { class: 'gv-st__cv-arc', d: kit.arcPath(600, 380, 70, 135, draw.valueToAngle(hero.value, hero.min, hero.max)) }),
      s('rect', { class: 'gv-st__cv-scan', x: 310, y: 120, width: 580, height: 2 }),
      s('g', { class: 'gv-st__cv-read', transform: 'translate(905 170)' },
        s('rect', { width: 250, height: 132, rx: 4 }),
        s('text', { class: 'gv-st__k', x: 16, y: 28 }, 'PI-102  θ = ' + fmt(draw.valueToAngle(hero.value, hero.min, hero.max) - 360 * (draw.valueToAngle(hero.value, hero.min, hero.max) >= 360 ? 1 : 0), 1) + '°'),
        s('text', { class: 'gv-st__big', x: 16, y: 78 }, fmt(hero.value, 2)),
        s('text', { class: 'gv-st__k', x: 150, y: 78 }, 'МПа'),
        s('text', { class: 'gv-st__ok', x: 16, y: 112 }, 'достоверно  H пройдена')));
    svg.appendChild(cv);

    // Телеметрия (этап 3): строки-потоки
    function rowY(i) { return 92 + i * 82; }
    var tele = s('g', { class: 'gv-st__layer gv-st__tele', 'data-for': '3 4' });
    panel.forEach(function (p, i) {
      var y = rowY(i);
      var spark = [];
      for (var k = 0; k <= 30; k++) {
        var nv = Math.sin(k * 0.7 + i) * 0.35 + Math.sin(k * 1.9 + i * 2) * 0.2;
        var trend = p.hero ? (k / 30) * 1.6 : 0;
        spark.push((300 + k * 14) + ' ' + (y - nv * 12 - trend * 12).toFixed(1));
      }
      tele.appendChild(s('g', { class: ['gv-st__row', p.hero ? 'gv-st__row--hero' : null] },
        s('line', { class: 'gv-st__row-line', x1: 165, x2: 300, y1: y, y2: y }),
        s('circle', { class: 'gv-st__packet', cx: 165, cy: y, r: 4, style: { '--d': (i * 0.17).toFixed(2) + 's' } }),
        s('path', { class: 'gv-st__spark', d: 'M' + spark.join('L') }),
        s('text', { class: 'gv-st__row-code', x: 90, y: y + 5 }, p.code),
        s('text', { class: 'gv-st__row-val', x: 760, y: y + 6 }, fmt(p.value, p.max < 10 ? 2 : 1) + ' ' + p.unit),
        s('circle', { class: ['gv-st__row-dot', p.hero ? 'gv-st__row-dot--warn' : null], cx: 905, cy: y, r: 5 }),
        s('text', { class: 'gv-st__row-st', x: 920, y: y + 5 }, p.hero ? 'H' : 'норма')));
      if (!p.hero) {
        var mini = draw.gauge({ r: 28, min: p.min, max: p.max, value: p.value, labels: false });
        mini.setAttribute('transform', 'translate(130 ' + y + ')');
        mini.setAttribute('class', 'gv-g gv-st__mini');
        tele.appendChild(mini);
      }
    });
    svg.appendChild(tele);

    // SCADA (этап 4): регистры и окно Ignition
    var scadaL = s('g', { class: 'gv-st__layer gv-st__scada', 'data-for': '4' },
      s('g', { transform: 'translate(985 60)' },
        s('rect', { class: 'gv-st__scada-win', width: 190, height: 640, rx: 6 }),
        s('text', { class: 'gv-st__k', x: 14, y: 28 }, 'Ignition 8.3.10'),
        s('text', { class: 'gv-st__k gv-st__k--dim', x: 14, y: 46 }, 'Tag Historian'),
        panel.map(function (p, i) {
          return s('g', { transform: 'translate(12 ' + (66 + i * 70) + ')' },
            s('rect', { class: ['gv-st__scada-tag', p.hero ? 'gv-st__scada-tag--warn' : null], width: 166, height: 58, rx: 3 }),
            s('text', { class: 'gv-st__k', x: 10, y: 20 }, 'P0' + (i + 1) + '  ' + p.code),
            s('text', { class: 'gv-st__v', x: 10, y: 45 }, fmt(p.value, p.max < 10 ? 2 : 1) + ' ' + p.unit));
        })),
      s('text', { class: 'gv-st__k gv-st__k--accent', x: 990, y: 735 }, 'Modbus TCP  HR 0…799'));
    svg.appendChild(scadaL);

    // Аналитика (этап 5): график прогноза
    var fc = draw.forecastChart({ w: 900, h: 520, f: C.forecast, compact: false, reveal: 0 });
    var analytics = s('g', { class: 'gv-st__layer gv-st__analytics', 'data-for': '5' },
      s('g', { transform: 'translate(250 150)' }, fc.el),
      s('g', { class: 'gv-st__hs', transform: 'translate(40 470)' },
        s('rect', { width: 180, height: 120, rx: 4 }),
        s('text', { class: 'gv-st__k', x: 14, y: 28 }, 'Health Score'),
        s('text', { class: 'gv-st__big gv-st__big--warn', x: 14, y: 80 }, '58 %'),
        s('text', { class: 'gv-st__k gv-st__k--dim', x: 14, y: 104 }, 'подсказка, не ресурс')),
      s('g', { class: 'gv-st__event', transform: 'translate(250 70)' },
        s('rect', { width: 560, height: 50, rx: 4 }),
        s('circle', { cx: 24, cy: 25, r: 6 }),
        s('text', { class: 'gv-st__k', x: 42, y: 31 }, 'prediction  imminent  PI-102: HH через ~13 мин')));
    svg.appendChild(analytics);

    // Решение (этап 6): плитки парка и бюджет
    var picked = { 'PI-101': 1, 'PI-102': 1, 'PI-104': 1, 'PI-107': 1 };
    var cands = GV.optimizerCore ? GV.optimizerCore.candidates(C.fleet, C.catalog, C.panel) : [];
    var budget = 450000;
    var decision = s('g', { class: 'gv-st__layer gv-st__decision', 'data-for': '6' });
    cands.forEach(function (cnd, i) {
      var x = 70 + (i % 4) * 275, y = 150 + Math.floor(i / 4) * 210;
      var on = !!picked[cnd.code];
      decision.appendChild(s('g', { class: ['gv-st__tile', on ? 'gv-st__tile--on' : null], transform: 'translate(' + x + ' ' + y + ')', style: { '--i': i } },
        s('rect', { width: 245, height: 180, rx: 6 }),
        s('text', { class: 'gv-st__k', x: 18, y: 32 }, cnd.code + (cnd.mandatory ? '  обяз.' : '')),
        s('text', { class: 'gv-st__k gv-st__k--dim', x: 18, y: 54 }, 'HS ' + cnd.hs + ' %'),
        s('text', { class: 'gv-st__v', x: 18, y: 112 }, fmt(cnd.capex / 1000, 1) + ' тыс. ₽'),
        s('text', { class: on ? 'gv-st__ok' : 'gv-st__k gv-st__k--dim', x: 18, y: 152 }, on ? 'в плане' : 'отложено')));
    });
    var used = cands.filter(function (c2) { return picked[c2.code]; }).reduce(function (a, c2) { return a + c2.capex; }, 0);
    decision.appendChild(s('g', { transform: 'translate(70 610)' },
      s('rect', { class: 'gv-st__budget-track', width: 1060, height: 18, rx: 9 }),
      s('rect', { class: 'gv-st__budget-fill', width: (1060 * used / budget).toFixed(1), height: 18, rx: 9 }),
      s('text', { class: 'gv-st__k', x: 0, y: 56 }, 'Использовано ' + fmt(used, 0) + ' ₽ из ' + fmt(budget, 0) + ' ₽'),
      s('text', { class: 'gv-st__k gv-st__k--accent', x: 1060, y: 56, 'text-anchor': 'end' }, 'оптимум доказан')));
    svg.appendChild(decision);

    // Документ (этап 7)
    var lines = [
      ['h', 'ТЕХНИЧЕСКОЕ ЗАДАНИЕ ' + C.documentSection.docNumber],
      ['m', 'на модернизацию КИПиА по данным мониторинга'],
      ['s', '1. Результаты мониторинга'],
      ['t', 'PI-102: рост 0,015 МПа/мин, уставка H пройдена'],
      ['t', 'прогноз HH через 13,18 мин, интервал 12,01–14,59'],
      ['s', '2. План модернизации'],
      ['t', 'PI-101, PI-102, PI-104, PI-107 — 383 040 ₽'],
      ['t', 'бюджет 450 000 ₽, PI-102 — обязательная позиция'],
      ['s', '3. Требования к оборудованию'],
      ['t', 'Цифровой преобразователь давления, 4–20 мА + HART'],
      ['t', 'Термопреобразователь Pt100, класс A']
    ];
    var docG = s('g', { class: 'gv-st__doc', transform: 'translate(330 40)' }, s('rect', { class: 'gv-st__doc-page', width: 540, height: 680, rx: 4 }));
    var ly = 70;
    lines.forEach(function (ln, i) {
      ly += ln[0] === 's' ? 44 : (ln[0] === 'h' ? 0 : 30);
      docG.appendChild(s('text', { class: 'gv-st__doc-' + ln[0], x: 40, y: ly, style: { '--i': i } }, ln[1]));
    });
    var docThumb = draw.forecastChart({ w: 220, h: 110, f: C.forecast, compact: true });
    docG.appendChild(s('g', { class: 'gv-st__doc-chart', transform: 'translate(40 ' + (ly + 26) + ')' }, docThumb.el));
    svg.appendChild(s('g', { class: 'gv-st__layer gv-st__document', 'data-for': '7' }, docG));

    /* ---------- колонка текста ---------- */
    var items = st.scenes.map(function (scn, i) {
      var srcObj = scn.source ? C.src[scn.source] : null;
      return h('li', { class: 'gv-story__item', 'data-i': i },
        h('button', { class: 'gv-story__btn', type: 'button', 'aria-controls': 'gv-story-stage' },
          h('span', { class: 'gv-story__num' }, String(i + 1).padStart(2, '0')),
          h('span', { class: 'gv-story__tag' }, scn.tag)),
        h('div', { class: 'gv-story__body' },
          h('h3', { class: 'gv-story__title' }, scn.title),
          h('p', { class: 'gv-story__text' }, scn.text),
          scn.proof ? h('p', { class: 'gv-story__proof' }, h('span', { class: 'gv-story__proof-mark', 'aria-hidden': 'true' }), scn.proof,
            srcObj ? h('span', null, ' — ', kit.extLink({ class: 'gv-src', href: srcObj.href }, srcObj.label)) : null) : null));
    });
    var list = h('ol', { class: 'gv-story__list', role: 'list' }, items);
    var progress = h('span', { class: 'gv-story__progress-fill' });
    var col = h('div', { class: 'gv-story__col' },
      opts && opts.head ? opts.head : null,
      h('div', { class: 'gv-story__progress', 'aria-hidden': 'true' }, progress),
      list);
    var badge = h('p', { class: 'gv-story__badge' }, C.labels.sim, ' — ', 'данные сквозного испытания v3.0.0');
    var stageBox = h('div', { class: 'gv-story__stage', id: 'gv-story-stage' }, svg, badge);
    var sticky = h('div', { class: 'gv-story__sticky' }, h('div', { class: 'gv-container gv-story__grid' }, col, stageBox));
    var scene = h('div', { class: 'gv-story', style: { '--n': N } }, sticky);
    el.appendChild(scene);

    var current = -1;
    function setScene(i) {
      if (i === current) return;
      current = i;
      svg.setAttribute('data-scene', String(i));
      items.forEach(function (it, k) {
        it.toggleAttribute('data-active', k === i);
        it.toggleAttribute('data-done', k < i);
        it.querySelector('.gv-story__btn').setAttribute('aria-current', k === i ? 'step' : 'false');
      });
      svg.querySelectorAll('.gv-st__layer').forEach(function (layer) {
        var on = (' ' + layer.getAttribute('data-for') + ' ').indexOf(' ' + i + ' ') >= 0;
        layer.toggleAttribute('data-on', on);
      });
      desc.textContent = st.scenes[i].title + '. ' + st.scenes[i].text;
      fc.setReveal(i === 5 ? 1 : 0);
    }

    function scrollToScene(i, smooth) {
      if (motion.reduced() || scene.hasAttribute('data-static')) { setScene(i); return; }
      var m = motion.measure(scene);
      var vh = motion.viewport().height;
      var span = Math.max(1, m.height - vh);
      root.scrollTo({ top: m.top + span * ((i + 0.5) / N), behavior: smooth ? 'smooth' : 'auto' });
    }

    items.forEach(function (it, i) {
      sc.on(it.querySelector('.gv-story__btn'), 'click', function () { scrollToScene(i, !motion.reduced()); });
    });

    if (motion.reduced()) {
      scene.setAttribute('data-static', '');
      setScene(0);
    } else {
      offs.push(motion.onScroll(function () {
        var p = motion.pinProgress(scene);
        var f = p * N;
        var i = Math.max(0, Math.min(N - 1, Math.floor(f)));
        setScene(i);
        var sp = Math.max(0, Math.min(1, f - i));
        svg.style.setProperty('--sp', sp.toFixed(3));
        progress.style.transform = 'scaleY(' + p.toFixed(4) + ')';
      }));
      setScene(0);
    }

    function destroy() {
      offs.forEach(function (off) { off(); });
      sc.destroy();
      if (scene.parentNode) scene.parentNode.removeChild(scene);
    }

    return { destroy: destroy, goTo: function (i) { scrollToScene(i, false); setScene(i); } };
  }

  GV.components.story = { mount: mount };
})();
