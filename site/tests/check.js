#!/usr/bin/env node
/*
 * GaugeVision AI — автоматическая проверка лендинга (одна страница «Циферблат»).
 * Запуск из корня репозитория: node site/tests/check.js
 * Без зависимостей. Код выхода 0 — всё зелёное; иначе каждое нарушение печатается строкой.
 *
 * Проверки (interfaces.md, «Шов тестов»):
 *   0. Форма GV.content: обязательные поля есть и не пустые; 8 секций, 4 карточки конвейера.
 *   1. Каждое число во всех строках и числовых полях GV.content (кроме служебных ключей
 *      и screenshotFacts) встречается в README.md, PRODUCT.md, app/config.py или notes.md прошлой сборки.
 *   2. Локальные src/href в index.html и content.js (и url() в css/) существуют; видео и картинки —
 *      в бюджете размера; оригинал видео побайтно равен references/; копии для перемотки —
 *      без звука, moov в начале файла, ключевой кадр не реже каждого 2-го кадра.
 *   3. Запрещённые слова в site/ (кроме tests/ и design-system.md); «гомограф» — только в roadmap.
 *   4. В js/ нет import/export и type="module".
 *   5. Секции идут в порядке брифа; каждый модуль из GV.page.mounts подключён <script> в index.html.
 *   6. Нет вариантов, роутера и студийной панели.
 *   7. Ни одна выводимая строка GV.content не длиннее 140 символов; заголовки 3–6 слов;
 *      в hero нет надзаголовка (kicker), строка сути — одно предложение;
 *      ссылки — только GitHub EGRNEGR; 25 камер — замер, 50 и 100 — расчёт.
 *   8. Типографика строк content.js: нет « - » вместо тире, дефисных диапазонов и десятичной точки.
 *   9. Движение: в css/ transition и @keyframes трогают только transform и opacity; карточки конвейера —
 *      четыре этапа по брифу с замеренной задержкой; hero.stage и старый pipeline.js удалены.
 *  10. Размеры в css/ (кроме fonts.css) — в rem: px только у линий ±1px, центровки -0.5px и в условиях @media.
 *  11. Каждый экспорт GV.kit используется в site/js или в тестах компонентов.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SITE = path.resolve(__dirname, '..');
const ROOT = path.resolve(SITE, '..');
const SECTION_IDS = ['hero', 'reading', 'pipeline', 'metrics', 'compare', 'architecture', 'limits', 'contact'];
const MAX_TEXT = 140;
const REPO_PREFIX = 'https://github.com/EGRNEGR';

/* notes.md прошлой сборки: папка теряет суффикс --wip при сдаче, ищем по маске. */
function findNotes() {
  const dir = path.join(ROOT, '.autopilot');
  const dirs = fs.existsSync(dir) ? fs.readdirSync(dir).filter((d) => /gaugevision-landing/.test(d)).sort() : [];
  const hit = dirs.map((d) => path.join(dir, d, 'notes.md')).find((p) => fs.existsSync(p));
  return hit || path.join(dir, '2026-11-14-gaugevision-landing', 'notes.md');
}
const NOTES = findNotes();

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
const words = (s) => String(s).split(/\s+/).filter((t) => /[\p{L}\p{N}]/u.test(t));

/* ---------- загрузка content.js и page.js ---------- */
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

/* page.js исполняется с заглушкой document: страница не строится, читается только таблица mounts. */
function loadMounts() {
  const file = path.join(SITE, 'js', 'page.js');
  const code = readText(file);
  if (code === null) { fail(5, `нет файла ${rel(file)}`); return null; }
  const document = { readyState: 'loading', addEventListener() {}, documentElement: {} };
  const sandbox = { console: { error() {}, log() {}, warn() {} }, document };
  sandbox.window = sandbox;
  sandbox.window.GV = {};
  try {
    vm.runInNewContext(code, sandbox, { filename: file });
  } catch (e) {
    fail(5, `page.js не загружается без DOM: ${e.message}`);
    return null;
  }
  const page = sandbox.GV.page;
  if (!page || typeof page.render !== 'function' || !page.mounts) { fail(5, 'page.js не определяет GV.page.render и GV.page.mounts'); return null; }
  return page.mounts;
}

