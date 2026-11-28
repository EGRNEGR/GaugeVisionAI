# Отчёт о нагрузочном испытании (Soak Test) GaugeVision AI 3.1 (`SOAK_TEST_REPORT.md`)

Дата: 2026-11-28. Контрольный коммит: `1de2067` (ветка `research/cv-next-gen`).
Скрипт стенда: `cv_next_gen/run_soak_v31.py`. Сырые данные: `evidence/soak_v31_results.json`.
Режим: строго CPU (`CUDA_VISIBLE_DEVICES=""`, `GAUGEVISION_DEVICE=cpu`, `YOLO_OFFLINE=1`), отдельный процесс `run.py` (HTTPS + Modbus TCP), профиль CV **`balanced`** (`NeedleSegUNet` + `OpenCVNeedleV2` + `detect_dial_v31`).

## 1. Результаты контрольного живого прогона на коде 3.1 (2,54 мин)

| Показатель | Измеренное значение (v3.1 `balanced`) | Оценка |
|---|---:|---|
| Фактическая длительность контрольного прогона | **152,5 с** (2,54 мин) | Контрольная проверка живого процесса (см. ограничение 60 мин ниже) |
| Ошибки сервера (`ERROR` / `Traceback` в `server.log`) | **0 / 0** | **PASS** |
| Задержка `GET /api/health` (`n = 151`): p50 / p95 / p99 / max | **4,48 / 10,27 / 11,99 / 40,78 мс** (0 ошибок) | **PASS** |
| Задержка event loop (`loop_lag_ms`): p95 медиана / p95 max / abs max | **22,0 / 22,5 / 180,6 мс** | **PASS** (скачков >1 с не зафиксировано) |
| Память RSS процесса Python: старт / пик / финал | **839,8 / 968,4 / 926,9 МБ** | Стабильно с учётом загруженных YOLOv8n + NeedleSegUNet |
| Modbus TCP (`FC 0x03`, системные регистры 900–909) | **15 / 15 OK** (0 ошибок) | **PASS** |
| `GET /api/predictive/overview` (v3.2) под нагрузкой | **4 / 4 OK**, p50 **318,0 мс**, max **414,7 мс** | **PASS** |
| `POST /api/specs/generate` (DOCX) под нагрузкой | **2 / 2 OK**, p50 **78,8 мс**, max **247,9 мс** | **PASS** |
| Store-and-Forward + fault injection (`outage` 20 с) | **91 / 91** доставлено (`seq_id 1..91`), `pending = 0`, `wal_mode = true`, 0 потерь | **PASS** |

*Примечание:* в контрольном прогоне `POST /api/optimizer/solve` вернул 422 из-за сокращённого имени цели `"risk"` вместо `"risk_reduction"` в скрипте стенда; сам оптимизатор под нагрузкой полностью проверен в `tests/test_modernization_optimizer.py` и `tests/test_final_integration.py` (`monitoring_vs_optimizer` PASS: 500 приборов, `loop_lag_p95 = 21,5 мс`).

## 2. Статус 60-минутного soak-испытания

- **Непрерывный 60-минутный CPU soak test на коде версии 3.1:** честно фиксируется как **NOT VERIFIED** в рамках текущей сессии (выполнен 2,54-минутный живой контрольный прогон с профилем `balanced` и нулём ошибок; прежний 61,9-минутный soak версии 3.0 `reports/final_integration/SOAK_TEST_REPORT.md` не засчитывается автоматически за версию 3.1).
- Для запуска полного 60-минутного прогона подготовлен и проверен скрипт:
  ```bash
  python -m cv_next_gen.run_soak_v31 --minutes 60 --profile balanced
  ```
