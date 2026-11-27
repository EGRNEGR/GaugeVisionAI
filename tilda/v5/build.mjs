/*
 * Сборка сайта v5 (site/v5 — «Сменный журнал обхода» с содержанием 3.0) для Tilda:
 * код <head> страницы и Vibe-блоки (tplid 1370).
 *
 *   node tilda/v5/build.mjs          → tilda/v5/dist/      (CDN Tilda для картинок, jsDelivr для шрифтов и видео)
 *   node tilda/v5/build.mjs --local  → tilda/v5/dist/local/ (локальные файлы /site/v5/assets/ для эмуляции)
 *
 * Основа: префикс .gvt и html.gvt-page (как в tilda/build.mjs) + esbuild, JSON-части GV.content
 * и предел 33 КБ на блок (как в tilda/v4/build.mjs). В <head> страницы — prepaint, @font-face,
 * правила уровня страницы (html.gvt-page, бумага, линовка, красное поле) и min-height:100vh
 * для пустого #gv-root (исключает сдвиг плашки «Made on Tilda»).
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const SITE = path.join(ROOT, 'site/v5');
const LOCAL = process.argv.includes('--local');
const OUT = path.join(HERE, 'dist', LOCAL ? 'local' : '');
const LIMIT = 33 * 1024;
const ASSETS = JSON.parse(fs.readFileSync(path.join(HERE, 'assets.json'), 'utf8'));
const STAMP = '<!-- GaugeVision AI 3.0 (журнал, v5) для Tilda: сгенерировано tilda/v5/build.mjs из site/v5. Правьте site/v5 и пересобирайте. -->';

const read = (rel) => fs.readFileSync(path.join(SITE, rel), 'utf8').replace(/\r\n/g, '\n');
const fail = (msg) => { console.error('ОШИБКА: ' + msg); process.exit(1); };
const kb = (s) => (Buffer.byteLength(s) / 1024).toFixed(1);

/* ---------- адреса файлов ---------- */

function assetUrl(kind, name) {
  if (LOCAL) return '/site/v5/assets/' + kind + '/' + name;
  if (kind === 'img') {
    if (!ASSETS.img[name]) fail('нет адреса CDN для assets/img/' + name);
    return ASSETS.img[name];
  }
  return ASSETS.cdn + kind + '/' + name;
}
const rewrite = (text) => text.replace(/(?:\.\.\/)?assets\/(img|video|fonts)\/([\w.-]+)/g, (m, kind, name) => {
  if (!fs.existsSync(path.join(SITE, 'assets', kind, name))) fail('ссылка на несуществующий файл ' + m);
  return assetUrl(kind, name);
});

/* ---------- CSS: разбор и префикс .gvt / html.gvt-page (из tilda/build.mjs) ---------- */

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

function pageSelector(sel) {
  if (sel === 'html') return ['html.gvt-page'];
  if (/^body\b/.test(sel)) return ['html.gvt-page ' + sel];
  if (sel === '::selection') return ['html.gvt-page ::selection'];
  if (/^::-webkit-scrollbar/.test(sel)) return ['html.gvt-page' + sel, 'html.gvt-page ' + sel];
  return null;
}

const ROOT_TYPE_PROPS = ['font-family', 'font-size', 'line-height', 'color', 'caret-color', 'font-kerning',
  'font-synthesis', 'text-rendering', '-webkit-font-smoothing'];

