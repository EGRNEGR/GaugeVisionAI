/*
 * GV.components.multigauge — лист 03 «Одна камера на целый щит».
 * mount(body) → { destroy(), setCount(n), openSpot(i) }
 *
 * Переключатель 1 / 2 / 4 / 8 / 16 (.gv-filter__b) меняет вклеенный кадр синтетической панели (.gv-plate)
 * с реальным выводом конвейера (tests/test_multigauge.py). Рядом — таблица бланка (синтетика + MeterFL).
 * При N = 16 появляется графа-предупреждение о 47,9 % годных. При N = 8 — интерактивные точки на кадре.
 * Ниже — вклеенный снимок реального пульта вкладки «Щит» со штампом «Снимок реального приложения».
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var SPOTS8 = [
    { code: 'PI-101', x: 0.164, y: 0.255, v: '10,25', unit: 'МПа' },
    { code: 'PI-102', x: 0.397, y: 0.298, v: '0,26', unit: 'МПа' },
    { code: 'PI-103', x: 0.652, y: 0.27, v: '58,51', unit: 'кПа' },
    { code: 'PI-104', x: 0.908, y: 0.255, v: '55,16', unit: '°C' },
    { code: 'PI-105', x: 0.148, y: 0.765, v: '2,01', unit: 'МПа' },
    { code: 'PI-106', x: 0.394, y: 0.76, v: '233,50', unit: 'кПа' },
    { code: 'PI-107', x: 0.657, y: 0.765, v: '200,53', unit: '°C' },
    { code: 'PI-108', x: 0.908, y: 0.775, v: '2,71', unit: 'МПа' }
  ];

  function mount(body) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit;
    var C = GV.content, M = C.multigauge;
    var sc = kit.scope();
    var count = M.initial;

    var imgA = h('img', { class: 'gv-mg__img', alt: '', decoding: 'async', src: M.images[count], width: 1280, height: 720 });
    var imgB = h('img', { class: 'gv-mg__img', alt: '', decoding: 'async', src: M.images[count], width: 1280, height: 720 });
    imgA.style.opacity = '1';
    imgB.style.opacity = '0';
    var front = imgA;
    var shownSrc = M.images[count];
    var spots = h('div', { class: 'gv-mg__spots' });
    var spotBtns = [];
    var card = h('div', { class: 'gv-mg__card', hidden: true });
    var frame = h('div', { class: 'gv-mg__frame gv-plate' }, imgA, imgB, spots, card);

    var btns = M.counts.map(function (n) {
      return h('button', { class: 'gv-filter__b gv-seg__btn', type: 'button', 'aria-pressed': n === count ? 'true' : 'false', 'data-n': n },
        h('span', { class: 'gv-num' }, String(n)), h('span', { class: 'gv-visually-hidden' }, ' приборов'));
    });
    var seg = h('div', { class: 'gv-filter gv-seg', role: 'group', 'aria-label': 'Приборов на кадре' }, btns);

    function rowStat(label) {
      var v = h('td', { class: 'gv-mg__v gv-num' }, '—');
      return { el: h('tr', null, h('th', { scope: 'row' }, label), v), v: v };
    }
    var sValid = rowStat('Годных показаний');
    var sMae = rowStat('Средняя ошибка шкалы (MAE)');
    var sFps = rowStat('Скорость обработки, кадр/с');
    var sIds = rowStat('Перепутанных идентификаторов');
    var rReg = rowStat('Приборов зарегистрировано (не точность)');
    var rValid = rowStat('Годных показаний от всех');
    var rMed = rowStat('Медианная ошибка шкалы');

    var warn = h('aside', { class: 'gv-mg__warn gv-box', hidden: true, role: 'status' },
      h('span', { class: 'gv-box__legend' }, 'Ограничение N = 16'),
      h('p', null, M.warn16));

    var srcMg = C.src.multigauge;
    var aside = h('div', { class: 'gv-mg__aside' },
      h('div', { class: 'gv-mg__ctl' },
        h('p', { class: 'gv-label' }, 'Приборов на кадре'),
        seg),
      h('table', { class: 'gv-mg__table' },
        h('caption', { class: 'gv-visually-hidden' }, 'Метрики распознавания нескольких приборов'),
        h('tbody', null,
          h('tr', { class: 'gv-mg__gh' }, h('th', { colspan: '2', scope: 'colgroup' }, 'Синтетический щит: панорама, перекрытие, затемнение')),
          sValid.el, sMae.el, sFps.el, sIds.el,
          h('tr', { class: 'gv-mg__gh' }, h('th', { colspan: '2', scope: 'colgroup' }, 'Мозаики реальных фото MeterFL, выборка final')),
          rReg.el, rValid.el, rMed.el)),
      warn,
      h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: srcMg.href }, srcMg.label)));

    var figMain = h('figure', { class: 'gv-mg__fig' },
      frame,
      h('figcaption', { class: 'gv-mg__cap gv-caption' },
        h('span', { class: 'gv-mark', 'data-tone': 'measured' }, C.labels.synthetic), ' ', M.imgNote));

    var hmi = h('figure', { class: 'gv-shot gv-mg__hmi', 'data-reveal': '' },
      h('div', { class: 'gv-shot__frame gv-plate' },
        h('img', { src: M.hmi.img, alt: 'Вкладка «Щит» пульта GaugeVision 3.0', loading: 'lazy', decoding: 'async', width: 1600, height: 900 })),
      h('figcaption', { class: 'gv-caption' },
        h('span', { class: 'gv-mark', 'data-tone': 'done' }, C.labels.real), ' ', M.hmi.caption));

    body.appendChild(h('div', { class: 'gv-mg' },
      h('div', { class: 'gv-mg__main', 'data-reveal': '' }, figMain, aside),
      h('p', { class: 'gv-mg__claim', 'data-reveal': '' }, M.claim),
      hmi));

    function spark(i) {
      var pts = [];
      for (var k = 0; k <= 40; k++) pts.push((k * 5) + ' ' + (30 - (Math.sin(k * 0.45 + i) * 9 + Math.sin(k * 1.3 + i * 3) * 4)).toFixed(1));
      return s('svg', { class: 'gv-mg__spark', viewBox: '0 0 200 60', 'aria-hidden': 'true' }, s('path', { d: 'M' + pts.join('L') }));
    }

    var activeSpot = null;
    function openCard(sp, i, btn) {
      if (activeSpot) activeSpot.removeAttribute('data-on');
      activeSpot = btn;
      btn.setAttribute('data-on', '');
      card.textContent = '';
      card.appendChild(h('p', { class: 'gv-mg__card-code gv-mono' }, sp.code));
      card.appendChild(h('p', { class: 'gv-mg__card-v gv-num' }, sp.v, h('span', null, ' ' + sp.unit)));
      card.appendChild(spark(i));
      card.appendChild(h('p', { class: 'gv-mg__card-note' }, 'Показание — с разметки кадра; график истории — иллюстрация'));
      var right = sp.x < 0.55;
      card.style.left = right ? 'calc(' + (sp.x * 100) + '% + 2rem)' : '';
      card.style.right = right ? '' : 'calc(' + ((1 - sp.x) * 100) + '% + 2rem)';
      card.style.top = 'calc(' + (sp.y * 100) + '% - 2.5rem)';
      card.hidden = false;
    }

    function renderSpots() {
      spots.textContent = '';
      spotBtns = [];
      card.hidden = true;
      activeSpot = null;
      if (count !== 8) return;
      SPOTS8.forEach(function (sp, i) {
        var b = h('button', {
          class: 'gv-mg__spot',
          type: 'button',
          style: { left: (sp.x * 100) + '%', top: (sp.y * 100) + '%' },
          'aria-label': sp.code + ': показать показание с кадра'
        }, h('span', { class: 'gv-mg__spot-dot', 'aria-hidden': 'true' }));
        sc.on(b, 'click', function () { openCard(sp, i, b); });
        spots.appendChild(b);
        spotBtns.push(b);
      });
    }

    function setCount(n) {
      if (!M.images[n]) return;
      count = n;
      btns.forEach(function (b) { b.setAttribute('aria-pressed', Number(b.getAttribute('data-n')) === n ? 'true' : 'false'); });
      var nextSrc = M.images[n];
      if (nextSrc !== shownSrc) {
        shownSrc = nextSrc;
        var back = front === imgA ? imgB : imgA;
        var prev = front;
        var swap = function () {
          if (shownSrc !== nextSrc) return;
          back.style.opacity = '1';
          prev.style.opacity = '0';
          front = back;
        };
        back.onload = swap;
        back.src = nextSrc;
        if (back.complete && back.naturalWidth > 0) swap();
      }
      var syn = M.synthetic[n], real = M.real[n];
      sValid.v.textContent = syn.valid;
      sMae.v.textContent = syn.mae;
      sFps.v.textContent = syn.fps;
      sIds.v.textContent = String(syn.ids);
      rReg.v.textContent = real.reg;
      rValid.v.textContent = real.valid;
      rMed.v.textContent = real.median;
      warn.hidden = n !== 16;
      frame.setAttribute('aria-label', 'Синтетическая панель из ' + n + ' приборов с разметкой конвейера');
      renderSpots();
    }

    function openSpot(i) {
      if (count !== 8) setCount(8);
      if (spotBtns[i] && SPOTS8[i]) openCard(SPOTS8[i], i, spotBtns[i]);
    }

    btns.forEach(function (b) { sc.on(b, 'click', function () { setCount(Number(b.getAttribute('data-n'))); }); });
    sc.on(document, 'keydown', function (e) {
      if (e.key === 'Escape' && !card.hidden) { card.hidden = true; if (activeSpot) activeSpot.removeAttribute('data-on'); }
    });
    setCount(count);

    return { destroy: function () { sc.destroy(); body.textContent = ''; }, setCount: setCount, openSpot: openSpot };
  }

  GV.components.multigauge = { mount: mount };
})();
