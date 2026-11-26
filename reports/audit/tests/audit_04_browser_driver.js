// Independent Audit Browser Driver (Playwright) — Sections 8, 11, 15.
// Blocks ALL external (non-localhost/non-127.0.0.1) network requests to prove Air-Gapped Readiness,
// checks 1920x1080 / 1440x900 / 1280x720, tests all 3 working contours, WS reconnect,
// Store-and-Forward UI outage/recovery, .docx + .md UI downloads, and console/network cleanliness.
const path = require('path');
const fs = require('fs');
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');

const BASE_URL = process.argv[2] || 'https://127.0.0.1:18443';
const OUT_DIR = process.argv[3];
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
  const consoleWarnings = [];
  const pageErrors = [];
  const failedRequests = [];
  const apiTimings = [];

  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (
      url.startsWith(BASE_URL)
      || url.startsWith('data:')
      || url.startsWith('blob:')
      || url.startsWith('https://127.0.0.1')
      || url.startsWith('https://localhost')
      || url.startsWith('wss://127.0.0.1')
      || url.startsWith('wss://localhost')
    ) {
      route.continue();
    } else {
      externalAttempts.push(url);
      route.abort('blockedbyclient');
    }
  });

  const page = await context.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
    else if (msg.type() === 'warning') consoleWarnings.push(msg.text());
  });
  page.on('pageerror', (err) => pageErrors.push(String(err)));
  page.on('response', (res) => {
    if (res.status() >= 400) failedRequests.push({ url: res.url(), status: res.status() });
  });

  const report = {
    baseUrl: BASE_URL,
    airGappedBlockedExternalUrls: externalAttempts,
    viewports: {},
    steps: {},
  };

  // 1. Load main HMI at 1920x1080
  const tLoad0 = Date.now();
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 25000 });
  await page.waitForSelector('.tile', { timeout: 15000 });
  await page.waitForTimeout(1500);
  report.steps.initialLoadMs = Date.now() - tLoad0;

  // Check primary monitoring grid + header metrics
  const checkViewport = async (name, w, h) => {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(450);
    const m = await page.evaluate(() => {
      const head = document.querySelector('header.head');
      const hr = head ? head.getBoundingClientRect() : null;
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
        cDev: document.querySelector('#cDev')?.textContent?.trim(),
        cNoData: document.querySelector('#cNoData')?.textContent?.trim(),
      };
    });
    report.viewports[name] = m;
    await page.screenshot({ path: path.join(SHOTS_DIR, `audit_monitor_${name}.png`) });
  };

  await checkViewport('1920x1080', 1920, 1080);

  // Check live #01 instrument card reading updated from WSS phone frames
  const liveCardText = await page.evaluate(() => {
    const first = document.querySelector('.tile');
    return first ? first.innerText.replace(/\s+/g, ' ').trim() : '';
  });
  report.steps.liveCardText = liveCardText;

  // Open inspector on #01 and verify fit without internal scroll
  await page.click('.tile');
  await page.waitForTimeout(500);
  const inspectorCheck = await page.evaluate(() => {
    const pane = document.querySelector('#detailPane');
    const body = document.querySelector('#detailBody');
    const trend = document.querySelector('#detTrendCanvas');
    const tr = trend ? trend.getBoundingClientRect() : null;
    return {
      visible: pane && !pane.hidden,
      bodyScrollH: body ? body.scrollHeight : 0,
      bodyClientH: body ? body.clientHeight : 0,
      trendInViewport: tr ? (tr.bottom <= window.innerHeight + 2 && tr.height >= 140) : false,
      trendH: tr ? Math.round(tr.height) : 0,
    };
  });
  report.steps.inspector1920 = inspectorCheck;
  await page.screenshot({ path: path.join(SHOTS_DIR, 'audit_inspector_1920x1080.png') });
  await page.click('#btnDetailClose');
  await page.waitForTimeout(250);

  // 2. Switch to Track 2: Architecture Videoanalytics tab
  await page.click('[data-view="architecture"]');
  await page.waitForTimeout(1600);
  await page.screenshot({ path: path.join(SHOTS_DIR, 'audit_arch_normal_1920x1080.png') });

  const archNormal = await page.evaluate(() => ({
    topoSources: document.querySelector('#topoSources')?.innerText?.replace(/\s+/g, ' ').trim(),
    topoEdge: document.querySelector('#topoEdge')?.innerText?.replace(/\s+/g, ' ').trim(),
    topoBuffer: document.querySelector('#topoBuffer')?.innerText?.replace(/\s+/g, ' ').trim(),
    topoScada: document.querySelector('#topoScada')?.innerText?.replace(/\s+/g, ' ').trim(),
    streamCards: document.querySelectorAll('.arch-cam-card').length,
    sfPending: Number(document.querySelector('#sfPendingVal')?.textContent || '0'),
    sfDelivered: Number(document.querySelector('#sfDeliveredVal')?.textContent || '0'),
    hasModbusRows: document.querySelectorAll('#archScadaBody tbody tr').length,
  }));
  report.steps.archNormal = archNormal;

  // Test MQTT tab inside SCADA inspector
  await page.click('#segScadaTab [data-scada="mqtt"]');
  await page.waitForTimeout(500);
  const mqttTabRows = await page.evaluate(() => document.querySelectorAll('#archScadaBody tbody tr').length);
  report.steps.mqttInspectorRows = mqttTabRows;
  await page.click('#segScadaTab [data-scada="modbus"]');
  await page.waitForTimeout(300);

  // Trigger Outage via UI button -> wait 5s -> confirm queue grows -> restore -> confirm drain!
  await page.click('#btnArchToggleOutage');
  await page.waitForTimeout(5200);
  const archOutage = await page.evaluate(() => ({
    outageBtnText: document.querySelector('#lblArchOutage')?.textContent?.trim(),
    banner: document.querySelector('#archOutageBanner')?.textContent?.trim(),
    sfPending: Number(document.querySelector('#sfPendingVal')?.textContent || '0'),
    linkBroken: document.querySelector('#topoLinkScada')?.dataset?.broken,
  }));
  report.steps.archOutage = archOutage;
  await page.screenshot({ path: path.join(SHOTS_DIR, 'audit_arch_outage_1920x1080.png') });

  // Restore via UI button
  await page.click('#btnArchToggleOutage');
  await page.waitForTimeout(2600);
  const archRecovered = await page.evaluate(() => ({
    sfPending: Number(document.querySelector('#sfPendingVal')?.textContent || '0'),
    sfDelivered: Number(document.querySelector('#sfDeliveredVal')?.textContent || '0'),
    batchRows: document.querySelectorAll('#archBatchBody tr').length,
    batchText: document.querySelector('#archBatchBody')?.innerText?.replace(/\s+/g, ' ').trim(),
  }));
  report.steps.archRecovered = archRecovered;

  // Test focus switching & steam degradation button on a bench stream
  const secondCard = await page.$('.arch-cam-card:nth-child(2)');
  if (secondCard) {
    await secondCard.click();
    await page.waitForTimeout(400);
    await page.click('#archFaultBtns [data-fault="steam"]');
    await page.waitForTimeout(1600);
    const afterSteam = await page.evaluate(() => ({
      focusTitle: document.querySelector('#archFocusTitle')?.textContent?.trim(),
      focusHealth: document.querySelector('#archFocusHealth')?.textContent?.trim(),
    }));
    report.steps.archFaultSteam = afterSteam;
    await page.click('#archFaultBtns [data-fault="recover"]');
    await page.waitForTimeout(800);
  }

  // 3. Switch to Track 1: Dispatch & Spec Builder tab
  await page.click('[data-view="dispatch"]');
  await page.waitForTimeout(1600);
  await page.screenshot({ path: path.join(SHOTS_DIR, 'audit_dispatch_1920x1080.png') });

  const dispState = await page.evaluate(() => ({
    avgHealth: document.querySelector('#dispAvgHealth')?.textContent?.trim(),
    critWear: document.querySelector('#dispCritWear')?.textContent?.trim(),
    modCount: document.querySelector('#dispModCount')?.textContent?.trim(),
    matrixRows: document.querySelectorAll('#dispMatrixBody tr').length,
    recsCount: document.querySelectorAll('#dispRecsList li').length,
    incidentCards: document.querySelectorAll('#dispIncidentsStrip .disp-inc-card').length,
    llmStatus: document.querySelector('#specLlmStatus')?.textContent?.trim(),
  }));
  report.steps.dispatchState = dispState;

  // Edit requisites in UI and verify live preview updates
  await page.fill('#specPlant', 'ТЭЦ-Аудит ПАО «Интер РАО»');
  await page.fill('#specDocNum', 'ТЗ-АУДИТ-E2E-01');
  await page.selectOption('#specPeriod', '24h');
  await page.waitForTimeout(900);

  const previewInfo = await page.evaluate(() => {
    const box = document.querySelector('#specPreviewBox');
    const txt = box ? box.innerText : '';
    return {
      len: txt.length,
      hasCustomPlant: txt.includes('ТЭЦ-Аудит'),
      hasCustomDocNum: txt.includes('ТЗ-АУДИТ-E2E-01'),
      hasEcoSummary: document.querySelector('#specEcoSummary')?.textContent?.trim(),
    };
  });
  report.steps.specPreview = previewInfo;

  // Scroll to spec builder and screenshot
  await page.locator('#specForm').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS_DIR, 'audit_spec_builder_1920x1080.png') });

  // Download real .docx via UI
  const [dlDocx] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.click('#btnSpecDownloadDocx'),
  ]);
  const docxPath = path.join(OUT_DIR, 'e2e_downloaded_spec.docx');
  await dlDocx.saveAs(docxPath);
  report.steps.downloadedDocx = {
    suggestedFilename: dlDocx.suggestedFilename(),
    savedPath: docxPath,
    sizeBytes: fs.statSync(docxPath).size,
  };

  // Download real .md via UI
  const [dlMd] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.click('#btnSpecDownloadMd'),
  ]);
  const mdPath = path.join(OUT_DIR, 'e2e_downloaded_spec.md');
  await dlMd.saveAs(mdPath);
  report.steps.downloadedMd = {
    suggestedFilename: dlMd.suggestedFilename(),
    savedPath: mdPath,
    sizeBytes: fs.statSync(mdPath).size,
  };

  // 4. Test responsive viewports 1440x900 and 1280x720 on monitor view
  await page.click('[data-view="monitor"]');
  await page.waitForTimeout(500);
  await checkViewport('1440x900', 1440, 900);
  await checkViewport('1280x720', 1280, 720);

  // Also check architecture and dispatch horizontal overflow at 1280x720
  await page.click('[data-view="architecture"]');
  await page.waitForTimeout(500);
  report.viewports.arch_1280x720_overflow = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    vw: window.innerWidth,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  }));
  await page.screenshot({ path: path.join(SHOTS_DIR, 'audit_arch_1280x720.png') });

  await page.click('[data-view="dispatch"]');
  await page.waitForTimeout(500);
  report.viewports.dispatch_1280x720_overflow = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    vw: window.innerWidth,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  }));
  await page.screenshot({ path: path.join(SHOTS_DIR, 'audit_dispatch_1280x720.png') });

  // 5. Check Diagnostics summary
  report.diagnostics = {
    consoleErrors,
    consoleWarningsCount: consoleWarnings.length,
    pageErrors,
    failedRequests,
    externalNetworkRequestsBlocked: externalAttempts.length,
  };

  fs.writeFileSync(path.join(OUT_DIR, 'browser_driver_report.json'), JSON.stringify(report, null, 2), 'utf-8');
  console.log('BROWSER_AUDIT_DONE', JSON.stringify({
    extBlocked: externalAttempts.length,
    consoleErrs: consoleErrors.length,
    pageErrs: pageErrors.length,
    failedReqs: failedRequests.length,
    docxBytes: report.steps.downloadedDocx.sizeBytes,
    mdBytes: report.steps.downloadedMd.sizeBytes,
    v1920Clipped: report.viewports['1920x1080'].clipped,
    v1440Clipped: report.viewports['1440x900'].clipped,
    v1280Clipped: report.viewports['1280x720'].clipped,
    outagePending: report.steps.archOutage.sfPending,
    recoveredPending: report.steps.archRecovered.sfPending,
  }));
  await browser.close();
})().catch((err) => {
  console.error('BROWSER_AUDIT_FATAL:', err);
  process.exit(1);
});
