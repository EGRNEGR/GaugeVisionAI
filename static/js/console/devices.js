// Вкладка «Камеры», диалог подключения Android по QR-коду, проверка живого кадра,
// техническая диагностика конвейера и добавление дополнительных камер.
import { $, $$, esc, api, toast, confirmDlg, fmt, durStr, durShort, timeStr, GAUGE_SHORT, SOURCE_TEXT, PHONE_STAGE_TEXT } from './util.js';
import { state, on, realCamList, livePrimaryCam, select, setView, evaluateInstrument } from './store.js';
import { jumpToInstrument } from './instruments.js';
import { openCalibrationFor } from './control.js';

const URL_HINTS = {
  rtsp: ['Адрес RTSP-потока', 'rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101',
    'Hikvision: /Streaming/Channels/101. Dahua: /cam/realmonitor?channel=1&subtype=0.'],
  http_mjpeg: ['Адрес HTTP / MJPEG-потока', 'http://192.168.1.50:8080/video',
    'IP Webcam: http://IP:8080/video. DroidCam: http://IP:4747/video.'],
  device: ['Индекс камеры сервера', '0', 'Локальная USB-камера: 0 — первая, 1 — вторая.'],
  phone_ws: ['', '', 'После сохранения откроется QR-код для подключения смартфона.'],
};

let activeQrSession = null; // { cam_id, url, qr_svg }
let previewMode = 'overlay';
let previewTimer = null;
let previewBlobUrl = null;
let addFields = null;

export function fillGaugeSelect(sel) {
  if (!sel || !state.meta) return;
  sel.innerHTML = Object.entries(state.meta.gauge_types)
    .map(([k, g]) => `<option value="${k}" title="${esc(g.label)}">${esc(GAUGE_SHORT[k] || g.label)}</option>`).join('');
}

export function fillUnitSelect(sel, gaugeType, current) {
  if (!sel || !state.meta) return;
  const units = state.meta.gauge_types[gaugeType]?.units || ['МПа'];
  sel.innerHTML = units.map((u) => `<option value="${esc(u)}">${esc(u)}</option>`).join('');
  sel.value = units.includes(current) ? current : units[0];
}

function fillTypeSelect(sel) {
  if (!sel || !state.meta) return;
  sel.innerHTML = state.meta.camera_types.map((t) => `<option value="${t}">${esc(SOURCE_TEXT[t] || t)}</option>`).join('');
}

export function bindSourceFields(form) {
  fillGaugeSelect(form.gauge_type);
  fillTypeSelect(form.type);
  const onType = () => {
    const [label, ph, hint] = URL_HINTS[form.type.value] || ['', '', ''];
    const wrap = $('[data-url]', form);
    if (wrap) {
      wrap.hidden = form.type.value === 'phone_ws';
      $('span', wrap).textContent = label;
    }
    if (form.source_url) form.source_url.placeholder = ph;
    const hintEl = $('[data-url-hint]', form);
    if (hintEl) hintEl.textContent = hint;
  };
  form.type.addEventListener('change', onType);
  form.gauge_type.addEventListener('change', () => fillUnitSelect(form.unit, form.gauge_type.value, form.unit.value));
  return {
    set(d) {
      form.name.value = d.name || '';
      form.gauge_type.value = d.gauge_type || 'pressure';
      fillUnitSelect(form.unit, form.gauge_type.value, d.unit);
      form.type.value = d.type || 'rtsp';
      form.source_url.value = d.source_url || '';
      onType();
    },
    read() {
      return {
        name: form.name.value.trim(),
        gauge_type: form.gauge_type.value,
        unit: form.unit.value,
        type: form.type.value,
        source_url: form.type.value === 'phone_ws' ? null : (form.source_url.value.trim() || null),
      };
    },
  };
}

export async function ensureQrSession(camId = null, regenerate = false) {
  const live = camId ? state.cams.get(camId) : livePrimaryCam();
  const targetId = live && live.data.type === 'phone_ws' ? live.id : null;

  if (regenerate && live && (live.status === 'online' || live.stream?.ws_connected)) {
    const ok = await confirmDlg(
      'Перевыпустить QR-код?',
      'Текущее подключение смартфона будет закрыто, а старая ссылка перестанет действовать. Потребуется заново отсканировать новый QR-код на Android.',
      'Перевыпустить QR'
    );
    if (!ok) return null;
  }

  const res = await api('/api/phone/session', {
    method: 'POST',
    body: { cam_id: targetId, regenerate },
  });
  activeQrSession = res;
  renderQrTargets();
  if (regenerate) toast('Выпущен новый QR-код — переподключите смартфон по новой ссылке', 'warn');
  return res;
}

