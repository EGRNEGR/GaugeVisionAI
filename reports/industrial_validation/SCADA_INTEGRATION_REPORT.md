# Отчёт о промышленной стыковке GaugeVision AI с SCADA Ignition 8.3.10 (REQ-API-07)

**Дата испытания:** 27 ноября 2026 г.  
**Ветка разработки:** `next-gen/scada-ignition` (создана от `origin/GaugeVision-2.0`, коммит `94e646e`)  
**Объект проверки:** требование **REQ-API-07** («Подтверждённая стыковка с реальными SCADA-системами Ignition или MasterSCADA»)  
**Вердикт по REQ-API-07:** **PASS** (с явно зафиксированными лабораторными ограничениями)  
**Итоговый расчёт по матрице 75 требований:** **97,79 / 100** (`+1,14` к базовым `96,65 / 100`; `73 PASS / 1 PARTIAL / 0 FAIL / 1 NOT VERIFIED`; `REQ-CV-05` не затрагивался).

---

## 1. Конфигурация стенда и версия SCADA

Испытание выполнено на реальной промышленной SCADA-платформе **Inductive Automation Ignition 8.3.10** без использования самописных эмуляторов или Python-клиентов вместо SCADA.

| Компонент | Версия / параметры | Примечание |
|---|---|---|
| SCADA-платформа | **Ignition Standard 8.3.10 (b2026100610)** | Дистрибутив `Ignition-windows-x86-64-8.3.10.zip`, SHA-256 `E6BB39118F4C517709BA65870553C45BB9A75575865068DD74767885371BAE88` |
| Режим запуска Ignition | Консольный `IgnitionGateway.exe -c .\data\ignition.conf` | Без установки Windows-службы и без прав администратора; каталог `C:\Hakatons\gv_scada_lab\ignition-8.3.10\` (вне репозитория) |
| Модули Ignition | `Modbus Driver v8.3.10`, `OPC-UA v10.3.10`, `Perspective v3.3.10`, `Historian Core` | Лицензия: 2-часовой trial-режим, мастер первого запуска пройден вручную на `http://localhost:8088` |
| Историческая БД SCADA | `Sample_SQLite_Database` (`sqlt_data_1_2026_11`) | Встроенный Tag Historian Ignition (114 тегов на записи) |
| Шлюз GaugeVision AI | `app/scada_gateway.py` (`ModbusTcpGateway`, карта v2) | Режим CPU (`CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`), профиль `--demo` (36 приборов), Modbus TCP `127.0.0.1:15020`, Unit ID `1`, только чтение (FC `0x03`/`0x04`) |
| Устройство в Ignition | `GaugeVisionModbus` (`ModbusTcp`) | `hostname=127.0.0.1`, `port=15020`, `zeroBasedAddressing=true`, `reverseWordOrder=false`, запросы записи отключены |

---

## 2. Расширение карты регистров Modbus TCP v2 и проверка адресации

В `app/scada_gateway.py` реализована обратно совместимая карта Holding-регистров v2 (`MAX_REGISTERS = 4096`, `REGISTER_MAP_VERSION = 2`), задокументированная в `docs/MODBUS_REGISTER_MAP.md` и покрытая модульными тестами `tests/test_modbus_register_map.py`:

- **Базовый блок приборов v1 (0..799 / HR 40001..40800, шаг 4)** — не изменён: `addr+0..+1` IEEE-754 `float32` (big-endian, старшее слово первым; `quiet NaN = 0x7FC00000` при недостоверном/устаревшем показании), `addr+2` код статуса (`0=OK`, `1=WARNING`, `2=CRITICAL`, `3=STALE`), `addr+3` `Health Score × 10` (`0..1000`).
- **Системный блок v1 (900..905 / HR 40901..40906)** — не изменён: всего приборов, число `CRITICAL`, число `WARNING`, число `STALE`, размер очереди Store-and-Forward, флаг обрыва канала АСУ ТП.
- **Системное расширение v2 (906..911 / HR 40907..40912):**
  - `906` — `heartbeat` (`uint16`, инкремент на каждом цикле обновления, обёртка `65535 → 0`);
  - `907..908` — `last_sync_unix` (`uint32` big-endian, время последней синхронизации UTC);
  - `909` — версия карты (`2`), `910` — база расширенного блока (`2000`), `911` — шаг расширенного блока (`8`).
