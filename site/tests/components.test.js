#!/usr/bin/env node
/*
 * Проверка расчётов, которые компоненты показывают на сайте (без браузера и зависимостей).
 * Запуск из корня репозитория: node site/tests/components.test.js
 * Ожидаемые значения — из спецификации (история 12, тикет 02) и разобраны вручную по
 * angle_to_value / classify_level в app/vision.py (notes.md §1.6, §1.8).
 * GV.motion: пружина стрелки (жёсткость 170, демпфирование 18 — спецификация, история 15)
 * и поведение при «уменьшить движение» (interfaces.md, правило 9).
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SITE = path.resolve(__dirname, '..');
const FILES = ['js/content.js', 'js/util.js', 'js/motion.js', 'js/components/kit.js'];

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

// Шкала 0–10 МПа, θmin = 135°, θmax = 45°, по часовой (спецификация, история 12)
eq('θ = 253,4° → МПа', r2(kit.angleToValue(253.4, calib)), 4.39);
eq('θ = 135° → МПа', r2(kit.angleToValue(135, calib)), 0);
eq('θ = 45° → МПа', r2(kit.angleToValue(45, calib)), 10);
eq('θ = 270° → МПа', r2(kit.angleToValue(270, calib)), 5);
// «Мёртвая зона»: ближе к максимуму — перелёт, ограниченный +5 % диапазона
eq('θ = 60° → МПа (перелёт, clamp)', r2(kit.angleToValue(60, calib)), 10.5);
// ближе к минимуму — недолёт, ограниченный −5 %
eq('θ = 120° → МПа (недолёт, clamp)', r2(kit.angleToValue(120, calib)), -0.5);
// Против часовой: та же шкала зеркально
eq('CCW θ = 45° → МПа', r2(kit.angleToValue(45, Object.assign({}, calib, { direction: 'CCW', thetaMin: 45, thetaMax: 135 }))), 0);

// Бары: 1 МПа = 10 бар
eq('4,39 МПа → бар', r2(kit.toBar(kit.angleToValue(253.4, calib), calib)), 43.85);

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

// Обратное преобразование для дуг уставок: 5 МПа → 270°
eq('5 МПа → θ', r2(kit.valueToAngle(5, calib)), 270);

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

if (failures.length) {
  console.log(failures.join('\n'));
  console.log(`\nFAIL: ${failures.length}`);
  process.exit(1);
}
console.log('OK: калибровка, бары, зоны уставок, EMA, пружина и reduced motion GV.motion');
