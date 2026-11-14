# Заметки по коду лендинга `site/` (срез на сейчас, вариант B в центре)

Всё ниже — по коду как он есть. Оценок нет. Корень — worktree `gaugevision-dial`.

## 1. Карта файлов `site/`

- `index.html` — оболочка: `<html lang="ru" data-font="auto" data-bg="graphite" data-media="shots" data-variant="a">`; inline-скрипт в `<head>` до отрисовки ставит `data-font|bg|media` и `--ui-scale` из localStorage `gv.tweaks`, `data-variant` из `?v=` или `gv.variant` (regexp `^[a-z]$`, без проверки существования); тело: `a.gv-skip`, `nav#gv-studio`, `main#gv-root[tabindex=-1]`, `noscript .gv-noscript`, `aside#gv-tweaks`, скрипты.
- Порядок стилей: `fonts.css` → `tokens.css` → `base.css` → `components.css` → `variant-a.css` → `variant-b.css` → `variant-c.css` → `tweaks.css`.
- Порядок скриптов (классические `<script src>`, без модулей): `js/content.js` → `js/util.js` → `js/components/kit.js` → `hero-stage.js` → `metrics.js` → `pipeline.js` → `compare.js` → `architecture.js` → `limits.js` → `js/variants/a.js` → `b.js` → `c.js` → `js/tweaks.js` → `js/app.js`.
- `js/content.js` — `GV.content` (данные + типограф в конце файла).
- `js/util.js` — `GV.util`.
- `js/components/kit.js` — `GV.kit`: расчёты калибровки, `scope`, `crop`, `dial`, иконки, `sectionNav`.
- `js/components/{hero-stage,metrics,pipeline,compare,architecture,limits}.js` — `GV.components.{heroStage,metrics,pipeline,compare,architecture,limits}`.
- `js/variants/{a,b,c}.js` — `GV.variants.{a,b,c} = { id, label, render }`; label: A «Пульт», B «Циферблат», C «Протокол» (по ADR 0005/architecture.md; у B в коде `label: 'Циферблат'`).
- `js/tweaks.js` — `GV.tweaks` (панель Tweaks).
- `js/app.js` — `GV.app` (роутер вариантов, студийная панель, запасная страница `renderShell`).
- `css/fonts.css` — 61 `@font-face` (`font-display: swap`, `unicode-range`), локальные woff2: Manrope (400/500/700/800), Onest (400/500/700/800), IBM Plex Sans (400/500/700), IBM Plex Mono (400/500/600), JetBrains Mono (400/500/700); подмножества cyrillic/latin/latin-ext (+greek у Manrope, Plex Sans, JetBrains).
- `css/tokens.css` — токены; `css/base.css` — reset, утилиты, `#gv-studio`, `.gv-shell`, `.gv-noscript`, `.gv-button`; `css/components.css` — раскладки всех компонентов (2730 строк); `css/variant-{a,b,c}.css` — под `[data-variant="x"]`; `css/tweaks.css` — панель Tweaks (`.gv-tweaks*`).
- `assets/smartphone-client.png`, `assets/dashboard-real.png` — скриншоты для hero и пары «Было → Стало»; `assets/img/favicon.svg`; `assets/fonts/*.woff2`.
- `design-system.md` — таблица токенов и контраста (исключён из проверки запрещённых слов).
- `tests/check.js`, `tests/components.test.js` — единственные автотесты.
- Вне `site/`: `docs/gemini_art/gaugevision_hero.jpg`, `docs/gemini_video/*`, `references/*` — на сайт не подключены (grep по `site/` на `gemini`/`references` пуст).

## 2. Глобальные имена и контракты

### 2.1 `GV.content` (ключи верхнего уровня)

`meta, sections, hero, coverage, metrics, metricsNote, pipeline, calibration, ema, compare, architecture, tradeoffs, limits, untested, roadmap, contact, labels, screenshotFacts`. Каждая строка (кроме ключей `id, src, href, file, source, formula, roi, repoUrl, licenseUrl, pdfUrl, authorUrl`) проходит `typo()`: NBSP между числом и единицей, перед « — », после №/≈/±/≤/≥/×, в разрядах тысяч.

- `meta`: `name, tagline, repoUrl, licenseUrl, pdfUrl, authorUrl, author, track, trackShort, copyright, version`. `REPO = https://github.com/EGRNEGR/GaugeVisionAI`.
- `sections[]` (7, одинаковы везде): `{ id, index, nav, title, lead? }`. id по порядку: `hero 01 «Суть»`, `metrics 02 «Замеры»`, `pipeline 03 «Конвейер»`, `compare 04 «Было → Стало»`, `architecture 05 «Архитектура»`, `limits 06 «Ограничения»`, `contact 07 «GitHub»`. `lead` есть у metrics, pipeline, compare, architecture, limits; нет у hero и contact.
- `hero`: `eyebrow, title, lead, chain{before[3], after[3]}, ctaPrimary{label:'Код на GitHub', href}, ctaSecondary{label:'Смотреть демо', target:'#hero-stage'}, stage`.
  - `hero.stage`: `rawLabel, recognizedLabel, caption, captionSchematic, raw{src,alt,crop{x,y,w,h}}, recognized{src,alt,crop}, readout, labels`.
  - `raw.src='assets/smartphone-client.png'` crop `{x:0.12,y:0.228,w:0.76,h:0.394}`; `recognized.src='assets/dashboard-real.png'` crop `{x:0.66,y:0.217,w:0.307,h:0.451}`.
  - `readout`: `device:'Тягонапоромер топки котла №1', value:4.74, unit:'кПа', theta:275.2, conf:0.92, roi:'yolo+ellipse', latencyMs:71.3`.
  - `labels`: `device, value, theta, conf, roi, latency`.
