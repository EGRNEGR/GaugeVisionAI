// Вкладка «Мониторинг»: сетка приборов (строго 3×3 / 4×4 / 6×6 колонок),
// двухстрочные наименования без потери идентификатора контура, полнофоновая заливка
// WARNING / CRITICAL, скорость изменения Δ/мин, 15-минутный спарклайн и шкала уставок.
import { $, $$, esc, fmt, fmtRate, durStr, LEVEL_TAG } from './util.js';
import {
  state, on, camList, select, setDetailOpen, setView,
  buildSensorTelemetry, selectDashboardSummary, unackedByCam,
} from './store.js';
import { renderRuler } from './ruler.js';
import { renderSparklineSvg } from './plot.js';
import { applyInspectorLayout } from './readout.js';

const gridEl = $('#tileGrid');
const tiles = new Map(); // id -> { btn, code, name, badges, num, unit, spark, rate, ruler }

function populateGroups() {
  const sel = $('#selGroup');
  const groups = [];
  const seen = new Set();
  for (const c of camList()) {
    const g = c.data.group || 'Прочие';
    if (!seen.has(g)) { seen.add(g); groups.push(g); }
  }
  const prev = state.grid.group;
  sel.innerHTML = `<option value="all">Все узлы (${groups.length})</option>`
    + groups.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
  sel.value = seen.has(prev) ? prev : 'all';
  state.grid.group = sel.value;
}

