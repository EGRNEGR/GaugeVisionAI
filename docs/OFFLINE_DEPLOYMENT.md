# Автономное развёртывание GaugeVision AI в закрытом промышленном контуре (Air-Gapped)

Документ описывает воспроизводимую установку и запуск **GaugeVision AI** без доступа к интернету и внешним облачным сервисам.

## 1. Требования к окружению

- ОС: Windows Server / Windows 10–11 или Linux (Debian/Ubuntu/Astra/RED OS).
- Python 3.12 (рекомендуется 3.12.9).
- Режим инференса по умолчанию: CPU (`GAUGEVISION_DEVICE=cpu`), для NVIDIA GPU в промышленном сервере — `GAUGEVISION_DEVICE=cuda:0` при отдельной установке PyTorch CUDA.
- Все статические ресурсы HMI (шрифты, SVG-иконки, JS/CSS) поставляются локально внутри каталога `static/` — внешние CDN не используются.
- Все функции Трека №1 (диспетчеризация, расчёт дефектов, генерация ТЗ `.md` / `.docx`) и Трека №2 (CV-инференс, Ring Buffer, SQLite WAL Store-and-Forward, MQTT 3.1.1 QoS 1, Modbus TCP) работают полностью локально.

## 2. Подготовка офлайн-пакета (на машине с доступом к PyPI)

1. Зафиксируйте и соберите локальные wheel-пакеты в каталог `wheels/`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prepare_offline_bundle.ps1 -PythonExe C:\C1\GaugeVS\.venv\Scripts\python.exe
```

2. Убедитесь, что в комплекте присутствуют:
   - `requirements.txt` и `requirements.lock`;
   - каталог `wheels/` со всеми `.whl`-пакетами;
   - локальные веса `models/gauge_yolov8.pt` (при отсутствии детектор автоматически работает через OpenCV-fallback без попыток скачивания из сети);
   - каталог `scripts/`.

## 3. Установка в изолированном контуре (без сети)

### Вариант А — чистое виртуальное окружение (Windows / Linux)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_offline.ps1 -VenvDir .venv_offline
```

Или вручную:

```bash
python -m venv .venv_offline
.venv_offline/bin/pip install --no-index --find-links=./wheels -r requirements.lock
```

### Вариант Б — Docker-контейнер

```bash
docker build --build-arg OFFLINE_WHEELS=1 -t gaugevision-ai:offline .
docker run -d --name gaugevision \
  -p 8000:8000 -p 5020:5020 \
  -e GAUGEVISION_DEVICE=cpu \
  -e GAUGEVISION_AUTH_REQUIRED=1 \
  -e GAUGEVISION_ADMIN_PASSWORD="<СЛОЖНЫЙ_ПАРОЛЬ>" \
  -v $(pwd)/data:/app/data \
  gaugevision-ai:offline
```

## 4. Обязательная настройка безопасности перед вводом в эксплуатацию

Скопируйте `.env.example` в `.env` и обязательно измените параметры по умолчанию:

- `GAUGEVISION_AUTH_REQUIRED=1` — обязательная локальная RBAC-аутентификация (`operator`, `engineer`, `admin`).
- `GAUGEVISION_ADMIN_PASSWORD`, `GAUGEVISION_ENGINEER_PASSWORD`, `GAUGEVISION_OPERATOR_PASSWORD` — задайте уникальные пароли (пароли по умолчанию предназначены только для локального стенда).
- `GAUGEVISION_SECRET_KEY` — стойкий секрет для шифрования учётных данных RTSP (Fernet) и подписи сессий.
- `GAUGEVISION_ALLOW_LOOPBACK_STREAMS=0` и `GAUGEVISION_ALLOW_EXTERNAL_STREAMS=0` — защита от SSRF (разрешены только частные промышленные подсети RFC1918 и явно указанные `GAUGEVISION_ALLOWED_STREAM_CIDRS`).
- `GAUGEVISION_ALLOW_FAULT_INJECTION=0` — запрет API инъекции сбоев в боевом режиме.
- `GAUGEVISION_MQTT_ENABLED=1`, `GAUGEVISION_MQTT_QOS=1`, `GAUGEVISION_MQTT_TLS=1`, `GAUGEVISION_MQTT_USERNAME`, `GAUGEVISION_MQTT_PASSWORD` — гарантированная доставка в SCADA с подтверждением `PUBACK`.
- `GAUGEVISION_CORS_ORIGINS` — белый список доверенных origin HMI.

## 5. Запуск и проверка работоспособности

Демонстрационный стенд (36 приборов, CPU-only, HTTPS):

```powershell
$env:CUDA_VISIBLE_DEVICES = ""
$env:GAUGEVISION_DEVICE = "cpu"
.\.venv_offline\Scripts\python.exe -B run.py --demo --host 127.0.0.1 --port 8443 --device cpu
```

Промышленный режим (HTTPS с локальным X.509 сертификатом):

```powershell
$env:CUDA_VISIBLE_DEVICES = ""
$env:GAUGEVISION_DEVICE = "cpu"
.\.venv_offline\Scripts\python.exe -B run.py --host 0.0.0.0 --port 8443 --device cpu
```

Вход в веб-консоль: откройте `https://<ip>:8443` (или `https://localhost:8443`) и авторизуйтесь в модальном окне `Вход в систему GaugeVision AI`.

## 6. Ограничения применения

GaugeVision AI является вспомогательной системой оптического мониторинга. Система не является сертифицированным средством измерений в соответствии с ФЗ-102 «Об обеспечении единства измерений» и не предназначена для замены штатных систем ПАЗ, защит и АСУ ТП.
