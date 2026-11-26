// Управляемый инспектор прибора (Split-Pane с drag-ресайзом 320px..65vw, сворачиванием в боковую
// полосу, широким режимом 50% и полноэкранным разворотом без зажатого скролла).
import { $, $$, esc, fmt, fmtRate, decimalsFor, timeStr, durStr, LEVEL_TAG, SOURCE_KIND_TEXT, DIAL_SOURCE, STATUS_TEXT } from './util.js';
import {
  state, on, selected, setDetailOpen, setInspectorMode, setInspectorWidth, clampInspectorWidth,
  livePrimaryCam, isSimulated, buildSensorTelemetry, unackedEventsOf,
} from './store.js';
import { renderRuler, scaleOf } from './ruler.js';
import { jumpToInstrument } from './instruments.js';
import { openPhoneDialog } from './devices.js';
import { openCalibrationFor } from './control.js';
import { openHistoryFor } from './history.js';
import { acknowledgeEvent } from './journal.js';

const MIN_CONF = 0.25;
const METHOD_LBL = { hough: 'HoughLinesP', moment: 'Радиальный момент', 'hough+moment': 'Hough + момент', none: '—' };

function kv(dt, dd, cls = '', title = '') {
  return `<div class="kv"${title ? ` title="${esc(title)}"` : ''}><dt>${dt}</dt><dd class="${cls}">${dd}</dd></div>`;
}

export function applyInspectorLayout() {
  const layout = $('#monitorLayout');
  const pane = $('#detailPane');
  const rail = $('#inspectorRail');
  const resizer = $('#splitResizer');
  if (!layout || !pane || !rail || !resizer) return;

  const cam = selected();
  const isOpen = state.detailOpen && !!cam;
  const mode = state.inspector.mode;

  if (!isOpen) {
    layout.dataset.detail = 'closed';
    layout.dataset.imode = 'normal';
    pane.hidden = true;
    rail.hidden = true;
    resizer.hidden = true;
    return;
  }

  layout.dataset.detail = 'open';
  layout.dataset.imode = mode;
  document.documentElement.style.setProperty('--detail-w', `${state.inspector.width}px`);

  const collapsed = mode === 'collapsed';
  pane.hidden = collapsed;
  rail.hidden = !collapsed;
  resizer.hidden = collapsed || mode === 'fullscreen';

  $$('.inspector-tools [data-imode]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.imode === mode));
  });

  if (collapsed && cam) {
    const t = buildSensorTelemetry(cam);
    rail.dataset.tone = t.tone;
    $('#railCode').textContent = t.code;
    $('#railVal').textContent = t.value !== null ? `${fmt(t.value, t.decimals)} ${t.unit}` : 'НЕТ ДАННЫХ';
    const badge = $('#railBadge');
    badge.dataset.level = t.tone === 'nodata' ? 'stale' : t.tone;
    badge.textContent = t.tone === 'alert' ? 'АВАР' : t.tone === 'warning' ? 'ПРЕД' : t.tone === 'nodata' ? 'СВЯЗЬ' : 'НОРМ';
  }
}

