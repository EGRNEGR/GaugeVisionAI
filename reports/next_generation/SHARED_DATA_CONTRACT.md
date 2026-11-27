# Общий контракт данных GaugeVision AI Next Generation

Версия **1.1**, 2026-11-27, ветка `next-gen/platform` (1.0 — первая фиксация; 1.1 — сверка с
реализацией Neon в ветках `next-gen/scada-ignition` d131d55 и `next-gen/analytics-optimizer` 6a1828d).
Участники: основной агент (ветка `next-gen/platform`: CV, Multi-Gauge Vision, Auto Calibration,
интеграция HMI/API/SQLite) и агент Neon (отдельная ветка: Ignition SCADA и REQ-API-07,
Predictive Analytics, Modernization Optimizer).

Документ описывает только то, на что опираются обе стороны: идентификацию приборов, запись телеметрии,
события, хранение истории и интерфейсы доступа. Всё, что здесь не названо, остаётся внутренним делом
владельца модуля.

## 0. Правила изменения контракта

1. Версия 1.x меняется только **аддитивно**: новые необязательные поля, новые таблицы, новые
   эндпоинты. Поле, таблицу или эндпоинт из этого документа нельзя удалить, переименовать или
   поменять им тип и смысл.
2. Изменение вносит владелец раздела (таблица в § 9) отдельным коммитом в `next-gen/platform` с записью
   в § 10 «Журнал изменений». Neon предлагает изменения через свой отчёт или `reports/next_generation/
   NEON_CONTRACT_REQUESTS.md` в своей ветке — основной агент переносит их сюда.
3. Потребитель обязан игнорировать неизвестные поля (forward compatibility) и не должен
   полагаться на порядок полей JSON или порядок приборов в списке.
4. Всё время — UTC, ISO 8601 с миллисекундами и смещением: `2026-11-27T08:15:02.123+00:00`
   (`db.utcnow_iso()`). Числа — IEEE-754 double; NaN и ±Inf в JSON запрещены (вместо них `null`).

## 1. Идентификация: источник и логический прибор

До версии 1.0 одна камера = один прибор: калибровка и уставки лежали в `cameras`. Multi-Gauge
разделяет эти понятия.

| Понятие | Что это | Ключ | Где живёт |
|---|---|---|---|
| **Источник** (source) | Видеопоток: USB/RTSP/HTTP MJPEG/телефон/видеофайл | `source_id` = `cameras.id` (UUID v4) | таблица `cameras` |
| **Прибор** (instrument) | Один физический манометр/термометр в кадре источника | `instrument_id` | таблица `instruments` (§ 4.1) |
| **Симулируемый прибор** | Стендовая позиция демопрофиля | `sim-NN` (`sim-02`…`sim-36`) | `demo.SIMULATED_CATALOG`, без строки в `instruments` |

### 1.1. Правила `instrument_id`

- **Основной прибор источника** имеет `instrument_id == source_id`. Это правило обеспечивает
  обратную совместимость: вся существующая история (`readings.camera_id`), события (`events.cam_id`),
  ссылки HMI, регистры Modbus и MQTT-каналы, ключом которых был `camera_id`, продолжают указывать
  на тот же прибор без миграции данных.
- **Дополнительные приборы** того же кадра получают `instrument_id` = новый UUID v4.
- `instrument_id` неизменяем и никогда не переиспользуется — даже после удаления прибора.
- Идентификатор не зависит от порядка детекции на кадре. Сопоставление «найденный на кадре
  циферблат → `instrument_id`» выполняет трекер Multi-Gauge по сохранённой якорной ROI прибора
  (`instruments.roi`, § 4.1). Если сопоставить не удалось, отсчёт помечается `track_lost`
  и не приписывается чужому прибору.
- `gauge_slot` — номер циферблата в кадре источника: основной прибор 0, дополнительные 1, 2, … (наименьший
  свободный номер на источнике, хранится в `instruments.gauge_slot`). Совпадает с полем
  `InstrumentIdentity.gauge_slot` модуля `app/contracts.py` Neon; `camera_id` записи прибора = `source_id`.
  Формат `<camera_id>#g<slot>` из `resolve_instrument_identity` не используется: в записях приборов
  всегда есть явные `camera_id` и `gauge_slot`, которые эта функция берёт в первую очередь.
- Человекочитаемые обозначения: `code` (позиция пульта, например `КМ-03`, `PI-101`) и `tag`
  (технологический тег КИПиА, необязательный). Оба можно менять; ключом служит только `instrument_id`.

### 1.2. Поле `cam_id` в существующих интерфейсах

