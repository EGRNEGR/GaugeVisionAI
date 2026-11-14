# Архив: три варианта лендинга (A «Пульт», B «Циферблат», C «Протокол»)

С 14.11.2026 сайт в `site/` — одна страница на основе варианта B («Циферблат»), без переключателя
вариантов. Здесь лежит то, что ушло со страницы, чтобы это можно было достать.

| Файл | Что это |
|---|---|
| `js/variants/a.js`, `css/variant-a.css` | вариант A «Пульт» |
| `js/variants/c.js`, `css/variant-c.css` | вариант C «Протокол» |
| `js/variants/b.js`, `css/variant-b.css` | прежний вариант B — его стили и разметка переехали в `site/js/page.js` и `site/css/page.css` |
| `js/app.js` | роутер вариантов `GV.app`: `?v=`, `localStorage gv.variant`, студийная панель `#gv-studio` |
| `js/components/hero-stage.js` | компонент `heroStage`: растровые скриншоты в hero |
| `assets/dashboard-real.png`, `assets/smartphone-client.png` | скриншоты пульта оператора и клиента на смартфоне |

## Как вернуть три варианта целиком

Файлы выше работают только вместе с общими файлами той же версии (`index.html`, `content.js`,
`kit.js`, `tweaks.js`, `tokens.css`, `base.css`, `components.css`): контент и раскладки компонентов
с тех пор ужаты. Поэтому целиком возвращается вся папка `site/` из коммита до этой сборки:

```
git checkout 90ba425 -- site/
```

Последний коммит, где три варианта работают, — `90ba425` («Autopilot: план сборки»).
Открыть: `site/index.html` двойным кликом, вариант — `site/index.html?v=a|b|c`.

## Как достать один кусок

- Скриншоты: скопировать `assets/*.png` в `site/assets/` и подключить через `<img>` с `alt`.
- Вариант A или C отдельной страницей: вернуть `site/` из `90ba425` в отдельную папку
  (`git worktree add ../gv-variants 90ba425`) и открыть там `site/index.html?v=a`.
