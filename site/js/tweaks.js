/*
 * GV.tweaks — плавающая панель настройки внешнего вида (бриф: шрифты, оттенки фона, масштаб, картинки).
 * Состояние { font, bg, scale, media } хранится в localStorage `gv.tweaks` и применяется
 * атрибутами <html>: data-font, data-bg, data-media и переменной --ui-scale.
 * После каждого изменения: document → CustomEvent('gv:tweaks', { detail: state }).
 * Подключается раньше app.js и применяет состояние синхронно, до первого рендера варианта.
 *
 * API: get() → копия состояния · set(partial) · reset() · open() · close() · defaults · options
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  var html = document.documentElement;
  var KEY = 'gv.tweaks';
  var NBSP = '\u00A0';

  var DEFAULTS = { font: 'auto', bg: 'graphite', scale: 1, media: 'shots' };

  var OPTIONS = {
    font: [
      { value: 'auto', label: 'По варианту' },
      { value: 'manrope', label: 'Manrope', family: "'Manrope', sans-serif" },
      { value: 'onest', label: 'Onest', family: "'Onest', sans-serif" },
      { value: 'plex', label: 'Plex', family: "'IBM Plex Sans', sans-serif" }
    ],
    bg: [
      { value: 'graphite', label: 'Графит', swatch: '#0E1116' },
      { value: 'anthracite', label: 'Антрацит', swatch: '#131313' },
      { value: 'blue', label: 'Сине-графитовый', swatch: '#0C1424' },
      { value: 'paper', label: 'Бумага', swatch: '#F3F1EA' }
    ],
    scale: [
      { value: 0.9, label: '90' + NBSP + '%' },
      { value: 1, label: '100' + NBSP + '%' },
      { value: 1.1, label: '110' + NBSP + '%' },
      { value: 1.25, label: '125' + NBSP + '%' }
    ],
    media: [
      { value: 'shots', label: 'Скриншоты' },
      { value: 'schematic', label: 'Схема' }
    ]
  };

  var GROUPS = [
    { key: 'font', legend: 'Шрифт', cols: 2 },
    { key: 'bg', legend: 'Фон', cols: 2 },
    { key: 'scale', legend: 'Масштаб', cols: 4 },
    { key: 'media', legend: 'Изображения', cols: 2 }
  ];

  var THEME_COLOR = { graphite: '#0E1116', anthracite: '#131313', blue: '#0C1424', paper: '#F3F1EA' };

  function allowed(key, value) {
    return OPTIONS[key].some(function (o) { return o.value === value; });
  }

  function sanitize(raw) {
    var out = {};
    Object.keys(DEFAULTS).forEach(function (key) {
      var v = raw && raw[key];
      if (key === 'scale' && typeof v === 'string') v = parseFloat(v);
      out[key] = allowed(key, v) ? v : DEFAULTS[key];
    });
    return out;
  }

  function load() {
    try {
      return sanitize(JSON.parse(window.localStorage.getItem(KEY) || '{}'));
    } catch (e) {
      // localStorage недоступен (приватный режим, file:// с запретом) — работаем на значениях по умолчанию
      return sanitize({});
    }
  }

  function save(state) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(state));
    } catch (e) {
      // без localStorage состояние живёт до перезагрузки — это ожидаемое поведение, не ошибка
    }
  }

  var state = load();

  function apply(notify) {
    html.setAttribute('data-font', state.font);
    html.setAttribute('data-bg', state.bg);
    html.setAttribute('data-media', state.media);
    html.style.setProperty('--ui-scale', String(state.scale));
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', THEME_COLOR[state.bg]);
    if (notify) document.dispatchEvent(new CustomEvent('gv:tweaks', { detail: get() }));
  }

  function get() {
    return { font: state.font, bg: state.bg, scale: state.scale, media: state.media };
  }

  function set(partial) {
    var next = sanitize(Object.assign(get(), partial || {}));
    var changed = Object.keys(next).some(function (k) { return next[k] !== state[k]; });
    state = next;
    if (!changed) return get();
    save(state);
    apply(true);
    syncControls();
    return get();
  }

  function reset() {
    state = sanitize({});
    try {
      window.localStorage.removeItem(KEY);
    } catch (e) {
      // см. save(): без localStorage сброс действует до перезагрузки
    }
    apply(true);
    syncControls();
    return get();
  }

  // Применяем сразу, синхронно: до первого рендера варианта в app.js.
  apply(true);

  /* ---------- Панель ---------- */

  var refs = { toggle: null, panel: null, form: null };

  function icon(paths) {
    var u = GV.util;
    return u.svg('svg', { viewBox: '0 0 20 20', width: '20', height: '20', 'aria-hidden': 'true', focusable: 'false', class: 'gv-tweaks__icon' },
      paths.map(function (d) { return u.svg('path', { d: d }); }));
  }

  function build() {
    var mount = document.getElementById('gv-tweaks');
    if (!mount || !GV.util) return;
    var h = GV.util.h;
    var panelId = 'gv-tweaks-panel';
    var titleId = 'gv-tweaks-title';

    refs.toggle = h('button', {
      type: 'button',
      class: 'gv-tweaks__toggle',
      'aria-expanded': 'false',
      'aria-controls': panelId,
      on: { click: function () { if (refs.panel.hidden) open(); else close(); } }
    }, icon(['M3 6h8', 'M15 6h2', 'M3 14h2', 'M9 14h8', 'M13 4v4', 'M7 12v4']), h('span', null, 'Tweaks'));

    refs.form = h('form', { class: 'gv-tweaks__form', on: { change: onChange, submit: function (e) { e.preventDefault(); } } },
      GROUPS.map(function (group) {
        return h('fieldset', { class: 'gv-tweaks__group' },
          h('legend', { class: 'gv-tweaks__legend' }, group.legend),
          h('div', { class: 'gv-tweaks__options', style: { '--cols': String(group.cols) } },
            OPTIONS[group.key].map(function (opt) {
              return h('label', { class: 'gv-tweaks__opt' },
                h('input', {
                  type: 'radio',
                  name: 'gv-tweaks-' + group.key,
                  value: String(opt.value),
                  class: 'gv-tweaks__radio',
                  checked: state[group.key] === opt.value
                }),
                h('span', { class: 'gv-tweaks__chip', style: opt.family ? { fontFamily: opt.family } : null },
                  opt.swatch ? h('i', { class: 'gv-tweaks__swatch', style: { background: opt.swatch }, 'aria-hidden': 'true' }) : null,
                  opt.label));
            })));
      }),
      h('div', { class: 'gv-tweaks__footer' },
        h('button', { type: 'button', class: 'gv-tweaks__reset', on: { click: function () { reset(); } } }, 'Сбросить'),
        h('span', { class: 'gv-tweaks__hint' }, 'Esc — закрыть')));

    refs.panel = h('section', {
      id: panelId,
      class: 'gv-tweaks__panel',
      role: 'dialog',
      'aria-modal': 'false',
      'aria-labelledby': titleId,
      hidden: true
    },
      h('div', { class: 'gv-tweaks__head' },
        h('h2', { id: titleId, class: 'gv-tweaks__title' }, 'Tweaks'),
        h('button', {
          type: 'button',
          class: 'gv-tweaks__close',
          'aria-label': 'Закрыть панель Tweaks',
          on: { click: function () { close(); } }
        }, icon(['M5 5l10 10', 'M15 5L5 15']))),
      refs.form);

    mount.appendChild(refs.panel);
    mount.appendChild(refs.toggle);
    document.addEventListener('keydown', onKeydown);
  }

  function onChange(e) {
    var input = e.target;
    if (!input || input.type !== 'radio') return;
    var key = input.name.replace('gv-tweaks-', '');
    var value = key === 'scale' ? parseFloat(input.value) : input.value;
    var patch = {};
    patch[key] = value;
    set(patch);
  }

  function syncControls() {
    if (!refs.form) return;
    GROUPS.forEach(function (group) {
      var inputs = refs.form.querySelectorAll('input[name="gv-tweaks-' + group.key + '"]');
      Array.prototype.forEach.call(inputs, function (input) {
        var value = group.key === 'scale' ? parseFloat(input.value) : input.value;
        input.checked = value === state[group.key];
      });
    });
  }

  function open() {
    if (!refs.panel) return;
    refs.panel.hidden = false;
    refs.toggle.setAttribute('aria-expanded', 'true');
    var first = refs.form.querySelector('input:checked') || refs.form.querySelector('input');
    if (first) first.focus();
  }

  function close() {
    if (!refs.panel || refs.panel.hidden) return;
    refs.panel.hidden = true;
    refs.toggle.setAttribute('aria-expanded', 'false');
    refs.toggle.focus();
  }

  function onKeydown(e) {
    if (e.key === 'Escape' && refs.panel && !refs.panel.hidden) {
      e.preventDefault();
      close();
    }
  }

  build();

  GV.tweaks = {
    get: get,
    set: set,
    reset: reset,
    open: open,
    close: close,
    defaults: Object.freeze(Object.assign({}, DEFAULTS)),
    options: OPTIONS
  };
})();
