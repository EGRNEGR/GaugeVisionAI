// Вкладка «История и CSV»: выбор любого из 36 приборов (включая демопрогоны живой камеры),
// журнал инцидентов всех узлов ТЭЦ (WARNING / CRITICAL / NO_DATA), тренд с разрывами и CSV.
import { $, $$, esc, api, toast, fmt, decimalsFor, timeStr, dateStr, LEVEL_TAG, LEVEL_FULL, SOURCE_KIND_TEXT, evText } from './util.js';
import { state, on, emit, camList, livePrimaryCam, isSimulated, setView, eventsSorted } from './store.js';
import { drawTrend, pointAt, tipText } from './plot.js';
import { openSnapshotDialog } from './journal.js';
import { jumpToInstrument } from './instruments.js';

const canvas = $('#histTrendCanvas');
const tip = $('#histTrendTip');
let currentCamId = null;
let selectedRunId = 'active'; // id прогона или 'all'
let loadedRows = [];
let loadedRun = null;
let geo = null;
let showRawCsv = false;
let refreshTimer = null;

function ensureTargetCam() {
  if (currentCamId && state.cams.has(currentCamId)) {
    return state.cams.get(currentCamId);
  }
  const live = livePrimaryCam();
  const all = camList();
  currentCamId = live ? live.id : (all[0]?.id || null);
  return currentCamId ? state.cams.get(currentCamId) : null;
}

function renderIncidentsLog() {
  const ul = $('#histIncidentsList');
  const cnt = $('#histIncidentsCnt');
  if (!ul || !cnt) return;
  const incidents = eventsSorted().filter((e) => (
    (e.kind === 'alarm' && (e.level === 'alert' || e.level === 'warning'))
    || (e.kind === 'link' && e.text !== 'online')
  ));
  cnt.textContent = `${incidents.length} инцид.`;
  if (!incidents.length) {
    ul.innerHTML = '<li class="j-empty">Инцидентов (предупреждений, аварий и обрывов связи) пока не зафиксировано.</li>';
    return;
  }
  ul.innerHTML = incidents.slice(0, 120).map((ev) => {
    const cam = state.cams.get(ev.cam_id);
    const dt = new Date(ev.ts);
    const isLink = ev.kind === 'link';
    const tagLv = isLink ? 'stale' : ev.level;
    const tagTxt = isLink ? 'НЕТ ДАННЫХ' : `${LEVEL_TAG[ev.level]}${ev.setpoint ? ` ${ev.setpoint}` : ''}`;
    const groupTxt = cam?.data?.group ? ` (${cam.data.group})` : '';
    const who = cam ? `${cam.data.code} ${cam.data.short_name || cam.data.name}` : (ev.cam_name || 'Прибор');
    const desc = isLink ? 'Потеря связи с датчиком / каналом передачи данных' : evText(ev, cam);
    const snapBtn = ev.has_frame
      ? `<button class="thumb" type="button" data-hsnap="${ev.id}" title="Открыть стоп-кадр срабатывания"><img src="/api/events/${ev.id}/frame.jpg" alt="Стоп-кадр" loading="lazy"></button>`
      : '<span></span>';
    return `<li class="ev">
      <span class="time">${timeStr(dt)}</span>
      <span class="tag" data-level="${esc(tagLv)}" data-unack="${!ev.acked}">${esc(tagTxt)}</span>
      <span class="who" title="${esc(who + groupTxt)}">${esc(who)}</span>
      <span class="what">${esc(desc)}<small>${esc(cam?.data?.group || 'Станция')}${ev.acked ? ' — квитировано' : ' — требует квитирования'}</small></span>
      ${snapBtn}
      <span class="foot">${ev.cam_id && state.cams.has(ev.cam_id) ? `<button class="btn sm" type="button" data-hcam="${esc(ev.cam_id)}">Прибор</button>` : ''}</span>
    </li>`;
  }).join('');
  $$('[data-hsnap]', ul).forEach((b) => b.addEventListener('click', () => openSnapshotDialog(Number(b.dataset.hsnap))));
  $$('[data-hcam]', ul).forEach((b) => b.addEventListener('click', () => jumpToInstrument(b.dataset.hcam)));
}

