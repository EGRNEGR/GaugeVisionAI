// Canvas-графики пульта: спарклайн смены в строке прибора и тренд выбранного прибора.
import { css, num, fmt, hmStr, timeStr, SETPOINT_KEYS, SETPOINT_CODE } from './util.js';

let C = null;
function colors() {
  if (!C) {
    C = {
      text: css('--text'), text2: css('--text-2'), text3: css('--text-3'),
      line: css('--line'), line2: css('--line-2'), env: '#353e48',
      ok: css('--ok'), warn: css('--warn'), alarm: css('--alarm'), bg: css('--bg'),
    };
  }
  return C;
}
const levelColor = (lv, c) => (lv === 'alert' ? c.alarm : lv === 'warning' ? c.warn : c.text2);
const spColor = (k, c) => (k === 'll_alert' || k === 'hh_alert' ? c.alarm : c.warn);

/** Canvas под размер CSS-бокса с учётом плотности пикселей. */
function prep(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return null;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

/** Диапазон оси Y: данные плюс ближайшие уставки снизу и сверху. */
function yRange(points, thresholds, minSpan) {
  let lo = Infinity, hi = -Infinity;
  for (const p of points) { lo = Math.min(lo, p.min); hi = Math.max(hi, p.max); }
  if (!Number.isFinite(lo)) return null;
  const sps = SETPOINT_KEYS.map((k) => num((thresholds || {})[k])).filter((v) => v !== null);
  const below = sps.filter((v) => v <= lo).sort((a, b) => b - a)[0];
  const above = sps.filter((v) => v >= hi).sort((a, b) => a - b)[0];
  if (below !== undefined && lo - below < (hi - lo + minSpan) * 3) lo = below;
  if (above !== undefined && above - hi < (hi - lo + minSpan) * 3) hi = above;
  if (hi - lo < minSpan) { const m = (hi + lo) / 2; lo = m - minSpan / 2; hi = m + minSpan / 2; }
  const pad = (hi - lo) * 0.08;
  return { lo: lo - pad, hi: hi + pad };
}

function niceStep(span, target) {
  const raw = span / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

function drawLevelLine(ctx, pts, X, Y, c) {
  ctx.lineWidth = 1.5;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    ctx.strokeStyle = levelColor(b.level, c);
    ctx.beginPath();
    ctx.moveTo(X(a.t), Y(a.avg));
    ctx.lineTo(X(b.t), Y(b.avg));
    ctx.stroke();
  }
}

/** Спарклайн смены: огибающая, среднее по уровням, уставки в диапазоне. */
export function drawSpark(canvas, series, cam, x0, x1) {
  const p = prep(canvas);
  if (!p) return;
  const { ctx, w, h } = p;
  const c = colors();
  const pts = series ? series.points : [];
  ctx.fillStyle = c.line;
  ctx.fillRect(0, h - 1, w, 1);
  if (!pts.length) return;
  const cal = cam.data.calibration || {};
  const span = Math.abs((num(cal.v_max) ?? 10) - (num(cal.v_min) ?? 0)) || 10;
  const r = yRange(pts, null, span * 0.04);
  const X = (t) => ((t - x0) / (x1 - x0)) * (w - 3) + 1;
  const Y = (v) => h - 2 - ((v - r.lo) / (r.hi - r.lo)) * (h - 5);
  const th = cam.data.thresholds || {};
  ctx.setLineDash([2, 2]);
  ctx.lineWidth = 1;
  for (const k of SETPOINT_KEYS) {
    const v = num(th[k]);
    if (v === null || v < r.lo || v > r.hi) continue;
    ctx.strokeStyle = spColor(k, c);
    ctx.globalAlpha = 0.7;
    ctx.beginPath(); ctx.moveTo(0, Math.round(Y(v)) + 0.5); ctx.lineTo(w, Math.round(Y(v)) + 0.5); ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
  ctx.fillStyle = c.env;
  ctx.beginPath();
  pts.forEach((q, i) => (i ? ctx.lineTo(X(q.t), Y(q.max)) : ctx.moveTo(X(q.t), Y(q.max))));
  for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(X(pts[i].t), Y(pts[i].min));
  ctx.closePath();
  ctx.fill();
  drawLevelLine(ctx, pts, X, Y, c);
  const last = pts[pts.length - 1];
  ctx.fillStyle = levelColor(last.level, c);
  ctx.fillRect(X(last.t) - 1.5, Y(last.avg) - 1.5, 3, 3);
}

/**
 * Тренд выбранного прибора: оси, огибающая, среднее, уставки, «сейчас»,
 * метки срабатываний. Возвращает геометрию для подсказки и кликов по меткам.
 */
export function drawTrend(canvas, { series, cam, x0, x1, events, decimals }) {
  const p = prep(canvas);
  if (!p) return null;
  const { ctx, w, h } = p;
  const c = colors();
  const pad = { l: 56, r: 12, t: 10, b: 22 };
  const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
  const pts = series ? series.points.filter((q) => q.t >= x0 - series.stepMs && q.t <= x1) : [];
  const cal = cam.data.calibration || {};
  const span = Math.abs((num(cal.v_max) ?? 10) - (num(cal.v_min) ?? 0)) || 10;
  const th = cam.data.thresholds || {};
  const r = yRange(pts, th, span * 0.04) || { lo: num(cal.v_min) ?? 0, hi: num(cal.v_max) ?? 10 };
  const X = (t) => pad.l + ((t - x0) / (x1 - x0)) * pw;
  const Y = (v) => pad.t + ph - ((v - r.lo) / (r.hi - r.lo)) * ph;
  ctx.font = '12px "JetBrains Mono", Consolas, monospace';
  ctx.textBaseline = 'middle';

  // сетка Y
  const ys = niceStep(r.hi - r.lo, 5);
  ctx.lineWidth = 1;
  for (let v = Math.ceil(r.lo / ys) * ys; v <= r.hi; v += ys) {
    const y = Math.round(Y(v)) + 0.5;
    ctx.strokeStyle = c.line;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillStyle = c.text3;
    ctx.textAlign = 'right';
    ctx.fillText(fmt(v, Math.max(0, Math.min(decimals, -Math.floor(Math.log10(ys)) + 1))), pad.l - 6, y);
  }
  // сетка времени
  const spanMin = (x1 - x0) / 60000;
  const stepMin = spanMin <= 20 ? 2 : spanMin <= 70 ? 10 : 60;
  const t0 = new Date(x0); t0.setSeconds(0, 0);
  t0.setMinutes(Math.ceil(t0.getMinutes() / stepMin) * stepMin);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let t = t0.getTime(); t <= x1; t += stepMin * 60000) {
    const x = Math.round(X(t)) + 0.5;
    ctx.strokeStyle = c.line;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
    ctx.fillStyle = c.text3;
    ctx.fillText(hmStr(new Date(t)), x, pad.t + ph + 6);
  }
  ctx.strokeStyle = c.line2;
  ctx.strokeRect(pad.l + 0.5, pad.t + 0.5, pw - 1, ph - 1);

  // уставки
  ctx.save();
  ctx.beginPath(); ctx.rect(pad.l, pad.t, pw, ph); ctx.clip();
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  for (const k of SETPOINT_KEYS) {
    const v = num(th[k]);
    if (v === null || v < r.lo || v > r.hi) continue;
    const y = Math.round(Y(v)) + 0.5;
    ctx.strokeStyle = spColor(k, c);
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = spColor(k, c);
    ctx.fillText(`${SETPOINT_CODE[k]} ${fmt(v, decimals)}`, pad.l + 6, y - 2);
  }
  // огибающая и среднее
  if (pts.length) {
    ctx.fillStyle = c.env;
    ctx.beginPath();
    pts.forEach((q, i) => (i ? ctx.lineTo(X(q.t), Y(q.max)) : ctx.moveTo(X(q.t), Y(q.max))));
    for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(X(pts[i].t), Y(pts[i].min));
    ctx.closePath();
    ctx.fill();
    drawLevelLine(ctx, pts, X, Y, c);
  }
  // метки срабатываний
  const marks = [];
  for (const ev of events) {
    const t = Date.parse(ev.ts);
    if (t < x0 || t > x1) continue;
    const x = Math.round(X(t)) + 0.5;
    const up = ev.level !== 'normal';
    ctx.strokeStyle = up ? levelColor(ev.level, c) : c.text3;
    ctx.globalAlpha = up ? 0.9 : 0.6;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, up ? pad.t + ph : pad.t + 8); ctx.stroke();
    if (up) { ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(x - 3, pad.t, 6, 6); }
    ctx.globalAlpha = 1;
    marks.push({ x, ev });
  }
  // «сейчас»
  const now = Date.now();
  if (now >= x0 && now <= x1) {
    const x = Math.round(X(now)) + 0.5;
    ctx.strokeStyle = c.text2;
    ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.restore();
  if (!pts.length) {
    ctx.fillStyle = c.text3;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = '12px "IBM Plex Sans", "Segoe UI", sans-serif';
    ctx.fillText('В этом окне ещё нет достоверных отсчётов', pad.l + pw / 2, pad.t + ph / 2);
  }
  return { pad, pw, ph, X, Y, x0, x1, pts, marks };
}

/** Ближайшая корзина к x — для подсказки. */
export function pointAt(geo, x) {
  if (!geo || !geo.pts.length) return null;
  let best = null, bd = Infinity;
  for (const q of geo.pts) {
    const d = Math.abs(geo.X(q.t) - x);
    if (d < bd) { bd = d; best = q; }
  }
  return bd < 24 ? best : null;
}
export const tipText = (q, unit, d) => `${timeStr(new Date(q.t))}   ср ${fmt(q.avg, d)}   мин ${fmt(q.min, d)}   макс ${fmt(q.max, d)} ${unit}`;
