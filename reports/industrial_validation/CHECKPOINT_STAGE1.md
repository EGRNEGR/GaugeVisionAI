# Контрольная точка этапа 1 (REQ-CV-05) — 2026-11-27

Ветка `next-gen/platform`, worktree `.claude/worktrees/next-gen`. Этап остановлен после записи базовой линии
на зафиксированной выборке v2; алгоритм ещё не менялся.

## Что сделано

1. Источники: MeterFL (CC BY-SA 4.0, разметка делений и стрелки, показания для 274 тестовых снимков) и
   MeasureBench real_world (CC BY-SA 4.0, 1272 снимка, интервальный эталон).
2. Группировка по физическому прибору: эмбеддинги ResNet-18 кропа циферблата со стёртой стрелкой,
   сферический k-means (k = 16), ручная проверка контактных листов → модели M1–M6
   (`tests/group_instruments.py`, `data/instrument_clusters_k16.json`).
3. Разбиение (`tests/build_split.py` → `data/dataset_manifest.json`):
   final — M1, M4, M6 + MeasureBench; dev — M2, M3, M5. Дубликаты MeasureBench ↔ MeterFL исключены по dHash.
4. Калибровка шкалы независима от эталонного показания: деления из полигонов MeterFL,
   для MeasureBench — ручная разметка центра и крайних делений (`data/mb_calibration.json`, 123 записи,
   исключения с причинами). Положение стрелки не размечается.
5. Manifest v2 (коммит 9645866) — зафиксирован до любых изменений алгоритма:
   primary 315 (round dial: 188 показаний MeterFL + 127 интервалов), arc-panel 41, final 985, dev 506.
6. Базовая линия кода 94e646e (`results/baseline_v2/`, CPU, YOLO на CPU):

| Набор | n | Локализация | Достоверных | Медиана | p95 | Грубые (>10 %) от достоверных |
|---|---|---|---|---|---|---|
| primary | 315 | 70,5 % | 58,1 % | 1,09 % | 47,9 % | 12,0 % |
| final | 985 | 79,3 % | 60,0 % | 1,10 % | 31,4 % | 8,0 % |
| dev | 506 | 78,8 % | 72,5 % | 0,59 % | 5,35 % | 4,1 % |
| arc | 41 | — | 12,2 % | 32,6 % | 41,8 % | 60 % |

   Корректный отказ на непригодных кадрах — 86,7 % (blur, dark, overexposed — 100 %; occluded — 60 %;
   нециферблатные: цифровые 80 %, линейные 72 %). Целевые значения ТЗ не достигнуты ни по одному показателю.

## Разбор отказов на dev (только dev используется для доработки)

- Локализация: 107 из 108 случаев `roi_source = yolo` (рамка YOLO без подтверждающего эллипса) — неверный центр
  (ошибка 0,6–0,9 радиуса шкалы при правильном размере). Почти все такие кадры дальше отклоняются
  правилом `low_confidence_unconfirmed` (86 шт.), 17 проходят как «достоверные» → грубые ошибки.
  Гипотеза: эллипс корпуса найден, но отброшен проверкой `detect_dial` (центр вне рамки + 15 % или
  размер вне 0,25–1,6), либо `_ellipse_candidates` отбрасывает контур по `fill`/`p90_err`.
- `out_of_scale` (38): стрелка найдена неверно на 50–135° — чаще всего выбран хвост или риска; 34 из 38 при верной локализации.
- `low_confidence_unconfirmed` при верной локализации — 14 (уверенность 0,06–0,39).

## С чего продолжить

1. Визуализировать на dev кадры `roi_source = yolo` (эллипсы-кандидаты, рамка YOLO, эталонный центр) и
   исправить выбор эллипса в `app/vision.py: detect_dial / _roi_from_yolo_bbox`.
2. Поиск стрелки: подавление хвоста (асимметрия момента относительно центра), проверка острия по внешнему кольцу.
3. После каждой правки — прогон только dev: `sh tests/tools/run_eval.sh <worktree> <label> <out> dev`.
4. Когда dev стабилен — однократный прогон primary/final/arc/unusable, отчёт `CV_VALIDATION_REPORT.md`.

## Где лежит всё вне репозитория

- `C:\Hakatons\gv_cv_validation\datasets\` — meterfl (git-клон github.com/weidazhaoooo/Meter-FL),
  measurebench (`real_world.parquet` с huggingface.co/datasets/FlagEval/MeasureBench + экспорт `export/img`),
  igvd (не используется в выборке).
- `C:\Hakatons\gv_cv_validation\cvwork\` — кропы разметки, прогоны (`eval2/` — базовая линия v2).
- `C:\Hakatons\gv_cv_validation\baseline_code\` — git worktree на 94e646e (базовый код).
- Python: `C:\C1\GaugeVS\.venv\Scripts\python.exe` (OpenCV, torch, ultralytics, pyarrow),
  запуск с `CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`.
- Инструменты разметки: `tests/tools/crop_view.sh`, `tests/tools/add_mb_annotation.py`.
