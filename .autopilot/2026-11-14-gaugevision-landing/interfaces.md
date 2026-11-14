# Интерфейсы и правила проекта

Читается каждым исполнителем первым. Имена — английские, тексты на сайте — русские.

## Правила проекта

1. **Факты.** Только из `README.md`, `PRODUCT.md`, кода в `app/` и `.autopilot/2026-11-14-gaugevision-landing--wip/notes.md`. Ни одной выдуманной метрики, функции, клиента, отзыва, контакта. Сомневаешься — не пиши.
1a. **Код главнее README.** Где `notes.md` § «Расхождения README ↔ код» фиксирует расхождение, сайт пишет как в коде:
   - стрелка: ведущий метод — радиальный момент, HoughLinesP уточняет при расхождении ≤ 12°; маски Black-Hat / Top-Hat (ядро 31×31) плюс маска по насыщенности для цветных стрелок;
   - CLAHE (clip 3,0, сетка 8×8) — только при локализации циферблата; в масках стрелки свет выравнивают морфологические «шляпы»;
   - смартфон без кадров: через 6 с — «переподключение», через 30 с — «офлайн»;
   - калибровка допускает выход стрелки за шкалу на ±5 %.
   **Не публиковать:** «34 проверки e2e / 18 браузерных» (тестов в репозитории нет) и «ответ сервера 3–37 мс» (это RTT в браузере, 3 мс не подтверждено). Метрики качества (0,38 %, mAP₅₀ 90,1 % и др.) публикуются как заявленные в README, с условиями замера.
2. **Лицензия проприетарная.** Никаких «open source», «MIT», «бесплатно», «скачайте и запустите».
3. **Русская типографика.** Длинное тире « — » с пробелами там, где его требует пунктуация; дефис только внутри слов; диапазоны чисел — «30–100» (короткое тире без пробелов). Десятичная запятая: 0,38 %, 7,2 мс. Неразрывный пробел между числом и единицей (`&nbsp;` / ` `).
4. **Статика без сборки.** Только классические `<script src>`, порядок подключения задан в `index.html`. Никаких `import`/`export`, `type="module"`, CDN, npm. Всё работает по `file://`.
5. **Только относительные пути** (`assets/…`, `css/…`, `js/…`).
6. **Размеры в `rem`**, чтобы работал масштаб из Tweaks. `px` допустимы только для линий 1px и медиазапросов.
7. **Доступность.** Каждый интерактивный элемент — нативная `<button>`, `<a>` или `<input>`, с видимым `:focus-visible`; `prefers-reduced-motion` отключает всю необязательную анимацию; анимация только по `transform`/`opacity`.
8. **Без мёртвых элементов.** Ни одной кнопки, вкладки или ссылки, которая ничего не делает.

## Окружение и команды

- Windows 11, Git Bash. `python3` — заглушка Microsoft Store: используй `python` (3.14) или `node` (есть). Конвертеров изображений (magick, cwebp, ffmpeg) нет.
- Проверка одной командой: `node site/tests/check.js` (создаёт тикет 01). Запускается из корня репозитория.
- Визуальная проверка: Playwright MCP (`mcp__playwright__*`, грузятся через ToolSearch) по адресу `file:///C:/Hakatons/GaugeVisionAI/worktrees/gaugevision-landing/site/index.html?v=a` — или поднять `python -m http.server 8765 --directory site` в фоне и открыть `http://localhost:8765/?v=a`. Ширины: 1440×900 и 390×844. Скриншоты — в `~/tmp` или `.autopilot/<dir>/shots/` (не в `site/`).
- Шрифты: скачать woff2 (кириллица + латиница) с `https://cdn.jsdelivr.net/fontsource/fonts/<family>@latest/<subset>-<weight>-normal.woff2` (например, `manrope@latest/cyrillic-400-normal.woff2`, `latin-…`), семейства `manrope`, `jetbrains-mono`, `onest`, `ibm-plex-sans`, `ibm-plex-mono`. Если скачать не удалось — `BLOCKED`, не подставлять CDN-ссылки в CSS.
- Не трогать: всё вне `site/` (кроме записи в «Что построили» этого файла), `site/assets/dashboard-real.png`, `site/assets/smartphone-client.png`. Копировать из `docs/images/` в `site/assets/img/` можно.
- Дизайн-скиллы: перед правкой UI прочитай `~/skills/tactical-hud-web-design/SKILL.md` и `~/skills/impeccable/reference/craft-floor.md`; ориентиры — `reference.md` в папке прогона и картинки `references/*.png`.

