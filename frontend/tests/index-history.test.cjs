const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../app/index-history.js');

const payload = { schema: 'index_bars.v1', dates: ['2000-01-04', '2000-01-05', '2024-01-02'], open: [1, 2, 9], high: [1, 2, 9], low: [1, 2, 9], close: [1, 2, 9], volume: [null, 5, 9] };

test('mergeBars only prepends bars older than the published window', () => {
  const bars = [{ date: '2024-01-02', open: 3, high: 3, low: 3, close: 3, volume: 7 }];
  const merged = H.mergeBars(bars, payload);
  assert.deepEqual(merged.map((b) => b.date), ['2000-01-04', '2000-01-05', '2024-01-02']);
  assert.equal(merged[2].close, 3);
  assert.equal(merged[0].volume, null);
  assert.equal(H.mergeBars(bars, { schema: 'other' }), bars);
  assert.equal(H.mergeBars(bars, null), bars);
});

test('bottomEvents lists only frames flagged by the backend up to the as-of date', () => {
  const history = { frames: [
    { asof: '2010-01-08', bottom_first_alert_flag: true },
    { asof: '2012-01-06', bottom_first_alert_flag: false },
    { asof: '2020-01-03', bottom_first_alert_flag: true },
  ] };
  assert.deepEqual(H.bottomEvents(history, '2015-01-01').map((e) => e.asof || e.date), ['2010-01-08']);
  assert.equal(H.bottomEvents(history).length, 2);
});
