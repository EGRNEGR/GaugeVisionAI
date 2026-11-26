/* =========================================================================
   GaugeVision AI — клиент захвата «Смартфон как камера» (Zero-Install Mobile Node)
   • Выбор объектива: основной 1×, ультраширокий 0.5×, телефото 2×/3×/5×, фронтальный
   • Зум: track.applyConstraints({advanced:[{zoom}]}) c валидацией getCapabilities().zoom,
     при отсутствии аппаратного зума — программный (кадрирование)
   • Фонарик (Torch API), удержание экрана (Wake Lock API)
   • Автофокус по точке касания на объективах с поддержкой настройки фокуса
   • Передача JPEG/WebP-кадров по WSS 3–5 к/с с подтверждением (backpressure)
   ========================================================================= */
(() => {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const params = new URLSearchParams(location.search);
  const camId = params.get('cam_id');
  const token = params.get('token');

  const video = $('#video');
  const focusTarget = $('#focusTarget');
  const focusMarker = $('#focusMarker');
  const focusHint = $('#focusHint');
  const canvas = document.createElement('canvas');
  const ctx2d = canvas.getContext('2d', { alpha: false });

  const st = {
    stream: null,
    track: null,
    lenses: [],               // [{key, label, constraints, deviceId}]
    lensKey: 'main',
    hwZoom: false,
    swZoom: 1,
    torch: false,
    ws: null,
    wsAttempt: 0,
    wsFatal: false,
    streaming: false,
    inflight: false,
    sentAt: 0,
    loopTimer: null,
    wakeLock: null,
    mime: 'image/jpeg',
    unit: '',
    stats: { frames: 0, bytes: 0, t0: performance.now(), rtt: 0, fps: 0, kb: 0 },
  };

  // ---------------------------------------------------------------------
  // Сообщения / статус
  // ---------------------------------------------------------------------
  function showMsg(title, text, retry = null) {
    $('#msgTitle').textContent = title;
    $('#msgText').innerHTML = text;
    const btn = $('#msgBtn');
    btn.classList.toggle('hidden', !retry);
    btn.onclick = retry;
    $('#msg').classList.remove('hidden');
  }
  const hideMsg = () => $('#msg').classList.add('hidden');

  function setConn(kind, text) {
    $('#connBadge').className = `badge st-${kind}`;
    $('#connText').textContent = text;
  }

  // ---------------------------------------------------------------------
  // Камера и объективы
  // ---------------------------------------------------------------------
  const BASE_VIDEO = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30, max: 30 } };
  let cameraControls = Promise.resolve();
  let appliedControls = {};

  function applyCameraControls(track, changes) {
    // applyConstraints заменяет набор ограничений. Храним настройки объектива вместе.
    const request = cameraControls.then(async () => {
      if (track !== st.track || track.readyState !== 'live') return false;
      const next = { ...appliedControls, ...changes };
      await track.applyConstraints({ advanced: [next] });
      if (track !== st.track) return false;
      appliedControls = next;
      return true;
    });
    cameraControls = request.catch(() => {});
    return request;
  }

  function stopStream() {
    if (st.stream) st.stream.getTracks().forEach((t) => t.stop());
    st.stream = null;
    st.track = null;
    st.torch = false;
    cameraControls = Promise.resolve();
    appliedControls = {};
    resetFocus();
  }

  async function openCamera(constraints) {
    stopStream();
    const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { ...BASE_VIDEO, ...constraints } });
    st.stream = stream;
    st.track = stream.getVideoTracks()[0];
    video.srcObject = stream;
    await video.play().catch(() => {});
    st.track.addEventListener('ended', () => {
      if (!document.hidden) setTimeout(() => selectLens(st.lensKey), 500);
    });
    setupZoom();
    setupTorch();
    setupFocus(st.track);
    return st.track;
  }

  function classifyLens(label) {
    const l = (label || '').toLowerCase();
    if (/front|user|передн|фронт|selfie|facing front/.test(l)) return 'front';
    if (/ultra|сверхшир|ультра|0[.,]5/.test(l)) return 'ultra';
    if (/tele|телефото/.test(l)) return 'tele';
    if (/dual|triple|двойн|тройн/.test(l)) return 'multi';
    if (/back|rear|environment|задн|основ|facing back/.test(l)) return 'back';
    return 'other';
  }

  async function buildLensList() {
    const mainId = st.track && st.track.getSettings ? st.track.getSettings().deviceId : null;
    let devices = [];
    try { devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput'); } catch (_) { /* нет доступа */ }

    const lenses = [{ key: 'main', label: '1× Основная', constraints: { facingMode: { ideal: 'environment' } } }];
    const tele = [], ultra = [], multi = [], back = [], other = [];
    let hasFront = false;
    devices.forEach((d) => {
      if (d.deviceId && d.deviceId === mainId) return;      // основной объектив уже в списке
      const kind = classifyLens(d.label);
      const item = { deviceId: d.deviceId, rawLabel: d.label };
      if (kind === 'front') { hasFront = true; return; }
      ({ tele, ultra, multi, back, other })[kind].push(item);
    });
    ultra.forEach((u, i) => lenses.push({ key: `dev:${u.deviceId}`, label: ultra.length > 1 ? `0.5× Ультраширокий ${i + 1}` : '0.5× Ультраширокий', constraints: { deviceId: { exact: u.deviceId } } }));
    const teleNames = ['2×', '3×', '5×'];
    tele.forEach((t, i) => lenses.push({ key: `dev:${t.deviceId}`, label: `${tele.length > 1 ? (teleNames[i] || `${i + 2}×`) : '2–5×'} Телефото`, constraints: { deviceId: { exact: t.deviceId } } }));
    multi.forEach((m) => lenses.push({ key: `dev:${m.deviceId}`, label: `Авто: ${m.rawLabel.replace(/camera/i, '').trim()}`, constraints: { deviceId: { exact: m.deviceId } } }));
    back.concat(other).forEach((b, i) => lenses.push({ key: `dev:${b.deviceId}`, label: b.rawLabel ? `Задняя: ${b.rawLabel.replace(/camera2?/i, '').trim()}` : `Камера ${i + 2}`, constraints: { deviceId: { exact: b.deviceId } } }));
    if (hasFront || devices.length === 0) lenses.push({ key: 'front', label: 'Фронтальная', constraints: { facingMode: { exact: 'user' } } });
    st.lenses = lenses;
    renderLenses();
  }

  function renderLenses() {
    const row = $('#lensRow');
    row.innerHTML = '';
    for (const lens of st.lenses) {
      const b = document.createElement('button');
      b.className = `lens-btn${lens.key === st.lensKey ? ' active' : ''}`;
      b.textContent = lens.label;
      b.title = lens.rawLabel || lens.label;
      b.addEventListener('click', () => selectLens(lens.key));
      row.appendChild(b);
    }
  }

  async function selectLens(key) {
    const lens = st.lenses.find((l) => l.key === key) || st.lenses[0];
    try {
      await openCamera(lens.constraints);
      st.lensKey = lens.key;
      video.style.transform = lens.key === 'front' ? 'scaleX(-1)' : '';
    } catch (e) {
      console.warn('lens', e);
      if (lens.key !== 'main') {
        toastLike(`Объектив недоступен: ${e.name || e.message}`);
        await openCamera(st.lenses[0].constraints).catch(() => {});
        st.lensKey = 'main';
      } else {
        throw e;
      }
    }
    renderLenses();
    applySwZoomPreview();
  }

  function toastLike(text) {
    $('#camInfo').textContent = text;
    setTimeout(updateInfo, 3500);
  }

  // ---------------------------------------------------------------------
  // Зум
  // ---------------------------------------------------------------------
  function setupZoom() {
    const slider = $('#zoom');
    const caps = st.track && st.track.getCapabilities ? st.track.getCapabilities() : {};
    const settings = st.track && st.track.getSettings ? st.track.getSettings() : {};
    if (caps.zoom && typeof caps.zoom.max === 'number' && caps.zoom.max > caps.zoom.min) {
      st.hwZoom = true;
      st.swZoom = 1;
      slider.min = caps.zoom.min;
      slider.max = caps.zoom.max;
      slider.step = caps.zoom.step || 0.1;
      slider.value = settings.zoom || caps.zoom.min;
      $('#zoomKind').textContent = 'камера';
    } else {
      st.hwZoom = false;
      slider.min = 1; slider.max = 4; slider.step = 0.1;
      slider.value = st.swZoom;
      $('#zoomKind').textContent = 'цифровой';
    }
    slider.disabled = false;
    $('#zoomVal').textContent = `${Number(slider.value).toFixed(1)}×`;
  }

  let zoomUpdate = null;
  async function applyZoom(v) {
    const slider = $('#zoom');
    const track = st.track;
    if (!track) return;
    if (st.hwZoom) {
      const caps = track.getCapabilities();
      // валидация по возможностям устройства
      const z = Math.min(caps.zoom.max, Math.max(caps.zoom.min, Number(v)));
      if (zoomUpdate?.track === track) {
        zoomUpdate.pending = z;
        return;
      }
      const update = { track, pending: null };
      zoomUpdate = update;
      try {
        if (await applyCameraControls(track, { zoom: z })) {
          $('#zoomVal').textContent = `${z.toFixed(1)}×`;
        }
      } catch (e) {
        console.warn('zoom', e);
      } finally {
        if (zoomUpdate === update) {
          zoomUpdate = null;
          if (update.pending !== null && track === st.track) applyZoom(update.pending);
        }
      }
    } else {
      st.swZoom = Math.min(4, Math.max(1, Number(v)));
      applySwZoomPreview();
      $('#zoomVal').textContent = `${st.swZoom.toFixed(1)}×`;
      slider.value = v;
    }
  }

  function applySwZoomPreview() {
    const mirror = st.lensKey === 'front' ? ' scaleX(-1)' : '';
    video.style.transform = `scale(${st.hwZoom ? 1 : st.swZoom})${mirror}`;
  }

  $('#zoom').addEventListener('input', (e) => applyZoom(e.target.value));

  // ---------------------------------------------------------------------
  // Фонарик
  // ---------------------------------------------------------------------
  function setupTorch() {
    const caps = st.track && st.track.getCapabilities ? st.track.getCapabilities() : {};
    const btn = $('#btnTorch');
    btn.disabled = !caps.torch;
    btn.classList.remove('on');
    btn.title = caps.torch ? 'Фонарик' : 'Фонарик недоступен для этого объектива';
  }
  $('#btnTorch').addEventListener('click', async () => {
    const track = st.track;
    if (!track) return;
    const want = !st.torch;
    try {
      if (!await applyCameraControls(track, { torch: want })) return;
      st.torch = want;
      $('#btnTorch').classList.toggle('on', want);
    } catch (e) {
      if (track === st.track) toastLike('Не удалось переключить фонарик');
    }
  });

  // ---------------------------------------------------------------------
  // Автофокус
  // ---------------------------------------------------------------------
  const FOCUS_HINT = 'Коснитесь циферблата, чтобы сфокусировать камеру';
  let focusTimer = null;
  let focusRequest = 0;

  function resetFocus() {
    focusRequest++;
    clearTimeout(focusTimer);
    focusTarget.classList.add('hidden');
    focusMarker.classList.add('hidden');
    focusHint.classList.add('hidden');
  }

  function setupFocus(track) {
    const modes = track.getCapabilities?.().focusMode ?? [];
    const continuous = modes.includes('continuous');
    const point = navigator.mediaDevices.getSupportedConstraints?.().pointsOfInterest;
    focusTarget.classList.toggle('hidden', !continuous || !point);
    focusHint.classList.toggle('hidden', !continuous || !point);
    focusHint.textContent = FOCUS_HINT;
    if (continuous && track.getSettings?.().focusMode !== 'continuous') {
      applyCameraControls(track, { focusMode: 'continuous' }).catch((e) => console.warn('focus', e));
    }
  }

  focusTarget.addEventListener('click', async (ev) => {
    const track = st.track;
    const { videoWidth, videoHeight } = video;
    if (!track || track.readyState !== 'live' || !videoWidth || !videoHeight) return;

    // object-fit: contain. Границы видео уже включают CSS-зум, но не поля вокруг кадра.
    const rect = video.getBoundingClientRect();
    const scale = Math.min(rect.width / videoWidth, rect.height / videoHeight);
    if (!scale) return;
    const width = videoWidth * scale;
    const height = videoHeight * scale;
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const clientX = ev.detail ? ev.clientX : centerX;
    const clientY = ev.detail ? ev.clientY : centerY;
    const x = 0.5 + (clientX - centerX) / width;
    const y = 0.5 + (clientY - centerY) / height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;

    const targetRect = focusTarget.getBoundingClientRect();
    focusMarker.style.left = `${clientX - targetRect.left}px`;
    focusMarker.style.top = `${clientY - targetRect.top}px`;
    focusMarker.classList.remove('hidden');
    clearTimeout(focusTimer);
    const request = ++focusRequest;
    focusHint.textContent = 'Настраиваем фокус…';

    const point = { x: st.lensKey === 'front' ? 1 - x : x, y };
    let message = 'Запрос фокуса отправлен';
    try {
      if (!await applyCameraControls(track, { focusMode: 'continuous', pointsOfInterest: [point] })) return;
    } catch (e) {
      console.warn('focus', e);
      message = 'Камера не приняла запрос фокуса';
    }
    if (track !== st.track || request !== focusRequest) return;
    focusHint.textContent = message;
    focusTimer = setTimeout(() => {
      focusMarker.classList.add('hidden');
      focusHint.textContent = FOCUS_HINT;
    }, 1800);
  });

  // ---------------------------------------------------------------------
  // WebSocket (WSS) к серверу
  // ---------------------------------------------------------------------
  function connectWs() {
    if (st.wsFatal) return;
    const url = `wss://${location.host}/ws/phone/${encodeURIComponent(camId)}?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    st.ws = ws;
    setConn('reconnecting', 'Подключение…');
    let ping = null;

    ws.onopen = () => {
      st.wsAttempt = 0;
      st.inflight = false;
      setConn(st.streaming ? 'online' : 'reconnecting', st.streaming ? 'В эфире' : 'Подключено');
      sendClientState(st.streaming ? 'streaming' : (st.track ? 'camera_ready' : 'awaiting_permission'));
      ping = setInterval(() => { if (ws.readyState === 1 && !st.streaming) ws.send(JSON.stringify({ type: 'ping', t: Date.now() })); }, 15000);
    };
    ws.onmessage = (ev) => {
      let m;
      try { m = JSON.parse(ev.data); } catch (_) { return; }
      if (m.type === 'hello') {
        $('#camName').textContent = m.name;
        st.unit = m.unit;
        $('#readingUnit').textContent = ` ${m.unit}`;
        if (m.fps) $('#fps').value = String(Math.round(m.fps));
        updateInfo();
      } else if (m.type === 'ack') {
        st.inflight = false;
        st.stats.rtt = Math.round(performance.now() - st.sentAt);
        if (m.unit) st.unit = m.unit;
        showReading(m.reading);
      } else if (m.type === 'error') {
        toastLike(m.message);
      }
    };
    ws.onclose = (ev) => {
      clearInterval(ping);
      st.inflight = false;
      if (ev.code === 4401) {
        st.wsFatal = true;
        setConn('offline', 'Сессия недействительна');
        showMsg('Сессия недействительна', 'Токен устарел (например, сервер был перезапущен) или прибор удалён. На дашборде нажмите «QR» на карточке смартфона и отсканируйте новый код.');
        stopStreaming();
        return;
      }
      setConn('reconnecting', 'Переподключение…');
      const seq = [1, 2, 4, 8, 15];   // exponential backoff
      const d = seq[Math.min(st.wsAttempt, seq.length - 1)];
      st.wsAttempt++;
      setTimeout(connectWs, d * 1000);
    };
    ws.onerror = () => {};
  }

  function sendClientState(stateName, errorText = null) {
    if (st.ws && st.ws.readyState === 1) {
      try {
        st.ws.send(JSON.stringify({ type: 'client_state', state: stateName, error: errorText }));
      } catch (_) { /* сокет закрывается */ }
    }
  }

  function showReading(r) {
    const el = $('#reading');
    el.className = 'cap-reading';
    if (!r || r.value === null || r.value === undefined) {
      el.firstChild.textContent = '—';
      return;
    }
    el.firstChild.textContent = Number(r.value).toFixed(Math.abs(r.value) < 10 ? 2 : 1);
    $('#readingUnit').textContent = ` ${st.unit}${r.valid ? '' : ' (посл.)'}`;
    if (r.level && r.level !== 'normal') el.classList.add(`level-${r.level}`);
  }

  // ---------------------------------------------------------------------
  // Передача кадров
  // ---------------------------------------------------------------------
  function detectMime() {
    try {
      const c = document.createElement('canvas');
      c.width = c.height = 2;
      if (c.toDataURL('image/webp').startsWith('data:image/webp')) return 'image/webp';
    } catch (_) { /* нет поддержки */ }
    return 'image/jpeg';
  }

  function grabFrame() {
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) return null;
    const z = st.hwZoom ? 1 : st.swZoom;
    const sw = vw / z, sh = vh / z;
    const sx = (vw - sw) / 2, sy = (vh - sh) / 2;
    const maxW = Number($('#quality').value) || 1280;
    const k = Math.min(1, maxW / Math.max(sw, sh));
    const cw = Math.round(sw * k), ch = Math.round(sh * k);
    if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
    ctx2d.drawImage(video, sx, sy, sw, sh, 0, 0, cw, ch);
    return new Promise((resolve) => canvas.toBlob(resolve, st.mime, 0.82));
  }

  async function loop() {
    if (!st.streaming) return;
    const t0 = performance.now();
    const interval = 1000 / (Number($('#fps').value) || 4);
    try {
      const ws = st.ws;
      if (st.inflight && t0 - st.sentAt > 4000) st.inflight = false;   // потеря ack
      if (ws && ws.readyState === 1 && !st.inflight && video.readyState >= 2 && ws.bufferedAmount < 512 * 1024) {
        const blob = await grabFrame();
        if (blob && st.streaming && ws.readyState === 1) {
          st.inflight = true;
          st.sentAt = performance.now();
          ws.send(blob);
          st.stats.frames++;
          st.stats.bytes += blob.size;
        }
      }
    } catch (e) {
      console.warn('frame', e);
    }
    updateStats();
    st.loopTimer = setTimeout(loop, Math.max(10, interval - (performance.now() - t0)));
  }

  function updateStats() {
    const s = st.stats;
    const dt = (performance.now() - s.t0) / 1000;
    if (dt >= 2) {
      s.fps = s.frames / dt;
      s.kb = s.frames ? s.bytes / s.frames / 1024 : 0;
      s.frames = 0; s.bytes = 0; s.t0 = performance.now();
    }
    const fmtName = st.mime === 'image/webp' ? 'WebP' : 'JPEG';
    $('#stats').innerHTML = st.streaming
      ? `<span class="live-dot"></span>${s.fps.toFixed(1)} к/с, ${s.kb.toFixed(0)} КБ<br>${fmtName}, RTT ${s.rtt} мс`
      : `${video.videoWidth || 0}×${video.videoHeight || 0}`;
  }

  async function requestWakeLock() {
    try {
      if ('wakeLock' in navigator) {
        st.wakeLock = await navigator.wakeLock.request('screen');
        st.wakeLock.addEventListener('release', () => { st.wakeLock = null; });
      }
    } catch (_) { /* не поддерживается / отклонено */ }
  }

  function startStreaming() {
    st.streaming = true;
    st.stats = { frames: 0, bytes: 0, t0: performance.now(), rtt: 0, fps: 0, kb: 0 };
    const btn = $('#btnStream');
    btn.textContent = '■ Остановить';
    btn.classList.add('live');
    if (st.ws && st.ws.readyState === 1) setConn('online', 'В эфире');
    sendClientState('streaming');
    requestWakeLock();
    loop();
  }

  function stopStreaming() {
    st.streaming = false;
    clearTimeout(st.loopTimer);
    const btn = $('#btnStream');
    btn.textContent = '▶ Начать трансляцию';
    btn.classList.remove('live');
    if (st.wakeLock) { st.wakeLock.release().catch(() => {}); st.wakeLock = null; }
    if (st.ws && st.ws.readyState === 1) setConn('reconnecting', 'Подключено (пауза)');
    sendClientState('paused');
    updateStats();
  }

  $('#btnStream').addEventListener('click', () => (st.streaming ? stopStreaming() : startStreaming()));

  document.addEventListener('visibilitychange', async () => {
    if (document.hidden) {
      if (st.streaming) sendClientState('paused', 'экран смартфона свёрнут или выключен');
      return;
    }
    if (st.streaming && !st.wakeLock) requestWakeLock();
    // iOS/Android останавливают камеру в фоне — восстанавливаем
    if (!st.track || st.track.readyState === 'ended') {
      try { await selectLens(st.lensKey); } catch (_) { /* покажется ниже */ }
    }
    sendClientState(st.streaming ? 'streaming' : 'camera_ready');
  });

  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
    navigator.mediaDevices.addEventListener('devicechange', () => buildLensList());
  }

  function updateInfo() {
    const settings = st.track && st.track.getSettings ? st.track.getSettings() : {};
    const lens = st.lenses.find((l) => l.key === st.lensKey);
    $('#camInfo').textContent = `${lens ? lens.label : '—'}, ${settings.width || '?'}×${settings.height || '?'}`;
  }

  // ---------------------------------------------------------------------
  // Запуск
  // ---------------------------------------------------------------------
  async function start() {
    if (!camId || !token) {
      showMsg('Нет параметров сессии', 'Откройте эту страницу по QR-коду с дашборда GaugeVision AI («Подключить смартфон как камеру»).');
      return;
    }
    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showMsg('Нужно защищённое соединение (HTTPS)',
        'Браузер запрещает доступ к камере по незащищённому соединению. Откройте адрес, начинающийся с <b>https://</b>, и примите самоподписный сертификат сервера (Chrome: «Дополнительно» → «Перейти на сайт»; Safari: «Подробнее» → «посетить этот веб-сайт»).');
      return;
    }
    st.mime = detectMime();
    // Сессия WSS поднимается сразу — статус виден, пока пользователь отвечает на запрос камеры
    if (!st.ws) connectWs();
    try {
      await openCamera(st.lenses.length ? st.lenses[0].constraints : { facingMode: { ideal: 'environment' } });
      hideMsg();
      sendClientState(st.streaming ? 'streaming' : 'camera_ready');
    } catch (e) {
      const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
      sendClientState(denied ? 'permission_denied' : 'camera_error', e && (e.name || e.message));
      showMsg(denied ? 'Доступ к камере запрещён' : 'Камера недоступна',
        denied
          ? 'Разрешите доступ к камере для этого сайта в настройках браузера (iOS: Настройки → Safari → Камера; Chrome: значок замка → Разрешения) и нажмите «Повторить».'
          : `Ошибка: ${e && (e.name || e.message)}. Закройте другие приложения, использующие камеру, и повторите.`,
        () => { hideMsg(); start(); });
      return;
    }
    await buildLensList();
    updateInfo();
    updateStats();
  }

  start();
})();