Во всех местах, где исторически фигурирует `cam_id` в значении «прибор пульта» (WS-сообщение
`reading`, события `alarm`, `/api/instruments/{inst_id}/…`, `events.cam_id`), значение равно
**`instrument_id`**. Для основного прибора это совпадает с `source_id`, поэтому для
однокамерных конфигураций ничего не меняется. Поле `source_id` добавляется рядом.

События канала связи (`link`) относятся к источнику: `cam_id = source_id`, `instrument_id = null`.

## 2. Запись телеметрии (InstrumentReading v1)

Одна запись — результат обработки одного прибора на одном кадре. Публикуется в WS (`type: "reading"`),
вкладывается в `instrument.reading` в `/api/instruments` и служит источником для Modbus, MQTT и
истории.

| Поле | Тип | Обяз. | Смысл |
|---|---|---|---|
| `schema` | str | да | `"gv.reading/1"` |
| `ts` | str | да | время обработки кадра (UTC) |
| `last_frame_ts` | str | да | время получения кадра источником |
| `cam_id` | str | да | = `instrument_id` (совместимость) |
| `instrument_id` | str | да | ключ прибора |
| `source_id` | str | да | ключ источника |
| `value` | float \| null | да | показываемое значение (EMA); `null`, пока нет достоверного отсчёта после калибровки |
| `raw_value` | float \| null | да | мгновенное значение по текущему кадру |
| `unit` | str | да | единица прибора |
| `angle` | float \| null | да | угол стрелки, градусы, система координат кадра |
| `valid` | bool | да | отсчёт по этому кадру достоверен |
| `confidence` | float | да | уверенность стрелки 0..1 |
| `level` | str \| null | да | `normal` / `warning` / `alert`; `null` — уровень неизвестен |
| `invalid_reason` | str \| null | да | причина недостоверности (§ 2.1) |
| `out_of_scale` | bool | да | стрелка вне рабочей дуги калибровки |
| `awaiting_post_cal` | bool | да | после смены калибровки ещё нет достоверного отсчёта |
| `last_valid_value`, `last_valid_level`, `last_valid_ts` | — | да | последний достоверный отсчёт |
| `dial_found`, `dial_source` | bool, str | да | локализация: `yolo`, `ellipse`, `yolo+ellipse`, `manual`, `frame`, `track` |
| `method` | str \| null | да | метод стрелки: `moment/…`, `hough/…` |
| `process_ms` | float | да | время конвейера на кадр, мс |
| `calibration_rev` | int | да | ревизия калибровки прибора (§ 4.1), с которой получен отсчёт |
| `track` | object \| null | нет | Multi-Gauge: `{"iou": float, "center_shift": float, "state": "locked"\|"reacquired"\|"lost"}` |
| `sparkline` | float[] | нет | последние ≤ 24 достоверных значения (для HMI) |
| `measurement_state`, `connection_state`, `quality`, … | — | нет | производные состояния `demo.compute_live_states` |

Неизвестные потребителю поля игнорируются. Предиктивной аналитике следует брать в расчёт только записи
с `valid = true` — остальные описывают состояние канала, а не процесс.

### 2.1. Коды `invalid_reason`

`no_frame`, `dial_not_found`, `track_lost`, `blur`, `dark`, `overexposed`, `scale_not_visible`,
`low_confidence_unconfirmed`, `out_of_scale`, `not_calibrated`, `calibration_unconfirmed`,
`unsupported_instrument`. Список расширяемый (§ 0, п. 1).

## 3. События

### 3.1. Модель события (`events`, WS `type: "event"`, SSE `event`)

Поля существующей модели сохраняются без изменений: `id, ts, kind, cam_id, cam_name, level,
prev_level, value, unit, setpoint, setpoint_value, text, has_frame, acked, acked_ts, acked_by,
ref_event_id, ref_ts, ref_level, duration_s`. Добавляются:

| Поле | Тип | Смысл |
|---|---|---|
| `instrument_id` | str \| null | прибор (для `alarm`, `config`, `calibration`); `null` для событий источника |
| `source_id` | str \| null | источник |

### 3.2. Типы (`kind`)

| kind | Когда | Квитирование |
|---|---|---|
| `alarm` | переход зоны уставок по достоверному отсчёту | при росте уровня |
| `link` | смена статуса потока источника | нет |
| `ack` | квитирование оператором | — |
| `config` | изменение прибора, источника, уставок, калибровки | нет |
| `calibration` | **новое (v1.0)**: предложение/подтверждение/отклонение автокалибровки; `text` — `proposed` / `confirmed` / `rejected` / `refused` | нет |
| `instrument` | **новое (v1.0)**: прибор добавлен/удалён/потерян трекером (`text` — `added` / `removed` / `track_lost` / `reacquired`) | `track_lost` — да |
| `prediction` | **резерв для Neon**: предупреждение предиктивной аналитики | на усмотрение Neon |

