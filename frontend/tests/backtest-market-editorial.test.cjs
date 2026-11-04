'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/backtest-market-editorial.js'), 'utf8');
const context = vm.createContext({}); vm.runInContext(source, context); const M = context.LPPLMarket;
const T = date => Date.parse(date + 'T00:00:00Z');
function snapshot(symbol = 'sh000001', asof = '2025-01-10') {
  return { sym: { sym: symbol }, asof, raw: { asof, price_history: {
    dates: ['2025-01-06', '2025-01-07', '2025-01-08'], open: [100, 101, 102], high: [103, 104, 105], low: [99, 100, 101], close: [102, 103, 104], volume: [10000, null, 30000]
  } }, bars: [{ date: '1999-01-01', open: 1, high: 1, low: 1, close: 1 }] };
}
test('close-only adapter fallbacks cannot become invented OHLC candles', () => {
  const D = snapshot(); delete D.raw.price_history.open;
  assert.equal(M.snapshotBars(D).length, 0);
  assert.equal(M.snapshotBars({ bars: D.bars }).length, 0);
});
test('null OHLC, incoherent ranges, and post-asof bars are rejected, while missing volume stays null', () => {
  const D = snapshot(); assert.equal(M.snapshotBars(D)[1].volume, null);
  D.raw.price_history.open[0] = null; D.raw.price_history.high[1] = 99; D.asof = '2025-01-07';
  assert.equal(M.snapshotBars(D).length, 0);
});
test('coverage islands stay separate and close-only paths never connect through candle islands', () => {
  const ranges = M.coverageFor([{ t: T('2025-01-10') }, { t: T('2025-01-13') }, { t: T('2025-06-01') }]);
  assert.equal(ranges.length, 2);
  const frames = ['2025-01-06', '2025-01-20', '2025-01-27', '2025-06-01'].map(asof => ({ asof, t: T(asof) }));
  const segments = M.weeklySegments(frames, ranges);
  assert.equal(segments.length, 2);
  assert.deepEqual(Array.from(segments, seg => Array.from(seg, f => f.asof)), [['2025-01-06'], ['2025-01-20', '2025-01-27']]);
});
test('snapshot loading is adapter-only, tolerates an unavailable replay, and rejects mismatched symbols', async () => {
  const calls = [];
  const adapter = { REPLAYS: { sh000001: ['2007-10-12', '2015-06-12'] }, load: async (symbol, asof) => {
    calls.push([symbol, asof]); if (asof === '2007-10-12') throw new Error('unavailable');
    return snapshot(asof ? 'sh000300' : symbol);
  } };
  const result = await M.load(adapter, 'sh000001');
  assert.equal(result.bars.length, 3); assert.equal(result.failures.length, 2);
  assert.equal(calls.length, 3); assert.equal(result.snapshots.length, 1);
  assert.equal(result.snapshots[0].latest, true); assert.equal(source.includes('fetch('), false);
});
test('volume absence is never filled and duplicate snapshot days have one real candle', async () => {
  const D = snapshot(); delete D.raw.price_history.volume;
  const result = await M.load({ REPLAYS: { sh000001: ['2025-01-10'] }, load: async () => D }, 'sh000001');
  assert.equal(result.bars.length, 3); assert.ok(result.bars.every(b => b.volume === null));
});
