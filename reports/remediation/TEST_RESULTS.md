# Результаты испытаний повторной приёмки GaugeVision AI

Испытания проведены 26–27.11.2026 на финальном коде ветки `remediation/acceptance`. Все прогоны, кроме разделов 9 и 10, шли на CPU (`CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`) в изолированных временных каталогах на локальном узле. Каждый результат ниже взят из сохранённого вывода. Повторный запуск — командами из раздела 12.

## 1. Сводка

| № | Набор | Тип | Результат | Доказательство |
|---|---|---|---|---|
| 1 | `tests/test_tracks_e2e.py` | Исходный, треки 1 и 2 | PASS | `evidence/test_runs/test_tracks_e2e.log` |
| 2 | `tests/test_demo_dashboard.py` | Исходный, контракт пульта | PASS | `evidence/test_runs/test_demo_dashboard.log` |
| 3 | `tests/test_remediation_full.py` | Antigravity | 8 / 8 PASS | `evidence/test_runs/test_remediation_full.log` |
| 4 | `tests/test_acceptance_independent.py` | Независимый, повторная приёмка | 21 / 21 PASS | `evidence/acceptance_tests/acceptance_results.json` |
| 5 | Исходные аудиты Gemini `audit_01…05` без изменений | Аудит | 6 прогонов, код 0; 10 из 11 флагов дефектов сняты, оставшийся объяснён | `evidence/original_audit_rerun/` |
| 6 | Интеграция RTSP + MQTT + Modbus со сторонними реализациями | Интеграционный | 16 / 16 PASS | `evidence/interop/interop_results.json` |
| 7 | Браузерный E2E (Chromium, три разрешения) | E2E | PASS, 0 сбоев | `evidence/browser_e2e/` |
| 8 | Чистая offline-установка и сетевой аудит runtime | Развёртывание | 14 / 14 PASS, 0 сетевых событий | `evidence/offline_install/` |
| 9 | USB/UVC-камера | Оборудование | 5 / 5 PASS | `evidence/usb_camera/` |
| 10 | Реальная локальная LLM (Ollama, qwen3.5) | Интеграционный | 6 / 6 PASS после исправления NEW-13 | `evidence/llm/` |
| 11 | GPU RTX 5060 Laptop: точность, задержка, VRAM, 5 мин нагрузки | Производительность | Выполнено, 0 ошибок | `evidence/gpu_rtx5060_laptop/` |
| 12 | Часовой soak работающего конвейера | Длительный | 17 / 17 после исправления критериев скрипта (исходный вердикт: 15 / 16) | `evidence/soak/`, `SOAK_TEST_REPORT.md` |
| 13 | CPU-бенчмарк | Производительность | Выполнен | `evidence/benchmark/`, `PERFORMANCE_COMPARISON.md` |
| 14 | Статический скан кода и скриптов | Качество кода | 64 файла, чисто | `evidence/static_scan.json` |

Наборы 1–3 запускались с `-W error::RuntimeWarning`, чтобы предупреждения о неожидаемых корутинах (NEW-07) ломали прогон.

## 2. Контроль изменений в тестах

После аудита в исходные наборы 1 и 2 добавлен только шаг входа, без него RBAC отвечает 401; сами проверки не менялись. В `test_remediation_full.py` (Antigravity) найдено три ослабления:

| Ослабление | Чем компенсировано |
|---|---|
| SHA-256 кадра сверяется при постановке в очередь, а не на стороне получателя | `store_forward_frames_duplicates_growth`: SHA-256 у получателя; подписчик amqtt в интеграционном прогоне и soak |
| Кольцевой буфер проверяется по числу клипов, а не по идентичности кадров | `ring_buffer_concurrent_clip_identity`: pre-кадры строго до триггера, post-кадры после |
| Допуски точности расширены с 0,25 до 0,3–0,35 | `audit_01` без изменений: MAE и показания на 27 кадрах совпали с исходным аудитом |

## 3. Независимые проверки (21)

