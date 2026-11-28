# Отчёт о регрессионном, интеграционном и автономном тестировании (`REGRESSION_TEST_REPORT.md`)

Дата: 2026-11-28. Ветка: `research/cv-next-gen`.
Объединяет материалы: `REGRESSION_TEST_REPORT`, `E2E_VALIDATION_REPORT`, `OFFLINE_DEPLOYMENT_REPORT`.
Сырые доказательства: `evidence/regression_15_summary.json`, `evidence/multigauge_1_2_4_8_16.json`, `evidence/soak_v31_results.json`.

## 1. Полная регрессия (15 / 15 PASS, CPU-only)

| № | Набор тестов | Область проверки | Результат |
|---:|---|---|---|
| 1 | `tests/test_instruments_db.py` | Реестр приборов SQLite, миграции, слоты | **PASS** |
| 2 | `tests/test_multigauge.py` | Multi-Gauge 1–16 приборов, трекер, 0 ID Switch | **PASS** |
| 3 | `tests/test_multigauge_api.py` | REST API Multi-Gauge и RBAC | **PASS** |
| 4 | `tests/test_autocal.py` | Изоляция и отключение автокалибровки | **PASS** |
| 5 | `tests/test_demo_dashboard.py` | Стендовый пульт, 36 приборов, WSS, CSV | **PASS** |
| 6 | `tests/test_tracks_e2e.py` | Сквозные треки 1 и 2, DOCX/MD, SSE | **PASS** |
| 7 | `tests/test_remediation_full.py` | Закрытие дефектов v2.0 (DEF-01..22) | **PASS** |
| 8 | `tests/test_acceptance_independent.py` | Независимая приёмка (21 сценарий) | **PASS** |
| 9 | `tests/test_modbus_register_map.py` | Карта Modbus TCP 5208 регистров | **PASS** |
| 10 | `tests/test_predictive_analytics.py` | Математические и Монте-Карло тесты прогноза v3.2 (5/5) | **PASS** |
| 11 | `tests/test_modernization_optimizer.py` | ILP-оптимизатор, Парето, `infeasible`, ТЗ | **PASS** |
| 12 | `tests/test_next_gen_integration_contract.py` | Единый контракт данных v1.3 | **PASS** |
| 13 | `tests/test_final_integration.py` | 12 интеграционных сценариев (миграции 1.0/2.0/NG, сетевая политика, Modbus, прогнозы, ТЗ, автокалибровка, рестарт) | **PASS (12/12)** |
| 14 | `tests/test_cv_next_gen.py` | Vision Engine 3.1, ModelRegistry SHA-256, профили, `OpenCVNeedleV2`, `NeedleSegUNet`, CCW/отрицательные шкалы, Multi-Gauge `balanced` | **PASS (8/8)** |
| 15 | `tests/test_security_hardening_v31.py` | RBAC + `audit_log` CV, CSRF `Origin`, DoS 10 МБ (`413`), SHA-256 YOLO/пустой хэш, LLM `<FACTS>`/SSRF, Modbus read-only/OOB, fuzzing | **PASS (4/4)** |

*Примечание по ходу приёмки:* при первом прогоне `test_final_integration.py` выявил пограничный регресс в `PredictiveAnalyzer` v3.2 (`t_prediction`: ряд с `dt=30 с` и `R²=0,9999`, но автокорреляцией синусоидальной ряби `rho1=0,54`). Исправлено добавлением условия `r2_w >= 0,94` в `linear_regime`, после чего `test_final_integration.py` (12/12, `eta_alert_min = 14,99` при эталоне `15,00`) и `test_predictive_analytics.py` (5/5) прошли полностью.

## 2. Автономность (Air-Gapped) и внешние контуры

- Все 15 наборов, валидация CV и 5-минутное soak-испытание выполнены при `YOLO_OFFLINE=1` без исходящих сетевых обращений.
- Статические ресурсы HMI не содержат внешних CDN; при недоступности LLM генерация ТЗ детерминированно завершается без ошибок.
- **Честные ограничения E2E:** живой шлюз Ignition SCADA 8.3.10 в данной сессии не запущен (`NOT VERIFIED` повторный живой опрос с кодом 3.1; протокол Modbus TCP 5208 регистров проверен прямым TCP-клиентом). Повторный браузерный прогон Playwright HMI на 3 разрешениях не выполнялся после изменений (интерфейс HMI не менялся с коммита `4d15cf8`; перенесено подтверждение 3.0 с пометкой `NOT RE-VERIFIED IN BROWSER`).
