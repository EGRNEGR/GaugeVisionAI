// Browser acceptance of site/v5 (local and Tilda): 5 viewports, errors, overflow, CLS, long tasks,
// scroll FPS, reduced motion, offline (optional), showcase 1920x1080 & 1280x720, tweaks.
// Usage: PAGE=/path node accept_v5.mjs <baseUrl> <outDir> [--no-offline]
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');

const args = process.argv.slice(2);
const noOffline = args.includes('--no-offline');
const [base, out] = args.filter((a) => !a.startsWith('--'));
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const VPS = [[1920, 1080], [1440, 900], [1280, 720], [768, 1024], [390, 844]];
const results = [];

const INIT = () => {
  window.__cls = 0; window.__lt = []; window.__lcp = 0;
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push(Math.round(e.duration)); }).observe({ type: 'longtask', buffered: true });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
};

async function run(name, w, h, opts = {}) {
  const ctx = await browser.newContext({
    viewport: { width: w, height: h },
    reducedMotion: opts.reduced ? 'reduce' : 'no-preference',
    isMobile: w < 500,
    hasTouch: w < 800,
    deviceScaleFactor: 1
  });
  const page = await ctx.newPage();
  await page.addInitScript(INIT);
  const errs = [], external = [], failed = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => {
    const err = (r.failure() || {}).errorText || '';
    const u = r.url();
    if (/\.mp4($|\?)/.test(u) && /ERR_ABORTED/.test(err)) return;
    failed.push(u + ' ' + err);
  });
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (!u.startsWith(base) && !u.startsWith('data:') && !u.startsWith('blob:')) {
      external.push(u);
      return opts.offline ? route.abort() : route.continue();
    }
    return route.continue();
  });

  const t0 = Date.now();
  await page.goto(base + (process.env.PAGE || '') + (opts.query || ''), { waitUntil: 'load' });
  const loadMs = Date.now() - t0;
  await page.waitForTimeout(1200);
  const nav = await page.evaluate(() => {
    const n = performance.getEntriesByType('navigation')[0];
    return {
      dcl: Math.round(n.domContentLoadedEventEnd),
      load: Math.round(n.loadEventEnd),
      transferKB: Math.round(performance.getEntriesByType('resource').reduce((s, r) => s + (r.transferSize || 0), 0) / 1024)
    };
  });

  let scroll = null;
  if (!opts.noScroll) {
    scroll = await page.evaluate(async () => {
      const H = document.documentElement.scrollHeight, vh = innerHeight;
      let frames = 0, worst = 0, last = performance.now(), on = true;
      const gaps = [];
      function tick(t) { frames++; const d = t - last; gaps.push(d); if (d > worst) worst = d; last = t; if (on) requestAnimationFrame(tick); }
      requestAnimationFrame(tick);
      const start = performance.now();
      for (let y = 0; y < H; y += Math.round(vh / 6)) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 45)); }
      const dur = performance.now() - start;
      on = false;
      gaps.sort((a, b) => a - b);
      return {
        height: H,
        fps: Math.round(frames / (dur / 1000) * 10) / 10,
        p95FrameMs: Math.round((gaps[Math.floor(gaps.length * 0.95)] || 0) * 10) / 10,
        worstFrameMs: Math.round(worst),
        framesOver50ms: gaps.filter((g) => g > 50).length,
        frames
      };
    });
    await page.waitForTimeout(600);
    await page.evaluate(async () => {
      const H = document.documentElement.scrollHeight;
      for (let y = H; y >= 0; y -= Math.round(innerHeight / 3)) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 25)); }
    });
    await page.waitForTimeout(500);
  }

  const checks = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const small = [...document.querySelectorAll('button, a, input, [role=tab]')].filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width && r.height && (r.height < 24 || r.width < 24) && getComputedStyle(e).visibility !== 'hidden';
    }).map((e) => ({ cls: String(e.className || e.tagName), w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height) }));
    const nonSrcSmall = small.filter((s) => !s.cls.includes('gv-src'));
    const txt = document.body.innerText;
    const mounted = [...document.querySelectorAll('section.gv-sheet[id]')].filter((s) => s.children.length).length;
    const brokenImgs = [...document.images].filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src);
    return {
      docW: document.documentElement.scrollWidth,
      vw,
      horizontalOverflow: document.documentElement.scrollWidth > vw,
      smallTargetCount: small.length,
      nonSrcSmall,
      middleDots: (txt.match(/\u00b7/g) || []).length,
      sectionsMounted: mounted,
      brokenImgs,
      cls: Math.round(window.__cls * 1000) / 1000,
      longTasks: window.__lt.length,
      longTaskMax: Math.max(0, ...window.__lt),
      lcpMs: Math.round(window.__lcp)
    };
  });

  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(400);
  if (!opts.noShot) {
    await page.screenshot({ path: path.join(out, `${name}_first.jpg`), type: 'jpeg', quality: 82 });
    if (w === 1440 || w === 390) {
      await page.screenshot({ path: path.join(out, `${name}_full.jpg`), type: 'jpeg', quality: 55, fullPage: true });
    }
  }
  let extra = {};
  if (opts.after) extra = await opts.after(page);
  const r = { name, w, h, loadMs, nav, scroll, ...checks, errors: errs, failed, external, extra };
  results.push(r);
  console.log(JSON.stringify({
    name,
    fps: scroll && scroll.fps,
    cls: checks.cls,
    lcp: checks.lcpMs,
    ovf: checks.horizontalOverflow,
    smallNonSrc: checks.nonSrcSmall.length,
    dots: checks.middleDots,
    err: errs.length,
    failed: failed.length,
    ext: external.length,
    sec: checks.sectionsMounted,
    broken: checks.brokenImgs.length
  }));
  await ctx.close();
}

