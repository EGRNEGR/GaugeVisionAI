# Результаты тестирования объединённой версии GaugeVision AI 3.0

Все прогоны выполнены последовательно на CPU (`CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`, Python 3.12)
на коде ветки `next-gen/integration` после коммита `bf09895` (финальная сборка 3.0, без нагрузки на GPU).

## 1. Полная регрессия: 13 автоматических наборов

Сырые сводки и журналы: `evidence/test_runs/suites_run1_summary.txt`, `test_final_integration.log`,
`test_acceptance_independent.log`.

| № | Набор тестов | Код | Время | Фактический итог |
|---:|---|---:|---:|---|
| 1 | `tests/test_instruments_db.py` | 0 | 1 с | `ALL INSTRUMENT DB TESTS PASSED` |
| 2 | `tests/test_multigauge.py` | 0 | 62 с | `ALL MULTI-GAUGE TESTS PASSED` |
| 3 | `tests/test_multigauge_api.py` | 0 | 16 с | `ALL MULTI-GAUGE API TESTS PASSED` |
| 4 | `tests/test_autocal.py` | 0 | 1 с | `ALL AUTOCAL SAFETY TESTS PASSED` |
| 5 | `tests/test_demo_dashboard.py` | 0 | 21 с | `ALL DEMO DASHBOARD CONTRACT TESTS PASSED` |
| 6 | `tests/test_tracks_e2e.py` | 0 | 15 с | `ALL TRACK 1 & TRACK 2 E2E TESTS PASSED` (DOCX 133 262 Б, 4 фото, 3 батча S&F, HR 40901 = 36) |
| 7 | `tests/test_remediation_full.py` | 0 | 15 с | `ALL REMEDIATION TESTS PASSED: 8/8` |
| 8 | `tests/test_acceptance_independent.py` | 0 | 36 с | `ACCEPTANCE: 21/21 PASSED` |
| 9 | `tests/test_modbus_register_map.py` | 0 | <1 с | `ALL MODBUS REGISTER MAP TESTS PASSED (2/2)` |
| 10 | `tests/test_predictive_analytics.py` | 0 | <1 с | `ALL PREDICTIVE ANALYTICS TESTS PASSED (5/5)` |
| 11 | `tests/test_modernization_optimizer.py` | 0 | 5 с | `ALL MODERNIZATION OPTIMIZER TESTS PASSED (4/4)` |
| 12 | `tests/test_next_gen_integration_contract.py` | 0 | 1 с | `3/3 CONTRACT_FIXTURE_VERIFIED` (4 стыковые проверки выполняются в объединённых наборах) |
| 13 | `tests/test_final_integration.py` | 0 | 40 с | `FINAL INTEGRATION: 12/12 PASSED` |

**Итог полной регрессии:** **13 / 13 PASS**.

### Состав независимого набора `tests/test_final_integration.py` (12 / 12 PASS)

- `migration_from_real_old_code` — базы, созданные реальным кодом `1.0` (`dd25bde`), `2.0` (`94e646e`),
  `next-gen/platform` (`90dcadf`) и `next-gen/analytics-validation` (`285e896`), открываются без потерь строк;
  во всех четырёх случаях слоты Modbus назначены в порядке `created_at` (`legacy-cam-z: 0`, `legacy-cam-1: 1`, `legacy-cam-a: 2`).
- `network_policy` — проверки OBS-SHARED-01..05 (отклонены `file://`, `169.254.169.254`, публичный LLM и URL с паролем).
- `cv_forecast_input` — усреднение ряда CV по корзинам 30 с (DEF-INT-13): медианное отношение ETA `1,04` (`[1,021; 1,051]`), ложных `imminent` на стабильном ряде — `0`.
- `multigauge_calibration_isolation` — смена шкалы одного прибора щита увеличивает `calibration_rev` (`0 → 1`),
  ряд прогноза содержит только отсчёты новой ревизии (`3` строки), соседние приборы не затронуты (DEF-INT-03).
- `modbus_slots_lifecycle` — постоянные слоты `[0, 1, 2]`, очистка всех трёх блоков при удалении слота 2, повторное занятие слота 2, `MAX_REGISTERS = 5208`.
- `stream_loss_and_recovery` — переход в `STALE` через `7,4 с` без разрыва TCP, мгновенное восстановление `0,0 с` (DEF-INT-01).
- `prediction_events_lifecycle` — конечный автомат `["imminent", "cleared", "imminent", "withdrawn", "imminent", "realized"]`, ETA `27,1 мин`, запись в журнал и S&F без дублей.
- `monitoring_vs_optimizer` — таймаут `0,06 с` → `time_limit`; расчёт на 500 приборах с кривой Парето уложился в общий лимит 2 с (`1,766 с`, `frontier_complete = true`, задержка loop p95 `36,6 мс`, DEF-INT-05).
- `spec_matches_saved_plan` — MD (`13 415 Б`) и DOCX (`67 394 Б`) совпадают с сохранённым планом (3 позиции).
- `new_api_security` — RBAC 401/403 и валидация 422/404 на всех маршрутах Multi-Gauge, прогноза и оптимизатора.
- `autocal_cannot_apply` — проверено 78 маршрутов (маршрутов автокалибровки нет), ревизии растут только по явному PATCH (`[2, 3, 4]`, 4 записи в `audit_log`).
- `restart_persistence` — после перезапуска сохранены 3 прибора и 49 отсчётов.

