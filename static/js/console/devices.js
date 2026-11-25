// Источники видео: добавление камеры, поиск в сети, смартфон по QR-коду.
import { $, $$, esc, api, toast, GAUGE_SHORT, SOURCE_TEXT } from './util.js';
import { state, select } from './store.js';

const URL_HINTS = {
  rtsp: ['Адрес RTSP-потока', 'rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101',
    'Hikvision: /Streaming/Channels/101. Dahua: /cam/realmonitor?channel=1&subtype=0. RTSP-сервер: rtsp://host:8554/stream.'],
  http_mjpeg: ['Адрес HTTP / MJPEG-потока', 'http://192.168.1.50:8080/video',
    'Android IP Webcam: http://IP:8080/video. DroidCam: http://IP:4747/video. ESP32-CAM: http://IP:81/stream.'],
  device: ['Индекс камеры сервера', '0', 'Камера, подключённая к серверу: 0 — первая, 1 — вторая.'],
  phone_ws: ['', '', 'После сохранения пульт покажет QR-код для подключения смартфона.'],
};

export function fillGaugeSelect(sel) {
  sel.innerHTML = Object.entries(state.meta.gauge_types)
    .map(([k, g]) => `<option value="${k}" title="${esc(g.label)}">${esc(GAUGE_SHORT[k] || g.label)}</option>`).join('');
}
export function fillUnitSelect(sel, gaugeType, current) {
  const units = state.meta.gauge_types[gaugeType].units;
  sel.innerHTML = units.map((u) => `<option value="${esc(u)}">${esc(u)}</option>`).join('');
  sel.value = units.includes(current) ? current : units[0];
}
function fillTypeSelect(sel) {
  sel.innerHTML = state.meta.camera_types.map((t) => `<option value="${t}">${esc(SOURCE_TEXT[t] || t)}</option>`).join('');
}