| Проверка | Ссылки |
|---|---|
| `dispatch_noise_under_hmi_polling` | NEW-01, DEF-14, REQ-DA-02 |
| `dispatch_overload_trips_and_health_split` | DEF-08, REQ-DA-04/05/07/08 |
| `period_stats_sql_vs_reference` | NEW-05, NEW-06, DEF-03, REQ-DOC-04 |
| `store_forward_frames_duplicates_growth` | DEF-01, DEF-06, DEF-21, NEW-02, NEW-03 |
| `store_forward_overflow_keeps_alarms` | DEF-06, REQ-SF-12 |
| `store_forward_real_link_failure_reported` | NEW-12, REQ-SF-06 |
| `llm_reasoning_model_empty_content_handled` | NEW-13, REQ-DOC-10 |
| `ring_buffer_concurrent_clip_identity` | DEF-10, NEW-08, REQ-VA-10 |
| `spec_single_trip_vs_regular_overloads` | DEF-04, REQ-DOC-06/08 |
| `api_unauthenticated_and_meta` | DEF-07, NEW-04 |
| `api_rbac_matrix` | DEF-07, REQ-SEC-05 |
| `api_ssrf_and_path_traversal` | DEF-07, REQ-SEC-04 |
| `api_rtsp_credentials_never_leak` | DEF-07, REQ-SEC-03 |
| `api_nan_payload_422` | DEF-09, REQ-API-02 |
| `api_sessions_logout_role_change_ws` | NEW-04, REQ-SEC-05 |
| `api_period_sensitivity_from_db` | DEF-03, NEW-06, REQ-DOC-04 |
| `auto_spec_generation_lifecycle` | REQ-DA-09, DEF-20 |
| `api_login_bruteforce_lockout` | NEW-04 |
| `restart_persistence` | DEF-20, REQ-ARCH-04 |
| `production_mode_rejects_default_passwords` (отдельный процесс) | NEW-04, REQ-SEC-05/06 |
| `legacy_db_migration` (БД схемы `dd25bde`, отдельный процесс) | REQ-ARCH-04 |

## 4. Исходные аудиты Gemini на финальном коде

Скрипты `reports/audit/tests/audit_01…05` запущены без изменений, результаты записаны в `evidence/original_audit_rerun/`. Каталог `reports/audit/` не изменился (`git status` пуст).

| Прогон | Условия | Код | Время |
|---|---|---:|---:|
| `audit_01_cv_regression` | штатно | 0 | 8,2 с |
| `audit_02_qos1_default` | MQTT QoS 1 | 0 | 37,5 с |
| `audit_02_qos0_emulator_compat` | `GAUGEVISION_MQTT_QOS=0`: встроенный эмулятор брокера не шлёт PUBACK | 0 | 32,2 с |
| `audit_03_security_rbac_on` | RBAC включён | 0 | 8,7 с |
| `audit_04_hmi_auth_off_compat` | `GAUGEVISION_AUTH_REQUIRED=0`: скрипт написан до RBAC и не выполняет вход | 0 | 39,0 с |
| `audit_05_soak_edge_cases` | штатно | 0 | 27,2 с |

Флаги `DEFECT_*` (в исходном аудите все `True`):

| Флаг | Аудит | Финальный код |
|---|:---:|:---:|
| `DEFECT_silent_drop_when_broker_down` | True | False |
| `DEFECT_camera_degradation_penalizes_equipment_health_score` | True | False |
| `DEFECT_bench_profile_overrides_zero_chatter` | True | False |
| `DEFECT_phantom_6_5_min_added` | True | False |
| `DEFECT_trips_24h_is_hardcoded_2x_shift` | True | False |
| `DEFECT_ssrf_unrestricted_url_accepted` | True | False |
| `DEFECT_arbitrary_absolute_path_accepted` | True | False |
| `DEFECT_forces_healthy_equipment_into_defects_and_tz` | True | False |
| `DEFECT_zero_capex_reports_1_month_payback` | True | False |
| `DEFECT_silent_fallback_to_all_items` | True | False |
| `DEFECT_period_12h_vs_30d_only_changes_header_label` | True | True — см. ниже |

