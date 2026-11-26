// Список приборов: состояние всех точек на одной колонке.
import { $, $$, esc, fmt, num, decimalsFor, LEVEL_TAG, shiftStart } from './util.js';
import { state, on, camList, select, displayLevel, unackedByCam } from './store.js';
import { renderRuler } from './ruler.js';
import { fetchSeries, pushLive } from './series.js';
import { drawSpark } from './plot.js';

const list = $('#instList');
const rows = new Map();          // camId -> { li, btn, f }
const sparks = new Map();        // camId -> ряд смены
let sortMode = localStorage.getItem('gv.sort') || 'order';
let sparkDirty = new Set();

/** Какая уставка нарушена — как crossed_setpoint на сервере. */
export function crossed(value, t) {
  const v = num(value);
  if (v === null || !t) return null;
  const LL = num(t.ll_alert), L = num(t.l_warn), H = num(t.h_warn), HH = num(t.hh_alert);
  if (LL !== null && v <= LL) return 'LL';
  if (HH !== null && v >= HH) return 'HH';
  if (L !== null && v <= L) return 'L';
  if (H !== null && v >= H) return 'H';
  return null;
}

/** Текст и уровень тега состояния прибора. */
export function tagOf(cam) {
  const lv = displayLevel(cam);
  if (!state.connected) return { level: 'stale', text: 'НЕТ ДАННЫХ' };
  if (lv === 'stale') return { level: 'stale', text: cam.status === 'reconnecting' ? 'ПЕРЕПОДКЛ.' : 'НЕТ СВЯЗИ' };
  if (lv === 'hold') return { level: 'hold', text: 'УДЕРЖАНИЕ' };
  const sp = lv === 'normal' ? null : crossed(cam.reading.value, cam.data.thresholds);
  return { level: lv, text: sp ? `${LEVEL_TAG[lv]} ${sp}` : LEVEL_TAG[lv] };
}

export function applyTag(el, cam, unack) {
  const t = tagOf(cam);
  el.dataset.level = t.level;
  el.textContent = t.text;
  el.dataset.unack = String(!!unack);
  el.title = unack ? 'Срабатывание не квитировано' : '';
}

function severity(cam, unack) {
  const lv = displayLevel(cam);
  const base = lv === 'alert' ? 4 : lv === 'warning' ? 3 : (lv === 'stale' || lv === 'hold') ? 2 : 0;
  return base + (unack.has(cam.id) ? 0.5 : 0);
}

function rowFor(cam) {
  let r = rows.get(cam.id);
  if (r) return r;
  const li = document.createElement('li');
  li.innerHTML = `<button class="inst" type="button">
      <span class="idx"></span><span class="name"></span><span class="tag"></span>
      <span class="val"><span class="v"></span><span class="ruler"></span></span>
      <canvas class="spark" aria-hidden="true"></canvas>
    </button>`;
  const btn = li.firstElementChild;
  const f = (s) => btn.querySelector(s);
  r = { li, btn, idx: f('.idx'), name: f('.name'), tag: f('.tag'), v: f('.v'), ruler: f('.ruler'), canvas: f('canvas') };
  btn.addEventListener('click', () => select(cam.id));
  btn.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const btns = $$('.inst', list);
    const i = btns.indexOf(btn) + (e.key === 'ArrowDown' ? 1 : -1);
    if (btns[i]) { btns[i].focus(); btns[i].click(); }
  });
  rows.set(cam.id, r);
  return r;
}

function renderRow(cam, unack) {
  const r = rowFor(cam);
  const d = decimalsFor(cam.data);
  const rd = cam.reading;
  r.name.textContent = cam.data.name;
  r.btn.title = cam.data.name;
  applyTag(r.tag, cam, unack.has(cam.id));
  r.v.innerHTML = `${fmt(rd && rd.value, d)}<small>${esc(cam.data.unit)}</small>`;
  const lv = displayLevel(cam);
  r.btn.dataset.stale = String(lv === 'stale' || lv === 'hold');
  r.btn.setAttribute('aria-current', String(state.selectedId === cam.id));
  renderRuler(r.ruler, {
    calibration: cam.data.calibration, thresholds: cam.data.thresholds,
    value: rd && rd.value, level: lv === 'stale' ? 'stale' : (rd && rd.level) || 'normal', decimals: d,
  });
}