function renderQrTargets() {
  if (!activeQrSession) return;
  $('#camQrSvg').innerHTML = activeQrSession.qr_svg;
  $('#camQrUrl').textContent = activeQrSession.url;
  $('#pQr').innerHTML = activeQrSession.qr_svg;
  $('#pUrl').textContent = activeQrSession.url;
  const cam = state.cams.get(activeQrSession.cam_id);
  if (cam) {
    $('#pCamTitle').textContent = `${cam.data.code ? `${cam.data.code} — ` : ''}${cam.data.name}`;
  }
}

export async function openPhoneDialog(camId = null) {
  try {
    await ensureQrSession(camId, false);
    renderCamerasView();
    if (!$('#dlgPhone').open) $('#dlgPhone').showModal();
  } catch (e) {
    toast(`Не удалось подготовить QR-сессию: ${e.message}`, 'err');
  }
}

function copyText(urlTxt) {
  if (!urlTxt || urlTxt === '—') return;
  navigator.clipboard?.writeText(urlTxt).then(
    () => toast('Ссылка захвата скопирована в буфер обмена'),
    () => toast('Не удалось скопировать автоматически — выделите адрес вручную', 'warn')
  );
}

function currentPhoneStage(cam) {
  if (!cam) return 'waiting_phone';
  if (!state.connected) return 'stream_interrupted';
  const st = cam.stream || {};
  const ev = evaluateInstrument(cam);
  if (st.client_state === 'permission_denied') return 'permission_denied';
  if (st.client_state === 'camera_error') return 'camera_error';
  if (ev.hasFreshValid) return 'reading_received';
  if (cam.status === 'online') return 'no_reading_yet';
  if ((st.frames_total || 0) > 0) return 'stream_interrupted';
  if (st.ws_connected) return 'awaiting_permission';
  return 'waiting_phone';
}

function adviceForStage(stage, cam) {
  const hostUrl = state.meta?.urls?.[1] || location.origin;
  switch (stage) {
    case 'waiting_phone':
      return { tone: 'normal', text: `Ожидаем подключение смартфона. Отсканируйте QR-код камерой Android в одной сети с ноутбуком (${hostUrl}).` };
    case 'awaiting_permission':
      return { tone: 'warn', text: 'Страница захвата открыта на телефоне. Разрешите браузеру доступ к задней камере и нажмите «Начать трансляцию».' };
    case 'permission_denied':
      return { tone: 'err', text: 'На смартфоне отклонён доступ к камере. В Chrome нажмите на значок замка в адресной строке → «Разрешения» → включите «Камера» и нажмите «Повторить».' };
    case 'camera_error':
      return { tone: 'err', text: `Камера смартфона недоступна (${cam?.stream?.client_error || 'занята другим приложением'}). Закройте сторонние приложения камеры и обновите вкладку на телефоне.` };
    case 'no_reading_yet':
      return { tone: 'warn', text: 'Кадры со смартфона поступают, но стрелка ещё не подтверждена. Наведите камеру прямо на светлый циферблат МТП-160 без сильного блика или проверьте область ROI.' };
    case 'reading_received':
      return { tone: 'normal', text: 'Цепочка работает штатно: кадры поступают по WSS, конвейер распознаёт положение стрелки и передаёт достоверные показания.' };
    case 'stream_interrupted':
      return { tone: 'err', text: 'Поток кадров прерван (экран телефона погас, свёрнут браузер или пропал Wi-Fi). Верните вкладку захвата на экран Android и убедитесь, что кнопка «В эфире» активна.' };
    default:
      return { tone: 'normal', text: '' };
  }
}

