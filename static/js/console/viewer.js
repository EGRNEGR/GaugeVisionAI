// Видео выбранного прибора: вкладки камер, живой кадр с векторной разметкой
// распознавания, стоп-кадры срабатываний, редактор ручной ROI на кадре.
import { $, $$, esc, fmt, decimalsFor, timeStr, LEVEL_TAG, DIAL_SOURCE, STATUS_TEXT } from './util.js';
import { state, on, emit, camList, select, selected, displayLevel, snapshotsOf } from './store.js';

const stage = $('#stage');
const media = $('#media');
const img = $('#frame');
const svg = $('#overlay');
const NS = 'http://www.w3.org/2000/svg';
const layers = { box: true, scale: true, needle: true, labels: true };
let frameTimer = null;
let frameCam = null;
let frameUrl = null;          // object URL текущего кадра
let filmOpen = false;
let roiDraft = null;          // { cx, cy, r } в долях кадра, пока редактор ROI открыт
let frameWH = null;           // размер обработанного кадра (геометрия сервера)

// ---------------------------------------------------------------- вкладки
export function renderTabs() {
  const box = $('#camTabs');
  const cams = camList();
  box.innerHTML = cams.map((c, i) => `
    <button class="cam-tab" role="tab" data-id="${c.id}" aria-selected="${c.id === state.selectedId}"
      tabindex="${c.id === state.selectedId ? 0 : -1}" title="${esc(c.data.name)} — клавиша ${i + 1}">
      <span class="lv" data-level="${displayLevel(c)}"></span><span class="k">${String(i + 1).padStart(2, '0')}</span><span class="nm">${esc(c.data.name)}</span>
    </button>`).join('');
  $$('.cam-tab', box).forEach((b) => b.addEventListener('click', () => select(b.dataset.id)));
  box.onkeydown = (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const tabs = $$('.cam-tab', box);
    const i = tabs.findIndex((t) => t.dataset.id === state.selectedId) + (e.key === 'ArrowRight' ? 1 : -1);
    if (tabs[i]) { select(tabs[i].dataset.id); $(`.cam-tab[data-id="${tabs[i].dataset.id}"]`, box)?.focus(); }
  };
  const cur = $('.cam-tab[aria-selected="true"]', box);
  if (cur) cur.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}
function updateTabLevel(camId) {
  const cam = state.cams.get(camId);
  const lv = $(`.cam-tab[data-id="${camId}"] .lv`);
  if (cam && lv) lv.dataset.level = displayLevel(cam);
}

