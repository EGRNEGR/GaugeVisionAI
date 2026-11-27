// Attribute layout shifts to elements during a scroll pass; list small targets.
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');
const [url, w = 1440, h = 900] = process.argv.slice(2);
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: +w, height: +h } });
await page.addInitScript(() => {
  window.__shifts = [];
  const name = (n) => { if (!n || !n.nodeType) return '?'; const e = n.nodeType === 1 ? n : n.parentElement; if (!e) return '?'; const s = e.closest('section[id]'); return (s ? '#' + s.id + ' ' : '') + e.tagName.toLowerCase() + '.' + (typeof e.className === 'string' ? e.className.split(' ').join('.') : ''); };
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__shifts.push({ v: +e.value.toFixed(4), y: scrollY, src: e.sources.map((s) => name(s.node) + ' ' + Math.round(s.previousRect.y) + '->' + Math.round(s.currentRect.y) + ' h' + Math.round(s.previousRect.height) + '->' + Math.round(s.currentRect.height)) }); }).observe({ type: 'layout-shift', buffered: true });
});
await page.goto(url, { waitUntil: 'load' });
await page.waitForTimeout(1200);
await page.evaluate(async () => { const H = document.documentElement.scrollHeight; for (let y = 0; y < H; y += Math.round(innerHeight / 6)) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 50)); } });
await page.waitForTimeout(800);
const r = await page.evaluate(() => {
  const s = window.__shifts.filter((x) => x.v > 0.005).sort((a, b) => b.v - a.v).slice(0, 15);
  const small = {};
  [...document.querySelectorAll('button, a, input, [role=tab]')].forEach((e) => { const b = e.getBoundingClientRect(); if (b.width && b.height && (b.height < 24 || b.width < 24)) { const k = (typeof e.className === 'string' && e.className ? e.className : e.tagName) + ' ' + Math.round(b.width) + 'x' + Math.round(b.height); small[k] = (small[k] || 0) + 1; } });
  return { total: window.__shifts.reduce((a, b) => a + b.v, 0), top: s, small };
});
console.log(JSON.stringify(r, null, 1));
await browser.close();
