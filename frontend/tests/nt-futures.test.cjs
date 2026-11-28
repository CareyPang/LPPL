const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const N = require('../app/nt-futures.js');

const leg = (cl, tl, ts, basis) => ({ cl, tl, ts, basis });
const rows = [
  { date: '2026-11-26', IF: leg(100, 10, 30, -1.3), IH: leg(50, 5, 9, -1.4), IC: leg(0, 0, 0, -1.25), IM: leg(0, 0, 0, -1.1) },
  { date: '2026-11-27', IF: leg(13680, 20, 50, 0.29), IH: leg(3347, 5, 19, 0.06), IC: leg(0, 0, 0, 0.18), IM: leg(0, 0, 0, -0.4) },
];
const evidence = {
  first: '2015-04-17', last: '2026-08-27', note: '没有一项通过。',
  baseline: { n: 2764, median_20: 0.0013, up_20: 0.507 },
  events: [
    { key: 'E1', label: '多单增加', n: 32, median_20: -0.0003, up_20: 0.469, passed: false },
    { key: 'E3', label: '同日', n: 9, median_20: 0.0257, up_20: 0.556, passed: false },
    { key: 'E4', label: '四路同向', n: 0, median_20: null, up_20: null, passed: false },
  ],
};

test('verdict follows the registered wording and never calls an unpassed event a signal', () => {
  assert.equal(N.verdict(evidence.events[0]), '之后走势与任选一天没有可分辨的差别');
  assert.equal(N.verdict(evidence.events[1]), '样本不足');
  assert.equal(N.verdict(evidence.events[2]), '从未出现');
});

test('series derives the seat change, top-20 net short and basis per day', () => {
  const s = N.series(rows, 60);
  assert.equal(s.length, 1);
  assert.equal(s[0].seat, 16877);
  assert.equal(s[0].net, 30 + 14);
  assert.equal(s[0].basis.IC, 0.18);
});

test('html lists only the events hit today, with their history and the baseline', () => {
  const today = { date: '2026-11-27', seat_long_chg: 16877, net_short: 44, net_short_chg: 20, index_pct: 4.17,
    basis: { IF: 0.29, IH: 0.06, IC: 0.18, IM: -0.4 }, basis_previous: { IC: -1.25 }, events: ['E1', 'E3'] };
  const out = N.html({ today, evidence });
  assert.match(out, /\+16,877 手/);
  assert.match(out, /多单增加：历史上出现 32 次，之后 20 日沪深300 中位 0\.0%、上涨 47%（任选一天 \+0\.1%、51%）/);
  assert.match(out, /同日：历史上出现 9 次.*样本不足/);
  assert.doesNotMatch(out, /进场|信号|买入|卖出/);
  assert.match(N.html({ today: { ...today, events: [] }, evidence }), /当日没有出现登记的 6 种情况/);
  assert.match(N.html({}), /暂未发布/);
});

test('the ETF page loads the panel module and reads futures from the published nt_etf data', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'nt.html'), 'utf8');
  assert.match(page, /app\/nt-futures\.js/);
  assert.match(page, /id="ntf"/);
  assert.match(page, /NtFutures\.html\(d\.futures\)/);
});
