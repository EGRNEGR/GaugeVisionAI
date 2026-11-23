/*
 * GV.tilda — сборщик страницы для Tilda: то же, что site/js/page.js, но листы разнесены по Vibe-блокам.
 * Каждый блок — контейнер <div class="gvt" data-gv-block="<id>"> со своими текстами, стилями и модулем.
 * Этот файл живёт в блоке 02 вместе с kit; общие тексты, util и motion — в блоке 01.
 *
 *   data-gv-block="top"     шапка бланка и ярлыки листов
 *   data-gv-block="<лист>"  лист GV.content.sections: hero, compare, reading, pipeline, metrics, architecture, limits, contact
 *   data-gv-block="foot"    футер
 *   data-gv-block="tweaks"  панель Tweaks (видит только автор)
 *
 *   GV.tilda.boot()  — монтирует все ещё не смонтированные блоки. Блоки зовут его в конце своего скрипта;
 *                      до DOMContentLoaded вызов откладывается, так что на опубликованной странице все блоки
 *                      монтируются одним проходом сверху вниз, как в page.js. В редакторе Tilda блоки
 *                      появляются позже — каждый новый монтируется сразу, навигация пересобирается.
 *
 * Разметка листа, шапки, ярлыков и футера — дословно из page.js. Изменено только то, чего требует Tilda:
 * поиск контейнеров вместо #gv-root и <main>, и режим редактора (анимации сразу в конечном состоянии).
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  var MOUNTS = {
    hero: 'journal',
    compare: 'shift',
    reading: 'precisionDial',
    pipeline: 'operations',
    metrics: 'metrics',
    architecture: 'architecture',
    limits: 'limits',
    contact: 'contact'
  };

  var state = null;

  function editMode() {
    var all = document.getElementById('allrecords');
    return !!(all && all.getAttribute('data-tilda-mode') === 'edit');
  }

  function init() {
    if (state) return state;
    var u = GV.util;
    var kit = GV.kit;
    var c = GV.content;
    if (editMode()) {
      // В редакторе страница не прокручивается как у посетителя: всё сразу в конечном состоянии,
      // стили уровня страницы (масштаб, линовка, красное поле) отключены.
      document.documentElement.classList.remove('gvt-page');
      GV.motion.reduced = function () { return true; };
      u.prefersReducedMotion = function () { return true; };
    }
    state = {
      sc: kit.scope(),
      nav: null,
      tabLinks: {},
      instances: [],
      reading: kit.createReading(c.reading.theta)
    };
    return state;
  }

  /* ---------- шапка бланка ---------- */

  function mark() {
    var kit = GV.kit;
    var s = GV.util.svg;
    var c = GV.content;
    var ticks = [];
    for (var i = 0; i <= 10; i++) {
      var a = 135 + i * 27;
      var p0 = kit.polar(16, 16, 13, a);
      var p1 = kit.polar(16, 16, i % 5 === 0 ? 9.5 : 11, a);
      ticks.push(s('line', { class: 'tick', x1: p0[0].toFixed(2), y1: p0[1].toFixed(2), x2: p1[0].toFixed(2), y2: p1[1].toFixed(2) }));
    }
    var tip = kit.polar(16, 16, 11.5, kit.valueToAngle(4.4, c.calibration));
    return s('svg', { class: 'gv-mast__mark', viewBox: '0 0 32 32', 'aria-hidden': 'true', focusable: 'false' },
      s('path', { class: 'arc', d: kit.arcPath(16, 16, 13, c.calibration.thetaMin, c.calibration.thetaMax) }),
      ticks,
      s('line', { class: 'needle', x1: 16, y1: 16, x2: tip[0].toFixed(2), y2: tip[1].toFixed(2) }),
      s('circle', { class: 'hub', cx: 16, cy: 16, r: 2.2 }));
  }

  function mountTop(box, st) {
    var h = GV.util.h;
    var kit = GV.kit;
    var c = GV.content;
    var L = c.labels;

    var mast = h('header', { class: 'gv-mast' },
      h('a', { class: 'gv-mast__home', href: '#hero', 'aria-label': L.home }, mark()),
      h('div', { class: 'gv-mast__row' },
        h('span', { class: 'gv-mast__name' }, c.meta.name),
        h('span', { class: 'gv-mast__form' }, c.meta.form),
        kit.extLink({ class: 'gv-mast__gh', href: c.meta.repoUrl }, kit.icon('github'), h('span', null, 'GitHub'))));

    /* ярлыки листов */
    var tabs = h('nav', { class: 'gv-tabs', 'aria-label': L.nav },
      h('ol', { class: 'gv-tabs__list', role: 'list' }, c.sections.map(function (sec) {
        var a = h('a', { class: 'gv-tab', href: '#' + sec.id },
          h('span', { class: 'gv-tab__no', 'aria-hidden': 'true' }, sec.index),
          h('span', { class: 'gv-tab__label' }, sec.nav));
        a.setAttribute('aria-label', L.sheet + ' ' + sec.index + ': ' + sec.nav);
        st.tabLinks[sec.id] = a;
        return h('li', null, a);
      })));

    box.appendChild(mast);
    box.appendChild(tabs);
  }

  /* ---------- лист ---------- */

  function mountSheet(box, sec, st) {
    var u = GV.util;
    var h = u.h;
    var kit = GV.kit;
    var headId = 'gv-h-' + sec.id;
    var sheet = h('section', { class: 'gv-sheet gv-sheet--' + sec.id, id: sec.id, 'aria-labelledby': headId });
    var opened = h('time', { class: 'gv-sheet__time' });
    sheet.appendChild(h('div', { class: 'gv-sheet__margin', 'aria-hidden': 'true' },
      h('span', { class: 'gv-sheet__no' }, sec.index),
      h('span', { class: 'gv-sheet__form' }, sec.form),
      opened));
    // время в поле — как у строки журнала: когда посетитель открыл этот лист
    st.sc.observe(u.onVisible(sheet, function () {
      var now = new Date();
      var hh = String(now.getHours()).padStart(2, '0');
      var mm = String(now.getMinutes()).padStart(2, '0');
      opened.textContent = hh + ':' + mm;
      opened.setAttribute('datetime', now.toISOString());
      opened.classList.add('is-written');
    }, { once: true, threshold: 0.15 }));

    if (sec.title) {
      sheet.appendChild(h('div', { class: 'gv-sheet__head' },
        h('h2', { class: 'gv-h2', id: headId, 'data-reveal': 'words' }, sec.title.split('\n').map(function (part, i, all) {
          return all.length > 1 ? h('span', { class: 'gv-h2__l' }, part) : part;
        })),
        // вывод листа: одна фраза под маркером, как в page.js
        sec.lede ? h('p', { class: 'gv-lede', 'data-reveal': '' }, kit.marked(sec.lede, sec.accent)) : null));
    }
    var body = h('div', { class: 'gv-sheet__body' });
    sheet.appendChild(body);
    box.appendChild(sheet);

    var name = MOUNTS[sec.id];
    var mod = name && GV.components && GV.components[name];
    if (!mod || typeof mod.mount !== 'function') {
      console.error('GV.tilda: нет модуля «' + name + '» для листа «' + sec.id + '»');
      return;
    }
    try {
      var inst = mod.mount(body, { section: sec, sheet: sheet, reading: st.reading, headId: headId });
      if (inst && typeof inst.destroy === 'function') st.instances.push(inst);
    } catch (err) {
      console.error('GV.tilda: модуль «' + name + '» упал при монтировании', err);
    }
  }

  /* ---------- футер ---------- */

  function mountFoot(box) {
    var h = GV.util.h;
    var kit = GV.kit;
    var c = GV.content;
    box.appendChild(h('footer', { class: 'gv-foot' },
      h('div', { class: 'gv-foot__body' },
        h('span', null, c.meta.copyright),
        h('span', null, c.meta.trackShort),
        h('span', null, c.meta.name + ' v' + c.meta.version + ', ',
          kit.extLink({ href: c.meta.licenseUrl }, c.contact.links[1].label)))));
  }

  /* ---------- навигация и проявление: по всем блокам страницы ---------- */

  function wire(st, fresh) {
    var kit = GV.kit;
    var c = GV.content;
    if (st.nav) st.nav.destroy();
    st.nav = kit.scope();
    var ids = c.sections.map(function (sec) { return sec.id; }).filter(function (id) {
      return document.getElementById(id);
    });
    kit.sectionNav(st.nav, {
      container: document,
      links: st.tabLinks,
      ids: ids,
      rootMargin: '-40% 0px -55% 0px',
      keepLast: true
    });
    fresh.forEach(function (box) { st.sc.observe(GV.motion.reveal(box, '[data-reveal]')); });
  }

  function mountAll() {
    var c = GV.content;
    if (!c || !GV.util || !GV.kit || !GV.motion) {
      console.error('GV.tilda: нет content, util, motion или kit — блоки 01 и 02 должны стоять первыми');
      return;
    }
    var st = init();
    var boxes = Array.prototype.slice.call(document.querySelectorAll('[data-gv-block]'));
    var fresh = [];
    boxes.forEach(function (box) {
      if (box.getAttribute('data-gv-mounted')) return;
      var id = box.getAttribute('data-gv-block');
      box.setAttribute('data-gv-mounted', '1');
      if (id === 'top') mountTop(box, st);
      else if (id === 'foot') mountFoot(box);
      else if (id === 'tweaks') {
        if (GV.tweaks && typeof GV.tweaks.mount === 'function') GV.tweaks.mount(box.querySelector('#gv-tweaks'));
      } else {
        var sec = c.sections.filter(function (s) { return s.id === id; })[0];
        if (!sec) {
          console.error('GV.tilda: в GV.content.sections нет листа «' + id + '»');
          return;
        }
        mountSheet(box, sec, st);
      }
      fresh.push(box);
    });
    if (fresh.length) wire(st, fresh);
  }

  var queued = false;
  function boot() {
    if (document.readyState === 'loading') {
      if (!queued) {
        queued = true;
        document.addEventListener('DOMContentLoaded', mountAll);
      }
      return;
    }
    mountAll();
  }

  GV.tilda = { mounts: MOUNTS, boot: boot };
})();
