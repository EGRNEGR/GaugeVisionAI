// Браузерная приёмка пульта на 1920×1080, 1440×900, 1280×720 (msedge, headless).
// Все запросы не к 127.0.0.1 блокируются и фиксируются — проверка автономной работы без CDN.
// Окружение: PW — путь к playwright-core, HMI_URL, HMI_COOKIE (gv_session), HMI_OUT — каталог результатов.
import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW);
const URL0 = process.env.HMI_URL;
const OUT = process.env.HMI_OUT;
const COOKIE = process.env.HMI_COOKIE;
const VIEWS = ['monitor', 'architecture', 'dispatch', 'events', 'history', 'cameras', 'panel', 'calibration'];
const SIZES = [[1920, 1080], [1440, 900], [1280, 720]];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const report = { sizes: {} };
for (const [w, h] of SIZES) {
  const tag = `${w}x${h}`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, ignoreHTTPSErrors: true, acceptDownloads: true });
  const host = new globalThis.URL(URL0).hostname;
  await ctx.addCookies([{ name: 'gv_session', value: COOKIE, domain: host, path: '/', httpOnly: true, secure: true }]);
  const external = [];
  const failed = [];
  await ctx.route('**/*', (route) => {
    const u = new globalThis.URL(route.request().url());
    if (u.hostname !== host && u.protocol.startsWith('http')) { external.push(u.href); return route.abort(); }
    return route.continue();
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('response', (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
  await page.goto(URL0, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  const res = { views: {}, actions: {} };
  for (const v of VIEWS) {
    const tab = page.locator(`.nav-tab[data-view="${v}"]`);
    if (!(await tab.count()) || !(await tab.isVisible())) { res.views[v] = { visible: false }; continue; }
    await tab.click();
    await page.waitForTimeout(v === 'panel' || v === 'dispatch' ? 3000 : 1500);
    const m = await page.evaluate(() => {
      const de = document.documentElement;
      const iw = window.innerWidth;
      const over = [];
      for (const el of document.querySelectorAll('body *')) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('[hidden]')) continue;
        const r = el.getBoundingClientRect();
        // содержимое прокручиваемых контейнеров (overflow-x: auto) не обрезано — проверяется сам контейнер
        if (r.width > 0 && r.right > iw + 1 && !el.closest('.j-table-wrap,.ev-tbl,.table-wrap,.md-tbl-wrap > *,[data-scroll-x]')) {
          over.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}.${[...el.classList].join('.')}`);
        }
      }
      const stubs = [...document.querySelectorAll('button,a')].filter((b) => b.offsetParent && /заглушк|todo|lorem|скоро|coming soon/i.test(b.innerText)).map((b) => b.innerText);
      const rr = (q) => { const e = document.querySelector(q); if (!e) return null; const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right)]; };
      const head = { head_ops: rr('.head-ops'), fullscreen: rr('#btnFullscreen'), head_right: rr('.head') };
      return { head, scrollW: de.scrollWidth, innerW: iw, hOverflow: de.scrollWidth > iw + 1, overflowing: over.slice(0, 8), nOver: over.length, stubs };
    });
    await page.screenshot({ path: `${OUT}/${tag}_${v}.png` });
    res.views[v] = m;
  }
  // Диспетчеризация: прогноз, оптимизатор, кривая Парето, сохранение плана, конструктор ТЗ
  await page.locator('.nav-tab[data-view="dispatch"]').click();
  await page.waitForTimeout(1500);
  const act = res.actions;
  try {
    await page.click('#btnPredRefresh');
    await page.waitForTimeout(2500);
    act.predictive_rows = await page.locator('#predictiveSection tbody tr').count();
    await page.fill('#optBudgetInput', '900000');
    await page.click('#btnOptSolve');
    await page.waitForFunction(() => (document.querySelector('#optKpiCount')?.textContent || '—').trim() !== '—', null, { timeout: 30000 });
    act.opt_selected = (await page.textContent('#optKpiCount')).trim();
    act.opt_rows = await page.locator('#optCandidatesBody tr').count();
    act.pareto_painted = await page.evaluate(() => {
      const c = document.querySelector('#optFrontierCanvas');
      if (!c || !c.width) return false;
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
      return n > 500;
    });
    const plans0 = await page.locator('#optPlansList li.opt-plan-item').count();
    page.once('dialog', (d) => d.accept(`План ${tag}`));
    await page.click('#btnOptSavePlan');
    await page.waitForTimeout(2500);
    act.plans_before = plans0;
    act.plans_after = await page.locator('#optPlansList li.opt-plan-item').count();
    await page.click('#btnOptApplyToSpec');
    await page.waitForTimeout(1500);
    await page.click('#btnSpecRefresh');
    await page.waitForTimeout(3000);
    const dl1 = page.waitForEvent('download', { timeout: 30000 });
    await page.click('#btnSpecDownloadDocx');
    const d1 = await dl1;
    await d1.saveAs(`${OUT}/${tag}_spec.docx`);
    act.docx_bytes = fs.statSync(`${OUT}/${tag}_spec.docx`).size;
    const dl2 = page.waitForEvent('download', { timeout: 30000 });
    await page.click('#btnSpecDownloadMd');
    const d2 = await dl2;
    await d2.saveAs(`${OUT}/${tag}_spec.md`);
    act.md_bytes = fs.statSync(`${OUT}/${tag}_spec.md`).size;
    await page.screenshot({ path: `${OUT}/${tag}_dispatch_after_actions.png`, fullPage: true });
  } catch (e) {
    act.error = String(e.message || e).slice(0, 300);
  }
  // Щит: кадр источника, таблица приборов
  try {
    await page.locator('.nav-tab[data-view="panel"]').click();
    await page.waitForTimeout(1000);
    // источник щита — синтетическое видео (в демопрофиле по умолчанию выбрана живая камера)
    const opt = await page.$$eval('#mgSource option', (os) => (os.find((o) => /синтет/i.test(o.textContent)) || {}).value);
    if (opt) await page.selectOption('#mgSource', opt);
    await page.waitForTimeout(4000);
    await page.screenshot({ path: `${OUT}/${tag}_panel_source.png` });
    act.panel_rows = await page.locator('#mgTable tbody tr').count();
    act.panel_frame = await page.evaluate(() => document.querySelector('#mgFrameImg')?.dataset.empty === 'false');
  } catch (e) { act.panel_error = String(e.message || e).slice(0, 200); }
  res.errors = errors;
  res.failed_requests = failed.filter((f) => !f.includes('/frame.jpg'));
  res.external_requests = external;
  report.sizes[tag] = res;
  await ctx.close();
}
await browser.close();
fs.writeFileSync(`${OUT}/hmi_results.json`, JSON.stringify(report, null, 1));
console.log(JSON.stringify(report, null, 1).slice(0, 6000));
