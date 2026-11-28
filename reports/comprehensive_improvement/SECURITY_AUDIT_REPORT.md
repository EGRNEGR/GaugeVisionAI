# Аудит безопасности, реестр уязвимостей и отчёт об исправлениях (`SECURITY_AUDIT_REPORT.md`)

Дата: 2026-11-28. Контрольный коммит: `1de2067` (ветка `research/cv-next-gen`).
Стенд проверки: локальный изолированный стенд (`TestClient`, loopback `127.0.0.1`), активные тесты `tests/test_security_hardening_v31.py`, `tests/test_cv_next_gen.py`, `tests/test_final_integration.py`, `tests/test_remediation_full.py`, `tests/test_acceptance_independent.py`.

## 1. Сводка проведённых проверок

| Область | Метод проверки | Результат |
|---|---|---|
| Статический анализ опасных конструкций (`eval/exec/pickle/yaml.load/shell=True/md5/verify=False`) | Автоматический скан `app/*.py` | **0 совпадений** |
| Поиск секретов в репозитории (API-ключи, приватные ключи, токены) | Регулярный скан всех текстовых файлов ветки | **0 совпадений** |
| RBAC и аудит-лог для новых API Vision Engine (`/api/vision/*`) | `tests/test_security_hardening_v31.py` | **PASS** (401/403/200 + `SET_VISION_PROFILE` в `audit_log`) |
| CSRF и DoS (размер тела запроса) | `tests/test_security_hardening_v31.py` | **PASS** (чужой `Origin` + cookie → 403; `Content-Length > 10 МБ` → 413) |
| ML Security (`ModelRegistry`, `gauge_yolov8.pt`, `weights_only=True`) | `tests/test_security_hardening_v31.py`, `tests/test_cv_next_gen.py` | **PASS** |
| LLM Security (Prompt Injection, HTML stripping, SSRF, fallback) | `tests/test_security_hardening_v31.py` | **PASS** |
| Промышленная безопасность (Modbus read-only + OOB, MQTT TLS, RTSP Fernet/SSRF) | `tests/test_security_hardening_v31.py`, `tests/test_final_integration.py` | **PASS** |
| Безопасный fuzzing входных данных (битые/мелкие кадры, NaN/Inf) | `tests/test_security_hardening_v31.py` | **PASS** (выявлен и устранён `DEF-SEC-01`) |

## 2. Реестр выявленных и устранённых дефектов безопасности (`SECURITY_DEFECT_REGISTER`)

| ID | Критичность (CVSS-оценка) | Описание дефекта | Первопричина | Исправление (коммит `1de2067`) | Статус |
|---|---|---|---|---|---|
| **DEF-SEC-01** | Средняя (`5.3` DoS) | `vision.assess_dial_suitability()` вызывал `IndexError` при подаче кадра размером != `640×640` (например `16×16` при fuzzing) | Маска `_RR` предвычислена под `640×640`, без проверки размера входа | Добавлена проверка `min(shape) < 32` и приведение размера к `_SIZE×_SIZE` (`app/vision.py`) | **CLOSED** |
| **DEF-SEC-02** | Высокая (`7.1` ML Integrity) | `_load_yolo()` загружал `models/gauge_yolov8.pt` напрямую, минуя проверку SHA-256 в `ModelRegistry` | Исторический загрузчик v3.0 не был связан с новым `ModelRegistry` | Добавлена обязательная проверка `get_registry().verify_and_resolve("gauge_yolov8_legacy")` перед `YOLO(...)` (`app/vision.py`) | **CLOSED** |
| **DEF-SEC-03** | Средняя (`6.5` ML Integrity) | `ModelRegistry.verify_and_resolve()` пропускал проверку SHA-256 при пустой строке `sha256: ""` в `registry.json` | Условие `if rec.sha256:` допускало пустой хэш | Требуется обязательный 64-символьный SHA-256, иначе возвращается `model_sha256_missing` (`app/vision_engine/registry.py`) | **CLOSED** |
| **DEF-SEC-04** | Средняя (`5.4` Auditability) | `POST /api/vision/profile` не записывал событие переключения нейросетевого профиля в `audit_log` | Пропущен вызов `db.log_audit` при добавлении маршрута | Добавлена запись `SET_VISION_PROFILE` (`prev->active`, user, role, IP) в `audit_log` (`app/main.py`) | **CLOSED** |
| **DEF-SEC-05** | Средняя (`5.3` DoS) | Отсутствовало ограничение максимального размера тела HTTP-запроса на уровне middleware | Полагались только на лимиты uvicorn по умолчанию | В `_security_headers` добавлен лимит `10 МБ` (HTTP `413`) и проверка валидности `Content-Length` (`400`) (`app/main.py`) | **CLOSED** |
| **DEF-SEC-06** | Средняя (`5.4` CSRF) | Защита от CSRF опиралась только на `SameSite=Strict` cookie без явной проверки `Origin` | Отсутствовала проверка `Origin` в middleware для изменяющих запросов | Добавлена проверка `Origin` против `Host` / `CORS_ORIGINS` для cookie-сессий на `POST/PUT/PATCH/DELETE` → `403` (`app/main.py`) | **CLOSED** |
| **DEF-SEC-07** | Средняя (`5.8` LLM Prompt Injection) | `spec_generator._try_llm_enrichment()` передавал пользовательский текст (имена/заметки приборов) в LLM без изоляции данных и фильтрации HTML в ответе | Прямая подстановка `summary_prompt` в `user` message | Изоляция в `<FACTS>...</FACTS>`, очистка управляющих символов, усиленный system prompt, удаление HTML-тегов и лимит 2500 симв. (`app/spec_generator.py`) | **CLOSED** |
| **DEF-SEC-08** | Низкая (`3.7` Storage DoS) | `db.prune_history()` не очищал таблицу `predictive_snapshots` и не задавал `PRAGMA busy_timeout` | Таблица добавлена позже без включения в ротацию | Добавлена очистка `predictive_snapshots` в `prune_history()` и `PRAGMA busy_timeout=5000`, `cache_size=-16000` (`app/db.py`) | **CLOSED** |

## 3. Ограничения инструментального аудита и остаточные риски

- В локальном офлайн-окружении `C:\C1\GaugeVS\.venv` не установлены внешние сканеры `pip-audit`, `bandit`, `trivy` и `semgrep`; аудит выполнен на основе сформированного CycloneDX `SBOM.json` (69 компонентов), статического паттерн-скана, поиска секретов и активных негативных тестов `tests/test_security_hardening_v31.py`.
- Протокол Modbus TCP не имеет встроенного шифрования — на объекте обязательна изоляция промышленного VLAN и задание `GAUGEVISION_MODBUS_ALLOWED_CLIENTS`.
- Внешний пентест и проверка промышленного TLS-брокера с корпоративным УЦ остаются вне лабораторного контура (`NOT VERIFIED`).
