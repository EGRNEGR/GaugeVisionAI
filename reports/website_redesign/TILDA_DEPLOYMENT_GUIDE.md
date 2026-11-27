# Публикация сайта GaugeVision AI 3.0 (v5) на Tilda

**Статус: опубликовано и назначено главной страницей (`28.11.2026`).**

- Главный адрес сайта: `https://gaugevs.tilda.ws/` (проект `7124340`, `indexpageid = 424686809`)
- Прямой адрес страницы v5: `https://gaugevs.tilda.ws/gaugevision-3` (страница `424686809`)
- Резервная страница отката (старая v3 с содержанием 2.0): `https://gaugevs.tilda.ws/gaugevision` (страница `409200509`, не изменялась и не удалялась)
- Сборщик и манифесты: [`tilda/v5/`](../../tilda/v5/README.md) (`build.mjs`, `assets.json`, `records.json`, `scripts/probe_live.mjs`)

## 1. Архитектура публикации

Для публикации переиспользована существующая страница `424686809` (`/gaugevision-3`), ранее содержавшая 8 блоков отклонённой тёмной v4. В сборке v5 код уложен в `<head>` страницы и **9 Vibe-блоков (`tplid 1370`)** — добавлен 9-й блок `6307265201` после `6306430801`. Все блоки укладываются в лимит `≤ 33 КБ` на вызов MCP.

| Место | ID блока | Файл в `tilda/v5/dist/` | Размер | Содержимое |
|---|---|---|---|---|
| `<head>` страницы | — | `head.html` | 6,4 КБ | `theme-color`, `preload` шрифтов, скрипт `html.gvt-page` и Tweaks, `@font-face` (11 `.woff2`), правила `body` и линовки |
| Блок 01 | `6306427101` | `blocks/01.html` | 30,0 КБ | CSS чанк 1 (префикс `.gvt`, минификация `esbuild`) |
| Блок 02 | `6306429901` | `blocks/02.html` | 30,1 КБ | CSS чанк 2 (префикс `.gvt`) |
| Блок 03 | `6306430001` | `blocks/03.html` | 11,0 КБ | CSS чанк 3 (префикс `.gvt`) |
| Блок 04 | `6306430101` | `blocks/04.html` | 26,9 КБ | `GV.content` чанк 1 (`src`, `panel`, `forecast`, `catalog`, `fleet`, `meta`, `sections`, `hero`…`diagnostics`) |
| Блок 05 | `6306430201` | `blocks/05.html` | 24,7 КБ | `GV.content` чанк 2 (`forecastSection`…`labels`), `typo()`, `util.js` |
| Блок 06 | `6306430601` | `blocks/06.html` | 25,5 КБ | `motion.js`, `optimizer-core.js`, `kit.js`, `draw.js` |
| Блок 07 | `6306430701` | `blocks/07.html` | 32,0 КБ | `journal.js`, `shift.js`, `multigauge.js`, `resilience.js`, `scada.js` |
| Блок 08 | `6306430801` | `blocks/08.html` | 32,4 КБ | `forecast.js`, `optimizer.js`, `metrics.js`, `evolution.js`, `limits.js`, `contact.js`, `showcase.js`, `tweaks.js` |
| Блок 09 | `6307265201` | `blocks/09.html` | 5,1 КБ | `<div class="gvt">`, `.gv-skip`, `#gv-root`, `<noscript>`, `#gv-tweaks`, `page.js` |

У всех 9 блоков выставлены `margintop: "0px"`, `margintop_res_480: "0px"`, `marginbottom: "0px"`, `marginbottom_res_480: "0px"`, `animationoff: "y"`. В результате первые 8 блоков имеют высоту `0 px`, а вся вёрстка рендерится внутри блока `6307265201`.

## 2. Настройки страницы `424686809` и проекта `7124340`

- **Страница `424686809`:** `title = "GaugeVision AI 3.0 — прибор пишет журнал сам"`, `alias = "gaugevision-3"`, `animationoff = true`, `fb_img = https://static.tildacdn.com/tila3262-6464-4261-b833-306634363339/shift-before.jpg`.
- **Проект `7124340`:** обновлено только поле `indexpageid = 424686809` (частичным вызовом `update_project_settings`); остальные параметры проекта не изменялись.
- **Внешние ресурсы (`tilda/v5/assets.json`):** 15 изображений `.jpg` раздаются с CDN Tilda (`static.tildacdn.com`, проверены по совпадению MD5), 11 шрифтов `.woff2` и 2 ролика `shift.scrub.mp4` / `shift.scrub-m.mp4` — с `cdn.jsdelivr.net` по закреплённому коммиту `c12b2a9` ветки `redesign/website-v5` (все проверены `HTTP 200`).

## 3. Команды пересборки и проверки

```bash
# 1. Локальная эмуляция Tilda
node tilda/v5/build.mjs --local

# 2. Продакшен-сборка (CDN Tilda + jsDelivr)
node tilda/v5/build.mjs

# 3. Проверка живой страницы (видео, шрифты, высота блоков, CLS)
node tilda/v5/scripts/probe_live.mjs https://gaugevs.tilda.ws/gaugevision-3 390 844
node tilda/v5/scripts/probe_live.mjs https://gaugevs.tilda.ws/gaugevision-3 1440 900

# 4. Полная браузерная и интерактивная приёмка живой страницы
PAGE=/gaugevision-3 node reports/website_redesign/evidence/scripts/accept_v5.mjs https://gaugevs.tilda.ws reports/website_redesign/evidence/v5/tilda --no-offline
node reports/website_redesign/evidence/scripts/interact_v5.mjs https://gaugevs.tilda.ws/gaugevision-3 reports/website_redesign/evidence/v5/tilda
```

## 4. Процедура отката

Чтобы мгновенно вернуть старую журнальную страницу v3 (`2.0`) в качестве главной:

```json
{
  "tool": "update_project_settings",
  "arguments": {
    "projectid": 7124340,
    "indexpageid": 409200509
  }
}
```

После этого `https://gaugevs.tilda.ws/` снова откроет нетронутую страницу `409200509` (`/gaugevision`), а версия v5 останется доступна по адресу `https://gaugevs.tilda.ws/gaugevision-3`.
