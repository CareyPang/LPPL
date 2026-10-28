'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const enginePath = path.join(root, 'web/app/engine.js');
const injectionPoint = '  global.OD = OD;';
let source = fs.readFileSync(enginePath, 'utf8');
const occurrences = source.split(injectionPoint).length - 1;
if (occurrences !== 1) {
  throw new Error(`Expected exactly one "${injectionPoint}" in ${enginePath}; found ${occurrences}`);
}
source = source.replace(
  injectionPoint,
  '  OD._internal = { makeWS, linFit, solveBeta, de, nelderMead, fitWindow, FILTERS };\n' +
    injectionPoint,
);
const fitMarker = '    fit.ds = FILTERS.ds(fit);';
const fitOccurrences = source.split(fitMarker).length - 1;
if (fitOccurrences !== 1) {
  throw new Error(`Expected exactly one fit marker in ${enginePath}; found ${fitOccurrences}`);
}
source = source.replace(
  fitMarker,
  '    fit._deSse = r1.f;\n    fit._nmSse = r2.f;\n' + fitMarker,
);

const context = {
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  Math,
  Date,
  Promise,
  Array,
  Object,
  Number,
  String,
  Boolean,
  Map,
  Set,
  WeakMap,
  WeakSet,
  JSON,
  RegExp,
  Error,
  TypeError,
  RangeError,
  Float32Array,
  Float64Array,
  Int8Array,
  Int16Array,
  Int32Array,
  Uint8Array,
  Uint8ClampedArray,
  Uint16Array,
  Uint32Array,
  parseInt,
  parseFloat,
  isFinite,
  Infinity,
  NaN,
  global: null,
};
context.global = context;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: enginePath });

function finiteOrNull(value) {
  if (typeof value === 'number' && !Number.isFinite(value)) return null;
  if (ArrayBuffer.isView(value)) return Array.from(value, finiteOrNull);
  if (Array.isArray(value)) return value.map(finiteOrNull);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, finiteOrNull(item)]));
  }
  return value;
}

function linfit(job) {
  const { makeWS, linFit, solveBeta } = context.OD._internal;
  const results = job.cases.map(({ y, tc, m, w, k = 4 }) => {
    const ws = makeWS(y);
    const sse = linFit(ws, tc, m, w, k);
    const beta = Number.isFinite(sse) ? solveBeta(ws, k) : null;
    return finiteOrNull({ sse, beta });
  });
  return { results };
}

function fitwindow(job) {
  const { fitWindow } = context.OD._internal;
  const defaultOpt = { pop: 24, gens: 45, nm: 120, keepWS: false };
  const results = job.cases.map(({ y, opt = defaultOpt, seed = 0 }) => {
    const started = process.hrtime.bigint();
    const fit = fitWindow(y, opt, context.OD.rng(seed));
    const elapsed = Number(process.hrtime.bigint() - started) / 1e9;
    const fields = [
      'n', 'tc', 'ahead', 'm', 'w', 'A', 'B', 'C1', 'C2', 'D', 'O', 'R2',
      'sse', 'ssePow', 'Fstat', 'pF', 'ds', 'strict', '_deSse', '_nmSse',
    ];
    const result = Object.fromEntries(fields
      .filter((field) => Object.hasOwn(fit, field))
      .map((field) => [field, fit[field]]));
    result.seconds = elapsed;
    return finiteOrNull(result);
  });
  return { results };
}

try {
  const input = fs.readFileSync(0, 'utf8');
  const job = JSON.parse(input);
  let result;
  if (job.type === 'linfit') result = linfit(job);
  else if (job.type === 'fitwindow') result = fitwindow(job);
  else throw new Error(`Unsupported job type: ${job.type}`);
  process.stdout.write(JSON.stringify(finiteOrNull(result)));
} catch (error) {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
}
