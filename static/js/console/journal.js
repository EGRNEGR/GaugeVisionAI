// Журнал событий: срабатывания уставок, связь с камерами, действия операторов.
import { $, $$, esc, timeStr, dateStr, sameDay, plural, LEVEL_RANK, LEVEL_TAG } from './util.js';
import { state, on, eventsSorted, select } from './store.js';
import { openStop, evText } from './viewer.js';

const list = $('#jList');
const CHATTER_GAP_MS = 60000;   // соседние переходы ближе минуты — одна серия
const CHATTER_MIN = 3;
const MAX_ROWS = 300;
let level = 'all';

const LINK_TEXT = { online: 'Камера в сети', reconnecting: 'Потеря кадров, переподключение', offline: 'Камера офлайн' };
const FIELD_TEXT = {
  name: 'наименование', type: 'тип источника', source_url: 'адрес потока', gauge_type: 'тип прибора',
  unit: 'единица измерения', calibration: 'калибровка и ROI', thresholds: 'уставки',
};

function matches(ev) {
  if (level === 'alert' && !(ev.kind === 'alarm' && ev.level === 'alert')) return false;
  if (level === 'warning' && !(ev.kind === 'alarm' && ev.level === 'warning')) return false;
  if (level === 'link' && ev.kind !== 'link') return false;
  if (level === 'action' && ev.kind !== 'config' && ev.kind !== 'ack') return false;
  if ($('#jUnack').checked && ev.acked) return false;
  if ($('#jMine').checked && ev.cam_id !== state.selectedId) return false;
  return true;
}

/** Серии дребезга: частые переходы одного прибора сворачиваются в одну строку. */
function group(events) {
  const out = [];
  const open = new Map();   // camId -> текущая серия
  for (const ev of events) {
    if (ev.kind !== 'alarm') { out.push({ ev, items: [ev] }); continue; }
    const g = open.get(ev.cam_id);
    const t = Date.parse(ev.ts);
    if (g && g.oldest - t <= CHATTER_GAP_MS) {
      g.items.push(ev);
      g.oldest = t;
      continue;
    }
    const ng = { ev, items: [ev], oldest: t };
    open.set(ev.cam_id, ng);
    out.push(ng);
  }
  const rows = [];
  for (const g of out) {
    if (g.items.length >= CHATTER_MIN) rows.push(g);
    else for (const ev of g.items) rows.push({ ev, items: [ev] });
  }
  return rows;
}

function tagFor(ev, worst) {
  if (ev.kind === 'alarm') {
    const lv = worst || ev.level;
    return { level: lv, text: `${LEVEL_TAG[lv]}${ev.setpoint && lv === ev.level ? ` ${ev.setpoint}` : ''}` };
  }
  if (ev.kind === 'link') return { level: ev.text === 'online' ? 'info' : 'stale', text: 'СВЯЗЬ' };
  if (ev.kind === 'ack') return { level: 'info', text: 'КВИТИР.' };
  return { level: 'info', text: 'НАСТРОЙКА' };
}

function whatFor(ev) {
  const cam = state.cams.get(ev.cam_id);
  if (ev.kind === 'alarm') return evText(ev, cam);
  if (ev.kind === 'link') return LINK_TEXT[ev.text] || ev.text;
  if (ev.kind === 'ack') return `Квитировано срабатываний: ${Math.round(ev.value || 0)}`;
  if (ev.text === 'added') return 'Прибор добавлен';
  if (ev.text === 'deleted') return 'Прибор удалён';
  return `Изменено: ${ev.text.split(',').map((f) => FIELD_TEXT[f] || f).join(', ')}`;
}

