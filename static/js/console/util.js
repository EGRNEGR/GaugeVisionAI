// Общие утилиты пульта: DOM, API, форматирование в русской нотации, смены.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Число из поля ввода: принимает и запятую, и точку; пусто — null. */
export function parseNum(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim().replace(/\s/g, '').replace(',', '.').replace('−', '-');
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}
export const num = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v))) ? null : Number(v);

const nfCache = new Map();
/** 4,392 — запятая, неразрывный пробел в тысячах, настоящий минус. */
export function fmt(v, d = 2) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  let nf = nfCache.get(d);
  if (!nf) {
    nf = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
    nfCache.set(d, nf);
  }
  return nf.format(Number(v)).replace('-', '−');
}
/** Значение для поля ввода: без группировки, с запятой. */
export const fmtInput = (v, d = 4) => (v === null || v === undefined) ? '' : String(+Number(v).toFixed(d)).replace('.', ',');
/** Значение для поля ввода с фиксированным числом знаков, как на шкале прибора: 1,00. */
export const fmtFixed = (v, d) => (v === null || v === undefined) ? '' : Number(v).toFixed(d).replace('.', ',').replace('-', '−');

/** Компактная длительность для таблиц: 2 сут 4 ч, 3:12 ч, 17:30 мин. */
export function durShort(s) {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  s = Math.max(0, Math.floor(s));
  const p = (n) => String(n).padStart(2, '0');
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d} сут ${h} ч`;
  if (h) return `${h}:${p(m)} ч`;
  return `${m}:${p(s % 60)} мин`;
}

/** Знаков после запятой под диапазон шкалы прибора. */
export function decimalsFor(cam) {
  const c = (cam && cam.calibration) || {};
  const span = Math.abs((num(c.v_max) ?? 10) - (num(c.v_min) ?? 0)) || 10;
  if (span <= 2.5) return 3;
  if (span <= 25) return 2;
  if (span <= 250) return 1;
  return 0;
}

const pad = (n) => String(n).padStart(2, '0');
export const timeStr = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
export const hmStr = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const dateStr = (d) => `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
export const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** Длительность: 3 ч 12 мин, 45 с, 2 сут 4 ч. */
export function durStr(s) {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d} сут ${h} ч`;
  if (h) return `${h} ч ${pad(m)} мин`;
  if (m) return `${m} мин ${pad(s % 60)} с`;
  return `${s} с`;
}

// --- Смены: две по 12 часов, 08:00 и 20:00 ---------------------------------
export const SHIFT_STARTS = [8, 20];
export function shiftStart(now = new Date()) {
  const d = new Date(now);
  const h = d.getHours();
  d.setMinutes(0, 0, 0);
  if (h >= SHIFT_STARTS[1]) d.setHours(SHIFT_STARTS[1]);
  else if (h >= SHIFT_STARTS[0]) d.setHours(SHIFT_STARTS[0]);
  else { d.setDate(d.getDate() - 1); d.setHours(SHIFT_STARTS[1]); }
  return d;
}
export const shiftEnd = (start) => new Date(start.getTime() + 12 * 3600 * 1000);
/** ISO 8601 с локальным часовым поясом — сервер принимает только время с поясом. */
export function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const a = Math.abs(off);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

// --- Уровни и подписи -------------------------------------------------------
export const LEVEL_RANK = { normal: 0, warning: 1, alert: 2 };
export const LEVEL_TAG = { normal: 'НОРМА', warning: 'ПРЕДУПР.', alert: 'АВАРИЯ' };
export const STATUS_TEXT = { online: 'В сети', reconnecting: 'Переподключение', offline: 'Офлайн' };
export const SOURCE_TEXT = { device: 'Локальная камера сервера (USB)', rtsp: 'RTSP — IP-камера или NVR', http_mjpeg: 'HTTP / MJPEG', phone_ws: 'Смартфон (WSS, по QR)' };
export const DIAL_SOURCE = {
  'yolo+ellipse': 'YOLO + эллипс', yolo: 'YOLO', ellipse: 'Эллипс', opencv: 'Hough', manual: 'Ручная ROI', frame: 'Весь кадр', none: '—',
};
export const GAUGE_SHORT = {
  pressure: 'Давление', temperature: 'Температура', draft: 'Тяга и разрежение',
  level: 'Уровень', electrical: 'Электрические величины', flow: 'Расход',
};
export const SETPOINT_KEYS = ['ll_alert', 'l_warn', 'h_warn', 'hh_alert'];
export const SETPOINT_CODE = { ll_alert: 'LL', l_warn: 'L', h_warn: 'H', hh_alert: 'HH' };

// --- API --------------------------------------------------------------------
export async function api(path, opts = {}) {
  const init = { method: 'GET', headers: {}, ...opts };
  if (init.body && typeof init.body !== 'string') {
    init.body = JSON.stringify(init.body);
    init.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, init);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch (_) { /* пустой ответ */ }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data && data.detail) {
      msg = Array.isArray(data.detail)
        ? data.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
        : data.detail;
    }
    throw new Error(msg);
  }
  return data;
}

export function toast(msg, kind = 'ok', ms = 4000) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.dataset.kind = kind;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

/** Подтверждение в диалоге пульта; true — оператор подтвердил. */
export function confirmDlg(title, text, okLabel = 'Удалить') {
  const dlg = $('#dlgConfirm');
  $('#confTitle').textContent = title;
  $('#confText').textContent = text;
  $('#confOk').textContent = okLabel;
  dlg.returnValue = '';
  dlg.showModal();
  return new Promise((resolve) => {
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true });
  });
}

/** Склонение по числу: plural(4, 'переход', 'перехода', 'переходов'). */
export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
