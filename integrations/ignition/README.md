# Интеграция GaugeVision AI с SCADA Ignition 8.3 (Modbus TCP, только чтение)

Каталог содержит переносимые артефакты для воспроизводимого развёртывания стыковки **GaugeVision AI** с промышленной SCADA **Inductive Automation Ignition 8.3.10** по протоколу Modbus TCP в изолированном лабораторном контуре (`127.0.0.1`, режим **только на чтение**).

> **Примечание по безопасности:** дистрибутив Ignition, бэкапы шлюза (`.gwbk`), каталог `data/` Ignition, локальные БД, пароли и API-токены в репозиторий **не включаются**.

---

## Содержимое каталога

- `device_config_template.json` — шаблон конфигурации устройства `GaugeVisionModbus` для драйвера Modbus Driver v2 (`ModbusTcp`, `127.0.0.1:15020`, `Zero-Based Addressing = true`, `Reverse Word Order = false`, запись отключена).
- `tags/gaugevision_tags.json` — официальный экспорт дерева тегов `[default]GaugeVision` (36 приборов × 19 тегов + 15 системных и производных тегов Expression; все теги `readOnly: true`).
- `projects/GaugeVisionLab/` — переносимые ресурсы Perspective-проекта **«GaugeVision — пульт»** (плитки 36 приборов в стиле ISA-101, строка статуса шлюза и системных регистров 900–911, живой тренд Tag Historian 4 приборов).
- `projects/GaugeVisionLab.zip` — экспорт проекта Ignition 8.3 (для импорта через Web UI или REST API).

Полное описание карты регистров (v1 + v2) приведено в [`docs/MODBUS_REGISTER_MAP.md`](../../docs/MODBUS_REGISTER_MAP.md).

---

## Пошаговое воспроизведение с нуля (Windows x86-64, без прав администратора)

### 1. Запуск GaugeVision AI с включённым шлюзом Modbus TCP

В корне репозитория (на CPU, без нагрузки на GPU):

```powershell
$env:CUDA_VISIBLE_DEVICES = ""
$env:GAUGEVISION_DEVICE = "cpu"
$env:GAUGEVISION_MODBUS_ENABLED = "1"
$env:GAUGEVISION_MODBUS_HOST = "127.0.0.1"
$env:GAUGEVISION_MODBUS_PORT = "15020"
$env:GAUGEVISION_MODBUS_UNIT_ID = "1"
python run.py --demo --device cpu --host 127.0.0.1 --port 8445
```

Убедитесь, что в журнале запуска появилась строка:
`Modbus TCP сервер запущен на 127.0.0.1:15020 (Unit ID 1)`.

### 2. Распаковка и запуск Ignition 8.3.10 без службы и UAC

1. Скачайте официальный дистрибутив **Ignition 8.3.10 Windows x86-64 ZIP** (`Ignition-windows-x86-64-8.3.10.zip`) со страницы `https://inductiveautomation.com/downloads/ignition/8.3.10`.
2. Распакуйте архив в короткий каталог вне репозитория, например `C:\Hakatons\gv_scada_lab\ignition-8.3.10\`.
3. Распакуйте встроенную JRE `lib\runtime\jre-win.zip` в `lib\runtime\` так, чтобы существовал файл `lib\runtime\jre-win\bin\java.exe`.
4. Запустите шлюз в консольном режиме (без `install-ignition.bat` и `start-ignition.bat`):
   ```powershell
   cd C:\Hakatons\gv_scada_lab\ignition-8.3.10
   .\IgnitionGateway.exe -c .\data\ignition.conf
   ```
5. Откройте `http://localhost:8088` в браузере и пройдите мастер первого запуска (commissioning): выберите издание **Ignition (Standard)** (пробный режим 2 ч с бесплатным сбросом на шлюзе), примите лицензионное соглашение, создайте учётную запись администратора и оставьте порты `8088 / 8043 / 8060`. Включите Quick Start, чтобы автоматически создалась локальная база историка `Sample_SQLite_Database` (либо настройте собственный Historian Provider и обновите поле `historyProvider` в JSON тегов).

### 3. Создание устройства Modbus TCP (`GaugeVisionModbus`)

Через Gateway Web UI (`Connections → Devices → Connections → Create Device Connection → Modbus TCP`) или через Gateway REST API (`POST /data/api/v1/resources/com.inductiveautomation.opcua/device` с телом из `[device_config_template.json]`):

- **Name:** `GaugeVisionModbus`
- **Hostname:** `127.0.0.1`
- **Port:** `15020`
- **Zero-based Addressing:** `true` (адреса 0..4095 напрямую совпадают с картой регистров без смещения +1)
- **Reverse Word Order:** `false` (стандартный IEEE-754 big-endian ABCD — старшее слово первым)
- **Write Requests:** отключены (`writeMultipleRegistersRequestAllowed = false`, `writeMultipleCoilsRequestAllowed = false`)

В таблице **Device Connections** статус устройства должен стать **`CONNECTED`**.

### 4. Импорт read-only тегов `[default]GaugeVision`

Через Designer (Tag Browser → Import → `tags/gaugevision_tags.json`) либо через Gateway REST API Ignition 8.3:

```text
POST /data/api/v1/tags/import?provider=default&type=json&collisionPolicy=Overwrite
Content-Type: application/octet-stream
Body: содержимое integrations/ignition/tags/gaugevision_tags.json
```

Проверьте сверку адресации на нескольких приборах:
- `[default]GaugeVision/Instruments/P02_K1_T01/Value` (HRF 4) должен совпадать с `К1-Т01` в `GET /api/scada/modbus/registers`;
- `[default]GaugeVision/Instruments/P01_K1_R01/IsNoData` (HRF 0 = quiet NaN, статус 3) должен быть `true`, `DisplayValue` — `«Нет данных»`;
- `[default]GaugeVision/System/Heartbeat` (HRUS 906) должен увеличиваться на `+1` каждые 2 с.

### 5. Импорт и запуск мнемосхемы Perspective

1. Импортируйте `projects/GaugeVisionLab.zip` (или скопируйте `projects/GaugeVisionLab/` в `<ignition>/data/projects/GaugeVisionLab` и вызовите `POST /data/api/v1/scan/projects`).
2. Откройте мнемосхему в браузере:
   `http://localhost:8088/data/perspective/client/GaugeVisionLab`

На экране отобразятся:
- шапка статуса шлюза (`НА СВЯЗИ` / `ДАННЫЕ УСТАРЕЛИ` / `БУФЕРИЗАЦИЯ АСУ ТП` / `НЕТ СВЯЗИ`), счётчик `Heartbeat (HR 906)` с возрастом и счётчики системного блока `HR 900..905`;
- матрица 6×6 всех 36 приборов в нотации ISA-101 (серый фон в норме, цвет только для отклонений `ПРЕДУПР.` / `АВАРИЯ`, честное `«Нет данных»` вместо `0` при `NaN` / `STALE`);
- живой тренд Tag Historian (`К1-Т01`, `ТА2-Т02`, `Д6-У01`, `СН1-Т01`).
