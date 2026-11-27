// Вкладка «Щит»: несколько приборов одной камерой (Multi-Gauge Vision).
// Общий кадр источника с разметкой всех приборов, обнаружение циферблатов, контролируемая регистрация
// новых приборов без дублей, увеличенная ROI выбранного прибора и переход к калибровке и истории.
import { $, esc, api, toast, confirmDlg, fmt, decimalsFor, LEVEL_TAG } from './util.js';
import { state, on, emit, camList, select, setView, sourceIdOf, isSimulated } from './store.js';
import { fillGaugeSelect, fillUnitSelect } from './devices.js';
import { openCalibrationFor } from './control.js';

const NS = 'http://www.w3.org/2000/svg';
const TRACK_TEXT = {
  locked: 'захвачен', reacquired: 'найден снова', coasting: 'удержание', predicted: 'по соседям',
  ambiguous: 'неоднозначно', lost: 'потерян', manual: 'ручная ROI', init: 'ожидание',
};

let sourceId = null;
let candidates = [];           // кандидаты последней детекции
let pick = null;               // { kind: 'inst', id } | { kind: 'cand', index }
let frameTimer = null;
let blobUrl = null;
let frameWH = null;

const img = () => $('#mgFrameImg');
const svg = () => $('#mgOverlay');

function sources() {
  // источники — реальные камеры (основные приборы), не позиции симуляции
  return camList().filter((c) => !isSimulated(c) && c.data.is_primary !== false);
}

function sourceInstruments(sid) {
  return camList().filter((c) => sourceIdOf(c) === sid);
}

function anchorOf(cam) {
  const a = cam.data.anchor_roi;
  return a && Number.isFinite(a.cx) && Number.isFinite(a.r) ? a : null;
}

function toPx(a) {
  const [w, h] = frameWH;
  const s = Math.min(w, h);
  const ax = Array.isArray(a.axes) ? a.axes.map((v) => v * s) : [a.r * s, a.r * s];
  return { x: a.cx * w, y: a.cy * h, rx: ax[0], ry: ax[1], angle: a.angle || 0 };
}

function levelOf(cam) {
  const r = cam.reading;
  if (!r || !r.valid) return 'invalid';
  return r.level || 'normal';
}

function valueText(cam) {
  const r = cam.reading;
  if (!r || r.value === null || r.value === undefined) return '—';
  return `${fmt(r.value, decimalsFor(cam.data))} ${cam.data.unit || ''}`;
}

function trackText(cam) {
  const st = cam.reading?.track?.state;
  if (st) return TRACK_TEXT[st] || st;
  if (!cam.reading) return 'нет данных';
  return cam.reading.valid ? 'однокамерный режим' : (cam.reading.invalid_reason || 'нет отсчёта');
}

function el(name, attrs, text) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

function renderOverlay() {
  const s = svg();
  s.replaceChildren();
  if (!frameWH || !sourceId) return;
  s.setAttribute('viewBox', `0 0 ${frameWH[0]} ${frameWH[1]}`);
  const fs = Math.max(12, Math.min(frameWH[0], frameWH[1]) / 40);
  for (const cam of sourceInstruments(sourceId)) {
    let g = null;
    const a = anchorOf(cam);
    const geom = cam.reading?.geom;
    let shape = null;
    if (geom?.ellipse && geom.w && geom.h) {
      // текущая ROI из конвейера (в пикселях обработанного кадра той же пропорции)
      const k = frameWH[0] / geom.w;
      const [ex, ey, ea, eb, eang] = geom.ellipse;
      shape = { x: ex * k, y: ey * k, rx: ea * k, ry: eb * k, angle: eang };
    } else if (a) {
      shape = toPx(a);
    }
    if (!shape) continue;
    g = el('g', { class: `mg-inst lvl-${levelOf(cam)}${pick?.kind === 'inst' && pick.id === cam.id ? ' is-picked' : ''}`, 'data-id': cam.id, tabindex: '0', role: 'button', 'aria-label': `${cam.data.code || ''} ${cam.data.name}` });
    g.append(el('ellipse', { cx: shape.x, cy: shape.y, rx: shape.rx, ry: shape.ry, transform: `rotate(${shape.angle} ${shape.x} ${shape.y})` }));
    if (geom?.needle && cam.reading?.valid) {
      const k = frameWH[0] / geom.w;
      const [[x0, y0], [x1, y1]] = geom.needle;
      g.append(el('line', { x1: x0 * k, y1: y0 * k, x2: x1 * k, y2: y1 * k, class: 'needle' }));
    }
    const label = `${cam.data.code || cam.data.name} ${valueText(cam)}`;
    const ty = Math.max(fs, shape.y - shape.ry - fs * 0.4);
    g.append(el('text', { x: shape.x - shape.rx, y: ty, 'font-size': fs }, label));
    s.append(g);
  }
  candidates.forEach((c, i) => {
    // зарегистрированные и основной циферблат камеры уже ведутся — их разметка выше
    if (c.registered_instrument_id || c.is_primary_dial) return;
    const p = toPx(c.anchor);
    const g = el('g', { class: `mg-cand${pick?.kind === 'cand' && pick.index === i ? ' is-picked' : ''}`, 'data-cand': String(i), tabindex: '0', role: 'button', 'aria-label': `Найденный циферблат ${i + 1}` });
    g.append(el('ellipse', { cx: p.x, cy: p.y, rx: p.rx, ry: p.ry, transform: `rotate(${p.angle} ${p.x} ${p.y})` }));
    g.append(el('text', { x: p.x - fs * 0.3, y: p.y + fs * 0.35, 'font-size': fs * 1.2 }, String(i + 1)));
    s.append(g);
  });
}

