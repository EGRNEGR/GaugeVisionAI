#!/usr/bin/env node
/*
 * Проверка расчётов, которые компоненты показывают на сайте (без браузера и зависимостей).
 * Запуск из корня репозитория: node site/tests/components.test.js
 * Ожидаемые значения — из спецификации (история 12, тикет 02) и разобраны вручную по
 * angle_to_value / classify_level в app/vision.py (notes.md §1.6, §1.8).
 * GV.motion: пружина стрелки (жёсткость 170, демпфирование 18 — спецификация, история 15)
 * и поведение при «уменьшить движение» (interfaces.md, правило 9).
 * Лист 02: время ролика по прокрутке и окно, в котором обходчик не видит отклонение;
 * лист 04: шаг операции по прокрутке; лист 01: время строк журнала и общее показание стрелки.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SITE = path.resolve(__dirname, '..');
const FILES = ['js/content.js', 'js/util.js', 'js/motion.js', 'js/components/kit.js',
  'js/components/shift.js', 'js/components/precision-dial.js', 'js/components/operations.js'];

function load(box) {
  vm.createContext(box);
  FILES.forEach((rel) => {
    const file = path.join(SITE, rel);
    if (!fs.existsSync(file)) return;
    vm.runInContext(fs.readFileSync(file, 'utf8'), box, { filename: file });
  });
  return box;
}

const sandbox = { console };
sandbox.window = sandbox;
load(sandbox);

const failures = [];
const eq = (name, actual, expected) => {
  if (actual !== expected) failures.push(`${name}: ожидалось ${expected}, получено ${actual}`);
};

const kit = sandbox.GV && sandbox.GV.kit;
if (!kit || typeof kit.angleToValue !== 'function') {
  console.log('FAIL: нет GV.kit.angleToValue (site/js/components/kit.js)');
  process.exit(1);
}

const r2 = (v) => Math.round(v * 100) / 100;
const calib = sandbox.GV.content.calibration;

// Шкала 0–10 МПа по часовой. Углы сайта — от «6 часов»: θmin = 45°, θmax = 315°
// (в кадре приложения те же точки — 135° и 45°, история 12)
eq('θ = 163,4° → МПа', r2(kit.angleToValue(163.4, calib)), 4.39);
eq('θ = 45° → МПа', r2(kit.angleToValue(45, calib)), 0);
eq('θ = 315° → МПа', r2(kit.angleToValue(315, calib)), 10);
eq('θ = 180° → МПа', r2(kit.angleToValue(180, calib)), 5);
// «Мёртвая зона»: ближе к максимуму — перелёт, ограниченный +5 % диапазона
eq('θ = 330° → МПа (перелёт, clamp)', r2(kit.angleToValue(330, calib)), 10.5);
// ближе к минимуму — недолёт, ограниченный −5 %
eq('θ = 30° → МПа (недолёт, clamp)', r2(kit.angleToValue(30, calib)), -0.5);
// Против часовой: та же шкала зеркально
eq('CCW θ = 315° → МПа', r2(kit.angleToValue(315, Object.assign({}, calib, { direction: 'CCW', thetaMin: 315, thetaMax: 45 }))), 0);
// Отсчёт сайта — это угол кадра минус 90°: формула не зависит от того, откуда считать
eq('кадр 253,4° / 135° / 45° → МПа', r2(kit.angleToValue(253.4, Object.assign({}, calib, { thetaMin: 135, thetaMax: 45 }))), 4.39);

// Бары: 1 МПа = 10 бар
eq('4,39 МПа → бар', r2(kit.toBar(kit.angleToValue(163.4, calib), calib)), 43.85);

// Зоны уставок LL 1 · L 2 · H 8 · HH 9 (classify_level: границы включены)
const sp = calib.setpoints;
eq('V = 0,5 → зона', kit.zoneOf(0.5, sp), 'LL');
eq('V = 1 → зона', kit.zoneOf(1, sp), 'LL');
eq('V = 1,5 → зона', kit.zoneOf(1.5, sp), 'L');
eq('V = 2 → зона', kit.zoneOf(2, sp), 'L');
eq('V = 4,39 → зона', kit.zoneOf(4.39, sp), 'NORMA');
eq('V = 8 → зона', kit.zoneOf(8, sp), 'H');
eq('V = 9 → зона', kit.zoneOf(9, sp), 'HH');
eq('V = 4,39 → статус', kit.levelOf(4.39, sp), 'normal');
eq('V = 8,5 → статус', kit.levelOf(8.5, sp), 'warning');
eq('V = 9,4 → статус', kit.levelOf(9.4, sp), 'alert');

// EMA α = 0,25: первое значение как есть, затем V̄ = α·V + (1 − α)·V̄
eq('EMA первый отсчёт', kit.emaStep(null, 4, 0.25), 4);
eq('EMA шаг 4 → 8', kit.emaStep(4, 8, 0.25), 5);

// Обратное преобразование для дуг уставок: 5 МПа → 180° (стрелка вверх)
eq('5 МПа → θ', r2(kit.valueToAngle(5, calib)), 180);

// Формула вёрсткой: «a / b» — дробь, у скобочной группы скобки снимаются, Vmin → V с индексом min
const tree = kit.mathTree('V = Vmin + ((θ − θmin) mod 360) / span · (Vmax − Vmin)');
const fracs = tree.filter((n) => n.t === 'frac');
eq('формула: одна дробь', fracs.length, 1);
eq('формула: знаменатель — span', fracs.length && fracs[0].den.map((n) => n.v).join(''), 'span');
eq('формула: числитель без внешних скобок', fracs.length && fracs[0].num[0].t, 'group');
eq('формула: индексы min / max', (JSON.stringify(tree).match(/"t":"sub"/g) || []).length, 4);
eq('формула без пробелов у «/»', kit.mathTree('((θ−θmin) mod 360)/span·(Vmax−Vmin)').filter((n) => n.t === 'frac').length, 1);
const slotTree = kit.mathTree('V = (({theta} − 45°) mod 360) / 270 = {V}');
eq('формула: слоты', slotTree.filter((n) => n.t === 'slot').map((n) => n.name).join(','), 'V');
eq('формула: слот в числителе', JSON.stringify(slotTree).indexOf('"name":"theta"') > 0, true);
eq('формула: дроби внутри скобок', JSON.stringify(kit.mathTree('diag(R/a, R/b)')).split('"frac"').length - 1, 2);

/* ---------- GV.motion ---------- */

