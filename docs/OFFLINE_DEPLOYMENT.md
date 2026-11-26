# Автономное развёртывание GaugeVision AI в закрытом промышленном контуре

Инструкция описывает установку и запуск GaugeVision AI без доступа к интернету. Процедура для Windows x64 проверена 26.11.2026 на чистом окружении: установка из локального wheelhouse, запуск, CV-инференс YOLOv8 на CPU, HMI, SQLite, аналитика, генерация `.docx`, Modbus TCP. Аудит сетевых вызовов процесса сервера за время проверки не зафиксировал ни одного обращения к нелокальному адресу. Отчёт и доказательства: `reports/remediation/OFFLINE_INSTALLATION_REPORT.md`.

## 1. Состав комплекта

| Компонент | Где | Назначение |
|---|---|---|
| `requirements.lock` | корень репозитория | Полный закреплённый набор из 61 пакета: FastAPI, OpenCV, aiosqlite, cryptography, ultralytics 8.4.183, torch 2.14.1+cpu, torchvision 0.29.1+cpu и их зависимости |
| `wheels/` | создаётся скриптом подготовки | Колёса всех пакетов комплекта (Windows x64, Python 3.12 — около 307 МБ) и `SHA256SUMS.txt` |
| `models/gauge_yolov8.pt` | в репозитории | Локальные веса детектора корпуса прибора (6,5 МБ, SHA-256 `0bcc644b40023ec281464c9a1d5d0431718708d9caa4fc2ed677d1b470ea9e68`) |
| `static/` | в репозитории | Весь интерфейс пульта: шрифты, иконки, JS и CSS; внешних CDN нет |
| `scripts/prepare_offline_bundle.ps1`, `scripts/install_offline.ps1` | в репозитории | Подготовка и установка комплекта |

Без `ultralytics` и `torch` конвейер не падает, а молча переходит на OpenCV-fallback, поэтому оба пакета входят в lock-файл обязательно.

## 2. Подготовка комплекта на машине с доступом к PyPI

Требуется Python 3.12 (версии в `requirements.lock` проверены на 3.12.9).

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prepare_offline_bundle.ps1 -PythonExe "C:\Program Files\Python312\python.exe"
```

Скрипт скачивает колёса по `requirements.lock` (PyTorch — из CPU-индекса `download.pytorch.org/whl/cpu`, остальное — из PyPI), пишет `wheels/SHA256SUMS.txt` и проверяет наличие весов YOLOv8. Внутреннее зеркало задаётся параметрами `-PypiIndex` и `-TorchIndex`.

В закрытый контур переносится репозиторий вместе с каталогами `wheels/` и `models/`.

## 3. Установка в закрытом контуре

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_offline.ps1 -BasePython "C:\Program Files\Python312\python.exe"
```

Скрипт сверяет SHA-256 колёс, создаёт `.venv_offline`, ставит пакеты с ключом `--no-index` (обращение к индексу пакетов невозможно), выполняет `pip check` и проверяет загрузку YOLOv8 на CPU. Ожидаемый вывод последнего шага: `YOLO True CPU`. Установка 61 пакета занимает около двух минут.

Ручной вариант:

```powershell
python -m venv .venv_offline
.venv_offline\Scripts\python.exe -m pip install --no-index --find-links=wheels -r requirements.lock
.venv_offline\Scripts\python.exe -m pip check
```

## 4. Настройка перед вводом в эксплуатацию

Скопируйте `.env.example` в `.env` и задайте параметры объекта. Переменные читаются при запуске; уже заданные в окружении значения имеют приоритет над `.env`.

