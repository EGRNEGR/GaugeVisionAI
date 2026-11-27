// Глобальная шапка станции, сводные счётчики (из единого селектора selectDashboardSummary),
// блок агрегированной статистики ТЭЦ и переключение сценариев симуляции.
import { $, $$, esc, api, toast, fmt, timeStr, durStr, plural, PHONE_STAGE_TEXT } from './util.js';
import {
  state, on, livePrimaryCam, selectDashboardSummary, setView, setStatsCollapsed,
} from './store.js';
import { Sound, renderSoundButton } from './sound.js';
import { acknowledgeAll, setJournalFilter } from './journal.js';
import { openPhoneDialog } from './devices.js';
import { jumpToInstrument, setMonitorFilter } from './instruments.js';
import { startNewRun, stopCurrentRun } from './history.js';

const BASE_TITLE = 'GaugeVision AI — пульт оператора КТЦ';
let issuesOpen = false;

function setCounter(id, n) {
  const el = $(`#${id}`);
  if (!el) return;
  el.textContent = String(n);
  const cell = el.closest('.counter');
  if (cell) cell.dataset.active = String(n > 0);
}

function derivePhoneStage(liveCam, liveTelemetry) {
  if (!liveCam) return 'waiting_phone';
  if (!state.connected) return 'stream_interrupted';
  const st = liveCam.stream || {};
  if (st.client_state === 'permission_denied') return 'permission_denied';
  if (st.client_state === 'camera_error') return 'camera_error';
  if (liveTelemetry?.hasFreshValid) return 'reading_received';
  if (liveCam.status === 'online') return 'no_reading_yet';
  if ((st.frames_total || 0) > 0) return 'stream_interrupted';
  if (st.ws_connected) return 'awaiting_permission';
  return 'waiting_phone';
}

function renderStationStats(summary) {
  const bar = $('#stationStatsBar');
  const toggleBtn = $('#btnToggleStats');
  if (!bar) return;

  bar.hidden = !!state.statsCollapsed;
  if (toggleBtn) toggleBtn.setAttribute('aria-pressed', String(!state.statsCollapsed));
  if (state.statsCollapsed) return;

  const { counts, station } = summary;

  // 1. Суммарная активная мощность генераторов ТГ-1 + ТГ-2 (МВт)
  if (station.powerMw !== null) {
    $('#stPowerVal').textContent = fmt(station.powerMw, 1);
    const pct = Math.min(100, Math.round((station.powerMw / station.powerNominalMw) * 100));
    $('#stPowerPct').textContent = `${pct}% уст.`;
    const fill = $('#stPowerFill');
    fill.style.width = `${pct}%`;
    fill.dataset.tone = pct >= 92 ? 'alert' : pct >= 85 ? 'warning' : 'normal';
    $('#stPowerSub').textContent = station.powerBreakdown.join(' | ');
  } else {
    $('#stPowerVal').textContent = '—';
    $('#stPowerPct').textContent = '—';
    $('#stPowerFill').style.width = '0%';
    $('#stPowerSub').textContent = 'Нет свежих данных ТГ';
  }

  // 2. Суммарный расход острого пара котлов (т/ч)
  $('#stSteamVal').textContent = station.steamTph !== null ? fmt(station.steamTph, 0) : '—';
  $('#stSteamSub').textContent = station.steamTph !== null
    ? 'Котлы К-1 + К-2 (острый пар)'
    : 'Нет свежих данных расходомеров';

  // 3. Средняя достоверность распознавания CV (Vision Engine 3.1)
  const ve = state.meta?.vision_engine;
  const profLabel = ve?.profile ? `${station.yoloActive ? 'YOLOv8n' : 'OpenCV'} (${ve.profile})` : (station.yoloActive ? 'YOLOv8n' : 'OpenCV');
  $('#stCvModel').textContent = profLabel;
  const selProf = $('#selVisionProfile');
  if (selProf && ve?.profile && selProf.value !== ve.profile) {
    selProf.value = ve.profile;
  }
  if (selProf && !selProf.dataset.bound) {
    selProf.dataset.bound = '1';
    selProf.addEventListener('change', async () => {
      try {
        const res = await api('/api/vision/profile', {
          method: 'POST',
          body: JSON.stringify({ profile: selProf.value }),
        });
        if (state.meta) state.meta.vision_engine = res;
        toast(`Профиль CV переключён: ${res.profile_label || res.profile}`, 'ok');
      } catch (err) {
        toast(`Ошибка смены профиля CV: ${err?.message || err}`, 'err');
        if (ve?.profile) selProf.value = ve.profile;
      }
    });
  }
  if (station.cvConfidencePct !== null) {
    $('#stCvVal').textContent = fmt(station.cvConfidencePct, 1);
    $('#stCvUnit').textContent = '%';
    $('#stCvSub').textContent = `Поток активен (${station.cvActiveCount} из ${station.cvTotalCount} кам.)`;
  } else {
    $('#stCvVal').textContent = 'Ожидание';
    $('#stCvUnit').textContent = '';
    $('#stCvSub').textContent = 'Подключите камеру К1-Р01 по QR';
  }

  // 4. Срабатывания за смену
  $('#stTripsVal').textContent = String(station.shiftTrips);
  $('#stTripsSub').textContent = counts.unack > 0
    ? `Неквитировано: ${counts.unack}`
    : 'Все срабатывания квитированы';

  // 5. Распределение по зонам состояния
  const tot = Math.max(1, counts.total);
  const seg = (z, n) => (n > 0 ? `<div class="zones-seg" data-z="${z}" style="flex:${(n / tot) * 100}"></div>` : '');
  $('#stZonesBar').innerHTML = [
    seg('normal', counts.normal),
    seg('warning', counts.warning),
    seg('alert', counts.critical),
    seg('stale', counts.stale),
  ].join('');

  $('#stZonesLegend').innerHTML = [
    `<span class="zl-item"><i class="zl-dot ok"></i>Норма: <b>${counts.normal}</b></span>`,
    `<span class="zl-item"><i class="zl-dot warn"></i>Предупр.: <b>${counts.warning}</b></span>`,
    `<span class="zl-item"><i class="zl-dot alarm"></i>Аварии: <b>${counts.critical}</b></span>`,
    `<span class="zl-item"><i class="zl-dot stale"></i>Без данных: <b>${counts.stale}</b></span>`,
  ].join('');
}

