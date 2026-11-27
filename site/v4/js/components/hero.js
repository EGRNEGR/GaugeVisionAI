/*
 * GV.components.hero — первый экран: ролик на прокрутке (развитие scroll-video v2) и разметка
 * компьютерного зрения поверх кадра.
 * mount(el) → { destroy(), setProgress(p) }
 *
 * Сцена .gv-hero высотой 320vh, внутри закреплённый кадр. Видео не играет: currentTime догоняет цель
 * с инерцией (как в v2). Камера в ролике отъезжает от манометра и «читает» его лучом.
 * Справа — панель этапов распознавания (content.heroSection.hud): этапы отмечаются по прогрессу
 * прокрутки. Геометрическую разметку поверх ролика сайт не рисует: ролик — генерация, и проверка
 * модулем app/vision.py на его кадрах не дала надёжной локализации (reports/website_redesign).
 * Точная демонстрация — в сцене «Как это работает» и реальные кадры конвейера — в секции «Щит».
 * Ошибка видео или reduced motion — постер, без закрепления.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var TAIL = 0.05;
  var LERP = 0.14;
  var MIN_STEP = 1 / 60;
  var MOBILE = '(max-width: 768px)';

  function clamp01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }
  function smooth(a, b, v) { var t = clamp01((v - a) / (b - a)); return t * t * (3 - 2 * t); }
  function timeFor(p, d) { return (!isFinite(d) || d <= TAIL) ? 0 : clamp01(p) * (d - TAIL); }

  function mount(el) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit, motion = GV.motion;
    var c = GV.content.heroSection;
    var L = GV.content.labels;
    var section = el.closest ? el.closest('section') : null;
    var offs = [];
    var sc = kit.scope();

    /* ---------- HUD: заголовок, строка, кнопки ---------- */
    var title = h('h1', { class: 'gv-hero__title', id: 'gv-hero-title' },
      c.title.map(function (line, i) { return h('span', { class: 'gv-hero__title-line', style: { '--i': i } }, line); }));
    var ctas = h('div', { class: 'gv-hero__ctas' }, c.ctas.map(function (cta) {
      return h('a', { class: ['gv-btn', cta.primary ? 'gv-btn--primary' : 'gv-btn--ghost'], href: cta.href },
        h('span', null, cta.label), cta.primary ? kit.icon('arrow') : null);
    }));
    var showBtn = h('button', { class: 'gv-hero__showcase', type: 'button', 'data-showcase-open': '' },
      h('span', { class: 'gv-hero__showcase-dot', 'aria-hidden': 'true' }), L.showcase);
    var copy = h('div', { class: 'gv-hero__copy' },
      h('p', { class: 'gv-hero__kicker' }, c.kicker),
      title,
      h('p', { class: 'gv-hero__line' }, c.line),
      ctas, showBtn);

    /* ---------- панель стадий CV ---------- */
    var stageEls = c.hud.map(function (st) {
      return h('li', { class: 'gv-cvp__stage' },
        h('span', { class: 'gv-cvp__code' }, st.code),
        h('span', { class: 'gv-cvp__text' }, st.text),
        h('span', { class: 'gv-cvp__tick', 'aria-hidden': 'true' }));
    });
    var panel = h('aside', { class: 'gv-cvp', 'aria-hidden': 'true' },
      h('p', { class: 'gv-cvp__head' }, h('span', { class: 'gv-cvp__rec' }), 'этапы распознавания'),
      h('ol', { class: 'gv-cvp__stages', role: 'list' }, stageEls),
      h('p', { class: 'gv-cvp__foot' }, 'Как это выглядит на приборе — ниже, в сцене «Как это работает»'));

    var media = h('div', { class: 'gv-hero__media' });
    var scrim = h('div', { class: 'gv-hero__scrim', 'aria-hidden': 'true' });
    var fill = h('span', { class: 'gv-hero__scroll-fill' });
    var indicator = h('div', { class: 'gv-hero__scroll', 'aria-hidden': 'true' }, h('span', { class: 'gv-hero__scroll-track' }, fill),
      h('span', { class: 'gv-hero__scroll-label' }, 'прокрутите'));
    var note = h('p', { class: 'gv-hero__note' }, c.note);
    var stage = h('div', { class: 'gv-hero__stage' }, media, scrim,
      h('div', { class: 'gv-container gv-hero__hud' }, copy, panel), indicator, note);
    var scene = h('div', { class: 'gv-hero' }, stage);
    el.appendChild(scene);

    var vid = null, stopped = false;
    var target = 0, cur = 0, visible = true, offFrame = null, lastP = -1;

    function poster() { return h('img', { class: 'gv-hero__poster', src: c.video.poster, alt: '', decoding: 'async' }); }

    function setStatic() {
      destroyVideo();
      media.textContent = '';
      media.appendChild(poster());
      scene.setAttribute('data-static', '');
      if (section) section.setAttribute('data-static', '');
      paint(0.02);
    }

    function destroyVideo() {
      stopped = true;
      if (offFrame) { offFrame(); offFrame = null; }
      if (vid) { vid.removeAttribute('src'); try { vid.load(); } catch (e) { /* снято */ } vid = null; }
    }

    function paint(p) {
      fill.style.transform = 'scaleY(' + p.toFixed(4) + ')';
      var out = smooth(0.1, 0.3, p);
      copy.style.opacity = (1 - out).toFixed(3);
      copy.style.transform = 'translate3d(0,' + (-out * 3).toFixed(2) + 'rem,0)';
      copy.style.visibility = out > 0.99 ? 'hidden' : '';
      var pin = smooth(0.08, 0.2, p) * (1 - smooth(0.82, 0.95, p));
      panel.style.opacity = pin.toFixed(3);
      panel.style.transform = 'translate3d(' + ((1 - smooth(0.08, 0.2, p)) * 1.5).toFixed(2) + 'rem,0,0)';
      var hud = c.hud;
      for (var i = 0; i < hud.length; i++) {
        var on = p >= hud[i].at + 0.06;
        stageEls[i].toggleAttribute('data-on', on);
        stageEls[i].toggleAttribute('data-current', on && (i === hud.length - 1 || p < hud[i + 1].at + 0.06));
      }
      var end = 1 - smooth(0.85, 1, p);
      media.style.opacity = end.toFixed(3);
      scrim.style.opacity = (0.55 + 0.45 * (1 - end)).toFixed(3);
      indicator.style.opacity = (1 - smooth(0.9, 1, p)).toFixed(3);
    }

    function frame(dt) {
      if (stopped || !vid) return sleep();
      var d = vid.duration;
      if (!isFinite(d) || vid.readyState < 1) return sleep();
      var k = 1 - Math.pow(1 - LERP, dt * 60);
      cur += (target - cur) * k;
      if (Math.abs(target - cur) < 0.002) cur = target;
      if (!vid.seeking && Math.abs(vid.currentTime - cur) > MIN_STEP) vid.currentTime = cur;
      if (cur === target && Math.abs(vid.currentTime - cur) <= MIN_STEP) sleep();
    }
    function sleep() { if (offFrame) { offFrame(); offFrame = null; } }
    function wake() { if (!offFrame && visible && !stopped) offFrame = motion.onFrame(frame); }

    function setProgress(p) {
      var m = motion.measure(scene);
      var vh = motion.viewport().height;
      root.scrollTo({ top: m.top + clamp01(p) * Math.max(0, m.height - vh), behavior: 'auto' });
    }

    function destroy() {
      destroyVideo();
      offs.forEach(function (off) { off(); });
      sc.destroy();
      if (scene.parentNode) scene.parentNode.removeChild(scene);
      if (section) section.removeAttribute('data-static');
    }

    if (motion.reduced() || !root.requestAnimationFrame) {
      setStatic();
      return { destroy: destroy, setProgress: setProgress };
    }

    var mobile = typeof root.matchMedia === 'function' && root.matchMedia(MOBILE).matches;
    vid = h('video', {
      class: 'gv-hero__video', muted: '', playsinline: '', 'webkit-playsinline': '', preload: 'auto',
      disablepictureinpicture: '', disableremoteplayback: '', poster: c.video.poster, 'aria-label': c.video.label
    });
    vid.muted = true;
    vid.playsInline = true;
    media.appendChild(vid);
    stopped = false;

    offs.push(motion.onScroll(function () {
      if (stopped || !visible) return;
      var p = motion.pinProgress(scene);
      if (Math.abs(p - lastP) > 1e-5) { paint(p); lastP = p; }
      if (vid) target = timeFor(p, vid.duration);
      wake();
    }));

    if ('IntersectionObserver' in root) {
      var io = new root.IntersectionObserver(function (entries) {
        visible = entries.some(function (e) { return e.isIntersecting; });
        if (visible) { var p = motion.pinProgress(scene); paint(p); lastP = p; if (vid) target = timeFor(p, vid.duration); wake(); }
        else sleep();
      });
      io.observe(scene);
      offs.push(function () { io.disconnect(); });
    }

    vid.addEventListener('loadedmetadata', function () { target = timeFor(motion.pinProgress(scene), vid.duration); wake(); });
    vid.addEventListener('error', function () {
      console.error('GV.components.hero: видео не загрузилось — показан постер', vid && vid.currentSrc);
      setStatic();
    });
    vid.src = mobile ? c.video.srcMobile : c.video.src;
    paint(motion.pinProgress(scene));

    return { destroy: destroy, setProgress: setProgress };
  }

  GV.components.hero = { mount: mount, timeFor: timeFor };
})();
