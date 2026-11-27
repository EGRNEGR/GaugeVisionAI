/*
 * Сборка сайта v4 (site/v4) для Tilda: код <head> страницы и Vibe-блоки (tplid 1370).
 *
 *   node tilda/v4/build.mjs          → tilda/v4/dist/      (адреса CDN Tilda и jsDelivr из assets.json)
 *   node tilda/v4/build.mjs --local  → tilda/v4/dist/local/ (файлы из site/v4/assets; открыть emulation.html
 *                                      с корня рабочей копии: serve.mjs <корень> <порт>, /tilda/v4/dist/local/emulation.html)
 *
 * Устройство. Сайт v4 строится на клиенте: page.js монтирует 15 секций в #gv-root. На Tilda этот механизм не
 * меняется: блоки 01…N−1 несут только <style> и <script> (нулевая высота), последний блок — разметку #gv-root,
 * <noscript>, панель Tweaks и page.js. Весь CSS лежит в блоках: в редакторе Tilda код блока показывается текстом
 * и не применяется, поэтому стили сайта не задевают редактор. Код <head> страницы — только скрипт до первой
 * отрисовки, @font-face, цвет фона до загрузки блоков и высота пустого #gv-root (иначе плашка Tilda под
 * страницей сначала видна вверху экрана и сдвигается вниз, когда page.js построит секции).
 *
 * CSS склеивается в порядке site/v4/index.html, минифицируется esbuild целиком (каскад сохраняется) и режется
 * на границах правил верхнего уровня. content.js исполняется в Node: готовый GV.content (уже после типографа)
 * переносится как JSON частями по ключам, функция typo() — исходным текстом. Остальные модули — esbuild --minify
 * по одному, каждый в своём <script>. Предел блока — 33 КБ: так поле кода проходит Tilda MCP одним вызовом.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const SITE = path.join(ROOT, 'site/v4');
const LOCAL = process.argv.includes('--local');
const OUT = path.join(HERE, 'dist', LOCAL ? 'local' : '');
const LIMIT = 33 * 1024;
const ASSETS = JSON.parse(fs.readFileSync(path.join(HERE, 'assets.json'), 'utf8'));
const STAMP = '<!-- GaugeVision AI 3.0 для Tilda: сгенерировано tilda/v4/build.mjs из site/v4. Правьте site/v4 и пересобирайте. -->';

const read = (rel) => fs.readFileSync(path.join(SITE, rel), 'utf8').replace(/\r\n/g, '\n');
const fail = (msg) => { console.error('ОШИБКА: ' + msg); process.exit(1); };
const kb = (s) => (Buffer.byteLength(s) / 1024).toFixed(1);

/* ---------- адреса файлов ---------- */

function assetUrl(kind, name) {
  if (LOCAL) return '/site/v4/assets/' + kind + '/' + name;
  if (kind === 'img') {
    if (!ASSETS.img[name]) fail('нет адреса CDN для assets/img/' + name + ' (загрузить через upload_image, дописать assets.json)');
    return ASSETS.img[name];
  }
  return ASSETS.cdn + kind + '/' + name;
}
const rewrite = (text) => text.replace(/(?:\.\.\/)?assets\/(img|video|fonts)\/([\w.-]+)/g, (m, kind, name) => {
  if (!fs.existsSync(path.join(SITE, 'assets', kind, name))) fail('ссылка на несуществующий файл ' + m);
  return assetUrl(kind, name);
});

/* ---------- esbuild ---------- */

function esbuild(code, loader) {
  return execFileSync('npx', ['-y', 'esbuild@0.24.0', '--minify', '--charset=utf8', '--legal-comments=none', '--loader=' + loader],
    { input: code, encoding: 'utf8', shell: true, maxBuffer: 64 * 1024 * 1024 }).trim();
}

/* Минифицированный CSS → куски не больше max по границам правил верхнего уровня (учитываются строки и скобки) */
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
const siteCss = esbuild(rewrite(cssFiles.slice(1).map(read).join('\n')), 'css');
const cssChunks = splitCss(siteCss, 30 * 1024);

/* ---------- контент ---------- */

