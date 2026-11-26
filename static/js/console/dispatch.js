// Вкладка «Диспетчеризация и ТЗ» (Трек №1):
// матрица Health Score (0–100%), графики тренда и скорости нарастания dV/dt,
// очередь рекомендаций, журнал инцидентов со стоп-кадрами и интерактивный конструктор ТЗ (.md / .docx).
import { $, $$, esc, api, toast, fmt, timeStr, css } from './util.js';
import { state, on } from './store.js';

let dispatchData = null;
let selectedDispId = null;
let filterGroup = 'all';
let filterCause = 'all';
let lastPreviewMd = '';
let previewTimer = null;

function healthTone(score) {
  if (score < 50) return 'alert';
  if (score < 75) return 'warning';
  if (score < 90) return 'attention';
  return 'normal';
}

function causeBadge(item) {
  const m = item.root_cause_meta || { short: 'Норма', tone: 'normal' };
  const lv = m.tone === 'stale' ? 'stale' : m.tone;
  return `<span class="tag" data-level="${lv}">${esc(m.short)}</span>`;
}

/** Безопасный рендер Markdown ТЗ в чистый HTML внутри dark-mode HMI без сторонних библиотек. */
function renderMarkdownHtml(md) {
  const lines = String(md || '').split(/\r?\n/);
  const out = [];
  let inList = false;
  let tableBuf = [];

  const fmtInline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="mono">$1</code>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>');

  const flushList = () => {
    if (inList) { out.push('</ul>'); inList = false; }
  };
  const flushTable = () => {
    if (!tableBuf.length) return;
    const rows = tableBuf
      .map((l) => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim()))
      .filter((r) => !r.every((c) => /^:?-+:?$/.test(c)));
    if (rows.length) {
      out.push('<div class="md-tbl-wrap"><table class="md-tbl"><thead><tr>'
        + rows[0].map((c) => `<th>${fmtInline(c)}</th>`).join('')
        + '</tr></thead><tbody>'
        + rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${fmtInline(c)}</td>`).join('')}</tr>`).join('')
        + '</tbody></table></div>');
    }
    tableBuf = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      flushList();
      tableBuf.push(line);
      continue;
    }
    flushTable();
    if (!line.trim()) {
      flushList();
      continue;
    }
    if (line.startsWith('### ')) {
      flushList();
      out.push(`<h4>${fmtInline(line.slice(4))}</h4>`);
    } else if (line.startsWith('## ')) {
      flushList();
      out.push(`<h3>${fmtInline(line.slice(3))}</h3>`);
    } else if (line.startsWith('# ')) {
      flushList();
      out.push(`<h2>${fmtInline(line.slice(2))}</h2>`);
    } else if (line.startsWith('> ')) {
      flushList();
      out.push(`<blockquote class="md-quote">${fmtInline(line.slice(2))}</blockquote>`);
    } else if (line.startsWith('- ')) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${fmtInline(line.slice(2))}</li>`);
    } else {
      flushList();
      out.push(`<p>${fmtInline(line)}</p>`);
    }
  }
  flushTable();
  flushList();
  return out.join('');
}

function updateNavBadge(ov) {
  const badge = $('#tabCntDispatch');
  if (!badge || !ov) return;
  const crit = Number(ov.summary?.critical_wear_count || 0);
  badge.textContent = crit > 0 ? String(crit) : `${Math.round(ov.summary?.avg_health_score || 100)}%`;
  badge.dataset.alert = String(crit > 0);
}

function renderKpis(ov) {
  const s = ov.summary || {};
  const byC = s.by_root_cause || {};
  $('#dispAvgHealth').textContent = `${fmt(s.avg_health_score ?? 0, 1)}%`;
  $('#dispAvgHealth').dataset.tone = healthTone(s.avg_health_score ?? 100);
  $('#dispCritWear').textContent = String(s.critical_wear_count || 0);
  $('#dispModCount').textContent = String(s.modernization_candidates || 0);
  $('#dispCauseSplit').textContent = `Техпроцесс: ${byC.process_anomaly || 0}, КИП: ${byC.instrument_degradation || 0}, Оптика: ${byC.optical_degradation || 0}`;
}

function populateFilters(ov) {
  const groups = (ov.groups || []).map((g) => g.group);
  const selG = $('#dispFilterGroup');
  const specG = $('#specGroup');
  const specI = $('#specInstrument');
  const items = ov.instruments || [];

  if (selG && selG.options.length <= 1) {
    selG.innerHTML = '<option value="all">Все узлы ТЭЦ</option>'
      + groups.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
  }
  if (specG && specG.options.length <= 1) {
    specG.innerHTML = '<option value="all">Вся станция (КТЦ)</option>'
      + groups.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
  }
  if (specI && specI.options.length <= 1) {
    specI.innerHTML = '<option value="all">Все проблемные приборы</option>'
      + items.map((x) => `<option value="${esc(x.id)}">${esc(x.code)} — ${esc(x.short_name)} (${fmt(x.health_score, 0)}%)</option>`).join('');
  }
}

function renderMatrix(ov) {
  const tbody = $('#dispMatrixBody');
  if (!tbody) return;
  let items = (ov.instruments || []).slice();
  if (filterGroup !== 'all') items = items.filter((x) => x.group === filterGroup);
  if (filterCause !== 'all') items = items.filter((x) => x.root_cause === filterCause);
  items.sort((a, b) => a.health_score - b.health_score);

  if (!selectedDispId || !ov.instruments.some((x) => x.id === selectedDispId)) {
    selectedDispId = items[0]?.id || ov.instruments[0]?.id || null;
  }

  tbody.innerHTML = items.map((x) => {
    const tone = healthTone(x.health_score);
    const valStr = x.valid ? `${fmt(x.value, x.decimals)} ${esc(x.unit)}` : 'НЕТ ДАННЫХ';
    const sel = x.id === selectedDispId;
    return `<tr class="disp-row" data-id="${esc(x.id)}" data-selected="${sel}">
      <td class="mono"><b>${esc(x.code)}</b></td>
      <td><div class="disp-name">${esc(x.short_name)}</div><div class="disp-grp">${esc(x.group)}</div></td>
      <td>
        <div class="hs-cell">
          <div class="hs-bar"><div class="hs-fill" data-tone="${tone}" style="width:${Math.max(4, Math.min(100, x.health_score))}%"></div></div>
          <span class="mono hs-num" data-tone="${tone}">${fmt(x.health_score, 0)}%</span>
        </div>
      </td>
      <td class="mono">${valStr}</td>
      <td class="mono">${x.rate_symbol}=${fmt(x.rate_per_min, 2)}</td>
      <td class="mono">${fmt(x.chatter_pct, 1)}%</td>
      <td class="mono">${fmt(x.overload_min, 1)} м</td>
      <td class="mono">${fmt(x.cv_confidence_pct, 0)}%</td>
      <td>${causeBadge(x)}</td>
    </tr>`;
  }).join('');

  $$('.disp-row', tbody).forEach((tr) => {
    tr.addEventListener('click', () => {
      selectedDispId = tr.dataset.id;
      renderMatrix(ov);
      loadSelectedDetail(selectedDispId);
    });
  });
}

function renderRecommendations(ov) {
  const ul = $('#dispRecsList');
  if (!ul) return;
  const recs = (ov.recommendations || []).slice(0, 12);
  if (!recs.length) {
    ul.innerHTML = '<li class="arch-empty">Активных критических рекомендаций нет — оборудование в штатном коридоре.</li>';
    return;
  }
  ul.innerHTML = recs.map((r) => {
    const lv = r.urgency === 'КРИТИЧНО' ? 'alert' : (r.urgency === 'ВЫСОКИЙ' ? 'warning' : 'stale');
    return `<li class="disp-rec-item" data-id="${esc(r.instrument_id)}">
      <div class="disp-rec-top">
        <span class="tag" data-level="${lv}">${esc(r.urgency)}</span>
        <strong class="mono">${esc(r.code)}</strong>
        <span class="mono hs-num" data-tone="${healthTone(r.health_score)}">HS ${fmt(r.health_score, 0)}%</span>
        <span class="sp"></span>
        <span class="disp-rec-cause">${esc(r.root_cause_label)}</span>
      </div>
      <div class="disp-rec-txt">${esc(r.recommendation)}</div>
    </li>`;
  }).join('');

  $$('.disp-rec-item', ul).forEach((li) => {
    li.addEventListener('click', () => {
      selectedDispId = li.dataset.id;
      if (dispatchData) renderMatrix(dispatchData);
      loadSelectedDetail(selectedDispId);
    });
  });
}

function drawRateAndTrendCanvas(detail) {
  const cv = $('#dispRateCanvas');
  if (!cv || !detail) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(240, cv.clientWidth || 440);
  const h = Math.max(150, cv.clientHeight || 168);
  cv.width = Math.round(w * dpr);
  cv.height = Math.round(h * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const bg = css('--stage') || '#07090b';
  const line = css('--line') || '#2a3037';
  const txt3 = css('--text-3') || '#8d96a0';
  const okCol = css('--ok') || '#52b073';
  const warnCol = css('--warn') || '#e7a83a';
  const alarmCol = css('--alarm') || '#f05a5f';

  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  const vals = detail.sparkline || [];
  const rates = detail.rate_series || [];
  const padL = 46;
  const padR = 44;
  const padT = 14;
  const padB = 22;
  const pw = w - padL - padR;
  const ph = h - padT - padB;

  if (vals.length < 2) {
    ctx.fillStyle = txt3;
    ctx.font = '12px "IBM Plex Sans", sans-serif';
    ctx.fillText('Недостаточно точек для построения тренда и dV/dt', padL, h / 2);
    return;
  }

  const thr = detail.thresholds || {};
  const loV = Math.min(...vals, ...[thr.l_warn, thr.ll_alert].filter((v) => v !== null && v !== undefined && Number.isFinite(v)));
  const hiV = Math.max(...vals, ...[thr.h_warn, thr.hh_alert].filter((v) => v !== null && v !== undefined && Number.isFinite(v)));
  const spanV = Math.max(1e-6, hiV - loV);
  const yMin = loV - spanV * 0.1;
  const yMax = hiV + spanV * 0.1;
  const yOf = (v) => padT + ph * (1 - (v - yMin) / (yMax - yMin));
  const xOf = (i) => padL + (i / Math.max(1, vals.length - 1)) * pw;

  // Сетка
  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = Math.round(padT + (ph * i) / 3) + 0.5;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    const lv = yMax - ((yMax - yMin) * i) / 3;
    ctx.fillStyle = txt3;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = 'right';
    ctx.fillText(fmt(lv, detail.decimals), padL - 5, y + 3);
  }

  // Линии уставок H и HH
  const drawThrLine = (val, col, lbl) => {
    if (val === null || val === undefined || !Number.isFinite(val)) return;
    const y = yOf(val);
    if (y < padT || y > padT + ph) return;
    ctx.save();
    ctx.strokeStyle = col;
    ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = col;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillText(lbl, w - padR + 4, y + 3);
    ctx.restore();
  };
  drawThrLine(thr.h_warn, warnCol, 'H');
  drawThrLine(thr.hh_alert, alarmCol, 'HH');

  // Столбцы производной dV/dt (нижняя полуплоскость, приглушённые)
  if (rates.length >= 2) {
    const maxR = Math.max(0.01, ...rates.map((r) => Math.abs(r)));
    const midY = padT + ph * 0.72;
    const barMaxH = ph * 0.26;
    const barW = Math.max(3, (pw / rates.length) * 0.55);
    rates.forEach((r, idx) => {
      const x = xOf(idx) - barW / 2;
      const bh = (Math.abs(r) / maxR) * barMaxH;
      ctx.fillStyle = Math.abs(r) >= maxR * 0.7 ? 'rgba(231, 168, 58, 0.45)' : 'rgba(141, 150, 160, 0.25)';
      ctx.fillRect(x, r >= 0 ? midY - bh : midY, barW, bh);
    });
  }

  // Основная кривая параметра
  ctx.strokeStyle = detail.level === 'alert' ? alarmCol : (detail.level === 'warning' ? warnCol : okCol);
  ctx.lineWidth = 2;
  ctx.beginPath();
  vals.forEach((v, idx) => {
    const x = xOf(idx);
    const y = yOf(v);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Подпись оси X
  ctx.fillStyle = txt3;
  ctx.font = '10px "JetBrains Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillText('−15 мин', padL, h - 6);
  ctx.textAlign = 'center';
  ctx.fillText(`Кривая параметра и ${detail.rate_symbol} (столбцы)`, padL + pw / 2, h - 6);
  ctx.textAlign = 'right';
  ctx.fillText('Сейчас', w - padR, h - 6);
}

async function loadSelectedDetail(instId) {
  if (!instId) return;
  try {
    const d = await api(`/api/dispatch/instrument/${encodeURIComponent(instId)}`);
    $('#dispDetailTitle').textContent = `${d.code} — ${d.name}`;
    $('#dispDetailHealth').innerHTML = `<span class="tag" data-level="${d.health_score < 50 ? 'alert' : (d.health_score < 75 ? 'warning' : 'normal')}">HS ${fmt(d.health_score, 1)}% (${esc(d.health_band)})</span>`;
    const pen = d.penalties || {};
    $('#dispDetailPenalties').innerHTML = `
      <span>Оборудование: <b>${fmt(d.equipment_health ?? d.health_score, 0)}%</b></span>
      <span>Прибор КИП: <b>${fmt(d.instrument_health ?? d.health_score, 0)}%</b></span>
      <span>Оптика CV: <b>${fmt(d.optical_health ?? d.optical_score, 0)}%</b></span>
      <span>Связь: <b>${fmt(d.communication_health ?? 100, 0)}%</b></span>
      <span>Перегрузка: <b>−${fmt(pen.overload, 0)}</b></span>
      <span>Дребезг: <b>−${fmt(pen.chatter, 0)}</b></span>
    `;
    const evImg = $('#dispDetailImg');
    if (evImg) evImg.src = `${d.evidence_url}?t=${Date.now()}`;
    drawRateAndTrendCanvas(d);
  } catch (_) {
    // игнорируем при смене вкладки
  }
}

async function loadIncidentsGallery() {
  const host = $('#dispIncidentsStrip');
  if (!host) return;
  try {
    const list = await api('/api/dispatch/incidents?limit=8');
    if (!list.length) {
      host.innerHTML = '<div class="arch-empty">Инцидентов за текущий период не зафиксировано.</div>';
      return;
    }
    host.innerHTML = list.map((ev) => {
      const lv = ev.kind === 'link' ? 'stale' : (ev.level || 'warning');
      const badgeLabel = ev.kind === 'link'
        ? 'СВЯЗЬ'
        : (lv === 'alert' ? 'АВАРИЯ' : lv === 'warning' ? 'ПРЕДУПР.' : lv === 'normal' ? 'НОРМА' : 'ИНФО');
      const valStr = ev.value !== null && ev.value !== undefined ? `${fmt(ev.value, 2)} ${esc(ev.unit || '')}` : esc(ev.text || 'обрыв');
      return `<button type="button" class="disp-inc-card" data-ev-img="${esc(ev.evidence_url)}" data-ev-title="${esc(ev.code)} — ${esc(ev.cam_name || '')}" data-ev-meta="${esc(ev.root_cause_label || '')}, ${valStr}">
        <img src="${esc(ev.evidence_url)}?t=${Date.now()}" alt="Доказательный кадр ${esc(ev.code)}" loading="lazy">
        <div class="disp-inc-meta">
          <div class="disp-inc-top"><strong class="mono">${esc(ev.code)}</strong><span class="tag" data-level="${lv}">${badgeLabel}</span></div>
          <div class="mono disp-inc-val">${valStr}</div>
          <div class="disp-inc-ts mono">${ev.ts ? timeStr(new Date(ev.ts)) : '—'}</div>
        </div>
      </button>`;
    }).join('');

    $$('.disp-inc-card', host).forEach((btn) => {
      btn.addEventListener('click', () => {
        const dlg = $('#dlgSnapshot');
        if (!dlg) return;
        $('#snapDlgTitle').textContent = `Доказательный кадр: ${btn.dataset.evTitle}`;
        $('#snapDlgMeta').textContent = btn.dataset.evMeta || '';
        $('#snapDlgImg').src = btn.dataset.evImg;
        const ackBtn = $('#btnSnapDlgAck');
        if (ackBtn) ackBtn.hidden = true;
        dlg.showModal();
      });
    });
  } catch (_) {
    // тихо пропускаем
  }
}

function collectSpecPayload(format = 'docx') {
  return {
    period: $('#specPeriod')?.value || '12h',
    group: $('#specGroup')?.value || 'all',
    instrument_id: $('#specInstrument')?.value || 'all',
    mode: $('#specMode')?.value || 'deterministic',
    format,
    plant_name: $('#specPlant')?.value?.trim() || null,
    branch_name: $('#specBranch')?.value?.trim() || null,
    workshop: $('#specWorkshop')?.value?.trim() || null,
    customer: $('#specCustomer')?.value?.trim() || null,
    contractor: $('#specContractor')?.value?.trim() || null,
    doc_number: $('#specDocNum')?.value?.trim() || null,
  };
}

export async function refreshSpecPreview() {
  const prev = $('#specPreviewBox');
  if (!prev) return;
  prev.innerHTML = '<div class="arch-empty">Формирование предварительного просмотра дефектной ведомости и ТЗ…</div>';
  try {
    const res = await api('/api/specs/preview', {
      method: 'POST',
      body: collectSpecPayload('md'),
    });
    lastPreviewMd = res.markdown || '';
    const eco = res.economics || {};
    const pbText = (eco.payback_months !== null && eco.payback_months !== undefined) ? `${eco.payback_months} мес.` : '—';
    $('#specEcoSummary').innerHTML = `
      <span>Позиций в ТЗ: <b>${res.tz_count ?? res.defective_count ?? 0} из ${res.scoped_count || 0}</b></span>
      <span>CAPEX: <b>${fmt((eco.capex_rub || 0) / 1000, 1)} тыс. ₽</b></span>
      <span>Чистый эффект: <b>${fmt((eco.annual_effect_rub || 0) / 1000, 1)} тыс. ₽/год</b></span>
      <span>Окупаемость: <b>${pbText}</b></span>
      <span>Охват БД: <b>${res.db_samples_count || 0} зап.</b></span>
      <span>Движок: <b>${esc(res.engine_used || 'deterministic')}</b></span>
    `;
    $('#dispPaybackKpi').textContent = pbText;
    prev.innerHTML = renderMarkdownHtml(lastPreviewMd);
  } catch (e) {
    prev.innerHTML = `<div class="arch-empty">Ошибка формирования ТЗ: ${esc(e.message)}</div>`;
  }
}

async function downloadSpec(format) {
  const btn = format === 'docx' ? $('#btnSpecDownloadDocx') : $('#btnSpecDownloadMd');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/specs/generate', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collectSpecPayload(format)),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const disp = res.headers.get('Content-Disposition') || '';
    const match = /filename\*=UTF-8''([^;]+)/i.exec(disp);
    const filename = match ? decodeURIComponent(match[1]) : `GaugeVision_TZ.${format}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toast(`Документ «${filename}» сформирован и загружен`);
  } catch (e) {
    toast(`Ошибка выгрузки ${format.toUpperCase()}: ${e.message}`, 'err');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function initSpecDefaults() {
  try {
    const cat = await api('/api/specs/catalog');
    const defs = cat.defaults || {};
    if ($('#specPlant') && !$('#specPlant').value) $('#specPlant').value = defs.plant_name || '';
    if ($('#specBranch') && !$('#specBranch').value) $('#specBranch').value = defs.branch_name || '';
    if ($('#specWorkshop') && !$('#specWorkshop').value) $('#specWorkshop').value = defs.workshop || '';
    if ($('#specCustomer') && !$('#specCustomer').value) $('#specCustomer').value = defs.customer || '';
    if ($('#specContractor') && !$('#specContractor').value) $('#specContractor').value = defs.contractor || '';
    const llmNote = $('#specLlmStatus');
    if (llmNote) {
      llmNote.textContent = cat.llm?.configured
        ? `LLM подключена (${cat.llm.model})`
        : 'Автономный режим (air-gapped: без облачных API)';
    }
  } catch (_) {
    // оставляем значения по умолчанию
  }
}

function renderAutoSpecs(ov) {
  const tbody = $('#autoSpecsBody');
  const cntEl = $('#autoSpecsCnt');
  if (!tbody) return;
  const list = ov.auto_spec_triggers || [];
  if (cntEl) cntEl.textContent = `${list.length} док.`;
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="arch-empty">Автоматических проектов ТЗ пока не сформировано.</td></tr>';
    return;
  }
  tbody.innerHTML = list.slice(0, 10).map((t) => {
    const stLv = t.status === 'completed' ? 'normal' : (t.status === 'failed' ? 'alert' : 'warning');
    const stLbl = t.status === 'completed' ? 'ГОТОВ' : (t.status === 'failed' ? 'ОШИБКА' : 'В РАБОТЕ');
    const dlHtml = t.status === 'completed' && t.id
      ? `<a class="btn sm" href="/api/specs/auto/${t.id}/download?format=docx">DOCX</a> <a class="btn sm" href="/api/specs/auto/${t.id}/download?format=md">MD</a>`
      : `<span class="hint">${esc(t.error || 'ожидание')}</span>`;
    return `<tr>
      <td class="mono">${esc(t.doc_number || `#${t.id || '—'}`)}</td>
      <td class="mono"><b>${esc(t.code || t.instrument_id)}</b></td>
      <td class="mono">${fmt(t.health_score, 1)}%</td>
      <td>${esc(t.reason || '—')}</td>
      <td><span class="tag" data-level="${stLv}">${stLbl}</span></td>
      <td>${dlHtml}</td>
    </tr>`;
  }).join('');
}

export async function refreshDispatch() {
  if (state.meta?.auth_required && !state.meta?.authenticated) return;
  try {
    const ov = await api('/api/dispatch/overview');
    dispatchData = ov;
    state.dispatch = ov;
    updateNavBadge(ov);
    if (state.view !== 'dispatch') return;
    renderKpis(ov);
    populateFilters(ov);
    renderMatrix(ov);
    renderRecommendations(ov);
    renderAutoSpecs(ov);
    loadIncidentsGallery();
    if (selectedDispId) loadSelectedDetail(selectedDispId);
    if (!lastPreviewMd) refreshSpecPreview();
  } catch (_) {
    // тихий повтор
  }
}

export function initDispatch() {
  $('#dispFilterGroup')?.addEventListener('change', (e) => {
    filterGroup = e.target.value;
    if (dispatchData) renderMatrix(dispatchData);
  });

  $('#dispFilterCause')?.addEventListener('change', (e) => {
    filterCause = e.target.value;
    if (dispatchData) renderMatrix(dispatchData);
  });

  const schedulePreview = () => {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => refreshSpecPreview(), 220);
  };

  ['#specPeriod', '#specGroup', '#specInstrument', '#specMode'].forEach((sel) => {
    $(sel)?.addEventListener('change', schedulePreview);
  });
  ['#specPlant', '#specBranch', '#specWorkshop', '#specCustomer', '#specContractor', '#specDocNum'].forEach((sel) => {
    $(sel)?.addEventListener('input', schedulePreview);
  });

  $('#btnSpecRefresh')?.addEventListener('click', () => refreshSpecPreview());
  $('#btnSpecDownloadDocx')?.addEventListener('click', () => downloadSpec('docx'));
  $('#btnSpecDownloadMd')?.addEventListener('click', () => downloadSpec('md'));

  on('view', (v) => {
    if (v === 'dispatch') {
      initSpecDefaults();
      refreshDispatch();
    }
  });

  on('events', () => {
    if (state.view === 'dispatch') refreshDispatch();
  });

  setTimeout(() => refreshDispatch(), 1100);
}