## Границы, решённые в спецификации

### Структура файлов `site/`

```
site/
├── index.html              оболочка: <html lang="ru">, студийная панель, <main id="gv-root">, Tweaks, noscript, скрипты
├── design-system.md        правила дизайна (R28–R29)
├── css/
│   ├── fonts.css           @font-face для 5 семейств
│   ├── tokens.css          :root-токены + [data-bg] + [data-font] + --ui-scale
│   ├── base.css            reset, типографика, утилиты, студийная панель
│   ├── components.css      раскладки компонентов .gv-* для всех layout-опций (тикет 02)
│   ├── tweaks.css          панель Tweaks
│   ├── variant-a.css       всё под [data-variant="a"]
│   ├── variant-b.css       всё под [data-variant="b"]
│   └── variant-c.css       всё под [data-variant="c"]
├── js/
│   ├── content.js          GV.content — единственный источник фактов
│   ├── util.js             GV.util — общие хелперы
│   ├── components/
│   │   ├── hero-stage.js   GV.components.heroStage
│   │   ├── metrics.js      GV.components.metrics
│   │   ├── pipeline.js     GV.components.pipeline (+ calibration, emaSim внутри деталей)
│   │   ├── compare.js      GV.components.compare
│   │   ├── architecture.js GV.components.architecture
│   │   └── limits.js       GV.components.limits
│   ├── variants/
│   │   ├── a.js            GV.variants.a
│   │   ├── b.js            GV.variants.b
│   │   └── c.js            GV.variants.c
│   ├── tweaks.js           GV.tweaks
│   └── app.js              GV.app — роутер вариантов, студийная панель; подключается последним
├── assets/
│   ├── dashboard-real.png, smartphone-client.png   (есть, не трогать)
│   ├── fonts/*.woff2
│   └── img/                копии docs/images/*.png, если нужны
└── tests/check.js          node site/tests/check.js
```

Порядок скриптов в `index.html`: `content.js` → `util.js` → `components/*.js` → `variants/*.js` → `tweaks.js` → `app.js`. Каждый файл — IIFE, который дописывает в `window.GV`: `window.GV = window.GV || {}`.

### `GV.content` (js/content.js) — владелец: тикет фундамента

Чистые данные, без DOM. Форма (поля можно добавлять, нельзя переименовывать):

```js
GV.content = {
  meta:   { name, tagline, repoUrl, licenseUrl, pdfUrl, track, copyright },
  hero:   { eyebrow, title, lead, ctaPrimary:{label,href}, ctaSecondary:{label,target:'#hero-stage'},
            stage:{ rawLabel, recognizedLabel, caption, captionSchematic,
                    raw:{ src, alt, crop:{x,y,w,h} },          // доли 0..1 от исходника
                    recognized:{ src, alt, crop:{x,y,w,h} },
                    readout:{ device, value, unit, theta, conf, roi, latencyMs } } },
  metrics: [ { id, value, unit, label, condition, kind:'measured'|'calculated' } ],
  pipeline:[ { id, index:'00', title, short, what, params:[{name,value,note}], file, aspect } ],
  calibration:{ thetaMin:135, thetaMax:45, vMin:0, vMax:10, unit:'МПа', direction:'CW',
                setpoints:{ LL:1, L:2, H:8, HH:9 }, barPerMpa:10, formula },
  ema:    { alpha:0.25, minConfidence:0.25, caption },
  compare:{ before:{ title, points:[...] , cost:{value,unit,note} },
            after:{ title, points:[...], cost:{value,unit,note} }, savingNote, timeline:{ caption } },
  architecture:{ nodes:[{id,label,sub,group,file?}], edges:[{from,to,label?}], stack:[{name,version?}], boundaryLabel },
  tradeoffs: [ { id, chose, cost, why, source } ],   // «выбрали → платим», source — константа/файл
  limits: [ { id, condition, risk, response, status:'done'|'partial' } ],
  untested:{ title, text },
  roadmap:[ { index, title, items, status:'done'|'planned' } ],
  contact:{ title, text, links:[{label,href}] },
  screenshotFacts:{ ... }   // значения, видимые только на скриншотах (уставки 1/2/8/9, θ 275.2°, 4.74 кПа и т. п.) — check.js их не сверяет с README
};
```

