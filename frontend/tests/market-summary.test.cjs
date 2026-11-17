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
  assert.deepEqual(result.lines.map(row => row.href), ['#s-sentiment', '#s-events', '#s-news', '#s-model-ranges']);
  assert.equal(result.lines[0].text, '上证指数 +1.20%');
  assert.equal(result.lines[1].text, '今日 3 项：金风科技解禁；浦发银行除息');
  assert.equal(result.lines[2].text, '今日 2 条自选相关快讯');
  assert.equal(result.lines[3].text, '最近发布主簇：1 项变化，1 项不变');
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
