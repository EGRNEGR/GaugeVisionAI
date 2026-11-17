/*
 * GV.components.compare — «Было (обход раз в смену) → Стало (GaugeVision AI)».
 * mount(el) → { destroy() }
 * Две колонки «Было» и «Стало» всегда видны (на телефоне — стопкой): пункты и стоимость точки (оценка
 * команды), ниже — итог −89 %. Под ним шкала смены 12 ч с подписью «Иллюстративный сценарий»; переключатель
 * «Было / Стало» стоит в шапке шкалы: ведёт отметку «Обнаружено» и подсвечивает свою колонку. Стартует с «Было».
 * Переключатель — капсула с бегунком (transform); отметка едет медленно (--dur-crawl), доехав — расходится
 * кольцом-пингом. Цены и итог докручиваются от нуля GV.motion.counter; ширину держит невидимый конечный текст.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var NUMBER_RE = /\d[\d \u00a0]*\d|\d/;

  var T = {
    modeGroup: 'Сценарий',
    timelineTitle: 'Смена',
    detected: 'Обнаружено',
    hourUnit: 'ч'
  };

  function mount(el) {
    var u = GV.util, kit = GV.kit, h = u.h, fmt = u.formatNumber, NBSP = kit.NBSP;
    var c = GV.content;
    var cmp = c.compare;
    var tl = cmp.timeline;
    var sc = kit.scope();
    var counters = [];

    /* Число с докруткой: живой текст поверх невидимого конечного, читающим экран — конечная строка */
    function countUp(cls, text) {
      var live = h('span', { class: 'gv-compare__count-live', 'aria-hidden': 'true' }, text);
      counters.push({ el: live, text: text });
      return h('span', { class: [cls, 'gv-compare__count'] },
        h('span', { class: 'gv-compare__count-ghost', 'aria-hidden': 'true' }, text),
        live,
        h('span', { class: 'gv-visually-hidden' }, text));
    }

    /* ---------- колонки ---------- */

    function column(key) {
      var data = cmp[key];
      return h('section', { class: 'gv-compare__col gv-compare__col--' + key, 'data-side': key },
        h('h3', { class: 'gv-compare__title' }, data.title),
        h('ul', { class: 'gv-compare__points', role: 'list' },
          data.points.map(function (p) { return h('li', { class: 'gv-compare__point' }, p); })),
        h('p', { class: 'gv-compare__cost' },
          countUp('gv-compare__cost-value', data.cost.value),
          h('span', { class: 'gv-compare__cost-unit' }, data.cost.unit)),
        h('p', { class: 'gv-compare__cost-note' }, data.cost.note));
    }

    var colBefore = column('before');
    var colAfter = column('after');

    var saving = h('div', { class: 'gv-compare__saving' },
      cmp.saving ? h('p', { class: 'gv-compare__saving-value' },
        countUp('gv-compare__saving-num', cmp.saving.value),
        h('span', { class: 'gv-compare__saving-label' }, cmp.saving.label)) : null,
      h('p', { class: 'gv-compare__saving-note' }, cmp.savingNote));

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
    var modes = h('div', { class: 'gv-compare__modes', role: 'group', 'aria-label': T.modeGroup },
      h('span', { class: 'gv-compare__thumb', 'aria-hidden': 'true' }), btnBefore, btnAfter);

    var timeline = h('div', { class: 'gv-compare__timeline' },
      h('div', { class: 'gv-compare__timeline-head' },
        h('h3', { class: 'gv-compare__timeline-title' }, T.timelineTitle + ' ' + fmt(hours) + NBSP + T.hourUnit),
        h('p', { class: 'gv-compare__illustrative' }, tl.caption),
        modes),
      scaleEl,
      tlText);

    var rootEl = h('div', { class: 'gv-compare gv-compare--toggle' },
      h('div', { class: 'gv-compare__cols' }, colBefore, colAfter),
      saving,
      timeline);
    el.appendChild(rootEl);

    /* Класс анимации снимается и ставится заново через перерасчёт стиля — так она играет при каждом переключении */
    function replay(node, cls) {
      node.classList.remove(cls);
      void node.offsetWidth;
      node.classList.add(cls);
    }

    var started = false;
    function apply(next) {
      rootEl.setAttribute('data-mode', next);
      var before = next === 'before';
      detect.style.setProperty('--pos', pos(before ? nextRound : tl.deviationHour));
      tlText.textContent = before ? tl.beforeText : tl.afterText;
      if (started) replay(tlText, 'is-swap');
      started = true;
      colBefore.classList.toggle('is-active', before);
      colAfter.classList.toggle('is-active', !before);
    }

    sc.on(detect, 'transitionend', function (e) {
      if (e.target === detect && e.propertyName === 'transform') replay(detect, 'is-ping');
    });

    var roving = u.rovingTabs(modes, {
      selector: '.gv-compare__mode',
      attr: 'aria-pressed',
      initial: 0,
      onSelect: function (i) { apply(i === 0 ? 'before' : 'after'); }
    });
    sc.add(roving.destroy);

    counters.forEach(function (n) {
      var m = n.text.match(NUMBER_RE);
      if (!m) return;
      var value = Number(m[0].replace(/\D/g, ''));
      sc.add(GV.motion.counter(n.el, {
        to: 1,
        display: n.text,
        duration: 1600,
        format: function (t) { return n.text.replace(m[0], fmt(Math.round(value * t))); }
      }));
    });

    return {
      destroy: function () {
        sc.destroy();
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      }
    };
  }

  GV.components.compare = { mount: mount };
})();
