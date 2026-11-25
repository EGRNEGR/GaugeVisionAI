// Управление и диагностика выбранного прибора: уставки, ROI и шкала,
// диагностика конвейера, источник видео.
import { $, $$, esc, api, toast, confirmDlg, fmt, fmtInput, fmtFixed, parseNum, num, decimalsFor, durStr, durShort,
  DIAL_SOURCE, SETPOINT_KEYS, SETPOINT_CODE } from './util.js';
import { state, on, emit, camList, selected } from './store.js';
import { renderRuler, scaleOf } from './ruler.js';
import { bindSourceFields, openPhone } from './devices.js';

let tab = localStorage.getItem('gv.tab') || 'sp';

// ---------------------------------------------------------------- вкладки
function setTab(name, focus = false) {
  tab = name;
  localStorage.setItem('gv.tab', name);
  $$('.control [role="tab"]').forEach((t) => {
    const on_ = t.id === `tab-${name}`;
    t.setAttribute('aria-selected', String(on_));
    t.tabIndex = on_ ? 0 : -1;
    if (on_ && focus) t.focus();
  });
  $$('.control [role="tabpanel"]').forEach((p) => { p.hidden = p.id !== `pane-${name}`; });
  if (name !== 'roi') setRoiEdit(false);
  if (name === 'diag') renderDiag();
}

// ---------------------------------------------------------------- уставки
const spForm = $('#pane-sp');
let spCam = null;
let spDirty = false;

function spRead() {
  const out = {};
  let bad = false;
  for (const k of SETPOINT_KEYS) {
    const v = parseNum(spForm[k].value);
    spForm[k].setAttribute('aria-invalid', String(Number.isNaN(v)));
    if (Number.isNaN(v)) bad = true;
    out[k] = Number.isNaN(v) ? null : v;
  }
  return { thr: out, bad };
}

function spValidate() {
  const cam = selected();
  const { thr, bad } = spRead();
  const err = $('#spErr');
  if (bad) { err.textContent = 'Уставка должна быть числом, например 4,6.'; return null; }
  const seq = SETPOINT_KEYS.filter((k) => thr[k] !== null);
  for (let i = 1; i < seq.length; i++) {
    if (thr[seq[i - 1]] > thr[seq[i]]) {
      err.textContent = `${SETPOINT_CODE[seq[i - 1]]} больше ${SETPOINT_CODE[seq[i]]}: уставки должны возрастать LL ≤ L ≤ H ≤ HH.`;
      spForm[seq[i]].setAttribute('aria-invalid', 'true');
      return null;
    }
  }
  const { lo, hi } = scaleOf(cam.data.calibration);
  const out = seq.filter((k) => thr[k] < lo || thr[k] > hi);
  err.textContent = out.length ? `Вне шкалы прибора: ${out.map((k) => SETPOINT_CODE[k]).join(', ')} — такая уставка никогда не сработает.` : '';
  return thr;
}

function spPreview() {
  const cam = selected();
  if (!cam) return;
  const thr = spValidate();
  const d = decimalsFor(cam.data);
  renderRuler($('#spRuler'), {
    calibration: cam.data.calibration, thresholds: thr || cam.data.thresholds,
    value: cam.reading && cam.reading.value, level: (cam.reading && cam.reading.level) || 'normal', big: true, decimals: d,
  });
  $('#spSave').disabled = !thr || !spDirty;
  $('#spReset').disabled = !spDirty;
}

function spFill(force = false) {
  const cam = selected();
  const has = !!cam;
  $$('input, button', spForm).forEach((x) => { x.disabled = !has; });
  if (!cam) { $('#spFor').textContent = 'Прибор не выбран'; $('#spRuler').textContent = ''; delete $('#spRuler').dataset.sig; return; }
  if (spCam !== cam.id || force || !spDirty) {
    spCam = cam.id;
    spDirty = false;
    const t = cam.data.thresholds || {};
    const dd = decimalsFor(cam.data);
    for (const k of SETPOINT_KEYS) spForm[k].value = fmtFixed(num(t[k]), dd);
  }
  const { lo, hi } = scaleOf(cam.data.calibration);
  const d = decimalsFor(cam.data);
  $('#spFor').textContent = `${cam.data.name}, ${cam.data.unit}`;
  $('#spScale').textContent = `${fmt(lo, d)}…${fmt(hi, d)} ${cam.data.unit}`;
  spPreview();
}

