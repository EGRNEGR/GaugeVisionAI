window.STATE =
{
  "version": 2,
  "slug": "gaugevision-dial",
  "dir": "2026-11-14-gaugevision-dial--wip",
  "title": "Лендинг GaugeVision AI: циферблат, видео на скролле, горизонтальный конвейер",
  "mode": "semi",
  "depth": "normal",
  "tier": "T1",
  "briefFile": "2026-11-14-brief.md",
  "memoryFile": "AGENTS.md",
  "memoryOwner": "autopilot",
  "skillDir": "~/skills/autopilot",
  "baseCommit": null,
  "startedAt": "2026-11-14T22:04:58+03:00",
  "updatedAt": "2026-11-14T22:23:27+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-11-14T22:04:58+03:00",
      "finishedAt": "2026-11-14T22:05:19+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-11-14T22:05:19+03:00",
      "finishedAt": "2026-11-14T22:06:40+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-11-14T22:06:40+03:00",
      "finishedAt": "2026-11-14T22:16:09+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-11-14T22:16:09+03:00",
      "finishedAt": "2026-11-14T22:23:25+03:00"
    },
    {
      "id": "plan",
      "status": "active",
      "startedAt": "2026-11-14T22:23:25+03:00"
    },
    {
      "id": "build",
      "status": "pending"
    },
    {
      "id": "review",
      "status": "pending"
    },
    {
      "id": "final",
      "status": "pending"
    }
  ],
  "requirements": {
    "total": 47,
    "done": 0,
    "inTicket": 47,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Одна страница на обсидиане: фундамент",
      "requirements": [
        "R01",
        "R04",
        "R05",
        "R06",
        "R07",
        "R10",
        "R11",
        "R12",
        "R26",
        "R29",
        "R36",
        "R37",
        "R39",
        "R40",
        "R41",
        "R42",
        "R43i",
        "R45i",
        "R46i",
        "G01"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "site/index.html",
        "site/js/content.js",
        "site/js/util.js",
        "site/js/motion.js",
        "site/js/page.js",
        "site/js/tweaks.js",
        "site/js/components/kit.js",
        "site/css/tokens.css",
        "site/css/base.css",
        "site/css/motion.css",
        "site/css/page.css",
        "site/css/tweaks.css",
        "site/css/fonts.css",
        "site/assets/",
        "site/tests/",
        "site/design-system.md",
        "archive/"
      ],
      "review": "да — фундамент",
      "model": "сильная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    },
    {
      "id": "02",
      "title": "Видео на скролле и прецизионный прибор",
      "requirements": [
        "R02",
        "R03",
        "R08",
        "R09",
        "R13",
        "R14",
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
        "R28",
        "R30",
        "R31",
        "R37",
        "R38",
        "R44i"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "site/js/components/scroll-video.js",
        "site/js/components/precision-dial.js",
        "site/css/hero.css",
        "site/css/dial.css",
        "site/index.html",
        "hero",
        "reading",
        "GV.page.mounts",
        "site/js/page.js",
        "site/tests/components.test.js"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    },
    {
      "id": "03",
      "title": "Горизонтальный конвейер и живые секции",
      "requirements": [
        "R02",
        "R03",
        "R20",
        "R21",
        "R22",
        "R23",
        "R24",
        "R25",
        "R26",
        "R27",
        "R28",
        "R30",
        "R31",
        "R32",
        "R33",
        "R34",
        "R35",
        "R37",
        "R38",
        "R41",
        "R44i",
        "G01"
      ],
      "blockedBy": [
        "01",
        "02"
      ],
      "wave": 3,
      "zone": [
        "site/js/components/pipeline-track.js",
        "site/css/track.css",
        "site/js/components/metrics.js",
        "site/js/components/compare.js",
        "site/js/components/architecture.js",
        "site/js/components/limits.js",
        "site/css/components.css",
        "site/css/motion.css",
        "site/index.html",
        "pipeline",
        "GV.page.mounts",
        "site/js/components/pipeline.js",
        "site/tests/"
      ],
      "review": "нет",
      "model": "обычная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    }
  ],
  "tests": null,
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [],
  "coverage": {
    "found": 2,
    "fixed": 2,
    "deferred": 0,
    "items": []
  },
  "concerns": [],
  "blind": null,
  "beats": [
    "2026-11-14T22:04:58+03:00",
    "2026-11-14T22:05:19+03:00",
    "2026-11-14T22:06:39+03:00",
    "2026-11-14T22:06:40+03:00",
    "2026-11-14T22:06:48+03:00",
    "2026-11-14T22:16:01+03:00",
    "2026-11-14T22:16:09+03:00",
    "2026-11-14T22:22:36+03:00",
    "2026-11-14T22:23:25+03:00",
    "2026-11-14T22:23:26+03:00",
    "2026-11-14T22:23:27+03:00"
  ],
  "rev": 13,
  "waiting": null,
  "waits": [
    {
      "kind": "briefing",
      "from": "2026-11-14T22:06:48+03:00",
      "to": "2026-11-14T22:16:01+03:00"
    }
  ],
  "log": [
    {
      "t": "2026-11-14T22:04:58+03:00",
      "k": "init"
    },
    {
      "t": "2026-11-14T22:05:19+03:00",
      "k": "stage",
      "id": "manifest",
      "act": "start"
    },
    {
      "t": "2026-11-14T22:06:40+03:00",
      "k": "stage",
      "id": "briefing",
      "act": "start"
    },
    {
      "t": "2026-11-14T22:06:48+03:00",
      "k": "ask",
      "kind": "briefing",
      "note": "4 вопроса — где циферблат, Tweaks, баги прошлой сборки, гомография vs код"
    },
    {
      "t": "2026-11-14T22:16:01+03:00",
      "k": "answered",
      "kind": "briefing"
    },
    {
      "t": "2026-11-14T22:16:09+03:00",
      "k": "gate",
      "g": "G1",
      "ok": false,
      "open": 46,
      "total": 46
    },
    {
      "t": "2026-11-14T22:16:09+03:00",
      "k": "stage",
      "id": "spec",
      "act": "start"
    },
    {
      "t": "2026-11-14T22:22:36+03:00",
      "k": "gate",
      "g": "G2",
      "ok": true,
      "found": 2,
      "fixed": 2,
      "deferred": 0
    },
    {
      "t": "2026-11-14T22:22:36+03:00",
      "k": "gate",
      "g": "G1",
      "ok": true,
      "open": 0,
      "total": 47
    },
    {
      "t": "2026-11-14T22:23:25+03:00",
      "k": "stage",
      "id": "plan",
      "act": "start"
    },
    {
      "t": "2026-11-14T22:23:26+03:00",
      "k": "tier",
      "v": "T1"
    },
    {
      "t": "2026-11-14T22:23:26+03:00",
      "k": "tickets",
      "n": 3
    },
    {
      "t": "2026-11-14T22:23:27+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    }
  ],
  "reqList": [
    {
      "id": "R01",
      "text": "«Пересобери сайт в ./site на основе Варианта B (циферблат)»",
      "status": "in-ticket"
    },
    {
      "id": "R02",
      "text": "«используя скилл tactical-hud-web-design»",
      "status": "in-ticket"
    },
    {
      "id": "R03",
      "text": "«подходы Impeccable (distill + animate + polish)»",
      "status": "in-ticket"
    },
    {
      "id": "R04",
      "text": "«строгие факты из PRODUCT.md»",
      "status": "in-ticket"
    },
    {
      "id": "R05",
      "text": "«остальные варианты (A и C) убери в архив»",
      "status": "in-ticket"
    },
    {
      "id": "R06",
      "text": "«удали верхний переключатель вариантов»",
      "status": "in-ticket"
    },
    {
      "id": "R07",
      "text": "«На первом экране (Hero) полностью убери старые растровые картинки»",
      "status": "in-ticket"
    },
    {
      "id": "R08",
      "text": "«Сделай Hero-секцию закреплённой (sticky) на 250–300vh высоты скролла»",
      "status": "in-ticket"
    },
    {
      "id": "R09",
      "text": "«при прокрутке страницы вниз видео плавно проигрывалось кадр за кадром (привязка video.currentTime к прогрессу скролла через requestAnimationFrame с инерцией)»",
      "status": "in-ticket"
    },
    {
      "id": "R10",
      "text": "«В ./site/assets/ лежит моё видео [...gauge_pullback.mp4]»",
      "status": "in-ticket"
    },
    {
      "id": "R11",
      "text": "«Если в системе доступен ffmpeg, оптимизируй видео для плавного скролла (частые keyframes)»",
      "status": "in-ticket"
    },
    {
      "id": "R12",
      "text": "«сохранив оригинал»",
      "status": "in-ticket"
    },
    {
      "id": "R13",
      "text": "«Поверх видео оставь только сверхчистый HUD-заголовок, 1 строку сути и аккуратный индикатор скролла»",
      "status": "in-ticket"
    },
    {
      "id": "R14",
      "text": "«циферблат [...] как дорогой прецизионный прибор: тонкая градуированная шкала с рисками»",
      "status": "in-ticket"
    },
    {
      "id": "R15",
      "text": "«стеклянно-металлический блик по контуру (rim light)»",
      "status": "in-ticket"
    },
    {
      "id": "R16",
      "text": "«плавная подсвеченная дуга активного диапазона (норма / предупреждение / CRITICAL)»",
      "status": "in-ticket"
    },
    {
      "id": "R17",
      "text": "«стрелка с физической инерцией (spring physics), реагирующая на скролл и наведение»",
      "status": "in-ticket"
    },
    {
      "id": "R18",
      "text": "«чёткие табличные цифры (tabular-nums)»",
      "status": "in-ticket"
    },
    {
      "id": "R19",
      "text": "«Доработка циферблата (Hero / ключевой визуальный узел)» — где он стоит при Hero-видео",
      "status": "in-ticket"
    },
    {
      "id": "R20",
      "text": "«Секцию с [...] математическим аппаратом и пайплайном [...] сделай в виде закреплённого горизонтального трека (pinned horizontal scroll)»",
      "status": "in-ticket"
    },
    {
      "id": "R21",
      "text": "«1. CLAHE-нормализация и ROI-детекция YOLOv8n → 2. Гомография и коррекция перспективы → 3. Аппроксимация шкалы эллипсом и субпиксельный расчёт угла θ → 4. Экспоненциальное сглаживание EMA α=0.25»",
      "status": "in-ticket"
    },
    {
      "id": "R22",
      "text": "«карточки этапов по порядку плавно выезжают слева направо»",
      "status": "in-ticket"
    },
    {
      "id": "R23",
      "text": "«с подсветкой активного шага»",
      "status": "in-ticket"
    },
    {
      "id": "R24",
      "text": "«формулой»",
      "status": "in-ticket"
    },
    {
      "id": "R25",
      "text": "«и задержкой»",
      "status": "in-ticket"
    },
    {
      "id": "R26",
      "text": "«Убери длинные абзацы, описания и лишние пояснения по всему сайту»",
      "status": "in-ticket"
    },
    {
      "id": "R27",
      "text": "«Оставь только короткие ёмкие заголовки (3–6 слов), сухие инженерные цифры, формулы и визуальные/интерактивные блоки»",
      "status": "in-ticket"
    },
    {
      "id": "R28",
      "text": "«Максимум воздуха»",
      "status": "in-ticket"
    },
    {
      "id": "R29",
      "text": "«глубокий обсидиановый фон (#090B0E)»",
      "status": "in-ticket"
    },
    {
      "id": "R30",
      "text": "«тонкие 1px-границы с деликатным верхним световым бликом»",
      "status": "in-ticket"
    },
    {
      "id": "R31",
      "text": "«направленные световые акценты без кислотного неона»",
      "status": "in-ticket"
    },
    {
      "id": "R32",
      "text": "«каскадное появление заголовков (staggered reveal)»",
      "status": "in-ticket"
    },
    {
      "id": "R33",
      "text": "«плавную прокрутку чисел (counters)»",
      "status": "in-ticket"
    },
    {
      "id": "R34",
      "text": "«световую реакцию карточек на курсор (spotlight border)»",
      "status": "in-ticket"
    },
    {
      "id": "R35",
      "text": "«анимированные SVG-связи»",
      "status": "in-ticket"
    },
    {
      "id": "R36",
      "text": "«прогресс-бар телеметрии при скролле»",
      "status": "in-ticket"
    },
    {
      "id": "R37",
      "text": "«Всё строго на GPU-свойствах (transform, opacity)»",
      "status": "in-ticket"
    },
    {
      "id": "R38",
      "text": "«Максимум плавной анимации (60 FPS)»",
      "status": "in-ticket"
    },
    {
      "id": "R39",
      "text": "«проприетарная лицензия»",
      "status": "in-ticket"
    },
    {
      "id": "R40",
      "text": "«из контактов только GitHub EGRNEGR»",
      "status": "in-ticket"
    },
    {
      "id": "R41",
      "text": "«оценки для 50/100 камер помечены как расчётные»",
      "status": "in-ticket"
    },
    {
      "id": "R42",
      "text": "«Можешь генерировать видео и изображения через Gemini, если это можно вставить красиво в мой сайт»",
      "status": "in-ticket"
    },
    {
      "id": "R43i",
      "text": "(подразумевается) сайт по-прежнему открывается двойным кликом по file:// и не требует сборки",
      "status": "in-ticket"
    },
    {
      "id": "R44i",
      "text": "(подразумевается) видео-hero и закреплённые треки работают на телефоне и при «уменьшить движение»",
      "status": "in-ticket"
    },
    {
      "id": "R45i",
      "text": "(подразумевается) остальные экраны варианта B (метрики, Было → Стало, архитектура, ограничения, финал) остаются, только ужатые",
      "status": "in-ticket"
    },
    {
      "id": "R46i",
      "text": "(подразумевается) панель Tweaks — судьба после фиксации одного варианта и обсидианового фона",
      "status": "in-ticket"
    },
    {
      "id": "G01",
      "text": "«ок» — взять 9 багов прошлой сборки (битый #%E0, два «GitHub» в шапке B, обратный порядок Tab в hero B, меню за краем на телефоне и т. д.)",
      "status": "in-ticket"
    }
  ],
  "gates": {
    "G1": {
      "ok": true,
      "at": "2026-11-14T22:22:36+03:00",
      "open": 0,
      "total": 47
    },
    "G2": {
      "ok": true,
      "at": "2026-11-14T22:22:36+03:00",
      "found": 2,
      "fixed": 2,
      "deferred": 0
    },
    "G3": {
      "ok": true,
      "at": "2026-11-14T22:23:27+03:00",
      "problems": 0
    }
  },
  "result": null
}
