# Архитектура лендинга (`site/`)

Одна страница из восьми секций. Статика без сборки: классические `<script src>`, глобальный объект `window.GV`, работает по `file://`. Почему так — `docs/adr/`. Варианты A и C убраны в `archive/site-variants-a-c/` (там README «как вернуть»); роутера и переключателя вариантов нет.

## Поток данных

`GV.content` (данные) → `GV.page` (шапка, секции, телеметрия) → `GV.components.*` (содержимое секций) → `GV.motion` (кадр, прокрутка, пружина).

- `site/js/content.js` — `GV.content`, единственный источник фактов, без DOM. Существующие поля не переименовывать: на них опирается `check.js`. `sections` — ровно 8 записей `hero, reading, pipeline, metrics, compare, architecture, limits, contact`.
- `site/js/page.js` — `GV.page = { mounts, render(root) → cleanup }`; сам вызывается на `DOMContentLoaded`, рисует в `#gv-root`. Для каждой записи `sections` строит `<section id>` с eyebrow, заголовком `title` и монтирует модуль из `GV.page.mounts` (`hero:scrollVideo`, `reading:precisionDial`, `pipeline:pipelineTrack`, `metrics`, `compare`, `architecture`, `limits`). `contact` и футер рисует сам.
- Модуля нет или `mount` бросил — `console.error`, секция остаётся с заголовком; hero показывает статичный h1 на постере. Битый `location.hash` страницу не роняет.
- `<html>` несёт умолчания Tweaks (`data-font="manrope"`, `data-ambient="blueprint"`, `--ui-scale: 1.1`); inline-скрипт в `<head>` `index.html` до первой отрисовки перекрывает их `data-font`, `data-ambient` и `--ui-scale` из localStorage `gv.tweaks`, а `data-tweaks="on"` — по адресу с `?tweaks` или флагу `gv.tweaks.on` (кнопка Tweaks видна только автору, ADR 0010).

## Порядок скриптов (`site/index.html`)

`content.js` → `util.js` → `motion.js` → `components/kit.js` → `components/{scroll-video,precision-dial,pipeline-track,metrics,compare,architecture,limits}.js` → `tweaks.js` → `page.js` (последним). Каждый файл — IIFE, дописывает в `window.GV`. Новый компонент: файл, `<script>` до `tweaks.js`, строка в `GV.page.mounts`, `<link>` на его CSS.

## Модули

- `GV.motion` (`js/motion.js`) — `reduced`, `onFrame(fn(dt, now)) → off`, `onScroll`, `measure`, `viewport`, `pinProgress(sectionEl)` 0..1, `spring`, `reveal`, `counter`, `spotlight`, `cursorLight(lightEl)` (пятно фона за курсором; слой `.gv-ambient` создаёт `GV.page`, первый ребёнок пятна едет навстречу — сетка «Чертежа»), `shiftBelow(el, change, scopeEl)` (раскрытие без скачка: всё ниже `el` доезжает по `transform`), `magnet(el, { pull, max })` (кнопка тянется к курсору через `--mx/--my`). Единственный rAF-цикл: спит, когда подписчиков нет; `dt` ≤ 1/20 с. Чистые `reduced` и `spring` работают и без DOM (на них тест).
- `GV.components.<name>.mount(el, options) → { destroy() }`; BEM-классы `gv-<name>__*`. Данные берёт из `GV.content`, страница их не передаёт.
- `scrollVideo` (`#hero`) — видео перематывается по `pinProgress`: `currentTime` догоняет цель с инерцией, пишется только если `!video.seeking`. Источник по `max-width: 768px`. Ошибка видео или reduced motion — постер, `data-static` на секции. Экспорт `timeFor(progress, duration)`.
- `precisionDial` (`#reading`) — SVG-прибор, стрелка на `spring`; цель — прогресс прокрутки, затем курсор (`angleFromPointer`, `clampAngle`) или клавиши ←/→/Home/End (`role="slider"`). Возврат `{ destroy, setValue(v) }`.
- `pipelineTrack` (`#pipeline`) — 4 карточки `pipelineCards`, sticky-сцена, трек сдвигается `translateX`, индикатор шагов — кнопки. Reduced motion — вертикальный список.
- `metrics`, `compare`, `architecture`, `limits` — по одной раскладке, строки таблиц на линиях 1px; движение через `GV.motion` (счётчики, `shiftBelow` у компромиссов, импульсы по рёбрам).
- `GV.kit` (`components/kit.js`) — чистая математика калибровки (`angleToValue`, `valueToAngle`, `toBar`, `zoneOf`, `levelOf`, `emaStep`, `NBSP`; повторяет `app/vision.py`) и DOM-хелперы: `scope()` (`on/add/timeout/interval/frame/observe/destroy`, всё снимается в `destroy`), `onTweaks`, `polar`, `arcPath`, `icon`, `extLink`, `sectionNav`. Неиспользуемый экспорт `kit` валит `check.js`.
- `GV.util` (`js/util.js`) — `h`, `svg`, `formatNumber` (запятая), `onVisible`, `rovingTabs`, `prefersReducedMotion`. `rovingTabs` вызывает `onSelect` синхронно в конструкторе, до возврата.
- `GV.tweaks` (`js/tweaks.js`) — `{ font: auto|manrope|onest|plex, scale: 0.9|1|1.1|1.25, ambient: warm|blueprint|dial|obsidian }` (по умолчанию `manrope`, `1.1`, `blueprint`) в localStorage `gv.tweaks`; применяет `html[data-font]`, `html[data-ambient]` и `--ui-scale`, шлёт `document`-событие `gv:tweaks`. API `get / set / reset / open / close`. Панель — в `#gv-tweaks`, видна при `html[data-tweaks="on"]`; Shift + T переключает видимость.

