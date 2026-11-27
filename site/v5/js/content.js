/*
 * GV.content — единственный источник фактов и текстов сайта GaugeVision AI 3.0 в дизайне «Журнал обходчика» (site/v5).
 * Каждая количественная метрика взята из реестра reports/website_redesign/PRODUCT_CLAIMS_REGISTER.md и
 * ссылается на неизменяемый тег v3.0.0 (коммит 0273436). Без DOM, классический скрипт.
 * В конце файла строки проходят типограф: неразрывный пробел перед тире, единицами и после коротких предлогов.
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var GV = (root.GV = root.GV || {});

  var REPO = 'https://github.com/EGRNEGR/GaugeVisionAI';
  var TAG = REPO + '/blob/v3.0.0/';
  var FI = TAG + 'reports/final_integration/';
  var NG = TAG + 'reports/next_generation/';

  var src = {
    acceptance: { label: 'FINAL_ACCEPTANCE_REPORT', href: FI + 'FINAL_ACCEPTANCE_REPORT.md' },
    summary: { label: 'EXECUTIVE_SUMMARY', href: FI + 'EXECUTIVE_SUMMARY.md' },
    release: { label: 'RELEASE_NOTES', href: FI + 'RELEASE_NOTES.md' },
    limits: { label: 'KNOWN_LIMITATIONS', href: FI + 'KNOWN_LIMITATIONS.md' },
    tests: { label: 'TEST_RESULTS', href: FI + 'TEST_RESULTS.md' },
    e2e: { label: 'E2E_INTEGRATION_REPORT', href: FI + 'E2E_INTEGRATION_REPORT.md' },
    soak: { label: 'SOAK_TEST_REPORT', href: FI + 'SOAK_TEST_REPORT.md' },
    scada: { label: 'SCADA_REVALIDATION_REPORT', href: FI + 'SCADA_REVALIDATION_REPORT.md' },
    offline: { label: 'OFFLINE_DEPLOYMENT_REPORT', href: FI + 'OFFLINE_DEPLOYMENT_REPORT.md' },
    perf: { label: 'PERFORMANCE_REPORT', href: FI + 'PERFORMANCE_REPORT.md' },
    security: { label: 'SECURITY_FINAL_REPORT', href: FI + 'SECURITY_FINAL_REPORT.md' },
    rtm: { label: 'RTM_ORIGINAL.csv', href: FI + 'RTM_ORIGINAL.csv' },
    rtmNg: { label: 'RTM_NEXT_GEN.csv', href: FI + 'RTM_NEXT_GEN.csv' },
    arch: { label: 'ARCHITECTURE_FINAL', href: FI + 'ARCHITECTURE_FINAL.md' },
    multigauge: { label: 'MULTI_GAUGE_VALIDATION', href: NG + 'MULTI_GAUGE_VALIDATION.md' },
    predictive: { label: 'PREDICTIVE_REAL_DATA_VALIDATION', href: NG + 'PREDICTIVE_REAL_DATA_VALIDATION.md' },
    ilp: { label: 'ILP_INDEPENDENT_VERIFICATION', href: NG + 'ILP_INDEPENDENT_VERIFICATION.md' },
    ilpScale: { label: 'ILP_SCALABILITY_REPORT', href: NG + 'ILP_SCALABILITY_REPORT.md' },
    autocal: { label: 'AUTO_CALIBRATION_REPORT', href: NG + 'AUTO_CALIBRATION_REPORT.md' },
    cv: { label: 'CV_VALIDATION_REPORT', href: TAG + 'reports/industrial_validation/CV_VALIDATION_REPORT.md' },
    demo: { label: 'DEMO_DEFENSE_GUIDE', href: TAG + 'docs/DEMO_DEFENSE_GUIDE.md' },
    readme: { label: 'README', href: TAG + 'README.md' },
    catalog: { label: 'app/spec_generator.py', href: TAG + 'app/spec_generator.py' },
    economics: { label: 'app/config.py', href: TAG + 'app/config.py' },
    optimizer: { label: 'app/modernization_optimizer.py', href: TAG + 'app/modernization_optimizer.py' },
    vision: { label: 'app/vision.py', href: TAG + 'app/vision.py' }
  };

  /* Восемь приборов синтетического щита пятого сквозного испытания (E2E прогон 5). */
  var panel = [
    { code: 'PI-101', name: 'Давление пара перед клапаном', unit: 'МПа', min: 0, max: 16, value: 9.16, kind: 'pressure' },
    { code: 'PI-102', name: 'Давление питательной воды', unit: 'МПа', min: 0, max: 1.6, value: 1.21, kind: 'pressure', hero: true },
    { code: 'PI-103', name: 'Разрежение в топке', unit: 'кПа', min: 0, max: 100, value: 47.9, kind: 'draft' },
    { code: 'PI-104', name: 'Температура масла', unit: '°C', min: 0, max: 150, value: 38.3, kind: 'temperature' },
    { code: 'PI-105', name: 'Давление в коллекторе', unit: 'МПа', min: 0, max: 2.5, value: 1.67, kind: 'pressure' },
    { code: 'PI-106', name: 'Напор дутьевого воздуха', unit: 'кПа', min: 0, max: 250, value: 140.9, kind: 'draft' },
    { code: 'PI-107', name: 'Температура перегретого пара', unit: '°C', min: 0, max: 300, value: 144.3, kind: 'temperature' },
    { code: 'PI-108', name: 'Давление в барабане', unit: 'МПа', min: 0, max: 6, value: 4.77, kind: 'pressure' }
  ];

  /* Прогноз пятого прогона: параметры модели и интервалы — E2E_INTEGRATION_REPORT, шаги 9–10. */
  var forecast = {
    start: 1.178,
    now: 1.211,
    slopeTrue: 0.0155,
    slopeModel: 0.01504,
    r2: 0.9962,
    eta: 13.18,
    etaTrue: 12.7,
    ciLo: 12.01,
    ciHi: 14.59,
    pi80Half60: 0.045,
    pi95Half60: 0.0826,
    warn: 1.2,
    alert: 1.408
  };

  /* Стендовый каталог и условный парк для оптимизатора модернизации (app/spec_generator.py, app/modernization_optimizer.py). */
  var catalog = {
    pressure: { label: 'Цифровой преобразователь давления', unit: 68000, install: 24000, risk: 195000, signal: '4–20 мА + HART', accuracy: 'не хуже ±0,075 %', ip: 'не ниже IP66' },
    draft: { label: 'Цифровой преобразователь давления и разрежения', unit: 62000, install: 25000, risk: 170000, signal: '4–20 мА + HART / RS-485 Modbus RTU', accuracy: 'не хуже ±0,15 %', ip: 'не ниже IP65' },
    temperature: { label: 'Цифровой термопреобразователь Pt100, класс A', unit: 54000, install: 22000, risk: 220000, signal: '4–20 мА + HART / RS-485 Modbus RTU', accuracy: 'не хуже ±0,15 °C', ip: 'не ниже IP65' }
  };

  var fleet = [
    { code: 'PI-101', hs: 62, crit: 1.3, prob: 0.15, warnP: 0.3, anom: 22, trips: 1, ex: false },
    { code: 'PI-102', hs: 58, crit: 1.3, prob: 0.85, warnP: 1, anom: 40, trips: 2, ex: false, mandatory: true },
    { code: 'PI-103', hs: 88, crit: 1.0, prob: 0, warnP: 0.05, anom: 6, trips: 0, ex: false },
    { code: 'PI-104', hs: 66, crit: 1.15, prob: 0.2, warnP: 0.35, anom: 28, trips: 1, ex: false },
    { code: 'PI-105', hs: 81, crit: 1.0, prob: 0.05, warnP: 0.15, anom: 12, trips: 0, ex: false },
    { code: 'PI-106', hs: 90, crit: 1.0, prob: 0, warnP: 0, anom: 4, trips: 0, ex: false },
    { code: 'PI-107', hs: 55, crit: 1.3, prob: 0.3, warnP: 0.6, anom: 35, trips: 2, ex: false },
    { code: 'PI-108', hs: 77, crit: 1.15, prob: 0.1, warnP: 0.2, anom: 15, trips: 0, ex: true }
  ];

  var content = {
    src: src,
    panel: panel,
    forecast: forecast,
    catalog: catalog,
    fleet: fleet,

    meta: {
      name: 'GaugeVision AI 3.0',
      version: '3.0.0',
      commit: '0273436',
      repoUrl: REPO,
      repoLabel: 'github.com/EGRNEGR/GaugeVisionAI',
      tagUrl: REPO + '/releases/tag/v3.0.0',
      branchUrl: REPO + '/tree/GaugeVision-3.0',
      readmeUrl: src.readme.href,
      reportUrl: src.acceptance.href,
      pilotUrl: REPO + '/issues/new?title=' + encodeURIComponent('Пилот GaugeVision AI 3.0: ') +
        '&body=' + encodeURIComponent('Объект и тип приборов:\nКоличество точек:\nЦель пилота:\n'),
      licenseUrl: REPO + '/blob/v3.0.0/LICENSE',
      form: 'Журнал обхода и показаний КИП, стабильная версия v3.0.0',
      copyright: '© 2026 EGRNEGR. Все права защищены. Код опубликован только для ознакомления',
      legal: 'Инженерный прототип информационной системы. Не является средством измерений утверждённого типа и не является системой противоаварийной защиты.'
    },

    /* 11 листов сменного журнала GaugeVision AI 3.0 */
    sections: [
      { id: 'hero', index: '01', nav: 'Журнал', form: 'Смена идёт' },
      { id: 'compare', index: '02', nav: 'Смена', form: 'Было и стало',
        title: 'Двенадцать часов против трети секунды',
        lede: 'Приборы уже стоят в цеху, а показания снимают при обходе: камера даёт поток данных без врезки и останова.',
        accent: 'без врезки и останова' },
      { id: 'multigauge', index: '03', nav: 'Щит', form: 'Щит приборов',
        title: 'Одна камера на целый щит',
        lede: 'Камера находит каждый прибор на щите, даёт постоянный код и ведёт отдельный канал; для работы рекомендуем 4–8 приборов на кадр.',
        accent: '4–8 приборов на кадр' },
      { id: 'resilience', index: '04', nav: 'Связь', form: 'Очередь MQTT',
        title: 'Обрыв связи без потери строк',
        lede: 'При потере сети или брокера показания копятся в локальной очереди и уходят в исходном порядке — в испытании 10 309 из 10 309.',
        accent: '10 309 из 10 309' },
      { id: 'scada', index: '05', nav: 'SCADA', form: 'Ignition SCADA',
        title: 'Данные в SCADA предприятия',
        lede: 'Показания и статусы уходят по Modbus TCP и MQTT: на лабораторном стенде с Ignition 8.3.10 пройдены 19 из 19 этапов.',
        accent: '19 из 19 этапов' },
      { id: 'forecast', index: '06', nav: 'Прогноз', form: 'Диагностика и тренд',
        title: 'Причины отклонений и прогноз',
        lede: 'Система делит причину на процесс, прибор или оптику и оценивает время до уставки — это подсказка инженеру, а не защита от аварий.',
        accent: 'подсказка инженеру, а не защита от аварий' },
      { id: 'optimizer', index: '07', nav: 'План и ТЗ', form: 'Модернизация',
        title: 'Бюджет, план и готовое ТЗ',
        lede: 'Оптимизатор подбирает обязательные и приоритетные замены под заданный бюджет, а результаты сразу ложатся в черновик ТЗ.',
        accent: 'сразу ложатся в черновик ТЗ' },
      { id: 'metrics', index: '08', nav: 'Протокол', form: 'Протокол',
        title: 'Протокол испытаний',
        lede: 'Стабильная версия v3.0.0 прошла комплексную приёмку: каждая цифра в таблице привязана к отчёту в репозитории.',
        accent: 'привязана к отчёту в репозитории' },
      { id: 'evolution', index: '09', nav: 'Эволюция', form: '1.0 → 2.0 → 3.0',
        title: 'От чтения стрелки к плану замен',
        lede: 'Три этапа развития в одном контуре: от распознавания одного прибора к щиту, SCADA, прогнозу и оптимизатору.',
        accent: 'к щиту, SCADA, прогнозу и оптимизатору' },
      { id: 'limits', index: '10', nav: 'Замечания', form: 'Ограничения',
        title: 'Готовность и ограничения',
        lede: 'Система готова к демонстрации и лабораторному стенду, но для промышленной эксплуатации статус сегодня — NOT READY.',
        accent: 'статус сегодня — NOT READY' },
      { id: 'contact', index: '11', nav: 'GitHub', form: 'Сдача смены',
        title: 'Журнал открыт на GitHub' }
    ],

    /* Калибровка для живого эмалевого прибора на листе 01 (0–10 МПа, CW, углы от «6 часов»). */
    calibration: {
      thetaMin: 45,
      thetaMax: 315,
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
    reading: {
      theta: 163.4,
      sliderLabel: 'Показание прибора, МПа',
      zones: { normal: 'НОРМА', warning: 'ПРЕДУПРЕЖДЕНИЕ', alert: 'АВАРИЯ' },
      written: 'Записано в журнал листа 01'
    },

    /* ---------- 01 Журнал ---------- */
    hero: {
      title: 'Прибор пишет журнал сам',
      slogan: 'Промышленность будущего. На оборудовании настоящего.',
      line: 'Камера снимает стрелку снаружи контура, а GaugeVision 3.0 ведёт щит приборов, SCADA, прогноз и план модернизации без облака.',
      lineAccent: 'щит приборов, SCADA, прогноз и план модернизации',
      columns: ['Время', 'Прибор', 'Показание, МПа', 'Записал'],
      hand: 'обходчик',
      machine: 'камера',
      demo: 'Симуляция журнала: строки считает калибровка из кода для манометра 0–10 МПа',
      rate: '3 обработки в секунду на камеру',
      dialLabel: 'Кадр камеры',
      dialHint: 'Потяните стрелку, и показание ляжет строкой в журнал',
      dialHintTouch: 'Проведите по шкале, и показание ляжет строкой в журнал',
      cta: 'Тег v3.0.0 на GitHub',
      ctaDemo: 'Режим демонстрации',
      ctaNext: 'Смотреть в действии',
      fresh: 'К новым записям'
    },

    /* ---------- 02 Смена и экономика сценария ---------- */
    compare: {
      video: {
        src: 'assets/video/shift.scrub.mp4',
        srcMobile: 'assets/video/shift.scrub-m.mp4',
        poster: 'assets/img/shift-before.jpg',
        posterAfter: 'assets/img/shift-after.jpg',
        label: 'Иллюстративный ролик: обходчик записывает показание манометра в журнал и уходит; на поручне появляется камера',
        note: 'Иллюстрация, сгенерированная Gemini, — не съёмка со стенда.'
      },
      captions: {
        before: 'Было: обход раз в смену, показание пишут в журнал от руки',
        after: 'Стало: камера на поручне читает стрелку вместо обходчика'
      },
      before: {
        title: 'Сегодня',
        points: [
          'Показание видят раз в обход и пишут в бумажный журнал',
          'Отклонение между обходами незаметно',
          'Нет истории для анализа и расчёта трендов',
          'Неясно, какие приборы менять в первую очередь',
          'Сплошная замена на датчики — проект, монтаж и часто останов'
        ]
      },
      after: {
        title: 'С GaugeVision 3.0',
        points: [
          'Камера снаружи контура: без врезки, останова и облака',
          'Архив, тренды и диагностика по каждому прибору щита',
          'Данные в SCADA по Modbus TCP и MQTT с локальной очередью',
          'Прогноз времени до уставок как подсказка инженеру',
          'Оптимальный план модернизации и черновик ТЗ под бюджет'
        ]
      },
      cost: {
        legend: 'Стендовый каталог проекта',
        value: '104 880',
        unit: '₽ за точку',
        text: 'стоит замена одной точки на цифровой преобразователь давления с монтажом и пусконаладкой 14 % по каталогу app/spec_generator.py. GaugeVision помогает выбрать, какие точки менять сейчас.',
        source: 'catalog'
      },
      timeline: {
        caption: 'Симуляция смены',
        shiftHours: 12,
        rounds: [0, 12],
        deviationHour: 5,
        roundLabel: 'Обход',
        handRow: 'Обходчик',
        cameraRow: 'Камера',
        deviationLabel: 'Отклонение',
        drag: 'Перетащите отклонение по смене или выберите час стрелками',
        deviationAt: 'Отклонение примерно в',
        deviationStart: 'Отклонение в начале смены',
        hourForms: ['час', 'часа', 'часов'],
        beforeLead: 'Обходчик заметит через',
        afterLead: 'Камера увидит на следующем кадре, через',
        afterValue: '⅓ с',
        emaNote: 'По формуле EMA α = 0,25 показание догоняет ≈ 90 % скачка за 8 кадров; это оценка по формуле, а не замер.',
        loupe: 'Одна секунда смены: три кадра камеры'
      },
      economics: {
        title: 'Сравнение двух сценариев',
        subtitle: 'Задайте свои допущения: полная замена на датчики (A) или камеры GaugeVision сейчас и замены по плану (B).',
        fields: [
          { id: 'points', label: 'Аналоговых приборов', value: 120, min: 8, max: 2000, step: 1, unit: 'шт.' },
          { id: 'sensorCost', label: 'Замена одной точки на датчик', value: 104880, min: 20000, max: 400000, step: 1000, unit: '₽', note: 'каталог проекта, давление, с монтажом и ПНР' },
          { id: 'perCamera', label: 'Приборов на одну камеру', value: 4, min: 1, max: 8, step: 1, unit: 'шт.', note: 'основной режим 4–8' },
          { id: 'cameraCost', label: 'Камера с установкой', value: 33000, min: 5000, max: 150000, step: 1000, unit: '₽', note: 'оценка команды, v2' },
          { id: 'serverCost', label: 'Сервер и наладка GaugeVision', value: 400000, min: 0, max: 5000000, step: 10000, unit: '₽', note: 'задайте свою оценку' },
          { id: 'opexSensor', label: 'Эксплуатация датчика в год', value: 8000, min: 0, max: 50000, step: 500, unit: '₽', note: 'app/config.py' },
          { id: 'opexCamera', label: 'Эксплуатация камеры в год', value: 8000, min: 0, max: 50000, step: 500, unit: '₽' },
          { id: 'priority', label: 'Доля приоритетных замен', value: 20, min: 0, max: 100, step: 5, unit: '%', note: 'по плану оптимизатора' },
          { id: 'years', label: 'Горизонт расчёта', value: 5, min: 1, max: 15, step: 1, unit: 'лет' }
        ],
        disclaimer: 'Сценарная оценка с изменяемыми допущениями. Не коммерческое предложение и не доказанная окупаемость: эффект подтверждается только пилотом на конкретном объекте.'
      }
    },

    /* ---------- 03 Щит ---------- */
    multigauge: {
      counts: [1, 2, 4, 8, 16],
      initial: 8,
      images: {
        1: 'assets/img/mg-01.jpg',
        2: 'assets/img/mg-02.jpg',
        4: 'assets/img/mg-04.jpg',
        8: 'assets/img/mg-08.jpg',
        16: 'assets/img/mg-16.jpg'
      },
      synthetic: {
        1: { valid: '100 %', mae: '0,23 %', fps: '16,5', ids: 0 },
        2: { valid: '100 %', mae: '0,46 %', fps: '12,6', ids: 0 },
        4: { valid: '100 %', mae: '0,32 %', fps: '8,8', ids: 0 },
        8: { valid: '100 %', mae: '0,36 %', fps: '4,5', ids: 0 },
        16: { valid: '100 %', mae: '0,56 %', fps: '2,3', ids: 0 }
      },
      real: {
        1: { reg: '97,5 %', valid: '82,5 %', median: '1,36 %' },
        2: { reg: '97,5 %', valid: '90,0 %', median: '1,53 %' },
        4: { reg: '97,5 %', valid: '87,5 %', median: '1,34 %' },
        8: { reg: '97,9 %', valid: '85,4 %', median: '1,08 %' },
        16: { reg: '89,6 %', valid: '47,9 %', median: '1,19 %' }
      },
      imgNote: 'Синтетическая панель app/panel_sim.py. Рамки, коды и значения — реальный вывод конвейера на последнем кадре tests/test_multigauge.py. При N = 8 нажмите на прибор на кадре.',
      warn16: 'При 16 приборах на мозаиках реальных фото годных показаний 47,9 %: надёжной работы с 16 реальными приборами нет, для основной работы рекомендуем 4–8 приборов на кадр.',
      claim: 'На мозаиках реальных фотографий MeterFL (выборка final) при N ≤ 8 регистрируется не менее 97,5 % приборов (регистрация, а не точность), медианная ошибка 1,1–1,5 % шкалы. Перепутанных идентификаторов — ноль во всех сценариях.',
      hmi: {
        img: 'assets/img/hmi-panel.jpg',
        caption: 'Вкладка «Щит» пульта GaugeVision 3.0: общий кадр источника, разметка и таблица приборов. Источник — синтетическое видео стенда.'
      }
    },

    /* ---------- 04 Связь (Store-and-Forward) ---------- */
    resilience: {
      controls: { cut: 'Отключить связь', restore: 'Восстановить связь', reset: 'Сначала' },
      nodes: { edge: 'Камера и GaugeVision', edgeSub: 'локальный узел', link: 'Канал MQTT', broker: 'Брокер и SCADA', brokerSub: 'система предприятия' },
      states: {
        ok: 'Связь есть: сообщения уходят сразу',
        down: 'Связь потеряна: распознавание идёт, строки копятся в локальной очереди',
        drain: 'Связь восстановлена: очередь досылается в исходном порядке',
        done: 'Очередь пуста, пропусков нет'
      },
      proof: [
        { value: '10 309 / 10 309', label: 'MQTT-сообщений доставлено', note: 'последовательность 1…10 309 без разрывов' },
        { value: '61,9 мин', label: 'непрерывного испытания', note: '12 приборов, CPU' },
        { value: '6 + 4', label: 'отказа пережито', note: '6 отключений брокера по 60 с и 4 прерывания RTSP' },
        { value: '0', label: 'ошибок сервера и Modbus', note: 'за всё испытание soak' }
      ],
      proofSource: 'soak',
      simNote: 'Схема на странице — симуляция очереди Store-and-Forward. Таблица справа — измерения 62-минутного испытания soak версии 3.0.'
    },

    /* ---------- 05 SCADA ---------- */
    scada: {
      chain: ['Камера', 'GaugeVision', 'Цифровая телеметрия', 'Ignition SCADA', 'Рабочее место инженера'],
      big: { value: '19 / 19', label: 'этапов сквозного испытания с Ignition 8.3.10 пройдены на финальном коде' },
      features: [
        'Постоянный слот Modbus за каждым прибором: адреса не съезжают после перезапуска и миграции',
        'Контроль актуальности: устаревшее показание помечается, пустой слот честно отмечен «нет данных»',
        'Связь восстанавливается сама: потеря видна SCADA через 0,4 с, возврат — через 15,2 с после рестарта',
        'Прогнозные регистры Modbus предусмотрены для 200 слотов'
      ],
      protocols: ['Modbus TCP, только чтение', 'MQTT с очередью', 'REST API', 'WebSocket для пульта'],
      shot: {
        img: 'assets/img/scada-perspective.jpg',
        caption: 'Ignition 8.3.10 Perspective получает данные GaugeVision по Modbus TCP. Лабораторный стенд, один узел, пробная лицензия.'
      },
      limit: 'Лабораторная интеграция на одном узле с пробной лицензией. Подключение через OPC UA и прогнозные регистры внутри Ignition не проверялись.'
    },

    /* ---------- 06 Диагностика и прогноз ---------- */
    diagnostics: {
      title: 'Диагностика причин отклонений',
      causes: [
        { tone: 'alert', label: 'Авария процесса', title: 'Технологический процесс', text: 'Параметр действительно ушёл за уставку или быстро растёт' },
        { tone: 'warning', label: 'Прибор', title: 'Измерительный прибор', text: 'Дребезг, залипание стрелки, износ механики' },
        { tone: 'planned', label: 'Оптика', title: 'Оптика и камера', text: 'Блики, грязное стекло, потеря кадра — менять сам прибор не нужно' }
      ],
      shot: {
        img: 'assets/img/hmi-dispatch.jpg',
        caption: 'Вкладка «Диспетчеризация и ТЗ» пульта GaugeVision 3.0 на демонстрационных данных 36 позиций.'
      },
      hotspots: [
        { x: 0.18, y: 0.37, title: 'Health Score', text: 'Вспомогательный индекс состояния 0–100 %. Подсказка для приоритета осмотра, а не оценка остаточного ресурса.' },
        { x: 0.405, y: 0.37, title: 'Скорость изменения', text: 'dT/dt, dP/dt — как быстро параметр движется к уставке.' },
        { x: 0.535, y: 0.37, title: 'Причина', text: 'Процесс, прибор или оптика: от этого зависит, кого звать — технолога, КИПовца или протереть стекло.' },
        { x: 0.75, y: 0.535, title: 'Очередь рекомендаций', text: 'Ранжирована по риску, с фактами: уставка, пик скорости, длительность перегрузки, число срабатываний.' },
        { x: 0.3, y: 0.845, title: 'Прогноз', text: 'Время до уставок и аномальные тренды в той же вкладке.' }
      ]
    },

    forecastSection: {
      title: 'Прогноз времени до уставки',
      legend: {
        observed: 'Показания',
        model: 'Прогноз',
        band: 'Область неопределённости',
        alert: 'Аварийная уставка HH',
        warn: 'Уставка H',
        eta: 'Ожидаемое время',
        fact: 'Фактическое время'
      },
      stats: [
        { value: '13,18 мин', label: 'прогноз до уставки HH' },
        { value: '12,7 мин', label: 'фактическое время' },
        { value: '12,01–14,59', label: 'интервал прогноза, мин' }
      ],
      event: 'Предупреждение «скоро уставка» уходит в журнал, на пульт и в MQTT. Квитирования не требует и аварийную защиту (ПАЗ) не заменяет.',
      context: 'Контролируемый синтетический дрейф пятого сквозного испытания (PI-102, 0–1,6 МПа, наклон 0,01504 МПа/мин при истинном 0,0155, R² = 0,9962). Это проверка цепочки, а не универсальная точность модели.',
      expert: {
        title: 'Научная валидация на реальных промышленных данных',
        items: [
          '4 открытых промышленных датасета, 82 независимых тестовых ряда, 14 760 проверок прогноза. Тестовая выборка открыта один раз после фиксации кода.',
          'На Gas Turbine и MetroPT-3 модель обходит все пять базовых методов; покрытие интервала PI95 — 83,4–91,1 % на горизонте 60 шагов.',
          'Ограничения: полнота выявления будущих пересечений уставок на горизонте 30 шагов — 4,65 %, ложные срабатывания детектора аномалий — 36,1 %. Прогноз — подсказка инженеру, а не гарантия предотвращения аварий.'
        ],
        source: 'predictive'
      }
    },

    /* ---------- 07 Оптимизатор и ТЗ ---------- */
    optimizerSection: {
      objectives: [
        { id: 'max_risk_reduction', label: 'Снижение риска' },
        { id: 'weighted_utility', label: 'Баланс риска и эффекта' },
        { id: 'max_net_effect', label: 'Экономический эффект' }
      ],
      budget: { min: 100000, max: 800000, step: 10000, initial: 450000 },
      model: 'Упрощённая демонстрационная модель. CAPEX — по стендовому каталогу проекта с пусконаладкой 14 %; состояние приборов и вероятности пробоя — условные. Точный оптимум находится полным перебором всех 256 наборов прямо в браузере; в продукте ту же задачу решает ILP-ядро app/ilp_solver.py.',
      proof: [
        { value: '1500 / 1500', label: 'задач совпали с полным перебором и HiGHS', source: 'ilp' },
        { value: '748 / 748', label: 'точных расчётов минимального бюджета', source: 'ilp' },
        { value: 'до 1000', label: 'объектов в испытании масштабирования', source: 'ilpScale' }
      ],
      honest: 'Это доказательство математической точности, а не подтверждённый экономический эффект на действующем предприятии.'
    },

    documentSection: {
      title: 'Черновик дефектной ведомости и ТЗ',
      docNumber: 'ТЗ-КИП-20261127-01',
      shot: {
        img: 'assets/img/hmi-spec.jpg',
        caption: 'Конструктор дефектной ведомости и ТЗ в пульте 3.0: журнал инцидентов с кадрами, черновик документа, выгрузка DOCX и Markdown.'
      },
      note: 'Предпросмотр собирается из плана, рассчитанного выше. Документ — черновик инженерного проекта: он требует проверки и утверждения в установленном порядке.'
    },

    /* ---------- 08 Протокол испытаний ---------- */
    evidence: {
      columns: ['№', 'Показатель', 'Условия и контекст', 'Значение', 'Источник'],
      key: [
        { value: '10 309', unit: 'из 10 309', label: 'сообщений без потерь за 61,9 мин с отказами связи', source: 'soak' },
        { value: '19', unit: 'из 19', label: 'этапов сквозного испытания с настоящей Ignition SCADA', source: 'e2e' },
        { value: '1500', unit: 'из 1500', label: 'задач оптимизатора совпали с независимыми решателями', source: 'ilp' },
        { value: '8', unit: 'приборов', label: 'на кадре в основном режиме, до 16 на синтетическом стенде', source: 'multigauge' },
        { value: '0', unit: 'запросов', label: 'внешних обращений при чистой автономной установке', source: 'offline' }
      ],
      groups: [
        {
          title: 'Промышленная интеграция',
          rows: [
            { value: '19 / 19', text: 'этапов финального сквозного испытания с Ignition 8.3.10', ctx: 'синтетический щит, лабораторный стенд', source: 'e2e', key: true },
            { value: '16 / 16', text: 'испытаний взаимодействия: mediamtx, ffmpeg, amqtt, pymodbus', ctx: 'сторонние инструменты', source: 'tests' }
          ]
        },
        {
          title: 'Надёжность',
          rows: [
            { value: '61,9 мин', text: 'непрерывной работы объединённой системы', ctx: '12 приборов, CPU', source: 'soak' },
            { value: '10 309 / 10 309', text: 'MQTT-сообщений доставлено без разрывов последовательности', ctx: '6 отключений брокера по 60 с', source: 'soak', key: true },
            { value: '4 / 4', text: 'восстановления после прерываний RTSP', ctx: '23–53 с до возврата', source: 'soak' },
            { value: '0', text: 'ошибок сервера и Modbus', ctx: 'за всё испытание soak', source: 'soak' }
          ]
        },
        {
          title: 'Качество разработки',
          rows: [
            { value: '13 / 13', text: 'регрессионных наборов, три повтора ключевых', ctx: 'полная регрессия', source: 'tests' },
            { value: '12 / 12', text: 'независимых интеграционных проверок', ctx: 'test_final_integration', source: 'tests' },
            { value: '21 / 21', text: 'независимых приёмочных проверок', ctx: 'test_acceptance_independent', source: 'tests' },
            { value: '6 / 6', text: 'повторных исходных аудитов', ctx: 'rerun_original_audits', source: 'tests' },
            { value: '14 / 14', text: 'проверок чистой автономной установки', ctx: '61 / 61 пакетов, 0 внешних запросов', source: 'offline' },
            { value: '11 / 11', text: 'проверок безопасности', ctx: 'включая сетевую политику', source: 'security' }
          ]
        },
        {
          title: 'Математическая оптимизация',
          rows: [
            { value: '1500 / 1500', text: 'точных совпадений с полным перебором и HiGHS', ctx: 'независимая проверка', source: 'ilp', key: true },
            { value: '748 / 748', text: 'точных расчётов минимального бюджета', ctx: 'для неразрешимых задач', source: 'ilp' },
            { value: '36–1000', text: 'объектов в испытании масштабирования', ctx: 'часть трудных задач — по лимиту времени', source: 'ilpScale' }
          ]
        },
        {
          title: 'Компьютерное зрение',
          rows: [
            { value: 'до 16', text: 'приборов на синтетической панели, 100 % годных', ctx: 'синтетика, 0 перепутанных ID', source: 'multigauge' },
            { value: '≥ 97,5 %', text: 'приборов регистрируется на мозаиках реальных фото при N ≤ 8', ctx: 'регистрация, а не точность', source: 'multigauge' },
            { value: '1,1–1,5 %', text: 'медианная ошибка шкалы в том же испытании', ctx: 'MeterFL, контрольная выборка final', source: 'multigauge' }
          ]
        },
        {
          title: 'Соответствие требованиям',
          rows: [
            { value: '96,95 / 100', text: 'по 75 исходным требованиям: 72 PASS, 2 PARTIAL, 0 FAIL, 1 NOT VERIFIED', ctx: 'методика аудита, не точность нейросети', source: 'rtm' },
            { value: '2 / 3 / 1', text: 'программа Next Generation: 2 PASS, 3 PARTIAL, 1 FAILED', ctx: 'отдельная матрица из 6 требований', source: 'rtmNg' }
          ]
        }
      ]
    },

    /* ---------- 09 Эволюция ---------- */
    evolution: {
      versions: [
        {
          id: 'v1', version: '1.0', verb: 'Видеть', title: 'Цифровизация показаний', img: 'assets/img/v1-dashboard.jpg',
          caption: 'Пульт 1.0: три источника, показания, уставки и тревога.',
          items: [
            'Распознавание стрелочных приборов камерой',
            'Камеры RTSP, MJPEG, USB и смартфон по QR-коду',
            'Ручная двухточечная калибровка по кадру',
            'История в SQLite, CSV и тревоги по уставкам',
            'Работа в локальной сети без интернета'
          ]
        },
        {
          id: 'v2', version: '2.0', verb: 'Понимать', title: 'Промышленный мониторинг', img: 'assets/img/v2-monitor.jpg',
          caption: 'Пульт 2.0: 36 позиций, статусы, тренды и скорость изменения.',
          items: [
            'Независимая обработка видеоканалов и адаптивная частота кадров',
            'Store-and-Forward, MQTT и Modbus TCP',
            'Диагностика качества изображения и Health Score',
            'Диспетчеризация и конструктор ТЗ',
            'Авторизация и роли, проверенная автономная установка'
          ]
        },
        {
          id: 'v3', version: '3.0', verb: 'Помогать решать', title: 'Поддержка инженерных решений', img: 'assets/img/v3-monitor.jpg',
          caption: 'Пульт 3.0: щит приборов, прогноз и оптимизатор в одном интерфейсе.',
          items: [
            'Несколько приборов на одном кадре (основной режим 4–8)',
            'Живая лабораторная интеграция с Ignition SCADA (19 / 19)',
            'Прогноз времени до уставок и информационные предупреждения',
            'Математическая оптимизация плана модернизации под бюджет',
            'План в техническом задании, независимая валидация и комплексная приёмка'
          ]
        }
      ]
    },

    /* ---------- 10 Готовность и ограничения ---------- */
    readiness: {
      levelsTitle: 'Уровни готовности версии v3.0.0',
      limitsTitle: 'Известные ограничения',
      levels: [
        { name: 'Демонстрация', verdict: 'READY', tone: 'done', text: 'Все вкладки пульта на трёх разрешениях, автономный запуск' },
        { name: 'Технический прототип', verdict: 'READY', tone: 'done', text: '13 / 13 наборов тестов, 19 / 19 E2E, 62-минутный soak' },
        { name: 'Лабораторная интеграция', verdict: 'READY с ограничениями', tone: 'done', text: 'Живой обмен с Ignition; пробная лицензия, один узел' },
        { name: 'Ограниченный пилот', verdict: 'CONDITIONAL', tone: 'warning', text: 'После проверки CV на приборах цеха и на целевом сервере' },
        { name: 'Промышленная эксплуатация', verdict: 'NOT READY', tone: 'alert', text: 'Нужны полевая валидация, 72-часовой прогон, промышленная лицензия SCADA' }
      ],
      limits: [
        { title: 'Не средство измерений и не ПАЗ', status: 'alert', statusText: 'ограничение', text: 'Показания, тревоги и прогнозы — информационная подсказка. Решение принимает человек по штатным приборам.', source: 'limits' },
        { title: 'Точность на реальных фото — частично', status: 'warning', statusText: 'частично', text: 'На 315 фотографиях MeterFL и MeasureBench: локализация 79,0 %, средняя ошибка 5,8 % шкалы. Полевая проверка в цеху не проводилась.', source: 'cv' },
        { title: 'Автокалибровка исключена', status: 'alert', statusText: 'выключена', text: 'Не прошла заранее установленные критерии (1 из 5) и выключена. Калибровка — ручная по кадру.', source: 'autocal' },
        { title: 'Прогноз — подсказка, а не гарантия', status: 'warning', statusText: 'частично', text: 'На реальных данных полнота выявления будущих пересечений уставки — 4,65 %, ложные срабатывания детектора аномалий — 36,1 %.', source: 'predictive' },
        { title: 'SCADA — лабораторный уровень', status: 'warning', statusText: 'стенд', text: 'Ignition на одном узле с пробной лицензией. OPC UA и прогнозные регистры внутри Ignition не проверялись.', source: 'scada' },
        { title: 'GPU в этой приёмке не проверялся', status: 'planned', statusText: 'не проверялся', text: 'Все испытания версии 3.0 шли на CPU; для GPU нужен отдельный прогон на целевом оборудовании.', source: 'limits' }
      ],
      untested: {
        title: 'Официальная граница применения',
        text: 'Инженерный прототип информационной системы. Не является средством измерений утверждённого типа и не является системой противоаварийной защиты.'
      },
      limitsLink: 'Все известные ограничения в репозитории'
    },

    /* ---------- 11 Сдача смены ---------- */
    contact: {
      title: 'Журнал открыт на GitHub',
      handedLabel: 'Смену сдал',
      handedBy: 'обходчик',
      acceptedLabel: 'Смену принял',
      acceptedBy: 'GaugeVision AI 3.0',
      yourEntries: 'Ваших записей в журнале',
      lead: 'Стабильная версия v3.0.0 (коммит 0273436): код, документация и все отчёты испытаний открыты на GitHub.',
      leadAccent: 'все отчёты испытаний открыты на GitHub',
      links: [
        { id: 'repo', label: 'Код на GitHub', href: REPO, primary: true },
        { id: 'tag', label: 'Тег v3.0.0', href: REPO + '/releases/tag/v3.0.0' },
        { id: 'branch', label: 'Ветка GaugeVision-3.0', href: REPO + '/tree/GaugeVision-3.0' },
        { id: 'report', label: 'Итоговый отчёт приёмки', href: src.acceptance.href },
        { id: 'pilot', label: 'Обсудить пилот на GitHub', href: REPO + '/issues/new?title=' + encodeURIComponent('Пилот GaugeVision AI 3.0: ') },
        { id: 'license', label: 'Проприетарная лицензия', href: REPO + '/blob/v3.0.0/LICENSE' }
      ]
    },

    /* ---------- Режим демонстрации (12 шагов) ---------- */
    showcase: {
      title: 'GaugeVision AI 3.0 — демонстрация',
      hint: '→ далее, ← назад, P пауза, R заново, F полный экран, Esc выход',
      modes: {
        sim: 'Симуляция',
        illustration: 'Иллюстрация',
        real: 'Снимок реального приложения',
        evidence: 'Доказательство испытаний'
      },
      steps: [
        { target: 'hero', mode: 'sim', title: 'Обычный стрелочный прибор', text: 'Камера смотрит на манометр снаружи и ведёт сменный журнал — без врезки в процесс и останова.' },
        { target: 'compare', mode: 'illustration', title: 'Двенадцать часов против трети секунды', text: 'Обходчик видит отклонение только на следующем обходе, камера фиксирует его на следующем кадре.' },
        { target: 'multigauge', count: 8, mode: 'evidence', title: 'Один прибор — целый щит', text: 'Восемь приборов на одном кадре: у каждого постоянный код и отдельный канал измерений.' },
        { target: 'multigauge', count: 8, spot: 1, mode: 'evidence', title: 'Показание прибора PI-102', text: 'Каждый прибор щита получает своё значение, статус достоверности и историю на вкладке «Щит».' },
        { target: 'scada', mode: 'real', title: 'Данные в Ignition SCADA', text: 'Ignition 8.3.10 Perspective получает показания по Modbus TCP: 19 из 19 этапов сквозного испытания. Лабораторный стенд.' },
        { target: 'resilience', action: 'cut', mode: 'sim', title: 'Связь потеряна', text: 'Канал MQTT разорван: распознавание продолжается, сообщения копятся в локальной очереди.' },
        { target: 'resilience', action: 'hold', mode: 'sim', title: 'Очередь растёт', text: 'Ни одна строка показаний не пропадает, пока брокер недоступен.' },
        { target: 'resilience', action: 'restore', mode: 'sim', title: 'Связь восстановлена', text: 'Очередь досылается в исходном порядке без пропусков. В испытании soak: 10 309 из 10 309.' },
        { target: 'forecast', action: 'play', mode: 'evidence', title: 'Прогноз тренда PI-102', text: 'Ожидаемое время до аварийной уставки HH — 13,18 мин при фактических 12,7 мин на синтетическом дрейфе.' },
        { target: 'optimizer', budget: 300000, mode: 'sim', title: 'Эксперт задаёт бюджет 300 тыс. ₽', text: 'При смене бюджета и цели оптимизатор перестраивает план модернизации.' },
        { target: 'optimizer', budget: 450000, mode: 'sim', title: 'Оптимальный план на 450 тыс. ₽', text: 'Четыре позиции (PI-101, PI-102, PI-104, PI-107) на 383 040 ₽ — как в сквозном испытании.' },
        { target: 'document', mode: 'sim', title: 'Готовый черновик ТЗ', text: 'План модернизации, данные мониторинга и требования к датчикам собираются в ТЗ-КИП-20261127-01.' }
      ]
    },

    /* Общие подписи интерфейса */
    labels: {
      nav: 'Листы журнала',
      home: 'GaugeVision AI 3.0, к первому листу',
      sheet: 'Лист',
      skip: 'К содержанию',
      newTab: 'откроется в новой вкладке',
      source: 'Источник',
      sim: 'Симуляция',
      real: 'Снимок реального приложения',
      evidence: 'Доказательство испытаний',
      synthetic: 'Синтетический стенд',
      illustration: 'Иллюстрация',
      showcase: 'Демо'
    }
  };

  /* ---------- Типограф: неразрывные пробелы ---------- */
  var NBSP = '\u00A0';
  var UNIT_RE = new RegExp(
    '(\\d) (?=(?:%|мин|мс|с|ч|к\\/с|px|МПа|кПа|бар|₽|тыс\\.|млн|шт\\.|лет|из|приборов|сообщений|°C|объектов|задач|кадров|кадра|этапов|позиций|наборов|б\\.)(?![A-Za-zА-Яа-яЁё]))',
    'g'
  );
  var SHORT_RE = /(^|[\s(«])((?:в|во|и|к|ко|с|со|о|об|у|на|по|за|из|от|до|не|ни|а|но|без|для|при|под|над)) /gi;
  var SKIP_KEYS = { id: 1, src: 1, srcMobile: 1, poster: 1, posterAfter: 1, href: 1, img: 1, code: 1, kind: 1, repoUrl: 1, tagUrl: 1, branchUrl: 1, readmeUrl: 1, reportUrl: 1, pilotUrl: 1, licenseUrl: 1, formula: 1, version: 1, commit: 1 };

  function typo(s) {
    return s
      .replace(/ — /g, NBSP + '— ')
      .replace(UNIT_RE, '$1' + NBSP)
      .replace(SHORT_RE, '$1$2' + NBSP)
      .replace(SHORT_RE, '$1$2' + NBSP)
      .replace(/(млн|тыс\.) ₽/g, '$1' + NBSP + '₽')
      .replace(/(№|≈|±|≤|≥|×) (?=\d)/g, '$1' + NBSP)
      .replace(/(\d) (\d{3})(?!\d)/g, '$1' + NBSP + '$2');
  }
  function walk(o, key) {
    if (typeof o === 'string') return SKIP_KEYS[key] || /^(https?:|assets\/|#)/.test(o) ? o : typo(o);
    if (Array.isArray(o)) return o.map(function (v) { return walk(v, key); });
    if (o && typeof o === 'object') {
      var out = {};
      Object.keys(o).forEach(function (k) { out[k] = walk(o[k], k); });
      return out;
    }
    return o;
  }

  var typed = walk(content, '');
  typed.src = src;
  typed.typo = typo;
  GV.content = typed;
})();
