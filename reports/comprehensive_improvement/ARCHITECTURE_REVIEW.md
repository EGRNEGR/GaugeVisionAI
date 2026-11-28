# Архитектурный аудит, качество кода, производительность, надёжность и БД (`ARCHITECTURE_REVIEW.md`)

Дата: 2026-11-28. Контрольный коммит: `1de2067` (ветка `research/cv-next-gen`).
Объединяет материалы: `ARCHITECTURE_REVIEW`, `CODE_QUALITY_AUDIT`, `PERFORMANCE_OPTIMIZATION_REPORT`, `RELIABILITY_AUDIT`, `DATABASE_AUDIT`.

## 1. Архитектура и качество кода

- **Модульность Vision Engine (`app/vision_engine/`):** единая точка расширения (`registry.py`, `detector.py`, `estimators.py`, `profiles.py`) без создания второго несовместимого конвейера. Все 4 профиля (`legacy`, `eco`, `balanced`, `precision`) прозрачно обслуживают одиночные камеры и Multi-Gauge.
- **Совместимость контрактов:** сохранены `instrument_id`, `camera_id`, `gauge_slot`, `modbus_slot`, `calibration_rev`, один проход детектора по кадру в Multi-Gauge, карта Modbus TCP (5208 регистров), Store-and-Forward, прогнозная аналитика, ILP-оптимизатор и генератор DOCX/MD. Автокалибровка остаётся отключённой в продакшен-маршрутах.
- **Статический аудит кода (`app/*.py`):** 0 вхождений `eval()`, `exec()`, `pickle`, `yaml.load()`, `shell=True`, `subprocess`, `md5`, `verify=False`. Все модули компилируются без ошибок.
- **Выявленная техдолг-зона (P3):** `app/main.py` имеет объём ~3750 строк (монолитный роутер + сервис); преднамеренный крупный рефакторинг не выполнялся во избежание регрессий стабильных контрактов 3.0.

## 2. База данных SQLite (`DATABASE_AUDIT`)

Проведён аудит `app/db.py`:
- единое долгоживущее соединение `aiosqlite` с `asyncio.Lock`, `WAL`, `synchronous=NORMAL`, `foreign_keys=ON`;
- корректные уникальные и составные индексы (`idx_instruments_primary`, `idx_instruments_gauge_slot`, `idx_readings_cam_ts`, `idx_inst_readings_id_ts`, `idx_sessions_exp`, `idx_audit_ts`);
- **Внесённые улучшения (коммит `1de2067`):**
  1. Добавлены `PRAGMA busy_timeout=5000`, `PRAGMA temp_store=MEMORY`, `PRAGMA cache_size=-16000` для снижения вероятности блокировок и пауз checkpoint при конкурентных операциях.
  2. В `prune_history()` добавлена очистка таблицы `predictive_snapshots` (`DELETE FROM predictive_snapshots WHERE computed_at < ?`), закрывающая риск неограниченного роста БД при длительной эксплуатации (`DEF-SEC-08`).
- Миграции баз версий `1.0`, `2.0` и `Next Gen` сохранены без изменений и подтверждены в `tests/test_final_integration.py`.

## 3. Анализ производительности и выброса event loop `1671,5 мс` (`PERFORMANCE_OPTIMIZATION_REPORT`)

- Проверены все тяжёлые синхронные операции в `app/main.py`: CV-инференс, `render_spec_docx`, `optimize_modernization_budget`, `build_evidence_frame_jpeg`, `encode_jpeg`, `_decode_image`, `yolo_available` уже вынесены в `loop.run_in_executor(...)`.
- **Исследование исторического скачка `1671,5 мс` (v3.0 soak на `t = 203 с`):** подтверждено, что в `app/db.py` ранее отсутствовал `PRAGMA busy_timeout` и расширенный кэш страниц, а также все синхронные тяжёлые обработчики уже вынесены в пул потоков; таким образом, наиболее вероятной первопричиной остаётся системная пауза ОС Windows или разовый WAL-checkpoint на старте (дополнительно смягчено настройками `cache_size=-16000` и `temp_store=MEMORY` и проверяется в новом soak-испытании v3.1).
- **CV-скорость:** `NeedleSegUNet` = `6,6 мс/кроп` CPU (в 4,8× быстрее OpenCV `32 мс`), `detect_dial_v31` в штатных кадрах работает **быстрее** v3.0 (`425 мс` vs `515 мс` на `M5` за счёт отсечения лишнего OpenCV-прохода при уверенной локализации).

## 4. Оптимизатор модернизации и инженерная документация

- `tests/test_modernization_optimizer.py` проверяет ILP-решатель, ограничения бюджета, невыполнимые сценарии (`infeasible`), кривую Парето и перенос в ТЗ.
- `app/spec_generator.py` детерминированно переносит измеренные показатели и результаты оптимизатора в DOCX/MD; опциональный LLM изолирован (`<FACTS>`) и не может изменять числовые значения, уставки или рекомендации при отказе.