Neon публикует свои события через `service.emit("prediction", instrument_id=…, source_id=…, cam_id=instrument_id,
level=…, text=…)` — общий журнал, общая SQLite-таблица, общее квитирование.

### 3.3. Store-and-Forward и MQTT

Топик: `{MQTT_TOPIC_PREFIX}/{channel_id}/{payload_type}`, `payload_type ∈ {telemetry, alarm, frame, health}`
(CHECK-ограничение `sf_queue`). Конверт сообщения неизменен: `seq_id, event_uuid, edge_node,
created_at, severity, …payload`.

| channel_id | payload_type | payload |
|---|---|---|
| `instrument_id` | `alarm` | событие § 3.1 |
| `source_id` | `health` | событие `link` |
| `ktc-telemetry` / `DEMO_LIVE_CAM_ID` | `telemetry` | сводка станции (как сейчас) |
| `instrument_id` | `telemetry` | **новое (v1.0)**: `{"schema": "gv.telemetry/1", "instrument_id", "source_id", "code", "ts", "value", "unit", "level", "valid", "confidence", "calibration_rev"}` — только для приборов многоприборных источников (однокамерная конфигурация не меняет поток MQTT), не чаще `MG_TELEMETRY_INTERVAL` = 5 с на прибор и только при `valid = true` (v1.1) |

## 4. Хранение (SQLite, `app/db.py`)

Миграции — только `CREATE TABLE IF NOT EXISTS` и `ALTER TABLE … ADD COLUMN` в `init_db()`
с проверкой `PRAGMA table_info`. Существующие столбцы не удаляются и не переименовываются.

### 4.1. Новая таблица `instruments` (владелец — основной агент)

```sql
CREATE TABLE IF NOT EXISTS instruments (
    id               TEXT PRIMARY KEY,               -- instrument_id
    source_id        TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    is_primary       INTEGER NOT NULL DEFAULT 0,      -- 1: id = source_id
    name             TEXT NOT NULL,
    code             TEXT,
    tag              TEXT,
    gauge_type       TEXT NOT NULL DEFAULT 'pressure',
    unit             TEXT NOT NULL DEFAULT 'МПа',
    roi              TEXT NOT NULL DEFAULT '{}',      -- якорная ROI, JSON (§ 4.4)
    calibration      TEXT NOT NULL DEFAULT '{}',      -- JSON, CalibrationModel (§ 4.4)
    calibration_rev  INTEGER NOT NULL DEFAULT 0,
    calibration_meta TEXT NOT NULL DEFAULT '{}',      -- источник, уверенность, кто подтвердил (§ 4.4)
    thresholds       TEXT NOT NULL DEFAULT '{}',      -- JSON, ThresholdsModel
    modbus_slot      INTEGER UNIQUE,                  -- § 5.3
    gauge_slot       INTEGER NOT NULL DEFAULT 0,      -- § 1.1, уникален в пределах source_id (v1.1)
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_instruments_primary ON instruments (source_id) WHERE is_primary = 1;
```

Миграция существующей базы: для каждой строки `cameras` создаётся основной прибор
(`id = cameras.id`, `is_primary = 1`, калибровка и уставки копируются, `modbus_slot` выдаётся по
порядку `cameras.created_at` в свободных слотах, § 5.3). Поля `cameras.calibration` и
`cameras.thresholds` остаются и синхронизируются с основным прибором: старый API
`PATCH /api/cameras/{id}` продолжает менять калибровку основного прибора.

### 4.2. История показаний

`readings` получает столбец `instrument_id TEXT` (NULL в старых строках) и индекс
`(instrument_id, timestamp)`. Ключ прибора строки — `COALESCE(instrument_id, camera_id)`;
`camera_id` всегда = `source_id`. Новые строки пишутся с заполненным `instrument_id`, старые при миграции
получают `instrument_id = camera_id`, поэтому чтение Neon по `COALESCE(instrument_id, camera_id)` и чтение
основного агента по `instrument_id` дают одинаковые ряды. Обе ветки добавляют один и тот же столбец
`readings.instrument_id` с проверкой `PRAGMA table_info` — при объединении миграции совместимы.
Добавляется столбец `calibration_rev INTEGER` — ревизия калибровки, с которой получен отсчёт,
чтобы аналитика не смешивала ряды до и после перекалибровки.

`instrument_readings` (симуляция и внешние источники) не меняется.

### 4.3. События

