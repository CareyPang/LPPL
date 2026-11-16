'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const ChartLab = require('../app/chart-lab.js');

function bar(date, open, high, low, close, volume = 100) {
  return { date, open, high, low, close, volume };
}

test('toCandles maps, sorts and deduplicates valid market bars', () => {
  const candles = ChartLab.toCandles([
    bar('2026-01-03', 12, 14, 11, 13, 120),
    bar('2026-01-02', 10, 12, 9, 11, 110),
    bar('2026-01-03', 13, 15, 12, 14, 130),
    bar('2026-01-04', 14, 13, 12, 13, 90),
    bar('2026-01-05', 0, 12, 9, 11, 100),
  ]);

  assert.deepEqual(candles, [
    { time: '2026-01-02', open: 10, high: 12, low: 9, close: 11, volume: 110 },
    { time: '2026-01-03', open: 13, high: 15, low: 12, close: 14, volume: 130 },
  ]);
});

test('futureWhitespace skips weekends and supplied market closures', () => {
  const points = ChartLab.futureWhitespace(
    [{ date: '2024-01-05' }],
    ['2024-01-10'],
    new Set(['2024-01-08']),
  );

  assert.deepEqual(points.map(point => point.time), [
    '2024-01-09',
    '2024-01-10',
    '2024-01-11',
    '2024-01-12',
    '2024-01-15',
  ]);
});

test('futureWhitespace caps the appended trading-day slots at 260', () => {
  const points = ChartLab.futureWhitespace(
    [{ date: '2024-01-05' }],
    ['2035-01-01'],
    [],
  );

  assert.equal(points.length, 260);
});

test('bandsFor returns only selectable scales with both dates and ignores other fields', () => {
  const bands = ChartLab.bandsFor({
    top: {
      lppls_confidence: {
        scale_evidence: {
          '6-12m': 'dev',
          '12-24m': 'none',
          '3-6m': 'dev',
          '1-3m': 'dev',
        },
        '6-12m': 0.92,
        tc_mode_date: '2026-10-01',
      },
      scale_windows: [
        {
          scale: '6-12m',
          q20_date: '2026-12-01',
          q80_date: '2026-12-10',
          tc_mode_date: '2026-09-01',
          representative: { date: '2026-09-01' },
          share: 0.8,
        },
        { scale: '12-24m', q20_date: '2027-01-01', q80_date: '2027-02-01' },
        { scale: '3-6m', q20_date: null, q80_date: '2026-08-01' },
        { scale: '1-3m', q20_date: '2026-07-01' },
        { scale: '2-4w', q20_date: '2026-05-01', q80_date: '2026-06-01' },
      ],
    },
  });

  assert.deepEqual(bands, [{
    scale: '6-12m',
    q20_date: '2026-12-01',
    q80_date: '2026-12-10',
  }]);
  assert.equal(JSON.stringify(bands).includes('confidence'), false);
  assert.equal(JSON.stringify(bands).includes('tc_mode_date'), false);
  assert.equal(JSON.stringify(bands).includes('representative'), false);
  assert.equal(JSON.stringify(bands).includes('share'), false);
});

test('pickCurrent prefers the candidate with the newer asof', () => {
  const older = { asof: '2026-11-15', requested_at: '2026-11-17T10:00:00Z' };
  const newer = { asof: '2026-11-16', requested_at: '2026-11-16T10:00:00Z' };

  assert.equal(ChartLab.pickCurrent(older, newer), newer);
  assert.equal(ChartLab.pickCurrent(newer, older), newer);
});

test('pickCurrent breaks equal-asof ties by requested or generated timestamp', () => {
  const older = { asof: '2026-11-16', generated_at: '2026-11-17T10:00:00Z' };
  const newer = { asof: '2026-11-16', requested_at: '2026-11-18T10:00:00Z' };

  assert.equal(ChartLab.pickCurrent(older, newer), newer);
});

test('pickCurrent ignores null candidates', () => {
  const available = { asof: '2026-11-16' };

  assert.equal(ChartLab.pickCurrent(null, available), available);
  assert.equal(ChartLab.pickCurrent(available, null), available);
  assert.equal(ChartLab.pickCurrent(null, null), null);
});
