// Вкладка «Архитектурная видеоаналитика» (Трек №2):
// интерактивная топология Edge -> Store-and-Forward -> SCADA, мультиэкранная сетка потоков,
// Adaptive FPS, диагностика деградации сигнала и симулятор обрыва канала АСУ ТП.
import { $, $$, esc, api, toast, fmt, timeStr, durShort } from './util.js';
import { state, on } from './store.js';

let focusedStreamId = null;
let scadaTab = 'modbus';
let pollTimer = null;
let frameTick = 0;

function healthBadgeHtml(hs) {
  const map = {
    ONLINE: { lv: 'normal', lbl: 'ONLINE' },
    DEGRADED: { lv: 'warning', lbl: 'DEGRADED' },
    OFFLINE: { lv: 'stale', lbl: 'OFFLINE' },
  };
  const m = map[hs] || map.OFFLINE;
  return `<span class="tag" data-level="${m.lv}">${m.lbl}</span>`;
}

function updateNavBadge(sf) {
  const badge = $('#tabCntArch');
  if (!badge || !sf) return;
  const pending = Number(sf.pending_count || 0);
  badge.textContent = sf.outage_active ? `Q:${pending}` : (pending > 0 ? `Q:${pending}` : 'OK');
  badge.dataset.alert = String(Boolean(sf.outage_active || pending > 0));
}

function renderTopology(data) {
  const edge = data.edge_node || {};
  const sf = data.store_forward || {};
  const scada = data.scada || {};
  const streams = data.streams || [];

  const camTone = edge.channels_online > 0
    ? (edge.channels_degraded > 0 ? 'warning' : 'normal')
    : 'stale';
  const sfTone = sf.outage_active ? 'alert' : (sf.pending_count > 0 ? 'warning' : 'normal');
  const scadaTone = sf.outage_active ? 'stale' : 'normal';

  const setNode = (id, tone, badgeText, metricsHtml) => {
    const el = $(`#${id}`);
    if (!el) return;
    el.dataset.tone = tone;
    const b = $('.topo-state', el);
    if (b) b.textContent = badgeText;
    const m = $('.topo-metrics', el);
    if (m) m.innerHTML = metricsHtml;
  };

  setNode(
    'topoSources',
    camTone,
    `${edge.channels_online || 0} / ${edge.channels_total || 0} ONLINE`,
    `<div>Потоки: <b>${streams.length}</b> (RTSP / WSS / Стенд)</div>
     <div>Деградация: <b>${edge.channels_degraded || 0}</b>, обрыв: <b>${edge.channels_offline || 0}</b></div>`,
  );

  setNode(
    'topoEdge',
    edge.channels_degraded > 0 ? 'warning' : 'normal',
    edge.yolo_available ? `YOLOv8 (${edge.yolo_device || 'CPU'})` : 'OpenCV Hybrid',
    `<div>Инференс: <b>${fmt(edge.avg_inference_ms || 0, 1)} мс</b></div>
     <div>Экономия Adaptive FPS: <b>${fmt(edge.avg_cpu_savings_pct || 0, 0)}%</b></div>`,
  );

  const sfStateLabel = sf.sync_state === 'BUFFERING'
    ? 'БУФЕРИЗАЦИЯ (ОБРЫВ)'
    : sf.sync_state === 'SYNCING'
      ? 'ДОСЫЛКА ПАЧКАМИ'
      : 'СИНХРОНИЗИРОВАН';
  setNode(
    'topoBuffer',
    sfTone,
    sfStateLabel,
    `<div>В очереди: <b>${sf.pending_count || 0}</b> зап. (${fmt(sf.pending_kb || 0, 1)} КБ)</div>
     <div>SQLite WAL: <b>${fmt(sf.db_size_mb || 0, 3)} МБ</b>, seq #${sf.last_seq_id || 0}</div>`,
  );

  const mqttSt = scada.mqtt || {};
  const mbSt = scada.modbus || {};
  setNode(
    'topoScada',
    scadaTone,
    sf.outage_active ? 'КАНАЛ ПРЕРВАН' : 'ДОСТАВКА АКТИВНА',
    `<div>MQTT: <b>${mqttSt.published_total || 0}</b> сообщ. (${mqttSt.enabled ? 'Брокер' : 'Авт. шина'})</div>
     <div>Modbus TCP: <b>${mbSt.registers_mapped || 0}</b> рег. (HR 40001+)</div>`,
  );

  // Состояние стрелки связи перед АСУ ТП
  const linkArrow = $('#topoLinkScada');
  if (linkArrow) {
    linkArrow.dataset.broken = String(Boolean(sf.outage_active));
    linkArrow.textContent = sf.outage_active ? 'ОБРЫВ КАНАЛА' : (sf.pending_count > 0 ? 'ДОСЫЛКА' : 'TLS / TCP');
  }
}