- **Расширенный блок приборов v2 (`ext = 2000 + idx * 8`, адреса 2000..3599):**
  - `ext+0` — возраст показания в секундах (`uint16`, насыщение `0..65535`);
  - `ext+1` — уверенность распознавания CV × 1000 (`uint16`, `0..1000`);
  - `ext+2` — 8-битовая маска флагов состояния (`camera_online`, `dial_detected`, `reading_valid`, `calibration_set`, `is_simulated`, `confidence_available`, `reading_stale`, `alarm_active`);
  - `ext+3..+4` — `last_valid_unix` (`uint32` big-endian);
  - `ext+5..+6` — `last_valid_value` (`float32` big-endian / `NaN`);
  - `ext+7` — резерв (`0`).

### Подтверждение адресации и порядка слов на живом обмене

Настройками драйвера `zeroBasedAddressing = true` и `reverseWordOrder = false` подтверждено прямое соответствие `1.HRF{idx*4}`, `1.HRUS{idx*4+2}`, `1.HRUS900..906`, `1.HRUI907` и `1.HRUS{2000+idx*8}` регистрам GaugeVision без смещения на 1 и без перестановки слов:

- Отрицательные числа (`К1-У01 = -16,2 мм`, `К1-ТН1 = -48,0 Па`, `ТА1-Р02 = -92,4 кПа`, `ДС1-ТН1 = -2,18 кПа`) декодируются Ignition с точным знаком и мантиссой.
- Высокие значения (`К1-Т01 = 570,38 °C`, `ГРП-F01 = 18 450 м³/ч`) и дробные значения (`К2-Р01 = 13,635 МПа`, `Д6-Р01 = 0,588 МПа`) совпадают с REST-снимком `/api/scada/modbus/registers`.
- Невалидные/устаревшие каналы (`К1-Р01`, `ДС1-ТН1`, `СН1-Т02`, `ПСГ-Р01` в соответствующих режимах) передают `0x7FC00000` (`quiet NaN`) и `Status = 3`: в Ignition Expression-тег `IsNoData` принимает значение `1`, а на мнемосхеме отображается «Нет данных», исключая подмену обрыва нулём.

---

## 3. Теги и мнемосхема Perspective в Ignition

- **Дерево тегов (`integrations/ignition/tags/gaugevision_tags.json`):** импортировано **738 read-only тегов** (`successCount = 738`, `failureCount = 0`) в провайдере `[default]GaugeVision/` — системный блок (`System/`), Expression-теги контроля свежести (`LinkConnected`, `HeartbeatAgeSec`, `DataStale`, `GatewayStatusText`), а также 36 папок приборов `P01_K1_R01`..`P36_KMP_R01` (базовые, расширенные и расчётные теги `Health`, `Confidence`, `IsNoData`, `DisplayValue`, `StatusLabel`).
- **Мнемосхема Perspective (`integrations/ignition/projects/GaugeVisionLab/` и `GaugeVisionLab.zip`):** экран «GaugeVision — пульт» в сдержанной палитре ISA-101 (спокойный серый для штатного режима, янтарный для `WARNING`, красный для `CRITICAL`, штриховая рамка «Нет данных» для `NaN`/`STALE`, шильд «НЕТ СВЯЗИ» при обрыве TCP). В верхней панели выводятся статус шлюза, `Heartbeat (HR 906)` с возрастом, системные счётчики `900–905`, ниже — матрица `6×6` всех 36 приборов и 4-канальный исторический тренд Tag Historian (`К1-Т01`, `ТА2-Т02`, `Д6-У01`, `СН1-Т01`).

---

## 4. Результаты функциональных и отказных сценариев

Все сценарии выполнены против живого экземпляра Ignition 8.3.10; результаты зафиксированы в `reports/industrial_validation/evidence/scada/scada_scenarios_results.json` и подтверждены 9 скриншотами `1920×1080`.

