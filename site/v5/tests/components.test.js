#!/usr/bin/env node
/*
 * Проверка расчётов компонентов site/v5 без браузера и зависимостей.
 * Запуск: node site/v5/tests/components.test.js
 * Проверяет калибровку, уставки, EMA, пружину и reduced motion, ролик/шкалу смены, экономику,
 * прогноз и все 5 контрольных режимов оптимизатора модернизации.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SITE = path.resolve(__dirname, '..');
const FILES = [
  'js/content.js',
  'js/util.js',
  'js/motion.js',
  'js/optimizer-core.js',
  'js/components/kit.js',
  'js/components/draw.js',
  'js/components/journal.js',
  'js/components/shift.js'
];

function load(box) {
  vm.createContext(box);
  FILES.forEach((rel) => {
    const file = path.join(SITE, rel);
    if (fs.existsSync(file)) vm.runInContext(fs.readFileSync(file, 'utf8'), box, { filename: file });
  });
  return box;
}

const sandbox = { console };
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
load(sandbox);

const failures = [];
const eq = (name, actual, expected) => {
  if (actual !== expected) failures.push(`${name}: ожидалось ${expected}, получено ${actual}`);
};
const r2 = (v) => Math.round(v * 100) / 100;

const C = sandbox.GV.content;
const kit = sandbox.GV.kit;
const motion = sandbox.GV.motion;
const core = sandbox.GV.optimizerCore;
const calib = C.calibration;

// Калибровка, зоны, EMA
eq('θ = 163,4° → МПа', r2(kit.angleToValue(163.4, calib)), 4.39);
eq('θ = 45° → 0 МПа', r2(kit.angleToValue(45, calib)), 0);
eq('θ = 315° → 10 МПа', r2(kit.angleToValue(315, calib)), 10);
eq('5 МПа → 180°', r2(kit.valueToAngle(5, calib)), 180);
eq('V = 4,39 → normal', kit.levelOf(4.39, calib.setpoints), 'normal');
eq('V = 8,5 → warning', kit.levelOf(8.5, calib.setpoints), 'warning');
eq('V = 9,4 → alert', kit.levelOf(9.4, calib.setpoints), 'alert');
eq('EMA шаг 4 → 8', kit.emaStep(4, 8, 0.25), 5);
eq('журнал: 08:00 + ⅓ с', kit.clockText(8 * 3600000 + 1000 / 3), '08:00:00,333');

// Углы стрелки journal.js
const jApi = sandbox.GV.components.journal;
eq('курсор вверх → 180°', r2(jApi.angleFromPointer(0, -1)), 180);
eq('ведение у θmax, курсор 20° → 315°', r2(jApi.clampAngle(20, calib, 312)), 315);

// Смена и экономика
const shApi = sandbox.GV.components.shift;
eq('видео 0,5 от 10 с', Math.round(shApi.timeFor(0.5, 10) * 1000) / 1000, 4.975);
eq('отклонение в 5 ч → 7 ч до обхода', shApi.delayHours(5, [0, 12], 12), 7);
const eco = shApi.computeEconomics({ points: 120, sensorCost: 104880, perCamera: 4, cameraCost: 33000, serverCost: 400000, opexSensor: 8000, opexCamera: 8000, priority: 20, years: 5 });
eq('экономика: приоритетных замен', eco.nRep, 24);
eq('экономика: камер на 96 приборов', eco.cams, 24);

// Оптимизатор модернизации: все 5 контрольных случаев брифа
const cands = core.candidates(C.fleet, C.catalog, C.panel);
const r450 = core.solve(cands, { budget: 450000, objective: 'max_risk_reduction' });
eq('450 тыс., риск: статус', r450.status, 'optimal');
eq('450 тыс., риск: состав', r450.picked.slice().sort().join(','), 'PI-101,PI-102,PI-104,PI-107');
eq('450 тыс., риск: CAPEX', r450.capex, 383040);

const r300r = core.solve(cands, { budget: 300000, objective: 'max_risk_reduction' });
eq('300 тыс., риск: CAPEX', r300r.capex, 296400);

const r300n = core.solve(cands, { budget: 300000, objective: 'max_net_effect' });
eq('300 тыс., экономический эффект: CAPEX', r300n.capex, 278160);

const r100 = core.solve(cands, { budget: 100000, objective: 'max_risk_reduction' });
eq('100 тыс.: infeasible', r100.status, 'infeasible');
eq('100 тыс.: дефицит', r100.deficit, 4880);

const r800 = core.solve(cands, { budget: 800000, objective: 'weighted_utility' });
eq('800 тыс.: CAPEX', r800.capex, 791160);

// Прогнозная модель
const fm = sandbox.GV.draw.forecastModel(C.forecast);
eq('прогноз t=0 совпадает с now', r2(fm.model(0)), 1.21);

// Reduced motion
const redBox = { console };
redBox.window = redBox;
redBox.globalThis = redBox;
redBox.matchMedia = (q) => ({ matches: /reduce/.test(q), media: q, addEventListener() {}, addListener() {} });
load(redBox);
eq('reduced() включён', redBox.GV.motion.reduced(), true);
const sp = redBox.GV.motion.spring({ value: 0 });
sp.target(180);
eq('spring при reduced motion сразу у цели', sp.step(1 / 60), 180);

if (failures.length) {
  console.log(failures.join('\n'));
  console.log(`\nFAIL: ${failures.length}`);
  process.exit(1);
}
console.log('OK: калибровка, зоны, EMA, углы, смена, экономика, 5 режимов оптимизатора, прогноз и reduced motion');
