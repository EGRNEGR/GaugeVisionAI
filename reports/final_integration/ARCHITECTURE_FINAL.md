# Архитектура GaugeVision AI 3.0 (объединённая версия)

Один процесс Python (FastAPI, asyncio, HTTPS) на пограничном узле. Видеозахват и CV — в потоках и пуле
`executor`, аналитика и оптимизатор — в отдельном пуле `analytics_executor` (2 потока), оперативный контур
(event loop: WebSocket, SSE, Modbus TCP, Store-and-Forward) их не ждёт. Данные — SQLite (WAL), очередь
Store-and-Forward — отдельная база SQLite. Облачные сервисы не нужны.

## 1. Поток данных

```
видеоисточник (RTSP / HTTP-MJPEG / USB / смартфон по WSS / видеофайл)
  └─ воркер захвата ─► FrameBroker (последний кадр, свежесть потока)
        └─ цикл обработки источника
              ├─ один прибор: GaugePipeline (YOLO → эллипс → шкала → стрелка → EMA)
              └─ щит: MultiGaugeProcessor (один проход детектора, трекер якорей, по-приборные конвейеры)
                    └─ _on_reading(instrument_id, view с calibration_rev)
                          ├─ отсчёт по устаревшей шкале → отброшен
                          ├─ состояние прибора (last), уставки → EventLog (alarm)
                          ├─ буфер записи → SQLite readings (instrument_id, calibration_rev)
                          └─ телеметрия щита → Store-and-Forward → MQTT {instrument_id}/telemetry
цикл синхронизации (2 с)
  ├─ DispatchAnalyzer (Health Score, причины)
  ├─ раз в 10 с PredictiveAnalyzer (в analytics_executor) → PredictionEventTracker → EventLog (prediction)
  ├─ ModbusTcpGateway.update_from_instruments(public_instruments()) — постоянные modbus_slot
  └─ автодокументы ТЗ по деградации
API /api/optimizer/* → ILP (analytics_executor, Semaphore(2), общий time_limit_s) → modernization_plans
API /api/specs/* → spec_generator (Markdown / DOCX, раздел плана модернизации)
```

## 2. Модули

| Модуль | Ответственность | Происхождение |
|---|---|---|
| `app/main.py` | сервис `GaugeService`, жизненный цикл, REST/WS/SSE, цикл синхронизации | общий |
| `app/vision.py`, `app/multigauge.py`, `app/multigauge_service.py` | CV одного прибора и щита, реестр приборов, телеметрия щита | platform |
| `app/db.py` | схема и миграции SQLite, история, реестр приборов, паспорта, планы | общий |
| `app/contracts.py` | идентичность прибора (`instrument_id`, `camera_id`, `gauge_slot`) | Neon |
| `app/scada_gateway.py` | Modbus TCP (карта v2 + продление прогнозного блока), MQTT 3.1.1 | общий |
| `app/store_forward.py` | очередь S&F (seq_id, идемпотентность, вытеснение, приоритеты) | 2.0 |
| `app/predictive_analytics.py` | тренды, PI80/PI95, ETA до уставок, аномалии | Neon |
| `app/prediction_events.py` | переходы прогноза в события без дублей | интеграция |
| `app/ilp_solver.py`, `app/modernization_optimizer.py` | 0-1 ILP, кривая Парето, сравнение с жадным | Neon |
| `app/spec_generator.py`, `app/docx_builder.py` | ТЗ и дефектная ведомость (.md, .docx) | 2.0 + Neon |
| `app/net_policy.py` | сетевая политика развёртывания (OBS-SHARED-01..05) | интеграция |
| `app/autocal.py` | исследовательский модуль автокалибровки — **выключен, не подключён** | platform |
| `static/` | пульт оператора (ES-модули без сборки и CDN): «Щит», прогноз, оптимизатор, конструктор ТЗ | общий |
| `integrations/ignition/` | теги и проект Perspective для Ignition 8.3 | Neon |

## 3. Идентификаторы и ревизии

- `source_id` = `cameras.id`; основной прибор источника — `instrument_id = source_id`, `gauge_slot = 0`;
  дополнительные — UUID v4, `gauge_slot` 1…
- `modbus_slot` — постоянный глобальный номер 0…199; освобождается при удалении прибора, все три блока слота
  переходят в NaN / STALE.
- `calibration_rev` — растёт при каждом изменении шкалы; отсчёты несут ревизию, ряд прогноза берёт только
  текущую.

## 4. Карта Modbus TCP (только чтение, FC 0x03/0x04)

| Блок | Адреса (0-based) | Слоты | Изменения при интеграции |
|---|---|---|---|
| базовый | 0…799, шаг 4 | 0…199 | свободные слоты — NaN / STALE с запуска |
| системный | 900…917 | — | HR 905 — также реальный отказ брокера; 916 — база продолжения прогнозного блока (4096), 917 — его первый слот (61) |
| расширенный | 2000…3599, шаг 8 | 0…199 | без изменений |
| прогнозный | 3600…4087, шаг 8 | 0…60 | без изменений |
| прогнозный, продолжение | 4096…5207, шаг 8 | 61…199 | новое; `MAX_REGISTERS` = 5208 |

Существующие привязки Ignition (слоты 0…35, адреса ниже 4096) не сдвинулись.

## 5. События

`alarm` (уставки, требует квитирования), `link` (связь), `ack`, `config`, `instrument` (сопровождение приборов
щита; потеря требует квитирования), `prediction` (подсказка, без квитирования). Все — в EventLog (RAM),
SQLite `events`, рассылка пультам; `alarm`, `link`, `prediction` — в Store-and-Forward и MQTT
(`{instrument_id}/alarm`, поле `kind`).

## 6. Конфигурация безопасности

См. `SECURITY_FINAL_REPORT.md`: роли operator / engineer / admin, сессии, блокировка перебора, шифрование
учётных данных RTSP, сетевая политика (`GAUGEVISION_STRICT_NETWORK`, `GAUGEVISION_MQTT_TLS`,
`GAUGEVISION_MODBUS_ALLOWED_CLIENTS`, `GAUGEVISION_LLM_ALLOW_PUBLIC`).
