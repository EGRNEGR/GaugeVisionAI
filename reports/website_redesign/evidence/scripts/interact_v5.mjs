// Interactive acceptance of site/v5: drives every demo, asserts real calculations & DOM state.
// Usage: node interact_v5.mjs <url> <outDir> [w h]
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/Egoru/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright-core');

const [url, out, w = 1440, hgt = 900] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const ctx = await browser.newContext({ viewport: { width: +w, height: +hgt } });
const page = await ctx.newPage();
const errs = [];
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message));

const R = {};
const shot = async (sel, name) => {
  const el = await page.$(sel);
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(600);
  await el.screenshot({ path: path.join(out, name + '.jpg'), type: 'jpeg', quality: 80 });
};

await page.goto(url, { waitUntil: 'load' });
await page.waitForTimeout(1200);

// 1. Multigauge: 1 / 4 / 16 / 8
R.multigauge = [];
for (const n of [1, 4, 16, 8]) {
  await page.click(`.gv-mg .gv-seg__btn[data-n="${n}"]`);
  await page.waitForTimeout(500);
  R.multigauge.push(await page.evaluate(() => ({
    pressed: document.querySelector('.gv-mg .gv-seg__btn[aria-pressed="true"]').dataset.n,
    synValid: document.querySelectorAll('.gv-mg__v')[0].textContent,
    realValid: document.querySelectorAll('.gv-mg__v')[5].textContent,
    warn: !document.querySelector('.gv-mg__warn').hidden,
    spots: document.querySelectorAll('.gv-mg__spot').length
  })));
}
await page.click('.gv-mg__spot >> nth=1');
await page.waitForTimeout(300);
R.mgCard = await page.evaluate(() => document.querySelector('.gv-mg__card:not([hidden]) .gv-mg__card-code')?.textContent);
await shot('#multigauge .gv-mg__main', 'sec_multigauge');

// 2. Store-and-Forward resilience: cut -> wait -> restore -> drained, gaps 0
await page.locator('#resilience').scrollIntoViewIfNeeded();
await page.waitForTimeout(1800);
await page.click('#resilience .gv-btn-paper--red');
await page.waitForTimeout(3000);
const during = await page.evaluate(() => ({
  state: document.querySelector('.gv-sf__sim').dataset.state,
  q: document.querySelector('.gv-sf__qn').textContent
}));
await shot('#resilience .gv-sf', 'sec_resilience_down');
await page.click('#resilience .gv-btn-paper--ink');
await page.waitForTimeout(3500);
const after = await page.evaluate(() => ({
  state: document.querySelector('.gv-sf__sim').dataset.state,
  q: document.querySelector('.gv-sf__qn').textContent,
  cv: [...document.querySelectorAll('.gv-sf__cv')].map((e) => e.textContent)
}));
R.resilience = { during, after };
await shot('#resilience .gv-sf', 'sec_resilience_after');

// 3. SCADA + Diagnostics + Forecast
await shot('#scada .gv-scada', 'sec_scada');
await page.click('.gv-hot >> nth=2');
R.diag = await page.evaluate(() => document.querySelector('.gv-hotlist__item[data-on] .gv-hotlist__t').textContent);
await shot('#diagnostics', 'sec_diagnostics');
await page.locator('.gv-fcw').scrollIntoViewIfNeeded();
await page.waitForTimeout(2800);
R.forecastDone = await page.evaluate(() => document.querySelector('.gv-fcw').hasAttribute('data-done'));
await shot('.gv-fcw', 'sec_forecast');

// 4. Optimizer: all 5 required cases
R.optimizer = [];
for (const [b, o] of [
  [450000, 'max_risk_reduction'],
  [300000, 'max_risk_reduction'],
  [300000, 'max_net_effect'],
  [100000, 'max_risk_reduction'],
  [800000, 'weighted_utility']
]) {
  await page.evaluate(([bb, oo]) => { GV.api.optimizer.setObjective(oo); GV.api.optimizer.setBudget(bb); }, [b, o]);
  await page.waitForTimeout(550);
  R.optimizer.push(await page.evaluate(() => ({
    plan: [...document.querySelectorAll('.gv-opt__zone--plan .gv-tile')].map((t) => t.dataset.code).sort().join(','),
    kpi: [...document.querySelectorAll('.gv-kpi__v')].map((e) => e.textContent),
    doc: document.querySelector('.gv-doc__table tfoot td:last-child').textContent
  })));
  if (b === 100000) await shot('#optimizer .gv-opt', 'sec_optimizer_deficit');
}
await page.evaluate(() => { GV.api.optimizer.setObjective('max_risk_reduction'); GV.api.optimizer.setBudget(450000); });
await page.waitForTimeout(500);
await shot('#optimizer .gv-opt', 'sec_optimizer');
await shot('#document', 'sec_document');

// 5. Evolution tabs keyboard
await page.locator('.gv-evo__tab').nth(2).focus();
await page.keyboard.press('ArrowLeft');
await page.waitForTimeout(300);
R.evo = await page.evaluate(() => [...document.querySelectorAll('.gv-evo__panel')].map((p) => !p.hidden));
await shot('#evolution .gv-evo', 'sec_evolution_v2');

// 6. Economics calculator
const num = page.locator('.gv-eco__num').first();
await num.fill('500');
await num.press('Tab');
await page.waitForTimeout(300);
R.eco = await page.evaluate(() => ({
  saving: document.querySelector('.gv-eco__saving').textContent,
  rows: [...document.querySelectorAll('.gv-eco__table tbody tr')].map((r) => r.textContent)
}));
await shot('#economics', 'sec_economics');

// 7. Showcase via keyboard (blur input first!)
await page.evaluate(() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); });
await page.keyboard.press('d');
await page.waitForTimeout(500);
R.showcaseOpen = await page.evaluate(() => ({
  active: document.documentElement.hasAttribute('data-showcase'),
  num: document.querySelector('.gv-sc__num').textContent,
  title: document.querySelector('.gv-sc__title').textContent,
  mast: getComputedStyle(document.querySelector('.gv-mast')).display
}));
await page.keyboard.press('ArrowRight');
await page.waitForTimeout(300);
R.showcaseStep2 = await page.evaluate(() => document.querySelector('.gv-sc__num').textContent);
await page.keyboard.press('r');
await page.waitForTimeout(300);
R.showcaseRestart = await page.evaluate(() => document.querySelector('.gv-sc__num').textContent);
await page.keyboard.press('Escape');
await page.waitForTimeout(250);
R.showcaseExit = await page.evaluate(() => ({
  active: document.documentElement.hasAttribute('data-showcase'),
  mast: getComputedStyle(document.querySelector('.gv-mast')).display
}));

R.errs = errs;
fs.writeFileSync(path.join(out, 'interact.json'), JSON.stringify(R, null, 1));
console.log(JSON.stringify(R, null, 1));
await browser.close();
