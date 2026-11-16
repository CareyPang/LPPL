'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const TradingDays = require('../app/trading-days.js');

const calendar = JSON.parse(fs.readFileSync(
  path.join(__dirname, '../../research/data/cn_market_holidays.json'),
  'utf8',
));
const closures = new Set(calendar.closures);

function bars(last) {
  return [{ date: last }];
}

function oldDateAt(series, idx) {
  if (idx < series.length) return series[Math.max(0, idx)].date;
  let date = new Date(series[series.length - 1].date + 'T00:00:00Z');
  let remaining = idx - (series.length - 1);
  while (remaining > 0) {
    date = new Date(date.getTime() + 86400000);
    const weekday = date.getUTCDay();
    if (weekday !== 0 && weekday !== 6) remaining--;
  }
  return date.toISOString().slice(0, 10);
}

function oldIdxOf(series, value) {
  if (!value) return -1;
  const length = series.length, last = series[length - 1].date;
  if (value <= last) {
    const index = series.findIndex(bar => bar.date >= value);
    return index < 0 ? length - 1 : index;
  }
  let index = length - 1;
  let date = new Date(last + 'T00:00:00Z');
  const end = new Date(value + 'T00:00:00Z');
  while (date < end) {
    date = new Date(date.getTime() + 86400000);
    const weekday = date.getUTCDay();
    if (weekday !== 0 && weekday !== 6) index++;
  }
  return index;
}

test('dateAt and idxOf skip CN holidays in 2027', () => {
  assert.equal(TradingDays.dateAt(bars('2026-12-31'), 1, closures), '2027-01-04');
  assert.equal(TradingDays.dateAt(bars('2026-12-31'), 2, closures), '2027-01-05');
  assert.equal(TradingDays.idxOf(bars('2026-12-31'), '2027-01-04', closures), 1);
  assert.equal(TradingDays.dateAt(bars('2027-02-04'), 1, closures), '2027-02-15');
  assert.equal(TradingDays.idxOf(bars('2027-02-04'), '2027-02-15', closures), 1);
  assert.equal(TradingDays.dateAt(bars('2027-09-30'), 1, closures), '2027-10-08');
  assert.equal(TradingDays.idxOf(bars('2027-09-30'), '2027-10-08', closures), 1);
});

test('dateAt and idxOf round-trip indices through the February holiday', () => {
  const series = bars('2027-02-04');
  for (let index = 0; index <= 20; index++) {
    assert.equal(TradingDays.idxOf(series, TradingDays.dateAt(series, index, closures), closures), index);
  }
});

test('dates after holiday coverage use plain weekdays', () => {
  const series = bars('2027-12-31');
  assert.equal(TradingDays.dateAt(series, 1, closures), '2028-01-03');
  assert.equal(TradingDays.idxOf(series, '2028-01-03', closures), 1);
});

test('omitting closures preserves the previous weekday-only behavior', () => {
  const series = bars('2026-12-31');
  for (let index = 0; index <= 20; index++) {
    const date = oldDateAt(series, index);
    assert.equal(TradingDays.dateAt(series, index), date);
    assert.equal(TradingDays.idxOf(series, date), oldIdxOf(series, date));
  }
});
