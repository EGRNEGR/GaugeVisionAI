/*
 * GV.app — роутер вариантов и студийная панель. Подключается последним.
 * Вариант: ?v= → localStorage `gv.variant` → 'a' → первый доступный.
 * Варианты регистрировать не нужно: app читает window.GV.variants
 * ({ id, label, render(root) → cleanup }). Кнопка показывается только у существующего варианта.
 * Переключение: cleanup() старого → render() нового → history.replaceState(?v=) →
 * прокрутка к той же секции, что была в зоне видимости. Событие document → 'gv:variant'.
 *
 * API: current() → id | null · switchTo(id) · ids() → ['a', …]
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  var KEY = 'gv.variant';
  var html = document.documentElement;
  var root = document.getElementById('gv-root');
  var studio = document.getElementById('gv-studio');
  var h = GV.util && GV.util.h;
  var current = null;
  var cleanup = null;

  if (!root || !studio || !h) {
    console.error('GV.app: нет #gv-root, #gv-studio или GV.util — проверьте порядок скриптов в index.html');
    return;
  }

  function ids() {
    var variants = GV.variants || {};
    return Object.keys(variants).filter(function (id) {
      return variants[id] && typeof variants[id].render === 'function';
    }).sort();
  }

  function readParam() {
    try {
      return new URLSearchParams(window.location.search).get('v');
    } catch (e) {
      return null;
    }
  }

  function readStored() {
    try {
      return window.localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function store(id) {
    try {
      window.localStorage.setItem(KEY, id);
    } catch (e) {
      // без localStorage выбор держится в ?v= адреса — этого достаточно
    }
  }

  function pick(list) {
    var candidates = [readParam(), readStored(), 'a'];
    for (var i = 0; i < candidates.length; i++) {
      if (candidates[i] && list.indexOf(candidates[i]) >= 0) return candidates[i];
    }
    return list[0] || null;
  }

  function writeUrl(id) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('v', id);
      window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
    } catch (e) {
      // file:// в некоторых браузерах запрещает replaceState — вариант всё равно сохранён в localStorage
    }
  }

  /* Секция, которая сейчас занимает верх экрана (под студийной панелью). */
  function sectionInView() {
    if (window.scrollY < 4) return null;
    var line = studio.getBoundingClientRect().bottom + window.innerHeight * 0.25;
    var found = null;
    Array.prototype.forEach.call(root.querySelectorAll('section[id]'), function (section) {
      if (section.getBoundingClientRect().top <= line) found = section.id;
    });
    return found;
  }

  function restorePosition(sectionId) {
    if (!sectionId) {
      window.scrollTo(0, 0);
      return;
    }
    var target = document.getElementById(sectionId);
    if (target && root.contains(target)) target.scrollIntoView({ block: 'start', behavior: 'auto' });
    else window.scrollTo(0, 0);
  }

  function runCleanup() {
    if (typeof cleanup !== 'function') return;
    var fn = cleanup;
    cleanup = null;
    try {
      fn();
    } catch (e) {
      console.error('GV.app: ошибка cleanup варианта «' + current + '»', e);
    }
  }

  function render(id, keepPosition) {
    var sectionId = keepPosition ? sectionInView() : null;
    runCleanup();
    root.textContent = '';
    html.setAttribute('data-variant', id);
    current = id;
    var result;
    try {
      result = GV.variants[id].render(root);
    } catch (e) {
      console.error('GV.app: вариант «' + id + '» не отрисовался', e);
      root.textContent = '';
      renderShell('Вариант «' + id.toUpperCase() + '» не отрисовался. Подробности — в консоли браузера.');
    }
    if (typeof result === 'function') cleanup = result;
    else if (result && typeof result.destroy === 'function') cleanup = function () { result.destroy(); };
    store(id);
    writeUrl(id);
    syncStudio();
    if (keepPosition) restorePosition(sectionId);
    document.dispatchEvent(new CustomEvent('gv:variant', { detail: { id: id } }));
  }

  function switchTo(id) {
    if (id === current || ids().indexOf(id) < 0) return;
    render(id, true);
  }

  /* ---------- Студийная панель ---------- */

  function buttonLabel(id) {
    var label = String(GV.variants[id].label || '').trim();
    var key = id.toUpperCase();
    if (!label) return [h('span', { class: 'gv-studio__key' }, key)];
    if (label.toUpperCase().indexOf(key + ' ') === 0 || label.toUpperCase().indexOf(key + '·') === 0) {
      label = label.slice(key.length).replace(/^\s*·\s*/, '');
    }
    return [h('span', { class: 'gv-studio__key' }, key), ' · ' + label];
  }

  function buildStudio(list) {
    studio.textContent = '';
    studio.appendChild(h('span', { class: 'gv-studio__label', 'aria-hidden': 'true' }, 'Вариант'));
    if (!list.length) {
      studio.appendChild(h('span', { class: 'gv-studio__empty', role: 'status' }, 'Варианты страницы пока не подключены'));
    } else {
      studio.appendChild(h('ul', { class: 'gv-studio__list', role: 'list', 'aria-label': 'Варианты страницы' },
        list.map(function (id) {
          return h('li', { class: 'gv-studio__item' },
            h('button', {
              type: 'button',
              class: 'gv-studio__btn',
              'aria-pressed': 'false',
              'data-variant-id': id,
              on: { click: function () { switchTo(id); } }
            }, buttonLabel(id)));
        })));
    }
    studio.appendChild(h('span', { class: 'gv-studio__note' }, 'GaugeVision AI · студия'));
  }

  function syncStudio() {
    Array.prototype.forEach.call(studio.querySelectorAll('.gv-studio__btn'), function (btn) {
      btn.setAttribute('aria-pressed', btn.getAttribute('data-variant-id') === current ? 'true' : 'false');
    });
  }

  /* ---------- Запасная страница: вариантов нет или вариант упал ---------- */

  function renderShell(note) {
    var c = GV.content;
    if (!c) return;
    var metrics = c.metrics.filter(function (m) { return m.kind === 'measured'; }).slice(0, 3);
    root.appendChild(h('div', { class: 'gv-shell' },
      h('p', { class: 'gv-shell__meta' }, c.meta.name + ' · ' + c.meta.trackShort),
      h('h1', { class: 'gv-shell__title' }, c.hero.title),
      h('p', { class: 'gv-shell__lead' }, c.hero.lead),
      h('a', { class: 'gv-button', href: c.hero.ctaPrimary.href, target: '_blank', rel: 'noopener' }, c.hero.ctaPrimary.label),
      h('dl', { class: 'gv-shell__metrics' },
        metrics.map(function (m) {
          return h('div', { class: 'gv-shell__metric' },
            h('dt', { class: 'gv-shell__cond' }, m.label),
            h('dd', { class: 'gv-shell__value' }, m.display, m.unit ? h('small', null, m.unit) : null),
            h('dd', { class: 'gv-shell__cond' }, m.condition));
        })),
      h('p', { class: 'gv-shell__note' }, note || (c.meta.copyright + '.'))));
  }

  /* ---------- Старт ---------- */

  var list = ids();
  buildStudio(list);
  var initial = pick(list);
  if (initial) {
    render(initial, false);
    if (window.location.hash) {
      var target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
      if (target) target.scrollIntoView({ block: 'start', behavior: 'auto' });
    }
  } else {
    renderShell();
  }

  GV.app = {
    current: function () { return current; },
    switchTo: switchTo,
    ids: ids
  };
})();
