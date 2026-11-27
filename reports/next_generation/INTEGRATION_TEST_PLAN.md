# План и инфраструктура комплексной приёмки GaugeVision AI Next Generation

**Проект:** GaugeVision AI Next Generation  
**Основание:** `SHARED_DATA_CONTRACT.md` v1.1 (`next-gen/platform`, `f720e74`)  
**Исполняемый тестовый стенд:** `tests/test_next_gen_integration_contract.py`  
**Артефакт прогона:** `reports/next_generation/evidence/integration/contract_v11_results.json`

---

## 1. Принцип честного разделения проверок до и после слияния веток

Ветка `next-gen/platform` (Multi-Gauge Vision, таблица `instruments`, Auto Calibration, изменения `app/vision.py`) разрабатывается параллельно и **ещё не объединена** с текущей веткой `next-gen/analytics-validation`.  
Во избежание фиктивного прохождения сквозных тестов инфраструктура приёмки разделена строго на два класса:
1. **`CONTRACT_FIXTURE_VERIFIED` (выполняются и подтверждены уже сейчас):** реальный прогон модулей `db`, `contracts`, `dispatch_analyzer`, `predictive_analytics`, `store_forward`, `scada_gateway` (`place_instruments`), `modernization_optimizer` и `spec_generator` (`.docx`) на строгих фикстурах `SHARED_DATA_CONTRACT.md` v1.1.
2. **`SKIPPED_PENDING_MERGE` (активируются строго после слияния веток):** сквозные проверки живого Multi-Gauge CV-детектора/трекера, SQLite-таблицы `instruments`, REST-эндпоинтов `/api/sources/{id}/instruments` и `/autocalibrate`, а также живого стенда Ignition 8.3.10 на объединённом коде.

---

## 2. Матрица комплексных приёмочных испытаний

| ID | Сценарий сквозного испытания | Проверяемый путь / инвариант | Текущий статус (до слияния) | Доказательство |
|---|---|---|---|---|
| **INT-PIPE-01** | Многоприборная камера -> SQLite -> Dispatch -> Predictive -> S&F/MQTT -> Modbus -> Optimizer -> DOCX | 1 камера `source_id` (UUID v4) → 3 логических прибора (`is_primary=1` с `id=source_id`, + 2 UUID v4 с `gauge_slot=0,1,2` и `modbus_slot=0,36,37`) → `gv.reading/1` → `readings.instrument_id` → независимые ряды → ETA `60,0 мин` для дрейфующего слота 1 и `None` для стабильного слота 0 → S&F `gv.telemetry/1` → Modbus HR `40001 / 40145 / 40149` и прогнозный `43889` → ILP `optimal` → валидный `.docx` (`39 688 Б`) | **PASS (`CONTRACT_FIXTURE_VERIFIED`)** | `contract_v11_results.json` |
| **INT-SLOT-01** | Стабильность `instrument_id`, `gauge_slot` и `modbus_slot` при добавлении, удалении, перестановке и перезапуске | Перестановка `[g2, g0, g1]` не меняет HR-адреса; удаление слота `36` очищает базовый (`NaN / STALE`), расширенный (`age=65535`) и прогнозный (`NaN / code=6`) блоки слота `36`, не сдвигая слоты `0` и `37`; добавление `g3` получает слот `38`; перезапуск `ModbusTcpGateway` воспроизводит идентичную карту; `0` пересечений диапазонов (`0..799`, `900..915`, `2000..3599`, `3600..4087`) | **PASS (`CONTRACT_FIXTURE_VERIFIED`)** | `contract_v11_results.json` |
| **INT-MIG-01** | Миграция старой БД GaugeVision 2.0 без `readings.instrument_id` и таблиц аналитики | Старая БД с `cameras` (без `video_file`) и `readings` (без `instrument_id`/`unit`/`run_id`) открывается через `db.init_db()`, сохраняет 100% исторических строк (`21/21`), корректно читается через `get_instrument_series` (`COALESCE(instrument_id, camera_id)`) | **PASS (`CONTRACT_FIXTURE_VERIFIED`)** | `contract_v11_results.json` |
| **INT-MG-01** | Живой CRUD таблицы `instruments` и REST `/api/sources/{source_id}/instruments` | Создание/редактирование/удаление доп. приборов через API; запрет удаления основного прибора отдельно от источника; уникальность `modbus_slot` и `gauge_slot` | **SKIPPED_PENDING_MERGE** | Требует merge `next-gen/platform` |
| **INT-MG-02** | Живой Multi-Gauge Vision (`app/vision.py`) на многоприборном кадре | Один проход детектора на кадр -> трекинг ROI -> независимые `InstrumentReading v1` -> `track_lost` не переписывает показания соседнего прибора | **SKIPPED_PENDING_MERGE** | Требует merge `next-gen/platform` |
| **INT-AC-01** | Живая автокалибровка (`/autocalibrate` -> `/calibration/confirm`) и изоляция `calibration_rev` | Неподтверждённая автокалибровка даёт `valid=false (calibration_unconfirmed)` и **игнорируется** Predictive Analytics; после подтверждения инженером инкрементируется `calibration_rev` | **SKIPPED_PENDING_MERGE** | Требует merge `next-gen/platform` |
| **INT-SCADA-02** | Живой сквозной прогон объединённой ветки с Ignition 8.3.10 | Чтение реальной Ignition 8.3.10 слотов `0`, `36`, `37` при удалении слота `36`: тег слота `36` уходит в `NaN / STALE`, тег слота `37` продолжает читать свой прибор без сдвига | **SKIPPED_PENDING_MERGE** | Требует merge + запуск Ignition |

---

## 3. Команда запуска приёмочного набора после объединения веток

```powershell
$env:CUDA_VISIBLE_DEVICES=""
$env:GAUGEVISION_DEVICE="cpu"
python -B tests/test_next_gen_integration_contract.py
python -B tests/test_predictive_analytics.py
python -B tests/test_modernization_optimizer.py
python -B tests/test_modbus_register_map.py
python -B tests/test_remediation_full.py
python -B tests/test_acceptance_independent.py
```

Дополнительно для независимой проверки решателя против HiGHS (если установлен `scipy`):
```powershell
python reports/next_generation/evidence/ilp/verify_and_benchmark_ilp.py
```
