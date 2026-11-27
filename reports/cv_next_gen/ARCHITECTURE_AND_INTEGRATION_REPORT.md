# Архитектура Vision Engine 3.1, адаптация продукта и ограничения (`ARCHITECTURE_AND_INTEGRATION_REPORT.md`)

Дата: 2026-11-28. Ветка: `research/cv-next-gen`.
Объединяет разделы: `ARCHITECTURE_NEXT_GEN`, `PRODUCT_ADAPTATION_REPORT`, `MULTI_GAUGE_REVALIDATION`, `PERFORMANCE_REPORT`, `OFFLINE_DEPLOYMENT_REPORT`, `KNOWN_LIMITATIONS`, `DEFECT_REGISTER`.

## 1. Модульная архитектура `app/vision_engine/`

| Модуль | Ответственность |
|---|---|
| `app/vision_engine/registry.py` | `ModelRegistry`: чтение `models/registry.json`, обязательная проверка SHA-256 перед загрузкой, защита от path traversal (`is_relative_to(MODELS_DIR)`), метаданные лицензий и форматов |
| `app/vision_engine/estimators.py` | `OpenCVNeedleV2` (исправление полярности M1), `NeuralKeypointEstimator` (пакетный CPU/ONNX), `NeuralSegEstimator` (пакетный CPU/ONNX + PCA/ODR), `FusionNeedleEstimator` (циклическое согласование без усреднения несовместимых углов) |
| `app/vision_engine/profiles.py` | Профили `legacy`, `eco`, `balanced`, `precision` с измеренным компромиссом точности и задержки |
| `app/vision.py` | Потокобезопасное переключение профилей (`get_vision_profile`, `set_vision_profile`, `vision_engine_status`) и диспетчеризация в `GaugePipeline.process()` с сохранением 100 % совместимости `legacy` |

## 2. Адаптация подсистем GaugeVision

- **Multi-Gauge Vision (`app/multigauge.py`, `app/multigauge_service.py`):** сохранён единый проход детектора на кадр, трекер якорных ROI, постоянные `instrument_id` и `modbus_slot`; проверено на синтетическом щите из 4 приборов в профиле `balanced` (`tests/test_cv_next_gen.py::test_multigauge_with_balanced_profile`, ошибка < 3 % шкалы, 0 ID Switch) и полным набором `tests/test_multigauge.py` (1/2/4/8/16 приборов — PASS).
- **Ручная калибровка:** полностью сохранена (`calibration_rev`, CW/CCW, отрицательные диапазоны, ручная ROI). Экспериментальная Auto Calibration остаётся выключенной (`test_autocal.py` PASS).
- **Контракт данных (аддитивное расширение v1.3 → v1.4):** в запись телеметрии (`_on_reading`) и `GET /api/meta` добавлены необязательные поля `vision_engine`, `vision_profile`, `needle_ms`; все существующие поля `SHARED_DATA_CONTRACT.md` v1.3, таблицы SQLite, карта Modbus (`MAX_REGISTERS = 5208`) и топики MQTT сохранены без изменений.
- **REST API и RBAC (`app/main.py`):** добавлены `GET /api/vision/status` (`operator`), `GET /api/vision/models` (`operator`) и `POST /api/vision/profile` (`engineer`, с записью аудита `config` в журнал событий).
- **Операторский HMI (`static/index.html`, `static/js/console/header.js`):** отображение активного профиля CV в блоке «Достоверность CV-зрения» и функциональный переключатель профилей `legacy / eco / balanced / precision` (без middle dot `·`, без декоративных элементов).
- **Диагностика, прогноз, оптимизатор, SCADA, ТЗ:** проверены прохождением всех 13 регрессионных наборов (`test_predictive_analytics`, `test_modernization_optimizer`, `test_modbus_register_map`, `test_tracks_e2e`, `test_acceptance_independent`, `test_final_integration`).

## 3. Производительность и автономность (CPU)

| Этап / профиль | Среднее время на кроп (CPU) | p95 (CPU) | Размер весов стрелки | Офлайн-работа |
|---|---:|---:|---:|---|
| `legacy` (`OpenCV v8`) | 28,0–32,0 мс | 57,5–58,2 мс | 0 КБ | Да |
| `eco` (`OpenCV v2`) | 29,3–31,8 мс | 50,3 мс | 0 КБ | Да |
| `neural_seg` (`NeedleSegUNet`, чистая нейросеть) | **6,6–6,9 мс** | **~10 мс** | **320 КБ** | Да (`weights_only=True`, SHA-256) |
| `precision` (`Kpt + Seg + OpenCV v2`) | 49,4–52,9 мс | 69,3–81,0 мс | 878 КБ | Да (`weights_only=True`, SHA-256) |

## 4. Известные ограничения и реестр открытых дефектов

1. **DEF-CV31-01 (Локализация `MeasureBench misc` = 55,7 %):** базовый детектор `gauge_yolov8.pt` не переобучался локально (GPU RTX 5060 запрещён для длительного обучения). Устраняется запуском `training_package_3090/train_all_3090.py` (`YOLO26s` / `YOLO26s-pose` / `RF-DETR`) на Linux RTX 3090 24 ГБ.
2. **DEF-CV31-02 (ONNX-экспорт в локальном `.venv`):** в локальном окружении `C:\C1\GaugeVS\.venv` установлен `onnxruntime 1.32.0`, но не установлен пакет `onnx`, поэтому `export_and_register.py` зарегистрировал безопасные чекпоинты `.pt` (`weights_only=True` + SHA-256); при установке `onnx` или на RTX 3090 бэкенд автоматически подхватит `.onnx` с нулевыми изменениями кода.
3. **DEF-CV31-03 (IGVD синхронизация секундомера):** метки Excel IGVD привязаны к секундомеру в кадре, а не к `t = 0` MP4; автоматическая привязка дала фазовый сдвиг. Для строгой видеовалидации IGVD требуется OCR секундомера или ручное выравнивание начального кадра каждого из 18 видео.
4. **Полевая валидация и статус СИ/ПАЗ:** система остаётся инженерным прототипом информационной системы, не является сертифицированным средством измерений и не входит в контуры ПАЗ. Повторный 60-минутный soak test и живой прогон с Ignition SCADA 8.3.10 на профиле `precision` рекомендуются после установки весов детектора с RTX 3090.