- `coverage`: `classes:6, units:17, types[{id,label,devices,units}] (6), sources[5]`.
- `metrics[]` (10): `{ id, group('quality'|'speed'|'scale'), value, valueTo?, digits, display, unit, label, condition, kind('measured'|'calculated') }`. id: `scale-error 0,38 %`, `infer-gpu 7,2`, `pipeline-latency 30–100`, `map50 90,1`, `phone-stream 3–4`, `bench-25 100 к/с`, `infer-cpu 29`, `recall-precision '1,00 / 1,00' (unit '')`, `scale-50 200 (calculated)`, `scale-100 400 (calculated)`. `metricsNote` — строка.
- `pipeline[]` (9, `index` '00'..'08'): `{ id, index, title, short, what, params[{name,value,note}], formula, file, aspect }`. id: `capture, locate, normalize, light, needle, calibrate, stabilize, setpoints, output`. Titles: Захват, Локализация, Нормализация, Свет и контраст, Вектор стрелки, Калибровка, Стабилизация, Уставки, Выдача.
- `calibration`: `thetaMin:135, thetaMax:45, vMin:0, vMax:10, unit:'МПа', direction:'CW', span:270, clamp:0.05, setpoints{LL:1,L:2,H:8,HH:9}, barPerMpa:10, formula, zones[{id:'LL'|'L'|'NORMA'|'H'|'HH', label, status:'alert'|'warning'|'normal', text}], sliderLabel:'Угол стрелки θ', caption`.
- `ema`: `alpha:0.25, minConfidence:0.25, formula, caption, toggleLabel:'Вибрация', legendRaw, legendEma`.
- `compare`: `before{title, points[4], cost{value,unit,note}}`, `after{…}`, `saving{value:'−89 %', label}`, `savingNote`, `pair{rawLabel, recognizedLabel}`, `timeline{caption, shiftHours:12, rounds:[0,12], deviationHour:5, roundLabel, deviationLabel, beforeLabel, afterLabel, beforeText, afterText}`.
- `architecture`: `nodes[12]{id,label,sub,group('source'|'server'|'storage'|'client'|'service'),file?}`, `edges[12]{from,to,label}`, `groups{source,server,storage,client,service}`, `stack[12]{name,version}`, `boundaryLabel`.
- `tradeoffs[]` (7): `{ id, chose, cost, why, source }` (id: yolo-nano, affine, ema, process-fps, confidence, local, sqlite).
- `limits[]` (5): `{ id, condition, risk, response, note?, status('done'|'partial') }` (id: glare, vibration, angle, dirt, network). `untested{title,text}`.
- `roadmap[]` (3): `{ index, title, status('done'|'planned'), items[] }`.
- `contact`: `title, text, links[{id,label,href,primary?}]` (repo primary, pdf, license, author).
- `labels`: `status{done,partial,planned}, kind{measured,calculated}, level{normal,warning,alert}, filterAll, tradeoffsTitle, tradeoffsLead, limitsTitle, chose, cost, why, source, condition, risk, response, params, formula, file, aspect, roadmapTitle, stackTitle, units{mpa,bar}, license`.
- `screenshotFacts` (check.js не сверяет): `dashboard{header, alarm, devices[3]{name,value,unit,level,link,theta,conf,processMs,roi,setpoints}}`, `calibrationWindow{source,vMin,thetaMin,vMax,thetaMax,direction,theta:253.4,conf,computedValue,computedNote}`, `phone{device,value,unit,fps,frameKb,format,resolution,status}`. `pipeline.js` берёт из него `calibrationWindow.theta` как стартовый угол слайдера.
- Для B «final/github» = `sections[6]` + `contact`; «dials/demo-кадры» = `hero.stage` (raw/recognized/readout/labels) + `calibration` (дуга).

### 2.2 `GV.util` (`js/util.js`)

- `formatNumber(n, digits) → string` — ru-RU, запятая, NBSP в разрядах, минус `−`; `digits` undefined → до 3 знаков.
- `prefersReducedMotion() → bool`.
- `onVisible(el, cb(isVisible, entry), {once, threshold=0.15, rootMargin}) → unsubscribe` (без IntersectionObserver вызывает `cb(true,null)`).
- `h(tag, attrs, ...children) → HTMLElement`; attrs-ключи: `on{type:fn}`, `html`, `text`, `class` (строка или массив), `style` (объект, `--var` через setProperty), `dataset`, `true`→пустой атрибут, `false/null/undefined` пропускаются.
- `svg(tag, attrs, ...children) → SVGElement` (то же).
- `rovingTabs(listEl, {onSelect(i, el), selector='[role="tab"]', attr='aria-selected'|'aria-pressed', orientation='horizontal'|'vertical'|'both', initial}) → { select(i), index(), destroy() }`. `onSelect` вызывается синхронно из конструктора (до возврата объекта).
- `uid(prefix) → 'prefix-N'`.

### 2.3 `GV.kit` (`js/components/kit.js`)

Чистые (доступны и без DOM): `angleToValue(theta, calib)`, `valueToAngle(value, calib)`, `fraction(value, calib)`, `toBar(value, calib)`, `zoneOf(value, setpoints) → 'LL'|'L'|'NORMA'|'H'|'HH'`, `levelOf(value, setpoints) → 'alert'|'warning'|'normal'`, `emaStep(prev, value, alpha)`, `mod(a, n)`, `NBSP` (литерал U+00A0). `calib` по умолчанию — `GV.content.calibration`.