function renderSelectors() {
  const camSel = $('#histCamSelect');
  const runSel = $('#histRunSelect');
  const all = camList();
  const cam = ensureTargetCam();

  camSel.innerHTML = all.map((c) => {
    const tag = isSimulated(c) ? c.data.group : 'Камера CV';
    return `<option value="${esc(c.id)}">${esc(c.data.code ? `${c.data.code} — ${c.data.short_name || c.data.name}` : c.data.name)} [${esc(tag)}]</option>`;
  }).join('');
  if (cam) camSel.value = cam.id;

  const sim = cam ? isSimulated(cam) : false;
  runSel.disabled = sim;
  $('#btnHistStartRun').disabled = sim;

  if (sim) {
    runSel.innerHTML = '<option value="sim15">Текущий режим симуляции (15 мин)</option>';
    runSel.value = 'sim15';
    $('#btnHistStopRun').disabled = true;
    return;
  }

  const runs = (state.demo?.runs || []).filter((r) => !cam || r.camera_id === cam.id);
  const activeRun = state.demo?.active_run;
  const opts = [];
  if (activeRun && (!cam || activeRun.camera_id === cam.id)) {
    opts.push({
      value: activeRun.id,
      label: `${activeRun.label} (${activeRun.ended_at ? 'завершён' : 'текущий прогон'})`,
    });
  }
  for (const r of runs) {
    if (activeRun && r.id === activeRun.id) continue;
    const t0 = timeStr(new Date(r.started_at));
    opts.push({
      value: r.id,
      label: `${r.label} (от ${t0}, отсчётов: ${r.readings_count ?? 0})`,
    });
  }
  opts.push({ value: 'all', label: 'Вся история прибора в базе' });

  const validValues = new Set(opts.map((o) => o.value));
  if (selectedRunId === 'active' || !validValues.has(selectedRunId)) {
    selectedRunId = (activeRun && (!cam || activeRun.camera_id === cam.id)) ? activeRun.id : 'all';
  }
  runSel.innerHTML = opts.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
  runSel.value = selectedRunId;

  const isRunning = activeRun && activeRun.id === selectedRunId && !activeRun.ended_at;
  $('#btnHistStopRun').disabled = !isRunning;
}

export async function refreshHistory() {
  const cam = ensureTargetCam();
  renderSelectors();
  renderIncidentsLog();
  if (!cam) return;

  try {
    if (state.demo?.enabled) {
      const demoSt = await api('/api/demo/state');
      state.demo = demoSt;
      renderSelectors();
    }
    if (isSimulated(cam)) {
      loadedRun = null;
      loadedRows = await api(`/api/instruments/${encodeURIComponent(cam.id)}/history?limit=120`);
    } else if (selectedRunId && selectedRunId !== 'all') {
      const data = await api(`/api/demo/runs/${encodeURIComponent(selectedRunId)}/readings?limit=5000`);
      loadedRun = data.run;
      loadedRows = data.readings || [];
    } else {
      loadedRun = null;
      const raw = await api(`/api/cameras/${encodeURIComponent(cam.id)}/history?limit=1000`);
      loadedRows = raw
        .filter((r) => r.value !== null && r.value !== undefined)
        .map((r) => ({
          id: r.id,
          timestamp_iso8601: r.timestamp,
          instrument_id: cam.data.code || cam.id,
          source_kind: cam.data.source_kind || 'phone_cv',
          value: r.value,
          unit: r.unit || cam.data.unit,
          raw_angle_deg: r.raw_angle,
          status_level: r.status_level,
        }));
    }
    renderHistoryContent(cam);
  } catch (e) {
    toast(`Не удалось загрузить историю: ${e.message}`, 'err');
  }
}

function buildCsvPreviewText(rows) {
  const lines = ['timestamp_iso8601;instrument_id;source_kind;value;unit;raw_angle_deg;status_level'];
  for (const r of rows) {
    lines.push([
      r.timestamp_iso8601,
      r.instrument_id,
      r.source_kind,
      Number(r.value).toFixed(4),
      r.unit,
      r.raw_angle_deg === null || r.raw_angle_deg === undefined ? '' : Number(r.raw_angle_deg).toFixed(2),
      r.status_level,
    ].join(';'));
  }
  return lines.join('\n');
}

