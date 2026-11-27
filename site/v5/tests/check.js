#!/usr/bin/env node
/*
 * Автоматическая проверка сайта GaugeVision AI 3.0 в дизайне «Журнал обходчика» (site/v5).
 * Запуск: node site/v5/tests/check.js
 * Без зависимостей. Проверяет форму контента, локальные пути и MP4, запрещённые слова и формулировки,
 * отсутствие средней точки «·» в текстах интерфейса, классические скрипты без import/export,
 * 11 листов и все модули GV.page.mounts, маркеры-акценты, ссылки только на GitHub EGRNEGR,
 * типографику, движение только через transform/opacity и размеры в rem.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SITE = path.resolve(__dirname, '..');
const ROOT = path.resolve(SITE, '../..');
const SECTION_IDS = ['hero', 'compare', 'multigauge', 'resilience', 'scada', 'forecast', 'optimizer', 'metrics', 'evolution', 'limits', 'contact'];
const REPO_PREFIX = 'https://github.com/EGRNEGR';

const failures = [];
const fail = (check, msg) => failures.push(`[${check}] ${msg}`);
const rel = (p) => path.relative(ROOT, p).split(path.sep).join('/');
const readText = (p) => { try { return fs.readFileSync(p, 'utf8'); } catch (e) { return null; } };

function walkFiles(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walkFiles(p, out); else out.push(p);
  }
  return out;
}

function walk(value, visit, keyPath = []) {
  if (value === null || value === undefined) return;
  if (Array.isArray(value)) { value.forEach((v, i) => walk(v, visit, keyPath.concat(i))); return; }
  if (typeof value === 'object') {
    for (const k of Object.keys(value)) walk(value[k], visit, keyPath.concat(k));
    return;
  }
  visit(value, keyPath);
}

const lastKey = (kp) => { for (let i = kp.length - 1; i >= 0; i--) if (typeof kp[i] === 'string') return kp[i]; return ''; };
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const isLocal = (u) => u && !/^(https?:|mailto:|tel:|data:|javascript:|#|\/\/)/i.test(u);

function loadContent() {
  const file = path.join(SITE, 'js', 'content.js');
  const code = readText(file);
  if (code === null) { fail(0, `нет файла ${rel(file)}`); return null; }
  const sandbox = { window: {}, console };
  sandbox.window.window = sandbox.window;
  try { vm.runInNewContext(code, sandbox, { filename: file }); } catch (e) { fail(0, `content.js не выполняется: ${e.message}`); return null; }
  const c = sandbox.window.GV && sandbox.window.GV.content;
  if (!c) { fail(0, 'content.js не определяет window.GV.content'); return null; }
  return c;
}

function loadMounts() {
  const file = path.join(SITE, 'js', 'page.js');
  const code = readText(file);
  if (code === null) { fail(5, `нет файла ${rel(file)}`); return null; }
  const document = { readyState: 'loading', addEventListener() {}, documentElement: {} };
  const sandbox = { console: { error() {}, log() {}, warn() {} }, document };
  sandbox.window = sandbox;
  sandbox.window.GV = {};
  try { vm.runInNewContext(code, sandbox, { filename: file }); } catch (e) { fail(5, `page.js не загружается: ${e.message}`); return null; }
  return sandbox.GV.page && sandbox.GV.page.mounts;
}

function checkLocalPath(u, from) {
  const clean = decodeURI(u.split('#')[0].split('?')[0]);
  if (!clean) return;
  if (clean.startsWith('/')) { fail(2, `абсолютный путь «${u}» в ${from}`); return; }
  if (!fs.existsSync(path.resolve(SITE, clean))) fail(2, `нет файла «${u}» (из ${from})`);
}

function parseMp4(buf) {
  const CONTAINERS = new Set(['moov', 'trak', 'mdia', 'minf', 'stbl']);
  const top = [], tracks = [];
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

function checkPaths(c) {
  const index = readText(path.join(SITE, 'index.html')) || '';
  let m;
  const re = /\b(?:src|href)\s*=\s*["']([^"']+)["']/g;
  while ((m = re.exec(index))) if (isLocal(m[1])) checkLocalPath(m[1], 'index.html');
  if (c) walk(c, (v, kp) => {
    if (typeof v !== 'string') return;
    const k = lastKey(kp);
    if ((k === 'src' || k === 'href' || k === 'img' || /^assets\//.test(v)) && isLocal(v)) checkLocalPath(v, `content.${kp.join('.')}`);
  });
  for (const css of walkFiles(path.join(SITE, 'css')).filter((f) => f.endsWith('.css'))) {
    const t = readText(css);
    const uRe = /url\(\s*["']?([^"')]+)["']?\s*\)/g;
    while ((m = uRe.exec(t))) {
      if (!isLocal(m[1])) continue;
      const p = path.resolve(path.dirname(css), decodeURI(m[1].split('#')[0].split('?')[0]));
      if (!fs.existsSync(p)) fail(2, `нет файла «${m[1]}» (url() в ${rel(css)})`);
    }
  }
  for (const f of ['assets/video/shift.scrub.mp4', 'assets/video/shift.scrub-m.mp4']) {
    const p = path.join(SITE, f);
    if (!fs.existsSync(p)) { fail(2, `нет видео ${f}`); continue; }
    const { top, tracks } = parseMp4(fs.readFileSync(p));
    if (top.indexOf('moov') < 0 || top.indexOf('moov') > top.indexOf('mdat')) fail(2, `${f}: moov не перед mdat`);
    if (tracks.some((t) => t.handler === 'soun')) fail(2, `${f}: есть звуковая дорожка`);
  }
}

function checkTextAndTypography(c) {
  const skip = new Set(['id', 'src', 'srcMobile', 'poster', 'posterAfter', 'href', 'img', 'version', 'commit', 'formula', 'repoUrl', 'tagUrl', 'branchUrl', 'readmeUrl', 'reportUrl', 'pilotUrl', 'licenseUrl', 'code', 'label']);
  walk(c, (v, kp) => {
    if (typeof v !== 'string') return;
    const where = `content.${kp.join('.')}`;
    const k = lastKey(kp);
    if (k !== 'formula' && v.includes('\u00B7')) fail(3, `средняя точка «·» в ${where}: «${v}»`);
    if (/ - /.test(v)) fail(8, `дефис вместо тире « — » в ${where}`);
    if (/--/.test(v)) fail(8, `«--» вместо тире в ${where}`);
    if (/окупаемость\s*5\s*мес/i.test(v)) fail(3, `запрещённое демо-утверждение «Окупаемость 5 мес.» в ${where}`);
    if (/\b(TODO|FIXME|TBD|lorem)\b/i.test(v)) fail(3, `заглушка в ${where}`);
    if (/^https?:/.test(v) && v !== REPO_PREFIX && !v.startsWith(REPO_PREFIX + '/')) fail(7, `ссылка не на GitHub EGRNEGR: ${where} = ${v}`);
    if (skip.has(k) || kp[0] === 'src') return;
    if (/(^|[^\w.-])\d+-\d+(?![\w.])/.test(v) && !/PI-10|ТЗ-КИП|20261127-01/.test(v)) fail(8, `диапазон через дефис в ${where}: «${v}»`);
  });

  (c.sections || []).forEach((s) => {
    if (s.lede) {
      if (!s.accent || !s.lede.includes(s.accent)) fail(7, `accent листа «${s.id}» не входит дословно в lede`);
    }
  });
  [['hero', 'line', 'lineAccent'], ['contact', 'lead', 'leadAccent']].forEach(([k, text, acc]) => {
    if (!c[k] || !String(c[k][text] || '').includes(c[k][acc])) fail(7, `${k}.${acc} не входит дословно в ${k}.${text}`);
  });
  if (!c.showcase || !Array.isArray(c.showcase.steps) || c.showcase.steps.length !== 12) fail(0, 'showcase.steps должен содержать 12 шагов');
}

function checkModulesAndSections(c, mounts) {
  const jsFiles = walkFiles(path.join(SITE, 'js')).filter((f) => f.endsWith('.js'));
  for (const f of jsFiles) {
    readText(f).split(/\r?\n/).forEach((line, i) => {
      if (/^\s*(import|export)\s+[\w{*'"]/.test(line)) fail(4, `import/export в ${rel(f)}:${i + 1}`);
      if (/type\s*=\s*["']module["']/.test(line)) fail(4, `type="module" в ${rel(f)}:${i + 1}`);
    });
  }
  const ids = (c.sections || []).map((s) => s.id).join(',');
  if (ids !== SECTION_IDS.join(',')) fail(5, `секции должны идти ${SECTION_IDS.join(', ')}, сейчас: ${ids}`);
  const index = readText(path.join(SITE, 'index.html')) || '';
  const scripts = [...index.matchAll(/<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/g)].map((m) => m[1]);
  for (const [secId, name] of Object.entries(mounts || {})) {
    const def = new RegExp(`GV\\.components\\.${escapeRe(String(name))}\\s*=`);
    if (!scripts.some((s) => isLocal(s) && def.test(readText(path.join(SITE, s)) || ''))) {
      fail(5, `модуль «${name}» для «${secId}» не подключён в index.html`);
    }
  }
  if (scripts[scripts.length - 1] !== 'js/page.js') fail(5, 'js/page.js должен подключаться последним');
}

function topLevelSplit(value) {
  const parts = [];
  let depth = 0, cur = '';
  for (const ch of value) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; } else cur += ch;
  }
  if (cur.trim()) parts.push(cur);
  return parts.map((p) => p.trim()).filter(Boolean);
}

const MOTION_OK = new Set(['transform', 'opacity', 'none']);
const PX_OK = new Set(['1px', '-1px', '-0.5px']);
function checkCss() {
  for (const f of walkFiles(path.join(SITE, 'css')).filter((x) => x.endsWith('.css'))) {
    const raw = readText(f) || '';
    const stripped = raw.replace(/\/\*[\s\S]*?\*\//g, '');
    let m;
    const tRe = /(^|[\s;{])(transition-property|transition)\s*:\s*([^;}]+)/g;
    while ((m = tRe.exec(stripped))) {
      topLevelSplit(m[3]).map((p) => p.split(/\s+/)[0]).filter(Boolean).forEach((name) => {
        if (!MOTION_OK.has(name)) fail(9, `transition по «${name}» в ${rel(f)}`);
      });
    }
    if (path.basename(f) !== 'fonts.css') {
      const lines = raw.replace(/\/\*[\s\S]*?\*\//g, (x) => x.replace(/[^\n]/g, ' '))
        .replace(/@media[^{]*/g, (x) => x.replace(/[^\n]/g, ' '))
        .split('\n');
      lines.forEach((line, i) => {
        const pRe = /(^|[^\w.-])(-?(?:\d+\.?\d*|\.\d+))px\b/g;
        while ((m = pRe.exec(line))) {
          const tok = m[2] + 'px';
          if (!PX_OK.has(tok)) fail(10, `${tok} в ${rel(f)}:${i + 1} — размеры в rem`);
        }
      });
    }
  }
}

const content = loadContent();
const mounts = loadMounts();
if (content) {
  checkPaths(content);
  checkTextAndTypography(content);
  checkModulesAndSections(content, mounts);
}
checkCss();

if (failures.length) {
  console.log(failures.join('\n'));
  console.log(`\nFAIL: нарушений ${failures.length}`);
  process.exit(1);
}
console.log(`OK: site/v5 проверен — 11 листов, ${Object.keys(mounts || {}).length} модулей, 12 шагов showcase, пути, медиа, типографика, движение и rem`);
process.exit(0);
