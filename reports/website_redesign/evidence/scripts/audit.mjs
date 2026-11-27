// Visual + technical audit of a site: screenshots, scroll frames, video, network, console, tokens.
// Usage: node audit.mjs <name> <url> <outDir>
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.GV_PLAYWRIGHT_CORE ||
  'C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');

const [name, url, outBase] = process.argv.slice(2);
const out = path.join(outBase, name);
fs.mkdirSync(path.join(out, 'scroll'), { recursive: true });
fs.mkdirSync(path.join(out, 'sections'), { recursive: true });
fs.mkdirSync(path.join(out, 'video'), { recursive: true });

const report = { name, url, at: new Date().toISOString(), viewports: {} };
const browser = await chromium.launch({ channel: 'msedge', headless: true });

async function slowScroll(page, stepFrac = 0.5, pauseMs = 450, shotDir = null) {
  const h = await page.evaluate(() => innerHeight);
  let y = 0, i = 0;
  for (;;) {
    const total = await page.evaluate(() => document.documentElement.scrollHeight);
    if (shotDir) await page.screenshot({ path: path.join(shotDir, `f${String(i).padStart(3, '0')}_y${Math.round(y)}.jpg`), quality: 70, type: 'jpeg' });
    if (y + h >= total - 2) break;
    y = Math.min(y + h * stepFrac, total - h);
    await page.evaluate((yy) => window.scrollTo(0, yy), y);
    await page.waitForTimeout(pauseMs);
    i++;
    if (i > 400) break;
  }
  return i;
}

for (const [vpName, w, hgt] of [['1920x1080', 1920, 1080], ['1440x900', 1440, 900], ['768x1024', 768, 1024], ['390x844', 390, 844]]) {
  const ctx = await browser.newContext({
    viewport: { width: w, height: hgt },
    deviceScaleFactor: 1,
    ...(vpName === '1440x900' ? { recordVideo: { dir: path.join(out, 'video'), size: { width: 1440, height: 900 } } } : {}),
  });
  const page = await ctx.newPage();
  const vr = { console: [], pageErrors: [], failed: [], requests: [] };
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) vr.console.push(`${m.type()}: ${m.text()}`.slice(0, 400)); });
  page.on('pageerror', (e) => vr.pageErrors.push(String(e).slice(0, 400)));
  page.on('requestfailed', (r) => vr.failed.push(`${r.failure()?.errorText} ${r.url()}`.slice(0, 300)));
  page.on('response', async (r) => {
    let size = Number(r.headers()['content-length'] || 0);
    vr.requests.push({ url: r.url().slice(0, 200), status: r.status(), type: r.request().resourceType(), size });
  });
  const t0 = Date.now();
  await page.goto(url, { waitUntil: 'load', timeout: 90000 });
  vr.loadMs = Date.now() - t0;
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(out, `first_${vpName}_t1.png`) });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(out, `first_${vpName}_t4.png`) });

  const steps = await slowScroll(page, vpName === '1920x1080' ? 0.33 : 0.6, vpName === '1440x900' ? 700 : 400,
    vpName === '1920x1080' || vpName === '390x844' ? path.join(out, 'scroll') : null);
  vr.scrollSteps = steps;
  vr.metrics = await page.evaluate(() => {
    const de = document.documentElement;
    return { scrollHeight: de.scrollHeight, scrollWidth: de.scrollWidth, innerWidth: innerWidth,
      overflowX: de.scrollWidth > innerWidth + 1, title: document.title };
  });
  if (vpName === '1920x1080') {
    report.tokens = await page.evaluate(() => {
      const out = {};
      for (const sh of document.styleSheets) {
        let rules; try { rules = sh.cssRules; } catch { continue; }
        for (const r of rules) {
          if (r.selectorText && /^(:root|html)/.test(r.selectorText)) {
            for (const p of r.style) if (p.startsWith('--')) out[p] = r.style.getPropertyValue(p).trim();
          }
        }
      }
      return out;
    });
    report.fonts = await page.evaluate(async () => { await document.fonts.ready; return [...document.fonts].filter((f) => f.status === 'loaded').map((f) => `${f.family} ${f.weight} ${f.style}`); });
    report.typography = await page.evaluate(() => {
      const pick = (sel) => [...document.querySelectorAll(sel)].slice(0, 6).map((el) => {
        const cs = getComputedStyle(el);
        return { tag: el.tagName, text: el.innerText.slice(0, 80), font: cs.fontFamily.slice(0, 60), size: cs.fontSize, weight: cs.fontWeight, lh: cs.lineHeight, ls: cs.letterSpacing, color: cs.color };
      });
      return { h1: pick('h1'), h2: pick('h2'), h3: pick('h3'), p: pick('p') };
    });
    report.sections = await page.evaluate(() => {
      const cand = [...document.querySelectorAll('section, [data-sheet], main > *, #gv-root > *, .t-rec')]
        .filter((el) => el.getBoundingClientRect().height > 200);
      const seen = new Set(); const res = [];
      for (const el of cand) {
        if ([...seen].some((s) => s.contains(el))) continue;
        seen.add(el);
        const r = el.getBoundingClientRect();
        res.push({ idx: res.length, tag: el.tagName, id: el.id, cls: String(el.className).slice(0, 80), top: Math.round(r.top + scrollY), h: Math.round(r.height),
          heading: (el.querySelector('h1,h2,h3')?.innerText || '').slice(0, 120) });
      }
      return res;
    });
    // Section screenshots: scroll each into view, wait for reveal, clip viewport-sized.
    for (const s of report.sections) {
      await page.evaluate((y) => window.scrollTo(0, y), s.top);
      await page.waitForTimeout(900);
      await page.screenshot({ path: path.join(out, 'sections', `s${String(s.idx).padStart(2, '0')}_${(s.id || s.cls.split(' ')[0] || s.tag).replace(/[^\w-]/g, '').slice(0, 30)}.png`) });
    }
    report.text = await page.evaluate(() => document.body.innerText.slice(0, 60000));
    report.middleDots = (report.text.match(/·/g) || []).length;
    report.domNodes = await page.evaluate(() => document.querySelectorAll('*').length);
    report.animations = await page.evaluate(() => document.getAnimations().map((a) => a.animationName || a.constructor.name).slice(0, 60));
    fs.writeFileSync(path.join(out, 'dom_after_js.html'), await page.content());
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(out, `full_${vpName}.png`), fullPage: true });
  const domains = {};
  for (const r of vr.requests) { const d = new URL(r.url).host; domains[d] = (domains[d] || 0) + 1; }
  vr.domains = domains;
  vr.byType = vr.requests.reduce((a, r) => { a[r.type] = (a[r.type] || 0) + 1; return a; }, {});
  vr.bytes = vr.requests.reduce((a, r) => a + r.size, 0);
  vr.requestsCount = vr.requests.length;
  vr.largest = [...vr.requests].sort((a, b) => b.size - a.size).slice(0, 10);
  delete vr.requests;
  report.viewports[vpName] = vr;
  await ctx.close();
}
await browser.close();
fs.writeFileSync(path.join(out, 'audit.json'), JSON.stringify(report, null, 1));
console.log(JSON.stringify({ name, vps: Object.fromEntries(Object.entries(report.viewports).map(([k, v]) => [k, { err: v.pageErrors.length, con: v.console.length, failed: v.failed.length, reqs: v.requestsCount, mb: +(v.bytes / 1e6).toFixed(2), overflowX: v.metrics.overflowX, h: v.metrics.scrollHeight, loadMs: v.loadMs }])), sections: report.sections?.length, dots: report.middleDots }));