Оставшийся флаг. Случай 3 в `audit_03` вызывает генератор без истории БД (`history_stats` не передаётся, событий в окне нет), поэтому при любом периоде данных нет, а цифры одинаковы. Это правильное поведение. Зависимость от периода проверена через API на реальной БД (`api_period_sensitivity_from_db`): 12h/24h/7d/30d дают +1 отсчёт и +1 событие на каждый шаг, пик 11,04 МПа появляется только в 30d.

Экономика в `audit_03` (`annual_effect_match`, `payback_years_match` = False). Аудит сверяет годовой эффект с формулой без OPEX, а после DEF-04 генератор вычитает OPEX. `tests/economics_reconcile_audit03.py` пересчитал формулу аудита с вычетом OPEX, и всё совпало: CAPEX 230 280 ₽, валовой эффект 556 000 ₽, OPEX 16 000 ₽, чистый эффект 540 000 ₽, окупаемость 0,43 года (`economics_reconciliation.json`).

## 5. Интеграция со сторонними реализациями протоколов

Стенд: mediamtx v1.21.4 и ffmpeg (сверены по SHA-256 с официальными релизами), брокер amqtt 0.12.2, клиент pymodbus 3.16.2. Прогон выполнен дважды, итоговый — после исправления NEW-12.

| Критерий | Результат |
|---|---|
| `rtsp_online` | подключение 3,0 с (в первом прогоне 2,5–3,5 с) |
| `rtsp_cv_accuracy` | 80 / 80 показаний в ±0,35 МПа, MAE 0,039 МПа, 10 к/с, обработка 53 мс |
| `rtsp_auto_recovery` | после остановки издателя — 10,1 с, после перезапуска RTSP-сервера — 14,1 с |
| `rtsp_inference_resumed` | да |
| `rtsp_outage_degradation_reported` | канал в OFFLINE с диагнозом, пропуски кадров зафиксированы |
| `rtsp_password_masked` | пароль камеры не найден в API и журнале |
| `no_tokens_in_server_log` | 0 немаскированных токенов |
| `mqtt_buffered_during_outage` | пик очереди 27 |
| `mqtt_outage_reported_as_buffering` | обрыв обнаружен через 6 с (тайм-аут PUBACK 2 с), `BUFFERING` до восстановления |
| `mqtt_drained_after_recovery` | 7,0 с |
| `mqtt_state_connected_after_drain` | `CONNECTED` |
| `mqtt_no_loss` | 117 / 117 записей получены подписчиком, 0 дублей |
| `mqtt_frames_intact` | 3 кадра тревог, SHA-256 совпал |
| `modbus_values_match` | 30 / 30 значений совпали с REST |
| `modbus_foreign_unit_rejected` | исключение 0x0B; неверный адрес — 0x02 |
| `server_graceful_exit` | «Application shutdown complete» в журнале |

Первый прогон (до NEW-12): 15 / 16, не прошёл `mqtt_outage_reported_as_buffering` — состояние `SYNCING` во время отказа. Затем исправлены код и критерий: проверка «все замеры с непустой очередью» не учитывала, что отказ можно обнаружить только после тайм-аута PUBACK.

## 6. Браузерный E2E

Chromium (Playwright Core), сервер `run.py --demo` с RBAC. Сценарий: вход, обрыв АСУ ТП и досылка, симуляция отказов, диспетчерская, предпросмотр ТЗ, скачивание `.docx` и `.md`, выход, вход оператора (403 на действия инженера и администратора). Три контура на 1920×1080, 1440×900 и 1280×720 — 9 снимков.

| Проверка | Результат |
|---|---|
| Сбои сценария | 0 |
| Ошибки консоли и страницы | 0 |
| HTTP 4xx/5xx | 0 |
| Внешние запросы | 0 |
| Переполнение и усечённый текст | 0 (после исправления плашки пользователя на 1280×720) |
| `.docx` | 132 753 байт, 4 кадра |

## 7. Offline-установка

Новое venv, `pip install --no-index` из wheelhouse на 61 пакет. 14 критериев PASS: установка 131 с, `pip check` чистый, YOLOv8 на CPU, запуск 7,2 с, инференс 73–75 мс, HMI, SQLite WAL, аналитика 36 приборов, `.docx`, Modbus. Аудит-хук Python — 0 обращений к нелокальным адресам. Подробности — в `OFFLINE_INSTALLATION_REPORT.md`.

