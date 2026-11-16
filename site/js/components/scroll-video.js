/*
 * GV.components.scrollVideo — #hero: ролик Gemini на прокрутке и HUD поверх.
 * mount(el) → { destroy() }; опций нет.
 *
 * Сцена .gv-hero высотой 280vh, внутри — закреплённый (sticky) кадр с <video muted playsinline
 * preload="auto">. Видео не играет (play() не вызывается): currentTime догоняет цель
 * timeFor(pinProgress, duration) с инерцией cur += (target − cur) × 0,12 за кадр 60 к/с;
 * запись — только когда !video.seeking и разница > 1/60 с. Цикл кадра спит, когда сцена вне экрана
 * или видео догнало цель.
 * Поверх — ровно три элемента: h1, одна строка сути и индикатор прокрутки (подпись + шкала прогресса).
 * Прогресс индикатора — CSS-переменная --hero-p (0..1) на .gv-hero__scroll: шкала заливается
 * transform: scaleY на широких экранах и scaleX на телефоне (там индикатор — строка под текстом).
 * Ближе к концу HUD гаснет, кадр и затемнение тают в фон страницы — из него проявляется прибор сцены «Показание».
 * Ошибка видео или prefers-reduced-motion — только постер, секция data-static (100vh, без закрепления).
 * Движение — только transform и opacity.
 *
 * Чистая функция (для тестов): timeFor(progress, duration) → секунды.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var TAIL = 0.05;          // последний кадр не трогаем: на нём часть браузеров отдаёт ended и чёрный кадр
  var LERP = 0.12;          // доля пути к цели за кадр при 60 к/с
  var MIN_STEP = 1 / 60;    // меньше — не пишем currentTime
  var MOBILE = '(max-width: 768px)';

  function clamp01(v) {
    return v < 0 ? 0 : (v > 1 ? 1 : v);
  }

  function timeFor(progress, duration) {
    if (typeof duration !== 'number' || !isFinite(duration) || duration <= TAIL) return 0;
    return clamp01(progress) * (duration - TAIL);
  }

  /* Плавный порог 0..1 между a и b. */
  function smooth(a, b, v) {
    var t = clamp01((v - a) / (b - a));
    return t * t * (3 - 2 * t);
  }

  function mount(el) {
    var u = GV.util;
    var h = u.h;
    var motion = GV.motion;
    var hero = GV.content.hero;
    var video = hero.video;
    var section = el.closest ? el.closest('section') : null;
    var offs = [];

    var fill = h('span', { class: 'gv-hero__scroll-fill' });
    var heading = h('h1', { class: 'gv-hero__title', id: 'gv-hero-title' }, hero.title);
    var line = h('p', { class: 'gv-hero__line' }, hero.line);
    var indicator = h('div', { class: 'gv-hero__scroll', 'aria-hidden': 'true' },
      h('span', { class: 'gv-hero__scroll-label' }, hero.scrollLabel),
      h('span', { class: 'gv-hero__scroll-track' }, fill));
    var media = h('div', { class: 'gv-hero__media' });
    var scrim = h('div', { class: 'gv-hero__scrim', 'aria-hidden': 'true' });
    var stage = h('div', { class: 'gv-hero__stage' },
      media,
      scrim,
      h('div', { class: 'gv-container gv-hero__hud' }, heading, line, indicator));
    var scene = h('div', { class: 'gv-hero' }, stage);
    el.appendChild(scene);

    function poster() {
      return h('img', { class: 'gv-hero__poster', src: video.poster, alt: '', decoding: 'async' });
    }

    var vid = null;
    var stopped = false;

    function setStatic() {
      destroyVideo();
      media.textContent = '';
      media.appendChild(poster());
      scene.setAttribute('data-static', '');
      if (section) section.setAttribute('data-static', '');
      heading.style.opacity = line.style.opacity = '';
      heading.style.transform = line.style.transform = '';
      media.style.opacity = scrim.style.opacity = '';
      indicator.style.removeProperty('--hero-p');
    }

    /* Снять подписки и отпустить декодер: src убирается, load() сбрасывает буфер. */
    function destroyVideo() {
      stopped = true;
      offs.forEach(function (off) { off(); });
      offs = [];
      if (vid) {
        vid.removeAttribute('src');
        try { vid.load(); } catch (e) { /* уже снято */ }
        vid = null;
      }
    }

    function destroy() {
      destroyVideo();
      if (scene.parentNode) scene.parentNode.removeChild(scene);
      if (section) section.removeAttribute('data-static');
    }

    if (motion.reduced() || !root.requestAnimationFrame) {
      setStatic();
      return { destroy: destroy };
    }

    var mobile = typeof root.matchMedia === 'function' && root.matchMedia(MOBILE).matches;
    vid = h('video', {
      class: 'gv-hero__video',
      muted: '',
      playsinline: '',
      'webkit-playsinline': '',
      preload: 'auto',
      disablepictureinpicture: '',
      disableremoteplayback: '',
      poster: video.poster,
      'aria-label': video.label
    });
    vid.muted = true;
    vid.playsInline = true;
    media.appendChild(vid);

    var target = 0;
    var cur = 0;
    var visible = true;
    var offFrame = null;
    var lastP = -1;

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
    function sleep() {
      if (offFrame) { offFrame(); offFrame = null; }
    }
    function wake() {
      if (!offFrame && visible && !stopped) offFrame = motion.onFrame(frame);
    }

    function paint(p) {
      indicator.style.setProperty('--hero-p', p.toFixed(4));
      var out = smooth(0.55, 0.82, p);
      var hudOpacity = (1 - out).toFixed(3);
      heading.style.opacity = hudOpacity;
      line.style.opacity = hudOpacity;
      var lift = 'translate3d(0,' + (-out * 2).toFixed(3) + 'rem,0)';
      heading.style.transform = lift;
      line.style.transform = lift;
      var frame = (1 - smooth(0.8, 1, p)).toFixed(3);
      media.style.opacity = frame;
      scrim.style.opacity = frame;
    }

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
        if (visible) {
          var p = motion.pinProgress(scene);
          paint(p);
          lastP = p;
          if (vid) target = timeFor(p, vid.duration);
          wake();
        } else {
          sleep();
        }
      });
      io.observe(scene);
      offs.push(function () { io.disconnect(); });
    }

    function onMeta() {
      target = timeFor(motion.pinProgress(scene), vid.duration);
      wake();
    }
    function onError() {
      console.error('GV.components.scrollVideo: видео не загрузилось — показан постер', video.src);
      setStatic();
    }
    vid.addEventListener('loadedmetadata', onMeta);
    vid.addEventListener('error', onError);
    offs.push(function () {
      if (!vid) return;
      vid.removeEventListener('loadedmetadata', onMeta);
      vid.removeEventListener('error', onError);
    });
    offs.push(sleep);

    vid.src = mobile && video.srcMobile ? video.srcMobile : video.src;
    paint(0);

    return { destroy: destroy };
  }

  GV.components.scrollVideo = { mount: mount, timeFor: timeFor };
})();