// ---------------------------------------------------------------- кадр
function startFrames() {
  clearTimeout(frameTimer);
  const cam = selected();
  frameCam = cam ? cam.id : null;
  if (!cam || state.stop) return;
  const id = cam.id;
  // кадр скачивается один раз и подменяется только готовым: без пустого кадра между загрузками
  const tick = async () => {
    if (frameCam !== id || state.stop) return;
    if (document.hidden) { frameTimer = setTimeout(tick, 1000); return; }
    const t0 = performance.now();
    try {
      const res = await fetch(`/api/cameras/${id}/frame.jpg?overlay=0`, { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      if (frameCam !== id || state.stop) { URL.revokeObjectURL(url); return; }
      const old = frameUrl;
      frameUrl = url;
      img.src = url;
      // прежний URL отзывается только после декодирования нового — иначе кадр может пропасть
      try { await img.decode(); } catch (_) { /* битый кадр: следующий заменит */ }
      if (old) URL.revokeObjectURL(old);
      frameTimer = setTimeout(tick, Math.max(60, 250 - (performance.now() - t0)));
    } catch (_) {
      frameTimer = setTimeout(tick, 2000);
    }
  };
  tick();
}

// ---------------------------------------------------------------- разметка
function el(name, attrs, text) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}
const NSS = { 'vector-effect': 'non-scaling-stroke' };

/** Подпись с подложкой; размеры в единицах кадра, k — пикселей экрана на единицу. */
function label(g, x, y, lines, k, anchor = 'start') {
  const fs = 12 / k;
  const padX = 5 / k, padY = 3 / k;
  const w = Math.max(...lines.map((s) => s.length)) * fs * 0.62 + padX * 2;
  const h = lines.length * fs * 1.3 + padY * 2;
  const x0 = anchor === 'end' ? x - w : x;
  g.appendChild(el('rect', { class: 'lbl-bg', x: x0, y: y - h, width: w, height: h, ...NSS, 'stroke-width': 1 }));
  lines.forEach((s, i) => g.appendChild(el('text', {
    x: x0 + padX, y: y - h + padY + fs * (i + 1) * 1.3 - fs * 0.3, 'font-size': fs,
  }, s)));
}

function stageScale(w, h) {
  return Math.min(media.clientWidth / w, media.clientHeight / h) || 1;
}
// на узком кадре подписи закрыли бы прибор: показываем их от 560 px ширины
const showLabels = () => layers.labels && media.clientWidth >= 560;

export function renderOverlay() {
  const cam = selected();
  svg.textContent = '';
  if (!cam || state.stop) return;
  const r = cam.reading;
  const g = r && r.geom;
  if (g) frameWH = { w: g.w, h: g.h };
  else if (img.naturalWidth) frameWH = { w: img.naturalWidth, h: img.naturalHeight };
  if (!frameWH) return;
  const { w, h } = frameWH;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.dataset.level = (r && r.level) || 'normal';
  const k = stageScale(w, h);
  const d = decimalsFor(cam.data);
  const root = el('g', {});
  svg.appendChild(root);

  if (g && !roiDraft) {
    if (layers.box) {
      const [cx, cy, a, b, ang] = g.ellipse;
      root.appendChild(el('ellipse', { class: 'ell', cx, cy, rx: a, ry: b, transform: `rotate(${ang} ${cx} ${cy})`, ...NSS, 'stroke-width': 1 }));
      const [bx, by, bw, bh] = g.bbox;
      root.appendChild(el('rect', { class: 'bbox', x: bx, y: by, width: bw, height: bh, ...NSS, 'stroke-width': 1 }));
      if (showLabels()) {
        const txt = `ЦИФЕРБЛАТ  ${DIAL_SOURCE[g.source] || g.source}  ${fmt(g.score, 2)}`;
        const above = by - 4 / k;
        label(root, bx, above - 20 / k > 0 ? above : by + 24 / k, [txt], k);
      }
    }
    if (layers.scale) {
      for (const z of g.zones) {
        root.appendChild(el('polyline', { class: 'zone', 'data-level': z.level, points: z.points.map((p) => p.join(',')).join(' '), ...NSS, 'stroke-width': 3 }));
      }
      for (const ray of g.rays) {
        const [p0, p1] = ray.points;
        root.appendChild(el('line', { class: 'ray', x1: p0[0], y1: p0[1], x2: p1[0], y2: p1[1], ...NSS, 'stroke-width': 1 }));
        if (showLabels()) {
          const right = p1[0] >= p0[0];
          label(root, p1[0] + (right ? 6 : -6) / k, p1[1] + 8 / k, [`θ${ray.name} ${fmt(ray.theta, 1)}°`], k, right ? 'start' : 'end');
        }
      }
    }
    if (layers.needle && g.needle) {
      const [[x0, y0], [x1, y1]] = g.needle;
      root.appendChild(el('line', { class: 'needle', x1: x0, y1: y0, x2: x1, y2: y1, ...NSS, 'stroke-width': 2 }));
      root.appendChild(el('circle', { class: 'hub', cx: x0, cy: y0, r: 4 / k }));
      const ang = Math.atan2(y1 - y0, x1 - x0);
      const s = 9 / k;
      const tri = [[x1 + Math.cos(ang) * s, y1 + Math.sin(ang) * s],
        [x1 + Math.cos(ang + 2.5) * s, y1 + Math.sin(ang + 2.5) * s],
        [x1 + Math.cos(ang - 2.5) * s, y1 + Math.sin(ang - 2.5) * s]];
      root.appendChild(el('polygon', { class: 'tip', points: tri.map((p) => p.join(',')).join(' ') }));
      if (showLabels()) {
        // подпись — за краем циферблата по направлению стрелки, шкала остаётся открытой;
        // стрелка почти вертикально вверх — подпись сбоку от рамки, мимо подписи рамки
        const [ecx, ecy, ea, eb] = g.ellipse;
        const [bx, , bw] = g.bbox;
        const R = Math.max(ea, eb) * 1.06 + 6 / k;
        const c = Math.cos(ang), sn = Math.sin(ang);
        const steepUp = sn < 0 && Math.abs(c) < 0.45;
        const right = steepUp ? true : c >= 0;
        const lx = steepUp ? bx + bw + 8 / k : ecx + c * R;
        const ly = steepUp ? ecy - Math.max(ea, eb) * 0.45 : ecy + sn * R + (sn > 0 ? 30 / k : 0);
        label(root, lx, ly, [`${fmt(r.value, d)} ${cam.data.unit}`, `θ ${fmt(r.angle, 2)}°  уверенность ${fmt(r.confidence, 2)}`], k, right ? 'start' : 'end');
      }
    }
    if (r && !r.valid && showLabels()) {
      const [bx, by, , bh] = g.bbox;
      label(root, bx, Math.min(h - 4 / k, by + bh + 26 / k), [`СТРЕЛКА НЕ НАЙДЕНА — удержание ${fmt(r.value, d)} ${cam.data.unit}`], k);
    }
  }
  if (roiDraft) drawRoiEditor(root, w, h, k, g);
}

// ---------------------------------------------------------------- редактор ROI
function drawRoiEditor(root, w, h, k, g) {
  if (g) {
    const [cx, cy, a, b, ang] = g.ellipse;
    root.appendChild(el('ellipse', { class: 'ell', cx, cy, rx: a, ry: b, transform: `rotate(${ang} ${cx} ${cy})`, ...NSS, 'stroke-width': 1 }));
  }
  const m = Math.min(w, h);
  const cx = roiDraft.cx * w, cy = roiDraft.cy * h, rr = roiDraft.r * m;
  const ge = el('g', { class: 'edit' });
  const circle = el('circle', { class: 'edit-circle', cx, cy, r: rr, ...NSS, 'stroke-width': 1 });
  ge.appendChild(circle);
  ge.appendChild(el('line', { class: 'cross', x1: cx - 10 / k, y1: cy, x2: cx + 10 / k, y2: cy, ...NSS, 'stroke-width': 1 }));
  ge.appendChild(el('line', { class: 'cross', x1: cx, y1: cy - 10 / k, x2: cx, y2: cy + 10 / k, ...NSS, 'stroke-width': 1 }));
  const hr = el('rect', { class: 'handle', x: cx + rr - 6 / k, y: cy - 6 / k, width: 12 / k, height: 12 / k, ...NSS, 'stroke-width': 1 });
  ge.appendChild(hr);
  label(ge, cx - rr, cy - rr - 6 / k, [`ROI  X ${fmt(roiDraft.cx, 3)}  Y ${fmt(roiDraft.cy, 3)}  R ${fmt(roiDraft.r, 3)}`], k);
  root.appendChild(ge);

  const toFrame = (ev) => {
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  };
  const drag = (target, onMove) => target.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    target.setPointerCapture(e.pointerId);
    const start = toFrame(e);
    const base = { ...roiDraft };
    const move = (ev) => { onMove(toFrame(ev), start, base); emit('roi-drag', { ...roiDraft }); renderOverlay(); };
    const up = () => { target.removeEventListener('pointermove', move); target.removeEventListener('pointerup', up); };
    target.addEventListener('pointermove', move);
    target.addEventListener('pointerup', up);
  });
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  drag(circle, (p, s, base) => {
    roiDraft.cx = +clamp(base.cx + (p.x - s.x) / w, 0, 1).toFixed(4);
    roiDraft.cy = +clamp(base.cy + (p.y - s.y) / h, 0, 1).toFixed(4);
  });
  drag(hr, (p) => {
    roiDraft.r = +clamp(Math.hypot(p.x - roiDraft.cx * w, p.y - roiDraft.cy * h) / m, 0.05, 1).toFixed(4);
  });
}

