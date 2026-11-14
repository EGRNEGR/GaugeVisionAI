#!/usr/bin/env node
/*
 * GaugeVision AI — единственная автоматическая проверка лендинга.
 * Запуск из корня репозитория: node site/tests/check.js
 * Без зависимостей. Код выхода 0 — всё зелёное; иначе каждое нарушение печатается строкой.
 *
 * Проверки (interfaces.md, «Шов тестов»):
 *   0. Форма GV.content: обязательные поля есть и не пустые.
 *   1. Каждое число в metrics, pipeline[].params, limits, compare, calibration, ema
 *      встречается в README.md, PRODUCT.md, app/config.py или notes.md.
 *   2. Каждый локальный src/href в index.html и content.js (и url() в css/) существует.
 *   3. В site/ (кроме tests/ и design-system.md) нет запрещённых слов; в content.js нет
 *      утверждений, запрещённых правилом 1a.
 *   4. В js/ нет import/export и type="module".
 *   5. Каждый вариант js/variants/*.js упоминает семь id секций в порядке брифа.
 *   6. Типографика строк content.js: нет « - » вместо тире, дефисных диапазонов и десятичной точки.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SITE = path.resolve(__dirname, '..');
const ROOT = path.resolve(SITE, '..');
const NOTES = path.join(ROOT, '.autopilot', '2026-11-14-gaugevision-landing--wip', 'notes.md');
const SECTION_IDS = ['hero', 'metrics', 'pipeline', 'compare', 'architecture', 'limits', 'contact'];

const failures = [];
const fail = (check, msg) => failures.push(`[${check}] ${msg}`);
const rel = (p) => path.relative(ROOT, p).split(path.sep).join('/');

function readText(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch (e) { return null; }
}

function walkFiles(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walkFiles(p, out); else out.push(p);
  }
  return out;
}

/* Обходит все строки и числа объекта, передавая путь ключей. */
function walk(value, visit, keyPath = []) {
  if (value === null || value === undefined) return;
  if (Array.isArray(value)) { value.forEach((v, i) => walk(v, visit, keyPath.concat(i))); return; }
  if (typeof value === 'object') {
    for (const k of Object.keys(value)) walk(value[k], visit, keyPath.concat(k));
    return;
  }
  visit(value, keyPath);
}
const lastKey = (keyPath) => {
  for (let i = keyPath.length - 1; i >= 0; i--) if (typeof keyPath[i] === 'string') return keyPath[i];
  return '';
};

/* ---------- загрузка content.js ---------- */
function loadContent() {
  const file = path.join(SITE, 'js', 'content.js');
  const code = readText(file);
  if (code === null) { fail(0, `нет файла ${rel(file)}`); return null; }
  const sandbox = { window: {}, console };
  sandbox.window.window = sandbox.window;
  try {
    vm.runInNewContext(code, sandbox, { filename: file });
  } catch (e) {
    fail(0, `content.js не выполняется: ${e.message}`);
    return null;
  }
  const content = sandbox.window.GV && sandbox.window.GV.content;
  if (!content) { fail(0, 'content.js не определяет window.GV.content'); return null; }
  return content;
}

/* ---------- 0. форма ---------- */
const SHAPE = {
  meta: ['name', 'tagline', 'repoUrl', 'licenseUrl', 'pdfUrl', 'track', 'copyright'],
  hero: ['eyebrow', 'title', 'lead', 'ctaPrimary', 'ctaSecondary', 'stage'],
  'hero.stage': ['rawLabel', 'recognizedLabel', 'caption', 'captionSchematic', 'raw', 'recognized', 'readout'],
  'hero.stage.readout': ['device', 'value', 'unit', 'theta', 'conf', 'roi', 'latencyMs'],
  calibration: ['thetaMin', 'thetaMax', 'vMin', 'vMax', 'unit', 'direction', 'setpoints', 'barPerMpa', 'formula'],
  ema: ['alpha', 'minConfidence', 'caption'],
  compare: ['before', 'after', 'savingNote', 'timeline'],
  architecture: ['nodes', 'edges', 'stack', 'boundaryLabel'],
  untested: ['title', 'text'],
  contact: ['title', 'text', 'links'],
};
const ITEM_SHAPE = {
  metrics: ['id', 'value', 'unit', 'label', 'condition', 'kind'],
  pipeline: ['id', 'index', 'title', 'short', 'what', 'params', 'file', 'aspect'],
  tradeoffs: ['id', 'chose', 'cost', 'why', 'source'],
  limits: ['id', 'condition', 'risk', 'response', 'status'],
  roadmap: ['index', 'title', 'items', 'status'],
};
const get = (obj, dotted) => dotted.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
const isEmpty = (v) => v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0);

