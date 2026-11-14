/*
 * GV.variants.a — «Пульт»: HUD-пульт оператора.
 * Асимметричная сетка 12 колонок: слева заголовок, лид и кнопки, справа hero-stage в рамке
 * с угловыми метками и телеметрией; метрики — телеметрическая полоса /01; конвейер — горизонтальная
 * лента этапов с панелью деталей снизу; сравнение split, ограничения cards. Акцент — холодный циан,
 * шрифты Manrope + JetBrains Mono (tokens.css). Стили — только css/variant-a.css под [data-variant="a"].
 * render(root) → cleanup(): снимает все компоненты, наблюдатели и слушатели.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.variants = GV.variants || {};

  /* Семь экранов в порядке брифа. */
  var ORDER = ['hero', 'metrics', 'pipeline', 'compare', 'architecture', 'limits', 'contact'];

  var MOUNTS = {
    metrics: { component: 'metrics', options: { layout: 'strip' } },
    pipeline: { component: 'pipeline', options: { layout: 'rail' } },
    compare: { component: 'compare', options: { layout: 'split' } },
    architecture: { component: 'architecture', options: {} },
    limits: { component: 'limits', options: { layout: 'cards' } }
  };

  var T = {
    nav: 'Разделы страницы',
    home: 'GaugeVision AI — к началу страницы',
    github: 'GitHub',
    chainBefore: 'Было',
    chainAfter: 'Стало',
    contactLinks: 'Ссылки проекта',
    track: 'Хакатон',
    license: 'Лицензия',
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

    function brandMark() {
      return s('svg', { class: 'gva-brand__mark', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
        s('path', { class: 'gva-brand__arc', d: kit.arcPath(12, 12, 9.5, 135, 45) }),
        s('line', { class: 'gva-brand__needle', x1: 12, y1: 12, x2: 17.5, y2: 6.5 }),
        s('circle', { class: 'gva-brand__hub', cx: 12, cy: 12, r: 1.8 }));
    }

    function index(id) {
      return h('span', { class: 'gva-index', 'aria-hidden': 'true' }, '/' + sections[id].index);
    }

    function sectionHead(id) {
      var sec = sections[id];
      return h('header', { class: 'gva-section__head' },
        h('h2', { class: 'gva-section__title', id: 'gva-' + id + '-title' }, index(id), sec.title),
        sec.lead ? h('p', { class: 'gva-section__lead' }, sec.lead) : null);
    }

    /* ---------- header ---------- */

    var navLinks = {};
    var header = h('header', { class: 'gva-header' },
      h('div', { class: 'gv-container gva-header__inner' },
        h('a', { class: 'gva-brand', href: '#hero', 'aria-label': T.home }, brandMark(),
          h('span', { class: 'gva-brand__name' }, c.meta.name)),
        h('nav', { class: 'gva-nav', 'aria-label': T.nav },
          h('ul', { class: 'gva-nav__list', role: 'list' }, ORDER.map(function (id) {
            var a = h('a', { class: 'gva-nav__link', href: '#' + id },
              h('span', { class: 'gva-nav__index', 'aria-hidden': 'true' }, sections[id].index), sections[id].nav);
            navLinks[id] = a;
            return h('li', null, a);
          }))),
        kit.extLink({ class: 'gva-header__cta', href: c.meta.repoUrl, 'aria-label': c.hero.ctaPrimary.label + T.newTab },
          kit.icon('github'), h('span', null, T.github))));

    /* ---------- 01 hero ---------- */

    function chain(label, items, mod) {
      return h('div', { class: 'gva-chain gva-chain--' + mod },
        h('span', { class: 'gva-chain__label' }, label),
        h('ol', { class: 'gva-chain__list', role: 'list' }, items.map(function (it, i) {
          return h('li', { class: 'gva-chain__item' },
            i > 0 ? h('span', { class: 'gva-chain__sep', 'aria-hidden': 'true' }, kit.icon('right')) : null, it);
        })));
    }

    var stageHost = h('div', { class: 'gva-hero__stage' });
    var hero = h('section', { id: 'hero', class: 'gva-hero', 'aria-labelledby': 'gva-hero-title' },
      h('div', { class: 'gv-container gva-hero__grid' },
        h('div', { class: 'gva-hero__copy' },
          h('h1', { class: 'gva-hero__title', id: 'gva-hero-title' }, c.hero.title),
          h('p', { class: 'gva-hero__lead' }, c.hero.lead),
          h('div', { class: 'gva-hero__actions' },
            kit.extLink({ class: 'gva-button gva-button--primary', href: c.hero.ctaPrimary.href },
              kit.icon('github'), c.hero.ctaPrimary.label),
            kit.demoLink(c.hero.ctaSecondary.label, 'gva-button gva-button--ghost')),
          h('div', { class: 'gva-hero__chains' },
            chain(T.chainBefore, c.hero.chain.before, 'before'),
            chain(T.chainAfter, c.hero.chain.after, 'after')),
          h('p', { class: 'gva-hero__meta' },
            h('span', null, c.meta.trackShort),
            h('span', null, 'v' + c.meta.version),
            h('span', null, c.labels.license))),
        stageHost));

    /* ---------- 02–06: секции с компонентами ---------- */

    var bodies = {};
    function section(id) {
      var body = h('div', { class: 'gva-section__body' });
      bodies[id] = body;
      return h('section', { id: id, class: 'gva-section gva-section--' + id, 'aria-labelledby': 'gva-' + id + '-title' },
        h('div', { class: 'gv-container' }, sectionHead(id), body));
    }

    /* ---------- 07 финал ---------- */

    var links = c.contact.links;
    var repo = links.filter(function (l) { return l.primary; })[0] || { label: c.hero.ctaPrimary.label, href: c.meta.repoUrl };
    var others = links.filter(function (l) { return !l.primary; });
    var contact = h('section', { id: 'contact', class: 'gva-contact', 'aria-labelledby': 'gva-contact-title' },
      h('div', { class: 'gv-container gva-contact__grid' },
        h('div', { class: 'gva-contact__copy' },
          h('h2', { class: 'gva-section__title gva-contact__title', id: 'gva-contact-title' }, index('contact'), c.contact.title),
          h('p', { class: 'gva-contact__text' }, c.contact.text),
          h('dl', { class: 'gva-contact__meta' },
            h('div', null, h('dt', null, T.track), h('dd', null, c.meta.track)),
            h('div', null, h('dt', null, T.license), h('dd', null, c.meta.copyright)))),
        h('div', { class: 'gva-contact__links' },
          kit.extLink({ class: 'gva-contact__repo', href: repo.href },
            h('span', { class: 'gva-contact__repo-top' }, kit.icon('github'), h('span', null, repo.label)),
            h('span', { class: 'gva-contact__repo-url' }, repo.href.replace(/^https?:\/\//, '')),
            h('span', { class: 'gva-contact__repo-arrow', 'aria-hidden': 'true' }, kit.icon('external'))),
          h('ul', { class: 'gva-contact__list', role: 'list', 'aria-label': T.contactLinks }, others.map(function (l) {
            return h('li', null, kit.extLink({ class: 'gva-contact__link', href: l.href },
              h('span', null, l.label), kit.icon('external')));
          })))));

    var footer = h('footer', { class: 'gva-footer' },
      h('div', { class: 'gv-container gva-footer__inner' },
        h('p', null, c.meta.copyright + '.'),
        h('p', { class: 'gva-footer__meta' },
          h('span', null, c.meta.name + ' v' + c.meta.version),
          kit.extLink({ href: c.meta.licenseUrl }, c.labels.license))));

    var page = h('div', { class: 'gva-page' },
      header,
      h('div', { class: 'gva-main' },
        hero,
        ORDER.slice(1, -1).map(section),
        contact),
      footer);
    root.appendChild(page);

    /* ---------- монтирование компонентов ---------- */

    instances.push(GV.components.heroStage.mount(stageHost, { layout: 'framed' }));
    ORDER.slice(1, -1).forEach(function (id) {
      var m = MOUNTS[id];
      instances.push(GV.components[m.component].mount(bodies[id], m.options));
    });

    /* ---------- навигация: плавный переход и подсветка текущего раздела ---------- */

    kit.sectionNav(sc, { container: header, links: navLinks, ids: ORDER, rootMargin: '-35% 0px -55% 0px' });

    return function cleanup() {
      sc.destroy();
      while (instances.length) {
        var inst = instances.pop();
        try { inst.destroy(); } catch (e) { console.error('GV.variants.a: ошибка destroy компонента', e); }
      }
      if (page.parentNode) page.parentNode.removeChild(page);
    };
  }

  GV.variants.a = { id: 'a', label: 'Пульт', render: render };
})();
