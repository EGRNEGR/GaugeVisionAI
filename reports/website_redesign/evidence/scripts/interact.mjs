// Interactive acceptance of v4: drives every demo, asserts real behaviour, screenshots each section.
// Usage: node interact.mjs <url> <outDir> <w> <h>
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
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.type() + ': ' + m.text()); });
page.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
const R = {};
const shot = async (sel, name) => {
  const el = await page.$(sel);
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(700);
  await el.screenshot({ path: path.join(out, name + '.png') });
};
await page.goto(url, { waitUntil: 'load' });
await page.waitForTimeout(1200);

// Story: every scene reachable via API, layers switch
R.story = [];
for (let i = 0; i < 8; i++) {
  await page.evaluate((k) => GV.api.story.goTo(k), i);
  await page.waitForTimeout(1300);
  const st = await page.evaluate(() => ({ scene: document.querySelector('.gv-st').getAttribute('data-scene'), on: [...document.querySelectorAll('.gv-st__layer[data-on]')].map((l) => l.getAttribute('class').split(' ')[1]) }));
  R.story.push(st);
  await page.screenshot({ path: path.join(out, `story_${i}.png`) });
}

// Multigauge: switch counts, check stats + warning
R.multigauge = [];
for (const n of [1, 4, 16, 8]) {
  await page.click(`.gv-seg__btn[data-n="${n}"]`);
  await page.waitForTimeout(700);
  R.multigauge.push(await page.evaluate(() => ({ pressed: document.querySelector('.gv-mg .gv-seg__btn[aria-pressed="true"]').dataset.n, valid: document.querySelectorAll('.gv-mg__v')[0].textContent, real: document.querySelectorAll('.gv-mg__v')[5].textContent, warn: !document.querySelector('.gv-mg__warn').hidden, spots: document.querySelectorAll('.gv-mg__spot').length })));
}
await page.click('.gv-mg__spot >> nth=1');
await page.waitForTimeout(400);
R.mgCard = await page.evaluate(() => document.querySelector('.gv-mg__card:not([hidden]) .gv-mg__card-code')?.textContent);
await shot('#multigauge', 'sec_multigauge');

// Resilience: cut → wait → restore → drained, no gaps
await page.locator('#resilience').scrollIntoViewIfNeeded();
await page.waitForTimeout(2500);
await page.click('#resilience .gv-btn--danger');
await page.waitForTimeout(5000);
const during = await page.evaluate(() => ({ state: document.querySelector('.gv-sf__sim').dataset.state, q: document.querySelector('.gv-sf__qn').textContent }));
await shot('#resilience .gv-sf', 'sec_resilience_down');
await page.click('#resilience .gv-btn--primary');
await page.waitForTimeout(4000);
const after = await page.evaluate(() => ({ state: document.querySelector('.gv-sf__sim').dataset.state, q: document.querySelector('.gv-sf__qn').textContent, cv: [...document.querySelectorAll('.gv-sf__cv')].map((e) => e.textContent) }));
R.resilience = { during, after };
await shot('#resilience .gv-sf', 'sec_resilience_after');

await shot('#scada', 'sec_scada');
await page.click('.gv-hot >> nth=2');
R.diag = await page.evaluate(() => document.querySelector('.gv-hotlist__item[data-on] .gv-hotlist__t').textContent);
await shot('#diagnostics', 'sec_diagnostics');
await shot('#forecast', 'sec_forecast');
await page.waitForTimeout(2600);
R.forecastDone = await page.evaluate(() => document.querySelector('.gv-fcw').hasAttribute('data-done'));
await shot('#forecast .gv-fcw', 'sec_forecast_done');

// Optimizer: budgets and objectives
R.optimizer = [];
for (const [b, o] of [[450000, 'max_risk_reduction'], [300000, 'max_risk_reduction'], [300000, 'max_net_effect'], [100000, 'max_risk_reduction'], [800000, 'weighted_utility']]) {
  await page.evaluate(([bb, oo]) => { GV.api.optimizer.setObjective(oo); GV.api.optimizer.setBudget(bb); }, [b, o]);
  await page.waitForTimeout(700);
  R.optimizer.push(await page.evaluate(() => ({ plan: [...document.querySelectorAll('.gv-opt__zone--plan .gv-tile')].map((t) => t.dataset.code).sort().join(','), kpi: [...document.querySelectorAll('.gv-kpi__v')].map((e) => e.textContent), doc: document.querySelector('.gv-doc__table tfoot td:last-child').textContent })));
  if (b === 100000) await shot('#optimizer .gv-opt', 'sec_optimizer_deficit');
}
await page.evaluate(() => { GV.api.optimizer.setObjective('max_risk_reduction'); GV.api.optimizer.setBudget(450000); });
await page.waitForTimeout(700);
await shot('#optimizer', 'sec_optimizer');
await shot('#document', 'sec_document');

// Evolution tabs keyboard
await page.locator('.gv-evo__tab').nth(2).focus();
await page.keyboard.press('ArrowLeft');
await page.waitForTimeout(400);
R.evo = await page.evaluate(() => [...document.querySelectorAll('.gv-evo__panel')].map((p) => !p.hidden));
await shot('#evolution', 'sec_evolution_v2');

// Economics: change points
const num = page.locator('.gv-eco__num').first();
await num.fill('500'); await num.press('Tab');
await page.waitForTimeout(400);
R.eco = await page.evaluate(() => ({ saving: document.querySelector('.gv-eco__saving').textContent, rows: [...document.querySelectorAll('.gv-eco__table tbody tr')].map((r) => r.textContent) }));
await shot('#economics', 'sec_economics');
await shot('#evidence', 'sec_evidence');
await shot('#readiness', 'sec_readiness');
await shot('#final', 'sec_final');
await shot('#problem', 'sec_problem');

// Showcase via keyboard
await page.evaluate(() => window.scrollTo(0, 0));
await page.keyboard.press('d');
await page.waitForTimeout(800);
R.showcase = [];
for (let i = 0; i < 11; i++) {
  await page.waitForTimeout(1500);
  R.showcase.push(await page.evaluate(() => ({ t: document.querySelector('.gv-sc__title').textContent, n: document.querySelector('.gv-sc__num').textContent, mode: document.querySelector('.gv-sc__mode').textContent, header: getComputedStyle(document.querySelector('.gv-header')).display })));
  await page.screenshot({ path: path.join(out, `showcase_${String(i + 1).padStart(2, '0')}.png`) });
  await page.keyboard.press('ArrowRight');
}
await page.keyboard.press('r');
await page.waitForTimeout(800);
R.showcaseRestart = await page.evaluate(() => document.querySelector('.gv-sc__num').textContent);
await page.keyboard.press('Escape');
await page.waitForTimeout(300);
R.showcaseExit = await page.evaluate(() => ({ attr: document.documentElement.hasAttribute('data-showcase'), header: getComputedStyle(document.querySelector('.gv-header')).display }));
R.errs = errs;
fs.writeFileSync(path.join(out, 'interact.json'), JSON.stringify(R, null, 1));
console.log(JSON.stringify(R, null, 1));
await browser.close();
