// Authenticated 25-Step Air-Gapped Remediation E2E Browser Driver (Playwright)
const path = require('path');
const fs = require('fs');
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');

const BASE_URL = process.argv[2] || 'http://127.0.0.1:18450';
const OUT_DIR = process.argv[3];
const ADMIN_PASS = process.argv[4] || 'GaugeAdmin!2026';
const SHOTS_DIR = path.join(OUT_DIR, 'screenshots');
fs.mkdirSync(SHOTS_DIR, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    ignoreHTTPSErrors: true,
    acceptDownloads: true,
  });

  const externalAttempts = [];
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];

  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (
      url.startsWith(BASE_URL)
      || url.startsWith('data:')
      || url.startsWith('blob:')
      || url.startsWith('http://127.0.0.1')
      || url.startsWith('https://127.0.0.1')
      || url.startsWith('http://localhost')
      || url.startsWith('https://localhost')
      || url.startsWith('ws://127.0.0.1')
      || url.startsWith('wss://127.0.0.1')
    ) {
      route.continue();
    } else {
      externalAttempts.push(url);
      route.abort('blockedbyclient');
    }
  });

  const page = await context.newPage();
  let expectIntentional401 = false;
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const txt = msg.text();
      if (expectIntentional401 && txt.includes('401')) return;
      consoleErrors.push(txt);
    }
  });
  page.on('pageerror', (err) => pageErrors.push(String(err)));
  page.on('response', (res) => {
    const st = res.status();
    const u = res.url();
    if (st >= 400 && !(expectIntentional401 && st === 401 && u.includes('/api/auth/login'))) {
      failedRequests.push({ url: u, status: st });
    }
  });

  const report = {
    baseUrl: BASE_URL,
    airGappedBlockedExternalUrls: externalAttempts,
    viewports: {},
    steps: {},
  };

  // Step 1: Load HMI with RBAC active -> login dialog opens automatically
  const tLoad0 = Date.now();
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 25000 });
  await page.waitForSelector('#dlgLogin[open]', { timeout: 10000 });
  report.steps.step01_loginModalOpened = true;
  report.steps.initialLoadMs = Date.now() - tLoad0;
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_01_login_modal_1920x1080.png') });

  // Step 2: Wrong password rejected cleanly
  expectIntentional401 = true;
  await page.fill('#inpLoginUser', 'admin');
  await page.fill('#inpLoginPass', 'WrongPass!000');
  await page.click('#btnLoginSubmit');
  await page.waitForTimeout(450);
  expectIntentional401 = false;
  report.steps.step02_wrongPassError = await page.evaluate(() => document.querySelector('#loginErr')?.textContent?.trim() || '');

  // Step 3: Valid admin login -> modal closes, role badge updates, WS connects, 36 tiles appear
  await page.fill('#inpLoginUser', 'admin');
  await page.fill('#inpLoginPass', ADMIN_PASS);
  await page.click('#btnLoginSubmit');
  await page.waitForSelector('.tile', { timeout: 15000 });
  await page.waitForTimeout(1600);
  report.steps.step03_authUser = await page.evaluate(() => ({
    label: document.querySelector('#authUserLbl')?.textContent?.trim(),
    modalClosed: !document.querySelector('#dlgLogin')?.open,
    disclaimerText: document.querySelector('#hmiDisclaimer')?.innerText?.replace(/\s+/g, ' ').trim(),
  }));

  const checkViewport = async (name, w, h, shotName) => {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(450);
    const m = await page.evaluate(() => {
      const head = document.querySelector('header.head');
      const children = head ? Array.from(head.children).filter((el) => getComputedStyle(el).display !== 'none') : [];
      const maxRight = Math.max(0, ...children.map((el) => Math.round(el.getBoundingClientRect().right)));
      return {
        vw: window.innerWidth,
        vh: window.innerHeight,
        docScrollW: document.documentElement.scrollWidth,
        headScrollW: head ? head.scrollWidth : 0,
        headClientW: head ? head.clientWidth : 0,
        maxRight,
        clipped: maxRight > window.innerWidth + 1 || document.documentElement.scrollWidth > window.innerWidth + 1,
        tilesCount: document.querySelectorAll('.tile').length,
        middleDotCount: (document.body.innerText.match(/\u00b7/g) || []).length,
        linkText: document.querySelector('#linkText')?.textContent?.trim(),
        cAlarm: document.querySelector('#cAlarm')?.textContent?.trim(),
        cWarn: document.querySelector('#cWarn')?.textContent?.trim(),
        cNoData: document.querySelector('#cNoData')?.textContent?.trim(),
      };
    });
    report.viewports[name] = m;
    if (shotName) await page.screenshot({ path: path.join(SHOTS_DIR, shotName) });
    return m;
  };

  // Step 4-5: 1920x1080 Monitor check
  await checkViewport('1920x1080', 1920, 1080, 'rem_02_monitor_1920x1080.png');

  // Step 6: Open Inspector on tile #1 and check trend fit
  await page.click('.tile');
  await page.waitForTimeout(600);
  report.steps.step06_inspector = await page.evaluate(() => {
    const pane = document.querySelector('#detailPane');
    const trend = document.querySelector('#detTrendCanvas');
    const tr = trend ? trend.getBoundingClientRect() : null;
    return {
      visible: Boolean(pane && !pane.hidden),
      trendInViewport: tr ? (tr.bottom <= window.innerHeight + 2 && tr.height >= 140) : false,
      trendH: tr ? Math.round(tr.height) : 0,
    };
  });
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_03_inspector_1920x1080.png') });
  await page.click('#btnDetailClose');
  await page.waitForTimeout(250);

  // Step 7-11: Track 2 Architecture, Modbus/MQTT, Outage + S&F drain, Steam + Partial Occlusion + Recover
  await page.click('[data-view="architecture"]');
  await page.waitForTimeout(1800);
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_04_architecture_normal_1920x1080.png') });

  report.steps.step07_archNormal = await page.evaluate(() => ({
    streamCards: document.querySelectorAll('.arch-cam-card').length,
    sfPending: Number(document.querySelector('#sfPendingVal')?.textContent || '0'),
    sfDelivered: Number(document.querySelector('#sfDeliveredVal')?.textContent || '0'),
    modbusRows: document.querySelectorAll('#archScadaBody tbody tr').length,
  }));

  await page.click('#segScadaTab [data-scada="mqtt"]');
  await page.waitForTimeout(400);
  report.steps.step08_mqttRows = await page.evaluate(() => document.querySelectorAll('#archScadaBody tbody tr').length);
  await page.click('#segScadaTab [data-scada="modbus"]');
  await page.waitForTimeout(250);

  // Outage -> buffer -> recover -> drain
  await page.click('#btnArchToggleOutage');
  await page.waitForTimeout(4800);
  report.steps.step09_outage = await page.evaluate(() => ({
    sfPending: Number(document.querySelector('#sfPendingVal')?.textContent || '0'),
    linkBroken: document.querySelector('#topoLinkScada')?.dataset?.broken,
    banner: document.querySelector('#archOutageBanner')?.textContent?.trim(),
  }));
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_05_architecture_outage_1920x1080.png') });

  await page.click('#btnArchToggleOutage');
  await page.waitForTimeout(2600);
  report.steps.step10_recovered = await page.evaluate(() => ({
    sfPending: Number(document.querySelector('#sfPendingVal')?.textContent || '0'),
    sfDelivered: Number(document.querySelector('#sfDeliveredVal')?.textContent || '0'),
    batchRows: document.querySelectorAll('#archBatchBody tr').length,
  }));

  // Fault injection: steam -> partial_occlusion -> recover on bench card
  const secondCard = await page.$('.arch-cam-card:nth-child(2)');
  if (secondCard) {
    await secondCard.click();
    await page.waitForTimeout(350);
    await page.click('#archFaultBtns [data-fault="steam"]');
    await page.waitForTimeout(2300);
    const stSteam = await page.evaluate(() => document.querySelector('#archFocusHealth')?.textContent?.trim());
    await page.click('#archFaultBtns [data-fault="partial_occlusion"]');
    await page.waitForTimeout(2300);
    const stOcc = await page.evaluate(() => document.querySelector('#archFocusHealth')?.textContent?.trim());
    await page.click('#archFaultBtns [data-fault="recover"]');
    await page.waitForTimeout(2300);
    const stRec = await page.evaluate(() => document.querySelector('#archFocusHealth')?.textContent?.trim());
    report.steps.step11_faultCycle = { steam: stSteam, partial_occlusion: stOcc, recovered: stRec };
  }

  // Step 12-16: Track 1 Dispatch & Spec Builder (.md & .docx download)
  await page.click('[data-view="dispatch"]');
  await page.waitForTimeout(1600);
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_06_dispatch_1920x1080.png') });

  report.steps.step12_dispatch = await page.evaluate(() => ({
    avgHealth: document.querySelector('#dispAvgHealth')?.textContent?.trim(),
    matrixRows: document.querySelectorAll('#dispMatrixBody tr').length,
    recsCount: document.querySelectorAll('#dispRecsList li').length,
    hasAutoSpecsSection: Boolean(document.querySelector('#autoSpecsSection')),
    middleDotCount: (document.body.innerText.match(/\u00b7/g) || []).length,
  }));

  await page.fill('#specPlant', 'ТЭЦ-Приёмка ПАО «Интер РАО»');
  await page.fill('#specDocNum', 'ТЗ-РЕМЕДИАЦИЯ-2026-01');
  await page.selectOption('#specPeriod', '24h');
  await page.waitForTimeout(900);

  report.steps.step13_specPreview = await page.evaluate(() => {
    const txt = document.querySelector('#specPreviewBox')?.innerText || '';
    return {
      len: txt.length,
      hasPlant: txt.includes('ТЭЦ-Приёмка'),
      hasDocNum: txt.includes('ТЗ-РЕМЕДИАЦИЯ-2026-01'),
      hasDisclaimer: txt.includes('ФЗ-102'),
      ecoSummary: document.querySelector('#specEcoSummary')?.textContent?.trim(),
    };
  });

  await page.locator('#specForm').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_07_spec_builder_1920x1080.png') });

  const [dlDocx] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.click('#btnSpecDownloadDocx'),
  ]);
  const docxPath = path.join(OUT_DIR, 'remediation_e2e_spec.docx');
  await dlDocx.saveAs(docxPath);
  report.steps.step14_docx = { filename: dlDocx.suggestedFilename(), bytes: fs.statSync(docxPath).size };

  const [dlMd] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.click('#btnSpecDownloadMd'),
  ]);
  const mdPath = path.join(OUT_DIR, 'remediation_e2e_spec.md');
  await dlMd.saveAs(mdPath);
  report.steps.step15_md = { filename: dlMd.suggestedFilename(), bytes: fs.statSync(mdPath).size };

  // Step 17-20: Events, History, Cameras, Calibration tabs cleanliness
  for (const tab of ['events', 'history', 'cameras', 'calibration']) {
    await page.click(`[data-view="${tab}"]`);
    await page.waitForTimeout(450);
  }

  // Step 21-24: Responsive viewports 1440x900 & 1280x720 (DEF-16 verification!)
  await page.click('[data-view="monitor"]');
  await page.waitForTimeout(450);
  await checkViewport('1440x900', 1440, 900, 'rem_08_monitor_1440x900.png');
  await checkViewport('1280x720', 1280, 720, 'rem_09_monitor_1280x720.png');

  await page.click('[data-view="architecture"]');
  await page.waitForTimeout(450);
  report.viewports.arch_1280x720 = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    vw: window.innerWidth,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  }));
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_10_arch_1280x720.png') });

  await page.click('[data-view="dispatch"]');
  await page.waitForTimeout(450);
  report.viewports.dispatch_1280x720 = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    vw: window.innerWidth,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  }));
  await page.screenshot({ path: path.join(SHOTS_DIR, 'rem_11_dispatch_1280x720.png') });

  // Step 25: Logout re-opens login dialog
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.waitForTimeout(250);
  await page.click('#btnAuthAction');
  await page.waitForSelector('#dlgLogin[open]', { timeout: 5000 });
  await page.click('#btnLogout');
  await page.waitForTimeout(600);
  report.steps.step25_logoutReopenedModal = await page.evaluate(() => Boolean(document.querySelector('#dlgLogin')?.open));

  report.diagnostics = {
    consoleErrors,
    pageErrors,
    failedRequests,
    externalNetworkRequestsBlocked: externalAttempts.length,
  };

  fs.writeFileSync(path.join(OUT_DIR, 'remediation_browser_report.json'), JSON.stringify(report, null, 2), 'utf-8');
  console.log('REMEDIATION_BROWSER_E2E_DONE', JSON.stringify({
    extBlocked: externalAttempts.length,
    consoleErrs: consoleErrors.length,
    pageErrs: pageErrors.length,
    failedReqs: failedRequests.length,
    clipped1920: report.viewports['1920x1080'].clipped,
    clipped1440: report.viewports['1440x900'].clipped,
    clipped1280: report.viewports['1280x720'].clipped,
    docxBytes: report.steps.step14_docx.bytes,
    mdBytes: report.steps.step15_md.bytes,
  }));

  await browser.close();
})();