const showcase = async (p) => {
  const steps = [];
  for (let i = 0; i < 12; i++) {
    await p.waitForTimeout(900);
    steps.push(await p.evaluate(() => {
      const d = document.querySelector('.gv-sc');
      const r = d.getBoundingClientRect();
      return {
        n: document.querySelector('.gv-sc__num').textContent,
        title: document.querySelector('.gv-sc__title').textContent,
        mode: document.querySelector('.gv-sc__mode').textContent,
        dockInside: r.bottom <= innerHeight + 1 && r.right <= innerWidth + 1,
        overflowX: document.documentElement.scrollWidth > innerWidth
      };
    }));
    await p.screenshot({ path: path.join(out, `showcase_${p.viewportSize().width}_${String(i + 1).padStart(2, '0')}.jpg`), type: 'jpeg', quality: 75 });
    await p.keyboard.press('ArrowRight');
  }
  return steps;
};

for (const [w, h] of VPS) await run(`v5_${w}x${h}`, w, h);
await run('v5_reduced_1440', 1440, 900, {
  reduced: true,
  after: async (p) => p.evaluate(() => ({
    runningAnims: document.getAnimations().filter((a) => a.playState === 'running').length,
    videosPlaying: [...document.querySelectorAll('video')].filter((v) => !v.paused).length
  }))
});
if (!noOffline) await run('v5_offline_1440', 1440, 900, { offline: true, noShot: true });
await run('showcase_1920x1080', 1920, 1080, { query: '?showcase=1', noShot: true, noScroll: true, after: showcase });
await run('showcase_1280x720', 1280, 720, { query: '?showcase=1', noShot: true, noScroll: true, after: showcase });
await run('v5_tweaks_1440', 1440, 900, {
  query: '?tweaks',
  noShot: true,
  noScroll: true,
  after: async (p) => {
    await p.click('.gv-tw__btn');
    await p.waitForTimeout(200);
    await p.screenshot({ path: path.join(out, 'tweaks_1440.jpg'), type: 'jpeg', quality: 78 });
    return p.evaluate(() => ({ panelOpen: !document.querySelector('.gv-tw__panel').hidden }));
  }
});

fs.writeFileSync(path.join(out, 'acceptance.json'), JSON.stringify(results, null, 1));
await browser.close();
