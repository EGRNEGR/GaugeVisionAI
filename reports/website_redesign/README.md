# Документация и доказательства сайта GaugeVision AI 3.0 (v5)

Материалы разработки, приёмки и публикации продуктового сайта **GaugeVision AI 3.0** (`site/v5`) в дизайне «Сменный журнал обхода» (`site/index.html` + `site/DESIGN.md`) под релиз `v3.0.0`. Тёмный промежуточный вариант `site/v4` отклонён владельцем проекта и сохранён в истории ветки `redesign/website-v4`.

- **Опубликованный сайт (главная на Tilda):** `https://gaugevs.tilda.ws/` (проект `7124340`, страница `424686809`, также доступна по `/gaugevision-3`)
- **Страница отката (старая v3 / 2.0):** `https://gaugevs.tilda.ws/gaugevision` (страница `409200509`, не изменялась)
- **Рабочая ветка сайта v5:** https://github.com/EGRNEGR/GaugeVisionAI/tree/redesign/website-v5
- **Источник истины о продукте:** тег https://github.com/EGRNEGR/GaugeVisionAI/releases/tag/v3.0.0 (коммит `0273436`) и ветка https://github.com/EGRNEGR/GaugeVisionAI/tree/GaugeVision-3.0

## Локальный запуск сайта v5

Требуется только Node.js (без установки пакетов). Из корня worktree:

```bash
node reports/website_redesign/evidence/scripts/serve.mjs site/v5 8705
```

После запуска открыть:
- сайт: `http://127.0.0.1:8705/`
- режим демонстрации (проектор 16:9, 12 шагов, клавиша `D`): `http://127.0.0.1:8705/?showcase=1`
- панель настроек автора Tweaks: `http://127.0.0.1:8705/?tweaks`

## Оглавление отчётов (11 документов)

| № | Файл | Содержание |
|---|---|---|
| 1 | [`WEBSITE_AUDIT.md`](WEBSITE_AUDIT.md) | Исходный аудит версий v2, v3 (старой Tilda) и v4 |
| 2 | [`CREATIVE_DIRECTION.md`](CREATIVE_DIRECTION.md) | Главная мысль, журнальное направление v5, сюжет 11 листов и маркировка материалов |
| 3 | [`CONTENT_STRATEGY.md`](CONTENT_STRATEGY.md) | Аудитории, правила работы с цифрами, запрещённые формулировки, карта 11 листов и CTA |
| 4 | [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) | Палитра и контраст по `site/DESIGN.md`, 4 шрифта, сетка, новые компоненты v5 и доступность |
| 5 | [`INTERACTION_AND_MOTION.md`](INTERACTION_AND_MOTION.md) | Принципы движения, длительности, таблица взаимодействий и `GV.api`, замеры прокрутки |
| 6 | [`PRODUCT_CLAIMS_REGISTER.md`](PRODUCT_CLAIMS_REGISTER.md) | Реестр 50 продуктовых заявлений со ссылками на документы неизменяемого тега `v3.0.0` |
| 7 | [`SHOWCASE_MODE_GUIDE.md`](SHOWCASE_MODE_GUIDE.md) | Руководство докладчика по 12-шаговому режиму демонстрации v5 на проекторе 16:9 |
| 8 | [`BROWSER_ACCEPTANCE_REPORT.md`](BROWSER_ACCEPTANCE_REPORT.md) | Браузерная и интерактивная приёмка v5 на локальном сервере, эмуляции Tilda и живом сайте |
| 9 | [`REDESIGN_COMPARISON.md`](REDESIGN_COMPARISON.md) | Сравнение старой v3 (2.0), отклонённой тёмной v4 и принятой журнальной v5 (3.0) |
| 10 | [`TILDA_DEPLOYMENT_GUIDE.md`](TILDA_DEPLOYMENT_GUIDE.md) | Руководство и отчёт публикации v5 на Tilda (9 блоков, назначение главной, откат на `409200509`) |
| 11 | [`FINAL_WEBSITE_REPORT.md`](FINAL_WEBSITE_REPORT.md) | Итоговый отчёт: сводка работ, запуск, карта файлов, метрики, дизайн-аудит по 14 критериям и ограничения |

## Структура папки `evidence/`

| Папка | Содержимое |
|---|---|
| `evidence/v5/local/` | Приёмка `site/v5` (`acceptance.json`, `interact.json`, снимки 5 разрешений, секций, Tweaks и 12 шагов демонстрации) |
| `evidence/v5/emu/` | Приёмка локальной эмуляции Tilda `tilda/v5/dist/local/` (`acceptance.json`, снимки) |
| `evidence/v5/tilda/` | Приёмка опубликованного сайта `https://gaugevs.tilda.ws/gaugevision-3` (`acceptance.json`, `interact.json`, снимки) |
| `evidence/scripts/` | Воспроизводимые скрипты: `serve.mjs`, `accept_v5.mjs`, `interact_v5.mjs` и архивные скрипты v4 |
| `evidence/audit/`, `acceptance/`, `screenshots/`, `recordings/`, `hero_cv_check/` | Архивные материалы аудита v2/v3 и отклонённой итерации v4 |
