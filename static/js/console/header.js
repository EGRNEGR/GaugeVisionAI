// Шапка: сводка тревог, часы и смена, связь с сервером, звук, квитирование.
import { $, $$, api, toast, timeStr, dateStr, hmStr, durStr, shiftStart, shiftEnd } from './util.js';
import { state, on, camList, displayLevel, unackedByCam } from './store.js';
import { Sound, renderSoundButton } from './sound.js';
import { setJournalFilter, unackedRowCount } from './journal.js';

const TITLE = 'GaugeVision AI — пульт оператора';

function setCounter(id, n) {
  const el = $(`#${id}`);
  el.textContent = String(n);
  el.closest('.counter').dataset.active = String(n > 0);
}

export function renderSummary() {
  const cams = camList();
  let alarm = 0, warn = 0, link = 0;
  for (const c of cams) {
    const lv = displayLevel(c);
    if (lv === 'alert') alarm++;
    if (lv === 'warning') warn++;
    if (!state.connected || c.status !== 'online') link++;
  }
  const unack = unackedByCam();
  const unackAlert = Array.from(unack.values()).includes('alert');
  setCounter('cAlarm', alarm);
  setCounter('cWarn', warn);
  setCounter('cUnack', unackedRowCount());
  setCounter('cLink', link);
  const ack = $('#btnAck');
  ack.disabled = unack.size === 0;
  ack.classList.toggle('warn-only', unack.size > 0 && !unackAlert);
  Sound.setMode(unackAlert ? 'alert' : unack.size ? 'warning' : 'none');
  document.title = alarm || warn ? `(${alarm + warn}) ${alarm ? 'АВАРИЯ' : 'ПРЕДУПР.'} — ${TITLE}` : TITLE;
}

function renderClock() {
  const now = new Date();
  $('#clockT').textContent = timeStr(now);
  $('#clockD').textContent = dateStr(now);
  const s = shiftStart(now);
  $('#shiftLbl').textContent = `Смена ${hmStr(s)}–${hmStr(shiftEnd(s))}`;
  const cell = $('#linkCell');
  cell.dataset.state = state.connected ? 'up' : 'down';
  $('#linkText').textContent = state.connected
    ? 'Сервер на связи'
    : `Нет связи с сервером${state.downSince ? `, ${durStr((Date.now() - state.downSince) / 1000)}` : ''}`;
}

async function acknowledge() {
  const btn = $('#btnAck');
  btn.disabled = true;
  try {
    await api('/api/alarms/ack', { method: 'POST' });
  } catch (e) {
    toast(`Квитирование не прошло: ${e.message}`, 'err');
    renderSummary();
  }
}

export function initHeader() {
  $('#btnAck').addEventListener('click', acknowledge);
  $('#btnSound').addEventListener('click', () => { Sound.toggle(); renderSummary(); });
  $$('.counter').forEach((b) => b.addEventListener('click', () => setJournalFilter(b.dataset.filter)));
  renderSoundButton();
  renderClock();
  setInterval(renderClock, 1000);
  on('reading', renderSummary);
  on('status', renderSummary);
  on('cams', renderSummary);
  on('events', renderSummary);
  on('conn', () => { renderClock(); renderSummary(); });
}
