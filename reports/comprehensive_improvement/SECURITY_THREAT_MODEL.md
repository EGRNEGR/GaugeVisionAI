# Модель угроз GaugeVision AI 3.1 (`SECURITY_THREAT_MODEL.md`)

Дата: 2026-11-28. Контрольный коммит: `1de2067` (ветка `research/cv-next-gen`).
Методология: STRIDE + принципы OWASP ASVS / OWASP API Top 10 / OWASP ML Security / IEC 62443 / NIST SP 800-82 (используются как инженерные ориентиры, без заявления формальной сертификации).

## 1. Защищаемые активы и границы доверия

| Актив | Критичность | Граница доверия |
|---|---|---|
| Достоверность числовых показаний и статусов (`normal/warning/alert/stale`) | Высокая | CV-конвейер → SQLite → Modbus TCP / MQTT / HMI |
| Веса нейросетей (`models/*.pt`, `models/registry.json`) | Высокая | Локальная ФС (`MODELS_DIR`) → `ModelRegistry` |
| Учётные записи, сессии (`gv_session`), аудит-лог (`audit_log`) | Высокая | HTTP/WS API → `app/auth.py` → SQLite |
| Учётные данные RTSP-камер и MQTT-брокера | Высокая | SQLite (Fernet `enc:v1:`) / переменные окружения |
| Промышленный шлюз Modbus TCP и MQTT S&F | Высокая | АСУ ТП / SCADA (loopback или выделенный VLAN) |
| База данных SQLite (`readings`, `instruments`, `events`, `predictive_snapshots`) | Средняя | Локальный том хоста |
| Инженерная документация (ТЗ/дефектные ведомости DOCX/MD) и LLM-шлюз | Средняя | `spec_generator.py` → опциональный локальный LLM |

## 2. Анализ угроз по модели STRIDE (11 компонентов)

| Компонент | Угроза (STRIDE) | Сценарий компрометации | Защитная мера в GaugeVision 3.1 | Остаточный риск |
|---|---|---|---|---|
| **Операторский HMI** | Spoofing / Tampering (XSS, CSRF) | Межсайтовый запрос с cookie-сессией или внедрение скрипта | `HttpOnly/Secure/SameSite=Strict`, строгий CSP (`script-src 'self'`), CSRF-проверка `Origin` в `_security_headers`, `X-Frame-Options: DENY` | Низкий (при работе по HTTPS) |
| **Административная УЗ** | Elevation of Privilege / Brute-force | Перебор пароля или использование стендового пароля в проде | PBKDF2-HMAC-SHA256 (120 000 итераций), lockout по `user+IP`, блокировка `KNOWN_DEFAULT_PASSWORDS` вне деморежима с генерацией одноразовых паролей (`0600`) | Низкий |
| **Камера / смартфон (`/ws/phone`)** | Spoofing / DoS | Подключение без токена, поток битых кадров | Одноразовый токен `/api/phone/session`, проверка `Origin` WS, защита от битых/мелких кадров (`assess_dial_suitability` после `DEF-SEC-01`) | Низкий |
| **RTSP-источник** | Information Disclosure / SSRF | Утечка пароля RTSP в логи/API; обращение к `169.254.169.254` | Шифрование Fernet (`enc:v1:`), `mask_url_credentials`, `SecretRedactingFilter` в логах, SSRF-фильтр `validate_network_stream_url` | Низкий |
| **Локальная сеть** | Spoofing / Eavesdropping | Широкое прослушивание `0.0.0.0`, утечка трафика | `GAUGEVISION_STRICT_NETWORK=1`, белый список `GAUGEVISION_MODBUS_ALLOWED_CLIENTS`, запрет plaintext MQTT вне loopback | Средний (требуется VLAN / TLS на объекте) |
| **MQTT-брокер** | Tampering / Replay / Disclosure | Перехват трафика или повторная доставка сообщений | TLS с проверкой сертификата (`GAUGEVISION_MQTT_TLS=1`, `CA_FILE`), QoS 1 + `IdempotentReceiverLedger` по `event_uuid` | Средний (зависит от ACL брокера) |
| **Modbus TCP клиент** | Tampering / DoS | Попытка записи (FC 0x06/0x10), переполнение соединений, чтение вне карты | Строго read-only (FC 0x03/0x04; запись → `0x86/0x01`), `MAX_CLIENTS=32`, `CLIENT_IDLE_TIMEOUT_S=300`, проверка `Unit ID` (`0x0B`) и `MAX_REGISTERS=5208` (`0x02`) | Средний (протокол Modbus без шифрования — обязательна сетевая сегментация) |
| **Файлы моделей ML** | Tampering / Arbitrary Code Execution | Подмена `.pt`, обход SHA-256 пустым хэшем, `../` path traversal | `ModelRegistry.verify_and_resolve` требует 64-символьный SHA-256 для всех моделей (включая `gauge_yolov8.pt`), `is_relative_to(MODELS_DIR)`, `torch.load(..., weights_only=True)`, приоритет ONNX Runtime | Низкий (для Ultralytics `.pt` остаётся зависимость от их загрузчика до перехода на ONNX) |
| **База данных SQLite** | Tampering / DoS (disk exhaustion) | SQL-инъекция, блокировка БД, неограниченный рост таблиц | Параметризованные запросы `aiosqlite`, `PRAGMA busy_timeout=5000`, `prune_history` очищает `readings`, `instrument_readings` и `predictive_snapshots` | Низкий |
| **LLM-подсистема** | Prompt Injection / SSRF / Hallucination | Инъекция инструкций через имя прибора; SSRF на metadata | Изоляция данных в `<FACTS>...</FACTS>`, очистка управляющих символов и HTML-тегов, лимит 2500 симв., SSRF-фильтр `llm_url_error`, детерминированный fallback; LLM не имеет доступа к уставкам/калибровкам/управлению | Низкий |
| **Инженерная документация** | Tampering / Information Disclosure | Выдача документов без прав, вымышленные числа | RBAC (`engineer` для генерации, `operator` для чтения), детерминированный перенос фактических чисел из БД/оптимизатора, юридический дисклеймер | Низкий |

## 3. Принципиальные границы безопасности

GaugeVision AI является **информационно-аналитической системой мониторинга (read-only)** и **не имеет** каналов выдачи управляющих воздействий на технологическое оборудование или в контуры ПАЗ/SIS.
