// Драйвер браузерной проверки Tap-to-Focus (Playwright, Chromium headless, файловая фейковая камера).
// Запуск из capture_focus_e2e.py: node capture_focus_driver.js <captureUrl> <outDir> <videosJson>
// Ожидаемая точка фокуса считается независимо от кода клиента: по рамке #videoWrap,
// размеру кадра, известному зуму сценария и признаку зеркала.
'use strict';
const path = require('path');
const fs = require('fs');
const { chromium } = require(process.env.GV_PLAYWRIGHT_CORE || 'playwright-core');

const [CAPTURE_URL, OUT_DIR, VIDEOS_JSON] = process.argv.slice(2);
const VIDEOS = JSON.parse(VIDEOS_JSON);
const SHOTS = path.join(OUT_DIR, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

const FOCUS_HINT = 'Коснитесь циферблата, чтобы сфокусировать камеру';
const FALSE_SUCCESS = /сфокусирован|фокус установлен|в фокусе|фокус наведён/i;
const TOL = 0.012;
const report = { url: CAPTURE_URL.replace(/token=[^&]+/, 'token=***'), scenarios: {}, failures: [] };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function expect(scn, cond, msg, extra) {
  if (!cond) report.failures.push(`${scn}: ${msg}${extra === undefined ? '' : ` ${JSON.stringify(extra)}`}`);
  return cond;
}

// Эмуляция возможностей объектива поверх настоящего MediaStreamTrack фейковой камеры
function mockScript(cfg) {
  return `(() => {
    const cfg = ${JSON.stringify(cfg)};
    const log = window.__gvLog = [];
    window.__gvHints = [];
    window.__gvMaxInflight = 0;
    let inflight = 0;
    const state = new WeakMap();
    const lensOf = new WeakMap();
    if (cfg.mock) {
      const origSupported = MediaDevices.prototype.getSupportedConstraints;
      MediaDevices.prototype.getSupportedConstraints = function () {
        return { ...origSupported.call(this), pointsOfInterest: !!cfg.poi };
      };
      const origCaps = MediaStreamTrack.prototype.getCapabilities;
      MediaStreamTrack.prototype.getCapabilities = function () {
        const c = { ...(origCaps ? origCaps.call(this) : {}) };
        delete c.zoom; delete c.torch; delete c.focusMode;
        const lens = lensOf.get(this) || 'back';
        const lc = (cfg.perLens && cfg.perLens[lens]) || cfg;
        if (lc.focusModes) c.focusMode = lc.focusModes.slice();
        if (lc.zoom) c.zoom = { min: 1, max: 5, step: 0.1 };
        if (lc.torch) c.torch = true;
        return c;
      };
      const origSettings = MediaStreamTrack.prototype.getSettings;
      MediaStreamTrack.prototype.getSettings = function () {
        const s = { ...origSettings.call(this) };
        const st = state.get(this) || {};
        const lens = lensOf.get(this) || 'back';
        const lc = (cfg.perLens && cfg.perLens[lens]) || cfg;
        delete s.zoom; delete s.focusMode; delete s.torch;
        if (lc.zoom) s.zoom = st.zoom ?? 1;
        if (lc.focusModes) s.focusMode = st.focusMode ?? (cfg.initialFocusMode || 'manual');
        if (lc.torch) s.torch = st.torch ?? false;
        return s;
      };
      MediaStreamTrack.prototype.applyConstraints = async function (c) {
        const adv = (c && c.advanced && c.advanced[0]) || {};
        const entry = { t0: performance.now(), track: this.id, lens: lensOf.get(this) || 'back',
                        adv: JSON.parse(JSON.stringify(adv)) };
        log.push(entry);
        inflight++;
        window.__gvMaxInflight = Math.max(window.__gvMaxInflight, inflight);
        try {
          await new Promise((r) => setTimeout(r, cfg.delayMs || 0));
          if (cfg.rejectPoi && adv.pointsOfInterest) {
            entry.rejected = true;
            throw new DOMException('mock: pointsOfInterest rejected', 'OverconstrainedError');
          }
          state.set(this, { ...(state.get(this) || {}), ...adv });
          entry.ok = true;
        } finally {
          inflight--;
          entry.t1 = performance.now();
        }
      };
    }
    if (cfg.lenses) {
      const origEnum = MediaDevices.prototype.enumerateDevices;
      MediaDevices.prototype.enumerateDevices = async function () {
        await origEnum.call(this);
        return [
          { deviceId: 'mock-back-0', groupId: 'g', kind: 'videoinput', label: 'camera2 0, facing back' },
          { deviceId: 'mock-front-1', groupId: 'g', kind: 'videoinput', label: 'camera2 1, facing front' },
        ];
      };
      const origGum = MediaDevices.prototype.getUserMedia;
      MediaDevices.prototype.getUserMedia = async function (constraints) {
        const v = { ...(constraints.video || {}) };
        const fm = v.facingMode;
        const front = !!(fm && (fm === 'user' || fm.exact === 'user' || fm.ideal === 'user'));
        delete v.facingMode; delete v.deviceId;
        const stream = await origGum.call(this, { ...constraints, video: v });
        stream.getVideoTracks().forEach((t) => lensOf.set(t, front ? 'front' : 'back'));
        return stream;
      };
    }
    // журнал всех текстов подсказки — для проверки отсутствия ложного «успеха»
    document.addEventListener('DOMContentLoaded', () => {
      const hint = document.getElementById('focusHint');
      if (!hint) return;
      new MutationObserver(() => window.__gvHints.push(hint.textContent)).observe(hint, { childList: true, characterData: true, subtree: true });
    });
  })();`;
}

async function openPage(browser, cfg, viewport) {
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true, viewport, hasTouch: true, isMobile: true, deviceScaleFactor: 2,
    permissions: ['camera'],
  });
  await ctx.addInitScript({ content: mockScript(cfg) });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('pageerror', (e) => consoleErrors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await page.goto(CAPTURE_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => {
    const v = document.getElementById('video');
    return v && v.videoWidth > 0 && v.readyState >= 2;
  }, null, { timeout: 30000 });
  await page.waitForFunction(() => document.querySelectorAll('#lensRow .lens-btn').length > 0, null, { timeout: 15000 });
  await sleep(300);
  return { ctx, page, consoleErrors };
}

