# Прогресс комплексного улучшения и аудита (`PROGRESS.md`)

- **Стадия I — Research & Improvement:** ЗАВЕРШЕНА (`95733e0`, `4d15cf8`, `3f9dc6e`, `1de2067`).
  - CV: `NeedleSegUNet` + `NeedleKeypointNet` + `OpenCVNeedleV2` + `detect_dial_v31` + `FusionNeedleEstimator` + dry-run `training_package_3090/`.
  - Predictive v3.2: робастный локальный затухающий Хольт, валидация на DEV (74 ряда) и LOCKED TEST (82 ряда).
  - SQLite: `PRAGMA busy_timeout=5000`, `cache_size=-16000`, ротация `predictive_snapshots`.
- **Стадия II — Comprehensive Audit & Remediation:** ЗАВЕРШЕНА (`1de2067`).
  - Модель угроз STRIDE, статический скан, поиск секретов (0), CycloneDX `SBOM.json` (69 компонентов), практический набор `tests/test_security_hardening_v31.py` (4/4 PASS).
  - Выявлены и закрыты 8 дефектов (`DEF-SEC-01..08`), включая краш `assess_dial_suitability`, найденный фаззером.
- **Стадия III — Final Independent Acceptance:** ЗАВЕРШЕНА.
  - Полная регрессия: **15 / 15 PASS** (включая выявленный и устранённый пограничный дефект `linear_regime` в `test_final_integration.py`).
  - Multi-Gauge 1/2/4/8/16 CPU: **16/16** во всех 4 профилях (`MAE 0,17–0,36 %`).
  - Unusable `n=300`: **`99,33 %`**; LOCKED non-dial `n=120`: **`99,17 %`**.
  - Живое CPU soak-испытание (5 мин, `balanced`, 8 приборов, Modbus TCP, Predictive, Optimizer, DOCX, outage): см. `SOAK_TEST_REPORT.md` (полный 60-мин прогон на 3.1 отмечен честно как `NOT VERIFIED` с готовым скриптом `cv_next_gen/run_soak_v31.py`).
  - Живой Ignition 8.3.10 на коде 3.1 и GPU-обучение на RTX 3090: честно зафиксированы как `NOT VERIFIED` / аппаратный блокер.
