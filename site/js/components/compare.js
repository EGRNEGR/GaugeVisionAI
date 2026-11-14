/*
 * GV.components.compare — «Было (обход раз в смену) → Стало (GaugeVision AI)».
 * mount(el, { layout: 'split'|'toggle' }) → { destroy() }
 *   split  — две колонки рядом, шкала смены со своим переключателем (вариант A);
 *   toggle — одна колонка, общий переключатель «Было / Стало» управляет и колонкой, и шкалой.
 * Состав: колонки с пунктами и стоимостью точки (оценка команды), итог −89 %,
 * пара «сырой кадр → распознанное значение» (скриншоты или SVG при data-media="schematic"),
 * интерактивная шкала смены 12 ч с подписью «Иллюстративный сценарий».
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var LAYOUTS = ['split', 'toggle'];
  var T = {
    modeGroup: 'Сценарий',
    timelineTitle: 'Смена',
    detected: 'Обнаружено',
    hourUnit: 'ч',
    perPoint: 'на точку'
  };

  function mount(el, options) {
    options = options || {};
    var u = GV.util, kit = GV.kit, h = u.h, s = u.svg, fmt = u.formatNumber, NBSP = kit.NBSP;
    var c = GV.content;
    var cmp = c.compare;
    var tl = cmp.timeline;
    var stage = c.hero.stage;
    var layout = kit.pick(options.layout, LAYOUTS);
    var sc = kit.scope();
    var mode = layout === 'toggle' ? 'before' : 'after';
    var mediaMode = null;

    /* ---------- колонки ---------- */

    function column(key) {
      var data = cmp[key];
      return h('section', { class: 'gv-compare__col gv-compare__col--' + key, 'data-side': key },
        h('h3', { class: 'gv-compare__title' }, data.title),
        h('ul', { class: 'gv-compare__points', role: 'list' },
          data.points.map(function (p) { return h('li', { class: 'gv-compare__point' }, p); })),
        h('p', { class: 'gv-compare__cost' },
          h('span', { class: 'gv-compare__cost-value' }, data.cost.value),
          h('span', { class: 'gv-compare__cost-unit' }, data.cost.unit)),
        h('p', { class: 'gv-compare__cost-note' }, data.cost.note));
    }

    var colBefore = column('before');
    var colAfter = column('after');

    var saving = h('div', { class: 'gv-compare__saving' },
      cmp.saving ? h('p', { class: 'gv-compare__saving-value' },
        h('span', { class: 'gv-compare__saving-num' }, cmp.saving.value),
        h('span', { class: 'gv-compare__saving-label' }, cmp.saving.label)) : null,
      h('p', { class: 'gv-compare__saving-note' }, cmp.savingNote));

    /* ---------- пара «сырой кадр → распознанное значение» ---------- */

    var pairRaw = h('div', { class: 'gv-compare__pair-media' });
    var pairRec = h('div', { class: 'gv-compare__pair-media' });
    var pair = h('div', { class: 'gv-compare__pair' },
      h('figure', { class: 'gv-compare__pair-item' }, pairRaw, h('figcaption', null, cmp.pair.rawLabel)),
      h('span', { class: 'gv-compare__pair-arrow', 'aria-hidden': 'true' }, kit.icon('right')),
      h('figure', { class: 'gv-compare__pair-item' }, pairRec, h('figcaption', null, cmp.pair.recognizedLabel)));

    function renderMedia() {
      var m = kit.media();
      if (m === mediaMode) return;
      mediaMode = m;
      pairRaw.textContent = '';
      pairRec.textContent = '';
      var ro = stage.readout;
      if (m === 'shots') {
        pairRaw.appendChild(kit.crop(stage.raw, 'gv-compare__shot'));
        pairRec.appendChild(kit.crop(stage.recognized, 'gv-compare__shot'));
      } else {
        pairRaw.appendChild(kit.dial({ theta: ro.theta, className: 'gv-compare__svg', title: cmp.pair.rawLabel }));
        pairRec.appendChild(kit.dial({
          theta: ro.theta, overlay: true, className: 'gv-compare__svg',
          valueLabel: fmt(ro.value, 2) + NBSP + ro.unit,
          title: cmp.pair.recognizedLabel + ': ' + fmt(ro.value, 2) + NBSP + ro.unit
        }));
      }
    }

    /* ---------- шкала смены ---------- */

    var hours = tl.shiftHours;
    function pos(hour) { return ((hour / hours) * 100).toFixed(3) + '%'; }
    var nextRound = tl.rounds.filter(function (r) { return r > tl.deviationHour; })[0];
    if (nextRound === undefined) nextRound = hours;

    var hourTicks = [];
    for (var i = 0; i <= hours; i++) {
      hourTicks.push(h('span', { class: ['gv-compare__hour', i % 6 === 0 ? 'gv-compare__hour--major' : null], style: { left: pos(i) }, 'aria-hidden': 'true' }));
    }
    var roundMarks = tl.rounds.map(function (r) {
      var edge = r <= 0 ? 'gv-compare__mark--start' : (r >= hours ? 'gv-compare__mark--end' : null);
      return h('span', { class: ['gv-compare__mark', 'gv-compare__mark--round', edge], style: { left: pos(r) } },
        h('span', { class: 'gv-compare__mark-label' }, tl.roundLabel));
    });
    var gap = h('span', { class: 'gv-compare__gap', style: { left: pos(tl.deviationHour), width: (((nextRound - tl.deviationHour) / hours) * 100).toFixed(3) + '%' }, 'aria-hidden': 'true' });
    var watch = h('span', { class: 'gv-compare__watch', 'aria-hidden': 'true' });
    var deviation = h('span', { class: 'gv-compare__mark gv-compare__mark--deviation', style: { left: pos(tl.deviationHour) } },
      h('span', { class: 'gv-compare__mark-label' }, tl.deviationLabel));
    var detect = h('span', { class: 'gv-compare__mark gv-compare__mark--detect' },
      h('span', { class: 'gv-compare__mark-label' }, T.detected));
    var scaleEl = h('div', { class: 'gv-compare__scale' },
      h('div', { class: 'gv-compare__bar' }, watch, gap, hourTicks),
      roundMarks, deviation, detect,
      h('span', { class: 'gv-compare__edge gv-compare__edge--start' }, '0' + NBSP + T.hourUnit),
      h('span', { class: 'gv-compare__edge gv-compare__edge--end' }, fmt(hours) + NBSP + T.hourUnit));
    var tlText = h('p', { class: 'gv-compare__timeline-text', 'aria-live': 'polite' });

    var btnBefore = h('button', { type: 'button', class: 'gv-compare__mode', 'aria-pressed': 'false', 'data-mode': 'before' }, tl.beforeLabel);
    var btnAfter = h('button', { type: 'button', class: 'gv-compare__mode', 'aria-pressed': 'false', 'data-mode': 'after' }, tl.afterLabel);
    var modes = h('div', { class: 'gv-compare__modes', role: 'group', 'aria-label': T.modeGroup }, btnBefore, btnAfter);

    var timeline = h('div', { class: 'gv-compare__timeline' },
      h('div', { class: 'gv-compare__timeline-head' },
        h('h3', { class: 'gv-compare__timeline-title' }, T.timelineTitle + ' ' + fmt(hours) + NBSP + T.hourUnit),
        layout === 'split' ? modes : null,
        h('p', { class: 'gv-compare__illustrative' }, tl.caption)),
      scaleEl,
      tlText);

    var rootEl = h('div', { class: ['gv-compare', 'gv-compare--' + layout] },
      layout === 'toggle' ? h('div', { class: 'gv-compare__switch' }, modes) : null,
      h('div', { class: 'gv-compare__cols' }, colBefore,
        h('span', { class: 'gv-compare__arrow', 'aria-hidden': 'true' }, kit.icon('right')),
        colAfter),
      h('div', { class: 'gv-compare__extra' }, saving, pair),
      timeline);
    el.appendChild(rootEl);

    function apply(next) {
      mode = next;
      rootEl.setAttribute('data-mode', next);
      var before = next === 'before';
      detect.style.setProperty('--pos', pos(before ? nextRound : tl.deviationHour));
      tlText.textContent = before ? tl.beforeText : tl.afterText;
      if (layout === 'toggle') {
        colBefore.hidden = !before;
        colAfter.hidden = before;
      }
    }

    var roving = u.rovingTabs(modes, {
      selector: '.gv-compare__mode',
      attr: 'aria-pressed',
      initial: mode === 'before' ? 0 : 1,
      onSelect: function (i) { apply(i === 0 ? 'before' : 'after'); }
    });
    sc.add(roving.destroy);

    renderMedia();
    kit.onTweaks(sc, renderMedia);

    return {
      destroy: function () {
        sc.destroy();
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      }
    };
  }

  GV.components.compare = { mount: mount, layouts: LAYOUTS.slice() };
})();