export function renderDetail() {
  applyInspectorLayout();
  if (!state.detailOpen || state.inspector.mode === 'collapsed') return;
  const cam = selected();
  if (!cam) return;

  const t = buildSensorTelemetry(cam);
  const d = t.decimals;
  const r = cam.reading;
  const sim = !t.isLive;

  $('#detCode').textContent = t.code;
  $('#detGroup').textContent = t.group;
  $('#detName').textContent = t.name;

  const srcTag = $('#detSourceTag');
  srcTag.textContent = SOURCE_KIND_TEXT[t.sourceKind] || t.sourceKind || 'Камера';
  srcTag.dataset.live = String(t.isLive);

  const readoutBox = $('#detReadout');
  readoutBox.dataset.tone = t.tone;

  const zTag = $('#detZoneTag');
  const unackList = unackedEventsOf(cam.id);
  zTag.dataset.unack = String(unackList.length > 0);

  const rateEl = $('#detRate');
  if (t.hasFreshValid) {
    const sp = t.tone === 'normal' ? null : t.crossedSetpoint;
    zTag.dataset.level = t.tone;
    zTag.textContent = sp ? `${LEVEL_TAG[t.tone]} ${sp}` : LEVEL_TAG[t.tone];
    $('#detQualityTxt').textContent = sim ? 'Телеметрия контура' : 'Достоверный отсчёт CV';
    $('#detValue').textContent = fmt(t.freshValue, d);
    $('#detSubnote').hidden = true;
    if (rateEl) {
      rateEl.textContent = `Δ ${fmtRate(t.rateOfChange, d)}`;
      rateEl.dataset.dir = t.rateOfChange > 0.01 ? 'up' : t.rateOfChange < -0.01 ? 'down' : 'flat';
    }
  } else {
    zTag.dataset.level = t.measState === 'hold' ? 'hold' : 'stale';
    zTag.textContent = t.measState === 'disconnected' ? 'НЕ ПОДКЛЮЧЕНА'
      : t.measState === 'awaiting_reading' ? 'ОЖИДАЕМ ПОКАЗАНИЕ'
      : t.measState === 'needs_calibration' ? 'НУЖНА КАЛИБРОВКА'
      : t.measState === 'hold' ? 'УДЕРЖАНИЕ' : 'НЕТ СВЕЖИХ ДАННЫХ';

    $('#detValue').textContent = t.value !== null ? fmt(t.value, d) : '—';
    $('#detQualityTxt').textContent = t.value !== null && Number.isFinite(t.ageS)
      ? `Устаревшие данные (${durStr(t.ageS)} назад)`
      : 'Достоверных отсчётов нет';
    if (rateEl) {
      rateEl.textContent = 'Δ —';
      rateEl.dataset.dir = 'flat';
    }

    const sub = $('#detSubnote');
    if (t.prevAlarm === 'alert' || t.prevAlarm === 'warning') {
      sub.hidden = false;
      sub.textContent = t.prevAlarm === 'alert'
        ? 'Последнее состояние до обрыва данных — АВАРИЯ (зафиксировано в журнале)'
        : 'Последнее состояние до обрыва данных — предупреждение';
    } else {
      sub.hidden = true;
    }
  }
  $('#detUnit').textContent = t.unit;

  const st = cam.stream || {};
  const frameTs = r?.last_frame_ts || st.last_frame_utc || null;
  const validTs = r?.last_valid_ts || (r?.valid ? r.ts : null);
  $('#detTimes').innerHTML = sim
    ? `<dt>Контур</dt><dd>${esc(t.group)}</dd><dt>Обновлено</dt><dd>${t.hasFreshValid && r ? timeStr(new Date(r.ts)) : `устар. ${durStr(t.ageS)}`}</dd>`
    : `<dt>Связь / кадр</dt><dd>${cam.status === 'online' ? 'Кадры поступают' : esc(STATUS_TEXT[cam.status] || cam.status)}${frameTs ? ` (${timeStr(new Date(frameTs))})` : ''}</dd>
       <dt>Достоверный замер</dt><dd>${validTs ? timeStr(new Date(validTs)) : 'ещё не получен'}</dd>`;

  const unackBar = $('#detUnackBar');
  if (unackList.length > 0) {
    const latestUnack = unackList[0];
    unackBar.hidden = false;
    $('#detUnackTxt').textContent = `Событие №${latestUnack.id}: ${latestUnack.level === 'alert' ? 'Авария' : 'Предупреждение'} (${fmt(latestUnack.value, d)} ${t.unit}) — не квитировано`;
    $('#btnDetAck').onclick = () => acknowledgeEvent(latestUnack.id);
  } else {
    unackBar.hidden = true;
  }

  $('#detVideoSec').hidden = sim;
  $('#detSimNote').hidden = !sim;
  $('#btnDetConnectPhone').hidden = sim || cam.data.type !== 'phone_ws';
  $('#btnDetCalibrate').hidden = sim;
  $('#btnDetHistory').hidden = false;

  const { lo, hi } = scaleOf(cam.data.calibration);
  $('#detScaleRange').textContent = `${fmt(lo, d)}…${fmt(hi, d)} ${t.unit}`;
  renderRuler($('#detRuler'), {
    calibration: cam.data.calibration,
    thresholds: cam.data.thresholds,
    value: t.hasFreshValid ? t.freshValue : null,
    level: t.tone === 'nodata' ? 'stale' : t.tone,
    big: true,
    decimals: d,
  });

  $('#detCvGrid').hidden = false;
  if (!sim) {
    const conf = r ? r.confidence : null;
    const [algo] = String((r && r.method) || 'none').split('/');
    $('#detCvGrid').innerHTML = [
      kv('Сырое знач.', r && r.raw_value !== null ? fmt(r.raw_value, d) : '—'),
      kv('Угол θ', r && r.angle !== null && r.angle !== undefined ? `${fmt(r.angle, 2)}°` : '—'),
      kv('Уверенность CV', conf !== null && conf !== undefined ? `${fmt(conf * 100, 1)} %` : '—', conf !== null && conf < MIN_CONF ? 'alarm' : ''),
      kv('ROI циферблата', r ? esc(DIAL_SOURCE[r.dial_source] || r.dial_source || '—') : '—'),
      kv('Метод вектора', esc(METHOD_LBL[algo] || algo)),
      kv('Время кадра', r && r.process_ms !== undefined ? `${fmt(r.process_ms, 1)} мс` : '—'),
      kv('Частота', cam.status === 'online' ? `${fmt(st.fps, 1)} к/с` : 'нет потока', cam.status !== 'online' ? 'alarm' : ''),
      kv('Кадров', String(st.frames_total ?? 0)),
    ].join('');
  } else {
    const sp = t.setpoints;
    $('#detCvGrid').innerHTML = [
      kv('Уставка LL (авар.)', sp.ll !== null ? `${fmt(sp.ll, d)} ${esc(t.unit)}` : 'откл.', sp.ll !== null ? 'alarm' : ''),
      kv('Уставка L (пред.)', sp.l !== null ? `${fmt(sp.l, d)} ${esc(t.unit)}` : 'откл.', sp.l !== null ? 'warn' : ''),
      kv('Уставка H (пред.)', sp.h !== null ? `${fmt(sp.h, d)} ${esc(t.unit)}` : '—', 'warn'),
      kv('Уставка HH (авар.)', sp.hh !== null ? `${fmt(sp.hh, d)} ${esc(t.unit)}` : '—', 'alarm'),
    ].join('');
  }
}