function renderFaultPanel(sf) {
  const btnToggle = $('#btnArchToggleOutage');
  const btnFlush = $('#btnArchFlushQueue');
  const stateBanner = $('#archOutageBanner');
  if (!btnToggle || !sf) return;

  const isOut = Boolean(sf.outage_active);
  btnToggle.dataset.outage = String(isOut);
  btnToggle.classList.toggle('danger', !isOut);
  btnToggle.classList.toggle('primary', isOut);
  $('#lblArchOutage').textContent = isOut
    ? 'Восстановить связь с АСУ ТП (дослать очередь)'
    : 'Симулировать обрыв связи с АСУ ТП';

  if (btnFlush) btnFlush.disabled = isOut || Number(sf.pending_count || 0) === 0;

  if (stateBanner) {
    stateBanner.dataset.tone = (isOut || sf.queue_overflow) ? 'alert' : (sf.pending_count > 0 ? 'warning' : 'normal');
    const ovTxt = sf.queue_overflow ? ` | ВНИМАНИЕ: ${esc(sf.overflow_reason || 'переполнение очереди')} (вытеснено ${sf.evicted_total || 0})` : '';
    stateBanner.innerHTML = isOut
      ? `<strong>Обрыв связи с верхним уровнем АСУ ТП</strong> — события и телеметрия накапливаются в SQLite WAL на Edge-узле (${sf.pending_count} записей, ${fmt(sf.pending_kb || 0, 1)} КБ)${ovTxt}`
      : (sf.pending_count > 0
        ? `<strong>Восстановление и синхронизация</strong> — автоматическая досылка очереди пачками по ${sf.batch_size} записей (осталось ${sf.pending_count})${ovTxt}`
        : `<strong>Связь с контуром АСУ ТП штатная</strong> — доставлено ${sf.delivered_total || 0} записей, буфер Store-and-Forward пуст (WAL ${fmt(sf.db_size_mb || 0, 3)} МБ, своб. ${fmt(sf.disk_free_mb || 0, 0)} МБ)`);
  }

  $('#sfPendingVal').textContent = String(sf.pending_count || 0);
  $('#sfPendingSize').textContent = `${fmt(sf.pending_kb || 0, 1)} КБ (${fmt(sf.db_size_mb || 0, 3)} МБ WAL)`;
  $('#sfDeliveredVal').textContent = String(sf.delivered_total || 0);
  $('#sfLastSyncVal').textContent = sf.last_sync_at ? timeStr(new Date(sf.last_sync_at)) : '—';

  const tbody = $('#archBatchBody');
  if (tbody) {
    const batches = sf.recent_batches || [];
    if (!batches.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="arch-empty">Пачки досылки появятся после восстановления связи после обрыва.</td></tr>';
    } else {
      tbody.innerHTML = batches.slice(0, 6).map((b) => `<tr>
        <td class="mono">${esc(b.batch_id)}</td>
        <td class="mono">${b.completed_at ? timeStr(new Date(b.completed_at)) : '—'}</td>
        <td class="mono">${b.items_count}</td>
        <td class="mono">${fmt((b.bytes_sent || 0) / 1024, 1)} КБ</td>
        <td><span class="tag" data-level="normal">ДОСТАВЛЕНО</span></td>
      </tr>`).join('');
    }
  }
}

