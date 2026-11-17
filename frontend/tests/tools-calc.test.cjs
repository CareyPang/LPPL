'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const T = require('../app/tools-calc.js');
const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps * Math.max(1, Math.abs(b)), `${a} vs ${b}`);

test('fx: amount × rate, per-100 bank quote, inverse', () => {
  close(T.fx(100, 7.2).converted, 720);
  close(T.fx(100, 720, 100).converted, 720);
  close(T.fx(720, 7.2).back, 100);
  close(T.fx(1, 8).inverseRate, 0.125);
  assert.equal(T.fx(1, 0).status, 'invalid_input');
});
test('cross rate via common base', () => {
  // EUR→USD 1.08, EUR→CNY 7.776 → USD→CNY 7.2
  close(T.crossRate(1.08, 7.776).rate, 7.2);
});
test('mass and temperature', () => {
  close(T.mass(1, 'ozt', 'g').value, 31.1034768);
  close(T.mass(1, 'kg', 'ozt').value, 1000 / 31.1034768);
  close(T.mass(1, 'tael_hk', 'g').value, 37.429);
  close(T.mass(2, 'liang', 'g').value, 100);
  close(T.temperature(100, 'C', 'F').value, 212);
  close(T.temperature(32, 'F', 'K').value, 273.15);
  assert.equal(T.temperature(-300, 'C', 'K').status, 'invalid_input');
});
test('metal price conversion and premium', () => {
  const r = T.metal(2000, 7.2, 470);
  close(r.cnyPerGram, 2000 * 7.2 / 31.1034768);
  close(r.cnyPerKg, r.cnyPerGram * 1000);
  close(r.premium, 470 - r.cnyPerGram);
  close(r.premiumPct, 470 / r.cnyPerGram - 1);
  assert.equal(T.metal(2000, 7.2).premium, undefined);
  const s = T.fxScenario(2000, 7.0, 7.2);
  close(s.diffPct, 7.2 / 7.0 - 1);
});
test('mortgage annuity and linear', () => {
  const a = T.mortgage(1000000, 3.6, 360, 'annuity');
  const r = 0.003;
  close(a.first, 1000000 * r * Math.pow(1 + r, 360) / (Math.pow(1 + r, 360) - 1));
  close(a.rows[359].balance, 0);
  const l = T.mortgage(1200000, 3.6, 120, 'linear');
  close(l.first, 10000 + 1200000 * r);
  close(l.interest, 1200000 * r * 121 / 2, 1e-9);
  close(T.mortgage(1200, 0, 12, 'annuity').first, 100);
  assert.equal(T.mortgage(1, 3, 0).status, 'invalid_input');
  assert.equal(T.mortgage(1000000, '', 360, 'annuity').status, 'invalid_input');
  assert.equal(T.fx('', 7.2).status, 'invalid_input');
  assert.equal(T.mass('  ', 'g', 'kg').status, 'invalid_input');
});
test('time zones: DST gap, overlap and plain conversion', () => {
  const gap = T.convertTime('America/New_York', 'Asia/Shanghai', 2026, 3, 8, 2, 30);
  assert.equal(gap.nonexistent, true);
  const dup = T.convertTime('America/New_York', 'Asia/Shanghai', 2026, 11, 1, 1, 30);
  assert.equal(dup.ambiguous, true);
  assert.equal(dup.results.length, 2);
  const ok = T.convertTime('Asia/Shanghai', 'Europe/London', 2026, 7, 1, 15, 0);
  assert.equal(ok.results[0].at.h, 8); // BST = UTC+1
  const w = T.convertTime('Asia/Shanghai', 'Europe/London', 2026, 1, 15, 15, 0);
  assert.equal(w.results[0].at.h, 7);
  assert.equal(T.convertTime('Mars/Base', 'UTC', 2026, 1, 1, 0, 0).status, 'invalid_input');
});
test('A-share session buckets', () => {
  const at = (h, m, d = 17) => Date.UTC(2026, 10, d, h - 8, m);
  assert.equal(T.ashareSession(at(9, 20)).code, 'auction');
  assert.equal(T.ashareSession(at(9, 27)).text, '竞价结束，待开盘');
  assert.equal(T.ashareSession(at(10, 0)).code, 'open');
  assert.equal(T.ashareSession(at(12, 0)).code, 'lunch');
  assert.equal(T.ashareSession(at(15, 0)).code, 'closed');
  assert.equal(T.ashareSession(at(10, 0, 21)).code, 'weekend');
});
