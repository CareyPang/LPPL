const test = require('node:test');
const assert = require('node:assert/strict');
const { chartSlice } = require('../app/guanshi-chart.js');

const asof = '2026-11-17';
const bars = [
  { date: '2026-11-16', open: 3, high: 4, low: 3, close: 3.5, volume: 0 },
  { date: asof, open: 3.5, high: 4, low: 2.8, close: 3, volume: 150 },
  { date: '2026-11-18', close: 9, volume: 300 },
  { date: '2027-06-11', close: 2, volume: 80 },
];

test('revealing later closes never changes window coordinates or the known bars', () => {
  const windows = [{ start: '2026-12-30', end: '2027-02-03' }];
  const known = chartSlice({ bars, asof, windows });
  const revealed = chartSlice({ bars, asof, windows, revealLater: true });
  assert.deepEqual(known.bars, bars.slice(0, 2));
  assert.deepEqual(revealed.bars, bars.slice(0, 3));
  for (const key of ['start', 'end', 'cutoff', 'bands', 'priorCount', 'candles']) {
    assert.deepEqual(known[key], revealed[key]);
  }
  assert.equal(known.hasVolume, true);
});

test('close-only prices, malformed OHLC and missing volumes cannot become generated candles or zeros', () => {
  const slice = chartSlice({ bars: [{ date: asof, close: 3.4, high: 1, low: 2, open: 2.5 }], asof });
  assert.equal(slice.candles, false);
  assert.equal(slice.hasVolume, false);
});

test('invalid or later-only inputs yield no as-of chart and invalid windows are not plotted', () => {
  assert.equal(chartSlice({ bars, asof: '2026-11-01', revealLater: true }), null);
  assert.equal(chartSlice({ bars, asof: '2026-02-31' }), null);
  assert.deepEqual(chartSlice({ bars, asof, windows: [{ start: '2026-99-01', end: asof }] }).bands, []);
});
