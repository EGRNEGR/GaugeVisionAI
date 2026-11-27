// Вкладка «Приборы и калибровка»: предзаполненный профиль МТП-160 (0–16 МПа),
// стоп-кадр, ручная/авто ROI, калибровка кликом по делениям ИЛИ по живой стрелке,
// настройка зон LL/L/H/HH с предпроверкой и сравнением «Сохранено / Черновик».
import { $, $$, esc, api, toast, confirmDlg, fmt, fmtInput, fmtFixed, parseNum, num, decimalsFor, DIAL_SOURCE, SOURCE_TEXT } from './util.js';
import { state, on, emit, camList, livePrimaryCam, isSimulated, setView, sourceIdOf, isSecondary } from './store.js';
import { renderRuler } from './ruler.js';
import { fillGaugeSelect, fillUnitSelect } from './devices.js';
import { jumpToInstrument } from './instruments.js';

const form = $('#calMasterForm');
const calMedia = $('#calMedia');
const calImg = $('#calFrameImg');
const calSvg = $('#calOverlaySvg');
const NS = 'http://www.w3.org/2000/svg';

let targetId = null;
let dirty = false;
let roiMode = 'auto';
let calDir = 'cw';
let pickMode = 'none'; // none | roi | theta_min | theta_max
let frozen = false;
let calTimer = null;
let calBlobUrl = null;
let calFrameWH = null;

function targetCam() {
  if (targetId && state.cams.has(targetId)) return state.cams.get(targetId);
  const live = livePrimaryCam();
  targetId = live ? live.id : null;
  return targetId ? state.cams.get(targetId) : null;
}

function populateSelector() {
  const q = $('#calSearch').value.trim().toLowerCase();
  const sel = $('#calSelect');
  const all = camList();
  const filtered = q
    ? all.filter((c) => `${c.data.code || ''} ${c.data.name || ''} ${c.data.group || ''}`.toLowerCase().includes(q))
    : all;
  const list = filtered.length ? filtered : all;
  const cur = targetCam();

  sel.innerHTML = list.map((c) => {
    const src = isSimulated(c) ? 'Симуляция' : 'Камера телефона';
    return `<option value="${esc(c.id)}">${esc(c.data.code ? `${c.data.code} — ` : '')}${esc(c.data.name)} [${src}]</option>`;
  }).join('');

  if (cur && list.some((c) => c.id === cur.id)) {
    sel.value = cur.id;
  } else if (list[0]) {
    targetId = list[0].id;
    sel.value = targetId;
  }
}

const EMPTY_IMG = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

function stopCalFrames(clearSrc = false) {
  clearTimeout(calTimer);
  calTimer = null;
  if (clearSrc) {
    calImg.dataset.empty = 'true';
    calImg.src = EMPTY_IMG;
    if (calBlobUrl) { URL.revokeObjectURL(calBlobUrl); calBlobUrl = null; }
  }
}

