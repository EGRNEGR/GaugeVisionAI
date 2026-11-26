// Тренд внутри правого инспектора прибора (высота >= 220px, окна «15 мин» / «1 ч» / «Прогон»).
import { $, $$, decimalsFor, hmStr, evText } from './util.js';
import { state, on, selected, isSimulated, eventsSorted } from './store.js';
import { fetchSeries, pushLive } from './series.js';
import { drawTrend, pointAt, tipText } from './plot.js';
import { openStop } from './viewer.js';

const canvas = $('#detTrendCanvas');
const tip = $('#detTrendTip');
let range = '900'; // по умолчанию 15 мин для полной истории и сравнения с уставочными линиями
let series = null;
let geo = null;
let dirty = true;
let loadSeq = 0;

function activeWindow(cam) {
  const now = Date.now();
  if (range === 'run' && cam && !isSimulated(cam) && state.demo?.active_run?.camera_id === cam.id) {
    const run = state.demo.active_run;
    const t0 = Date.parse(run.started_at);
    const t1 = run.ended_at ? Date.parse(run.ended_at) : now;
    return {
      x0: t0,
      x1: Math.max(t1, t0 + 30000),
      since: new Date(t0),
      until: run.ended_at ? new Date(t1) : null,
      title: `Тренд: ${run.label} (линии уставок L / H / HH)`,
    };
  }
  const spanSec = range === 'run' ? 900 : Number(range) || 900;
  const x0 = now - spanSec * 1000;
  const lbl = spanSec >= 3600 ? '1 ч' : '15 мин';
  return {
    x0,
    x1: now,
    since: new Date(x0),
    until: null,
    title: `Тренд за ${lbl} (уставки L / H / HH)`,
  };
}

export async function reloadDetailTrend() {
  const cam = selected();
  const seq = ++loadSeq;
  series = null;
  dirty = true;
  if (!cam || !state.detailOpen || state.inspector.mode === 'collapsed' || state.view !== 'monitor') return;
  const w = activeWindow(cam);
  try {
    const s = await fetchSeries(cam.id, w.since, 180, w.until);
    if (seq === loadSeq) { series = s; dirty = true; draw(); }
  } catch (_) { /* повтор при следующем обновлении */ }
}

function draw() {
  if (!dirty || !state.detailOpen || state.inspector.mode === 'collapsed' || state.view !== 'monitor') return;
  dirty = false;
  const cam = selected();
  if (!cam) return;
  const w = activeWindow(cam);
  $('#detTrendTitle').textContent = w.title;
  const evs = eventsSorted().filter((e) => e.kind === 'alarm' && e.cam_id === cam.id);
  geo = drawTrend(canvas, {
    series,
    cam,
    x0: w.x0,
    x1: w.x1,
    events: evs,
    decimals: decimalsFor(cam.data),
  });
}

function markAt(x) {
  if (!geo) return null;
  let best = null, bd = 6;
  for (const m of geo.marks) {
    const d = Math.abs(m.x - x);
    if (d <= bd) { bd = d; best = m; }
  }
  return best;
}

export function initTrend() {
  $$('#segDetRange [data-drange]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.drange === range));
    b.addEventListener('click', () => {
      range = b.dataset.drange;
      $$('#segDetRange [data-drange]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      reloadDetailTrend();
    });
  });

  canvas.addEventListener('pointermove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const cam = selected();
    const m = markAt(x);
    const q = pointAt(geo, x);
    if (!cam || (!m && !q)) { tip.hidden = true; return; }
    tip.hidden = false;
    tip.textContent = m
      ? `${hmStr(new Date(m.ev.ts))} — ${evText(m.ev, cam)}`
      : tipText(q, cam.data.unit, decimalsFor(cam.data));
    const tw = tip.offsetWidth;
    tip.style.left = `${Math.min(rect.width - tw - 4, Math.max(4, x + 10))}px`;
    tip.style.top = '6px';
  });
  canvas.addEventListener('pointerleave', () => { tip.hidden = true; });
  canvas.addEventListener('click', (e) => {
    const m = markAt(e.clientX - canvas.getBoundingClientRect().left);
    if (m && m.ev.has_frame) openStop(m.ev.id);
  });

  new ResizeObserver(() => { dirty = true; draw(); }).observe($('#detTrendBox'));

  on('select', reloadDetailTrend);
  on('detail-toggle', (open) => { if (open) reloadDetailTrend(); });
  on('inspector-layout', () => { dirty = true; reloadDetailTrend(); });
  on('view', (v) => { if (v === 'monitor' && state.detailOpen) reloadDetailTrend(); });
  on('cam-config', (id) => { if (id === state.selectedId) reloadDetailTrend(); });
  on('cams', () => { if (state.detailOpen && state.view === 'monitor') reloadDetailTrend(); });
  on('demo-run', reloadDetailTrend);
  on('reading', (id) => {
    if (id !== state.selectedId || !series || !state.detailOpen) return;
    const r = selected()?.reading;
    if (r && r.valid && r.value !== null) {
      pushLive(series, Date.parse(r.ts), r.value, r.level);
      dirty = true;
    }
  });
  on('sim-tick', (ids) => {
    if (!state.detailOpen || !series || !ids.includes(state.selectedId)) return;
    const r = selected()?.reading;
    if (r && r.valid && r.value !== null) {
      pushLive(series, Date.parse(r.ts), r.value, r.level);
      dirty = true;
    }
  });
  on('events', () => { dirty = true; });

  setInterval(draw, 500);
  setInterval(() => { if (state.detailOpen && state.view === 'monitor') dirty = true; }, 2000);
}
