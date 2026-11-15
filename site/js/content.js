/*
 * GV.content — единственный источник фактов лендинга GaugeVision AI.
 * Чистые данные, без DOM. Источники: README.md, PRODUCT.md, код в app/ и notes.md
 * (где README и код расходятся, текст написан по коду — interfaces.md, правило 1a).
 * Все числа во всех строках (кроме служебных ключей) сверяются с источниками
 * командой `node site/tests/check.js`; там же — длина выводимых строк (≤ 140 символов)
 * и заголовки секций в 3–6 слов: на странице нет абзацев, только заголовки, цифры и формулы.
 * В конце файла строки проходят типограф: неразрывный пробел между числом и единицей
 * и перед длинным тире.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : this;
  var GV = (root.GV = root.GV || {});

  var REPO = 'https://github.com/EGRNEGR/GaugeVisionAI';

  var content = {
    meta: {
      name: 'GaugeVision AI',
      repoUrl: REPO,
      licenseUrl: REPO + '/blob/main/LICENSE',
      trackShort: 'Трек №3 · Умное производство',
      copyright: '© 2026 EGRNEGR. Все права защищены. Код опубликован только для ознакомления',
      version: '1.0.0'
    },

    /* Восемь экранов одной страницы в порядке брифа; заголовок — 3–6 слов. У hero заголовок — hero.title (h1). */
    sections: [
      { id: 'hero', index: '01', nav: 'Суть' },
      { id: 'reading', index: '02', nav: 'Показание', title: 'От угла θ к МПа' },
      { id: 'pipeline', index: '03', nav: 'Конвейер', title: 'Четыре шага от кадра к значению' },
      { id: 'metrics', index: '04', nav: 'Замеры', title: 'Замеры с условиями стенда' },
      { id: 'compare', index: '05', nav: 'Было → Стало', title: 'Журнал обходчика → пульт оператора' },
      { id: 'architecture', index: '06', nav: 'Архитектура', title: 'Один сервер, локальный контур' },
      { id: 'limits', index: '07', nav: 'Ограничения', title: 'Компромиссы и ограничения среды' },
      { id: 'contact', index: '08', nav: 'GitHub', title: 'Код и README — на GitHub' }
    ],

    /* Hero: ролик Gemini на прокрутке и поверх только три элемента — h1, одна строка сути (одно предложение), индикатор. */
    hero: {
      title: 'Стрелочные приборы ТЭЦ — на пульте оператора',
      line: 'Камера считывает показания КИПиА без врезки и останова, без интернета.',
      scrollLabel: 'Прокрутите',
      video: {
        src: 'assets/video/gauge_pullback.scrub.mp4',
        srcMobile: 'assets/video/gauge_pullback.scrub-m.mp4',
        poster: 'assets/img/poster.jpg',
        label: 'Ролик: камера отъезжает от манометра на трубопроводе котельной, рядом — камера, которая снимает его шкалу'
      }
    },

    /* Сцена «Показание»: значение (4,39 МПа) не хранится — считается из theta по calibration. */
    reading: {
      theta: 253.4,
      device: 'Манометр, шкала 0–10 МПа',
      caption: 'Калибровка по двум точкам: θmin 135° → 0, θmax 45° → 10 МПа, по часовой',
      zones: { normal: 'НОРМА', warning: 'ПРЕДУПРЕЖДЕНИЕ', alert: 'CRITICAL' },
      sliderLabel: 'Показание прибора, МПа'
    },

    /* value — число для счётчика, display — итоговая запись (русская нотация). */
    metrics: [
      { id: 'scale-error', group: 'quality', value: 0.38, digits: 2, display: '0,38', unit: '%',
        label: 'Максимальная ошибка шкалы', condition: '28 сцен стенда, средняя ошибка 0,11 %', kind: 'measured' },
      { id: 'infer-gpu', group: 'speed', value: 7.2, digits: 1, display: '7,2', unit: 'мс/кадр',
        label: 'Инференс YOLOv8n на GPU', condition: 'RTX 5060 Laptop, FP16, кадр 1280×720', kind: 'measured' },
      { id: 'pipeline-latency', group: 'speed', value: 30, valueTo: 100, digits: 0, display: '30–100', unit: 'мс/кадр',
        label: 'Полный конвейер', condition: 'локализация, нормализация, стрелка, EMA', kind: 'measured' },
      { id: 'map50', group: 'quality', value: 90.1, digits: 1, display: '90,1', unit: '%',
        label: 'mAP₅₀ детектора', condition: 'YOLOv8n, 25 эпох, валидация обучения', kind: 'measured' },
      { id: 'phone-stream', group: 'speed', value: 3, valueTo: 4, digits: 0, display: '3–4', unit: 'к/с',
        label: 'Поток со смартфона', condition: 'WebP, 1280 px', kind: 'measured' },
      { id: 'bench-25', group: 'scale', value: 100, digits: 0, display: '100', unit: 'к/с',
        label: '25 камер на одном ноутбуке', condition: 'стенд команды: RTX 5060 Laptop 8 GB, 16 GB RAM, 4 к/с на камеру, загрузка GPU 72 %', kind: 'measured' },
      { id: 'infer-cpu', group: 'speed', value: 29, digits: 0, display: '29', unit: 'мс/кадр',
        label: 'Инференс YOLOv8n на CPU', condition: 'FP32, без видеокарты', kind: 'measured' },
      { id: 'recall-precision', group: 'quality', value: 1, digits: 2, display: '1,00 / 1,00', unit: '',
        label: 'Recall Gauge / Precision Needle', condition: 'валидация обучения', kind: 'measured' },
      { id: 'scale-50', group: 'scale', value: 200, digits: 0, display: '200', unit: 'к/с',
        label: '50 камер', condition: 'расчёт: RTX 4070 Ti Super 16 GB, узел ≈ 230–260 тыс. ₽', kind: 'calculated' },
      { id: 'scale-100', group: 'scale', value: 400, digits: 0, display: '400', unit: 'к/с',
        label: '100 камер', condition: 'расчёт: RTX 4090 24 GB, узел ≈ 580–680 тыс. ₽', kind: 'calculated' }
    ],
    metricsNote: 'Стенд: синтетические приборы, наклон ≈ 41°. Скриптов воспроизведения замеров в репозитории нет.',

    /* Девять этапов конвейера по коду (notes.md §1) — источник для карточек pipelineCards. */
    pipeline: [
      {
        id: 'capture', index: '00', title: 'Захват',
        short: 'Последний кадр каждой камеры, буфер 1 кадр',
        params: [
          { name: 'CAPTURE_BUFFERSIZE', value: '1', note: 'кадр в буфере драйвера' },
          { name: 'PROCESS_FPS', value: '3,0', note: 'обработок в секунду на камеру' },
          { name: 'VISION_EXECUTOR_WORKERS', value: '2', note: 'потока для расчёта кадров' },
          { name: 'MAX_PROCESS_WIDTH', value: '1280 px', note: 'кадры шире уменьшаются (INTER_AREA)' },
          { name: 'Лимит кадра смартфона', value: '8 МиБ', note: 'проверка в ws_phone' }
        ],
        formula: 'cap.set(CAP_PROP_BUFFERSIZE, 1)',
        file: 'app/streamer.py · app/main.py',
        aspect: 'Потоковая обработка'
      },
      {
        id: 'locate', index: '01', title: 'Локализация',
        short: 'YOLOv8n находит корпус, OpenCV уточняет циферблат эллипсом',
        params: [
          { name: 'YOLO_IMGSZ', value: '640', note: 'размер входа детектора' },
          { name: 'YOLO_CONF', value: '0,35', note: 'порог уверенности бокса' },
          { name: 'YOLO_CLASSES', value: 'gauge, dial, meter, manometer, clock', note: 'классы корпуса прибора' },
          { name: 'Устройство', value: 'CUDA FP16 или CPU', note: 'YOLO_DEVICE = auto' },
          { name: 'Допуск эллипса', value: '± 15 % бокса', note: 'центр эллипса внутри бокса YOLO' },
          { name: 'HoughCircles', value: 'dp 1,2 · param1 140 · param2 45', note: 'только подтверждение эллипса' }
        ],
        formula: 'source = «yolo+ellipse», если центр эллипса ∈ бокс YOLO ± 15 %',
        file: 'app/vision.py',
        aspect: 'Детекция'
      },
      {
        id: 'normalize', index: '02', title: 'Нормализация',
        short: 'Эллипс циферблата аффинно выпрямляется в круг 640 × 640',
        params: [
          { name: 'DIAL_SIZE', value: '640 px', note: 'диаметр нормализованного циферблата' },
          { name: 'Интерполяция', value: 'INTER_LINEAR', note: 'cv2.warpAffine' },
          { name: 'Края', value: 'BORDER_REPLICATE', note: 'без чёрной рамки' },
          { name: 'Проверенный наклон', value: '≈ 41°', note: 'стенд, по README' }
        ],
        formula: 'M = T(S/2) · R(φ) · diag(R/a, R/b) · R(−φ) · T(−c)',
        file: 'app/vision.py',
        aspect: 'Коррекция перспективы'
      },
      {
        id: 'light', index: '03', title: 'Свет и контраст',
        short: 'CLAHE для циферблата, «шляпы» Black-Hat / Top-Hat для стрелки',
        params: [
          { name: 'CLAHE', value: 'clip 3,0 · сетка 8×8', note: 'только при поиске циферблата' },
          { name: 'Ядро Black-Hat / Top-Hat', value: 'эллипс 31×31', note: 'три маски: тёмная, светлая, насыщенность' },
          { name: 'Кольцо порога Otsu', value: '0,04–0,46 размера', note: 'фон вне циферблата не влияет' },
          { name: 'Нижний порог маски', value: '18', note: 'после Otsu' },
          { name: 'MORPH_CLOSE', value: 'ядро 5×5', note: 'склейка разрывов стрелки' }
        ],
        formula: 'BlackHat = close(I) − I · TopHat = I − open(I)',
        file: 'app/vision.py',
        aspect: 'Коррекция освещения'
      },
      {
        id: 'needle', index: '04', title: 'Вектор стрелки',
        short: 'Радиальный момент ведёт, HoughLinesP уточняет',
        params: [
          { name: 'Кольцо момента', value: '0,06–0,36 размера', note: 'внешние риски и цифры исключены' },
          { name: 'Гистограмма', value: 'шаг 1°, сглаживание ± 4°', note: 'круговое окно 9' },
          { name: 'Второй максимум', value: 'за пределами ± 25°', note: 'входит в уверенность' },
          { name: 'HoughLinesP', value: 'порог 0,08·size · длина ≥ 0,15·size · разрыв 10', note: 'линия через ось' },
          { name: 'Согласование Hough и момента', value: '≤ 12°', note: 'иначе уверенность × 0,9' }
        ],
        formula: 'θ = atan2(Δy, Δx) mod 360',
        file: 'app/vision.py',
        aspect: 'Детекция стрелки'
      },
      {
        id: 'calibrate', index: '05', title: 'Калибровка',
        short: 'Угол θ → значение по двухточечной калибровке',
        params: [
          { name: 'θmin → Vmin', value: '135° → 0', note: 'по умолчанию' },
          { name: 'θmax → Vmax', value: '45° → 10', note: 'по умолчанию' },
          { name: 'Направление', value: 'CW или CCW', note: 'задаётся в окне «Настройка»' },
          { name: 'Выход за шкалу', value: '± 5 %', note: 'clamp = 0,05' }
        ],
        formula: 'V = Vmin + ((θ − θmin) mod 360) / span · (Vmax − Vmin)',
        file: 'app/vision.py',
        aspect: 'Перевод в МПа / бар'
      },
      {
        id: 'stabilize', index: '06', title: 'Стабилизация',
        short: 'EMA α = 0,25 и порог уверенности 0,25',
        params: [
          { name: 'EMA_ALPHA', value: '0,25', note: 'вес нового отсчёта' },
          { name: 'MIN_NEEDLE_CONFIDENCE', value: '0,25', note: 'ниже — отсчёт недостоверен' },
          { name: 'REDETECT_EVERY_N_FRAMES', value: '15', note: 'период повторной локализации' },
          { name: 'Промахов до сброса', value: '3', note: 'подряд' },
          { name: 'Гистерезис ROI', value: '5 % оси', note: 'меньшее смещение игнорируется' }
        ],
        formula: 'V̄ₜ = α · Vₜ + (1 − α) · V̄ₜ₋₁',
        file: 'app/vision.py · app/config.py',
        aspect: 'Сглаживание показаний'
      },
      {
        id: 'setpoints', index: '07', title: 'Уставки',
        short: 'Пять зон LL / L / НОРМА / H / HH',
        params: [
          { name: 'Зоны', value: 'LL / L / НОРМА / H / HH', note: 'дуги на оверлее шкалы' },
          { name: 'Статусы', value: 'normal · warning · alert', note: 'хранятся в БД' },
          { name: 'Порядок', value: 'LL ≤ L ≤ H ≤ HH', note: 'иначе ошибка 422' },
          { name: 'Стандарт', value: 'ISA-18.2 / ГОСТ Р МЭК 62682', note: 'модель сигнализации' }
        ],
        formula: 'V ≤ LL или V ≥ HH → alert; V ≤ L или V ≥ H → warning',
        file: 'app/vision.py · app/main.py',
        aspect: 'Сигнализация'
      },
      {
        id: 'output', index: '08', title: 'Выдача',
        short: 'WebSocket на пульт, SQLite раз в секунду, CSV',
        params: [
          { name: 'DB_WRITE_INTERVAL', value: '1 с', note: 'минимальный интервал записи' },
          { name: 'Очередь пульта', value: '300 сообщений', note: 'DashboardHub, на каждого клиента' },
          { name: 'HISTORY_KEEP_DAYS', value: '90 суток', note: 'срок хранения истории' },
          { name: 'MJPEG_FPS', value: '8', note: 'превью с оверлеем' },
          { name: 'CSV', value: 'UTF-8 с BOM, разделитель «;»', note: 'открывается в Excel' }
        ],
        formula: 'запись, если valid и прошло ≥ 1 с с прошлой записи',
        file: 'app/main.py · app/db.py',
        aspect: 'Потоковая обработка'
      }
    ],

    /*
     * Четыре карточки горизонтального трека (бриф, пункт 4) — подписи как в коде: аффинная коррекция,
     * радиальный момент. Задержка — только замеренная; у 02 и 03 отдельного замера нет (latency: null,
     * они входят в pipelineTotal).
     */
    pipelineCards: [
      { id: 'locate', index: '01', title: 'Локализация: CLAHE + YOLOv8n',
        formula: ['CLAHE clip 3,0 · 8×8', 'ROI = YOLOv8n(кадр)'],
        params: [{ name: 'YOLO_IMGSZ', value: '640' }, { name: 'YOLO_CONF', value: '0,35' }, { name: 'Устройство', value: 'CUDA FP16 или CPU' }],
        latency: { value: '7,2', unit: 'мс/кадр GPU', note: '29 мс/кадр CPU' } },
      { id: 'normalize', index: '02', title: 'Эллипс → круг: аффинная коррекция',
        formula: ['M = T(S/2)·R(φ)·diag(R/a, R/b)·R(−φ)·T(−c)'],
        params: [{ name: 'DIAL_SIZE', value: '640 px' }, { name: 'Интерполяция', value: 'INTER_LINEAR' }, { name: 'Наклон на стенде', value: 'до ≈ 41°' }],
        latency: null },
      { id: 'needle', index: '03', title: 'Угол θ: радиальный момент + HoughLinesP',
        formula: ['θ = atan2(y₁−y₀, x₁−x₀)', 'V = Vmin + ((θ−θmin) mod 360)/Δθ·(Vmax−Vmin)'],
        params: [{ name: 'Гистограмма', value: 'шаг 1°, ± 4°' }, { name: 'Маски', value: 'Black-Hat / Top-Hat 31×31' }, { name: 'Hough ↔ момент', value: '≤ 12°' }],
        latency: null },
      { id: 'stabilize', index: '04', title: 'Сглаживание EMA α = 0,25',
        formula: ['V̄ₜ = α·Vₜ + (1−α)·V̄ₜ₋₁'],
        params: [{ name: 'EMA_ALPHA', value: '0,25' }, { name: 'MIN_NEEDLE_CONFIDENCE', value: '0,25' }],
        latency: { value: '≈ 90 %', unit: 'скачка за 8 кадров', note: 'оценка по формуле, не замер' } }
    ],
    pipelineTotal: { value: '30–100', unit: 'мс/кадр', label: 'Конвейер целиком' },

    /* Калибровка по app/vision.py angle_to_value; уставки — со скриншота пульта (манометр). */
    calibration: {
      thetaMin: 135,
      thetaMax: 45,
      vMin: 0,
      vMax: 10,
      unit: 'МПа',
      direction: 'CW',
      span: 270,
      clamp: 0.05,
      setpoints: { LL: 1, L: 2, H: 8, HH: 9 },
      barPerMpa: 10,
      formula: 'V = Vmin + ((θ − θmin) mod 360) / span · (Vmax − Vmin)'
    },

    compare: {
      before: {
        title: 'Было: обход раз в смену',
        points: [
          'Показания — раз в смену, в журнал',
          'Отклонение между обходами незаметно',
          'Диспетчер видит запись с задержкой',
          'Смарт-датчик: барьеры, кабели, проект, останов котла'
        ],
        cost: { value: '300 000', unit: '₽ на точку', note: 'замена на смарт-датчик, оценка команды' }
      },
      after: {
        title: 'Стало: GaugeVision AI',
        points: [
          'Камера снаружи контура: без врезки и останова',
          '3 обработки в секунду на камеру',
          'Пятизонные уставки, сирена, квитирование',
          'Архив SQLite и CSV с метками ISO 8601 UTC'
        ],
        cost: { value: '33 000', unit: '₽ на точку', note: 'ПО и камера «Рубитек», оценка команды' }
      },
      saving: { value: '−89 %', label: 'затрат на точку' },
      savingNote: 'Оценка команды: 26,7 млн ₽ на 100 приборах. Нужен пилот.',
      timeline: {
        caption: 'Иллюстративный сценарий',
        shiftHours: 12,
        rounds: [0, 12],
        deviationHour: 5,
        roundLabel: 'Обход',
        deviationLabel: 'Отклонение',
        beforeLabel: 'Было',
        afterLabel: 'Стало',
        beforeText: 'Отклонение заметят на следующем обходе',
        afterText: 'Отклонение видно на пульте сразу, уставки поднимают сигнал'
      }
    },

    architecture: {
      nodes: [
        { id: 'rtsp', label: 'RTSP / NVR', sub: 'IP-камеры, транспорт TCP', group: 'source' },
        { id: 'onvif', label: 'ONVIF', sub: 'камеры, найденные WS-Discovery', group: 'source' },
        { id: 'mjpeg', label: 'HTTP / MJPEG', sub: 'IP Webcam, DroidCam, ESP32-CAM', group: 'source' },
        { id: 'usb', label: 'USB', sub: 'камера сервера', group: 'source' },
        { id: 'phone', label: 'Смартфон', sub: 'браузер по QR-коду, WebP / JPEG по WSS', group: 'source' },
        { id: 'streamer', label: 'streamer.py', sub: 'захват в отдельных потоках, буфер 1 кадр, переподключение 1 → 15 с', group: 'server', file: 'app/streamer.py' },
        { id: 'vision', label: 'vision.py', sub: 'YOLOv8n CUDA FP16 / CPU, резерв OpenCV, EMA', group: 'server', file: 'app/vision.py' },
        { id: 'main', label: 'main.py', sub: 'FastAPI: REST, WebSocket, оркестрация камер', group: 'server', file: 'app/main.py' },
        { id: 'db', label: 'db.py', sub: 'aiosqlite, WAL → CSV', group: 'storage', file: 'app/db.py' },
        { id: 'dashboard', label: 'Пульт оператора', sub: 'static/, Chart.js локально', group: 'client', file: 'static/index.html' },
        { id: 'discovery', label: 'discovery.py', sub: 'ONVIF WS-Discovery, скан подсети /24', group: 'service', file: 'app/discovery.py' },
        { id: 'cert', label: 'cert_gen.py', sub: 'самоподписанный сертификат, HTTPS / WSS', group: 'service', file: 'app/cert_gen.py' }
      ],
      edges: [
        { from: 'rtsp', to: 'streamer', label: 'RTSP' },
        { from: 'mjpeg', to: 'streamer', label: 'HTTP' },
        { from: 'usb', to: 'streamer', label: 'USB' },
        { from: 'phone', to: 'streamer', label: 'WSS' },
        { from: 'onvif', to: 'discovery', label: 'WS-Discovery' },
        { from: 'discovery', to: 'main', label: 'найденные камеры' },
        { from: 'streamer', to: 'vision', label: 'последний кадр' },
        { from: 'vision', to: 'main', label: 'значение, θ, уверенность' },
        { from: 'main', to: 'dashboard', label: 'WSS и MJPEG' },
        { from: 'main', to: 'db', label: 'запись раз в 1 с' },
        { from: 'db', to: 'main', label: 'история и CSV' },
        { from: 'cert', to: 'main', label: 'TLS' }
      ],
      groups: {
        source: 'Источники видео',
        server: 'Сервер',
        storage: 'Архив',
        client: 'Пульт',
        service: 'Служебные модули'
      },
      stack: [
        { name: 'Python', version: '3.12' },
        { name: 'FastAPI', version: '≥ 0.110, async' },
        { name: 'Uvicorn', version: '≥ 0.29, только HTTPS' },
        { name: 'aiosqlite', version: '≥ 0.20' },
        { name: 'OpenCV', version: '≥ 4.9' },
        { name: 'NumPy', version: '≥ 1.26' },
        { name: 'Ultralytics YOLOv8n', version: '≥ 8.1' },
        { name: 'PyTorch', version: 'CUDA FP16 или CPU' },
        { name: 'cryptography', version: '≥ 42' },
        { name: 'qrcode', version: '≥ 7.4' },
        { name: 'Chart.js', version: 'локально, без CDN' },
        { name: 'HTML / CSS / JS', version: 'без фреймворков' }
      ],
      boundaryLabel: 'Локальный контур: HTTPS / WSS, без исходящих запросов в интернет'
    },

    /* «Выбрали → платим», источник — константа или файл из notes.md. */
    tradeoffs: [
      {
        id: 'yolo-nano',
        chose: 'YOLOv8n только для поиска корпуса',
        cost: 'Стрелку ищет геометрия OpenCV, не нейросеть',
        why: '7,2 мс/кадр на GPU, 29 мс на CPU. Класс Needle в модели есть, конвейер его не использует.',
        source: 'models/gauge_yolov8.pt · YOLO_CLASSES в app/config.py'
      },
      {
        id: 'affine',
        chose: 'Аффинная нормализация эллипса',
        cost: 'Проверено до ≈ 41°; сильные наклоны — в Roadmap 02',
        why: 'Эллипс по контуру находится на любом круглом приборе без разметки рисок.',
        source: 'roi_from_ellipse, normalize_dial в app/vision.py'
      },
      {
        id: 'ema',
        chose: 'EMA α = 0,25 гасит вибрацию',
        cost: 'Показание догоняет скачок за несколько кадров',
        why: 'Остаток × 0,75 за кадр: половина — за 3 кадра, ≈ 90 % — за 8. Оценка по формуле, не замер.',
        source: 'EMA_ALPHA = 0.25 в app/config.py'
      },
      {
        id: 'process-fps',
        chose: '3 обработки в секунду на камеру',
        cost: 'Мониторинг, не видеопоток: броски короче трети секунды не видны',
        why: '25 камер замерены при 4 к/с на камеру (100 к/с, GPU 72 %) — запас против 3 к/с.',
        source: 'PROCESS_FPS = 3.0 в app/config.py'
      },
      {
        id: 'confidence',
        chose: 'Порог уверенности 0,25 и удержание значения',
        cost: 'При грязном стекле пульт держит последнее достоверное значение; автоалерта нет',
        why: 'Недостоверные точки не попадают в архив, тренд не скачет. Автоалерт — в плане.',
        source: 'MIN_NEEDLE_CONFIDENCE = 0.25 в app/config.py'
      },
      {
        id: 'local',
        chose: 'Самоподписанный сертификат, локальный контур',
        cost: 'Браузер раз предупреждает о сертификате на каждом новом устройстве',
        why: 'Ни одного исходящего запроса в интернет. Без HTTPS нет доступа к камере смартфона.',
        source: 'app/cert_gen.py · run.py'
      },
      {
        id: 'sqlite',
        chose: 'SQLite и CSV вместо интеграции со SCADA',
        cost: 'Связи с АСУ ТП нет: Modbus TCP и OPC UA — в Roadmap 02',
        why: 'Запуск без проекта интеграции: архив и выгрузка в Excel работают сразу.',
        source: 'app/db.py'
      }
    ],

    /* Ограничения среды: README «Ограничения», ответы уточнены по коду (notes.md §4). */
    limits: [
      {
        id: 'glare',
        condition: 'Блики, тени, копоть',
        risk: 'Ошибки выделения шкалы и стрелки',
        response: 'CLAHE при поиске циферблата; Black-Hat / Top-Hat 31×31; Otsu по кольцу; фонарь смартфона',
        note: 'Отдельной обработки копоти в коде нет',
        status: 'done'
      },
      {
        id: 'vibration',
        condition: 'Вибрация',
        risk: 'Дрожание показаний',
        response: 'EMA α = 0,25; смещение ROI меньше 5 % оси игнорируется',
        status: 'done'
      },
      {
        id: 'angle',
        condition: 'Съёмка под углом',
        risk: 'Искажение геометрии шкалы',
        response: 'Аффинная нормализация в круг 640 px; на стенде — до ≈ 41°',
        note: 'Сильные наклоны — в Roadmap 02',
        status: 'partial'
      },
      {
        id: 'dirt',
        condition: 'Загрязнение стекла',
        risk: 'Падение достоверности',
        response: 'Порог 0,25: недостоверный кадр не пишется; после 3 промахов — новый поиск',
        note: 'Автоалерт — в плане',
        status: 'partial'
      },
      {
        id: 'network',
        condition: 'Обрыв сети или камеры',
        risk: 'Потеря телеметрии',
        response: 'Переподключение 1 → 15 с, после 8 неудач — «офлайн». Смартфон без кадров: 6 с — «переподключение», 30 с — «офлайн»',
        status: 'done'
      }
    ],

    untested: {
      title: 'Не проверено в поле',
      text: 'Нелинейные шкалы, многострелочные приборы, работа на станции. Испытания — только стенд.'
    },

    roadmap: [
      { index: '01', title: 'MVP', status: 'done',
        items: ['6 классов приборов', 'YOLOv8n на CUDA', 'смартфон по QR-коду', 'уставки, сирена и экспорт в CSV'] },
      { index: '02', title: 'Связь со SCADA', status: 'planned',
        items: ['Modbus TCP и OPC UA', 'полевой пилот на станции', 'полная гомография', 'нелинейные шкалы и многоточечная калибровка'] },
      { index: '03', title: 'Масштаб цеха', status: 'planned',
        items: ['PTZ-камеры с пресетами обхода: одна камера на десятки приборов', 'нательные регистраторы обходчиков'] }
    ],

    /* Финал: одна главная ссылка — репозиторий; лицензия — в футере. Других контактов нет (PRODUCT.md). */
    contact: {
      title: 'Код и README — на GitHub',
      backdrop: 'assets/img/boiler-hall.jpg',
      links: [
        { id: 'repo', label: 'Код на GitHub', href: REPO, primary: true },
        { id: 'license', label: 'Проприетарная лицензия', href: REPO + '/blob/main/LICENSE' }
      ]
    },

    /* Общие подписи интерфейса, чтобы компоненты не хардкодили тексты. */
    labels: {
      status: { done: 'реализовано', partial: 'частично', planned: 'в плане' },
      kind: { measured: 'замер', calculated: 'расчёт' },
      filterAll: 'Все',
      tradeoffsTitle: 'Компромиссы',
      tradeoffsLead: 'Выбрали → платим',
      limitsTitle: 'Ограничения среды цеха',
      chose: 'Выбрали',
      cost: 'Платим',
      why: 'Почему так',
      source: 'Где в коде',
      risk: 'Риск',
      response: 'Ответ в коде',
      roadmapTitle: 'Roadmap',
      stackTitle: 'Стек',
      newTab: 'откроется в новой вкладке'
    }
  };

  /* ---------- типограф ---------- */
  var NBSP = '\u00A0';
  var UNIT_RE = new RegExp(
    '(\\d) (?=(?:%|мс\\/кадр|мс|с|ч|к\\/с|px|МиБ|КБ|GB|МПа|кПа|бар|₽|тыс\\.|млн|эпох|сцен|кадр|кадра|кадров|камер|камеры|' +
    'сообщений|суток|месяцев|приборах|потока|°)(?![A-Za-zА-Яа-яЁё]))',
    'g'
  );
  var SKIP_KEYS = { id: 1, src: 1, srcMobile: 1, poster: 1, backdrop: 1, href: 1, file: 1, source: 1, formula: 1, roi: 1, repoUrl: 1, licenseUrl: 1 };

  function typo(s) {
    return s
      .replace(UNIT_RE, '$1' + NBSP)
      .replace(/ — /g, NBSP + '— ')
      .replace(/(млн|тыс\.) ₽/g, '$1' + NBSP + '₽')
      .replace(/(№|≈|±|≤|≥|×) (?=\d)/g, '$1' + NBSP)
      .replace(/(\d) (\d{3})(?!\d)/g, '$1' + NBSP + '$2');
  }
  function deep(value, key) {
    if (typeof value === 'string') return SKIP_KEYS[key] ? value : typo(value);
    if (Array.isArray(value)) return value.map(function (v) { return deep(v, key); });
    if (value && typeof value === 'object') {
      var out = {};
      Object.keys(value).forEach(function (k) { out[k] = deep(value[k], k); });
      return out;
    }
    return value;
  }

  GV.content = deep(content, '');
})();