*Примечание по чистоте дерева:* `test_multigauge.py` перезаписывает файл доказательств ветки platform
`reports/next_generation/evidence/multigauge/multigauge_synthetic.json`; после прогона файл возвращён в исходное
состояние через `git checkout --`, исторические доказательства агентов не изменены.

## 2. Повтор исходных аудитов (`rerun_original_audits.py`)

Доказательства: `evidence/original_audit_rerun/rerun_summary.json` и JSON-отчёты всех 6 запусков.

| Аудит | Скрипт | Код | Время | Ключевые показатели на финальном коде |
|---|---|---:|---:|---|
| `audit_01_cv_regression` | `audit_01_cv_regression.py` | 0 | 8,3 с | YOLO CPU загружен; CW 17/17 (MAE 0,079 % шкалы, 0 пропусков), CCW 5/5 (MAE 0,084 %), отр. шкала 5/5 (MAE 0,093 кПа), отбраковка пустых/бликов/44 % перекрытия |
| `audit_02_qos1_default` | `audit_02_track2_streams_sf_scada.py` | 0 | 37,7 с | 11 сценариев качества сигнала, Adaptive FPS (переключение 0,016 мс), Ring Buffer 2/2 параллельных инцидента, S&F WAL A–G (0 потерь, 0 дублей, cap 30), Modbus/MQTT без тихой потери |
| `audit_02_qos0_emulator_compat` | `audit_02_track2_streams_sf_scada.py` (`QOS=0`) | 0 | 32,5 с | Обратная совместимость QoS 0 подтверждена |
| `audit_03_security_rbac_on` | `audit_03_track1_dispatch_specs_security.py` | 0 | 8,6 с | 12 сигналов диспетчеризации (нет фантомных минут и влияния оптики на Health Score), 9 кейсов ТЗ + LLM fallback, RBAC 401 на неавторизованных запросах |
| `audit_04_hmi_auth_off_compat` | `audit_04_hmi_browser_airgap_e2e.py` (`AUTH=0`) | 0 | 39,5 с | WSS смартфона 20/23 годных (`normal`/`warning`/`alert`), браузер 3 разрешения (0 переполнений, 0 middle dot, 0 ошибок JS, 0 внешних запросов), DOCX 133 177 Б (4 фото, 5 разделов) |
| `audit_05_soak_edge_cases` | `audit_05_soak_and_edge_cases.py` | 0 | 27,3 с | SQLite 84 150 стр/с, S&F drain 61 843 стр/с, DOCX 35,1 мс, Adaptive FPS экономия CPU **79,2 %**, кадр 4×4 без исключения |

**Итог исходных аудитов:** **6 / 6 PASS**.

## 3. Повторяемость и устойчивость плавающих наборов

Этот раздел фиксирует фактические результаты повторных прогонов для дефектов `DEF-INT-03`, `DEF-INT-08`,
`DEF-INT-14` и известного плавающего тайминга `test_demo_dashboard`. Утверждения тестов не ослаблялись.

| Набор | Прогон 1 (`suites_run1`) | Прогон 2 (`suites_rep2`) | Прогон 3 (`suites_rep3`) | Итог |
|---|---:|---:|---:|---|
| `test_acceptance_independent` (21 проверка, в т. ч. `auto_spec_generation_lifecycle` — DEF-INT-08) | **21/21 PASS** (36 с) | **21/21 PASS** (36 с) | **21/21 PASS** (36 с) | **3 / 3 PASS** |
| `test_final_integration` (12 проверок, в т. ч. `multigauge_calibration_isolation` — DEF-INT-03) | **12/12 PASS** (40 с) | **12/12 PASS** (40 с) | **12/12 PASS** (40 с) | **3 / 3 PASS** |
| `test_demo_dashboard` (WSS смартфон + 36 позиций + демозапись) | **PASS** (21 с) | **PASS** (22 с) | **PASS** (21 с) | **3 / 3 PASS** |

