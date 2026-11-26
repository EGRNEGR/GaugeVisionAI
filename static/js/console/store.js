// Единое хранилище состояния пульта, унифицированная модель SensorTelemetry (36 позиций),
// селектор счётчиков без расхождений и агрегатор общестанционной статистики ТЭЦ.
import { num, decimalsFor, crossed, shiftStart, LEVEL_RANK } from './util.js';

const listeners = new Map();
export function on(topic, fn) {
  if (!listeners.has(topic)) listeners.set(topic, new Set());
  listeners.get(topic).add(fn);
}
export function emit(topic, payload) {
  const set = listeners.get(topic);
  if (set) for (const fn of set) fn(payload);
}

const savedDensity = localStorage.getItem('gv.density');
const initialDensity = ['9', '16', '36'].includes(savedDensity) ? savedDensity : '36';
const savedInspectorMode = localStorage.getItem('gv.inspectorMode');
const initialInspectorMode = ['normal', 'collapsed', 'wide', 'fullscreen'].includes(savedInspectorMode)
  ? savedInspectorMode
  : 'normal';
const savedInspectorWidth = Number(localStorage.getItem('gv.inspectorWidth'));

export const state = {
  meta: null,
  metaAt: 0,
  demo: {
    enabled: false,
    scenario: 'mixed',
    scenarios: [],
    active_run: null,
    runs: [],
    groups: [],
    live_cam_id: 'demo-mtp160-steam',
  },
  cams: new Map(),        // id -> { id, data, status, stream, reading, samples, diag }
  order: [],              // стабильный порядок ID приборов (36 позиций)
  selectedId: localStorage.getItem('gv.sel') || null,
  detailOpen: false,
  inspector: {
    mode: initialInspectorMode, // normal | collapsed | wide | fullscreen
    width: Number.isFinite(savedInspectorWidth) && savedInspectorWidth >= 340 ? savedInspectorWidth : 480,
  },
  statsCollapsed: localStorage.getItem('gv.statsCollapsed') === '1',
  view: 'monitor',        // monitor | events | history | cameras | calibration
  grid: {
    density: initialDensity, // '9' (3x3) | '16' (4x4) | '36' (6x6)
    filter: 'all',           // all | alert | warning | deviation | nodata
    group: 'all',
    search: '',
    page: 1,
  },
  events: new Map(),
  connected: false,
  downSince: null,
  stop: null,             // { camId, eventId }
};

export function makeCam(data) {
  const r = data.reading || null;
  const samples = [];
  if (Array.isArray(r?.sparkline) && r.sparkline.length) {
    const now = Date.now();
    const stepMs = (15 * 60 * 1000) / Math.max(1, r.sparkline.length - 1);
    r.sparkline.forEach((v, idx) => {
      if (v !== null && v !== undefined && Number.isFinite(Number(v))) {
        samples.push({ t: now - (r.sparkline.length - 1 - idx) * stepMs, v: Number(v) });
      }
    });
  } else if (r?.valid && r.value !== null && r.value !== undefined) {
    samples.push({ t: Date.parse(r.ts) || Date.now(), v: Number(r.value) });
  }
  return {
    id: data.id,
    data,
    status: data.status || 'offline',
    stream: data.stream || {},
    reading: r,
    samples, // скользящее окно 15 минут для расчёта Δ/мин и спарклайна
    diag: { readTs: [], procMs: [] },
  };
}

export function recordSample(cam, tsIso, val, sparkline = null) {
  if (!cam) return;
  if (Array.isArray(sparkline) && sparkline.length >= 4) {
    const tEnd = (tsIso ? Date.parse(tsIso) : Date.now()) || Date.now();
    const stepMs = (15 * 60 * 1000) / Math.max(1, sparkline.length - 1);
    cam.samples = sparkline
      .map((v, i) => ({ t: tEnd - (sparkline.length - 1 - i) * stepMs, v: Number(v) }))
      .filter((p) => Number.isFinite(p.v));
    return;
  }
  if (val === null || val === undefined || !Number.isFinite(Number(val))) return;
  const t = (tsIso ? Date.parse(tsIso) : Date.now()) || Date.now();
  const v = Number(val);
  const last = cam.samples[cam.samples.length - 1];
  if (!last || t - last.t >= 900) {
    cam.samples.push({ t, v });
  } else {
    last.v = v;
  }
  const cutoff = t - 15 * 60 * 1000;
  while (cam.samples.length > 2 && cam.samples[0].t < cutoff) {
    cam.samples.shift();
  }
  if (cam.samples.length > 90) {
    cam.samples.splice(0, cam.samples.length - 90);
  }
}

