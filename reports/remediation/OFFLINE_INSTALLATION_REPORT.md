# Отчёт о проверке чистой автономной установки GaugeVision AI

Чистая установка из локального wheelhouse без доступа к индексам пакетов выполнена и подтверждена запуском всей системы: YOLOv8 на CPU, CV-инференс, HMI, SQLite WAL, аналитика 36 приборов, генерация `.docx`, Modbus TCP. Аудит сетевых вызовов процесса сервера не зафиксировал ни одного обращения к нелокальному адресу. Требования REQ-SEC-02 и REQ-SEC-01 (в части runtime) — PASS.

Доказательства: `evidence/offline_install/` — `offline_install_results.json`, `pip_install_offline.log`, `pip_check.log`, `pip_freeze_installed.txt`, `install_offline_ps1.log`, `offline_server.log`, `runtime_network_audit.jsonl`, `wheelhouse_SHA256SUMS.txt`, `tested_env_freeze_cpu.txt`, `offline_generated_spec.docx`.

## 1. Что было не так в комплекте Antigravity

| Недостаток | Последствие |
|---|---|
| `requirements.lock` из 28 пакетов без `ultralytics`, `torch`, `torchvision` | Offline-установка по lock-файлу проходила, но конвейер молча работал без YOLOv8, на OpenCV-fallback (NEW-09) |
| Проверка установки — только импорт базовых модулей | Потеря детектора не обнаруживалась |
| Скрипт подготовки без индекса PyTorch CPU | Колёса `torch==…+cpu` не скачиваются из PyPI |
| `docs/OFFLINE_DEPLOYMENT.md`: имена переменных `GAUGEVISION_ADMIN_PASSWORD` и др. | Переменные из инструкции не читаются кодом (`GAUGEVISION_ADMIN_PASS`) — пароли по инструкции не менялись бы |
| `Dockerfile`: `COPY wheels` без каталога, порт 5020 | Обычная сборка падала; порт Modbus по умолчанию — 15020 |
| ultralytics при импорте выполнял DNS-запросы к внешним серверам | Скрытая сетевая зависимость runtime (NEW-11) |

## 2. Формирование комплекта

Версии зафиксированы по окружению, на котором пройдены все испытания (`C:\C1\GaugeVS\.venv`): его `pip freeze` взят как ограничения, `torch`/`torchvision` заменены CPU-сборками той же версии. Wheelhouse скачан командой `pip download -r requirements.txt -c constraints.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple`.

| Параметр | Значение |
|---|---|
| Пакетов | 61 колесо |
| Объём | 307,2 МБ |
| Ключевые версии | torch 2.14.1+cpu, torchvision 0.29.1+cpu, ultralytics 8.4.183, opencv-python(-headless) 5.0.0.93, numpy 2.5.2, fastapi 0.156.4, uvicorn 0.54.0, aiosqlite 0.22.1, cryptography 50.0.2 |
| Python | 3.12.9, Windows 11 x64 |
| Веса | `models/gauge_yolov8.pt`, 6 503 658 байт, SHA-256 `0bcc644b40023ec281464c9a1d5d0431718708d9caa4fc2ed677d1b470ea9e68` |

`requirements.lock` сформирован `pip freeze` чистого окружения, установленного только из этого wheelhouse, и совпал с ограничениями пакет в пакет.

## 3. Установка без сети

Условия: новое venv от базового Python 3.12; `pip install --no-index --find-links <wheelhouse> -r requirements.lock`; `PIP_NO_INDEX=1`, `HTTP_PROXY`/`HTTPS_PROXY` указывают на закрытый порт — обращение к любому индексу невозможно.

| Проверка | Результат |
|---|---|
| Установка | код 0, 131 с |
| `pip check` | No broken requirements found |
| Установлено против lock | 61 / 61, лишних и недостающих нет |
| Импорт | torch 2.14.1+cpu, ultralytics 8.4.183, cv2 5.0.0, `cuda.is_available() = False` |
| Штатный `scripts/install_offline.ps1` на том же wheelhouse | SHA-256 всех колёс сверены, установка и `pip check` успешны, `YOLO True CPU` |

## 4. Запуск из установленного окружения

Сервер `run.py --demo --device cpu` запущен из нового окружения с аудит-хуком Python (`sitecustomize`), который пишет каждую попытку DNS-разрешения или подключения к нелокальному адресу со стеком вызовов.

| Проверка | Результат |
|---|---|
| Время запуска до ответа `/api/health` | 7,2 с |
| YOLOv8 | загружена на CPU (журнал: «YOLOv8 загружена … устройство cpu»), `/api/meta`: `yolo=true` |
| CV-инференс стендовых каналов | оба online, 152–153 обработанных кадра через 25 с после запуска, 73–75 мс на кадр |
| HMI | `index.html` и 4 ресурса — 200, CSP `default-src 'self'` |
| Статика | 4 ссылки `index.html` и 17 импортов JS-модулей на месте; внешних загружаемых ресурсов нет |
| SQLite | `journal_mode = wal`, 170 отсчётов стендовых приборов, 8 событий, 3 учётные записи |
| Аналитика | 36 приборов, средний Health Score 88,4 |
| Генерация ТЗ | `.docx` 132 841 байт, валидный OpenXML, 4 встроенных кадра |
| Modbus TCP | системный блок HR 40901–40906: `[36, 1, 4, 2, 0, 0]` |
| Ошибки в журнале сервера | 0 |
| Сетевой аудит | 0 событий с нелокальными адресами |

Первый прогон аудита (до исправлений NEW-11 и `run.py`) зафиксировал 5 событий: разрешение имени собственного узла и UDP `connect()` к 8.8.8.8 и широковещательным адресам частных сетей из `config.candidate_lan_ips()` — ОС при этом выбирает интерфейс и пакетов не отправляет. После исправлений при заданном `GAUGEVISION_LAN_IP` событий нет.

## 5. Что не проверено

- Сборка и запуск Docker-образа: Docker Engine на стенде отсутствует. `Dockerfile` исправлен (каталог `wheels/`, порты 8443 и 15020, `YOLO_OFFLINE`, `pip check`), для автономной сборки нужен wheelhouse под manylinux (`prepare_offline_bundle.ps1 -Platform manylinux_2_28_x86_64`).
- Установка на Linux и Astra/RED OS: не выполнялась.
- GPU-комплект (`+cu130`): не собирался, процедура описана в `docs/OFFLINE_DEPLOYMENT.md`, раздел 7.

## 6. Воспроизведение

```powershell
python reports/remediation/tests/offline_install_check.py --wheels <wheelhouse> --base-python "C:\Program Files\Python312\python.exe" --out reports/remediation/evidence/offline_install
```

Инструкция для эксплуатации обновлена: `docs/OFFLINE_DEPLOYMENT.md`.