/* ---------- 0. форма ---------- */
const SHAPE = {
  meta: ['name', 'tagline', 'repoUrl', 'licenseUrl', 'track', 'trackShort', 'copyright', 'version'],
  hero: ['title', 'line', 'scrollLabel', 'video'],
  'hero.video': ['src', 'srcMobile', 'poster', 'label'],
  reading: ['theta', 'device', 'caption'],
  calibration: ['thetaMin', 'thetaMax', 'vMin', 'vMax', 'unit', 'direction', 'setpoints', 'barPerMpa', 'formula'],
  ema: ['alpha', 'minConfidence', 'caption'],
  compare: ['before', 'after', 'savingNote', 'timeline'],
  architecture: ['nodes', 'edges', 'stack', 'boundaryLabel'],
  untested: ['title', 'text'],
  pipelineTotal: ['value', 'unit', 'label'],
  contact: ['title', 'links', 'backdrop'],
};
const ITEM_SHAPE = {
  sections: ['id', 'index', 'nav'],
  metrics: ['id', 'value', 'unit', 'label', 'condition', 'kind'],
  pipeline: ['id', 'index', 'title', 'short', 'params', 'file', 'aspect'],
  pipelineCards: ['id', 'index', 'title', 'formula', 'params'],
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
      if (Array.isArray(s.params)) s.params.forEach((p, j) => ['name', 'value'].forEach((k) => {
        if (isEmpty(p[k])) fail(0, `пустое поле pipeline[${i}].params[${j}].${k}`);
      }));
    });
  }
  if (Array.isArray(c.pipelineCards)) {
    const ids = c.pipelineCards.map((s) => s.id).join(',');
    if (ids !== 'locate,normalize,needle,stabilize') fail(0, `карточки конвейера: нужно locate, normalize, needle, stabilize, сейчас: ${ids}`);
    const idx = c.pipelineCards.map((s) => s.index).join(',');
    if (idx !== '01,02,03,04') fail(0, `индексы карточек конвейера 01–04, сейчас: ${idx}`);
    const titles = c.pipelineCards.map((x) => String(x.title).replace(/\u00A0/g, ' ')).join(' | ');
    const brief = 'Локализация: CLAHE + YOLOv8n | Эллипс → круг: аффинная коррекция | Угол θ: радиальный момент + HoughLinesP | Сглаживание EMA α = 0,25';
    if (titles !== brief) fail(0, `заголовки карточек конвейера не по брифу: ${titles}`);
    c.pipelineCards.forEach((card, i) => {
      const lat = card.latency;
      const want = [['7,2', 'GPU'], null, null, ['≈ 90 %', 'скачка за 8 кадров']][i];
      if (want === null && lat !== null) fail(0, `pipelineCards[${i}]: у этапа нет отдельного замера, latency должен быть null (показывается «в составе» итога)`);
      if (want && (!lat || String(lat.value).replace(/\u00A0/g, ' ') !== want[0] || String(lat.unit).replace(/\u00A0/g, ' ').indexOf(want[1]) < 0)) {
        fail(0, `pipelineCards[${i}].latency должен быть «${want[0]}» … «${want[1]}»`);
      }
      if (!Array.isArray(card.formula)) fail(0, `pipelineCards[${i}].formula должен быть массивом строк`);
      if (!('latency' in card)) fail(0, `pipelineCards[${i}] без поля latency (объект или null)`);
      else if (card.latency !== null && ['value', 'unit'].some((k) => isEmpty(card.latency[k]))) fail(0, `pipelineCards[${i}].latency без value/unit`);
    });
  }
  if (c.reading && typeof c.reading.theta !== 'number') fail(0, 'content.reading.theta должен быть числом');
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