/** Полная перерисовка: состав, порядок, номера. */
export function renderList() {
  const cams = camList();
  const unack = unackedByCam();
  $('#instCount').textContent = String(cams.length);
  let ordered = cams.map((c, i) => ({ c, i }));
  if (sortMode === 'severity') {
    ordered.sort((a, b) => severity(b.c, unack) - severity(a.c, unack) || a.i - b.i);
  }
  for (const id of Array.from(rows.keys())) if (!state.cams.has(id)) { rows.get(id).li.remove(); rows.delete(id); sparks.delete(id); }
  if (!cams.length) {
    list.innerHTML = `<li class="empty-list"><p>Приборы ещё не подключены. Добавьте IP-камеру (RTSP или HTTP-MJPEG), найдите устройства в сети или подключите смартфон по QR-коду.</p></li>`;
    return;
  }
  const empty = $('.empty-list', list);
  if (empty) empty.remove();
  ordered.forEach(({ c, i }) => {
    const r = rowFor(c);
    r.idx.textContent = String(i + 1).padStart(2, '0');
    renderRow(c, unack);
    list.appendChild(r.li);
    if (!sparks.has(c.id)) loadSpark(c);
  });
}

export function updateRow(camId) {
  const cam = state.cams.get(camId);
  if (cam) renderRow(cam, unackedByCam());
}

async function loadSpark(cam) {
  sparks.set(cam.id, null);
  try {
    const s = await fetchSeries(cam.id, shiftStart(), 140);
    sparks.set(cam.id, s);
    sparkDirty.add(cam.id);
  } catch (e) {
    sparks.delete(cam.id);
  }
}

function drawSparks() {
  // спарклайн — смена с начала до текущего момента
  const x0 = shiftStart().getTime();
  const x1 = Math.max(Date.now(), x0 + 15 * 60000);
  for (const id of sparkDirty) {
    const cam = state.cams.get(id), r = rows.get(id);
    if (cam && r) drawSpark(r.canvas, sparks.get(id), cam, x0, x1);
  }
  sparkDirty = new Set();
}

export function initInstruments() {
  $$('[data-sort]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.sort === sortMode));
    b.addEventListener('click', () => {
      sortMode = b.dataset.sort;
      localStorage.setItem('gv.sort', sortMode);
      $$('[data-sort]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      renderList();
    });
  });
  on('reading', (camId) => {
    updateRow(camId);
    const cam = state.cams.get(camId);
    const s = sparks.get(camId);
    const r = cam && cam.reading;
    if (s && r && r.valid) {
      pushLive(s, Date.parse(r.ts), r.value, r.level);
      sparkDirty.add(camId);
    }
  });
  on('status', updateRow);
  on('cams', renderList);
  on('select', () => { for (const c of camList()) updateRow(c.id); });
  on('conn', renderList);
  on('events', () => {
    if (sortMode === 'severity') renderList();
    else for (const c of camList()) updateRow(c.id);
  });
  on('cam-config', (camId) => { sparks.delete(camId); renderList(); });

  // спарклайны: перерисовка не чаще раза в секунду, свежие агрегаты — раз в минуту и на новой смене
  let shiftAt = shiftStart().getTime();
  setInterval(drawSparks, 1000);
  setInterval(() => { for (const id of sparks.keys()) sparkDirty.add(id); }, 30000);
  setInterval(() => {
    const s = shiftStart().getTime();
    if (s !== shiftAt) { shiftAt = s; sparks.clear(); renderList(); return; }
    for (const c of camList()) loadSpark(c);
  }, 60000);
  window.addEventListener('resize', () => { for (const id of sparks.keys()) sparkDirty.add(id); });

  // 1…9 — выбор прибора по номеру в списке
  document.addEventListener('keydown', (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const tgt = e.target;
    if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'SELECT' || tgt.tagName === 'TEXTAREA')) return;
    if (document.querySelector('dialog[open]')) return;
    if (!/^[1-9]$/.test(e.key)) return;
    const cam = camList()[Number(e.key) - 1];
    if (cam) { select(cam.id); rows.get(cam.id)?.btn.scrollIntoView({ block: 'nearest' }); }
  });
}
