#!/usr/bin/env node
/*
 * Сборка версии для Tilda из site/ — единственного источника кода, текстов и стилей.
 *
 *   node tilda/build.mjs           → tilda/dist/head.html (код <head> страницы), blocks/NN-<id>.html (адреса файлов — CDN Tilda
 *                                    и jsDelivr из tilda/assets.json) и tilda/dist/emulation.html для проверки
 *   node tilda/build.mjs --local   → то же, но файлы из site/assets: эмуляция открывается без сети и без загрузки
 *
 * Что куда (README.md рядом):
 *   код <head> страницы — шрифты, общий CSS (токены, база, движение, каркас листа, прибор), CSS уровня страницы
 *                          под классом html.gvt-page, общие тексты и библиотека: util, motion, kit, сборщик страницы;
 *   блоки (Vibe, tplid 1370) — шапка, восемь листов (тексты листа + CSS + модуль), футер, панель Tweaks.
 * Каждое правило CSS получает префикс .gvt (корень любого блока): Tilda не задевает стили сайта, сайт — стили Tilda.
 * Порядок правил внутри файлов и порядок файлов сохраняется; ledger.css делится между листами 05, 07 и 08 по классам.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const SITE = path.join(ROOT, 'site');
const DIST = path.join(HERE, 'dist');
const LOCAL = process.argv.includes('--local');

// переводы строк — \n: часть исходников сохранена с \r\n, а Tilda и сверка после загрузки работают с \n
const lf = (s) => s.replace(/\r\n/g, '\n');
const read = (p) => lf(fs.readFileSync(path.join(SITE, p), 'utf8'));
const fail = (msg) => { console.error('build: ' + msg); process.exit(1); };

/* ---------- адреса файлов ---------- */

const assets = JSON.parse(fs.readFileSync(path.join(HERE, 'assets.json'), 'utf8'));
function assetUrl(rel) {
  // rel — путь от site/: assets/fonts/x.woff2
  if (LOCAL) return '../../../site/' + rel;
  const url = assets.files[rel];
  if (!url) fail('нет адреса на CDN для ' + rel + ' в tilda/assets.json');
  return url;
}

/* ---------- CSS: разбор и префикс ---------- */

function parseCss(src) {
  let i = 0;
  function skipString(q) {
    let j = i + 1;
    while (j < src.length && src[j] !== q) j += src[j] === '\\' ? 2 : 1;
    return j + 1;
  }
  function rawBody() {
    const start = i;
    let depth = 1;
    while (i < src.length && depth) {
      const ch = src[i];
      if (ch === '/' && src[i + 1] === '*') { i = src.indexOf('*/', i + 2) + 2; continue; }
      if (ch === '"' || ch === "'") { i = skipString(ch); continue; }
      if (ch === '{') depth++;
      if (ch === '}') depth--;
      i++;
    }
    return src.slice(start, i - 1);
  }
  function block() {
    const nodes = [];
    let buf = '';
    while (i < src.length) {
      const ch = src[i];
      if (ch === '/' && src[i + 1] === '*') {
        const j = src.indexOf('*/', i + 2) + 2;
        if (!buf.trim()) nodes.push({ t: 'comment', v: src.slice(i, j) });
        i = j;
        continue;
      }
      if (ch === '"' || ch === "'") { const j = skipString(ch); buf += src.slice(i, j); i = j; continue; }
      if (ch === '{') {
        const pre = buf.trim();
        buf = '';
        i++;
        if (/^@(media|supports|container|layer)\b/.test(pre)) nodes.push({ t: 'group', pre, kids: block() });
        else nodes.push({ t: pre.startsWith('@') ? 'raw' : 'rule', pre, body: rawBody() });
        continue;
      }
      if (ch === '}') { i++; return nodes; }
      if (ch === ';' && buf.trim().startsWith('@')) { nodes.push({ t: 'stmt', v: buf.trim() + ';' }); buf = ''; i++; continue; }
      buf += ch;
      i++;
    }
    if (buf.trim()) fail('хвост CSS без скобок: ' + buf.trim().slice(0, 60));
    return nodes;
  }
  return block();
}