/* Ключи без фактов: идентификаторы, порядковые номера, пути, ссылки, точность вывода. */
const NUMBER_SKIP = new Set(['id', 'kind', 'status', 'index', 'digits', 'version', 'group', 'src', 'srcMobile', 'poster',
  'backdrop', 'href', 'file', 'source', 'roi', 'repoUrl', 'licenseUrl']);

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
  walk(c, (v, kp) => {
    if (kp[0] === 'screenshotFacts' || NUMBER_SKIP.has(lastKey(kp))) return;
    if (typeof v !== 'string' && typeof v !== 'number') return;
    for (const token of numberTokens(typeof v === 'number' ? String(v) : v)) {
      if (!has(token)) fail(1, `число ${token} из content.${kp.join('.')} не найдено в README.md, PRODUCT.md, app/config.py, notes.md`);
    }
  });
}

/* ---------- 2. локальные пути и медиа ---------- */
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

/* Минимальный разбор MP4: дорожки (тип обработчика, число кадров, ключевые кадры) и порядок moov/mdat. */
function parseMp4(buf) {
  const CONTAINERS = new Set(['moov', 'trak', 'mdia', 'minf', 'stbl']);
  const top = [];
  const tracks = [];
  let track = null;
  function boxes(start, end, depth) {
    let pos = start;
    while (pos + 8 <= end) {
      let size = buf.readUInt32BE(pos);
      const type = buf.toString('latin1', pos + 4, pos + 8);
      let header = 8;
      if (size === 1) { size = Number(buf.readBigUInt64BE(pos + 8)); header = 16; } else if (size === 0) size = end - pos;
      if (size < header || pos + size > end) break;
      if (depth === 0) top.push(type);
      if (type === 'trak') { track = { handler: '', samples: 0, sync: null }; tracks.push(track); }
      const body = pos + header;
      if (CONTAINERS.has(type)) boxes(body, pos + size, depth + 1);
      else if (track && type === 'hdlr') track.handler = buf.toString('latin1', body + 8, body + 12);
      else if (track && type === 'stsz') track.samples = buf.readUInt32BE(body + 8);
      else if (track && type === 'stss') {
        const n = buf.readUInt32BE(body + 4);
        track.sync = [];
        for (let i = 0; i < n; i++) track.sync.push(buf.readUInt32BE(body + 8 + i * 4));
      }
      pos += size;
    }
  }
  boxes(0, buf.length, 0);
  return { top, tracks };
}

