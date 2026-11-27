# Независимый аудит промышленной кибербезопасности GaugeVision AI

**Проект:** GaugeVision AI Next Generation  
**Ветка:** `next-gen/analytics-validation`  
**Стенд испытаний:** строго локальный изолированный стенд (`FastAPI TestClient`, временная SQLite БД, loopback Modbus TCP `127.0.0.1:0`). Внешние промышленные системы не затрагивались.  
**Автоматизированный скрипт и сырые доказательства:** `reports/next_generation/evidence/security/run_security_audit.py`, `security_audit_results.json`

---

## 1. Объект и периметр аудита

Проверены все контуры безопасности системы с особым фокусом на новые аналитические и оптимизационные интерфейсы:
- аутентификация, сессии, защита от перебора паролей и ролевая модель RBAC (`operator` / `engineer` / `admin`);
- защита новых эндпоинтов `/api/predictive/*`, `/api/passports/*`, `/api/optimizer/*` от ресурсоёмкого DoS, подмены экономических параметров, несанкционированного изменения планов, IDOR и SQL-инъекций;
- обработка RTSP credentials (шифрование в SQLite, маскирование в API/логах), защита от SSRF и Path Traversal;
- безопасность промышленных шлюзов Modbus TCP и MQTT 3.1.1;
- безопасность экспорта документации `.docx` (XML 1.0 sanitization) и `.csv` (защита от CSV formula injection);
- готовность к автономному air-gapped развёртыванию.

---

## 2. Реализованные меры усиления безопасности в собственных компонентах

В ходе аудита выявлены и устранены следующие уязвимости в аналитических/оптимизационных и шлюзовых модулях:

1. **Ограничение ресурсоёмких запросов и DoS к оптимизатору (`app/main.py`, `app/ilp_solver.py`):**
   - Введены жёсткие верхние пределы на размеры коллекций в `OptimizerSolveRequest`: `mandatory_ids <= 250`, `excluded_ids <= 250`, `dependencies <= 250` ключей (не более 20 зависимостей на ключ), `min_per_group` / `max_per_group <= 50` групп (значения `0..1000`), `time_limit_s <= 5,0 с`.
   - Добавлен `asyncio.Semaphore(2)` с таймаутом 2,5 с (при перегрузке возвращается HTTP `429`), кооперативная отмена `cancel_event` и вынос вычислений из asyncio event loop.
   - Добавлена запись `OPTIMIZER_SOLVE` в защищённый журнал аудита `audit_log`.
2. **Валидация экономических параметров и паспортов (`app/main.py`):**
   - Добавлены явные валидаторы конечности (`math.isfinite`) для всех float-параметров оптимизатора и паспортов, проверка формата ISO-даты `verification_due_date` (`YYYY-MM-DD`), запрет отрицательных стоимостей и `NaN`/`Inf` в ядре ILP.
3. **Защита от повреждения OpenXML / XML-инъекций в `.docx` (`app/docx_builder.py`):**
   - Обёртка `xml_escape()` теперь удаляет запрещённые стандартом XML 1.0 управляющие байты (`0x00–0x08`, `0x0B`, `0x0C`, `0x0E–0x1F`) помимо экранирования `<>&"`. Проверено, что `.docx` с внедрёнными `\x00\x07<script>` открывается стандартным XML-парсером без ошибок.
4. **Проверка `inst_id` в `/api/predictive/history/{inst_id}` (`app/main.py`):**
   - Отсекаются идентификаторы с управляющими символами / длиной `> 120` (HTTP `422`) и несуществующие приборы без снапшотов (HTTP `404`).
5. **Защита Modbus TCP от истощения сокетов (`app/scada_gateway.py`):**
   - Добавлены лимит одновременных TCP-клиентов `MAX_CLIENTS = 32` и таймаут простоя соединения `CLIENT_IDLE_TIMEOUT_S = 300 с` (10 с на дочитывание PDU).

---

## 3. Результаты автоматизированных проверок безопасности (11 / 11 PASS)