function renderCamerasView() {
  const cam = livePrimaryCam();
  if (state.meta) {
    $('#camLanHost').textContent = state.meta.urls?.[1] || `https://${state.meta.lan_ip}:${state.meta.port}`;
    // ссылка на внешний симулятор — только если сервер её выдал (демопрофиль, OBS-SHARED-05)
    if (state.meta.simulator_url) $('#lnkSimulator').href = state.meta.simulator_url;
    $('#simulatorHint').hidden = !state.meta.simulator_url;
  }
  if (!cam) return;

  $('#camCardId').textContent = `${cam.data.code || ''} (${cam.id})`;
  const stage = currentPhoneStage(cam);
  $('#pStageBadge').textContent = `Статус: ${PHONE_STAGE_TEXT[stage] || stage}`;

  const steps = [
    { id: 'waiting_phone', lbl: '1. Ожидаем телефон' },
    { id: 'awaiting_permission', lbl: '2. Доступ к камере' },
    { id: 'frames', lbl: '3. Кадры поступают' },
    { id: 'no_reading_yet', lbl: '4. Поиск стрелки' },
    { id: 'reading_received', lbl: '5. Показание получено' },
    { id: 'stream_interrupted', lbl: '6. Контроль обрыва' },
  ];
  const rank = {
    waiting_phone: 0,
    awaiting_permission: 1,
    permission_denied: 1,
    camera_error: 1,
    no_reading_yet: 3,
    reading_received: 4,
    stream_interrupted: 5,
  }[stage] ?? 0;

  $('#phoneStepper').innerHTML = steps.map((s, idx) => {
    const bad = (stage === 'permission_denied' || stage === 'camera_error') && idx === 1
      || (stage === 'stream_interrupted' && idx === 5);
    const active = !bad && ((stage === 'no_reading_yet' && (idx === 2 || idx === 3)) || idx === rank);
    const done = !bad && !active && idx < rank && stage !== 'stream_interrupted';
    return `<div class="step-cell" data-active="${active}" data-done="${done}" data-bad="${bad}">
      <span class="dot"></span><span>${esc(s.lbl)}</span>
    </div>`;
  }).join('');

  const adv = adviceForStage(stage, cam);
  const advEl = $('#phoneAdvice');
  advEl.dataset.tone = adv.tone;
  advEl.textContent = adv.text;

  const st = cam.stream || {};
  const r = cam.reading;
  const kv = (dt, dd) => `<div class="kv"><dt>${dt}</dt><dd>${dd}</dd></div>`;
  $('#camStateGrid').innerHTML = [
    kv('Связанный прибор', esc(`${cam.data.code || ''} ${cam.data.name}`)),
    kv('WSS смартфона', st.ws_connected ? 'Подключён' : 'Нет активного сокета'),
    kv('Получение кадров', cam.status === 'online' ? `${fmt(st.fps, 1)} к/с (всего ${st.frames_total ?? 0})` : 'Нет свежих кадров'),
    kv('Последний кадр', st.last_frame_utc ? timeStr(new Date(st.last_frame_utc)) : '—'),
    kv('Последний замер CV', r?.last_valid_ts ? `${fmt(r.last_valid_value ?? r.value, 2)} ${esc(cam.data.unit)} (${timeStr(new Date(r.last_valid_ts))})` : 'Показаний пока нет'),
    kv('Уверенность / угол', r && r.angle !== null ? `θ = ${fmt(r.angle, 1)}°, увер. ${fmt(r.confidence, 2)}` : '—'),
  ].join('');

  renderDiagnostics();
}

function stopCamPreview() {
  clearTimeout(previewTimer);
  previewTimer = null;
  if (previewBlobUrl) {
    URL.revokeObjectURL(previewBlobUrl);
    previewBlobUrl = null;
  }
}

function syncCamPreview() {
  if (state.view !== 'cameras') {
    stopCamPreview();
    return;
  }
  const cam = livePrimaryCam();
  if (!cam || previewTimer !== null) return;

  const tick = async () => {
    if (state.view !== 'cameras') { stopCamPreview(); return; }
    const cur = livePrimaryCam();
    if (!cur || ((cur.stream?.frames_total || 0) === 0 && cur.status !== 'online')) {
      $('#camPreviewEmpty').hidden = false;
      $('#camPreviewImg').dataset.empty = 'true';
      previewTimer = setTimeout(tick, 1000);
      return;
    }
    try {
      const ov = previewMode === 'overlay' ? 1 : 0;
      const res = await fetch(`/api/cameras/${encodeURIComponent(cur.id)}/frame.jpg?overlay=${ov}`, { cache: 'no-store' });
      if (res.ok) {
        const url = URL.createObjectURL(await res.blob());
        if (state.view !== 'cameras') { URL.revokeObjectURL(url); return; }
        const old = previewBlobUrl;
        previewBlobUrl = url;
        $('#camPreviewImg').dataset.empty = 'false';
        $('#camPreviewImg').src = url;
        $('#camPreviewEmpty').hidden = true;
        try { await $('#camPreviewImg').decode(); } catch (_) { /* ok */ }
        if (old) URL.revokeObjectURL(old);
      }
    } catch (_) { /* повтор */ }
    previewTimer = setTimeout(tick, 400);
  };
  tick();
}