const MEDIA = [
  { file: 'assets/video/gauge_pullback.scrub.mp4', max: 14 * 1024 * 1024, scrub: true },
  { file: 'assets/video/gauge_pullback.scrub-m.mp4', max: 6 * 1024 * 1024, scrub: true },
  { file: 'assets/img/poster.jpg', max: 250 * 1024 },
  { file: 'assets/img/boiler-hall.jpg', max: 350 * 1024 },
];
function checkMedia() {
  const original = path.join(SITE, 'assets', 'video', 'gauge_pullback.mp4');
  const reference = path.join(ROOT, 'references', 'gauge_pullback.mp4');
  if (!fs.existsSync(original)) fail(2, 'нет оригинала site/assets/video/gauge_pullback.mp4');
  else if (fs.existsSync(reference) && !fs.readFileSync(original).equals(fs.readFileSync(reference))) {
    fail(2, 'site/assets/video/gauge_pullback.mp4 не совпадает побайтно с references/gauge_pullback.mp4');
  }
  for (const m of MEDIA) {
    const p = path.join(SITE, m.file);
    if (!fs.existsSync(p)) { fail(2, `нет файла site/${m.file}`); continue; }
    const size = fs.statSync(p).size;
    if (size > m.max) fail(2, `site/${m.file}: ${(size / 1048576).toFixed(2)} МБ больше бюджета ${(m.max / 1048576).toFixed(2)} МБ`);
    if (!m.scrub) continue;
    const { top, tracks } = parseMp4(fs.readFileSync(p));
    if (top.indexOf('moov') < 0 || top.indexOf('mdat') < 0 || top.indexOf('moov') > top.indexOf('mdat')) fail(2, `site/${m.file}: moov не перед mdat (нужен +faststart)`);
    if (tracks.some((t) => t.handler === 'soun')) fail(2, `site/${m.file}: есть звуковая дорожка`);
    const video = tracks.find((t) => t.handler === 'vide');
    if (!video) { fail(2, `site/${m.file}: нет видеодорожки`); continue; }
    if (video.sync) {
      const marks = video.sync.concat([video.samples + 1]);
      let prev = 0;
      for (const s of marks) {
        if (s - prev > 2) { fail(2, `site/${m.file}: между ключевыми кадрами ${s - prev} кадров, нужно ≤ 2`); break; }
        prev = s;
      }
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
  [/субпиксел/i, 'субпиксельный'],
];
const HOMOGRAPHY = /гомограф/i;
const BANNED_CLAIMS = [
  [/34\s*(e2e|провер)/i, '«34 проверки e2e» (тестов в репозитории нет)'],
  [/18\s*(браузерн|провер)/i, '«18 браузерных проверок» (тестов в репозитории нет)'],
  [/3\s*[–—-]\s*37/, '«3–37 мс» (RTT браузера, не ответ сервера)'],
  [/ответ\s+сервера/i, '«ответ сервера» (метрика не подтверждена кодом)'],
  [/GuageVision/, 'опечатка «GuageVision» в тексте'],
];
const TEXT_EXT = new Set(['.html', '.css', '.js', '.md', '.svg', '.json', '.txt']);
function siteTextFiles() {
  return walkFiles(SITE).filter((f) => {
    const r = path.relative(SITE, f).split(path.sep).join('/');
    return TEXT_EXT.has(path.extname(f)) && !r.startsWith('tests/') && r !== 'design-system.md';
  });
}
function checkBanned(c) {
  const contentFile = path.join(SITE, 'js', 'content.js');
  for (const f of siteTextFiles()) {
    const lines = readText(f).split(/\r?\n/);
    lines.forEach((line, i) => {
      for (const [re, word] of BANNED) if (re.test(line)) fail(3, `«${word}» в ${rel(f)}:${i + 1}`);
      // в content.js «гомография» допустима только в roadmap — это проверяется по данным ниже
      if (f !== contentFile && HOMOGRAPHY.test(line)) fail(3, `«гомография» вне roadmap в ${rel(f)}:${i + 1}`);
    });
  }
  if (c) walk(c, (v, kp) => {
    if (typeof v !== 'string') return;
    const k = lastKey(kp);
    if (HOMOGRAPHY.test(v) && kp[0] !== 'roadmap') fail(3, `«гомография» вне roadmap: content.${kp.join('.')}`);
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

/* ---------- 5. секции и модули страницы ---------- */
function checkSections(c, mounts) {
  if (c && Array.isArray(c.sections)) {
    const ids = c.sections.map((s) => s.id).join(',');
    if (ids !== SECTION_IDS.join(',')) fail(5, `секции должны идти ${SECTION_IDS.join(', ')}, сейчас: ${ids}`);
  }
  if (!mounts) return;
  const index = readText(path.join(SITE, 'index.html')) || '';
  const scripts = [];
  const re = /<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/g;
  let m;
  while ((m = re.exec(index))) scripts.push(m[1]);
  for (const [sectionId, name] of Object.entries(mounts)) {
    if (SECTION_IDS.indexOf(sectionId) < 0) fail(5, `GV.page.mounts: неизвестная секция «${sectionId}»`);
    const defines = new RegExp(`GV\\.components\\.${escapeRe(String(name))}\\s*=`);
    const ok = scripts.some((src) => isLocal(src) && defines.test(readText(path.join(SITE, src)) || ''));
    if (!ok) fail(5, `модуль «${name}» для секции «${sectionId}» не подключён <script> в index.html`);
  }
  const page = scripts.indexOf('js/page.js');
  if (page < 0) fail(5, 'js/page.js не подключён в index.html');
  else if (page !== scripts.length - 1) fail(5, 'js/page.js должен подключаться последним');
}

/* ---------- 6. нет вариантов, роутера и студии ---------- */
const LEGACY = [
  [/gv-studio/, '#gv-studio'],
  [/gv\.variant/, 'gv.variant'],
  [/GV\.variants|GV\.app\b/, 'GV.variants / GV.app'],
  [/data-variant|data-bg/, 'атрибуты вариантов и фона старых Tweaks'],
];
/* Компонент heroStage: в скриптах и разметке его нет (стили-остатки в components.css — не код компонента). */
const HERO_STAGE = /heroStage|hero-stage\.js/;
function checkLegacy() {
  if (fs.existsSync(path.join(SITE, 'js', 'variants'))) fail(6, 'папка site/js/variants/ должна уйти в archive/');
  if (fs.existsSync(path.join(SITE, 'js', 'app.js'))) fail(6, 'site/js/app.js (роутер вариантов) должен уйти в archive/');
  if (fs.existsSync(path.join(SITE, 'js', 'components', 'hero-stage.js'))) fail(6, 'site/js/components/hero-stage.js должен уйти в archive/');
  for (const f of siteTextFiles()) {
    const markup = /\.(js|html)$/.test(f);
    readText(f).split(/\r?\n/).forEach((line, i) => {
      for (const [re, what] of LEGACY) if (re.test(line)) fail(6, `${what} в ${rel(f)}:${i + 1}`);
      if (markup && HERO_STAGE.test(line)) fail(6, `heroStage в ${rel(f)}:${i + 1}`);
    });
  }
}

/* ---------- 7. минимум текста, ссылки, метки замер/расчёт ---------- */
/* Ключи, которые не выводятся на страницу текстом: ARIA-описания, пути, ссылки, данные скриншотов. */
const TEXT_SKIP = new Set(['alt', 'id', 'src', 'srcMobile', 'poster', 'backdrop', 'href', 'repoUrl', 'licenseUrl']);
function checkText(c) {
  walk(c, (v, kp) => {
    if (typeof v !== 'string' || kp[0] === 'screenshotFacts' || TEXT_SKIP.has(lastKey(kp))) return;
    if (kp.join('.') === 'hero.video.label') return; // aria-описание видео
    if (v.length > MAX_TEXT) fail(7, `строка длиннее ${MAX_TEXT} символов (${v.length}): content.${kp.join('.')}`);
  });
  (c.sections || []).forEach((s, i) => {
    if (s.id !== 'hero' && isEmpty(s.title)) fail(7, `у секции «${s.id}» нет заголовка`);
    if (s.title !== undefined) {
      const n = words(s.title).length;
      if (n < 3 || n > 6) fail(7, `заголовок секции «${s.id}» — ${n} слов, нужно 3–6: «${s.title}»`);
    }
    if (s.lead !== undefined) fail(7, `у секции «${s.id}» остался lead — абзацев на странице нет`);
  });
  if (c.hero) {
    const n = words(c.hero.title || '').length;
    if (n < 3 || n > 6) fail(7, `hero.title — ${n} слов, нужно 3–6`);
    if (String(c.hero.line || '').length > 90) fail(7, `hero.line длиннее 90 символов (${String(c.hero.line).length})`);
    // Поверх видео — только h1, одна строка сути и индикатор прокрутки (R13): надзаголовка нет
    if (c.hero.kicker !== undefined) fail(7, 'content.hero.kicker: поверх видео нет надзаголовка — только h1, строка сути и индикатор');
    // Строка сути — одно предложение: внутри нет конца предложения
    if (/[.!?…]\s+\S/.test(String(c.hero.line || ''))) fail(7, `hero.line — больше одного предложения: «${c.hero.line}»`);
  }
  // Разметка HUD hero (компонент и его стили) тоже без надзаголовка
  for (const f of [path.join(SITE, 'js', 'components', 'scroll-video.js'), path.join(SITE, 'css', 'hero.css')]) {
    (readText(f) || '').split(/\r?\n/).forEach((line, i) => {
      if (/kicker/.test(line)) fail(7, `надзаголовок (kicker) в HUD hero: ${rel(f)}:${i + 1}`);
    });
  }
  walk(c, (v, kp) => {
    if (typeof v !== 'string' || !/^https?:/.test(v)) return;
    if (v !== REPO_PREFIX && v.indexOf(REPO_PREFIX + '/') !== 0) fail(7, `ссылка не на GitHub EGRNEGR: content.${kp.join('.')} = ${v}`);
  });
  const primary = ((c.contact && c.contact.links) || []).filter((l) => l.primary);
  if (primary.length !== 1 || primary[0].href !== c.meta.repoUrl) fail(7, 'в финале должна быть ровно одна главная ссылка — на репозиторий');
  const cams = { '25': 'measured', '50': 'calculated', '100': 'calculated' };
  Object.keys(cams).forEach((n) => {
    const m = (c.metrics || []).find((x) => new RegExp(`(^|\\D)${n}\\s*камер`).test(x.label || ''));
    if (!m) fail(7, `нет метрики «${n} камер»`);
    else if (m.kind !== cams[n]) fail(7, `«${n} камер» должна быть «${cams[n] === 'measured' ? 'замер' : 'расчёт'}», сейчас kind = ${m.kind}`);
  });
}

/* ---------- 8. типографика content.js ---------- */
function checkTypography(c) {
  const skip = new Set(['id', 'file', 'source', 'src', 'srcMobile', 'poster', 'backdrop', 'href', 'version', 'formula', 'repoUrl', 'licenseUrl', 'roi', 'code']);
  walk(c, (v, kp) => {
    if (typeof v !== 'string' || kp[0] === 'screenshotFacts') return;
    const where = `content.${kp.join('.')}`;
    const k = lastKey(kp);
    if (/ - /.test(v)) fail(8, `дефис вместо тире « — » в ${where}`);
    if (/--/.test(v)) fail(8, `«--» вместо тире в ${where}`);
    if (skip.has(k)) return;
    if (/(^|[^\w.-])\d+-\d+(?![\w.])/.test(v)) fail(8, `диапазон через дефис (нужно «–») в ${where}: «${v}»`);
    const decimals = v.match(/(^|[^\w.≥\-])\d+\.\d+(?![\w.])/g);
    if (decimals) fail(8, `десятичная точка (нужна запятая) в ${where}: «${decimals.join(', ').trim()}»`);
  });
}

/* ---------- 9. движение: только transform и opacity ---------- */
const MOTION_OK = new Set(['transform', 'opacity', 'none']);
function topLevelSplit(value) {
  const parts = [];
  let depth = 0;
  let cur = '';
  for (const ch of value) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; } else cur += ch;
  }
  if (cur.trim()) parts.push(cur);
  return parts.map((p) => p.trim()).filter(Boolean);
}
function keyframeBodies(css) {
  const out = [];
  const re = /@keyframes\s+([\w-]+)\s*\{/g;
  let m;
  while ((m = re.exec(css))) {
    let depth = 1;
    let i = re.lastIndex;
    while (i < css.length && depth > 0) { if (css[i] === '{') depth++; else if (css[i] === '}') depth--; i++; }
    out.push({ name: m[1], body: css.slice(re.lastIndex, i - 1) });
  }
  return out;
}
function checkMotionCss() {
  const files = walkFiles(path.join(SITE, 'css')).filter((f) => f.endsWith('.css'));
  for (const f of files) {
    const css = (readText(f) || '').replace(/\/\*[\s\S]*?\*\//g, '');
    const re = /(^|[\s;{])(transition-property|transition)\s*:\s*([^;}]+)/g;
    let m;
    while ((m = re.exec(css))) {
      const names = m[2] === 'transition'
        ? topLevelSplit(m[3]).map((part) => part.split(/\s+/)[0])
        : topLevelSplit(m[3]);
      for (const name of names) {
        if (!MOTION_OK.has(name)) fail(9, `transition по «${name}» в ${rel(f)} (разрешены transform и opacity)`);
      }
    }
    for (const { name, body } of keyframeBodies(css)) {
      const decl = /([\w-]+)\s*:/g;
      let d;
      while ((d = decl.exec(body))) {
        if (!MOTION_OK.has(d[1]) && d[1] !== 'animation-timing-function') fail(9, `@keyframes ${name} трогает «${d[1]}» в ${rel(f)} (разрешены transform и opacity)`);
      }
    }
  }
  if (fs.existsSync(path.join(SITE, 'js', 'components', 'pipeline.js'))) fail(9, 'site/js/components/pipeline.js (старый конвейер на 9 этапов) должен быть удалён');
}

/* ---------- 10. размеры в rem: px только у линий 1px и в условиях @media ---------- */
// ±1px — линия и её смещение на толщину линии, -0.5px — центровка линии 1px. fonts.css — вне правила.
const PX_OK = new Set(['1px', '-1px', '-0.5px']);
function checkPxCss() {
  const files = walkFiles(path.join(SITE, 'css')).filter((f) => f.endsWith('.css') && path.basename(f) !== 'fonts.css');
  for (const f of files) {
    const lines = (readText(f) || '')
      .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
      .replace(/@media[^{]*/g, (m) => m.replace(/[^\n]/g, ' '))
      .split('\n');
    lines.forEach((line, i) => {
      const re = /(^|[^\w.-])(-?(?:\d+\.?\d*|\.\d+))px\b/g;
      let m;
      while ((m = re.exec(line))) {
        const token = m[2] + 'px';
        if (!PX_OK.has(token)) fail(10, `${token} в ${rel(f)}:${i + 1} — размеры в rem (масштаб Tweaks), px только у линий 1px`);
      }
    });
  }
}

/* ---------- 11. GV.kit без мёртвых экспортов ---------- */
// Каждый экспорт kit.js вызывается где-то ещё в site/js или в тестах компонентов.
function checkKitExports() {
  const file = path.join(SITE, 'js', 'components', 'kit.js');
  const code = readText(file);
  if (code === null) { fail(11, `нет файла ${rel(file)}`); return; }
  // Экспорты читаются из текста: DOM-часть kit.js без браузера не выполняется.
  const literal = (code.match(/var kit = \{([\s\S]*?)\};/) || [null, ''])[1];
  const names = new Set();
  literal.replace(/(\w+)\s*:/g, (m, n) => names.add(n));
  code.replace(/\bkit\.(\w+)\s*=/g, (m, n) => names.add(n));
  if (!names.size) { fail(11, 'kit.js: не найдены экспорты GV.kit (var kit = {…}, kit.name = …)'); return; }
  const users = walkFiles(path.join(SITE, 'js')).filter((f) => f.endsWith('.js') && f !== file)
    .concat([path.join(SITE, 'tests', 'components.test.js')])
    .map((f) => readText(f) || '').join('\n');
  for (const name of names) {
    if (!new RegExp('\\.' + escapeRe(name) + '\\b').test(users)) fail(11, `GV.kit.${name} нигде не используется — удалить из kit.js`);
  }
}

/* ---------- запуск ---------- */
const content = loadContent();
const mounts = loadMounts();
if (content) {
  checkShape(content);
  checkNumbers(content);
  checkText(content);
  checkTypography(content);
}
checkPaths(content);
checkMedia();
checkBanned(content);
checkModules();
checkSections(content, mounts);
checkLegacy();
checkMotionCss();
checkPxCss();
checkKitExports();

if (failures.length) {
  console.log(failures.join('\n'));
  console.log(`\nFAIL: нарушений ${failures.length}`);
  process.exit(1);
}
console.log(`OK: факты, пути и медиа, запрещённые слова, модули, 8 секций и ${Object.keys(mounts || {}).length} модулей, без вариантов, минимум текста, типографика`);
process.exit(0);