| ID | Категория | Проверка | Фактический результат | Статус |
|---|---|---|---|---|
| **SEC-01** | Auth / RBAC | Блокировка неаутентифицированного доступа ко всем новым API | `GET /api/predictive/overview`, `/api/passports`, `/api/optimizer/plans`, `POST /api/optimizer/solve`, `PATCH /api/passports/sim-02` → все **HTTP 401** | **PASS** |
| **SEC-02** | HTTP Hardening | Защитные заголовки и политика CORS | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `CSP frame-ancestors 'none'`, нет `Access-Control-Allow-Origin: *` | **PASS** |
| **SEC-03** | Auth / RBAC | Матрица прав `operator` / `engineer` / `admin` | `operator`: чтение `200`, `solve/save/patch_passport` → **`403`**; `engineer`: `solve` `200`, `/api/auth/audit` → **`403`**; `admin`: `audit` `200` | **PASS** |
| **SEC-04** | Auth / RBAC | Защита от перебора паролей (brute-force lockout) | 5 неудачных попыток `401`, 6-я попытка → **`429 Too Many Requests`** (`Retry-After`) | **PASS** |
| **SEC-05** | Input / DoS | Фаззинг 9 вредоносных и ресурсоёмких запросов к `/api/optimizer/solve` | Отрицательный/сверхбольшой бюджет, `time_limit_s=999`, `300` mandatory, `260` deps, отриц. квота, `commissioning_rate=5.5`, SQLi в `objective` → все **HTTP 422**, 0 ошибок 500 | **PASS** |
| **SEC-06** | DOCX / XML | Подмена параметров паспорта и инъекция управляющих байтов/HTML в DOCX | Невалидная дата `422`, отрицательный CAPEX `422`, DOCX с `\x00\x07<script>` — валидный XML (`ET.fromstring` OK) | **PASS** |
| **SEC-07** | IDOR / SQLi | SQL-инъекции, управляющие байты в `inst_id` и неизменяемость планов | `' OR 1=1--` → `404`, `%00` → `422`, `DELETE /api/optimizer/plans/1` → **`405 Method Not Allowed`** | **PASS** |
| **SEC-08** | RTSP / SSRF / PT | Шифрование RTSP credentials, блокировка SSRF и Path Traversal | `169.254.169.254` → `422`, `../../Windows/win.ini` → `422`; RTSP пароль скрыт `***:***` в API и зашифрован `enc:v1:` (Fernet) в SQLite | **PASS** |
| **SEC-09** | Audit Log | Запись операций и попыток эскалации в `audit_log` | Зафиксированы `OPTIMIZER_SOLVE`, `PASSPORT_UPDATE`, `CREATE_CAMERA`, `FORBIDDEN ...` | **PASS** |
| **SEC-10** | SCADA / Modbus | Read-only, Unit ID и границы карты Modbus TCP | Запись FC `0x06` → `0x86 / 0x01` (Illegal Function); чужой Unit ID `99` → `0x83 / 0x0B`; выход за 4095 → `0x83 / 0x02` | **PASS** |
| **SEC-11** | Air-Gapped | Отсутствие внешних CDN-ресурсов в `static/` | `external_cdn_assets = []` (0 внешних `<script>`, `<link>`, `<img>`); выявлена 1 информационная ссылка `<a href="https://gaugevision-simulator...">` в `index.html` | **PASS** |

---

## 4. Задокументированные замечания по общим компонентам (для агента интеграции)

Следующие архитектурные замечания относятся к общим модулям (`app/config.py`, сетевые дефолты, общий UI) и зафиксированы без вмешательства в параллельную ветку Claude:

| ID | Уровень | Компонент | Суть замечания и рекомендация для эксплуатации / интеграции |
|---|---|---|---|
| **OBS-SHARED-01** | Средний | `app/config.py` (`HOST = "0.0.0.0"`) | Веб-сервер по умолчанию слушает все интерфейсы. В промышленном контуре АСУ ТП задавать `GAUGEVISION_HOST` на конкретный адрес технологического VLAN. |
| **OBS-SHARED-02** | Средний | `app/config.py` (`MQTT_TLS = False`) | MQTT по умолчанию работает без TLS. При выносе брокера за пределы loopback обязательно включать `GAUGEVISION_MQTT_TLS=1` и проверку сертификата сервера. |
| **OBS-SHARED-03** | Низкий | `app/scada_gateway.py` (Modbus TCP) | Протокол Modbus TCP не имеет встроенной аутентификации и шифрования. По умолчанию шлюз безопасно привязан к `127.0.0.1:15020`; при публикации на LAN обязателен firewall/VLAN allowlist только для IP SCADA-сервера. |
| **OBS-SHARED-04** | Низкий | `app/spec_generator.py` (`_try_llm_enrichment`) | Опциональный `GAUGEVISION_LLM_BASE_URL` (задаётся администратором) не проходит SSRF-фильтр. В air-gapped режиме переменная пуста и используется детерминированный режим. |
| **OBS-SHARED-05** | Низкий | `static/index.html`, `app/config.py` | В `index.html` присутствует справочная ссылка `<a href>` на внешний симулятор (`SIMULATOR_URL`), а `candidate_lan_ips` открывает UDP `connect("8.8.8.8", 80)` без отправки пакетов для определения маршрута. Для строго изолированных объектов рекомендуется опциональное скрытие внешней ссылки и явный `GAUGEVISION_LAN_IP`. |