### Компоненты — владелец: тикеты компонентов

Каждый: `GV.components.<name>.mount(el, options) → { destroy() }`.
- `el` — пустой контейнер, который даёт вариант; компонент рендерит внутрь свою разметку с классами `gv-<name>__*` (BEM).
- `options.layout` — строка, раскладку выбирает вариант: `heroStage: 'framed'|'dial'|'sheet'`, `pipeline: 'rail'|'arc'|'timeline'`, `metrics: 'strip'|'dial'|'table'`, `compare: 'split'|'toggle'`, `limits: 'cards'|'rows'`. Нераспознанное значение → первое из списка.
- Данные берутся из `GV.content`, не передаются вариантом.
- Компонент слушает `document`-событие `gv:tweaks` (меняется `data-media`) и перерисовывает медиа; в `destroy()` снимает все слушатели, observers, таймеры и rAF.
- Компонент не задаёт цвета и шрифты напрямую — только через токены (`var(--accent)` и т. д.); раскладочный CSS для своих layout-опций лежит в `components.css`, вариант лишь перекрашивает и масштабирует.
- `GV.components.metrics` форматирует числа через `GV.util.formatNumber` и рендерит итоговое значение в DOM сразу; счётчик — только визуальная анимация.

### `GV.util` — владелец: тикет фундамента

`formatNumber(n, digits) → '0,38'` (ru-RU, запятая) · `prefersReducedMotion() → bool` · `onVisible(el, cb, {once}) → unsubscribe` (IntersectionObserver) · `h(tag, attrs, ...children) → Element` (маленький DOM-хелпер; `attrs.class`, `attrs.on:{click}`, `attrs.html` только для доверенного контента из `GV.content`) · `svg(tag, attrs, ...children)` · `rovingTabs(listEl, {onSelect})` (стрелки ←/→, Home/End, `aria-selected`).

### Варианты — владелец: тикеты вариантов

`GV.variants.<a|b|c> = { id, label, render(root) → cleanup }`.
- `render` строит всю страницу внутри `root`: свой header с навигацией по якорям, семь секций с `id` = `hero, metrics, pipeline, compare, architecture, limits, contact` **в этом порядке**, футер. В секции монтирует компоненты и возвращает функцию, которая вызывает `destroy()` у каждого.
- Стили варианта — только в `css/variant-<id>.css` и только под селектором `[data-variant="<id>"]`.
- Вариант может добавлять декоративный SVG (дуга шкалы, угловые метки), но не новые факты.

### `GV.app` (js/app.js) — владелец: тикет фундамента

- Выбирает вариант: `?v=` → localStorage `gv.variant` → `'a'`. Ставит `document.documentElement.dataset.variant`.
- Рендерит студийную панель `#gv-studio` (вне `#gv-root`): три кнопки с `aria-pressed`. Переключение: `cleanup()` старого → `render()` нового → `history.replaceState` с `?v=` → прокрутка к той же секции, что была в зоне видимости.
- Регистрация вариантов не нужна: app читает `GV.variants`. Отсутствующий вариант кнопкой не показывается.

### `GV.tweaks` (js/tweaks.js) — владелец: тикет Tweaks