export function renderSummary() {
  const summary = selectDashboardSummary();
  const { counts, criticalItems, warningItems, staleItems } = summary;

  // Единый источник истины для шапки (1:1 с фильтрами в instruments.js)
  setCounter('cAlarm', counts.critical);
  setCounter('cWarn', counts.warning);
  setCounter('cDev', counts.deviations);
  setCounter('cNoData', counts.stale);
  setCounter('cUnack', counts.unack);

  $('#tabCntMonitor').textContent = String(counts.total);
  const evBadge = $('#tabCntEvents');
  evBadge.textContent = String(counts.unack);
  evBadge.dataset.alert = String(counts.unack > 0);

  const run = state.demo?.active_run;
  const runCount = Number(run?.readings_count || 0);
  $('#tabCntHistory').textContent = String(runCount + summary.station.shiftTrips);

  const isDemo = !!(state.meta?.demo_mode || state.demo?.enabled);
  const mb = $('#modeBadge');
  mb.textContent = isDemo ? 'ДЕМО КТЦ' : 'КТЦ';
  mb.dataset.demo = String(isDemo);

  // Синхронизация кнопок сценария симуляции
  const curScenario = state.demo?.scenario || 'mixed';
  $('#scenarioWrap').hidden = !isDemo;
  $$('#segScenario [data-scenario]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.scenario === curScenario));
  });

  // Компактная полоса показа
  const rs = $('#runStrip');
  rs.hidden = !isDemo || !run;
  if (isDemo && run) {
    const ended = !!run.ended_at;
    $('#runStripLbl').textContent = `${run.label}${ended ? ' (стоп)' : ''}`;
    $('#runStripCnt').textContent = `${runCount} отсч.`;
    $('#btnRunStop').disabled = ended;
  }

  // Индикатор камеры телефона
  const live = livePrimaryCam();
  const liveTel = live ? summary.byId.get(live.id) : null;
  const phonePill = $('#phonePill');
  const SHORT_PHONE_STAGE = {
    waiting_phone: 'Камера: ожид.',
    awaiting_permission: 'Камера: доступ',
    permission_denied: 'Камера: отказ',
    camera_error: 'Камера: сбой',
    no_reading_yet: 'Камера: поиск',
    reading_received: 'Камера: CV ок',
    stream_interrupted: 'Камера: обрыв',
  };
  if (live && live.data.type === 'phone_ws') {
    phonePill.hidden = false;
    const stage = derivePhoneStage(live, liveTel);
    phonePill.dataset.stage = stage;
    phonePill.title = PHONE_STAGE_TEXT[stage] || stage;
    $('#phoneStageTxt').textContent = SHORT_PHONE_STAGE[stage] || stage;
    $('#lblJumpLive').textContent = `Камера ${live.data.code || 'К1-Р01'}`;
  } else {
    phonePill.hidden = true;
  }

  // Глобальный баннер статуса станции (без дублирования цифр счётчиков справа)
  const banner = $('#plantBanner');
  const headline = $('#plantHeadline');
  const actions = $('#plantActions');
  actions.innerHTML = '';

  const totalIssues = counts.critical + counts.warning + counts.stale;
  if (!state.connected) {
    banner.dataset.tone = 'alert';
    headline.textContent = 'Нет связи с сервером (WSS)';
  } else if (counts.critical > 0) {
    banner.dataset.tone = 'alert';
    const top = criticalItems[0];
    const valTxt = fmt(top.freshValue, top.decimals);
    const spTxt = top.crossedSetpoint ? ` (${top.crossedSetpoint})` : '';
    headline.textContent = `${top.code} ${valTxt} ${top.unit}${spTxt}`;
    banner.title = `${top.code}: ${valTxt} ${top.unit}${spTxt} — ${top.name}`;
    const btnJump = document.createElement('button');
    btnJump.className = 'btn sm primary';
    btnJump.type = 'button';
    btnJump.textContent = 'Открыть';
    btnJump.addEventListener('click', () => jumpToInstrument(top.id));
    actions.appendChild(btnJump);
  } else if (counts.warning > 0) {
    banner.dataset.tone = 'warning';
    const top = warningItems[0];
    const valTxt = fmt(top.freshValue, top.decimals);
    const spTxt = top.crossedSetpoint ? ` (${top.crossedSetpoint})` : '';
    headline.textContent = `${top.code} ${valTxt} ${top.unit}${spTxt}`;
    banner.title = `${top.code}: ${valTxt} ${top.unit}${spTxt} — ${top.name}`;
    const btnJump = document.createElement('button');
    btnJump.className = 'btn sm primary';
    btnJump.type = 'button';
    btnJump.textContent = 'Открыть';
    btnJump.addEventListener('click', () => jumpToInstrument(top.id));
    actions.appendChild(btnJump);
  } else if (counts.stale > 0) {
    const top = staleItems[0];
    banner.dataset.tone = top.prevAlarm === 'alert' ? 'alert' : 'nodata';
    headline.textContent = `Без данных: ${top.code}`;
    banner.title = `Без данных: ${top.code} — ${top.name}`;
    const btnAct = document.createElement('button');
    btnAct.className = 'btn sm';
    btnAct.type = 'button';
    if (top.cam.data.type === 'phone_ws' && top.measState === 'disconnected') {
      btnAct.textContent = 'QR телефона';
      btnAct.addEventListener('click', () => openPhoneDialog(top.id));
    } else {
      btnAct.textContent = `К ${top.code}`;
      btnAct.addEventListener('click', () => jumpToInstrument(top.id));
    }
    actions.appendChild(btnAct);
  } else {
    banner.dataset.tone = 'normal';
    headline.textContent = counts.total
      ? `Штатный режим станции (${counts.total} ${plural(counts.total, 'прибор', 'прибора', 'приборов')} в норме)`
      : 'Нет подключённых приборов';
  }

  if (totalIssues > 1) {
    const btnMore = document.createElement('button');
    btnMore.className = 'btn sm';
    btnMore.type = 'button';
    btnMore.textContent = `Список (${totalIssues})`;
    btnMore.addEventListener('click', () => {
      issuesOpen = !issuesOpen;
      renderIssuesDrawer(criticalItems, warningItems, staleItems);
    });
    actions.appendChild(btnMore);
  } else if (issuesOpen && totalIssues === 0) {
    issuesOpen = false;
  }
  renderIssuesDrawer(criticalItems, warningItems, staleItems);
  renderStationStats(summary);

  // Кнопка квитирования
  const ackBtn = $('#btnAckAll');
  ackBtn.disabled = counts.unack === 0;
  ackBtn.classList.toggle('warn-only', counts.unack > 0 && !counts.unackHasAlert);
  $('#lblAckAll').textContent = counts.unack > 0 ? `Квитировать (${counts.unack})` : 'Квитировано';

  Sound.setMode(counts.unackHasAlert ? 'alert' : counts.unack > 0 ? 'warning' : 'none');
  document.title = counts.deviations > 0
    ? `(${counts.deviations}) ${counts.critical ? 'АВАРИЯ' : 'ПРЕДУПР.'} — ${BASE_TITLE}`
    : BASE_TITLE;
}