function checkShape(c) {
  for (const [where, keys] of Object.entries(SHAPE)) {
    const obj = get(c, where);
    if (!obj || typeof obj !== 'object') { fail(0, `нет объекта content.${where}`); continue; }
    for (const k of keys) if (isEmpty(obj[k])) fail(0, `пустое поле content.${where}.${k}`);
  }
  for (const [where, keys] of Object.entries(ITEM_SHAPE)) {
    const arr = c[where];
    if (!Array.isArray(arr) || arr.length === 0) { fail(0, `content.${where} должен быть непустым массивом`); continue; }
    arr.forEach((item, i) => {
      for (const k of keys) {
        // unit метрики может быть пустым (безразмерная доля), но поле обязано быть
        if (where === 'metrics' && k === 'unit' && item.unit === '') continue;
        if (isEmpty(item[k])) fail(0, `пустое поле content.${where}[${i}].${k}`);
      }
    });
  }
  if (!c.screenshotFacts || typeof c.screenshotFacts !== 'object') fail(0, 'нет объекта content.screenshotFacts');
  if (Array.isArray(c.metrics)) {
    if (c.metrics.length < 5) fail(0, `метрик ${c.metrics.length}, нужно не меньше 5`);
    c.metrics.forEach((m, i) => {
      if (!['measured', 'calculated'].includes(m.kind)) fail(0, `metrics[${i}].kind = «${m.kind}»`);
    });
  }
  if (Array.isArray(c.pipeline)) {
    const idx = c.pipeline.map((s) => s.index).join(',');
    if (idx !== '00,01,02,03,04,05,06,07,08') fail(0, `этапы конвейера должны идти 00–08, сейчас: ${idx}`);
    c.pipeline.forEach((s, i) => {
      if (!Array.isArray(s.params) || s.params.length === 0) fail(0, `pipeline[${i}].params пуст`);
      else s.params.forEach((p, j) => ['name', 'value'].forEach((k) => {
        if (isEmpty(p[k])) fail(0, `пустое поле pipeline[${i}].params[${j}].${k}`);
      }));
    });
  }
  if (Array.isArray(c.tradeoffs) && c.tradeoffs.length < 5) fail(0, `компромиссов ${c.tradeoffs.length}, нужно не меньше 5`);
  if (Array.isArray(c.limits)) {
    if (c.limits.length !== 5) fail(0, `ограничений ${c.limits.length}, нужно 5`);
    c.limits.forEach((l, i) => {
      if (!['done', 'partial'].includes(l.status)) fail(0, `limits[${i}].status = «${l.status}»`);
    });
  }
  if (Array.isArray(c.roadmap)) c.roadmap.forEach((r, i) => {
    if (!['done', 'planned'].includes(r.status)) fail(0, `roadmap[${i}].status = «${r.status}»`);
  });
  walk(c, (v, kp) => {
    if (typeof v === 'string' && v.trim() === '' && !(kp[0] === 'metrics' && lastKey(kp) === 'unit')) {
      fail(0, `пустая строка content.${kp.join('.')}`);
    }
  });
}

