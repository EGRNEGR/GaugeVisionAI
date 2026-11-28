# Примечания к выпуску GaugeVision AI 3.1 (`RELEASE_NOTES.md`)

Дата: 2026-11-28. Ветка: `research/cv-next-gen` (база `v3.0.0`, коммит `0273436`). Релизный тег `v3.1.0` не создавался (требует отдельного согласования).

## Основные изменения

### 1. Компьютерное зрение (Vision Engine 3.1)
- Добавлен модульный `app/vision_engine/` (`ModelRegistry`, `detect_dial_v31`, `OpenCVNeedleV2`, `NeedleKeypointEstimator`, `NeedleSegEstimator`, `FusionNeedleEstimator`, профили `legacy / eco / balanced / precision`).
- Обучены и зарегистрированы с SHA-256 коммерчески чистые веса `models/needle_seg_v31.pt` (320 КБ, MIT/BSD-3, `1,93°` MAE на невидимом `M5`) и `models/needle_keypoint_v31.pt` (557 КБ).
- Каскадный локализатор `detect_dial_v31` улучшил локализацию на сложных кадрах `MeasureBench misc` с `55,74 %` до **`63,93 %`** (+8,2 п.п.) без GPU-переобучения; корректный отказ на непригодных кадрах (`n=300`) вырос до **`99,33 %`**.
- Профиль `legacy` сохранён по умолчанию как гарантированный возврат к GaugeVision 3.0.
- Подготовлен и проверен dry-run автономного пакета обучения полнокадровых детекторов `training_package_3090/` для Linux RTX 3090 24 ГБ.

### 2. Прогнозная аналитика (Predictive v3.2)
- В `app/predictive_analytics.py` добавлен робастный локальный затухающий Хольт (`_robust_damped_holt`) с разделением траектории прогноза и ранней оценки ETA.
- На `LOCKED TEST` (82 реальных промышленных ряда): полнота прогноза пробоя уставки `H = 30` выросла с `4,65 %` до **`7,98 %`** (×1,72), точность с `66,36 %` до **`77,22 %`**, медианная ошибка ETA снижена на **43 %**, FAR детектора аномалий снижен с `36,11 %` до **`33,75 %`**.

### 3. Безопасность и надёжность
- Закрыты 8 дефектов безопасности (`DEF-SEC-01..08`): проверка SHA-256 для `gauge_yolov8.pt`, запрет пустого хэша в `ModelRegistry`, защита от `IndexError` при fuzzing `assess_dial_suitability`, аудит-лог `SET_VISION_PROFILE`, лимит тела HTTP 10 МБ (`413`), проверка CSRF `Origin`, `<FACTS>`-изоляция и очистка HTML в LLM, `PRAGMA busy_timeout=5000` и ротация `predictive_snapshots`.
- Сформирован CycloneDX `SBOM.json` (69 компонентов); подтверждено 0 секретов в репозитории.
