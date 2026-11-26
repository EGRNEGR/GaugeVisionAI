// Просмотр кадра и векторной CV-разметки в инспекторе прибора.
// Жёсткое правило HMI: статус потери потока НИКОГДА не перекрывает область ROI/стрелки/шкалы,
// а выводится в компактный верхний баннер #staleNote над окном кадра.
import { $, $$, esc, fmt, decimalsFor, timeStr, durStr, LEVEL_TAG, DIAL_SOURCE, PHONE_STAGE_TEXT, evText } from './util.js';
import { state, on, emit, selected, select, setDetailOpen, isSimulated, evaluateInstrument, snapshotsOf } from './store.js';
import { openPhoneDialog } from './devices.js';

const videoSec = $('#detVideoSec');
const media = $('#media');
const img = $('#frame');
const svg = $('#overlay');
const NS = 'http://www.w3.org/2000/svg';

const layers = { box: true, scale: true, needle: true, labels: true };
let frameMode = localStorage.getItem('gv.fmode') || 'overlay';
let frameTimer = null;
let activeCamId = null;
let frameBlobUrl = null;
let frameWH = null;
let filmOpen = false;

function revokeFrameUrl() {
  if (frameBlobUrl) {
    URL.revokeObjectURL(frameBlobUrl);
    frameBlobUrl = null;
  }
}

const EMPTY_IMG = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

function stopPolling(clearImg = false) {
  clearTimeout(frameTimer);
  frameTimer = null;
  activeCamId = null;
  if (clearImg) {
    img.dataset.empty = 'true';
    img.src = EMPTY_IMG;
    revokeFrameUrl();
  }
}

function shouldPollLiveFrame() {
  const cam = selected();
  return (
    state.view === 'monitor'
    && state.detailOpen
    && state.inspector.mode !== 'collapsed'
    && !state.stop
    && !!cam
    && !isSimulated(cam)
  );
}

function syncPolling() {
  if (!shouldPollLiveFrame()) {
    stopPolling(!state.stop);
    return;
  }
  const cam = selected();
  if (activeCamId === cam.id && frameTimer !== null) return;
  stopPolling(false);
  activeCamId = cam.id;
  const targetId = cam.id;

  const tick = async () => {
    if (!shouldPollLiveFrame() || activeCamId !== targetId) {
      stopPolling(false);
      return;
    }
    if (document.hidden) {
      frameTimer = setTimeout(tick, 1000);
      return;
    }
    const t0 = performance.now();
    const wantServerOv = frameMode === 'server' ? 1 : 0;
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(targetId)}/frame.jpg?overlay=${wantServerOv}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      if (!shouldPollLiveFrame() || activeCamId !== targetId) {
        URL.revokeObjectURL(url);
        return;
      }
      const prev = frameBlobUrl;
      frameBlobUrl = url;
      img.dataset.empty = 'false';
      img.src = url;
      try { await img.decode(); } catch (_) { /* следующий кадр обновит */ }
      if (prev) URL.revokeObjectURL(prev);
      frameTimer = setTimeout(tick, Math.max(80, 280 - (performance.now() - t0)));
    } catch (_) {
      frameTimer = setTimeout(tick, 1500);
    }
  };
  tick();
}

function el(name, attrs, text) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}
const NSS = { 'vector-effect': 'non-scaling-stroke' };

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

