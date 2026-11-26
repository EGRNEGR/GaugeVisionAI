// Браузерный E2E повторной приёмки GaugeVision AI (Playwright, Chromium headless, air-gapped).
// Запускается оркестратором browser_e2e.py: node browser_e2e_driver.js <baseUrl> <outDir> <adminPass> <operatorPass>
// Модуль playwright-core: переменная GV_PLAYWRIGHT_CORE (путь к пакету) или обычный require.
'use strict';
const path = require('path');
const fs = require('fs');
const { chromium } = require(process.env.GV_PLAYWRIGHT_CORE || 'playwright-core');

const [BASE_URL, OUT_DIR, ADMIN_PASS, OPERATOR_PASS] = process.argv.slice(2);
const SHOTS = path.join(OUT_DIR, 'screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

const report = { baseUrl: BASE_URL, steps: {}, viewports: {}, failures: [] };
const expect = (cond, msg, extra) => {
  if (!cond) report.failures.push(extra === undefined ? msg : `${msg}: ${JSON.stringify(extra)}`);
  return cond;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitNumber(page, selector, pred, timeoutMs) {
  const t0 = Date.now();
  let v = NaN;
  while (Date.now() - t0 < timeoutMs) {
    v = await page.evaluate((s) => Number((document.querySelector(s)?.textContent || '').replace(/\s/g, '')), selector);
    if (pred(v)) return { value: v, ms: Date.now() - t0 };
    await sleep(400);
  }
  return { value: v, ms: null };
}

// Проверка компоновки: горизонтальное переполнение, элементы шапки за краем экрана
// и усечённый текст (DEF-16: «Список» → «Списо») у видимых кнопок/вкладок/плашек.
async function layoutProbe(page) {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const visible = (el) => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    };
    const head = document.querySelector('header.head');
    const headKids = head ? Array.from(head.children).filter(visible) : [];
    const beyond = headKids.filter((el) => el.getBoundingClientRect().right > vw + 1).map((el) => el.className || el.id);
    const truncated = [];
    const cands = document.querySelectorAll('header.head button, header.head .nav-tab, header.head .plant-banner *, header.head .chip, .view:not([hidden]) .btn');
    cands.forEach((el) => {
      if (!visible(el)) return;
      const txt = (el.innerText || '').trim();
      if (!txt) return;
      if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible') {
        truncated.push({ text: txt.slice(0, 40), scrollW: el.scrollWidth, clientW: el.clientWidth });
      }
    });
    return {
      vw,
      docScrollW: document.documentElement.scrollWidth,
      horizontalOverflow: document.documentElement.scrollWidth > vw + 1,
      headerBeyondViewport: beyond,
      truncatedTexts: truncated,
      middleDots: (document.body.innerText.match(/·/g) || []).length,
    };
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, ignoreHTTPSErrors: true, acceptDownloads: true });
  const external = [];
  const consoleErrors = [];
  const pageErrors = [];
  const failed = [];
  let allow401 = false;
  await context.route('**/*', (route) => {
    const u = route.request().url();
    const local = u.startsWith(BASE_URL) || /^(https?|wss?):\/\/(127\.0\.0\.1|localhost)(:|\/)/.test(u) || u.startsWith('data:') || u.startsWith('blob:');
    if (local) return route.continue();
    external.push(u);
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error' && !(allow401 && /401|403/.test(m.text()))) consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  page.on('response', (r) => {
    if (r.status() >= 400 && !(allow401 && [401, 403].includes(r.status()))) failed.push({ url: r.url(), status: r.status() });
  });

  try {
    // 1. Вход: окно авторизации, неверный пароль, вход администратора
    const t0 = Date.now();
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForSelector('#dlgLogin[open]', { timeout: 10000 });
    report.steps.loadMs = Date.now() - t0;
    await page.screenshot({ path: path.join(SHOTS, 'e2e_01_login_1920x1080.png') });
    allow401 = true;
    await page.fill('#inpLoginUser', 'admin');
    await page.fill('#inpLoginPass', 'Wrong-Password-1');
    await page.click('#btnLoginSubmit');
    await sleep(600);
    const wrongErr = await page.evaluate(() => document.querySelector('#loginErr')?.textContent?.trim() || '');
    expect(wrongErr.length > 0, 'нет сообщения о неверном пароле');
    expect(await page.evaluate(() => document.querySelector('#dlgLogin')?.open === true), 'окно входа закрылось при неверном пароле');
    allow401 = false;
    await page.fill('#inpLoginPass', ADMIN_PASS);
    await page.click('#btnLoginSubmit');
    await page.waitForSelector('.tile', { timeout: 20000 });
    await sleep(2000);
    const tiles = await page.evaluate(() => document.querySelectorAll('.tile').length);
    report.steps.login = { wrongErr, tiles, user: await page.evaluate(() => document.querySelector('#authUserLbl')?.textContent?.trim()) };
    expect(tiles === 36, '36 плиток приборов после входа', tiles);

    // 2. Компоновка на трёх разрешениях и трёх рабочих контурах
    for (const [w, h] of [[1920, 1080], [1440, 900], [1280, 720]]) {
      await page.setViewportSize({ width: w, height: h });
      for (const view of ['monitor', 'architecture', 'dispatch']) {
        await page.click(`[data-view="${view}"]`);
        await sleep(900);
        const m = await layoutProbe(page);
        report.viewports[`${view}_${w}x${h}`] = m;
        expect(!m.horizontalOverflow, `горизонтальное переполнение ${view} ${w}x${h}`, m.docScrollW);
        expect(m.headerBeyondViewport.length === 0, `шапка за краем экрана ${view} ${w}x${h}`, m.headerBeyondViewport);
        expect(m.truncatedTexts.length === 0, `усечённый текст ${view} ${w}x${h}`, m.truncatedTexts);
        expect(m.middleDots === 0, `символ middle dot ${view} ${w}x${h}`, m.middleDots);
        await page.screenshot({ path: path.join(SHOTS, `e2e_${view}_${w}x${h}.png`) });
      }
    }
    await page.setViewportSize({ width: 1920, height: 1080 });

    // 3. Инспектор прибора
    await page.click('[data-view="monitor"]');
    await sleep(500);
    await page.click('.tile');
    await sleep(800);
    const insp = await page.evaluate(() => ({ visible: !document.querySelector('#detailPane')?.hidden }));
    expect(insp.visible, 'инспектор прибора не открылся');
    await page.screenshot({ path: path.join(SHOTS, 'e2e_inspector_1920x1080.png') });
    await page.click('#btnDetailClose');

    // 4. Архитектура: обрыв АСУ ТП → накопление → восстановление → досылка
    await page.click('[data-view="architecture"]');
    await sleep(1500);
    const cards = await page.evaluate(() => document.querySelectorAll('.arch-cam-card').length);
    expect(cards >= 3, 'карточки видеоканалов', cards);
    await page.click('#btnArchToggleOutage');
    const grow = await waitNumber(page, '#sfPendingVal', (v) => v > 0, 15000);
    const banner = await page.evaluate(() => document.querySelector('#archOutageBanner')?.textContent?.trim() || '');
    await page.screenshot({ path: path.join(SHOTS, 'e2e_architecture_outage_1920x1080.png') });
    await page.click('#btnArchToggleOutage');
    const drain = await waitNumber(page, '#sfPendingVal', (v) => v === 0, 30000);
    report.steps.outage = { pendingDuringOutage: grow.value, growMs: grow.ms, banner, drainMs: drain.ms };
    expect(grow.ms !== null, 'очередь не росла при обрыве', grow);
    expect(drain.ms !== null, 'очередь не досылалась после восстановления', drain);

    // 5. Инъекция деградации видеосигнала на стендовом канале и восстановление
    const card2 = await page.$('.arch-cam-card:nth-child(2)');
    if (expect(Boolean(card2), 'нет второй карточки канала')) {
      await card2.click();
      await sleep(400);
      const states = {};
      for (const f of ['steam', 'partial_occlusion', 'recover']) {
        await page.click(`#archFaultBtns [data-fault="${f}"]`);
        await sleep(3500);
        states[f] = await page.evaluate(() => document.querySelector('#archFocusHealth')?.textContent?.trim() || '');
      }
      report.steps.faults = states;
      expect(/DEGRADED|ДЕГРАД/i.test(states.steam), 'пар не перевёл канал в DEGRADED', states);
      expect(/DEGRADED|ДЕГРАД/i.test(states.partial_occlusion), 'частичное перекрытие не перевело канал в DEGRADED', states);
      expect(/ONLINE|НОРМ|В СЕТИ/i.test(states.recover), 'канал не восстановился', states);
    }

    // 6. Диспетчеризация: матрица, теги ленты инцидентов (DEF-18), автодокументы
    await page.click('[data-view="dispatch"]');
    await sleep(2500);
    const disp = await page.evaluate(() => {
      const tags = Array.from(document.querySelectorAll('#dispIncidentsStrip .tag')).map((t) => ({ level: t.dataset.level, text: t.textContent.trim() }));
      return {
        matrixRows: document.querySelectorAll('#dispMatrixBody tr').length,
        tags,
        autoSpecs: Boolean(document.querySelector('#autoSpecsSection')),
      };
    });
    report.steps.dispatch = disp;
    expect(disp.matrixRows === 36, 'строки матрицы Health Score', disp.matrixRows);
    const wrongTags = disp.tags.filter((t) => (t.level === 'normal' && t.text !== 'НОРМА') || (t.text === 'СВЯЗЬ' && t.level !== 'stale'));
    expect(wrongTags.length === 0, 'неверные теги ленты инцидентов (DEF-18)', wrongTags);
    expect(disp.autoSpecs, 'нет раздела автоматически сформированных ТЗ');

    // 7. Конструктор ТЗ: реквизиты, предпросмотр, скачивание .docx и .md
    await page.fill('#specPlant', 'ТЭЦ стенда приёмки');
    await page.fill('#specDocNum', 'ТЗ-ПРИЁМКА-2026-11');
    await page.selectOption('#specPeriod', '24h');
    await sleep(1500);
    const prev = await page.evaluate(() => document.querySelector('#specPreviewBox')?.innerText || '');
    report.steps.specPreview = { len: prev.length, plant: prev.includes('ТЭЦ стенда приёмки'), num: prev.includes('ТЗ-ПРИЁМКА-2026-11'), law: prev.includes('ФЗ-102'), period: prev.includes('24 часа') };
    expect(report.steps.specPreview.plant && report.steps.specPreview.num && report.steps.specPreview.law, 'предпросмотр ТЗ', report.steps.specPreview);
    await page.locator('#specForm').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(SHOTS, 'e2e_spec_builder_1920x1080.png') });
    const [dDocx] = await Promise.all([page.waitForEvent('download', { timeout: 20000 }), page.click('#btnSpecDownloadDocx')]);
    await dDocx.saveAs(path.join(OUT_DIR, 'e2e_spec.docx'));
    const [dMd] = await Promise.all([page.waitForEvent('download', { timeout: 20000 }), page.click('#btnSpecDownloadMd')]);
    await dMd.saveAs(path.join(OUT_DIR, 'e2e_spec.md'));
    report.steps.downloads = { docx: dDocx.suggestedFilename(), md: dMd.suggestedFilename() };

    // 8. Остальные вкладки без ошибок
    for (const tab of ['events', 'history', 'cameras', 'calibration', 'monitor']) {
      await page.click(`[data-view="${tab}"]`);
      await sleep(600);
    }

    // 9. Выход: окно входа, API закрыт
    await page.click('#btnAuthAction');
    await page.waitForSelector('#dlgLogin[open]', { timeout: 5000 });
    allow401 = true;
    await page.click('#btnLogout');
    await sleep(900);
    const after = await page.evaluate(async () => ({
      modal: Boolean(document.querySelector('#dlgLogin')?.open),
      api: (await fetch('/api/cameras', { credentials: 'same-origin' })).status,
    }));
    report.steps.logout = after;
    expect(after.modal && after.api === 401, 'выход из системы', after);

    // 10. Оператор: просмотр доступен, формирование ТЗ запрещено сервером
    await page.fill('#inpLoginUser', 'operator');
    await page.fill('#inpLoginPass', OPERATOR_PASS);
    await page.click('#btnLoginSubmit');
    await page.waitForSelector('.tile', { timeout: 20000 });
    await sleep(1200);
    const op = await page.evaluate(async () => ({
      overview: (await fetch('/api/dispatch/overview')).status,
      generate: (await fetch('/api/specs/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"period":"12h"}' })).status,
      outage: (await fetch('/api/architecture/outage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"active":true}' })).status,
    }));
    allow401 = false;
    report.steps.operator = op;
    expect(op.overview === 200 && op.generate === 403 && op.outage === 403, 'RBAC оператора в браузере', op);
  } catch (e) {
    report.failures.push(`исключение: ${e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e}`);
    await page.screenshot({ path: path.join(SHOTS, 'e2e_exception.png') }).catch(() => {});
  }
  report.diagnostics = { consoleErrors, pageErrors, failedRequests: failed, externalRequestsBlocked: external };
  expect(consoleErrors.length === 0, 'ошибки консоли', consoleErrors);
  expect(pageErrors.length === 0, 'ошибки страницы', pageErrors);
  expect(failed.length === 0, 'HTTP 4xx/5xx', failed);
  expect(external.length === 0, 'обращения во внешнюю сеть', external);
  report.passed = report.failures.length === 0;
  fs.writeFileSync(path.join(OUT_DIR, 'browser_e2e_report.json'), JSON.stringify(report, null, 2), 'utf-8');
  console.log('BROWSER_E2E', JSON.stringify({ passed: report.passed, failures: report.failures }));
  await browser.close();
  process.exit(report.passed ? 0 : 1);
})();