## CSS

Порядок в `index.html`: `fonts` → `tokens` → `base` → `motion` → `components` → `hero` → `dial` → `track` → `page` → `tweaks`. `components.css` — раскладки metrics/compare/architecture/limits; `motion.css` — общие `.gv-reveal`, `.gv-spot`, `.gv-telemetry`. Верх закреплённых сцен — `--pin-top` (задан в `hero.css`, читает `dial.css`).

Токены (`tokens.css`): `--bg-canvas` (#090B0E, обсидиан), `--bg-surface|elevated`, `--border-hairline|strong`, `--text-primary|muted|faint`, `--accent` (#FF5A1F, цвет стрелки), `--status-ok|warn|alert`, `--font-sans|display|mono`, `--ui-scale`, `--space-*`, `--radius-*`, `--ease-out|spring`, `--edge-light`, `--glow-warm|cool`. Только тёмная тема.

## Правила

- Движение только `transform` и `opacity`: никаких `clip-path`, `stroke-dashoffset`, `width/height/top/left`, `filter`, `background-position` в анимациях и переходах. Пятна света двигаются `transform`.
- Один rAF-цикл (`GV.motion`); scroll-слушатели пассивные; геометрия кэшируется на resize (`measure`), в кадре не читается.
- Размеры в `rem` (масштаб Tweaks через `--ui-scale`); `px` только для линий 1px, медиазапросов и `fonts.css`; `vh/svh` допустимы для высот закреплённых сцен.
- `prefers-reduced-motion: reduce`: нет закреплений, инерции, reveal и счётчиков; всё сразу в конечном состоянии; видео заменено постером; стрелка сразу на значении.
- Без ES-модулей (`import`/`export`, `type="module"`), CDN, npm и `fetch` локальных файлов; пути относительные.
- Интерактив — нативные `<button>/<a>/<input>` или ARIA-роль с клавиатурой; видимый `:focus-visible`; ссылка в новой вкладке — через `GV.kit.extLink`. Мёртвых кнопок и заглушек нет.
- Минимум текста: заголовки секций 3–6 слов, ни одной выводимой строки длиннее 140 символов.
- Факты только из `README.md`, `PRODUCT.md`, `app/`; при расхождении верен код (`docs/adr/0003-kod-glavnee-readme.md`). Каждое число из `content.js` сверяет `check.js`.
- Типографика: « — » с пробелами, диапазоны «30–100», десятичная запятая, неразрывный пробел перед единицей (его ставит `typo()` в `content.js`).
- Лицензия проприетарная: «open source», «MIT», «бесплатно» запрещены; не публиковать «34 проверки e2e / 18 браузерных» и «ответ сервера 3–37 мс».

## Проверки и медиа

- `node site/tests/check.js` — факты, пути и медиа, запрещённые слова, модули в `index.html`, 8 секций, отсутствие вариантов, длина строк, типографика, px, анимации не по transform/opacity.
- `node site/tests/components.test.js` — калибровка, зоны, EMA, `spring` и reduced motion, угол курсора прибора, время видео hero.
- Видео hero: `site/assets/video/` (оригинал + две копии для перемотки, каждый кадр ключевой) — команды ffmpeg в `site/assets/video/README.md`. Без Range-запросов (`python -m http.server`) видео стоит на кадре 0.