export const camList = () => state.order.map((id) => state.cams.get(id)).filter(Boolean);
export const realCamList = () => camList().filter((c) => c.data.source_kind !== 'simulated');
export const selected = () => (state.selectedId ? state.cams.get(state.selectedId) : null);

export function livePrimaryCam() {
  const pref = state.demo?.live_cam_id || 'demo-mtp160-steam';
  if (state.cams.has(pref)) return state.cams.get(pref);
  return realCamList()[0] || camList()[0] || null;
}

export function setView(viewName) {
  if (!['monitor', 'events', 'history', 'cameras', 'calibration'].includes(viewName)) return;
  if (state.view === viewName) return;
  state.view = viewName;
  emit('view', viewName);
}

export function select(id, { openDetail = null } = {}) {
  const changed = state.selectedId !== id;
  state.selectedId = id;
  if (id) localStorage.setItem('gv.sel', id);
  if (openDetail !== null) {
    state.detailOpen = !!openDetail;
    if (openDetail && state.inspector.mode === 'collapsed') {
      state.inspector.mode = 'normal';
      localStorage.setItem('gv.inspectorMode', 'normal');
    }
  }
  if (changed) {
    state.stop = null;
    emit('select', id);
    emit('stop', null);
  } else if (openDetail !== null) {
    emit('detail-toggle', state.detailOpen);
  }
}

export function setDetailOpen(open) {
  const next = !!open && !!selected();
  if (state.detailOpen === next) return;
  state.detailOpen = next;
  if (!next && state.stop) {
    state.stop = null;
    emit('stop', null);
  }
  emit('detail-toggle', state.detailOpen);
}

export function setInspectorMode(mode) {
  if (!['normal', 'collapsed', 'wide', 'fullscreen'].includes(mode)) return;
  state.inspector.mode = mode;
  localStorage.setItem('gv.inspectorMode', mode);
  if (!state.detailOpen && selected()) {
    state.detailOpen = true;
  }
  emit('inspector-layout', state.inspector);
}

export function clampInspectorWidth(px) {
  const maxW = Math.max(360, Math.floor(window.innerWidth * 0.65));
  return Math.max(340, Math.min(maxW, Math.round(px)));
}

export function setInspectorWidth(px, { silent = false } = {}) {
  const clamped = clampInspectorWidth(px);
  state.inspector.width = clamped;
  if (state.inspector.mode !== 'normal') {
    state.inspector.mode = 'normal';
    localStorage.setItem('gv.inspectorMode', 'normal');
  }
  localStorage.setItem('gv.inspectorWidth', String(clamped));
  document.documentElement.style.setProperty('--detail-w', `${clamped}px`);
  if (!silent) emit('inspector-layout', state.inspector);
  return clamped;
}

export function setStatsCollapsed(collapsed) {
  state.statsCollapsed = !!collapsed;
  localStorage.setItem('gv.statsCollapsed', state.statsCollapsed ? '1' : '0');
  emit('stats-toggle', state.statsCollapsed);
}

export function readingAgeSeconds(cam) {
  if (!cam || !cam.reading) return Infinity;
  if (typeof cam.reading.age_s === 'number' && Number.isFinite(cam.reading.age_s) && cam.data?.source_kind === 'simulated') {
    return Math.max(0, cam.reading.age_s);
  }
  const ts = cam.reading.last_valid_ts || (cam.reading.valid ? cam.reading.ts : null);
  if (!ts) return Infinity;
  const ms = Date.now() - Date.parse(ts);
  return Number.isFinite(ms) ? Math.max(0, ms / 1000) : Infinity;
}

export function isSimulated(cam) {
  return !!(cam && cam.data && cam.data.source_kind === 'simulated');
}