function renderIssuesDrawer(criticalItems, warningItems, staleItems) {
  const drawer = $('#issuesDrawer');
  const ul = $('#issuesList');
  const items = [...criticalItems, ...warningItems, ...staleItems];
  drawer.hidden = !issuesOpen || items.length === 0;
  if (drawer.hidden) return;
  ul.innerHTML = items.map((t) => {
    const kindLbl = t.tone === 'alert' ? `АВАРИЯ${t.crossedSetpoint ? ` ${t.crossedSetpoint}` : ''}`
      : t.tone === 'warning' ? `ПРЕДУПР.${t.crossedSetpoint ? ` ${t.crossedSetpoint}` : ''}` : 'БЕЗ ДАННЫХ';
    const tagLv = t.tone === 'nodata' ? 'stale' : t.tone;
    const valTxt = t.hasFreshValid ? `${fmt(t.freshValue, t.decimals)} ${esc(t.unit)}` : 'нет свежего замера';
    return `<li>
      <span class="tag" data-level="${tagLv}">${kindLbl}</span>
      <strong class="mono">${esc(t.code)}</strong>
      <span>${esc(t.name)}</span>
      <span class="mono">${valTxt}</span>
      <span class="sp"></span>
      <button class="btn sm" type="button" data-jump="${esc(t.id)}">Инспектор</button>
    </li>`;
  }).join('');
  $$('[data-jump]', ul).forEach((b) => b.addEventListener('click', () => {
    issuesOpen = false;
    drawer.hidden = true;
    jumpToInstrument(b.dataset.jump);
  }));
}