function renderTable() {
  const tb = $('#mgTable tbody');
  const list = sourceId ? sourceInstruments(sourceId) : [];
  $('#mgCount').textContent = list.length ? `${list.length} прибор(а/ов)` : '—';
  $('#tabCntPanel').textContent = String(list.length || '—');
  tb.innerHTML = list.map((c) => `
    <tr data-id="${esc(c.id)}" class="${pick?.kind === 'inst' && pick.id === c.id ? 'is-picked' : ''}">
      <td class="mono">${esc(c.data.code || '—')}</td>
      <td>${esc(c.data.name)}${c.data.is_primary ? ' <span class="mg-tag">основной</span>' : ''}</td>
      <td class="mono lvl-${levelOf(c)}">${esc(valueText(c))}</td>
      <td>${esc(trackText(c))}</td>
      <td class="mono">${c.data.modbus_slot ?? '—'}</td>
    </tr>`).join('') || '<tr><td colspan="5" class="mg-muted">Нет приборов</td></tr>';
}

function zoomCanvas(anchor) {
  const cv = document.createElement('canvas');
  cv.width = 220;
  cv.height = 220;
  cv.className = 'mg-zoom';
  const im = img();
  if (!frameWH || !anchor || im.dataset.empty === 'true') return cv;
  const p = toPx(anchor);
  const half = Math.max(p.rx, p.ry) * 1.15;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#07090b';
  ctx.fillRect(0, 0, 220, 220);
  const k = im.naturalWidth / frameWH[0];
  ctx.drawImage(im, (p.x - half) * k, (p.y - half) * k, 2 * half * k, 2 * half * k, 0, 0, 220, 220);
  return cv;
}