- Состояние `{ font:'auto'|'manrope'|'onest'|'plex', bg:'graphite'|'anthracite'|'blue'|'paper', scale:0.9|1|1.1|1.25, media:'shots'|'schematic' }`, localStorage `gv.tweaks`, по умолчанию `{auto, graphite, 1, shots}`.
- Применение: `html[data-font]`, `html[data-bg]`, `html[data-media]`, `html.style.setProperty('--ui-scale', …)`; затем `document.dispatchEvent(new CustomEvent('gv:tweaks', {detail: state}))`.
- `GV.tweaks.get()` возвращает копию состояния. Состояние применяется до первого рендера варианта: `tweaks.js` подключается раньше `app.js` и применяет атрибуты синхронно при загрузке.

### Токены (css/tokens.css) — владелец: тикет фундамента

Обязательные имена: `--bg-canvas --bg-surface --bg-elevated --border-hairline --border-strong --text-primary --text-muted --text-faint --accent --accent-contrast --status-ok --status-warn --status-alert --font-sans --font-display --font-mono --ui-scale --radius-s --radius-m --space-1…--space-8 --ease-out`.
- Фон: `[data-bg="graphite"|"anthracite"|"blue"|"paper"]` переопределяет `--bg-*`, `--border-*`, `--text-*`.
- Вариант задаёт `--accent`, `--accent-contrast` и шрифты по умолчанию под `[data-variant="x"]`.
- `[data-font="manrope"|"onest"|"plex"]` переопределяет `--font-*` с большей специфичностью, чем вариант (`html[data-font="…"][data-variant]`).

### Шов тестов

`node site/tests/check.js` — единственная автоматическая проверка, без зависимостей. Код выхода 0 — всё зелёное, иначе печатает каждое нарушение строкой. Проверяет:
1. Каждое число в `metrics`, `pipeline[].params`, `limits`, `compare`, `calibration`, `ema` (исключая `screenshotFacts`) встречается в README.md, PRODUCT.md, `app/config.py` или `notes.md` (нормализация: «0,38» ≡ «0.38», пробелы игнорируются).
2. Каждый локальный `src`/`href` в `index.html` и `content.js` существует.
3. В `site/` (кроме `tests/` и `design-system.md`) нет «open source», «opensource», «MIT», «lorem», «TODO», «FIXME».
4. В `js/` нет `import `, `export `, `type="module"`.
5. Каждый вариант (`js/variants/*.js`) упоминает все семь `id` секций в правильном порядке.

Исполнители дописывают сюда «Что построили» после своего тикета.

## Что построили

### 01 — Фундамент

- `GV.content` — по форме выше, плюс: `meta.authorUrl/author/trackShort/version`; `sections[{id,index,nav,title,lead?}]` (заголовки и навигация семи секций — бери отсюда); `hero.chain{before,after}`; `hero.stage.labels`; `coverage{classes,units,types[],sources[]}`; `metricsNote`; `labels{status,kind,level,…}`.
- `metrics[]` добавлены: `valueTo?` (конец диапазона), `digits`, `display` (готовая русская строка, напр. `'30–100'` — показывай её), `group`; `value` — число для счётчика; `unit` может быть `''`.
- `pipeline[]`: `formula`; `params[].note`. `limits[]`: `note?`. `calibration`: `span, clamp, zones[{id,label,status,text}], sliderLabel, caption`. `ema`: `formula, toggleLabel, legendRaw, legendEma`. `compare`: `saving, pair{rawLabel,recognizedLabel}, timeline{shiftHours:12, rounds, deviationHour, …}`. `architecture.groups`. Все строки прошли типограф (NBSP перед единицами и « — »).
- `GV.util`: `formatNumber(n,digits)`, `prefersReducedMotion()`, `onVisible(el, cb(isVisible, entry), {once,threshold,rootMargin}) → unsubscribe`, `h/svg(tag, attrs{class,on,html,text,style,dataset}, ...children)`, `rovingTabs(list, {onSelect(i,el), selector, attr:'aria-selected'|'aria-pressed', orientation, initial}) → {select,index,destroy}`, `uid(prefix)`.
- `GV.tweaks`: `get / set(partial) / reset / open / close / defaults / options`. `GV.app`: `current / switchTo(id) / ids`; событие `document` `'gv:variant'` `{id}`. `label` варианта — `'Пульт'`, префикс «A · » добавляет app.
- Токены сверх обязательных: `--accent-soft --font-chrome --chrome-u --studio-h --tap --fs-* --lh-* --dur-* --container --gutter --measure --radius-l`.
- `index.html` содержит комментарии-места для подключения `components.css`, `variant-*.css`, `components/*.js`, `variants/*.js`. Inline-скрипт в `<head>` ставит атрибуты Tweaks и `data-variant` до первой отрисовки.
- `check.js` проверяет сверх пяти пунктов: 0 — форма content, 6 — типографика, `url()` в CSS, утверждения правила 1a. Числовая сверка ловит выдуманные числа, но не проверяет контекст мелких чисел.
### 02 — Компоненты и вариант A