async function spSubmit(e) {
  e.preventDefault();
  const cam = selected();
  const thr = cam && spValidate();
  if (!thr) return;
  const btn = $('#spSave');
  btn.disabled = true;
  try {
    await api(`/api/cameras/${cam.id}`, { method: 'PATCH', body: { thresholds: thr } });
    spDirty = false;
    toast(`Уставки применены: ${cam.data.name}`);
  } catch (ex) {
    $('#spErr').textContent = ex.message;
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- ROI и шкала
const roiForm = $('#pane-roi');
let roiCam = null;
let roiDirty = false;
let roiMode = 'auto';
let calDir = 'cw';
let roiEdit = false;

function setSeg(box, attr, value) {
  $$(`[data-${attr}]`, box).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset[attr] === value)));
}

function roiDraftValues() {
  return { cx: parseNum(roiForm.roi_cx.value), cy: parseNum(roiForm.roi_cy.value), r: parseNum(roiForm.roi_r.value) };
}

function setRoiEdit(onOff) {
  roiEdit = onOff && roiMode === 'manual' && !!selected();
  $('#roiEdit').setAttribute('aria-pressed', String(roiEdit));
  const d = roiDraftValues();
  const ok = [d.cx, d.cy, d.r].every((v) => v !== null && Number.isFinite(v));
  emit('roi-draft', roiEdit && ok ? d : null);
}

function roiUi() {
  setSeg($('#roiMode'), 'mode', roiMode);
  setSeg($('#calDir'), 'dir', calDir);
  const manual = roiMode === 'manual';
  $$('#roiManual input').forEach((x) => { x.disabled = !manual || !selected(); });
  $('#roiEdit').disabled = !manual || !selected();
  $('#roiHint').textContent = manual
    ? 'Ручной режим: окружность в долях кадра. Перетащите её на кадре или задайте числа; ручка справа меняет радиус.'
    : 'Автоматический режим: YOLOv8 или резервный конвейер OpenCV находит циферблат и вписывает эллипс.';
  $('#roiSave').disabled = !roiDirty || !selected();
  $('#roiReset').disabled = !roiDirty;
}

function roiFill(force = false) {
  const cam = selected();
  $$('input, button', roiForm).forEach((x) => { x.disabled = !cam; });
  if (!cam) { $('#roiFor').textContent = 'Прибор не выбран'; setRoiEdit(false); return; }
  if (roiCam !== cam.id || force || !roiDirty) {
    if (roiCam !== cam.id) setRoiEdit(false);
    roiCam = cam.id;
    roiDirty = false;
    const c = cam.data.calibration || {};
    const roi = c.roi || { mode: 'auto', cx: 0.5, cy: 0.5, r: 0.45 };
    roiMode = roi.mode || 'auto';
    calDir = c.direction || 'cw';
    roiForm.roi_cx.value = fmtInput(roi.cx); roiForm.roi_cy.value = fmtInput(roi.cy); roiForm.roi_r.value = fmtInput(roi.r);
    roiForm.v_min.value = fmtInput(c.v_min); roiForm.v_max.value = fmtInput(c.v_max);
    roiForm.theta_min.value = fmtInput(c.theta_min, 1); roiForm.theta_max.value = fmtInput(c.theta_max, 1);
    $('#roiErr').textContent = '';
  }
  $('#roiFor').textContent = `${cam.data.name}, ${cam.data.unit}`;
  roiUi();
  roiLive();
}