/* ---------- 1. числа ---------- */
function normalizeNumbers(text) {
  return String(text)
    .replace(/(\d)[ \u00A0\u202F\u2009](?=\d{3}(?!\d))/g, '$1') // 300 000 → 300000
    .replace(/(\d),(\d)/g, '$1.$2');                               // 0,38 → 0.38
}
function numberTokens(text) {
  return normalizeNumbers(text).match(/\d+(?:\.\d+)?/g) || [];
}
function variantsOf(token) {
  const out = new Set([token]);
  if (token.includes('.')) {
    const stripped = token.replace(/0+$/, '').replace(/\.$/, '');
    out.add(stripped);
  } else {
    out.add(`${token}.0`);
  }
  return [...out];
}
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function checkNumbers(c) {
  const sources = [path.join(ROOT, 'README.md'), path.join(ROOT, 'PRODUCT.md'), path.join(ROOT, 'app', 'config.py'), NOTES];
  let corpus = '';
  for (const s of sources) {
    const t = readText(s);
    if (t === null) fail(1, `нет источника фактов ${rel(s)}`); else corpus += '\n' + t;
  }
  corpus = normalizeNumbers(corpus);
  const found = new Map();
  const has = (token) => {
    if (found.has(token)) return found.get(token);
    const ok = variantsOf(token).some((v) => new RegExp(`(^|[^\\d.])${escapeRe(v)}(?![\\d]|\\.\\d)`).test(corpus));
    found.set(token, ok);
    return ok;
  };
  const scope = {
    metrics: c.metrics,
    'pipeline[].params': (c.pipeline || []).map((s) => s.params),
    limits: c.limits,
    compare: c.compare,
    calibration: c.calibration,
    ema: c.ema,
  };
  const skipKeys = new Set(['id', 'kind', 'status', 'index']);
  for (const [name, value] of Object.entries(scope)) {
    walk(value, (v, kp) => {
      if (skipKeys.has(lastKey(kp))) return;
      if (typeof v !== 'string' && typeof v !== 'number') return;
      for (const token of numberTokens(typeof v === 'number' ? String(v) : v)) {
        if (!has(token)) fail(1, `число ${token} из ${name}.${kp.join('.')} не найдено в README.md, PRODUCT.md, app/config.py, notes.md`);
      }
    });
  }
}