// ---------------------------------------------------------------- углы кадра
function renderCorners() {
  const cam = selected();
  $('#strip').hidden = !!state.stop;
  const live = $('#liveInfo'), perf = $('#perfInfo');
  if (!cam) { live.textContent = ''; perf.textContent = ''; return; }
  const r = cam.reading;
  const st = cam.stream || {};
  const age = r ? (Date.now() - Date.parse(r.ts)) / 1000 : null;
  live.innerHTML = `<b>${cam.status === 'online' ? 'ЖИВОЙ' : esc((STATUS_TEXT[cam.status] || cam.status).toUpperCase())}</b>`
    + `<span>${r ? timeStr(new Date(r.ts)) : '—'}</span><span>${age === null ? '' : `отсчёт ${fmt(age, 1)} с назад`}</span>`;
  perf.innerHTML = `<span>захват <b>${fmt(st.fps, 1)}</b> к/с</span><span>конвейер <b>${r ? fmt(r.process_ms, 0) : '—'}</b> мс</span>`;
}

function renderStale() {
  const cam = selected();
  const note = $('#staleNote');
  const lv = cam ? displayLevel(cam) : null;
  const stale = !!cam && !state.stop && lv === 'stale';
  stage.dataset.stale = String(stale);
  note.hidden = !stale;
  if (stale) {
    const last = cam.reading ? timeStr(new Date(cam.reading.ts)) : '—';
    note.textContent = !state.connected
      ? 'Нет связи с сервером — кадр не обновляется'
      : `Нет связи с камерой: ${(STATUS_TEXT[cam.status] || cam.status).toLowerCase()}, последний отсчёт ${last}`;
  }
}