const ui = (page) => page.evaluate(() => {
  const vis = (id) => !document.getElementById(id).classList.contains('hidden');
  const m = document.getElementById('focusMarker');
  return {
    targetVisible: vis('focusTarget'), markerVisible: vis('focusMarker'), hintVisible: vis('focusHint'),
    hint: document.getElementById('focusHint').textContent,
    marker: { left: parseFloat(m.style.left), top: parseFloat(m.style.top) },
    video: { w: document.getElementById('video').videoWidth, h: document.getElementById('video').videoHeight },
    zoomVal: document.getElementById('zoomVal').textContent,
    torchOn: document.getElementById('btnTorch').classList.contains('on'),
    torchDisabled: document.getElementById('btnTorch').disabled,
    lenses: [...document.querySelectorAll('#lensRow .lens-btn')].map((b) => b.textContent),
    caps: (() => { try { return document.getElementById('video').srcObject.getVideoTracks()[0].getCapabilities(); } catch (e) { return String(e); } })(),
    poiSupported: !!navigator.mediaDevices.getSupportedConstraints().pointsOfInterest,
  };
});

// Независимое прямое преобразование: точка кадра (fx, fy) → экранная точка
async function screenPoint(page, fx, fy, zoom, mirror) {
  return page.evaluate(([fx, fy, zoom, mirror]) => {
    const wrap = document.getElementById('videoWrap').getBoundingClientRect();
    const v = document.getElementById('video');
    const s = Math.min(wrap.width / v.videoWidth, wrap.height / v.videoHeight);
    const dx = (fx - 0.5) * v.videoWidth * s * zoom * (mirror ? -1 : 1);
    const dy = (fy - 0.5) * v.videoHeight * s * zoom;
    return { x: wrap.left + wrap.width / 2 + dx, y: wrap.top + wrap.height / 2 + dy, wrapLeft: wrap.left, wrapTop: wrap.top };
  }, [fx, fy, zoom, mirror]);
}