function roiLive() {
  const cam = selected();
  const r = cam && cam.reading;
  $('#calAngle').textContent = r && r.valid && r.angle !== null ? `${fmt(r.angle, 1)}°` : '—';
  $('#roiSrc').textContent = r ? `${DIAL_SOURCE[r.dial_source] || r.dial_source}${r.geom ? `, ${fmt(r.geom.score, 2)}` : ''}` : '—';
}

function roiMarkDirty() {
  roiDirty = true;
  roiUi();
  if (roiEdit) setRoiEdit(true);
}

function roiRead() {
  const v = (n) => parseNum(roiForm[n].value);
  const f = { v_min: v('v_min'), v_max: v('v_max'), theta_min: v('theta_min'), theta_max: v('theta_max'),
    cx: v('roi_cx'), cy: v('roi_cy'), r: v('roi_r') };
  for (const [k, x] of Object.entries(f)) if (x === null || Number.isNaN(x)) {
    if (roiMode === 'auto' && ['cx', 'cy', 'r'].includes(k)) continue;
    throw new Error('Заполните все поля калибровки числами.');
  }
  if (f.v_min === f.v_max) throw new Error('Vmin и Vmax должны различаться.');
  if (roiMode === 'manual' && (f.cx < 0 || f.cx > 1 || f.cy < 0 || f.cy > 1 || f.r < 0.05 || f.r > 1)) {
    throw new Error('Центр ROI — от 0 до 1, радиус — от 0,05 до 1.');
  }
  return {
    v_min: f.v_min, v_max: f.v_max, theta_min: f.theta_min, theta_max: f.theta_max, direction: calDir,
    roi: { mode: roiMode, cx: f.cx ?? 0.5, cy: f.cy ?? 0.5, r: f.r ?? 0.45 },
  };
}

async function roiSubmit(e) {
  e.preventDefault();
  const cam = selected();
  if (!cam) return;
  let calibration;
  try { calibration = roiRead(); } catch (ex) { $('#roiErr').textContent = ex.message; return; }
  $('#roiSave').disabled = true;
  try {
    await api(`/api/cameras/${cam.id}`, { method: 'PATCH', body: { calibration } });
    roiDirty = false;
    setRoiEdit(false);
    $('#roiErr').textContent = '';
    toast(`Калибровка применена: ${cam.data.name}`);
  } catch (ex) {
    $('#roiErr').textContent = ex.message;
    roiUi();
  }
}

// ---------------------------------------------------------------- диагностика
function pctl(arr, p) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
}

