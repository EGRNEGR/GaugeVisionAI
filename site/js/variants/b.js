/*
 * GV.variants.b — «Циферблат»: прибор как сцена.
 * Центрированная композиция по мотивам ref3–5: hero-stage в раскладке dial — круглое окно кадра,
 * вокруг него гигантская дуга шкалы с рисками (шкала GV.content.calibration), оранжевая стрелка
 * стоит на нуле шкалы в режиме «Сырой кадр» и поворачивается на реальный угол θ из readout
 * в режиме «Распознавание». Под дугой — заголовок слева, лид и кнопки справа (ref5).
 * Метрики — крупные контурные цифры (dial), конвейер — риски на дуге (arc), сравнение — toggle,
 * ограничения — cards. Акцент — оранжевая стрелка, шрифты Onest + IBM Plex Mono (tokens.css).
 * Стили — только css/variant-b.css под [data-variant="b"].
 * render(root) → cleanup(): снимает компоненты, наблюдатели и слушатели.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.variants = GV.variants || {};

  /* Семь экранов в порядке брифа. */
  var ORDER = ['hero', 'metrics', 'pipeline', 'compare', 'architecture', 'limits', 'contact'];

  var MOUNTS = {
    metrics: { component: 'metrics', options: { layout: 'dial' } },
    pipeline: { component: 'pipeline', options: { layout: 'arc' } },
    compare: { component: 'compare', options: { layout: 'toggle' } },
    architecture: { component: 'architecture', options: {} },
    limits: { component: 'limits', options: { layout: 'cards' } }
  };

  var T = {
    nav: 'Разделы страницы',
    home: 'GaugeVision AI — к началу страницы',
    github: 'GitHub',
    contactLinks: 'Ссылки проекта',
    track: 'Хакатон',
    license: 'Лицензия',
    newTab: ' (откроется в новой вкладке)'
  };

  var SVG_NS = 'http://www.w3.org/2000/svg';

  function render(root) {
    var u = GV.util;
    var kit = GV.kit;
    var h = u.h;
    var s = u.svg;
    var c = GV.content;
    var fmt = u.formatNumber;
    var NBSP = kit.NBSP;
    var cal = c.calibration;
    var ro = c.hero.stage.readout;
    var sc = kit.scope();
    var instances = [];
    var sections = {};
    c.sections.forEach(function (sec) { sections[sec.id] = sec; });

    function brandMark() {
      return s('svg', { class: 'gvb-brand__mark', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
        s('path', { class: 'gvb-brand__arc', d: kit.arcPath(12, 12, 9.5, 135, 45) }),
        s('line', { class: 'gvb-brand__needle', x1: 12, y1: 12, x2: 13.2, y2: 3.8 }),
        s('circle', { class: 'gvb-brand__hub', cx: 12, cy: 12, r: 2.2 }));
    }

    /* Заголовок секции: крупный контурный номер за названием (как «26» на ref4). */
    function sectionHead(id) {
      var sec = sections[id];
      return h('header', { class: 'gvb-head' },
        h('span', { class: 'gvb-head__index', 'aria-hidden': 'true' }, sec.index),
        h('h2', { class: 'gvb-head__title', id: 'gvb-' + id + '-title' }, sec.title),
        sec.lead ? h('p', { class: 'gvb-head__lead' }, sec.lead) : null);
    }

    /* ---------- header ---------- */

    var navLinks = {};
    var header = h('header', { class: 'gvb-header' },
      h('div', { class: 'gv-container gvb-header__inner' },
        h('a', { class: 'gvb-brand', href: '#hero', 'aria-label': T.home }, brandMark(),
          h('span', { class: 'gvb-brand__name' }, c.meta.name)),
        h('nav', { class: 'gvb-nav', 'aria-label': T.nav },
          h('ul', { class: 'gvb-nav__list', role: 'list' }, ORDER.map(function (id) {
            var a = h('a', { class: 'gvb-nav__link', href: '#' + id }, sections[id].nav);
            navLinks[id] = a;
            return h('li', null, a);
          }))),
        kit.extLink({ class: 'gvb-header__cta', href: c.meta.repoUrl, 'aria-label': c.hero.ctaPrimary.label + T.newTab },
          kit.icon('github'), h('span', null, T.github))));

    /* ---------- 01 hero: дуга шкалы вокруг окна кадра ---------- */

    var arcSvg = document.createElementNS(SVG_NS, 'svg');
    arcSvg.setAttribute('class', 'gvb-arc');
    arcSvg.setAttribute('aria-hidden', 'true');
    arcSvg.setAttribute('focusable', 'false');
    var arcScale = s('g', { class: 'gvb-arc__scale' });
    var needle = s('g', { class: 'gvb-arc__needle' });
    var needleLine = s('line', { class: 'gvb-arc__needle-line', x1: 0, y1: 0, x2: 0, y2: 0 });
    var needleTail = s('line', { class: 'gvb-arc__needle-tail', x1: 0, y1: 0, x2: 0, y2: 0 });
    needle.appendChild(needleTail);
    needle.appendChild(needleLine);
    var ring = s('circle', { class: 'gvb-arc__ring', cx: 0, cy: 0, r: 0 });
    var thetaLabel = s('text', { class: 'gvb-arc__theta', x: 0, y: 0, 'text-anchor': 'middle' },
      'θ' + NBSP + '=' + NBSP + fmt(ro.theta, 1) + '°');
    var pivot = s('g', { class: 'gvb-arc__pivot' }, ring, needle, thetaLabel);
    arcSvg.appendChild(arcScale);
    arcSvg.appendChild(pivot);

    var stageHost = h('div', { class: 'gvb-hero__stage' });
    var gauge = h('div', { class: 'gvb-hero__gauge' }, arcSvg, stageHost);

    var hero = h('section', { id: 'hero', class: 'gvb-hero', 'aria-labelledby': 'gvb-hero-title' },
      h('div', { class: 'gv-container gvb-hero__grid' },
        h('div', { class: 'gvb-hero__title-col' },
          h('h1', { class: 'gvb-hero__title', id: 'gvb-hero-title' }, c.hero.title)),
        h('div', { class: 'gvb-hero__copy' },
          h('p', { class: 'gvb-hero__lead' }, c.hero.lead),
          h('div', { class: 'gvb-hero__actions' },
            kit.extLink({ class: 'gvb-button gvb-button--primary', href: c.hero.ctaPrimary.href },
              kit.icon('github'), c.hero.ctaPrimary.label),
            kit.demoLink(c.hero.ctaSecondary.label, 'gvb-button gvb-button--ghost')),
          h('p', { class: 'gvb-hero__meta' },
            h('span', null, c.meta.trackShort),
            h('span', null, c.labels.license))),
        gauge));

    /* ---------- 02–06: секции с компонентами ---------- */

    var bodies = {};
    function section(id) {
      var body = h('div', { class: 'gvb-section__body' });
      bodies[id] = body;
      return h('section', { id: id, class: 'gvb-section gvb-section--' + id, 'aria-labelledby': 'gvb-' + id + '-title' },
        h('div', { class: 'gv-container' }, sectionHead(id), body));
    }

    /* ---------- 07 финал ---------- */

    var links = c.contact.links;
    var repo = links.filter(function (l) { return l.primary; })[0] || { label: c.hero.ctaPrimary.label, href: c.meta.repoUrl };
    var others = links.filter(function (l) { return !l.primary; });
    var contact = h('section', { id: 'contact', class: 'gvb-contact', 'aria-labelledby': 'gvb-contact-title' },
      h('div', { class: 'gv-container gvb-contact__inner' },
        sectionHead('contact'),
        h('p', { class: 'gvb-contact__text' }, c.contact.text),
        kit.extLink({ class: 'gvb-contact__repo', href: repo.href },
          kit.icon('github'),
          h('span', { class: 'gvb-contact__repo-label' }, repo.label),
          h('span', { class: 'gvb-contact__repo-url' }, repo.href.replace(/^https?:\/\//, '')),
          kit.icon('external')),
        h('ul', { class: 'gvb-contact__list', role: 'list', 'aria-label': T.contactLinks }, others.map(function (l) {
          return h('li', null, kit.extLink({ class: 'gvb-contact__link', href: l.href },
            h('span', null, l.label), kit.icon('external')));
        })),
        h('dl', { class: 'gvb-contact__meta' },
          h('div', null, h('dt', null, T.track), h('dd', null, c.meta.track)),
          h('div', null, h('dt', null, T.license), h('dd', null, c.meta.copyright)))));

    var footer = h('footer', { class: 'gvb-footer' },
      h('div', { class: 'gv-container gvb-footer__inner' },
        h('p', null, c.meta.copyright + '.'),
        h('p', { class: 'gvb-footer__meta' },
          h('span', null, c.meta.name + ' v' + c.meta.version),
          kit.extLink({ href: c.meta.licenseUrl }, c.labels.license))));

    var page = h('div', { class: 'gvb-page' },
      header,
      h('div', { class: 'gvb-main' },
        hero,
        ORDER.slice(1, -1).map(section),
        contact),
      footer);
    root.appendChild(page);

    /* ---------- монтирование компонентов ---------- */

    instances.push(GV.components.heroStage.mount(stageHost, { layout: 'dial' }));
    ORDER.slice(1, -1).forEach(function (id) {
      var m = MOUNTS[id];
      instances.push(GV.components[m.component].mount(bodies[id], m.options));
    });

    /* ---------- дуга шкалы: геометрия по фактическому окну кадра ---------- */

    var stageEl = stageHost.querySelector('.gv-hero-stage');
    var lastKey = '';

    function remPx() {
      return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    }

    function layoutArc() {
      var vp = stageHost.querySelector('.gv-hero-stage__viewport');
      if (!vp) return;
      var g = gauge.getBoundingClientRect();
      var r = vp.getBoundingClientRect();
      if (!g.width || !r.width) return;
      var rem = remPx();
      var cx = r.left + r.width / 2 - g.left;
      var cy = r.top + r.height / 2 - g.top;
      var face = r.width / 2;
      var vw = document.documentElement.clientWidth;
      var pageCx = r.left + r.width / 2;
      var R = Math.min(cy - 2.25 * rem, pageCx - 0.75 * rem, vw - pageCx - 0.75 * rem);
      var key = [g.width, g.height, cx, cy, face, R].map(function (n) { return Math.round(n); }).join(',');
      if (key === lastKey) return;
      lastKey = key;

      arcSvg.setAttribute('viewBox', '0 0 ' + g.width.toFixed(1) + ' ' + g.height.toFixed(1));
      arcSvg.setAttribute('width', g.width.toFixed(1));
      arcSvg.setAttribute('height', g.height.toFixed(1));
      pivot.setAttribute('transform', 'translate(' + cx.toFixed(1) + ' ' + cy.toFixed(1) + ')');
      ring.setAttribute('r', (face + 0.375 * rem).toFixed(1));

      var room = R - face;
      arcSvg.classList.toggle('is-compact', room < 3.5 * rem);
      while (arcScale.firstChild) arcScale.removeChild(arcScale.firstChild);
      if (room < 2 * rem) {
        arcSvg.classList.add('is-hidden');
        return;
      }
      arcSvg.classList.remove('is-hidden');

      var scaleG = s('g', { transform: 'translate(' + cx.toFixed(1) + ' ' + cy.toFixed(1) + ')' });
      scaleG.appendChild(s('path', { class: 'gvb-arc__line', d: kit.arcPath(0, 0, R, cal.thetaMin, cal.thetaMax) }));
      var steps = 50;
      var range = cal.vMax - cal.vMin;
      var major = Math.min(1.1 * rem, room * 0.22);
      var minor = Math.min(0.6 * rem, room * 0.12);
      var inset = 0.5 * rem;
      for (var k = 0; k <= steps; k++) {
        var v = cal.vMin + (range * k) / steps;
        var a = kit.valueToAngle(v, cal);
        var isMajor = k % 5 === 0;
        var p0 = kit.polar(0, 0, R - inset, a);
        var p1 = kit.polar(0, 0, R - inset - (isMajor ? major : minor), a);
        scaleG.appendChild(s('line', {
          class: isMajor ? 'gvb-arc__tick gvb-arc__tick--major' : 'gvb-arc__tick',
          x1: p0[0].toFixed(1), y1: p0[1].toFixed(1), x2: p1[0].toFixed(1), y2: p1[1].toFixed(1)
        }));
        if (isMajor && k % 10 === 0) {
          var pt = kit.polar(0, 0, R - inset - major - 0.9 * rem, a);
          scaleG.appendChild(s('text', {
            class: 'gvb-arc__num', x: pt[0].toFixed(1), y: pt[1].toFixed(1),
            'text-anchor': 'middle', 'dominant-baseline': 'central'
          }, fmt(v)));
        }
      }
      arcScale.appendChild(scaleG);

      var tipR = R - inset - major - 0.25 * rem;
      needleLine.setAttribute('x1', (face + 0.9 * rem).toFixed(1));
      needleLine.setAttribute('x2', Math.max(face + 1.5 * rem, tipR).toFixed(1));
      needleTail.setAttribute('x1', (face + 0.375 * rem).toFixed(1));
      needleTail.setAttribute('x2', (face + 0.9 * rem).toFixed(1));

      var lp = kit.polar(0, 0, R + 1.1 * rem, ro.theta);
      thetaLabel.setAttribute('x', lp[0].toFixed(1));
      thetaLabel.setAttribute('y', lp[1].toFixed(1));
    }

    /* Стрелка: ноль шкалы в «Сыром кадре», реальный θ в «Распознавании». */
    function syncNeedle() {
      var recognized = stageEl && stageEl.getAttribute('data-state') === 'recognized';
      var angle = recognized ? ro.theta : cal.thetaMin;
      needle.style.transform = 'rotate(' + angle + 'deg)';
      arcSvg.setAttribute('data-state', recognized ? 'recognized' : 'raw');
    }

    syncNeedle();
    layoutArc();
    if (stageEl && 'MutationObserver' in window) {
      var mo = new MutationObserver(syncNeedle);
      mo.observe(stageEl, { attributes: true, attributeFilter: ['data-state'] });
      sc.add(function () { mo.disconnect(); });
    }
    if ('ResizeObserver' in window) {
      var rs = new ResizeObserver(function () { layoutArc(); });
      rs.observe(gauge);
      if (stageEl) rs.observe(stageEl);
      sc.add(function () { rs.disconnect(); });
    }
    sc.on(window, 'resize', layoutArc);
    kit.onTweaks(sc, function () { sc.timeout(function () { lastKey = ''; layoutArc(); }, 60); });
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () { if (page.parentNode) { lastKey = ''; layoutArc(); } });
    }

    /* ---------- навигация: плавный переход и подсветка текущего раздела ---------- */

    sc.on(header, 'click', function (e) {
      var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
      if (!a) return;
      var id = a.getAttribute('href').slice(1);
      var target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: u.prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
      if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      try { target.focus({ preventScroll: true }); } catch (err) { target.focus(); }
    });

    if ('IntersectionObserver' in window) {
      var visible = {};
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
        var current = null;
        ORDER.forEach(function (id) { if (!current && visible[id]) current = id; });
        ORDER.forEach(function (id) {
          if (id === current) navLinks[id].setAttribute('aria-current', 'true');
          else navLinks[id].removeAttribute('aria-current');
        });
      }, { rootMargin: '-35% 0px -55% 0px' });
      ORDER.forEach(function (id) {
        var el = document.getElementById(id);
        if (el) io.observe(el);
      });
      sc.add(function () { io.disconnect(); });
    }

    return function cleanup() {
      sc.destroy();
      while (instances.length) {
        var inst = instances.pop();
        try { inst.destroy(); } catch (e) { console.error('GV.variants.b: ошибка destroy компонента', e); }
      }
      if (page.parentNode) page.parentNode.removeChild(page);
    };
  }

  GV.variants.b = { id: 'b', label: 'Циферблат', render: render };
})();