const logLen = (page) => page.evaluate(() => window.__gvLog.length);
const logFrom = (page, n) => page.evaluate((n) => window.__gvLog.slice(n), n);

async function waitPoiCall(page, n0, timeoutMs = 4000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const calls = (await logFrom(page, n0)).filter((e) => e.adv.pointsOfInterest);
    if (calls.length && calls[calls.length - 1].t1) return calls[calls.length - 1];
    await sleep(50);
  }
  return null;
}

async function tapAndCheck(scn, page, fx, fy, zoom, mirror, checks) {
  const p = await screenPoint(page, fx, fy, zoom, mirror);
  const rec = { fx, fy, zoom, mirror, screen: { x: +p.x.toFixed(1), y: +p.y.toFixed(1) } };
  // Точка может быть закрыта верхней плашкой или уйти за край экрана при зуме:
  // тогда касание принадлежит другому элементу и запроса фокуса быть не должно.
  const hit = await page.evaluate(([x, y]) => {
    const el = document.elementFromPoint(x, y);
    return el ? (el.id || el.className || el.tagName) : null;
  }, [p.x, p.y]);
  if (hit !== 'focusTarget') {
    rec.coveredBy = hit;
    const n1 = await logLen(page);
    if (hit !== null) await page.touchscreen.tap(p.x, p.y);
    await sleep(300);
    const extra = (await logFrom(page, n1)).filter((e) => e.adv.pointsOfInterest);
    expect(scn, extra.length === 0, `касание по элементу «${hit}» отправило запрос фокуса`, extra);
    return rec;
  }
  const n0 = await logLen(page);
  await page.touchscreen.tap(p.x, p.y);
  const call = await waitPoiCall(page, n0);
  if (!expect(scn, call, `нет вызова applyConstraints с pointsOfInterest для (${fx}, ${fy})`)) return rec;
  const got = call.adv.pointsOfInterest[0];
  rec.got = got;
  rec.err = Math.max(Math.abs(got.x - fx), Math.abs(got.y - fy));
  expect(scn, rec.err <= TOL, `точка фокуса не совпала: ожидалась (${fx}, ${fy})`, got);
  expect(scn, call.adv.focusMode === 'continuous', 'focusMode в запросе фокуса не continuous', call.adv);
  for (const [k, v] of Object.entries(checks || {})) {
    expect(scn, call.adv[k] === v, `запрос фокуса потерял ${k}=${v}`, call.adv);
  }
  const u = await ui(page);
  rec.markerErr = Math.hypot(u.marker.left - (p.x - p.wrapLeft), u.marker.top - (p.y - p.wrapTop));
  expect(scn, u.markerVisible && rec.markerErr < 2, 'маркер фокуса не в точке касания', rec.markerErr);
  expect(scn, u.hint === 'Запрос фокуса отправлен', 'подсказка после принятого запроса', u.hint);
  return rec;
}

async function setSlider(page, value) {
  await page.evaluate((v) => {
    const s = document.getElementById('zoom');
    s.value = String(v);
    s.dispatchEvent(new Event('input', { bubbles: true }));
  }, value);
}

async function finish(scn, page, ctx, consoleErrors, data) {
  const hints = await page.evaluate(() => window.__gvHints || []);
  expect(scn, !hints.some((h) => FALSE_SUCCESS.test(h)), 'подсказка имитирует успешную фокусировку', hints);
  const focusErrors = consoleErrors.filter((e) => !/focus|mock: pointsOfInterest/i.test(e));
  expect(scn, focusErrors.length === 0, 'ошибки консоли', focusErrors);
  await page.screenshot({ path: path.join(SHOTS, `${scn}.jpg`), type: 'jpeg', quality: 80 });
  report.scenarios[scn] = { ...data, hints: [...new Set(hints)], maxInflight: await page.evaluate(() => window.__gvMaxInflight) };
  await ctx.close();
}

const SUPPORTED = { mock: true, poi: true, focusModes: ['manual', 'single-shot', 'continuous'], zoom: true, torch: true, lenses: true };
const POINTS = [[0.5, 0.5], [0.3, 0.35], [0.7, 0.65], [0.2, 0.8], [0.85, 0.15]];
const ZOOM_POINTS = [[0.5, 0.5], [0.4, 0.4], [0.6, 0.58], [0.35, 0.62]];

