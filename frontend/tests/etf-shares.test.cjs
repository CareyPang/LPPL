const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../app/etf-shares.js');

test('merge prefers the daily series, keeps archive rows before it, and computes size', () => {
  const rows = E.merge([['2026-01-02', 10, 2, 1], ['2026-01-05', null, 2.1, null]], [['2025-12-30', 8, 1.5], ['2026-01-02', 9, 2], ['2026-01-05', 11, 2.1]]);
  assert.deepEqual(rows.map(r => r.d), ['2025-12-30', '2026-01-02', '2026-01-05']);
  assert.equal(rows[0].value, 12);
  assert.equal(rows[1].shares, 10);
  assert.equal(rows[2].shares, 11, 'a daily row without shares does not erase the archive value');
  assert.equal(E.merge([['2026-01-06', null, 2]], [])[0].value, null);
});

test('sum carries the last known shares of an ETF across its missing day', () => {
  const a = E.merge([['2026-01-02', 10, 2], ['2026-01-05', null, 3], ['2026-01-06', 12, 3]]);
  const b = E.merge([['2026-01-05', 5, 1], ['2026-01-06', 5, 1]]);
  const s = E.sum([a, b]);
  assert.deepEqual(s.map(r => [r.d, r.shares, r.value, r.n]), [['2026-01-02', 10, 20, 1], ['2026-01-05', 15, 35, 2], ['2026-01-06', 17, 41, 2]]);
});

test('sliceRange cuts by calendar months from the last known day and drops days without shares', () => {
  const rows = E.merge([['2025-01-02', 1, 1], ['2025-11-28', 2, 1], ['2026-08-27', 3, 1], ['2026-11-26', 4, 1], ['2026-11-27', null, 1]]);
  assert.deepEqual(E.sliceRange(rows, '3m').map(r => r.d), ['2026-08-27', '2026-11-26']);
  assert.deepEqual(E.sliceRange(rows, '1y').map(r => r.d), ['2025-11-28', '2026-08-27', '2026-11-26']);
  assert.equal(E.sliceRange(rows, 'all').length, 4);
});

test('tableRows lists newest first with change against the previous known day', () => {
  const t = E.tableRows(E.merge([['2026-01-02', 10, 2], ['2026-01-05', null, 2], ['2026-01-06', 12, 3]]));
  assert.deepEqual(t[0], { d: '2026-01-06', shares: 12, chg: 2, value: 36, flow: 6 });
  assert.equal(t[1].chg, null);
});

test('ticks are round and indexAt clamps to the series', () => {
  assert.deepEqual(E.ticks(0, 100, 4), [0, 50, 100]);
  assert.equal(E.indexAt({ left: 40, width: 100 }, 11, 90), 5);
  assert.equal(E.indexAt({ left: 40, width: 100 }, 11, 500), 10);
  assert.equal(E.indexAt(null, 11, 90), null);
});

test('nt.html draws the shares chart from LPPL.ntEtf only and labels disclosure dates', () => {
  const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '../nt.html'), 'utf8');
  assert.match(html, /<script src="app\/etf-shares\.js"><\/script>/);
  assert.match(html, /id="sh-chart"/);
  assert.match(html, /LPPL\.ntEtf\(\)/);
  assert.doesNotMatch(html, /fetch\(/);
  assert.match(html, /份额变化是全市场申赎合计，不能直接算作某一类持有人的买卖/);
  assert.match(html, /n\.report_date\+' 披露/);
});
