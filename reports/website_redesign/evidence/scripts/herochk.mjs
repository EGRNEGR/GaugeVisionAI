import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');
const b = await chromium.launch({ channel: 'msedge', headless: true });
for (const [w, h] of [[1920, 1080], [1440, 900], [1280, 720], [390, 844]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  await p.goto('http://127.0.0.1:8704/'); await p.waitForTimeout(2500);
  const r = await p.evaluate(() => { const e = document.querySelector('.gv-hero__line').getBoundingClientRect(); return [e.x, e.y, e.width, e.height].map(Math.round); });
  // screenshot with text hidden to sample background behind lede
  await p.addStyleTag({ content: '.gv-hero__line,.gv-hero__kicker{visibility:hidden!important}' });
  await p.screenshot({ path: `out/herobg_${w}.png`, clip: { x: r[0], y: r[1], width: r[2], height: r[3] } });
  await p.close();
}
await b.close();
