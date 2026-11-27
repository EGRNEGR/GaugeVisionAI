/*
 * GV.components.document — «От показания стрелки — до технического задания».
 * mount(el) → { destroy(), assemble() }
 * Слева — страница ТЗ, собранная из плана оптимизатора (событие 'gv:plan'), данных PI-102 и каталога
 * требований: позиции плана, CAPEX, требования к преобразователям. Текст настоящий и читаемый.
 * При первом появлении строки собираются по очереди (каскад transform + opacity), при смене плана
 * обновляется таблица. Справа — реальный экран конструктора ТЗ пульта 3.0.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit, motion = GV.motion;
    var C = GV.content, D = C.documentSection, F = C.forecast;
    var sc = kit.scope();
    var rub = function (n) { return u.formatNumber(Math.round(n), 0) + ' ₽'; };

    var planBody = h('tbody');
    var reqList = h('ul', { class: 'gv-doc__req', role: 'list' });
    var totalCell = h('td', { class: 'gv-doc__num' });
    var basis = h('p', { class: 'gv-doc__p' });
    var page = h('article', { class: 'gv-doc', 'aria-label': 'Предпросмотр технического задания' },
      h('header', { class: 'gv-doc__head' },
        h('p', { class: 'gv-doc__org' }, 'Служба КИПиА и видеоаналитики GaugeVision AI'),
        h('h3', { class: 'gv-doc__title' }, 'Техническое задание на модернизацию КИПиА'),
        h('p', { class: 'gv-doc__no' }, D.docNumber, h('span', null, 'черновик инженерного проекта'))),
      h('section', { class: 'gv-doc__sec' },
        h('h4', null, '1. Результаты мониторинга'),
        h('p', { class: 'gv-doc__p' }, 'PI-102, давление питательной воды, шкала 0–1,6 МПа: рост ' + u.formatNumber(F.slopeModel, 3) + ' МПа/мин, уставка H ' + u.formatNumber(F.warn, 1) + ' МПа пройдена.'),
        h('p', { class: 'gv-doc__p' }, 'Прогноз достижения HH ' + u.formatNumber(F.alert, 3) + ' МПа — через ' + u.formatNumber(F.eta, 2) + ' мин, интервал ' + u.formatNumber(F.ciLo, 2) + '–' + u.formatNumber(F.ciHi, 2) + ' мин.')),
      h('section', { class: 'gv-doc__sec' },
        h('h4', null, '2. План модернизации'),
        basis,
        h('table', { class: 'gv-doc__table' },
          h('thead', null, h('tr', null, h('th', null, 'Позиция'), h('th', null, 'Мероприятие'), h('th', { class: 'gv-doc__num' }, 'CAPEX'))),
          planBody,
          h('tfoot', null, h('tr', null, h('td', { colspan: 2 }, 'Итого'), totalCell)))),
      h('section', { class: 'gv-doc__sec' },
        h('h4', null, '3. Требования к оборудованию'),
        reqList),
      h('footer', { class: 'gv-doc__foot' }, 'Документ сформирован автоматически и подлежит экспертной проверке. GaugeVision AI не является средством измерений и системой ПАЗ.'));

    el.appendChild(h('div', { class: 'gv-docw' },
      h('div', { class: 'gv-docw__page' },
        h('p', { class: 'gv-docw__badge' }, h('span', { class: 'gv-chip gv-chip--sim' }, 'Собрано из вашего плана'), h('span', { class: 'gv-docw__fmt' }, 'DOCX  Markdown')),
        page,
        h('p', { class: 'gv-cap' }, D.note)),
      h('figure', { class: 'gv-shot gv-shot--lift gv-docw__shot' },
        h('div', { class: 'gv-shot__frame' }, h('img', { src: D.shot.img, alt: 'Конструктор дефектной ведомости и ТЗ в пульте GaugeVision 3.0', loading: 'lazy', decoding: 'async', width: 1600, height: 900 })),
        h('figcaption', null, h('span', { class: 'gv-chip gv-chip--real' }, C.labels.record), ' ', D.shot.caption))));

    function render(plan) {
      var res = plan.res;
      planBody.textContent = '';
      reqList.textContent = '';
      if (res.status !== 'optimal') {
        basis.textContent = 'Бюджет ' + rub(plan.budget) + ' не покрывает обязательные позиции: дефицит ' + rub(res.deficit) + '. План не сформирован.';
        totalCell.textContent = '—';
        return;
      }
      basis.textContent = 'Бюджет ' + rub(plan.budget) + ', выбрано ' + res.picked.length + ' из ' + plan.cands.length + ' позиций; оптимум найден точным перебором.';
      var kinds = {};
      res.picked.forEach(function (code, i) {
        var c = plan.cands.filter(function (x) { return x.code === code; })[0];
        var cat = C.catalog[c.kind];
        kinds[c.kind] = cat;
        planBody.appendChild(h('tr', { style: { '--i': i } }, h('td', null, code), h('td', null, 'Замена на: ' + cat.label.toLowerCase()), h('td', { class: 'gv-doc__num' }, rub(c.capex))));
      });
      totalCell.textContent = rub(res.capex);
      Object.keys(kinds).forEach(function (k) {
        var cat = kinds[k];
        reqList.appendChild(h('li', null, h('strong', null, cat.label), ': сигнал ' + cat.signal + ', погрешность ' + cat.accuracy + ', защита ' + cat.ip + '.'));
      });
    }

    function assemble() {
      page.removeAttribute('data-pending');
      page.removeAttribute('data-built');
      void page.offsetWidth;
      page.setAttribute('data-built', '');
    }

    sc.on(document, 'gv:plan', function (e) { render(e.detail); });
    if (GV.state && GV.state.plan) render(GV.state.plan);
    if (motion.reduced()) page.setAttribute('data-built', '');
    else { page.setAttribute('data-pending', ''); sc.add(u.onVisible(page, function (vis) { if (vis) assemble(); }, { once: true, threshold: 0.12 })); }

    return { destroy: function () { sc.destroy(); el.textContent = ''; }, assemble: assemble };
  }

  GV.components.document = { mount: mount };
})();
