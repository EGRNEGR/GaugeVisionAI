// Графики пульта: полноразмерный Canvas-тренд (с обязательной отрисовкой уставок LL/L/H/HH,
// честными разрывами связи и отметкой пика) и векторный 15-минутный спарклайн карточки.
import { css, num, fmt, hmStr, timeStr, SETPOINT_KEYS, SETPOINT_CODE } from './util.js';

let C = null;
function colors() {
  if (!C) {
    C = {
      text: css('--text') || '#e1e5e9',
      text2: css('--text-2') || '#a9b2ba',
      text3: css('--text-3') || '#8d96a0',
      line: css('--line') || '#2a3037',
      line2: css('--line-2') || '#3a424b',
      env: 'rgba(169, 178, 186, 0.14)',
      ok: css('--ok') || '#52b073',
      warn: css('--warn') || '#f59e0b',
      alarm: css('--alarm') || '#ff5c62',
      bg: css('--bg') || '#0f1215',
    };
  }
  return C;
}
const levelColor = (lv, c) => (lv === 'alert' ? c.alarm : lv === 'warning' ? c.warn : c.text);
const spColor = (k, c) => (k === 'll_alert' || k === 'hh_alert' ? c.alarm : c.warn);

function prep(canvas) {
  if (!canvas) return null;
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

export function activeSetpoints(thresholds) {
  const th = thresholds || {};
  const lowerOff = th.lower_enabled === false;
  return SETPOINT_KEYS
    .filter((k) => !(lowerOff && (k === 'll_alert' || k === 'l_warn')))
    .map((k) => ({ key: k, val: num(th[k]) }))
    .filter((x) => x.val !== null);
}

function yRange(points, thresholds, cal, minSpan) {
  let lo = Infinity, hi = -Infinity;
  for (const p of points) {
    lo = Math.min(lo, p.min);
    hi = Math.max(hi, p.max);
  }
  const sps = activeSetpoints(thresholds);
  const scaleLo = Math.min(num(cal?.v_min) ?? 0, num(cal?.v_max) ?? 16);
  const scaleHi = Math.max(num(cal?.v_min) ?? 0, num(cal?.v_max) ?? 16);

  if (!Number.isFinite(lo)) {
    return { lo: scaleLo, hi: scaleHi };
  }

  // Всегда включаем верхние уставки H и HH, а нижние L и LL — если сигнал в нижней половине или включён каскад
  for (const { key, val } of sps) {
    if (key === 'h_warn' || key === 'hh_alert') {
      lo = Math.min(lo, val);
      hi = Math.max(hi, val);
    } else if (val >= lo - (scaleHi - scaleLo) * 0.38) {
      lo = Math.min(lo, val);
      hi = Math.max(hi, val);
    }
  }

  if (hi - lo < minSpan) {
    const m = (hi + lo) / 2;
    lo = m - minSpan / 2;
    hi = m + minSpan / 2;
  }
  const pad = (hi - lo) * 0.14;
  return { lo: lo - pad, hi: hi + pad };
}

function niceStep(span, target) {
  const raw = Math.max(1e-6, span / target);
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

function splitByGaps(pts, gapMs) {
  if (!pts.length) return [];
  const segs = [[pts[0]]];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].t - pts[i - 1].t > gapMs) {
      segs.push([pts[i]]);
    } else {
      segs[segs.length - 1].push(pts[i]);
    }
  }
  return segs;
}

