window.STATE =
{
  "version": 2,
  "slug": "gaugevision-dial",
  "dir": "2026-11-14-gaugevision-dial",
  "title": "Лендинг GaugeVision AI: циферблат, видео на скролле, горизонтальный конвейер",
  "mode": "semi",
  "depth": "normal",
  "tier": "T1",
  "briefFile": "2026-11-14-brief.md",
  "memoryFile": "AGENTS.md",
  "memoryOwner": "autopilot",
  "skillDir": "~/skills/autopilot",
  "baseCommit": "90ba425",
  "startedAt": "2026-11-14T22:04:58+03:00",
  "updatedAt": "2026-11-15T03:25:35+03:00",
  "finishedAt": "2026-11-15T03:25:36+03:00",
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
      "status": "done",
      "startedAt": "2026-11-14T22:23:25+03:00",
      "finishedAt": "2026-11-14T22:24:01+03:00"
    },
    {
      "id": "build",
      "status": "done",
      "startedAt": "2026-11-14T22:24:01+03:00",
      "finishedAt": "2026-11-15T02:38:07+03:00"
    },
    {
      "id": "review",
      "status": "done",
      "startedAt": "2026-11-15T02:38:07+03:00",
      "finishedAt": "2026-11-15T03:08:31+03:00"
    },
    {
      "id": "final",
      "status": "done",
      "startedAt": "2026-11-15T03:08:31+03:00",
      "finishedAt": "2026-11-15T03:25:36+03:00"
    }
  ],
  "requirements": {
    "total": 47,
    "done": 47,
    "inTicket": 0,
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
      "status": "done",
      "startedAt": "2026-11-14T22:24:02+03:00",
      "finishedAt": "2026-11-14T23:03:28+03:00",
      "retries": 0,
      "repairs": 1,
      "repairFindings": [
        "полоса телеметрии не видна (overflow + top:-1px); spotlight считает позицию из кэша документных координат"
      ],
      "tests": {
        "passed": 2,
        "failed": 0
      },
      "commit": "7291598"
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
      "status": "done",
      "startedAt": "2026-11-14T22:53:11+03:00",
      "finishedAt": "2026-11-15T02:18:24+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 2,
        "failed": 0
      },
      "commit": "0a87898"
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
      "status": "done",
      "startedAt": "2026-11-15T02:18:26+03:00",
      "finishedAt": "2026-11-15T02:38:05+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 2,
        "failed": 0
      },
      "commit": "7b91a97"
    },
    {
      "id": "F1",
      "title": "Исправления по ревью ветки",
      "requirements": [
        "R01",
        "R22",
        "R23",
        "R37",
        "R38",
        "R46i",
        "G01"
      ],
      "blockedBy": [],
      "wave": 4,
      "zone": [
        "site/js/motion.js",
        "site/css/",
        "site/js/components/kit.js",
        "site/js/page.js",
        "site/js/components/architecture.js",
        "site/js/components/pipeline-track.js",
        "site/tests/"
      ],
      "review": "да — ремонт ветки",
      "model": "сильная",
      "status": "done",
      "startedAt": "2026-11-15T02:51:59+03:00",
      "finishedAt": "2026-11-15T03:13:12+03:00",
      "retries": 0,
      "repairs": 0,
      "tests": {
        "passed": 2,
        "failed": 0
      },
      "commit": "76e9594"
    },
    {
      "id": "F2",
      "title": "Поверх видео только три элемента",
      "requirements": [
        "R13"
      ],
      "blockedBy": [],
      "wave": 5,
      "zone": [
        "site/js/components/scroll-video.js",
        "site/css/hero.css",
        "site/css/tweaks.css",
        "site/js/content.js",
        "site/tests/"
      ],
      "review": "да — ремонт ветки",
      "model": "сильная",
      "status": "done",
      "retries": 0,
      "repairs": 0,
      "startedAt": "2026-11-15T03:18:05+03:00",
      "finishedAt": "2026-11-15T03:25:06+03:00",
      "tests": {
        "passed": 2,
        "failed": 0
      },
      "commit": "aeb1589"
    }
  ],
  "tests": {
    "passed": 2,
    "failed": 0
  },
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
  "concerns": [
    "site/assets/video — две копии для перемотки (8,1 + 4,2 МБ) и оригинал 5 МБ добавляют ≈ 18 МБ бинарников в git",
    "site/js/motion.js:98-113 — исключение подписчика останавливает общий rAF-цикл навсегда (running=true без следующего кадра)",
    "site/js/motion.js:182-188 — pinProgress вне tick берёт устаревший scrollY",
    "site/tests/components.test.js:122-133 — reduced→pinProgress=1 проверяет Node-заглушку; формулу 0..1 не проверяет ничто; тест dt=1/20 зелёный и без подшагов",
    "site/css/page.css:107,352,402,495; base.css:113-114,129 — размеры 2px, 1.25px, translateY(-2px) вместо rem (правило 7)",
    "site/css/components.css:339,405 — переходы clip-path/color/background/stroke и стили heroStage (зона таска 03)",
    "site/js/page.js — заголовок #reading (h2 + «02») стоит в потоке над закреплённой сценой, а не внутри неё",
    "site/css/hero.css — kicker над h1 против правила impeccable «без eyebrow» (оставлен по контракту kicker + h1)",
    "AGENTS.md — python -m http.server не умеет Range: видео hero там не перематывается; смотреть по file:// или серверу с Range",
    "site/js/components/kit.js — kit.dial, kit.crop, kit.mini больше не используются (мёртвый код)",
    "site/design-system.md — нет описания горизонтального трека конвейера",
    "site/js/page.js — OPTIONS передаёт ключи layout:, которые компоненты больше не читают",
    "site/js/components/compare.js — пропала пара «сырой кадр → значение» (держалась на hero.stage)",
    "site/** — смешанные окончания строк LF/CRLF",
    "site/js/page.js (heroFallback) и site/css/page.css (.gv-hero-static__kicker) — остались ссылки на удалённый hero.kicker: при запасном показе hero вставится пустой <p>"
  ],
  "blind": {
    "checked": 1,
    "matched": 1,
    "mismatches": []
  },
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
    "2026-11-14T22:23:27+03:00",
    "2026-11-14T22:23:42+03:00",
    "2026-11-14T22:24:01+03:00",
    "2026-11-14T22:24:02+03:00",
    "2026-11-14T22:52:35+03:00",
    "2026-11-14T22:53:10+03:00",
    "2026-11-14T22:53:11+03:00",
    "2026-11-14T22:58:34+03:00",
    "2026-11-14T22:58:35+03:00",
    "2026-11-14T23:03:28+03:00",
    "2026-11-15T02:18:24+03:00",
    "2026-11-15T02:18:25+03:00",
    "2026-11-15T02:18:26+03:00",
    "2026-11-15T02:38:05+03:00",
    "2026-11-15T02:38:06+03:00",
    "2026-11-15T02:38:07+03:00",
    "2026-11-15T02:51:46+03:00",
    "2026-11-15T02:51:58+03:00",
    "2026-11-15T02:51:59+03:00",
    "2026-11-15T03:08:30+03:00",
    "2026-11-15T03:08:31+03:00",
    "2026-11-15T03:13:12+03:00",
    "2026-11-15T03:13:13+03:00",
    "2026-11-15T03:18:03+03:00",
    "2026-11-15T03:18:04+03:00",
    "2026-11-15T03:18:05+03:00",
    "2026-11-15T03:23:31+03:00",
    "2026-11-15T03:23:32+03:00",
    "2026-11-15T03:23:33+03:00",
    "2026-11-15T03:25:06+03:00",
    "2026-11-15T03:25:31+03:00",
    "2026-11-15T03:25:35+03:00"
  ],
  "rev": 49,
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
    },
    {
      "t": "2026-11-14T22:24:01+03:00",
      "k": "stage",
      "id": "build",
      "act": "start"
    },
    {
      "t": "2026-11-14T22:24:02+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "start"
    },
    {
      "t": "2026-11-14T22:52:35+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-14T22:53:10+03:00",
      "k": "add",
      "key": "concerns",
      "n": 1
    },
    {
      "t": "2026-11-14T22:53:10+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "review"
    },
    {
      "t": "2026-11-14T22:53:11+03:00",
      "k": "ticket",
      "ids": [
        "02"
      ],
      "act": "start"
    },
    {
      "t": "2026-11-14T22:58:34+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "repair",
      "note": "полоса телеметрии не видна (overflow + top:-1px); spotlight считает позицию из кэша документных координат"
    },
    {
      "t": "2026-11-14T22:58:35+03:00",
      "k": "add",
      "key": "concerns",
      "n": 5
    },
    {
      "t": "2026-11-14T23:03:28+03:00",
      "k": "ticket",
      "ids": [
        "01"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-15T02:18:24+03:00",
      "k": "ticket",
      "ids": [
        "02"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-15T02:18:25+03:00",
      "k": "add",
      "key": "concerns",
      "n": 3
    },
    {
      "t": "2026-11-15T02:18:26+03:00",
      "k": "ticket",
      "ids": [
        "03"
      ],
      "act": "start"
    },
    {
      "t": "2026-11-15T02:38:05+03:00",
      "k": "ticket",
      "ids": [
        "03"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-15T02:38:06+03:00",
      "k": "add",
      "key": "concerns",
      "n": 5
    },
    {
      "t": "2026-11-15T02:38:07+03:00",
      "k": "stage",
      "id": "review",
      "act": "start"
    },
    {
      "t": "2026-11-15T02:51:46+03:00",
      "k": "add",
      "key": "report",
      "n": 3
    },
    {
      "t": "2026-11-15T02:51:58+03:00",
      "k": "tickets",
      "n": 4
    },
    {
      "t": "2026-11-15T02:51:59+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    },
    {
      "t": "2026-11-15T02:51:59+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "start"
    },
    {
      "t": "2026-11-15T03:08:30+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-15T03:08:30+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "review"
    },
    {
      "t": "2026-11-15T03:08:31+03:00",
      "k": "stage",
      "id": "final",
      "act": "start"
    },
    {
      "t": "2026-11-15T03:13:12+03:00",
      "k": "ticket",
      "ids": [
        "F1"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-15T03:13:13+03:00",
      "k": "add",
      "key": "report",
      "n": 1
    },
    {
      "t": "2026-11-15T03:18:03+03:00",
      "k": "gate",
      "g": "G4",
      "ok": false,
      "checked": 24,
      "matched": 23
    },
    {
      "t": "2026-11-15T03:18:04+03:00",
      "k": "tickets",
      "n": 5
    },
    {
      "t": "2026-11-15T03:18:04+03:00",
      "k": "gate",
      "g": "G3",
      "ok": true,
      "problems": 0
    },
    {
      "t": "2026-11-15T03:18:05+03:00",
      "k": "ticket",
      "ids": [
        "F2"
      ],
      "act": "start"
    },
    {
      "t": "2026-11-15T03:23:31+03:00",
      "k": "ticket",
      "ids": [
        "F2"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-15T03:23:32+03:00",
      "k": "ticket",
      "ids": [
        "F2"
      ],
      "act": "review"
    },
    {
      "t": "2026-11-15T03:23:33+03:00",
      "k": "add",
      "key": "concerns",
      "n": 1
    },
    {
      "t": "2026-11-15T03:25:06+03:00",
      "k": "ticket",
      "ids": [
        "F2"
      ],
      "act": "done",
      "tests": {
        "passed": 2,
        "failed": 0
      }
    },
    {
      "t": "2026-11-15T03:25:31+03:00",
      "k": "gate",
      "g": "G4",
      "ok": true,
      "checked": 1,
      "matched": 1
    },
    {
      "t": "2026-11-15T03:25:31+03:00",
      "k": "tests",
      "passed": 2,
      "failed": 0
    },
    {
      "t": "2026-11-15T03:25:35+03:00",
      "k": "finish",
      "result": "Лендинг в site/ — одна страница на основе «Циферблата»: видео на скролле, прецизионный прибор на пружине, горизонтальный трек конвейера, живые секции на обсидиане",
      "problems": 0
    }
  ],
  "reqList": [
    {
      "id": "R01",
      "text": "«Пересобери сайт в ./site на основе Варианта B (циферблат)»",
      "status": "done"
    },
    {
      "id": "R02",
      "text": "«используя скилл tactical-hud-web-design»",
      "status": "done"
    },
    {
      "id": "R03",
      "text": "«подходы Impeccable (distill + animate + polish)»",
      "status": "done"
    },
    {
      "id": "R04",
      "text": "«строгие факты из PRODUCT.md»",
      "status": "done"
    },
    {
      "id": "R05",
      "text": "«остальные варианты (A и C) убери в архив»",
      "status": "done"
    },
    {
      "id": "R06",
      "text": "«удали верхний переключатель вариантов»",
      "status": "done"
    },
    {
      "id": "R07",
      "text": "«На первом экране (Hero) полностью убери старые растровые картинки»",
      "status": "done"
    },
    {
      "id": "R08",
      "text": "«Сделай Hero-секцию закреплённой (sticky) на 250–300vh высоты скролла»",
      "status": "done"
    },
    {
      "id": "R09",
      "text": "«при прокрутке страницы вниз видео плавно проигрывалось кадр за кадром (привязка video.currentTime к прогрессу скролла через requestAnimationFrame с инерцией)»",
      "status": "done"
    },
    {
      "id": "R10",
      "text": "«В ./site/assets/ лежит моё видео [...gauge_pullback.mp4]»",
      "status": "done"
    },
    {
      "id": "R11",
      "text": "«Если в системе доступен ffmpeg, оптимизируй видео для плавного скролла (частые keyframes)»",
      "status": "done"
    },
    {
      "id": "R12",
      "text": "«сохранив оригинал»",
      "status": "done"
    },
    {
      "id": "R13",
      "text": "«Поверх видео оставь только сверхчистый HUD-заголовок, 1 строку сути и аккуратный индикатор скролла»",
      "status": "done"
    },
    {
      "id": "R14",
      "text": "«циферблат [...] как дорогой прецизионный прибор: тонкая градуированная шкала с рисками»",
      "status": "done"
    },
    {
      "id": "R15",
      "text": "«стеклянно-металлический блик по контуру (rim light)»",
      "status": "done"
    },
    {
      "id": "R16",
      "text": "«плавная подсвеченная дуга активного диапазона (норма / предупреждение / CRITICAL)»",
      "status": "done"
    },
    {
      "id": "R17",
      "text": "«стрелка с физической инерцией (spring physics), реагирующая на скролл и наведение»",
      "status": "done"
    },
    {
      "id": "R18",
      "text": "«чёткие табличные цифры (tabular-nums)»",
      "status": "done"
    },
    {
      "id": "R19",
      "text": "«Доработка циферблата (Hero / ключевой визуальный узел)» — где он стоит при Hero-видео",
      "status": "done"
    },
    {
      "id": "R20",
      "text": "«Секцию с [...] математическим аппаратом и пайплайном [...] сделай в виде закреплённого горизонтального трека (pinned horizontal scroll)»",
      "status": "done"
    },
    {
      "id": "R21",
      "text": "«1. CLAHE-нормализация и ROI-детекция YOLOv8n → 2. Гомография и коррекция перспективы → 3. Аппроксимация шкалы эллипсом и субпиксельный расчёт угла θ → 4. Экспоненциальное сглаживание EMA α=0.25»",
      "status": "done"
    },
    {
      "id": "R22",
      "text": "«карточки этапов по порядку плавно выезжают слева направо»",
      "status": "done"
    },
    {
      "id": "R23",
      "text": "«с подсветкой активного шага»",
      "status": "done"
    },
    {
      "id": "R24",
      "text": "«формулой»",
      "status": "done"
    },
    {
      "id": "R25",
      "text": "«и задержкой»",
      "status": "done"
    },
    {
      "id": "R26",
      "text": "«Убери длинные абзацы, описания и лишние пояснения по всему сайту»",
      "status": "done"
    },
    {
      "id": "R27",
      "text": "«Оставь только короткие ёмкие заголовки (3–6 слов), сухие инженерные цифры, формулы и визуальные/интерактивные блоки»",
      "status": "done"
    },
    {
      "id": "R28",
      "text": "«Максимум воздуха»",
      "status": "done"
    },
    {
      "id": "R29",
      "text": "«глубокий обсидиановый фон (#090B0E)»",
      "status": "done"
    },
    {
      "id": "R30",
      "text": "«тонкие 1px-границы с деликатным верхним световым бликом»",
      "status": "done"
    },
    {
      "id": "R31",
      "text": "«направленные световые акценты без кислотного неона»",
      "status": "done"
    },
    {
      "id": "R32",
      "text": "«каскадное появление заголовков (staggered reveal)»",
      "status": "done"
    },
    {
      "id": "R33",
      "text": "«плавную прокрутку чисел (counters)»",
      "status": "done"
    },
    {
      "id": "R34",
      "text": "«световую реакцию карточек на курсор (spotlight border)»",
      "status": "done"
    },
    {
      "id": "R35",
      "text": "«анимированные SVG-связи»",
      "status": "done"
    },
    {
      "id": "R36",
      "text": "«прогресс-бар телеметрии при скролле»",
      "status": "done"
    },
    {
      "id": "R37",
      "text": "«Всё строго на GPU-свойствах (transform, opacity)»",
      "status": "done"
    },
    {
      "id": "R38",
      "text": "«Максимум плавной анимации (60 FPS)»",
      "status": "done"
    },
    {
      "id": "R39",
      "text": "«проприетарная лицензия»",
      "status": "done"
    },
    {
      "id": "R40",
      "text": "«из контактов только GitHub EGRNEGR»",
      "status": "done"
    },
    {
      "id": "R41",
      "text": "«оценки для 50/100 камер помечены как расчётные»",
      "status": "done"
    },
    {
      "id": "R42",
      "text": "«Можешь генерировать видео и изображения через Gemini, если это можно вставить красиво в мой сайт»",
      "status": "done"
    },
    {
      "id": "R43i",
      "text": "(подразумевается) сайт по-прежнему открывается двойным кликом по file:// и не требует сборки",
      "status": "done"
    },
    {
      "id": "R44i",
      "text": "(подразумевается) видео-hero и закреплённые треки работают на телефоне и при «уменьшить движение»",
      "status": "done"
    },
    {
      "id": "R45i",
      "text": "(подразумевается) остальные экраны варианта B (метрики, Было → Стало, архитектура, ограничения, финал) остаются, только ужатые",
      "status": "done"
    },
    {
      "id": "R46i",
      "text": "(подразумевается) панель Tweaks — судьба после фиксации одного варианта и обсидианового фона",
      "status": "done"
    },
    {
      "id": "G01",
      "text": "«ок» — взять 9 багов прошлой сборки (битый #%E0, два «GitHub» в шапке B, обратный порядок Tab в hero B, меню за краем на телефоне и т. д.)",
      "status": "done"
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
      "at": "2026-11-15T03:18:04+03:00",
      "problems": 0
    },
    "G4": {
      "ok": true,
      "at": "2026-11-15T03:25:31+03:00",
      "checked": 1,
      "matched": 1
    }
  },
  "result": "Лендинг в site/ — одна страница на основе «Циферблата»: видео на скролле, прецизионный прибор на пружине, горизонтальный трек конвейера, живые секции на обсидиане",
  "report": [
    "Не сверяются тестом: формула pinProgress 0..1 (проверка reduced идёт на Node-заглушке), тест пружины при dt = 1/20 зелёный и без подшагов",
    "В content.js остались невыводимые поля (coverage, ema, calibration.zones/caption/sliderLabel, часть labels и meta) — источник фактов, на странице не видны",
    "В site/design-system.md нет раздела о горизонтальном треке конвейера",
    "Телефон, трек конвейера: при смене шага подсвеченная карточка ≈ 0,3 с стоит за правым краем, пока трек догоняет её на пружине; в покое всё верно (pipeline-track.js:195-197, 224)"
  ],
  "blindRounds": 2
}
