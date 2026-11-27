// Probe live Tilda page: video (shift.scrub), loaded fonts, block heights, and CLS sources.
// Usage: node probe_live.mjs <url> [w h]
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');

const [url, w = 390, h = 844] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'msedge', headless: true });
const p = await b.newPage({ viewport: { width: +w, height: +h }, isMobile: +w < 500, hasTouch: +w < 800 });
await p.addInitScript(() => {
  window.__shifts = [];
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) {
      if (!e.hadRecentInput) {
        window.__shifts.push({
          v: +e.value.toFixed(4),
          t: Math.round(e.startTime),
          src: (e.sources || []).map((s) => {
            const n = s.node;
            const d = n && n.nodeType === 1 ? (n.id ? '#' + n.id : '') + '.' + String(n.className).split(' ')[0] : (n ? n.nodeName : '?');
            return d + ' ' + JSON.stringify([s.previousRect.y, s.currentRect.y, s.previousRect.height, s.currentRect.height].map(Math.round));
          })
        });
      }
    }
  }).observe({ type: 'layout-shift', buffered: true });
});
await p.goto(url, { waitUntil: 'load' });
await p.waitForTimeout(3500);
const v = await p.evaluate(() => {
  const x = document.querySelector('.gv-shift__video');
  return x && { src: x.currentSrc, rs: x.readyState, dur: x.duration, ct: x.currentTime };
});
await p.evaluate(() => {
  const s = document.querySelector('#compare');
  if (s) s.scrollIntoView({ behavior: 'auto' });
});
await p.waitForTimeout(2500);
const v2 = await p.evaluate(() => {
  const x = document.querySelector('.gv-shift__video');
  return x && { src: x.currentSrc, rs: x.readyState, dur: x.duration, ct: x.currentTime };
});
console.log('video', JSON.stringify(v), JSON.stringify(v2));
console.log('fonts', JSON.stringify(await p.evaluate(() => [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family + ':' + f.weight))));
console.log('rec', JSON.stringify(await p.evaluate(() => [...document.querySelectorAll('.t-rec')].map((r) => r.id + ':' + Math.round(r.getBoundingClientRect().height)))));
console.log('shifts', JSON.stringify(await p.evaluate(() => window.__shifts)));
await b.close();
