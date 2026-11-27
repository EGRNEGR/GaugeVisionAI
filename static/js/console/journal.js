// Вкладка «События»: активные аварии/предупреждения сверху, хронология ниже,
// адресное идемпотентное квитирование POST /api/events/{id}/ack и просмотр стоп-кадра.
import { $, $$, esc, api, toast, fmt, decimalsFor, timeStr, dateStr, sameDay, LEVEL_TAG, evText } from './util.js';
import { state, on, emit, camList, evaluateInstrument, eventsSorted } from './store.js';
import { jumpToInstrument } from './instruments.js';

const listEl = $('#jList');
const activeBody = $('#activeAlarmsBody');
let filterKind = 'all';
let filterCam = 'all';
let snapDialogEventId = null;

const LINK_TEXT = {
  online: 'Камера в сети — кадры поступают',
  reconnecting: 'Поток кадров прерван — ожидание восстановления',
  offline: 'Камера отключена (офлайн)',
};
// Прогнозные события (app/prediction_events.py) и сопровождение приборов щита (Multi-Gauge)
const PREDICTION_TEXT = {
  cleared: 'Прогноз снят: тренд больше не ведёт к аварийной уставке',
  realized: 'Прогноз подтвердился: уставка пробита, дальше — по журналу тревог',
  withdrawn: 'Прогноз отозван: нет достоверного ряда (обрыв, отказ CV или смена калибровки)',
};
const INSTRUMENT_TEXT = {
  track_lost: 'Циферблат потерян в кадре — показания прибора не выдаются',
  track_ambiguous: 'Положение циферблата неоднозначно — показания прибора не выдаются',
  reacquired: 'Циферблат снова найден — показания восстановлены',
  added: 'Прибор щита зарегистрирован',
  removed: 'Прибор щита удалён, его слот Modbus освобождён',
};
const FIELD_TEXT = {
  name: 'наименование',
  type: 'тип источника',
  source_url: 'адрес потока',
  gauge_type: 'тип прибора',
  unit: 'единица измерения',
  calibration: 'калибровка шкалы и ROI',
  thresholds: 'границы зон (уставки)',
};

export function unackedCount() {
  let n = 0;
  for (const ev of state.events.values()) {
    if (ev.kind === 'alarm' && !ev.acked) n++;
  }
  return n;
}

export async function acknowledgeEvent(evId) {
  try {
    const res = await api(`/api/events/${evId}/ack`, { method: 'POST' });
    if (res && res.event) {
      state.events.set(res.event.id, res.event);
    }
    emit('events');
    toast(res.already_acked
      ? `Событие №${evId} уже было квитировано ранее`
      : `Событие №${evId} квитировано (активная зона сохраняется до возврата в норму)`);
    return res;
  } catch (e) {
    toast(`Ошибка квитирования: ${e.message}`, 'err');
    return null;
  }
}

export async function acknowledgeAll() {
  try {
    const res = await api('/api/alarms/ack', { method: 'POST', body: {} });
    const count = (res?.ids || []).length;
    toast(count > 0 ? `Квитировано событий: ${count}` : 'Все активные события уже квитированы');
  } catch (e) {
    toast(`Квитирование не выполнено: ${e.message}`, 'err');
  }
}

export function openSnapshotDialog(evId) {
  const ev = state.events.get(evId);
  if (!ev || !ev.has_frame) return;
  snapDialogEventId = evId;
  const cam = state.cams.get(ev.cam_id);
  $('#snapDlgTitle').textContent = `Стоп-кадр события №${ev.id} — ${ev.cam_name || ''}`;
  $('#snapDlgMeta').textContent = `${timeStr(new Date(ev.ts))} — ${evText(ev, cam)}`;
  $('#snapDlgImg').src = `/api/events/${ev.id}/frame.jpg`;
  const btnAck = $('#btnSnapDlgAck');
  btnAck.disabled = !!ev.acked;
  btnAck.textContent = ev.acked
    ? `Квитировано${ev.acked_ts ? ` в ${timeStr(new Date(ev.acked_ts))}` : ''}`
    : 'Квитировать это событие';
  $('#dlgSnapshot').showModal();
}

