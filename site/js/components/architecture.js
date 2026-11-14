/*
 * GV.components.architecture — схема архитектуры и чипы стека.
 * mount(el, options) → { destroy() }   (раскладка выбирается сама по ширине контейнера)
 *   ≥ 62rem — горизонтальная: источники → streamer → vision → main → пульт и архив, служебные модули снизу;
 *   уже     — вертикальная в две дорожки: цепочка данных слева, служебные модули справа.
 * Связи и граница «локальный контур» — инлайн-SVG; узлы — нативные <button> поверх него
 * (фокусируемы, aria-pressed закрепляет подсветку). Наведение или фокус подсвечивает связи узла
 * и показывает подпись (aria-live). Перекладка — по ResizeObserver и событию gv:tweaks (масштаб).
 */
(function () {
  'use strict';

  var GV = (window.GV = window.GV || {});
  GV.components = GV.components || {};

  var NODE_W = 10.5;   // rem
  var NODE_H = 3.25;
  var WIDE_MIN = 62;
  var T = {
    hint: 'Наведите курсор на узел или перейдите к нему клавишей Tab — подсветятся его связи.',
    diagram: 'Схема архитектуры GaugeVision AI',
    incoming: 'Получает',
    outgoing: 'Передаёт',
    file: 'Файл'
  };

  function mount(el) {
    var u = GV.util, kit = GV.kit, h = u.h, s = u.svg;
    var c = GV.content;
    var arch = c.architecture;
    var sc = kit.scope();
    var nodes = arch.nodes;
    var edges = arch.edges;
    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    var captionId = u.uid('gv-arch-caption');
    var markerId = u.uid('gv-arch-arrow');
    var active = null;
    var pinned = null;
    var lastKey = null;

    /* Источники: сначала те, что ведут в сервер, затем — в служебные модули. */
    function outGroup(n) {
      var e = edges.filter(function (x) { return x.from === n.id; })[0];
      return e && byId[e.to] ? byId[e.to].group : '';
    }
    var sources = nodes.filter(function (n) { return n.group === 'source'; })
      .sort(function (a, b) { return (outGroup(a) === 'server' ? 0 : 1) - (outGroup(b) === 'server' ? 0 : 1); });
    var server = nodes.filter(function (n) { return n.group === 'server'; });
    var services = nodes.filter(function (n) { return n.group === 'service'; });
    var sinks = nodes.filter(function (n) { return n.group === 'client'; })
      .concat(nodes.filter(function (n) { return n.group === 'storage'; }));

    /* ---------- раскладки (единица — rem) ---------- */

    function wide(W) {
      var pos = {};
      var top = 3;
      var gap = (W - 5 * NODE_W - 2) / 4;
      var col = function (i) { return 1 + i * (NODE_W + gap); };
      var rowStep = NODE_H + 0.9;
      sources.forEach(function (n, i) { pos[n.id] = { x: col(0), y: top + i * rowStep, w: NODE_W }; });
      var chainY = top + 1.5 * rowStep;
      server.forEach(function (n, i) { pos[n.id] = { x: col(1 + Math.min(i, 2)), y: chainY, w: NODE_W }; });
      sinks.forEach(function (n, i) { pos[n.id] = { x: col(4), y: chainY + (i === 0 ? -2.25 : 2.25) * 1.15, w: NODE_W }; });
      var lastSourceY = top + (sources.length - 1) * rowStep;
      services.forEach(function (n, i) { pos[n.id] = { x: col(2 + Math.min(i, 2)), y: lastSourceY, w: NODE_W }; });
      return { pos: pos, W: W, H: lastSourceY + NODE_H + 1.5 };
    }

    function narrow(W) {
      var pos = {};
      var g = 1;
      var lane = (W - 2 - g) / 2;
      var xL = 1, xR = 1 + lane + g;
      var y = 4.25;
      var rowStep = NODE_H + 0.75;
      sources.forEach(function (n, i) {
        pos[n.id] = { x: i % 2 === 0 ? xL : xR, y: y + Math.floor(i / 2) * rowStep, w: lane, col: i % 2 };
      });
      y += Math.ceil(sources.length / 2) * rowStep + 1.25;
      var busY = y - 0.85;
      var gutter = xL + lane + g / 2;
      /* Источники соединяются ортогонально: по краю схемы к общей шине над цепочкой. */
      var route = function (e) {
        var a = pos[e.from], b = pos[e.to];
        if (!a || !b || byId[e.from].group !== 'source') return null;
        var mid = a.y + NODE_H / 2;
        var bx = b.x + b.w / 2;
        if (byId[e.to].group === 'server') {
          var edgeX = a.col === 0 ? 0.6 : W - 0.6;
          var sx = a.col === 0 ? a.x : a.x + a.w;
          return 'M' + sx + ' ' + mid + ' H' + edgeX + ' V' + busY + ' H' + bx + ' V' + b.y;
        }
        var fromX = a.col === 0 ? a.x + a.w : a.x;
        var toX = b.x > gutter ? b.x : b.x + b.w;
        return 'M' + fromX + ' ' + mid + ' H' + gutter + ' V' + (b.y + NODE_H / 2) + ' H' + toX;
      };
      var chainStep = NODE_H + 1.5;
      server.forEach(function (n, i) { pos[n.id] = { x: xL, y: y + i * chainStep, w: lane }; });
      services.forEach(function (n, i) {
        var row = i === 0 ? 0 : Math.max(0, server.length - 1);
        pos[n.id] = { x: xR, y: y + row * chainStep, w: lane };
      });
      y += Math.max(1, server.length) * chainStep + 0.25;
      sinks.forEach(function (n, i) { pos[n.id] = { x: i % 2 === 0 ? xL : xR, y: y + Math.floor(i / 2) * chainStep, w: lane }; });
      y += Math.ceil(sinks.length / 2) * chainStep;
      return { pos: pos, W: W, H: y + 0.5, route: route };
    }

    /* Точки входа и выхода связи: по горизонтали — боковые стороны, по вертикали — верх и низ. */
    function anchors(a, b) {
      var ax = a.x + a.w / 2, ay = a.y + NODE_H / 2;
      var bx = b.x + b.w / 2, by = b.y + NODE_H / 2;
      var dx = bx - ax, dy = by - ay;
      var horizontal = Math.abs(dx) > Math.max(a.w, b.w) * 0.75;
      if (horizontal) {
        var sx = dx > 0 ? a.x + a.w : a.x;
        var ex = dx > 0 ? b.x : b.x + b.w;
        var k = (ex - sx) * 0.5;
        return 'M' + sx + ' ' + ay + ' C' + (sx + k) + ' ' + ay + ' ' + (ex - k) + ' ' + by + ' ' + ex + ' ' + by;
      }
      var sy = dy > 0 ? a.y + NODE_H : a.y;
      var ey = dy > 0 ? b.y : b.y + NODE_H;
      var m = (ey - sy) * 0.5;
      return 'M' + ax + ' ' + sy + ' C' + ax + ' ' + (sy + m) + ' ' + bx + ' ' + (ey - m) + ' ' + bx + ' ' + ey;
    }

    /* ---------- разметка ---------- */

    var edgeEls = edges.map(function (e) {
      return s('path', { class: 'gv-architecture__edge', 'data-from': e.from, 'data-to': e.to, 'marker-end': 'url(#' + markerId + ')' });
    });
    var boundary = s('rect', { class: 'gv-architecture__boundary', rx: 0.5 });
    var svgEl = s('svg', { class: 'gv-architecture__links', 'aria-hidden': 'true', focusable: 'false', preserveAspectRatio: 'none' },
      s('defs', null, s('marker', { id: markerId, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 0.55, markerHeight: 0.55, markerUnits: 'userSpaceOnUse', orient: 'auto-start-reverse' },
        s('path', { class: 'gv-architecture__arrowhead', d: 'M0 0 L10 5 L0 10 z' }))),
      boundary, edgeEls);

    /* Кнопки узлов в DOM — в порядке раскладки, чтобы Tab шёл так же, как читается схема. */
    var nodeEls = {};
    var nodeButtons = sources.concat(server, sinks, services).map(function (n) {
      var b = h('button', {
        type: 'button', class: 'gv-architecture__node', 'data-id': n.id, 'data-group': n.group,
        'aria-pressed': 'false', 'aria-describedby': captionId
      },
        h('span', { class: 'gv-architecture__group' }, arch.groups[n.group] || n.group),
        h('span', { class: 'gv-architecture__label' }, n.label));
      nodeEls[n.id] = b;
      return b;
    });

    var boundaryLabel = h('p', { class: 'gv-architecture__boundary-label' }, arch.boundaryLabel);
    var canvas = h('div', { class: 'gv-architecture__canvas', role: 'group', 'aria-label': T.diagram }, svgEl, boundaryLabel, nodeButtons);
    var caption = h('div', { class: 'gv-architecture__caption', id: captionId, 'aria-live': 'polite' });
    var stack = h('div', { class: 'gv-architecture__stack' },
      h('h3', { class: 'gv-architecture__stack-title' }, c.labels.stackTitle),
      h('ul', { class: 'gv-architecture__chips', role: 'list' }, arch.stack.map(function (it) {
        return h('li', { class: 'gv-architecture__chip' },
          h('span', { class: 'gv-architecture__chip-name' }, it.name),
          it.version ? h('span', { class: 'gv-architecture__chip-ver' }, it.version) : null);
      })));

    var rootEl = h('div', { class: 'gv-architecture' },
      h('div', { class: 'gv-architecture__viewport' }, canvas),
      caption,
      stack);
    el.appendChild(rootEl);

    /* ---------- подпись и подсветка ---------- */

    function renderCaption(id) {
      caption.textContent = '';
      if (!id) {
        caption.appendChild(h('p', { class: 'gv-architecture__hint' }, T.hint));
        return;
      }
      var n = byId[id];
      var ins = edges.filter(function (e) { return e.to === id; });
      var outs = edges.filter(function (e) { return e.from === id; });
      function list(title, arr, key) {
        if (!arr.length) return null;
        return h('div', { class: 'gv-architecture__links-list' },
          h('p', { class: 'gv-architecture__links-title' }, title),
          h('ul', { role: 'list' }, arr.map(function (e) {
            return h('li', null, h('span', { class: 'gv-architecture__peer' }, byId[e[key]] ? byId[e[key]].label : e[key]),
              e.label ? h('span', { class: 'gv-architecture__via' }, e.label) : null);
          })));
      }
      caption.appendChild(h('div', { class: 'gv-architecture__caption-main' },
        h('p', { class: 'gv-architecture__caption-title' }, n.label,
          h('span', { class: 'gv-architecture__caption-group' }, arch.groups[n.group] || '')),
        h('p', { class: 'gv-architecture__caption-sub' }, n.sub),
        n.file ? h('p', { class: 'gv-architecture__caption-file' }, h('span', null, T.file), h('code', null, n.file)) : null));
      caption.appendChild(list(T.incoming, ins, 'from'));
      caption.appendChild(list(T.outgoing, outs, 'to'));
    }

    function highlight(id) {
      active = id;
      if (id) rootEl.setAttribute('data-active', id);
      else rootEl.removeAttribute('data-active');
      var linked = {};
      if (id) linked[id] = true;
      edgeEls.forEach(function (p) {
        var on = !!id && (p.getAttribute('data-from') === id || p.getAttribute('data-to') === id);
        p.classList.toggle('is-active', on);
        if (on) { linked[p.getAttribute('data-from')] = true; linked[p.getAttribute('data-to')] = true; }
      });
      Object.keys(nodeEls).forEach(function (k) {
        nodeEls[k].classList.toggle('is-linked', !!linked[k]);
        nodeEls[k].classList.toggle('is-active', k === id);
      });
      if ((id || '') !== lastKey) { lastKey = id || ''; renderCaption(id); }
    }

    nodeButtons.forEach(function (b) {
      var id = b.getAttribute('data-id');
      sc.on(b, 'mouseenter', function () { highlight(id); });
      sc.on(b, 'focus', function () { highlight(id); });
      sc.on(b, 'click', function () {
        pinned = pinned === id ? null : id;
        nodeButtons.forEach(function (o) { o.setAttribute('aria-pressed', o.getAttribute('data-id') === pinned ? 'true' : 'false'); });
        highlight(pinned || id);
      });
    });
    sc.on(canvas, 'mouseleave', function () {
      if (!canvas.contains(document.activeElement)) highlight(pinned);
    });
    sc.on(canvas, 'focusout', function (e) {
      if (!e.relatedTarget || !canvas.contains(e.relatedTarget)) highlight(pinned);
    });

    /* ---------- перекладка ---------- */

    var lastLayout = '';
    function layout() {
      var rem = parseFloat(window.getComputedStyle(document.documentElement).fontSize) || 16;
      var avail = rootEl.clientWidth / rem;
      if (!avail) return;
      var isWide = avail >= WIDE_MIN;
      var W = isWide ? avail : Math.max(19, Math.min(avail, 40));
      var key = (isWide ? 'w' : 'n') + Math.round(W * 4) + '@' + rem;
      if (key === lastLayout) return;
      lastLayout = key;
      var L = isWide ? wide(W) : narrow(W);
      rootEl.setAttribute('data-layout', isWide ? 'wide' : 'narrow');
      canvas.style.width = L.W + 'rem';
      canvas.style.height = L.H + 'rem';
      svgEl.setAttribute('viewBox', '0 0 ' + L.W + ' ' + L.H);
      boundary.setAttribute('x', 0.25);
      boundary.setAttribute('y', 0.25);
      boundary.setAttribute('width', Math.max(0, L.W - 0.5));
      boundary.setAttribute('height', Math.max(0, L.H - 0.5));
      boundaryLabel.style.maxWidth = (L.W - 2) + 'rem';
      nodes.forEach(function (n) {
        var p = L.pos[n.id];
        var b = nodeEls[n.id];
        if (!b) return;
        if (!p) { b.hidden = true; return; }
        b.hidden = false;
        b.style.left = p.x + 'rem';
        b.style.top = p.y + 'rem';
        b.style.width = p.w + 'rem';
        b.style.height = NODE_H + 'rem';
      });
      edges.forEach(function (e, i) {
        var a = L.pos[e.from], b = L.pos[e.to];
        if (a && b) edgeEls[i].setAttribute('d', (L.route && L.route(e)) || anchors(a, b));
      });
    }

    layout();
    highlight(null);
    if ('ResizeObserver' in window) {
      var ro = new ResizeObserver(function () { layout(); });
      ro.observe(rootEl);
      sc.add(function () { ro.disconnect(); });
    } else {
      sc.on(window, 'resize', layout);
    }
    kit.onTweaks(sc, function () { lastLayout = ''; layout(); });

    return {
      destroy: function () {
        sc.destroy();
        if (rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
      }
    };
  }

  GV.components.architecture = { mount: mount, layouts: ['auto'] };
})();