`events` получает столбцы `instrument_id TEXT`, `source_id TEXT` и индекс `(instrument_id, ts)`.
Для старых строк ключ прибора — `cam_id`.

### 4.4. JSON-поля прибора

`roi` (якорь трекера, доли кадра источника, как `RoiModel`):
`{"mode": "auto"|"manual", "cx": 0..1, "cy": 0..1, "r": 0..1, "axes": [a, b]?, "angle": φ?}`,
`r` — в долях меньшей стороны кадра.

`calibration` — без изменений (`CalibrationModel`): `v_min, theta_min, v_max, theta_max, direction, roi?`;
**новое необязательное поле** `points: [{"theta": град, "value": float}, …]` — многоточечная
кусочно-линейная шкала для нелинейных приборов (≥ 3 точек, монотонно по ходу стрелки). При наличии
`points` значение вычисляется по ним, `v_min/v_max/theta_*` остаются крайними точками.

`calibration_meta`:
`{"source": "manual"|"auto"|"legacy", "status": "confirmed"|"proposed"|"refused",
"confidence": 0..1, "residual_deg": float?, "ocr_labels": [...]?, "confirmed_by": str?,
"confirmed_at": str?, "rev": int}`. Значение, рассчитанное по неподтверждённой автокалибровке, не
публикуется как достоверное (`invalid_reason = calibration_unconfirmed`).

### 4.5. Таблицы Neon

Фактически реализованы (v1.1): `instrument_passports`, `predictive_snapshots`, `modernization_plans`.
Ссылка на прибор — `instrument_id TEXT` с `camera_id` и `gauge_slot`, **без** внешнего ключа (приборы
`sim-NN` не лежат в `instruments`). Основной агент эти таблицы не меняет; Neon не меняет таблицы § 4.1–4.3.

## 5. Интерфейсы доступа

### 5.1. REST (существующие сохраняются)

| Метод | Путь | Что отдаёт / делает | Изменение v1.0 |
|---|---|---|---|
| GET | `/api/instruments` | все приборы пульта | каждый логический прибор — отдельная запись; добавлены `instrument_id`, `source_id`, `is_primary`, `modbus_slot`, `calibration_meta` |
| GET | `/api/instruments/{inst_id}/history?limit=` | последние отсчёты | работает для любого `instrument_id` |
| GET | `/api/instruments/{inst_id}/trend?since=&until=&step=` | агрегаты min/avg/max по корзинам | работает для любого `instrument_id` |
| GET | `/api/instruments/{inst_id}/export.csv` | CSV протокол | то же |
| GET | `/api/events?limit=&cam_id=` | журнал | фильтр `cam_id` = `instrument_id` |
| GET/PATCH/DELETE | `/api/cameras/{id}` | источник и его основной прибор | без изменений |
| GET | `/api/sources/{source_id}/instruments` | **новое**: приборы источника | — |
| POST | `/api/sources/{source_id}/instruments` | **новое**: добавить прибор (ROI, калибровка, уставки) | — |
| POST | `/api/sources/{source_id}/instruments/detect` | **новое**: найти все циферблаты на текущем кадре, вернуть кандидатов ROI | — |
| PATCH/DELETE | `/api/instruments/{inst_id}` | **новое**: изменить/удалить логический прибор (основной удаляется только вместе с источником) | — |
| POST | `/api/instruments/{inst_id}/autocalibrate` | **новое**: предложение автокалибровки (без применения) | — |
| POST | `/api/instruments/{inst_id}/calibration/confirm` | **новое**: инженер подтверждает/правит предложение | роль `engineer` |

Предиктивная аналитика читает историю через `GET /api/instruments/{id}/trend` или внутри процесса через
функции § 5.4. Свои эндпоинты Neon размещает под `/api/predictive/…` и `/api/optimizer/…`.

### 5.2. WebSocket `/ws/dashboard`

Сообщения сохраняются: `reading`, `status`, `event`, `ack`, `camera_added|updated|deleted`, `demo_run`,
`architecture_tick`, `store_forward`, тики симуляции. `reading` несёт запись § 2 (`cam_id = instrument_id`).
Новые типы: `instrument_added`, `instrument_updated`, `instrument_deleted` (`{"instrument": {...}}` /
`{"instrument_id": ...}`) и `calibration_proposal`.

### 5.3. Modbus TCP (карта регистров владеет Neon, слоты — основной агент)

Карта v2 Neon (`docs/MODBUS_REGISTER_MAP.md` его ветки, `MAX_REGISTERS = 4096`). Все блоки прибора
адресуются одним и тем же индексом `idx`, и этим индексом является `modbus_slot`:

