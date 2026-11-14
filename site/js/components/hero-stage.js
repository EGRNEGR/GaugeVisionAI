/*
 * GV.components.heroStage — переключатель «Сырой кадр с камеры → Распознавание и снятие показаний».
 * mount(el, { layout: 'framed'|'dial'|'sheet' }) → { destroy() }
 *   framed — рамка с угловыми метками: кадр слева, телеметрия справа (вариант A);
 *   dial   — круглое окно кадра, телеметрия строкой под ним;
 *   sheet  — лист протокола: кадр и таблица значений.
 * Корень получает id="hero-stage" и tabindex="-1" — к нему ведёт кнопка «Смотреть демо».
 * Скриншоты кадрируются CSS (GV.kit.crop); при html[data-media="schematic"] — SVG-циферблат
 * с эллипсом ROI, вектором стрелки и θ. Переход — сканирующая линия ≤ 600 мс, без неё при reduced motion.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var LAYOUTS = ['framed', 'dial', 'sheet'];
  var SCAN_MS = 600;
  var AUTOPLAY_MS = 1600;
  var T = {
    group: 'Режим демонстрации',
    empty: '—',
    pending: 'не снято',
    live: 'Сейчас показан режим: '
  };

  function mount(el, options) {
    var u = GV.util;
    var kit = GV.kit;
    var h = u.h;
    var fmt = u.formatNumber;
    var NBSP = kit.NBSP;
    var stage = GV.content.hero.stage;
    var ro = stage.readout;
    var L = stage.labels;
    var layout = kit.pick(options && options.layout, LAYOUTS);
    var sc = kit.scope();
    var state = 'raw';
    var touched = false;
    var mediaMode = null;
    var cancelScan = null;

    var thetaText = 'θ' + NBSP + '=' + NBSP + fmt(ro.theta, 1) + '°';
    var valueText = fmt(ro.value, 2) + NBSP + ro.unit;
    var rows = [
      { key: 'value', label: L.value, value: valueText, strong: true },
      { key: 'theta', label: L.theta, value: fmt(ro.theta, 1) + '°' },
      { key: 'conf', label: L.conf, value: fmt(ro.conf, 2) },
      { key: 'roi', label: L.roi, value: ro.roi },
      { key: 'latency', label: L.latency, value: fmt(ro.latencyMs, 1) + NBSP + 'мс' }
    ];

    /* ---------- разметка ---------- */

    var btnRaw = h('button', { type: 'button', class: 'gv-hero-stage__mode', 'aria-pressed': 'true', 'data-mode': 'raw' },
      h('span', { class: 'gv-hero-stage__mode-dot', 'aria-hidden': 'true' }), stage.rawLabel);
    var btnRec = h('button', { type: 'button', class: 'gv-hero-stage__mode', 'aria-pressed': 'false', 'data-mode': 'recognized' },
      h('span', { class: 'gv-hero-stage__mode-dot', 'aria-hidden': 'true' }), stage.recognizedLabel);
    var toggle = h('div', { class: 'gv-hero-stage__toggle', role: 'group', 'aria-label': T.group }, btnRaw, btnRec);

    var layerRaw = h('div', { class: 'gv-hero-stage__layer gv-hero-stage__layer--raw' });
    var layerRec = h('div', { class: 'gv-hero-stage__layer gv-hero-stage__layer--recognized', 'aria-hidden': 'true' });
    var scan = h('div', { class: 'gv-hero-stage__scan', 'aria-hidden': 'true' });
    var viewport = h('div', { class: 'gv-hero-stage__viewport' }, layerRaw, layerRec, scan);

    var readout = h('dl', { class: 'gv-hero-stage__readout' },
      rows.map(function (r) {
        return h('div', { class: ['gv-hero-stage__row', r.strong ? 'gv-hero-stage__row--main' : null], 'data-key': r.key },
          h('dt', { class: 'gv-hero-stage__key' }, r.label),
          h('dd', { class: 'gv-hero-stage__val' },
            h('span', { class: 'gv-hero-stage__val-live' }, r.value),
            h('span', { class: 'gv-hero-stage__val-empty', title: T.pending }, T.empty)));
      }));

    var caption = h('p', { class: 'gv-hero-stage__caption' });
    var live = h('p', { class: 'gv-visually-hidden', 'aria-live': 'polite' });

    var corners = layout === 'framed'
      ? ['tl', 'tr', 'bl', 'br'].map(function (pos) { return h('span', { class: 'gv-hero-stage__corner gv-hero-stage__corner--' + pos, 'aria-hidden': 'true' }); })
      : null;

    var rootEl = h('div', {
      class: ['gv-hero-stage', 'gv-hero-stage--' + layout],
      id: 'hero-stage',
      tabindex: '-1',
      role: 'region',
      'aria-label': stage.rawLabel + ' → ' + stage.recognizedLabel,
      'data-state': 'raw'
    },
      corners,
      h('div', { class: 'gv-hero-stage__bar' },
        h('p', { class: 'gv-hero-stage__device' }, ro.device),
        toggle),
      h('div', { class: 'gv-hero-stage__body' }, viewport, readout),
      caption,
      live);

    el.appendChild(rootEl);

    /* ---------- медиа: скриншоты или схема ---------- */

    function renderMedia() {
      var mode = kit.media();
      if (mode === mediaMode) return;
      mediaMode = mode;
      layerRaw.textContent = '';
      layerRec.textContent = '';
      rootEl.setAttribute('data-media-mode', mode);
      if (mode === 'shots') {
        layerRaw.appendChild(kit.crop(stage.raw, 'gv-hero-stage__shot'));
        layerRec.appendChild(kit.crop(stage.recognized, 'gv-hero-stage__shot'));
        caption.textContent = stage.caption;
      } else {
        layerRaw.appendChild(kit.dial({
          className: 'gv-hero-stage__svg',
          theta: ro.theta,
          title: ro.device + ': ' + stage.rawLabel.toLowerCase()
        }));
        layerRec.appendChild(kit.dial({
          className: 'gv-hero-stage__svg',
          theta: ro.theta,
          overlay: true,
          roi: 'ROI: ' + ro.roi,
          thetaLabel: thetaText,
          valueLabel: valueText,
          title: ro.device + ': ' + stage.recognizedLabel.toLowerCase() + ', ' + thetaText + ', ' + valueText
        }));
        caption.textContent = stage.captionSchematic;
      }
    }

    /* ---------- состояния ---------- */

    function setState(next, animate, announce) {
      if (next === state) return;
      state = next;
      var recognized = next === 'recognized';
      if (cancelScan) { cancelScan(); cancelScan = null; }
      if (animate && !u.prefersReducedMotion()) {
        rootEl.classList.add('is-scanning');
        cancelScan = sc.timeout(function () {
          rootEl.classList.remove('is-scanning');
          cancelScan = null;
        }, SCAN_MS + 40);
      } else {
        rootEl.classList.remove('is-scanning');
      }
      rootEl.setAttribute('data-state', next);
      layerRaw.setAttribute('aria-hidden', recognized ? 'true' : 'false');
      layerRec.setAttribute('aria-hidden', recognized ? 'false' : 'true');
      if (roving.index() !== (recognized ? 1 : 0)) roving.select(recognized ? 1 : 0);
      if (announce) {
        live.textContent = T.live + (recognized ? stage.recognizedLabel + '. ' + valueText + ', ' + thetaText : stage.rawLabel);
      }
    }

    var ready = false;
    var roving = u.rovingTabs(toggle, {
      selector: '.gv-hero-stage__mode',
      attr: 'aria-pressed',
      onSelect: function (i) {
        if (!ready) return;
        touched = true;
        setState(i === 1 ? 'recognized' : 'raw', true, true);
      }
    });
    sc.add(roving.destroy);
    ready = true;

    renderMedia();
    layerRaw.setAttribute('aria-hidden', 'false');
    kit.onTweaks(sc, renderMedia);

    /* Один раз показываем распознавание сами, если посетитель ещё не трогал переключатель. */
    if (!u.prefersReducedMotion()) {
      sc.observe(u.onVisible(rootEl, function () {
        sc.timeout(function () {
          if (!touched && state === 'raw') setState('recognized', true, false);
        }, AUTOPLAY_MS);
      }, { once: true, threshold: 0.5 }));
    }

    return {
      destroy: function () {
        sc.destroy();
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      },
      setState: function (next) { touched = true; setState(next === 'recognized' ? 'recognized' : 'raw', true, true); }
    };
  }

  GV.components.heroStage = { mount: mount, layouts: LAYOUTS.slice() };
})();
