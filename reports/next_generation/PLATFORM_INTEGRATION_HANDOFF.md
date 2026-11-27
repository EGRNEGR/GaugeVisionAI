# Передача на интеграцию: ветка `next-gen/platform`

Документ для агента, который объединяет `next-gen/platform` (основной агент: CV, Multi-Gauge Vision,
Auto Calibration, HMI/API/SQLite) и `next-gen/analytics-validation` (агент Neon, HEAD 285e896:
Ignition SCADA, карта Modbus v2, Predictive Analytics, ILP-оптимизатор). Парный документ Neon —
`reports/next_generation/INTEGRATION_HANDOFF.md` в его ветке. Ветки не объединялись; `main` не
изменялся.

## 1. Что в ветке `next-gen/platform`

| Направление | Состояние | Отчёт |
|---|---|---|
| REQ-CV-05, валидация CV на реальных снимках | PARTIAL: v7 final — локализация 79 %, годных 65,4 %; v8 — правка проверки шкалы | `reports/industrial_validation/CV_VALIDATION_REPORT.md` |
| NG-MG-01, Multi-Gauge Vision | реализовано и испытано (синтетика, API, мозаики реальных фото, браузер) | `MULTI_GAUGE_VALIDATION.md` |
| NG-AC-01, Auto Calibration | испытано, **в продукт не включено**; модуль выключен и не подключён | `AUTO_CALIBRATION_REPORT.md` |
| Контракт данных | v1.2 (v1.1 + фактический состав поля `track`) | `SHARED_DATA_CONTRACT.md` |

Новые модули: `app/multigauge.py` (детектор, трекер, процессор), `app/multigauge_service.py`
(миксин сервиса: реестр приборов, телеметрия, события), `app/panel_sim.py` (синтетический щит для
тестов и демо), `app/autocal.py` (исследовательский, не подключён). HMI: вкладка «Щит»
(`static/js/console/multigauge.js`, `static/css/multigauge.css`). Скрипты:
`scripts/make_panel_video.py` (демо-видео щита).

## 2. Слияние: проверенный рецепт

Пробное слияние выполнено без изменения веток и ссылок: `git merge-tree --write-tree HEAD
origin/next-gen/analytics-validation` (база слияния 94e646e), результат распакован во временный каталог,
конфликты разрешены, тесты прогнаны там же.

| Файл | Конфликт | Разрешение |
|---|---|---|
| `app/scada_gateway.py` | 6 участков | **сторона Neon целиком**: тот же `place_instruments` (плюс проверка `bool`), карта v2, прогнозный блок, `_clear_slot` во всех трёх блоках, `MAX_REGISTERS = 4096`, heartbeat/sync. Моя версия — подмножество |
| `app/db.py` | 1 участок в `init_db` (миграция `readings`) | **моя сторона участка**: та же колонка `instrument_id` и индекс `idx_readings_inst_ts`, плюс `calibration_rev`, заполнение `instrument_id = camera_id` для старых строк, колонки событий, основные приборы для старых камер. Остальные изменения Neon в `db.py` (таблицы аналитики, `get_instrument_series`) сливаются автоматически |
| `.gitignore` | 1 участок | сторона Neon (добавляет исключения для CSV-доказательств) |
| `.autopilot/PROGRESS.md` | 1 участок | обе стороны подряд |
| `app/main.py`, `static/index.html` | сливаются автоматически | проверить по § 4 |

Результат пробного слияния — все 12 наборов тестов обеих веток пройдены (CPU):

| Набор | Итог |
|---|---|
| `test_acceptance_independent` | 21/21 |
| `test_remediation_full` | 8/8 |
| `test_tracks_e2e`, `test_demo_dashboard` | пройдены |
| `test_instruments_db`, `test_multigauge`, `test_multigauge_api`, `test_autocal` | пройдены |
| `test_modbus_register_map` (Neon) | 2/2 |
| `test_predictive_analytics` (Neon) | 5/5 |
| `test_modernization_optimizer` (Neon) | 4/4 |
| `test_next_gen_integration_contract` (Neon) | 3/3 проверено, 4 ожидают слияния |

## 3. Общие интерфейсы — что сверено

- **Идентификация.** Основной прибор: `instrument_id == source_id == cameras.id`; дополнительный — UUID.
  `gauge_slot` уникален в пределах источника (0 — основной). Модуль Neon `app/contracts.py`
  (`resolve_instrument_identity`) принимает явные `camera_id`/`gauge_slot` из моего реестра.
- **Слоты Modbus.** `modbus_slot` постоянен, хранится в таблице `instruments` и выдаётся
  `public_instruments()` в каждом приборе (через `demo.unify_camera` поле сохраняется). Оба места вызова
  `update_from_instruments` в объединённом `main.py` берут список из `public_instruments()`, поэтому
  `place_instruments` Neon получает постоянные слоты и дополнительных приборов щита. Удалённый прибор
  освобождает слот, регистры переходят в NaN / STALE во всех трёх блоках.
