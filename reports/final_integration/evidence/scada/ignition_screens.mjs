// Снимок мнемосхемы Perspective «GaugeVisionLab» в живой Ignition 8.3.10 (msedge, headless).
// PW — путь к playwright-core, OUT — файл PNG, IGN_URL — адрес клиента Perspective.
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW);
const url = process.env.IGN_URL || 'http://127.0.0.1:8088/data/perspective/client/GaugeVisionLab';
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(8000);
await page.screenshot({ path: process.env.OUT });
const text = (await page.innerText('body')).replace(/\s+/g, ' ').slice(0, 1500);
console.log(text);
await browser.close();
