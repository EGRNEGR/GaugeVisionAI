# Безопасность моделей ML, зависимостей и промышленных протоколов (`ML_SECURITY_REPORT.md`)

Дата: 2026-11-28. Контрольный коммит: `1de2067`.
Объединяет материалы: `ML_SECURITY_REPORT`, `DEPENDENCY_SECURITY_REPORT`, `INDUSTRIAL_SECURITY_REPORT`, `SECURITY_REMEDIATION_REPORT`, `SECURITY_REVALIDATION_REPORT`.
Связанный артефакт: `reports/comprehensive_improvement/SBOM.json` (CycloneDX 1.5, 69 компонентов).

## 1. Безопасность моделей машинного обучения (ML Security)

| Модель (`model_id`) | Файл | Формат | Лицензия | SHA-256 | Проверка при загрузке |
|---|---|---|---|---|---|
| `gauge_yolov8_legacy` | `models/gauge_yolov8.pt` | PyTorch (Ultralytics) | AGPL-3.0 | `0bcc644b40023ec281464c9a1d5d0431718708d9caa4fc2ed677d1b470ea9e68` | **SHA-256 через `ModelRegistry` (`DEF-SEC-02`)** |
| `needle_keypoint_v31_pt` | `models/needle_keypoint_v31.pt` | PyTorch (`weights_only=True`) | MIT / BSD-3 | `1ab9e7e0540604f9b5fd871bdfe5ebb6c53959b75b2127463a092a8e671192fe` | **SHA-256 + `weights_only=True`** (приоритет ONNX) |
| `needle_seg_v31_pt` | `models/needle_seg_v31.pt` | PyTorch (`weights_only=True`) | MIT / BSD-3 | `ca570bd622507c0e9e92875bb1f417f4df5a162e18b1af82ab679c73ecd605ba` | **SHA-256 + `weights_only=True`** (приоритет ONNX) |

- Загрузка произвольных весов через API **отсутствует** (доступно только переключение между 4 фиксированными профилями для роли `engineer` с записью в `audit_log`).
- Path traversal (`../`), отсутствие файла, несовпадение SHA-256 и пустой SHA-256 (`DEF-SEC-03`) жёстко блокируются.
- Все новые модели стрелки загружаются через `torch.load(..., weights_only=True)` (исключает выполнение произвольного pickle-кода), а при появлении `.onnx` автоматически переключаются на `onnxruntime` (без pickle).
- Уверенность нейросети (`confidence`) **не трактуется как гарантия безопасности**: в `FusionNeedleEstimator` при расхождении оценок и низкой согласованности возвращается безопасный отказ (`valid=False`), а на непригодных/повреждённых кадрах срабатывает `assess_dial_suitability` (усилена проверкой размеров `DEF-SEC-01`).

## 2. Безопасность зависимостей и цепочки поставок (SBOM)

- Сформирован `SBOM.json` (CycloneDX 1.5) по рабочему окружению `C:\C1\GaugeVS\.venv`: **69 пакетов**.
- Ключевые версии: `fastapi 0.156.4`, `uvicorn 0.54.0`, `cryptography 50.0.2`, `torch 2.14.1+cu130`, `onnxruntime 1.32.0`, `opencv-python 5.0.0.93`, `ultralytics 8.4.183`.
- **Лицензионный риск цепочки поставок:** `ultralytics 8.4.183` распространяется под **AGPL-3.0**. Новые модели стрелки (`NeedleSegUNet`, `NeedleKeypointNet`) и их веса полностью чисты (**MIT / BSD-3-Clause**). Для коммерческого закрытого развёртывания без AGPL в `training_package_3090/` предусмотрен переход на **RF-DETR Nano/Small (Apache 2.0)** + ONNX Runtime (MIT).
- Скан секретов по всем текстовым файлам репозитория: **0 находок**.
- Внешние сканеры CVE (`pip-audit`, `trivy`) в локальном air-gapped окружении не установлены; рекомендуется регулярный прогон `pip-audit` по `SBOM.json` в контуре CI при наличии доступа к базе OSV.

## 3. Безопасность промышленной интеграции (OT / ICS)

- **Modbus TCP (`app/scada_gateway.py`):** строго read-only (FC 0x03/0x04), запись FC 0x06/0x10 отклоняется исключением `0x86/0x01`, чужой Unit ID → `0x83/0x0B`, выход за `MAX_REGISTERS=5208` → `0x83/0x02`, ограничение `MAX_CLIENTS=32`, idle timeout `300 с`, обязательный белый список `GAUGEVISION_MODBUS_ALLOWED_CLIENTS` при биндинге вне loopback.
- **MQTT (`app/net_policy.py`, `app/scada_gateway.py`):** вне loopback требуется `GAUGEVISION_MQTT_TLS=1` с проверкой сертификата и имени хоста (`GAUGEVISION_MQTT_CA_FILE` для локального УЦ); защита от дубликатов `IdempotentReceiverLedger` по `event_uuid`.
- **RTSP / HTTP-MJPEG (`app/security.py`):** блокировка link-local/metadata (`169.254.0.0/16`), шифрование учётных данных Fernet `enc:v1:` в SQLite, маскирование в API и логах (`SecretRedactingFilter`).

## 4. Повторная проверка после исправлений (`SECURITY_REVALIDATION`)

Повторный прогон `tests/test_security_hardening_v31.py` на замороженном коммите `1de2067`: **4 / 4 PASS** (`ml_security_registry`, `api_rbac_csrf_dos_audit`, `llm_and_industrial_security`, `fuzzing_malformed_inputs`). Все 8 дефектов `DEF-SEC-01..08` закрыты и покрыты регрессионными тестами.
