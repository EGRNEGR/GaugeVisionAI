// Общие утилиты пульта: DOM, API, русская числовая нотация, подписи состояний.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Число из поля ввода: принимает запятую, точку и настоящий минус; пусто -> null, ошибка -> NaN. */
export function parseNum(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim().replace(/\s/g, '').replace(',', '.').replace(/−/g, '-');
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}
export const num = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v))) ? null : Number(v);

const nfCache = new Map();
/** Русская нотация: запятая, неразрывный пробел в тысячах, настоящий минус U+2212. */
export function fmt(v, d = 2) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  let nf = nfCache.get(d);
  if (!nf) {
    nf = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
    nfCache.set(d, nf);
  }
  return nf.format(Number(v)).replace(/-/g, '−');
}

export const fmtInput = (v, d = 4) => (v === null || v === undefined || !Number.isFinite(Number(v))) ? '' : String(+Number(v).toFixed(d)).replace('.', ',');
export const fmtFixed = (v, d = 2) => (v === null || v === undefined || !Number.isFinite(Number(v))) ? '' : Number(v).toFixed(d).replace('.', ',').replace(/-/g, '−');

/** Компактное число для шкалы уставок на карточке (без лишних хвостовых нулей). */
export function fmtCompact(v, maxD = 2) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  const n = Number(v);
  const abs = Math.abs(n);
  const d = abs >= 100 || Number.isInteger(n) ? 0 : Math.min(maxD, abs >= 10 ? 1 : maxD);
  return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: d })
    .format(n)
    .replace(/-/g, '−');
}

/** Сверхкомпактное число для подписей LL/L/H/HH на карточке (без широких пробелов разрядов). */
export function fmtRulerVal(v, maxD = 2) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  const n = Number(v);
  const abs = Math.abs(n);
  const d = abs >= 100 || Number.isInteger(n) ? 0 : Math.min(maxD, abs >= 10 ? 1 : maxD);
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: d,
    useGrouping: false,
  })
    .format(n)
    .replace(/-/g, '−');
}

/** Скорость изменения параметра Δ/мин со знаком (+ / −). */
export function fmtRate(ratePerMin, decimals = 2) {
  if (ratePerMin === null || ratePerMin === undefined || !Number.isFinite(Number(ratePerMin))) return '—';
  const n = Number(ratePerMin);
  const d = Math.min(3, Math.max(1, decimals));
  const eps = 0.5 * (10 ** (-d));
  if (Math.abs(n) < eps) return `0,${'0'.repeat(Math.min(1, d))}/мин`;
  const absStr = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d }).format(Math.abs(n));
  return `${n > 0 ? '+' : '−'}${absStr}/мин`;
}

export function durShort(s) {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  s = Math.max(0, Math.floor(s));
  const p = (n) => String(n).padStart(2, '0');
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d} сут ${h} ч`;
  if (h) return `${h}:${p(m)} ч`;
  return `${m}:${p(s % 60)} мин`;
}

export function durStr(s) {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—';
  s = Math.max(0, Math.floor(s));
  const p = (n) => String(n).padStart(2, '0');
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d} сут ${h} ч`;
  if (h) return `${h} ч ${p(m)} мин`;
  if (m) return `${m} мин ${p(s % 60)} с`;
  return `${s} с`;
}