function populateCamFilter() {
  const sel = $('#jCamFilter');
  const cams = camList();
  const prev = filterCam;
  sel.innerHTML = '<option value="all">Все приборы (36)</option>'
    + cams.map((c) => `<option value="${esc(c.id)}">${esc(c.data.code ? `${c.data.code} — ${c.data.name}` : c.data.name)}</option>`).join('');
  sel.value = cams.some((c) => c.id === prev) ? prev : 'all';
  filterCam = sel.value;
}

function renderActiveSection() {
  const rows = [];
  // 1. Текущие активные отклонения и удержанные аварии по всем 36 позициям
  for (const cam of camList()) {
    const ev = evaluateInstrument(cam);
    const d = decimalsFor(cam.data);
    if (ev.tone === 'alert' || ev.tone === 'warning') {
      const unackEv = eventsSorted().find((e) => e.kind === 'alarm' && !e.acked && e.cam_id === cam.id);
      rows.push({
        level: ev.tone,
        title: `${cam.data.code || ''} ${cam.data.name}`,
        desc: `Текущая зона: ${ev.tone === 'alert' ? 'Авария' : 'Предупреждение'} — ${fmt(cam.reading?.value, d)} ${cam.data.unit}`,
        camId: cam.id,
        evObj: unackEv || null,
      });
    } else if (ev.tone === 'nodata' && (ev.prevAlarm === 'alert' || ev.prevAlarm === 'warning')) {
      const unackEv = eventsSorted().find((e) => e.kind === 'alarm' && !e.acked && e.cam_id === cam.id);
      rows.push({
        level: ev.prevAlarm,
        title: `${cam.data.code || ''} ${cam.data.name}`,
        desc: `Нет свежих данных — последнее известное состояние: ${ev.prevAlarm === 'alert' ? 'АВАРИЯ' : 'предупреждение'}`,
        camId: cam.id,
        evObj: unackEv || null,
      });
    }
  }
  // 2. Неквитированные прошлые срабатывания, даже если стрелка уже вернулась в норму
  const coveredEvIds = new Set(rows.map((r) => r.evObj?.id).filter(Boolean));
  for (const e of eventsSorted()) {
    if (e.kind === 'alarm' && !e.acked && !coveredEvIds.has(e.id)) {
      const cam = state.cams.get(e.cam_id);
      rows.push({
        level: e.level,
        title: `${cam?.data?.code || ''} ${e.cam_name || 'Прибор'}`,
        desc: `Неквитированное событие №${e.id} от ${timeStr(new Date(e.ts))}: ${evText(e, cam)}`,
        camId: e.cam_id,
        evObj: e,
      });
    }
  }

  $('#activeAlarmsCnt').textContent = String(rows.length);
  if (!rows.length) {
    activeBody.innerHTML = '<div class="j-empty">Активных аварий, предупреждений и неквитированных событий сейчас нет.</div>';
    return;
  }

  activeBody.innerHTML = rows.map((r) => `
    <div class="active-alarm-row" data-level="${esc(r.level)}">
      <span class="tag" data-level="${esc(r.level)}" data-unack="${!!r.evObj}">${LEVEL_TAG[r.level] || r.level}</span>
      <strong>${esc(r.title)}</strong>
      <span>${esc(r.desc)}</span>
      <span class="sp"></span>
      ${r.evObj && r.evObj.has_frame ? `<button class="btn sm" type="button" data-snap="${r.evObj.id}">Стоп-кадр</button>` : ''}
      ${r.evObj ? `<button class="btn sm ack" type="button" data-ack="${r.evObj.id}">Квитировать №${r.evObj.id}</button>` : '<span class="hint">Ознакомление подтверждено</span>'}
      ${r.camId ? `<button class="btn sm" type="button" data-goto="${esc(r.camId)}">К прибору</button>` : ''}
    </div>`).join('');

  $$('[data-ack]', activeBody).forEach((b) => b.addEventListener('click', () => acknowledgeEvent(Number(b.dataset.ack))));
  $$('[data-snap]', activeBody).forEach((b) => b.addEventListener('click', () => openSnapshotDialog(Number(b.dataset.snap))));
  $$('[data-goto]', activeBody).forEach((b) => b.addEventListener('click', () => jumpToInstrument(b.dataset.goto)));
}

