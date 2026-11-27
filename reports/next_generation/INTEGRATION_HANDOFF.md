# Пакет передачи на комплексную интеграцию (Integration Handoff)

**Ветка передачи:** `next-gen/analytics-validation` (основана на `next-gen/analytics-optimizer` `6a1828d`, который основан на `next-gen/scada-ignition` `d131d55`)  
**Целевая ветка объединения:** будущая интеграционная ветка с `next-gen/platform` (Claude, `f720e74`)  
**Базовые ветки (`main`, `GaugeVision-2.0`) и `app/vision.py`:** **НЕ ИЗМЕНЯЛИСЬ**  
**Контракт совместимости:** `SHARED_DATA_CONTRACT.md` v1.1

---

## 1. Перечень реализованных модулей и изменённых файлов

### Новые модули (владелец — Neon, нулевой риск Git-конфликта)
| Файл | Назначение |
|---|---|
| `app/contracts.py` | Унифицированная идентификация `InstrumentIdentity` (`instrument_id`, `camera_id`, `gauge_slot`) и инженерные паспорта по умолчанию. Полностью совместимо с UUID v4 и явными `camera_id`/`gauge_slot` из контракта v1.1. |
| `app/predictive_analytics.py` | Прогнозная аналитика v2: адаптивный затухающий WLS + робастный Theil-Sen + привязка уровня + автокорреляционно-диффузионные интервалы PI80/PI95 + ETA до уставок `LL/L/H/HH` + Hamed-Rao Mann-Kendall + CUSUM + MAD + ускорение + волатильность (векторизовано на NumPy). |
| `app/ilp_solver.py` | Точный 0-1 ILP-решатель: air-gapped итеративный Branch-and-Bound с `O(log n)` оценкой Данцига, транзитивным замыканием циклов SCC, точным расчётом `min_required_budget`, жёстким `time_limit_s`, `cancel_event`, честным `frontier_ub` + опциональный промышленный бэкенд HiGHS (`scipy.optimize.milp`). |
| `app/modernization_optimizer.py` | Оптимизатор бюджета модернизации КИПиА (3 целевые функции, отделение оптических проблем, учёт прогноза и паспортов, кривая Парето, сравнение с жадным алгоритмом). |
| `tests/test_predictive_analytics.py` | Математические и интеграционные тесты Predictive Analytics (5/5 PASS). |
| `tests/test_modernization_optimizer.py` | Математические и API/SQLite/DOCX тесты Modernization Optimizer (4/4 PASS). |
| `tests/test_modbus_register_map.py` | Тесты карты регистров Modbus v1/v2 (2/2 PASS). |
| `tests/test_next_gen_integration_contract.py` | Приёмочная инфраструктура по `SHARED_DATA_CONTRACT.md` v1.1 (3/3 `CONTRACT_FIXTURE_VERIFIED`, 4 `SKIPPED_PENDING_MERGE`). |
| `integrations/ignition/*` | Экспортированный проект Perspective `GaugeVisionLab`, 738 read-only тегов и шаблон устройства Modbus TCP для Ignition 8.3.10. |
| `docs/MODBUS_REGISTER_MAP.md` | Полная спецификация карты регистров Modbus v2 + прогнозного блока. |

