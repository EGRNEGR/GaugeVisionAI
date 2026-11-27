# Итоговый отчёт приёмки и примечания к выпуску GaugeVision AI 3.1 (`FINAL_ACCEPTANCE_REPORT.md`)

Дата: 2026-11-28. Ветка: `research/cv-next-gen` (база `v3.0.0`, коммит `0273436`).

## 1. Результаты тестирования

- **Полная регрессия GaugeVision AI 3.0:** **13 / 13 PASS** (`reports/cv_next_gen/evidence/regression_13_summary.json`):
  `test_instruments_db`, `test_multigauge`, `test_multigauge_api`, `test_autocal`, `test_demo_dashboard`, `test_tracks_e2e`, `test_remediation_full`, `test_acceptance_independent`, `test_modbus_register_map`, `test_predictive_analytics`, `test_modernization_optimizer`, `test_next_gen_integration_contract`, `test_final_integration`.
- **Новый набор Vision Engine 3.1 (`tests/test_cv_next_gen.py`):** **8 / 8 PASS** (SHA-256 целостность, защита путей, круговая математика, переключение 4 профилей, `OpenCVNeedleV2`, `NeedleSegUNet` пакетный инференс, отказ при перекрытии, отрицательные шкалы и CCW, Multi-Gauge 4 прибора в `balanced`).

## 2. Оценка по критериям приёмки CV-этапа

| Критерий | Цель | GaugeVision 3.0 (`primary`) | GaugeVision 3.1 `precision` (`primary`) | M1 (`final`, n=664) | Статус |
|---|---:|---:|---:|---:|---|
| Локализация приборов | ≥ 95 % | 79,05 % | 79,05 % | **99,10 %** | **PARTIAL** (нужен детектор RTX 3090) |
| Доля валидных показаний | ≥ 90 % | 66,67 % | 78,73 % (+12,0 п.п.) | **93,37 %** | **PARTIAL** (выполнено на M1) |
| MAE от полной шкалы | ≤ 2 % | 5,82 % | 2,52 % (в 2,3× лучше) | **1,87 %** | **PARTIAL** (выполнено на M1 и M4) |
| Медианная ошибка | ≤ 1 % | 1,08 % | 1,29 % (`eco`: **0,97 %**) | 1,39 % | **PARTIAL** (`eco` PASS) |
| p95 ошибки | ≤ 5 % | 32,71 % | 6,38 % (в 5,1× лучше) | **4,86 %** | **PARTIAL** (выполнено на M1 и M4) |
| Грубые ошибки (> 10 %) | ≤ 1 % | 11,43 % (24) | 3,23 % (8, в 3,5× лучше) | **0,97 % (6)** | **PARTIAL** (выполнено на M1 и M4) |
| Корректный отказ (непригодные) | ≥ 95 % | 98,0 % | **99,0 %** (`LOCKED non-dial`: **99,17 %**) | — | **PASS** |
| Регрессия 13 наборов + Multi-Gauge | 100 % | 13/13 | **13/13 + 8/8** | — | **PASS** |

## 3. Уровни готовности

| Уровень | Статус | Обоснование |
|---|---|---|
| Исследовательская модель (`NeedleSegUNet` + `Fusion`) | **ГОТОВО** | Доказано снижение грубых ошибок в 3,5–12,8× без утечек данных |
| Интегрированный технический прототип | **ГОТОВО** | `app/vision_engine/`, API, HMI, реестр SHA-256, 13/13 + 8/8 тестов PASS |
| Демонстрационная готовность | **ГОТОВО** | Живое переключение профилей, сохранение всех возможностей 3.0 |
| Лабораторная готовность | **ЧАСТИЧНО** | Требуется дообучение полнокадрового детектора на RTX 3090 (`training_package_3090/`) и повторный прогон Ignition/60-мин soak в профиле `precision` |
| Ограниченный промышленный пилот | **НЕ ГОТОВО** | Требуется полевая валидация на реальных камерах объекта |
| Промышленная эксплуатация / СИ / ПАЗ | **НЕ ПРИМЕНИМО** | Информационный прототип, не является утверждённым СИ и не входит в контур ПАЗ |

## 4. Примечания к выпуску (Release Notes v3.1-research)

- Добавлен модульный `app/vision_engine/` (`ModelRegistry`, `OpenCVNeedleV2`, `NeedleKeypointEstimator`, `NeedleSegEstimator`, `FusionNeedleEstimator`, профили `legacy / eco / balanced / precision`).
- Обучены и зарегистрированы с SHA-256 коммерчески чистые веса `models/needle_seg_v31.pt` (320 КБ, MIT/BSD-3) и `models/needle_keypoint_v31.pt` (557 КБ, MIT/BSD-3).
- Добавлен генератор синтетики `cv_next_gen/synthetic_generator.py`, протокол дедупликации `cv_next_gen/build_dataset_manifest.py` и автономный пакет `training_package_3090/` для Linux RTX 3090 24 ГБ.
- Добавлены REST-эндпоинты `/api/vision/status`, `/api/vision/models`, `/api/vision/profile` и переключатель профиля CV в пульте оператора.
- Стабильный `legacy`-конвейер GaugeVision 3.0 сохранён по умолчанию; исторические ветки и тег `v3.0.0` не изменены.
