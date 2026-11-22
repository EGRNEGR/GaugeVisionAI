/*
 * GV.components.journal — первый лист: «Прибор пишет журнал сам».
 * Слева h1 и живой журнал смены: строка обходчика 08:00 его рукой, ниже машинные строки камеры
 * каждые ⅓ с (PROCESS_FPS = 3). Справа — вклеенный кадр камеры: эмалевый прибор, стрелку тянут мышью,
 * пальцем или стрелками клавиатуры. Камера «читает» отображаемую стрелку: к углу добавляется дрожь
 * вибрации, значение сглаживает EMA α = 0,25 — как в app/vision.py, поэтому строки догоняют рывок.
 *
 * Демонстрационные данные (время смены, бирка МН-1, амплитуда дрожи) — здесь, а не в content.js:
 * это не факты продукта, и страница подписывает их как демонстрацию (hero.demo).
 * reading — общее показание страницы: чертёж листа 03 двигает эту же стрелку и пишет строки «вы».
 *
 * Журнал хранит историю (KEEP строк) и прокручивается. Пока посетитель следит за концом, новые строки
 * въезжают снизу. Ручная прокрутка (колесо, палец, полоса прокрутки) ставит слежение на паузу: строки
 * дописываются в конец, не сдвигая читаемое, а у края появляется «К новым записям». Через IDLE_MS
 * без прокрутки, по кнопке или когда посетитель сам вернулся в конец, журнал плавно доезжает
 * до свежих строк и снова следит за ними.
 *
 *   mount(body, { section, sheet, reading, headId }) → { destroy }
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  var SHIFT_START = 8 * 3600000;   // 08:00 — начало демонстрационной смены
  var FRAME_MS = 1000 / 3;         // PROCESS_FPS = 3,0 (app/config.py)
  var ROWS = 6;                    // машинных строк в окне журнала
  var KEEP = 360;                  // строк истории: две минуты смены при 3 строках в секунду
  var SPARE = 180;                 // запас на паузе, пока посетитель листает историю
  var IDLE_MS = 4000;              // без прокрутки столько — журнал возвращается к свежим строкам
  var INTENT_MS = 400;             // прокрутка в этом окне после колеса, касания или нажатия — ручная
  var TAG = 'МН-1';                // бирка демонстрационного манометра
  var JITTER = 0.6;                // дрожь стрелки от вибрации, ± градусы
  var ALPHA = 0.25;                // EMA_ALPHA (app/config.py)

  function mount(body, opts) {
    var u = GV.util;
    var kit = GV.kit;
    var motion = GV.motion;
    var h = u.h;
    var c = GV.content;
    var t = c.hero;
    var calib = c.calibration;
    var reading = opts.reading;
    var sc = kit.scope();
    var fmt = u.formatNumber;
    var fine = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    body.classList.add('gv-hero');

    /* ---------- заголовок, суть, действия ---------- */

    var words = t.title.split(' ');
    var cut = Math.ceil(words.length / 2);
    var title = h('h1', { class: 'gv-hero__title', id: opts.headId, 'data-reveal': 'words' },
      h('span', { class: 'gv-hero__l1' }, words.slice(0, cut).join(' ')), ' ',
      h('span', { class: 'gv-hero__l2' }, words.slice(cut).join(' ')));
    var line = h('p', { class: 'gv-hero__line', 'data-reveal': '' }, t.line);

    var cta = kit.extLink({ class: 'gv-stamp gv-hero__cta', href: c.meta.repoUrl }, kit.icon('github'), h('span', null, t.cta));
    var next = h('a', { class: 'gv-arrow-link', href: '#compare' }, h('span', null, t.ctaNext), kit.icon('arrow'));
    var actions = h('div', { class: 'gv-hero__actions', 'data-reveal': '' }, cta, next);
    sc.add(motion.magnet(cta, { pull: 0.2, max: 0.375 }));

    /* ---------- журнал ---------- */

    function cell(cls, content) {
      return h('span', { class: 'gv-log__c gv-log__c--' + cls, role: 'cell' }, content);
    }
    var head = h('div', { class: 'gv-log__row gv-log__row--head', role: 'row' },
      t.columns.map(function (col, i) {
        return h('span', { class: 'gv-log__c gv-log__c--' + ['time', 'tag', 'value', 'who'][i], role: 'columnheader' }, col);
      }));

    function handWrite(text, delay) {
      return h('span', { class: 'gv-write gv-hand', style: { '--gv-write-delay': delay + 'ms' } }, text);
    }
    var handVal = angleText(kit.angleToValue(reading.get(), calib), 1);
    var handRow = h('div', { class: 'gv-log__row gv-log__row--hand', role: 'row' },
      cell('time', handWrite('08:00', 300)),
      cell('tag', handWrite(TAG, 700)),
      cell('value', handWrite(handVal, 1000)),
      cell('who', handWrite(t.hand, 1400)));

    var stream = h('div', { class: 'gv-log__stream', 'aria-hidden': 'true' });
    var scroller = h('div', { class: 'gv-log__scroll' });
    var track = h('div', { class: 'gv-log__track' });
    scroller.appendChild(track);
    stream.appendChild(scroller);
    var freshCount = h('span', { class: 'gv-log__fresh-n gv-num' });
    var fresh = h('button', { class: 'gv-log__fresh', type: 'button', hidden: true },
      kit.icon('arrow'), h('span', null, t.fresh), freshCount);

    var latest = h('p', { class: 'gv-visually-hidden', 'aria-live': 'polite' });
    var log = h('div', { class: 'gv-log', 'data-reveal': '' },
      h('div', { class: 'gv-log__table', role: 'table', 'aria-label': c.meta.form },
        h('div', { role: 'rowgroup' }, head),
        h('div', { role: 'rowgroup' }, handRow),
        stream),
      fresh);
    var demo = h('p', { class: 'gv-hero__demo gv-caption' }, t.demo, '. ', t.rate, '.');

    /* ---------- кадр камеры ---------- */

    var g = kit.gauge({ kind: 'enamel' });
    var dialBox = h('div', {
      class: 'gv-hero__dial',
      role: 'slider',
      tabindex: '0',
      'aria-label': c.reading.sliderLabel,
      'aria-valuemin': String(calib.vMin),
      'aria-valuemax': String(calib.vMax)
    }, g.el);
    var thetaOut = h('span', { class: 'gv-num' });
    var valueOut = h('span', { class: 'gv-num' });
    var dot = h('span', { class: 'gv-hero__dot', 'aria-hidden': 'true' });
    var frame = h('figure', { class: 'gv-hero__frame gv-plate', 'data-reveal': '' },
      h('div', { class: 'gv-hero__frame-bar' },
        h('span', null, t.dialLabel),
        h('span', { class: 'gv-hero__rec' }, dot, TAG)),
      dialBox,
      h('figcaption', { class: 'gv-hero__read' },
        h('span', { class: 'gv-hero__read-k' }, 'θ'), thetaOut,
        h('span', { class: 'gv-hero__read-k' }, 'V'), valueOut),
      h('p', { class: 'gv-hero__hint' }, fine ? t.dialHint : t.dialHintTouch));

    body.appendChild(title);
    body.appendChild(frame);
    body.appendChild(line);
    body.appendChild(actions);
    body.appendChild(log);
    body.appendChild(demo);
    body.appendChild(latest);

    /* рукописная строка проявляется, когда журнал в кадре */
    sc.observe(u.onVisible(log, function () {
      Array.prototype.forEach.call(handRow.querySelectorAll('.gv-write'), function (el) { el.classList.add('is-written'); });
    }, { once: true, threshold: 0.3 }));

    /* ---------- стрелка: пружина, указатель, клавиатура ---------- */

    var spring = motion.spring({ stiffness: 170, damping: 18, value: kit.valueToAngle(calib.vMin, calib), precision: 0.02 });
    var shown = spring.value();

    function clampTheta(theta, prev) {
      var comp = GV.components.precisionDial;
      return comp && comp.clampAngle ? comp.clampAngle(theta, calib, prev) : theta;
    }
    function angleText(v, digits) {
      return fmt(v, digits);
    }
    function paintNeedle(theta) {
      theta = clampTheta(theta);
      g.setAngle(theta);
      var v = kit.angleToValue(theta, calib);
      thetaOut.textContent = fmt(((theta % 360) + 360) % 360, 1) + '°';
      valueOut.textContent = fmt(v, 2) + kit.NBSP + calib.unit;
      dialBox.setAttribute('aria-valuenow', v.toFixed(2));
      dialBox.setAttribute('aria-valuetext', fmt(v, 2) + ' ' + calib.unit);
    }

    var offSpring = null;
    function wakeSpring() {
      if (offSpring) return;
      offSpring = motion.onFrame(function (dt) {
        shown = spring.step(dt);
        paintNeedle(shown);
        if (spring.settled()) { offSpring(); offSpring = null; }
      });
    }
    sc.add(function () { if (offSpring) offSpring(); });

    function aim(theta) {
      spring.target(theta);
      wakeSpring();
    }
    sc.add(reading.on(function (theta) { aim(theta); }));

    /* follow — палец или мышь ведут стрелку: под шкалой она держится края, у которого стоит */
    function pointerTheta(e, follow) {
      var box = g.el.getBoundingClientRect();
      var comp = GV.components.precisionDial;
      return clampTheta(comp.angleFromPointer(e.clientX - (box.left + box.width / 2), e.clientY - (box.top + box.height / 2)),
        follow ? reading.get() : undefined);
    }
    var dragging = false;
    sc.on(dialBox, 'pointerdown', function (e) {
      dragging = true;
      dialBox.setPointerCapture(e.pointerId);
      dialBox.classList.add('is-dragging');
      reading.set(pointerTheta(e), 'hero');
    });
    sc.on(dialBox, 'pointermove', function (e) {
      if (dragging) reading.set(pointerTheta(e, true), 'hero');
    });
    function stop() {
      dragging = false;
      dialBox.classList.remove('is-dragging');
    }
    sc.on(dialBox, 'pointerup', stop);
    sc.on(dialBox, 'pointercancel', stop);
    sc.on(dialBox, 'keydown', function (e) {
      var v = kit.angleToValue(reading.get(), calib);
      var step = e.shiftKey ? 1 : 0.1;
      var nextV = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowUp') nextV = v + step;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') nextV = v - step;
      else if (e.key === 'Home') nextV = calib.vMin;
      else if (e.key === 'End') nextV = calib.vMax;
      if (nextV === null) return;
      e.preventDefault();
      nextV = Math.max(calib.vMin, Math.min(calib.vMax, nextV));
      reading.set(kit.valueToAngle(nextV, calib), 'hero');
    });

    /* ---------- машинные строки ---------- */

    var ema = null;
    var clock = SHIFT_START;
    var phase = Math.random() * 10;
    var rows = [];

    function measure() {
      phase += 1.7;
      var shake = JITTER * (Math.sin(phase) * 0.6 + Math.sin(phase * 2.3 + 1) * 0.4);
      var raw = kit.angleToValue(clampTheta(shown + shake), calib);
      ema = kit.emaStep(ema, raw, ALPHA);
      return ema;
    }

    function rowFor(ms, value, mine) {
      var level = kit.levelOf(value, calib.setpoints);
      var who = [h('span', { class: 'gv-log__machine' }, t.machine)];
      if (level !== 'normal') who.push(h('span', { class: 'gv-mark', 'data-tone': level }, c.reading.zones[level]));
      if (mine) who.push(h('span', { class: 'gv-hand gv-log__mine' }, 'ваша запись'));
      return h('div', { class: 'gv-log__row gv-log__row--machine' + (mine ? ' is-mine' : '') },
        h('span', { class: 'gv-log__c gv-log__c--time' }, kit.clockText(ms)),
        h('span', { class: 'gv-log__c gv-log__c--tag' }, TAG),
        h('span', { class: 'gv-log__c gv-log__c--value gv-num' }, fmt(value, 2)),
        h('span', { class: 'gv-log__c gv-log__c--who' }, who));
    }

    /* ---------- слежение за концом журнала и пауза на ручной прокрутке ---------- */

    var following = true;
    var unseen = 0;
    var intentAt = -Infinity;
    var touching = false;
    var cancelIdle = null;
    var cancelSettle = null;
    function now() { return window.performance ? performance.now() : Date.now(); }
    // конец с допуском в полторы строки: пока колесо доезжает до низа, снизу успевает дописаться строка
    function atEnd() {
      var row = rows.length ? rows[rows.length - 1].offsetHeight : 0;
      return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < row * 1.5 + 2;
    }
    function toEnd() { scroller.scrollTop = scroller.scrollHeight; }
    function showFresh() {
      freshCount.textContent = unseen ? '+' + unseen : '';
      fresh.hidden = following;
    }
    function follow() {
      if (cancelIdle) { cancelIdle(); cancelIdle = null; }
      if (cancelSettle) { cancelSettle(); cancelSettle = null; }
      following = true;
      unseen = 0;
      toEnd();
      showFresh();
    }
    /* плавный проезд к концу; ручная прокрутка во время проезда снова ставит паузу */
    function resume() {
      if (cancelIdle) { cancelIdle(); cancelIdle = null; }
      if (motion.reduced()) { follow(); return; }
      scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
      if (cancelSettle) cancelSettle();
      cancelSettle = sc.timeout(follow, 700);
    }
    function pause() {
      following = false;
      if (cancelSettle) { cancelSettle(); cancelSettle = null; }
      if (cancelIdle) cancelIdle();
      cancelIdle = sc.timeout(resume, IDLE_MS);
      showFresh();
    }
    function intent() { intentAt = now(); }
    sc.on(scroller, 'wheel', intent, { passive: true });
    sc.on(scroller, 'pointerdown', intent);
    sc.on(scroller, 'touchstart', function () { touching = true; intent(); }, { passive: true });
    sc.on(scroller, 'touchend', function () { touching = false; intent(); }, { passive: true });
    sc.on(scroller, 'scroll', function () {
      // прокрутку кодом (строка въехала, проезд к концу) пропускаем: ручная — сразу после жеста
      if (!touching && now() - intentAt > INTENT_MS) return;
      intent(); // инерция пальца продолжает ручную прокрутку
      if (atEnd()) follow();
      else pause();
    }, { passive: true });
    sc.on(fresh, 'click', resume);

    function push(mine, exact) {
      clock += FRAME_MS;
      var value = typeof exact === 'number' ? exact : measure();
      var row = rowFor(clock, value, mine);
      track.appendChild(row);
      rows.push(row);
      if (!following) {
        // на паузе читаемое не двигается: строки дописываются в конец, старые уходят только сверх запаса
        unseen += 1;
        if (rows.length > KEEP + SPARE) {
          var gone = rows.shift();
          var lost = gone.offsetHeight;
          track.removeChild(gone);
          scroller.scrollTop -= lost;
        }
        showFresh();
        return;
      }
      while (rows.length > KEEP) track.removeChild(rows.shift());
      toEnd();
      if (!motion.reduced()) {
        track.style.transition = 'none';
        track.style.transform = 'translate3d(0, var(--row), 0)';
        void track.offsetHeight;
        track.style.transition = '';
        track.style.transform = '';
      }
    }

    // Окно журнала заполнено сразу: строки уже идут, когда посетитель смотрит
    shown = kit.valueToAngle(calib.vMin, calib);
    paintNeedle(shown);
    var startTheta = reading.get();
    shown = startTheta;
    for (var i = 0; i < ROWS; i++) push(false);
    shown = spring.value();
    paintNeedle(shown);

    var visible = false;
    var acc = 0;
    var offTick = null;
    // точка записи вспыхивает на каждом обработанном кадре — живой индикатор потока, а не украшение
    function flash() {
      dot.classList.add('is-frame');
      sc.timeout(function () { dot.classList.remove('is-frame'); }, 90);
    }
    function tick(dt) {
      acc += dt * 1000;
      while (acc >= FRAME_MS) {
        acc -= FRAME_MS;
        push(false);
        flash();
      }
    }
    function syncStream() {
      var run = visible && !document.hidden && !motion.reduced();
      if (run && !offTick) offTick = motion.onFrame(tick);
      if (!run && offTick) { offTick(); offTick = null; acc = 0; }
    }
    sc.observe(u.onVisible(body, function (isIn) {
      visible = isIn;
      syncStream();
    }, { threshold: 0.05 }));
    sc.on(document, 'visibilitychange', syncStream);
    sc.add(function () { if (offTick) offTick(); });

    // Стрелка встаёт на показание при первом показе листа
    sc.timeout(function () { aim(startTheta); }, motion.reduced() ? 0 : 450);

    // При «уменьшить движение» поток стоит: строка обновляется, когда стрелку двигают
    sc.add(reading.on(function () {
      if (motion.reduced()) push(false);
    }));

    // «Записать в журнал» с листа 03: строка с отметкой «вы»
    sc.add(reading.onCommit(function (theta) {
      shown = theta;
      spring.set(theta);
      paintNeedle(theta);
      ema = kit.angleToValue(theta, calib);
      push(true, ema);
      latest.textContent = c.reading.written + ': ' + fmt(ema, 2) + ' ' + calib.unit;
    }));

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.journal = { mount: mount };
})();