export function decimalsFor(camData) {
  if (camData && Number.isInteger(camData.decimals)) return camData.decimals;
  const c = (camData && camData.calibration) || {};
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

export function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const a = Math.abs(off);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

export const LEVEL_RANK = { normal: 0, warning: 1, alert: 2 };
export const LEVEL_TAG = { normal: 'НОРМА', warning: 'ПРЕДУПР.', alert: 'АВАРИЯ' };
export const LEVEL_FULL = { normal: 'Норма', warning: 'Предупреждение', alert: 'Авария' };
export const STATUS_TEXT = { online: 'В сети', reconnecting: 'Поток прерван', offline: 'Не подключена' };
export const SOURCE_TEXT = {
  device: 'Локальная камера сервера (USB)',
  rtsp: 'RTSP (IP-камера или NVR)',
  http_mjpeg: 'HTTP / MJPEG',
  phone_ws: 'Камера телефона (Android, WSS)',
  video_file: 'Локальный видеофайл (стенд)',
};
export const SOURCE_KIND_TEXT = {
  phone_cv: 'Камера телефона (CV)',
  camera_cv: 'Видеокамера (CV)',
  simulated: 'Симуляция',
};
export const PHONE_STAGE_TEXT = {
  waiting_phone: 'Ожидаем телефон',
  awaiting_permission: 'Разрешите доступ к камере',
  permission_denied: 'Доступ к камере отклонён',
  camera_error: 'Камера недоступна',
  no_reading_yet: 'Кадры поступают, показаний пока нет',
  reading_received: 'Показание получено',
  stream_interrupted: 'Поток прерван',
};
export const DIAL_SOURCE = {
  'yolo+ellipse': 'YOLOv8n + эллипс',
  yolo: 'YOLOv8n',
  ellipse: 'Контурный эллипс',
  opencv: 'HoughCircles',
  manual: 'Ручная ROI',
  frame: 'Весь кадр',
  none: '—',
};
export const GAUGE_SHORT = {
  pressure: 'Давление (манометр)',
  temperature: 'Температура (термометр)',
  draft: 'Тяга и разрежение (тягонапоромер)',
  level: 'Уровень (уровнемер)',
  electrical: 'Электрические щитовые приборы',
  flow: 'Расход (расходомер)',
};
export const SETPOINT_KEYS = ['ll_alert', 'l_warn', 'h_warn', 'hh_alert'];
export const SETPOINT_CODE = { ll_alert: 'LL', l_warn: 'L', h_warn: 'H', hh_alert: 'HH' };

export function crossed(value, thresholds) {
  const v = num(value);
  if (v === null || !thresholds) return null;
  const lowerOff = thresholds.lower_enabled === false;
  const LL = lowerOff ? null : num(thresholds.ll_alert);
  const L = lowerOff ? null : num(thresholds.l_warn);
  const H = num(thresholds.h_warn);
  const HH = num(thresholds.hh_alert);
  if (LL !== null && v <= LL) return 'LL';
  if (HH !== null && v >= HH) return 'HH';
  if (L !== null && v <= L) return 'L';
  if (H !== null && v >= H) return 'H';
  return null;
}

export function evText(ev, cam) {
  const d = cam ? decimalsFor(cam.data) : 2;
  const unit = ev.unit || (cam && cam.data && cam.data.unit) || '';
  if (ev.level === 'normal') {
    let base = `Возврат в норму: ${fmt(ev.value, d)} ${unit}`.trim();
    if (ev.ref_event_id) {
      const prevKind = ev.ref_level === 'alert' ? 'аварии' : 'предупреждения';
      const dur = ev.duration_s !== null && ev.duration_s !== undefined ? `, длительность ${durStr(ev.duration_s)}` : '';
      const when = ev.ref_ts ? ` от ${timeStr(new Date(ev.ref_ts))}` : '';
      base += ` (после ${prevKind} №${ev.ref_event_id}${when}${dur})`;
    }
    return base;
  }
  const sp = ev.setpoint && ev.setpoint_value !== null && ev.setpoint_value !== undefined
    ? `, уставка ${ev.setpoint} ${fmt(ev.setpoint_value, d)} ${unit}`.trimEnd()
    : '';
  const what = ev.level === 'alert' ? 'Авария' : 'Предупреждение';
  return `${what}${ev.setpoint ? ` (${ev.setpoint})` : ''}: ${fmt(ev.value, d)} ${unit}${sp}`;
}

export async function api(path, opts = {}) {
  const init = { method: 'GET', credentials: 'same-origin', headers: {}, ...opts };
  if (init.body && typeof init.body !== 'string') {
    init.body = JSON.stringify(init.body);
    init.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, init);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch (_) { /* пустой ответ */ }
  if (!res.ok) {
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('gv-auth-required'));
    }
    let msg = `Ошибка HTTP ${res.status}`;
    if (data && data.detail) {
      msg = Array.isArray(data.detail)
        ? data.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
        : String(data.detail);
    }
    throw new Error(msg);
  }
  return data;
}

export function toast(msg, kind = 'ok', ms = 4000) {
  const box = $('#toasts');
  if (!box) return;
  const el = document.createElement('div');
  el.className = 'toast';
  el.dataset.kind = kind;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

export function confirmDlg(title, text, okLabel = 'Подтвердить') {
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

export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