const motion = sandbox.GV.motion;
if (!motion || typeof motion.spring !== 'function') {
  failures.push('нет GV.motion.spring (site/js/motion.js)');
} else {
  // Скачок цели 0 → 253,4° (стрелка от θmin до 4,39 МПа). Пружина успокаивается у цели
  // (отклонение < 0,1°, скорость < 0,5 °/с) меньше чем за 2 с модельного времени.
  const settle = (dt) => {
    const s = motion.spring({ stiffness: 170, damping: 18, value: 0 });
    s.target(253.4);
    let t = 0;
    let peak = 0;
    let settledAt = null;
    while (t < 4) {
      const v = s.step(dt);
      t += dt;
      peak = Math.max(peak, Math.abs(v));
      if (settledAt === null && s.settled()) settledAt = t;
    }
    return { value: s.value(), peak, settledAt, settled: s.settled() };
  };
  const at60 = settle(1 / 60);
  if (!(at60.settledAt !== null && at60.settledAt < 2)) failures.push(`spring при dt = 1/60 не успокоился за 2 с (успокоился на ${at60.settledAt})`);
  if (Math.abs(at60.value - 253.4) > 0.1) failures.push(`spring при dt = 1/60 остановился на ${at60.value}, ожидалось 253,4`);
  // Длинный кадр (dt = 1/20 — потолок dt в onFrame): не разносит и сходится к той же цели.
  const at20 = settle(1 / 20);
  if (!isFinite(at20.value) || at20.peak > 253.4 * 1.5) failures.push(`spring при dt = 1/20 расходится: пик ${at20.peak}`);
  if (Math.abs(at20.value - 253.4) > 0.1 || !at20.settled) failures.push(`spring при dt = 1/20 не сошёлся: ${at20.value}`);
  if (!(at20.settledAt !== null && at20.settledAt < 2)) failures.push(`spring при dt = 1/20 не успокоился за 2 с (успокоился на ${at20.settledAt})`);
  // set() ставит значение сразу, без движения
  const jump = motion.spring({ value: 0 });
  jump.set(5);
  eq('spring.set(5) → value()', jump.value(), 5);
  eq('spring.set(5) → step()', jump.step(1 / 60), 5);
}

/* ---------- Лист 03 «Показание» и прибор первого листа ---------- */