| Переменная | Значение для промышленного режима |
|---|---|
| `GAUGEVISION_DEMO` | `0` — промышленный профиль (отдельная БД `data/gaugevision.db`) |
| `GAUGEVISION_ADMIN_PASS`, `GAUGEVISION_ENGINEER_PASS`, `GAUGEVISION_OPERATOR_PASS` | Уникальные пароли учётных записей `admin`, `engineer`, `operator` |
| `GAUGEVISION_SECRET_KEY` | Длинный случайный ключ шифрования паролей RTSP в БД (Fernet). Без него ключ создаётся в файле `data/.gv_secret.key` |
| `GAUGEVISION_LAN_IP` | Адрес узла в сети цеха: ссылки и QR-коды строятся по нему, интерфейсы не перебираются |
| `GAUGEVISION_ALLOWED_STREAM_CIDRS` | Подсети камер, если они вне RFC 1918 (например `10.20.0.0/16`) |
| `GAUGEVISION_ALLOW_LOOPBACK_STREAMS`, `GAUGEVISION_ALLOW_EXTERNAL_STREAMS` | `0` — защита от SSRF |
| `GAUGEVISION_ALLOW_FAULT_INJECTION` | `0` — симуляция отказов из интерфейса запрещена |
| `GAUGEVISION_MQTT_ENABLED`, `GAUGEVISION_MQTT_HOST`, `GAUGEVISION_MQTT_PORT`, `GAUGEVISION_MQTT_QOS=1`, `GAUGEVISION_MQTT_USERNAME`, `GAUGEVISION_MQTT_PASSWORD`, `GAUGEVISION_MQTT_TLS` | Доставка в SCADA с подтверждением PUBACK |
| `GAUGEVISION_MODBUS_ENABLED`, `GAUGEVISION_MODBUS_HOST`, `GAUGEVISION_MODBUS_PORT` (по умолчанию 15020), `GAUGEVISION_MODBUS_UNIT_ID` | Регистровая карта для SCADA |
| `GAUGEVISION_LLM_BASE_URL`, `GAUGEVISION_LLM_MODEL`, `GAUGEVISION_LLM_TIMEOUT` | Необязательное обогащение формулировок ТЗ локальной LLM (Ollama, vLLM, llama.cpp). Пусто — детерминированный режим. На CPU ответ модели 7–9 млрд параметров занимает минуты, тайм-аут задаётся соответственно |

Если в промышленном режиме пароль не задан или совпадает со стендовым из `.env.example`, при первом запуске для учётной записи создаётся случайный пароль. Он однократно записывается в `data/initial_credentials.txt` (права 0600); файл нужно перенести в защищённое хранилище и удалить. Стендовые пароли вне деморежима отклоняются при входе даже для ранее созданных учётных записей.

## 5. Запуск

```powershell
$env:CUDA_VISIBLE_DEVICES = ""
.\.venv_offline\Scripts\python.exe -B run.py --host 0.0.0.0 --port 8443 --device cpu
```

Демонстрационный профиль (36 приборов: живая камера смартфона и 35 стендовых): добавить `--demo`.

Пульт: `https://<адрес-узла>:8443`. Сертификат самоподписный, создаётся при первом запуске в `certs/`.

Сервер выставляет `YOLO_OFFLINE=1` до загрузки ultralytics: без этого библиотека при импорте проверяет «онлайн» DNS-запросами к внешним серверам.

## 6. Проверка установки

Полная автоматическая проверка (чистое окружение, установка, запуск, аудит сетевых вызовов):

```powershell
python reports/remediation/tests/offline_install_check.py --wheels wheels --base-python "C:\Program Files\Python312\python.exe"
```

Ручная проверка после запуска: `https://<адрес>:8443/api/health` отвечает `{"ok": true, ...}`; после входа на вкладке «Видеоаналитика» стендовые каналы показывают задержку инференса около 60–75 мс на кадр (CPU).

## 7. GPU-узел

Для NVIDIA GPU замените в `requirements.lock` строки `torch==2.14.1+cpu` и `torchvision==0.29.1+cpu` на сборки `+cu130` и подготовьте комплект с `-TorchIndex https://download.pytorch.org/whl/cu130`. Запуск — с `--device cuda:0`. Сценарий проверки производительности на GPU-станции: `reports/remediation/tests/gpu_validation_3090.py`.

## 8. Docker

`Dockerfile` собирает CPU-образ из `requirements.lock`. Для автономной сборки нужен wheelhouse под Linux:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prepare_offline_bundle.ps1 -Platform manylinux_2_28_x86_64
docker build --build-arg OFFLINE_WHEELS=1 -t gaugevision-ai:offline .
docker run -d -p 8443:8443 -p 15020:15020 -v ./data:/app/data --env-file .env gaugevision-ai:offline
```

Сборка образа на стенде приёмки не выполнялась: Docker Engine на нём отсутствует.

## 9. Ограничения применения

GaugeVision AI — вспомогательная система оптического мониторинга. Она не является средством измерений утверждённого типа (ФЗ-102 «Об обеспечении единства измерений») и не заменяет штатные системы ПАЗ, защит и АСУ ТП.