| Блок | Адреса | Формула | Слоты |
|---|---|---|---|
| базовый (v1) | 0–799 | `idx × 4` | 0–199 |
| системный | 900–915 | — | — |
| расширенный (v2) | 2000–3599 | `2000 + idx × 8` | 0–199 |
| прогнозный (Predictive) | 3600–4087 | `3600 + idx × 8` | **только 0–60** |

Прибор со слотом > 60 публикует базовый и расширенный блоки, прогнозного блока у него нет (ограничение
карты v2; расширение карты — решение Neon).

- Раньше слот определялся позицией прибора в списке и сдвигался при удалении прибора; с v1.0
  слот хранится в `instruments.modbus_slot` и не меняется в течение жизни прибора.
- Демопрофиль: основной живой прибор — слот 0, симуляция `sim-NN` — слот `NN − 1` (как сейчас,
  по `grid_pos − 1`), реальные приборы — первый свободный слот ≥ 36.
- Без демопрофиля: первый свободный слот ≥ 0 в порядке создания.
- `ModbusTcpGateway.place_instruments` (ветка `next-gen/platform`) размещает прибор по
  `inst["modbus_slot"]`; приборы без слота (симуляция стенда) занимают свободные слоты по порядку списка
  (прежнее поведение). Слот удалённого прибора переходит в NaN / STALE.
- **При объединении веток** в `update_from_instruments` Neon и в заполнении расширенного и прогнозного
  блоков `enumerate(instruments)` заменяется на `place_instruments(instruments)`: иначе при удалении или
  добавлении дополнительного прибора индексы сдвинутся и теги Ignition начнут читать чужой прибор. Карту тегов Ignition Neon строит по
  `GET /api/scada/modbus/registers`, где у каждой строки есть `instrument_id`, `hr_value`,
  `hr_status`, `hr_health`.

### 5.4. Внутрипроцессный доступ (Python)

| Функция | Что возвращает |
|---|---|
| `service.public_instruments()` | список приборов (как `/api/instruments`) |
| `service.events.list(limit, cam_id)` | события из памяти |
| `db.get_history(instrument_id, limit)` | последние отсчёты `readings` |
| `db.get_trend(instrument_id, since, step, until)` | агрегаты по корзинам |
| `db.get_instrument_series(instrument_ids=None, *, since_iso, until_iso=None, max_per_instrument=360)` | реализация Neon (v1.1): `{instrument_id: [(unix_ts, value)]}` из `readings` и `instrument_readings`; основной агент своей версии не держит |
| `dispatch.overview(instruments, events, stream_map)` | health score и сводка (используется Modbus) |

## 6. Обратная совместимость (проверяется тестами основного агента)

1. Существующая база без таблицы `instruments` открывается, мигрирует, история и события
   доступны по прежним id.
2. `GET/POST/PATCH/DELETE /api/cameras…` работают как раньше; одна камера = один основной прибор.
3. Однокамерная конфигурация даёт те же регистры Modbus (слот 0) и те же MQTT-топики.
4. Генератор ТЗ (`spec_generator`), диспетчерский анализ (`dispatch_analyzer`) и HMI получают приборы
   из `public_instruments()` с теми же полями; дополнительные приборы — новые записи того же формата.
5. Все тесты `tests/` ветки зелёные до и после.

## 7. Нефункциональные договорённости

- Долгие и массовые прогоны — на CPU (`CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`).
- Multi-Gauge: один проход детектора на кадр источника, далее по-приборная обработка ROI.
- Без обязательных облачных API.

## 8. Чего этот контракт не фиксирует

Внутренние алгоритмы, формат отчётов, внутренние таблицы `pa_*`/`mo_*`, вёрстку HMI.

## 9. Владельцы разделов

| Раздел | Владелец |
|---|---|
| § 1, § 2, § 4.1–4.4, § 5.1 (кроме `/api/predictive`, `/api/optimizer`), § 5.2, слоты § 5.3, § 5.4 | основной агент |
| карта регистров § 5.3, проект Ignition, § 4.5, `/api/predictive/…`, `/api/optimizer/…`, событие `prediction` | Neon |
| § 3 | основной агент; новые `kind` для Neon — по запросу |

## 10. Журнал изменений

| Версия | Дата | Изменение |
|---|---|---|
| 1.0 | 2026-11-27 | первая фиксация |
| 1.1 | 2026-11-27 | сверка с реализацией Neon: `gauge_slot`, карта Modbus v2 и общий индекс слота для всех блоков, фактические таблицы аналитики, сигнатура `get_instrument_series` Neon, телеметрия по приборам только для многоприборных источников |