function syncCalFrames() {
  const cam = targetCam();
  if (state.view !== 'calibration' || frozen || !cam || isSimulated(cam)) {
    stopCalFrames(false);
    return;
  }
  if (calTimer !== null) return;
  const id = cam.id;

  const tick = async () => {
    if (state.view !== 'calibration' || frozen || targetId !== id) { stopCalFrames(false); return; }
    if ((cam.stream?.frames_total || 0) === 0 && cam.status !== 'online') {
      $('#calMediaEmpty').hidden = false;
      calTimer = setTimeout(tick, 900);
      return;
    }
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(sourceIdOf(cam))}/frame.jpg?overlay=0`, { cache: 'no-store' });
      if (res.ok) {
        const url = URL.createObjectURL(await res.blob());
        if (state.view !== 'calibration' || frozen || targetId !== id) { URL.revokeObjectURL(url); return; }
        const prev = calBlobUrl;
        calBlobUrl = url;
        calImg.dataset.empty = 'false';
        calImg.src = url;
        $('#calMediaEmpty').hidden = true;
        try { await calImg.decode(); } catch (_) { /* ok */ }
        if (prev) URL.revokeObjectURL(prev);
        renderCalOverlay();
      }
    } catch (_) { /* повтор */ }
    calTimer = setTimeout(tick, 350);
  };
  tick();
}

function syncUnitLabels(unitStr) {
  $$('[data-unit-lbl]', form).forEach((el) => { el.textContent = unitStr || 'МПа'; });
}

function fillFormFromCam(force = false) {
  populateSelector();
  const cam = targetCam();
  if (!cam) return;

  const sim = isSimulated(cam);
  $('#calSimGuard').hidden = !sim;
  form.hidden = sim;
  if (sim) {
    stopCalFrames(true);
    return;
  }

  if (!force && dirty) {
    updateLiveReadout();
    return;
  }

  dirty = false;
  $('#calSaveStatus').hidden = true;
  clearErrors();

  fillGaugeSelect($('#calGaugeType'));
  form.name.value = cam.data.name || '';
  $('#calSourceReadonly').value = SOURCE_TEXT[cam.data.type] || cam.data.type;
  $('#calSourceBadge').textContent = cam.data.type === 'phone_ws' ? 'Камера телефона' : cam.data.type;
  $('#calGaugeType').value = cam.data.gauge_type || 'pressure';
  fillUnitSelect($('#calUnit'), $('#calGaugeType').value, cam.data.unit);
  syncUnitLabels($('#calUnit').value);

  const c = cam.data.calibration || {};
  const roi = c.roi || { mode: 'auto', cx: 0.5, cy: 0.5, r: 0.45 };
  roiMode = roi.mode || 'auto';
  calDir = c.direction || 'cw';

  form.roi_cx.value = fmtInput(roi.cx, 3);
  form.roi_cy.value = fmtInput(roi.cy, 3);
  form.roi_r.value = fmtInput(roi.r, 3);

  form.v_min.value = fmtInput(c.v_min, 2);
  form.v_max.value = fmtInput(c.v_max, 2);
  form.theta_min.value = fmtInput(c.theta_min, 1);
  form.theta_max.value = fmtInput(c.theta_max, 1);

  const t = cam.data.thresholds || {};
  const dd = decimalsFor(cam.data);
  const lowerOn = t.lower_enabled === undefined
    ? (num(t.ll_alert) !== null || num(t.l_warn) !== null)
    : Boolean(t.lower_enabled);
  $('#calLowerEnabled').checked = lowerOn;

  form.ll_alert.value = lowerOn ? fmtFixed(num(t.ll_alert), dd) : '';
  form.l_warn.value = lowerOn ? fmtFixed(num(t.l_warn), dd) : '';
  form.h_warn.value = fmtFixed(num(t.h_warn), dd);
  form.hh_alert.value = fmtFixed(num(t.hh_alert), dd);

  syncFormControls();
  validateAndPreview();
  syncCalFrames();
}

function syncFormControls() {
  $$('#calRoiMode [data-rmode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.rmode === roiMode)));
  $$('#calDirSeg [data-cdir]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.cdir === calDir)));
  $$('#segCalPick [data-pick]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.pick === pickMode)));
  $$('#segCalFreeze [data-freeze]').forEach((b) => b.setAttribute('aria-pressed', String((b.dataset.freeze === 'freeze') === frozen)));

  const manual = roiMode === 'manual';
  $$('#calRoiInputs input').forEach((inp) => { inp.disabled = !manual; });

  const lowerOn = $('#calLowerEnabled').checked;
  form.ll_alert.disabled = !lowerOn;
  form.l_warn.disabled = !lowerOn;
  form.ll_alert.placeholder = lowerOn ? 'например 2,00' : 'выкл.';
  form.l_warn.placeholder = lowerOn ? 'например 4,00' : 'выкл.';

  const cam = targetCam();
  const isPinnedDemo = state.demo?.enabled && cam && cam.id === state.demo.live_cam_id;
  $('#btnCalDeleteCam').disabled = !!isPinnedDemo;
  $('#btnCalDeleteCam').title = isPinnedDemo ? 'Основной прибор демонстрации закреплён за позицией 01' : '';
}

function clearErrors() {
  $$('[data-ferr]', form).forEach((el) => { el.textContent = ''; });
  $$('input', form).forEach((inp) => inp.setAttribute('aria-invalid', 'false'));
  $('#calFormErr').textContent = '';
}

function setFieldErr(fieldName, message) {
  const errEl = $(`[data-ferr="${fieldName}"]`, form);
  if (errEl) errEl.textContent = message;
  const inp = form[fieldName];
  if (inp) inp.setAttribute('aria-invalid', 'true');
}

/** Полная клиентская валидация черновика с понятными сообщениями у каждого поля. */
function validateDraft() {
  clearErrors();
  let ok = true;

  const name = form.name.value.trim();
  if (!name) {
    setFieldErr('name', 'Введите название прибора');
    ok = false;
  }

  const reqNum = (fname, labelTxt) => {
    const raw = form[fname].value.trim();
    if (raw === '') {
      setFieldErr(fname, `Поле «${labelTxt}» обязательно`);
      ok = false;
      return null;
    }
    const v = parseNum(raw);
    if (Number.isNaN(v)) {
      setFieldErr(fname, 'Введите число (допустима запятая, например 14,2)');
      ok = false;
      return null;
    }
    return v;
  };

  const vMin = reqNum('v_min', 'Vmin');
  const vMax = reqNum('v_max', 'Vmax');
  const thMin = reqNum('theta_min', 'θmin');
  const thMax = reqNum('theta_max', 'θmax');

  if (vMin !== null && vMax !== null && Math.abs(vMax - vMin) < 1e-9) {
    setFieldErr('v_max', 'Vmax должен отличаться от Vmin (нулевой диапазон)');
    ok = false;
  }

  let arcSpan = null;
  if (thMin !== null && thMax !== null) {
    const a0 = ((thMin % 360) + 360) % 360;
    const a1 = ((thMax % 360) + 360) % 360;
    arcSpan = calDir === 'cw' ? (a1 - a0 + 360) % 360 : (a0 - a1 + 360) % 360;
    if (arcSpan < 5 || arcSpan > 355) {
      setFieldErr('theta_max', 'Нулевой или вырожденный размах шкалы: задайте две разные отметки');
      ok = false;
    }
  }

  let cx = 0.5, cy = 0.5, rr = 0.45;
  if (roiMode === 'manual') {
    cx = reqNum('roi_cx', 'Центр X');
    cy = reqNum('roi_cy', 'Центр Y');
    rr = reqNum('roi_r', 'Радиус R');
    if (cx !== null && (cx < 0.05 || cx > 0.95)) { setFieldErr('roi_cx', 'Допустимо от 0,05 до 0,95'); ok = false; }
    if (cy !== null && (cy < 0.05 || cy > 0.95)) { setFieldErr('roi_cy', 'Допустимо от 0,05 до 0,95'); ok = false; }
    if (rr !== null && (rr < 0.05 || rr > 1.0)) { setFieldErr('roi_r', 'Допустимо от 0,05 до 1,00'); ok = false; }
    if (cx !== null && cy !== null && rr !== null) {
      if (cx - rr < -0.15 || cx + rr > 1.15 || cy - rr < -0.15 || cy + rr > 1.15) {
        setFieldErr('roi_r', 'Окружность ROI выходит за границы кадра');
        ok = false;
      }
    }
  }

  const lowerOn = $('#calLowerEnabled').checked;
  const hWarn = reqNum('h_warn', 'H');
  const hhAlert = reqNum('hh_alert', 'HH');
  let llAlert = null, lWarn = null;
  if (lowerOn) {
    llAlert = reqNum('ll_alert', 'LL');
    lWarn = reqNum('l_warn', 'L');
  }

  if (vMin !== null && vMax !== null) {
    const lo = Math.min(vMin, vMax);
    const hi = Math.max(vMin, vMax);
    const checkBound = (fname, val) => {
      if (val !== null && (val < lo - 1e-9 || val > hi + 1e-9)) {
        setFieldErr(fname, `Вне шкалы [${fmt(lo, 2)}…${fmt(hi, 2)}]`);
        ok = false;
      }
    };
    if (lowerOn) {
      checkBound('ll_alert', llAlert);
      checkBound('l_warn', lWarn);
    }
    checkBound('h_warn', hWarn);
    checkBound('hh_alert', hhAlert);
  }

  // Строгий порядок границ без равенства: LL < L < H < HH
  const ordered = lowerOn
    ? [['ll_alert', 'LL', llAlert], ['l_warn', 'L', lWarn], ['h_warn', 'H', hWarn], ['hh_alert', 'HH', hhAlert]]
    : [['h_warn', 'H', hWarn], ['hh_alert', 'HH', hhAlert]];
  for (let i = 1; i < ordered.length; i++) {
    const [, prevCode, prevVal] = ordered[i - 1];
    const [curField, curCode, curVal] = ordered[i];
    if (prevVal !== null && curVal !== null && prevVal >= curVal) {
      setFieldErr(curField, prevVal === curVal
        ? `Граница ${curCode} не может быть равна ${prevCode}`
        : `Должно выполняться ${prevCode} < ${curCode}`);
      ok = false;
    }
  }

  if (arcSpan !== null) {
    const wraps = calDir === 'cw'
      ? (((thMin % 360) + 360) % 360) > (((thMax % 360) + 360) % 360)
      : (((thMin % 360) + 360) % 360) < (((thMax % 360) + 360) % 360);
    $('#calArcSpanLbl').textContent = `Дуга ${fmt(arcSpan, 1)}° ${calDir.toUpperCase()}${wraps ? ', переход через 0°' : ''}`;
  }

  const draftCalibration = (vMin !== null && vMax !== null && thMin !== null && thMax !== null)
    ? {
      v_min: vMin,
      v_max: vMax,
      theta_min: ((thMin % 360) + 360) % 360,
      theta_max: ((thMax % 360) + 360) % 360,
      direction: calDir,
      roi: { mode: roiMode, cx: cx ?? 0.5, cy: cy ?? 0.5, r: rr ?? 0.45 },
    }
    : null;

  const draftThresholds = {
    ll_alert: lowerOn ? llAlert : null,
    l_warn: lowerOn ? lWarn : null,
    h_warn: hWarn,
    hh_alert: hhAlert,
    lower_enabled: lowerOn,
  };

  return {
    ok,
    body: ok && draftCalibration ? {
      name,
      gauge_type: $('#calGaugeType').value,
      unit: $('#calUnit').value,
      calibration: draftCalibration,
      thresholds: draftThresholds,
    } : null,
    draftCalibration,
    draftThresholds,
  };
}

function previewAngleToValue(angleDeg, cal) {
  if (angleDeg === null || angleDeg === undefined || !cal) return null;
  const span = cal.direction === 'cw'
    ? (cal.theta_max - cal.theta_min + 360) % 360
    : (cal.theta_min - cal.theta_max + 360) % 360;
  if (span < 5) return null;
  let delta = cal.direction === 'cw'
    ? (angleDeg - cal.theta_min + 360) % 360
    : (cal.theta_min - angleDeg + 360) % 360;
  if (delta > span) {
    const over = delta - span;
    const under = 360 - delta;
    delta = over <= under ? span + over : -under;
  }
  const rawFrac = delta / span;
  if (rawFrac < -0.08 || rawFrac > 1.08) return null;
  const frac = Math.max(-0.05, Math.min(1.05, rawFrac));
  return cal.v_min + frac * (cal.v_max - cal.v_min);
}

function classifyDraft(val, thr) {
  if (val === null || val === undefined || !thr) return null;
  const lowOn = thr.lower_enabled !== false;
  if ((lowOn && thr.ll_alert !== null && val <= thr.ll_alert) || (thr.hh_alert !== null && val >= thr.hh_alert)) return 'alert';
  if ((lowOn && thr.l_warn !== null && val <= thr.l_warn) || (thr.h_warn !== null && val >= thr.h_warn)) return 'warning';
  return 'normal';
}

function updateLiveReadout(validated = null) {
  const cam = targetCam();
  if (!cam || isSimulated(cam)) return;
  const v = validated || validateDraft();
  const r = cam.reading;
  const d = decimalsFor({ calibration: v.draftCalibration || cam.data.calibration });
  const unit = $('#calUnit').value || cam.data.unit;

  $('#calRoiStatus').textContent = r
    ? `${DIAL_SOURCE[r.dial_source] || r.dial_source}${r.geom ? `, оценка ${fmt(r.geom.score, 2)}` : ''}`
    : 'ожидание кадра';

  $('#calLiveAngle').textContent = r && r.angle !== null && r.angle !== undefined ? `${fmt(r.angle, 2)}°` : '—';
  $('#calLiveRaw').textContent = r && r.raw_value !== null && r.raw_value !== undefined ? `${fmt(r.raw_value, d)} ${cam.data.unit}` : '—';

  const draftVal = (r && r.angle !== null && v.draftCalibration)
    ? previewAngleToValue(r.angle, v.draftCalibration)
    : null;
  const draftLv = classifyDraft(draftVal, v.draftThresholds);
  const lvWord = draftLv === 'alert' ? 'Авария' : draftLv === 'warning' ? 'Предупреждение' : 'Норма';
  $('#calDraftPreviewVal').textContent = draftVal !== null
    ? `${fmt(draftVal, d)} ${unit} (${lvWord})`
    : (r && r.angle !== null ? 'вне дуги шкалы' : '—');

  // Сравнение двух шкал: сохранённой и предлагаемой
  renderRuler($('#calSavedRuler'), {
    calibration: cam.data.calibration,
    thresholds: cam.data.thresholds,
    value: r && r.valid ? r.value : null,
    level: (r && r.valid && r.level) || 'normal',
    big: true,
    decimals: decimalsFor(cam.data),
  });

  renderRuler($('#calDraftRuler'), {
    calibration: v.draftCalibration || cam.data.calibration,
    thresholds: v.draftThresholds,
    value: draftVal,
    level: draftLv || 'normal',
    big: true,
    decimals: d,
  });

  const canSave = v.ok && dirty;
  $('#btnCalSave').disabled = !canSave;
  $('#btnCalSaveAndMonitor').disabled = !canSave;
  $('#btnCalReset').disabled = !dirty;
}

function validateAndPreview() {
  const v = validateDraft();
  updateLiveReadout(v);
  renderCalOverlay(v);
  return v;
}

function svgEl(name, attrs) {
  const e = document.createElementNS(NS, name);
  for (const [k, val] of Object.entries(attrs)) e.setAttribute(k, val);
  return e;
}

function currentDialCenter(w, h, cam, draftCal) {
  if (roiMode === 'manual' && draftCal?.roi) {
    return {
      cx: draftCal.roi.cx * w,
      cy: draftCal.roi.cy * h,
      rx: draftCal.roi.r * Math.min(w, h),
      ry: draftCal.roi.r * Math.min(w, h),
      ang: 0,
    };
  }
  const g = cam?.reading?.geom;
  if (g && g.ellipse) {
    const [cx, cy, a, b, ang] = g.ellipse;
    return { cx, cy, rx: a, ry: b, ang };
  }
  const r = 0.45 * Math.min(w, h);
  return { cx: w / 2, cy: h / 2, rx: r, ry: r, ang: 0 };
}

function renderCalOverlay(validated = null) {
  calSvg.textContent = '';
  const cam = targetCam();
  if (!cam || isSimulated(cam)) return;
  const g = cam.reading?.geom;
  if (g) calFrameWH = { w: g.w, h: g.h };
  else if (calImg.naturalWidth) calFrameWH = { w: calImg.naturalWidth, h: calImg.naturalHeight };
  if (!calFrameWH) return;

  const { w, h } = calFrameWH;
  calSvg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  calSvg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

  const v = validated || validateDraft();
  const dial = currentDialCenter(w, h, cam, v.draftCalibration);
  const k = Math.min(calMedia.clientWidth / w, calMedia.clientHeight / h) || 1;
  const nss = { 'vector-effect': 'non-scaling-stroke' };

  // Эллипс / окружность ROI
  calSvg.appendChild(svgEl('ellipse', {
    class: roiMode === 'manual' ? 'edit-circle' : 'ell',
    cx: dial.cx, cy: dial.cy, rx: dial.rx, ry: dial.ry,
    transform: `rotate(${dial.ang} ${dial.cx} ${dial.cy})`,
    ...nss, 'stroke-width': 1.5,
  }));
  calSvg.appendChild(svgEl('line', { class: 'cross', x1: dial.cx - 10 / k, y1: dial.cy, x2: dial.cx + 10 / k, y2: dial.cy, ...nss, 'stroke-width': 1 }));
  calSvg.appendChild(svgEl('line', { class: 'cross', x1: dial.cx, y1: dial.cy - 10 / k, x2: dial.cx, y2: dial.cy + 10 / k, ...nss, 'stroke-width': 1 }));

  // Опорные лучи θmin и θmax из черновика
  if (v.draftCalibration) {
    const drawRay = (deg, color) => {
      const rad = (deg * Math.PI) / 180;
      const r0 = Math.min(dial.rx, dial.ry) * 0.72;
      const r1 = Math.max(dial.rx, dial.ry) * 0.98;
      calSvg.appendChild(svgEl('line', {
        x1: dial.cx + Math.cos(rad) * r0,
        y1: dial.cy + Math.sin(rad) * r0,
        x2: dial.cx + Math.cos(rad) * r1,
        y2: dial.cy + Math.sin(rad) * r1,
        stroke: color, ...nss, 'stroke-width': 2.5,
      }));
    };
    drawRay(v.draftCalibration.theta_min, '#52b073');
    drawRay(v.draftCalibration.theta_max, '#f05a5f');
  }

  // Распознанная стрелка
  if (g && g.needle) {
    const [[x0, y0], [x1, y1]] = g.needle;
    calSvg.appendChild(svgEl('line', { class: 'needle', x1: x0, y1: y0, x2: x1, y2: y1, ...nss, 'stroke-width': 2 }));
    calSvg.appendChild(svgEl('circle', { class: 'hub', cx: x0, cy: y0, r: 4 / k }));
  }

  // Ручка радиуса в ручном режиме
  if (roiMode === 'manual') {
    const hr = svgEl('rect', {
      class: 'handle',
      x: dial.cx + dial.rx - 7 / k,
      y: dial.cy - 7 / k,
      width: 14 / k,
      height: 14 / k,
      ...nss, 'stroke-width': 1.5,
    });
    calSvg.appendChild(hr);
  }
}

function clientPointToFrame(ev) {
  if (!calFrameWH) return null;
  const ctm = calSvg.getScreenCTM();
  if (!ctm) return null;
  const pt = calSvg.createSVGPoint();
  pt.x = ev.clientX;
  pt.y = ev.clientY;
  return pt.matrixTransform(ctm.inverse());
}

function onStagePointerDown(e) {
  const cam = targetCam();
  if (!cam || isSimulated(cam) || !calFrameWH) return;
  const p = clientPointToFrame(e);
  if (!p) return;
  const { w, h } = calFrameWH;

  if (pickMode === 'theta_min' || pickMode === 'theta_max') {
    e.preventDefault();
    const v = validateDraft();
    const dial = currentDialCenter(w, h, cam, v.draftCalibration);
    // Нормализация к кругу по полуосям эллипса — совпадает с системой углов vision.py
    const phi = (dial.ang * Math.PI) / 180;
    const dx = p.x - dial.cx;
    const dy = p.y - dial.cy;
    const ux = (dx * Math.cos(phi) + dy * Math.sin(phi)) / Math.max(1, dial.rx);
    const uy = (-dx * Math.sin(phi) + dy * Math.cos(phi)) / Math.max(1, dial.ry);
    const nx = ux * Math.cos(phi) - uy * Math.sin(phi);
    const ny = ux * Math.sin(phi) + uy * Math.cos(phi);
    const deg = ((Math.atan2(ny, nx) * 180) / Math.PI + 360) % 360;
    form[pickMode].value = fmtInput(deg, 1);
    dirty = true;
    $('#calSaveStatus').hidden = true;
    validateAndPreview();
    toast(`Угол ${pickMode === 'theta_min' ? 'θmin' : 'θmax'} выставлен по кадру: ${fmt(deg, 1)}°`);
    return;
  }

  if (pickMode === 'roi' || roiMode === 'manual') {
    if (roiMode !== 'manual') {
      roiMode = 'manual';
      syncFormControls();
    }
    e.preventDefault();
    calSvg.setPointerCapture(e.pointerId);
    const m = Math.min(w, h);
    const cx0 = parseNum(form.roi_cx.value) ?? 0.5;
    const cy0 = parseNum(form.roi_cy.value) ?? 0.5;
    const r0 = parseNum(form.roi_r.value) ?? 0.45;
    const distHandle = Math.hypot(p.x - (cx0 * w + r0 * m), p.y - cy0 * h);
    const resizing = distHandle < 28 * (w / Math.max(1, calMedia.clientWidth));

    const onMove = (ev) => {
      const q = clientPointToFrame(ev);
      if (!q) return;
      const clamp = (val, a, b) => Math.max(a, Math.min(b, val));
      if (resizing) {
        const nr = clamp(Math.hypot(q.x - cx0 * w, q.y - cy0 * h) / m, 0.05, 0.95);
        form.roi_r.value = fmtInput(nr, 3);
      } else {
        form.roi_cx.value = fmtInput(clamp(cx0 + (q.x - p.x) / w, 0.05, 0.95), 3);
        form.roi_cy.value = fmtInput(clamp(cy0 + (q.y - p.y) / h, 0.05, 0.95), 3);
      }
      dirty = true;
      validateAndPreview();
    };
    const onUp = () => {
      calSvg.removeEventListener('pointermove', onMove);
      calSvg.removeEventListener('pointerup', onUp);
    };
    calSvg.addEventListener('pointermove', onMove);
    calSvg.addEventListener('pointerup', onUp);
  }
}

function applyMtp160Preset() {
  const cam = targetCam();
  if (!cam || isSimulated(cam)) return;
  form.name.value = 'Манометр острого пара К-1 (МТП-160)';
  $('#calGaugeType').value = 'pressure';
  fillUnitSelect($('#calUnit'), 'pressure', 'МПа');
  syncUnitLabels('МПа');
  form.v_min.value = '0';
  form.theta_min.value = '135';
  form.v_max.value = '16';
  form.theta_max.value = '45';
  calDir = 'cw';
  roiMode = 'auto';
  $('#calLowerEnabled').checked = true;
  form.ll_alert.value = '2,00';
  form.l_warn.value = '4,00';
  form.h_warn.value = '14,20';
  form.hh_alert.value = '15,20';
  dirty = true;
  syncFormControls();
  validateAndPreview();
  toast('Заполнен штатный профиль МТП-160 (0–16 МПа, 270° CW) — нажмите «Сохранить» для применения');
}

async function saveCalibration(returnToMonitor = false) {
  const cam = targetCam();
  if (!cam || isSimulated(cam)) return;
  const v = validateAndPreview();
  if (!v.ok || !v.body) {
    $('#calFormErr').textContent = 'Исправьте выделенные поля перед сохранением конфигурации.';
    return;
  }
  $('#btnCalSave').disabled = true;
  $('#btnCalSaveAndMonitor').disabled = true;
  try {
    // дополнительный прибор щита хранит шкалу и уставки в реестре приборов, основной — в записи камеры
    const url = isSecondary(cam) ? `/api/instruments/${encodeURIComponent(cam.id)}` : `/api/cameras/${encodeURIComponent(cam.id)}`;
    const updated = await api(url, { method: 'PATCH', body: v.body });
    dirty = false;
    const stBox = $('#calSaveStatus');
    stBox.hidden = false;
    stBox.textContent = `Конфигурация сохранена на сервере: ${updated.name}, шкала ${fmt(updated.calibration.v_min, 2)}–${fmt(updated.calibration.v_max, 2)} ${updated.unit}. Показания пересчитываются по новой калибровке с очередного кадра.`;
    toast(`Настройки сохранены: ${updated.name}`);
    fillFormFromCam(true);
    if (returnToMonitor) {
      jumpToInstrument(cam.id);
    }
  } catch (e) {
    $('#calFormErr').textContent = e.message;
    updateLiveReadout();
  }
}

export function openCalibrationFor(instId) {
  if (instId && state.cams.has(instId)) {
    targetId = instId;
    dirty = false;
  }
  setView('calibration');
}

export function initControl() {
  $('#calSearch').addEventListener('input', populateSelector);
  $('#calSelect').addEventListener('change', (e) => {
    targetId = e.target.value;
    dirty = false;
    calFrameWH = null;
    stopCalFrames(true);
    fillFormFromCam(true);
  });

  $('#btnCalSwitchLive').addEventListener('click', () => {
    const live = livePrimaryCam();
    if (live) {
      targetId = live.id;
      dirty = false;
      fillFormFromCam(true);
    }
  });
  $('#btnCalBackMonitor').addEventListener('click', () => {
    const cam = targetCam();
    if (cam) jumpToInstrument(cam.id);
    else setView('monitor');
  });
  $('#btnCalPresetMtp').addEventListener('click', applyMtp160Preset);

  $('#calGaugeType').addEventListener('change', () => {
    fillUnitSelect($('#calUnit'), $('#calGaugeType').value, $('#calUnit').value);
    syncUnitLabels($('#calUnit').value);
    dirty = true;
    validateAndPreview();
  });
  $('#calUnit').addEventListener('change', () => {
    syncUnitLabels($('#calUnit').value);
    dirty = true;
    validateAndPreview();
  });

  $$('#calRoiMode [data-rmode]').forEach((b) => b.addEventListener('click', () => {
    roiMode = b.dataset.rmode;
    const cam = targetCam();
    const g = cam?.reading?.geom;
    if (roiMode === 'manual' && g && g.ellipse) {
      const [cx, cy, a, bb] = g.ellipse;
      form.roi_cx.value = fmtInput(cx / g.w, 3);
      form.roi_cy.value = fmtInput(cy / g.h, 3);
      form.roi_r.value = fmtInput(Math.max(a, bb) / Math.min(g.w, g.h), 3);
    }
    dirty = true;
    syncFormControls();
    validateAndPreview();
  }));

  $$('#calDirSeg [data-cdir]').forEach((b) => b.addEventListener('click', () => {
    calDir = b.dataset.cdir;
    dirty = true;
    syncFormControls();
    validateAndPreview();
  }));

  $$('#segCalFreeze [data-freeze]').forEach((b) => b.addEventListener('click', () => {
    frozen = b.dataset.freeze === 'freeze';
    syncFormControls();
    syncCalFrames();
  }));

  $$('#segCalPick [data-pick]').forEach((b) => b.addEventListener('click', () => {
    pickMode = b.dataset.pick;
    if (pickMode === 'roi' && roiMode !== 'manual') roiMode = 'manual';
    syncFormControls();
    renderCalOverlay();
  }));

  $$('[data-take-live]', form).forEach((b) => b.addEventListener('click', () => {
    const cam = targetCam();
    const ang = cam?.reading?.angle;
    if (ang === null || ang === undefined) {
      toast('Стрелка сейчас не распознана на кадре — используйте клик по делению на стоп-кадре или проверьте камеру', 'warn');
      return;
    }
    const field = b.dataset.takeLive;
    form[field].value = fmtInput(ang, 1);
    dirty = true;
    validateAndPreview();
    toast(`Взят текущий угол стрелки: ${fmt(ang, 1)}°`);
  }));

  $('#calLowerEnabled').addEventListener('change', () => {
    const onLow = $('#calLowerEnabled').checked;
    if (onLow) {
      const preset = state.demo?.preset?.lower_defaults || { ll_alert: 2.0, l_warn: 4.0 };
      if (!form.ll_alert.value.trim()) form.ll_alert.value = fmtFixed(preset.ll_alert, 2);
      if (!form.l_warn.value.trim()) form.l_warn.value = fmtFixed(preset.l_warn, 2);
    }
    dirty = true;
    syncFormControls();
    validateAndPreview();
  });

  form.addEventListener('input', () => {
    dirty = true;
    $('#calSaveStatus').hidden = true;
    validateAndPreview();
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    saveCalibration(false);
  });
  $('#btnCalSaveAndMonitor').addEventListener('click', () => saveCalibration(true));
  $('#btnCalReset').addEventListener('click', () => {
    dirty = false;
    fillFormFromCam(true);
    toast('Черновик отменён — восстановлены сохранённые значения');
  });

  $('#btnCalRedetect').addEventListener('click', async () => {
    const cam = targetCam();
    if (!cam || isSimulated(cam)) return;
    try {
      await api(`/api/cameras/${encodeURIComponent(sourceIdOf(cam))}/redetect`, { method: 'POST' });
      toast('Запрошена повторная локализация циферблата');
    } catch (e) {
      toast(e.message, 'err');
    }
  });

  $('#btnCalClearHistory').addEventListener('click', async () => {
    const cam = targetCam();
    if (!cam || isSimulated(cam)) return;
    const ok = await confirmDlg(
      'Очистить архив показаний?',
      `Все записанные в базу отсчёты прибора «${cam.data.name}» будут удалены.`,
      'Очистить архив'
    );
    if (!ok) return;
    try {
      const histUrl = isSecondary(cam) ? `/api/instruments/${encodeURIComponent(cam.id)}/history` : `/api/cameras/${encodeURIComponent(cam.id)}/history`;
      await api(histUrl, { method: 'DELETE' });
      emit('cam-config', cam.id);
      toast('Архив показаний очищен');
    } catch (e) {
      toast(e.message, 'err');
    }
  });

  $('#btnCalDeleteCam').addEventListener('click', async () => {
    const cam = targetCam();
    if (!cam || isSimulated(cam)) return;
    const secondary = isSecondary(cam);
    const ok = await confirmDlg(
      secondary ? 'Удалить прибор щита?' : 'Удалить камеру?',
      secondary
        ? `Прибор «${cam.data.name}» и его архив будут удалены; камера и остальные приборы щита продолжат работу.`
        : `Камера «${cam.data.name}» и её архив будут удалены с пульта.`,
      'Удалить'
    );
    if (!ok) return;
    try {
      const delUrl = secondary ? `/api/instruments/${encodeURIComponent(cam.id)}` : `/api/cameras/${encodeURIComponent(cam.id)}`;
      await api(delUrl, { method: 'DELETE' });
      targetId = null;
      toast(secondary ? 'Прибор удалён' : 'Камера удалена');
    } catch (e) {
      toast(e.message, 'err');
    }
  });

  calSvg.addEventListener('pointerdown', onStagePointerDown);
  calImg.addEventListener('load', () => { if (!calFrameWH) renderCalOverlay(); });
  new ResizeObserver(() => { if (state.view === 'calibration') renderCalOverlay(); }).observe(calMedia);

  on('view', (v) => {
    if (v === 'calibration') {
      fillFormFromCam(false);
      syncCalFrames();
    } else {
      stopCalFrames(true);
    }
  });
  on('cams', () => { if (state.view === 'calibration') fillFormFromCam(false); });
  on('cam-config', (id) => { if (state.view === 'calibration' && id === targetId && !dirty) fillFormFromCam(true); });
  on('reading', (id) => {
    if (state.view === 'calibration' && id === targetId) {
      updateLiveReadout();
      renderCalOverlay();
    }
  });
}
