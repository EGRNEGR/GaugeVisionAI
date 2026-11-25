// Пульт оператора GaugeVision AI: загрузка, WebSocket-телеметрия, сборка модулей.
import { $, api, toast } from './util.js';
import { state, emit, makeCam, select } from './store.js';
import { initHeader } from './header.js';
import { initInstruments } from './instruments.js';
import { initViewer } from './viewer.js';
import { initReadout } from './readout.js';
import { initTrend } from './trend.js';
import { initJournal } from './journal.js';
import { initControl } from './control.js';
import { initDevices } from './devices.js';

const BACKOFF = [1, 2, 4, 8, 15];   // переподключение, с — как у захвата камер
let wsAttempt = 0;

function ensureSelection() {
  if (state.selectedId && state.cams.has(state.selectedId)) return;
  select(state.order[0] || null);
}

function upsert(data) {
  const cam = state.cams.get(data.id);
  if (!cam) {
    state.cams.set(data.id, makeCam(data));
    if (!state.order.includes(data.id)) state.order.push(data.id);
    return;
  }
  const cfgChanged = JSON.stringify([cam.data.calibration, cam.data.thresholds, cam.data.unit])
    !== JSON.stringify([data.calibration, data.thresholds, data.unit]);
  cam.data = data;
  cam.status = data.status || cam.status;
  if (data.stream) cam.stream = data.stream;
  if (data.reading && !cam.reading) cam.reading = data.reading;
  if (cfgChanged) emit('cam-config', data.id);
}

function remove(id) {
  state.cams.delete(id);
  state.order = state.order.filter((x) => x !== id);
}

function onReading(msg) {
  const cam = state.cams.get(msg.cam_id);
  if (!cam) return;
  const { type, cam_id: _id, ...r } = msg;
  cam.reading = r;
  const now = Date.now();
  cam.diag.readTs.push(now);
  while (cam.diag.readTs.length && now - cam.diag.readTs[0] > 30000) cam.diag.readTs.shift();
  if (r.process_ms !== null && r.process_ms !== undefined) {
    cam.diag.procMs.push(r.process_ms);
    if (cam.diag.procMs.length > 90) cam.diag.procMs.shift();
  }
  emit('reading', msg.cam_id);
}

function handle(msg) {
  switch (msg.type) {
    case 'snapshot': {
      const ids = new Set(msg.cameras.map((c) => c.id));
      for (const id of Array.from(state.cams.keys())) if (!ids.has(id)) remove(id);
      state.order = msg.cameras.map((c) => c.id);
      for (const c of msg.cameras) {
        upsert(c);
        const cam = state.cams.get(c.id);
        cam.reading = c.reading || cam.reading;
        cam.status = c.status;
      }
      ensureSelection();
      emit('cams');
      break;
    }
    case 'reading': onReading(msg); break;
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
      upsert(msg.camera);
      ensureSelection();
      emit('cams');
      break;
    case 'camera_deleted':
      remove(msg.cam_id);
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
        if (!ev.acked && (ids.has(ev.id) || !msg.ids)) { ev.acked = true; ev.acked_ts = msg.ts; ev.acked_by = msg.by; }
      }
      emit('events');
      break;
    }
    default: break;
  }
}

async function loadEvents() {
  try {
    const evs = await api('/api/events?limit=1000');
    state.events = new Map(evs.map((e) => [e.id, e]));
    emit('events');
  } catch (e) {
    toast(`Журнал не загружен: ${e.message}`, 'err');
  }
}

function setConn(ok) {
  if (state.connected === ok) return;
  state.connected = ok;
  state.downSince = ok ? null : Date.now();
  emit('conn', ok);
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard`);
  let ping = null;
  ws.onopen = () => {
    wsAttempt = 0;
    setConn(true);
    loadEvents();
    setTimeout(() => loadMeta().catch(() => {}), 500);   // число пультов на связи — уже с этим
    ping = setInterval(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping', t: Date.now() })); }, 20000);
  };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch (_) { return; }
    handle(msg);
  };
  ws.onclose = () => {
    clearInterval(ping);
    setConn(false);
    const delay = BACKOFF[Math.min(wsAttempt, BACKOFF.length - 1)];
    wsAttempt++;
    setTimeout(connect, delay * 1000);
  };
  ws.onerror = () => { try { ws.close(); } catch (_) { /* уже закрыт */ } };
}

async function loadMeta() {
  state.meta = await api('/api/meta');
  state.metaAt = performance.now();
}

/** Статистика потоков (к/с, сбои, аптайм) приходит только со сменой статуса — освежаем раз в 5 с. */
async function pollStreams() {
  if (!state.connected || document.hidden) return;
  try {
    const cams = await api('/api/cameras');
    for (const c of cams) {
      const cam = state.cams.get(c.id);
      if (cam && c.stream) cam.stream = c.stream;
    }
  } catch (_) { /* связь пропала — сообщит WebSocket */ }
}

async function init() {
  try {
    await loadMeta();
  } catch (e) {
    $('#linkText').textContent = `Сервер недоступен: ${e.message}. Повтор через 3 с`;
    setTimeout(init, 3000);
    return;
  }
  initDevices();
  initHeader();
  initInstruments();
  initViewer();
  initReadout();
  initTrend();
  initJournal();
  initControl();
  if (state.meta.cert_sha256 && localStorage.getItem('gv.certNotice') !== 'hidden') {
    $('#certFp').textContent = `${state.meta.cert_sha256.slice(0, 23)}…`;
    $('#certNotice').hidden = false;
  }
  $('#btnHideNotice').addEventListener('click', () => {
    $('#certNotice').hidden = true;
    localStorage.setItem('gv.certNotice', 'hidden');
  });
  emit('cams');
  connect();
  setInterval(pollStreams, 5000);
  setInterval(() => loadMeta().catch(() => {}), 30000);
}

init();
