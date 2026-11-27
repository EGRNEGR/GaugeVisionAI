# Отчёт о слиянии веток: GaugeVision AI 3.0

Ветка интеграции `next-gen/integration` создана от `next-gen/platform` и опубликована в `origin`. Защищённые
ветки не изменялись: `main` остался на dd25bde, `GaugeVision-2.0` — на 94e646e. Ветки агентов и их рабочие
каталоги не трогались; интеграция шла в отдельном каталоге `.claude/worktrees/integration`.

## 1. Исходные точки

| Ветка | Коммит | Содержание |
|---|---|---|
| `next-gen/platform` (основной агент) | 90dcadf | CV (REQ-CV-05), Multi-Gauge Vision, контракт данных v1.2, таблица `instruments`, HMI «Щит», исследование Auto Calibration (выключено) |
| `next-gen/analytics-validation` (Neon) | 285e896 | Ignition 8.3.10, карта Modbus v2, Predictive Analytics, ILP-оптимизатор, валидация на реальных данных, аудит безопасности; включает `next-gen/scada-ignition` и `next-gen/analytics-optimizer` |
| База слияния | 94e646e | `GaugeVision-2.0` |

Замечание: локальная `main` — dd25bde, а `origin/main` — b802681 (коммиты сайта). Расхождение существовало до
интеграции и не относится к ней; `main` не изменялся ни локально, ни в `origin`.

## 2. Способ слияния

`git merge --no-ff --no-commit origin/next-gen/analytics-validation`, конфликты разрешены по файлам, затем
коммит слияния c0d839c с двумя родителями — история обеих веток сохранена. Массовые стратегии `ours/theirs`
не применялись.

| Файл | Конфликт | Решение | Обоснование |
|---|---|---|---|
| `app/scada_gateway.py` | 6 участков | сторона Neon целиком | надмножество: тот же `place_instruments` (с проверкой `bool`), карта v2, прогнозный блок, очистка трёх блоков, `MAX_CLIENTS` |
| `app/db.py` | 1 участок в `init_db` | сторона platform | та же колонка `instrument_id` и индекс плюс `calibration_rev`, заполнение `instrument_id` для старых строк, колонки событий, основные приборы старых камер; таблицы Neon сливаются автоматически |
| `.gitignore` | 1 участок | сторона Neon | исключения для CSV-доказательств |
| `.autopilot/PROGRESS.md` | 1 участок | обе стороны | журнал двух направлений |

## 3. Семантическая проверка автослияния

- `app/main.py`: по AST нет повторов функций, классов и маршрутов (83 маршрута); оба вызова
  `update_from_instruments` берут `public_instruments()` — постоянные `modbus_slot` и приборы щита доходят до
  карты Neon.
- `static/index.html`: на пульте есть и вкладка «Щит», и секции `#predictiveSection` и `#optimizerSection`;
  в браузере проверено на трёх разрешениях (`HMI_ACCEPTANCE` в `TEST_RESULTS.md`).
- Контракт данных поднят с v1.2 до **v1.3** (`reports/next_generation/SHARED_DATA_CONTRACT.md` — рабочая спецификация, коммит `3272dcc`):
  - зафиксированы идентификаторы `instrument_id`, `source_id`, `gauge_slot`, `modbus_slot`, `calibration_rev` (проверены в `tests/test_final_integration.py`);
  - описаны поля события прогноза `prediction` (`imminent` / `cleared` / `realized` / `withdrawn`) и его доставка в MQTT;
  - зафиксировано продолжение прогнозного блока Modbus для слотов 61–199 (адреса 4096–5207, `MAX_REGISTERS = 5208`) и системные регистры `HR 905` (включая реальный отказ брокера), `HR 916` (4096) и `HR 917` (61).

## 4. Коммиты интеграционной ветки

| Коммит | Содержание |
|---|---|
| `c0d839c` | слияние веток `next-gen/platform` (`90dcadf`) и `next-gen/analytics-validation` (`285e896`) |
| `11c6d1a` | задачи после слияния и дефекты, найденные при приёмке (`DEF-INT-01..07`, сетевая политика `app/net_policy.py`) |
| `615a697` | независимый набор `tests/test_final_integration.py` и правки существующих наборов (`DEF-INT-08`) |
| `f3dea4d` | HR 905 при реальном отказе брокера (`DEF-INT-04`), корзины 30 с для ряда CV (`DEF-INT-13`), задержка event loop в `/api/health`, приоритет кода основного прибора (`DEF-INT-14`), правка шапки CSS |
| `3272dcc` | тест порядка слотов миграции по `created_at`, тест `cv_forecast_input`, контракт данных v1.3, обновление `README.md`, `MODBUS_REGISTER_MAP.md` и `DEMO_DEFENSE_GUIDE.md` |
| `bf09895` | стенды E2E/soak/HMI, промежуточные доказательства и отчёты приёмки |
| `660e87f` | доказательства 62-минутного soak-испытания (`evidence/soak/soak_results.json`) |
| финальные | исправление стартовой гонки `is_primary_dial` в стенде `run_e2e.py`, прогон 5 E2E с Ignition 8.3.10, доказательства post-soak/interop/offline/probe_lag, `build_rtm_final.py`, матрицы RTM и итоговые отчёты |

## 5. Регрессия сразу после слияния (c0d839c, до правок)

11 из 12 наборов прошли. `test_acceptance_independent` дал 20/21: проверка `auto_spec_generation_lifecycle`
зависела от гонки с фоновым циклом arch-sync (тот же плавающий тайминг отмечен в отчёте SCADA на 94e646e).
Дефект теста исправлен (DEF-INT-08), итоговая регрессия — в `TEST_RESULTS.md`.