export function staleLimitSeconds() {
  return Number(state.meta?.stale_seconds || state.demo?.stale_seconds || 6.0);
}

function computeRatePerMin(cam) {
  const r = cam?.reading;
  if (r && typeof r.rate_per_min === 'number' && Number.isFinite(r.rate_per_min)) {
    return r.rate_per_min;
  }
  const pts = cam?.samples || [];
  if (pts.length < 2) return null;
  const last = pts[pts.length - 1];
  // Ищем опорную точку 20–90 с назад для устойчивой оценки Δ/мин
  let ref = pts[0];
  for (let i = pts.length - 2; i >= 0; i--) {
    const dt = (last.t - pts[i].t) / 1000;
    ref = pts[i];
    if (dt >= 30) break;
  }
  const dtSec = (last.t - ref.t) / 1000;
  if (dtSec < 2) return null;
  return ((last.v - ref.v) / dtSec) * 60;
}

function extractHistoryValues(cam, maxPts = 24) {
  const pts = cam?.samples || [];
  if (pts.length >= 2) {
    if (pts.length <= maxPts) return pts.map((p) => p.v);
    const out = [];
    const step = (pts.length - 1) / (maxPts - 1);
    for (let i = 0; i < maxPts; i++) {
      out.push(pts[Math.round(i * step)].v);
    }
    return out;
  }
  const r = cam?.reading;
  if (Array.isArray(r?.sparkline) && r.sparkline.length >= 1) {
    return r.sparkline.map(Number).filter(Number.isFinite);
  }
  return pts.map((p) => p.v);
}

/**
 * Унифицированная оценка состояния прибора:
 *  - status: 'NORMAL' | 'WARNING' | 'CRITICAL' | 'STALE'
 *  - tone:   'normal' | 'warning' | 'alert'    | 'nodata'
 */
export function evaluateInstrument(cam) {
  if (!cam) {
    return { status: 'STALE', tone: 'nodata', level: 'stale', measState: 'disconnected', hasFreshValid: false, prevAlarm: null, ageS: Infinity };
  }
  const r = cam.reading;
  if (!state.connected) {
    const prevLv = r?.last_valid_level || r?.level || null;
    return { status: 'STALE', tone: 'nodata', level: 'stale', measState: 'no_fresh_data', hasFreshValid: false, prevAlarm: prevLv, ageS: readingAgeSeconds(cam) };
  }

  if (isSimulated(cam)) {
    const simOnline = cam.status !== 'offline' && r && r.valid !== false && r.value !== null && r.value !== undefined;
    if (!simOnline) {
      const prevLv = r?.last_valid_level || null;
      return {
        status: 'STALE',
        tone: 'nodata',
        level: 'stale',
        measState: 'no_fresh_data',
        hasFreshValid: false,
        prevAlarm: prevLv,
        ageS: readingAgeSeconds(cam),
      };
    }
    const lv = r.level || 'normal';
    const status = lv === 'alert' ? 'CRITICAL' : lv === 'warning' ? 'WARNING' : 'NORMAL';
    const tone = lv === 'alert' ? 'alert' : lv === 'warning' ? 'warning' : 'normal';
    return { status, tone, level: lv, measState: 'valid', hasFreshValid: true, prevAlarm: null, ageS: 0 };
  }

  const ageS = readingAgeSeconds(cam);
  const limitS = staleLimitSeconds();
  const streamOnline = cam.status === 'online';
  const prevLv = (r && !r.awaiting_post_cal) ? (r.last_valid_level || null) : null;

  if (!streamOnline) {
    const hadData = !!(r && r.last_valid_ts && !r.awaiting_post_cal);
    return {
      status: 'STALE',
      tone: 'nodata',
      level: 'stale',
      measState: hadData ? 'no_fresh_data' : 'disconnected',
      hasFreshValid: false,
      prevAlarm: prevLv,
      ageS,
    };
  }

  if (!r) {
    return { status: 'STALE', tone: 'nodata', level: 'stale', measState: 'awaiting_reading', hasFreshValid: false, prevAlarm: null, ageS: Infinity };
  }

  if (r.valid && r.value !== null && r.value !== undefined && ageS <= limitS) {
    const lv = r.level || 'normal';
    const status = lv === 'alert' ? 'CRITICAL' : lv === 'warning' ? 'WARNING' : 'NORMAL';
    const tone = lv === 'alert' ? 'alert' : lv === 'warning' ? 'warning' : 'normal';
    return { status, tone, level: lv, measState: 'valid', hasFreshValid: true, prevAlarm: null, ageS };
  }

  if (r.out_of_scale) {
    return { status: 'STALE', tone: 'nodata', level: 'stale', measState: 'needs_calibration', hasFreshValid: false, prevAlarm: prevLv, ageS };
  }

  if (r.last_valid_ts && !r.awaiting_post_cal) {
    if (ageS <= limitS) {
      return { status: 'STALE', tone: 'nodata', level: 'hold', measState: 'hold', hasFreshValid: false, prevAlarm: prevLv, ageS };
    }
    return { status: 'STALE', tone: 'nodata', level: 'stale', measState: 'no_fresh_data', hasFreshValid: false, prevAlarm: prevLv, ageS };
  }

  return { status: 'STALE', tone: 'nodata', level: 'stale', measState: 'awaiting_reading', hasFreshValid: false, prevAlarm: null, ageS: Infinity };
}

