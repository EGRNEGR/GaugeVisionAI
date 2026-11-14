# Архитектура лендинга (`site/`)

Статика без сборки: классические `<script src>`, глобальный объект `window.GV`, работает по `file://`. Почему так — `docs/adr/`.

## Поток данных

`GV.content` (данные) → `GV.components.*` (рендер блоков) → `GV.variants.{a,b,c}` (страница из семи секций) → `GV.app` (выбор варианта).

- `site/js/content.js` — `GV.content`, единственный источник фактов, без DOM. Поля можно добавлять, переименовывать нельзя. Числа сверяет `site/tests/check.js` с `README.md`, `PRODUCT.md`, `app/config.py`; `screenshotFacts` не сверяется.
- Порядок скриптов задан в `site/index.html`: `content.js`, `util.js`, `components/kit.js` (первым среди компонентов), остальные `components/*.js`, `variants/*.js`, `tweaks.js`, `app.js` (последним). Каждый файл — IIFE с `window.GV = window.GV || {}`.
- Inline-скрипт в `<head>` `index.html` до первой отрисовки ставит `data-variant` и атрибуты Tweaks.

## Компоненты

- Контракт: `GV.components.<name>.mount(el, options) → { destroy() }`; имена — `heroStage, metrics, pipeline, compare, architecture, limits`; BEM-классы `gv-<name>__*`.
- `options.layout` выбирает вариант страницы; допустимые значения — в `.layouts` компонента; неизвестное значение → первое из списка. Данные компонент берёт из `GV.content`, вариант их не передаёт.
- `destroy()` снимает слушатели, observers, таймеры, rAF. Для этого есть `GV.kit.scope()` (`on/add/timeout/interval/frame/observe/destroy`), используй его и в вариантах.
- Компонент слушает `document`-событие `gv:tweaks` (смена `data-media`) и перерисовывает медиа (`GV.kit.onTweaks`).
- Раскладочный CSS компонентов — `site/css/components.css`; цвета и шрифты только через токены.
- `GV.kit` (`site/js/components/kit.js`) — общая математика калибровки (`angleToValue`, `zoneOf`, `emaStep`) и SVG-циферблат (`dial`); `GV.util` (`site/js/util.js`) — `h`, `svg`, `formatNumber` (запятая), `onVisible`, `rovingTabs`, `prefersReducedMotion`.
- Подписи интерфейса (заголовки столбцов, кнопки) живут в локальных объектах `T` внутри компонентов; факты — только из `GV.content`.

## Варианты

- `GV.variants.<a|b|c> = { id, label, render(root) → cleanup }`: «Пульт», «Циферблат», «Протокол»; префиксы классов `gva-*`, `gvb-*`, `gvc-*`.
- `render` строит header, семь секций с `id` `hero, metrics, pipeline, compare, architecture, limits, contact` в этом порядке, футер; монтирует компоненты и возвращает cleanup. Заголовки и навигация секций — `GV.content.sections`.
- Стили варианта — `site/css/variant-<id>.css` только под `[data-variant="<id>"]`. Вариант задаёт `--accent`, `--accent-contrast`, шрифты по умолчанию; новых фактов не добавляет.

## GV.app и GV.tweaks

- `site/js/app.js`: вариант выбирается по `?v=` → localStorage `gv.variant` → `a`. Студийная панель `#gv-studio` вне `#gv-root`. Переключение: cleanup старого → render нового → `history.replaceState` → прокрутка к той же секции. Событие `gv:variant`.
- `GV.app` определяется только после первого `render()`: внутри `render` брать вариант из `document.documentElement.dataset.variant`.
- `GV.util.rovingTabs` вызывает `onSelect` синхронно в конструкторе, до возврата `{select,index,destroy}`.
- `site/js/tweaks.js`: состояние `{font, bg, scale, media}` в localStorage `gv.tweaks`, применяется синхронно при загрузке (`html[data-font|data-bg|data-media]`, `--ui-scale`) и рассылается событием `gv:tweaks`. API: `get / set / reset / open / close`.

## Токены

`site/css/tokens.css`: `--bg-*`, `--border-*`, `--text-*`, `--accent`, `--status-ok|warn|alert`, `--font-*`, `--ui-scale`, `--space-*`, `--radius-*`, `--fs-*`, `--dur-*`. `[data-bg]` переопределяет фон и текст; `html[data-font][data-variant]` перебивает шрифты варианта. Все размеры в `rem`, `px` только для линий 1px и медиазапросов.

## Правила

- Факты только из `README.md`, `PRODUCT.md`, `app/`; при расхождении README и кода верен код (`docs/adr/0003-kod-glavnee-readme.md`).
- Метрики публикуются с условиями замера; не публиковать «34 проверки e2e / 18 браузерных» и «ответ сервера 3–37 мс».
- Лицензия проприетарная: слова «open source», «MIT», «бесплатно» запрещены.
- Русская типографика: « — » с пробелами, диапазоны через «–», десятичная запятая, неразрывный пробел перед единицей.
- Нет `import`/`export`, `type="module"`, CDN; пути только относительные.
- Интерактивное — нативные `<button>/<a>/<input>` с видимым `:focus-visible`; `prefers-reduced-motion` отключает необязательную анимацию; анимируются только `transform`/`opacity`; мёртвых кнопок и ссылок нет.
- Проверка: `node site/tests/check.js && node site/tests/components.test.js` (запускать из корня).