function pctl(arr, p) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
}

function renderDiagnostics() {
  const m = state.meta;
  if (!m) return;
  const up = m.uptime_s + (performance.now() - state.metaAt) / 1000;
  const kv = (dt, dd) => `<div class="kv"><dt>${dt}</dt><dd>${dd}</dd></div>`;
  $('#diagSys').innerHTML = [
    kv('Аптайм сервера', durStr(up)),
    kv('Детектор циферблата', m.yolo ? 'YOLOv8n + эллипс' : 'OpenCV (CLAHE + эллипс)'),
    kv('Вычислитель', esc(m.yolo ? String(m.yolo_device || 'CPU') : 'CPU')),
    kv('Целевая частота CV', `${fmt(m.process_fps, 1)} к/с, EMA α = ${fmt(m.ema_alpha, 2)}`),
    kv('Файл базы SQLite', esc(String(m.db_path || '').split(/[\\/]/).slice(-2).join('/'))),
    kv('Отпечаток TLS SHA-256', esc(m.cert_sha256 ? `${m.cert_sha256.slice(0, 23)}…` : '—')),
  ].join('');

  const now = Date.now();
  const reals = realCamList();
  $('#diagTable tbody').innerHTML = reals.map((c) => {
    const ts = c.diag.readTs.filter((t) => now - t <= 30000);
    const span = ts.length > 1 ? (ts[ts.length - 1] - ts[0]) / 1000 : 0;
    const rate = span > 0 ? (ts.length - 1) / span : null;
    const p50 = pctl(c.diag.procMs, 0.5), p95 = pctl(c.diag.procMs, 0.95);
    const st = c.stream || {};
    const upS = st.online_since ? now / 1000 - st.online_since : null;
    return `<tr>
      <td>${esc(c.data.name)}</td>
      <td>${esc(SOURCE_TEXT[c.data.type] || c.data.type)}</td>
      <td class="${c.status !== 'online' ? 'bad' : ''}">${esc(c.status)}</td>
      <td>${c.status === 'online' ? fmt(st.fps, 1) : '—'}</td>
      <td>${rate === null ? '—' : fmt(rate, 1)}</td>
      <td>${p50 === null ? '—' : `${fmt(p50, 0)} / ${fmt(p95, 0)}`}</td>
      <td>${upS === null ? '—' : durShort(upS)}</td>
      <td class="${st.fail_count ? 'bad' : 'dim'}">${st.fail_count ?? 0}</td>
    </tr>`;
  }).join('');
}

async function submitAddCamera(e) {
  const form = $('#addForm');
  if (e.submitter && e.submitter.value !== 'ok') return;
  e.preventDefault();
  const err = $('[data-err]', form);
  const body = addFields.read();
  if (!body.name) { err.textContent = 'Укажите наименование прибора.'; return; }
  if (body.type !== 'phone_ws' && !body.source_url) { err.textContent = 'Укажите адрес видеопотока.'; return; }
  e.submitter.disabled = true;
  try {
    const cam = await api('/api/cameras', { method: 'POST', body });
    $('#dlgAdd').close();
    select(cam.id, { openDetail: true });
    toast(`Камера добавлена: ${cam.name}`);
  } catch (ex) {
    err.textContent = ex.message;
  } finally {
    e.submitter.disabled = false;
  }
}

