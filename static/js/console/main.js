// Точка входа пульта GaugeVision AI: загрузка метаданных, WebSocket /ws/dashboard,
// синхронизация 36 приборов, контроль свежести живого источника и сборка модулей.
import { $, api, toast } from './util.js';
import { state, emit, makeCam, recordSample, select, livePrimaryCam, readingAgeSeconds, staleLimitSeconds } from './store.js';
import { initHeader } from './header.js';
import { initInstruments } from './instruments.js';
import { initViewer } from './viewer.js';
import { initReadout } from './readout.js';
import { initTrend } from './trend.js';
import { initJournal } from './journal.js';
import { initHistory } from './history.js';
import { initControl } from './control.js';
import { initDevices } from './devices.js';

const BACKOFF = [1, 2, 4, 8, 15];
let wsAttempt = 0;
let selectionAnnounced = false;
let lastFreshFlag = null;

function ensureSelection() {
  if (state.selectedId && state.cams.has(state.selectedId)) {
    // выбор, восстановленный из localStorage, объявляем модулям один раз: кадр, тренд, вкладки
    if (!selectionAnnounced) {
      selectionAnnounced = true;
      emit('select', state.selectedId);
      emit('stop', null);
    }
    return;
  }
  selectionAnnounced = true;
  const primary = livePrimaryCam();
  select(primary ? primary.id : (state.order[0] || null), { openDetail: false });
}

function upsertInstrument(data) {
  const existing = state.cams.get(data.id);
  if (!existing) {
    state.cams.set(data.id, makeCam(data));
    if (!state.order.includes(data.id)) state.order.push(data.id);
    return;
  }
  const cfgChanged = JSON.stringify([existing.data.calibration, existing.data.thresholds, existing.data.unit])
    !== JSON.stringify([data.calibration, data.thresholds, data.unit]);
  existing.data = { ...existing.data, ...data };
  existing.status = data.status || existing.status;
  if (data.stream) existing.stream = data.stream;
  if (data.reading !== undefined) {
    existing.reading = data.reading;
    recordSample(existing, data.reading?.ts, data.reading?.valid !== false ? data.reading?.value : null, data.reading?.sparkline);
  }
  if (cfgChanged) emit('cam-config', data.id);
}

function removeInstrument(id) {
  state.cams.delete(id);
  state.order = state.order.filter((x) => x !== id);
}

function onReading(msg) {
  const cam = state.cams.get(msg.cam_id);
  if (!cam) return;
  const { type, cam_id: _id, ...r } = msg;
  cam.reading = r;
  if (r.valid && r.value !== null && r.value !== undefined) {
    recordSample(cam, r.ts, r.value);
  }
  const now = Date.now();
  cam.diag.readTs.push(now);
  while (cam.diag.readTs.length && now - cam.diag.readTs[0] > 30000) cam.diag.readTs.shift();
  if (r.process_ms !== null && r.process_ms !== undefined) {
    cam.diag.procMs.push(r.process_ms);
    if (cam.diag.procMs.length > 90) cam.diag.procMs.shift();
  }
  if (state.demo?.active_run && state.demo.active_run.camera_id === msg.cam_id && !state.demo.active_run.ended_at && r.valid) {
    // счётчик прогона уточняется по событиям сервера, но даём плавный отклик в шапке
  }
  emit('reading', msg.cam_id);
}

