/*
 * GV.components.contact — лист 11 «Журнал открыт на GitHub» (сдача смены).
 * «Смену сдал — обходчик» рукой, «Смену принял — GaugeVision AI 3.0» печатью с датой/временем.
 * Ниже — главная штамп-кнопка GitHub, запуск демонстрации и ссылки на тег v3.0.0, ветку,
 * итоговый отчёт, пилот на GitHub и лицензию. Контакты — только GitHub.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(body, opts) {
    var u = GV.util, kit = GV.kit, motion = GV.motion, h = u.h;
    var c = GV.content, t = c.contact;
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
    var extras = t.links.filter(function (l) { return !l.primary; });
    var cta = kit.extLink({ class: 'gv-stamp gv-close__cta', href: repo.href },
      kit.icon('github'),
      h('span', { class: 'gv-close__cta-t' }, repo.label, h('span', { class: 'gv-stamp__sub' }, c.meta.repoLabel)));
    sc.add(motion.magnet(cta, { pull: 0.22, max: 0.5 }));

    var demoBtn = h('button', { class: 'gv-btn-paper', type: 'button', 'data-showcase-open': '' }, 'Запустить демонстрацию');

    body.appendChild(handover);
    body.appendChild(h('div', { class: 'gv-close__act', 'data-reveal': '' },
      h('p', { class: 'gv-close__lead' }, kit.marked(t.lead, t.leadAccent)),
      h('div', { class: 'gv-close__btns' }, cta, demoBtn),
      h('ul', { class: 'gv-close__links', role: 'list' }, extras.map(function (l) {
        return h('li', null, kit.extLink({ class: 'gv-close__license', href: l.href }, l.label));
      }))));

    sc.observe(u.onVisible(handover, function () {
      sign();
      handed.classList.add('is-written');
      handover.classList.add('gv-stamped');
    }, { once: true, threshold: 0.4 }));
    accepted.firstChild.style.setProperty('--gv-stamp-delay', '900ms');

    return { destroy: sc.destroy };
  }

  GV.components.contact = { mount: mount };
})();