export function renderDiag() {
  if (tab !== 'diag') return;
  const m = state.meta;
  if (!m) return;
  const up = m.uptime_s + (performance.now() - state.metaAt) / 1000;
  const kv = (dt, dd, title = '') => `<div class="kv"${title ? ` title="${esc(title)}"` : ''}><dt>${dt}</dt><dd>${dd}</dd></div>`;
  $('#diagSys').innerHTML = [
    kv('Сервер работает', durStr(up)),
    kv('Детектор', m.yolo ? 'YOLOv8n' : 'OpenCV, резерв', m.yolo ? 'Веса модели загружены' : 'Нет весов модели или пакета ultralytics — работает классический конвейер'),
    kv('Устройство', esc(m.yolo ? String(m.yolo_device || 'CPU').replace(/^NVIDIA (GeForce )?/, '') : 'CPU'), m.yolo_device || ''),
    kv('Обработка, задано', `${fmt(m.process_fps, 1)} к/с`, 'Частота обработки на каждую камеру, config.PROCESS_FPS'),
    kv('Сглаживание EMA', `α = ${fmt(m.ema_alpha, 2)}`),
    kv('Пультов на связи', String(m.dashboards ?? '—')),
  ].join('');
  const now = Date.now();
  const errs = [];
  $('#diagTable tbody').innerHTML = camList().map((c) => {
    const ts = c.diag.readTs.filter((t) => now - t <= 30000);
    const span = ts.length > 1 ? (ts[ts.length - 1] - ts[0]) / 1000 : 0;
    const rate = span > 0 ? (ts.length - 1) / span : null;
    const p50 = pctl(c.diag.procMs, 0.5), p95 = pctl(c.diag.procMs, 0.95);
    const st = c.stream || {};
    const upS = st.online_since ? now / 1000 - st.online_since : null;
    if (st.last_error) errs.push(`${c.data.name}: ${st.last_error}`);
    const low = rate !== null && m.process_fps && rate < m.process_fps * 0.6;
    return `<tr aria-current="${c.id === state.selectedId}">
      <td class="nm" title="${esc(c.data.name)}">${esc(c.data.name)}</td>
      <td class="${c.status !== 'online' ? 'bad' : ''}">${c.status === 'online' ? fmt(st.fps, 1) : '—'}</td>
      <td class="${low ? 'bad' : ''}">${rate === null ? '—' : fmt(rate, 1)}</td>
      <td>${p50 === null ? '—' : `${fmt(p50, 0)} / ${fmt(p95, 0)}`}</td>
      <td class="${upS === null ? 'bad' : ''}" title="${upS === null ? '' : durStr(upS)}">${upS === null ? 'нет' : durShort(upS)}</td>
      <td class="${st.fail_count ? 'bad' : 'dim'}">${st.fail_count ?? 0}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" class="dim">Приборов нет</td></tr>';
  $('#diagErr').innerHTML = errs.map((t) => `<div class="err-line">${esc(t)}</div>`).join('');
}

// ---------------------------------------------------------------- источник
const srcForm = $('#pane-src');
let srcFields = null;
let srcCam = null;
let srcDirty = false;

function srcFill(force = false) {
  const cam = selected();
  $$('input, select, button', srcForm).forEach((x) => { x.disabled = !cam; });
  if (!cam) { $('#srcFor').textContent = 'Прибор не выбран'; return; }
  if (srcCam !== cam.id || force || !srcDirty) {
    srcCam = cam.id;
    srcDirty = false;
    srcFields.set(cam.data);
    $('#srcErr').textContent = '';
  }
  $('#srcFor').textContent = `${cam.data.name}: ${cam.status === 'online' ? 'поток в сети' : 'нет потока'}`;
  $('#srcQr').hidden = cam.data.type !== 'phone_ws';
  $('#srcSave').disabled = !srcDirty;
}

async function srcSubmit(e) {
  e.preventDefault();
  const cam = selected();
  if (!cam) return;
  const body = srcFields.read();
  if (!body.name) { $('#srcErr').textContent = 'Укажите наименование прибора.'; return; }
  $('#srcSave').disabled = true;
  try {
    await api(`/api/cameras/${cam.id}`, { method: 'PATCH', body });
    srcDirty = false;
    toast('Источник сохранён');
  } catch (ex) {
    $('#srcErr').textContent = ex.message;
    $('#srcSave').disabled = false;
  }
}

// ---------------------------------------------------------------- сборка
function fillAll(force = false) { spFill(force); roiFill(force); srcFill(force); renderDiag(); }

export function initControl() {
  const tabs = $$('.control [role="tab"]');
  tabs.forEach((t) => t.addEventListener('click', () => setTab(t.id.slice(4))));
  $('.control .tabs').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const i = tabs.findIndex((t) => t.getAttribute('aria-selected') === 'true') + (e.key === 'ArrowRight' ? 1 : -1);
    const t = tabs[(i + tabs.length) % tabs.length];
    setTab(t.id.slice(4), true);
  });

  spForm.addEventListener('input', () => { spDirty = true; spPreview(); });
  spForm.addEventListener('submit', spSubmit);
  $('#spReset').addEventListener('click', () => { spDirty = false; spFill(true); $('#spErr').textContent = ''; });

  roiForm.addEventListener('input', roiMarkDirty);
  roiForm.addEventListener('submit', roiSubmit);
  $$('#roiMode [data-mode]').forEach((b) => b.addEventListener('click', () => {
    if (roiMode === b.dataset.mode) return;
    roiMode = b.dataset.mode;
    const cam = selected();
    const g = cam && cam.reading && cam.reading.geom;
    if (roiMode === 'manual' && g && !(cam.data.calibration.roi && cam.data.calibration.roi.mode === 'manual')) {
      // старт ручной ROI — от найденного сейчас эллипса
      const [cx, cy, a, bb] = g.ellipse;
      roiForm.roi_cx.value = fmtInput(cx / g.w, 3);
      roiForm.roi_cy.value = fmtInput(cy / g.h, 3);
      roiForm.roi_r.value = fmtInput(Math.max(a, bb) / Math.min(g.w, g.h), 3);
    }
    roiMarkDirty();
    if (roiMode === 'manual') setRoiEdit(true); else setRoiEdit(false);
  }));
  $$('#calDir [data-dir]').forEach((b) => b.addEventListener('click', () => { calDir = b.dataset.dir; roiMarkDirty(); }));
  $('#roiEdit').addEventListener('click', () => setRoiEdit(!roiEdit));
  $$('[data-take]').forEach((b) => b.addEventListener('click', () => {
    const r = selected() && selected().reading;
    if (!r || !r.valid || r.angle === null) { toast('Стрелка сейчас не распознана — угол взять нельзя', 'warn'); return; }
    roiForm[b.dataset.take].value = fmtInput(r.angle, 1);
    roiMarkDirty();
  }));
  $('#roiReset').addEventListener('click', () => { roiDirty = false; setRoiEdit(false); roiFill(true); });
  $('#roiRedetect').addEventListener('click', async () => {
    const cam = selected();
    try { await api(`/api/cameras/${cam.id}/redetect`, { method: 'POST' }); toast('Циферблат будет найден заново на следующем кадре'); } catch (ex) { toast(ex.message, 'err'); }
  });
  on('roi-drag', (d) => {
    roiForm.roi_cx.value = fmtInput(d.cx, 3);
    roiForm.roi_cy.value = fmtInput(d.cy, 3);
    roiForm.roi_r.value = fmtInput(d.r, 3);
    roiDirty = true;
    roiUi();
  });

  srcFields = bindSourceFields(srcForm);
  srcForm.addEventListener('input', () => { srcDirty = true; $('#srcSave').disabled = false; });
  srcForm.addEventListener('change', () => { srcDirty = true; $('#srcSave').disabled = false; });
  srcForm.addEventListener('submit', srcSubmit);
  $('#srcRestart').addEventListener('click', async () => {
    const cam = selected();
    try { await api(`/api/cameras/${cam.id}/restart`, { method: 'POST' }); toast(`Переподключение: ${cam.data.name}`); } catch (ex) { toast(ex.message, 'err'); }
  });
  $('#srcQr').addEventListener('click', () => openPhone(selected().id));
  $('#srcClear').addEventListener('click', async () => {
    const cam = selected();
    if (!await confirmDlg('Очистить архив?', `Все сохранённые показания «${cam.data.name}» будут удалены из базы. Тренды начнутся заново.`, 'Очистить')) return;
    try { await api(`/api/cameras/${cam.id}/history`, { method: 'DELETE' }); emit('cam-config', cam.id); toast('Архив показаний очищен'); } catch (ex) { toast(ex.message, 'err'); }
  });
  $('#srcDelete').addEventListener('click', async () => {
    const cam = selected();
    if (!await confirmDlg('Удалить прибор?', `«${cam.data.name}» исчезнет с пульта вместе с архивом показаний. Записи журнала останутся.`)) return;
    try { await api(`/api/cameras/${cam.id}`, { method: 'DELETE' }); toast('Прибор удалён'); } catch (ex) { toast(ex.message, 'err'); }
  });

  on('select', () => fillAll());
  on('cams', () => fillAll());
  on('cam-config', (id) => { if (id === state.selectedId) fillAll(); });
  on('reading', (id) => {
    if (id !== state.selectedId) return;
    roiLive();
    if (tab === 'sp') spPreview();
  });
  on('status', (id) => { if (id === state.selectedId) srcFill(); });
  setInterval(renderDiag, 1000);
  setTab(tab);
  fillAll();
}