## 8. Часовой soak

3603 с, пять CV-каналов, клиенты HMI, 6 остановок брокера, 4 остановки RTSP-издателя, 3 симуляции обрыва из интерфейса. Исходный вердикт скрипта — 15 / 16 (`docx_generated_valid`: ожидалось 6, хотя по расписанию внутри часа их 5). После исправления двух критериев (число `.docx` и утечка по private bytes) — 17 / 17 по тем же замерам. Подробности — в `SOAK_TEST_REPORT.md`.

## 9. USB/UVC-камера

Встроенная камера ноутбука, устройство `USB\VID_5986&PID_2174&MI_00`, DirectShow, тип источника `device`. Кадры на диск не сохранялись.

| Критерий | Результат |
|---|---|
| Подключение | 2,0 с |
| Поток | 189 кадров, 9,9 к/с |
| CV-конвейер | кадры обработаны (прибора в кадре нет, достоверное показание не ожидалось) |
| Перезапуск | 200, online через 0,5 с |
| Освобождение устройства после удаления | да |

Внешняя USB-камера не испытывалась.

## 10. Локальная LLM

Ollama 0.40.18 (официальный zip, SHA-256 сверен), модель `qwen3.5:latest` (9,7 млрд, Q4_K_M), RTX 5060 Laptop, только 127.0.0.1.

| Критерий | Первый прогон | После NEW-13 |
|---|:---:|:---:|
| Ответ модели использован (`llm_enhanced`) | FAIL: пустой `content`, весь лимит ушёл на рассуждения | PASS, 8,5 с |
| Русский текст | PASS | PASS (99 % кириллицы) |
| Нет утечки рассуждений | PASS | PASS |
| Нет чисел вне исходных фактов | PASS | PASS |
| Правовое разграничение и экономика не изменены | PASS | PASS |
| Безопасный откат при недоступном сервере | PASS | PASS |

## 11. GPU RTX 5060 Laptop

Выполнено по просьбе пользователя, с контролем температуры. Детектор: 8,5 мс на CUDA FP16 против 21,4 мс на CPU. Полный конвейер: 51 мс на обоих устройствах, время уходит на CPU-часть. Показания на 27 кадрах совпадают с CPU. 5 минут нагрузки без ошибок, до 65 °C, 0 событий WHEA. Подробности — в `PERFORMANCE_COMPARISON.md`, раздел 4.

## 12. Воспроизведение

```powershell
$env:CUDA_VISIBLE_DEVICES = ""; $env:GAUGEVISION_DEVICE = "cpu"
python -B -W error::RuntimeWarning tests/test_tracks_e2e.py
python -B -W error::RuntimeWarning tests/test_demo_dashboard.py
python -B -W error::RuntimeWarning tests/test_remediation_full.py
$env:ACCEPTANCE_TEST_OUT = "reports/remediation/evidence/acceptance_tests/acceptance_results.json"
python -B tests/test_acceptance_independent.py
python reports/remediation/tests/rerun_original_audits.py
python reports/remediation/tests/economics_reconcile_audit03.py
python reports/remediation/tests/setup_validation_tools.py
python reports/remediation/tests/interop_rtsp_mqtt_modbus.py
python reports/remediation/tests/browser_e2e.py
python reports/remediation/tests/offline_install_check.py --wheels <wheelhouse> --base-python <python3.12>
python reports/remediation/tests/soak_real_pipeline.py
python reports/remediation/tests/usb_camera_check.py --index 0
python reports/remediation/tests/llm_local_check.py --base-url http://127.0.0.1:11434/v1 --model qwen3.5 --timeout 600
python reports/remediation/tests/build_rtm.py
```

GPU (только на стабильной станции, на ноутбуке — с `--allow-laptop` и коротким `--soak-min`):

```powershell
python reports/remediation/tests/gpu_validation_3090.py --out gpu_results --soak-min 30
python reports/remediation/tests/yolo_device_microbench.py --n 200
```
