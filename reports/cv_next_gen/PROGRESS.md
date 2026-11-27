# GaugeVision AI 3.1 — Журнал прогресса (`research/cv-next-gen`)

Ветка: `research/cv-next-gen` (от тега `v3.0.0`, коммит `0273436`).
Статус исследовательско-интеграционного цикла (CPU): **ЗАВЕРШЁН**.

| Этап | Название | Статус | Ключевой результат |
|---|---|---|---|
| 0 | Проверка Git, изоляция ветки `research/cv-next-gen` и аудит v3.0.0 | DONE | Создан worktree `cv-next-gen` от `v3.0.0` (`0273436`); исторические ветки и теги не изменены |
| 1–3 | Исследование архитектур, ETHZ, лицензий и происхождения `gauge_yolov8.pt` | DONE | `MODEL_RESEARCH.md`, `MODEL_AND_DATA_LICENSES.md` |
| 4–6 | Аудит датасетов, дедупликация SHA-256/dHash и генератор синтетики | DONE | `dataset_manifest.json` (2444 фото + 18 видео IGVD, −104 дубликата), `cv_next_gen/synthetic_generator.py` |
| 7–11 | Обучение `NeedleKeypointNet` и `NeedleSegUNet`, сравнение 6 архитектур и пакет RTX 3090 | DONE | `NeedleSegUNet` (320 КБ): `1,93°` MAE на M5; `fusion_precision` снизил грубые ошибки primary в 3,5× и M1 final в 12,8× (`77 → 6`) |
| 12–25 | Интеграция `app/vision_engine/`, `models/registry.json`, API `/api/vision/*`, HMI и профили | DONE | 4 профиля (`legacy`, `eco`, `balanced`, `precision`), проверка SHA-256, защита путей, аддитивный контракт |
| 26–34 | Полная регрессия (13 + 1), независимая валидация, RTM и итоговая документация | DONE | 13/13 регрессия 3.0 PASS + 8/8 `test_cv_next_gen` PASS; `FINAL_ACCEPTANCE_REPORT.md`, `REQUIREMENTS_TRACEABILITY_MATRIX.csv` |
