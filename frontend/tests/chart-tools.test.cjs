const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const T = require('../app/chart-tools.js');

test('parsePeriods keeps up to five distinct periods in 2..500', () => {
  assert.deepEqual(T.parsePeriods('5, 20 60/60 1 999 120 250 30'), [5, 20, 60, 120, 250]);
  assert.deepEqual(T.parsePeriods(''), []);
});
test('sma is null before the window fills and never uses later bars', () => {
  const a = T.sma([1, 2, 3, 4, 5], 3);
  assert.deepEqual(a, [null, null, 2, 3, 4]);
  assert.deepEqual(T.sma([1, 2, 3, 4, 99], 3).slice(0, 4), a.slice(0, 4));
});
test('rsi and kdj stay in range; macd histogram is 2*(dif-dea)', () => {
  const close = Array.from({ length: 80 }, (_, i) => 100 + Math.sin(i / 5) * 10 + i * 0.1);
  const bars = close.map((c) => ({ close: c, high: c + 1, low: c - 1 }));
  T.rsi(close).forEach((v, i) => { if (i < 14) assert.equal(v, null); else assert.ok(v >= 0 && v <= 100); });
  const k = T.kdj(bars);
  k.k.concat(k.d).forEach((v) => assert.ok(v >= 0 && v <= 100));
  const m = T.macd(close);
  assert.ok(Math.abs(m.hist[40] - 2 * (m.dif[40] - m.dea[40])) < 1e-12);
  assert.deepEqual(T.rsi([1, 1, 1].concat(new Array(20).fill(1))).slice(-1), [50]);
});
test('index page labels the chart tools as not a signal and splits red/green toggles', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  assert.match(html, /data-k="fcoTop"[^>]*>.*红柱/);
  assert.match(html, /data-k="fcoBot"[^>]*>.*绿柱/);
  assert.match(html, /行情工具、不作信号/);
  assert.match(html, /<option value="macd">成交量 + MACD<\/option>/);
  assert.match(html, /app\/chart-tools\.js/);
});