function splitSelectors(pre) {
  const out = [];
  let depth = 0, cur = '';
  for (const ch of pre) {
    if (ch === '(' || ch === '[') depth++;
    if (ch === ')' || ch === ']') depth--;
    if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out.map((s) => s.replace(/\s+/g, ' '));
}

const HTML_RE = /^html((?:\[[^\]]*\]|\.[\w-]+|:[\w-]+(?:\([^)]*\))?)*)(\s.*)?$/;
function scopeSelector(sel) {
  if (sel === ':root') return [sel];
  const m = sel.match(HTML_RE);
  if (m) return m[2] ? ['html' + m[1] + ' .gvt' + m[2]] : [sel];
  if (sel === '*') return ['.gvt', '.gvt *'];
  const pseudo = sel.match(/^\*(::?(?:before|after))$/);
  if (pseudo) return ['.gvt' + pseudo[1], '.gvt *' + pseudo[1]];
  if (/^(body|::selection|::-webkit-scrollbar)/.test(sel)) fail('селектор уровня страницы вне base.css: ' + sel);
  return ['.gvt ' + sel];
}

/* Правила уровня страницы из base.css: включаются классом html.gvt-page (его не ставит редактор Tilda) */
function pageSelector(sel) {
  if (sel === 'html') return ['html.gvt-page'];
  if (/^body\b/.test(sel)) return ['html.gvt-page ' + sel];
  if (sel === '::selection') return ['html.gvt-page ::selection'];
  if (/^::-webkit-scrollbar/.test(sel)) return ['html.gvt-page' + sel, 'html.gvt-page ' + sel];
  return null;
}
const isPageSel = (sel) => pageSelector(sel) !== null;

/* Наследуемая типографика body — ещё и на корень каждого блока: в редакторе Tilda html.gvt-page нет */
const ROOT_TYPE_PROPS = ['font-family', 'font-size', 'line-height', 'color', 'caret-color', 'font-kerning',
  'font-synthesis', 'text-rendering', '-webkit-font-smoothing'];

