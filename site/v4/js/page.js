/*
 * GV.page — сборка страницы v4: шапка (бренд, навигация, демонстрация, тег v3.0.0) и полоса телеметрии,
 * секции по таблице SECTIONS, финал, футер, фон из Tweaks и режим демонстрации.
 * Секция: заголовок (номер, надзаголовок, h2 с каскадом слов, вводка) + тело — модуль
 * GV.components[name].mount(body, opts) → { destroy, …API }. API модулей собирается в GV.api для
 * режима демонстрации. Модуль не встал — console.error, секция остаётся с заголовком.
 * Подключается последним и строит страницу на DOMContentLoaded.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  /* id секции → модуль, ключ текстов в GV.content, раскладка */
  var SECTIONS = [
    { id: 'hero', comp: 'hero', bleed: true, nav: 'Начало' },
    { id: 'problem', comp: 'problem', key: 'problem', nav: 'Задача' },
    { id: 'story', comp: 'story', key: 'story', bleed: true, pinHead: true, nav: 'Как работает' },
    { id: 'multigauge', comp: 'multigauge', key: 'multigauge', nav: 'Щит' },
    { id: 'resilience', comp: 'resilience', key: 'resilience', nav: 'Надёжность', glow: 'cool' },
    { id: 'scada', comp: 'scada', key: 'scada', nav: 'SCADA' },
    { id: 'diagnostics', comp: 'diagnostics', key: 'diagnostics', nav: 'Диагностика', glow: 'deep' },
    { id: 'forecast', comp: 'forecast', key: 'forecastSection', nav: 'Прогноз' },
    { id: 'optimizer', comp: 'optimizer', key: 'optimizerSection', nav: 'Модернизация', glow: 'cool' },
    { id: 'document', comp: 'document', key: 'documentSection', nav: 'ТЗ' },
    { id: 'evolution', comp: 'evolution', key: 'evolution', nav: 'Эволюция', glow: 'deep' },
    { id: 'economics', comp: 'economics', key: 'economics', nav: 'Экономика' },
    { id: 'evidence', comp: 'evidence', key: 'evidence', nav: 'Доказательства', glow: 'cool' },
    { id: 'readiness', comp: 'readiness', key: 'readiness', nav: 'Готовность' },
    { id: 'final', nav: 'Итог' }
  ];

  function pad(n, len) { var s = String(n); while (s.length < len) s = '0' + s; return s; }

  function render(root) {
    var u = GV.util, kit = GV.kit, motion = GV.motion, h = u.h, s = u.svg, c = GV.content;
    var sc = kit.scope();
    var offs = [], api = {}, sectionEls = [];
    GV.api = api;

    /* ---------- шапка ---------- */
    function brandMark() {
      return s('svg', { class: 'gv-brand__mark', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
        s('path', { class: 'gv-brand__arc', d: kit.arcPath(12, 12, 9.5, 135, 45) }),
        s('line', { class: 'gv-brand__needle', x1: 12, y1: 12, x2: 13.2, y2: 3.8 }),
        s('circle', { class: 'gv-brand__hub', cx: 12, cy: 12, r: 2.2 }));
    }
    var navLinks = {};
    var nav = h('nav', { class: 'gv-nav', 'aria-label': 'Разделы страницы' },
      h('ul', { class: 'gv-nav__list', role: 'list' }, c.nav.map(function (n) {
        var a = h('a', { class: 'gv-nav__link', href: '#' + n.id }, n.label);
        navLinks[n.id] = a;
        return h('li', null, a);
      })));
    var bar = h('span', { class: 'gv-telemetry__bar' });
    var teleLabel = h('span', { class: 'gv-telemetry__label' });
    var teleName = h('span', { class: 'gv-telemetry__name' });
    var header = h('header', { class: 'gv-header' },
      h('div', { class: 'gv-container gv-header__inner' },
        h('a', { class: 'gv-brand', href: '#hero', 'aria-label': 'GaugeVision AI — к началу страницы' }, brandMark(),
          h('span', { class: 'gv-brand__name' }, c.meta.name), h('span', { class: 'gv-brand__ver' }, '3.0')),
        nav,
        h('div', { class: 'gv-header__actions' },
          h('button', { class: 'gv-header__demo', type: 'button', 'data-showcase-open': '' }, h('span', { class: 'gv-header__demo-dot', 'aria-hidden': 'true' }), 'Демо'),
          kit.extLink({ class: 'gv-header__github', href: c.meta.tagUrl }, kit.icon('github'), h('span', null, 'v3.0.0')))),
      h('div', { class: 'gv-telemetry', 'aria-hidden': 'true' },
        h('span', { class: 'gv-telemetry__track' }, bar),
        h('div', { class: 'gv-container gv-telemetry__inner' }, teleLabel, teleName)));

    /* ---------- секции ---------- */
    function head(sec, pinned) {
      var t = c[sec.key];
      if (!t || !t.title) return null;
      return h('header', { class: ['gv-head', pinned ? 'gv-head--pinned' : null] },
        h('p', { class: 'gv-head__meta' }, h('span', { class: 'gv-head__index' }, t.index), h('span', { class: 'gv-head__eyebrow' }, t.eyebrow)),
        h('h2', { class: 'gv-head__title', id: 'gv-' + sec.id + '-title', 'data-reveal': 'words' }, t.title),
        t.lede ? h('p', { class: 'gv-head__lede', 'data-reveal': '' }, t.lede) : null);
    }

    function mountModule(sec, body, opts) {
      var comp = GV.components && GV.components[sec.comp];
      if (!comp || typeof comp.mount !== 'function') {
        console.error('GV.page: нет модуля GV.components.' + sec.comp + ' для секции #' + sec.id);
        return false;
      }
      try {
        api[sec.comp] = comp.mount(body, opts);
        return true;
      } catch (e) {
        console.error('GV.page: модуль ' + sec.comp + ' не смонтировался в #' + sec.id, e);
        body.textContent = '';
        return false;
      }
    }

    var main = h('main', { id: 'gv-main', class: 'gv-main', tabindex: '-1' });
    SECTIONS.forEach(function (sec) {
      if (sec.id === 'final') return;
      var body = h('div', { class: ['gv-section__body', sec.bleed ? null : 'gv-container'] });
      var pinnedHead = sec.pinHead ? head(sec, true) : null;
      var el = h('section', { id: sec.id, class: ['gv-section', 'gv-section--' + sec.id] },
        sec.glow ? h('span', { class: 'gv-glow gv-glow--' + sec.glow, 'aria-hidden': 'true' }) : null,
        (!sec.pinHead && sec.key) ? h('div', { class: 'gv-container gv-section__head' }, head(sec, false)) : null,
        body);
      main.appendChild(el);
      sectionEls.push(el);
      var ok = mountModule(sec, body, pinnedHead ? { head: pinnedHead } : undefined);
      if (!ok && pinnedHead) el.insertBefore(h('div', { class: 'gv-container gv-section__head' }, head(sec, false)), body);
      var heading = el.querySelector('h1, h2');
      if (heading) { if (!heading.id) heading.id = 'gv-' + sec.id + '-title'; el.setAttribute('aria-labelledby', heading.id); }
    });

    /* ---------- финал ---------- */
    var F = c.final;
    var path = h('ol', { class: 'gv-path', role: 'list' }, F.path.map(function (p, i) {
      return h('li', { class: 'gv-path__step', style: { '--i': i } }, h('span', { class: 'gv-path__dot', 'aria-hidden': 'true' }), h('span', { class: 'gv-path__t' }, p));
    }));
    var ctas = h('div', { class: 'gv-final__ctas' }, F.ctas.map(function (cta) {
      if (cta.id === 'showcase') return h('button', { class: 'gv-btn gv-btn--primary gv-btn--l', type: 'button', 'data-showcase-open': '' }, cta.label);
      return kit.extLink({ class: 'gv-btn gv-btn--ghost gv-btn--l', href: c.meta[cta.href] }, cta.label);
    }));
    var finalSec = h('section', { id: 'final', class: 'gv-section gv-section--final', 'aria-labelledby': 'gv-final-title' },
      h('div', { class: 'gv-final__backdrop', 'aria-hidden': 'true' }, h('img', { src: 'assets/img/boiler-hall.jpg', alt: '', loading: 'lazy', decoding: 'async' })),
      h('div', { class: 'gv-container gv-final' },
        path,
        h('h2', { class: 'gv-final__title', id: 'gv-final-title', 'data-reveal': 'words' }, F.title.map(function (t) { return h('span', { class: 'gv-final__line' }, t); })),
        h('p', { class: 'gv-final__line-text', 'data-reveal': '' }, F.line),
        ctas,
        h('p', { class: 'gv-final__refs' }, F.refs.map(function (r) { return kit.extLink({ class: 'gv-src', href: c.meta[r.href] }, r.label); }))));
    main.appendChild(finalSec);
    sectionEls.push(finalSec);
    sc.add(u.onVisible(path, function (vis) { if (vis) path.setAttribute('data-on', ''); }, { once: true, threshold: 0.4 }));

    var footer = h('footer', { class: 'gv-footer' },
      h('div', { class: 'gv-container gv-footer__inner' },
        h('p', { class: 'gv-footer__legal' }, c.meta.legal),
        h('p', { class: 'gv-footer__copy' }, c.meta.copyright + '. ',
          kit.extLink({ href: c.meta.licenseUrl }, 'Лицензия')),
        h('p', { class: 'gv-footer__meta' }, c.meta.name + ' v' + c.meta.version + ', коммит ' + c.meta.commit)));

    /* ---------- фон: градиент, пятно за курсором, сетка «Чертежа», шкала «Шкалы» ---------- */
    var ticks = [];
    for (var i = 0; i <= 50; i++) {
      var a = (135 + i * 5.4) * Math.PI / 180, major = i % 5 === 0, r1 = major ? 80 : 85;
      ticks.push(s('line', { class: ['gv-ambient__tick', major ? 'gv-ambient__tick--major' : null], x1: (Math.cos(a) * r1).toFixed(2), y1: (Math.sin(a) * r1).toFixed(2), x2: (Math.cos(a) * 90).toFixed(2), y2: (Math.sin(a) * 90).toFixed(2) }));
    }
    var needle = s('g', { class: 'gv-ambient__needle' }, s('line', { x1: -12, y1: 0, x2: 76, y2: 0 }), s('circle', { cx: 0, cy: 0, r: 2.5 }));
    var light = h('span', { class: 'gv-ambient__light' }, h('span', { class: 'gv-ambient__grid' }));
    var ambient = h('div', { class: 'gv-ambient', 'aria-hidden': 'true' },
      s('svg', { class: 'gv-ambient__dial', viewBox: '-100 -100 200 200', focusable: 'false' }, s('path', { class: 'gv-ambient__arc', d: kit.arcPath(0, 0, 90, 135, 45) }), ticks, needle),
      light);
    var page = h('div', { class: 'gv-page' }, ambient, header, main, footer);
    root.appendChild(page);

    /* ---------- навигация и телеметрия ---------- */
    kit.sectionNav(sc, { container: header, links: navLinks, ids: c.nav.map(function (n) { return n.id; }), rootMargin: '-35% 0px -55% 0px' });
    var total = pad(SECTIONS.length, 2), lastLabel = '', lastName = '', lastAngle = '';
    offs.push(motion.onScroll(function (y) {
      var vh = motion.viewport().height;
      var doc = motion.measure(page);
      var p = Math.min(1, Math.max(0, y / Math.max(1, doc.top + doc.height - vh)));
      bar.style.transform = 'scaleX(' + p.toFixed(4) + ')';
      var angle = (135 + 270 * p).toFixed(1);
      if (angle !== lastAngle) { needle.style.transform = 'rotate(' + angle + 'deg)'; lastAngle = angle; }
      var idx = 0;
      for (var k = 0; k < sectionEls.length; k++) if (motion.measure(sectionEls[k]).top <= y + vh * 0.4) idx = k;
      var label = pad(idx + 1, 2) + ' / ' + total;
      if (label !== lastLabel) { teleLabel.textContent = label; lastLabel = label; }
      var name = SECTIONS[idx].nav;
      if (name !== lastName) { teleName.textContent = name; lastName = name; }
    }));

    offs.push(motion.reveal(main));
    offs.push(motion.cursorLight(light));

    GV.showcaseCtl = GV.showcase ? GV.showcase.create(function () { return api; }) : null;

    var raw = (window.location.hash || '').slice(1);
    if (raw) {
      var id = null;
      try { id = decodeURIComponent(raw); } catch (e) { id = null; }
      var target = id ? document.getElementById(id) : null;
      if (target && main.contains(target)) setTimeout(function () { target.scrollIntoView({ block: 'start', behavior: 'auto' }); }, 60);
    }

    return function cleanup() {
      sc.destroy();
      offs.forEach(function (off) { off(); });
      Object.keys(api).forEach(function (k) { try { if (api[k] && api[k].destroy) api[k].destroy(); } catch (e) { console.error('GV.page: ошибка destroy', k, e); } });
      if (page.parentNode) page.parentNode.removeChild(page);
    };
  }

  GV.page = { sections: SECTIONS, render: render };

  function boot() {
    var root = document.getElementById('gv-root');
    if (!root || !GV.util || !GV.kit || !GV.motion || !GV.content) {
      console.error('GV.page: нет #gv-root или общих скриптов (content, util, motion, kit)');
      return;
    }
    render(root);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