### Изменённые общие файлы (требуют внимательного слияния с `next-gen/platform`)
| Файл | Что изменено в нашей ветке | Потенциальные Git-конфликты при merge с `next-gen/platform` и стратегия разрешения |
|---|---|---|
| `app/scada_gateway.py` | Карта v2 (`EXTENDED_BASE=2000`), прогнозный блок (`PREDICTIVE_BASE=3600`, слоты `0..60`), системные `906..915`, **`place_instruments(instruments)`** по контракту v1.1 § 5.3 с очисткой удалённых слотов во всех 3 блоках, `MAX_CLIENTS=32` и idle timeout. | **Средний конфликт** в `update_from_instruments` / `__init__`: в `next-gen/platform` добавлен `place_instruments` поверх карты v1 (`MAX_REGISTERS=1024`). **Решение:** сохранить нашу версию `app/scada_gateway.py` целиком — она уже содержит идентичный `place_instruments` + карту v2 (`4096`) + прогнозный блок + очистку 3 блоков. |
| `app/db.py` | Миграция `ALTER TABLE readings ADD COLUMN instrument_id TEXT` + индекс `idx_readings_inst_ts`; новые таблицы `instrument_passports`, `predictive_snapshots`, `modernization_plans`; функция `get_instrument_series()`. | **Средний конфликт** в `SCHEMA` и `init_db()`: `next-gen/platform` добавляет таблицу `instruments`, `readings.calibration_rev`, `events.instrument_id/source_id`. **Решение:** объединить аддитивно — оставить обе части `SCHEMA` и оба блока `PRAGMA table_info` в `init_db()`. Проверить, чтобы `get_instrument_series()` опционально фильтровала по последней `calibration_rev` (см. § 4). |
| `app/main.py` | Инициализация `service.predictive`, `service.analytics_executor`, `_predictive_cache`, `_optimizer_sem`; неблокирующие эндпоинты `/api/predictive/*`, `/api/passports*`, `/api/optimizer/*`; параметры оптимизации в `/api/specs/preview` и `/api/specs/generate`; усиленная Pydantic-валидация и аудит `OPTIMIZER_SOLVE`. | **Высокий конфликт** в `GaugeService.__init__`, `_architecture_sync_loop`, `api_dispatch_overview`, Pydantic-моделях. **Решение:** брать Multi-Gauge CRUD и `public_instruments()` из `next-gen/platform`, сохраняя все наши маршруты `/api/predictive/*`, `/api/passports*`, `/api/optimizer/*`, `analytics_executor`, кэш и семафор. |
| `app/spec_generator.py` | Опциональные аргументы `predictive_overview`, `optimization_result`, `selected_instrument_ids` и разделы 5.1 / 5.2 в `.md`/`.docx`. | **Низкий конфликт** (все параметры опциональные с дефолтом `None`). |
| `app/docx_builder.py` | Удаление недопустимых в XML 1.0 управляющих байтов внутри `xml_escape()`. | **Низкий конфликт** (5 строк в шапке файла). |
| `static/index.html`, `static/js/console/dispatch.js`, `static/css/console.css` | Секции `#predictiveSection` и `#optimizerSection` на вкладке диспетчеризации. | **Средний конфликт** в `static/index.html` и CSS (если Claude добавил UI Multi-Gauge/Auto-Cal). **Решение:** аддитивное слияние секций, проверка отсутствия `·` (U+00B7) в UI. |

---

## 2. Миграции SQLite

- **Совместимые с `next-gen/platform`:** `readings.instrument_id TEXT` + индекс `idx_readings_inst_ts (instrument_id, timestamp)` — добавляются через `PRAGMA table_info(readings)`.
- **Изолированные таблицы Neon (без FK на `instruments`, совместимы с `sim-NN`):**
  1. `instrument_passports` (`instrument_id PK`, `camera_id`, `gauge_slot`, `criticality_class`, `criticality_weight`, `hazardous_zone`, `mandatory_regulation`, `custom_capex_rub`, `custom_downtime_risk_rub_yr`, `verification_due_date`, `notes`, `updated_at`)
  2. `predictive_snapshots` (`id PK`, `instrument_id`, `camera_id`, `gauge_slot`, `computed_at`, `status`, `trend_class`, `slope_per_min`, `eta_warning_min`, `eta_alert_min`, `breach_prob_alert`, `anomaly_score`, `confidence`, `payload_json`)
  3. `modernization_plans` (`id PK`, `name`, `created_at`, `created_by`, `budget_rub`, `objective`, `status`, `selected_count`, `total_capex_rub`, `total_net_annual_effect_rub`, `total_risk_reduction`, `selected_ids_json`, `result_json`)

---

## 3. REST API контракты (добавленные/расширенные)

| Метод | Путь | Роль RBAC | Описание |
|---|---|---|---|
| `GET` | `/api/predictive/overview?window_min=&horizon_min=&persist=` | `operator` | Сводка прогнозов по всем приборам (кэш TTL 5 с, неблокирующий `analytics_executor`) |
| `GET` | `/api/predictive/instrument/{inst_id}` | `operator` | Детальный прогноз, 80%/95% ДИ, `history_points`, `snapshots_history` |
| `GET` | `/api/predictive/history/{inst_id}` | `operator` | История снапшотов прогнозов прибора (валидация `inst_id`, 404/422) |
| `GET` | `/api/passports` | `operator` | Инженерные паспорта всех приборов (объединение БД + дефолты) |
| `PATCH` | `/api/passports/{inst_id}` | `engineer` | Обновление паспорта прибора + запись `PASSPORT_UPDATE` в `audit_log` |
| `POST` | `/api/optimizer/solve` | `engineer` | Точный 0-1 ILP расчёт портфеля + кривая Парето (`Semaphore(2)`, `time_limit_s <= 5.0`, аудит `OPTIMIZER_SOLVE`) |
| `POST` | `/api/optimizer/plans` | `engineer` | Расчёт и сохранение неизменяемого инвестплана в SQLite + аудит `OPTIMIZER_PLAN_SAVE` |
| `GET` | `/api/optimizer/plans` | `operator` | Список сохранённых планов модернизации |
| `GET` | `/api/optimizer/plans/{plan_id}` | `operator` | Детальный сохранённый план |
| `POST` | `/api/specs/preview`, `/api/specs/generate` | `engineer` | Расширены опциональными полями `optimization_plan_id`, `optimization_budget_rub`, `optimization_objective`, `selected_instrument_ids` |