function renderClockAndLink() {
  $('#clockT').textContent = timeStr(new Date());
  const cell = $('#linkCell');
  cell.dataset.state = state.connected ? 'up' : 'down';
  $('#linkText').textContent = state.connected
    ? 'WSS'
    : `Обрыв${state.downSince ? ` ${durStr((Date.now() - state.downSince) / 1000)}` : ''}`;
}

function syncTabs() {
  $$('.nav-tab').forEach((t) => {
    const active = t.dataset.view === state.view;
    t.setAttribute('aria-selected', String(active));
  });
  for (const name of ['monitor', 'architecture', 'dispatch', 'events', 'history', 'cameras', 'panel', 'calibration']) {
    const sec = $(`#view-${name}`);
    if (sec) sec.hidden = name !== state.view;
  }
}

async function switchScenario(scenarioId) {
  try {
    const res = await api('/api/demo/scenario', {
      method: 'POST',
      body: { scenario: scenarioId },
    });
    if (res) state.demo = res;
    renderSummary();
    const labelMap = {
      mixed: 'Смешанный режим (2 аварии, 3 предупреждения, 1 обрыв)',
      nominal: 'Штатный режим (все 35 каналов стенда в норме)',
      peak: 'Пиковая нагрузка и перегрев парового тракта',
      cascade: 'Аварийный каскад нарушений верхних и нижних уставок',
    };
    toast(`Включён сценарий: ${labelMap[scenarioId] || scenarioId}`);
  } catch (e) {
    toast(`Не удалось переключить сценарий: ${e.message}`, 'err');
  }
}

export function initHeader() {
  $$('.nav-tab').forEach((btn) => {
    btn.addEventListener('click', () => setView(btn.dataset.view));
  });

  $$('#segScenario [data-scenario]').forEach((btn) => {
    btn.addEventListener('click', () => switchScenario(btn.dataset.scenario));
  });

  $('#btnToggleStats')?.addEventListener('click', () => {
    setStatsCollapsed(!state.statsCollapsed);
  });

  $('#btnJumpLive').addEventListener('click', () => {
    const live = livePrimaryCam();
    if (live) jumpToInstrument(live.id);
  });

  $('#btnHeaderQr').addEventListener('click', () => {
    const live = livePrimaryCam();
    openPhoneDialog(live ? live.id : null);
  });

  $('#btnAckAll').addEventListener('click', () => acknowledgeAll());
  $('#btnRunNew').addEventListener('click', () => startNewRun());
  $('#btnRunStop').addEventListener('click', () => stopCurrentRun());
  $('#btnCloseIssues').addEventListener('click', () => { issuesOpen = false; $('#issuesDrawer').hidden = true; });

  $('#btnSound').addEventListener('click', () => { Sound.toggle(); renderSummary(); });
  $('#btnFullscreen').addEventListener('click', () => {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
    else document.exitFullscreen?.().catch(() => {});
  });

  $$('.counter').forEach((b) => b.addEventListener('click', () => {
    const kind = b.dataset.summary;
    if (kind === 'unack') {
      setView('events');
      setJournalFilter('unack');
    } else if (['alert', 'warning', 'deviation', 'nodata'].includes(kind)) {
      setView('monitor');
      setMonitorFilter(kind);
    }
  }));

  renderSoundButton();
  renderClockAndLink();
  syncTabs();
  setInterval(renderClockAndLink, 1000);

  on('view', syncTabs);
  on('stats-toggle', renderSummary);
  on('reading', renderSummary);
  on('sim-tick', renderSummary);
  on('status', renderSummary);
  on('cams', renderSummary);
  on('events', renderSummary);
  on('demo-run', renderSummary);
  on('freshness', renderSummary);
  on('conn', () => { renderClockAndLink(); renderSummary(); });
}