function renderDetail() {
  const body = $('#mgDetailBody');
  const title = $('#mgDetailTitle');
  if (!pick) {
    title.textContent = 'Прибор не выбран';
    body.innerHTML = '<p class="mg-muted">Выберите прибор на кадре или в списке.</p>';
    return;
  }
  if (pick.kind === 'inst') {
    const cam = state.cams.get(pick.id);
    if (!cam) { pick = null; renderDetail(); return; }
    title.textContent = `${cam.data.code || ''} ${cam.data.name}`.trim();
    const r = cam.reading || {};
    body.replaceChildren();
    const a = anchorOf(cam) || (cam.reading?.geom ? geomAnchor(cam.reading.geom) : null);
    body.append(zoomCanvas(a));
    const dl = document.createElement('dl');
    dl.className = 'mg-kv';
    const kv = [
      ['Показание', valueText(cam)],
      ['Уровень', r.valid ? (LEVEL_TAG[r.level] || r.level || '—') : 'нет достоверного отсчёта'],
      ['Трекер', trackText(cam)],
      ['Причина отказа', r.valid ? '—' : (r.invalid_reason || '—')],
      ['Шкала', `${fmt(cam.data.calibration?.v_min, 2)}–${fmt(cam.data.calibration?.v_max, 2)} ${cam.data.unit || ''}`],
      ['Ревизия калибровки', String(cam.data.calibration_rev ?? 0)],
      ['Слот Modbus / циферблат', `${cam.data.modbus_slot ?? '—'} / ${cam.data.gauge_slot ?? 0}`],
    ];
    dl.innerHTML = kv.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
    body.append(dl);
    const foot = document.createElement('div');
    foot.className = 'foot';
    foot.innerHTML = `
      <button class="btn sm primary" type="button" data-act="cal">Калибровка и уставки</button>
      <button class="btn sm" type="button" data-act="hist">История</button>
      ${cam.data.is_primary ? '' : '<button class="btn sm danger" type="button" data-act="del">Удалить прибор</button>'}`;
    body.append(foot);
    foot.addEventListener('click', (e) => onDetailAction(e, cam));
    return;
  }
  const c = candidates[pick.index];
  if (!c) { pick = null; renderDetail(); return; }
  title.textContent = `Новый циферблат № ${pick.index + 1}`;
  body.replaceChildren(zoomCanvas(c.anchor));
  const form = document.createElement('form');
  form.className = 'mg-form';
  form.noValidate = true;
  form.innerHTML = `
    <label class="field"><span>Наименование</span><input class="input sm" name="name" maxlength="200" required></label>
    <label class="field"><span>Код позиции</span><input class="input sm mono" name="code" maxlength="40" placeholder="PI-102"></label>
    <label class="field"><span>Тип прибора</span><select class="input sm" name="gauge_type"></select></label>
    <label class="field"><span>Единица</span><select class="input sm" name="unit"></select></label>
    <label class="field"><span>Начало шкалы</span><input class="input sm mono" name="v_min" inputmode="decimal" value="0"></label>
    <label class="field"><span>Конец шкалы</span><input class="input sm mono" name="v_max" inputmode="decimal" value="10"></label>
    <p class="mg-muted span2">Углы начала и конца шкалы по умолчанию — 135° и 45° по часовой; точно они задаются по кадру на вкладке «Калибровка» после регистрации.</p>
    <small class="field-err span2" data-ferr="form"></small>
    <div class="foot span2"><button class="btn sm primary" type="submit">Зарегистрировать прибор</button></div>`;
  body.append(form);
  fillGaugeSelect(form.gauge_type);
  fillUnitSelect(form.unit, form.gauge_type.value, null);
  form.gauge_type.addEventListener('change', () => fillUnitSelect(form.unit, form.gauge_type.value, null));
  form.addEventListener('submit', (e) => { e.preventDefault(); registerCandidate(form, c); });
}

function geomAnchor(geom) {
  if (!geom?.ellipse || !geom.w) return null;
  const [ex, ey, ea, eb] = geom.ellipse;
  const s = Math.min(geom.w, geom.h);
  return { cx: ex / geom.w, cy: ey / geom.h, r: Math.sqrt(ea * eb) / s, axes: [ea / s, eb / s], angle: geom.ellipse[4] };
}

function parseDec(v) {
  const n = Number(String(v).trim().replace(',', '.').replace('−', '-'));
  return Number.isFinite(n) ? n : null;
}

async function registerCandidate(form, cand) {
  const err = form.querySelector('[data-ferr="form"]');
  const name = form.name.value.trim();
  const vMin = parseDec(form.v_min.value);
  const vMax = parseDec(form.v_max.value);
  if (!name) { err.textContent = 'Укажите наименование прибора'; return; }
  if (vMin === null || vMax === null || vMin === vMax) { err.textContent = 'Начало и конец шкалы — разные числа'; return; }
  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const res = await api(`/api/sources/${encodeURIComponent(sourceId)}/instruments`, {
      method: 'POST',
      body: {
        name, code: form.code.value.trim() || null, gauge_type: form.gauge_type.value, unit: form.unit.value,
        roi: cand.anchor,
        calibration: { v_min: vMin, v_max: vMax, theta_min: 135, theta_max: 45, direction: 'cw' },
      },
    });
    toast(`Прибор зарегистрирован: ${res.name}`);
    cand.registered_instrument_id = res.id;
    pick = { kind: 'inst', id: res.id };
    renderAll();
  } catch (e) {
    err.textContent = e.message;
    btn.disabled = false;
  }
}

async function onDetailAction(e, cam) {
  const act = e.target.closest('button')?.dataset.act;
  if (act === 'cal') {
    openCalibrationFor(cam.id);
  } else if (act === 'hist') {
    select(cam.id, { openDetail: false });
    setView('history');
  } else if (act === 'del') {
    const ok = await confirmDlg('Удалить прибор щита?',
      `Прибор «${cam.data.name}» и его архив будут удалены. Камера и остальные приборы продолжат работу.`, 'Удалить');
    if (!ok) return;
    try {
      await api(`/api/instruments/${encodeURIComponent(cam.id)}`, { method: 'DELETE' });
      pick = null;
      toast('Прибор удалён');
      renderAll();
    } catch (er) {
      toast(er.message, 'err');
    }
  }
}

