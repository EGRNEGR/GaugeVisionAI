# GaugeVision AI 3.0 (v5) на Tilda

Версия сайта для Tilda собирается скриптом `tilda/v5/build.mjs` напрямую из автономного исходника `site/v5/`. Файлы в `tilda/v5/dist/` генерируются автоматически; любые правки вносятся только в `site/v5/`, после чего выполняется пересборка.

- Проект Tilda: `7124340` (`https://gaugevs.tilda.ws`)
- Страница v5 (3.0 в дизайне «Сменный журнал обхода»): `424686809` (`/gaugevision-3`), назначена главной (`indexpageid = 424686809`)
- Резервная страница отката (старая v3 с содержанием 2.0): `409200509` (`/gaugevision`), не изменялась и не удалялась
- Номера блоков и контрольные суммы MD5: [`records.json`](records.json)
- Карта внешних ресурсов CDN: [`assets.json`](assets.json)

## 1. Архитектура переноса

| Место на странице `424686809` | Содержимое | Объём |
|---|---|---|
| `<head>` страницы (`dist/head.html`) | `theme-color`, `color-scheme`, `preload` двух кириллических шрифтов, ранний скрипт (`html.gvt-page`, Tweaks), `@font-face` для 11 файлов `.woff2`, правила уровня страницы (`html.gvt-page body`, линовка, красное поле, `#gv-root:empty{min-height:100vh}`) | 6,4 КБ |
| Блоки `01`–`03` (`tplid 1370`) | Весь CSS из `site/v5/css/` с префиксом `.gvt` (3 чанка, минифицировано `esbuild`) | 30,0 / 30,1 / 11,0 КБ |
| Блоки `04`–`05` (`tplid 1370`) | Данные `GV.content` после типографа (разделены на два чанка), функция `typo()` и `util.js` | 26,9 / 24,7 КБ |
| Блоки `06`–`08` (`tplid 1370`) | `motion.js`, `optimizer-core.js`, `kit.js`, `draw.js`, все 11 секционных модулей, `showcase.js`, `tweaks.js` | 25,5 / 32,0 / 32,4 КБ |
| Блок `09` (`tplid 1370`, `6307265201`) | Контейнер `<div class="gvt">` с `#gv-root`, ссылкой `.gv-skip`, `<noscript>`, `#gv-tweaks` и загрузчиком `page.js` | 5,1 КБ |

Ключевые инженерные решения:
- Все 9 блоков укладываются в безопасный предел `≤ 33 КБ` на один вызов Tilda MCP (`update_record`).
- Каждое CSS-правило изолировано префиксом `.gvt`, а глобальные правила (`body`, фон, линовка, красное поле) привязаны к классу `html.gvt-page`, который не выставляется в редакторе Tilda (`tilda.ru` / `tilda.cc` вне `/preview/`).
- У всех 9 блоков включён параметр `animationoff = "y"` и обнулены вертикальные отступы (`margintop = "0px"`, `marginbottom = "0px"`, включая `_res_480`), чтобы первые 8 стилевых и скриптовых блоков имели высоту `0 px`.
- Режим демонстрации (`showcase.js`) монтирует пульт `.gv-sc` внутрь `#gv-root` (внутри `.gvt`), поэтому все стили пульта работают без утечки за пределы `.gvt`.

## 2. Ресурсы CDN (`assets.json`)

- **Изображения (15 файлов `.jpg`):** размещены на CDN Tilda (`static.tildacdn.com`, переиспользованы по точному совпадению MD5 из `tilda/assets.json` и `tilda/v4/images.json`).
- **Шрифты (11 файлов `.woff2`) и видео смены (`shift.scrub.mp4`, `shift.scrub-m.mp4`):** раздаются через `cdn.jsdelivr.net` по закреплённому коммиту `c12b2a9` ветки `redesign/website-v5`.

## 3. Сборка и проверка на эмуляции

```bash
# Сборка локальной эмуляции (все ресурсы из site/v5/assets)
node tilda/v5/build.mjs --local

# Прогон браузерной приёмки на локальной эмуляции
node reports/website_redesign/evidence/scripts/accept_v5.mjs http://127.0.0.1:8707 reports/website_redesign/evidence/v5/emu

# Продакшен-сборка с адресами CDN Tilda и jsDelivr
node tilda/v5/build.mjs
```

## 4. Загрузка, публикация и откат

Загрузка выполняется через Tilda MCP (`migrated-settings_tilda`):

1. `update_page_head_code` — записать `tilda/v5/dist/head.html` в страницу `424686809` проекта `7124340`.
2. Для каждого из 9 блоков в `tilda/v5/records.json` вызвать `update_record` (`tab: "content"`, `only_field: "code"`) с содержимым `tilda/v5/dist/blocks/01.html`…`09.html`.
3. Проверить настройки страницы (`update_page_settings` / `get_page_settings`: заголовок, описание, `alias: "gaugevision-3"`, `animationoff: true`, `fb_imgfile`).
4. Вызвать `publish_page` для страницы `424686809` и прогнать проверку на живом адресе:
   ```bash
   node tilda/v5/scripts/probe_live.mjs https://gaugevs.tilda.ws/gaugevision-3 390 844
   node tilda/v5/scripts/probe_live.mjs https://gaugevs.tilda.ws/gaugevision-3 1440 900
   ```
5. Назначить страницу `424686809` главной: `update_project_settings` с единственным изменяемым полем `{ projectid: 7124340, indexpageid: 424686809 }`.

**Мгновенный откат на старую версию v3 (2.0):** вызвать `update_project_settings` с `{ projectid: 7124340, indexpageid: 409200509 }`. Страница `409200509` (`/gaugevision`) оставлена нетронутой.