function drawSegmentedTrend(ctx, segs, X, Y, c) {
  for (const seg of segs) {
    if (seg.length === 1) {
      const q = seg[0];
      ctx.fillStyle = levelColor(q.level, c);
      ctx.fillRect(X(q.t) - 2.5, Y(q.avg) - 2.5, 5, 5);
      continue;
    }
    ctx.fillStyle = c.env;
    ctx.beginPath();
    seg.forEach((q, i) => (i ? ctx.lineTo(X(q.t), Y(q.max)) : ctx.moveTo(X(q.t), Y(q.max))));
    for (let i = seg.length - 1; i >= 0; i--) ctx.lineTo(X(seg[i].t), Y(seg[i].min));
    ctx.closePath();
    ctx.fill();

    ctx.lineWidth = 2;
    for (let i = 1; i < seg.length; i++) {
      const a = seg[i - 1], b = seg[i];
      ctx.strokeStyle = levelColor(b.level, c);
      ctx.beginPath();
      ctx.moveTo(X(a.t), Y(a.avg));
      ctx.lineTo(X(b.t), Y(b.avg));
      ctx.stroke();
    }
    const last = seg[seg.length - 1];
    ctx.fillStyle = levelColor(last.level, c);
    ctx.fillRect(X(last.t) - 2.5, Y(last.avg) - 2.5, 5, 5);
  }
}

export function drawTrend(canvas, { series, cam, x0, x1, events = [], decimals = 2, maxGapMs = null }) {
  const p = prep(canvas);
  if (!p) return null;
  const { ctx, w, h } = p;
  const c = colors();
  const pad = { l: 56, r: 14, t: 14, b: 24 };
  const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
  if (pw <= 10 || ph <= 10) return null;

  const stepMs = (series && series.stepMs) || 1000;
  const pts = series ? series.points.filter((q) => q.t >= x0 - stepMs && q.t <= x1 + stepMs) : [];
  const cal = (cam && cam.data && cam.data.calibration) || cam?.calibration || {};
  const span = Math.abs((num(cal.v_max) ?? 16) - (num(cal.v_min) ?? 0)) || 16;
  const th = (cam && cam.data && cam.data.thresholds) || cam?.thresholds || {};
  const r = yRange(pts, th, cal, span * 0.06);
  const spanX = Math.max(1000, x1 - x0);
  const X = (t) => pad.l + ((t - x0) / spanX) * pw;
  const Y = (v) => pad.t + ph - ((v - r.lo) / ((r.hi - r.lo) || 1)) * ph;

  ctx.font = '11px "JetBrains Mono", Consolas, monospace';
  ctx.textBaseline = 'middle';

  const ys = niceStep(r.hi - r.lo, 5);
  ctx.lineWidth = 1;
  for (let v = Math.ceil(r.lo / ys) * ys; v <= r.hi + 1e-9; v += ys) {
    const y = Math.round(Y(v)) + 0.5;
    ctx.strokeStyle = c.line;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillStyle = c.text3;
    ctx.textAlign = 'right';
    ctx.fillText(fmt(v, Math.max(0, Math.min(decimals, -Math.floor(Math.log10(ys)) + 1))), pad.l - 6, y);
  }

  const spanSec = spanX / 1000;
  const stepSec = spanSec <= 90 ? 15 : spanSec <= 360 ? 60 : spanSec <= 1500 ? 180 : spanSec <= 4200 ? 600 : 3600;
  const firstTick = Math.ceil(x0 / (stepSec * 1000)) * (stepSec * 1000);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let t = firstTick; t <= x1; t += stepSec * 1000) {
    const x = Math.round(X(t)) + 0.5;
    ctx.strokeStyle = c.line;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
    ctx.fillStyle = c.text3;
    const d = new Date(t);
    ctx.fillText(spanSec <= 600 ? timeStr(d) : hmStr(d), x, pad.t + ph + 5);
  }

  ctx.strokeStyle = c.line2;
  ctx.strokeRect(pad.l + 0.5, pad.t + 0.5, pw - 1, ph - 1);

  ctx.save();
  ctx.beginPath(); ctx.rect(pad.l, pad.t, pw, ph); ctx.clip();

  // Горизонтальные пунктирные линии уставок LL / L / H / HH
  ctx.font = '700 10.5px "JetBrains Mono", Consolas, monospace';
  for (const { key, val } of activeSetpoints(th)) {
    if (val < r.lo || val > r.hi) continue;
    const y = Math.round(Y(val)) + 0.5;
    ctx.strokeStyle = spColor(key, c);
    ctx.lineWidth = 1.25;
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.setLineDash([]);

    const lbl = `${SETPOINT_CODE[key]} ${fmt(val, decimals)}`;
    const tw = ctx.measureText(lbl).width + 8;
    const ly = y < pad.t + 16 ? y + 9 : y - 9;
    ctx.fillStyle = 'rgba(15, 18, 21, 0.88)';
    ctx.fillRect(pad.l + 4, ly - 7, tw, 14);
    ctx.fillStyle = spColor(key, c);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(lbl, pad.l + 8, ly);
  }

  if (pts.length) {
    const gapLimit = maxGapMs || Math.max(6500, stepMs * 3.5);
    const segs = splitByGaps(pts, gapLimit);
    drawSegmentedTrend(ctx, segs, X, Y, c);

    // Явная подпись экстремума (пика) на интервале
    let peak = pts[0];
    for (const q of pts) {
      if (q.max > peak.max) peak = q;
    }
    const px = Math.min(w - pad.r - 46, Math.max(pad.l + 46, X(peak.t)));
    const py = Y(peak.max);
    const peakTxt = `пик ${fmt(peak.max, decimals)}`;
    ctx.font = '500 10.5px "JetBrains Mono", Consolas, monospace';
    const ptw = ctx.measureText(peakTxt).width + 8;
    const boxY = py > pad.t + 22 ? py - 18 : py + 6;
    ctx.fillStyle = 'rgba(22, 26, 30, 0.92)';
    ctx.strokeStyle = levelColor(peak.level, c);
    ctx.lineWidth = 1;
    ctx.fillRect(px - ptw / 2, boxY, ptw, 15);
    ctx.strokeRect(px - ptw / 2 + 0.5, boxY + 0.5, ptw - 1, 14);
    ctx.fillStyle = c.text;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(peakTxt, px, boxY + 7.5);
  }

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
  ctx.restore();

  if (!pts.length) {
    ctx.fillStyle = c.text3;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = '12px "IBM Plex Sans", "Segoe UI", sans-serif';
    ctx.fillText('В выбранном интервале ещё нет сохранённых достоверных отсчётов', pad.l + pw / 2, pad.t + ph / 2);
  }
  return { pad, pw, ph, X, Y, x0, x1, pts, marks };
}