function onSimTick(msg) {
  if (msg.scenario && state.demo) state.demo.scenario = msg.scenario;
  const updatedIds = [];
  for (const item of (msg.items || [])) {
    const cam = state.cams.get(item.id);
    if (!cam) continue;
    const isValid = item.valid !== false && item.value !== null && item.value !== undefined;
    cam.status = item.status || (isValid ? 'online' : 'offline');
    cam.data.status = cam.status;
    cam.reading = {
      ...(cam.reading || {}),
      ts: msg.ts,
      last_valid_ts: isValid ? msg.ts : (cam.reading?.last_valid_ts || msg.ts),
      value: isValid ? item.value : null,
      raw_value: isValid ? item.value : null,
      last_valid_value: item.last_valid_value ?? (isValid ? item.value : cam.reading?.last_valid_value ?? null),
      valid: isValid,
      level: item.level || 'normal',
      last_valid_level: item.last_valid_level || item.level || 'normal',
      rate_per_min: item.rate_per_min ?? null,
      age_s: item.age_s ?? 0,
      source_kind: 'simulated',
    };
    if (isValid) {
      recordSample(cam, msg.ts, item.value);
    }
    updatedIds.push(item.id);
  }
  if (updatedIds.length) emit('sim-tick', updatedIds);
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'snapshot': {
      if (msg.demo) state.demo = msg.demo;
      const list = msg.instruments || msg.cameras || [];
      const ids = new Set(list.map((c) => c.id));
      for (const id of Array.from(state.cams.keys())) {
        if (!ids.has(id)) removeInstrument(id);
      }
      state.order = list.map((c) => c.id);
      for (const c of list) upsertInstrument(c);
      ensureSelection();
      emit('cams');
      emit('demo-run', state.demo?.active_run || null);
      break;
    }
    case 'reading':
      onReading(msg);
      break;
    case 'sim_tick':
      onSimTick(msg);
      break;
    case 'status': {
      const cam = state.cams.get(msg.cam_id);
      if (!cam) break;
      cam.status = msg.status;
      cam.data.status = msg.status;
      if (msg.stream) cam.stream = msg.stream;
      emit('status', msg.cam_id);
      break;
    }
    case 'camera_added':
    case 'camera_updated':
      upsertInstrument(msg.camera);
      ensureSelection();
      emit('cams');
      break;
    case 'camera_deleted':
      removeInstrument(msg.cam_id);
      ensureSelection();
      emit('cams');
      break;
    case 'event':
      state.events.set(msg.event.id, msg.event);
      emit('events');
      break;
    case 'ack': {
      const ids = new Set(msg.ids || []);
      for (const ev of state.events.values()) {
        if (!ev.acked && (ids.has(ev.id) || !msg.ids)) {
          ev.acked = true;
          ev.acked_ts = msg.ts;
          ev.acked_by = msg.by;
        }
      }
      emit('events');
      break;
    }
    case 'demo_run':
      if (state.demo) {
        state.demo.active_run = msg.run;
        const idx = (state.demo.runs || []).findIndex((r) => r.id === msg.run.id);
        if (idx >= 0) state.demo.runs[idx] = msg.run;
        else if (state.demo.runs) state.demo.runs.unshift(msg.run);
      }
      emit('demo-run', msg.run);
      break;
    default:
      break;
  }
}

async function loadEvents() {
  try {
    const evs = await api('/api/events?limit=1000');
    state.events = new Map(evs.map((e) => [e.id, e]));
    emit('events');
  } catch (e) {
    toast(`Журнал событий не загружен: ${e.message}`, 'err');
  }
}

function setConnected(ok) {
  if (state.connected === ok) return;
  state.connected = ok;
  state.downSince = ok ? null : Date.now();
  emit('conn', ok);
}

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard`);
  let ping = null;
  ws.onopen = () => {
    wsAttempt = 0;
    setConnected(true);
    loadEvents();
    setTimeout(() => loadMeta().catch(() => {}), 400);
    ping = setInterval(() => {
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping', t: Date.now() }));
    }, 20000);
  };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch (_) { return; }
    handleMessage(msg);
  };
  ws.onclose = () => {
    clearInterval(ping);
    setConnected(false);
    const delay = BACKOFF[Math.min(wsAttempt, BACKOFF.length - 1)];
    wsAttempt++;
    setTimeout(connectWs, delay * 1000);
  };
  ws.onerror = () => { try { ws.close(); } catch (_) { /* закрыт */ } };
}

async function loadMeta() {
  state.meta = await api('/api/meta');
  state.metaAt = performance.now();
  if (state.meta.demo) {
    state.demo = state.meta.demo;
    emit('demo-run', state.demo.active_run || null);
  }
}

async function pollRealStreams() {
  if (!state.connected || document.hidden) return;
  try {
    const cams = await api('/api/cameras');
    for (const c of cams) {
      const cam = state.cams.get(c.id);
      if (cam && c.stream) cam.stream = c.stream;
    }
    if (state.demo?.enabled) {
      const dm = await api('/api/demo/state');
      state.demo = dm;
      emit('demo-run', dm.active_run || null);
    }
  } catch (_) { /* сообщит WebSocket */ }
}

/** Отдельный контроль свежести достоверного замера живой камеры (не зависит от статуса WSS пульта). */
function checkFreshnessTick() {
  const live = livePrimaryCam();
  if (!live || live.data.source_kind === 'simulated') return;
  const age = readingAgeSeconds(live);
  const fresh = state.connected && live.status === 'online' && !!(live.reading?.valid) && age <= staleLimitSeconds();
  if (fresh !== lastFreshFlag || (!fresh && Number.isFinite(age))) {
    lastFreshFlag = fresh;
    emit('freshness', fresh);
  }
}

async function init() {
  try {
    await loadMeta();
  } catch (e) {
    $('#linkText').textContent = `Сервер недоступен (${e.message}), повтор…`;
    setTimeout(init, 2500);
    return;
  }

  initDevices();
  initControl();
  initHistory();
  initJournal();
  initInstruments();
  initViewer();
  initReadout();
  initTrend();
  initHeader();

  emit('cams');
  connectWs();
  setInterval(checkFreshnessTick, 1000);
  setInterval(pollRealStreams, 5000);
  setInterval(() => loadMeta().catch(() => {}), 30000);
}

init();