function matchesEvent(ev) {
  if (filterCam !== 'all' && ev.cam_id !== filterCam) return false;
  if ($('#jUnack').checked && ev.acked) return false;
  if (filterKind === 'alert') return ev.kind === 'alarm' && ev.level === 'alert';
  if (filterKind === 'warning') return ev.kind === 'alarm' && ev.level === 'warning';
  if (filterKind === 'return') return ev.kind === 'alarm' && ev.level === 'normal';
  if (filterKind === 'link') return ev.kind === 'link';
  if (filterKind === 'action') return ev.kind === 'ack' || ev.kind === 'config';
  if (filterKind === 'prediction') return ev.kind === 'prediction';
  return true;
}

function tagInfo(ev) {
  if (ev.kind === 'alarm') {
    if (ev.level === 'normal') return { level: 'normal', text: 'ВОЗВРАТ В НОРМУ' };
    return { level: ev.level, text: `${LEVEL_TAG[ev.level]}${ev.setpoint ? ` ${ev.setpoint}` : ''}` };
  }
  if (ev.kind === 'link') return { level: ev.text === 'online' ? 'info' : 'stale', text: 'СВЯЗЬ' };
  if (ev.kind === 'ack') return { level: 'info', text: 'КВИТИРОВАНИЕ' };
  if (ev.kind === 'prediction') return { level: ev.text === 'imminent' ? 'warning' : 'info', text: 'ПРОГНОЗ' };
  if (ev.kind === 'instrument') {
    const bad = ev.text === 'track_lost' || ev.text === 'track_ambiguous';
    return { level: bad ? 'stale' : 'info', text: bad ? 'СОПРОВОЖДЕНИЕ' : 'ЩИТ' };
  }
  return { level: 'info', text: 'НАСТРОЙКА' };
}

function describeEvent(ev) {
  const cam = state.cams.get(ev.cam_id);
  if (ev.kind === 'alarm') return evText(ev, cam);
  if (ev.kind === 'link') return LINK_TEXT[ev.text] || ev.text;
  if (ev.kind === 'ack') {
    if (ev.ref_event_id) return `Квитировано событие №${ev.ref_event_id} (оператор ${ev.text || 'локальный'})`;
    return `Квитировано событий: ${Math.round(ev.value || 0)} (оператор ${ev.text || 'локальный'})`;
  }
  if (ev.kind === 'prediction') {
    if (ev.text !== 'imminent') return PREDICTION_TEXT[ev.text] || ev.text;
    const sp = ev.setpoint ? `уставки ${ev.setpoint}` : 'аварийной уставки';
    const spv = ev.setpoint_value != null ? ` (${String(ev.setpoint_value).replace('.', ',')})` : '';
    return ev.value != null
      ? `Прогноз: достижение ${sp}${spv} примерно через ${String(ev.value).replace('.', ',')} мин`
      : `Прогноз: высокая вероятность достижения ${sp}${spv} на горизонте 60 мин`;
  }
  if (ev.kind === 'instrument') return INSTRUMENT_TEXT[ev.text] || ev.text;
  if (ev.text === 'added') return 'Прибор добавлен в конфигурацию';
  if (ev.text === 'deleted') return 'Прибор удалён';
  return `Сохранены параметры: ${String(ev.text || '').split(',').map((k) => FIELD_TEXT[k] || k).join(', ')}`;
}

