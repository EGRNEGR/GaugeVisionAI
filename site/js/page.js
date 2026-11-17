/*
 * GV.page — одна страница «Циферблат» (бывший вариант B): шапка с навигацией и полосой телеметрии,
 * восемь секций GV.content.sections по порядку, финал с GitHub и футер.
 * Секция получает заголовок (номер в левой колонке + h2 с каскадом слов), а содержимое рисует модуль
 * из таблицы mounts: GV.components[name].mount(body, options) → { destroy }.
 * Подключается последним и строит страницу сам на DOMContentLoaded.
 *
 *   GV.page.mounts = { <id секции>: <имя в GV.components> }   таски 02 и 03 дописывают hero, reading, pipeline
 *   GV.page.render(root) → cleanup()
 *
 * Закреплённые сцены (PIN_HEAD) получают заголовок в mount(body, { head }) и ставят его внутрь
 * sticky-сцены: иначе при закреплении заголовок уезжает и сцена остаётся без подписи.
 * Модуля из mounts нет или mount бросил — console.error, секция остаётся с заголовком
 * (у hero — h1 и строка на постере). Это ошибка сборки, а не режим работы.
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

  /* Закреплённые сцены: заголовок живёт внутри sticky-сцены модуля. */
  var PIN_HEAD = { reading: true, pipeline: true };

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

    function headCore(sec, pinned) {
      // В закреплённой сцене номер не ставится: надзаголовок над h2 — шум, номер раздела уже в телеметрии
      return h('header', { class: ['gv-head', pinned ? 'gv-head--pinned' : null] },
        pinned ? null : h('span', { class: 'gv-head__index', 'aria-hidden': 'true' }, sec.index),
        h('h2', { class: 'gv-head__title', id: 'gv-' + sec.id + '-title', 'data-reveal': 'words' }, sec.title));
    }

    function head(sec) {
      if (!sec.title) return null;
      return h('div', { class: 'gv-container gv-section__head' }, headCore(sec, false));
    }

    function heroFallback() {
      var hero = c.hero;
      return h('div', { class: 'gv-hero-static' },
        h('img', { class: 'gv-hero-static__poster', src: hero.video.poster, alt: '', decoding: 'async' }),
        h('div', { class: 'gv-container gv-hero-static__hud' },
          h('h1', { class: 'gv-hero-static__title', id: 'gv-hero-title' }, hero.title),
          h('p', { class: 'gv-hero-static__line' }, hero.line)));
    }

    function mountModule(id, body, options) {
      var name = MOUNTS[id];
      if (!name) return false;
      var comp = GV.components && GV.components[name];
      if (!comp || typeof comp.mount !== 'function') {
        console.error('GV.page: нет модуля GV.components.' + name + ' для секции #' + id + ' — подключите его <script> до page.js');
        return false;
      }
      try {
        instances.push(comp.mount(body, options));
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
      var pinnedHead = PIN_HEAD[sec.id] && sec.title ? headCore(sec, true) : null;
      var el = h('section', { id: sec.id, class: ['gv-section', 'gv-section--' + sec.id], 'data-module': MOUNTS[sec.id] || null },
        GLOWS[sec.id] ? h('span', { class: 'gv-glow gv-glow--' + GLOWS[sec.id], 'aria-hidden': 'true' }) : null,
        pinnedHead ? null : head(sec),
        body);
      main.appendChild(el);
      sectionEls.push(el);
      var mounted = mountModule(sec.id, body, pinnedHead ? { head: pinnedHead } : undefined);
      // Модуль не встал — заголовок возвращается над телом секции
      if (pinnedHead && (!mounted || !pinnedHead.parentNode)) el.insertBefore(head(sec), body);
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
    var repoLink;
    var contact = h('section', { id: 'contact', class: 'gv-section gv-section--contact gv-contact', 'aria-labelledby': 'gv-contact-title' },
      h('div', { class: 'gv-contact__backdrop', 'aria-hidden': 'true' },
        h('img', { src: c.contact.backdrop, alt: '', loading: 'lazy', decoding: 'async' })),
      h('span', { class: 'gv-glow gv-glow--' + GLOWS.contact, 'aria-hidden': 'true' }),
      head(contactSec),
      h('div', { class: 'gv-container gv-contact__inner' },
        repoLink = kit.extLink({ class: 'gv-contact__repo', href: repo.href },
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

    /* Фон страницы — слой под всем содержимым: градиент и светлое пятно за курсором. Вариант фона из Tweaks
       (data-ambient на <html>) включает свои слои: «Чертёж» — сетку, которую пятно проявляет под курсором,
       «Шкала» — шкалу прибора 270°, стрелка которой показывает, сколько страницы прочитано. */
    function dialScale(needleEl) {
      var ticks = [];
      for (var i = 0; i <= 50; i++) {
        var a = (135 + i * 5.4) * Math.PI / 180;
        var major = i % 5 === 0;
        var r1 = major ? 80 : 85;
        ticks.push(s('line', {
          class: ['gv-ambient__tick', major ? 'gv-ambient__tick--major' : null],
          x1: (Math.cos(a) * r1).toFixed(2), y1: (Math.sin(a) * r1).toFixed(2),
          x2: (Math.cos(a) * 90).toFixed(2), y2: (Math.sin(a) * 90).toFixed(2)
        }));
      }
      return s('svg', { class: 'gv-ambient__dial', viewBox: '-100 -100 200 200', focusable: 'false' },
        s('path', { class: 'gv-ambient__arc', d: kit.arcPath(0, 0, 90, 135, 45) }), ticks, needleEl);
    }
    var needle = s('g', { class: 'gv-ambient__needle' },
      s('line', { x1: -12, y1: 0, x2: 76, y2: 0 }),
      s('circle', { cx: 0, cy: 0, r: 2.5 }));
    var light = h('span', { class: 'gv-ambient__light' }, h('span', { class: 'gv-ambient__grid' }));
    var ambient = h('div', { class: 'gv-ambient', 'aria-hidden': 'true' }, dialScale(needle), light);
    var page = h('div', { class: 'gv-page' }, ambient, header, main, footer);
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
    var lastAngle = '';
    offs.push(motion.onScroll(function (y) {
      var vh = motion.viewport().height;
      var doc = motion.measure(page);
      var p = Math.min(1, Math.max(0, y / Math.max(1, doc.top + doc.height - vh)));
      bar.style.transform = 'scaleX(' + p.toFixed(4) + ')';
      // Стрелка шкалы фона: 135° — начало страницы, +270° — конец (догоняет переходом transform в css)
      var angle = (135 + 270 * p).toFixed(1);
      if (angle !== lastAngle) { needle.style.transform = 'rotate(' + angle + 'deg)'; lastAngle = angle; }
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
    offs.push(motion.cursorLight(light));
    offs.push(motion.magnet(repoLink, { pull: 0.25 }));

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