---

## 4. Карта регистров Modbus TCP (MAX_REGISTERS = 4096, v2)

| Блок | 0-based адреса | 1-based HR | Слоты (`modbus_slot`) | Формула |
|---|---|---|---|---|
| Базовый (v1) | `0..799` | `40001..40800` | `0..199` | `slot * 4` (`value f32`, `status u16`, `health*10 u16`) |
| Системный (v1+v2+pred) | `900..915` | `40901..40916` | — | `900..905` v1, `906..911` v2 heartbeat/sync/meta, `912..915` pred counters/meta |
| Расширенный (v2) | `2000..3599` | `42001..43600` | `0..199` | `2000 + slot * 8` (`age`, `conf*1000`, `flags`, `last_valid_ts`, `last_valid_val`) |
| Прогнозный (Predictive) | `3600..4087` | `43601..44088` | **`0..60`** | `3600 + slot * 8` (`eta_alert`, `eta_warn`, `prob*1000`, `anom*10`, `trend`, `conf*1000`) |

---

## 5. Зависимости

- **Обязательные новые зависимости:** **НЕТ** (`requirements.txt` не изменён, 100% air-gapped совместимость).
- **Опциональное ускорение для парков `> 40` приборов:** установка `scipy>=1.13` автоматически активирует промышленный C++ MILP-решатель HiGHS в `app/ilp_solver.py` (`solver_backend="auto"`).

---

## 6. Обязательные действия и проверки после слияния с `next-gen/platform`

1. **Фильтрация `calibration_rev` в `db.get_instrument_series()`:** после появления столбца `readings.calibration_rev` отбирать ряды только текущей ревизии калибровки, чтобы смена шкалы не создавала ложный скачок CUSUM/тренда.
2. **Публикация событий `kind="prediction"`:** при переходе прогноза прибора в критическое состояние (`eta_alert_min <= 30` или `breach_prob_alert_horizon >= 0.7`) публиковать событие через `service.emit("prediction", instrument_id=..., source_id=..., cam_id=instrument_id, ...)`.
3. **Запуск 4 отложенных приёмочных тестов (`SKIPPED_PENDING_MERGE`):** `INT-MG-01`, `INT-MG-02`, `INT-AC-01`, `INT-SCADA-02` (см. `INTEGRATION_TEST_PLAN.md`).
4. **Проверка неподтверждённых требований RTM:** `REQ-CV-05` (валидация CV) остаётся в зоне ответственности ветки Claude; требования безопасности `OBS-SHARED-01..05` (явный `GAUGEVISION_HOST`, `MQTT_TLS=1`, firewall для Modbus) — в инструкции ввода в эксплуатацию.

---

## 7. Сводный реестр отчётов и доказательств в `reports/next_generation/`

- [PREDICTIVE_REAL_DATA_VALIDATION.md](PREDICTIVE_REAL_DATA_VALIDATION.md) — валидация на 4 открытых промышленных датасетах (SKAB, UCI 447 Hydraulic, UCI 791 MetroPT-3, UCI 551 Gas Turbine), DEV vs LOCKED TEST.
- [ILP_INDEPENDENT_VERIFICATION.md](ILP_INDEPENDENT_VERIFICATION.md) — 1 500 случайных задач против Brute-Force $2^N$ и HiGHS 1.16.0 + 14 граничных случаев.
- [ILP_SCALABILITY_REPORT.md](ILP_SCALABILITY_REPORT.md) — масштабирование 36…1000 объектов (BnB vs HiGHS, 4 семейства задач).
- [ANALYTICS_PERFORMANCE_REPORT.md](ANALYTICS_PERFORMANCE_REPORT.md) — профилирование 36…1000 приборов, неблокирующий event loop (ускорение в 50,8×), кэш API (11×), DOCX.
- [SECURITY_VALIDATION_REPORT.md](SECURITY_VALIDATION_REPORT.md) — аудит промышленной кибербезопасности (11/11 PASS + 5 общих замечаний).
- [INTEGRATION_TEST_PLAN.md](INTEGRATION_TEST_PLAN.md) — матрица сквозной приёмки по контракту v1.1.
- [INTEGRATION_HANDOFF.md](INTEGRATION_HANDOFF.md) — настоящий документ передачи на интеграцию.
- `evidence/` — воспроизводимые скрипты, JSON-отчёты и CSV-таблицы по всем 5 направлениям (`predictive/`, `ilp/`, `performance/`, `integration/`, `security/`).
