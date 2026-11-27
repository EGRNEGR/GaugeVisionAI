/*
 * GV.components.multigauge — «Одна камера. Несколько приборов.»
 * mount(el) → { destroy(), setCount(n) }
 *
 * Переключатель 1 / 2 / 4 / 8 / 16 меняет кадр синтетической панели с реальной разметкой конвейера
 * (tests/test_multigauge.py) — два слоя <img> с перекрёстным проявлением, кадр не прыгает (aspect-ratio).
 * Справа — метрики выбранного N из MULTI_GAUGE_VALIDATION: синтетика (годных, MAE, кадр/с, ID Switch)
 * и мозаики реальных фото MeterFL (регистрация, годных, медиана). При 16 — честное предупреждение.
 * При N = 8 приборы на кадре — кнопки: выбранный раскрывает карточку с кодом, показанием с кадра и
 * историей (история — иллюстрация, помечена).
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  /* Центры приборов и показания с плашек конвейера на кадре mg-08.jpg (1280×720). */
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

  function mount(el) {
    var u = GV.util, h = u.h, s = u.svg, kit = GV.kit;
    var C = GV.content, M = C.multigauge;
    var sc = kit.scope();
    var count = M.initial;

    var imgA = h('img', { class: 'gv-mg__img', alt: '', decoding: 'async', loading: 'lazy', src: M.images[count] });
    var imgB = h('img', { class: 'gv-mg__img', alt: '', decoding: 'async', loading: 'lazy' });
    imgB.style.opacity = '0';
    var front = imgA;
    var spots = h('div', { class: 'gv-mg__spots' });
    var card = h('div', { class: 'gv-mg__card', hidden: true });
    var frame = h('div', { class: 'gv-mg__frame' }, imgA, imgB, spots, card,
      h('span', { class: 'gv-mg__badge' }, C.labels.synthetic));

    var btns = M.counts.map(function (n) {
      return h('button', { class: 'gv-seg__btn', type: 'button', 'aria-pressed': n === count ? 'true' : 'false', 'data-n': n },
        h('span', { class: 'gv-seg__num' }, String(n)), h('span', { class: 'gv-visually-hidden' }, ' приборов'));
    });
    var seg = h('div', { class: 'gv-seg', role: 'group', 'aria-label': 'Приборов на кадре' }, btns);

    function stat(label) { var v = h('span', { class: 'gv-mg__v' }, '—'); return { el: h('div', { class: 'gv-mg__stat' }, v, h('span', { class: 'gv-mg__l' }, label)), v: v }; }
    var sValid = stat('годных показаний'), sMae = stat('средняя ошибка шкалы'), sFps = stat('кадров в секунду'), sIds = stat('перепутанных ID');
    var rReg = stat('приборов зарегистрировано'), rValid = stat('годных от всех'), rMed = stat('медианная ошибка');
    var warn = h('p', { class: 'gv-mg__warn', hidden: true }, M.warn16);
    var srcMg = C.src.multigauge;
    var aside = h('div', { class: 'gv-mg__aside' },
      h('p', { class: 'gv-mg__label' }, 'Приборов на кадре'), seg,
      h('div', { class: 'gv-mg__group' },
        h('p', { class: 'gv-mg__gtitle' }, 'Синтетический щит: панорама, выпадение кадров, перекрытие, затемнение'),
        h('div', { class: 'gv-mg__stats' }, sValid.el, sMae.el, sFps.el, sIds.el)),
      h('div', { class: 'gv-mg__group' },
        h('p', { class: 'gv-mg__gtitle' }, 'Мозаики реальных фотографий MeterFL, контрольная выборка'),
        h('div', { class: 'gv-mg__stats gv-mg__stats--3' }, rReg.el, rValid.el, rMed.el)),
      warn,
      h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: srcMg.href }, srcMg.label)));

    var hmi = h('figure', { class: 'gv-shot gv-mg__hmi' },
      h('img', { src: M.hmi.img, alt: 'Вкладка «Щит» пульта GaugeVision 3.0', loading: 'lazy', decoding: 'async', width: 1600, height: 900 }),
      h('figcaption', null, h('span', { class: 'gv-chip gv-chip--real' }, C.labels.record), ' ', M.hmi.caption));

    el.appendChild(h('div', { class: 'gv-mg' },
      h('div', { class: 'gv-mg__main' }, h('figure', { class: 'gv-mg__fig' }, frame, h('figcaption', { class: 'gv-mg__cap' }, M.imgNote)), aside),
      h('p', { class: 'gv-mg__claim' }, M.claim),
      hmi));

    function renderSpots() {
      spots.textContent = '';
      card.hidden = true;
      if (count !== 8) return;
      SPOTS8.forEach(function (sp, i) {
        var b = h('button', { class: 'gv-mg__spot', type: 'button', style: { left: (sp.x * 100) + '%', top: (sp.y * 100) + '%' }, 'aria-label': sp.code + ': показать историю' });
        sc.on(b, 'click', function () { openCard(sp, i, b); });
        spots.appendChild(b);
      });
    }

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
      card.appendChild(h('p', { class: 'gv-mg__card-code' }, sp.code));
      card.appendChild(h('p', { class: 'gv-mg__card-v' }, sp.v, h('span', null, ' ' + sp.unit)));
      card.appendChild(spark(i));
      card.appendChild(h('p', { class: 'gv-mg__card-note' }, 'Показание — с разметки кадра; линия истории — иллюстрация'));
      var right = sp.x < 0.6;
      card.style.left = right ? 'calc(' + (sp.x * 100) + '% + 3.5rem)' : '';
      card.style.right = right ? '' : 'calc(' + ((1 - sp.x) * 100) + '% + 3.5rem)';
      card.style.top = 'calc(' + (sp.y * 100) + '% - 3rem)';
      card.hidden = false;
    }

    function setCount(n) {
      if (!M.images[n]) return;
      count = n;
      btns.forEach(function (b) { b.setAttribute('aria-pressed', Number(b.getAttribute('data-n')) === n ? 'true' : 'false'); });
      var back = front === imgA ? imgB : imgA;
      back.src = M.images[n];
      var swap = function () { back.style.opacity = '1'; front.style.opacity = '0'; front = back; };
      if (back.complete) swap(); else back.onload = swap;
      var syn = M.synthetic[n], real = M.real[n];
      sValid.v.textContent = syn.valid; sMae.v.textContent = syn.mae; sFps.v.textContent = syn.fps; sIds.v.textContent = String(syn.ids);
      rReg.v.textContent = real.reg; rValid.v.textContent = real.valid; rMed.v.textContent = real.median;
      warn.hidden = n !== 16;
      frame.setAttribute('aria-label', 'Синтетическая панель из ' + n + ' приборов с разметкой конвейера');
      renderSpots();
    }

    btns.forEach(function (b) { sc.on(b, 'click', function () { setCount(Number(b.getAttribute('data-n'))); }); });
    sc.on(document, 'keydown', function (e) { if (e.key === 'Escape' && !card.hidden) { card.hidden = true; if (activeSpot) activeSpot.removeAttribute('data-on'); } });
    setCount(count);

    return { destroy: function () { sc.destroy(); el.textContent = ''; }, setCount: setCount };
  }

  GV.components.multigauge = { mount: mount };
})();
