'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Chart = require('../app/candle-chart.js');

test('actual OHLC extremes determine price scale; bodies never substitute for shadows', () => {
  const bars = Chart.normalize([
    { date: '2026-10-20', open: 10, high: 18, low: 4, close: 11, volume: 0 },
    { date: '2026-10-21', open: 12, high: 13, low: 8, close: 9, volume: 1400 },
  ]);
  const g = Chart.geometry(bars, 390, 370);
  assert.ok(g.min < 4 && g.max > 18);
  assert.ok(g.y(18) < g.y(13));
  assert.ok(g.priceBottom < g.volumeTop && g.volumeTop < g.bottom);
  assert.equal(g.indexAt(g.x(0)), 0);
  assert.equal(g.indexAt(g.x(1)), 1);
  assert.equal(g.indexAt(-10), 0);
  assert.equal(g.indexAt(400), 1);
});

test('zero volume remains zero, missing and invalid volumes remain unknown', () => {
  const price = { open: 10, high: 12, low: 9, close: 11 };
  const bars = Chart.normalize([
    { date: '2026-10-20', ...price, volume: 0 },
    { date: '2026-10-21', ...price, volume: null },
    { date: '2026-10-22', ...price, volume: -10 },
  ]);
  assert.deepEqual(bars.map(bar => bar.volume), [0, null, null]);
  assert.match(Chart.describe(bars[0]), /成交量 0/);
  assert.match(Chart.describe(bars[1]), /成交量 缺失/);
  assert.match(Chart.describe(bars[0]), /源单位未核验/);
});

test('missing or contradictory OHLC is never reconstructed from close', () => {
  const bars = Chart.normalize([
    { date: '2026-10-20', close: 10, volume: 5 },
    { date: '2026-10-21', open: 10, high: 9, low: 7, close: 11, volume: 5 },
  ]);
  assert.ok(bars.every(bar => !bar.ohlcValid && bar.open === null && bar.high === null && bar.low === null));
  assert.match(Chart.describe(bars[0]), /仅显示收盘标记/);
});

test('invalid dates and prices do not enter the chart; dates stay ordered and unique', () => {
  const bars = Chart.normalize([
    { date: '2026-10-22', close: 22 }, { date: '2026-10-20', close: 20 },
    { date: '2026-02-30', close: 2 }, { date: '2026-10-21', close: 0 },
    { date: '2026-10-20', close: 21 }, { date: '2026-10-23', close: NaN },
  ]);
  assert.deepEqual(bars.map(bar => [bar.date, bar.close]), [['2026-10-20', 21], ['2026-10-22', 22]]);
});

test('flat prices and all missing volume still have finite usable axes', () => {
  const bars = Chart.normalize([{ date: '2026-10-20', open: 10, high: 10, low: 10, close: 10 }]);
  const g = Chart.geometry(bars, 300, 370);
  assert.ok(Number.isFinite(g.y(10)) && Number.isFinite(g.vy(0)));
  assert.ok(g.min < 10 && g.max > 10);
  assert.equal(Chart.adjustmentLabel('qfq'), '前复权');
  assert.equal(Chart.adjustmentLabel('none'), '未复权');
  assert.equal(Chart.adjustmentLabel(undefined), '复权口径未核验');
  assert.equal(Chart.unitLabel('vendor_native'), '源单位未核验');
});

test('canvas paints candles and volume using their common session coordinates', () => {
  const fills = [], outlines = [], strokes = [];
  let segment = [];
  const context = { setTransform() {}, clearRect() {}, fillText() {}, setLineDash() {},
    beginPath() { segment = []; }, moveTo(x, y) { segment.push([x, y]); },
    lineTo(x, y) { segment.push([x, y]); }, stroke() { strokes.push(segment); },
    fillRect(...args) { fills.push(args); }, strokeRect(...args) { outlines.push(args); } };
  const canvas = { clientWidth: 390, clientHeight: 370, getContext: () => context };
  const bars = Chart.normalize([
    { date: '2026-10-20', open: 10, high: 13, low: 9, close: 12, volume: 500 },
    { date: '2026-10-21', open: 12, high: 14, low: 9, close: 10, volume: 0 },
    { date: '2026-10-22', open: 10, high: 12, low: 8, close: 9, volume: null },
  ]);
  const g = Chart.draw(canvas, bars, 1, { pixelRatio: 1 });
  assert.equal(outlines.length, 1, 'up candle is outlined rather than colored as a down candle');
  const volumeRects = fills.filter(rect => rect[1] >= g.volumeTop);
  assert.equal(volumeRects.length, 2, 'missing volume does not become a zero-volume rectangle');
  assert.equal(volumeRects[1][3], 1, 'known zero uses a baseline tick');
  assert.equal(outlines[0][0] + outlines[0][2] / 2, g.x(0));
  assert.equal(volumeRects[0][0] + volumeRects[0][2] / 2, g.x(0));
  assert.ok(strokes.some(points => points.length === 2 && points[0][0] === g.x(2) && points[0][1] === g.y(12) && points[1][1] === g.y(8)));
});
