/*
 * GV.components.contact — лист 08 «Журнал открыт на GitHub».
 * Сдача смены двумя строками журнала: «Смену сдал — обходчик» его рукой, «Смену принял —
 * GaugeVision AI» печатью. Под ними одно главное действие — штамп «Код на GitHub» с адресом
 * репозитория — и проприетарная лицензия. Других контактов нет (PRODUCT.md).
 *
 *   mount(body, { reading }) → { destroy }   reading — общее показание: считает записи посетителя
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  function mount(body, opts) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var t = c.contact;
    var sc = kit.scope();

    body.classList.add('gv-close');

    var handed = h('span', { class: 'gv-write gv-hand gv-close__sign' }, t.handedBy);
    var stampTime = h('time', { class: 'gv-close__time gv-num' });
    var mine = h('span', { class: 'gv-close__mine' });
    var accepted = h('span', { class: 'gv-close__seal' },
      h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': 'measured' }, t.acceptedBy), stampTime, mine);
    var entries = 0;
    function sign() {
      var now = new Date();
      var p2 = function (n) { return String(n).padStart(2, '0'); };
      stampTime.textContent = p2(now.getDate()) + '.' + p2(now.getMonth() + 1) + '.' + now.getFullYear() + ', ' + p2(now.getHours()) + ':' + p2(now.getMinutes());
      stampTime.setAttribute('datetime', now.toISOString());
      mine.textContent = entries ? t.yourEntries + ': ' + entries : '';
    }
    if (opts && opts.reading) sc.add(opts.reading.onCommit(function () { entries += 1; sign(); }));
    var handover = h('dl', { class: 'gv-close__handover', 'data-reveal': '' },
      h('div', { class: 'gv-close__line' }, h('dt', { class: 'gv-label' }, t.handedLabel), h('dd', null, handed)),
      h('div', { class: 'gv-close__line' }, h('dt', { class: 'gv-label' }, t.acceptedLabel), h('dd', null, accepted)));

    var repo = t.links.filter(function (l) { return l.primary; })[0];
    var license = t.links.filter(function (l) { return !l.primary; })[0];
    var cta = kit.extLink({ class: 'gv-stamp gv-close__cta', href: repo.href },
      kit.icon('github'),
      h('span', { class: 'gv-close__cta-t' }, repo.label, h('span', { class: 'gv-stamp__sub' }, c.meta.repoLabel)));
    sc.add(motion.magnet(cta, { pull: 0.22, max: 0.5 }));

    body.appendChild(handover);
    body.appendChild(h('div', { class: 'gv-close__act', 'data-reveal': '' },
      h('p', { class: 'gv-close__lead' }, t.lead),
      cta,
      kit.extLink({ class: 'gv-close__license', href: license.href }, license.label)));

    sc.observe(u.onVisible(handover, function () {
      sign();
      handed.classList.add('is-written');
      handover.classList.add('gv-stamped');
    }, { once: true, threshold: 0.5 }));
    accepted.firstChild.style.setProperty('--gv-stamp-delay', '900ms');

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.contact = { mount: mount };
})();
