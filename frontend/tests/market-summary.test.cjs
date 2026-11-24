'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Summary = require('../app/market-summary.js');

test('builds four linked summary rows from available market data', () => {
  const result = Summary.build({
    indices: [{ name: '上证指数', change: '+1.20%' }],
    events: ['金风科技解禁', '浦发银行除息', '第三项'],
    watchlist: [{ code: '600519', name: '贵州茅台' }],
    relatedCount: 2,
    models: [{ symbol: 'sh000300', change: '新出现' }, { symbol: 'sh000001', change: '不变' }],
  });
  assert.equal(result.lines.length, 4);
  assert.deepEqual(result.lines.map(row => row.href), ['#s-sentiment', '#s-events', '#s-news', '#model-range-details']);
  assert.equal(result.lines[0].text, '上证指数 +1.20%');
  assert.equal(result.lines[1].text, '今日 3 项：金风科技解禁；浦发银行除息');
  assert.equal(result.lines[2].text, '今日 2 条自选相关快讯');
  assert.equal(result.lines[3].text, '暂无可比较的模型区间');
});

test('model summary names the compared dates', () => {
  const result = Summary.build({
    models: [
      { change: '起点后移 4 个交易日', previousAsOf: '2025-08-18', currentAsOf: '2025-08-25' },
      { change: '不变', previousAsOf: '2025-08-18', currentAsOf: '2025-08-25' },
    ],
  });
  assert.equal(result.lines[3].text, '2025-08-18→2025-08-25：1 项变化，1 项不变');
});

test('event retries target the event loader instead of summary data', () => {
  assert.equal(Summary.retryTarget('events'), 'events');
  assert.equal(Summary.retryTarget('index'), 'summary');
  assert.equal(Summary.retryTarget('models'), 'summary');
});

test('uses reason codes for missing sources and empty watchlists', () => {
  const result = Summary.build({
    indices: [],
    indicesReason: 'unavailable',
    events: [],
    eventsReason: 'empty',
    watchlist: [],
    models: [{ symbol: 'sh000688', reason: 'not_applicable' }],
    modelsReason: 'not_applicable',
  });
  assert.equal(result.lines[0].reason, 'unavailable');
  assert.equal(result.lines[0].text, '暂时无法读取');
  assert.equal(result.lines[1].text, '数据源返回空结果');
  assert.equal(result.lines[2].reason, 'not_applicable');
  assert.equal(result.lines[3].text, '不适用');
});

test('hidden-evidence model rows are reported as evidence-gated, not inapplicable', () => {
  const result = Summary.build({
    models: [{ symbol: 'sh000001', scale: '6-12m', reason: 'hidden_evidence' }],
    modelsReason: 'hidden_evidence',
  });
  assert.equal(result.modelDetails[0].reason, 'hidden_evidence');
  assert.equal(result.lines[3].reason, 'hidden_evidence');
  assert.equal(result.lines[3].text, '证据不足，不显示');
});

test('index selection falls back to published closes and fills missing live rows', () => {
  const closes = [
    { symbol: 'sh000001', name: '上证指数', change: '-1.44%（收盘 2026-10-30）' },
    { symbol: 'sz399001', name: '深证成指', change: '+0.20%（收盘 2026-10-30）' },
  ];
  const fallback = Summary.selectIndexRows([], closes, 'unavailable');
  assert.equal(fallback.source, 'published');
  assert.equal(fallback.rows[0].change, '-1.44%（收盘 2026-10-30）');
  assert.equal(fallback.reason, null);

  const mixed = Summary.selectIndexRows([
    { symbol: 'sh000001', name: '上证指数', change: '+1.00%（盘中 10:32）' },
  ], closes, 'empty');
  assert.equal(mixed.source, 'mixed');
  assert.deepEqual(mixed.rows.map(row => row.change), [
    '+1.00%（盘中 10:32）',
    '+0.20%（收盘 2026-10-30）',
  ]);
  assert.equal(Summary.selectIndexRows([], [], 'empty').reason, 'empty');
});

test('model comparison uses the two newest published frames not after the latest result', () => {
  const frames = [
    { asof: '2025-08-18' },
    { asof: '2026-11-02' },
    { asof: '2025-08-25' },
  ];
  const pair = Summary.historyPair(frames, '2026-10-30');
  assert.equal(pair.current.asof, '2025-08-25');
  assert.equal(pair.previous.asof, '2025-08-18');
});
