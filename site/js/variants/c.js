/*
 * GV.variants.c — «Протокол»: инженерный даташит по мотивам ref6 и Ref1.
 * Слева липкий индекс секций 01–07 (на узком экране — горизонтальная строка), справа лист:
 * моноширинные метаданные проекта, заголовок, hero-stage в раскладке sheet (кадр и таблица значений),
 * метрики таблицей (table), конвейер вертикальной шкалой с формулами (timeline), сравнение split,
 * ограничения строками протокола (rows). Акцент — холодное серебро, янтарь только у статусов;
 * IBM Plex Sans + IBM Plex Mono (tokens.css). Стили — только css/variant-c.css под [data-variant="c"].
 * render(root) → cleanup(): снимает компоненты, наблюдатели и слушатели.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.variants = GV.variants || {};

  /* Семь экранов в порядке брифа. */
  var ORDER = ['hero', 'metrics', 'pipeline', 'compare', 'architecture', 'limits', 'contact'];

  var MOUNTS = {
    metrics: { component: 'metrics', options: { layout: 'table' } },
    pipeline: { component: 'pipeline', options: { layout: 'timeline' } },
    compare: { component: 'compare', options: { layout: 'split' } },
    architecture: { component: 'architecture', options: {} },
    limits: { component: 'limits', options: { layout: 'rows' } }
  };

  var T = {
    nav: 'Разделы страницы',
    home: 'GaugeVision AI — к началу страницы',
    meta: 'Сведения о проекте',
    project: 'Проект',
    version: 'Версия',
    track: 'Трек',
    author: 'Автор',
    license: 'Лицензия',
    hackathon: 'Хакатон',
    contactLinks: 'Ссылки проекта',
    newTab: ' (откроется в новой вкладке)'
  };

  function render(root) {
    var u = GV.util;
    var kit = GV.kit;
    var h = u.h;
    var s = u.svg;
    var c = GV.content;
    var sc = kit.scope();
    var instances = [];
    var sections = {};
    c.sections.forEach(function (sec) { sections[sec.id] = sec; });
    var licenseShort = c.labels.license.replace(/^[^:]*:\s*/, '');

    function brandMark() {
      return s('svg', { class: 'gvc-brand__mark', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
        s('rect', { class: 'gvc-brand__frame', x: 2.5, y: 2.5, width: 19, height: 19, rx: 1 }),
        s('path', { class: 'gvc-brand__arc', d: kit.arcPath(12, 13, 6.5, 135, 45) }),
        s('line', { class: 'gvc-brand__needle', x1: 12, y1: 13, x2: 15.5, y2: 9 }));
    }

    function sectionHead(id, tag) {
      var sec = sections[id];
      return h('header', { class: 'gvc-head' },
        h('span', { class: 'gvc-head__index', 'aria-hidden': 'true' }, sec.index),
        h(tag || 'h2', { class: 'gvc-head__title', id: 'gvc-' + id + '-title' }, sec.title),
        sec.lead ? h('p', { class: 'gvc-head__lead' }, sec.lead) : null);
    }

    /* ---------- header: липкий индекс 01–07 ---------- */

    var navLinks = {};
    var header = h('header', { class: 'gvc-header' },
      h('div', { class: 'gvc-header__top' },
        h('a', { class: 'gvc-brand', href: '#hero', 'aria-label': T.home }, brandMark(),
          h('span', { class: 'gvc-brand__name' }, c.meta.name)),
        h('p', { class: 'gvc-header__version' }, 'v' + c.meta.version)),
      h('nav', { class: 'gvc-index', 'aria-label': T.nav },
        h('ol', { class: 'gvc-index__list', role: 'list' }, ORDER.map(function (id) {
          var a = h('a', { class: 'gvc-index__link', href: '#' + id },
            h('span', { class: 'gvc-index__num', 'aria-hidden': 'true' }, sections[id].index),
            h('span', { class: 'gvc-index__label' }, sections[id].nav));
          navLinks[id] = a;
          return h('li', { class: 'gvc-index__item' }, a);
        }))),
      kit.extLink({ class: 'gvc-header__cta', href: c.meta.repoUrl, 'aria-label': c.hero.ctaPrimary.label + T.newTab },
        kit.icon('github'), h('span', null, c.hero.ctaPrimary.label), kit.icon('external')));

    /* ---------- 01 hero: лист с метаданными ---------- */

    function metaCell(key, value) {
      return h('div', { class: 'gvc-meta__cell' }, h('dt', null, key), h('dd', null, value));
    }

    var stageHost = h('div', { class: 'gvc-hero__stage' });
    var hero = h('section', { id: 'hero', class: 'gvc-hero', 'aria-labelledby': 'gvc-hero-title' },
      h('dl', { class: 'gvc-meta', 'aria-label': T.meta },
        metaCell(T.project, c.meta.name),
        metaCell(T.version, c.meta.version),
        metaCell(T.track, c.meta.trackShort),
        metaCell(T.author, c.meta.author),
        metaCell(T.license, licenseShort)),
      h('div', { class: 'gvc-hero__head' },
        h('span', { class: 'gvc-head__index', 'aria-hidden': 'true' }, sections.hero.index),
        h('h1', { class: 'gvc-hero__title', id: 'gvc-hero-title' }, c.hero.title),
        h('div', { class: 'gvc-hero__copy' },
          h('p', { class: 'gvc-hero__lead' }, c.hero.lead),
          h('div', { class: 'gvc-hero__actions' },
            kit.extLink({ class: 'gvc-button gvc-button--primary', href: c.hero.ctaPrimary.href },
              kit.icon('github'), c.hero.ctaPrimary.label),
            kit.demoLink(c.hero.ctaSecondary.label, 'gvc-button gvc-button--ghost')))),
      stageHost);

    /* ---------- 02–06: секции с компонентами ---------- */

    var bodies = {};
    function section(id) {
      var body = h('div', { class: 'gvc-section__body' });
      bodies[id] = body;
      return h('section', { id: id, class: 'gvc-section gvc-section--' + id, 'aria-labelledby': 'gvc-' + id + '-title' },
        sectionHead(id), body);
    }

    /* ---------- 07 финал: таблица ссылок ---------- */

    var contact = h('section', { id: 'contact', class: 'gvc-section gvc-contact', 'aria-labelledby': 'gvc-contact-title' },
      sectionHead('contact'),
      h('div', { class: 'gvc-contact__body' },
        h('p', { class: 'gvc-contact__text' }, c.contact.text),
        h('ul', { class: 'gvc-contact__list', role: 'list', 'aria-label': T.contactLinks }, c.contact.links.map(function (l) {
          return h('li', { class: ['gvc-contact__item', l.primary ? 'gvc-contact__item--primary' : null] },
            kit.extLink({ class: 'gvc-contact__link', href: l.href },
              h('span', { class: 'gvc-contact__label' }, l.primary ? kit.icon('github') : null, l.label),
              h('span', { class: 'gvc-contact__url' }, l.href.replace(/^https?:\/\//, '')),
              kit.icon('external')));
        })),
        h('dl', { class: 'gvc-contact__meta' },
          h('div', null, h('dt', null, T.hackathon), h('dd', null, c.meta.track)),
          h('div', null, h('dt', null, T.license), h('dd', null, c.meta.copyright)))));

    var footer = h('footer', { class: 'gvc-footer' },
      h('p', null, c.meta.copyright + '.'),
      h('p', { class: 'gvc-footer__meta' },
        h('span', null, c.meta.name + ' v' + c.meta.version),
        kit.extLink({ href: c.meta.licenseUrl }, c.labels.license)));

    var main = h('div', { class: 'gvc-main' },
      hero,
      ORDER.slice(1, -1).map(section),
      contact,
      footer);
    var page = h('div', { class: 'gvc-page' }, header, main);
    root.appendChild(page);

    /* ---------- монтирование компонентов ---------- */

    instances.push(GV.components.heroStage.mount(stageHost, { layout: 'sheet' }));
    ORDER.slice(1, -1).forEach(function (id) {
      var m = MOUNTS[id];
      instances.push(GV.components[m.component].mount(bodies[id], m.options));
    });

    /* ---------- индекс: переход и подсветка текущей секции ---------- */

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

    var currentId = null;
    function setCurrent(id) {
      if (id === currentId) return;
      currentId = id;
      ORDER.forEach(function (key) {
        if (key === id) navLinks[key].setAttribute('aria-current', 'true');
        else navLinks[key].removeAttribute('aria-current');
      });
      /* На узком экране индекс — горизонтальная строка: держим текущий пункт в зоне видимости. */
      var list = navLinks[id] && navLinks[id].closest('.gvc-index');
      if (list && list.scrollWidth > list.clientWidth + 1) {
        var link = navLinks[id];
        var left = link.offsetLeft - (list.clientWidth - link.offsetWidth) / 2;
        list.scrollTo({ left: Math.max(0, left), behavior: u.prefersReducedMotion() ? 'auto' : 'smooth' });
      }
    }

    if ('IntersectionObserver' in window) {
      var visible = {};
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
        var current = null;
        ORDER.forEach(function (id) { if (!current && visible[id]) current = id; });
        if (current) setCurrent(current);
      }, { rootMargin: '-30% 0px -60% 0px' });
      ORDER.forEach(function (id) {
        var el = document.getElementById(id);
        if (el) io.observe(el);
      });
      sc.add(function () { io.disconnect(); });
    }
    setCurrent('hero');

    return function cleanup() {
      sc.destroy();
      while (instances.length) {
        var inst = instances.pop();
        try { inst.destroy(); } catch (e) { console.error('GV.variants.c: ошибка destroy компонента', e); }
      }
      if (page.parentNode) page.parentNode.removeChild(page);
    };
  }

  GV.variants.c = { id: 'c', label: 'Протокол', render: render };
})();