const comps = sandbox.GV.components || {};
const dialApi = comps.precisionDial;
if (!dialApi || typeof dialApi.clampAngle !== 'function' || typeof dialApi.angleFromPointer !== 'function') {
  failures.push('нет GV.components.precisionDial.clampAngle / angleFromPointer (site/js/components/precision-dial.js)');
} else {
  // Значение сцены: θ 163,4° из reading.theta → 4,39 МПа (в кадре приложения 253,4°, история 11)
  const readingTheta = sandbox.GV.content.reading.theta;
  eq('reading.theta → МПа', r2(kit.angleToValue(dialApi.clampAngle(readingTheta, calib), calib)), 4.39);
  // Курсор: 0° — «6 часов», по часовой, ось Y вниз; 360° = 0° смотрит вниз
  eq('курсор вниз → θ', r2(dialApi.angleFromPointer(0, 1)), 0);
  eq('курсор влево → θ', r2(dialApi.angleFromPointer(-1, 0)), 90);
  eq('курсор вверх → θ', r2(dialApi.angleFromPointer(0, -1)), 180);
  eq('курсор вправо → θ', r2(dialApi.angleFromPointer(1, 0)), 270);
  eq('курсор вниз-вправо → θ', r2(dialApi.angleFromPointer(1, 1)), 315);
  // Внутри шкалы угол не меняется, и вся шкала лежит в одном куске 45°…315° — без шва 360 → 0
  eq('θ 200° внутри шкалы', r2(dialApi.clampAngle(200, calib)), 200);
  eq('θ 300° внутри шкалы', r2(dialApi.clampAngle(300, calib)), 300);
  let seam = false;
  for (let a = 0; a < 360; a += 0.5) {
    const c2 = dialApi.clampAngle(a, calib);
    if (c2 < 45 || c2 > 315) seam = true;
  }
  eq('любой угол курсора → θ в 45°…315°', seam, false);
  // За шкалой (нижний сектор 315°…45° через 0°) угол зажимается к ближнему краю
  eq('θ 330° за шкалой → θmax', r2(dialApi.clampAngle(330, calib)), 315);
  eq('θ 20° за шкалой → θmin', r2(dialApi.clampAngle(20, calib)), 45);
  eq('θ 0° за шкалой → МПа в пределах шкалы', [0, 10].indexOf(r2(kit.angleToValue(dialApi.clampAngle(0, calib), calib))) >= 0, true);
  // При ведении стрелка держится края, у которого стоит: курсор прошёл низ — перелёта через шкалу нет
  eq('ведение у θmax, курсор на 20° → θmax', r2(dialApi.clampAngle(20, calib, 312)), 315);
  eq('ведение у θmin, курсор на 340° → θmin', r2(dialApi.clampAngle(340, calib, 50)), 45);
  eq('ведение: курсор вернулся на шкалу', r2(dialApi.clampAngle(60, calib, 315)), 60);
}

const videoApi = comps.shift;
if (!videoApi || typeof videoApi.timeFor !== 'function' || typeof videoApi.delayHours !== 'function') {
  failures.push('нет GV.components.shift.timeFor / delayHours (site/js/components/shift.js)');
} else {
  // Цель currentTime = прогресс × (длительность − 0,05) — interfaces.md, scrollVideo
  eq('видео: прогресс 0 → 0 с', videoApi.timeFor(0, 10), 0);
  eq('видео: прогресс 1 → 9,95 с', r2(videoApi.timeFor(1, 10)), 9.95);
  eq('видео: прогресс 0,5 → 4,975 с', Math.round(videoApi.timeFor(0.5, 10) * 1000) / 1000, 4.975);
  eq('видео: длительность неизвестна → 0', videoApi.timeFor(0.5, NaN), 0);
  eq('видео: прогресс за пределами → 0', videoApi.timeFor(-0.2, 10), 0);
  // Шкала смены: обходы в 0 и 12 ч (content.compare.timeline)
  const tl = sandbox.GV.content.compare.timeline;
  eq('отклонение в 5 ч → обходчик заметит через 7 ч', videoApi.delayHours(5, tl.rounds, tl.shiftHours), 7);
  eq('отклонение сразу после обхода → 12 ч', videoApi.delayHours(0, tl.rounds, tl.shiftHours), 12);
  eq('отклонение в 11,75 ч → 0,25 ч', videoApi.delayHours(11.75, tl.rounds, tl.shiftHours), 0.25);
  eq('три обхода за смену: 7 ч → 1 ч', videoApi.delayHours(7, [0, 4, 8, 12], 12), 1);
}

const opsApi = comps.operations;
if (!opsApi || typeof opsApi.stepFor !== 'function') {
  failures.push('нет GV.components.operations.stepFor (site/js/components/operations.js)');
} else {
  eq('операции: прогресс 0 → шаг 0', opsApi.stepFor(0, 4), 0);
  eq('операции: прогресс 0,3 → шаг 1', opsApi.stepFor(0.3, 4), 1);
  eq('операции: прогресс 1 → последний шаг', opsApi.stepFor(1, 4), 3);
  eq('операции: прогресс за пределами → шаг 0', opsApi.stepFor(-1, 4), 0);
}

