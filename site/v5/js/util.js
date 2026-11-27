/*
 * GV.util — общие хелперы. Без зависимостей, классический скрипт.
 *   formatNumber(n, digits)          → '0,38' (ru-RU, запятая, неразрывный пробел в разрядах)
 *   prefersReducedMotion()           → bool
 *   onVisible(el, cb, {once, threshold, rootMargin}) → unsubscribe; cb(isVisible, entry)
 *   h(tag, attrs, ...children)       → HTMLElement
 *   svg(tag, attrs, ...children)     → SVGElement
 *   rovingTabs(listEl, {onSelect, selector, attr, orientation, initial}) → {select(i), index(), destroy()}
 *   uid(prefix)                      → уникальный id для aria-связок
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var formatters = {};

  function formatNumber(n, digits) {
    if (typeof n !== 'number' || !isFinite(n)) return String(n);
    var key = digits === undefined ? 'auto' : String(digits);
    if (!formatters[key]) {
      formatters[key] = new Intl.NumberFormat('ru-RU', digits === undefined
        ? { maximumFractionDigits: 3 }
        : { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }
    // Intl в ru-RU разделяет разряды неразрывным пробелом; минус — типографский.
    return formatters[key].format(n).replace(/[\u202F\u2009 ]/g, '\u00A0').replace(/^-/, '−');
  }

  var motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  function prefersReducedMotion() {
    return !!(motionQuery && motionQuery.matches);
  }

  function onVisible(el, cb, opts) {
    opts = opts || {};
    if (!el || typeof cb !== 'function') return function () {};
    if (!('IntersectionObserver' in window)) {
      cb(true, null);
      return function () {};
    }
    var done = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (done) return;
        if (opts.once) {
          if (entry.isIntersecting) {
            done = true;
            io.disconnect();
            cb(true, entry);
          }
          return;
        }
        cb(entry.isIntersecting, entry);
      });
    }, { threshold: opts.threshold === undefined ? 0.15 : opts.threshold, rootMargin: opts.rootMargin || '0px' });
    io.observe(el);
    return function unsubscribe() {
      done = true;
      io.disconnect();
    };
  }

  function append(parent, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(parent, c); }); return; }
    parent.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }

  function applyAttrs(el, attrs, isSvg) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === 'on') {
        Object.keys(value).forEach(function (type) { el.addEventListener(type, value[type]); });
      } else if (key === 'html') {
        el.innerHTML = value; // только доверенный контент из GV.content
      } else if (key === 'text') {
        el.textContent = value;
      } else if (key === 'class') {
        el.setAttribute('class', Array.isArray(value) ? value.filter(Boolean).join(' ') : value);
      } else if (key === 'style' && typeof value === 'object') {
        Object.keys(value).forEach(function (prop) {
          if (prop.indexOf('--') === 0) el.style.setProperty(prop, value[prop]);
          else el.style[prop] = value[prop];
        });
      } else if (key === 'dataset') {
        Object.keys(value).forEach(function (d) { el.dataset[d] = value[d]; });
      } else if (value === true) {
        el.setAttribute(key, '');
      } else if (!isSvg && (key === 'value' || key === 'checked' || key === 'disabled') && key in el) {
        el[key] = value;
      } else {
        el.setAttribute(key, String(value));
      }
    });
  }

  function h(tag, attrs) {
    var el = document.createElement(tag);
    applyAttrs(el, attrs, false);
    append(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }

  function svg(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    applyAttrs(el, attrs, true);
    append(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }

  /*
   * Roving tabindex для списка вкладок или переключателей.
   * attr: 'aria-selected' (по умолчанию, role="tab") или 'aria-pressed' (кнопки-переключатели).
   * Стрелки ←/→ (и ↑/↓ при orientation: 'vertical' или 'both'), Home/End; клик выбирает.
   */
  function rovingTabs(listEl, opts) {
    opts = opts || {};
    var selector = opts.selector || '[role="tab"]';
    var attr = opts.attr || 'aria-selected';
    var orientation = opts.orientation || 'horizontal';
    var current = -1;

    function items() {
      return Array.prototype.slice.call(listEl.querySelectorAll(selector));
    }
    function select(i, focus) {
      var list = items();
      if (!list.length) return;
      i = (i + list.length) % list.length;
      list.forEach(function (el, j) {
        el.setAttribute(attr, j === i ? 'true' : 'false');
        el.tabIndex = j === i ? 0 : -1;
      });
      if (focus) list[i].focus();
      var changed = i !== current;
      current = i;
      if (changed && typeof opts.onSelect === 'function') opts.onSelect(i, list[i]);
    }
    function onKey(e) {
      var list = items();
      var i = list.indexOf(document.activeElement);
      if (i < 0) return;
      var next = null;
      var horizontal = orientation !== 'vertical';
      var vertical = orientation !== 'horizontal';
      if ((e.key === 'ArrowRight' && horizontal) || (e.key === 'ArrowDown' && vertical)) next = i + 1;
      else if ((e.key === 'ArrowLeft' && horizontal) || (e.key === 'ArrowUp' && vertical)) next = i - 1;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = list.length - 1;
      if (next === null) return;
      e.preventDefault();
      select(next, true);
    }
    function onClick(e) {
      var list = items();
      var target = e.target.closest ? e.target.closest(selector) : null;
      var i = list.indexOf(target);
      if (i >= 0) select(i, false);
    }

    listEl.addEventListener('keydown', onKey);
    listEl.addEventListener('click', onClick);
    select(opts.initial || 0, false);

    return {
      select: function (i) { select(i, false); },
      index: function () { return current; },
      destroy: function () {
        listEl.removeEventListener('keydown', onKey);
        listEl.removeEventListener('click', onClick);
      }
    };
  }

  var uidCounter = 0;
  function uid(prefix) {
    uidCounter += 1;
    return (prefix || 'gv') + '-' + uidCounter;
  }

  GV.util = {
    formatNumber: formatNumber,
    prefersReducedMotion: prefersReducedMotion,
    onVisible: onVisible,
    h: h,
    svg: svg,
    rovingTabs: rovingTabs,
    uid: uid
  };
})();