function rowHtml(g) {
  const ev = g.ev;
  const d = new Date(ev.ts);
  const today = sameDay(d, new Date());
  const series = g.items.length > 1;
  const worst = series ? g.items.reduce((a, e) => (LEVEL_RANK[e.level] > LEVEL_RANK[a] ? e.level : a), 'normal') : null;
  const acked = g.items.every((e) => e.acked);
  const tag = tagFor(ev, worst);
  const who = ev.kind === 'ack' ? `Оператор ${ev.text}` : (ev.cam_name || '—');
  let what = whatFor(ev);
  if (series) {
    const secs = Math.round((Date.parse(g.items[0].ts) - Date.parse(g.items[g.items.length - 1].ts)) / 1000);
    const n = g.items.length;
    what = `Дребезг: ${n} ${plural(n, 'переход', 'перехода', 'переходов')} за ${secs} с, последний — ${what}`;
  }
  const framed = g.items.find((e) => e.has_frame);
  const current = state.stop && g.items.some((e) => e.id === state.stop.eventId);
  return `<li class="ev" data-ev="${(framed || ev).id}" data-cam="${esc(ev.cam_id || '')}" data-acked="${acked}" aria-current="${!!current}" tabindex="0">
    <span class="time">${timeStr(d)}${today ? '' : `<small>${dateStr(d).slice(0, 5)}</small>`}</span>
    <span class="tag" data-level="${tag.level}" data-unack="${!acked}">${tag.text}</span>
    <span class="who">${esc(who)}</span>
    ${framed ? `<button class="thumb" data-frame="${framed.id}" title="Открыть стоп-кадр в окне видео"><img src="/api/events/${framed.id}/frame.jpg" alt="Стоп-кадр ${timeStr(new Date(framed.ts))}" loading="lazy"></button>` : '<span class="nothumb"></span>'}
    <span class="what" title="${esc(what)}">${esc(what)}</span>
  </li>`;
}

export function renderJournal() {
  const all = eventsSorted();
  const esc2 = all.filter((e) => e.kind === 'alarm' && e.level !== 'normal');
  $('#jcAlert').textContent = String(esc2.filter((e) => e.level === 'alert').length);
  $('#jcWarn').textContent = String(esc2.filter((e) => e.level === 'warning').length);
  const rows = group(all.filter(matches)).slice(0, MAX_ROWS);
  $('#jCount').textContent = String(rows.length);
  if (!rows.length) {
    list.innerHTML = `<li class="j-empty">${all.length ? 'Под выбранный фильтр событий нет.' : 'Событий за время работы сервера пока нет. Здесь появятся срабатывания уставок, потери связи и действия операторов.'}</li>`;
    return;
  }
  const top = list.scrollTop;
  list.innerHTML = rows.map(rowHtml).join('');
  list.scrollTop = top;
}

function activate(li) {
  const ev = state.events.get(Number(li.dataset.ev));
  if (!ev) return;
  if (ev.has_frame) openStop(ev.id);
  else if (ev.cam_id && state.cams.has(ev.cam_id)) select(ev.cam_id);
}

/** Строк под фильтром «Неквитированные» — столько же покажет счётчик в шапке. */
export function unackedRowCount() {
  return group(eventsSorted().filter((e) => e.kind === 'alarm' && !e.acked)).length;
}

export function setJournalFilter(f) {
  if (f === 'unack') {
    $('#jUnack').checked = true;
    f = 'all';
  } else if (f === 'link' || f === 'alert' || f === 'warning') {
    $('#jUnack').checked = false;
  }
  level = f;
  $$('#jLevels [data-f]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.f === level)));
  renderJournal();
}

export function initJournal() {
  $$('#jLevels [data-f]').forEach((b) => b.addEventListener('click', () => setJournalFilter(b.dataset.f)));
  $('#jUnack').addEventListener('change', renderJournal);
  $('#jMine').addEventListener('change', renderJournal);
  list.addEventListener('click', (e) => {
    const li = e.target.closest('.ev');
    if (li) activate(li);
  });
  list.addEventListener('keydown', (e) => {
    const li = e.target.closest('.ev');
    if (!li) return;
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(li); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const sib = e.key === 'ArrowDown' ? li.nextElementSibling : li.previousElementSibling;
      if (sib && sib.classList.contains('ev')) sib.focus();
    }
  });
  let pending = false;
  const later = () => { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; renderJournal(); }); };
  on('events', later);
  on('stop', later);
  on('select', () => { if ($('#jMine').checked) later(); });
  setInterval(later, 60000);   // смена суток в метках времени
}
