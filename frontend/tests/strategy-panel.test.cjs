'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const SP = require('../app/strategy-panel.js');

const published = {
  rule_id: 'R1-top-exit-v1', prereg_doc: 'docs/preregistration.md', asof: '2026-11-13',
  segments: { dev: ['2005-01-04', '2014-12-31'], cal: ['2015-01-01', '2019-12-31'], test: ['2020-01-01', '2026-11-13'] },
  metrics: {
    dev: { evidence: 'dev_only', n_trades: 12, win_rate: 0.5, total_return: 0.3, max_drawdown: -0.2 },
    test: { evidence: 'descriptive', n_trades: 4, win_rate: 0.75, total_return: 0.12, bh_return: 0.05, max_drawdown: -0.08 },
  },
  trades: [{ entry: '2020-03-02', exit: '2020-04-01', bars: 21, ret: 0.04, segment: 'test' }, { entry: '2007-10-16', exit: '2007-11-01', bars: 12, ret: -0.03, segment: 'dev' }],
  equity: [{ date: '2020-01-02', nav: 1, bh_nav: 1 }, { date: '2020-06-30', nav: 1.1, bh_nav: 1.02 }],
  properties: { t_plus_1: true, limit_lock: true, fee_bps: 2.5, stamp_bps: 5, slippage_bps: 5 },
};

test('unpublished data renders the fallback text and never a number', () => {
  for (const data of [null, undefined, {}, { metrics: {} }]) {
    const M = SP.model(data, 'test');
    assert.equal(M.published, false);
    const html = SP.render(M, 'metrics');
    assert.match(html, /策略回测结果未发布/);
    assert.doesNotMatch(html, /\d+\.\d+%/);
  }
});

test('evidence gating: dev_only hides values and shows status text; descriptive shows values with n', () => {
  const dev = SP.model(published, 'dev');
  assert.equal(dev.shown, false);
  assert.ok(dev.metrics.every((m) => m.text === '只在开发段看过'));
  const html = SP.render(dev, 'metrics');
  assert.match(html, /按规则不显示数值/);
  assert.doesNotMatch(html, /\+30\.00%/);
  const t = SP.model(published, 'test');
  assert.equal(t.shown, true);
  assert.equal(t.n, 4);
  const h2 = SP.render(t, 'metrics');
  assert.match(h2, /n = 4/);
  assert.match(h2, /历史回放，不是预测/);
  assert.match(h2, /\+12\.00%/);
  assert.match(h2, /买入持有/);
});

test('trades filter by segment and hide returns when gated; properties list assumptions', () => {
  const t = SP.model(published, 'test');
  assert.equal(t.trades.length, 1);
  assert.match(SP.render(t, 'trades'), /\+4\.00%/);
  const d = SP.model(published, 'dev');
  assert.equal(d.trades.length, 1);
  assert.doesNotMatch(SP.render(d, 'trades'), /-3\.00%/);
  const all = SP.model(published, 'all');
  assert.equal(all.trades.length, 2);
  const props = SP.render(t, 'props');
  assert.match(props, /T\+1/);
  assert.match(props, /2\.5 bp/);
  assert.match(props, /R1-top-exit-v1/);
});

test('segment fallback: missing requested segment falls back to test, then all', () => {
  assert.equal(SP.model(published, 'cal').segment, 'test');
  const onlyAll = { rule_id: 'x', metrics: { all: { evidence: 'descriptive', n_trades: 1 } } };
  assert.equal(SP.model(onlyAll, 'test').segment, 'all');
});
