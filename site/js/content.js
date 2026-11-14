/*
 * GV.content — единственный источник фактов лендинга GaugeVision AI.
 * Чистые данные, без DOM. Источники: README.md, PRODUCT.md, код в app/ и notes.md
 * (где README и код расходятся, текст написан по коду — interfaces.md, правило 1a).
 * Все числа в metrics, pipeline[].params, limits, compare, calibration, ema
 * сверяются с источниками командой `node site/tests/check.js`.
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
      tagline: 'Компьютерное зрение для аналогового контура ТЭЦ',
      repoUrl: REPO,
      licenseUrl: REPO + '/blob/main/LICENSE',
      pdfUrl: REPO + '/blob/main/GuageVision%20AI.pdf',
      authorUrl: 'https://github.com/EGRNEGR',
      author: 'EGRNEGR',
      track: 'Трек №3 «Умное производство: ИИ-аналитика видеоданных для повышения эффективности»',
      trackShort: 'Трек №3 · Умное производство',
      copyright: '© 2026 EGRNEGR. Все права защищены. Код опубликован только для ознакомления',
      version: '1.0.0'
    },

    /* Подписи и якоря семи экранов — одинаковы во всех вариантах. */
    sections: [
      { id: 'hero', index: '01', nav: 'Суть', title: 'Стрелочные приборы ТЭЦ — на пульте оператора' },
      { id: 'metrics', index: '02', nav: 'Замеры', title: 'Подтверждённые замеры',
        lead: 'Каждая цифра взята из README проекта, рядом — условия замера. Стенд подписан как стенд, расчёт — как расчёт.' },
      { id: 'pipeline', index: '03', nav: 'Конвейер', title: 'Конвейер: от кадра до значения в МПа',
        lead: 'Девять этапов, как они написаны в коде. Выберите этап — откроются параметры, формула и файл.' },
      { id: 'compare', index: '04', nav: 'Было → Стало', title: 'Было → Стало',
        lead: 'Обход раз в смену против камеры, которая смотрит на прибор постоянно.' },
      { id: 'architecture', index: '05', nav: 'Архитектура', title: 'Архитектура и стек',
        lead: 'Один сервер в локальной сети: источники видео, конвейер зрения, пульт и архив.' },
      { id: 'limits', index: '06', nav: 'Ограничения', title: 'Компромиссы и ограничения',
        lead: 'Что выбрано, чем за это заплачено и что пока не проверено в поле.' },
      { id: 'contact', index: '07', nav: 'GitHub', title: 'Код, README и презентация — на GitHub' }
    ],

    hero: {
      eyebrow: 'Трек №3 · Умное производство: ИИ-аналитика видеоданных',
      title: 'Стрелочные приборы ТЭЦ — на пульте оператора',
      lead: 'GaugeVision AI снимает показания манометров, тягомеров, уровнемеров и термометров КИПиА обычной камерой: без врезки в трубопроводы, без кабельных трасс и без останова оборудования. Всё работает в локальном контуре, без интернета.',
      chain: {
        before: ['Прибор', 'Обходчик и журнал', 'Диспетчер'],
        after: ['Прибор', 'Камера', 'Пульт оператора']
      },
      ctaPrimary: { label: 'Код на GitHub', href: REPO },
      ctaSecondary: { label: 'Смотреть демо', target: '#hero-stage' },
      stage: {
        rawLabel: 'Сырой кадр с камеры',
        recognizedLabel: 'Распознавание и снятие показаний',
        caption: 'Стенд, синтетический прибор. Кадр и карточка сняты в разные моменты',
        captionSchematic: 'Схема, синтетический прибор. Угол, уверенность и значение — со скриншота пульта',
        raw: {
          src: 'assets/smartphone-client.png',
          alt: 'Кадр со смартфона: тягонапоромер топки котла №1 в прицельном круге клиента захвата, без распознавания',
          crop: { x: 0.12, y: 0.228, w: 0.76, h: 0.394 }
        },
        recognized: {
          src: 'assets/dashboard-real.png',
          alt: 'Карточка того же прибора на пульте оператора: найденный циферблат, стрелка, θ = 275,2°, уверенность 0,92, значение 4,74 кПа',
          crop: { x: 0.66, y: 0.217, w: 0.307, h: 0.451 }
        },
        readout: {
          device: 'Тягонапоромер топки котла №1',
          value: 4.74,
          unit: 'кПа',
          theta: 275.2,
          conf: 0.92,
          roi: 'yolo+ellipse',
          latencyMs: 71.3
        },
        labels: {
          device: 'Прибор',
          value: 'Значение',
          theta: 'Угол стрелки θ',
          conf: 'Уверенность',
          roi: 'Источник ROI',
          latency: 'Обработка кадра'
        }
      }
    },

    coverage: {
      classes: 6,
      units: 17,
      types: [
        { id: 'pressure', label: 'Давление', devices: 'манометр, вакуумметр, мановакуумметр', units: 'МПа, бар, кгс/см², кПа' },
        { id: 'temperature', label: 'Температура', devices: 'манометрический и биметаллический термометр', units: '°C' },
        { id: 'draft', label: 'Тяга и разрежение', devices: 'тягомер, напоромер, тягонапоромер', units: 'кПа, Па, кгс/м²' },
        { id: 'level', label: 'Уровень', devices: 'стрелочный уровнемер', units: '%, мм, м' },
        { id: 'electrical', label: 'Электрические щитовые', devices: 'амперметр, вольтметр, ваттметр', units: 'А, кА, В, кВ, МВт' },
        { id: 'flow', label: 'Расход', devices: 'дифманометр-расходомер', units: 'т/ч, м³/ч' }
      ],
      sources: ['IP-камеры RTSP и NVR', 'ONVIF', 'HTTP / MJPEG', 'USB-камеры', 'смартфон по QR-коду без установки приложения']
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
        label: '100 камер', condition: 'расчёт: RTX 4090 24 GB или 2 × RTX 4070 Ti Super, узел ≈ 580–680 тыс. ₽', kind: 'calculated' }
    ],
    metricsNote: 'Замеры приведены по README проекта: стенд — синтетические приборы с тёмными, светлыми и красными стрелками, наклон камеры ≈ 41°, посторонние объекты в кадре и шум. Скриптов и данных для воспроизведения замеров в репозитории нет.',

    /* Конвейер по коду: notes.md §1. */
    pipeline: [
      {
        id: 'capture', index: '00', title: 'Захват',
        short: 'Последний кадр каждой камеры, буфер 1 кадр',
        what: 'RTSP, HTTP/MJPEG и USB читает CaptureWorker в отдельном потоке, смартфон присылает кадры WebP или JPEG по WSS. Буфер драйвера — 1 кадр, а FrameBroker хранит только последний кадр камеры, поэтому анализ не стоит в очереди из старых кадров. Цикл обработки берёт новый кадр 3 раза в секунду и считает его в пуле из 2 потоков, не блокируя сервер.',
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
        what: 'Детектор YOLOv8n ищет корпус прибора, затем OpenCV уточняет границу циферблата эллипсом по контуру. Если центр эллипса лежит внутри бокса YOLO ± 15 %, берётся эллипс — источник yolo+ellipse. Без весов модели или пакета ultralytics, а также когда YOLO прибор не нашла, работает резервный путь: эллипс по контуру, HoughCircles его только подтверждает.',
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
        what: 'Циферблат, снятый под углом, выглядит эллипсом. Аффинная матрица растягивает его вдоль осей эллипса в круг 640 × 640 px, ориентация шкалы при этом сохраняется. На стенде проверены наклоны камеры до ≈ 41°. Это аффинная коррекция: полной гомографии в коде нет, она в Roadmap 02.',
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
        what: 'При поиске циферблата контраст выравнивает CLAHE. Для стрелки строятся три маски: Black-Hat для тёмной стрелки на светлом фоне, Top-Hat для светлой на тёмном и Top-Hat по насыщенности для цветных стрелок. Морфологические «шляпы» вычитают фон шкалы, поэтому блики и тени меньше влияют на результат. Порог Otsu считается только по кольцу циферблата.',
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
        what: 'Для каждой маски считается радиальный момент: гистограмма направлений по 1° на кольце, где нет рисок и цифр. Побеждает маска с наибольшей уверенностью. HoughLinesP ищет отрезок через ось; если его угол расходится с моментом не больше чем на 12°, углы усредняются с весами. Иначе остаётся результат момента с уверенностью × 0,9.',
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
        what: 'Угол стрелки переводится в значение линейной двухточечной калибровкой по часовой (CW) или против (CCW). Типовая шкала — 270°: θmin = 135°, θmax = 45°. Если стрелка в «мёртвой зоне» шкалы, угол относится к ближайшему краю, а значение может выйти за шкалу не больше чем на 5 % диапазона.',
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
        what: 'EMA-фильтр гасит вибрацию стрелки. Кадр с уверенностью ниже 0,25 считается недостоверным: он не пишется в архив, а пульт удерживает последнее значение. После 3 промахов подряд или каждые 15 кадров циферблат ищется заново; если центр сместился меньше чем на 5 % оси, область остаётся прежней.',
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
        what: 'Сглаженное значение сравнивается с уставками. V ≤ LL или V ≥ HH — авария, V ≤ L или V ≥ H — предупреждение, между ними — норма. Порядок LL ≤ L ≤ H ≤ HH проверяется при сохранении. Пятизонная модель следует ISA-18.2 и ГОСТ Р МЭК 62682; на пульте авария включает сирену и квитирование.',
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
        what: 'Каждое обработанное показание уходит на все открытые пульты по WebSocket, у каждого пульта своя очередь, старые сообщения при переполнении отбрасываются. В SQLite пишется только достоверное сглаженное значение, не чаще раза в секунду на камеру. Архив выгружается в CSV с метками ISO 8601 UTC.',
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
      formula: 'V = Vmin + ((θ − θmin) mod 360) / span · (Vmax − Vmin)',
      zones: [
        { id: 'LL', label: 'LL', status: 'alert', text: 'Авария: V ≤ LL' },
        { id: 'L', label: 'L', status: 'warning', text: 'Предупреждение: V ≤ L' },
        { id: 'NORMA', label: 'НОРМА', status: 'normal', text: 'Норма: L < V < H' },
        { id: 'H', label: 'H', status: 'warning', text: 'Предупреждение: V ≥ H' },
        { id: 'HH', label: 'HH', status: 'alert', text: 'Авария: V ≥ HH' }
      ],
      sliderLabel: 'Угол стрелки θ',
      caption: 'Формула из app/vision.py: шкала 0–10 МПа, θmin = 135°, θmax = 45°, по часовой. Уставки — как у манометра на скриншоте пульта.'
    },

    ema: {
      alpha: 0.25,
      minConfidence: 0.25,
      formula: 'V̄ₜ = α · Vₜ + (1 − α) · V̄ₜ₋₁',
      caption: 'Симуляция формулы, не запись с объекта',
      toggleLabel: 'Вибрация',
      legendRaw: 'Сырой отсчёт',
      legendEma: 'EMA, α = 0,25'
    },

    compare: {
      before: {
        title: 'Было: обход раз в смену',
        points: [
          'Обходчик снимает показания раз в смену и пишет их в журнал',
          'Отклонение между обходами остаётся незамеченным',
          'Диспетчер получает запись из журнала с задержкой',
          'Смарт-датчик требует искробезопасных барьеров, кабельных трасс, проекта и планового останова котлоагрегата'
        ],
        cost: { value: '300 000', unit: '₽ на точку', note: 'замена на смарт-датчик, оценка команды' }
      },
      after: {
        title: 'Стало: GaugeVision AI',
        points: [
          'Камера снаружи технологического контура: без врезки, кабелей и останова',
          'Каждая камера обрабатывается 3 раза в секунду',
          'Пятизонные уставки, сирена и квитирование аварии на всех открытых пультах',
          'Архив в SQLite и выгрузка в CSV с метками ISO 8601 UTC'
        ],
        cost: { value: '33 000', unit: '₽ на точку', note: 'GaugeVision AI и камера «Рубитек» (RTSP / ONVIF, PoE), оценка команды' }
      },
      saving: { value: '−89 %', label: 'затрат на точку' },
      savingNote: 'Затраты на точку ниже на 89 %, на 100 приборах — 26,7 млн ₽ экономии, окупаемость на один турбогенератор — менее 2 месяцев. Это оценка команды, цифры требуют подтверждения на пилоте.',
      pair: {
        rawLabel: 'Сырой кадр: стрелка на шкале',
        recognizedLabel: 'На пульте: значение, статус и тренд'
      },
      timeline: {
        caption: 'Иллюстративный сценарий',
        shiftHours: 12,
        rounds: [0, 12],
        deviationHour: 5,
        roundLabel: 'Обход',
        deviationLabel: 'Отклонение',
        beforeLabel: 'Было',
        afterLabel: 'Стало',
        beforeText: 'Отклонение заметят только на следующем обходе, а диспетчер узнает о нём из журнала',
        afterText: 'Отклонение видно на пульте сразу и поднимает сигнализацию по уставкам'
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
        { id: 'cert', label: 'cert_gen.py', sub: 'самоподписанный X.509, HTTPS / WSS', group: 'service', file: 'app/cert_gen.py' }
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
        chose: 'YOLOv8n (nano) только для поиска корпуса',
        cost: 'Лёгкая модель не ищет стрелку: стрелку находит геометрия OpenCV',
        why: '7,2 мс на кадр на GPU и работа без видеокарты (29 мс на CPU) важнее, чем нейросеть для стрелки. Класс Needle в модели есть, но конвейер его не использует.',
        source: 'models/gauge_yolov8.pt · YOLO_CLASSES в app/config.py'
      },
      {
        id: 'affine',
        chose: 'Аффинная нормализация эллипса',
        cost: 'Проверено на стенде до ≈ 41°, полной гомографии нет',
        why: 'Эллипс по контуру находится на любом круглом приборе без разметки рисок. Гомография нужна для сильных наклонов и запланирована в Roadmap 02.',
        source: 'roi_from_ellipse, normalize_dial в app/vision.py'
      },
      {
        id: 'ema',
        chose: 'EMA α = 0,25 гасит вибрацию',
        cost: 'Показание догоняет резкий скачок за несколько кадров',
        why: 'После скачка остаток ошибки на каждом кадре умножается на 0,75: больше половины скачка проходит за 3 кадра (≈ 1 с при 3 к/с), ≈ 90 % — за 8 кадров (≈ 2,7 с). Это оценка по формуле, не замер.',
        source: 'EMA_ALPHA = 0.25 в app/config.py'
      },
      {
        id: 'process-fps',
        chose: '3 обработки в секунду на камеру',
        cost: 'Это мониторинг, а не видеопоток: броски короче трети секунды между кадрами не видны',
        why: 'Нагрузка остаётся предсказуемой: на стенде команды 25 камер на одном ноутбучном GPU замерены при 4 к/с на камеру (100 к/с, загрузка GPU 72 %), то есть с запасом против рабочих 3 к/с.',
        source: 'PROCESS_FPS = 3.0 в app/config.py'
      },
      {
        id: 'confidence',
        chose: 'Порог уверенности 0,25 и удержание значения',
        cost: 'При загрязнении стекла пульт показывает последнее достоверное значение, а не потерю; автоалерта нет',
        why: 'В архив не попадают недостоверные точки, а тренд не скачет от ложных отсчётов. Автоалерт о потере достоверности — в плане.',
        source: 'MIN_NEEDLE_CONFIDENCE = 0.25 в app/config.py'
      },
      {
        id: 'local',
        chose: 'Самоподписанный сертификат и полностью локальный контур',
        cost: 'Браузер один раз предупреждает о сертификате на каждом новом устройстве',
        why: 'Ни одного исходящего запроса в интернет. Без HTTPS браузер не дал бы доступ к камере смартфона.',
        source: 'app/cert_gen.py · run.py'
      },
      {
        id: 'sqlite',
        chose: 'SQLite и CSV вместо интеграции со SCADA',
        cost: 'Связи с АСУ ТП пока нет: Modbus TCP и OPC UA — в Roadmap 02',
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
        response: 'CLAHE (clip 3,0, сетка 8×8) при поиске циферблата; Black-Hat / Top-Hat с ядром 31×31 и маска по насыщенности вычитают фон; порог Otsu по кольцу циферблата; выбор маски по уверенности; фонарь смартфона через Torch API',
        note: 'Отдельной обработки копоти в коде нет',
        status: 'done'
      },
      {
        id: 'vibration',
        condition: 'Вибрация',
        risk: 'Дрожание показаний',
        response: 'EMA с α = 0,25; гистерезис области циферблата: смещение меньше 5 % оси не сбрасывает ROI',
        status: 'done'
      },
      {
        id: 'angle',
        condition: 'Съёмка под углом',
        risk: 'Искажение геометрии шкалы',
        response: 'Эллипс по контуру и аффинная нормализация в круг 640 px; на стенде — до ≈ 41°',
        note: 'Полная гомография — в плане',
        status: 'partial'
      },
      {
        id: 'dirt',
        condition: 'Загрязнение стекла',
        risk: 'Падение достоверности',
        response: 'Порог уверенности 0,25: недостоверный кадр не пишется в архив, удерживается последнее значение; после 3 промахов подряд циферблат ищется заново',
        note: 'Автоалерт — в плане',
        status: 'partial'
      },
      {
        id: 'network',
        condition: 'Обрыв сети или камеры',
        risk: 'Потеря телеметрии',
        response: 'Переподключение 1 → 2 → 4 → 8 → 15 с; после 8 неудач подряд — статус «офлайн», попытки продолжаются. Смартфон без кадров: через 6 с — «переподключение», через 30 с — «офлайн»',
        status: 'done'
      }
    ],

    untested: {
      title: 'Не проверено в поле',
      text: 'Нелинейные шкалы, многострелочные приборы, длительная работа на станции. Испытания — стенд и синтетические сцены.'
    },

    roadmap: [
      { index: '01', title: 'MVP', status: 'done',
        items: ['6 классов приборов', 'YOLOv8n на CUDA', 'смартфон по QR-коду', 'уставки, сирена и экспорт в CSV'] },
      { index: '02', title: 'Связь со SCADA', status: 'planned',
        items: ['Modbus TCP и OPC UA', 'полевой пилот на станции', 'полная гомография', 'нелинейные шкалы и многоточечная калибровка'] },
      { index: '03', title: 'Масштаб цеха', status: 'planned',
        items: ['PTZ-камеры с пресетами обхода: одна камера на десятки приборов', 'нательные регистраторы обходчиков'] }
    ],

    contact: {
      title: 'Код, README и презентация — на GitHub',
      text: 'В репозитории — исходный код сервиса, README с метриками и условиями замера и презентация проекта. Код опубликован только для ознакомления: использование и запуск — с письменного разрешения правообладателя.',
      links: [
        { id: 'repo', label: 'Код на GitHub', href: REPO, primary: true },
        { id: 'pdf', label: 'Презентация, PDF', href: REPO + '/blob/main/GuageVision%20AI.pdf' },
        { id: 'license', label: 'Лицензия', href: REPO + '/blob/main/LICENSE' },
        { id: 'author', label: 'Автор — EGRNEGR на GitHub', href: 'https://github.com/EGRNEGR' }
      ]
    },

    /* Общие подписи интерфейса, чтобы компоненты не хардкодили тексты. */
    labels: {
      status: { done: 'реализовано', partial: 'частично', planned: 'в плане' },
      kind: { measured: 'замер', calculated: 'расчёт' },
      level: { normal: 'Норма', warning: 'Предупреждение', alert: 'Авария' },
      filterAll: 'Все',
      tradeoffsTitle: 'Компромиссы',
      tradeoffsLead: 'Выбрали → платим',
      limitsTitle: 'Ограничения среды цеха',
      chose: 'Выбрали',
      cost: 'Платим',
      why: 'Почему так',
      source: 'Где в коде',
      condition: 'Условие',
      risk: 'Риск',
      response: 'Ответ в коде',
      params: 'Параметры',
      formula: 'Формула',
      file: 'Файл',
      aspect: 'Аспект',
      roadmapTitle: 'Roadmap',
      stackTitle: 'Стек',
      units: { mpa: 'МПа', bar: 'бар' },
      license: 'Лицензия: все права защищены'
    },

    /*
     * Значения, видимые только на скриншотах репозитория (не замеры).
     * check.js их не сверяет с README. Источники: site/assets/dashboard-real.png,
     * docs/images/calibration.png, docs/images/phone_capture.png.
     */
    screenshotFacts: {
      dashboard: {
        header: 'EMA α=0.25 · YOLOv8 · NVIDIA GeForce RTX 5060 Laptop GPU',
        alarm: 'CRITICAL (1): «Манометр питательного узла котла №2» = 9.40 МПа',
        devices: [
          { name: 'Манометр питательного узла котла №2', value: 9.40, unit: 'МПа', level: 'alert', link: 'В СЕТИ',
            theta: 28.8, conf: 0.92, processMs: 57.9, roi: 'yolo+ellipse', setpoints: { LL: 1, L: 2, H: 8, HH: 9 } },
          { name: 'Термометр пара за котлом', value: 455, unit: '°C', level: 'normal', link: 'В СЕТИ',
            theta: 340.0, conf: 0.92, processMs: 60, roi: 'yolo+ellipse', setpoints: { LL: 300, L: 400, H: 520, HH: 560 } },
          { name: 'Тягонапоромер топки котла №1', value: 4.74, unit: 'кПа', level: 'normal', link: 'ПЕРЕПОДКЛЮЧЕНИЕ',
            theta: 275.2, conf: 0.92, processMs: 71.3, roi: 'yolo+ellipse', setpoints: { LL: 1, L: 2, H: 7, HH: 8.5 } }
        ]
      },
      calibrationWindow: {
        source: 'Смартфон (WSS, по QR-коду)',
        vMin: 0, thetaMin: 135.0, vMax: 10, thetaMax: 45.0, direction: 'CW',
        theta: 253.4, conf: 0.92,
        computedValue: 4.39,
        computedNote: 'по формуле калибровки: θ = 253,4° → 4,39 МПа на шкале 0–10'
      },
      phone: {
        device: 'Тягонапоромер топки котла №1',
        value: 4.42, unit: 'кПа', fps: 3.9, frameKb: 121, format: 'WebP', resolution: '1280×720', status: 'В ЭФИРЕ'
      }
    }
  };

  /* ---------- типограф ---------- */
  var NBSP = '\u00A0';
  var UNIT_RE = new RegExp(
    '(\\d) (?=(?:%|мс\\/кадр|мс|с|ч|к\\/с|px|МиБ|КБ|GB|МПа|кПа|бар|₽|тыс\\.|млн|эпох|сцен|кадр|кадра|кадров|камер|камеры|' +
    'сообщений|суток|месяцев|приборах|потока|°)(?![A-Za-zА-Яа-яЁё]))',
    'g'
  );
  var SKIP_KEYS = { id: 1, src: 1, href: 1, file: 1, source: 1, formula: 1, roi: 1, repoUrl: 1, licenseUrl: 1, pdfUrl: 1, authorUrl: 1 };

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
