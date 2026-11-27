# Документация и доказательства сайта GaugeVision AI 3.0 (v4)

Материалы эволюции продуктового сайта GaugeVision AI от версий v2/v3 к версии **v4** под релиз `v3.0.0`.

- Рабочая ветка сайта: https://github.com/EGRNEGR/GaugeVisionAI/tree/redesign/website-v4
- Источник истины о продукте: тег https://github.com/EGRNEGR/GaugeVisionAI/releases/tag/v3.0.0 (коммит `0273436`) и ветка https://github.com/EGRNEGR/GaugeVisionAI/tree/GaugeVision-3.0
- Статус Tilda: на `https://gaugevs.tilda.ws/` (проект `7124340`, страница `409200509`) ничего не публиковалось; перенос описан в `TILDA_DEPLOYMENT_GUIDE.md` и выполняется только после отдельного разрешения.

## Локальный запуск сайта v4

Требуется только Node.js (без установки пакетов). Из корня worktree:

```bash
node reports/website_redesign/evidence/scripts/serve.mjs site/v4 8704
```

После запуска открыть:
- сайт: `http://127.0.0.1:8704/`
- режим демонстрации (проектор 16:9, 12 шагов, клавиша `D`): `http://127.0.0.1:8704/?showcase=1`
- панель настроек автора Tweaks: `http://127.0.0.1:8704/?tweaks`

## Оглавление отчётов (11 документов)

| № | Файл | Содержание |
|---|---|---|
| 1 | [`WEBSITE_AUDIT.md`](WEBSITE_AUDIT.md) | Аудит действующего сайта на Tilda (= v3), локальных версий v2, v3 и сводные замеры v4 |
| 2 | [`CREATIVE_DIRECTION.md`](CREATIVE_DIRECTION.md) | Главная мысль, визуальное направление, сюжет 15 секций, тон и подписи трёх типов изображений |
| 3 | [`CONTENT_STRATEGY.md`](CONTENT_STRATEGY.md) | Аудитории, правила работы с цифрами, список запрещённых формулировок, структура страницы и CTA |
| 4 | [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) | Палитра и контраст по WCAG 2.2, типографика, сетка, компоненты и требования доступности |
| 5 | [`INTERACTION_AND_MOTION.md`](INTERACTION_AND_MOTION.md) | Принципы движения, длительности и кривые, таблица взаимодействий и API модулей, замеры кадров |
| 6 | [`PRODUCT_CLAIMS_REGISTER.md`](PRODUCT_CLAIMS_REGISTER.md) | Реестр 50 продуктовых заявлений со ссылками на документы неизменяемого тега `v3.0.0` и проверка формулировок |
| 7 | [`SHOWCASE_MODE_GUIDE.md`](SHOWCASE_MODE_GUIDE.md) | Руководство докладчика по 12-шаговому режиму демонстрации на проекторе 16:9 и горячим клавишам |
| 8 | [`BROWSER_ACCEPTANCE_REPORT.md`](BROWSER_ACCEPTANCE_REPORT.md) | Инструментальная браузерная приёмка на 5 разрешениях, режимы `reduced-motion`, офлайн, Tweaks, проектор, интерактив и доступность |
| 9 | [`REDESIGN_COMPARISON.md`](REDESIGN_COMPARISON.md) | Сравнение «до и после» (опубликованный сайт = v3, v2, v4): метрики, коллажи первых экранов, сохранённое и изменённое |
| 10 | [`TILDA_DEPLOYMENT_GUIDE.md`](TILDA_DEPLOYMENT_GUIDE.md) | Техническое руководство переноса `site/v4` на Tilda через копию страницы и `tilda/build.mjs` (не выполнялось) |
| 11 | [`FINAL_WEBSITE_REPORT.md`](FINAL_WEBSITE_REPORT.md) | Итоговый отчёт: сводка работ, запуск, карта файлов, метрики с источниками, дизайн-аудит по 14 критериям и 10 ограничений сайта |

## Структура папки `evidence/`

| Папка | Содержимое |
|---|---|
| `evidence/audit/` | Сырые JSON-аудиты `published_audit.json`, `v2_audit.json`, `v3_audit.json`, `v4_audit.json` |
| `evidence/acceptance/` | Результаты браузерной приёмки `acceptance.json` и проверки интерактивных модулей `interact.json` |
| `evidence/screenshots/` | Коллажи `compare_first_1920x1080.jpg` и `compare_first_390x844.jpg`, подпапки `before/{published,v2,v3}/`, `after/`, `sections/`, `showcase/` |
| `evidence/recordings/` | 4 видеозаписи WebM (история `PI-102`, Store-and-Forward, оптимизатор бюджета, проход 12 шагов демонстрации на 1280×720) |
| `evidence/hero_cv_check/` | Проверка модуля `app/vision.py` на ролике первого экрана (`annotate.py`, `track.json`, `overlay_frames_0_80_160_230.jpg`) |
| `evidence/scripts/` | Воспроизводимые скрипты: `serve.mjs`, `audit.mjs`, `accept.mjs`, `interact.mjs`, `cls.mjs`, `herochk.mjs`, `record.mjs`, `collect.py`, `compare.py` |