export function renderJournal() {
  populateCamFilter();
  renderActiveSection();

  const all = eventsSorted();
  $('#jcAlert').textContent = String(all.filter((e) => e.kind === 'alarm' && e.level === 'alert').length);
  $('#jcWarn').textContent = String(all.filter((e) => e.kind === 'alarm' && e.level === 'warning').length);

  const filtered = all.filter(matchesEvent).slice(0, 300);
  $('#jCount').textContent = `${filtered.length} записей`;

  if (!filtered.length) {
    listEl.innerHTML = `<li class="j-empty">${all.length ? 'Под выбранный фильтр записей нет.' : 'Журнал текущего сеанса пуст. Срабатывания уставок, возвраты в норму, квитирования и события связи появятся здесь автоматически.'}</li>`;
    return;
  }

  const now = new Date();
  listEl.innerHTML = filtered.map((ev) => {
    const d = new Date(ev.ts);
    const today = sameDay(d, now);
    const tg = tagInfo(ev);
    const cam = state.cams.get(ev.cam_id);
    const who = cam ? `${cam.data.code ? `${cam.data.code} ` : ''}${cam.data.short_name || cam.data.name}` : (ev.cam_name || 'Система');
    const desc = describeEvent(ev);
    // потеря сопровождения прибора щита тоже требует квитирования (app/events.py, _ACK_TEXTS)
    const canAck = (ev.kind === 'alarm' && ev.level !== 'normal') || (ev.kind === 'instrument' && (ev.text === 'track_lost' || ev.text === 'track_ambiguous'));
    const ackMeta = canAck
      ? (ev.acked
        ? `<small>Оператор ознакомлен${ev.acked_ts ? ` в ${timeStr(new Date(ev.acked_ts))}` : ''}</small>`
        : '<small>Требуется квитирование оператором</small>')
      : '';
    const ackControl = canAck
      ? `<button class="btn sm ${ev.acked ? '' : 'ack'}" type="button" data-ev-ack="${ev.id}">${ev.acked ? 'Квитировано' : 'Квитировать'}</button>`
      : '';
    const snapControl = ev.has_frame
      ? `<button class="thumb" type="button" data-ev-snap="${ev.id}" title="Открыть стоп-кадр срабатывания"><img src="/api/events/${ev.id}/frame.jpg" alt="Стоп-кадр" loading="lazy"></button>`
      : '<span></span>';

    return `<li class="ev" data-id="${ev.id}">
      <span class="time">${timeStr(d)}${today ? '' : `<small>${dateStr(d)}</small>`}</span>
      <span class="tag" data-level="${tg.level}" data-unack="${!ev.acked}">${tg.text}</span>
      <span class="who" title="${esc(who)}">${esc(who)}</span>
      <span class="what">${esc(desc)}${ackMeta}</span>
      ${snapControl}
      <span class="foot">${ackControl}${ev.cam_id && state.cams.has(ev.cam_id) ? `<button class="btn sm" type="button" data-ev-cam="${esc(ev.cam_id)}">Прибор</button>` : ''}</span>
    </li>`;
  }).join('');

  $$('[data-ev-ack]', listEl).forEach((b) => b.addEventListener('click', () => acknowledgeEvent(Number(b.dataset.evAck))));
  $$('[data-ev-snap]', listEl).forEach((b) => b.addEventListener('click', () => openSnapshotDialog(Number(b.dataset.evSnap))));
  $$('[data-ev-cam]', listEl).forEach((b) => b.addEventListener('click', () => jumpToInstrument(b.dataset.evCam)));

  if (snapDialogEventId !== null && $('#dlgSnapshot').open) {
    const curEv = state.events.get(snapDialogEventId);
    if (curEv) {
      const btn = $('#btnSnapDlgAck');
      btn.disabled = !!curEv.acked;
      btn.textContent = curEv.acked ? `Квитировано в ${timeStr(new Date(curEv.acked_ts))}` : 'Квитировать это событие';
    }
  }
}

export function setJournalFilter(kind) {
  if (kind === 'unack') {
    $('#jUnack').checked = true;
    filterKind = 'all';
  } else {
    if (kind === 'alert' || kind === 'warning' || kind === 'link') $('#jUnack').checked = false;
    filterKind = kind;
  }
  $$('#jLevels [data-f]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.f === filterKind)));
  renderJournal();
}

export function initJournal() {
  $$('#jLevels [data-f]').forEach((b) => b.addEventListener('click', () => setJournalFilter(b.dataset.f)));
  $('#jCamFilter').addEventListener('change', (e) => { filterCam = e.target.value; renderJournal(); });
  $('#jUnack').addEventListener('change', renderJournal);
  $('#btnSnapDlgAck').addEventListener('click', () => {
    if (snapDialogEventId !== null) acknowledgeEvent(snapDialogEventId);
  });

  on('events', renderJournal);
  on('reading', () => { if (state.view === 'events') renderActiveSection(); });
  on('sim-tick', () => { if (state.view === 'events') renderActiveSection(); });
  on('status', () => { if (state.view === 'events') renderActiveSection(); });
  on('freshness', () => { if (state.view === 'events') renderActiveSection(); });
  on('cams', renderJournal);
  on('view', (v) => { if (v === 'events') renderJournal(); });
}