function renderHistoryContent(cam) {
  const d = decimalsFor(cam.data);
  const unit = loadedRun?.unit || cam.data.unit;
  const srcTxt = SOURCE_KIND_TEXT[cam.data.source_kind] || 'Камера телефона (CV)';

  let intervalTxt = 'Вся история базы';
  if (loadedRun) {
    const s = new Date(loadedRun.started_at);
    const e = loadedRun.ended_at ? new Date(loadedRun.ended_at) : null;
    intervalTxt = `${dateStr(s)} ${timeStr(s)} — ${e ? timeStr(e) : 'запись идёт'}`;
  } else if (loadedRows.length) {
    const s = new Date(loadedRows[0].timestamp_iso8601);
    const e = new Date(loadedRows[loadedRows.length - 1].timestamp_iso8601);
    intervalTxt = `${timeStr(s)} — ${timeStr(e)}`;
  }

  $('#histMeta').innerHTML = [
    `<div class="kv"><dt>Прибор</dt><dd>${esc(cam.data.code ? `${cam.data.code} (${cam.data.short_name || cam.data.name})` : cam.data.name)}</dd></div>`,
    `<div class="kv"><dt>Интервал прогона</dt><dd>${esc(intervalTxt)}</dd></div>`,
    `<div class="kv"><dt>Источник данных</dt><dd>${esc(srcTxt)}</dd></div>`,
    `<div class="kv"><dt>Единица шкалы</dt><dd>${esc(unit)}</dd></div>`,
    `<div class="kv"><dt>Сохранённых отсчётов</dt><dd>${loadedRows.length}</dd></div>`,
  ].join('');

  // Ссылка скачивания CSV строго соответствует выбранному фильтру
  const dlBtn = $('#btnDownloadCsv');
  const csvHref = isSimulated(cam)
    ? `/api/instruments/${encodeURIComponent(cam.id)}/export.csv`
    : (loadedRun
      ? `/api/demo/runs/${encodeURIComponent(loadedRun.id)}/export.csv`
      : `/api/cameras/${encodeURIComponent(cam.id)}/export.csv?format=demo`);
  dlBtn.href = csvHref;
  const empty = loadedRows.length === 0;
  dlBtn.setAttribute('aria-disabled', String(empty));
  $('#lblDownloadCsv').textContent = empty ? 'Нет записей для CSV' : `Скачать CSV (${loadedRows.length})`;

  // Предпросмотр сырого CSV
  const rawBox = $('#csvRawBox');
  rawBox.hidden = !showRawCsv;
  if (showRawCsv) {
    rawBox.textContent = buildCsvPreviewText(loadedRows);
  }

  // Таблица отсчётов (новые сверху для быстрого визуального контроля, в CSV — хронологически)
  $('#histRowsCount').textContent = `${loadedRows.length} строк`;
  const tbody = $('#histTbody');
  const emptyEl = $('#histEmpty');
  if (empty) {
    tbody.innerHTML = '';
    emptyEl.hidden = false;
    emptyEl.textContent = 'В текущем показе ещё нет достоверных отсчётов с камеры телефона. Подключите Android по QR и наведите камеру на циферблат МТП-160 — записи появятся автоматически с шагом 1 с.';
  } else {
    emptyEl.hidden = true;
    const displayRows = [...loadedRows].reverse().slice(0, 300);
    tbody.innerHTML = displayRows.map((r) => {
      const dt = new Date(r.timestamp_iso8601);
      const lv = r.status_level || 'normal';
      return `<tr>
        <td class="mono">${timeStr(dt)}</td>
        <td class="mono">${esc(r.timestamp_iso8601)}</td>
        <td class="mono">${esc(r.instrument_id)}</td>
        <td>${esc(SOURCE_KIND_TEXT[r.source_kind] || r.source_kind)}</td>
        <td class="num-col">${fmt(r.value, Math.max(d, 2))}</td>
        <td>${esc(r.unit)}</td>
        <td class="num-col">${r.raw_angle_deg === null || r.raw_angle_deg === undefined ? '—' : fmt(r.raw_angle_deg, 2)}</td>
        <td><span class="tag" data-level="${esc(lv)}">${esc(LEVEL_FULL[lv] || lv)}</span></td>
      </tr>`;
    }).join('');
  }

  // График прогона с разрывами на паузах > 5,5 с
  drawHistoryChart(cam);
}