function matchesFilter(telemetry) {
  const f = state.grid.filter;
  if (f === 'alert' && telemetry.status !== 'CRITICAL') return false;
  if (f === 'warning' && telemetry.status !== 'WARNING') return false;
  if (f === 'deviation' && telemetry.status !== 'WARNING' && telemetry.status !== 'CRITICAL') return false;
  if (f === 'nodata' && telemetry.status !== 'STALE') return false;
  if (state.grid.group !== 'all' && telemetry.group !== state.grid.group) return false;
  if (state.grid.search) {
    const q = state.grid.search.toLowerCase();
    const hay = `${telemetry.code} ${telemetry.displayName} ${telemetry.name} ${telemetry.group}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function buildTile(id) {
  let t = tiles.get(id);
  if (t) return t;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'tile';
  btn.setAttribute('role', 'listitem');
  btn.dataset.id = id;
  btn.innerHTML = `
    <div class="tile-head">
      <span class="tile-code"></span>
      <span class="tile-badges"></span>
    </div>
    <div class="tile-name"></div>
    <div class="tile-mid">
      <div class="tile-val-wrap">
        <span class="tile-num mono"></span>
        <span class="tile-unit"></span>
      </div>
      <div class="tile-dyn">
        <svg class="tile-spark" aria-hidden="true"></svg>
        <span class="tile-rate mono"></span>
      </div>
    </div>
    <div class="tile-bot">
      <div class="ruler"></div>
    </div>`;
  const q = (s) => btn.querySelector(s);
  t = {
    btn,
    code: q('.tile-code'),
    badges: q('.tile-badges'),
    name: q('.tile-name'),
    num: q('.tile-num'),
    unit: q('.tile-unit'),
    spark: q('.tile-spark'),
    rate: q('.tile-rate'),
    ruler: q('.ruler'),
  };
  btn.addEventListener('click', () => {
    if (state.selectedId === id && state.detailOpen && state.inspector.mode !== 'collapsed') {
      setDetailOpen(false);
    } else {
      select(id, { openDetail: true });
    }
  });
  btn.addEventListener('keydown', onTileKeydown);
  tiles.set(id, t);
  return t;
}

function renderTileTelemetry(tel) {
  const t = buildTile(tel.id);
  const d = tel.decimals;
  const live = tel.isLive;
  const unack = tel.unacked;

  t.btn.dataset.live = String(live);
  t.btn.dataset.tone = tel.tone;
  t.btn.setAttribute('aria-current', String(state.detailOpen && state.selectedId === tel.id));

  t.code.textContent = tel.code;
  t.name.textContent = tel.displayName;
  t.btn.title = `${tel.code} — ${tel.name} (${live ? 'Камера телефона CV' : 'Телеметрия контура'})`;

  // Верхние статусные плашки
  let badgeHtml = '';
  if (live) {
    badgeHtml += '<span class="cam-chip" title="Живой источник компьютерного зрения"><svg class="i" aria-hidden="true"><use href="#i-cam"/></svg>КАМЕРА</span>';
  }
  if (tel.status === 'CRITICAL' || tel.status === 'WARNING') {
    const sp = tel.crossedSetpoint;
    badgeHtml += `<span class="tile-zone" data-kind="${tel.tone}" data-unack="${unack}">${LEVEL_TAG[tel.tone]}${sp ? ` ${sp}` : ''}</span>`;
  } else if (tel.status === 'STALE') {
    const lbl = tel.measState === 'disconnected' ? 'ОЖИД. КАМЕРЫ'
      : tel.measState === 'awaiting_reading' ? 'ПОИСК СТРЕЛКИ'
      : tel.measState === 'needs_calibration' ? 'КАЛИБРОВКА'
      : tel.measState === 'hold' ? 'УДЕРЖАНИЕ' : 'НЕТ ДАННЫХ';
    badgeHtml += `<span class="tile-zone" data-kind="nodata" data-unack="${unack}">${lbl}</span>`;
  } else if (unack) {
    badgeHtml += '<span class="tile-zone" data-kind="warning" data-unack="true">НЕКВИТ.</span>';
  } else {
    badgeHtml += '<span class="tile-zone" data-kind="normal">НОРМА</span>';
  }
  if (t.badges.dataset.html !== badgeHtml) {
    t.badges.dataset.html = badgeHtml;
    t.badges.innerHTML = badgeHtml;
  }

  // Главное числовое показание и скорость изменения Δ/мин
  t.num.textContent = fmt(tel.value, d);
  t.unit.textContent = tel.unit;

  if (tel.hasFreshValid) {
    const rateTxt = fmtRate(tel.rateOfChange, d);
    t.rate.textContent = `Δ ${rateTxt}`;
    t.rate.dataset.dir = tel.rateOfChange > 0.01 ? 'up' : tel.rateOfChange < -0.01 ? 'down' : 'flat';
  } else {
    t.rate.textContent = Number.isFinite(tel.ageS) ? `устар. ${durStr(tel.ageS)}` : 'ожид. связи';
    t.rate.dataset.dir = 'flat';
  }

  renderSparklineSvg(t.spark, tel);

  renderRuler(t.ruler, {
    calibration: tel.cam.data.calibration,
    thresholds: tel.cam.data.thresholds,
    value: tel.hasFreshValid ? tel.freshValue : null,
    level: tel.tone === 'nodata' ? 'stale' : tel.tone,
    showScaleLabels: true,
    decimals: d,
  });
}

function syncFilterBadges(counts) {
  $('#gfAll').textContent = String(counts.total);
  $('#gfAlert').textContent = String(counts.critical);
  $('#gfWarn').textContent = String(counts.warning);
  $('#gfDev').textContent = String(counts.deviations);
  $('#gfNoData').textContent = String(counts.stale);
}

export function renderGrid() {
  const summary = selectDashboardSummary();
  syncFilterBadges(summary.counts);

  for (const id of Array.from(tiles.keys())) {
    if (!state.cams.has(id)) {
      tiles.get(id).btn.remove();
      tiles.delete(id);
    }
  }

  const filtered = summary.telemetries.filter(matchesFilter);
  const density = ['9', '16', '36'].includes(String(state.grid.density)) ? Number(state.grid.density) : 36;
  const pageSize = density === 36 ? Math.max(36, filtered.length || 36) : density;
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  if (state.grid.page > totalPages) state.grid.page = totalPages;
  if (state.grid.page < 1) state.grid.page = 1;

  const start = (state.grid.page - 1) * pageSize;
  const visible = density === 36 ? filtered : filtered.slice(start, start + pageSize);

  gridEl.dataset.density = String(density);
  $$('#segDensity [data-density]').forEach((b) => {
    b.setAttribute('aria-pressed', String(Number(b.dataset.density) === density));
  });

  const hasActiveFilter = state.grid.filter !== 'all' || state.grid.group !== 'all' || state.grid.search !== '';
  $('#btnResetFilters').hidden = !hasActiveFilter;

  $('#gridCountLbl').textContent = density !== 36 && filtered.length > 0
    ? `${start + 1}–${start + visible.length} из ${filtered.length}`
    : `${filtered.length} из ${summary.counts.total}`;

  const pager = $('#gridPager');
  pager.hidden = density === 36 || totalPages <= 1;
  if (!pager.hidden) {
    $('#lblPage').textContent = `${state.grid.page} / ${totalPages}`;
    $('#btnPagePrev').disabled = state.grid.page <= 1;
    $('#btnPageNext').disabled = state.grid.page >= totalPages;
  }

  const emptyBox = $('#gridEmpty');
  if (visible.length === 0) {
    gridEl.hidden = true;
    emptyBox.hidden = false;
    $('#gridEmptyText').textContent = state.grid.filter !== 'all'
      ? 'Приборов в выбранной категории состояния сейчас нет.'
      : 'Под выбранные условия поиска приборы не найдены.';
    return;
  }
  gridEl.hidden = false;
  emptyBox.hidden = true;

  const frag = document.createDocumentFragment();
  for (const tel of visible) {
    renderTileTelemetry(tel);
    frag.appendChild(tiles.get(tel.id).btn);
  }
  const curChildren = Array.from(gridEl.children);
  const sameOrder = curChildren.length === visible.length && curChildren.every((el, idx) => el.dataset.id === visible[idx].id);
  if (!sameOrder) {
    gridEl.replaceChildren(frag);
  }
}

export function updateTile(camId) {
  const summary = selectDashboardSummary();
  syncFilterBadges(summary.counts);
  if (state.grid.filter !== 'all') {
    renderGrid();
    return;
  }
  const tel = summary.byId.get(camId);
  if (tel && tiles.has(camId)) {
    renderTileTelemetry(tel);
  }
}

function onTileKeydown(e) {
  if (!['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp'].includes(e.key)) return;
  e.preventDefault();
  const btns = $$('.tile', gridEl);
  const idx = btns.indexOf(e.currentTarget);
  if (idx < 0) return;
  const cols = state.grid.density === '9' ? 3 : state.grid.density === '16' ? 4 : 6;
  const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowDown' ? cols : -cols;
  const target = btns[idx + step];
  if (target) target.focus();
}

export function setMonitorFilter(filterName) {
  state.grid.filter = filterName;
  state.grid.page = 1;
  $$('#segFilter [data-gfilter]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.gfilter === filterName)));
  renderGrid();
}

export function resetMonitorFilters() {
  state.grid.filter = 'all';
  state.grid.group = 'all';
  state.grid.search = '';
  state.grid.page = 1;
  $('#selGroup').value = 'all';
  $('#inpSearch').value = '';
  $$('#segFilter [data-gfilter]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.gfilter === 'all')));
  renderGrid();
}

export function jumpToInstrument(instId) {
  if (!state.cams.has(instId)) return;
  setView('monitor');
  const summary = selectDashboardSummary();
  const tel = summary.byId.get(instId);
  if (tel && !matchesFilter(tel)) {
    resetMonitorFilters();
  }
  const density = Number(state.grid.density) || 36;
  if (density !== 36) {
    const filtered = selectDashboardSummary().telemetries.filter(matchesFilter);
    const pos = filtered.findIndex((t) => t.id === instId);
    if (pos >= 0) state.grid.page = Math.floor(pos / density) + 1;
  }
  select(instId, { openDetail: true });
  renderGrid();
  requestAnimationFrame(() => {
    tiles.get(instId)?.btn.scrollIntoView({ block: 'nearest' });
  });
}

function syncDetailSelection() {
  applyInspectorLayout();
  const unack = unackedByCam();
  for (const [id] of tiles) {
    const cam = state.cams.get(id);
    if (cam) renderTileTelemetry(buildSensorTelemetry(cam, unack));
  }
}

export function initInstruments() {
  $$('#segDensity [data-density]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.density === state.grid.density));
    b.addEventListener('click', () => {
      state.grid.density = b.dataset.density;
      state.grid.page = 1;
      localStorage.setItem('gv.density', state.grid.density);
      renderGrid();
    });
  });

  $$('#segFilter [data-gfilter]').forEach((b) => {
    b.addEventListener('click', () => setMonitorFilter(b.dataset.gfilter));
  });

  $('#selGroup').addEventListener('change', (e) => {
    state.grid.group = e.target.value;
    state.grid.page = 1;
    renderGrid();
  });

  $('#inpSearch').addEventListener('input', (e) => {
    state.grid.search = e.target.value.trim();
    state.grid.page = 1;
    renderGrid();
  });

  $('#btnResetFilters').addEventListener('click', resetMonitorFilters);
  $('#btnEmptyReset').addEventListener('click', resetMonitorFilters);
  $('#btnEmptyLive').addEventListener('click', () => {
    const liveId = state.demo?.live_cam_id || 'demo-mtp160-steam';
    jumpToInstrument(liveId);
  });

  $('#btnPagePrev').addEventListener('click', () => { state.grid.page--; renderGrid(); });
  $('#btnPageNext').addEventListener('click', () => { state.grid.page++; renderGrid(); });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && state.view === 'monitor' && state.detailOpen && !state.stop && !document.querySelector('dialog[open]')) {
      setDetailOpen(false);
    }
  });

  syncDetailSelection();

  on('cams', () => { populateGroups(); renderGrid(); syncDetailSelection(); });
  on('reading', updateTile);
  on('sim-tick', (ids) => {
    const summary = selectDashboardSummary();
    syncFilterBadges(summary.counts);
    if (state.grid.filter !== 'all') {
      renderGrid();
      return;
    }
    for (const id of ids) {
      const tel = summary.byId.get(id);
      if (tel && tiles.has(id)) renderTileTelemetry(tel);
    }
  });
  on('status', updateTile);
  on('freshness', () => {
    const liveId = state.demo?.live_cam_id || 'demo-mtp160-steam';
    if (state.cams.has(liveId)) updateTile(liveId);
  });
  on('events', renderGrid);
  on('conn', renderGrid);
  on('select', syncDetailSelection);
  on('detail-toggle', syncDetailSelection);
  on('inspector-layout', syncDetailSelection);
}