| Сценарий | Проверяемое поведение | Замеренные показатели | Результат | Скриншоты |
|---|---|---|---|---|
| **1. Штатный режим (`nominal`)** | Отсутствие ложных тревог, корректный `NaN` на неподключённой камере `К1-Р01` | `ActiveCritical = 0`, `ActiveWarning = 0`, `StaleChannels = 1`, `К1-Т01 = 539,27 °C (OK)`, `К1-Р01 IsNoData = 1` | **PASS** | `scada_02_nominal.png` |
| **2. Аварийный каскад (`cascade`)** | Живые переходы `OK → CRITICAL/WARNING/STALE` и `NaN` на `СН1-Т02` | Переход за **4,59 с**: `ActiveCritical = 4`, `ActiveWarning = 4`, `StaleChannels = 3`, `К1-Т01 = 572,60 °C (CRITICAL)`, `СН1-Т02 Status = 3 / IsNoData = 1` | **PASS** | `scada_03_cascade_alarms.png` |
| **3. Буферизация Store-and-Forward (HR 904/905)** | Отражение обрыва верхнего канала АСУ ТП, роста очереди и дренирования после восстановления | Флаг `OutageFlag = 1` за **4,08 с**, рост очереди `SfQueuePending >= 3` за **3,83 с** (пик на экране `8`), баннер «БУФЕРИЗАЦИЯ АСУ ТП»; возврат к `OutageFlag = 0` и `SfQueuePending = 0` за **3,83 с** | **PASS** | `scada_04_sf_outage.png` |
| **4. Зависание `heartbeat` HR 906 без обрыва TCP** | Обнаружение «зависшего» процесса при живом TCP-сокете (через `POST /api/architecture/modbus/freeze`) | `LinkConnected` остался `1` (`Good quality = 192`), `Heartbeat` замер на `25`, `DataStale = 1` («ДАННЫЕ УСТАРЕЛИ») выставлен за **10,2 с** (порог > 8 с); после снятия заморозки возврат `DataStale = 0` за **3,69 с** | **PASS** | `scada_05_heartbeat_stale.png` |
| **5. Реальный обрыв TCP и автовосстановление** | Остановка процесса GaugeVision, переход тегов в `Bad` quality, статус `DISCONNECTED` в Ignition Devices, затем перезапуск шлюза | Обнаружение обрыва `LinkConnected = 0` и падение качества тегов `192 → 0 (Bad)` за **1,84 с**; статус устройства `DISCONNECTED`; на экране красный баннер «НЕТ СВЯЗИ» по всем 36 плиткам. После рестарта шлюза (`boot = 5,05 с`) автовосстановление Ignition заняло **0,02 с** после готовности порта (**5,06 с** суммарно), качество вернулось в `192 (Good)` | **PASS** | `ign_00_devices_connected.png`, `ign_01_device_disconnected.png`, `scada_06_link_lost.png`, `scada_07_recovered.png` |

---

## 5. Непрерывная 30,6-минутная сверка журналов Ignition ↔ GaugeVision

Для подтверждения устойчивости длительного обмена выполнен непрерывный прогон длительностью **1838,7 с (30,65 мин)** с автоматическим переключением технологических режимов (`mixed → nominal → peak → cascade → mixed`) и независимой сверкой архива **Ignition Tag Historian** (`Sample_SQLite_Database`, таблица `sqlt_data_1_2026_11`) с REST-снимками Modbus-карты GaugeVision каждые 10 секунд по всем 36 приборам.