- **История.** Строки `readings` несут `instrument_id` и `calibration_rev`; Neon читает
  `COALESCE(instrument_id, camera_id)` — совместимо.
- **Телеметрия.** MQTT `gv.telemetry/1` и очередь Store-and-Forward — отдельный канал на прибор
  многоприборного источника (`channel_id = instrument_id`); однокамерная конфигурация поток не меняет.
- **События.** `service.emit(kind, ..., instrument_id=..., source_id=...)` — поля заполняются по
  умолчанию из `cam_id`; добавлены виды `calibration`, `instrument`, `prediction`.

## 4. Обязательные действия после слияния

1. **Фильтр `calibration_rev` в `db.get_instrument_series()`** (пункт 1 списка Neon). После смены шкалы
   прибора ряд должен начинаться с текущей ревизии, иначе прогноз увидит ложный скачок. Текущая ревизия —
   `instruments.calibration_rev`; старые строки без ревизии (NULL) относятся к ревизии 0.
2. **INT-AC-01 в плане Neon неприменим.** Он предполагает `/autocalibrate` и `/calibration/confirm` с
   состоянием `calibration_unconfirmed`. Автокалибровка в продукт не включена, таких эндпоинтов нет.
   Предлагаемая замена проверки: калибровка меняется только явным `PATCH /api/cameras/{id}` (основной
   прибор) или `PATCH /api/instruments/{id}` (дополнительный), каждое изменение шкалы увеличивает
   `calibration_rev`, а модуль `app/autocal.py` не вызывается сервисом (`tests/test_autocal.py`).
3. **INT-MG-01 и INT-MG-02** уже покрыты моими тестами: `test_instruments_db` (CRUD, уникальность
   `gauge_slot` и `modbus_slot`, запрет удаления основного прибора — HTTP 409), `test_multigauge_api`
   (8 приборов через HTTP, история по каждому), `test_multigauge` (перекрытый прибор получает отказ, а
   соседние приборы продолжают давать годные отсчёты; ID Switch = 0). После слияния их достаточно
   перепрогнать и перевести проверки в харнессе Neon из `SKIPPED_PENDING_MERGE` в выполненные.
4. **Прогнозный блок Modbus — только слоты 0–60.** Приборы с `modbus_slot ≥ 61` получают базовый и
   расширенный блоки, но не прогнозный. В демопрофиле дополнительные приборы занимают слоты с 36, вне
   демо — первый свободный. Для щитов с большим числом приборов нужна карта v3 или явная пометка в HMI;
   решение — за интегратором/Neon.
5. **`static/index.html` слился автоматически** — проверить в браузере, что на пульте есть и вкладка
   «Щит», и секции прогноза и оптимизатора на вкладке диспетчеризации. Браузерный сценарий «Щит»:
   `reports/next_generation/tests/hmi_panel_playwright.mjs` (сервер на 127.0.0.1:8765 с источником
   `video_file` из `scripts/make_panel_video.py`).
6. **События `prediction`** (пункт 2 списка Neon) — публиковать через `service.emit("prediction",
   instrument_id=..., source_id=..., cam_id=instrument_id, ...)`; виды событий и квитирование уже
   поддерживают эти поля.

## 5. Команды проверки

```
set CUDA_VISIBLE_DEVICES=
set GAUGEVISION_DEVICE=cpu
python -B tests/test_instruments_db.py
python -B tests/test_multigauge.py
python -B tests/test_multigauge_api.py
python -B tests/test_autocal.py
python -B tests/test_demo_dashboard.py
python -B tests/test_tracks_e2e.py
python -B tests/test_remediation_full.py
python -B tests/test_acceptance_independent.py
```

Тесты запускаются как скрипты (pytest в окружении не требуется). Проверки на реальных снимках
(`reports/next_generation/tests/mg_real_mosaic.py`, `autocal_eval.py`) требуют локальной копии MeterFL
и в репозиторий изображения не кладут.

## 6. Ограничения, которые переходят в объединённую версию

- REQ-CV-05 — PARTIAL (см. отчёт CV): точность на реальных снимках ниже целевой, отказ на непригодных
  кадрах — 98 %.
- Multi-Gauge: при 16 приборах в кадре 1280×720 на final годных 48 % (отказы безопасные, грубых 0);
  хвост ошибок на final тяжелее, чем у однокамерного режима; около 2 кадров/с на CPU при 16 приборах.
- Auto Calibration — не в продукте; `rapidocr-onnxruntime` не входит в `requirements.txt`.
- Мозаики MeterFL — фотографии приборов, а не видео действующего щита; синтетические кадры
  `panel_sim` везде подписаны как синтетика.