function declarations(body) {
  return body.replace(/\/\*[\s\S]*?\*\//g, '').split(';').map((d) => d.trim()).filter(Boolean);
}

function scopeCss(src, isBase) {
  const pageRules = [];
  const blockRules = [];
  function walk(nodes) {
    const localPage = [];
    const localBlock = [];
    for (const n of nodes) {
      if (n.t === 'stmt' || n.t === 'raw') {
        localBlock.push(n.t === 'raw' ? n.pre + '{' + n.body + '}' : n.v);
        continue;
      }
      if (n.t === 'group') {
        const inner = walk(n.kids);
        if (inner.page.length) localPage.push(n.pre + '{' + inner.page.join('\n') + '}');
        if (inner.block.length) localBlock.push(n.pre + '{' + inner.block.join('\n') + '}');
        continue;
      }
      const sels = splitSelectors(n.pre.replace(/\/\*[\s\S]*?\*\//g, ''));
      const pSels = [], bSels = [];
      for (const sel of sels) {
        const ps = isBase ? pageSelector(sel) : null;
        if (ps) {
          pSels.push(...ps);
          if (sel === 'body') {
            const keep = declarations(n.body).filter((d) => ROOT_TYPE_PROPS.includes(d.split(':')[0].trim()));
            localBlock.push('.gvt{' + keep.join(';') + '}');
          }
          continue;
        }
        bSels.push(...scopeSelector(sel));
      }
      if (pSels.length) localPage.push(pSels.join(',') + '{' + n.body + '}');
      if (bSels.length) localBlock.push(bSels.join(',') + '{' + n.body + '}');
    }
    return { page: localPage, block: localBlock };
  }
  const r = walk(parseCss(src));
  pageRules.push(...r.page);
  blockRules.push(...r.block);
  return { page: pageRules.join('\n'), block: blockRules.join('\n') };
}

/* ---------- esbuild ---------- */

function esbuild(code, loader) {
  return execFileSync('npx', ['-y', 'esbuild@0.24.0', '--minify', '--charset=utf8', '--legal-comments=none', '--loader=' + loader],
    { input: code, encoding: 'utf8', shell: true, maxBuffer: 64 * 1024 * 1024 }).trim();
}

function splitCss(css, max) {
  const rules = [];
  let depth = 0, start = 0, q = null;
  for (let i = 0; i < css.length; i++) {
    const c = css[i];
    if (q) { if (c === '\\') i++; else if (c === q) q = null; continue; }
    if (c === '"' || c === "'") q = c;
    else if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) { rules.push(css.slice(start, i + 1)); start = i + 1; } }
    else if (c === ';' && depth === 0) { rules.push(css.slice(start, i + 1)); start = i + 1; }
  }
  if (depth !== 0 || css.slice(start).trim()) fail('CSS не разобран до конца');
  const chunks = [''];
  for (const r of rules) {
    if (Buffer.byteLength(r) > max) fail('правило CSS длиннее предела: ' + r.slice(0, 80));
    if (Buffer.byteLength(chunks[chunks.length - 1] + r) > max) chunks.push('');
    chunks[chunks.length - 1] += r;
  }
  return chunks;
}

const safeScript = (code) => code.replace(/<\/script/gi, '<\\/script').replace(/<!--/g, '<\\!--');
const safeStyle = (code) => { if (/<\/style/i.test(code)) fail('</style> внутри CSS'); return code; };

/* ---------- CSS ---------- */

const indexHtml = read('index.html');
const cssFiles = [...indexHtml.matchAll(/<link rel="stylesheet" href="([^"]+)">/g)].map((m) => m[1]);
if (cssFiles[0] !== 'css/fonts.css') fail('первым должен идти css/fonts.css');
const fontsCss = esbuild(rewrite(read('css/fonts.css')), 'css');

const pageCssParts = [];
const blockCssParts = [];
for (const f of cssFiles.slice(1)) {
  const res = scopeCss(rewrite(read(f)), f === 'css/base.css');
  if (res.page) pageCssParts.push(res.page);
  if (res.block) blockCssParts.push(res.block);
}
if (!pageCssParts.length) fail('не найдены правила уровня страницы в base.css');

const pageCssMin = esbuild(pageCssParts.join('\n') +
  '\nhtml.gvt-page #gv-root:empty{min-height:100vh}' +
  "\n#allrecords[data-tilda-mode='edit'] .gvt{background-color:#E9EBE4}", 'css');
const siteCssMin = esbuild(blockCssParts.join('\n'), 'css');
const cssChunks = splitCss(siteCssMin, 30 * 1024);

/* ---------- контент ---------- */

const contentSrc = read('js/content.js');
const sandbox = { window: {} };
sandbox.window.window = sandbox.window;
vm.runInNewContext(contentSrc, sandbox);
const content = sandbox.window.GV.content;
const typoSrc = contentSrc.slice(contentSrc.indexOf('  var NBSP'), contentSrc.indexOf('  function walk'));
if (!/function typo\(s\)/.test(typoSrc)) fail('не найдена функция typo() в content.js');

const keys = Object.keys(content).filter((k) => k !== 'typo');
const contentScripts = [];
let cur = {};
const flush = () => {
  if (!Object.keys(cur).length) return;
  contentScripts.push({
    name: 'content:' + Object.keys(cur).join(','),
    code: '(function(){var GV=window.GV=window.GV||{};var c=GV.content=GV.content||{};var p=' +
      rewrite(JSON.stringify(cur)) + ';for(var k in p)c[k]=p[k];})();'
  });
  cur = {};
};
for (const k of keys) {
  const one = JSON.stringify({ [k]: content[k] });
  if (Buffer.byteLength(one) > 28 * 1024) fail('ключ content.' + k + ' больше 28 КБ');
  if (Buffer.byteLength(JSON.stringify({ ...cur, [k]: content[k] })) > 28 * 1024) flush();
  cur[k] = content[k];
}
flush();
contentScripts.push({
  name: 'content:typo',
  code: esbuild('(function(){var GV=window.GV;\n' + typoSrc + 'GV.content.typo=typo;})();', 'js')
});

/* ---------- модули ---------- */

const jsFiles = [...indexHtml.matchAll(/<script src="([^"]+)"><\/script>/g)].map((m) => m[1]);
if (jsFiles[0] !== 'js/content.js' || jsFiles[jsFiles.length - 1] !== 'js/page.js') fail('порядок скриптов: content.js первым, page.js последним');
const modules = jsFiles.slice(1).map((f) => ({ name: f, code: esbuild(rewrite(read(f)), 'js') }));

/* ---------- блоки ---------- */

const items = [
  ...cssChunks.map((c, i) => ({ name: 'css#' + (i + 1), html: '<style>' + safeStyle(c) + '</style>\n' })),
  ...contentScripts.map((s) => ({ name: s.name, html: '<script>' + safeScript(s.code) + '</script>\n' })),
  ...modules.slice(0, -1).map((s) => ({ name: s.name, html: '<script>' + safeScript(s.code) + '</script>\n' }))
];

const skip = indexHtml.match(/<a class="gv-skip"[^>]*>[^<]*<\/a>/)[0];
const noscript = indexHtml.match(/<noscript>[\s\S]*?<\/noscript>/)[0].replace(/\n\s*/g, '');
const tweaksEl = indexHtml.match(/<aside id="gv-tweaks"[^>]*><\/aside>/)[0];
const markup = '<div class="gvt">\n' + skip + '\n<div id="gv-root"></div>\n' + noscript + '\n' + tweaksEl + '\n</div>\n';
const pageJs = '<script>' + safeScript(modules[modules.length - 1].code) + '</script>\n';

const blocks = [{ items: [], html: STAMP + '\n' }];
for (const it of items) {
  if (Buffer.byteLength(it.html) > LIMIT - 512) fail(it.name + ' больше предела блока: ' + kb(it.html) + ' КБ');
  let b = blocks[blocks.length - 1];
  if (Buffer.byteLength(b.html + it.html) > LIMIT) { b = { items: [], html: STAMP + '\n' }; blocks.push(b); }
  b.items.push(it.name);
  b.html += it.html;
}
let last = blocks[blocks.length - 1];
if (Buffer.byteLength(last.html + markup + pageJs) > LIMIT) { last = { items: [], html: STAMP + '\n' }; blocks.push(last); }
last.items.unshift('markup');
last.items.push('js/page.js');
last.html = STAMP + '\n' + markup + last.html.slice(STAMP.length + 1) + pageJs;

/* ---------- код <head> страницы ---------- */

const prepaint = esbuild(`(function(){
  var d=document.documentElement;
  var editor=/(^|\\.)tilda\\.(ru|cc)$/.test(location.hostname)&&!/\\/preview\\//.test(location.pathname);
  if(editor)return;
  d.classList.add('gvt-page');
  d.lang='ru';
  var q=location.search;
  var on=/[?&]tweaks(=on|=1)?(&|$)/.test(q);
  var off=/[?&]tweaks=off(&|$)/.test(q);
  try{
    if(on)localStorage.setItem('gv.tweaks.on','1');
    if(off)localStorage.removeItem('gv.tweaks.on');
    if(localStorage.getItem('gv.tweaks.on')==='1')d.setAttribute('data-tweaks','on');
    var t=JSON.parse(localStorage.getItem('gv.tweaks')||'{}');
    if([0.9,1,1.1,1.25].indexOf(t.scale)>=0)d.style.setProperty('--ui-scale',String(t.scale));
    if(['ledger','graph','tracing'].indexOf(t.paper)>=0)d.setAttribute('data-paper',t.paper);
  }catch(e){if(on)d.setAttribute('data-tweaks','on');}
})();`, 'js');

const head = [
  STAMP,
  '<meta name="theme-color" content="#E9EBE4">',
  '<meta name="color-scheme" content="light">',
  '<link rel="preload" href="' + assetUrl('fonts', 'sofia-xcond-cyrillic.woff2') + '" as="font" type="font/woff2" crossorigin>',
  '<link rel="preload" href="' + assetUrl('fonts', 'martian-mono-cyrillic.woff2') + '" as="font" type="font/woff2" crossorigin>',
  '<script>' + safeScript(prepaint) + '</script>',
  '<style>' + fontsCss + '\n' + pageCssMin + '</style>'
].join('\n') + '\n';

/* ---------- запись ---------- */

fs.rmSync(path.join(OUT, 'blocks'), { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, 'blocks'), { recursive: true });
fs.writeFileSync(path.join(OUT, 'head.html'), head);
const md5 = (s) => crypto.createHash('md5').update(s).digest('hex');
const manifest = { head: { file: 'head.html', bytes: Buffer.byteLength(head), md5: md5(head) }, blocks: [] };
blocks.forEach((b, i) => {
  const file = 'blocks/' + String(i + 1).padStart(2, '0') + '.html';
  fs.writeFileSync(path.join(OUT, file), b.html);
  manifest.blocks.push({ file, bytes: Buffer.byteLength(b.html), md5: md5(b.html), items: b.items });
});
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');

const title = indexHtml.match(/<title>([^<]*)<\/title>/)[1];
const emuCss = LOCAL ? '/tilda/emu/' : '../../emu/';
fs.writeFileSync(path.join(OUT, 'emulation.html'), '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n' +
  '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>' + title + '</title>\n' +
  '<link rel="stylesheet" href="' + emuCss + 'tilda-grid-3.0.min.css">\n' +
  '<link rel="stylesheet" href="' + emuCss + 'tilda-blocks-base.css">\n' +
  head + '</head>\n<body class="t-body" style="margin:0;">\n<div id="allrecords" class="t-records" data-tilda-mode="published">\n' +
  blocks.map((b, i) => '<div id="rec' + (1000 + i) + '" class="r t-rec" data-record-type="1370" data-animationappear="off">\n<div class="t1370">\n' +
    b.html + '</div>\n</div>').join('\n') + '\n</div>\n</body>\n</html>\n');

console.log('OK' + (LOCAL ? ' (локальные файлы)' : '') + ': head ' + kb(head) + ' КБ; CSS ' + kb(siteCssMin) + ' КБ в ' + cssChunks.length +
  ' кусках; блоков ' + blocks.length + ': ' + manifest.blocks.map((m) => (m.bytes / 1024).toFixed(1)).join(', ') + ' КБ');
