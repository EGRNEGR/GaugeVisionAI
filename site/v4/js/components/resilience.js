/*
 * GV.components.resilience — интерактивная симуляция Store-and-Forward.
 * mount(el) → { destroy(), cut(), restore(), reset() }
 *
 * Локальный узел выпускает показания 4 раза в секунду (номер последовательности seq). Пока канал есть,
 * пакет летит по линии и доставляется. «Отключить связь» — линия рвётся, распознавание продолжается,
 * пакеты складываются в очередь (столбик блоков, счётчик). «Восстановить» — очередь уходит со скоростью
 * 24 в секунду в исходном порядке, затем режим возвращается к норме. Пакеты в полёте в момент обрыва
 * не подтверждены и возвращаются в голову очереди. Счётчики: выпущено, доставлено,
 * в очереди, последний доставленный seq и пропуски (всегда 0 — проверяется по порядку доставки).
 * Цикл кадра работает только при видимой секции. Это симуляция; доказательство — цифры испытания soak.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var RATE = 4;        // показаний в секунду
  var DRAIN = 24;      // досылка из очереди, сообщений в секунду
  var FLIGHT = 0.9;    // секунд полёта пакета по линии
  var STACK_MAX = 48;  // видимых блоков очереди

  function mount(el) {
    var u = GV.util, h = u.h, kit = GV.kit, motion = GV.motion;
    var C = GV.content, R = C.resilience;
    var sc = kit.scope();
    var fmt = function (n) { return u.formatNumber(n, 0); };

    var state = 'ok'; // ok | down | drain | done
    var seq = 0, delivered = 0, lastSeq = 0, gaps = 0, acc = 0, drainAcc = 0;
    var queue = [];
    var flying = [];

    var lane = h('div', { class: 'gv-sf__lane' });
    var breakMark = h('span', { class: 'gv-sf__break', 'aria-hidden': 'true' });
    var stack = h('div', { class: 'gv-sf__stack', 'aria-hidden': 'true' });
    var qCount = h('span', { class: 'gv-sf__qn' }, '0');
    var edgeTick = h('span', { class: 'gv-sf__pulse', 'aria-hidden': 'true' });

    var nEdge = h('div', { class: 'gv-sf__node gv-sf__node--edge' },
      edgeTick,
      h('p', { class: 'gv-sf__nt' }, R.nodes.edge), h('p', { class: 'gv-sf__ns' }, R.nodes.edgeSub),
      h('div', { class: 'gv-sf__queue' }, stack, h('p', { class: 'gv-sf__ql' }, 'в очереди ', qCount)));
    var nBroker = h('div', { class: 'gv-sf__node gv-sf__node--broker' },
      h('p', { class: 'gv-sf__nt' }, R.nodes.broker), h('p', { class: 'gv-sf__ns' }, R.nodes.brokerSub));
    var link = h('div', { class: 'gv-sf__link' }, h('span', { class: 'gv-sf__wire' }), lane, breakMark, h('span', { class: 'gv-sf__linklabel' }, R.nodes.link));

    var status = h('p', { class: 'gv-sf__status', role: 'status', 'aria-live': 'polite' }, R.states.ok);
    function counter(label) { var v = h('span', { class: 'gv-sf__cv' }, '0'); return { el: h('div', { class: 'gv-sf__c' }, v, h('span', { class: 'gv-sf__cl' }, label)), v: v }; }
    var cMade = counter('показаний сформировано'), cDel = counter('доставлено'), cLast = counter('последний seq у получателя'), cGap = counter('пропусков');

    var btnCut = h('button', { class: 'gv-btn gv-btn--danger', type: 'button' }, R.controls.cut);
    var btnRestore = h('button', { class: 'gv-btn gv-btn--primary', type: 'button', disabled: true }, R.controls.restore);
    var btnReset = h('button', { class: 'gv-btn gv-btn--ghost', type: 'button' }, R.controls.reset);

    var srcSoak = C.src[R.proofSource];
    var proof = h('div', { class: 'gv-sf__proof' },
      h('p', { class: 'gv-sf__proof-title' }, h('span', { class: 'gv-chip gv-chip--evidence' }, 'Испытание soak v3.0'), ' Что показали измерения'),
      h('dl', { class: 'gv-sf__plist' }, R.proof.map(function (p) {
        return h('div', { class: 'gv-sf__pi' }, h('dt', null, p.value), h('dd', null, h('span', null, p.label), h('small', null, p.note)));
      })),
      h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: srcSoak.href }, srcSoak.label)));

    var sim = h('div', { class: 'gv-sf__sim', 'data-state': 'ok' },
      h('p', { class: 'gv-sf__badge' }, h('span', { class: 'gv-chip gv-chip--sim' }, C.labels.sim)),
      h('div', { class: 'gv-sf__diagram' }, nEdge, link, nBroker),
      status,
      h('div', { class: 'gv-sf__counters' }, cMade.el, cDel.el, cLast.el, cGap.el),
      h('div', { class: 'gv-sf__controls' }, btnCut, btnRestore, btnReset),
      h('p', { class: 'gv-cap' }, R.simNote));

    el.appendChild(h('div', { class: 'gv-sf' }, sim, proof));

    function setState(s2) {
      state = s2;
      sim.setAttribute('data-state', s2);
      status.textContent = R.states[s2];
      btnCut.disabled = s2 === 'down' || s2 === 'drain';
      btnRestore.disabled = s2 !== 'down';
    }

    function spawnPacket(n) {
      var p = h('span', { class: 'gv-sf__pkt' });
      lane.appendChild(p);
      flying.push({ el: p, t: 0, seq: n });
    }

    function pushQueue(n) {
      queue.push(n);
      if (stack.childElementCount < STACK_MAX) stack.appendChild(h('span', { class: 'gv-sf__blk' }));
      qCount.textContent = fmt(queue.length);
    }

    function deliver(n) {
      if (n !== lastSeq + 1) gaps++;
      lastSeq = n;
      delivered++;
    }

    function paintCounters() {
      cMade.v.textContent = fmt(seq);
      cDel.v.textContent = fmt(delivered);
      cLast.v.textContent = lastSeq ? fmt(lastSeq) : '—';
      cGap.v.textContent = fmt(gaps);
      qCount.textContent = fmt(queue.length);
    }

    function step(dt) {
      // Распознавание идёт всегда, связь не влияет
      acc += dt * RATE;
      while (acc >= 1) {
        acc -= 1;
        seq++;
        edgeTick.classList.remove('is-on'); void edgeTick.offsetWidth; edgeTick.classList.add('is-on');
        if (state === 'down' || state === 'drain' || queue.length) pushQueue(seq);
        else spawnPacket(seq);
      }
      if (state === 'drain' || (state === 'done' && queue.length)) {
        drainAcc += dt * DRAIN;
        while (drainAcc >= 1 && queue.length) {
          drainAcc -= 1;
          spawnPacket(queue.shift());
          if (stack.lastChild && stack.childElementCount > Math.min(queue.length, STACK_MAX)) stack.removeChild(stack.lastChild);
        }
        if (!queue.length && state === 'drain') setState('done');
      }
      var w = lane.clientWidth || 300;
      for (var i = flying.length - 1; i >= 0; i--) {
        var f = flying[i];
        f.t += dt / FLIGHT;
        if (f.t >= 1) { f.el.remove(); flying.splice(i, 1); deliver(f.seq); continue; }
        f.el.style.transform = 'translate3d(' + (f.t * w).toFixed(1) + 'px,0,0)';
      }
      paintCounters();
    }

    var offFrame = null, visible = false;
    function wake() { if (!offFrame && visible) offFrame = motion.onFrame(step); }
    function sleep() { if (offFrame) { offFrame(); offFrame = null; } }
    sc.add(u.onVisible(sim, function (vis) { visible = vis; if (vis) wake(); else sleep(); }, { threshold: 0.15 }));
    sc.add(sleep);

    /* Обрыв: всё, что в полёте, брокер не подтвердил — пакеты сразу возвращаются в голову очереди
       по возрастанию seq. Поэтому после досылки порядок у получателя непрерывный. */
    function cut() {
      if (state === 'down' || state === 'drain') return;
      var back = flying.map(function (f) { f.el.remove(); return f.seq; }).sort(function (a, b) { return a - b; });
      flying = [];
      queue = back.concat(queue);
      back.forEach(function () { if (stack.childElementCount < STACK_MAX) stack.appendChild(h('span', { class: 'gv-sf__blk' })); });
      setState('down');
      paintCounters();
    }
    function restore() { if (state !== 'down') return; drainAcc = 0; setState('drain'); }
    function reset() {
      flying.forEach(function (f) { f.el.remove(); });
      flying = []; queue = []; stack.textContent = '';
      seq = delivered = lastSeq = gaps = 0; acc = drainAcc = 0;
      setState('ok'); paintCounters();
    }
    sc.on(btnCut, 'click', cut);
    sc.on(btnRestore, 'click', restore);
    sc.on(btnReset, 'click', reset);
    if (motion.reduced()) { visible = true; }
    paintCounters();

    return { destroy: function () { sc.destroy(); el.textContent = ''; }, cut: cut, restore: restore, reset: reset };
  }

  GV.components.resilience = { mount: mount };
})();