// Время строки журнала: 08:00 + ⅓ с, 3 обработки в секунду
eq('журнал: 08:00 + ⅓ с', kit.clockText(8 * 3600000 + 1000 / 3), '08:00:00,333');
eq('журнал: 08:00 + 2⅔ с', kit.clockText(8 * 3600000 + 8000 / 3), '08:00:02,667');
eq('журнал: переход через сутки', kit.clockText(24 * 3600000 + 5), '00:00:00,005');

// Общее показание: подписчики получают угол и источник, свой же set без изменения — тишина
{
  const r = kit.createReading(253.4);
  const seen = [];
  const commits = [];
  const off = r.on((theta, from) => seen.push(theta + ':' + from));
  r.onCommit((theta) => commits.push(theta));
  r.set(270, 'dial');
  r.set(270, 'dial');
  r.commit();
  off();
  r.set(200, 'hero');
  eq('общее показание: get()', r.get(), 200);
  eq('общее показание: уведомления', seen.join(','), '270:dial');
  eq('общее показание: запись в журнал', commits.join(','), '270');
}

// «Уменьшить движение»: закреплённая секция сразу в конечном состоянии, пружина сразу у цели.
const reducedBox = { console };
reducedBox.window = reducedBox;
reducedBox.matchMedia = (q) => ({ matches: /reduce/.test(q), media: q, addEventListener() {}, addListener() {} });
load(reducedBox);
const rm = reducedBox.GV && reducedBox.GV.motion;
if (!rm || typeof rm.pinProgress !== 'function') {
  failures.push('нет GV.motion.pinProgress (site/js/motion.js)');
} else {
  eq('reduced() при prefers-reduced-motion: reduce', rm.reduced(), true);
  eq('pinProgress при reduced motion', rm.pinProgress({}), 1);
  const s = rm.spring({ value: 0 });
  s.target(253.4);
  eq('spring.step при reduced motion → цель', s.step(1 / 60), 253.4);
}

// Цикл кадра переживает ошибку подписчика: исключение уходит в console.error,
// остальные подписчики этого кадра вызваны, следующий кадр запланирован (ревью ветки, F1).
{
  const queue = [];
  const errors = [];
  const loopBox = {
    console: { log() {}, warn() {}, error: (...args) => errors.push(args) },
    requestAnimationFrame: (fn) => { queue.push(fn); return queue.length; },
    addEventListener() {},
    pageYOffset: 0,
    innerHeight: 900,
    document: { addEventListener() {}, documentElement: { clientWidth: 1440 } }
  };
  loopBox.window = loopBox;
  vm.createContext(loopBox);
  const motionFile = path.join(SITE, 'js/motion.js');
  vm.runInContext(fs.readFileSync(motionFile, 'utf8'), loopBox, { filename: motionFile });
  const lm = loopBox.GV && loopBox.GV.motion;
  if (!lm || typeof lm.onFrame !== 'function' || typeof lm.onScroll !== 'function') {
    failures.push('нет GV.motion.onFrame / onScroll (site/js/motion.js)');
  } else {
    let frameCalls = 0;
    let scrollCalls = 0;
    lm.onScroll(() => { throw new Error('подписчик прокрутки упал'); });
    lm.onScroll(() => { scrollCalls += 1; });
    lm.onFrame(() => { throw new Error('подписчик кадра упал'); });
    lm.onFrame(() => { frameCalls += 1; });
    const run = (now) => {
      const fn = queue.shift();
      if (!fn) return false;
      try { fn(now); } catch (e) { failures.push(`цикл кадра выбросил наружу: ${e.message}`); }
      return true;
    };
    run(16);
    eq('второй подписчик прокрутки вызван после ошибки первого', scrollCalls, 1);
    eq('второй подписчик кадра вызван после ошибки первого', frameCalls, 1);
    eq('следующий кадр запланирован после ошибки', queue.length, 1);
    eq('ошибки подписчиков ушли в console.error', errors.length, 2);
    run(32);
    eq('цикл жив: второй кадр вызвал подписчика', frameCalls, 2);
  }
}

if (failures.length) {
  console.log(failures.join('\n'));
  console.log(`\nFAIL: ${failures.length}`);
  process.exit(1);
}
console.log('OK: калибровка, бары, зоны уставок, EMA, пружина и reduced motion GV.motion, угол курсора прибора, ролик и шкала смены, шаги операций, журнал и общее показание');
