/*
 * GV.page — сборщик страницы GaugeVision AI 3.0 в дизайне «Журнал обходчика» (11 листов).
 * Шапка бланка, ярлыки листов у правого края, листы GV.content.sections по порядку, футер,
 * Tweaks и режим демонстрации GV.showcase. API компонентов собирается в GV.api.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  var MOUNTS = {
    hero: 'journal',
    compare: 'shift',
    multigauge: 'multigauge',
    resilience: 'resilience',
    scada: 'scada',
    forecast: 'forecast',
    optimizer: 'optimizer',
    metrics: 'metrics',
    evolution: 'evolution',
    limits: 'limits',
    contact: 'contact'
  };

  function render(root) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var s = u.svg;
    var c = GV.content;
    var L = c.labels;
    var sc = kit.scope();
    var instances = [];
    var api = {};
    GV.api = api;
    var reading = kit.createReading(c.reading.theta);

    /* ---------- шапка бланка ---------- */

    function mark() {
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

    var mast = h('header', { class: 'gv-mast' },
      h('a', { class: 'gv-mast__home', href: '#hero', 'aria-label': L.home }, mark()),
      h('div', { class: 'gv-mast__row' },
        h('span', { class: 'gv-mast__name' }, c.meta.name),
        h('span', { class: 'gv-mast__form' }, c.meta.form),
        h('div', { class: 'gv-mast__acts' },
          h('button', { class: 'gv-mast__demo', type: 'button', 'data-showcase-open': '' }, L.showcase),
          kit.extLink({ class: 'gv-mast__gh', href: c.meta.tagUrl }, kit.icon('github'), h('span', null, 'v3.0.0')))));

    /* ---------- ярлыки листов ---------- */

    var tabLinks = {};
    var tabs = h('nav', { class: 'gv-tabs', 'aria-label': L.nav },
      h('ol', { class: 'gv-tabs__list', role: 'list' }, c.sections.map(function (sec) {
        var a = h('a', { class: 'gv-tab', href: '#' + sec.id },
          h('span', { class: 'gv-tab__no', 'aria-hidden': 'true' }, sec.index),
          h('span', { class: 'gv-tab__label' }, sec.nav));
        a.setAttribute('aria-label', L.sheet + ' ' + sec.index + ': ' + sec.nav);
        tabLinks[sec.id] = a;
        return h('li', null, a);
      })));

    /* ---------- листы ---------- */

    var main = h('main', { id: 'gv-main', class: 'gv-main', tabindex: '-1' });

    c.sections.forEach(function (sec) {
      var headId = 'gv-h-' + sec.id;
      var sheet = h('section', { class: 'gv-sheet gv-sheet--' + sec.id, id: sec.id, 'aria-labelledby': headId });
      var opened = h('time', { class: 'gv-sheet__time' });
      sheet.appendChild(h('div', { class: 'gv-sheet__margin', 'aria-hidden': 'true' },
        h('span', { class: 'gv-sheet__no' }, sec.index),
        h('span', { class: 'gv-sheet__form' }, sec.form),
        opened));
      sc.observe(u.onVisible(sheet, function () {
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
          sec.lede ? h('p', { class: 'gv-lede', 'data-reveal': '' }, kit.marked(sec.lede, sec.accent)) : null));
      }
      var body = h('div', { class: 'gv-sheet__body' });
      sheet.appendChild(body);
      main.appendChild(sheet);

      var name = MOUNTS[sec.id];
      var mod = name && GV.components && GV.components[name];
      if (!mod || typeof mod.mount !== 'function') {
        console.error('GV.page: нет модуля «' + name + '» для листа «' + sec.id + '»');
        return;
      }
      try {
        var inst = mod.mount(body, { section: sec, sheet: sheet, reading: reading, headId: headId });
        if (inst) {
          api[sec.id] = inst;
          if (typeof inst.destroy === 'function') instances.push(inst);
        }
      } catch (err) {
        console.error('GV.page: модуль «' + name + '» упал при монтировании', err);
      }
    });

    /* ---------- футер ---------- */

    var foot = h('footer', { class: 'gv-foot' },
      h('div', { class: 'gv-foot__body' },
        h('p', { class: 'gv-foot__legal' }, c.meta.legal),
        h('div', { class: 'gv-foot__row' },
          h('span', null, c.meta.copyright),
          h('span', null, c.meta.name + ', v' + c.meta.version + ' (' + c.meta.commit + '), ',
            kit.extLink({ href: c.meta.licenseUrl }, 'Лицензия')))));

    root.appendChild(mast);
    root.appendChild(tabs);
    root.appendChild(main);
    root.appendChild(foot);

    kit.sectionNav(sc, {
      container: document,
      links: tabLinks,
      ids: c.sections.map(function (sec) { return sec.id; }),
      rootMargin: '-40% 0px -55% 0px',
      keepLast: true
    });
    sc.observe(motion.reveal(root, '[data-reveal]'));

    GV.showcaseCtl = GV.showcase ? GV.showcase.create(function () { return api; }) : null;

    return function cleanup() {
      instances.forEach(function (i) { i.destroy(); });
      sc.destroy();
    };
  }

  function boot() {
    var root = document.getElementById('gv-root');
    if (!root || !GV.content || !GV.util || !GV.kit) {
      console.error('GV.page: не найдены #gv-root или скрипты content/util/kit');
      return;
    }
    render(root);
    if (GV.tweaks && typeof GV.tweaks.mount === 'function') GV.tweaks.mount(document.getElementById('gv-tweaks'));
  }

  GV.page = { mounts: MOUNTS, render: render };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