function renderVeil() {
  const veil = $('#veil');
  const cams = camList();
  if (!cams.length) {
    veil.hidden = false;
    veil.innerHTML = `<h3>Камеры не подключены</h3>
      <p>Пульт покажет кадр прибора с разметкой распознавания, как только появится первый источник видео.</p>
      <div class="row"><button class="btn primary" data-act="add">Добавить камеру</button><button class="btn" data-act="discover">Поиск в сети</button><button class="btn" data-act="phone">Смартфон по QR</button></div>`;
    img.removeAttribute('src');
    return;
  }
  veil.hidden = true;
  veil.textContent = '';
}

// ---------------------------------------------------------------- стоп-кадры
function evText(ev, cam) {
  const d = cam ? decimalsFor(cam.data) : 2;
  const unit = ev.unit || '';
  if (ev.level === 'normal') return `Возврат в норму: ${fmt(ev.value, d)} ${unit}`;
  const sp = ev.setpoint ? `${ev.setpoint} ${fmt(ev.setpoint_value, d)}` : '';
  const what = ev.level === 'alert' ? 'Авария' : 'Предупреждение';
  return `${what}${ev.setpoint ? ` по уставке ${ev.setpoint}` : ''}: ${fmt(ev.value, d)} ${unit}${sp ? `, уставка ${sp}` : ''}`;
}
export { evText };

export function openStop(eventId) {
  const ev = state.events.get(eventId);
  if (!ev || !ev.has_frame) return;
  if (ev.cam_id !== state.selectedId) select(ev.cam_id);
  state.stop = { camId: ev.cam_id, eventId };
  emit('stop', state.stop);
}
export function closeStop() {
  state.stop = null;
  emit('stop', null);
}

