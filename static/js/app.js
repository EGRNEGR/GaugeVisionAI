/* =========================================================================
   GaugeVision AI — дашборд оператора
   • WebSocket-телеметрия в реальном времени (авто-переподключение)
   • Chart.js-тренды с фоновыми зонами уставок (норма / предупреждение / авария)
   • Web Audio API: синтез сигналов тревоги без MP3-файлов
   • Калибровка шкалы, уставки, поиск устройств, «смартфон как камера»
   ========================================================================= */
(() => {
  'use strict';

  // ---------------------------------------------------------------------
  // Утилиты
  // ---------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v))) ? null : Number(v);
  const LEVEL_RANK = { normal: 0, warning: 1, alert: 2 };
  const COLORS = {
    normal: '#22c55e', warning: '#f5b301', alert: '#ef4444', line: '#38bdf8',
    grid: 'rgba(138,155,176,.12)', tick: '#8a9bb0',
  };
  const STATUS_TEXT = { online: 'В сети', reconnecting: 'Переподключение', offline: 'Офлайн' };
  const LEVEL_TEXT = { normal: 'НОРМА', warning: 'ПРЕДУПРЕЖДЕНИЕ', alert: 'CRITICAL' };
  const SOURCE_TEXT = { device: 'USB/локальная', rtsp: 'RTSP', http_mjpeg: 'HTTP/MJPEG', phone_ws: 'Смартфон WSS' };
  const GAUGE_SHORT = {
    pressure: 'Давление', temperature: 'Температура', draft: 'Тяга/разрежение',
    level: 'Уровень', electrical: 'Электрический', flow: 'Расход',
  };
  const MAX_POINTS = 120;
  const PREVIEW_INTERVAL_MS = 350;

  async function api(path, opts = {}) {
    const init = { method: 'GET', headers: {}, ...opts };
    if (init.body && typeof init.body !== 'string') {
      init.body = JSON.stringify(init.body);
      init.headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(path, init);
    if (res.status === 204) return null;
    let data = null;
    try { data = await res.json(); } catch (_) { /* пустой ответ */ }
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      if (data && data.detail) {
        msg = Array.isArray(data.detail)
          ? data.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
          : data.detail;
      }
      throw new Error(msg);
    }
    return data;
  }

  function toast(msg, kind = 'ok', ms = 4000) {
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = msg;
    $('#toasts').appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  function decimalsFor(cam) {
    const c = cam.calibration || {};
    const span = Math.abs((num(c.v_max) ?? 10) - (num(c.v_min) ?? 0)) || 10;
    if (span <= 1) return 3;
    if (span <= 20) return 2;
    if (span <= 200) return 1;
    return 0;
  }
  const fmt = (v, d) => (v === null || v === undefined) ? '—' : Number(v).toFixed(d);
  const timeStr = (iso) => { try { return new Date(iso).toLocaleTimeString('ru-RU'); } catch (_) { return '—'; } };

  // ---------------------------------------------------------------------
  // Состояние
  // ---------------------------------------------------------------------
  const state = {
    meta: null,
    cams: new Map(),          // id -> { data, el, chart, points, win, ... }
    ws: null,
    wsAttempt: 0,
    acked: new Map(),         // id -> квитированный уровень
    editingId: null,
    phoneCamId: null,
  };

  // ---------------------------------------------------------------------
  // Web Audio API — синтезатор тревоги
  // ---------------------------------------------------------------------
  const Sound = {
    ctx: null,
    enabled: localStorage.getItem('gv.sound') !== 'off',
    mode: 'none',
    nodes: [],
    timer: null,

    ensure() {
      if (!this.ctx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return null;
        this.ctx = new AC();
      }
      if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
      return this.ctx;
    },
    get ready() { return !!this.ctx && this.ctx.state === 'running'; },

    stop() {
      clearInterval(this.timer);
      this.timer = null;
      for (const n of this.nodes) { try { n.stop ? n.stop() : null; } catch (_) {} try { n.disconnect(); } catch (_) {} }
      this.nodes = [];
    },

    beep(freq, at, dur, vol = 0.18) {
      const ctx = this.ctx;
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = 'square';
      osc.frequency.value = freq;
      const t = ctx.currentTime + at;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(vol, t + 0.015);
      g.gain.setValueAtTime(vol, t + dur - 0.03);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      osc.connect(g).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + dur + 0.02);
    },

    // Warning: дискретный двухтональный сигнал 440 Гц / 880 Гц
    startWarning() {
      const play = () => { if (this.ready) { this.beep(440, 0, 0.22); this.beep(880, 0.28, 0.22); } };
      play();
      this.timer = setInterval(play, 1800);
    },

    // Alert: непрерывная промышленная сирена, ЧМ 600–1200 Гц
    startAlert() {
      const ctx = this.ctx;
      const osc = ctx.createOscillator();
      const lfo = ctx.createOscillator();
      const lfoGain = ctx.createGain();
      const filter = ctx.createBiquadFilter();
      const out = ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.value = 900;           // центр
      lfo.type = 'sine';
      lfo.frequency.value = 0.8;           // скорость качания сирены, Гц
      lfoGain.gain.value = 300;            // девиация ±300 → 600…1200 Гц
      filter.type = 'lowpass';
      filter.frequency.value = 2600;
      out.gain.value = 0.0001;
      out.gain.exponentialRampToValueAtTime(0.14, ctx.currentTime + 0.15);
      lfo.connect(lfoGain).connect(osc.frequency);
      osc.connect(filter).connect(out).connect(ctx.destination);
      osc.start();
      lfo.start();
      this.nodes = [osc, lfo, lfoGain, filter, out];
    },

    setMode(mode) {
      if (!this.enabled) mode = 'none';
      if (mode === this.mode) return;
      this.stop();
      this.mode = mode;
      if (mode !== 'none') {
        if (!this.ensure()) return;
        if (mode === 'alert') this.startAlert();
        else this.startWarning();
      }
      const btn = $('#btnSound');
      btn.classList.toggle('sounding', mode !== 'none');
    },

    toggle() {
      this.enabled = !this.enabled;
      localStorage.setItem('gv.sound', this.enabled ? 'on' : 'off');
      if (this.enabled) this.ensure();
      const prev = this.mode;
      this.mode = 'none';
      this.setMode(this.enabled ? prev : 'none');
      updateSoundButton();
      evaluateAlarms();
      if (this.enabled && this.ready) this.beep(880, 0, 0.08, 0.08);
    },
  };

  function updateSoundButton() {
    const on = Sound.enabled;
    const blocked = on && !Sound.ready;
    $('#soundIco').textContent = on ? (blocked ? '🔈' : '🔊') : '🔇';
    $('#soundLbl').textContent = on ? (blocked ? 'Нажмите для звука' : 'Звук вкл.') : 'Звук выкл.';
    $('#btnSound').title = blocked
      ? 'Браузер блокирует звук до первого нажатия на страницу'
      : 'Звуковая сигнализация';
  }

  // Браузеры разрешают звук только после жеста пользователя
  ['pointerdown', 'keydown', 'touchend'].forEach((ev) => document.addEventListener(ev, () => {
    if (Sound.enabled) {
      Sound.ensure();
      setTimeout(() => {
        updateSoundButton();
        if (Sound.ready && Sound.mode !== 'none' && Sound.nodes.length === 0 && !Sound.timer) {
          const m = Sound.mode; Sound.mode = 'none'; Sound.setMode(m);
        }
      }, 60);
    }
  }, { passive: true }));

  // ---------------------------------------------------------------------
  // Chart.js: плагин фоновых зон уставок
  // ---------------------------------------------------------------------
  function computeBands(thr, lo, hi) {
    const LL = num(thr.ll_alert), L = num(thr.l_warn), H = num(thr.h_warn), HH = num(thr.hh_alert);
    const bands = [];
    if (LL !== null) bands.push({ from: lo, to: LL, c: 'alert' });
    if (L !== null) bands.push({ from: LL ?? lo, to: L, c: 'warning' });
    bands.push({ from: L ?? LL ?? lo, to: H ?? HH ?? hi, c: 'normal' });
    if (H !== null) bands.push({ from: H, to: HH ?? hi, c: 'warning' });
    if (HH !== null) bands.push({ from: HH, to: hi, c: 'alert' });
    return { bands, lines: [[LL, 'alert'], [L, 'warning'], [H, 'warning'], [HH, 'alert']].filter((x) => x[0] !== null) };
  }

  const zonesPlugin = {
    id: 'gvZones',
    beforeDatasetsDraw(chart, _args, opts) {
      const area = chart.chartArea;
      const y = chart.scales.y;
      if (!area || !y || !opts || !opts.thresholds) return;
      const { ctx } = chart;
      const { bands, lines } = computeBands(opts.thresholds, y.min, y.max);
      ctx.save();
      ctx.beginPath();
      ctx.rect(area.left, area.top, area.right - area.left, area.bottom - area.top);
      ctx.clip();
      const alpha = { normal: 0.10, warning: 0.16, alert: 0.18 };
      for (const b of bands) {
        const lo = Math.max(Math.min(b.from, b.to), y.min - 1e9);
        const hi = Math.max(b.from, b.to);
        const top = y.getPixelForValue(Math.min(hi, y.max + (y.max - y.min)));
        const bot = y.getPixelForValue(Math.max(lo, y.min - (y.max - y.min)));
        ctx.fillStyle = hexA(COLORS[b.c], alpha[b.c]);
        ctx.fillRect(area.left, top, area.right - area.left, bot - top);
      }
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      for (const [v, c] of lines) {
        const py = y.getPixelForValue(v);
        ctx.strokeStyle = hexA(COLORS[c], 0.75);
        ctx.beginPath(); ctx.moveTo(area.left, py); ctx.lineTo(area.right, py); ctx.stroke();
      }
      ctx.restore();
    },
  };
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  if (window.Chart) Chart.register(zonesPlugin);

  function yBounds(cam) {
    const c = cam.calibration || {};
    const a = num(c.v_min) ?? 0, b = num(c.v_max) ?? 10;
    const lo = Math.min(a, b), hi = Math.max(a, b);
    const pad = (hi - lo) * 0.05 || 1;
    return { min: lo - pad, max: hi + pad };
  }

  function makeChart(canvas, cam) {
    if (!window.Chart) return null;
    const b = yBounds(cam);
    return new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: [], datasets: [{
        data: [], levels: [], borderColor: COLORS.line, borderWidth: 2, pointRadius: 0, pointHitRadius: 6,
        tension: 0.25, fill: false,
        segment: { borderColor: (ctx) => COLORS[ctx.chart.data.datasets[0].levels[ctx.p1DataIndex]] || COLORS.line },
      }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, parsing: true,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { ticks: { color: COLORS.tick, maxTicksLimit: 4, maxRotation: 0, font: { size: 10 } }, grid: { color: COLORS.grid } },
          y: { min: b.min, max: b.max, ticks: { color: COLORS.tick, maxTicksLimit: 5, font: { size: 10 } }, grid: { color: COLORS.grid } },
        },
        plugins: {
          legend: { display: false },
          gvZones: { thresholds: cam.thresholds || {} },
          tooltip: {
            callbacks: {
              label: (ctx) => `${fmt(ctx.parsed.y, decimalsFor(cam))} ${cam.unit}`,
            },
          },
        },
      },
    });
  }

  // ---------------------------------------------------------------------
  // Карточки приборов
  // ---------------------------------------------------------------------
  const io = ('IntersectionObserver' in window) ? new IntersectionObserver((entries) => {
    for (const e of entries) {
      const c = state.cams.get(e.target.dataset.id);
      if (c) c.visible = e.isIntersecting;
    }
  }, { rootMargin: '100px' }) : null;

  function createCard(data) {
    const el = $('#tplCard').content.firstElementChild.cloneNode(true);
    el.dataset.id = data.id;
    const f = (name) => $(`[data-f="${name}"]`, el);
    const c = {
      id: data.id, data, el, f, chart: null, points: [], lastPointAt: 0,
      win: Number(localStorage.getItem(`gv.win.${data.id}`)) || (state.meta ? state.meta.trend_default : 60),
      visible: true, imgTimer: null, level: 'normal', status: data.status || 'offline', reading: null,
      chartDirty: false,
    };
    state.cams.set(data.id, c);
    $('#grid').appendChild(el);
    if (io) io.observe(el);

    c.chart = makeChart(f('chart'), data);
    $$('[data-win]', el).forEach((b) => b.addEventListener('click', () => {
      c.win = Number(b.dataset.win);
      localStorage.setItem(`gv.win.${c.id}`, String(c.win));
      renderWin(c);
      scheduleChart(c);
    }));
    $('[data-act="csv"]', el).addEventListener('click', () => downloadCsv(c));
    $('[data-act="settings"]', el).addEventListener('click', () => openCameraForm(c.id));
    $('[data-act="restart"]', el).addEventListener('click', () => restartCamera(c));
    $('[data-act="delete"]', el).addEventListener('click', () => deleteCamera(c));
    $('[data-act="qr"]', el).addEventListener('click', () => openPhoneModal(c.id));
    $('[data-act="full"]', el).addEventListener('click', () => openFull(c.id));
    f('img').addEventListener('click', () => openFull(c.id));

    renderStatic(c);
    renderWin(c);
    renderStatus(c, data.status);
    if (data.reading) applyReading(c, data.reading, false);
    loadHistory(c);
    startPreview(c);
    updateEmpty();
    return c;
  }

  function renderWin(c) {
    $$('[data-win]', c.el).forEach((b) => b.classList.toggle('active', Number(b.dataset.win) === c.win));
  }

  function renderStatic(c) {
    const d = c.data;
    const g = state.meta && state.meta.gauge_types[d.gauge_type];
    c.f('name').textContent = d.name;
    c.f('name').title = d.name;
    c.f('sub').textContent = `${GAUGE_SHORT[d.gauge_type] || d.gauge_type} · ${d.unit} · ${SOURCE_TEXT[d.type] || d.type}`;
    c.f('sub').title = g ? g.label : '';
    c.f('unit').textContent = d.unit;
    $('[data-act="qr"]', c.el).classList.toggle('hidden', d.type !== 'phone_ws');

    const t = d.thresholds || {};
    const cal = d.calibration || {};
    const dec = decimalsFor(d);
    const parts = [];
    parts.push(`<span>шкала ${fmt(cal.v_min, dec)}…${fmt(cal.v_max, dec)}</span>`);
    if (num(t.ll_alert) !== null) parts.push(`<span class="l-alert">LL ${fmt(t.ll_alert, dec)}</span>`);
    if (num(t.l_warn) !== null) parts.push(`<span class="l-warn">L ${fmt(t.l_warn, dec)}</span>`);
    if (num(t.l_warn) !== null || num(t.h_warn) !== null) {
      parts.push(`<span class="l-norm">норма ${num(t.l_warn) !== null ? fmt(t.l_warn, dec) : '−∞'}…${num(t.h_warn) !== null ? fmt(t.h_warn, dec) : '+∞'}</span>`);
    }
    if (num(t.h_warn) !== null) parts.push(`<span class="l-warn">H ${fmt(t.h_warn, dec)}</span>`);
    if (num(t.hh_alert) !== null) parts.push(`<span class="l-alert">HH ${fmt(t.hh_alert, dec)}</span>`);
    c.f('limits').innerHTML = parts.join('');

    if (c.chart) {
      const b = yBounds(d);
      c.chart.options.scales.y.min = b.min;
      c.chart.options.scales.y.max = b.max;
      c.chart.options.plugins.gvZones.thresholds = t;
      scheduleChart(c);
    }
  }

  function renderStatus(c, status) {
    c.status = status || 'offline';
    const b = c.f('status');
    b.className = `badge st-${c.status}`;
    c.f('statusText').textContent = STATUS_TEXT[c.status] || c.status;
    c.el.classList.toggle('stale', c.status !== 'online');
    updateCounters();
  }

  function applyReading(c, r, live = true) {
    c.reading = r;
    const dec = decimalsFor(c.data);
    c.f('value').textContent = fmt(r.value, dec);
    c.f('angle').textContent = r.angle === null || r.angle === undefined ? '—' : Number(r.angle).toFixed(1);
    c.f('conf').textContent = r.confidence === undefined ? '—' : Number(r.confidence).toFixed(2);
    c.f('ts').textContent = r.valid ? timeStr(r.ts) : (r.last_valid_ts ? `дост. ${timeStr(r.last_valid_ts)}` : 'нет отсчёта');
    const srcTxt = { yolo: 'YOLO', ellipse: 'эллипс', opencv: 'Hough', manual: 'ручная ROI', frame: 'кадр' }[r.dial_source] || r.dial_source || '—';
    c.f('tag').textContent = `${r.valid ? 'стрелка ✓' : 'стрелка не найдена'} · ROI: ${srcTxt} · ${r.process_ms ?? '—'} мс`;
    c.el.classList.toggle('stale', c.status !== 'online' || !r.valid);
    setLevel(c, r.level || 'normal');

    if (live && r.valid && r.value !== null) {
      const now = Date.now();
      if (now - c.lastPointAt >= 1000) {   // 1 точка/с — как запись в БД
        c.lastPointAt = now;
        pushPoint(c, r.ts, r.value, r.level);
      }
    }
    if (state.editingId === c.id) updateCalibLive(c);
  }

  function setLevel(c, level) {
    if (c.level === level) return;
    const prev = c.level;
    c.level = level;
    c.el.classList.remove('level-normal', 'level-warning', 'level-alert');
    c.el.classList.add(`level-${level}`);
    c.el.classList.toggle('animate-pulse', level === 'alert');
    const b = c.f('level');
    b.className = `badge lv-${level}${level === 'alert' ? ' animate-pulse' : ''}`;
    b.textContent = LEVEL_TEXT[level] || level;
    if (level === 'normal') state.acked.delete(c.id);
    if (LEVEL_RANK[level] > LEVEL_RANK[prev]) {
      toast(`${level === 'alert' ? '🚨 АВАРИЯ' : '⚠ Предупреждение'}: ${c.data.name}`, level === 'alert' ? 'err' : 'warn', 6000);
    }
    evaluateAlarms();
  }

  function pushPoint(c, ts, value, level) {
    c.points.push({ ts, value, level });
    if (c.points.length > MAX_POINTS) c.points.splice(0, c.points.length - MAX_POINTS);
    scheduleChart(c);
  }

  function scheduleChart(c) {
    if (!c.chart || c.chartDirty) return;
    c.chartDirty = true;
    requestAnimationFrame(() => {
      c.chartDirty = false;
      if (!c.chart) return;
      const pts = c.points.slice(-c.win);
      const ds = c.chart.data.datasets[0];
      c.chart.data.labels = pts.map((p) => timeStr(p.ts));
      ds.data = pts.map((p) => p.value);
      ds.levels = pts.map((p) => p.level);
      c.chart.update('none');
    });
  }

  async function loadHistory(c) {
    try {
      const rows = await api(`/api/cameras/${c.id}/history?limit=${MAX_POINTS}`);
      const hist = rows.filter((r) => r.value !== null).map((r) => ({ ts: r.timestamp, value: r.value, level: r.status_level }));
      // объединяем с уже пришедшими живыми точками
      const lastHistTs = hist.length ? hist[hist.length - 1].ts : '';
      c.points = hist.concat(c.points.filter((p) => p.ts > lastHistTs)).slice(-MAX_POINTS);
      scheduleChart(c);
    } catch (e) {
      console.warn('history', e);
    }
  }

  function startPreview(c) {
    const tick = () => {
      if (!state.cams.has(c.id)) return;
      if (document.hidden || !c.visible) { c.imgTimer = setTimeout(tick, 1000); return; }
      const img = new Image();
      const t0 = performance.now();
      img.onload = () => {
        if (!state.cams.has(c.id)) return;
        c.f('img').src = img.src;
        const spent = performance.now() - t0;
        c.imgTimer = setTimeout(tick, Math.max(80, PREVIEW_INTERVAL_MS - spent));
      };
      img.onerror = () => { c.imgTimer = setTimeout(tick, 2500); };
      img.src = `/api/cameras/${c.id}/frame.jpg?t=${Date.now()}`;
    };
    tick();
  }

  function removeCard(id) {
    const c = state.cams.get(id);
    if (!c) return;
    clearTimeout(c.imgTimer);
    if (io) io.unobserve(c.el);
    if (c.chart) c.chart.destroy();
    c.el.remove();
    state.cams.delete(id);
    state.acked.delete(id);
    updateEmpty();
    updateCounters();
    evaluateAlarms();
  }

  function upsertCamera(data) {
    const c = state.cams.get(data.id);
    if (!c) return createCard(data);
    const calibChanged = JSON.stringify(c.data.calibration) !== JSON.stringify(data.calibration);
    c.data = data;
    renderStatic(c);
    renderStatus(c, data.status);
    if (calibChanged) { c.points = []; c.lastPointAt = 0; loadHistory(c); }
    return c;
  }

  function updateEmpty() {
    $('#emptyState').classList.toggle('hidden', state.cams.size > 0);
  }

  function updateCounters() {
    let on = 0, w = 0, a = 0;
    for (const c of state.cams.values()) {
      if (c.status === 'online') on++;
      if (c.level === 'warning') w++;
      if (c.level === 'alert') a++;
    }
    $('#cntOnline').textContent = `${on}/${state.cams.size}`;
    $('#cntWarn').textContent = w;
    $('#cntAlert').textContent = a;
  }

  // ---------------------------------------------------------------------
  // Аварийная логика: баннер, звук, квитирование
  // ---------------------------------------------------------------------
  function evaluateAlarms() {
    const alerts = [], warns = [];
    let unackedAlert = false, unackedWarn = false;
    for (const c of state.cams.values()) {
      if (c.level === 'normal') continue;
      const acked = LEVEL_RANK[state.acked.get(c.id) || 'normal'];
      const isUnacked = LEVEL_RANK[c.level] > acked;
      if (c.level === 'alert') { alerts.push(c); if (isUnacked) unackedAlert = true; }
      if (c.level === 'warning') { warns.push(c); if (isUnacked) unackedWarn = true; }
    }
    updateCounters();
    const banner = $('#alarmBanner');
    if (!alerts.length && !warns.length) {
      banner.classList.add('hidden');
      document.title = 'GaugeVision AI — Мониторинг КИПиА';
    } else {
      banner.classList.remove('hidden');
      banner.classList.toggle('warning-only', alerts.length === 0);
      banner.classList.toggle('acked', !unackedAlert && !unackedWarn);
      banner.classList.toggle('animate-pulse', unackedAlert);
      const item = (c) => `«${esc(c.data.name)}» = ${fmt(c.reading && c.reading.value, decimalsFor(c.data))} ${esc(c.data.unit)}`;
      const parts = [];
      if (alerts.length) parts.push(`CRITICAL (${alerts.length}): ${alerts.map(item).join(', ')}`);
      if (warns.length) parts.push(`Предупреждение (${warns.length}): ${warns.map(item).join(', ')}`);
      $('#alarmMsg').innerHTML = parts.join(' · ') + ((!unackedAlert && !unackedWarn) ? ' — <i>квитировано</i>' : '');
      $('#btnAck').disabled = !unackedAlert && !unackedWarn;
      document.title = `${alerts.length ? '🚨' : '⚠'} (${alerts.length + warns.length}) GaugeVision AI`;
    }
    Sound.setMode(unackedAlert ? 'alert' : (unackedWarn ? 'warning' : 'none'));
  }

  function acknowledgeLocal() {
    for (const c of state.cams.values()) {
      if (c.level !== 'normal') state.acked.set(c.id, c.level);
    }
    evaluateAlarms();
  }

  async function acknowledge() {
    acknowledgeLocal();
    try { await api('/api/alarms/ack', { method: 'POST' }); } catch (e) { toast(`Квитирование: ${e.message}`, 'err'); }
  }

  // ---------------------------------------------------------------------
  // WebSocket дашборда
  // ---------------------------------------------------------------------
  function connectWs() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard`);
    state.ws = ws;
    let pingTimer = null;
    ws.onopen = () => {
      state.wsAttempt = 0;
      setConn(true);
      pingTimer = setInterval(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping', t: Date.now() })); }, 20000);
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      handleMessage(msg);
    };
    ws.onclose = () => {
      clearInterval(pingTimer);
      setConn(false);
      const seq = [1, 2, 4, 8, 15];
      const delay = seq[Math.min(state.wsAttempt, seq.length - 1)];
      state.wsAttempt++;
      setTimeout(connectWs, delay * 1000);
    };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  function setConn(ok) {
    const chip = $('#connChip');
    chip.classList.toggle('conn-ok', ok);
    chip.classList.toggle('conn-bad', !ok);
    $('#connText').textContent = ok ? 'Сервер' : 'Нет связи';
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case 'snapshot': {
        const ids = new Set(msg.cameras.map((c) => c.id));
        for (const id of Array.from(state.cams.keys())) if (!ids.has(id)) removeCard(id);
        for (const cam of msg.cameras) {
          const c = upsertCamera(cam);
          if (cam.reading) applyReading(c, cam.reading, false);
        }
        updateEmpty();
        evaluateAlarms();
        break;
      }
      case 'reading': {
        const c = state.cams.get(msg.cam_id);
        if (c) applyReading(c, msg, true);
        break;
      }
      case 'status': {
        const c = state.cams.get(msg.cam_id);
        if (c) {
          c.data.status = msg.status;
          renderStatus(c, msg.status);
          if (msg.status === 'offline' && c.data.type !== 'phone_ws') toast(`Камера офлайн: ${c.data.name}`, 'warn');
        }
        break;
      }
      case 'camera_added':
      case 'camera_updated':
        upsertCamera(msg.camera);
        updateEmpty();
        break;
      case 'camera_deleted':
        removeCard(msg.cam_id);
        break;
      case 'ack':
        acknowledgeLocal();
        break;
      default:
        break;
    }
  }

  // ---------------------------------------------------------------------
  // Модальные окна
  // ---------------------------------------------------------------------
  const modalCleanup = new Map();
  function openModal(id, onClose) {
    $(`#${id}`).classList.remove('hidden');
    if (onClose) modalCleanup.set(id, onClose);
  }
  function closeModal(id) {
    const m = $(`#${id}`);
    if (!m || m.classList.contains('hidden')) return;
    m.classList.add('hidden');
    const fn = modalCleanup.get(id);
    modalCleanup.delete(id);
    if (fn) fn();
  }
  $$('.modal-backdrop').forEach((bd) => {
    bd.addEventListener('mousedown', (e) => { if (e.target === bd) closeModal(bd.id); });
    $$('[data-close]', bd).forEach((b) => b.addEventListener('click', () => closeModal(bd.id)));
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') $$('.modal-backdrop:not(.hidden)').forEach((m) => closeModal(m.id));
  });

  function fillGaugeSelect(sel) {
    sel.innerHTML = Object.entries(state.meta.gauge_types)
      .map(([k, g]) => `<option value="${k}" title="${esc(g.label)}">${esc(GAUGE_SHORT[k] || k)} — ${esc(g.label.split('—')[1] || g.label).trim()}</option>`).join('');
  }
  function fillUnitSelect(sel, gaugeType, current) {
    const units = state.meta.gauge_types[gaugeType].units;
    sel.innerHTML = units.map((u) => `<option value="${esc(u)}">${esc(u)}</option>`).join('');
    sel.value = units.includes(current) ? current : units[0];
  }

  // ---------------------------------------------------------------------
  // Форма прибора: добавление / калибровка / уставки
  // ---------------------------------------------------------------------
  const form = $('#camForm');
  const URL_HINTS = {
    rtsp: ['Адрес RTSP-потока', 'rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101',
      'Hikvision: /Streaming/Channels/101 · Dahua: /cam/realmonitor?channel=1&subtype=0 · RTSP Media Server: rtsp://host:8554/stream'],
    http_mjpeg: ['Адрес HTTP/MJPEG-потока', 'http://192.168.1.50:8080/video',
      'Android IP Webcam: http://IP:8080/video · DroidCam: http://IP:4747/video · ESP32-CAM: http://IP:81/stream'],
    device: ['Индекс локальной камеры', '0', 'Камера, подключённая к серверу: 0 — первая, 1 — вторая и т.д.'],
    phone_ws: ['', '', 'После сохранения будет показан QR-код для подключения смартфона.'],
  };
  function onTypeChange() {
    const t = $('#fType').value;
    const [label, ph, hint] = URL_HINTS[t];
    $('#fUrlWrap').classList.toggle('hidden', t === 'phone_ws');
    $('#fUrlLabel').textContent = label;
    $('#fUrl').placeholder = ph;
    $('#fUrlHint').textContent = hint;
  }
  $('#fType').addEventListener('change', onTypeChange);
  $('#fGaugeType').addEventListener('change', () => fillUnitSelect($('#fUnit'), $('#fGaugeType').value));
  $('#fRoiMode').addEventListener('change', () => $('#roiManual').classList.toggle('hidden', $('#fRoiMode').value !== 'manual'));
  form.addEventListener('input', (e) => { if (e.target.name !== 'name' && e.target.name !== 'source_url') renderZoneBar(); });

  let calibImgTimer = null;
  function openCameraForm(id = null) {
    state.editingId = id;
    const c = id ? state.cams.get(id) : null;
    const d = c ? c.data : null;
    form.reset();
    fillGaugeSelect($('#fGaugeType'));
    $('#camFormTitle').textContent = d ? `Настройка: ${d.name}` : 'Добавить камеру';
    $('#camFormSubmit').textContent = d ? 'Сохранить' : 'Добавить';
    const cal = d ? d.calibration : { v_min: 0, theta_min: 135, v_max: 10, theta_max: 45, direction: 'cw' };
    const thr = d ? d.thresholds : {};
    form.name.value = d ? d.name : '';
    $('#fGaugeType').value = d ? d.gauge_type : 'pressure';
    fillUnitSelect($('#fUnit'), $('#fGaugeType').value, d ? d.unit : null);
    $('#fType').value = d ? d.type : 'rtsp';
    $('#fType').disabled = false;
    form.source_url.value = d && d.source_url ? d.source_url : '';
    form.v_min.value = cal.v_min; form.v_max.value = cal.v_max;
    form.theta_min.value = Number(cal.theta_min).toFixed(1); form.theta_max.value = Number(cal.theta_max).toFixed(1);
    form.direction.value = cal.direction || 'cw';
    const roi = cal.roi || { mode: 'auto', cx: 0.5, cy: 0.5, r: 0.45 };
    $('#fRoiMode').value = roi.mode || 'auto';
    form.roi_cx.value = roi.cx; form.roi_cy.value = roi.cy; form.roi_r.value = roi.r;
    $('#roiManual').classList.toggle('hidden', $('#fRoiMode').value !== 'manual');
    for (const k of ['ll_alert', 'l_warn', 'h_warn', 'hh_alert']) form[k].value = num(thr[k]) ?? '';
    onTypeChange();
    renderZoneBar();

    $('#calibLive').classList.toggle('hidden', !d);
    $('#btnRedetect').classList.toggle('hidden', !d);
    $('#btnClearHist').classList.toggle('hidden', !d);
    clearTimeout(calibImgTimer);
    if (d) {
      updateCalibLive(c);
      const tick = () => {
        if (state.editingId !== id) return;
        const img = new Image();
        img.onload = () => { $('#calibImg').src = img.src; calibImgTimer = setTimeout(tick, 300); };
        img.onerror = () => { calibImgTimer = setTimeout(tick, 2000); };
        img.src = `/api/cameras/${id}/frame.jpg?t=${Date.now()}`;
      };
      tick();
    }
    openModal('mCamera', () => { state.editingId = null; clearTimeout(calibImgTimer); });
    setTimeout(() => form.name.focus(), 50);
  }

  function updateCalibLive(c) {
    const r = c.reading;
    $('#calibAngle').textContent = r && r.angle !== null && r.angle !== undefined ? Number(r.angle).toFixed(1) : '—';
    $('#calibConf').textContent = r
      ? `${r.valid ? 'Стрелка найдена' : 'Стрелка не найдена'} · уверенность ${Number(r.confidence || 0).toFixed(2)} · V = ${fmt(r.raw_value, decimalsFor(c.data))} ${c.data.unit}`
      : 'Нет данных с камеры';
  }

  $$('[data-take]').forEach((b) => b.addEventListener('click', () => {
    const c = state.editingId && state.cams.get(state.editingId);
    const r = c && c.reading;
    if (!r || r.angle === null || r.angle === undefined || !r.valid) {
      toast('Стрелка сейчас не распознана — угол взять нельзя', 'warn');
      return;
    }
    form[b.dataset.take].value = Number(r.angle).toFixed(1);
    toast(`${b.dataset.take === 'theta_min' ? 'θmin' : 'θmax'} = ${Number(r.angle).toFixed(1)}°`, 'ok', 2000);
  }));

  function renderZoneBar() {
    const vmin = num(form.v_min.value) ?? 0, vmax = num(form.v_max.value) ?? 10;
    const lo = Math.min(vmin, vmax), hi = Math.max(vmin, vmax);
    const span = hi - lo || 1;
    const thr = { ll_alert: form.ll_alert.value, l_warn: form.l_warn.value, h_warn: form.h_warn.value, hh_alert: form.hh_alert.value };
    const { bands } = computeBands(thr, lo, hi);
    $('#zoneBar').innerHTML = bands.map((b) => {
      const w = Math.max(0, (Math.min(hi, b.to) - Math.max(lo, b.from)) / span * 100);
      return `<div style="width:${w}%;background:${hexA(COLORS[b.c], 0.75)}" title="${b.c}: ${b.from}…${b.to}"></div>`;
    }).join('');
  }

  function readForm() {
    const thresholds = {};
    for (const k of ['ll_alert', 'l_warn', 'h_warn', 'hh_alert']) thresholds[k] = num(form[k].value);
    const seq = ['ll_alert', 'l_warn', 'h_warn', 'hh_alert'].map((k) => [k, thresholds[k]]).filter((x) => x[1] !== null);
    for (let i = 1; i < seq.length; i++) {
      if (seq[i - 1][1] > seq[i][1]) throw new Error('Уставки должны возрастать: LL ≤ L ≤ H ≤ HH');
    }
    const v_min = num(form.v_min.value), v_max = num(form.v_max.value);
    if (v_min === null || v_max === null || v_min === v_max) throw new Error('Задайте различные V_min и V_max');
    const theta_min = num(form.theta_min.value), theta_max = num(form.theta_max.value);
    if (theta_min === null || theta_max === null) throw new Error('Задайте углы θmin и θmax');
    return {
      name: form.name.value.trim(),
      type: $('#fType').value,
      gauge_type: $('#fGaugeType').value,
      unit: $('#fUnit').value,
      source_url: form.source_url.value.trim() || null,
      calibration: {
        v_min, theta_min, v_max, theta_max, direction: form.direction.value,
        roi: { mode: $('#fRoiMode').value, cx: num(form.roi_cx.value) ?? 0.5, cy: num(form.roi_cy.value) ?? 0.5, r: num(form.roi_r.value) ?? 0.45 },
      },
      thresholds,
    };
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    let payload;
    try { payload = readForm(); } catch (err) { toast(err.message, 'err'); return; }
    const btn = $('#camFormSubmit');
    btn.disabled = true;
    try {
      if (state.editingId) {
        const cam = await api(`/api/cameras/${state.editingId}`, { method: 'PATCH', body: payload });
        upsertCamera(cam);
        toast('Настройки прибора сохранены');
        closeModal('mCamera');
      } else if (payload.type === 'phone_ws') {
        closeModal('mCamera');
        const res = await api('/api/phone/session', { method: 'POST', body: { name: payload.name, gauge_type: payload.gauge_type, unit: payload.unit } });
        await api(`/api/cameras/${res.cam_id}`, { method: 'PATCH', body: { calibration: payload.calibration, thresholds: payload.thresholds } });
        showPhoneResult(res);
      } else {
        const cam = await api('/api/cameras', { method: 'POST', body: payload });
        upsertCamera(cam);
        toast(`Добавлено: ${cam.name}`);
        closeModal('mCamera');
      }
    } catch (err) {
      toast(err.message, 'err', 6000);
    } finally {
      btn.disabled = false;
    }
  });

  $('#btnRedetect').addEventListener('click', async () => {
    try { await api(`/api/cameras/${state.editingId}/redetect`, { method: 'POST' }); toast('Циферблат будет найден заново'); } catch (e) { toast(e.message, 'err'); }
  });
  $('#btnClearHist').addEventListener('click', async () => {
    const c = state.cams.get(state.editingId);
    if (!c || !confirm(`Удалить всю историю телеметрии «${c.data.name}»?`)) return;
    try {
      await api(`/api/cameras/${c.id}/history`, { method: 'DELETE' });
      c.points = []; scheduleChart(c);
      toast('История очищена');
    } catch (e) { toast(e.message, 'err'); }
  });

  // ---------------------------------------------------------------------
  // Действия карточки
  // ---------------------------------------------------------------------
  function downloadCsv(c) {
    const a = document.createElement('a');
    a.href = `/api/cameras/${c.id}/export.csv`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  async function restartCamera(c) {
    try { await api(`/api/cameras/${c.id}/restart`, { method: 'POST' }); toast(`Переподключение: ${c.data.name}`); } catch (e) { toast(e.message, 'err'); }
  }
  async function deleteCamera(c) {
    if (!confirm(`Удалить прибор «${c.data.name}» вместе с историей показаний?`)) return;
    try { await api(`/api/cameras/${c.id}`, { method: 'DELETE' }); removeCard(c.id); toast('Прибор удалён'); } catch (e) { toast(e.message, 'err'); }
  }

  let fullTimer = null;
  function openFull(id) {
    const c = state.cams.get(id);
    if (!c) return;
    $('#fullTitle').textContent = c.data.name;
    $('#fullMjpeg').href = `/api/cameras/${id}/mjpeg`;
    const tick = () => {
      const img = new Image();
      img.onload = () => {
        $('#fullImg').src = img.src;
        const r = c.reading || {};
        const st = c.data.stream || {};
        $('#fullInfo').textContent = `V=${fmt(r.value, decimalsFor(c.data))} ${c.data.unit} · θ=${r.angle ?? '—'}° · conf=${r.confidence ?? '—'} · метод: ${r.method || '—'} · статус: ${STATUS_TEXT[c.status]} · ${st.last_error ? 'ошибка: ' + st.last_error : ''}`;
        fullTimer = setTimeout(tick, 250);
      };
      img.onerror = () => { fullTimer = setTimeout(tick, 1500); };
      img.src = `/api/cameras/${id}/frame.jpg?t=${Date.now()}`;
    };
    tick();
    openModal('mFull', () => clearTimeout(fullTimer));
  }

  // ---------------------------------------------------------------------
  // Поиск устройств (ONVIF + скан подсети)
  // ---------------------------------------------------------------------
  async function runDiscovery() {
    const btn = $('#btnScan');
    btn.disabled = true;
    $('#discStatus').innerHTML = '<span class="spinner"></span> Сканирование сети… (ONVIF Probe + 254 хоста × 5 портов, ~5–10 с)';
    $('#discTable').classList.add('hidden');
    try {
      const sub = $('#discSubnet').value.trim();
      const res = await api(`/api/discover${sub ? `?subnet=${encodeURIComponent(sub)}` : ''}`);
      const devs = res.devices;
      $('#discStatus').textContent = `Подсеть ${res.subnet}: найдено устройств — ${devs.length} (за ${res.elapsed_s} с).`;
      $('#discBody').innerHTML = devs.map((d, i) => `
        <tr data-i="${i}">
          <td class="mono">${esc(d.ip)}</td>
          <td>${esc(d.vendor || '—')}<div class="hint">${esc(d.source)}</div></td>
          <td>${d.open_ports.map((p) => `<span class="port">${p}</span>`).join('')}</td>
          <td>
            <div class="input-group">
              <select class="input" data-k="type" style="max-width:110px">
                <option value="rtsp" ${d.suggested_type === 'rtsp' ? 'selected' : ''}>RTSP</option>
                <option value="http_mjpeg" ${d.suggested_type === 'http_mjpeg' ? 'selected' : ''}>HTTP</option>
              </select>
              <input class="input" data-k="url" value="${esc(d.suggested_url || '')}">
            </div>
          </td>
          <td><button class="btn btn-sm btn-primary" data-add ${d.already_added ? 'disabled' : ''}>${d.already_added ? '✓ Уже добавлено' : '＋ Добавить'}</button></td>
        </tr>`).join('');
      $$('#discBody [data-add]').forEach((b) => b.addEventListener('click', async () => {
        const tr = b.closest('tr');
        const d = devs[Number(tr.dataset.i)];
        b.disabled = true;
        try {
          const cam = await api('/api/cameras', { method: 'POST', body: {
            name: `${d.vendor || 'Камера'} ${d.ip}`,
            type: $('[data-k="type"]', tr).value,
            source_url: $('[data-k="url"]', tr).value.trim(),
            gauge_type: 'pressure',
          } });
          upsertCamera(cam);
          b.textContent = '✓ Добавлено';
          toast(`Добавлено: ${cam.name}. Откройте «Настройка» для калибровки шкалы.`);
        } catch (e) {
          b.disabled = false;
          toast(e.message, 'err');
        }
      }));
      $('#discTable').classList.toggle('hidden', devs.length === 0);
    } catch (e) {
      $('#discStatus').textContent = `Ошибка: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------
  // Смартфон как камера: QR-код сессии
  // ---------------------------------------------------------------------
  function openPhoneModal(camId = null) {
    state.phoneCamId = camId;
    fillGaugeSelect($('#pGaugeType'));
    fillUnitSelect($('#pUnit'), $('#pGaugeType').value);
    $('#phoneSetup').classList.toggle('hidden', !!camId);
    $('#phoneResult').classList.add('hidden');
    $('#btnMakeQr').classList.remove('hidden');
    $('#pName').value = '';
    openModal('mPhone');
    if (camId) makeQr();
  }
  $('#pGaugeType').addEventListener('change', () => fillUnitSelect($('#pUnit'), $('#pGaugeType').value));

  async function makeQr() {
    const btn = $('#btnMakeQr');
    btn.disabled = true;
    try {
      const body = state.phoneCamId
        ? { cam_id: state.phoneCamId }
        : { name: $('#pName').value.trim() || null, gauge_type: $('#pGaugeType').value, unit: $('#pUnit').value };
      const res = await api('/api/phone/session', { method: 'POST', body });
      upsertCamera(res.camera);
      showPhoneResult(res);
    } catch (e) {
      toast(e.message, 'err');
    } finally {
      btn.disabled = false;
    }
  }

  function showPhoneResult(res) {
    $('#pQr').innerHTML = res.qr_svg;
    $('#pUrl').textContent = res.url;
    $('#phoneSetup').classList.add('hidden');
    $('#phoneResult').classList.remove('hidden');
    $('#btnMakeQr').classList.add('hidden');
    state.phoneCamId = res.cam_id;
    if ($('#mPhone').classList.contains('hidden')) openModal('mPhone');
  }

  $('#btnCopyUrl').addEventListener('click', async () => {
    const text = $('#pUrl').textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast('Ссылка скопирована');
    } catch (_) {
      const r = document.createRange(); r.selectNodeContents($('#pUrl'));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      toast('Выделено — скопируйте вручную', 'warn');
    }
  });

  // ---------------------------------------------------------------------
  // Инициализация
  // ---------------------------------------------------------------------
  function bindTopbar() {
    $('#btnAdd').addEventListener('click', () => openCameraForm());
    $('#btnDiscover').addEventListener('click', () => { openModal('mDiscover'); });
    $('#btnScan').addEventListener('click', runDiscovery);
    $('#btnPhone').addEventListener('click', () => openPhoneModal());
    $('#btnMakeQr').addEventListener('click', makeQr);
    $('#btnSound').addEventListener('click', () => Sound.toggle());
    $('#btnAck').addEventListener('click', acknowledge);
    $$('#emptyState [data-action]').forEach((b) => b.addEventListener('click', () => {
      const a = b.dataset.action;
      if (a === 'add') openCameraForm();
      if (a === 'discover') openModal('mDiscover');
      if (a === 'phone') openPhoneModal();
    }));
    $('#btnHideNotice').addEventListener('click', () => {
      $('#certNotice').classList.add('hidden');
      localStorage.setItem('gv.certNotice', 'hidden');
    });
  }

  async function init() {
    bindTopbar();
    updateSoundButton();
    try {
      state.meta = await api('/api/meta');
    } catch (e) {
      toast(`Сервер недоступен: ${e.message}`, 'err', 8000);
      setTimeout(init, 3000);
      return;
    }
    $('#brandSub').textContent = `${state.meta.urls[1]} · EMA α=${state.meta.ema_alpha} · ${state.meta.yolo ? `YOLOv8 · ${state.meta.yolo_device || 'CPU'}` : 'OpenCV Hough/эллипс'}`;
    $('#certFp').textContent = state.meta.cert_sha256 ? state.meta.cert_sha256.slice(0, 23) + '…' : '—';
    if (localStorage.getItem('gv.certNotice') !== 'hidden') $('#certNotice').classList.remove('hidden');
    if (!window.Chart) toast('Chart.js не загружен — графики недоступны', 'err', 8000);
    updateEmpty();
    connectWs();
  }

  document.addEventListener('visibilitychange', () => { if (!document.hidden) updateSoundButton(); });
  init();
})();
