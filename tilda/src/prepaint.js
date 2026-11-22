/* Tilda: класс gvt-page включает стили уровня страницы (масштаб, линовка, красное поле, скроллбар) —
   везде, кроме редактора Tilda. Настройки Tweaks — до первой отрисовки, без скачка вёрстки, как в site/index.html.
   Кнопку Tweaks видит только автор: адрес с ?tweaks включает её на этом устройстве, ?tweaks=off — выключает. */
(function () {
  var d = document.documentElement;
  var editor = /(^|\.)tilda\.(ru|cc)$/.test(location.hostname) && !/\/preview\//.test(location.pathname);
  if (editor) return;
  d.classList.add('gvt-page');
  var q = location.search;
  var on = /[?&]tweaks(=on|=1)?(&|$)/.test(q);
  var off = /[?&]tweaks=off(&|$)/.test(q);
  try {
    if (on) localStorage.setItem('gv.tweaks.on', '1');
    if (off) localStorage.removeItem('gv.tweaks.on');
    if (localStorage.getItem('gv.tweaks.on') === '1') d.setAttribute('data-tweaks', 'on');
    var t = JSON.parse(localStorage.getItem('gv.tweaks') || '{}');
    if ([0.9, 1, 1.1, 1.25].indexOf(t.scale) >= 0) d.style.setProperty('--ui-scale', String(t.scale));
    if (['ledger', 'graph', 'tracing'].indexOf(t.paper) >= 0) d.setAttribute('data-paper', t.paper);
  } catch (e) {
    if (on) d.setAttribute('data-tweaks', 'on');
  }
})();
