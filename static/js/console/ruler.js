// Линейка уставок: шкала прибора Vmin…Vmax, зоны пятизонной модели, засечки
// LL / L / H / HH и указатель текущего значения. Одна линейка на весь пульт:
// в строке прибора, в отсчёте под кадром и в редакторе уставок.
import { num, fmt, SETPOINT_KEYS, SETPOINT_CODE } from './util.js';

export function scaleOf(calibration) {
  const c = calibration || {};
  const a = num(c.v_min) ?? 0;
  const b = num(c.v_max) ?? 10;
  return { lo: Math.min(a, b), hi: Math.max(a, b) };
}

/** Зоны (от, до, уровень) — так же, как сервер раскрашивает дугу шкалы. */
export function zonesOf(thresholds, lo, hi) {
  const t = thresholds || {};
  const LL = num(t.ll_alert), L = num(t.l_warn), H = num(t.h_warn), HH = num(t.hh_alert);
  const zones = [{ from: L ?? LL ?? lo, to: H ?? HH ?? hi, level: 'normal' }];
  if (LL !== null) zones.push({ from: lo, to: LL, level: 'alert' });
  if (L !== null) zones.push({ from: LL ?? lo, to: L, level: 'warning' });
  if (H !== null) zones.push({ from: H, to: HH ?? hi, level: 'warning' });
  if (HH !== null) zones.push({ from: HH, to: hi, level: 'alert' });
  return zones
    .map((z) => ({ ...z, from: Math.max(lo, Math.min(hi, z.from)), to: Math.max(lo, Math.min(hi, z.to)) }))
    .filter((z) => z.to > z.from);
}

const pct = (v, lo, hi) => Math.max(0, Math.min(100, ((v - lo) / ((hi - lo) || 1)) * 100));

/**
 * Рисует линейку в el. Перестраивает разметку только при смене шкалы
 * или уставок; при новом значении двигается один указатель.
 */
export function renderRuler(el, { calibration, thresholds, value, level, big = false, decimals = 2 }) {
  const { lo, hi } = scaleOf(calibration);
  const sig = JSON.stringify([lo, hi, thresholds, big, decimals]);
  if (el.dataset.sig !== sig) {
    el.dataset.sig = sig;
    el.className = `ruler${big ? ' big' : ''}`;
    const t = thresholds || {};
    let html = '<div class="track"></div>';
    for (const z of zonesOf(t, lo, hi)) {
      html += `<div class="zone" data-level="${z.level}" style="left:${pct(z.from, lo, hi)}%;width:${pct(z.to, lo, hi) - pct(z.from, lo, hi)}%"></div>`;
    }
    for (const k of SETPOINT_KEYS) {
      const v = num(t[k]);
      if (v === null || v < lo || v > hi) continue;
      html += `<div class="sp" style="left:${pct(v, lo, hi)}%"></div>`;
      if (big) {
        const row = k === 'll_alert' || k === 'hh_alert' ? 0 : 1;
        html += `<div class="sp-lbl" style="left:${pct(v, lo, hi)}%;top:${row ? 2.375 : 1.5}rem"><b>${SETPOINT_CODE[k]}</b>${fmt(v, decimals)}</div>`;
      }
    }
    if (big) {
      html += `<div class="end-lbl" style="left:0;top:2.375rem">${fmt(lo, decimals)}</div>`;
      html += `<div class="end-lbl" style="right:0;top:2.375rem">${fmt(hi, decimals)}</div>`;
    }
    html += '<div class="ptr"></div>';
    el.innerHTML = html;
    el.setAttribute('role', 'img');
  }
  el.dataset.level = level || 'normal';
  const ptr = el.querySelector('.ptr');
  const v = num(value);
  ptr.hidden = v === null;
  if (v !== null) ptr.style.left = `${pct(v, lo, hi)}%`;
  el.setAttribute('aria-label', v === null ? 'Нет значения' : `Значение ${fmt(v, decimals)} на шкале ${fmt(lo, decimals)}…${fmt(hi, decimals)}`);
}