const contentSrc = read('js/content.js');
const sandbox = { window: {} };
vm.runInNewContext(contentSrc, sandbox);
const content = sandbox.window.GV.content;
const typoSrc = contentSrc.slice(contentSrc.indexOf('  var NBSP'), contentSrc.indexOf('  function walk'));
if (!/function typo\(s\)/.test(typoSrc)) fail('не найдена функция typo() в content.js');
const keys = Object.keys(content).filter((k) => k !== 'typo');
const contentScripts = [];
let cur = {};
const flush = () => {
  if (!Object.keys(cur).length) return;
  contentScripts.push({ name: 'content:' + Object.keys(cur).join(','), code:
    '(function(){var GV=window.GV=window.GV||{};var c=GV.content=GV.content||{};var p=' + rewrite(JSON.stringify(cur)) +
    ';for(var k in p)c[k]=p[k];})();' });
  cur = {};
};
for (const k of keys) {
  const one = JSON.stringify({ [k]: content[k] });
  if (Buffer.byteLength(one) > 28 * 1024) fail('ключ content.' + k + ' больше 28 КБ — разделить');
  if (Buffer.byteLength(JSON.stringify({ ...cur, [k]: content[k] })) > 28 * 1024) flush();
  cur[k] = content[k];
}
flush();
contentScripts.push({ name: 'content:typo', code: esbuild('(function(){var GV=window.GV;\n' + typoSrc + 'GV.content.typo=typo;})();', 'js') });

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
const markup = ['<div id="gv-root"></div>', indexHtml.match(/<noscript>[\s\S]*?<\/noscript>/)[0].replace(/\n\s*/g, ''),
  indexHtml.match(/<aside id="gv-tweaks"[^>]*><\/aside>/)[0]].join('\n') + '\n';
const pageJs = '<script>' + safeScript(modules[modules.length - 1].code) + '</script>\n';

const blocks = [{ items: [], html: STAMP + '\n' + skip + '\n' }];
for (const it of items) {
  if (Buffer.byteLength(it.html) > LIMIT - 512) fail(it.name + ' больше предела блока: ' + kb(it.html) + ' КБ');
  let b = blocks[blocks.length - 1];
  if (Buffer.byteLength(b.html + it.html) > LIMIT) { b = { items: [], html: STAMP + '\n' }; blocks.push(b); }
  b.items.push(it.name);
  b.html += it.html;
}
/* Разметка — в начало последнего блока: tweaks.js и page.js находят #gv-tweaks и #gv-root при исполнении */
let last = blocks[blocks.length - 1];
if (Buffer.byteLength(last.html + markup + pageJs) > LIMIT) { last = { items: [], html: STAMP + '\n' }; blocks.push(last); }
last.items.unshift('markup');
last.items.push('js/page.js');
last.html = STAMP + '\n' + markup + last.html.slice(STAMP.length + 1) + pageJs;

/* ---------- код <head> страницы ---------- */

const prepaint = esbuild(`(function () {
  var d = document.documentElement;
  var editor = /(^|\\.)tilda\\.(ru|cc)$/.test(location.hostname) && !/\\/preview\\//.test(location.pathname);
  if (editor) return;
  d.classList.add('gvt-page');
  d.lang = 'ru';
  d.setAttribute('data-font', 'manrope');
  d.setAttribute('data-ambient', 'blueprint');
  d.style.setProperty('--ui-scale', '1');
` + indexHtml.match(/\(function \(\) \{\s*var d = document\.documentElement;\s*var q = location\.search;([\s\S]*?)\}\)\(\);\s*<\/script>/)[1].replace(/^/, '  var q = location.search;') + '})();', 'js');
const head = [
  STAMP,
  '<meta name="theme-color" content="#070A0F">',
  '<meta name="color-scheme" content="dark">',
  '<link rel="preload" href="' + assetUrl('fonts', 'manrope-cyrillic-800.woff2') + '" as="font" type="font/woff2" crossorigin>',
  '<link rel="preload" href="' + assetUrl('img', 'poster.jpg') + '" as="image">',
  '<script>' + safeScript(prepaint) + '</script>',
  '<style>' + fontsCss + '\nhtml.gvt-page{background:#070A0F;color:#E8EDF3}html.gvt-page #gv-root:empty{min-height:100vh}</style>'
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

/* Эмуляция опубликованной страницы Tilda: стили Tilda (tilda/emu), обёртки записей, код <head> */
const title = indexHtml.match(/<title>([^<]*)<\/title>/)[1];
const emuCss = LOCAL ? '/tilda/emu/' : '../../emu/';
fs.writeFileSync(path.join(OUT, 'emulation.html'), '<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n' +
  '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>' + title + '</title>\n' +
  '<link rel="stylesheet" href="' + emuCss + 'tilda-grid-3.0.min.css">\n<link rel="stylesheet" href="' + emuCss + 'tilda-blocks-base.css">\n' +
  head + '</head>\n<body class="t-body" style="margin:0;">\n<div id="allrecords" class="t-records" data-tilda-mode="published">\n' +
  blocks.map((b, i) => '<div id="rec' + (1000 + i) + '" class="r t-rec" data-record-type="1370" data-animationappear="off">\n<div class="t1370">\n' +
    b.html + '</div>\n</div>').join('\n') + '\n</div>\n</body>\n</html>\n');

console.log('OK' + (LOCAL ? ' (локальные файлы)' : '') + ': head ' + kb(head) + ' КБ; CSS ' + kb(siteCss) + ' КБ в ' + cssChunks.length +
  ' кусках; блоков ' + blocks.length + ': ' + manifest.blocks.map((m) => (m.bytes / 1024).toFixed(1)).join(', ') + ' КБ');
