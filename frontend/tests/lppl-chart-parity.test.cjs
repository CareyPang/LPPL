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
    path.resolve(__dirname, '../../web/mock/data/market/archives/sh600519_2026-11-17.json'), 'utf8',
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

test('all scale bands use selected emphasis and suppress labels on unselected scales', () => {
  const top = { scale_clusters: {
    '6-12m': [{ share: 0.4, q20_date: '2026-12-01', q80_date: '2026-12-12' }],
    '12-24m': [{ share: 0.3, q20_date: '2027-01-04', q80_date: '2027-01-15' },
      { share: 0.2, q20_date: '2027-01-05', q80_date: '2027-01-16' }],
  } };
  const bands = Chart.bandsForAllScales({ top });
  assert.deepEqual(bands.map(({ scale, rank }) => [scale, rank]), [
    ['6-12m', 'main'], ['12-24m', 'main'], ['12-24m', 'secondary'],
  ]);
  assert.deepEqual(Chart.bandStyle(bands[0], false), {
    fillAlpha: 0.045,
    strokeColor: 'rgba(36,71,201,.42)',
    lineWidth: 0.75,
    dashed: false,
    showLabel: false,
  });
  assert.deepEqual(Chart.bandStyle(bands[1], true), {
    fillAlpha: 0.16,
    strokeColor: 'rgba(36,71,201,.96)',
    lineWidth: 2,
    dashed: false,
    showLabel: true,
  });
  assert.deepEqual(Chart.bandStyle(bands[2], true), {
    fillAlpha: 0.06,
    strokeColor: 'rgba(49,92,245,.68)',
    lineWidth: 1.25,
    dashed: true,
    showLabel: true,
  });
  assert.equal(Chart.bandStyle(bands[0], true).showLabel, true);
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

test('default and focused ranges preserve cutoff context through the furthest band', () => {
  const latest = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'stock_601838.json'), 'utf8',
  ));
  const market = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'stock_601838_market.json'), 'utf8',
  ));
  const bars = Chart.toCandles(market.price);
  const closures = new Set(latest.future_calendar.closures || []);
  const bands = Chart.bandsForAllScales(latest).concat([{
    rank: 'main', scale: '2-6y', q20_date: '2027-02-01', q80_date: '2027-02-15',
  }]);
  const whitespace = Chart.futureWhitespace(bars, bands.map(band => band.q80_date), closures);
  const availableTo = bars.length + whitespace.length - 1;
  const cutoffDate = Chart.mapTime(bars, latest.asof, closures);
  const cutoff = bars.findIndex(bar => bar.time === cutoffDate);
  const furthest = bands.map(band => Chart.bandSlotRange(bars, band, closures))
    .reduce((result, range) => range.to > result.to ? range : result);
  const expected = {
    from: Math.max(0, cutoff - 120),
    to: Math.min(availableTo, furthest.to + 5),
  };

  assert.deepEqual(Chart.defaultVisibleRange(
    bars, bands, latest.asof, closures, availableTo,
  ), expected);
  assert.deepEqual(Chart.focusVisibleRange(
    bars, latest.asof, closures, furthest.from, furthest.to, availableTo,
  ), expected);
  assert.deepEqual(Chart.defaultVisibleRange(
    bars, [], latest.asof, closures, bars.length - 1,
  ), { from: Math.max(0, cutoff - 120), to: bars.length - 1 });
});

test('a single-day cluster occupies one logical bar slot', () => {
  const range = Chart.bandSlotRange([{ time: '2025-08-11' }], {
    q20_date: '2025-08-12', q80_date: '2025-08-12',
  }, new Set());
  assert.equal(range.start, '2025-08-12');
  assert.equal(range.end, '2025-08-13');
  assert.ok(range.to - range.from >= 1);
});

test('sh601838: published 6-12m scale window is exposed as a band', () => {
  const data = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'stock_601838.json'), 'utf8',
  ));
  assert.equal(data.asof, '2026-11-13');
  assert.deepEqual(Chart.bandsFor(data, '6-12m'), [{
    rank: 'main', source: 'scale_window', q20_date: '2026-12-30', q80_date: '2027-01-07',
  }]);
});

test('sh601838: published CN calendar covers its 6-12m band', () => {
  const data = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'stock_601838.json'), 'utf8',
  ));
  const market = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'stock_601838_market.json'), 'utf8',
  ));
  assert.equal(Chart.needsCalendarCoverage(
    Chart.bandsFor(data, '6-12m'), market.price.at(-1).date, data.future_calendar,
  ), false);
});

test('sh601838: worker market bars preserve the legacy Canvas OHLCV input', () => {
  const market = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'stock_601838_market.json'), 'utf8',
  ));
  const candles = Chart.toCandles(market.price);
  assert.equal(market.asof, '2026-11-17');
  assert.equal(market.adjustment, 'none');
  assert.equal(candles.length, market.price.length);
  assert.deepEqual(candles.map(({ time, open, high, low, close, volume }) =>
    [time, open, high, low, close, volume]), market.price.map(({ date, open, high, low, close, volume }) =>
    [date, open, high, low, close, volume]));
});

test('published sh000001 history frame preserves primary and secondary future bands', () => {
  const history = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'sh000001_history.json'), 'utf8',
  ));
  assert.deepEqual(history.frames.map(item => item.asof), ['2025-08-11']);
  const { oldInput } = readBars(path.join(__dirname, 'fixtures', 'sh000001_latest.json'));
  const frame = history.frames.find(item => item.asof === '2025-08-11');
  const bands = Chart.bandsFor({ top: { scale_clusters: frame.clusters } }, '6-12m');
  const candles = Chart.toCandles(oldInput.filter(bar => bar.date <= frame.asof));
  assert.equal(candles.at(-1).time, frame.asof);
  assert.deepEqual(bands.map(({ rank, q20_date, q80_date }) =>
    [rank, q20_date, q80_date]), [
    ['main', '2025-08-12', '2025-08-12'],
    ['secondary', '2025-08-18', '2025-08-18'],
  ]);
  assert.ok(bands.some(band => band.q80_date > candles.at(-1).time));
  const slots = bands.map(band => Chart.bandSlotRange(candles, band,
    new Set(history.future_calendar?.closures || [])));
  assert.ok(slots.every(range => range && range.to - range.from >= 1));
  const whitespace = Chart.futureWhitespace(candles, bands.map(band => band.q80_date),
    new Set(history.future_calendar?.closures || []));
  assert.ok(whitespace.some(point => point.time === '2025-08-18'));
  assert.ok(whitespace.every(point => Object.keys(point).length === 1 && point.time));
});

test('calendar coverage notice is limited to bands that extend past coverage', () => {
  const band = { q20_date: '2027-01-04', q80_date: '2027-01-08' };
  assert.equal(Chart.needsCalendarCoverage([], '2026-12-31', null), false);
  assert.equal(Chart.needsCalendarCoverage([band], '2027-01-09', null), false);
  assert.equal(Chart.needsCalendarCoverage([band], '2026-12-31', {
    coverage_end: '2027-01-08',
  }), false);
  assert.equal(Chart.needsCalendarCoverage([band], '2026-12-31', {
    holidays_through: '2027-01-08',
  }), false);
  assert.equal(Chart.needsCalendarCoverage([band], '2026-12-31', {
    coverage_end: '2027-01-07',
  }), true);
  assert.equal(Chart.needsCalendarCoverage([band], '2026-12-31', null), true);
});
