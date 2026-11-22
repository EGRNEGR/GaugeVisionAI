# Архитектура лендинга (`site/`)

Одна страница-журнал из восьми листов (мир «Журнал обходчика», ADR 0011). Статика без сборки: классические
`<script src>`, глобальный объект `window.GV`, работает по `file://`. Почему так — `docs/adr/`. Варианты A и C
лежат в `archive/site-variants-a-c/`; роутера и переключателя вариантов нет.

## Поток данных

`GV.content` (данные) → `GV.page` (шапка бланка, ярлыки листов, листы, футер) → `GV.components.*` (содержимое
листов) → `GV.motion` (кадр, прокрутка, пружина). Общее показание стрелки `kit.createReading` связывает
прибор первого листа и чертёж листа 03.

- `site/js/content.js` — `GV.content`, единственный источник фактов, без DOM. Поля, на которые опирается
  `check.js`, не переименовывать. `sections` — ровно 8 записей `hero, compare, reading, pipeline, metrics,
  architecture, limits, contact`; у каждой `index`, `nav`, `form` (строка бланка в поле листа) и `title`
  (кроме hero — его h1 рисует модуль).
- `site/js/page.js` — `GV.page = { mounts, render(root) → cleanup }`; вызывается на `DOMContentLoaded`, рисует
  в `#gv-root`. Лист: `<section class="gv-sheet">` с номером и строкой бланка в поле (сбоку от заголовка,
  не над ним), h2 и телом-подсеткой на 12 колонок; модуль из `GV.page.mounts` получает
  `mount(body, { section, sheet, reading, headId })`.
- Модуля нет или `mount` бросил — `console.error`, лист остаётся с заголовком. Битый `location.hash` страницу
  не роняет.
- Inline-скрипт в `<head>` до первой отрисовки ставит `--ui-scale` и `data-paper` из localStorage `gv.tweaks`
  и `data-tweaks="on"` по адресу с `?tweaks` или флагу `gv.tweaks.on` (кнопка Tweaks видна только автору, ADR 0010).

## Порядок скриптов (`site/index.html`)

`content.js` → `util.js` → `motion.js` → `components/kit.js` →
`components/{journal,shift,precision-dial,operations,metrics,architecture,limits,contact}.js` → `tweaks.js` →
`page.js` (последним). Каждый файл — IIFE, дописывает в `window.GV`. Новый компонент: файл, `<script>` до
`tweaks.js`, строка в `GV.page.mounts`, `<link>` на его CSS.

## Модули

- `GV.motion` (`js/motion.js`) — `reduced`, `onFrame(fn(dt, now)) → off`, `onScroll`, `measure`, `viewport`,
  `pinProgress(el)` 0..1, `spring`, `reveal`, `counter`, `spotlight`, `cursorLight`, `shiftBelow(el, change, scopeEl)`,
  `magnet(el, { pull, max })`. Единственный rAF-цикл: спит без подписчиков; `dt` ≤ 1/20 с.
- `GV.components.<name>.mount(el, options) → { destroy() }`; классы `gv-<name>__*`.
- `journal` (`#hero`) — h1, живой журнал: строка обходчика 08:00 его рукой и машинные строки каждые ⅓ с
  (EMA α = 0,25 поверх дрожи стрелки), справа вклеенный кадр камеры с эмалевым прибором (`kit.gauge`);
  стрелка тянется мышью, пальцем, клавишами (`role="slider"`). Поток идёт, только пока лист виден.
  Демонстрационные данные (время смены, бирка МН-1) — в коде модуля и подписаны на странице.
- `shift` (`#compare`) — закреплённая сцена: ролик Gemini перематывается по `pinProgress`, подписи «было / стало»;
  шкала смены в масштабе с перетаскиваемым отклонением и лупой на одну секунду; затраты полосами в пропорции;
  колонки «Было / Стало». Экспорт `timeFor(progress, duration)`, `delayHours(hour, rounds, shiftHours)`.
