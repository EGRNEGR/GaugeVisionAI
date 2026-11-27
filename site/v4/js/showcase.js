/*
 * GV.showcase — режим конкурсной демонстрации поверх обычной страницы.
 * Включение: кнопка «Режим демонстрации», адрес ?showcase=1 или клавиша D. Выход — Esc или кнопка.
 * В режиме: шапка и навигация скрыты (html[data-showcase]), внизу — пульт демонстрации: номер шага,
 * заголовок, плашка режима (симуляция / запись приложения / доказательство испытаний), кнопки.
 * Шаг (GV.content.showcase.steps) ставит страницу в воспроизводимое состояние через API компонентов:
 * hero.setProgress, story.goTo, multigauge.setCount, resilience.cut/restore/reset, forecast.play,
 * optimizer.setBudget, document.assemble — и прокручивает к секции без плавности.
 * Клавиши: → / Space / PageDown — далее, ← / PageUp — назад, P — пауза автопоказа, R — заново,
 * F — полный экран, 1–9 — шаг, Esc — выход. Автопоказ: 7 с на шаг, по умолчанию выключен.
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  var AUTO_MS = 7000;

  function create(api) {
    var u = GV.util, h = u.h, kit = GV.kit;
    var S = GV.content.showcase;
    var html = document.documentElement;
    var steps = S.steps;
    var idx = -1, active = false, auto = false, timer = 0;

    var num = h('span', { class: 'gv-sc__num' });
    var mode = h('span', { class: 'gv-sc__mode' });
    var title = h('p', { class: 'gv-sc__title' });
    var text = h('p', { class: 'gv-sc__text' });
    var bar = h('span', { class: 'gv-sc__bar-fill' });
    function btn(label, key, glyph) { return h('button', { class: 'gv-sc__btn', type: 'button', 'aria-label': label, title: label + ' (' + key + ')' }, glyph); }
    var bPrev = btn('Назад', '←', '←'), bNext = btn('Далее', '→', '→'), bPause = btn('Автопоказ', 'P', '▶'), bRestart = btn('Заново', 'R', '↺'), bFull = btn('Полный экран', 'F', '⛶'), bExit = btn('Выйти', 'Esc', '✕');
    var dock = h('div', { class: 'gv-sc', role: 'region', 'aria-label': 'Пульт режима демонстрации', hidden: true },
      h('span', { class: 'gv-sc__bar', 'aria-hidden': 'true' }, bar),
      h('div', { class: 'gv-sc__info' }, h('p', { class: 'gv-sc__meta' }, num, mode), title, text),
      h('div', { class: 'gv-sc__ctl' }, bPrev, bNext, bPause, bRestart, bFull, bExit),
      h('p', { class: 'gv-sc__hint' }, S.hint));
    var live = h('p', { class: 'gv-visually-hidden', 'aria-live': 'polite' });
    document.body.appendChild(dock);
    document.body.appendChild(live);

    function section(id) { return document.getElementById(id); }
    function scrollTo(id) { var el = section(id); if (el) el.scrollIntoView({ block: 'start', behavior: 'auto' }); }

    function apply(st) {
      var a = api();
      if (st.target === 'hero' && a.hero) { a.hero.setProgress(st.progress || 0); return; }
      if (st.target === 'story' && a.story) { a.story.goTo(st.scene || 0); return; }
      scrollTo(st.target);
      if (st.target === 'multigauge' && a.multigauge) a.multigauge.setCount(st.count || 8);
      if (st.target === 'resilience' && a.resilience) {
        if (st.action === 'cut') { a.resilience.reset(); a.resilience.cut(); }
        if (st.action === 'restore') a.resilience.restore();
      }
      if (st.target === 'forecast' && a.forecast) a.forecast.play();
      if (st.target === 'optimizer' && a.optimizer) a.optimizer.setBudget(st.budget || 450000);
      if (st.target === 'document' && a.document) a.document.assemble();
    }

    function go(i) {
      i = Math.max(0, Math.min(steps.length - 1, i));
      idx = i;
      var st = steps[i];
      num.textContent = String(i + 1).padStart(2, '0') + ' / ' + steps.length;
      mode.textContent = S.modes[st.mode] || '';
      mode.setAttribute('data-mode', st.mode);
      title.textContent = st.title;
      text.textContent = st.text;
      bar.style.transform = 'scaleX(' + ((i + 1) / steps.length).toFixed(3) + ')';
      live.textContent = 'Шаг ' + (i + 1) + ' из ' + steps.length + ': ' + st.title;
      apply(st);
      arm();
    }

    function arm() {
      clearTimeout(timer);
      if (auto && active) timer = setTimeout(function () { if (idx < steps.length - 1) go(idx + 1); else setAuto(false); }, AUTO_MS);
    }
    function setAuto(on) { auto = on; bPause.textContent = on ? '❚❚' : '▶'; bPause.setAttribute('aria-pressed', on ? 'true' : 'false'); arm(); }

    function restart() {
      var a = api();
      if (a.resilience) a.resilience.reset();
      if (a.optimizer) { a.optimizer.setObjective('max_risk_reduction'); a.optimizer.setBudget(450000); }
      if (a.multigauge) a.multigauge.setCount(8);
      go(0);
    }

    function open() {
      if (active) return;
      active = true;
      html.setAttribute('data-showcase', '');
      dock.hidden = false;
      go(idx < 0 ? 0 : idx);
      bNext.focus();
    }
    function close() {
      if (!active) return;
      active = false;
      setAuto(false);
      html.removeAttribute('data-showcase');
      dock.hidden = true;
      if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {});
      try { var url = new URL(location.href); url.searchParams.delete('showcase'); history.replaceState(null, '', url); } catch (e) { /* без History API */ }
    }
    function full() {
      if (document.fullscreenElement) { document.exitFullscreen().catch(function () {}); return; }
      if (html.requestFullscreen) html.requestFullscreen().catch(function () {});
    }

    bPrev.addEventListener('click', function () { go(idx - 1); });
    bNext.addEventListener('click', function () { go(idx + 1); });
    bPause.addEventListener('click', function () { setAuto(!auto); });
    bRestart.addEventListener('click', restart);
    bFull.addEventListener('click', full);
    bExit.addEventListener('click', close);
    document.addEventListener('click', function (e) {
      var t = e.target.closest ? e.target.closest('[data-showcase-open]') : null;
      if (t) { e.preventDefault(); open(); }
    });
    document.addEventListener('keydown', function (e) {
      var tag = (e.target && e.target.tagName) || '';
      if (/INPUT|TEXTAREA|SELECT/.test(tag) || e.altKey || e.ctrlKey || e.metaKey) return;
      if (!active) { if (e.key === 'd' || e.key === 'D' || e.key === 'в' || e.key === 'В') { open(); e.preventDefault(); } return; }
      var k = e.key;
      if (k === 'ArrowRight' || k === 'PageDown' || k === ' ') go(idx + 1);
      else if (k === 'ArrowLeft' || k === 'PageUp') go(idx - 1);
      else if (k === 'Escape') close();
      else if (k === 'p' || k === 'P' || k === 'з' || k === 'З') setAuto(!auto);
      else if (k === 'r' || k === 'R' || k === 'к' || k === 'К') restart();
      else if (k === 'f' || k === 'F' || k === 'а' || k === 'А') full();
      else if (/^[1-9]$/.test(k)) go(Number(k) - 1);
      else if (k === 'Home') go(0);
      else if (k === 'End') go(steps.length - 1);
      else return;
      e.preventDefault();
    });

    if (/[?&]showcase=(1|on|true)(&|$)/.test(location.search)) setTimeout(open, 400);

    return { open: open, close: close, go: go, restart: restart, active: function () { return active; }, index: function () { return idx; } };
  }

  GV.showcase = { create: create };
})();
