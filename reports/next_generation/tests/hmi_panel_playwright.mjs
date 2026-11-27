// Браузерная проверка вкладки «Щит»: детекция, регистрация через форму, повторная детекция без дублей.
// Стенд: сервер с источником video_file из scripts/make_panel_video.py (синтетический щит);
// PW — путь к playwright-core, HMI_DIR — каталог с legend.json и ck.txt (cookie gv_session).
// Адрес сервера: http://127.0.0.1:8765.
import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW);
const DIR = process.env.HMI_DIR || '.';  // legend.json, ck.txt (gv_session) и скриншоты
const legend = JSON.parse(fs.readFileSync(`${DIR}/legend.json`, 'utf8'));
const token = fs.readFileSync(`${DIR}/ck.txt`, 'utf8').trim().split('\n').pop().split('\t').pop();

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await ctx.addCookies([{ name: 'gv_session', value: token, domain: '127.0.0.1', path: '/', httpOnly: true }]);
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle' });
await page.click('.nav-tab[data-view="panel"]');
await page.waitForSelector('#view-panel:not([hidden])');
await page.waitForFunction(() => document.querySelector('#mgFrameImg')?.dataset.empty === 'false', null, { timeout: 30000 });
await page.screenshot({ path: `${DIR}/01_panel_tab.png` });

await page.click('#btnMgDetect');
await page.waitForSelector('.mg-cand', { timeout: 60000 });
const nCand = await page.locator('.mg-cand').count();
console.log('candidates', nCand, 'status:', await page.textContent('#mgStatus'));
await page.screenshot({ path: `${DIR}/02_detected.png` });

let registered = 0;
for (let k = 0; k < 20; k++) {
  const cands = page.locator('.mg-cand');
  if (await cands.count() === 0) break;
  await cands.first().click();
  const form = page.locator('#mgDetailBody form');
  if (await form.count() === 0) {
    // основной циферблат камеры: формы нет, переходим к следующему
    const rest = await page.locator('.mg-cand').count();
    if (rest <= 1) break;
    await page.locator('.mg-cand').nth(1).click();
    if (await page.locator('#mgDetailBody form').count() === 0) break;
  }
  const idx = Number(await page.locator('.mg-cand.is-picked').getAttribute('data-cand'));
  const anchor = await page.evaluate((i) => {
    const svg = document.querySelector('#mgOverlay');
    const e = svg.querySelector(`.mg-cand[data-cand="${i}"] ellipse`);
    const vb = svg.viewBox.baseVal;
    return e ? { cx: Number(e.getAttribute('cx')) / vb.width, cy: Number(e.getAttribute('cy')) / vb.height } : null;
  }, idx);
  let near = legend[0];
  if (anchor) near = legend.reduce((b, g) => (Math.hypot(g.cx - anchor.cx, g.cy - anchor.cy) < Math.hypot(b.cx - anchor.cx, b.cy - anchor.cy) ? g : b));
  const f = page.locator('#mgDetailBody form');
  await f.locator('[name=name]').fill(`Манометр ${near.code}`);
  await f.locator('[name=code]').fill(near.code);
  await f.locator('[name=v_max]').fill(String(near.v_max));
  await f.locator('button[type=submit]').click();
  await page.waitForTimeout(1200);
  registered++;
  if (registered === 1) await page.screenshot({ path: `${DIR}/03_registered_first.png` });
}
console.log('registered via UI', registered);
await page.waitForTimeout(8000);
await page.screenshot({ path: `${DIR}/04_all_registered.png` });
const rows = await page.$$eval('#mgTable tbody tr', (trs) => trs.map((t) => t.innerText.replace(/\s+/g, ' ')));
console.log(rows.join('\n'));
// повторная детекция не должна создавать дубли
await page.click('#btnMgDetect');
await page.waitForTimeout(6000);
console.log('candidates after redetect', await page.locator('.mg-cand').count(), 'status:', await page.textContent('#mgStatus'));
await page.locator('.mg-inst').nth(1).click();
await page.waitForTimeout(800);
await page.screenshot({ path: `${DIR}/05_detail.png` });
console.log('errors', JSON.stringify(errors));
await browser.close();