/** Поля «прибор и источник» формы: справочники, подсказки адреса. */
export function bindSourceFields(form) {
  fillGaugeSelect(form.gauge_type);
  fillTypeSelect(form.type);
  const onType = () => {
    const [label, ph, hint] = URL_HINTS[form.type.value] || ['', '', ''];
    const wrap = $('[data-url]', form);
    wrap.hidden = form.type.value === 'phone_ws';
    $('span', wrap).textContent = label;
    form.source_url.placeholder = ph;
    $('[data-url-hint]', form).textContent = hint;
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

// ---------------------------------------------------------------- добавление
let addFields = null;
export function openAdd() {
  const dlg = $('#dlgAdd');
  const form = $('#addForm');
  addFields.set({});
  $('[data-err]', form).textContent = '';
  dlg.showModal();
  form.name.focus();
}

async function submitAdd(e) {
  const form = $('#addForm');
  if (e.submitter && e.submitter.value !== 'ok') return;
  e.preventDefault();
  const err = $('[data-err]', form);
  const body = addFields.read();
  if (!body.name) { err.textContent = 'Укажите наименование прибора.'; form.name.focus(); return; }
  if (body.type !== 'phone_ws' && !body.source_url) { err.textContent = 'Укажите адрес потока.'; form.source_url.focus(); return; }
  const btn = e.submitter;
  btn.disabled = true;
  try {
    if (body.type === 'phone_ws') {
      const res = await api('/api/phone/session', { method: 'POST', body: { name: body.name, gauge_type: body.gauge_type, unit: body.unit } });
      $('#dlgAdd').close();
      select(res.cam_id);
      showPhoneResult(res);
    } else {
      const cam = await api('/api/cameras', { method: 'POST', body });
      $('#dlgAdd').close();
      select(cam.id);
      toast(`Добавлено: ${cam.name}. Задайте калибровку на вкладке «ROI и шкала».`);
    }
  } catch (ex) {
    err.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- поиск
export function openDiscover() { $('#dlgDiscover').showModal(); $('#discSubnet').focus(); }

async function runDiscovery() {
  const btn = $('#btnScan');
  btn.disabled = true;
  btn.classList.add('busy');
  $('#discStatus').textContent = 'Сканирование: ONVIF Probe и 254 адреса по 5 портам, обычно 5–10 с.';
  $('#discTable').hidden = true;
  try {
    const sub = $('#discSubnet').value.trim();
    const res = await api(`/api/discover${sub ? `?subnet=${encodeURIComponent(sub)}` : ''}`);
    const devs = res.devices;
    $('#discStatus').textContent = devs.length
      ? `Подсеть ${res.subnet}: найдено устройств — ${devs.length}, за ${String(res.elapsed_s).replace('.', ',')} с.`
      : `Подсеть ${res.subnet}: камер не найдено. Проверьте, что камера в той же сети, или укажите IP из другой подсети.`;
    $('#discBody').innerHTML = devs.map((d, i) => `
      <tr data-i="${i}">
        <td class="mono">${esc(d.ip)}</td>
        <td>${esc(d.vendor || '—')}<div class="hint">${esc(d.source)}</div></td>
        <td>${d.open_ports.map((p) => `<span class="port">${p}</span>`).join('')}</td>
        <td><div class="input-row">
          <select class="input" data-k="type" style="max-width:6.5rem">
            <option value="rtsp" ${d.suggested_type === 'rtsp' ? 'selected' : ''}>RTSP</option>
            <option value="http_mjpeg" ${d.suggested_type === 'http_mjpeg' ? 'selected' : ''}>HTTP</option>
          </select>
          <input class="input mono" data-k="url" value="${esc(d.suggested_url || '')}">
        </div></td>
        <td><button class="btn sm" data-add ${d.already_added ? 'disabled' : ''}>${d.already_added ? 'Уже на пульте' : 'Добавить'}</button></td>
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
        b.textContent = 'Добавлено';
        toast(`Добавлено: ${cam.name}. Задайте калибровку на вкладке «ROI и шкала».`);
      } catch (ex) {
        b.disabled = false;
        toast(ex.message, 'err');
      }
    }));
    $('#discTable').hidden = devs.length === 0;
  } catch (ex) {
    $('#discStatus').textContent = `Поиск не выполнен: ${ex.message}`;
  } finally {
    btn.disabled = false;
    btn.classList.remove('busy');
  }
}

// ---------------------------------------------------------------- смартфон
let phoneCamId = null;
export function openPhone(camId = null) {
  phoneCamId = camId;
  fillGaugeSelect($('#pGaugeType'));
  fillUnitSelect($('#pUnit'), $('#pGaugeType').value);
  $('#phoneSetup').hidden = !!camId;
  $('#phoneResult').hidden = true;
  $('#btnMakeQr').hidden = false;
  $('#pName').value = '';
  $('#dlgPhone').showModal();
  if (camId) makeQr();
}

async function makeQr() {
  const btn = $('#btnMakeQr');
  btn.disabled = true;
  try {
    const body = phoneCamId
      ? { cam_id: phoneCamId }
      : { name: $('#pName').value.trim() || null, gauge_type: $('#pGaugeType').value, unit: $('#pUnit').value };
    const res = await api('/api/phone/session', { method: 'POST', body });
    if (!phoneCamId) select(res.cam_id);
    showPhoneResult(res);
  } catch (ex) {
    toast(ex.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

function showPhoneResult(res) {
  $('#pQr').innerHTML = res.qr_svg;
  $('#pUrl').textContent = res.url;
  $('#phoneSetup').hidden = true;
  $('#phoneResult').hidden = false;
  $('#btnMakeQr').hidden = true;
  phoneCamId = res.cam_id;
  if (!$('#dlgPhone').open) $('#dlgPhone').showModal();
}

export function initDevices() {
  addFields = bindSourceFields($('#addForm'));
  $('#addForm').addEventListener('submit', submitAdd);
  $('#btnScan').addEventListener('click', runDiscovery);
  $('#discSubnet').addEventListener('keydown', (e) => { if (e.key === 'Enter') runDiscovery(); });
  $('#btnMakeQr').addEventListener('click', makeQr);
  $('#pGaugeType').addEventListener('change', () => fillUnitSelect($('#pUnit'), $('#pGaugeType').value));
  $('#btnCopyUrl').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('#pUrl').textContent);
      toast('Ссылка скопирована');
    } catch (_) {
      const r = document.createRange(); r.selectNodeContents($('#pUrl'));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      toast('Ссылка выделена — скопируйте её вручную', 'warn');
    }
  });
  $$('dialog [data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    if (b.dataset.act === 'add') openAdd();
    if (b.dataset.act === 'discover') openDiscover();
    if (b.dataset.act === 'phone') openPhone();
  });
}