DOM (только при `document` и `GV.util`):
- `scope() → { on(target,type,fn,opts), add(fn), timeout(fn,ms)→cancel, interval(fn,ms)→stop, frame(duration, step(t), done)→cancel, observe(unsubscribe), destroy() }`.
- `pick(value, allowed)` — значение из списка или первый элемент.
- `media() → 'shots'|'schematic'` (читает `html[data-media]`); `onTweaks(scope, cb(state))` — слушает `document` `gv:tweaks`.
- `crop(media{src,alt,crop}, className) → div.gv-crop` (img `.gv-crop__img` шириной `100%/w`, `translate(-x,-y)`, `--crop-ar` пересчитывается по naturalWidth/Height; классы `is-loaded`, `is-broken`).
- `dial(opts{theta, overlay, zones, title, thetaLabel, valueLabel, roi, className, numbers, calib}) → <svg class="gv-dial …" viewBox="0 0 200 200">`: `bezel` r80, `face` r72, дуги зон `gv-dial__zone--alert|warning|normal` (если `zones`), `gv-dial__scale`, 21 риска `gv-dial__tick[--major]`, цифры `gv-dial__num` (если `numbers !== false`), стрелка `g.gv-dial__needle` (rotate θ вокруг 100 100), `gv-dial__hub`, оверлей `g.gv-dial__overlay` (`roi` эллипс, `ref`, `theta`, `vector`, `arrow`, `label`, `label--roi`, `value`).
- `setNeedle(svgEl, theta)`; `arcPath(cx, cy, r, a0, a1) → 'M… A…'` (по часовой, экранные координаты, 0° = «3 часа»); `polar(cx, cy, r, deg) → [x,y]`.
- `icon(name) → svg` (`external`, `arrow`, `right`, `github`; неизвестное → `right`); `extLink(attrs, ...children) → <a target=_blank rel=noopener>`.
- `scrollToStage(id='hero-stage') → bool` (scrollIntoView + focus); `demoLink(label, className) → <a href="#hero-stage">` + иконка `arrow`.
- `sectionNav(scope, { container, links{id:<a>}, ids[], rootMargin='-35% 0px -55% 0px', keepLast, onChange(id|null) }) → { setCurrent(id|null) }` — клик по `a[href^="#"]` внутри `container`: smooth-scroll (auto при reduced motion), `tabindex=-1` и focus на секции; IntersectionObserver ставит `aria-current="true"` на ссылку первой из `ids` в полосе.

### 2.4 Компоненты: `GV.components.<name> = { mount(el, options) → {destroy(), …}, layouts[] }`

Неизвестный `layout` → первый из списка (`kit.pick`). `destroy()` снимает scope и удаляет корень из DOM.
- `heroStage` — `layouts ['framed','dial','sheet']`. Опции: `{ layout }`. Корень `div.gv-hero-stage.gv-hero-stage--<layout>#hero-stage[tabindex=-1][role=region][data-state=raw|recognized][data-media-mode]`. Внутри: `.gv-hero-stage__bar` (`__device` + `__toggle` с двумя `button.gv-hero-stage__mode[data-mode]`, `aria-pressed`, через `rovingTabs`), `.gv-hero-stage__body` = `.gv-hero-stage__viewport` (`__layer--raw`, `__layer--recognized`, `__scan`) + `dl.gv-hero-stage__readout` (5 строк `__row[data-key=value|theta|conf|roi|latency]`, `__val-live`/`__val-empty`), `p.gv-hero-stage__caption`, `p.gv-visually-hidden[aria-live]`. Режим `shots`: `kit.crop(stage.raw|recognized, 'gv-hero-stage__shot')`; `schematic`: два `kit.dial({numbers:false, theta:ro.theta, …})` (второй с `overlay`, `roi`, `thetaLabel`, `valueLabel`). Автопереход в `recognized` через 1600 мс после появления на 50 % экрана, если не трогали и нет reduced motion; `SCAN_MS=600`, класс `is-scanning`. Возврат: `{ destroy, setState('raw'|'recognized') }`.
- `metrics` — `['strip','dial','table']`. Опции `{ layout, ids?[], note? (false скрывает) }`. `dial`/`strip`: `div.gv-metrics.gv-metrics--<layout> > dl.gv-metrics__list > div.gv-metrics__item[data-kind][data-group]` с `dt.__label`, `dd.__figure` (`.gv-metrics__digits[aria-hidden]`, `.gv-visually-hidden` с итогом, `.gv-metrics__unit`), `dd.__condition`, `dd.__meta` (`__index` `/01`, `__kind[data-kind]`). `--long` на digits при `display.length > 7`. Счётчик до 1100 мс при 30 % видимости, только визуальный слой, не при reduced motion. `p.gv-metrics__note` с `metricsNote`. Возврат `{ destroy }`.
- `pipeline` — `['rail','arc','timeline']`. Опции `{ layout, initial?: id }`. Корень `div.gv-pipeline.gv-pipeline--<layout>[data-current]` (`--progress`), `div.gv-pipeline__track` (+ для `arc` svg `.gv-pipeline__arc` с `arc-scale` 135→45, 49 рисок `arc-tick[--major]` каждая 6-я, `g.gv-pipeline__arc-needle` rotate по `135 + i*270/8`; для `rail` `span.gv-pipeline__rail-line`) + `div[role=tablist].gv-pipeline__tabs` из 9 `button[role=tab].gv-pipeline__tab[data-id]` (`--x`,`--y` в % для `arc`: `polar(50,50,33,угол)`), `div[role=tabpanel].gv-pipeline__panel`. Деталь `article.gv-pipeline__detail[data-id]`: head, short, what, formula, file, таблица params, `figure` — мини-схема `miniSvg(id)` (`svg.gv-mini`) или живой виджет: `calibrate` → `.gv-calib` (`kit.dial` с `zones`, `input[type=range] 0–359 шаг 0,1`, вывод МПа/бар/зона, легенда зон), `stabilize` → `.gv-ema` (polyline raw/smooth, кнопка «Вибрация», 400 мс/60 точек, пауза вне экрана). Возврат `{ destroy, select(id) }`.
- `compare` — `['split','toggle']`. Опции `{ layout }`. Корень `div.gv-compare.gv-compare--<layout>[data-mode=before|after]`; `toggle` стартует с `before` и прячет неактивную колонку (`hidden`), `split` — с `after`. Состав: (`toggle`) `.gv-compare__switch` с `.gv-compare__modes`, `.gv-compare__cols` (`section.gv-compare__col--before|after`, стрелка), `.gv-compare__extra` (`.gv-compare__saving` + `.gv-compare__pair` — `kit.crop`/`kit.dial` по `data-media`), `.gv-compare__timeline` (шкала 12 ч, метки обхода/отклонения/обнаружения). Возврат `{ destroy }`.
- `architecture` — `layouts ['auto']`, опций нет (раскладка `wide` ≥ 62 rem / `narrow` по ширине контейнера, ResizeObserver + `gv:tweaks`). Корень `div.gv-architecture[data-layout][data-active]`: `.gv-architecture__canvas` (svg связей + 12 `button.gv-architecture__node[data-id][data-group][aria-pressed]`), `.gv-architecture__caption[aria-live]`, `.gv-architecture__stack` (чипы). Порядок кнопок в DOM: `sources, server, sinks(client+storage), services`. Возврат `{ destroy }`.
- `limits` — `['cards','rows']`. Опции `{ layout }`. Корень `div.gv-limits.gv-limits--<layout>`: блок компромиссов (7 `li.gv-limits__trade` с кнопкой-аккордеоном), блок ограничений (фильтр `.gv-limits__filters` через `rovingTabs`, 5 `li.gv-limits__item[data-status]`), `.gv-limits__after` = `untested` + `roadmap`. Возврат `{ destroy }`.