function initSplitResizer() {
  const resizer = $('#splitResizer');
  if (!resizer) return;

  resizer.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    resizer.setPointerCapture(e.pointerId);
    resizer.dataset.dragging = 'true';
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    const layout = $('#monitorLayout');
    let latestWidth = state.inspector.width;
    let rafId = 0;

    if (state.inspector.mode !== 'normal') {
      state.inspector.mode = 'normal';
      localStorage.setItem('gv.inspectorMode', 'normal');
      layout.dataset.imode = 'normal';
      $$('.inspector-tools [data-imode]').forEach((b) => b.setAttribute('aria-pressed', 'false'));
    }

    const applyVisual = () => {
      rafId = 0;
      document.documentElement.style.setProperty('--detail-w', `${latestWidth}px`);
    };

    const onMove = (ev) => {
      const rect = layout.getBoundingClientRect();
      latestWidth = clampInspectorWidth(rect.right - ev.clientX);
      if (!rafId) rafId = requestAnimationFrame(applyVisual);
    };
    const onUp = () => {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      resizer.dataset.dragging = 'false';
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      resizer.removeEventListener('pointermove', onMove);
      resizer.removeEventListener('pointerup', onUp);
      resizer.removeEventListener('pointercancel', onUp);
      setInspectorWidth(latestWidth, { silent: true });
    };
    resizer.addEventListener('pointermove', onMove);
    resizer.addEventListener('pointerup', onUp);
    resizer.addEventListener('pointercancel', onUp);
  });

  resizer.addEventListener('dblclick', () => {
    setInspectorMode(state.inspector.mode === 'wide' ? 'normal' : 'wide');
  });

  resizer.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setInspectorWidth(state.inspector.width + 32, { silent: true });
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      setInspectorWidth(state.inspector.width - 32, { silent: true });
    }
  });
}

export function initReadout() {
  initSplitResizer();

  $('#btnDetailClose').addEventListener('click', () => setDetailOpen(false));
  $('#btnDetailBack').addEventListener('click', () => setDetailOpen(false));
  $('#btnRailExpand')?.addEventListener('click', () => setInspectorMode('normal'));

  $$('.inspector-tools [data-imode]').forEach((b) => {
    b.addEventListener('click', () => {
      const target = b.dataset.imode;
      if (target === state.inspector.mode && target !== 'normal') {
        setInspectorMode('normal');
      } else {
        setInspectorMode(target);
      }
    });
  });

  $('#btnSimToLive').addEventListener('click', () => {
    const live = livePrimaryCam();
    if (live) jumpToInstrument(live.id);
  });

  $('#btnDetConnectPhone').addEventListener('click', () => {
    const cam = selected();
    if (cam) openPhoneDialog(cam.id);
  });
  $('#btnDetCalibrate').addEventListener('click', () => {
    const cam = selected();
    if (cam) openCalibrationFor(cam.id);
  });
  $('#btnDetHistory').addEventListener('click', () => {
    const cam = selected();
    if (cam) openHistoryFor(cam.id);
  });

  on('select', renderDetail);
  on('detail-toggle', renderDetail);
  on('inspector-layout', renderDetail);
  on('reading', (id) => { if (state.detailOpen && id === state.selectedId) renderDetail(); });
  on('sim-tick', (ids) => { if (state.detailOpen && ids.includes(state.selectedId)) renderDetail(); });
  on('status', (id) => { if (state.detailOpen && id === state.selectedId) renderDetail(); });
  on('freshness', () => { if (state.detailOpen) renderDetail(); });
  on('cams', renderDetail);
  on('events', renderDetail);
  on('conn', renderDetail);
}