function drawHistoryChart(cam) {
  if (!cam) return;
  const pts = loadedRows.map((r) => ({
    t: Date.parse(r.timestamp_iso8601),
    min: Number(r.value),
    max: Number(r.value),
    avg: Number(r.value),
    n: 1,
    level: r.status_level || 'normal',
  }));
  const now = Date.now();
  const x0 = loadedRun ? Date.parse(loadedRun.started_at) : (pts[0]?.t ?? now - 300000);
  const rawX1 = loadedRun?.ended_at ? Date.parse(loadedRun.ended_at) : (pts[pts.length - 1]?.t ?? now);
  const x1 = Math.max(rawX1, x0 + 20000);
  const evs = eventsSorted().filter((e) => e.kind === 'alarm' && e.cam_id === cam.id);

  geo = drawTrend(canvas, {
    series: { camId: cam.id, since: x0, stepMs: 1000, points: pts },
    cam: loadedRun ? { calibration: loadedRun.calibration, thresholds: loadedRun.thresholds } : cam,
    x0,
    x1,
    events: evs,
    decimals: decimalsFor(cam.data),
    maxGapMs: 5500,
  });
}

export async function startNewRun() {
  try {
    const cam = ensureTargetCam();
    const run = await api('/api/demo/runs/start', {
      method: 'POST',
      body: { cam_id: cam ? cam.id : null },
    });
    state.demo.active_run = run;
    selectedRunId = run.id;
    emit('demo-run', run);
    toast(`Начат новый интервал записи: ${run.label}`);
    if (state.view === 'history') await refreshHistory();
  } catch (e) {
    toast(`Не удалось начать прогон: ${e.message}`, 'err');
  }
}

export async function stopCurrentRun() {
  const run = state.demo?.active_run;
  if (!run) return;
  try {
    const stopped = await api('/api/demo/runs/stop', {
      method: 'POST',
      body: { run_id: run.id },
    });
    state.demo.active_run = stopped;
    emit('demo-run', stopped);
    toast(`${stopped.label} завершён — выборка зафиксирована (${stopped.readings_count ?? 0} отсч.)`);
    if (state.view === 'history') await refreshHistory();
  } catch (e) {
    toast(`Не удалось завершить прогон: ${e.message}`, 'err');
  }
}

export function openHistoryFor(camId) {
  if (camId && state.cams.has(camId)) {
    currentCamId = camId;
    if (!isSimulated(state.cams.get(camId)) && state.demo?.active_run?.camera_id === camId) {
      selectedRunId = state.demo.active_run.id;
    }
  }
  setView('history');
}

export function initHistory() {
  $('#histCamSelect').addEventListener('change', (e) => {
    currentCamId = e.target.value;
    selectedRunId = 'active';
    refreshHistory();
  });
  $('#histRunSelect').addEventListener('change', (e) => {
    selectedRunId = e.target.value;
    refreshHistory();
  });
  $('#btnHistStartRun').addEventListener('click', startNewRun);
  $('#btnHistStopRun').addEventListener('click', stopCurrentRun);
  $('#btnHistRefresh').addEventListener('click', refreshHistory);
  $('#btnToggleCsvRaw').addEventListener('click', (e) => {
    showRawCsv = !showRawCsv;
    e.currentTarget.setAttribute('aria-pressed', String(showRawCsv));
    const cam = ensureTargetCam();
    if (cam) renderHistoryContent(cam);
  });

  canvas.addEventListener('pointermove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const cam = ensureTargetCam();
    const q = pointAt(geo, x);
    if (!cam || !q) { tip.hidden = true; return; }
    tip.hidden = false;
    tip.textContent = tipText(q, loadedRun?.unit || cam.data.unit, decimalsFor(cam.data));
    const tw = tip.offsetWidth;
    tip.style.left = `${Math.min(rect.width - tw - 4, Math.max(4, x + 10))}px`;
    tip.style.top = '8px';
  });
  canvas.addEventListener('pointerleave', () => { tip.hidden = true; });

  new ResizeObserver(() => {
    if (state.view === 'history') {
      const cam = ensureTargetCam();
      if (cam) drawHistoryChart(cam);
    }
  }).observe($('#histTrendBody'));

  on('view', (v) => {
    clearInterval(refreshTimer);
    refreshTimer = null;
    if (v === 'history') {
      refreshHistory();
      refreshTimer = setInterval(() => {
        if (!document.hidden && state.view === 'history') refreshHistory();
      }, 2500);
    }
  });
  on('demo-run', () => { if (state.view === 'history') refreshHistory(); });
  on('events', () => { if (state.view === 'history') renderIncidentsLog(); });
  on('cams', () => { if (state.view === 'history') renderSelectors(); });
}
