# Реестр лицензий моделей, библиотек и датасетов (`MODEL_AND_DATA_LICENSES.md`)

Дата: 2026-11-28. Ветка: `research/cv-next-gen`.

## 1. Архитектуры, веса и фреймворки

| Компонент | Источник | Лицензия | Коммерческое использование в закрытом продукте | Примечание для GaugeVision |
|---|---|---|---|---|
| `models/gauge_yolov8.pt` (baseline) | Ultralytics YOLOv8n (`8.4.183`), обучена на `Analog-Gauge-Meter-1` | **AGPL-3.0** (фреймворк/веса Ultralytics) | Требует раскрытия кода под AGPL-3.0 либо покупки Ultralytics Enterprise License | Сохраняется как legacy-опция; в документации явно отмечено лицензионное ограничение |
| `YOLO26n / 26s / 26m / 26-pose / 26-seg` | Ultralytics (`ultralytics 8.4.183`) | **AGPL-3.0** / Enterprise | Аналогично YOLOv8 — требуется Enterprise License для закрытого коммерческого ПО | Подготовлены конфигурации в `training_package_3090/` с явной пометкой лицензии |
| `RF-DETR Nano / Small / Seg` | Roboflow (`rfdetr`) | **Apache 2.0** | **Разрешено** (с сохранением уведомлений) | Приоритетный коммерчески чистый детектор; экспорт в ONNX |
| `NeedleKeypointNet` (собственная) | Собственный код GaugeVision (PyTorch, обучение с нуля / без AGPL-весов) | **MIT / собственная** (PyTorch: BSD-3-Clause) | **Разрешено** (при обучении на совместимых данных — см. § 2) | Компактная нейросеть ключевых точек и угла стрелки |
| `NeedleSegUNet` (собственная) | Собственный код GaugeVision (PyTorch) | **MIT / собственная** (PyTorch: BSD-3-Clause) | **Разрешено** (с учётом лицензии обучающих данных) | Компактная сегментационная сеть стрелки и рисок |
| `ethz-asl/analog_gauge_reader` | ETH Zurich ASL | Код: **MIT**; зависимости: YOLOv8 (**AGPL-3.0**), MMOCR (Apache 2.0), DINOv2 (Apache 2.0) | Код — да; зависимости YOLOv8 — AGPL-3.0 | Готовые веса не опубликованы; сторонний код не копируется |
| OpenCV (`opencv-python`) | OpenCV | **Apache 2.0** | **Разрешено** | Геометрический резерв и предобработка |
| ONNX Runtime (`onnxruntime`) | Microsoft | **MIT** | **Разрешено** | Автономный CPU-бэкенд без зависимости от Ultralytics |
| FastAPI / NumPy / SciPy | Соответствующие проекты | MIT / BSD-3-Clause | **Разрешено** | Базовый стек продукта |

## 2. Датасеты

| Датасет | Источник | Лицензия | Коммерч. обучение | Использование в GaugeVision 3.1 |
|---|---|---|---|---|
| **MeterFL** | `github.com/weidazhaoooo/Meter-FL` | **CC BY-SA 4.0** (данные), MIT (код) | Разрешено с атрибуцией; производные адаптации данных — ShareAlike | `dev` (M2, M3, M5) — обучение/валидация исследовательских моделей; `final` (M1, M4, M6) — только оценка (Legacy Benchmark). В Git изображения не добавляются |
| **MeasureBench** | `huggingface.co/datasets/FlagEval/MeasureBench` | **CC BY-SA 4.0** | Разрешено с атрибуцией и ShareAlike | 123 снимка — Legacy Benchmark; 588 неиспользованных `dial` + `linear/digital` — новый независимый Locked Final Test (только оценка, в обучение не входит) |
| **IGVD** (Industrial Gauge Video Dataset) | `zenodo.org/records/20147961` (`aMa2210/VLM_gauge`) | **CC BY 4.0** | **Разрешено** с атрибуцией | Независимая видеовалидация (Locked Final Test, в обучение не входит) |
| **RealGauges / SyntheticGauges** | University of Cambridge (`jjcvision.com`) | **CC BY-NC 4.0** | **Запрещено** (NonCommercial) | **Исключён** из обучения и коммерческого конвейера |
| **Синтетический генератор GaugeVision** | Собственный код (`cv_next_gen/synthetic_generator.py`) | **Собственная / MIT** | **Полностью разрешено** | Воспроизводимые обучающие, валидационные и стресс-данные с фиксированными seed |
| **Roboflow Universe** (`Analog-Gauge-Meter-1` и аналоги) | Roboflow Universe | Зависит от конкретного набора (часто CC BY 4.0) | Требует проверки каждого набора отдельно | Не загружается автоматически; в `training_package_3090/` предусмотрен явный аудит лицензии перед импортом |

## 3. Требования безопасности и автономности MLOps

- Все файлы весов проверяются по **SHA-256** из `models/registry.json` перед загрузкой.
- Запрещена загрузка произвольных путей за пределами `MODELS_DIR` (проверка `resolve().is_relative_to(MODELS_DIR)`).
- Формат ONNX (`onnxruntime`) исключает выполнение произвольного Python-кода через `pickle` (в отличие от `.pt` при `weights_only=False`); для `.pt` разрешена загрузка только зарегистрированных файлов с совпавшим SHA-256.
- Переменная `YOLO_OFFLINE=1` и локальный `YOLO_CONFIG_DIR` исключают внешние сетевые запросы и телеметрию при запуске.
