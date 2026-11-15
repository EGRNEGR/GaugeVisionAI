/*
 * GV.page — одна страница «Циферблат» (бывший вариант B): шапка с навигацией и полосой телеметрии,
 * восемь секций GV.content.sections по порядку, финал с GitHub и футер.
 * Секция получает заголовок (крупный контурный номер + h2 с каскадом слов), а содержимое рисует модуль
 * из таблицы mounts: GV.components[name].mount(body, options) → { destroy }.
 * Подключается последним и строит страницу сам на DOMContentLoaded.
 *
 *   GV.page.mounts = { <id секции>: <имя в GV.components> }   таски 02 и 03 дописывают hero, reading, pipeline
 *   GV.page.render(root) → cleanup()
 *
 * Модуля из mounts нет или mount бросил — console.error, секция остаётся с заголовком
 * (у hero — kicker, h1 и строка на постере). Это ошибка сборки, а не режим работы.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  var MOUNTS = {
    hero: 'scrollVideo',
    reading: 'precisionDial',
    pipeline: 'pipelineTrack',
    metrics: 'metrics',
    compare: 'compare',
    architecture: 'architecture',
    limits: 'limits'
  };

  /* Сцены во всю ширину экрана: модуль сам задаёт сетку и закрепление. */
  var FULL_BLEED = { hero: true, reading: true, pipeline: true };

  /* Направленные пятна света: где и какое (статичные, низкая непрозрачность). */
  var GLOWS = { metrics: 'warm', architecture: 'cool', limits: 'warm', contact: 'warm' };

  var T = {
    nav: 'Разделы страницы',
    home: 'GaugeVision AI — к началу страницы',
    github: 'GitHub'
  };

  function pad(n, len) {
    var s = String(n);
    while (s.length < len) s = '0' + s;
    return s;
  }

  function render(root) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var s = u.svg;
    var c = GV.content;
    var NBSP = kit.NBSP;
    var sc = kit.scope();
    var offs = [];
    var instances = [];
    var sections = c.sections;
    var byId = {};
    sections.forEach(function (sec) { byId[sec.id] = sec; });

    /* ---------- шапка: бренд · навигация · GitHub, под ней телеметрия ---------- */

    function brandMark() {
      return s('svg', { class: 'gv-brand__mark', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
        s('path', { class: 'gv-brand__arc', d: kit.arcPath(12, 12, 9.5, 135, 45) }),
        s('line', { class: 'gv-brand__needle', x1: 12, y1: 12, x2: 13.2, y2: 3.8 }),
        s('circle', { class: 'gv-brand__hub', cx: 12, cy: 12, r: 2.2 }));
    }

    var navLinks = {};
    var navIds = sections.filter(function (sec) { return sec.id !== 'contact'; }).map(function (sec) { return sec.id; });
    var nav = h('nav', { class: 'gv-nav', 'aria-label': T.nav },
      h('ul', { class: 'gv-nav__list', role: 'list' }, navIds.map(function (id) {
        var a = h('a', { class: 'gv-nav__link', href: '#' + id }, byId[id].nav);
        navLinks[id] = a;
        return h('li', null, a);
      })));

    var bar = h('span', { class: 'gv-telemetry__bar' });
    var teleLabel = h('span', { class: 'gv-telemetry__label' });
    var teleName = h('span', { class: 'gv-telemetry__name' });
    var telemetry = h('div', { class: 'gv-telemetry', 'aria-hidden': 'true' },
      h('span', { class: 'gv-telemetry__track' }, bar),
      h('div', { class: 'gv-container gv-telemetry__inner' }, teleLabel, teleName));

    var header = h('header', { class: 'gv-header' },
      h('div', { class: 'gv-container gv-header__inner' },
        h('a', { class: 'gv-brand', href: '#hero', 'aria-label': T.home }, brandMark(),
          h('span', { class: 'gv-brand__name' }, c.meta.name)),
        nav,
        kit.extLink({ class: 'gv-header__github', href: c.meta.repoUrl }, kit.icon('github'), h('span', null, T.github))),
      telemetry);

    /* ---------- секции ---------- */

    function head(sec) {
      if (!sec.title) return null;
      return h('div', { class: 'gv-container gv-section__head' },
        h('header', { class: 'gv-head' },
          h('span', { class: 'gv-head__index', 'aria-hidden': 'true' }, sec.index),
          h('h2', { class: 'gv-head__title', id: 'gv-' + sec.id + '-title', 'data-reveal': 'words' }, sec.title)));
    }

    function heroFallback() {
      var hero = c.hero;
      return h('div', { class: 'gv-hero-static' },
        h('img', { class: 'gv-hero-static__poster', src: hero.video.poster, alt: '', decoding: 'async' }),
        h('div', { class: 'gv-container gv-hero-static__hud' },
          h('p', { class: 'gv-hero-static__kicker' }, hero.kicker),
          h('h1', { class: 'gv-hero-static__title', id: 'gv-hero-title' }, hero.title),
          h('p', { class: 'gv-hero-static__line' }, hero.line)));
    }

    function mountModule(id, body) {
      var name = MOUNTS[id];
      if (!name) return false;
      var comp = GV.components && GV.components[name];
      if (!comp || typeof comp.mount !== 'function') {
        console.error('GV.page: нет модуля GV.components.' + name + ' для секции #' + id + ' — подключите его <script> до page.js');
        return false;
      }
      try {
        instances.push(comp.mount(body));
        return true;
      } catch (e) {
        console.error('GV.page: модуль ' + name + ' не смонтировался в #' + id, e);
        body.textContent = '';
        return false;
      }
    }

    var sectionEls = [];
    var main = h('main', { id: 'gv-main', class: 'gv-main', tabindex: '-1' });

    sections.forEach(function (sec) {
      if (sec.id === 'contact') return;
      var body = h('div', { class: ['gv-section__body', FULL_BLEED[sec.id] ? null : 'gv-container'] });
      var el = h('section', { id: sec.id, class: ['gv-section', 'gv-section--' + sec.id], 'data-module': MOUNTS[sec.id] || null },
        GLOWS[sec.id] ? h('span', { class: 'gv-glow gv-glow--' + GLOWS[sec.id], 'aria-hidden': 'true' }) : null,
        head(sec),
        body);
      main.appendChild(el);
      sectionEls.push(el);
      var mounted = mountModule(sec.id, body);
      if (!mounted && sec.id === 'hero') body.appendChild(heroFallback());
      var heading = el.querySelector('h1, h2');
      if (heading) {
        if (!heading.id) heading.id = 'gv-' + sec.id + '-title';
        el.setAttribute('aria-labelledby', heading.id);
      }
    });

    /* ---------- финал и футер ---------- */

    var links = c.contact.links;
    var repo = links.filter(function (l) { return l.primary; })[0];
    var license = links.filter(function (l) { return l.id === 'license'; })[0];
    var contactSec = byId.contact;
    var contact = h('section', { id: 'contact', class: 'gv-section gv-section--contact gv-contact', 'aria-labelledby': 'gv-contact-title' },
      h('div', { class: 'gv-contact__backdrop', 'aria-hidden': 'true' },
        h('img', { src: c.contact.backdrop, alt: '', loading: 'lazy', decoding: 'async' })),
      h('span', { class: 'gv-glow gv-glow--' + GLOWS.contact, 'aria-hidden': 'true' }),
      head(contactSec),
      h('div', { class: 'gv-container gv-contact__inner' },
        kit.extLink({ class: 'gv-contact__repo', href: repo.href },
          kit.icon('github'),
          h('span', { class: 'gv-contact__repo-label' }, repo.label),
          h('span', { class: 'gv-contact__repo-url' }, repo.href.replace(/^https?:\/\//, ''))),
        h('p', { class: 'gv-contact__meta' }, c.meta.trackShort)));
    main.appendChild(contact);
    sectionEls.push(contact);

    var footer = h('footer', { class: 'gv-footer' },
      h('div', { class: 'gv-container gv-footer__inner' },
        h('p', { class: 'gv-footer__copy' }, c.meta.copyright + '.'),
        h('p', { class: 'gv-footer__meta' },
          h('span', null, c.meta.name + NBSP + 'v' + c.meta.version),
          license ? kit.extLink({ class: 'gv-footer__license', href: license.href }, license.label) : null)));

    var page = h('div', { class: 'gv-page' }, header, main, footer);
    root.appendChild(page);

    /* ---------- навигация, телеметрия, появление заголовков ---------- */

    kit.sectionNav(sc, {
      container: header,
      links: navLinks,
      ids: sections.map(function (sec) { return sec.id; }),
      rootMargin: '-35% 0px -55% 0px'
    });

    var total = pad(sections.length, 2);
    var lastLabel = '';
    var lastName = '';
    offs.push(motion.onScroll(function (y) {
      var vh = motion.viewport().height;
      var doc = motion.measure(page);
      var p = Math.min(1, Math.max(0, y / Math.max(1, doc.top + doc.height - vh)));
      bar.style.transform = 'scaleX(' + p.toFixed(4) + ')';
      var idx = 0;
      for (var i = 0; i < sectionEls.length; i++) {
        if (motion.measure(sectionEls[i]).top <= y + vh * 0.4) idx = i;
      }
      var label = pad(idx + 1, 2) + ' / ' + total + ' · ' + pad(Math.round(p * 100), 3) + NBSP + '%';
      if (label !== lastLabel) { teleLabel.textContent = label; lastLabel = label; }
      var name = sections[idx].nav;
      if (name !== lastName) { teleName.textContent = name; lastName = name; }
    }));

    offs.push(motion.reveal(main));

    /* Переход по якорю из адреса. Битый адрес (#%E0) не роняет страницу — хэш просто игнорируется. */
    var raw = (window.location.hash || '').slice(1);
    if (raw) {
      var id = null;
      try { id = decodeURIComponent(raw); } catch (e) { id = null; }
      var target = id ? document.getElementById(id) : null;
      if (target && main.contains(target)) target.scrollIntoView({ block: 'start', behavior: 'auto' });
    }

    return function cleanup() {
      sc.destroy();
      offs.forEach(function (off) { off(); });
      while (instances.length) {
        var inst = instances.pop();
        try { if (inst && inst.destroy) inst.destroy(); } catch (e) { console.error('GV.page: ошибка destroy модуля', e); }
      }
      if (page.parentNode) page.parentNode.removeChild(page);
    };
  }

  GV.page = { mounts: MOUNTS, render: render };

  function boot() {
    var root = document.getElementById('gv-root');
    if (!root || !GV.util || !GV.kit || !GV.motion || !GV.content) {
      console.error('GV.page: нет #gv-root или общих скриптов (content, util, motion, kit) — проверьте порядок <script>');
      return;
    }
    render(root);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
