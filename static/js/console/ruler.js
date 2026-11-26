// Линейка уставок: шкала прибора Vmin…Vmax, пятизонная модель ISA-18.2 (LL / L / НОРМА / H / HH),
// читаемая полоса 8–10 px, все четыре порога без обрезки и наложений, указатель текущего значения.
import { num, fmt, fmtRulerVal, SETPOINT_KEYS, SETPOINT_CODE } from './util.js';

export function scaleOf(calibration) {
  const c = calibration || {};
  const a = num(c.v_min) ?? 0;
  const b = num(c.v_max) ?? 10;
  return { lo: Math.min(a, b), hi: Math.max(a, b) };
}

export function zonesOf(thresholds, lo, hi) {
  const t = thresholds || {};
  const lowerOff = t.lower_enabled === false;
  const LL = lowerOff ? null : num(t.ll_alert);
  const L = lowerOff ? null : num(t.l_warn);
  const H = num(t.h_warn);
  const HH = num(t.hh_alert);
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

function spreadPositions(items, minGap = 20, minX = 9, maxX = 91) {
  const arr = items.map((it) => ({ ...it, x: Math.max(minX, Math.min(maxX, it.rawX)) }));
  arr.sort((a, b) => a.x - b.x);
  for (let i = 1; i < arr.length; i++) {
    if (arr[i].x - arr[i - 1].x < minGap) {
      arr[i].x = arr[i - 1].x + minGap;
    }
  }
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i].x > maxX) arr[i].x = maxX;
    if (i > 0 && arr[i].x - arr[i - 1].x < minGap) {
      arr[i - 1].x = Math.max(minX, arr[i].x - minGap);
    }
  }
  return arr;
}

export function renderRuler(el, { calibration, thresholds, value, level, big = false, showScaleLabels = false, decimals = 2 }) {
  if (!el) return;
  const { lo, hi } = scaleOf(calibration);
  const t = thresholds || {};
  const lowerOff = t.lower_enabled === false;
  const sig = JSON.stringify([lo, hi, t, big, showScaleLabels, decimals]);

  if (el.dataset.sig !== sig) {
    el.dataset.sig = sig;
    el.className = `ruler${big ? ' big' : ''}${showScaleLabels ? ' with-scale' : ''}`;
    let html = '<div class="ruler-bar"><div class="track"></div>';
    for (const z of zonesOf(t, lo, hi)) {
      html += `<div class="zone" data-level="${z.level}" style="left:${pct(z.from, lo, hi)}%;width:${pct(z.to, lo, hi) - pct(z.from, lo, hi)}%"></div>`;
    }

    const spChips = [];
    const bigRow0 = [];
    const bigRow1 = [];

    for (const k of SETPOINT_KEYS) {
      if (lowerOff && (k === 'll_alert' || k === 'l_warn')) continue;
      const v = num(t[k]);
      if (v === null || v < lo || v > hi) continue;
      const kind = (k === 'll_alert' || k === 'hh_alert') ? 'alert' : 'warning';
      const pos = pct(v, lo, hi);
      html += `<div class="sp" data-kind="${kind}" style="left:${pos}%"></div>`;
      if (big) {
        const entry = { key: k, kind, rawX: pos, val: v };
        if (k === 'll_alert' || k === 'hh_alert') bigRow0.push(entry);
        else bigRow1.push(entry);
      } else if (showScaleLabels) {
        spChips.push(`<span class="sp-chip" data-sp="${SETPOINT_CODE[k]}" data-kind="${kind}"><b>${SETPOINT_CODE[k]}</b>${fmtRulerVal(v, decimals)}</span>`);
      }
    }

    if (big) {
      for (const item of spreadPositions(bigRow0, 22, 10, 90)) {
        html += `<div class="sp-lbl" data-kind="${item.kind}" style="left:${item.x}%;top:1.3rem"><b>${SETPOINT_CODE[item.key]}</b>${fmt(item.val, decimals)}</div>`;
      }
      for (const item of spreadPositions(bigRow1, 22, 10, 90)) {
        html += `<div class="sp-lbl" data-kind="${item.kind}" style="left:${item.x}%;top:2rem"><b>${SETPOINT_CODE[item.key]}</b>${fmt(item.val, decimals)}</div>`;
      }
      html += `<div class="end-lbl" style="left:0;top:0">${fmt(lo, decimals)}</div>`;
      html += `<div class="end-lbl" style="right:0;top:0">${fmt(hi, decimals)}</div>`;
    }
    html += '<div class="ptr"></div></div>';

    if (showScaleLabels && !big) {
      html += `<div class="ruler-legend mono" title="Шкала ${fmt(lo, decimals)}…${fmt(hi, decimals)}">${spChips.join('')}</div>`;
    }

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