function declarations(body) {
  return body.replace(/\/\*[\s\S]*?\*\//g, '').split(';').map((d) => d.trim()).filter(Boolean);
}

function indent(text, pad) {
  return text.split('\n').map((l) => (l.trim() ? pad + l : l)).join('\n');
}

function ruleText(sels, body) {
  return sels.join(',\n') + ' {' + body + '}';
}

/*
 * Собирает CSS файла в набор «владельцев»: owner(sel) → имя (head, page, metrics…) или null — владелец файла.
 * Комментарии идут к владельцу файла, группы @media повторяются у каждого владельца, у которого есть правила внутри.
 */
function transformCss(src, { fileOwner, owner = () => null, base = false, route = false }) {
  const outs = {};
  const push = (who, text) => { (outs[who] = outs[who] || []).push(text); };

  function walk(nodes, wrap) {
    const local = {};
    const add = (who, text) => { (local[who] = local[who] || []).push(text); };
    // route (файл делится между листами): комментарий идёт к владельцу следующего правила,
    // @keyframes — к владельцу предыдущего (в исходнике они стоят сразу после правила, которое их использует)
    let pending = [];
    let lastOwner = fileOwner;
    const flush = (who) => { pending.forEach((v) => add(who, v)); pending = []; };
    for (const n of nodes) {
      if (n.t === 'comment') { if (route) pending.push(n.v); else add(fileOwner, n.v); continue; }
      if (n.t === 'stmt' || n.t === 'raw') {
        if (/^@(import|charset)/.test(n.pre || n.v)) fail('@import/@charset не поддерживается');
        const who = route && n.t === 'raw' && /^@keyframes/.test(n.pre) ? lastOwner : fileOwner;
        flush(who);
        add(who, n.t === 'raw' ? n.pre + ' {' + n.body + '}' : n.v);
        continue;
      }
      if (n.t === 'group') {
        flush(fileOwner);
        const inner = walk(n.kids, true);
        for (const who of Object.keys(inner)) add(who, n.pre + ' {\n' + indent(inner[who].join('\n'), '  ') + '\n}');
        continue;
      }
      const sels = splitSelectors(n.pre.replace(/\/\*[\s\S]*?\*\//g, ''));
      const byOwner = {};
      for (const sel of sels) {
        if (base && isPageSel(sel)) {
          (byOwner.page = byOwner.page || []).push(...pageSelector(sel));
          if (sel === 'body') {
            const keep = declarations(n.body).filter((d) => ROOT_TYPE_PROPS.includes(d.split(':')[0].trim()));
            add(fileOwner, '.gvt {\n' + keep.map((d) => '  ' + d + ';').join('\n') + '\n}');
          }
          continue;
        }
        const who = owner(sel) || fileOwner;
        (byOwner[who] = byOwner[who] || []).push(...scopeSelector(sel));
      }
      const owners = Object.keys(byOwner);
      if (owners.length) { flush(owners[0]); lastOwner = owners[0]; }
      for (const who of owners) add(who, ruleText(byOwner[who], n.body));
    }
    flush(lastOwner);
    if (!wrap) for (const who of Object.keys(local)) push(who, local[who].join('\n'));
    return local;
  }
  walk(parseCss(src), false);
  const res = {};
  for (const who of Object.keys(outs)) res[who] = outs[who].join('\n');
  return res;
}

/* ledger.css: протокол — лист 05, компромиссы, среда, «не проверено», план — лист 07, сдача смены — лист 08 */
// класс-корень БЭМ: за ним __элемент, --модификатор или конец имени (.gv-env не путается с .gv-envwrap)
const END = '(?=__|--|[^\\w-]|$)';
const LEDGER_OWNERS = [
  [new RegExp('^\\.gv-(proto)' + END + '|^\\.gv-sheet--metrics' + END), 'metrics'],
  [new RegExp('^\\.gv-(trade|env|envwrap|filter|plan|untested|h3)' + END + '|^\\.gv-sheet--limits' + END), 'limits'],
  [new RegExp('^\\.gv-close' + END + '|^\\.gv-sheet--contact' + END), 'contact']
];
function ledgerOwner(sel) {
  for (const [re, who] of LEDGER_OWNERS) if (re.test(sel)) return who;
  fail('ledger.css: правило без листа-владельца: ' + sel);
}

/* шрифты: url('../assets/…') → адрес CDN */
function fontsCss() {
  return read('css/fonts.css').replace(/url\('\.\.\/(assets\/fonts\/[^']+)'\)/g, (m, rel) => "url('" + assetUrl(rel) + "')");
}

/* ---------- тексты ---------- */

function loadContent() {
  const sandbox = { window: {} };
  sandbox.window.window = sandbox.window;
  vm.runInNewContext(read('js/content.js'), sandbox.window);
  return sandbox.window.GV.content;
}

const SHARED_KEYS = ['meta', 'sections', 'labels', 'calibration', 'reading'];
const SHEETS = [
  { id: 'hero', keys: ['hero'], js: 'components/journal.js', css: ['hero.css'] },
  { id: 'compare', keys: ['compare'], js: 'components/shift.js', css: ['shift.css'] },
  { id: 'reading', keys: [], js: 'components/precision-dial.js', css: ['dial.css'] },
  { id: 'pipeline', keys: ['pipeline', 'pipelineCards', 'pipelineTotal', 'pipelineFrame'], js: 'components/operations.js', css: ['operations.css'] },
  { id: 'metrics', keys: ['metrics', 'metricsColumns', 'metricsAxis'], js: 'components/metrics.js', css: [] },
  { id: 'architecture', keys: ['architecture'], js: 'components/architecture.js', css: ['schema.css'] },
  { id: 'limits', keys: ['tradeoffs', 'limits', 'untested', 'roadmap'], js: 'components/limits.js', css: [] },
  { id: 'contact', keys: ['contact'], js: 'components/contact.js', css: [] }
];

function json(value) {
  return JSON.stringify(value, null, 2)
    .replace(/[<>&\u00a0\u2000-\u200f\u2028\u2029\u202f\u2060\ufeff]/g, (ch) => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'));
}

function contentScript(content, keys, title) {
  const part = {};
  for (const k of keys) part[k] = content[k];
  return '/* ' + title + ' — данные из site/js/content.js после типографа */\n' +
    '(function () {\n  var GV = (window.GV = window.GV || {});\n  var c = (GV.content = GV.content || {});\n' +
    '  var part = ' + indent(json(part), '  ').trimStart() + ';\n' +
    '  Object.keys(part).forEach(function (k) { c[k] = part[k]; });\n})();';
}

function guardScript(code, file) {
  if (/<\/script/i.test(code)) fail(file + ': внутри есть </script');
  return code;
}

/* ---------- сборка ---------- */

const content = loadContent();
const covered = new Set([...SHARED_KEYS, ...SHEETS.flatMap((s) => s.keys)]);
for (const k of Object.keys(content)) if (!covered.has(k)) fail('ключ GV.content.' + k + ' не попал ни в один блок');
if (content.sections.map((s) => s.id).join() !== SHEETS.map((s) => s.id).join()) fail('порядок листов в content.sections изменился');

// адреса ролика и кадров листа 02
const video = content.compare.video;
for (const k of ['src', 'srcMobile', 'poster', 'posterAfter']) video[k] = assetUrl(video[k]);

// CSS: голова — tokens, base, motion, page, gauge (порядок site/index.html); листы — свои файлы
const css = { head: [], page: [] };
const addCss = (res) => { for (const who of Object.keys(res)) (css[who] = css[who] || []).push(res[who]); };
addCss(transformCss(read('css/tokens.css'), { fileOwner: 'head' }));
addCss(transformCss(read('css/base.css'), { fileOwner: 'head', base: true }));
for (const f of ['motion.css', 'page.css', 'gauge.css']) addCss(transformCss(read('css/' + f), { fileOwner: 'head' }));
for (const s of SHEETS) for (const f of s.css) addCss(transformCss(read('css/' + f), { fileOwner: s.id }));
addCss(transformCss(read('css/ledger.css'), { fileOwner: 'metrics', owner: ledgerOwner, route: true }));
addCss(transformCss(read('css/tweaks.css'), { fileOwner: 'tweaks' }));
if (!css.page.length) fail('не найдены правила уровня страницы в base.css');

const STAMP = 'GaugeVision AI для Tilda: сгенерировано tilda/build.mjs из site/. Правьте site/ и пересобирайте.';

/*
 * Раскладка под ограничения Tilda: код передаётся в MCP текстом одного вызова, поэтому каждое поле ≤ ~50 КБ;
 * код <head> проекта Tilda сохраняет только у подтверждённого аккаунта, поэтому общий код — в <head> страницы:
 *   код <head> страницы — мета, скрипт до первой отрисовки, шрифты и весь общий CSS;
 *   блок 01 lib (невидимый) — общие тексты, util и motion;
 *   блок 02 top — kit и сборщик страницы GV.tilda, ссылка «К содержанию», <noscript>; шапку и ярлыки строит GV.tilda.
 * Оба первых блока должны оставаться первыми: их скрипты нужны всем листам.
 */
const head = [
  '<!-- ' + STAMP + ' -->',
  '<meta name="theme-color" content="#E9EBE4">',
  '<meta name="color-scheme" content="light">',
  '<script>\n' + lf(fs.readFileSync(path.join(HERE, 'src/prepaint.js'), 'utf8')) + '</script>',
  '<style>\n' + fontsCss() + '</style>',
  '<style>\n' + css.head.join('\n') + '\n' +
    '/* Tilda: в редакторе нет бумаги страницы — блок сам кладёт цвет бумаги под лист */\n' +
    "#allrecords[data-tilda-mode='edit'] .gvt { background-color: var(--paper); }\n</style>",
  '<style>\n/* Уровень страницы (site/css/base.css): только с классом html.gvt-page, редактор Tilda его не получает */\n' +
    css.page.join('\n') + '\n</style>'
].join('\n');

const libJs = [
  contentScript(content, SHARED_KEYS, 'Общие тексты: шапка, листы, подписи, калибровка, показание'),
  read('js/util.js'), read('js/motion.js')
].map((code, i) => guardScript(code, 'lib#' + i)).join('\n');

const BOOT = 'window.GV && GV.tilda && GV.tilda.boot();';
const blocks = [];
const noscript = read('index.html').match(/<noscript>[\s\S]*?<\/noscript>/)[0];
const skip = read('index.html').match(/<a class="gv-skip"[^>]*>[^<]*<\/a>/)[0];

blocks.push({ id: 'lib', anchor: '', html:
  '<!-- ' + STAMP + ' -->\n<!-- Блок 01 всегда первый и невидим: общие тексты и библиотека util, motion -->\n' +
  '<script>\n' + libJs + '\n</script>\n' });

blocks.push({ id: 'top', anchor: '', html:
  '<!-- ' + STAMP + ' -->\n<!-- Блок 02 всегда второй: kit и сборщик страницы GV.tilda; шапку бланка и ярлыки листов строит GV.tilda -->\n' +
  '<div class="gvt" data-gv-block="top">\n  ' + skip + '\n  ' + noscript.replace(/\n/g, '\n  ') + '\n</div>\n' +
  '<script>\n' + guardScript(read('js/components/kit.js'), 'kit.js') + '\n' +
  guardScript(lf(fs.readFileSync(path.join(HERE, 'src/runtime.js'), 'utf8')), 'runtime.js') + '\n' + BOOT + '\n</script>\n' });

for (const s of SHEETS) {
  const sec = content.sections.find((x) => x.id === s.id);
  const attrs = s.id === 'hero' ? ' id="gv-main" tabindex="-1"' : '';
  const js = [
    s.keys.length ? contentScript(content, s.keys, 'Тексты листа ' + sec.index) : '',
    guardScript(read('js/' + s.js), s.js),
    BOOT
  ].filter(Boolean).join('\n');
  blocks.push({ id: s.id, anchor: s.id, html:
    '<!-- ' + STAMP + ' -->\n<!-- Лист ' + sec.index + ' «' + sec.nav + '»: тексты, стили и модуль ' + s.js + ' -->\n' +
    '<div class="gvt" data-gv-block="' + s.id + '"' + attrs + '></div>\n' +
    (css[s.id] ? '<style>\n' + css[s.id].join('\n') + '\n</style>\n' : '') +
    '<script>\n' + js + '\n</script>\n' });
}

blocks.push({ id: 'foot', anchor: '', html:
  '<!-- ' + STAMP + ' -->\n<!-- Футер строит GV.tilda (блок 02) -->\n' +
  '<div class="gvt" data-gv-block="foot"></div>\n<script>\n' + BOOT + '\n</script>\n' });

blocks.push({ id: 'tweaks', anchor: '', html:
  '<!-- ' + STAMP + ' -->\n<!-- Панель Tweaks: масштаб и сорт бумаги, видит только автор (адрес с ?tweaks) -->\n' +
  '<div class="gvt" data-gv-block="tweaks">\n  <aside id="gv-tweaks" aria-label="Настройки внешнего вида"></aside>\n</div>\n' +
  '<style>\n' + css.tweaks.join('\n') + '\n</style>\n' +
  '<script>\n' + guardScript(read('js/tweaks.js'), 'tweaks.js') + '\n' + BOOT + '\n</script>\n' });

for (const who of Object.keys(css)) {
  if (!['head', 'page', 'tweaks'].includes(who) && !SHEETS.some((s) => s.id === who)) fail('CSS без блока: ' + who);
}

/* ---------- запись ---------- */

const out = LOCAL ? path.join(DIST, 'local') : DIST;
fs.rmSync(path.join(out, 'blocks'), { recursive: true, force: true });
fs.mkdirSync(path.join(out, 'blocks'), { recursive: true });
for (const f of ['head-project.html', 'head-page.html']) fs.rmSync(path.join(out, f), { force: true });
fs.writeFileSync(path.join(out, 'head.html'), head);
const manifest = [];
blocks.forEach((b, i) => {
  const name = String(i + 1).padStart(2, '0') + '-' + b.id + '.html';
  fs.writeFileSync(path.join(out, 'blocks', name), b.html);
  manifest.push({ file: 'blocks/' + name, id: b.id, anchor: b.anchor, bytes: Buffer.byteLength(b.html) });
});
fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify({ head: { file: 'head.html', bytes: Buffer.byteLength(head) }, blocks: manifest }, null, 2));

// Эмуляция страницы Tilda: стили Tilda, обёртки записей, код <head> — для сравнения с site/index.html
const title = read('index.html').match(/<title>([^<]*)<\/title>/)[1];
const emu = '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n' +
  '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>' + title + '</title>\n' +
  '<link rel="stylesheet" href="' + (LOCAL ? '../../emu/' : '../emu/') + 'tilda-grid-3.0.min.css">\n' +
  '<link rel="stylesheet" href="' + (LOCAL ? '../../emu/' : '../emu/') + 'tilda-blocks-base.css">\n' +
  head + '\n</head>\n<body class="t-body" style="margin:0;">\n' +
  '<div id="allrecords" class="t-records" data-tilda-mode="published" data-tilda-page-alias="emulation">\n' +
  blocks.map((b, i) => '<div id="rec' + (1000 + i) + '" class="r t-rec" style=" " data-record-type="1370">\n' +
    (b.anchor ? '<a name="' + b.anchor + '" style="font-size:0;"></a>\n' : '') +
    '<div class="t1370">\n' + b.html + '</div>\n</div>').join('\n') +
  '\n</div>\n</body>\n</html>\n';
fs.writeFileSync(path.join(out, 'emulation.html'), emu);

console.log('OK: head страницы ' + (Buffer.byteLength(head) / 1024).toFixed(1) + ' КБ, блоков ' + blocks.length + ': ' +
  manifest.map((m) => m.id + ' ' + (m.bytes / 1024).toFixed(1)).join(', ') + ' КБ' + (LOCAL ? ' (локальные файлы)' : ''));
