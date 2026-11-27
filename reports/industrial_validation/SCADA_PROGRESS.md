# План и прогресс: REQ-API-07 — стыковка GaugeVision AI с реальной SCADA Ignition 8.3.10

Рабочий worktree: `.claude/worktrees/scada`, ветка: `next-gen/scada-ignition` (от `origin/GaugeVision-2.0`, коммит `94e646e`).
Лабораторный каталог Ignition вне репозитория: `C:\Hakatons\gv_scada_lab\ignition-8.3.10\`.

## План работ

| № | Этап | Статус | Примечание |
|---|---|---|---|
| 1 | Создание worktree `next-gen/scada-ignition`, сверка SHA-256 дистрибутива Ignition 8.3.10 | Выполнен | SHA-256 `e6bb3911…371bae88` совпал |
| 2 | Распаковка Ignition 8.3.10 + JRE и запуск `IgnitionGateway.exe -c .\data\ignition.conf` (без службы и UAC) | В работе | Ожидание готовности `http://localhost:8088` и commissioning от пользователя |
| 3 | Базовая регрессия тестов (`test_demo_dashboard`, `test_tracks_e2e`, `test_remediation_full`, `test_acceptance_independent`) на CPU | В работе | До внесения правок |
| 4 | Расширение карты регистров Modbus TCP с обратной совместимостью + `docs/MODBUS_REGISTER_MAP.md` + автотесты | Ожидает | Адреса 0–799 и 900–905 без изменений; 906–909 системные, 2000+ расширенный блок приборов |
| 5 | Настройка устройства Modbus TCP (Modbus Driver v2) в Ignition, подтверждение адресации и порядка слов | Ожидает | `127.0.0.1:15020`, Unit ID 1, read-only |
| 6 | Создание read-only тегов 36 приборов, системного блока и Expression-тегов («связь», «устарело», «нет данных»), экспорт JSON | Ожидает | Папка `GaugeVision`, сохранение в `integrations/ignition/` |
| 7 | Построение мнемосхемы Perspective «GaugeVision — пульт» (ISA-101, 36 плиток, статус шлюза, системные счётчики, тренд) | Ожидает | Проект `GaugeVisionLab` |
| 8 | Испытания обмена (включая ≥ 30 мин сверки журналов SCADA vs GaugeVision, живые изменения, STALE/NaN, обрыв/восстановление, freeze heartbeat, S&F 904/905) и скриншоты Playwright 1920×1080 | Ожидает | Все артефакты в `reports/industrial_validation/evidence/scada/` |
| 9 | Повторная регрессия тестов, сборка отчёта `SCADA_INTEGRATION_REPORT.md`, пересчёт матрицы 75 требований (без правки REQ-CV-05), коммиты и публикация ветки | Ожидает | Без модификации `main`, `GaugeVision-2.0`, `reports/audit/`, `reports/remediation/`, `app/vision.py` |

## Хронология

- **2026-11-27 10:02** — создан worktree `.claude/worktrees/scada` на ветке `next-gen/scada-ignition` от `origin/GaugeVision-2.0` (`94e646e`).
- **2026-11-27 10:03** — проверен SHA-256 архива `Ignition-windows-x86-64-8.3.10.zip`, распакованы дистрибутив и встроенная JRE в `C:\Hakatons\gv_scada_lab\ignition-8.3.10\`.
- **2026-11-27 10:05** — запущен консольный процесс `IgnitionGateway.exe -c .\data\ignition.conf` и базовый прогон регрессионных тестов на CPU.
