/*
 * GV.tweaks — инструмент автора (ADR 0010): масштаб страницы и сорт бумаги.
 * Посетитель кнопку не видит: адрес с ?tweaks включает её на этом устройстве (запоминается),
 * ?tweaks=off выключает, Shift + T показывает или прячет. Выбор хранится в localStorage gv.tweaks
 * и ставится до первой отрисовки скриптом в <head>; здесь — панель и событие gv:tweaks.
 *
 *   mount(asideEl)
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  var KEY = 'gv.tweaks';
  var SCALES = [0.9, 1, 1.1, 1.25];
  var PAPERS = [['ledger', 'Журнальная'], ['graph', 'Миллиметровка'], ['tracing', 'Калька']];

  function read() {
    try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { return {}; }
  }
  function write(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* приватный режим: только на сессию */ }
  }

  function mount(aside) {
    if (!aside || aside.childNodes.length) return;
    var h = GV.util.h;
    var d = document.documentElement;
    var state = read();
    if (SCALES.indexOf(state.scale) < 0) state.scale = 1;
    if (!PAPERS.some(function (p) { return p[0] === state.paper; })) state.paper = 'ledger';

    function apply() {
      d.style.setProperty('--ui-scale', String(state.scale));
      if (state.paper === 'ledger') d.removeAttribute('data-paper');
      else d.setAttribute('data-paper', state.paper);
      write(state);
      document.dispatchEvent(new CustomEvent('gv:tweaks', { detail: { scale: state.scale, paper: state.paper } }));
    }

    function group(legend, name, options, current, onPick) {
      return h('fieldset', { class: 'gv-tw__group' },
        h('legend', { class: 'gv-label' }, legend),
        h('div', { class: 'gv-tw__opts' }, options.map(function (o) {
          var id = 'gv-tw-' + name + '-' + String(o[0]).replace('.', '');
          var input = h('input', { type: 'radio', name: 'gv-tw-' + name, id: id, value: String(o[0]), class: 'gv-tw__radio' });
          input.checked = String(o[0]) === String(current);
          input.addEventListener('change', function () { onPick(o[0]); });
          return h('label', { class: 'gv-tw__opt', for: id }, input, h('span', null, o[1]));
        })));
    }

    var panelId = 'gv-tw-panel';
    var btn = h('button', { class: 'gv-tw__btn', type: 'button', 'aria-expanded': 'false', 'aria-controls': panelId }, 'Tweaks');
    var panel = h('div', { class: 'gv-tw__panel', id: panelId, hidden: true },
      group('Масштаб', 'scale', SCALES.map(function (v) { return [v, Math.round(v * 100) + ' %']; }), state.scale,
        function (v) { state.scale = v; apply(); }),
      group('Бумага', 'paper', PAPERS, state.paper, function (v) { state.paper = v; apply(); }));

    btn.addEventListener('click', function () {
      var open = btn.getAttribute('aria-expanded') !== 'true';
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      panel.hidden = !open;
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panel.hidden) { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); btn.focus(); return; }
      if (!e.shiftKey || (e.key !== 'T' && e.key !== 'Т')) return;
      var tag = (e.target && e.target.tagName) || '';
      if (/INPUT|TEXTAREA|SELECT/.test(tag)) return;
      if (d.getAttribute('data-tweaks') === 'on') d.removeAttribute('data-tweaks');
      else d.setAttribute('data-tweaks', 'on');
    });

    aside.className = 'gv-tw';
    aside.appendChild(panel);
    aside.appendChild(btn);
  }

  GV.tweaks = { mount: mount };
})();
