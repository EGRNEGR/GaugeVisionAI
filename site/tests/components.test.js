#!/usr/bin/env node
/*
 * Проверка расчётов, которые компоненты показывают на сайте (без браузера и зависимостей).
 * Запуск из корня репозитория: node site/tests/components.test.js
 * Ожидаемые значения — из спецификации (история 12, тикет 02) и разобраны вручную по
 * angle_to_value / classify_level в app/vision.py (notes.md §1.6, §1.8).
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SITE = path.resolve(__dirname, '..');
const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
['js/content.js', 'js/util.js', 'js/components/kit.js'].forEach((rel) => {
  const file = path.join(SITE, rel);
  if (!fs.existsSync(file)) return;
  vm.runInContext(fs.readFileSync(file, 'utf8'), sandbox, { filename: file });
});

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

if (failures.length) {
  console.log(failures.join('\n'));
  console.log(`\nFAIL: ${failures.length}`);
  process.exit(1);
}
console.log('OK: калибровка, бары, зоны уставок, EMA');