### 2.5 `GV.variants.<id>`

`{ id, label, render(root) → cleanup() }`. `render` строит `div.gv<x>-page` внутри `#gv-root`; app сам принимает функцию или `{destroy}`.

### 2.6 `GV.app` (`js/app.js`, последний скрипт)

- Берёт `#gv-root`, `#gv-studio`, `GV.util.h`; без них — `console.error` и выход.
- Выбор варианта: `?v=` → localStorage `gv.variant` → `'a'` → первый из `ids()`; кандидаты проверяются по `ids()` (варианты с `render` в `GV.variants`, отсортированы).
- `render(id, keepPosition)`: `cleanup` старого → `root.textContent=''` → `html[data-variant]=id` → `GV.variants[id].render(root)` (ошибка → `renderShell`) → `store(id)` в `gv.variant` → `history.replaceState(?v=)` (try/catch для file://) → `syncStudio()` → восстановление секции (`sectionInView` по `section[id]` в `#gv-root`) → `document` CustomEvent `gv:variant {detail:{id}}`.
- Студийная панель в `nav#gv-studio` (вне `#gv-root`): `span.gv-studio__label` «Вариант» → `ul.gv-studio__list[role=list]` → `li.gv-studio__item > button.gv-studio__btn[data-variant-id][aria-pressed]` (внутри `span.gv-studio__key` + « · label») → `span.gv-studio__note` «GaugeVision AI · студия». Если вариантов нет — `span.gv-studio__empty`. Кнопки есть всегда для каждого найденного варианта (в т.ч. при одном).
- Старт: `buildStudio` → `render(initial,false)` → если есть `location.hash` — `getElementById(decodeURIComponent(hash.slice(1)))` и `scrollIntoView`. Нет вариантов: `renderShell()` (`.gv-shell` с h1, lead, кнопкой и тремя метриками `kind==='measured'`).
- API `GV.app = { current(), switchTo(id), ids() }` — определяется только после первого `render()`.

### 2.7 `GV.tweaks` (`js/tweaks.js`)

- Состояние `{ font, bg, scale, media }`; `DEFAULTS = { font:'auto', bg:'graphite', scale:1, media:'shots' }`.
- Оси: `font` auto|manrope|onest|plex; `bg` graphite|anthracite|blue|paper; `scale` 0.9|1|1.1|1.25; `media` shots|schematic.
- Применение (`apply`): `html[data-font]`, `html[data-bg]`, `html[data-media]`, `html.style --ui-scale`, `meta[name=theme-color]`; `document` CustomEvent `gv:tweaks {detail: state}` (первый раз — синхронно при загрузке скрипта, до `app.js`).
- localStorage `gv.tweaks` (JSON, санитизация по OPTIONS). API: `get, set(partial), reset, open, close, defaults, options`.
- Панель строится в `aside#gv-tweaks`: `section.gv-tweaks__panel[role=dialog][hidden]#gv-tweaks-panel` (4 `fieldset.gv-tweaks__group` с radio `.gv-tweaks__radio`, `.gv-tweaks__chip`, сброс, подсказка «Esc — закрыть») + кнопка `button.gv-tweaks__toggle` «Tweaks». Esc закрывает.

## 3. Вариант B «Циферблат» (`js/variants/b.js`, `css/variant-b.css`)

### 3.1 Структура и порядок
`ORDER = ['hero','metrics','pipeline','compare','architecture','limits','contact']`. Страница: `div.gvb-page` → `header.gvb-header` → `div.gvb-main` (`section#hero.gvb-hero`, 5 секций `section#<id>.gvb-section.gvb-section--<id>`, `section#contact.gvb-contact`) → `footer.gvb-footer`.
- `header`: `.gv-container.gvb-header__inner` (grid `1fr auto 1fr`): `a.gvb-brand[href=#hero]` (SVG-марка `.gvb-brand__mark` из `kit.arcPath(12,12,9.5,135,45)`, `__needle`, `__hub`; `span.gvb-brand__name`), `nav.gvb-nav > ul.gvb-nav__list > li > a.gvb-nav__link[href=#id]` (текст `sections[id].nav`, 7 пунктов, в т.ч. «GitHub» → `#contact`), `a.gvb-header__cta` (`kit.extLink` на `meta.repoUrl`, иконка github, текст `T.github`='GitHub'). Sticky: `top: var(--studio-h)`, `--gvb-header-h:4rem`; ниже 1100 px — `position: static`, nav второй строкой с `overflow-x:auto`.
- `sectionHead(id)` → `header.gvb-head` (`span.gvb-head__index[aria-hidden]` = `sec.index`, `h2.gvb-head__title#gvb-<id>-title`, `p.gvb-head__lead` если есть `lead`). Индекс — контурная цифра за заголовком (`grid-area:1/1`, `-webkit-text-stroke` под `@supports`).
- Секции 02–06: `h('div.gv-container', sectionHead(id), div.gvb-section__body)`; `aria-labelledby='gvb-<id>-title'`.

### 3.2 Монтирование компонентов (`MOUNTS` + hero)
- hero: `GV.components.heroStage.mount(stageHost, { layout: 'dial' })`, `stageHost = div.gvb-hero__stage`.
- `metrics` → `{ layout: 'dial' }`; `pipeline` → `{ layout: 'arc' }`; `compare` → `{ layout: 'toggle' }`; `architecture` → `{}`; `limits` → `{ layout: 'cards' }`.
- `contact` рисуется самим вариантом (не компонент): `p.gvb-contact__text`, `a.gvb-contact__repo` (`.gvb-contact__repo-label`, `__repo-url` без `https://`), `ul.gvb-contact__list` (непервичные `contact.links`: pdf, license, author), `dl.gvb-contact__meta` (Хакатон = `meta.track`, Лицензия = `meta.copyright`). Футер: `meta.copyright + '.'`, `name vversion`, ссылка на `meta.licenseUrl` с текстом `labels.license`.
- Нав: `kit.sectionNav(sc, { container: header, links: navLinks, ids: ORDER, rootMargin: '-35% 0px -55% 0px' })`.
- cleanup: `sc.destroy()`, `destroy()` всех компонентов, удаление `page`.
- Подписи `T`: `nav`, `home`, `github`, `contactLinks`, `track`, `license`, `newTab`.

### 3.3 Hero: растровые картинки и дуга
- Hero-grid `.gv-container.gvb-hero__grid` (3 колонки `1fr minmax(0,36rem) 1fr`): `.gvb-hero__title-col` (h1 `#gvb-hero-title` = `hero.title`) — колонка 1; `.gvb-hero__copy` (`hero.lead`, `.gvb-hero__actions`: `a.gvb-button--primary` на `ctaPrimary.href` + `kit.demoLink(...,'gvb-button gvb-button--ghost')`, `p.gvb-hero__meta` = `trackShort` + `labels.license`) — колонка 3; `.gvb-hero__gauge` — колонка 2 (`position:relative; padding-top: var(--gvb-arc-room)`), в нём `svg.gvb-arc` и `.gvb-hero__stage`.
- Растровые картинки в hero — только через `heroStage` (режим `data-media="shots"`): `assets/smartphone-client.png` (слой raw) и `assets/dashboard-real.png` (слой recognized), кадрирование `kit.crop` + `.gv-crop`/`.gv-crop__img` (CSS `aspect-ratio: var(--crop-ar)`), слой recognized открывается `clip-path: inset(0 0 100% 0)` → `inset(0 0 0 0)` (`components.css` ~404–410). Окно круглое: `.gv-hero-stage--dial .gv-hero-stage__viewport` `border-radius:50%`, ширина `var(--gvb-face)` (18rem; 14rem ≤760 px). В режиме `schematic` — `kit.dial({numbers:false})`.
- Дуга шкалы — собственная SVG варианта B (не `kit.dial`): создаётся `createElementNS`, `svg.gvb-arc[aria-hidden]` с детьми `g.gvb-arc__scale` (перерисовывается) и `g.gvb-arc__pivot` (`circle.gvb-arc__ring`, `g.gvb-arc__needle` с `line.gvb-arc__needle-tail` и `line.gvb-arc__needle-line`, `text.gvb-arc__theta`). Стрелка рисуется горизонтально вдоль +x от центра, поворачивается CSS `needle.style.transform = rotate(<угол>deg)`.
- `layoutArc()` (вызов: сразу, `ResizeObserver` на `gauge` и `stageEl`, `window resize`, `gv:tweaks` через `sc.timeout(60)`, `document.fonts.ready`): берёт `getBoundingClientRect` у `.gv-hero-stage__viewport` и `gauge`; `cx, cy` — центр окна относительно gauge; `face = r.width/2`; `R = min(cy - 2.25rem, pageCx - 0.75rem, vw - pageCx - 0.75rem)`; кэш по `lastKey`. Ставит `viewBox/width/height` svg, `translate(cx cy)` на `pivot`, `ring r = face + 0.375rem`. `room = R - face`: `< 3.5rem` → класс `is-compact`; `< 2rem` → класс `is-hidden` (display none) и дуга не строится.
- Дуга: `g[translate(cx,cy)]` → `path.gvb-arc__line` = `kit.arcPath(0,0,R, cal.thetaMin(135), cal.thetaMax(45))` (270° по часовой), 51 риска (`steps=50`), каждая 5-я `gvb-arc__tick--major` (11 крупных), угол `kit.valueToAngle(v, cal)`, `inset=0.5rem`, длины `major=min(1.1rem, room*0.22)`, `minor=min(0.6rem, room*0.12)`. Цифр нет (ADR 0004); CSS `.gvb-arc__num` и `.is-compact .gvb-arc__num` в `variant-b.css` есть, JS такой класс не создаёт.
- Стрелка: `needleLine x1 = face+0.9rem`, `x2 = max(face+1.5rem, tipR)`, `tipR = R - inset - major - 0.25rem`; `needleTail` `face+0.375rem → face+0.9rem`. `syncNeedle()`: по `data-state` на `.gv-hero-stage` (MutationObserver, `attributeFilter ['data-state']`) — `raw` → угол `cal.thetaMin` (135°), `recognized` → `ro.theta` (275.2°); ставит `arcSvg[data-state]`. CSS: `transition: transform 900ms var(--ease-out)`.
- Подпись `text.gvb-arc__theta` = `θ = 275,2°` в точке `polar(0,0,R+1.1rem, ro.theta)` (в системе pivot — без смещения, т.к. pivot уже в центре); видна (`opacity:1`, `transition-delay:600ms`) только при `data-state=recognized`.
- hero-stage в B переупорядочен CSS: `.gv-hero-stage__body {order:1}`, `__bar {order:2}`, `__caption {order:3}`; `.gv-dial__label--roi` скрыт; телеметрия — `repeat(4,auto)` (≤760 px `repeat(2,…)`), строка `--main` на всю ширину.

### 3.4 Токены B
- `tokens.css` `[data-variant="b"]`: `--accent:#FF5A1F`, `--accent-contrast:#1A0802`, `--accent-soft:rgba(255,90,31,.12)`, `--font-sans` и `--font-display` = `'Onest'`, `--font-mono` = `'IBM Plex Mono'`. На «Бумаге»: `--accent:#C2410C`, `--accent-contrast:#FFFFFF`.
- Локальные в `variant-b.css`: `--gvb-header-h:4rem`, `--gvb-face:18rem`, `--gvb-arc-room:12.5rem` (760 px: `14rem`, `6.5rem`).
- Шрифты: Onest 400/500/700/800 + IBM Plex Mono 400/500/600 (`@font-face` в `fonts.css`). Tweaks `font` перебивает: `html[data-font="…"][data-variant]`. Хром студии/Tweaks — `--font-chrome` (JetBrains Mono, не меняется).
- Брейкпоинты `variant-b.css` (px только в медиазапросах): `min-width:1100px` (pipeline arc в 2 колонки `34rem | 1fr`), `max-width:1240px` (паддинг пунктов nav), `max-width:1099px` (header static, nav 2-й строкой, hero grid 2 колонки, gauge на всю ширину строкой 2 ≤`36rem`), `max-width:760px` (hero 1 колонка: copy → gauge, `--gvb-face`, `--gvb-arc-room`), `max-width:640px` (метрики 2 колонки, мельче цифры, кнопки hero flex, repo-кнопка на всю ширину), `prefers-reduced-motion` (transition:none для `.gvb-arc__needle`, `__theta`, `.gvb-nav__link::before`, `.gv-metrics--dial .gv-metrics__digits`).
- `scroll-margin-top: calc(var(--studio-h) + var(--gvb-header-h) + var(--space-4))` для `section[id]` и `#hero-stage`.
- Переопределения компонентов в B: `.gv-metrics--dial` (контурные цифры `-webkit-text-stroke`), `.gv-pipeline--arc` (+`__panel`), `.gv-compare--toggle .gv-compare__mode`, `.gv-compare__col[--after]`, `.gv-compare__cost-value`, `.gv-architecture__node/__caption`, `.gv-limits--cards .gv-limits__item`, `.gv-limits__condition`.

## 4. Токены и CSS

- `tokens.css` (`:root`): `--bg-canvas --bg-surface --bg-elevated`, `--border-hairline --border-strong`, `--text-primary --text-muted --text-faint`, `--accent --accent-contrast --accent-soft`, `--status-ok --status-warn --status-alert`, `--font-sans --font-display --font-mono --font-chrome`, `--ui-scale`, `--chrome-u` (= `1rem / --ui-scale`), `--fs-2xs|xs|s|m|l|xl|2xl|3xl|display`, `--lh-tight|snug|body`, `--tracking-display|caps`, `--space-1..8` (0.25 … 5 rem), `--container` (90rem), `--gutter`, `--measure`, `--radius-s|m|l`, `--ease-out|in-out`, `--dur-fast|med|slow` (160/320/600 ms), `--studio-h`, `--tap`, `--focus-ring`.
- Слои: `:root` (графит) → `html[data-bg=graphite|anthracite|blue|paper]` (фон/текст; paper ещё `color-scheme:light` и статусы) → `[data-variant=a|b|c]` (акцент, шрифты) → `html[data-bg=paper][data-variant=x]` (акцент ≥ 4,5:1) → `html[data-font=manrope|onest|plex]` и `[data-variant]` (шрифты Tweaks).
- Правило rem: `html { font-size: calc(100% * var(--ui-scale)) }` — весь UI в rem масштабируется Tweaks; px только `1px` линии и `@media`. Хром (`#gv-studio`, Tweaks) считается от `--chrome-u` и от масштаба не зависит. Внутри SVG-viewBox числа в user units (не rem); B для дуги переводит rem в px через `getComputedStyle(html).fontSize`.
- `base.css`: reset, `html/body`, заголовки, `:focus-visible` (outline 2px accent), утилиты `.gv-visually-hidden .gv-mono .gv-num .gv-caps .gv-muted .gv-container .gv-skip`, `#gv-root section[id]` scroll-margin, `#gv-studio` (sticky top:0, z-index 60) и `.gv-studio__*`, `.gv-shell*`, `.gv-noscript*`, `.gv-button`, медиазапрос ≤640 px, блок reduced-motion.
- `components.css` секции (по комментариям): «Общее» (`.gv-crop`, `.gv-icon`, `.gv-dial*`, `.gv-mini*`), `heroStage`, `metrics`, `pipeline` (rail/arc/timeline, панель, `.gv-calib*`, `.gv-ema*`), `compare`, `architecture`, `limits` (cards/rows, roadmap), «Адаптив» (1099/760/640 px).
- `prefers-reduced-motion`: (1) `base.css` — `*{animation-duration:.01ms!important; transition-duration:.01ms!important; scroll-behavior:auto!important}`; (2) `components.css` — `.gv-hero-stage__scan{display:none}` и `transition:none` у слоя recognized, `__val > span`, меток compare, `.gv-pipeline__arc-needle`, `.gv-dial__needle`; (3) `tweaks.css` — панель без анимации; (4) `variant-b.css` — см. 3.4. В JS: `GV.util.prefersReducedMotion()` отключает автопереход hero, счётчик метрик, скан-линию, интервал EMA, smooth-scroll.
- `tweaks.css` — `.gv-tweaks__*` (toggle z-index 70, панель).

## 5. Тесты

Запуск из корня: `node site/tests/check.js` и `node site/tests/components.test.js` (без зависимостей; `check.js` печатает нарушения и `FAIL`, код 1; иначе `OK: …; вариантов проверено: N`).

### 5.1 `check.js` (загружает `content.js` через `vm.runInNewContext` с `window` из `{}`)
- Путь к notes.md: `NOTES` = первый существующий из `.autopilot/2026-11-14-gaugevision-landing/notes.md`, `.autopilot/2026-11-14-gaugevision-landing--wip/notes.md`; если нет ни одного — первый путь (ошибка «нет источника фактов»). Папки `…-gaugevision-dial--wip` не знает. Сейчас `notes.md` лежит в папке `2026-11-14-gaugevision-landing/`.
- `SECTION_IDS` (захардкожено, строка 30): `hero metrics pipeline compare architecture limits contact`.
- [0] Форма: `SHAPE` (meta, hero, hero.stage, hero.stage.readout, calibration, ema, compare, architecture, untested, contact — непустые поля) и `ITEM_SHAPE` (metrics, pipeline, tradeoffs, limits, roadmap — поля у каждого элемента); `screenshotFacts` — объект; metrics ≥ 5 и `kind ∈ measured|calculated`; pipeline индексы строго `00,…,08`, у каждого `params` непуст с `name`,`value`; tradeoffs ≥ 5; limits ровно 5 со `status ∈ done|partial`; roadmap `status ∈ done|planned`; нет пустых строк (кроме `metrics[].unit`).
- [1] Числа: каждое число из `metrics`, `pipeline[].params`, `limits`, `compare`, `calibration`, `ema` (кроме ключей `id, kind, status, index`) должно встретиться в корпусе `README.md + PRODUCT.md + app/config.py + notes.md` (нормализация: `300 000`→`300000`, `0,38`→`0.38`; варианты `5`/`5.0`; границы токена по регулярке). Нет источника → ошибка «нет источника фактов».
- [2] Пути: в `index.html` каждый локальный `src|href`; в `content.js` значения по ключам `src`/`href` и строки `assets/…`; `url()` во всех `css/*.css`; абсолютные пути (`/x`) — ошибка; существование относительно `site/`.
- [3] Запрещённые слова во всех текстовых файлах `site/` (`.html .css .js .md .svg .json .txt`, кроме `tests/` и `design-system.md`), построчно: `open source`, `MIT`, `lorem`, `TODO`, `FIXME`, `бесплатн`; в строках `content`: «34 e2e/провер», «18 браузерн/провер», «3–37», «ответ сервера», опечатка `GuageVision` (кроме значений `href`/`*Url`).
- [4] Модули: в `js/**/*.js` нет `import`/`export` в начале строки, `import(`; нет `type="module"` ни в js, ни в `index.html`.
- [5] Варианты: для каждого файла `js/variants/*.js` — все семь id встречаются в кавычках (`'id'`, `"id"`, backtick, `#id`) или как `id="…"` и в порядке `SECTION_IDS` по первому вхождению. Число проверенных файлов выводится как «вариантов проверено» (сейчас 3).
- [6] Типографика строк `content` (кроме `screenshotFacts`): нет « - » и `--`; для ключей вне `id file source src href version formula repoUrl licenseUrl pdfUrl authorUrl roi code` — нет диапазонов через дефис `\d+-\d+` и десятичной точки `\d+\.\d+`.
- «3 варианта» нигде не захардкожено числом: проверка обходит `readdir` папки `js/variants` — удаление `a.js`/`c.js` просто уменьшит счётчик. Но `check.js` читает `walkFiles(site/css)` для `url()` и `walkFiles(site)` для запрещённых слов, т.е. включает любые оставшиеся файлы.

### 5.2 `components.test.js`
Грузит через `vm.createContext`+`runInContext` три файла в общий sandbox (`sandbox.window = sandbox`): `js/content.js`, `js/util.js`, `js/components/kit.js` (без jsdom; DOM-хелперы kit не создаются, т.к. `document` нет). Проверяет на `GV.content.calibration`: `angleToValue` (253,4°→4,39; 135°→0; 45°→10; 270°→5; 60°→10,5; 120°→−0,5; CCW зеркально), `toBar` (43,85), `zoneOf` (0,5/1→LL; 1,5/2→L; 4,39→NORMA; 8→H; 9→HH), `levelOf` (normal/warning/alert), `emaStep` (null→4; 4→8 при 0,25 = 5), `valueToAngle(5)=270`. Ошибка при отсутствии `GV.kit.angleToValue`.

## 6. Зависимости между вариантами A/C и общими файлами

- Только A: `js/variants/a.js` (`gva-*`, mounts: heroStage `framed`, metrics `strip`, pipeline `rail`, compare `split`, limits `cards`), `css/variant-a.css`, `[data-variant="a"]` и `html[data-bg="paper"][data-variant="a"]` в `tokens.css`, `<link variant-a.css>` и `<script a.js>` в `index.html`.
- Только C: `js/variants/c.js` (`gvc-*`, heroStage `sheet`, metrics `table`, pipeline `timeline`, compare `split`, limits `rows`), `css/variant-c.css`, `[data-variant="c"]` и paper-блок в `tokens.css`, `<link>`/`<script>` в `index.html`.
- Layout-опции компонентов, используемые только A/C (код и CSS остаются жить в общих файлах): heroStage `framed` (`gv-hero-stage--framed`, `__corner*`, угловые метки) и `sheet`; metrics `strip`, `table`; pipeline `rail` (`gv-pipeline__rail-line`) и `timeline` (`__tab-short`, `__tab-formula`, `orientation:'both'`); compare `split` (кнопки режима в шапке шкалы, обе колонки); limits `rows`. В B используются: heroStage `dial`, metrics `dial`, pipeline `arc`, compare `toggle`, limits `cards`, architecture.
- Общие и нужные B: `index.html`, `content.js`, `util.js`, `kit.js` (весь, включая `dial`/`setNeedle` — их использует `pipeline.js` для калибровки и `hero-stage`/`compare` в режиме `schematic`), все шесть компонентов, `tweaks.js`, `app.js`, `fonts.css`, `tokens.css`, `base.css`, `components.css`, `variant-b.css`, `tweaks.css`, ассеты.
- В коде общих файлов упоминания «a» вне вариантов: `app.js` — `candidates = [readParam(), readStored(), 'a']` и комментарии; `index.html` — `data-variant="a"` в `<html>` (до JS-выбора) и inline-скрипт (любая буква a–z); `tokens.css` — блоки `a`/`c`. Если `a` отсутствует в `ids()`, `pick` берёт `list[0]`.
- Студийная панель и `?v=`/`gv.variant`/`gv:variant` — только в `app.js` и `base.css` (`#gv-studio`, `.gv-studio__*`), `tokens.css` (`--studio-h`), `variant-b.css` (`top: var(--studio-h)`, `scroll-margin-top`), `components.css`/`base.css` (`scroll-margin-top: calc(var(--studio-h)…)`). `studio.getBoundingClientRect()` читается в `sectionInView`.
- `kit.sectionNav`, `kit.demoLink`, `kit.arcPath` используют все три варианта; `kit.valueToAngle`, `kit.polar`, `kit.onTweaks` в вариантах — только B.
- `check.js` и `components.test.js` вариантов по именам не знают (см. 5.1): `check.js` проверяет каждый найденный файл в `js/variants/`.

## 7. Подводные камни по коду

- Порядок скриптов — скрытый контракт (ADR 0001): `kit.js` до остальных компонентов; `tweaks.js` до `app.js`; `app.js` в конце, читает `GV.variants`. `tweaks.js` вызывает `apply(true)` при загрузке (событие `gv:tweaks` уходит до того, как компоненты подписаны).
- `file://`: нет модулей/`fetch`; `history.replaceState` и `localStorage` обёрнуты в try/catch.
- `GV.app` не определён до конца первого `render()`; внутри `render` вариант берут из `document.documentElement.dataset.variant`.
- `rovingTabs` вызывает `onSelect` синхронно в конструкторе — отсюда флаги `ready` в `heroStage`/`limits`.
- B считает дугу по `getBoundingClientRect` окна кадра; пересчёт по `ResizeObserver`, `resize`, `gv:tweaks` (+60 мс), `document.fonts.ready`; ключ `lastKey` округляет значения до целых пикселей.
- `kit.crop` подгоняет `--crop-ar` после загрузки картинки (`naturalWidth/Height`); до загрузки используется `w/h` в долях.
- Известные баги (`PROGRESS.md`) и где они в коде:
  - Битый хеш `#%E0` → `URIError`: `app.js`, блок «Старт», `decodeURIComponent(window.location.hash.slice(1))` без try/catch.
  - `check.js` не сверяет числа в `tradeoffs`, `hero`, `roadmap`, `architecture`: `checkNumbers` → объект `scope` (metrics, pipeline params, limits, compare, calibration, ema).
  - Студийная панель на телефоне 48 px (вместо ≤40): `--studio-h: calc(2.5 * var(--chrome-u))` в `tokens.css` и media ≤640 px в `base.css`.
  - Переход hero через `clip-path`: `components.css` ~404–410 (`.gv-hero-stage__layer--recognized`, `transition: clip-path var(--dur-slow)`); при reduced motion — `transition: none` (`components.css` блок в конце).
  - Ссылки GitHub в hero/футере в новой вкладке без пометки: в B `kit.extLink` в `hero.actions`, `gvb-footer`, `gvb-contact__*`; `aria-label` с `T.newTab` есть только у `gvb-header__cta`.
  - В шапке B два «GitHub»: `nav` пункт `sections[6].nav='GitHub'` → `#contact`, и `a.gvb-header__cta` с `T.github` → репозиторий.
  - Порядок Tab в hero B «справа налево»: DOM — `title-col`, `copy` (кнопки), `gauge` (в нём `bar` с переключателем раньше `body`); визуально `copy` в колонке 3, `gauge` в колонке 2, `.gv-hero-stage__body` вынесен `order:1` перед `bar`.
  - Навигация B на телефоне уходит за край: `.gvb-nav` `overflow-x:auto` и `white-space:nowrap` у `.gvb-nav__link` (≤1099 px).
  - Tab по архитектуре на телефоне: порядок `nodeButtons = sources.concat(server, sinks, services)` в `architecture.js`, а в `narrow()` служебные модули стоят в правой дорожке рядом с сервером.
- Мёртвый код в B: CSS `.gvb-arc__num` / `.is-compact .gvb-arc__num` (JS числа не рисует).
- Переменные B, привязанные к JS: классы `is-compact`, `is-hidden` на `.gvb-arc`, `data-state` на `.gvb-arc`.
- `check.js` ищет `notes.md` только в папках `…gaugevision-landing` / `…landing--wip`; этот файл (в `…gaugevision-dial--wip/`) корпус сверки чисел не читает.
- `index.html` `<html data-variant="a">` и `meta theme-color` стартуют до JS; inline-скрипт принимает `?v=x` без проверки наличия — до `app.js` `data-variant` может указывать на несуществующий вариант (токены `[data-variant]` не найдутся, пока app не поправит).
