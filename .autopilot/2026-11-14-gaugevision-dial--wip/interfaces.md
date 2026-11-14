# Интерфейсы и правила проекта

Читается каждым исполнителем первым. Имена — английские, тексты на сайте — русские. Рабочая папка — worktree `C:/Hakatons/GaugeVisionAI/worktrees/gaugevision-dial` (команды — из её корня). Карта текущего кода — `notes.md` рядом.

## Правила проекта

1. **Факты.** Только из `README.md`, `PRODUCT.md`, кода в `app/` и `notes.md` прошлой сборки (`.autopilot/2026-11-14-gaugevision-landing/notes.md`, раздел «Расхождения README ↔ код»). Ни одной выдуманной метрики, функции, клиента, контакта. Сомневаешься — не пиши.
1a. **Код главнее README** (`docs/adr/0003-kod-glavnee-readme.md`):
   - перспективу правит **аффинное** выпрямление эллипса в круг 640 px (`roi_from_ellipse`, `warpAffine`); **гомографии в коде нет** — она в roadmap; слов «гомография» и «субпиксельный» на сайте нет, кроме roadmap;
   - стрелка: ведущий метод — радиальный момент (гистограмма 1°, сглаживание ±4°, уточнение взвешенным круговым средним ±6°), HoughLinesP уточняет при расхождении ≤ 12°; маски Black-Hat / Top-Hat (ядро 31×31);
   - CLAHE (clip 3,0, сетка 8×8) — только при локализации циферблата;
   - смартфон без кадров: через 6 с — «переподключение», через 30 с — «офлайн»; калибровка допускает выход за шкалу ±5 %.
   **Не публиковать:** «34 проверки e2e / 18 браузерных», «ответ сервера 3–37 мс».
2. **Лицензия проприетарная.** Никаких «open source», «MIT», «бесплатно», «скачайте и запустите».
3. **Контакты — только GitHub EGRNEGR** (`https://github.com/EGRNEGR/GaugeVisionAI`). 50 и 100 камер — всегда с меткой «расчёт», 25 камер — «замер».
4. **Русская типографика.** « — » с пробелами по пунктуации; дефис только внутри слов; диапазоны «30–100»; десятичная запятая; неразрывный пробел между числом и единицей (это делает `typo()` в `content.js`).
5. **Статика без сборки.** Только классические `<script src>`; никаких `import`/`export`, `type="module"`, CDN, npm, `fetch` локальных файлов. Работает по `file://` двойным кликом.
6. **Только относительные пути.**
7. **Размеры в `rem`** (масштаб Tweaks через `--ui-scale`); `px` — только линии 1px и медиазапросы; `vh`/`vw`/`svh` допустимы для высот закреплённых сцен.
8. **Движение — только `transform` и `opacity`.** Ни `clip-path`, ни `stroke-dashoffset`, ни `width/height/top/left`, ни `filter`, ни `background-position` в анимациях и переходах. Пятна света двигаются `transform`, а не CSS-переменными в градиенте. Пассивные слушатели scroll; один rAF-цикл (`GV.motion`); геометрия кэшируется на resize, не читается в кадре.
9. **`prefers-reduced-motion: reduce`** — нет закреплений, инерции, reveal и счётчиков: всё видно сразу в конечном состоянии; видео заменено постером; стрелка сразу на значении.
10. **Доступность.** Интерактив — нативные `<button>`/`<a>`/`<input>` или ARIA-роль с клавиатурой; видимый `:focus-visible`; порядок Tab совпадает с визуальным (слева направо, сверху вниз); ссылка в новой вкладке — с пометкой (иконка + визуально скрытое «откроется в новой вкладке»).
11. **Минимум текста.** Заголовки секций 3–6 слов. Ни одного текстового блока длиннее 140 символов на отрисованной странице. Подписи — цифры, формулы, условия замера одной строкой.
12. **Без мёртвых элементов и заглушек.** Ни одной кнопки или ссылки, которая ничего не делает; ни одного «TODO».

### Договорились с пользователем (прошлая сборка, слово в слово)

- Аудитория лендинга — «Все сразу, жюри в приоритете»
- Контакты — «Только GitHub EGRNEGR»; других контактов на сайте нет
- Стек сайта — «Статика HTML/CSS/JS», без сборки, работает по file://
- Демо-видео и развёрнутого стенда нет: главная кнопка → GitHub
- При расхождении README и кода сайт пишет как в коде; «34/18 проверок» и «3–37 мс» не публикуются