Историческая оговорка: до финальной серии, на одном из промежуточных прогонов, `test_demo_dashboard` дал 1 сбой
по таймингу ожидания отсчёта после 6 кадров. На финальном коде зафиксированы 3 успешных прогона подряд из 3.
Исправление `DEF-INT-14` (приоритет кода основного прибора) дополнительно подтверждено сквозным прогоном E2E № 5
с реальной Ignition 8.3.10 (`PI-107` в плане, MD и DOCX).

## 4. Сторонние реализации протоколов (`interop_rtsp_mqtt_modbus.py`)

Доказательство: `evidence/interop/interop_results.json`.

- **Замечание по запуску:** в первом вызове из `post_soak.sh` скрипт завершился с кодом 1 на шаге `modbus_probe`,
  поскольку переменная `GV_TOOLS_PY` указывала на вспомогательное окружение без пакета `pymodbus`. После указания
  штатного окружения инструментов стенда (`pymodbus 3.16.2` + `amqtt 0.12.2`) прогон выполнен целиком без правок кода.
- **RTSP (`mediamtx` с аутентификацией + `ffmpeg` H.264):** подключение `4,03 с`, точность `80/80` в ±0,35 МПа
  (MAE `0,0282 МПа`, p50 обработки `65,8 мс`), обрыв издателя восстановлен за `10,07 с`, перезапуск сервера —
  за `14,11 с`, инференс возобновлён (`0,0 с`), 2 соседних канала оставались `online`, пароль RTSP не утек (`0` в API и логе).
  В момент обрыва `frame_drop_pct = 1,0 %` (`OFFLINE`); `packet_loss_pct` остаётся `null` → `REQ-VA-08` остаётся **PARTIAL**.
- **MQTT 3.1.1 QoS 1 (`amqtt`):** обрыв брокера обнаружен за `6,0 с` (`BUFFERING`, пик `22` записи), досылка
  за `9,05 с`, сверено `109 / 109` записей (`0` потерь, `0` дублей), доставлено `3 / 3` кадра тревог с совпадением SHA-256.
- **Смартфон WSS (`/ws/phone`):** `221 / 221` кадров с `ack`, 0 ошибок.
- **Modbus TCP (`pymodbus 3.16.2`):** `30 / 30` значений совпали с REST, `STALE = NaN`, чужой `unit_id = 99`
  отклонён с кодом исключения `11` (`0x0B`). *Прозрачное примечание:* проверка `out_of_range_address` в старом
  скрипте 2.0 опрашивала адрес `5000`, который в версии 3.0 является валидным адресом продлённого прогнозного
  блока (`4096–5207`, `MAX_REGISTERS = 5208`), поэтому вернула данные; отказ `0x02` на реальной границе карты
  (`5208`) подтверждён в `SEC-10`, `test_modbus_register_map` и `modbus_slots_lifecycle`.

**Итог interop:** **16 / 16 флагов вердикта PASS** (`passed: true`).

## 5. Браузерные проверки HMI (Playwright)

| Проверка | Разрешения | Ошибки JS / Page / HTTP / внешние | Переполнение / middle dot | Доказательство |
|---|---|---|---|---|
| `browser_e2e.py` (контуры 2.0 + RBAC + S&F + деградации + ТЗ) | 1920×1080, 1440×900, 1280×720 (9 видов) | 0 / 0 / 0 / 0 | 0 / 0 | `evidence/browser_e2e/browser_e2e_report.json` |
| `hmi_check.mjs` (все 8 вкладок 3.0 включая «Щит», прогноз, оптимизатор, Парето, сохранение плана, DOCX/MD) | 1920×1080, 1440×900, 1280×720 (24 вида) | 0 / 0 / 0 / 0 | 0 / 0 | `evidence/hmi/hmi_results.json`, `evidence/hmi/screens/` |

В `hmi_check.mjs` на всех трёх разрешениях подтверждены: 41 строка прогноза, расчёт оптимизатора и отрисовка
кривой Парето (`pareto_painted = true`), сохранение планов (`0 → 1 → 2 → 3`), скачивание DOCX (`~134 КБ`) и MD
(`~37–39 КБ`), отображение 5 приборов и живого кадра на вкладке «Щит».

## 6. Аудит безопасности, миграции и статический скан

- **Аудит безопасности (`evidence/security/security_audit_merged.json`):** **11 / 11 PASS** (`SEC-01..SEC-11`, граница Modbus `MAX_REGISTERS`). См. `SECURITY_FINAL_REPORT.md`.
- **Миграции копий реальных локальных БД (`evidence/migration/migration_copies.json`):** **3 / 3 PASS**, 0 потерянных строк. См. `DATABASE_MIGRATION_REPORT.md`.
- **Статический скан (`evidence/static/static_scan.json`):** проверен 91 файл — `clean: true` (0 `TODO`/`FIXME`, 0 `NotImplementedError`, 0 жёстких путей Windows/пользователя, 0 `·` в UI).