export function renderOverlay() {
  svg.textContent = '';
  const cam = selected();
  if (!cam || isSimulated(cam) || state.stop || frameMode !== 'overlay') return;
  const r = cam.reading;
  const g = r && r.geom;
  if (g) frameWH = { w: g.w, h: g.h };
  else if (img.naturalWidth) frameWH = { w: img.naturalWidth, h: img.naturalHeight };
  if (!frameWH) return;

  const { w, h } = frameWH;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.dataset.level = (r && r.valid && r.level) || 'normal';
  const k = Math.min(media.clientWidth / w, media.clientHeight / h) || 1;
  const showLbls = layers.labels && media.clientWidth >= 320;
  const d = decimalsFor(cam.data);
  const root = el('g', {});
  svg.appendChild(root);

  if (!g) return;
  if (layers.box) {
    const [cx, cy, a, b, ang] = g.ellipse;
    root.appendChild(el('ellipse', { class: 'ell', cx, cy, rx: a, ry: b, transform: `rotate(${ang} ${cx} ${cy})`, ...NSS, 'stroke-width': 1 }));
    const [bx, by, bw, bh] = g.bbox;
    root.appendChild(el('rect', { class: 'bbox', x: bx, y: by, width: bw, height: bh, ...NSS, 'stroke-width': 1 }));
    if (showLbls) {
      const txt = `ROI: ${DIAL_SOURCE[g.source] || g.source} (${fmt(g.score, 2)})`;
      const above = by - 4 / k;
      label(root, bx, above - 20 / k > 0 ? above : by + 22 / k, [txt], k);
    }
  }
  if (layers.scale) {
    for (const z of g.zones) {
      root.appendChild(el('polyline', { class: 'zone', 'data-level': z.level, points: z.points.map((p) => p.join(',')).join(' '), ...NSS, 'stroke-width': 3 }));
    }
    for (const ray of g.rays) {
      const [p0, p1] = ray.points;
      root.appendChild(el('line', { class: 'ray', x1: p0[0], y1: p0[1], x2: p1[0], y2: p1[1], ...NSS, 'stroke-width': 1 }));
    }
  }
  if (layers.needle && g.needle) {
    const [[x0, y0], [x1, y1]] = g.needle;
    root.appendChild(el('line', { class: 'needle', x1: x0, y1: y0, x2: x1, y2: y1, ...NSS, 'stroke-width': 2 }));
    root.appendChild(el('circle', { class: 'hub', cx: x0, cy: y0, r: 4 / k }));
    const ang = Math.atan2(y1 - y0, x1 - x0);
    const s = 8 / k;
    const tri = [
      [x1 + Math.cos(ang) * s, y1 + Math.sin(ang) * s],
      [x1 + Math.cos(ang + 2.5) * s, y1 + Math.sin(ang + 2.5) * s],
      [x1 + Math.cos(ang - 2.5) * s, y1 + Math.sin(ang - 2.5) * s],
    ];
    root.appendChild(el('polygon', { class: 'tip', points: tri.map((p) => p.join(',')).join(' ') }));
    if (showLbls && r && r.valid) {
      const [ecx, ecy, ea, eb] = g.ellipse;
      const R = Math.max(ea, eb) * 1.05 + 6 / k;
      const c = Math.cos(ang), sn = Math.sin(ang);
      label(root, ecx + c * R, ecy + sn * R + (sn > 0 ? 26 / k : 0), [
        `${fmt(r.value, d)} ${cam.data.unit}`,
        `θ ${fmt(r.angle, 1)}°, увер. ${fmt(r.confidence, 2)}`,
      ], k, c >= 0 ? 'start' : 'end');
    }
  }
}

function renderStatusOverlay() {
  const cam = selected();
  const veil = $('#veil');
  const note = $('#staleNote'); // Расположен в верхнем баннере НАД #media — не перекрывает циферблат!
  if (!cam || isSimulated(cam) || state.stop) {
    veil.hidden = true;
    note.hidden = true;
    videoSec.dataset.stale = 'false';
    return;
  }

  const st = cam.stream || {};
  const ev = evaluateInstrument(cam);
  const framesTotal = Number(st.frames_total || 0);

  if (framesTotal === 0 && cam.status !== 'online') {
    veil.hidden = false;
    note.hidden = true;
    videoSec.dataset.stale = 'false';
    const stageTxt = cam.data.type === 'phone_ws'
      ? (PHONE_STAGE_TEXT[cam.data.phone_stage] || 'Камера телефона не подключена')
      : 'Источник видео не подключён';
    veil.innerHTML = `<h3>${esc(stageTxt)}</h3>
      <p>Отсканируйте QR-код на смартфоне Android, разрешите доступ к задней камере и нажмите «Начать трансляцию».</p>
      <div><button class="btn sm primary" type="button" id="btnVeilQr">Подключить по QR-коду</button></div>`;
    $('#btnVeilQr', veil)?.addEventListener('click', () => openPhoneDialog(cam.id));
    return;
  }

  veil.hidden = true;
  const notFresh = !ev.hasFreshValid;
  videoSec.dataset.stale = String(cam.status !== 'online');
  note.hidden = !notFresh;
  if (notFresh) {
    if (!state.connected) {
      note.textContent = 'Связь пульта с сервером потеряна — показан последний принятый кадр';
    } else if (cam.status !== 'online') {
      const age = Number.isFinite(ev.ageS) ? `, достоверный замер ${durStr(ev.ageS)} назад` : '';
      note.textContent = `Поток кадров прерван — ниже открыт последний кадр без перекрытия шкалы${age}`;
    } else if (ev.measState === 'needs_calibration') {
      note.textContent = 'Стрелка вне рабочей дуги шкалы — проверьте направление CW/CCW или углы θmin / θmax';
    } else if (ev.measState === 'hold') {
      note.textContent = `Удержание значения: стрелка не подтверждена в текущем кадре (${durStr(ev.ageS)} назад)`;
    } else if (ev.measState === 'no_fresh_data') {
      note.textContent = `Нет свежих достоверных отсчётов (${durStr(ev.ageS)} назад)`;
    } else {
      note.textContent = 'Кадры поступают — поиск устойчивого вектора стрелки';
    }
  }
}

