# Отчёт об автономном развёртывании (Air-Gapped / Offline Deployment)

Доказательство: `evidence/offline_install/offline_install_results.json`, `evidence/security/security_audit_merged.json`,
`evidence/hmi/hmi_results.json`, `evidence/browser_e2e/browser_e2e_report.json`.

## 1. Сохранность списка зависимостей относительно GaugeVision 2.0

Проверка `git diff 94e646e -- requirements.txt requirements.lock Dockerfile` на финальном коде ветки
`next-gen/integration` **пуста**: все новые возможности 3.0 (Multi-Gauge Vision, Predictive Analytics,
0-1 ILP Modernization Optimizer, сетевая политика, расширенная карта Modbus TCP) работают на прежнем наборе
зависимостей без добавления новых пакетов. Исследовательский модуль `app/autocal.py` выключен, OCR-зависимости
в `requirements.txt` не добавлялись.

## 2. Чистая offline-установка из локального wheelhouse

Испытание выполнено скриптом `reports/remediation/tests/offline_install_check.py` с базовым интерпретатором
Python 3.12 (`--no-index --find-links`) из локального набора колёс **без доступа к внешним индексам PyPI**:

| Проверка (`offline_install_results.json`) | Фактический результат | Статус |
|---|---|---|
| Локальный wheelhouse | `61` файл, `307,2 МБ` | PASS |
| Установка `pip install --no-index` в чистое venv | `rc = 0`, длительность **108,5 с** | PASS |
| Целостность зависимостей (`pip check`) | `rc = 0` (конфликтов нет) | PASS |
| Сверка с `requirements.lock` | **61 / 61** совпадение (`missing = []`, `extra = []`) | PASS |
| Импорты (`torch`, `ultralytics`, `cv2`, CUDA disabled) | `rc = 0` (`2.14.1+cpu 8.4.183 5.0.0 False`) | PASS |
| Локальные веса YOLOv8 (`models/gauge_yolov8.pt`) | есть, `6 503 658 Б`, SHA-256 `0bcc644b…0ea9e68` | PASS |
| Статические ресурсы HMI | `5 / 5` файлов `index.html`, `18` ES-модулей, `missing = []` | PASS |
| Внешние URL ресурсов и ссылок в статике | `external_resource_urls = []`, `external_navigation_links = []` (OBS-SHARED-05 закрыт) | PASS |
| Старт сервера в чистом окружении | `6,1 с`, `yolo = true`, `yolo_device = CPU`, `log_errors = 0` | PASS |
| Работа CV на 2 стендовых каналах | оба `online`, `158` кадров, инференс `75,0` / `98,7 мс` | PASS |
| Диспетчеризация / DOCX / Modbus / SQLite WAL | 36 приборов, DOCX валиден (`132 690 Б`, 4 фото), Modbus `[36, 2, 3, 2, 0, 0]`, `journal_mode = wal` | PASS |
| Аудит-хук сетевых обращений Python (`runtime_network_audit`) | `events_total = 0`, `external_attempts = []`, `udp_route_probe_no_packets = []` | PASS |
| Штатное завершение сервера | `graceful_shutdown_logged = true`, `log_errors = 0` | PASS |

**Вердикт `offline_install_check.py`:** **14 / 14 флагов PASS** (`passed: true`).

## 3. Автономность клиентской части (HMI)

- В браузерных прогонах `browser_e2e.py` (9 вьюпортов) и `hmi_check.mjs` (24 вида, все 8 вкладок 3.0) все запросы
  не к `127.0.0.1` принудительно блокировались и протоколировались: `externalRequestsBlocked = []`,
  `external_requests = []`.
- Статическая проверка безопасности `SEC-11` (`security_audit_merged.json`): `external_cdn_assets = []`,
  `informational_anchor_links = 0`.
- При отсутствии внешней LLM (`GAUGEVISION_LLM_BASE_URL` не задан) конструктор ТЗ работает на 100 % в
  детерминированном автономном режиме без сетевых запросов (`REQ-DOC-09`).

## 4. Практические замечания по развёртыванию в изолированном контуре

- Зависимости не изменились относительно `2.0`, поэтому при обновлении узла достаточно обновить код и сохранить
  резервную копию `data/gaugevision.db` и `data/store_forward.db` (миграция схемы выполняется автоматически при старте).
- Вне деморежима рекомендуется явно задавать `GAUGEVISION_STRICT_NETWORK=1`, адрес интерфейса `GAUGEVISION_HOST`,
  `GAUGEVISION_LAN_IP`, белый список `GAUGEVISION_MODBUS_ALLOWED_CLIENTS` и TLS для удалённого брокера MQTT
  (`GAUGEVISION_MQTT_TLS=1`, `GAUGEVISION_MQTT_CA_FILE`).
- Образ `Dockerfile` не изменялся, но сборка и прогон контейнера на целевой Linux-ОС в этой приёмке не
  выполнялись (проверялась чистая установка в Python venv на Windows).
