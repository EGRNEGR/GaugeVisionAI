// Тренд выбранного прибора: 15 мин, 1 ч или текущая смена; метки срабатываний
// ведут к стоп-кадрам.
import { $, $$, decimalsFor, shiftStart, shiftEnd, hmStr } from './util.js';
import { state, on, selected, eventsSorted } from './store.js';
import { fetchSeries, pushLive } from './series.js';
import { drawTrend, pointAt, tipText } from './plot.js';
import { openStop, evText } from './viewer.js';

const canvas = $('#trendCanvas');
const tip = $('#trendTip');
let range = localStorage.getItem('gv.trend') || 'shift';
let series = null;
let geo = null;
let dirty = true;
let loadSeq = 0;

function window_() {
  if (range === 'shift') {
    // смена с начала до текущего момента: будущие часы смены не сжимают данные
    const s = shiftStart();
    const now = Date.now();
    const x1 = Math.min(shiftEnd(s).getTime(), now + Math.max(60000, (now - s.getTime()) * 0.03));
    return { x0: s.getTime(), x1: Math.max(x1, s.getTime() + 15 * 60000), since: s };
  }
  const span = Number(range) * 1000;
  const x1 = Date.now();
  return { x0: x1 - span, x1, since: new Date(x1 - span) };
}

async function load() {
  const cam = selected();
  const seq = ++loadSeq;
  series = null;
  dirty = true;
  if (!cam) return;
  const { since } = window_();
  try {
    const s = await fetchSeries(cam.id, since, range === 'shift' ? 720 : 450);
    if (seq === loadSeq) { series = s; dirty = true; }
  } catch (_) { /* следующая попытка — по таймеру */ }
}

function draw() {
  if (!dirty) return;
  dirty = false;
  const cam = selected();
  $('#hTrend').textContent = cam ? `Тренд: ${cam.data.name}` : 'Тренд';
  $('#lnkCsv').toggleAttribute('hidden', !cam);
  if (cam) $('#lnkCsv').href = `/api/cameras/${cam.id}/export.csv`;
  if (!cam) { canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height); geo = null; return; }
  const { x0, x1 } = window_();
  const events = eventsSorted().filter((e) => e.kind === 'alarm' && e.cam_id === cam.id);
  geo = drawTrend(canvas, { series, cam, x0, x1, events, decimals: decimalsFor(cam.data) });
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
  $$('[data-range]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.range === range));
    b.addEventListener('click', () => {
      range = b.dataset.range;
      localStorage.setItem('gv.trend', range);
      $$('[data-range]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      load();
    });
  });
  canvas.addEventListener('pointermove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const cam = selected();
    const m = markAt(x);
    const q = pointAt(geo, x);
    canvas.style.cursor = m && m.ev.has_frame ? 'pointer' : 'crosshair';
    if (!cam || (!m && !q)) { tip.hidden = true; return; }
    tip.hidden = false;
    tip.textContent = m
      ? `${hmStr(new Date(m.ev.ts))}  ${evText(m.ev, cam)}${m.ev.has_frame ? ' — щелчок открывает стоп-кадр' : ''}`
      : tipText(q, cam.data.unit, decimalsFor(cam.data));
    const tw = tip.offsetWidth;
    tip.style.left = `${Math.min(rect.width - tw - 4, Math.max(4, x + 12))}px`;
    tip.style.top = '8px';
  });
  canvas.addEventListener('pointerleave', () => { tip.hidden = true; });
  canvas.addEventListener('click', (e) => {
    const m = markAt(e.clientX - canvas.getBoundingClientRect().left);
    if (m && m.ev.has_frame) openStop(m.ev.id);
  });
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'Тренд выбранного прибора: среднее, минимум и максимум, уставки и срабатывания');

  on('select', load);
  on('cam-config', (id) => { if (id === state.selectedId) load(); });
  on('reading', (id) => {
    if (id !== state.selectedId || !series) return;
    const r = selected().reading;
    if (r && r.valid) { pushLive(series, Date.parse(r.ts), r.value, r.level); dirty = true; }
  });
  on('events', () => { dirty = true; });
  new ResizeObserver(() => { dirty = true; }).observe($('#trendBody'));

  setInterval(draw, 500);
  setInterval(() => { dirty = true; }, 2000);
  setInterval(load, 60000);
}
