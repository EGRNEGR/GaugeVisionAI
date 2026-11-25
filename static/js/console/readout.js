// Отсчёт под кадром: показание, линейка уставок и параметры распознавания.
import { $, esc, fmt, decimalsFor, timeStr, DIAL_SOURCE, STATUS_TEXT } from './util.js';
import { state, on, selected, displayLevel, unackedByCam } from './store.js';
import { renderRuler } from './ruler.js';
import { applyTag } from './instruments.js';

const MIN_CONF = 0.25;   // config.MIN_NEEDLE_CONFIDENCE — ниже отсчёт недостоверен
const METHOD = { hough: 'HoughLinesP', moment: 'Радиальный момент', 'hough+moment': 'Hough + момент', none: '—' };
const MASK = { blackhat: 'Black-Hat, тёмная стрелка', tophat: 'Top-Hat, светлая стрелка', saturation: 'по насыщенности, цветная стрелка' };

function kv(label, value, cls = '', title = '') {
  return `<div class="kv"${title ? ` title="${esc(title)}"` : ''}><dt>${label}</dt><dd class="${cls}">${value}</dd></div>`;
}

export function renderReadout() {
  const cam = selected();
  const main = $('#roMain');
  if (!cam) {
    $('#roValue').textContent = '—';
    $('#roUnit').textContent = '';
    $('#roTag').dataset.level = 'info';
    $('#roTag').textContent = '—';
    $('#roRuler').textContent = '';
    delete $('#roRuler').dataset.sig;
    $('#roGrid').textContent = '';
    return;
  }
  const r = cam.reading;
  const d = decimalsFor(cam.data);
  const lv = displayLevel(cam);
  main.dataset.level = lv;
  main.dataset.stale = String(lv === 'stale' || lv === 'hold');
  $('#roValue').textContent = fmt(r && r.value, d);
  $('#roUnit').textContent = cam.data.unit;
  applyTag($('#roTag'), cam, unackedByCam().has(cam.id));
  const rr = $('#roRuler');
  renderRuler(rr, {
    calibration: cam.data.calibration, thresholds: cam.data.thresholds, value: r && r.value,
    level: lv === 'stale' ? 'stale' : (r && r.level) || 'normal', big: true, decimals: d,
  });
  const st = cam.stream || {};
  const conf = r ? r.confidence : null;
  $('#roGrid').innerHTML = [
    kv('Сырое значение', r ? `${fmt(r.raw_value, d)}` : '—', '', 'Мгновенное значение кадра до сглаживания EMA'),
    kv('Угол стрелки θ', r && r.angle !== null && r.angle !== undefined ? `${fmt(r.angle, 2)}°` : '—'),
    kv('Уверенность', conf === null || conf === undefined ? '—' : fmt(conf, 2), conf !== null && conf < MIN_CONF ? 'alarm' : '', `Ниже ${fmt(MIN_CONF, 2)} отсчёт не записывается, удерживается последний достоверный`),
    kv('Циферблат', r ? esc(DIAL_SOURCE[r.dial_source] || r.dial_source || '—') : '—', r && !r.dial_found ? 'warn' : ''),
    (() => {
      const [algo, mask] = String((r && r.method) || 'none').split('/');
      return kv('Метод стрелки', esc(METHOD[algo] || algo), '', mask ? `Маска стрелки: ${MASK[mask] || mask}` : '');
    })(),
    kv('Конвейер', r ? `${fmt(r.process_ms, 1)} мс` : '—'),
    kv('Отсчёт', r ? timeStr(new Date(r.ts)) : '—', '', r && !r.valid && r.last_valid_ts ? `Последний достоверный: ${timeStr(new Date(r.last_valid_ts))}` : ''),
    kv('Захват', cam.status === 'online' ? `${fmt(st.fps, 1)} к/с` : esc(STATUS_TEXT[cam.status] || cam.status), cam.status !== 'online' ? 'alarm' : '', 'Кадров в секунду с камеры'),
  ].join('');
}

export function initReadout() {
  on('select', renderReadout);
  on('reading', (id) => { if (id === state.selectedId) renderReadout(); });
  on('status', (id) => { if (id === state.selectedId) renderReadout(); });
  on('cams', renderReadout);
  on('conn', renderReadout);
  on('events', renderReadout);
}