function renderStop() {
  const bar = $('#stopbar');
  if (!state.stop) {
    bar.hidden = true;
    renderFilm();
    startFrames();
    renderOverlay();
    renderCorners();
    renderStale();
    return;
  }
  const ev = state.events.get(state.stop.eventId);
  const cam = state.cams.get(state.stop.camId);
  clearTimeout(frameTimer);
  svg.textContent = '';
  bar.hidden = false;
  img.src = `/api/events/${ev.id}/frame.jpg`;
  const tag = $('#stopTag');
  tag.dataset.level = ev.level;
  tag.textContent = `${LEVEL_TAG[ev.level]}${ev.setpoint ? ` ${ev.setpoint}` : ''}`;
  $('#stopWhat').innerHTML = `<span class="mono">${timeStr(new Date(ev.ts))}</span> — ${esc(evText(ev, cam))}. Стоп-кадр с разметкой сервера.`;
  const snaps = snapshotsOf(state.stop.camId);
  const i = snaps.findIndex((e) => e.id === ev.id);
  $('#stopPrev').disabled = i < 0 || i >= snaps.length - 1;
  $('#stopNext').disabled = i <= 0;
  renderFilm();
  renderCorners();
  renderStale();
}

function renderFilm() {
  const film = $('#film');
  const cam = selected();
  const snaps = cam ? snapshotsOf(cam.id).slice(0, 16) : [];
  $('#filmCount').textContent = String(cam ? snapshotsOf(cam.id).length : 0);
  $('#btnFilm').setAttribute('aria-pressed', String(filmOpen));
  const show = (filmOpen || !!state.stop) && snaps.length > 0;
  film.hidden = !show;
  if (!show) return;
  film.innerHTML = snaps.map((e) => `
    <button data-ev="${e.id}" aria-current="${state.stop && state.stop.eventId === e.id}" title="${esc(evText(e, cam))}">
      <img src="/api/events/${e.id}/frame.jpg" alt="" loading="lazy">
      <span data-level="${e.level}">${timeStr(new Date(e.ts))}${e.setpoint ? ` ${e.setpoint}` : ''}</span>
    </button>`).join('');
  $$('button', film).forEach((b) => b.addEventListener('click', () => openStop(Number(b.dataset.ev))));
}

// ---------------------------------------------------------------- сборка
function onReading(camId) {
  updateTabLevel(camId);
  if (camId !== state.selectedId) return;
  if (!state.stop) renderOverlay();
  renderCorners();
  renderStale();
}

export function initViewer() {
  $$('[data-layer]').forEach((cb) => {
    const saved = localStorage.getItem(`gv.layer.${cb.dataset.layer}`);
    if (saved !== null) cb.checked = saved === '1';
    layers[cb.dataset.layer] = cb.checked;
    cb.addEventListener('change', () => {
      layers[cb.dataset.layer] = cb.checked;
      localStorage.setItem(`gv.layer.${cb.dataset.layer}`, cb.checked ? '1' : '0');
      renderOverlay();
    });
  });
  $('#btnFilm').addEventListener('click', () => { filmOpen = !filmOpen; renderFilm(); });
  $('#stopLive').addEventListener('click', closeStop);
  const step = (dir) => {
    const snaps = snapshotsOf(state.stop.camId);
    const i = snaps.findIndex((e) => e.id === state.stop.eventId) + dir;
    if (snaps[i]) openStop(snaps[i].id);
  };
  $('#stopPrev').addEventListener('click', () => step(1));
  $('#stopNext').addEventListener('click', () => step(-1));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && state.stop && !document.querySelector('dialog[open]')) closeStop();
  });
  img.addEventListener('load', () => { if (!frameWH) renderOverlay(); });
  new ResizeObserver(() => renderOverlay()).observe(media);

  on('cams', () => { renderTabs(); renderVeil(); renderFilm(); });
  on('select', () => {
    frameWH = null;
    img.removeAttribute('src');
    renderTabs();
    renderVeil();
    const cam = selected();
    $('#lnkMjpeg').href = cam ? `/api/cameras/${cam.id}/mjpeg` : '#';
  });
  on('stop', renderStop);
  on('reading', onReading);
  on('status', (id) => { updateTabLevel(id); if (id === state.selectedId) { renderCorners(); renderStale(); } });
  on('conn', () => { for (const c of camList()) updateTabLevel(c.id); renderStale(); });
  on('events', () => { renderFilm(); });
  on('roi-draft', (draft) => { roiDraft = draft; renderOverlay(); });
  setInterval(renderCorners, 1000);
}