async function runDiscovery() {
  const btn = $('#btnScan');
  btn.disabled = true;
  $('#discStatus').textContent = 'Сканирование подсети (обычно 5–10 с)…';
  $('#discTable').hidden = true;
  try {
    const sub = $('#discSubnet').value.trim();
    const res = await api(`/api/discover${sub ? `?subnet=${encodeURIComponent(sub)}` : ''}`);
    const devs = res.devices || [];
    $('#discStatus').textContent = devs.length
      ? `Найдено устройств в ${res.subnet}: ${devs.length}`
      : `В подсети ${res.subnet} открытых видеопотоков не обнаружено.`;
    $('#discBody').innerHTML = devs.map((d, i) => `
      <tr data-i="${i}">
        <td class="mono">${esc(d.ip)}</td>
        <td>${esc(d.vendor || '—')}</td>
        <td>${(d.open_ports || []).map((p) => `<span class="port">${p}</span>`).join('')}</td>
        <td class="mono">${esc(d.suggested_url || '')}</td>
        <td><button class="btn sm" type="button" data-add ${d.already_added ? 'disabled' : ''}>${d.already_added ? 'Добавлено' : 'Добавить'}</button></td>
      </tr>`).join('');
    $$('#discBody [data-add]').forEach((b) => b.addEventListener('click', async () => {
      const d = devs[Number(b.closest('tr').dataset.i)];
      b.disabled = true;
      try {
        await api('/api/cameras', {
          method: 'POST',
          body: { name: `${d.vendor || 'Камера'} ${d.ip}`, type: d.suggested_type || 'rtsp', source_url: d.suggested_url, gauge_type: 'pressure' },
        });
        b.textContent = 'Добавлено';
      } catch (ex) {
        b.disabled = false;
        toast(ex.message, 'err');
      }
    }));
    $('#discTable').hidden = devs.length === 0;
  } catch (ex) {
    $('#discStatus').textContent = `Ошибка сканирования: ${ex.message}`;
  } finally {
    btn.disabled = false;
  }
}

export function initDevices() {
  addFields = bindSourceFields($('#addForm'));
  $('#addForm').addEventListener('submit', submitAddCamera);
  $('#btnScan').addEventListener('click', runDiscovery);

  $('#btnCamShowQr').addEventListener('click', () => ensureQrSession(null, false));
  $('#btnCamRegenQr').addEventListener('click', () => ensureQrSession(null, true));
  $('#btnDlgRegenQr').addEventListener('click', () => ensureQrSession(null, true));

  $('#btnCamCopyUrl').addEventListener('click', () => copyText($('#camQrUrl').textContent));
  $('#btnCopyUrl').addEventListener('click', () => copyText($('#pUrl').textContent));
  $('#btnDlgGoCameras').addEventListener('click', () => { $('#dlgPhone').close(); setView('cameras'); });

  $('#btnCamRestart').addEventListener('click', async () => {
    const cam = livePrimaryCam();
    if (!cam) return;
    try {
      await api(`/api/cameras/${encodeURIComponent(cam.id)}/restart`, { method: 'POST' });
      toast(`Поток перезапущен: ${cam.data.name}`);
    } catch (e) {
      toast(e.message, 'err');
    }
  });
  $('#btnCamOpenCal').addEventListener('click', () => {
    const cam = livePrimaryCam();
    if (cam) openCalibrationFor(cam.id);
  });
  $('#btnCamOpenMonitor').addEventListener('click', () => {
    const cam = livePrimaryCam();
    if (cam) jumpToInstrument(cam.id);
  });

  $$('#segCamPreview [data-cprev]').forEach((b) => {
    b.addEventListener('click', () => {
      previewMode = b.dataset.cprev;
      $$('#segCamPreview [data-cprev]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    });
  });

  $$('dialog [data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    if (b.dataset.act === 'add') { addFields.set({}); $('#dlgAdd').showModal(); }
    if (b.dataset.act === 'discover') { $('#dlgDiscover').showModal(); }
    if (b.dataset.act === 'phone') openPhoneDialog();
  });

  on('view', (v) => {
    if (v === 'cameras') {
      if (!activeQrSession) ensureQrSession(null, false).catch(() => {});
      renderCamerasView();
      syncCamPreview();
    } else {
      stopCamPreview();
    }
  });
  on('status', () => { if (state.view === 'cameras' || $('#dlgPhone').open) renderCamerasView(); });
  on('reading', () => { if (state.view === 'cameras') renderCamerasView(); });
  on('cams', () => { if (state.view === 'cameras') renderCamerasView(); });
}