export function openStop(eventId) {
  const ev = state.events.get(eventId);
  if (!ev || !ev.has_frame) return;
  if (ev.cam_id && ev.cam_id !== state.selectedId) select(ev.cam_id, { openDetail: true });
  else setDetailOpen(true);
  state.stop = { camId: ev.cam_id, eventId };
  emit('stop', state.stop);
}

export function closeStop() {
  if (!state.stop) return;
  state.stop = null;
  emit('stop', null);
}

function renderFilm() {
  const film = $('#film');
  const cam = selected();
  const snaps = (cam && !isSimulated(cam)) ? snapshotsOf(cam.id).slice(0, 16) : [];
  $('#filmCount').textContent = String(cam && !isSimulated(cam) ? snapshotsOf(cam.id).length : 0);
  $('#btnFilm').setAttribute('aria-pressed', String(filmOpen));
  const show = (filmOpen || !!state.stop) && snaps.length > 0;
  film.hidden = !show;
  if (!show) return;
  film.innerHTML = snaps.map((e) => `
    <button type="button" data-ev="${e.id}" aria-current="${!!(state.stop && state.stop.eventId === e.id)}" title="${esc(evText(e, cam))}">
      <img src="/api/events/${e.id}/frame.jpg" alt="" loading="lazy">
      <span data-level="${e.level}">${timeStr(new Date(e.ts))}${e.setpoint ? ` ${e.setpoint}` : ''}</span>
    </button>`).join('');
  $$('button', film).forEach((b) => b.addEventListener('click', () => openStop(Number(b.dataset.ev))));
}

function renderStopBar() {
  const bar = $('#stopbar');
  if (!state.stop) {
    bar.hidden = true;
    renderFilm();
    syncPolling();
    renderOverlay();
    renderStatusOverlay();
    return;
  }
  const ev = state.events.get(state.stop.eventId);
  const cam = state.cams.get(state.stop.camId);
  stopPolling(false);
  revokeFrameUrl();
  svg.textContent = '';
  bar.hidden = false;
  img.dataset.empty = 'false';
  img.src = `/api/events/${ev.id}/frame.jpg`;
  const tag = $('#stopTag');
  tag.dataset.level = ev.level;
  tag.textContent = `${LEVEL_TAG[ev.level]}${ev.setpoint ? ` ${ev.setpoint}` : ''}`;
  $('#stopWhat').textContent = `${timeStr(new Date(ev.ts))} — ${evText(ev, cam)}`;
  const snaps = snapshotsOf(state.stop.camId);
  const i = snaps.findIndex((e) => e.id === ev.id);
  $('#stopPrev').disabled = i < 0 || i >= snaps.length - 1;
  $('#stopNext').disabled = i <= 0;
  renderFilm();
  renderStatusOverlay();
}

export function initViewer() {
  $$('#segFrameMode [data-fmode]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.fmode === frameMode));
    b.addEventListener('click', () => {
      frameMode = b.dataset.fmode;
      localStorage.setItem('gv.fmode', frameMode);
      $$('#segFrameMode [data-fmode]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      $('#detLayers').hidden = frameMode !== 'overlay';
      stopPolling(false);
      syncPolling();
      renderOverlay();
    });
  });
  $('#detLayers').hidden = frameMode !== 'overlay';

  $$('#detLayers [data-layer]').forEach((cb) => {
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
  const stepSnap = (dir) => {
    if (!state.stop) return;
    const snaps = snapshotsOf(state.stop.camId);
    const i = snaps.findIndex((e) => e.id === state.stop.eventId) + dir;
    if (snaps[i]) openStop(snaps[i].id);
  };
  $('#stopPrev').addEventListener('click', () => stepSnap(1));
  $('#stopNext').addEventListener('click', () => stepSnap(-1));

  img.addEventListener('load', () => { if (!frameWH) renderOverlay(); });
  new ResizeObserver(() => renderOverlay()).observe(media);

  const refreshAll = () => {
    syncPolling();
    renderFilm();
    renderOverlay();
    renderStatusOverlay();
  };

  on('view', refreshAll);
  on('detail-toggle', refreshAll);
  on('inspector-layout', refreshAll);
  on('select', () => { frameWH = null; stopPolling(true); refreshAll(); });
  on('stop', renderStopBar);
  on('reading', (id) => { if (id === state.selectedId) { renderOverlay(); renderStatusOverlay(); } });
  on('status', (id) => { if (id === state.selectedId) { syncPolling(); renderStatusOverlay(); } });
  on('freshness', () => { if (state.detailOpen) renderStatusOverlay(); });
  on('conn', refreshAll);
  on('events', renderFilm);
}
