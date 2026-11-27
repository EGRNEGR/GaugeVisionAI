/*
 * GV.motion — общий двигатель движения страницы. Классический скрипт, подключается после util.js.
 * Один rAF-цикл на всю страницу: он спит, пока нет подписчиков кадра и непрочитанной прокрутки.
 * Геометрия (measure) кэшируется и сбрасывается на resize и при изменении высоты документа,
 * в кадре getBoundingClientRect не читается. Двигаются только transform и opacity.
 *
 *   reduced() → bool                              prefers-reduced-motion: reduce
 *   onFrame(fn(dt, now)) → off                    dt в секундах, не больше 1/20
 *   onScroll(fn(scrollY)) → off                   пассивный scroll + resize, не чаще кадра
 *   measure(el) → { top, height }                 документные координаты, кэш до resize
 *   viewport() → { width, height }                размер окна, кэш до resize
 *   pinProgress(sectionEl) → 0..1                 0 — верх секции у верха экрана, 1 — низ секции у низа
 *   spring({ stiffness, damping, mass, value, precision }) → { target(v), set(v), step(dt), value(), settled() }
 *   reveal(rootEl, selector = '[data-reveal]') → off       каскад по словам или элементам, шаг 60 мс, один раз
 *   counter(el, { to, from, digits, display, duration, format }) → off   докрутка до display при появлении
 *   spotlight(rootEl, selector) → off             пятно света по ободку карточки за курсором (transform)
 *   cursorLight(lightEl) → off                    светлое пятно фона за курсором (transform), только мышь
 *   magnet(el, { pull, max }) → off               кнопка тянется к курсору (доля pull, не дальше max rem), только мышь
 *   shiftBelow(el, change, scopeEl)               change() меняет высоту el, всё ниже доезжает по transform
 *
 * При reduced(): pinProgress → 1, spring.step → цель, reveal и counter сразу ставят конечное состояние.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});

  var MAX_DT = 1 / 20;
  var SUB_DT = 1 / 120;
  var STAGGER_MS = 60;
  var STAGGER_CAP = 10;

  var reducedQuery = typeof root.matchMedia === 'function' ? root.matchMedia('(prefers-reduced-motion: reduce)') : null;

  function reduced() {
    return !!(reducedQuery && reducedQuery.matches);
  }

  function clamp01(v) {
    return v < 0 ? 0 : (v > 1 ? 1 : v);
  }

  /*
   * Пружина: полунеявный Эйлер с подшагом ≤ 1/120 с — устойчива и при длинном кадре.
   * Единицы любые (градусы стрелки, доли прогресса); precision — порог «успокоилась».
   */
  function spring(opts) {
    opts = opts || {};
    var k = opts.stiffness === undefined ? 170 : opts.stiffness;
    var c = opts.damping === undefined ? 18 : opts.damping;
    var m = opts.mass === undefined ? 1 : opts.mass;
    var eps = opts.precision === undefined ? 0.01 : opts.precision;
    var x = opts.value === undefined ? 0 : opts.value;
    var goal = x;
    var v = 0;

    function settled() {
      return Math.abs(goal - x) <= eps && Math.abs(v) <= eps * 10;
    }

    return {
      target: function (next) { goal = next; return this; },
      set: function (next) { x = next; goal = next; v = 0; return this; },
      step: function (dt) {
        if (reduced()) { x = goal; v = 0; return x; }
        var left = Math.min(Math.max(dt || 0, 0), MAX_DT);
        while (left > 1e-9) {
          var h = Math.min(SUB_DT, left);
          v += ((-k * (x - goal) - c * v) / m) * h;
          x += v * h;
          left -= h;
        }
        if (settled()) { x = goal; v = 0; }
        return x;
      },
      value: function () { return x; },
      settled: settled
    };
  }

  var motion = {
    reduced: reduced,
    spring: spring,
    pinProgress: function () { return reduced() ? 1 : 0; }
  };
  GV.motion = motion;

  if (typeof document === 'undefined' || typeof root.requestAnimationFrame !== 'function') return;

  /* ---------- Кадр и прокрутка ---------- */

  var frameSubs = [];
  var scrollSubs = [];
  var running = false;
  var last = 0;
  var scrollDirty = true;
  var scrollY = root.pageYOffset || 0;
  var listening = false;

  // Ошибка одного подписчика не должна останавливать цикл всей страницы:
  // она уходит в консоль, остальные подписчики кадра выполняются, следующий кадр планируется.
  function each(list, a, b) {
    list.slice().forEach(function (fn) {
      try { fn(a, b); } catch (err) { root.console.error('GV.motion: подписчик упал', err); }
    });
  }

  function tick(now) {
    var dt = last ? Math.min((now - last) / 1000, MAX_DT) : 1 / 60;
    last = now;
    if (scrollDirty) {
      scrollDirty = false;
      scrollY = root.pageYOffset || 0;
      each(scrollSubs, scrollY);
    }
    each(frameSubs, dt, now);
    if (frameSubs.length || scrollDirty) {
      root.requestAnimationFrame(tick);
    } else {
      running = false;
      last = 0;
    }
  }

  function wake() {
    if (running) return;
    running = true;
    root.requestAnimationFrame(tick);
  }

  function remove(list, fn) {
    return function off() {
      var i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
    };
  }

  function onFrame(fn) {
    frameSubs.push(fn);
    wake();
    return remove(frameSubs, fn);
  }

  function onScroll(fn) {
    listen();
    scrollSubs.push(fn);
    scrollDirty = true;
    wake();
    return remove(scrollSubs, fn);
  }

  /* ---------- Геометрия: кэш до resize ---------- */

  var geometry = new WeakMap();
  var view = null;

  function invalidate() {
    geometry = new WeakMap();
    view = null;
    scrollDirty = true;
    wake();
  }

  function listen() {
    if (listening) return;
    listening = true;
    root.addEventListener('scroll', function () { scrollDirty = true; wake(); }, { passive: true });
    root.addEventListener('resize', invalidate, { passive: true });
    root.addEventListener('orientationchange', invalidate, { passive: true });
    document.addEventListener('gv:tweaks', invalidate);
    // Высота документа меняется при загрузке шрифтов, видео и монтировании модулей
    if ('ResizeObserver' in root && document.body) {
      new root.ResizeObserver(invalidate).observe(document.body);
    }
  }

  function viewport() {
    if (!view) view = { width: document.documentElement.clientWidth, height: root.innerHeight };
    return view;
  }

  function measure(el) {
    listen();
    var hit = geometry.get(el);
    if (hit) return hit;
    var r = el.getBoundingClientRect();
    hit = { top: r.top + (root.pageYOffset || 0), height: r.height };
    geometry.set(el, hit);
    return hit;
  }

  function pinProgress(el) {
    if (reduced()) return 1;
    if (!el || typeof el.getBoundingClientRect !== 'function') return 0;
    var m = measure(el);
    var range = m.height - viewport().height;
    if (range <= 0) return scrollY >= m.top ? 1 : 0;
    return clamp01((scrollY - m.top) / range);
  }

  /* ---------- Появление заголовков и блоков ---------- */

  function splitWords(el) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    var i = 0;
    nodes.forEach(function (node) {
      var parts = node.nodeValue.split(/( +)/);
      var frag = document.createDocumentFragment();
      parts.forEach(function (part) {
        if (!part) return;
        if (/^ +$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
        var w = document.createElement('span');
        w.className = 'gv-reveal__w';
        w.style.setProperty('--i', String(Math.min(i, STAGGER_CAP * 2)));
        w.textContent = part;
        frag.appendChild(w);
        i += 1;
      });
      node.parentNode.replaceChild(frag, node);
    });
  }

  function reveal(rootEl, selector) {
    if (!rootEl) return function () {};
    selector = selector || '[data-reveal]';
    var els = Array.prototype.slice.call(rootEl.querySelectorAll(selector));
    if (rootEl.matches && rootEl.matches(selector)) els.unshift(rootEl);
    els = els.filter(function (el) { return !el.classList.contains('gv-reveal'); });
    var still = reduced() || !('IntersectionObserver' in root);
    els.forEach(function (el) {
      if (!still && el.getAttribute('data-reveal') === 'words') splitWords(el);
      el.classList.add('gv-reveal');
      if (still) el.classList.add('is-in');
    });
    if (still || !els.length) return function () {};

    var io = new root.IntersectionObserver(function (entries) {
      var batch = entries.filter(function (e) { return e.isIntersecting; }).map(function (e) { return e.target; });
      batch.forEach(function (el, i) {
        el.style.setProperty('--gv-reveal-delay', Math.min(i, STAGGER_CAP) * STAGGER_MS + 'ms');
        el.classList.add('is-in');
        io.unobserve(el);
      });
    }, { threshold: 0.2, rootMargin: '0px 0px -8% 0px' });
    els.forEach(function (el) { io.observe(el); });
    return function off() {
      io.disconnect();
      els.forEach(function (el) { el.classList.add('is-in'); });
    };
  }

  /* ---------- Счётчик ---------- */

  function counter(el, opts) {
    opts = opts || {};
    if (!el) return function () {};
    var fmt = (GV.util && GV.util.formatNumber) || function (n) { return String(n); };
    var digits = opts.digits === undefined ? 0 : opts.digits;
    var from = opts.from === undefined ? 0 : opts.from;
    var to = Number(opts.to);
    var format = typeof opts.format === 'function' ? opts.format : function (v) { return fmt(v, digits); };
    var finalText = opts.display !== undefined ? String(opts.display) : format(to);
    var duration = opts.duration === undefined ? 1200 : opts.duration;

    if (reduced() || !('IntersectionObserver' in root) || !isFinite(to)) {
      el.textContent = finalText;
      return function () {};
    }

    var offFrame = null;
    var done = false;
    el.textContent = format(from);
    function finish() {
      done = true;
      if (offFrame) { offFrame(); offFrame = null; }
      el.textContent = finalText;
    }
    var io = new root.IntersectionObserver(function (entries) {
      if (done || !entries.some(function (e) { return e.isIntersecting; })) return;
      io.disconnect();
      var t = 0;
      offFrame = onFrame(function (dt) {
        t = Math.min(1, t + (dt * 1000) / duration);
        var eased = 1 - Math.pow(1 - t, 3);
        if (t >= 1) finish();
        else el.textContent = format(from + (to - from) * eased);
      });
    }, { threshold: 0.4 });
    io.observe(el);
    return function off() {
      io.disconnect();
      finish();
    };
  }

  /* ---------- Пятно света по ободку ---------- */

  var finePointer = typeof root.matchMedia === 'function' ? root.matchMedia('(hover: hover) and (pointer: fine)') : null;

  function spotlight(rootEl, selector) {
    if (!rootEl || !selector) return function () {};
    var cards = Array.prototype.slice.call(rootEl.querySelectorAll(selector));
    cards.forEach(function (card) {
      if (card.querySelector(':scope > .gv-spot')) return;
      var layer = document.createElement('span');
      layer.className = 'gv-spot';
      layer.setAttribute('aria-hidden', 'true');
      var light = document.createElement('span');
      light.className = 'gv-spot__light';
      layer.appendChild(light);
      card.classList.add('gv-spot-host');
      card.insertBefore(layer, card.firstChild);
    });
    if (finePointer && !finePointer.matches) return function () {};

    var lit = null;
    var pending = null;
    var offFrame = null;

    function paint() {
      if (pending) {
        var light = pending.card.querySelector(':scope > .gv-spot > .gv-spot__light');
        if (light) light.style.transform = 'translate3d(' + pending.x.toFixed(1) + 'px,' + pending.y.toFixed(1) + 'px,0)';
        pending = null;
      }
      if (offFrame) { offFrame(); offFrame = null; }
    }
    function dim() {
      if (lit) lit.classList.remove('is-lit');
      lit = null;
    }
    function onMove(e) {
      var card = e.target && e.target.closest ? e.target.closest(selector) : null;
      if (!card || !rootEl.contains(card)) { dim(); return; }
      if (card !== lit) { dim(); lit = card; card.classList.add('is-lit'); }
      // Положение карточки читается в событии, а не из кэша measure: карточка может ехать transform
      // (трек конвейера) без resize, и документные координаты из кэша устаревают.
      var box = card.getBoundingClientRect();
      pending = { card: card, x: e.clientX - box.left, y: e.clientY - box.top };
      if (!offFrame) offFrame = onFrame(paint);
    }
    rootEl.addEventListener('pointermove', onMove, { passive: true });
    rootEl.addEventListener('pointerleave', dim, { passive: true });
    return function off() {
      rootEl.removeEventListener('pointermove', onMove);
      rootEl.removeEventListener('pointerleave', dim);
      if (offFrame) offFrame();
      dim();
    };
  }

  /* ---------- Свет фона за курсором ---------- */

  /*
   * lightEl лежит в неподвижном слое на весь экран, поэтому координаты — прямо clientX/clientY.
   * Пятно догоняет курсор с коротким затуханием (при reduced() — встаёт сразу); слой получает is-lit,
   * пока мышь над окном. Палец и стилус без наведения пятна не зажигают.
   * Вложенный слой пятна (первый ребёнок) едет навстречу и стоит на месте относительно экрана:
   * пятно его не тащит, а проявляет — так фон «Чертёж» светит сеткой под курсором.
   */
  function cursorLight(lightEl) {
    var host = lightEl && lightEl.parentNode;
    if (!host || (finePointer && !finePointer.matches)) return function () {};
    var inner = lightEl.firstElementChild;
    var x = 0;
    var y = 0;
    var tx = 0;
    var ty = 0;
    var placed = false;
    var offFrame = null;

    function place() {
      lightEl.style.transform = 'translate3d(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px,0)';
      if (inner) inner.style.transform = 'translate3d(' + (-x).toFixed(1) + 'px,' + (-y).toFixed(1) + 'px,0)';
    }
    function paint(dt) {
      var k = reduced() ? 1 : 1 - Math.exp(-dt * 14);
      x += (tx - x) * k;
      y += (ty - y) * k;
      if (Math.abs(tx - x) < 0.5 && Math.abs(ty - y) < 0.5) {
        x = tx;
        y = ty;
        if (offFrame) { offFrame(); offFrame = null; }
      }
      place();
    }
    function onMove(e) {
      if (e.pointerType === 'touch') return;
      tx = e.clientX;
      ty = e.clientY;
      if (!placed) { x = tx; y = ty; placed = true; place(); }
      host.classList.add('is-lit');
      if (!offFrame) offFrame = onFrame(paint);
    }
    function onOut(e) {
      if (!e.relatedTarget) host.classList.remove('is-lit');
    }
    function onBlur() {
      host.classList.remove('is-lit');
    }
    document.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('pointerout', onOut, { passive: true });
    root.addEventListener('blur', onBlur);
    return function off() {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerout', onOut);
      root.removeEventListener('blur', onBlur);
      if (offFrame) offFrame();
      offFrame = null;
      onBlur();
    };
  }

  /*
   * Раскрытие без скачка: change() меняет высоту el (показывает или прячет блок), а всё, что ниже el
   * до границы scopeEl, стартует со старого места и доезжает на новое по transform (FLIP). Высота
   * не анимируется — сдвиг одинаков для всех следующих соседей el и его предков. Фиксированные слои
   * не трогаются. При reduced() — просто change().
   */
  function shiftBelow(el, change, scopeEl) {
    if (!el) { change(); return; }
    var scope = scopeEl || document.body;
    var targets = [];
    for (var node = el; node && node !== scope && node.parentElement; node = node.parentElement) {
      for (var sib = node.nextElementSibling; sib; sib = sib.nextElementSibling) {
        if (root.getComputedStyle(sib).position !== 'fixed') targets.push(sib);
      }
    }
    var before = el.getBoundingClientRect().bottom;
    change();
    if (reduced() || !targets.length) return;
    var delta = before - el.getBoundingClientRect().bottom;
    if (Math.abs(delta) < 1) return;
    targets.forEach(function (t) {
      t.style.transition = 'none';
      t.style.transform = 'translate3d(0,' + delta.toFixed(1) + 'px,0)';
    });
    void el.offsetHeight; // стартовое положение применено до включения перехода
    targets.forEach(function (t) {
      t.style.transition = 'transform var(--dur-med) var(--ease-out)';
      t.style.transform = '';
    });
    root.setTimeout(function () {
      targets.forEach(function (t) { if (!t.style.transform) t.style.transition = ''; });
    }, 400);
  }

  /* ---------- Магнит ---------- */

  // Смещение — доля pull от расстояния курсора до центра кнопки; CSS собирает из --mx/--my transform.
  // Центр считается без текущего смещения, иначе кнопка убегала бы от собственного сдвига.
  function clampAbs(v, lim) {
    return v > lim ? lim : (v < -lim ? -lim : v);
  }

  function magnet(el, opts) {
    if (!el || reduced() || (finePointer && !finePointer.matches)) return function () {};
    var pull = (opts && opts.pull) || 0.25;
    var maxRem = (opts && opts.max) || 0.5;
    var limit = 8;
    var x = 0;
    var y = 0;
    var tx = 0;
    var ty = 0;
    var offFrame = null;

    function paint(dt) {
      var k = 1 - Math.exp(-dt * 12);
      x += (tx - x) * k;
      y += (ty - y) * k;
      if (Math.abs(tx - x) < 0.1 && Math.abs(ty - y) < 0.1) {
        x = tx;
        y = ty;
        if (offFrame) { offFrame(); offFrame = null; }
      }
      el.style.setProperty('--mx', x.toFixed(2) + 'px');
      el.style.setProperty('--my', y.toFixed(2) + 'px');
    }
    function wake() {
      if (!offFrame) offFrame = onFrame(paint);
    }
    function onMove(e) {
      if (e.pointerType === 'touch') return;
      var box = el.getBoundingClientRect();
      tx = clampAbs((e.clientX - (box.left - x) - box.width / 2) * pull, limit);
      ty = clampAbs((e.clientY - (box.top - y) - box.height / 2) * pull, limit);
      wake();
    }
    function onEnter() {
      limit = maxRem * (parseFloat(root.getComputedStyle(document.documentElement).fontSize) || 16);
    }
    function onLeave() {
      tx = 0;
      ty = 0;
      wake();
    }
    el.addEventListener('pointerenter', onEnter, { passive: true });
    el.addEventListener('pointermove', onMove, { passive: true });
    el.addEventListener('pointerleave', onLeave, { passive: true });
    return function off() {
      el.removeEventListener('pointerenter', onEnter);
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerleave', onLeave);
      if (offFrame) { offFrame(); offFrame = null; }
      el.style.removeProperty('--mx');
      el.style.removeProperty('--my');
    };
  }

  motion.onFrame = onFrame;
  motion.onScroll = onScroll;
  motion.measure = measure;
  motion.viewport = viewport;
  motion.pinProgress = pinProgress;
  motion.reveal = reveal;
  motion.counter = counter;
  motion.spotlight = spotlight;
  motion.cursorLight = cursorLight;
  motion.magnet = magnet;
  motion.shiftBelow = shiftBelow;
})();
