/*
 * GV.components.resilience — лист 04 «Обрыв связи без потери строк».
 * mount(body) → { destroy(), cut(), restore(), reset() }
 *
 * Симуляция очереди Store-and-Forward на миллиметровке (.gv-schema__sheet): 4 сообщения/с, при обрыве
 * пакеты в полёте возвращаются в голову очереди, при восстановлении досылаются со скоростью 24/с без
 * пропусков (gaps = 0). Справа — таблица доказательств 62-минутного испытания soak v3.0.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});
  GV.components = GV.components || {};

  var RATE = 4;
  var DRAIN = 24;
  var FLIGHT = 0.9;
  var STACK_MAX = 40;

  function mount(body) {
    var u = GV.util, h = u.h, kit = GV.kit, motion = GV.motion;
    var C = GV.content, R = C.resilience;
    var sc = kit.scope();
    var fmt = function (n) { return u.formatNumber(n, 0); };

    var state = 'ok';
    var seq = 0, delivered = 0, lastSeq = 0, gaps = 0, acc = 0, drainAcc = 0;
    var queue = [];
    var flying = [];

    var lane = h('div', { class: 'gv-sf__lane' });
    var breakMark = h('span', { class: 'gv-sf__break', 'aria-hidden': 'true' }, 'ОБРЫВ');
    var stack = h('div', { class: 'gv-sf__stack', 'aria-hidden': 'true' });
    var qCount = h('span', { class: 'gv-sf__qn gv-num' }, '0');
    var edgeTick = h('span', { class: 'gv-sf__pulse', 'aria-hidden': 'true' });

    var nEdge = h('div', { class: 'gv-sf__node gv-sf__node--edge' },
      edgeTick,
      h('p', { class: 'gv-sf__nt' }, R.nodes.edge),
      h('p', { class: 'gv-sf__ns' }, R.nodes.edgeSub),
      h('div', { class: 'gv-sf__queue' }, stack, h('p', { class: 'gv-sf__ql' }, 'в очереди: ', qCount)));
    var nBroker = h('div', { class: 'gv-sf__node gv-sf__node--broker' },
      h('p', { class: 'gv-sf__nt' }, R.nodes.broker),
      h('p', { class: 'gv-sf__ns' }, R.nodes.brokerSub));
    var link = h('div', { class: 'gv-sf__link' },
      h('span', { class: 'gv-sf__wire' }),
      lane,
      breakMark,
      h('span', { class: 'gv-sf__linklabel gv-label' }, R.nodes.link));

    var status = h('p', { class: 'gv-sf__status', role: 'status', 'aria-live': 'polite' }, R.states.ok);
    function counter(label) {
      var v = h('span', { class: 'gv-sf__cv gv-num' }, '0');
      return { el: h('div', { class: 'gv-sf__c' }, v, h('span', { class: 'gv-sf__cl' }, label)), v: v };
    }
    var cMade = counter('сформировано');
    var cDel = counter('доставлено');
    var cLast = counter('последний seq');
    var cGap = counter('пропусков');

    var btnCut = h('button', { class: 'gv-btn-paper gv-btn-paper--red', type: 'button' }, R.controls.cut);
    var btnRestore = h('button', { class: 'gv-btn-paper gv-btn-paper--ink', type: 'button', disabled: true }, R.controls.restore);
    var btnReset = h('button', { class: 'gv-filter__b', type: 'button' }, R.controls.reset);

    var srcSoak = C.src[R.proofSource];
    var proof = h('div', { class: 'gv-sf__proof', 'data-reveal': '' },
      h('p', { class: 'gv-sf__proof-head' },
        h('span', { class: 'gv-mark gv-mark--stamp', 'data-tone': 'done' }, C.labels.evidence),
        h('span', { class: 'gv-label' }, 'Испытание soak v3.0')),
      h('dl', { class: 'gv-sf__plist' }, R.proof.map(function (p) {
        return h('div', { class: 'gv-sf__pi' },
          h('dt', { class: 'gv-num' }, p.value),
          h('dd', null, h('strong', null, p.label), h('span', { class: 'gv-caption' }, p.note)));
      })),
      h('p', { class: 'gv-src-line' }, C.labels.source + ': ', kit.extLink({ class: 'gv-src', href: srcSoak.href }, srcSoak.label)));

    var sim = h('div', { class: 'gv-sf__sim gv-graph-sheet', 'data-state': 'ok', 'data-reveal': '' },
      h('p', { class: 'gv-sf__badge' }, h('span', { class: 'gv-mark', 'data-tone': 'warning' }, C.labels.sim)),
      h('div', { class: 'gv-sf__diagram' }, nEdge, link, nBroker),
      status,
      h('div', { class: 'gv-sf__counters' }, cMade.el, cDel.el, cLast.el, cGap.el),
      h('div', { class: 'gv-sf__controls' }, btnCut, btnRestore, btnReset),
      h('p', { class: 'gv-caption' }, R.simNote));

    body.appendChild(h('div', { class: 'gv-sf' }, sim, proof));
    sc.observe(u.onVisible(proof, function () { proof.classList.add('gv-stamped'); }, { once: true, threshold: 0.2 }));

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
      acc += dt * RATE;
      while (acc >= 1) {
        acc -= 1;
        seq++;
        edgeTick.classList.remove('is-on');
        void edgeTick.offsetWidth;
        edgeTick.classList.add('is-on');
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
      var w = lane.clientWidth || 260;
      for (var i = flying.length - 1; i >= 0; i--) {
        var f = flying[i];
        f.t += dt / FLIGHT;
        if (f.t >= 1) { f.el.remove(); flying.splice(i, 1); deliver(f.seq); continue; }
        f.el.style.transform = 'translate3d(' + (f.t * w).toFixed(1) + 'px,0,0)';
      }
      paintCounters();
    }

    var offFrame = null, visible = false;
    function wake() { if (!offFrame && visible && !motion.reduced()) offFrame = motion.onFrame(step); }
    function sleep() { if (offFrame) { offFrame(); offFrame = null; } }
    sc.add(u.onVisible(sim, function (vis) { visible = vis; if (vis) wake(); else sleep(); }, { threshold: 0.1 }));
    sc.add(sleep);

    function cut() {
      if (state === 'down' || state === 'drain') return;
      var back = flying.map(function (f) { f.el.remove(); return f.seq; }).sort(function (a, b) { return a - b; });
      flying = [];
      queue = back.concat(queue);
      back.forEach(function () { if (stack.childElementCount < STACK_MAX) stack.appendChild(h('span', { class: 'gv-sf__blk' })); });
      if (motion.reduced()) {
        for (var k = 0; k < 6; k++) { seq++; pushQueue(seq); }
      }
      setState('down');
      paintCounters();
    }
    function restore() {
      if (state !== 'down') return;
      drainAcc = 0;
      if (motion.reduced()) {
        while (queue.length) deliver(queue.shift());
        stack.textContent = '';
        setState('done');
        paintCounters();
        return;
      }
      setState('drain');
    }
    function reset() {
      flying.forEach(function (f) { f.el.remove(); });
      flying = [];
      queue = [];
      stack.textContent = '';
      seq = delivered = lastSeq = gaps = 0;
      acc = drainAcc = 0;
      setState('ok');
      paintCounters();
    }
    sc.on(btnCut, 'click', cut);
    sc.on(btnRestore, 'click', restore);
    sc.on(btnReset, 'click', reset);
    if (motion.reduced()) {
      for (var j = 1; j <= 8; j++) { seq++; deliver(j); }
    }
    paintCounters();

    return { destroy: function () { sc.destroy(); body.textContent = ''; }, cut: cut, restore: restore, reset: reset };
  }

  GV.components.resilience = { mount: mount };
})();