/** Полная унифицированная модель SensorTelemetry для одного прибора. */
export function buildSensorTelemetry(cam, unackMap = null) {
  const ev = evaluateInstrument(cam);
  const d = cam?.data || {};
  const r = cam?.reading || null;
  const cal = d.calibration || {};
  const th = d.thresholds || {};
  const lowerOn = th.lower_enabled !== false && (num(th.ll_alert) !== null || num(th.l_warn) !== null);
  const uMap = unackMap || unackedByCam();
  const unackedLv = cam ? (uMap.get(cam.id) || null) : null;
  const freshValue = ev.hasFreshValid ? num(r?.value) : null;
  const shownValue = ev.hasFreshValid
    ? num(r?.value)
    : (ev.measState === 'hold' || ev.measState === 'no_fresh_data' ? (num(r?.last_valid_value) ?? num(r?.value)) : null);

  return {
    id: cam.id,
    cam,
    code: d.code || String(d.grid_pos || '').padStart(2, '0'),
    name: d.name || '',
    displayName: d.short_name || d.name || '',
    group: d.group || 'Прочие',
    gaugeType: d.gauge_type || 'pressure',
    sourceKind: d.source_kind || 'camera_cv',
    isLive: !isSimulated(cam),
    value: shownValue,
    freshValue,
    unit: d.unit || '',
    decimals: decimalsFor(d),
    scale: {
      min: Math.min(num(cal.v_min) ?? 0, num(cal.v_max) ?? 16),
      max: Math.max(num(cal.v_min) ?? 0, num(cal.v_max) ?? 16),
    },
    setpoints: {
      ll: lowerOn ? num(th.ll_alert) : null,
      l: lowerOn ? num(th.l_warn) : null,
      h: num(th.h_warn),
      hh: num(th.hh_alert),
      lowerEnabled: lowerOn,
    },
    crossedSetpoint: freshValue !== null ? crossed(freshValue, th) : null,
    status: ev.status, // NORMAL | WARNING | CRITICAL | STALE
    tone: ev.tone,     // normal | warning | alert | nodata
    level: ev.level,
    measState: ev.measState,
    hasFreshValid: ev.hasFreshValid,
    prevAlarm: ev.prevAlarm,
    ageS: ev.ageS,
    unacked: unackedLv !== null,
    unackedLevel: unackedLv,
    rateOfChange: ev.hasFreshValid ? computeRatePerMin(cam) : null,
    history: extractHistoryValues(cam, 24),
    cvMeta: isSimulated(cam) ? null : {
      confidence: num(r?.confidence),
      angle: num(r?.angle),
      dialSource: r?.dial_source || null,
      method: r?.method || null,
      processMs: num(r?.process_ms),
      fps: num(cam.stream?.fps),
      framesTotal: Number(cam.stream?.frames_total || 0),
    },
  };
}

/**
 * ЕДИНЫЙ СЕЛЕКТОР ИСТИНЫ для шапки, бейджей фильтрации и сводной статистики ТЭЦ.
 * Исключает любое расхождение между cAlarm / cWarn / cDev / cNoData и фильтрами сетки.
 */
