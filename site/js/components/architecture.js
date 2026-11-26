/*
 * GV.components.architecture — лист 06 «Один сервер в локальном контуре».
 * Схема соединений на миллиметровке: источники видео → streamer.py → vision.py → main.py → пульт и архив;
 * служебные discovery.py и cert_gen.py снизу. Граница локального контура — штрихпунктир, как на чертеже.
 * Узел выбирают наведением, касанием или стрелками (roving tabindex: одна остановка Tab на всю схему);
 * выбранный узел подсвечивает свои связи, остальные гаснут рамкой, подпись узла — в выноске под схемой.
 * Ниже — спецификация стека: поз. · компонент · версия.
 *
 *   mount(body) → { destroy }
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});

  /* Положение узлов в единицах viewBox 0 0 1400 560: источники слева, сервер в строку, пульт справа,
     архив под main.py, служебные модули снизу. Зазоры между узлами сервера ≥ 120 — подписи связей
     помещаются целиком. */
  var VB = [1400, 560];
  var LAYOUT = {
    rtsp: [40, 64], mjpeg: [40, 140], usb: [40, 216], phone: [40, 292], onvif: [40, 452],
    streamer: [300, 178], vision: [590, 178], main: [880, 178],
    dashboard: [1170, 178], db: [880, 352],
    discovery: [330, 452], cert: [1170, 452]
  };
  var W = 170;
  var NH = 52;
  /* Порядок обхода стрелками: слева направо, сверху вниз */
  var ORDER = ['rtsp', 'mjpeg', 'usb', 'phone', 'onvif', 'streamer', 'discovery', 'vision', 'main', 'cert', 'dashboard', 'db'];

  function mount(body) {
    var u = GV.util;
    var kit = GV.kit;
    var h = u.h;
    var s = u.svg;
    var c = GV.content;
    var A = c.architecture;
    var L = c.labels;
    var sc = kit.scope();
    var fine = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    body.classList.add('gv-schema');

    var nodesById = {};
    A.nodes.forEach(function (n) { nodesById[n.id] = n; });

    function box(id) {
      var p = LAYOUT[id];
      var w = id === 'dashboard' ? 196 : W;
      return { x: p[0], y: p[1], w: w, h: NH, cx: p[0] + w / 2, cy: p[1] + NH / 2 };
    }

    /* ---------- связи: ортогональные ломаные ---------- */
    /* Ломаная и место подписи: { pts, lx, ly, anchor } */
    function route(e) {
      var a = box(e.from);
      var b = box(e.to);
      if (e.from === 'main' && e.to === 'db') {
        var x0 = a.cx - 28;
        return { pts: [[x0, a.y + a.h], [x0, b.y]], lx: x0 - 8, ly: (a.y + a.h + b.y) / 2 + 4, anchor: 'end' };
      }
      if (e.from === 'db' && e.to === 'main') {
        var x1 = a.cx + 28;
        return { pts: [[x1, a.y], [x1, b.y + b.h]], lx: x1 + 8, ly: (a.y + b.y + b.h) / 2 + 4, anchor: 'start' };
      }
      if (e.from === 'discovery') {
        var xd = b.x - 36;
        return { pts: [[a.x + a.w, a.cy], [xd, a.cy], [xd, b.cy + 16], [b.x, b.cy + 16]], lx: (a.x + a.w + xd) / 2, ly: a.cy - 8, anchor: 'middle' };
      }
      if (e.from === 'cert') {
        // в обход пульта: влево до середины зазора main.py → пульт, вверх, в правый бок main.py
        var xc = b.x + b.w + 60;
        return { pts: [[a.x, a.cy], [xc, a.cy], [xc, b.cy + 16], [b.x + b.w, b.cy + 16]], lx: xc + 8, ly: (a.cy + b.cy) / 2 + 20, anchor: 'start' };
      }
      if (e.from === 'onvif') {
        return { pts: [[a.x + a.w, a.cy], [b.x, b.cy]], lx: (a.x + a.w + b.x) / 2, ly: a.cy - 8, anchor: 'middle' };
      }
      if (a.cy === b.cy) {
        return { pts: [[a.x + a.w, a.cy], [b.x, b.cy]], lx: (a.x + a.w + b.x) / 2, ly: a.cy - 10, anchor: 'middle' };
      }
      // источники → streamer.py: общий коллектор слева от узла, подпись у входа в коллектор
      var mx = b.x - 34;
      var ty = b.cy + (a.cy - b.cy) * 0.12;
      return { pts: [[a.x + a.w, a.cy], [mx, a.cy], [mx, ty], [b.x, ty]], lx: a.x + a.w + 10, ly: a.cy - 6, anchor: 'start' };
    }
    function d(pts) {
      return pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0] + ' ' + p[1]; }).join(' ');
    }

    var defs = s('defs', null,
      s('marker', { id: 'gv-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
        s('path', { d: 'M0 1 L9 5 L0 9 z', class: 'gv-schema__head' })));

    var edgeEls = [];
    var edgesG = s('g', { class: 'gv-schema__edges' });
    A.edges.forEach(function (e) {
      var r = route(e);
      var path = s('path', { class: 'gv-schema__edge', d: d(r.pts), 'marker-end': 'url(#gv-arrow)' });
      var lx = r.lx;
      var label = s('text', { class: 'gv-schema__elabel', x: lx, y: r.ly, 'font-size': 11, 'text-anchor': r.anchor });
      var words = e.label.split(' ');
      if (e.label.length > 16 && words.length > 1) {
        var cut = Math.ceil(words.length / 2);
        label.appendChild(s('tspan', { x: lx, dy: '-1.1em' }, words.slice(0, cut).join(' ')));
        label.appendChild(s('tspan', { x: lx, dy: '1.15em' }, words.slice(cut).join(' ')));
      } else {
        label.textContent = e.label;
      }
      var g = s('g', { class: 'gv-schema__e', 'data-from': e.from, 'data-to': e.to }, path, label);
      edgeEls.push(g);
      edgesG.appendChild(g);
    });

    var nodeEls = {};
    var nodesG = s('g', { class: 'gv-schema__nodes' });
    ORDER.forEach(function (id) {
      var n = nodesById[id];
      if (!n) return;
      var b = box(id);
      var g = s('g', {
        class: 'gv-schema__n gv-schema__n--' + n.group,
        tabindex: '-1',
        role: 'button',
        'data-id': id,
        'aria-label': n.label + ': ' + n.sub
      },
        s('rect', { class: 'gv-schema__box', x: b.x, y: b.y, width: b.w, height: b.h, rx: 3 }),
        s('text', { class: 'gv-schema__label', x: b.x + 12, y: b.y + 22, 'font-size': 15 }, n.label),
        s('text', { class: 'gv-schema__group', x: b.x + 12, y: b.y + 40, 'font-size': 10 }, A.groups[n.group]));
      nodeEls[id] = g;
      nodesG.appendChild(g);
    });

    var boundary = s('g', { class: 'gv-schema__boundary' },
      s('rect', { x: 14, y: 22, width: VB[0] - 28, height: VB[1] - 38, rx: 6 }),
      s('text', { x: 30, y: 16, 'font-size': 12 }, A.boundaryLabel));

    var svgEl = s('svg', { class: 'gv-schema__svg', viewBox: '0 0 ' + VB[0] + ' ' + VB[1], role: 'group', 'aria-label': A.boundaryLabel },
      defs, boundary, edgesG, nodesG);

    var callout = h('p', { class: 'gv-schema__callout', 'aria-live': 'polite' });
    var hint = fine ? A.hint : A.hintTouch;
    function setCallout(id) {
      callout.textContent = '';
      if (!id) {
        callout.appendChild(h('span', { class: 'gv-schema__hint' }, hint));
        return;
      }
      var n = nodesById[id];
      callout.appendChild(h('span', { class: 'gv-schema__c-name' }, n.label));
      callout.appendChild(h('span', { class: 'gv-schema__c-sub' }, n.sub));
      if (n.file) callout.appendChild(h('code', { class: 'gv-schema__c-file' }, n.file));
    }
    setCallout(null);

    function item(id) {
      var n = nodesById[id];
      return h('li', { class: 'gv-flow__node gv-flow__node--' + n.group },
        h('span', { class: 'gv-flow__label' }, n.label), h('span', { class: 'gv-flow__sub' }, n.sub));
    }
    function step(title, ids) {
      return h('li', { class: 'gv-flow__step' },
        h('p', { class: 'gv-flow__title' }, title),
        h('ul', { class: 'gv-flow__nodes', role: 'list' }, ids.map(item)));
    }
    var flow = h('ol', { class: 'gv-flow', role: 'list', 'aria-label': A.boundaryLabel },
      step(A.groups.source, ['rtsp', 'mjpeg', 'usb', 'phone', 'onvif']),
      step(A.groups.server, ['streamer', 'vision', 'main']),
      step(A.groups.client + ', ' + A.groups.storage.toLowerCase(), ['dashboard', 'db']),
      step(A.groups.service, ['discovery', 'cert']));

    var sheet = h('figure', { class: 'gv-schema__sheet', 'data-reveal': '' },
      h('p', { class: 'gv-schema__bound gv-label' }, A.boundaryLabel),
      h('div', { class: 'gv-schema__scroll' }, svgEl),
      flow,
      h('figcaption', null, callout));
    body.appendChild(sheet);

    /* ---------- выбор узла ---------- */
    var active = null;
    function select(id) {
      active = id;
      svgEl.classList.toggle('has-active', !!id);
      var linked = {};
      if (id) linked[id] = true;
      edgeEls.forEach(function (g) {
        var on = !!id && (g.getAttribute('data-from') === id || g.getAttribute('data-to') === id);
        g.classList.toggle('is-on', on);
        if (on) { linked[g.getAttribute('data-from')] = true; linked[g.getAttribute('data-to')] = true; }
      });
      Object.keys(nodeEls).forEach(function (k) {
        nodeEls[k].classList.toggle('is-on', !!linked[k]);
        nodeEls[k].classList.toggle('is-current', k === id);
      });
      setCallout(id);
    }

    var focusIndex = 0;
    function setTab(i) {
      focusIndex = (i + ORDER.length) % ORDER.length;
      ORDER.forEach(function (id, j) { nodeEls[id].setAttribute('tabindex', j === focusIndex ? '0' : '-1'); });
    }
    setTab(0);

    ORDER.forEach(function (id, i) {
      var g = nodeEls[id];
      sc.on(g, 'pointerenter', function (e) { if (e.pointerType === 'mouse') select(id); });
      sc.on(g, 'click', function () { setTab(i); select(active === id && !fine ? null : id); });
      sc.on(g, 'focus', function () { setTab(i); select(id); });
      sc.on(g, 'keydown', function (e) {
        var step = 0;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') step = 1;
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') step = -1;
        else if (e.key === 'Home') { e.preventDefault(); setTab(0); nodeEls[ORDER[0]].focus(); return; }
        else if (e.key === 'End') { e.preventDefault(); setTab(ORDER.length - 1); nodeEls[ORDER[ORDER.length - 1]].focus(); return; }
        else if (e.key === 'Escape') { select(null); return; }
        if (!step) return;
        e.preventDefault();
        setTab(focusIndex + step);
        nodeEls[ORDER[focusIndex]].focus();
      });
    });
    sc.on(svgEl, 'pointerleave', function (e) { if (e.pointerType === 'mouse' && !svgEl.contains(document.activeElement)) select(null); });
    sc.on(svgEl, 'focusout', function (e) { if (!svgEl.contains(e.relatedTarget)) select(null); });

    /* ---------- спецификация ---------- */
    var cols = A.stackColumns;
    var spec = h('table', { class: 'gv-spec', 'data-reveal': '' },
      h('caption', { class: 'gv-spec__cap' }, L.stackTitle),
      h('thead', null, h('tr', null, cols.map(function (col) { return h('th', { scope: 'col' }, col); }))),
      h('tbody', null, A.stack.map(function (item, i) {
        return h('tr', null,
          h('td', { class: 'gv-spec__pos gv-num' }, String(i + 1)),
          h('th', { scope: 'row' }, item.name),
          h('td', { class: 'gv-spec__ver' }, item.version));
      })));
    body.appendChild(spec);

    return { destroy: sc.destroy };
  }

  GV.components = GV.components || {};
  GV.components.architecture = { mount: mount };
})();