- `precisionDial` (`#reading`) — прибор-чертёж с размерными дугами, значение крупно, формула и подстановка,
  ползунок, «Записать в журнал» (`reading.commit`). Экспорт `angleFromPointer`, `clampAngle(θ, calib, prev)`.
  Углы сайта — от «6 часов» по часовой (θ = θкадра − 90°), шов 0° / 360° в пустом секторе под шкалой.
  Формулы набирает `kit.math` (дроби, индексы, слоты для живых чисел; разбор — чистая `kit.mathTree`).
- `operations` (`#pipeline`) — один синтетический кадр проходит четыре операции кода; на десктопе сцена
  закреплена и шаг задаёт прокрутка, уже 900 px — кнопки. Экспорт `stepFor(progress, count)`.
- `metrics` — протокол испытаний таблицей; `architecture` — схема соединений на миллиметровке с roving tabindex
  и спецификация стека; `limits` — компромиссы (раскрытие через `shiftBelow`), ограничения с фильтром, план;
  `contact` — сдача смены и штамп «Код на GitHub».
- `GV.kit` (`components/kit.js`) — математика калибровки (`angleToValue`, `valueToAngle`, `toBar`, `zoneOf`,
  `levelOf`, `emaStep`; повторяет `app/vision.py`), `createReading`, `clockText`, `NBSP` и DOM-хелперы: `scope()`,
  `gauge({ kind })`, `polar`, `arcPath`, `icon`, `extLink`, `sectionNav`. Неиспользуемый экспорт валит `check.js`.
- `GV.util` (`js/util.js`) — `h`, `svg`, `formatNumber` (запятая), `onVisible`, `rovingTabs`, `prefersReducedMotion`, `uid`.
- `GV.tweaks` (`js/tweaks.js`) — `{ scale: 0.9|1|1.1|1.25, paper: ledger|graph|tracing }` в localStorage `gv.tweaks`;
  применяет `--ui-scale` и `html[data-paper]`, шлёт событие `gv:tweaks`. Панель видна при `html[data-tweaks="on"]`.

## CSS

Порядок в `index.html`: `fonts` → `tokens` → `base` → `motion` → `page` → `gauge` → `hero` → `shift` → `dial` →
`operations` → `ledger` → `schema` → `tweaks`. Токены — `tokens.css`, правила мира — `DESIGN.md` в корне.

## Правила

- Движение только `transform` и `opacity` (проверяет `check.js`); один rAF-цикл; геометрия кэшируется на resize.
- Размеры в `rem` (масштаб Tweaks через `--ui-scale`); `px` — только линии 1px, медиазапросы и `fonts.css`;
  `vh/svh` — высоты закреплённых сцен. Кегли внутри SVG — атрибутом `font-size` в единицах viewBox.
- `prefers-reduced-motion: reduce`: нет закреплений и потока строк, ролик заменён двумя кадрами, всё сразу
  в конечном состоянии.
- Без ES-модулей, CDN, npm и `fetch` локальных файлов; пути относительные.
- Интерактив — нативные `<button>/<a>/<input>` или ARIA-роль с клавиатурой; видимый `:focus-visible`; ссылка
  в новой вкладке — через `GV.kit.extLink`.
- Заголовки листов 3–6 слов, ни одной выводимой строки длиннее 140 символов, над заголовком нет надзаголовка.
- Факты только из `README.md`, `PRODUCT.md`, `app/`; при расхождении верен код (ADR 0003).
- Лицензия проприетарная: «open source», «MIT», «бесплатно» запрещены.

## Проверки и медиа

- `node site/tests/check.js` — факты, пути и медиа, запрещённые слова, модули в `index.html`, 8 листов, длина
  строк, типографика, px, анимации не по transform/opacity.
- `node site/tests/components.test.js` — калибровка, зоны, EMA, `spring` и reduced motion, угол курсора,
  ролик и шкала смены, шаги операций, время строк журнала и общее показание.
- Ролик листа 02 — `site/assets/video/README.md`. Без Range-запросов (`python -m http.server`) видео стоит на кадре 0.
