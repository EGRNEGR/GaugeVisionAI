// Состояние пульта и шина событий между модулями.
import { LEVEL_RANK } from './util.js';

const listeners = new Map();
export function on(topic, fn) {
  if (!listeners.has(topic)) listeners.set(topic, new Set());
  listeners.get(topic).add(fn);
}
export function emit(topic, payload) {
  const set = listeners.get(topic);
  if (set) for (const fn of set) fn(payload);
}

export const state = {
  meta: null,
  metaAt: 0,              // performance.now() при получении meta — для аптайма сервера
  cams: new Map(),        // id -> Cam
  order: [],              // порядок приборов как на сервере
  selectedId: localStorage.getItem('gv.sel') || null,
  events: new Map(),      // id -> событие журнала
  connected: false,
  downSince: null,
  stop: null,             // { camId, eventId } — показ стоп-кадра вместо живого потока
};

/** Прибор пульта: данные сервера + живое состояние + замеры диагностики. */
export function makeCam(data) {
  return {
    id: data.id,
    data,
    status: data.status || 'offline',
    stream: data.stream || {},
    reading: data.reading || null,
    diag: { readTs: [], procMs: [] },
  };
}

export const camList = () => state.order.map((id) => state.cams.get(id)).filter(Boolean);
export const selected = () => (state.selectedId ? state.cams.get(state.selectedId) : null);

export function select(id) {
  if (state.selectedId === id) return;
  state.selectedId = id;
  if (id) localStorage.setItem('gv.sel', id);
  state.stop = null;
  emit('select', id);
  emit('stop', null);
}

/** Уровень для отображения: нет связи и удержание значения важнее зоны уставок. */
export function displayLevel(cam) {
  if (!cam) return 'stale';
  if (!state.connected || cam.status !== 'online') return 'stale';
  const r = cam.reading;
  if (!r) return 'stale';
  if (!r.valid) return 'hold';
  return r.level || 'normal';
}
export const zoneLevel = (cam) => (cam && cam.reading && cam.reading.level) || 'normal';

/** Неквитированные срабатывания: camId -> худший уровень. */
export function unackedByCam() {
  const m = new Map();
  for (const ev of state.events.values()) {
    if (ev.kind !== 'alarm' || ev.acked || !ev.cam_id) continue;
    const prev = m.get(ev.cam_id);
    if (!prev || LEVEL_RANK[ev.level] > LEVEL_RANK[prev]) m.set(ev.cam_id, ev.level);
  }
  return m;
}

export function eventsSorted() {
  return Array.from(state.events.values()).sort((a, b) => b.id - a.id);
}

/** Стоп-кадры прибора, новые первыми. */
export const snapshotsOf = (camId) => eventsSorted().filter((e) => e.cam_id === camId && e.has_frame);