/**
 * Быстрый векторный 15-минутный мини-спарклайн для каждой из 36 карточек с адаптивным
 * масштабированием по реальному размаху сигнала (без «сплющивания» в прямую линию).
 */
export function renderSparklineSvg(svgEl, telemetry) {
  if (!svgEl) return;
  const vals = telemetry.history || [];
  const midVal = vals.length ? vals[Math.floor(vals.length / 2)] : '';
  const sig = `${telemetry.status}|${vals.length}|${vals[0] ?? ''}|${midVal}|${vals[vals.length - 1] ?? ''}|${telemetry.setpoints.h}|${telemetry.setpoints.hh}|${telemetry.setpoints.l}|${telemetry.setpoints.ll}`;
  if (svgEl.dataset.sig === sig) return;
  svgEl.dataset.sig = sig;

  const W = 120, H = 26;
  svgEl.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svgEl.setAttribute('preserveAspectRatio', 'none');

  const gridBg = `<line x1="0" y1="6.5" x2="${W}" y2="6.5" stroke="rgba(255,255,255,0.06)" stroke-width="1" vector-effect="non-scaling-stroke"/>`
    + `<line x1="0" y1="19.5" x2="${W}" y2="19.5" stroke="rgba(255,255,255,0.06)" stroke-width="1" vector-effect="non-scaling-stroke"/>`;

  if (vals.length === 0) {
    // Честная пустая дорожка 15-мин спарклайна (например, камера К1-Р01 до поступления первого кадра)
    svgEl.innerHTML = `${gridBg}`
      + `<line x1="2" y1="${H / 2}" x2="${W - 2}" y2="${H / 2}" stroke="var(--text-3)" stroke-opacity="0.55" stroke-width="1.2" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"/>`
      + `<rect x="${W - 5}" y="${H / 2 - 2}" width="4" height="4" fill="var(--text-3)" fill-opacity="0.7"/>`;
    return;
  }

  const series = vals.length === 1 ? [vals[0], vals[0]] : vals;
  let lo = Math.min(...series);
  let hi = Math.max(...series);
  const rawSpan = hi - lo;
  const scaleSpan = Math.max(1e-4, (telemetry.scale.max - telemetry.scale.min) || 1);
  const { ll, l, h, hh } = telemetry.setpoints;

  // Включаем уставки в масштаб спарклайна только когда сигнал реально рядом с порогом или пересекает его,
  // чтобы штатные колебания не сплющивались в прямую линию.
  const proximity = rawSpan * 1.35;
  const isDeviating = telemetry.status === 'WARNING' || telemetry.status === 'CRITICAL';
  for (const sp of [ll, l, h, hh]) {
    if (sp === null) continue;
    const dist = sp < lo ? lo - sp : sp > hi ? sp - hi : 0;
    if (dist <= proximity || (isDeviating && dist <= rawSpan * 2.5)) {
      lo = Math.min(lo, sp);
      hi = Math.max(hi, sp);
    }
  }

  const minSpan = Math.max(1e-4, rawSpan > 0 ? rawSpan * 1.15 : scaleSpan * 0.015);
  if (hi - lo < minSpan) {
    const mid = (hi + lo) / 2;
    lo = mid - minSpan / 2;
    hi = mid + minSpan / 2;
  }
  const padY = (hi - lo) * 0.16;
  lo -= padY;
  hi += padY;

  const X = (i) => ((i / (series.length - 1)) * (W - 6) + 2).toFixed(1);
  const Y = (v) => (H - 3 - ((v - lo) / ((hi - lo) || 1)) * (H - 6)).toFixed(1);

  let html = gridBg;
  const drawRef = (spVal, stroke) => {
    if (spVal === null || spVal < lo || spVal > hi) return;
    const sy = Y(spVal);
    html += `<line x1="0" y1="${sy}" x2="${W}" y2="${sy}" stroke="${stroke}" stroke-opacity="0.6" stroke-width="1" stroke-dasharray="3 2" vector-effect="non-scaling-stroke"/>`;
  };
  drawRef(l, 'var(--warn)');
  drawRef(h, 'var(--warn)');
  drawRef(ll, 'var(--alarm)');
  drawRef(hh, 'var(--alarm)');

  const coords = series.map((v, i) => [X(i), Y(v)]);
  const pts = coords.map(([x, y]) => `${x},${y}`).join(' ');
  const strokeColor = telemetry.status === 'CRITICAL'
    ? '#ffffff'
    : telemetry.status === 'WARNING'
      ? '#ffd166'
      : telemetry.status === 'STALE'
        ? '#9aa4af'
        : '#7fc0f5';
  const fillColor = telemetry.status === 'CRITICAL'
    ? 'rgba(255,255,255,0.16)'
    : telemetry.status === 'WARNING'
      ? 'rgba(255,209,102,0.16)'
      : telemetry.status === 'STALE'
        ? 'rgba(154,164,175,0.10)'
        : 'rgba(127,192,245,0.14)';

  const firstX = coords[0][0];
  const lastX = coords[coords.length - 1][0];
  const lastY = coords[coords.length - 1][1];
  html += `<polygon points="${firstX},${H - 1} ${pts} ${lastX},${H - 1}" fill="${fillColor}"/>`;
  html += `<polyline points="${pts}" fill="none" stroke="${strokeColor}" stroke-width="1.65" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`;
  html += `<rect x="${(Number(lastX) - 2).toFixed(1)}" y="${(Number(lastY) - 2).toFixed(1)}" width="4" height="4" fill="${strokeColor}"/>`;
  svgEl.innerHTML = html;
}

export function pointAt(geo, x) {
  if (!geo || !geo.pts.length) return null;
  let best = null, bd = Infinity;
  for (const q of geo.pts) {
    const d = Math.abs(geo.X(q.t) - x);
    if (d < bd) { bd = d; best = q; }
  }
  return bd < 24 ? best : null;
}

export const tipText = (q, unit, d) => `${timeStr(new Date(q.t))} — знач. ${fmt(q.avg, d)} ${unit}`;