async function detect() {
  if (!sourceId) return;
  const btn = $('#btnMgDetect');
  btn.disabled = true;
  $('#mgStatus').textContent = 'Поиск циферблатов…';
  try {
    const res = await api(`/api/sources/${encodeURIComponent(sourceId)}/instruments/detect`, { method: 'POST' });
    candidates = res.candidates || [];
    const fresh = candidates.filter((c) => !c.registered_instrument_id && !c.is_primary_dial).length;
    $('#mgStatus').textContent = `Найдено ${candidates.length}, новых ${fresh} — ${res.detect?.detect_ms ?? '—'} мс`;
    $('#btnMgClear').hidden = candidates.length === 0;
    renderOverlay();
  } catch (e) {
    $('#mgStatus').textContent = e.message;
    toast(e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

function stopFrames() {
  if (frameTimer !== null) clearTimeout(frameTimer);
  frameTimer = null;
}

function pollFrames() {
  stopFrames();
  if (state.view !== 'panel' || !sourceId) return;
  const sid = sourceId;
  const tick = async () => {
    if (state.view !== 'panel' || sid !== sourceId) return;
    if (document.hidden) { frameTimer = setTimeout(tick, 1000); return; }
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(sid)}/frame.jpg?overlay=0`, { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      const im = img();
      const prev = blobUrl;
      blobUrl = url;
      im.src = url;
      try { await im.decode(); } catch (_) { /* следующий кадр */ }
      if (prev) URL.revokeObjectURL(prev);
      im.dataset.empty = 'false';
      $('#mgEmpty').hidden = true;
      const wh = [im.naturalWidth, im.naturalHeight];
      if (!frameWH || frameWH[0] !== wh[0] || frameWH[1] !== wh[1]) frameWH = wh;
      renderOverlay();
      frameTimer = setTimeout(tick, 700);
    } catch (_) {
      $('#mgEmpty').hidden = false;
      frameTimer = setTimeout(tick, 1500);
    }
  };
  tick();
}

function renderSources() {
  const sel = $('#mgSource');
  const list = sources();
  if (!sourceId || !list.some((c) => c.id === sourceId)) sourceId = list[0]?.id || null;
  sel.innerHTML = list.map((c) => `<option value="${esc(c.id)}">${esc(c.data.name)}</option>`).join('')
    || '<option value="">Нет подключённых камер</option>';
  if (sourceId) sel.value = sourceId;
}

function renderAll() {
  renderSources();
  renderTable();
  renderOverlay();
  renderDetail();
}

function pickFromEvent(e) {
  const g = e.target.closest('g[data-id], g[data-cand]');
  if (!g) return;
  pick = g.dataset.id ? { kind: 'inst', id: g.dataset.id } : { kind: 'cand', index: Number(g.dataset.cand) };
  renderOverlay();
  renderTable();
  renderDetail();
}

export function initMultiGauge() {
  $('#mgSource').addEventListener('change', (e) => {
    sourceId = e.target.value || null;
    candidates = [];
    pick = null;
    frameWH = null;
    renderAll();
    pollFrames();
  });
  $('#btnMgDetect').addEventListener('click', detect);
  $('#btnMgClear').addEventListener('click', () => {
    candidates = [];
    $('#btnMgClear').hidden = true;
    if (pick?.kind === 'cand') pick = null;
    renderAll();
  });
  svg().addEventListener('click', pickFromEvent);
  svg().addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pickFromEvent(e); } });
  $('#mgTable').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    pick = { kind: 'inst', id: tr.dataset.id };
    renderAll();
  });
  on('view', (v) => {
    if (v === 'panel') { renderAll(); pollFrames(); } else { stopFrames(); }
  });
  on('cams', () => { if (state.view === 'panel') renderAll(); else renderTable(); });
  on('instruments-changed', () => { if (state.view === 'panel') renderAll(); });
  on('reading', (id) => {
    if (state.view !== 'panel') return;
    const cam = state.cams.get(id);
    if (cam && sourceIdOf(cam) === sourceId) {
      renderTable();
      if (pick?.kind === 'inst' && pick.id === id) renderDetail();
    }
  });
}
