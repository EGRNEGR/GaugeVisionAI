/*
 * GV.components.problem — «Приборы уже стоят. Данных от них нет.»
 * mount(el) → { destroy() }
 *
 * Сравнение «Сегодня / С GaugeVision» шторкой: две иллюстрации друг на друге, граница — ползунок
 * (role="slider", ←/→ шаг 5 %, Home/End, перетаскивание мышью и пальцем). Под кадром — два списка;
 * активной считается сторона, которой больше на экране (подсветка списка). Ниже — стоимость одной
 * традиционной замены по каталогу проекта со ссылкой на источник.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit, motion = GV.motion;
    var C = GV.content, P = C.problem;
    var sc = kit.scope();
    var pos = 50;

    var after = h('img', { class: 'gv-cmp__img', src: P.after.img, alt: 'Камера на поручне читает стрелку манометра', loading: 'lazy', decoding: 'async', width: 1280, height: 720 });
    var before = h('img', { class: 'gv-cmp__img', src: P.before.img, alt: 'Обходчик записывает показание манометра в журнал', loading: 'lazy', decoding: 'async', width: 1280, height: 720 });
    var clip = h('div', { class: 'gv-cmp__clip' }, before);
    var handle = h('div', { class: 'gv-cmp__handle', role: 'slider', tabindex: '0', 'aria-label': 'Граница сравнения «Сегодня» и «С GaugeVision»', 'aria-valuemin': '0', 'aria-valuemax': '100' },
      h('span', { class: 'gv-cmp__grip', 'aria-hidden': 'true' }, kit.icon('right')));
    var frame = h('div', { class: 'gv-cmp' }, after, clip, handle,
      h('span', { class: 'gv-cmp__label gv-cmp__label--l' }, P.before.label),
      h('span', { class: 'gv-cmp__label gv-cmp__label--r' }, P.after.label));

    function list(side, cls) {
      return h('div', { class: ['gv-cmp__list', cls] },
        h('p', { class: 'gv-cmp__ltitle' }, side.label),
        h('ul', { role: 'list' }, side.items.map(function (t) { return h('li', null, t); })));
    }
    var lBefore = list(P.before, 'gv-cmp__list--before');
    var lAfter = list(P.after, 'gv-cmp__list--after');
    var srcCat = C.src[P.cost.source];

    el.appendChild(h('div', { class: 'gv-problem' },
      h('figure', { class: 'gv-problem__fig' }, frame, h('figcaption', { class: 'gv-cap' }, h('span', { class: 'gv-chip' }, C.labels.illustrative), ' ', P.imgNote)),
      h('div', { class: 'gv-problem__lists' }, lBefore, lAfter),
      h('div', { class: 'gv-problem__cost', 'data-reveal': '' },
        h('p', { class: 'gv-problem__cost-v' }, P.cost.value, h('span', null, ' ' + P.cost.unit)),
        h('p', { class: 'gv-problem__cost-t' }, P.cost.text, ' ', kit.extLink({ class: 'gv-src', href: srcCat.href }, srcCat.label)))));

    function set(p) {
      pos = Math.max(0, Math.min(100, p));
      clip.style.clipPath = 'inset(0 ' + (100 - pos) + '% 0 0)';
      handle.style.left = pos + '%';
      handle.setAttribute('aria-valuenow', String(Math.round(pos)));
      handle.setAttribute('aria-valuetext', pos < 50 ? 'больше «С GaugeVision»' : 'больше «Сегодня»');
      lBefore.toggleAttribute('data-active', pos >= 50);
      lAfter.toggleAttribute('data-active', pos < 50);
    }

    var dragging = false;
    function fromEvent(e) {
      var r = frame.getBoundingClientRect();
      set(((e.clientX - r.left) / r.width) * 100);
    }
    sc.on(frame, 'pointerdown', function (e) { dragging = true; frame.setPointerCapture(e.pointerId); fromEvent(e); });
    sc.on(frame, 'pointermove', function (e) { if (dragging) fromEvent(e); });
    sc.on(frame, 'pointerup', function () { dragging = false; });
    sc.on(frame, 'pointercancel', function () { dragging = false; });
    sc.on(handle, 'keydown', function (e) {
      var k = e.key;
      if (k === 'ArrowLeft' || k === 'ArrowDown') set(pos - 5);
      else if (k === 'ArrowRight' || k === 'ArrowUp') set(pos + 5);
      else if (k === 'Home') set(0);
      else if (k === 'End') set(100);
      else return;
      e.preventDefault();
    });

    set(72);
    // Первое появление: шторка сама уезжает к «С GaugeVision», показывая смысл жеста
    if (!motion.reduced()) {
      var off = u.onVisible(frame, function (vis) {
        if (!vis) return;
        var t0 = null;
        var stop = motion.onFrame(function (dt, now) {
          t0 = t0 || now;
          var k = Math.min(1, (now - t0) / 1600);
          var e2 = 1 - Math.pow(1 - k, 3);
          if (!dragging) set(72 - 44 * e2);
          if (k >= 1) stop();
        });
      }, { once: true, threshold: 0.5 });
      sc.add(off);
    }

    return { destroy: function () { sc.destroy(); el.textContent = ''; } };
  }

  GV.components.problem = { mount: mount };
})();