async function geometryScenarios(browser, aspect) {
  const viewports = { portrait: { width: 390, height: 844 }, landscape: { width: 844, height: 390 }, tablet: { width: 768, height: 1024 } };
  for (const [vpName, vp] of Object.entries(viewports)) {
    // Основная камера, аппаратный зум и фонарик доступны
    const scn = `geom_${aspect}_${vpName}_back_hwzoom`;
    const { ctx, page, consoleErrors } = await openPage(browser, { ...SUPPORTED, initialFocusMode: 'manual' }, vp);
    const u0 = await ui(page);
    const taps = [];
    expect(scn, u0.targetVisible && u0.hintVisible && u0.hint === FOCUS_HINT, 'зона фокуса не показана при поддержке', u0);
    const init = (await logFrom(page, 0)).find((e) => e.adv.focusMode === 'continuous' && !e.adv.pointsOfInterest);
    expect(scn, !!init, 'при открытии не включён непрерывный автофокус');
    for (const [fx, fy] of POINTS) taps.push(await tapAndCheck(scn, page, fx, fy, 1, false));
    // аппаратный зум + фонарик: превью не масштабируется, параметры должны сохраниться в запросе фокуса
    await setSlider(page, 2.5);
    await sleep(150);
    await page.click('#btnTorch');
    await sleep(150);
    for (const [fx, fy] of POINTS.slice(0, 3)) taps.push(await tapAndCheck(scn, page, fx, fy, 1, false, { zoom: 2.5, torch: true }));
    // промах по полям вокруг кадра (letterbox) не должен отправлять запрос
    const u1 = await ui(page);
    const n0 = await logLen(page);
    const outside = await page.evaluate(() => {
      const wrap = document.getElementById('videoWrap').getBoundingClientRect();
      const v = document.getElementById('video');
      const s = Math.min(wrap.width / v.videoWidth, wrap.height / v.videoHeight);
      const h = v.videoHeight * s, w = v.videoWidth * s;
      if (wrap.height - h > 24) return { x: wrap.left + wrap.width / 2, y: wrap.top + (wrap.height - h) / 4 };
      if (wrap.width - w > 24) return { x: wrap.left + (wrap.width - w) / 4, y: wrap.top + wrap.height / 2 };
      return null;
    });
    let letterbox = 'нет полей при этом соотношении сторон';
    if (outside) {
      await page.touchscreen.tap(outside.x, outside.y);
      await sleep(300);
      const extra = (await logFrom(page, n0)).filter((e) => e.adv.pointsOfInterest);
      expect(scn, extra.length === 0, 'касание поля вне кадра отправило запрос фокуса', extra);
      letterbox = extra.length === 0 ? 'запрос не отправлен' : 'ОТПРАВЛЕН';
    }
    // смена ориентации без перезапуска камеры
    await page.setViewportSize({ width: vp.height, height: vp.width });
    await sleep(300);
    taps.push(await tapAndCheck(scn, page, 0.3, 0.7, 1, false, { zoom: 2.5, torch: true }));
    await finish(scn, page, ctx, consoleErrors, { viewport: vp, video: u1.video, taps, letterbox, rotatedTo: { width: vp.height, height: vp.width } });

    // Программный зум (аппаратного нет): превью масштабировано CSS
    const scn2 = `geom_${aspect}_${vpName}_back_swzoom`;
    const s2 = await openPage(browser, { ...SUPPORTED, zoom: false }, vp);
    const taps2 = [];
    for (const z of [1.5, 2.0, 3.0]) {
      await setSlider(s2.page, z);
      await sleep(150);
      const zs = (await ui(s2.page)).zoomVal;
      expect(scn2, zs === `${z.toFixed(1)}×`, 'индикатор программного зума', zs);
      for (const [fx, fy] of ZOOM_POINTS) taps2.push(await tapAndCheck(scn2, s2.page, fx, fy, z, false));
    }
    await finish(scn2, s2.page, s2.ctx, s2.consoleErrors, { viewport: vp, taps: taps2 });

    // Фронтальная камера: зеркальное превью, точка в кадре без зеркала
    const scn3 = `geom_${aspect}_${vpName}_front_mirror`;
    const s3 = await openPage(browser, { ...SUPPORTED, zoom: false }, vp);
    await s3.page.click('#lensRow .lens-btn:has-text("Фронтальная")');
    await s3.page.waitForFunction(() => document.getElementById('video').style.transform.includes('scaleX(-1)'), null, { timeout: 10000 });
    await sleep(400);
    const taps3 = [];
    for (const [fx, fy] of POINTS) taps3.push(await tapAndCheck(scn3, s3.page, fx, fy, 1, true));
    await setSlider(s3.page, 2.0);
    await sleep(150);
    for (const [fx, fy] of ZOOM_POINTS) taps3.push(await tapAndCheck(scn3, s3.page, fx, fy, 2.0, true));
    await finish(scn3, s3.page, s3.ctx, s3.consoleErrors, { viewport: vp, taps: taps3 });
  }
}