| Метрика длительного испытания | Фактическое значение |
|---|---|
| Интервал прогона (UTC) | `2026-11-27T07:58:59.907Z` — `2026-11-27T08:29:38.621Z` |
| Фактическая длительность | **1838,7 с** (**30,65 мин**, требование ≥ 30 мин выполнено) |
| Снимков GaugeVision / проверено приборов | **184** снимка × **36** приборов = **6 624** парных замера |
| Обслужено запросов Modbus TCP (FC `0x03`) | **11 124** (`rejected_unit_ids = 0`) |
| Точек `Heartbeat` (HR 906) в Historian Ignition | **918** (`LinkConnected = 99,73 %`) |
| Валидных числовых пар / пар `NaN` (`STALE`) | **6 271** числовых / **353** `NaN` |
| Доля `Good` quality (`192`) в Ignition | **100,0 %** (6 624 / 6 624) |
| Совпадение кодов состояния (`OK`/`WARNING`/`CRITICAL`/`STALE`) | **100,0 %** (6 624 / 6 624) |
| Совпадение `NaN` / «Нет данных» (`IsNoData`) | **100,0 %** (353 / 353) |
| Среднее относительное расхождение по 6 271 числовым парам | **0,2775 %** (p95: **0,6783 %**) |
| Среднее абсолютное расхождение (MAE / p95) | **0,4645** / **1,60** в физических единицах каналов |

*Пояснение к остаточному расхождению 0,28 %:* GaugeVision обновляет стендовые синусоиды раз в 1 с, а Tag Historian Ignition записывает точки с интервалом опроса `~2 с` (deadband по изменению); наибольшие единичные абсолютные дельты (`46,9 м³/ч` на `ГРП-F01` при шкале `30 000 м³/ч` — это всего `0,25 %`, и `2,6 мм` на `К1-У01` вблизи перехода через `0 мм` на 400-миллиметровой шкале) полностью объясняются межвыборочным сдвигом фазы ~1 с между опросом Historian и REST-снимком. Систематического смещения или ошибок декодирования IEEE-754 `float32` нет ни по одному из 36 приборов.

Полная поприборная сводка по всем 36 позициям сохранена в `reports/industrial_validation/evidence/scada/reconciliation_30min_summary.json` и `reconciliation_30min_summary.csv`, выборка парных замеров — в `reconciliation_30min_samples.csv`, выдержка журнала запуска и работы шлюза Ignition — в `ignition_wrapper_excerpt.log`.

---

## 6. Регрессионное тестирование (CPU)

Сравнение прогона тестов до внесения изменений (`94e646e`) и после завершения всех доработок ветки `next-gen/scada-ignition` (`CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`):

| Тестовый набор | До изменений (`94e646e`) | После изменений (`next-gen/scada-ignition`) | Примечание |
|---|---|---|---|
| `tests/test_modbus_register_map.py` | — (новый) | **PASS (2/2)** | Карта v1 + v2, `NaN`, флаги, `heartbeat` wrap, выключенный Modbus не слушает порт |
| `tests/test_demo_dashboard.py` | **PASS** | **PASS** | Контракт 36 позиций, WSS, QR, авторизация, CSV |
| `tests/test_tracks_e2e.py` | **PASS** | **PASS** | Track 1 + Track 2 (`docx=133 190 B`, `media_imgs=4`, `sf_batches=3`, `HR40901=36`) |
| `tests/test_remediation_full.py` | **PASS (8/8)** | **PASS (8/8)** | MQTT QoS 1, S&F, CV overlay, потоки, dispatch, spec, RBAC, HTTP-MJPEG |
| `tests/test_acceptance_independent.py` | 20/21* | **PASS (21/21)** | *На базовом коммите `94e646e` фиксировался плавающий тайминг в `auto_spec_generation_lifecycle` (`sim-12`); после доработок все 21/21 проверок пройдены |

---

## 7. Пересчёт матрицы 75 требований (методика `build_rtm.py`)

Пересчёт выполнен скриптом `reports/industrial_validation/build_rtm_scada.py` с сохранением исходных `reports/audit/` и `reports/remediation/` без изменений. Требование **`REQ-CV-05` не затрагивалось** (остаётся `NOT VERIFIED`).