- Проверка теперь двумя командами: `node site/tests/check.js && node site/tests/components.test.js` (21 проверка: калибровка, бары, зоны, EMA).
- Подключение: `components.css` и `variant-*.css` после `base.css`; `components/kit.js` грузится первым среди `components/*.js`.
- `GV.components.{heroStage,metrics,pipeline,compare,limits}.mount(el, {layout}) → {destroy}`; у каждого `.layouts` — список поддерживаемых. `architecture.mount(el) → {destroy}` (wide/narrow — сам по ширине). `pipeline.mount(el, {layout, initial:id})` → `{destroy, select(id)}`. `heroStage` → `{destroy, setState('raw'|'recognized')}`; корень получает `id="hero-stage"` и `tabindex=-1`. `metrics.mount(el, {layout, ids:[…], note:bool})`.
- `GV.kit` (общий для компонентов и вариантов): `angleToValue(θ,calib) · valueToAngle · fraction · toBar · zoneOf(V,sp) → LL|L|NORMA|H|HH · levelOf · emaStep · scope() → {on,add,timeout,interval,frame,observe,destroy}` (используй `scope()` в вариантах для слушателей — cleanup одной строкой) `· pick · media() · onTweaks(sc,cb) · crop(media,cls) · dial({theta,overlay,zones,thetaLabel,valueLabel,roi,title,className}) · setNeedle · arcPath · polar · icon(external|github|arrow|right) · extLink · demoLink(label,cls) · scrollToStage(id)`.
- `GV.variants.a = {id:'a', label:'Пульт', render(root) → cleanup}`; классы варианта — префикс `gva-*` (B — `gvb-*`, C — `gvc-*`).
- hero-stage сам переключается на «Распознавание» через 1,6 с после первого появления в зоне видимости, если пользователь не кликал и reduced motion выключен.
- Раскладки `dial/sheet/arc/timeline/table/toggle/rows` прошли только дымовую проверку (монтируются, без ошибок, без переполнения на 390) — финальные размеры и цвета делает вариант, который их использует.
- Подписи интерфейса (заголовки столбцов, кнопки) лежат в локальных объектах `T` внутри компонентов; факты — только из `GV.content`.

### 03 — Варианты B и C

- `GV.variants.b = {id:'b', label:'Циферблат', render(root) → cleanup}`, `GV.variants.c = {id:'c', label:'Протокол', render(root) → cleanup}`; классы `gvb-*`, `gvc-*`.
- B: `.gvb-arc[data-state="raw"|"recognized"]` зеркалит `data-state` hero-stage; переменные `--gvb-face`, `--gvb-arc-room`; геометрию дуги в px считает `b.js` по фактическому окну кадра (ResizeObserver). C: `--gvc-index-w`.
- `components.css` в T03 не менялся; вариант A попиксельно совпадает с состоянием после T02.

- Поведение, которое надо учитывать: `GV.util.rovingTabs` вызывает `onSelect` синхронно в конструкторе (для начального элемента) — до того, как вернётся `{select,index,destroy}`; не обращайся к возвращаемому объекту из первого `onSelect`. `GV.app` определяется только после первого `render()` — внутри `render` и в обработчиках старта `GV.app.current()` ещё `undefined`, используй `document.documentElement.dataset.variant`.
- Playwright MCP может быть занят другой сессией; запасной путь — `playwright-core` из кэша npx с установленным chromium (так проверял T01).
