window.STATE =
{
  "version": 2,
  "slug": "gaugevision-landing",
  "dir": "2026-11-14-gaugevision-landing--wip",
  "title": "Лендинг GaugeVision AI",
  "mode": "semi",
  "depth": "normal",
  "tier": "T2",
  "briefFile": "2026-11-14-brief.md",
  "memoryFile": "AGENTS.md",
  "memoryOwner": "autopilot",
  "skillDir": "~/skills/autopilot",
  "baseCommit": null,
  "startedAt": "2026-11-14T11:59:29+03:00",
  "updatedAt": "2026-11-14T12:13:02+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-11-14T11:59:29+03:00",
      "finishedAt": "2026-11-14T11:59:42+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-11-14T11:59:42+03:00",
      "finishedAt": "2026-11-14T12:00:28+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-11-14T12:00:28+03:00",
      "finishedAt": "2026-11-14T12:06:40+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-11-14T12:06:40+03:00",
      "finishedAt": "2026-11-14T12:11:34+03:00"
    },
    {
      "id": "plan",
      "status": "active",
      "startedAt": "2026-11-14T12:11:34+03:00"
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
    "total": 40,
    "done": 0,
    "inTicket": 40,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Фундамент: оболочка, факты, токены, переключатель вариантов, Tweaks, правила дизайна",
      "requirements": [
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
        "R06",
        "R07",
        "R08",
        "R11",
        "R28",
        "R29",
        "R31",
        "R32",
        "R33",
        "R34",
        "R35",
        "R36",
        "R37"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "site/index.html",
        "site/design-system.md",
        "site/css/fonts.css",
        "site/css/tokens.css",
        "site/css/base.css",
        "site/css/tweaks.css",
        "site/js/content.js",
        "site/js/util.js",
        "site/js/tweaks.js",
        "site/js/app.js",
        "site/assets/fonts/",
        "site/assets/img/",
        "site/tests/"
      ],
      "review": "да — фундамент",
      "model": "сильная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    },
    {
      "id": "02",
      "title": "Интерактивные компоненты и вариант A «Пульт»: вся страница работает",
      "requirements": [
        "R09",
        "R10",
        "R12",
        "R13",
        "R14",
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
        "R20",
        "R21",
        "R22",
        "R23",
        "R24",
        "R25",
        "R26",
        "R27",
        "R30",
        "R38i",
        "R39i",
        "R40i"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "site/js/components/",
        "site/js/variants/a.js",
        "site/css/variant-a.css",
        "site/css/components.css"
      ],
      "review": "нет",
      "model": "сильная",
      "status": "pending",
      "retries": 0,
      "repairs": 0
    },
    {
      "id": "03",
      "title": "Варианты B «Циферблат» и C «Протокол»",
      "requirements": [
        "R30",
        "R31",
        "R06",
        "R07",
        "R09",
        "R27",
        "R34",
        "R38i"
      ],
      "blockedBy": [
        "02"
      ],
      "wave": 3,
      "zone": [
        "site/js/variants/b.js",
        "site/js/variants/c.js",
        "site/css/variant-b.css",
        "site/css/variant-c.css"
      ],
      "review": "нет",
      "model": "сильная",
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
    "2026-11-14T11:59:29+03:00",
    "2026-11-14T11:59:42+03:00",
    "2026-11-14T12:00:27+03:00",
    "2026-11-14T12:00:28+03:00",
    "2026-11-14T12:01:07+03:00",
    "2026-11-14T12:06:40+03:00",
    "2026-11-14T12:11:33+03:00",
    "2026-11-14T12:11:34+03:00",
    "2026-11-14T12:11:46+03:00",
    "2026-11-14T12:13:01+03:00",
    "2026-11-14T12:13:02+03:00"
  ],
  "rev": 12,
  "waiting": null,
  "waits": [
    {
      "kind": "briefing",
      "from": "2026-11-14T12:01:07+03:00",
      "to": "2026-11-14T12:06:40+03:00"
    }
  ],
  "log": [
    {
      "t": "2026-11-14T11:59:29+03:00",
      "k": "init"
    },
    {
      "t": "2026-11-14T11:59:42+03:00",
      "k": "stage",
      "id": "manifest",
      "act": "start"
    },
    {
      "t": "2026-11-14T12:00:28+03:00",
      "k": "stage",
      "id": "briefing",
      "act": "start"
    },
    {
      "t": "2026-11-14T12:01:07+03:00",
      "k": "ask",
      "kind": "briefing",
      "note": "три вопроса — фон вариантов, ссылка на демо, объём вариантов"
    },
    {
      "t": "2026-11-14T12:06:40+03:00",
      "k": "answered",
      "kind": "briefing"
    },
    {
      "t": "2026-11-14T12:06:40+03:00",
      "k": "gate",
      "g": "G1",
      "ok": false,
      "open": 40,
      "total": 40
    },
    {
      "t": "2026-11-14T12:06:40+03:00",
      "k": "stage",
      "id": "spec",
      "act": "start"
    },
    {
      "t": "2026-11-14T12:11:33+03:00",
      "k": "gate",
      "g": "G2",
      "ok": true,
      "found": 2,
      "fixed": 2,
      "deferred": 0
    },
    {
      "t": "2026-11-14T12:11:33+03:00",
      "k": "gate",
      "g": "G1",
      "ok": true,
      "open": 0,
      "total": 40
    },
    {
      "t": "2026-11-14T12:11:34+03:00",
      "k": "stage",
      "id": "plan",
      "act": "start"
    },
    {
      "t": "2026-11-14T12:11:46+03:00",
      "k": "tier",
      "v": "T2"
    },
    {
      "t": "2026-11-14T12:13:01+03:00",
      "k": "tickets",
      "n": 3
    },
    {
      "t": "2026-11-14T12:13:02+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    }
  ],
  "reqList": [
    {
      "id": "R01",
      "text": "«используй скилл tactical-hud-web-design»",
      "status": "in-ticket"
    },
    {
      "id": "R02",
      "text": "«строго опирайся на PRODUCT.md»",
      "status": "in-ticket"
    },
    {
      "id": "R03",
      "text": "«одностраничный продуктовый сайт-презентацию»",
      "status": "in-ticket"
    },
    {
      "id": "R04",
      "text": "«в папке ./site»",
      "status": "in-ticket"
    },
    {
      "id": "R05",
      "text": "«на базе реального кода и документации из текущего репозитория»",
      "status": "in-ticket"
    },
    {
      "id": "R06",
      "text": "«эстетику Tactical HUD Minimalism / Technical Precision»",
      "status": "in-ticket"
    },
    {
      "id": "R07",
      "text": "«глубокий графитовый фон»",
      "status": "in-ticket"
    },
    {
      "id": "R08",
      "text": "«тонкие 1px-разделители»",
      "status": "in-ticket"
    },
    {
      "id": "R09",
      "text": "«моноширинные цифры для метрик»",
      "status": "in-ticket"
    },
    {
      "id": "R10",
      "text": "«живые интерактивные блоки вместо сплошного текста»",
      "status": "in-ticket"
    },
    {
      "id": "R11",
      "text": "«Запрещено выдумывать метрики, стеки и функции, которых нет в проекте.»",
      "status": "in-ticket"
    },
    {
      "id": "R12",
      "text": "«Отрази реальный пайплайн обработки (детекция, коррекция перспективы/освещения, сглаживание показаний, потоковая обработка)»",
      "status": "in-ticket"
    },
    {
      "id": "R13",
      "text": "«и реальные замеры качества/скорости»",
      "status": "in-ticket"
    },
    {
      "id": "R14",
      "text": "«честный блок с физическими ограничениями цеха (блики на стекле, вибрация, угол камеры)»",
      "status": "in-ticket"
    },
    {
      "id": "R15",
      "text": "«и тем, как они решаются алгоритмически»",
      "status": "in-ticket"
    },
    {
      "id": "R16",
      "text": "«Hero: сильный заголовок»",
      "status": "in-ticket"
    },
    {
      "id": "R17",
      "text": "«суть системы за 5 секунд»",
      "status": "in-ticket"
    },
    {
      "id": "R18",
      "text": "«кнопка перехода к демо/репозиторию»",
      "status": "in-ticket"
    },
    {
      "id": "R19",
      "text": "«интерактивный визуальный блок (например, переключатель «Сырой кадр с камеры → Распознавание и снятие показаний»)»",
      "status": "in-ticket"
    },
    {
      "id": "R20",
      "text": "«Полоса подтверждённых метрик (точность, задержка, FPS/условия замера)»",
      "status": "in-ticket"
    },
    {
      "id": "R21",
      "text": "«Интерактивный разбор пайплайна: кликабельные этапы от захвата кадра до выдачи значения в МПа/бар»",
      "status": "in-ticket"
    },
    {
      "id": "R22",
      "text": "«Сравнение «Было (ручной обход / сырой кадр) → Стало (GaugeVisionAI)»»",
      "status": "in-ticket"
    },
    {
      "id": "R23",
      "text": "«Архитектура и стек проекта (наглядная SVG-схема)»",
      "status": "in-ticket"
    },
    {
      "id": "R24",
      "text": "«Инженерные компромиссы и ограничения»",
      "status": "in-ticket"
    },
    {
      "id": "R25",
      "text": "«Финальный блок со ссылкой на GitHub»",
      "status": "in-ticket"
    },
    {
      "id": "R26",
      "text": "«и контактами автора»",
      "status": "in-ticket"
    },
    {
      "id": "R27",
      "text": "«Структура экранов» 1–7 — в этом порядке",
      "status": "in-ticket"
    },
    {
      "id": "R28",
      "text": "«Проанализируй скриншоты в ./references»",
      "status": "in-ticket"
    },
    {
      "id": "R29",
      "text": "«запиши правила дизайна в ./site/design-system.md»",
      "status": "in-ticket"
    },
    {
      "id": "R30",
      "text": "«Собери 3 принципиально разных визуальных варианта главной страницы (с разной композицией и акцентами)»",
      "status": "in-ticket"
    },
    {
      "id": "R31",
      "text": "«с переключателем сверху»",
      "status": "in-ticket"
    },
    {
      "id": "R32",
      "text": "«плавающей панелью Tweaks»",
      "status": "in-ticket"
    },
    {
      "id": "R33",
      "text": "«(переключение шрифтов,»",
      "status": "in-ticket"
    },
    {
      "id": "R34",
      "text": "«оттенков фона,»",
      "status": "in-ticket"
    },
    {
      "id": "R35",
      "text": "«масштаба»",
      "status": "in-ticket"
    },
    {
      "id": "R36",
      "text": "«и картинок)»",
      "status": "in-ticket"
    },
    {
      "id": "R37",
      "text": "«Статика HTML/CSS/JS» (ответ на init, PRODUCT.md § Stack)",
      "status": "in-ticket"
    },
    {
      "id": "R38i",
      "text": "(подразумевается) сайт открывается и читается на телефоне и ноутбуке жюри",
      "status": "in-ticket"
    },
    {
      "id": "R39i",
      "text": "(подразумевается) интерактив доступен с клавиатуры и уважает prefers-reduced-motion",
      "status": "in-ticket"
    },
    {
      "id": "R40i",
      "text": "(подразумевается) «сырой кадр» и «распознавание» нужно чем-то показать",
      "status": "in-ticket"
    }
  ],
  "gates": {
    "G1": {
      "ok": true,
      "at": "2026-11-14T12:11:33+03:00",
      "open": 0,
      "total": 40
    },
    "G2": {
      "ok": true,
      "at": "2026-11-14T12:11:33+03:00",
      "found": 2,
      "fixed": 2,
      "deferred": 0
    },
    "G3": {
      "ok": true,
      "at": "2026-11-14T12:13:02+03:00",
      "problems": 0
    }
  },
  "result": null
}
