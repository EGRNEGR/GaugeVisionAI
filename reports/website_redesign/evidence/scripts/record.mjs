// Records key v4 interactions as webm: hero+story scroll, resilience, optimizer, showcase walkthrough.
// Usage: node record.mjs <baseUrl> <outDir>
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');
const [base, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const size = { width: 1280, height: 720 };
const vsize = { width: 960, height: 540 };

async function rec(name, query, fn) {
  const ctx = await browser.newContext({ viewport: size, recordVideo: { dir: out, size: vsize } });
  const page = await ctx.newPage();
  await page.goto(base + query, { waitUntil: 'load' });
  await page.waitForTimeout(1200);
  await fn(page);
  const v = page.video();
  await ctx.close();
  const p = await v.path();
  const dst = path.join(out, name + '.webm');
  if (fs.existsSync(dst)) fs.unlinkSync(dst);
  fs.renameSync(p, dst);
  console.log(name, Math.round(fs.statSync(dst).size / 1024) + ' KB');
}

const smooth = (page, to, ms) => page.evaluate(async ([to, ms]) => {
  const from = scrollY, t0 = performance.now();
  await new Promise((res) => { (function f(t) { const k = Math.min(1, (t - t0) / ms); scrollTo(0, from + (to - from) * (0.5 - Math.cos(Math.PI * k) / 2)); k < 1 ? requestAnimationFrame(f) : res(); })(t0); });
}, [to, ms]);
const topOf = (page, sel) => page.evaluate((s) => document.querySelector(s).getBoundingClientRect().top + scrollY, sel);

await rec('01_hero_story_scroll', '', async (p) => {
  const story = await topOf(p, '#story');
  await smooth(p, story, 5000);
  const end = await p.evaluate(() => { const s = document.querySelector('.gv-story'); return s.getBoundingClientRect().top + scrollY + s.offsetHeight - innerHeight; });
  await smooth(p, end, 16000);
  await p.waitForTimeout(800);
});
await rec('02_resilience_store_and_forward', '', async (p) => {
  await p.evaluate(() => { const e = document.querySelector('.gv-sf__sim'); scrollTo(0, e.getBoundingClientRect().top + scrollY - 60); });
  await p.waitForTimeout(2500);
  await p.click('#resilience .gv-btn--danger');
  await p.waitForTimeout(6000);
  await p.click('#resilience .gv-btn--primary');
  await p.waitForTimeout(5000);
});
await rec('03_optimizer_budget', '', async (p) => {
  await p.evaluate(() => { const e = document.querySelector('.gv-opt'); scrollTo(0, e.getBoundingClientRect().top + scrollY - 40); });
  await p.waitForTimeout(1200);
  for (const b of [300000, 200000, 100000, 600000, 450000]) { await p.evaluate((bb) => GV.api.optimizer.setBudget(bb), b); await p.waitForTimeout(1800); }
  await p.evaluate(() => GV.api.optimizer.setObjective('max_net_effect')); await p.waitForTimeout(1800);
  await p.evaluate(() => GV.api.optimizer.setObjective('max_risk_reduction')); await p.waitForTimeout(1500);
});
await rec('04_showcase_projector_1280x720', '?showcase=1', async (p) => {
  for (let i = 0; i < 12; i++) { await p.waitForTimeout(3200); await p.keyboard.press('ArrowRight'); }
  await p.waitForTimeout(1500);
});
await browser.close();
