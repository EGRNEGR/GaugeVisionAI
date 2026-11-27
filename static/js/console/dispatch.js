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

// Состояние модулей Predictive Analytics и Modernization Optimizer (0-1 ILP)
let predictiveData = null;
let selectedPredId = null;
let optimizerResult = null;
let optMandatorySet = new Set();
let optExcludedSet = new Set();
let specOptimizationContext = null; // { budget_rub, objective, selected_ids, plan_id, label }

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
  const payload = {
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
  if (specOptimizationContext) {
    if (specOptimizationContext.plan_id) {
      payload.optimization_plan_id = specOptimizationContext.plan_id;
    } else if (Array.isArray(specOptimizationContext.selected_ids) && specOptimizationContext.selected_ids.length) {
      payload.selected_instrument_ids = specOptimizationContext.selected_ids;
      if (Number.isFinite(specOptimizationContext.budget_rub)) {
        payload.optimization_budget_rub = specOptimizationContext.budget_rub;
        payload.optimization_objective = specOptimizationContext.objective || 'weighted_utility';
      }
    }
  }
  return payload;
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

// ---------------------------------------------------------------------------
// Прогнозная аналитика (Predictive Analytics)
// ---------------------------------------------------------------------------
function fmtEta(val) {
  if (val === null || val === undefined || !Number.isFinite(Number(val))) return '—';
  const m = Number(val);
  if (m <= 0.01) return 'СЕЙЧАС';
  if (m < 60) return `${fmt(m, 1)} мин`;
  return `${fmt(m / 60, 1)} ч`;
}

function drawPredictiveForecastCanvas(detail) {
  const cv = $('#predForecastCanvas');
  if (!cv || !detail) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(280, cv.clientWidth || 520);
  const h = Math.max(170, cv.clientHeight || 200);
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

  const hist = detail.history_points || [];
  const fc = detail.forecast_points || [];
  const padL = 50;
  const padR = 44;
  const padT = 16;
  const padB = 24;
  const pw = w - padL - padR;
  const ph = h - padT - padB;

  if (detail.status !== 'ok' || fc.length < 2) {
    ctx.fillStyle = txt3;
    ctx.font = '12px "IBM Plex Sans", sans-serif';
    ctx.fillText(detail.status_reason || 'Недостаточно данных для построения прогноза', padL, h / 2);
    return;
  }

  const xMin = hist.length ? Math.min(-1, ...hist.map((p) => p.t_rel_min)) : -15;
  const xMax = Math.max(5, ...fc.map((p) => p.h_min));
  const thr = detail.thresholds || {};
  const ys = [
    ...hist.map((p) => p.value),
    ...fc.flatMap((p) => [p.lo95, p.hi95, p.yhat]),
    ...[thr.ll_alert, thr.l_warn, thr.h_warn, thr.hh_alert].filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v))),
  ];
  const rawMin = Math.min(...ys);
  const rawMax = Math.max(...ys);
  const spanY = Math.max(1e-6, rawMax - rawMin);
  const yMin = rawMin - spanY * 0.08;
  const yMax = rawMax + spanY * 0.08;

  const xOf = (t) => padL + ((t - xMin) / Math.max(1e-6, xMax - xMin)) * pw;
  const yOf = (v) => padT + ph * (1 - (v - yMin) / (yMax - yMin));

  // Сетка по Y
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

  // Вертикальная граница «Сейчас (t=0)»
  const xZero = Math.round(xOf(0)) + 0.5;
  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.28)';
  ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(xZero, padT); ctx.lineTo(xZero, padT + ph); ctx.stroke();
  ctx.restore();

  // Конус 95% доверительного интервала
  ctx.beginPath();
  fc.forEach((p, idx) => {
    const x = xOf(p.h_min);
    const y = yOf(p.hi95);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  for (let i = fc.length - 1; i >= 0; i--) {
    ctx.lineTo(xOf(fc[i].h_min), yOf(fc[i].lo95));
  }
  ctx.closePath();
  ctx.fillStyle = 'rgba(122, 162, 196, 0.16)';
  ctx.fill();

  // Конус 80% доверительного интервала
  ctx.beginPath();
  fc.forEach((p, idx) => {
    const x = xOf(p.h_min);
    const y = yOf(p.hi80);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  for (let i = fc.length - 1; i >= 0; i--) {
    ctx.lineTo(xOf(fc[i].h_min), yOf(fc[i].lo80));
  }
  ctx.closePath();
  ctx.fillStyle = 'rgba(122, 162, 196, 0.28)';
  ctx.fill();

  // Линии уставок LL / L / H / HH
  const drawThr = (val, col, lbl) => {
    if (val === null || val === undefined || !Number.isFinite(Number(val))) return;
    const y = yOf(Number(val));
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
  drawThr(thr.h_warn, warnCol, 'H');
  drawThr(thr.hh_alert, alarmCol, 'HH');
  if (thr.lower_enabled !== false) {
    drawThr(thr.l_warn, warnCol, 'L');
    drawThr(thr.ll_alert, alarmCol, 'LL');
  }

  // Историческая кривая
  if (hist.length >= 2) {
    ctx.strokeStyle = okCol;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    hist.forEach((p, idx) => {
      const x = xOf(p.t_rel_min);
      const y = yOf(p.value);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  // Прогнозная траектория
  ctx.save();
  ctx.strokeStyle = detail.breach_prob_alert_horizon >= 0.5 ? alarmCol : (detail.anomaly_score >= 35 ? warnCol : '#7aa2c4');
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 3]);
  ctx.beginPath();
  fc.forEach((p, idx) => {
    const x = xOf(p.h_min);
    const y = yOf(p.yhat);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();

  // Подписи оси X (без наложения при короткой истории относительно горизонта)
  ctx.fillStyle = txt3;
  ctx.font = '10px "JetBrains Mono", monospace';
  ctx.textAlign = 'left';
  if (xZero - padL >= 62) {
    ctx.fillText(`${fmt(xMin, 0)} мин`, padL, h - 6);
    ctx.textAlign = 'center';
    ctx.fillText('Сейчас', xZero, h - 6);
  } else {
    ctx.fillText(`${fmt(xMin, 0)} мин / Сейчас`, padL, h - 6);
  }
  ctx.textAlign = 'right';
  ctx.fillText(`+${fmt(xMax, 0)} мин (ДИ 80%/95%)`, w - padR, h - 6);
}

async function loadPredictiveInstrument(instId) {
  if (!instId) return;
  const win = Number($('#predWindowSel')?.value || 60);
  const hor = Number($('#predHorizonSel')?.value || 60);
  try {
    const d = await api(`/api/predictive/instrument/${encodeURIComponent(instId)}?window_min=${win}&horizon_min=${hor}`);
    $('#predDetailTitle').textContent = `${d.code} — ${d.short_name}`;
    const metaParts = [
      `Тренд: ${(d.trend_meta?.label || d.trend_class)}`,
      `уверенность ${fmt((d.forecast_confidence || 0) * 100, 0)}%`,
    ];
    $('#predDetailMeta').textContent = metaParts.join(', ');
    drawPredictiveForecastCanvas(d);
    const m = d.model || {};
    const mk = d.diagnostics?.mann_kendall || {};
    const cs = d.diagnostics?.cusum || {};
    if (d.status === 'ok') {
      $('#predDetailStats').innerHTML = `
        <span>Метод: <b>${esc(m.method || 'WLS')}</b></span>
        <span>Наклон: <b>${fmt(m.slope_per_min, 4)} ${esc(d.unit)}/мин</b></span>
        <span>R²: <b>${fmt(m.r2_weighted, 3)}</b></span>
        <span>ДИ ±95%: <b>${fmt(d.uncertainty_pct, 1)}% шкалы</b></span>
        <span>Манн-Кендалл Z: <b>${fmt(mk.z, 2)} (p=${fmt(mk.p_value, 4)})</b></span>
        <span>CUSUM: <b>${fmt(cs.max_stat, 2)}</b></span>
        <span>ETA пред./авар.: <b>${fmtEta(d.eta_warning_min)} / ${fmtEta(d.eta_alert_min)}</b></span>
      `;
    } else {
      $('#predDetailStats').textContent = d.status_reason || 'Недостаточно данных для модели.';
    }
    const ul = $('#predAnomaliesList');
    if (ul) {
      const anoms = d.anomalies || [];
      if (!anoms.length) {
        ul.innerHTML = '<li class="hint">Аномальных трендов и сдвигов по критериям CUSUM / Манна-Кендалла / MAD не выявлено.</li>';
      } else {
        ul.innerHTML = anoms.map((a) => `
          <li class="pred-anom-item">
            <span class="tag" data-level="${a.severity === 'alert' ? 'alert' : 'warning'}">${esc(a.code)}</span>
            <span>${esc(a.description)}</span>
            <span class="mono hint">${esc(a.metric)}</span>
          </li>
        `).join('');
      }
    }
  } catch (_) {
    // тихо пропускаем при переключении вкладки
  }
}

async function refreshPredictive() {
  if (state.meta?.auth_required && !state.meta?.authenticated) return;
  const win = Number($('#predWindowSel')?.value || 60);
  const hor = Number($('#predHorizonSel')?.value || 60);
  try {
    const ov = await api(`/api/predictive/overview?window_min=${win}&horizon_min=${hor}`);
    predictiveData = ov;
    const s = ov.summary || {};
    $('#predImminentCnt').textContent = String(s.imminent_alert_count || 0);
    $('#predImminentCnt').dataset.tone = (s.imminent_alert_count || 0) > 0 ? 'alert' : 'normal';
    $('#predAnomCnt').textContent = String(s.anomalous_trend_count || 0);
    $('#predAnomCnt').dataset.tone = (s.anomalous_trend_count || 0) > 0 ? 'warning' : 'normal';
    const nr = s.nearest_upcoming;
    $('#predNearestEta').textContent = nr
      ? `${nr.code}: ${fmtEta(nr.eta_alert_min ?? nr.eta_warning_min)}`
      : 'Нет угроз';
    $('#predAvgConf').textContent = `${fmt((s.avg_forecast_confidence || 0) * 100, 0)}%`;

    const items = ov.instruments || [];
    if (!selectedPredId || !items.some((x) => x.instrument_id === selectedPredId)) {
      selectedPredId = items[0]?.instrument_id || null;
    }
    const tbody = $('#predTableBody');
    if (tbody) {
      tbody.innerHTML = items.map((x) => {
        const tm = x.trend_meta || { short: x.trend_class, tone: 'stale' };
        const fh = x.forecast_at_horizon;
        const fcStr = fh
          ? `${fmt(fh.yhat, x.decimals)} ±${fmt((fh.hi95 - fh.lo95) / 2, x.decimals)} ${esc(x.unit)}`
          : '—';
        const probPct = `${fmt((x.breach_prob_alert_horizon || 0) * 100, 0)}%`;
        const sel = x.instrument_id === selectedPredId;
        return `<tr class="disp-row pred-row" data-id="${esc(x.instrument_id)}" data-selected="${sel}">
          <td class="mono"><b>${esc(x.code)}</b></td>
          <td><div class="disp-name">${esc(x.short_name)}</div><div class="disp-grp">${esc(x.group)}</div></td>
          <td><span class="tag" data-level="${esc(tm.tone)}">${esc(tm.short)}</span></td>
          <td class="mono">${fcStr}</td>
          <td class="mono">${fmtEta(x.eta_warning_min)}</td>
          <td class="mono">${fmtEta(x.eta_alert_min)}</td>
          <td class="mono">${probPct}</td>
          <td class="mono">${fmt(x.anomaly_score, 0)}</td>
        </tr>`;
      }).join('');
      $$('.pred-row', tbody).forEach((tr) => {
        tr.addEventListener('click', () => {
          selectedPredId = tr.dataset.id;
          $$('.pred-row', tbody).forEach((r) => { r.dataset.selected = String(r.dataset.id === selectedPredId); });
          loadPredictiveInstrument(selectedPredId);
        });
      });
    }
    if (selectedPredId) loadPredictiveInstrument(selectedPredId);
  } catch (_) {
    // тихий повтор
  }
}

// ---------------------------------------------------------------------------
// Оптимизатор бюджета модернизации (0-1 ILP)
// ---------------------------------------------------------------------------
function drawParetoFrontierCanvas(res) {
  const cv = $('#optFrontierCanvas');
  if (!cv) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(260, cv.clientWidth || 440);
  const h = Math.max(150, cv.clientHeight || 175);
  cv.width = Math.round(w * dpr);
  cv.height = Math.round(h * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const bg = css('--stage') || '#07090b';
  const line = css('--line') || '#2a3037';
  const txt3 = css('--text-3') || '#8d96a0';
  const okCol = css('--ok') || '#52b073';
  const warnCol = css('--warn') || '#e7a83a';

  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  const pts = (res?.budget_frontier || []).filter((p) => p.status !== 'infeasible');
  const padL = 44;
  const padR = 20;
  const padT = 14;
  const padB = 26;
  const pw = w - padL - padR;
  const ph = h - padT - padB;

  if (!pts.length) {
    ctx.fillStyle = txt3;
    ctx.font = '12px "IBM Plex Sans", sans-serif';
    ctx.fillText('Нет допустимых точек Парето для текущих ограничений', padL, h / 2);
    return;
  }

  const maxB = Math.max(100000, ...pts.map((p) => p.budget_rub));
  const xOf = (b) => padL + (b / maxB) * pw;
  const yOf = (pct) => padT + ph * (1 - Math.max(0, Math.min(100, pct)) / 100);

  ctx.strokeStyle = line;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const pct = i * 25;
    const y = Math.round(yOf(pct)) + 0.5;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = txt3;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`${pct}%`, padL - 5, y + 3);
  }

  // Линия покрытия риска
  ctx.strokeStyle = okCol;
  ctx.lineWidth = 2;
  ctx.beginPath();
  pts.forEach((p, idx) => {
    const x = xOf(p.budget_rub);
    const y = yOf(p.risk_coverage_pct);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Точки и текущая точка бюджета
  pts.forEach((p) => {
    const x = xOf(p.budget_rub);
    const y = yOf(p.risk_coverage_pct);
    ctx.beginPath();
    ctx.arc(x, y, p.is_current_budget ? 5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = p.is_current_budget ? warnCol : okCol;
    ctx.fill();
  });

  ctx.fillStyle = txt3;
  ctx.font = '10px "JetBrains Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillText('0 ₽', padL, h - 6);
  ctx.textAlign = 'center';
  ctx.fillText('Бюджет CAPEX (тыс. ₽) → Покрытие риска (%)', padL + pw / 2, h - 6);
  ctx.textAlign = 'right';
  ctx.fillText(`${fmt(maxB / 1000, 0)} т.₽`, w - padR, h - 6);
}

function collectOptimizerPayload() {
  const maxRaw = $('#optMaxItems')?.value?.trim();
  const maxItems = maxRaw ? Math.max(1, parseInt(maxRaw, 10)) : null;
  return {
    budget_rub: Math.max(0, parseInt($('#optBudgetInput')?.value || '500000', 10) || 0),
    objective: $('#optObjectiveSel')?.value || 'weighted_utility',
    max_items: Number.isFinite(maxItems) ? maxItems : null,
    mandatory_ids: Array.from(optMandatorySet),
    excluded_ids: Array.from(optExcludedSet),
    auto_mandatory_critical: !!$('#optAutoMandatory')?.checked,
    include_healthy: !!$('#optIncludeHealthy')?.checked,
    window_min: Number($('#predWindowSel')?.value || 60),
    horizon_min: Number($('#predHorizonSel')?.value || 60),
    include_frontier: true,
  };
}

function renderOptimizerResult(res) {
  optimizerResult = res;
  const s = res.summary || {};
  const sv = res.solver || {};
  const badge = $('#optSolverBadge');
  if (badge) {
    const lv = res.status === 'optimal' ? 'normal' : (res.status === 'infeasible' ? 'alert' : 'warning');
    const txt = res.status === 'optimal'
      ? `OPTIMAL (gap ${fmt((sv.optimality_gap || 0) * 100, 2)}%, ${fmt(sv.solve_time_ms || 0, 1)} мс)`
      : (res.status === 'infeasible' ? 'INFEASIBLE (дефицит бюджета)' : String(res.status || '—').toUpperCase());
    badge.innerHTML = `<span class="tag" data-level="${lv}">${esc(txt)}</span>`;
  }

  const infBanner = $('#optInfeasibleBanner');
  if (infBanner) {
    if (res.status === 'infeasible') {
      infBanner.hidden = false;
      infBanner.textContent = sv.infeasibility_reason || 'Задача несовместима с заданными ограничениями.';
    } else {
      infBanner.hidden = true;
      infBanner.textContent = '';
    }
  }

  $('#optKpiCount').textContent = `${s.selected_count || 0} из ${s.candidates_total || 0}`;
  $('#optKpiCapex').textContent = `${fmt((s.total_capex_rub || 0) / 1000, 1)} т.₽ (${fmt(s.budget_utilization_pct || 0, 0)}%)`;
  $('#optKpiRisk').textContent = `${fmt(s.risk_coverage_pct || 0, 1)}% (${fmt(s.total_risk_reduction || 0, 0)} б.)`;
  const pbStr = s.payback_months ? `${s.payback_months} мес.` : '—';
  $('#optKpiEffect').textContent = `${fmt((s.total_net_annual_effect_rub || 0) / 1000, 0)} т.₽/г (${pbStr})`;

  const gr = res.greedy_comparison;
  $('#optKpiGain').textContent = gr
    ? `+${fmt(gr.ilp_gain_objective || 0, 1)} (+${fmt(gr.ilp_gain_pct || 0, 1)}%)`
    : '—';

  const allRows = [...(res.selected || []), ...(res.deferred || [])];
  const tbody = $('#optCandidatesBody');
  if (tbody) {
    if (!allRows.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="arch-empty">Кандидатов на модернизацию по текущему состоянию станции не выявлено.</td></tr>';
    } else {
      tbody.innerHTML = allRows.map((c) => {
        const isMandChecked = optMandatorySet.has(c.instrument_id);
        const isExclChecked = optExcludedSet.has(c.instrument_id);
        const clsRoman = c.criticality_class === 1 ? 'I' : (c.criticality_class === 2 ? 'II' : 'III');
        const stTag = c.selected
          ? `<span class="tag" data-level="normal">В ПЛАНЕ</span>`
          : (c.excluded ? `<span class="tag" data-level="stale">ИСКЛЮЧЁН</span>` : `<span class="tag" data-level="warning">ОТЛОЖЕНО</span>`);
        const mandMark = c.mandatory ? ' <span class="tag" data-level="alert">ОБЯЗ.</span>' : '';
        return `<tr class="opt-row" data-selected="${c.selected}">
          <td><input type="checkbox" class="opt-mand-chk" data-id="${esc(c.instrument_id)}" ${isMandChecked ? 'checked' : ''} aria-label="Обязательно включить ${esc(c.code)}"></td>
          <td><input type="checkbox" class="opt-excl-chk" data-id="${esc(c.instrument_id)}" ${isExclChecked ? 'checked' : ''} aria-label="Исключить ${esc(c.code)}"></td>
          <td class="mono"><b>${esc(c.code)}</b>${mandMark}</td>
          <td><div class="disp-name">${esc(c.short_name)}</div><div class="disp-grp">Кат. ${clsRoman}, ${esc(c.group)}${c.hazardous_zone ? ' (1Ex)' : ''}</div></td>
          <td class="mono">${fmt(c.health_score, 0)}% / P=${fmt((c.breach_prob_alert_horizon || 0) * 100, 0)}%</td>
          <td class="mono">${fmt(c.capex_rub / 1000, 1)} т.₽</td>
          <td class="mono">${fmt(c.net_annual_effect_rub_yr / 1000, 0)} т.₽</td>
          <td class="mono">${fmt(c.risk_reduction_points, 1)}</td>
          <td>${stTag}</td>
        </tr>`;
      }).join('');

      $$('.opt-mand-chk', tbody).forEach((chk) => {
        chk.addEventListener('change', () => {
          const id = chk.dataset.id;
          if (chk.checked) {
            optMandatorySet.add(id);
            optExcludedSet.delete(id);
          } else {
            optMandatorySet.delete(id);
          }
          runOptimizerSolve();
        });
      });
      $$('.opt-excl-chk', tbody).forEach((chk) => {
        chk.addEventListener('change', () => {
          const id = chk.dataset.id;
          if (chk.checked) {
            optExcludedSet.add(id);
            optMandatorySet.delete(id);
          } else {
            optExcludedSet.delete(id);
          }
          runOptimizerSolve();
        });
      });
    }
  }

  $('#optFrontierMeta').textContent = `Полный CAPEX: ${fmt((s.all_candidates_capex_rub || 0) / 1000, 0)} тыс. ₽`;
  drawParetoFrontierCanvas(res);
}

async function runOptimizerSolve() {
  if (state.meta?.auth_required && !state.meta?.authenticated) return;
  try {
    const res = await api('/api/optimizer/solve', {
      method: 'POST',
      body: collectOptimizerPayload(),
    });
    renderOptimizerResult(res);
  } catch (e) {
    toast(`Ошибка оптимизатора: ${e.message}`, 'err');
  }
}

async function loadSavedPlans() {
  const ul = $('#optPlansList');
  if (!ul) return;
  try {
    const plans = await api('/api/optimizer/plans?limit=10');
    $('#optPlansCnt').textContent = `${plans.length} шт.`;
    if (!plans.length) {
      ul.innerHTML = '<li class="arch-empty">Сохранённых планов пока нет.</li>';
      return;
    }
    ul.innerHTML = plans.map((p) => `
      <li class="opt-plan-item">
        <div>
          <strong>${esc(p.name)}</strong>
          <div class="mono hint">${p.selected_count} поз., CAPEX ${fmt((p.total_capex_rub || 0) / 1000, 1)} т.₽ из ${fmt((p.budget_rub || 0) / 1000, 0)} т.₽</div>
        </div>
        <button class="btn sm" type="button" data-apply-plan="${p.id}">В ТЗ</button>
      </li>
    `).join('');
    $$('[data-apply-plan]', ul).forEach((btn) => {
      btn.addEventListener('click', () => {
        const pid = Number(btn.dataset.applyPlan);
        specOptimizationContext = { plan_id: pid, label: `Сохранённый план #${pid}` };
        updateSpecOptBadge();
        refreshSpecPreview();
        toast(`План #${pid} применён к конструктору ТЗ`);
      });
    });
  } catch (_) {
    // тихо пропускаем
  }
}

function updateSpecOptBadge() {
  const note = $('#specOptNote');
  const clearBtn = $('#btnSpecClearOpt');
  if (!note || !clearBtn) return;
  if (specOptimizationContext) {
    note.hidden = false;
    clearBtn.hidden = false;
    note.textContent = `Активен оптимальный портфель ILP: ${specOptimizationContext.label}`;
  } else {
    note.hidden = true;
    clearBtn.hidden = true;
    note.textContent = '';
  }
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
    refreshPredictive();
    if (!optimizerResult) runOptimizerSolve();
    loadSavedPlans();
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
  $('#btnSpecClearOpt')?.addEventListener('click', () => {
    specOptimizationContext = null;
    updateSpecOptBadge();
    refreshSpecPreview();
  });

  // Predictive Analytics handlers
  $('#predWindowSel')?.addEventListener('change', () => refreshPredictive());
  $('#predHorizonSel')?.addEventListener('change', () => refreshPredictive());
  $('#btnPredRefresh')?.addEventListener('click', () => refreshPredictive());

  // Modernization Optimizer handlers
  $('#btnOptSolve')?.addEventListener('click', () => runOptimizerSolve());
  $('#optObjectiveSel')?.addEventListener('change', () => runOptimizerSolve());
  $('#optAutoMandatory')?.addEventListener('change', () => runOptimizerSolve());
  $('#optIncludeHealthy')?.addEventListener('change', () => runOptimizerSolve());
  $$('[data-opt-budget]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if ($('#optBudgetInput')) $('#optBudgetInput').value = btn.dataset.optBudget;
      runOptimizerSolve();
    });
  });
  $('#btnOptSavePlan')?.addEventListener('click', async () => {
    try {
      const payload = collectOptimizerPayload();
      const name = `Этап КИПиА (${Math.round(payload.budget_rub / 1000)} тыс. ₽)`;
      const saved = await api('/api/optimizer/plans', {
        method: 'POST',
        body: { ...payload, name },
      });
      toast(`Оптимальный план «${saved.name}» сохранён в SQLite (#${saved.id})`);
      loadSavedPlans();
    } catch (e) {
      toast(`Не удалось сохранить план: ${e.message}`, 'err');
    }
  });
  $('#btnOptApplyToSpec')?.addEventListener('click', () => {
    if (!optimizerResult || optimizerResult.status === 'infeasible') {
      toast('Сначала рассчитайте допустимый оптимальный план', 'err');
      return;
    }
    const selIds = (optimizerResult.selected || []).map((x) => x.instrument_id);
    if (!selIds.length) {
      toast('В оптимальном плане не выбрано ни одной позиции', 'err');
      return;
    }
    specOptimizationContext = {
      selected_ids: selIds,
      budget_rub: optimizerResult.budget_rub,
      objective: optimizerResult.objective,
      label: `${selIds.length} поз., бюджет ${fmt(optimizerResult.budget_rub / 1000, 0)} тыс. ₽`,
    };
    updateSpecOptBadge();
    refreshSpecPreview();
    $('#specPreviewBox')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    toast(`Оптимальный портфель (${selIds.length} поз.) передан в конструктор ТЗ`);
  });

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