function renderStreamsGrid(streams) {
  const grid = $('#archStreamsGrid');
  if (!grid) return;

  if (!streams.length) {
    grid.innerHTML = '<div class="arch-empty">Нет активных видеопотоков.</div>';
    return;
  }

  if (!focusedStreamId || !streams.some((s) => s.id === focusedStreamId)) {
    const prefer = streams.find((s) => s.health_status === 'ONLINE') || streams[0];
    focusedStreamId = prefer.id;
  }

  frameTick++;
  grid.innerHTML = streams.map((s) => {
    const q = s.quality || {};
    const ad = s.adaptive || {};
    const rb = s.ring_buffer || {};
    const focused = s.id === focusedStreamId;
    const valStr = s.value !== null && s.value !== undefined ? `${fmt(s.value, 2)} ${esc(s.unit)}` : '—';
    const reasons = (q.degradation_reasons || []).join('; ') || 'Сигнал стабилен';
    const adTone = ad.mode === 'event_burst' ? 'warning' : 'normal';
    const imgSrc = `${s.frame_url}?overlay=1&t=${frameTick}`;
    return `<article class="arch-cam-card" data-stream-id="${esc(s.id)}" data-focused="${focused}" data-health="${esc(s.health_status)}">
      <header class="arch-cam-head">
        <div class="arch-cam-title">
          <strong class="mono">${esc(s.code)}</strong>
          <span>${esc(s.name)}</span>
        </div>
        ${healthBadgeHtml(s.health_status)}
      </header>
      <div class="arch-cam-stage">
        <img src="${imgSrc}" alt="${esc(s.name)}" loading="lazy">
        <span class="arch-cam-fps mono">${fmt(s.fps || 0, 1)} FPS | ${fmt(s.inference_ms || 0, 1)} мс</span>
      </div>
      <div class="arch-cam-meta">
        <div class="arch-kv"><span>Показание</span><b class="mono">${valStr}</b></div>
        <div class="arch-kv"><span>Adaptive FPS</span><b class="mono" data-tone="${adTone}">${ad.mode === 'event_burst' ? `ТРЕВОГА ${ad.target_fps} FPS` : `ЭКОНОМ ${ad.target_fps} FPS`}</b></div>
        <div class="arch-kv"><span>Качество кадра</span><b class="mono">${fmt(q.quality_score || 0, 0)}% (ярк. ${fmt(q.mean_luma || 0, 0)})</b></div>
        <div class="arch-kv"><span>Кольц. буфер</span><b class="mono">${rb.pre_buffered || 0}/${rb.pre_capacity || 12} кадр. (${fmt(rb.buffer_kb || 0, 0)} КБ)</b></div>
      </div>
      <div class="arch-cam-reason" title="${esc(reasons)}">${esc(reasons)}</div>
    </article>`;
  }).join('');

  $$('.arch-cam-card', grid).forEach((card) => {
    card.addEventListener('click', () => {
      focusedStreamId = card.dataset.streamId;
      renderStreamsGrid(streams);
      renderFocusedStream(streams);
    });
  });

  renderFocusedStream(streams);
}

