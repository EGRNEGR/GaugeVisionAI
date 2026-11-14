<!-- autopilot:start -->
# GaugeVision AI

Офлайн-сервис оцифровки стрелочных приборов КИПиА (FastAPI + YOLOv8n/OpenCV) и статический лендинг в `site/`.

## Команды

Сервис (нужны PyTorch и желательно GPU; в проверках не запускать):
- `py -3.12 -m venv .venv`
- `.\.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130` — PyTorch строго первым (без GPU: без `--index-url`)
- `.\.venv\Scripts\pip install -r requirements.txt`
- `.\.venv\Scripts\python run.py` — пульт на `https://localhost:8443`; флаги `--host --port --lan-ip --log-level`

Лендинг (сборки и зависимостей нет; из корня репозитория):
- `node site/tests/check.js` — факты, пути, запрещённые слова, модули, типографика, 3 варианта
- `node site/tests/components.test.js` — калибровка, бары, зоны уставок, EMA
- открыть `site/index.html` двойным кликом (file://); варианты `site/index.html?v=a|b|c`
- `python -m http.server 8765 --directory site` — `http://localhost:8765/?v=a` (порт бывает занят)

## Где что

- `app/main.py` — REST/WebSocket и оркестрация камер; `app/vision.py` — CV-конвейер; `app/config.py` — константы, типы приборов, env-переменные
- `static/` — пульт оператора сервиса (отдельно от лендинга)
- `site/js/content.js` — `GV.content`, единственный источник фактов лендинга
- `site/js/components/`, `site/js/variants/{a,b,c}.js`, `site/css/variant-*.css` — компоненты и три варианта страницы
- `site/tests/` — единственные автотесты репозитория (сервис без тестов)
- `PRODUCT.md` — аудитория и тон; `README.md` — факты и метрики; `docs/adr/` — почему так; `CONTEXT.md` — словарь
- Архитектура лендинга (поток данных, `GV.app`/`GV.tweaks`, токены, правила) — `docs/architecture.md`

## Подводные камни

- `python3` на этой машине — заглушка Microsoft Store: используй `python` или `node`
- ES-модули запрещены (не грузятся по file://); новый скрипт подключай в `site/index.html` с учётом порядка
- Размеры только в `rem` (масштаб Tweaks); `px` лишь для линий 1px и медиазапросов
- Каждое число в `site/js/content.js` сверяет `check.js` с `README.md`, `PRODUCT.md`, `app/config.py`: новое число без источника уронит проверку
- README расходится с кодом (стрелка, CLAHE, таймауты смартфона 6 с / 30 с, выход за шкалу ±5 %): прав код, см. `docs/adr/0003-kod-glavnee-readme.md`
- Не публиковать «34 проверки e2e / 18 браузерных» и «ответ сервера 3–37 мс»; лицензия проприетарная, без «open source», «MIT», «бесплатно»
- Playwright MCP блокирует file:// и открывает страницу в масштабе 67 %: для визуальной проверки сайта брать `playwright-core` из кэша npx с установленным chromium или http-сервер выше
- `GV.app` до первого `render()` не определён: в `render` вариант берут из `document.documentElement.dataset.variant`

## Окружение

Обязательных переменных нет, все с умолчаниями (`app/config.py`):
- `GAUGEVISION_DB` — путь к базе SQLite
- `GAUGEVISION_YOLO` — веса детектора; нет файла или `ultralytics` — резервный конвейер OpenCV
- `GAUGEVISION_DEVICE` — `auto`, `cuda:0` или `cpu`
- `GAUGEVISION_KEEP_DAYS` — срок хранения истории
- `GAUGEVISION_HOST`, `GAUGEVISION_PORT` — адрес и порт HTTPS
- `GAUGEVISION_LAN_IP` — LAN IP для ссылок и QR-кода (`--lan-ip` в `run.py` задаёт её же)

## Как здесь работает Autopilot

Сборка ведётся навыком `/autopilot`. Требования, спецификация и таски — в `.autopilot/`.
Прогресс — `.autopilot/dashboard.html`. Требование из `manifest.md` может снять
только пользователь. Прерванную сборку продолжает «продолжи автопилот».

### Правка без автопилота

Мелкий баг или доводка после сборки — обычная сессия, без прогона.

Сначала прочитай:
1. `.autopilot/PROGRESS.md` — что не доделано, известные баги, о чём договорились с пользователем.
2. Что правили после последней сборки — первая строка таблицы в «История git».
3. Только если правка их касается: почему сделано так — `docs/adr/`; что значат слова — `CONTEXT.md`;
   что именно просили — `manifest.md` в папке сборки (указана в начале `PROGRESS.md`).

После правки:
- коммит — по правилам из «История git»;
- строка в «Правки без автопилота» в `PROGRESS.md`: дата — что — почему;
- починенный пункт из «Не доделано» или «Известные баги» — удали;
- договорились с пользователем о том, что следующая сборка не должна пересматривать, —
  строка в «Договорились», его словами.

### История git

Целиком не читай — бери срез под вопрос:

| Вопрос | Команда |
|---|---|
| что правили после последней сборки | `git log --oneline "$(git log -1 --format=%h --grep='^Autopilot: сборка сдана')"..HEAD -- . ':(exclude).autopilot'` |
| всё, что делали ради требования | `git log --oneline --grep="R02"` |
| история файла | `git log --oneline -10 -- <файл>` |
| когда появился или исчез код | `git log --oneline -S "<фрагмент>"` |
| почему строка такая | `git blame -L <с>,<по> <файл>`, затем `git show <sha>` |
| что внутри коммита | `git show --stat <sha>` |

Срез длиннее ~30 коммитов — отдай его субагенту и возьми выжимку в десять строк.

Коммит: заголовок — что (`fix: даты в одном формате`), тело — почему, трейлер
`--trailer "Requirements: R02"`, если правка касается требования из `manifest.md`.
Заголовок `Autopilot: сборка сдана` пишет только автопилот — по нему находят последнюю сборку.
<!-- autopilot:end -->
