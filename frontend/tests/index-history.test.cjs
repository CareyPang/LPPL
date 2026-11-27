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

test('older bottom events fall back to published frame closes once mature', () => {
  const frames = Array.from({ length: 60 }, (_, i) => ({
    asof: `d${String(i).padStart(2, '0')}`, close: 100 + i, bottom_first_alert_flag: i === 0 || i === 20,
  }));
  const history = { frames, bottom_summary: { events: [{ asof: 'd20', ret_24w: 0.5, ret_50w: null }] } };
  const [later, first] = H.bottomEvents(history);
  assert.equal(first.ret24.toFixed(4), '0.2400');
  assert.equal(first.ret50.toFixed(4), '0.5000');
  assert.equal(later.ret24, 0.5);
  assert.equal(later.ret50, null);
  assert.equal(H.bottomEvents(history, 'd30')[1].ret50, null);
});

test('top record tab carries the recompute caveat', () => {
  const html = H.renderTop({ frames: [], recompute: { label: '事后重算，不是样本外', note: '测试段未通过' } }, {});
  assert.match(html, /事后重算，不是样本外/);
  assert.match(html, /测试段未通过/);
  const replay = H.renderTop({ frames: [], recompute: { label: '事后重算，不是样本外', note: '测试段未通过' } }, { historical: true });
  assert.match(replay, /事后重算，不是样本外/);
  assert.doesNotMatch(replay, /测试段未通过/);
});