| Направление | Макс. балл | Было (после remediation) | Стало (после SCADA) | Изменение |
|---|---:|---:|---:|---:|
| Архитектурная видеоаналитика | 12 | 11,45 (10 PASS, 1 PARTIAL) | 11,45 (10 PASS, 1 PARTIAL) | 0,00 |
| Store-and-Forward и отказоустойчивость | 15 | 15,00 (12 PASS) | 15,00 (12 PASS) | 0,00 |
| **API и промышленные интеграции** | **8** | **6,86 (6 PASS, 1 NOT VERIFIED)** | **8,00 (7 PASS)** | **+1,14** |
| Аналитика и умная диспетчеризация | 15 | 15,00 (9 PASS) | 15,00 (9 PASS) | 0,00 |
| Генерация инженерной документации | 15 | 15,00 (10 PASS) | 15,00 (10 PASS) | 0,00 |
| Корректность и сохранение CV-инференса | 10 | 8,33 (5 PASS, 1 NOT VERIFIED) | 8,33 (5 PASS, 1 NOT VERIFIED) | 0,00 |
| Функциональность и качество HMI | 10 | 10,00 (7 PASS) | 10,00 (7 PASS) | 0,00 |
| Безопасность и автономность | 8 | 8,00 (6 PASS) | 8,00 (6 PASS) | 0,00 |
| Архитектура и качество кода | 4 | 4,00 (4 PASS) | 4,00 (4 PASS) | 0,00 |
| Тестирование и воспроизводимость | 3 | 3,00 (3 PASS) | 3,00 (3 PASS) | 0,00 |
| **ИТОГО** | **100** | **96,65** | **97,79** | **+1,14** |

- **Распределение 75 требований:** `73 PASS / 1 PARTIAL / 0 FAIL / 1 NOT VERIFIED`.
- **Соответствие требованиям:** `98,0 %` (`(73 + 0,5) / 75`).
- **Доля верифицированных требований:** `98,7 %` (`74 / 75`).
- Новая матрица сохранена в `reports/industrial_validation/REQUIREMENTS_TRACEABILITY_MATRIX.csv`, сводка расчёта — в `reports/industrial_validation/evidence/scada/score_after_scada.json`.

---

## 8. Честные ограничения испытания

1. **Trial-режим Ignition:** испытания проведены в ознакомительном 2-часовом режиме Ignition Standard 8.3.10 (функционально идентичном коммерческой лицензии для Modbus Driver v2, Tag Historian и Perspective).
2. **Локальный контур `127.0.0.1` и режим read-only:** обмен проверялся на локальном loopback-интерфейсе (`127.0.0.1:15020`) без маршрутизации через промышленный межсетевой экран/DMZ и строго на чтение (FC `0x03`/`0x04`).
3. **MasterSCADA 4D не испытывалась:** формулировка REQ-API-07 допускает подтверждение на Ignition или MasterSCADA; в данной работе подтверждена стыковка с Ignition 8.3.10.
4. **Демонстрационная телеметрия на 35 из 36 каналов:** во время 30,6-минутного прогона позиция `К1-Р01` работала как неподключённая живая камера (проверяя стабильность `NaN`/«Нет данных»), а 35 каналов формировались стендовым генератором КТЦ ТЭЦ.
5. **Метрологический статус:** шлюз GaugeVision AI передаёт вспомогательную информационно-аналитическую телеметрию и не предназначен для контуров ПАЗ и средств измерений утверждённого типа (ФЗ-102).

---

## 9. Артефакты в репозитории

- Код и документация шлюза: `app/scada_gateway.py`, `app/main.py`, `docs/MODBUS_REGISTER_MAP.md`, `tests/test_modbus_register_map.py`.
- Артефакты Ignition (без паролей, токенов и бинарников): `integrations/ignition/README.md`, `integrations/ignition/device_config_template.json`, `integrations/ignition/tags/gaugevision_tags.json`, `integrations/ignition/projects/GaugeVisionLab/`, `integrations/ignition/projects/GaugeVisionLab.zip`.
- Доказательства испытаний: `reports/industrial_validation/evidence/scada/` (9 скриншотов `1920×1080`, `scada_scenarios_results.json`, `reconciliation_30min_summary.json`, `reconciliation_30min_summary.csv`, `reconciliation_30min_samples.csv`, `ignition_wrapper_excerpt.log`, `score_after_scada.json`).
- Матрица требований и прогресс: `reports/industrial_validation/REQUIREMENTS_TRACEABILITY_MATRIX.csv`, `reports/industrial_validation/SCADA_PROGRESS.md`, `.autopilot/PROGRESS.md`.
