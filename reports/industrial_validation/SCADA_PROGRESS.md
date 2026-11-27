# План и прогресс: REQ-API-07 — стыковка GaugeVision AI с реальной SCADA Ignition 8.3.10

Рабочий worktree: `.claude/worktrees/scada`, ветка: `next-gen/scada-ignition` (от `origin/GaugeVision-2.0`, коммит `94e646e`).
Лабораторный каталог Ignition вне репозитория: `C:\Hakatons\gv_scada_lab\ignition-8.3.10\`.

## План работ

| № | Этап | Статус | Примечание |
|---|---|---|---|
| 1 | Создание worktree `next-gen/scada-ignition`, сверка SHA-256 дистрибутива Ignition 8.3.10 | Выполнен | SHA-256 `E6BB3911…371BAE88` подтверждён |
| 2 | Распаковка Ignition 8.3.10 + JRE и запуск `IgnitionGateway.exe -c .\data\ignition.conf` (без службы и UAC) | Выполнен | Commissioning на `http://localhost:8088` выполнен пользователем (Ignition Standard 8.3.10 b2026100610, trial, `Sample_SQLite_Database`) |
| 3 | Базовая регрессия тестов (`test_demo_dashboard`, `test_tracks_e2e`, `test_remediation_full`, `test_acceptance_independent`) на CPU | Выполнен | 3/4 PASS полностью, в `test_acceptance_independent` 20/21 (прежде существовавший тайминг-флейк `auto_spec_generation_lifecycle` на `94e646e`) |
| 4 | Расширение карты регистров Modbus TCP с обратной совместимостью + `docs/MODBUS_REGISTER_MAP.md` + автотесты | Выполнен | Коммит `f0ce0e5`: адреса 0–799 и 900–905 без изменений; добавлены 906–911 и расширенный блок v2 `2000 + idx*8` |
| 5 | Настройка устройства Modbus TCP (Modbus Driver v2) в Ignition, подтверждение адресации и порядка слов | Выполнен | `GaugeVisionModbus` (`127.0.0.1:15020`, Unit ID 1, `zeroBasedAddressing=true`, `reverseWordOrder=false`, read-only) — статус `CONNECTED` |
| 6 | Создание read-only тегов 36 приборов, системного блока и Expression-тегов («связь», «устарело», «нет данных»), экспорт JSON | Выполнен | Коммит `b75d520`: 738 read-only тегов (`[default]GaugeVision/`), Tag Historian `Sample_SQLite_Database`, экспорт в `integrations/ignition/` |
| 7 | Построение мнемосхемы Perspective «GaugeVision — пульт» (ISA-101, 36 плиток, статус шлюза, системные счётчики, тренд) | Выполнен | Проект `GaugeVisionLab`, 4-канальный исторический тренд, визуально проверено на 1920×1080 |
| 8 | Испытания обмена (30,6 мин сверки журналов SCADA vs GaugeVision, живые изменения, STALE/NaN, обрыв/восстановление, freeze heartbeat, S&F 904/905) и скриншоты Playwright 1920×1080 | Выполнен | 1838,7 с, 11 124 запроса Modbus, 6 624 парных замера по 36 приборам: Good quality 100 %, статусы 100 %, NaN 100 %, ср. отн. расхождение 0,2775 % |
| 9 | Повторная регрессия тестов, сборка отчёта `SCADA_INTEGRATION_REPORT.md`, пересчёт матрицы 75 требований (без правки REQ-CV-05), коммиты и публикация ветки | Выполнен | `REQ-API-07 -> PASS`, итог 96,65 → 97,79 / 100 (`REQ-CV-05` оставлен `NOT VERIFIED`), Ignition остановлен, ветка опубликована |

## Хронология

- **2026-11-27 10:02** — создан worktree `.claude/worktrees/scada` на ветке `next-gen/scada-ignition` от `origin/GaugeVision-2.0` (`94e646e`).
- **2026-11-27 10:03** — проверен SHA-256 архива `Ignition-windows-x86-64-8.3.10.zip`, распакованы дистрибутив и встроенная JRE в `C:\Hakatons\gv_scada_lab\ignition-8.3.10\`.
- **2026-11-27 10:05** — запущен консольный процесс `IgnitionGateway.exe -c .\data\ignition.conf` и базовый прогон регрессионных тестов на CPU.
- **2026-11-27 10:15** — расширена карта регистров Modbus TCP v2 (`app/scada_gateway.py`, `docs/MODBUS_REGISTER_MAP.md`, `tests/test_modbus_register_map.py`, коммит `f0ce0e5`).
- **2026-11-27 10:40** — после commissioning пользователем в Ignition 8.3.10 настроено устройство `GaugeVisionModbus` (`CONNECTED`), импортировано 738 read-only тегов с Tag Historian, собрана мнемосхема Perspective `GaugeVisionLab` (коммит `b75d520`).
- **2026-11-27 10:54–10:57** — выполнены интерактивные сценарии проверки (Nominal, Cascade, S&F Outage 904/905, Heartbeat Freeze без обрыва TCP, реальный обрыв TCP и автовосстановление), сняты 9 скриншотов 1920×1080.
- **2026-11-27 10:59–11:30** — выполнен непрерывный 30,6-минутный прогон сверки журналов Ignition Tag Historian и GaugeVision по всем 36 приборам (1838,7 с, 11 124 запроса Modbus, 6 624 парных замера).
- **2026-11-27 11:30** — остановлен консольный шлюз Ignition, пересчитана матрица 75 требований (96,65 → 97,79 / 100), выполнена повторная регрессия, сформирован `SCADA_INTEGRATION_REPORT.md` и опубликована ветка `next-gen/scada-ignition`.
