'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Chart = require('../app/lppl-chart.js');
const TopClusters = require('../app/top-clusters.js');

const published = {
  sh000001: path.join(__dirname, 'fixtures', 'sh000001_latest.json'),
  sh600519: path.join(__dirname, 'fixtures', 'stock_600519.json'),
};
const scales = ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'];

function readBars(file) {
  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  const history = data.price_history;
  const oldInput = history.dates.map((date, index) => ({
    date,
    open: history.open?.[index] ?? history.close[index],
    high: history.high?.[index] ?? history.close[index],
    low: history.low?.[index] ?? history.close[index],
    close: history.close[index],
    volume: history.volume ? history.volume[index] : null,
  }));
  return { data, oldInput };
}

for (const [symbol, file] of Object.entries(published)) {
  test(`${symbol}: published price history converts losslessly to candles`, () => {
    const { data, oldInput } = readBars(file);
    const candles = Chart.toCandles(oldInput);
    assert.equal(candles.length, oldInput.length);
    assert.equal(candles[0].time, oldInput[0].date);
    assert.equal(candles.at(-1).time, oldInput.at(-1).date);
    assert.deepEqual(candles.map(({ time, open, high, low, close, volume }) =>
      [time, open, high, low, close, volume]), oldInput.map(({ date, open, high, low, close, volume }) =>
      [date, open, high, low, close, volume]));
    assert.ok(data.asof);
  });

  test(`${symbol}: each scale preserves CPTopClusters dates`, () => {
    const { data } = readBars(file);
    for (const scale of scales) {
      const expected = TopClusters.forScale(data.top || {}, scale) || [];
      assert.deepEqual(Chart.bandsFor(data, scale), expected);
    }
  });
}

test('missing volume stays empty', () => {
  const [bar] = Chart.toCandles([{
    date: '2026-01-05', open: 10, high: 11, low: 9, close: 10.5, volume: null,
  }]);
  assert.equal(bar.volume, null);
  assert.notEqual(bar.volume, 0);
});

test('sh600519: live published market bars preserve the stock Canvas OHLCV input', () => {
  const market = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'stock_600519_market.json'), 'utf8',
  ));
  const oldInput = market.price;
  const candles = Chart.toCandles(oldInput);
  assert.equal(candles.length, oldInput.length);
  assert.equal(candles[0].time, oldInput[0].date);
  assert.equal(candles.at(-1).time, oldInput.at(-1).date);
  assert.deepEqual(candles.map(({ time, open, high, low, close, volume }) =>
    [time, open, high, low, close, volume]), oldInput.map(({ date, open, high, low, close, volume }) =>
    [date, open, high, low, close, volume]));
});

test('crosshair dates accept Lightweight Charts business-day time objects', () => {
  assert.equal(Chart.dateFromTime('2026-11-17'), '2026-11-17');
  assert.equal(Chart.dateFromTime({ year: 2026, month: 11, day: 17 }), '2026-11-17');
  assert.equal(Chart.dateFromTime({ year: 2026, month: 2, day: 30 }), '');
});

test('main and secondary bands exactly follow normalized CPTopClusters output', () => {
  const top = { scale_clusters: Object.fromEntries(scales.map(scale => [scale, [
    { share: 0.35, q20_date: '2027-01-04', q80_date: '2027-02-15' },
    { share: 0.65, q20_date: '2027-01-05', q80_date: '2027-02-16' },
  ]])) };
  for (const scale of scales) {
    assert.deepEqual(Chart.bandsFor({ top }, scale), TopClusters.forScale(top, scale));
  }
});

test('future bands map through cross-year, Spring Festival, and National Day calendars', () => {
  const yearEnd = [{ time: '2026-12-31' }];
  assert.equal(Chart.mapTime(yearEnd, '2027-01-04', new Set(['2027-01-01'])), '2027-01-04');
  const spring = [{ time: '2027-02-05' }];
  assert.equal(Chart.mapTime(spring, '2027-02-15', new Set([
    '2027-02-08', '2027-02-09', '2027-02-10', '2027-02-11', '2027-02-12',
  ])), '2027-02-15');
  const national = [{ time: '2026-09-30' }];
  assert.equal(Chart.mapTime(national, '2026-10-08', new Set([
    '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07',
  ])), '2026-10-08');
});

test('future whitespace contains no OHLC and is bounded', () => {
  const bars = [{ time: '2026-12-31' }];
  const whitespace = Chart.futureWhitespace(bars, ['2027-01-04'], new Set(['2027-01-01']));
  assert.ok(whitespace.length > 0 && whitespace.length <= 260);
  assert.ok(whitespace.every(point => Object.keys(point).length === 1 && point.time));
});