async function behaviourScenarios(browser) {
  const vp = { width: 390, height: 844 };

  // Повторные быстрые касания + зум + фонарик: вызовы строго последовательны, ни один параметр не теряется
  {
    const scn = 'serial_rapid_taps_zoom_torch';
    const { ctx, page, consoleErrors } = await openPage(browser, { ...SUPPORTED, delayMs: 250 }, vp);
    await sleep(400);
    const n0 = await logLen(page);
    const pts = [[0.3, 0.4], [0.6, 0.5], [0.45, 0.7]];
    for (const [fx, fy] of pts) {
      const p = await screenPoint(page, fx, fy, 1, false);
      await page.touchscreen.tap(p.x, p.y);
      await sleep(40);
    }
    await setSlider(page, 3.0);
    await page.click('#btnTorch');
    await sleep(2500);
    const calls = await logFrom(page, n0);
    const maxInflight = await page.evaluate(() => window.__gvMaxInflight);
    expect(scn, maxInflight === 1, 'applyConstraints вызывался параллельно', maxInflight);
    const overlaps = calls.filter((c, i) => i > 0 && c.t0 < calls[i - 1].t1 - 0.5).length;
    expect(scn, overlaps === 0, 'перекрытие вызовов applyConstraints', overlaps);
    const last = calls[calls.length - 1];
    expect(scn, last && last.adv.zoom === 3 && last.adv.torch === true, 'последний вызов не содержит итоговых зума и фонарика', last);
    const lastPoi = [...calls].reverse().find((c) => c.adv.pointsOfInterest);
    const lp = lastPoi && lastPoi.adv.pointsOfInterest[0];
    expect(scn, lp && Math.abs(lp.x - 0.45) <= TOL && Math.abs(lp.y - 0.7) <= TOL, 'итоговая точка фокуса не последнее касание', lp);
    expect(scn, last && last.adv.pointsOfInterest && Math.abs(last.adv.pointsOfInterest[0].x - 0.45) <= TOL,
      'зум/фонарик сбросили точку фокуса', last);
    const u = await ui(page);
    expect(scn, u.zoomVal === '3.0×' && u.torchOn, 'интерфейс зума/фонарика', u);
    await finish(scn, page, ctx, consoleErrors, { calls: calls.map((c) => ({ adv: c.adv, dt: +(c.t1 - c.t0).toFixed(0) })), maxInflight });
  }

  // Смена объектива во время запроса фокуса: старый запрос не применяется к новому объективу
  {
    const scn = 'lens_switch_during_focus';
    const { ctx, page, consoleErrors } = await openPage(browser, { ...SUPPORTED, delayMs: 700 }, vp);
    await sleep(900);
    await setSlider(page, 2.0);
    await sleep(800);
    const p = await screenPoint(page, 0.3, 0.3, 1, false);
    const n0 = await logLen(page);
    await page.touchscreen.tap(p.x, p.y);
    await sleep(60);
    await page.click('#lensRow .lens-btn:has-text("Фронтальная")');
    await sleep(2500);
    const calls = await logFrom(page, n0);
    const frontCalls = calls.filter((c) => c.lens === 'front');
    const leaked = frontCalls.filter((c) => c.adv.pointsOfInterest || c.adv.zoom !== undefined || c.adv.torch !== undefined);
    expect(scn, leaked.length === 0, 'параметры старого объектива перенесены на новый', leaked);
    const u = await ui(page);
    expect(scn, !u.markerVisible, 'маркер старого запроса остался после смены объектива');
    expect(scn, u.hint === FOCUS_HINT, 'подсказка после смены объектива', u.hint);
    await finish(scn, page, ctx, consoleErrors, { calls: calls.map((c) => ({ lens: c.lens, adv: c.adv })) });
  }

  // Клавиатурная активация зоны фокуса (доступность): фокус в центр кадра
  {
    const scn = 'keyboard_activation_center';
    const { ctx, page, consoleErrors } = await openPage(browser, SUPPORTED, vp);
    const n0 = await logLen(page);
    await page.focus('#focusTarget');
    await page.keyboard.press('Enter');
    const call = await waitPoiCall(page, n0);
    const pt = call && call.adv.pointsOfInterest[0];
    expect(scn, pt && Math.abs(pt.x - 0.5) <= 1e-6 && Math.abs(pt.y - 0.5) <= 1e-6, 'клавиатура: фокус не в центр', pt);
    await finish(scn, page, ctx, consoleErrors, { point: pt });
  }

  // Камера отклоняет запрос фокуса: честное сообщение, никакой имитации успеха
  {
    const scn = 'device_rejects_focus';
    const { ctx, page, consoleErrors } = await openPage(browser, { ...SUPPORTED, rejectPoi: true }, vp);
    const p = await screenPoint(page, 0.4, 0.4, 1, false);
    await page.touchscreen.tap(p.x, p.y);
    await sleep(500);
    const u = await ui(page);
    expect(scn, u.hint === 'Камера не приняла запрос фокуса', 'сообщение об отказе камеры', u.hint);
    await sleep(2000);
    const u2 = await ui(page);
    expect(scn, !u2.markerVisible && u2.hint === FOCUS_HINT, 'маркер/подсказка после отказа не сброшены', u2);
    // после отказа зум и фонарик продолжают работать
    await setSlider(page, 2.0);
    await page.click('#btnTorch');
    await sleep(400);
    const u3 = await ui(page);
    expect(scn, u3.zoomVal === '2.0×' && u3.torchOn, 'зум/фонарик сломаны отказом фокуса', u3);
    await finish(scn, page, ctx, consoleErrors, { afterReject: u, afterReset: u2, controls: u3 });
  }

  // Неподдерживаемые устройства и браузеры: зона фокуса не показывается, запросов нет
  const unsupported = {
    unsupported_no_focus_caps: { ...SUPPORTED, focusModes: null },
    unsupported_manual_only: { ...SUPPORTED, focusModes: ['manual'] },
    unsupported_browser_no_poi: { ...SUPPORTED, poi: false },
    unsupported_front_lens_fixed_focus: { ...SUPPORTED, perLens: { back: SUPPORTED, front: { focusModes: null, zoom: false, torch: false } } },
  };
  for (const [scn, cfg] of Object.entries(unsupported)) {
    const { ctx, page, consoleErrors } = await openPage(browser, cfg, vp);
    if (scn === 'unsupported_front_lens_fixed_focus') {
      const ub = await ui(page);
      expect(scn, ub.targetVisible, 'зона фокуса не показана на задней камере с поддержкой', ub);
      await page.click('#lensRow .lens-btn:has-text("Фронтальная")');
      await sleep(800);
    }
    const u = await ui(page);
    expect(scn, !u.targetVisible && !u.hintVisible, 'зона/подсказка фокуса показаны без поддержки', u);
    const n0 = await logLen(page);
    const box = await page.evaluate(() => { const r = document.getElementById('videoWrap').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    await page.touchscreen.tap(box.x, box.y);
    await sleep(400);
    const poi = (await logFrom(page, n0)).filter((e) => e.adv.pointsOfInterest);
    expect(scn, poi.length === 0, 'запрос фокуса отправлен без поддержки', poi);
    await finish(scn, page, ctx, consoleErrors, { ui: u });
  }

  // Без эмуляции: что реально отдаёт Chromium с фейковой камерой
  {
    const scn = 'native_chromium_no_mock';
    const { ctx, page, consoleErrors } = await openPage(browser, { mock: false }, vp);
    const u = await ui(page);
    const fm = Array.isArray(u.caps && u.caps.focusMode) ? u.caps.focusMode : [];
    const shouldShow = fm.includes('continuous') && u.poiSupported;
    expect(scn, u.targetVisible === shouldShow, 'видимость зоны фокуса не соответствует возможностям браузера', { caps: u.caps, poi: u.poiSupported });
    await finish(scn, page, ctx, consoleErrors, { caps: u.caps, poiSupported: u.poiSupported, targetVisible: u.targetVisible });
  }

  // Регрессия: трансляция по WSS, CV-показание и касания во время трансляции
  {
    const scn = 'streaming_wss_with_focus';
    const { ctx, page, consoleErrors } = await openPage(browser, SUPPORTED, vp);
    await page.waitForFunction(() => /В сети|Подключено|online/i.test(document.getElementById('connText').textContent), null, { timeout: 20000 }).catch(() => {});
    await page.click('#btnStream');
    const t0 = Date.now();
    let reading = null;
    for (let i = 0; i < 10; i++) {
      await sleep(1000);
      const p = await screenPoint(page, 0.3 + 0.04 * i, 0.5, 1, false);
      await page.touchscreen.tap(p.x, p.y);
    }
    while (Date.now() - t0 < 40000) {
      reading = await page.evaluate(() => document.getElementById('reading').firstChild.textContent);
      if (reading && reading !== '—') break;
      await sleep(500);
    }
    const stats = await page.evaluate(() => document.getElementById('stats').textContent);
    const conn = await page.evaluate(() => document.getElementById('connText').textContent);
    const fps = parseFloat((stats.match(/([\d.]+)\s*к\/с/) || [])[1] || '0');
    expect(scn, fps > 0, 'кадры не передаются по WSS', stats);
    expect(scn, reading && reading !== '—' && Number.isFinite(Number(reading)), 'нет CV-показания по кадрам смартфона', reading);
    const poiCalls = (await page.evaluate(() => window.__gvLog)).filter((e) => e.adv.pointsOfInterest).length;
    expect(scn, poiCalls >= 10, 'касания во время трансляции не дошли до камеры', poiCalls);
    await page.click('#btnStream');
    await finish(scn, page, ctx, consoleErrors, { reading: Number(reading), stats, conn, poiCalls });
  }
}

(async () => {
  for (const [aspect, file] of Object.entries(VIDEOS)) {
    const browser = await chromium.launch({
      headless: true,
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
        `--use-file-for-fake-video-capture=${file}`, '--ignore-certificate-errors'],
    });
    try {
      await geometryScenarios(browser, aspect);
      if (aspect === '16x9') await behaviourScenarios(browser);
    } catch (e) {
      report.failures.push(`исключение (${aspect}): ${e && e.stack || e}`);
    } finally {
      await browser.close();
    }
  }
  const taps = Object.values(report.scenarios).flatMap((s) => s.taps || []).filter((t) => t.err !== undefined);
  report.summary = {
    scenarios: Object.keys(report.scenarios).length,
    taps_checked: taps.length,
    taps_covered_by_other_ui: Object.values(report.scenarios).flatMap((s) => s.taps || []).filter((t) => t.coveredBy !== undefined)
      .map((t) => ({ fx: t.fx, fy: t.fy, zoom: t.zoom, coveredBy: t.coveredBy })),
    max_point_error: taps.length ? Math.max(...taps.map((t) => t.err)) : null,
    max_marker_error_px: taps.length ? Math.max(...taps.map((t) => t.markerErr)) : null,
    failures: report.failures.length,
  };
  fs.writeFileSync(path.join(OUT_DIR, 'capture_focus_report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report.summary, null, 2));
  if (report.failures.length) console.log(report.failures.slice(0, 40).join('\n'));
  process.exit(report.failures.length ? 1 : 0);
})();