function renderFocusedStream(streams) {
  const s = streams.find((x) => x.id === focusedStreamId) || streams[0];
  const box = $('#archFocusBox');
  if (!box || !s) return;
  const q = s.quality || {};
  const ad = s.adaptive || {};
  const rb = s.ring_buffer || {};
  const fault = s.injected_fault || 'recover';

  $('#archFocusTitle').textContent = `${s.code} — ${s.name}`;
  $('#archFocusUrl').textContent = `${s.source_url} (${s.type})`;
  $('#archFocusImg').src = `${s.frame_url}?overlay=1&t=${frameTick}`;
  $('#archFocusHealth').innerHTML = healthBadgeHtml(s.health_status);

  const pktTxt = q.packet_loss_available && q.packet_loss_pct !== null && q.packet_loss_pct !== undefined
    ? `${fmt(q.packet_loss_pct, 1)}%`
    : 'н/д (нет RTP)';
  $('#archFocusMetrics').innerHTML = `
    <div><span>Реальный FPS</span><b class="mono">${fmt(s.fps || 0, 1)} к/с</b></div>
    <div><span>Задержка инференса</span><b class="mono">${fmt(s.inference_ms || 0, 1)} мс</b></div>
    <div><span>Режим Adaptive FPS</span><b class="mono">${esc(ad.mode_label || '—')} (${ad.target_fps || 0} FPS)</b></div>
    <div><span>Экономия Edge CPU</span><b class="mono">${fmt(ad.cpu_savings_pct || 0, 0)}% (wakeups: ${ad.motion_wakeups_total || 0})</b></div>
    <div><span>Яркость / Чёткость</span><b class="mono">${fmt(q.mean_luma || 0, 0)} / ${fmt(q.sharpness || 0, 0)}</b></div>
    <div><span>Пропуск кадров / RTP потери / Блик</span><b class="mono">${fmt(q.frame_drop_pct || 0, 1)}% / ${pktTxt} / ${fmt(q.glare_pct || 0, 1)}%</b></div>
    <div><span>Pre/Post Ring Buffer</span><b class="mono">${rb.pre_buffered || 0} кадр. (клипов: ${rb.archived_clips || 0}, диск: ${rb.persisted_clips || 0})</b></div>
    <div><span>Причина статуса</span><b>${esc((q.degradation_reasons || []).join('; ') || 'Штатный поток')}</b></div>
  `;

  $$('#archFaultBtns [data-fault]').forEach((b) => {
    b.setAttribute('aria-pressed', String(b.dataset.fault === fault));
  });
}

async function loadScadaInspector() {
  const host = $('#archScadaBody');
  if (!host) return;
  try {
    if (scadaTab === 'modbus') {
      const data = await api('/api/scada/modbus/registers?limit=18');
      const sys = data.system || {};
      const rows = data.instruments || [];
      host.innerHTML = `
        <div class="arch-scada-sys mono">
          <span>HR40901 Приборы: <b>${sys.HR40901_instruments_total ?? 0}</b></span>
          <span>HR40902 Аварии: <b>${sys.HR40902_active_critical ?? 0}</b></span>
          <span>HR40903 Предупр.: <b>${sys.HR40903_active_warning ?? 0}</b></span>
          <span>HR40905 Очередь S&amp;F: <b>${sys.HR40905_sf_queue_pending ?? 0}</b></span>
          <span>HR40906 Обрыв: <b>${sys.HR40906_outage_flag ?? 0}</b></span>
        </div>
        <div class="arch-table-scroll">
          <table class="ev-tbl">
            <thead><tr><th>Код</th><th>Прибор</th><th>HR Значение (float32)</th><th>Значение</th><th>HR Статус</th><th>HR Health</th></tr></thead>
            <tbody>
              ${rows.map((r) => `<tr>
                <td class="mono"><b>${esc(r.code)}</b></td>
                <td>${esc(r.name)}</td>
                <td class="mono">${r.hr_value}..${r.hr_value + 1} (0x${(r.raw_hi || 0).toString(16).padStart(4, '0')})</td>
                <td class="mono">${r.value !== null ? `${fmt(r.value, 2)} ${esc(r.unit)}` : '—'}</td>
                <td class="mono">${r.hr_status} = ${r.status_code}</td>
                <td class="mono">${r.hr_health} = ${fmt(r.health_score, 1)}%</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } else {
      const data = await api('/api/scada/mqtt/messages?limit=18');
      const st = data.status || {};
      const msgs = data.messages || [];
      host.innerHTML = `
        <div class="arch-scada-sys mono">
          <span>Режим: <b>${esc(st.mode || '—')}</b></span>
          <span>Брокер: <b>${esc(st.broker || '—')}</b></span>
          <span>Префикс: <b>${esc(st.topic_prefix || '—')}</b></span>
          <span>Опубликовано: <b>${st.published_total || 0}</b></span>
        </div>
        <div class="arch-table-scroll">
          <table class="ev-tbl">
            <thead><tr><th>Время</th><th>Seq</th><th>Топик MQTT 3.1.1</th><th>Размер</th><th>Полезная нагрузка (JSON)</th></tr></thead>
            <tbody>
              ${msgs.length ? msgs.map((m) => `<tr>
                <td class="mono">${m.ts ? timeStr(new Date(m.ts)) : '—'}</td>
                <td class="mono">#${m.seq_id ?? '—'}</td>
                <td class="mono">${esc(m.topic)}</td>
                <td class="mono">${m.bytes} Б</td>
                <td class="mono arch-json-cell">${esc(JSON.stringify(m.payload))}</td>
              </tr>`).join('') : '<tr><td colspan="5" class="arch-empty">Ожидание публикаций MQTT…</td></tr>'}
            </tbody>
          </table>
        </div>`;
    }
  } catch (e) {
    host.innerHTML = `<div class="arch-empty">Ошибка загрузки SCADA-инспектора: ${esc(e.message)}</div>`;
  }
}