Пересмотрено пользователем в этой сборке: три варианта → один (B), переключатель удалён, Tweaks урезаны до масштаба и шрифта, светлый фон «Бумага» больше не нужен (фон — обсидиан #090B0E).

## Окружение и команды

- Windows 11, Git Bash. `python3` — заглушка: `python` (3.14) или `node`.
- ffmpeg 7.1: `F="C:/Users/Egoru/AppData/Local/Programs/Python/Python314/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"`. ffprobe нет — `"$F" -i файл` печатает параметры.
- Проверки (из корня worktree): `node site/tests/check.js && node site/tests/components.test.js`.
- Визуальная проверка: Playwright MCP блокирует file:// — поднять `python -m http.server 8765 --directory site` в фоне (порт занят → 8766) и открыть `http://localhost:8765/`; или `playwright-core` из кэша npx (`find ~/AppData/Local/npm-cache/_npx -name playwright-core -maxdepth 4`). Ширины 1440×900 и 390×844. Скриншоты — в `~/tmp`, не в репозиторий.
- Дизайн-скиллы: перед работой над UI прочитай `~/skills/tactical-hud-web-design/SKILL.md` и из `~/skills/impeccable/` — `SKILL.md` и reference-файлы про distill, animate, polish (имена найди `ls reference/`). Ориентиры — `references/*.png` и видео `references/gauge_pullback.mp4`.
- Не трогать: `app/`, `static/`, `references/`, `docs/gemini_*` (читать и брать как источник можно).

## Границы, решённые в спецификации

### Структура `site/` после сборки

```
site/
├── index.html                 <html lang="ru">, #gv-root, панель Tweaks, noscript, скрипты; шапку и секции рисует GV.page
├── design-system.md           правила дизайна этой страницы (обновить под обсидиан и движение)
├── css/
│   ├── fonts.css              @font-face (оставить Onest, IBM Plex Mono, Manrope, IBM Plex Sans; JetBrains Mono — можно убрать вместе с файлами)
│   ├── tokens.css             :root-токены обсидиана + [data-font] + --ui-scale (без [data-bg], без вариантов)
│   ├── base.css               reset, типографика, утилиты (без #gv-studio)
│   ├── motion.css             .gv-reveal, .gv-spot (spotlight), .gv-telemetry — общие классы движения
│   ├── components.css         раскладки оставшихся компонентов: metrics, compare, architecture, limits (только используемые layout)
│   ├── hero.css               #hero: scroll-video + HUD (тикет hero)
│   ├── dial.css               #reading: прецизионный прибор (тикет hero)
│   ├── track.css              #pipeline: горизонтальный трек (тикет конвейера)
│   ├── page.css               шапка, секции, contact, футер, ритм — бывший variant-b.css без префикса
│   └── tweaks.css
├── js/
│   ├── content.js             GV.content
│   ├── util.js                GV.util (без изменений контрактов)
│   ├── motion.js              GV.motion — новый
│   ├── components/
│   │   ├── kit.js             GV.kit (heroStage/crop/demoLink можно удалить, если не используются)
│   │   ├── scroll-video.js    GV.components.scrollVideo — новый
│   │   ├── precision-dial.js  GV.components.precisionDial — новый
│   │   ├── pipeline-track.js  GV.components.pipelineTrack — новый
│   │   ├── metrics.js, compare.js, architecture.js, limits.js
│   ├── page.js                GV.page — строит страницу; подключается предпоследним
│   └── tweaks.js              GV.tweaks; до page.js — применяет атрибуты до рендера
├── assets/
│   ├── video/gauge_pullback.mp4         оригинал, побайтно = references/gauge_pullback.mp4
│   ├── video/gauge_pullback.scrub.mp4   1280×720, keyint ≤ 2, без звука, faststart
│   ├── video/gauge_pullback.scrub-m.mp4 854×480, то же
│   ├── video/README.md                  команды ffmpeg, откуда исходник
│   ├── img/poster.jpg                   первый кадр видео, ≤ 250 КБ
│   ├── img/boiler-hall.jpg              docs/gemini_art/gaugevision_hero.jpg, ≤ 350 КБ, ширина 1920
│   ├── img/favicon.svg
│   └── fonts/*.woff2
└── tests/check.js, components.test.js
archive/site-variants-a-c/      вне site/: a.js, c.js, variant-a.css, variant-c.css, app.js (роутер), hero-stage.js, скриншоты dashboard-real.png и smartphone-client.png, README.md «как вернуть»
```

Порядок скриптов: `content.js` → `util.js` → `motion.js` → `components/kit.js` → `components/*.js` → `tweaks.js` → `page.js`. Каждый файл — IIFE, дописывает в `window.GV`.

### `GV.content` — поля этой сборки

Существующие поля не переименовывать (на них опирается `check.js`). Добавить/заменить:

```js
sections: [ // ровно 8, в этом порядке; title 3–6 слов
  { id:'hero', index:'01', nav:'Суть' }, { id:'reading', index:'02', nav:'Показание', title },
  { id:'pipeline', index:'03', nav:'Конвейер', title }, { id:'metrics', index:'04', nav:'Замеры', title },
  { id:'compare', index:'05', nav:'Было → Стало', title }, { id:'architecture', index:'06', nav:'Архитектура', title },
  { id:'limits', index:'07', nav:'Ограничения', title }, { id:'contact', index:'08', nav:'GitHub', title } ],
hero: { kicker, title, line, scrollLabel,           // title 3–6 слов, line ≤ 90 символов
        video:{ src:'assets/video/gauge_pullback.scrub.mp4', srcMobile:'assets/video/gauge_pullback.scrub-m.mp4',
                poster:'assets/img/poster.jpg', label } },   // label — aria-описание видео
reading: { theta:253.4, device, caption },           // 4,39 МПа считается из theta по calibration, не хранится строкой
pipelineCards: [ // ровно 4, порядок брифа
  { id:'locate', index:'01', title, formula:[...], params:[{name,value}], latency:{ value, unit, note } | null } , … ],
pipelineTotal: { value:'30–100', unit:'мс/кадр', label },
contact: { title, links:[{id:'repo', label, href:REPO, primary:true}, {id:'license', …}] } // только GitHub-ссылки
```

`hero.stage`, `hero.lead`, `hero.chain`, `hero.cta*` и `screenshotFacts.dashboard/phone` удалить вместе с `heroStage`. Длинные `lead`/`what`/`why`/`text` либо удалить, либо сжать до ≤ 140 символов; `check.js` сверяет числа во всех оставшихся.

### `GV.motion` (js/motion.js) — владелец: тикет фундамента

```js
GV.motion = {
  reduced(),                         // bool, следит за matchMedia
  onFrame(fn(dt, now)) → off,        // общий rAF; цикл спит, когда подписчиков нет; dt в секундах, ≤ 1/20
  onScroll(fn(scrollY)) → off,       // пассивный scroll + resize, вызывается в rAF не чаще кадра
  measure(el) → { top, height },     // кэш на resize (документные координаты)
  pinProgress(sectionEl) → 0..1,     // прогресс закреплённой секции: 0 — верх секции у верха экрана, 1 — низ секции у низа
  spring({ stiffness=170, damping=18, mass=1, value=0 }) → { target(v), set(v), step(dt) → value, value(), settled() },
  reveal(rootEl, selector='[data-reveal]') → off,   // слова/элементы входят каскадом, шаг 60 мс, IntersectionObserver, once
  counter(el, { to, digits, display, duration=1200 }) → off,  // по видимости; конечный текст — display
  spotlight(rootEl, selector) → off  // слой .gv-spot__light внутри карточки двигается transform за курсором
};
```

При `reduced()`: `pinProgress` → 1, `reveal`/`counter` сразу ставят конечное состояние, `spring.step` возвращает цель.

### Компоненты: `GV.components.<name>.mount(el, options) → { destroy() }`

- `scrollVideo` — `#hero`: ставит `<video muted playsinline preload="auto" disablepictureinpicture>`, источник по `matchMedia('(max-width: 768px)')`, постер; HUD (`kicker`, `h1` = `hero.title`, `line`, индикатор прокрутки с `transform: scaleY` прогресса). Цель `currentTime = pinProgress × (duration − 0,05)`, инерция: `cur += (target − cur) × 0.12`, запись `currentTime`, только если `!video.seeking` и разница > 1/60 с. Ошибка видео или `reduced()` → только постер, секция `data-static`. Цикл спит вне экрана. `options` нет.
- `precisionDial` — `#reading`: SVG прибора (шкала 0–10 МПа из `calibration`, риски 100/20/11, зоны из `setpoints`, ободок-металл, стеклянный блик), стрелка на `GV.motion.spring`. Цель: `pinProgress` → θ от `thetaMin` до `reading.theta`; наведение → угол курсора, зажатый в шкалу; клавиши ←/→ (шаг 0,1 МПа), Home/End на фокусированном приборе (`role="slider"`, `aria-valuemin/max/now/text`). Выводит `value` МПа, бар (`kit.toBar`), θ, зону (`kit.zoneOf`, подписи «НОРМА / ПРЕДУПРЕЖДЕНИЕ / CRITICAL»), всё `tabular-nums`. Опции `{ interactive = true }`. Возврат `{ destroy, setValue(v) }`.
- `pipelineTrack` — `#pipeline`: 4 карточки `pipelineCards`, сцена sticky, трек `translateX`, активный шаг по прогрессу (индикатор `01 02 03 04` — кнопки, клик прокручивает к шагу), связь между карточками растёт `scaleX`, итог `pipelineTotal`. Телефон: карточки 85vw. `reduced()`: вертикальный список. Возврат `{ destroy }`.
- `metrics`, `compare`, `architecture`, `limits` — существующие (контракт из `notes.md` §2.4), оставить по одной раскладке (B: `dial`, `toggle`, `auto`, `cards`), лишние layout-ветки удалить; тексты сжать по правилу 11; движение — через `GV.motion` (счётчики, spotlight, импульсы по рёбрам архитектуры через `transform`).

### `GV.page` (js/page.js) — владелец: тикет фундамента

`GV.page = { render(root) → cleanup }`, вызывается сам на `DOMContentLoaded`. Строит: шапку (лого, навигация по 8 якорям через `GV.kit.sectionNav`, один пункт «GitHub» — ссылка на репозиторий в новой вкладке с пометкой), полосу телеметрии `.gv-telemetry` (полоса `scaleX` + моно «NN / 08 · NNN %»), `<section id>` для каждой записи `sections` (eyebrow `index`, заголовок `title` с `data-reveal`), монтирует в секцию её модуль из таблицы `GV.page.mounts = { hero:'scrollVideo', reading:'precisionDial', pipeline:'pipelineTrack', metrics:'metrics', compare:'compare', architecture:'architecture', limits:'limits' }`, contact и футер рисует сам. Если `GV.components[name]` нет — `console.error` и секция с заголовком без содержимого (это ошибка сборки, не режим работы; `check.js` проверяет, что все модули из `mounts` подключены). Битый `location.hash` (`#%E0`) не роняет страницу.

### `GV.tweaks` — урезанный

Состояние `{ font:'auto'|'manrope'|'onest'|'plex', scale:0.9|1|1.1|1.25 }`, localStorage `gv.tweaks` (лишние старые ключи игнорируются). Применение: `html[data-font]`, `--ui-scale`, событие `gv:tweaks`. Панель — плавающая кнопка «Tweaks» в углу, не перекрывает HUD hero.

### Токены (css/tokens.css)

Сохранить имена из прошлой сборки (`--bg-canvas --bg-surface --bg-elevated --border-hairline --border-strong --text-primary --text-muted --text-faint --accent --accent-contrast --status-ok --status-warn --status-alert --font-sans --font-display --font-mono --ui-scale --radius-s --radius-m --space-1…--space-8 --ease-out`). `--bg-canvas: #090B0E`. Добавить: `--edge-light` (верхний блик 1px), `--glow-warm`, `--glow-cool` (направленные пятна, низкая непрозрачность), `--ease-spring`. Акцент — `#FF5A1F` (стрелка); статусы приглушённые, без кислотного неона; контраст текста ≥ 4,5 : 1.

### Шов тестов

`node site/tests/check.js` (код выхода 0 — зелёно):
1. Числа во всех строках `GV.content` (кроме `SKIP_KEYS` и `screenshotFacts`) — в README / PRODUCT / `app/config.py` / notes прошлой сборки (путь к notes искать по папкам `.autopilot/*gaugevision-landing*`).
2. Локальные `src`/`href` в `index.html` и `content.js` существуют; видео-файлы существуют.
3. Запрещённые слова в `site/` (кроме `tests/`, `design-system.md`): «open source», «opensource», «MIT», «lorem», «TODO», «FIXME», «бесплатно», «гомограф» вне `roadmap`, «субпиксел».
4. Нет `import `/`export `/`type="module"` в `js/`.
5. `sections` — ровно 8 `id` в порядке `hero, reading, pipeline, metrics, compare, architecture, limits, contact`; у каждого модуля из `GV.page.mounts` есть `<script>` в `index.html`.
6. Нет `js/variants/`, `app.js`, `#gv-studio`, `gv.variant`.
7. Ни одна строка `GV.content`, которая выводится на страницу (кроме `alt`/`label` для ARIA), не длиннее 140 символов; `sections[].title` — 3–6 слов.
8. Типографика (как была).

`node site/tests/components.test.js` — расчёты калибровки/зон/EMA, плюс `GV.motion.spring` сходится к цели и не расходится при dt = 1/20.

## Что построили

<!-- исполнители дописывают сюда после тикета: файл — что экспортирует — заметка -->
