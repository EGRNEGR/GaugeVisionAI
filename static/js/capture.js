/* =========================================================================
   GaugeVision AI — клиент захвата «Смартфон как камера» (Zero-Install Mobile Node)
   • Выбор объектива: основной 1×, ультраширокий 0.5×, телефото 2×/3×/5×, фронтальный
   • Зум: track.applyConstraints({advanced:[{zoom}]}) c валидацией getCapabilities().zoom,
     при отсутствии аппаратного зума — программный (кадрирование)
   • Фонарик (Torch API), удержание экрана (Wake Lock API)
   • Передача JPEG/WebP-кадров по WSS 3–5 к/с с подтверждением (backpressure)
   ========================================================================= */
(() => {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const params = new URLSearchParams(location.search);
  const camId = params.get('cam_id');
  const token = params.get('token');

  const video = $('#video');
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

  function stopStream() {
    if (st.stream) st.stream.getTracks().forEach((t) => t.stop());
    st.stream = null;
    st.track = null;
    st.torch = false;
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

  let zoomBusy = false, zoomPending = null;
  async function applyZoom(v) {
    const slider = $('#zoom');
    if (st.hwZoom) {
      const caps = st.track.getCapabilities();
      // валидация по возможностям устройства
      const z = Math.min(caps.zoom.max, Math.max(caps.zoom.min, Number(v)));
      if (zoomBusy) { zoomPending = z; return; }
      zoomBusy = true;
      try {
        await st.track.applyConstraints({ advanced: [{ zoom: z }] });
      } catch (e) {
        console.warn('zoom', e);
      } finally {
        zoomBusy = false;
        if (zoomPending !== null) { const p = zoomPending; zoomPending = null; applyZoom(p); }
      }
      $('#zoomVal').textContent = `${z.toFixed(1)}×`;
    } else {
      st.swZoom = Math.min(4, Math.max(1, Number(v)));
      applySwZoomPreview();
      $('#zoomVal').textContent = `${st.swZoom.toFixed(1)}×`;
    }
    slider.value = v;
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
    if (!st.track) return;
    const want = !st.torch;
    try {
      await st.track.applyConstraints({ advanced: [{ torch: want }] });
      st.torch = want;
      $('#btnTorch').classList.toggle('on', want);
    } catch (e) {
      toastLike('Не удалось переключить фонарик');
    }
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
      ? `<span class="live-dot"></span>${s.fps.toFixed(1)} к/с · ${s.kb.toFixed(0)} КБ<br>${fmtName} · RTT ${s.rtt} мс`
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
    updateStats();
  }

  $('#btnStream').addEventListener('click', () => (st.streaming ? stopStreaming() : startStreaming()));

  document.addEventListener('visibilitychange', async () => {
    if (document.hidden) return;
    if (st.streaming && !st.wakeLock) requestWakeLock();
    // iOS/Android останавливают камеру в фоне — восстанавливаем
    if (!st.track || st.track.readyState === 'ended') {
      try { await selectLens(st.lensKey); } catch (_) { /* покажется ниже */ }
    }
  });

  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
    navigator.mediaDevices.addEventListener('devicechange', () => buildLensList());
  }

  function updateInfo() {
    const settings = st.track && st.track.getSettings ? st.track.getSettings() : {};
    const lens = st.lenses.find((l) => l.key === st.lensKey);
    $('#camInfo').textContent = `${lens ? lens.label : '—'} · ${settings.width || '?'}×${settings.height || '?'}`;
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
    } catch (e) {
      const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
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