export async function refreshArchitecture() {
  if (state.meta?.auth_required && !state.meta?.authenticated) return;
  try {
    const data = await api('/api/architecture/status');
    state.architecture = data;
    updateNavBadge(data.store_forward);
    if (state.view !== 'architecture') return;
    renderTopology(data);
    renderFaultPanel(data.store_forward);
    renderStreamsGrid(data.streams || []);
    loadScadaInspector();
  } catch (_) {
    // WebSocket уведомит о потере связи
  }
}

export function initArchitecture() {
  $('#btnArchToggleOutage')?.addEventListener('click', async () => {
    const cur = Boolean(state.architecture?.store_forward?.outage_active);
    try {
      const res = await api('/api/architecture/outage', {
        method: 'POST',
        body: {
          active: !cur,
          reason: !cur ? 'Демонстрация обрыва связи Edge — АСУ ТП' : 'Восстановление связи оператором',
        },
      });
      if (state.architecture && res.store_forward) {
        state.architecture.store_forward = res.store_forward;
        renderTopology(state.architecture);
        renderFaultPanel(res.store_forward);
        updateNavBadge(res.store_forward);
      }
      toast(!cur
        ? 'Симуляция обрыва АСУ ТП включена — сообщения накапливаются в SQLite WAL'
        : 'Связь с АСУ ТП восстановлена — запущена хронологическая досылка пачками');
    } catch (e) {
      toast(`Ошибка переключения режима обрыва: ${e.message}`, 'err');
    }
  });

  $('#btnArchFlushQueue')?.addEventListener('click', async () => {
    try {
      const res = await api('/api/architecture/store-forward/flush', { method: 'POST' });
      toast(`Синхронизация завершена: доставлено ${res.flushed || 0} записей`);
      refreshArchitecture();
    } catch (e) {
      toast(`Не удалось дослать очередь: ${e.message}`, 'err');
    }
  });

  $$('#archFaultBtns [data-fault]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!focusedStreamId) return;
      const mode = btn.dataset.fault;
      try {
        await api('/api/architecture/degrade', {
          method: 'POST',
          body: { stream_id: focusedStreamId, mode },
        });
        toast(mode === 'recover'
          ? 'Деградация видеосигнала снята — поток восстановлен'
          : `Применена симуляция деградации: ${btn.textContent}`);
        refreshArchitecture();
      } catch (e) {
        toast(`Ошибка управления каналом: ${e.message}`, 'err');
      }
    });
  });

  $$('#segScadaTab [data-scada]').forEach((btn) => {
    btn.addEventListener('click', () => {
      scadaTab = btn.dataset.scada;
      $$('#segScadaTab [data-scada]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.scada === scadaTab)));
      loadScadaInspector();
    });
  });

  on('store-forward', (sf) => {
    updateNavBadge(sf);
    if (state.architecture) state.architecture.store_forward = sf;
    if (state.view === 'architecture' && state.architecture) {
      renderTopology(state.architecture);
      renderFaultPanel(sf);
    }
  });

  on('architecture-tick', (msg) => {
    if (msg.store_forward) updateNavBadge(msg.store_forward);
    if (state.view === 'architecture') {
      refreshArchitecture();
    }
  });

  on('view', (v) => {
    if (v === 'architecture') {
      refreshArchitecture();
      if (!pollTimer) pollTimer = setInterval(() => { if (state.view === 'architecture') refreshArchitecture(); }, 2500);
    }
  });

  // Первичное обновление бейджа очереди при старте
  setTimeout(() => refreshArchitecture(), 900);
}