/* ---------- 2. локальные пути ---------- */
const isLocal = (u) => u && !/^(https?:|mailto:|tel:|data:|javascript:|#|\/\/)/i.test(u);
function checkLocalPath(u, from) {
  const clean = decodeURI(u.split('#')[0].split('?')[0]);
  if (!clean) return;
  if (clean.startsWith('/')) { fail(2, `абсолютный путь «${u}» в ${from}`); return; }
  const p = path.resolve(SITE, clean);
  if (!fs.existsSync(p)) fail(2, `нет файла «${u}» (ссылка из ${from})`);
}
function checkPaths(c) {
  const index = readText(path.join(SITE, 'index.html'));
  if (index === null) fail(2, 'нет файла site/index.html');
  else {
    const re = /\b(?:src|href)\s*=\s*["']([^"']+)["']/g;
    let m;
    while ((m = re.exec(index))) if (isLocal(m[1])) checkLocalPath(m[1], 'index.html');
  }
  if (c) walk(c, (v, kp) => {
    if (typeof v !== 'string') return;
    const k = lastKey(kp);
    if ((k === 'src' || k === 'href' || /^assets\//.test(v)) && isLocal(v)) checkLocalPath(v, `content.${kp.join('.')}`);
  });
  for (const css of walkFiles(path.join(SITE, 'css')).filter((f) => f.endsWith('.css'))) {
    const t = readText(css);
    const re = /url\(\s*["']?([^"')]+)["']?\s*\)/g;
    let m;
    while ((m = re.exec(t))) {
      if (!isLocal(m[1])) continue;
      const p = path.resolve(path.dirname(css), decodeURI(m[1].split('#')[0].split('?')[0]));
      if (!fs.existsSync(p)) fail(2, `нет файла «${m[1]}» (url() в ${rel(css)})`);
    }
  }
}

/* ---------- 3. запрещённые слова и утверждения ---------- */
const BANNED = [
  [/open[\s-]?source/i, 'open source'],
  [/\bMIT\b/, 'MIT'],
  [/lorem/i, 'lorem'],
  [/\bTODO\b/i, 'TODO'],
  [/\bFIXME\b/i, 'FIXME'],
  [/бесплатн/i, 'бесплатно'],
];
const BANNED_CLAIMS = [
  [/34\s*(e2e|провер)/i, '«34 проверки e2e» (тестов в репозитории нет)'],
  [/18\s*(браузерн|провер)/i, '«18 браузерных проверок» (тестов в репозитории нет)'],
  [/3\s*[–—-]\s*37/, '«3–37 мс» (RTT браузера, не ответ сервера)'],
  [/ответ\s+сервера/i, '«ответ сервера» (метрика не подтверждена кодом)'],
  [/GuageVision/, 'опечатка «GuageVision» в тексте'],
];
const TEXT_EXT = new Set(['.html', '.css', '.js', '.md', '.svg', '.json', '.txt']);
function checkBanned(c) {
  const files = walkFiles(SITE).filter((f) => {
    const r = path.relative(SITE, f).split(path.sep).join('/');
    return TEXT_EXT.has(path.extname(f)) && !r.startsWith('tests/') && r !== 'design-system.md';
  });
  for (const f of files) {
    const lines = readText(f).split(/\r?\n/);
    lines.forEach((line, i) => {
      for (const [re, word] of BANNED) if (re.test(line)) fail(3, `«${word}» в ${rel(f)}:${i + 1}`);
    });
  }
  if (c) walk(c, (v, kp) => {
    if (typeof v !== 'string') return;
    const k = lastKey(kp);
    for (const [re, what] of BANNED_CLAIMS) {
      if (what.startsWith('опечатка') && (k === 'href' || /Url$/.test(k))) continue;
      if (re.test(v)) fail(3, `${what}: content.${kp.join('.')}`);
    }
  });
}

/* ---------- 4. модули ---------- */
function checkModules() {
  const files = walkFiles(path.join(SITE, 'js')).filter((f) => f.endsWith('.js'));
  for (const f of files) {
    const lines = readText(f).split(/\r?\n/);
    lines.forEach((line, i) => {
      if (/^\s*(import|export)\s+[\w{*'"]/.test(line) || /\bimport\s*\(/.test(line)) fail(4, `import/export в ${rel(f)}:${i + 1}`);
      if (/type\s*=\s*["']module["']/.test(line)) fail(4, `type="module" в ${rel(f)}:${i + 1}`);
    });
  }
  const index = readText(path.join(SITE, 'index.html'));
  if (index && /type\s*=\s*["']module["']/.test(index)) fail(4, 'type="module" в site/index.html');
}

/* ---------- 5. порядок секций в вариантах ---------- */
function firstMention(code, id) {
  const re = new RegExp(`(['"\`])#?${id}\\1|id\\s*=\\s*\\\\?["']${id}\\\\?["']`);
  const m = re.exec(code);
  return m ? m.index : -1;
}
function checkVariants() {
  const dir = path.join(SITE, 'js', 'variants');
  const files = walkFiles(dir).filter((f) => f.endsWith('.js'));
  for (const f of files) {
    const code = readText(f);
    let prev = -1;
    let prevId = null;
    for (const id of SECTION_IDS) {
      const pos = firstMention(code, id);
      if (pos < 0) { fail(5, `${rel(f)} не упоминает секцию «${id}»`); continue; }
      if (pos < prev) fail(5, `${rel(f)}: секция «${id}» упомянута раньше «${prevId}»`);
      prev = pos; prevId = id;
    }
  }
  return files.length;
}

/* ---------- 6. типографика content.js ---------- */
function checkTypography(c) {
  const skip = new Set(['id', 'file', 'source', 'src', 'href', 'version', 'formula', 'repoUrl', 'licenseUrl', 'pdfUrl', 'authorUrl', 'roi', 'code']);
  walk(c, (v, kp) => {
    if (typeof v !== 'string' || kp[0] === 'screenshotFacts') return;
    const where = `content.${kp.join('.')}`;
    const k = lastKey(kp);
    if (/ - /.test(v)) fail(6, `дефис вместо тире « — » в ${where}`);
    if (/--/.test(v)) fail(6, `«--» вместо тире в ${where}`);
    if (skip.has(k)) return;
    if (/(^|[^\w.-])\d+-\d+(?![\w.])/.test(v)) fail(6, `диапазон через дефис (нужно «–») в ${where}: «${v}»`);
    const decimals = v.match(/(^|[^\w.≥\-])\d+\.\d+(?![\w.])/g);
    if (decimals) fail(6, `десятичная точка (нужна запятая) в ${where}: «${decimals.join(', ').trim()}»`);
  });
}

/* ---------- запуск ---------- */
const content = loadContent();
if (content) {
  checkShape(content);
  checkNumbers(content);
  checkTypography(content);
}
checkPaths(content);
checkBanned(content);
checkModules();
const variantCount = checkVariants();

if (failures.length) {
  console.log(failures.join('\n'));
  console.log(`\nFAIL: нарушений ${failures.length}`);
  process.exit(1);
}
console.log(`OK: факты, пути, запрещённые слова, модули, типографика; вариантов проверено: ${variantCount}`);
process.exit(0);