export function selectDashboardSummary() {
  const unackMap = unackedByCam();
  const telemetries = camList().map((c) => buildSensorTelemetry(c, unackMap));

  const criticalItems = [];
  const warningItems = [];
  const staleItems = [];
  const normalItems = [];

  for (const t of telemetries) {
    if (t.status === 'CRITICAL') criticalItems.push(t);
    else if (t.status === 'WARNING') warningItems.push(t);
    else if (t.status === 'STALE') staleItems.push(t);
    else normalItems.push(t);
  }

  let unackCount = 0;
  let unackHasAlert = false;
  const shiftStartMs = shiftStart(new Date()).getTime();
  let shiftTrips = 0;

  for (const ev of state.events.values()) {
    if (ev.kind === 'alarm' && ev.level !== 'normal') {
      if (!ev.acked) {
        unackCount++;
        if (ev.level === 'alert') unackHasAlert = true;
      }
      const evMs = Date.parse(ev.ts);
      if (!Number.isFinite(evMs) || evMs >= shiftStartMs) {
        shiftTrips++;
      }
    }
  }

  // Агрегированная статистика станции (КТЦ ТЭЦ)
  let totalPowerMw = 0;
  let powerSources = 0;
  const powerBreakdown = [];
  let totalSteamTph = 0;
  let steamSources = 0;
  const cvConfidences = [];

  for (const t of telemetries) {
    if (t.unit === 'МВт' && t.freshValue !== null) {
      totalPowerMw += t.freshValue;
      powerSources++;
      powerBreakdown.push(`${t.code.replace('-РВт', '')}: ${t.freshValue.toFixed(1).replace('.', ',')}`);
    }
    if (t.unit === 'т/ч' && t.gaugeType === 'flow' && t.freshValue !== null) {
      totalSteamTph += t.freshValue;
      steamSources++;
    }
    if (t.isLive && t.cvMeta && t.cvMeta.confidence !== null && t.hasFreshValid) {
      cvConfidences.push(t.cvMeta.confidence);
    }
  }

  const meanCvConfPct = cvConfidences.length
    ? (cvConfidences.reduce((a, b) => a + b, 0) / cvConfidences.length) * 100
    : null;

  const total = telemetries.length;
  const critical = criticalItems.length;
  const warning = warningItems.length;
  const deviations = critical + warning;
  const stale = staleItems.length;
  const normal = normalItems.length;

  return {
    telemetries,
    byId: new Map(telemetries.map((t) => [t.id, t])),
    criticalItems,
    warningItems,
    deviationItems: [...criticalItems, ...warningItems],
    staleItems,
    normalItems,
    counts: {
      total,
      normal,
      warning,
      critical,
      deviations, // СТРОГО critical + warning
      stale,
      unack: unackCount,
      unackHasAlert,
    },
    station: {
      powerMw: powerSources > 0 ? totalPowerMw : null,
      powerNominalMw: 240,
      powerBreakdown,
      steamTph: steamSources > 0 ? totalSteamTph : null,
      cvConfidencePct: meanCvConfPct,
      cvActiveCount: cvConfidences.length,
      cvTotalCount: telemetries.filter((t) => t.isLive).length,
      yoloActive: !!state.meta?.yolo,
      shiftTrips,
    },
  };
}

export function displayLevel(cam) {
  return evaluateInstrument(cam).level;
}

export function unackedByCam() {
  const m = new Map();
  for (const ev of state.events.values()) {
    if (ev.kind !== 'alarm' || ev.acked || !ev.cam_id) continue;
    const prev = m.get(ev.cam_id);
    if (!prev || LEVEL_RANK[ev.level] > LEVEL_RANK[prev]) m.set(ev.cam_id, ev.level);
  }
  return m;
}

export function unackedEventsOf(camId) {
  return eventsSorted().filter((e) => e.kind === 'alarm' && !e.acked && e.cam_id === camId);
}

export function eventsSorted() {
  return Array.from(state.events.values()).sort((a, b) => b.id - a.id);
}

export const snapshotsOf = (camId) => eventsSorted().filter((e) => e.cam_id === camId && e.has_frame);
