# PROGRESS — повторная приёмка и завершение устранения дефектов GaugeVision AI

Файл ведётся по ходу работы, чтобы любой следующий исполнитель мог продолжить без истории сессии.

## Где идёт работа

- Репозиторий: `C:\Hakatons\GaugeVisionAIDesign DashBoard`.
- Изолированный worktree: `.claude/worktrees/remediation-acceptance`, ветка `remediation/acceptance` (от `dd25bde`).
- Основной checkout `main` не изменялся: в нём остаётся незакоммиченная рабочая копия Antigravity.
- Коммит `60908e7` — снимок рабочей копии `main` на 26.11.2026 21:21 (модернизация, аудит Gemini, устранение дефектов Antigravity) без изменений. Все последующие коммиты — работа этой приёмки.
- В снимок не включены медиаматериалы `docs/gemini_art`, `docs/gemini_journal`, `docs/gemini_video`, `Dashboard/` (≈31 МБ скриншотов и видео, к дефектам не относятся). Они остались в основном checkout.
- Python-окружение для прогонов: `C:\C1\GaugeVS\.venv\Scripts\python.exe` (3.12.9, torch 2.14.1+cu130, ultralytics 8.4.183). Все длительные прогоны: `CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`.

## Этап 1. Восстановление контекста — выполнен

- Журнал сессии Antigravity: `~/.gemini/antigravity-cli/brain/695f6dc6-…/.system_generated/logs/transcript_full.jsonl`. Шаги 764–883 — аудит Gemini, шаги 900–1363 — устранение дефектов.
- `task-1363` (повторный прогон `audit_05`) завершился `exit=0` в 21:21; результат: `scratch/original_audit_rerun/perf_soak_fault_results.json` (мини-soak 12 с, часовой soak не выполнялся).
- Повторные прогоны `audit_01–04` Antigravity делал в режиме совместимости: `audit_04` с отключённым RBAC (`compat`), `audit_03` с `rbac=1`.
- CUDA smoke: `scratch/cuda_smoke_5frames.json` — 5 кадров, `[4604, 57.7, 54.8, 50.3, 50.9]` мс, torch 2.14.1+cu130, RTX 5060 Laptop. Повтор не требуется.
- Версии модулей на момент аудита восстановлены обратным применением правок из журнала (`tmp/restore_preaudit.py`): `config, db, demo, discovery, events, main, streamer, vision` и два исходных теста. Модули `auth, security, scada_gateway, store_forward, stream_manager, dispatch_analyzer, spec_generator, test_remediation_full` Antigravity перезаписал целиком — ревью идёт по текущему коду.

## Этап 2. Базовый прогон — выполнен

| Набор | Результат | Время |
|---|---|---|
| `tests/test_remediation_full.py` | 8/8 PASS | 18 с |
| `tests/test_demo_dashboard.py` | PASS | 25 с |
| `tests/test_tracks_e2e.py` | PASS | 17 с |

## Этап 3. Контроль изменений тестов — выполнен

- `test_demo_dashboard.py`, `test_tracks_e2e.py`: после аудита добавлен только шаг логина (RBAC). Ни одна проверка не удалена.
- `test_remediation_full.py`: правки после неудачных запусков в основном адаптируют тест к реальному API. Ослабления: проверка `frame_sha256` при постановке в очередь заменена проверкой размера; идентичность клипов кольцевого буфера заменена подсчётом; допуски CV 0,25→0,3 и 0,3→0,35 МПа. Компенсируется независимыми тестами `tests/test_acceptance_independent.py`.

## Найденные в ревью дефекты (новые, NEW-xx)

| ID | Суть | Статус |
|---|---|---|
| NEW-01 | `dispatch_analyzer`: каждый вызов `overview()` добавляет точку ряда; при опросе HMI 20 Гц шум ±0,01 МПа даёт `peak_rate` 20,45 МПа/мин, ложный гидроудар, `process_anomaly` и CAPEX на исправный прибор | в работе |
| NEW-02 | Store-and-Forward: доставленные записи хранят `frame_blob` до 25 000 строк — неограниченный рост БД | в работе |
| NEW-03 | Store-and-Forward: живая доставка и фоновая досылка не сериализованы — возможна повторная отправка | в работе |
| NEW-04 | Безопасность: известные пароли по умолчанию действуют вне демо-режима; нет защиты от перебора; WS-дашборд не перепроверяет сессию; `/api/meta` без входа раскрывает путь к БД | в работе |
| NEW-05 | `get_period_reading_stats` выгружает все строки периода в Python (30 суток живой камеры ≈ 2,6 млн строк) | в работе |
| NEW-06 | В демо-профиле 35 из 36 приборов не пишут историю в SQLite — протокол ТЗ за период для них пуст | в работе |
| NEW-07 | `streamer._set_status`: корутина `_safe_notify` создаётся и не ожидается при закрытом loop (RuntimeWarning) | в работе |
| NEW-08 | `IncidentRingBuffer`: клип, вытесненный при `max_active`, не сохраняется на диск | в работе |
| NEW-09 | `requirements.lock` не содержит `ultralytics`/`torch` — offline-установка молча теряет YOLOv8 | в работе |

## Следующий шаг

Исправить NEW-01…NEW-09, добавить независимые регрессионные тесты, затем offline-установка и часовой soak.
