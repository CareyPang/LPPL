'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Core = require('../app/chart-page-core.js');
const Reader = require('../app/chart-readonly-data.js');
const indices = [{ sym: 'sh000001', code: '000001', name: '上证指数' }];

function published(symbol = 'US_NVDA') {
  return {
    symbol, name: 'NVIDIA', asof: '2026-11-20', source: 'fixture-published',
    adjust: 'multiplicative back-adjusted (splits + cash dividends)',
    model_version: 'fixture-v1', stock_meta: { evidence: 'research_candidate' },
    price_history: { dates: ['2026-11-18', '2026-11-19', '2026-11-20'],
      close: [140, 135, 130], open: [141, 140, 135], high: [144, 142, 137],
      low: [139, 132, 128], volume: [100, 150, 160] },
    top: { scale_clusters: { '6-12m': [] } },
  };
}

test('US routes preserve asset identity and do not reinterpret unsupported JP/KR codes', () => {
  const us = Core.parseContext('?code=us_nvda&kind=stock&from=home.html', indices);
  assert.equal(us.valid, true);
  assert.equal(us.market, 'us');
  assert.equal(us.code, 'US_NVDA');
  assert.equal(us.stockCode, 'US_NVDA');
  assert.equal(us.from, 'home.html');
  assert.equal(Core.parseContext('?code=US_NVDA&kind=index', indices).valid, false);
  for (const code of ['JP_N225', 'KR_000660', '^KS11', '../US_NVDA']) {
    assert.equal(Core.parseContext('?code=' + encodeURIComponent(code), indices).valid, false);
  }
  assert.equal(Core.parseContext('?code=000001', indices).assetType, 'index');
  const cn = Core.parseContext('?code=000001&kind=stock', indices);
  assert.equal(cn.assetType, 'stock');
  assert.equal(cn.stockCode, '000001');
  assert.equal(cn.market, 'cn');
});

test('published US candles retain missing OHLC and truthful units and source', () => {
  const raw = published();
  raw.price_history.open[1] = null;
  const market = Reader.marketFromPublished(raw, 'US_NVDA');
  const data = Core.assembleStockData('US_NVDA', raw, market);
  assert.equal(data.symbol, 'US_NVDA');
  assert.equal(data.market, 'us');
  assert.equal(data.currency, 'USD');
  assert.equal(data.quoteUnit, 'USD · 美元');
  assert.equal(data.exchange, '美国市场');
  assert.equal(data.volumeUnit, '');
  assert.equal(data.adjustment, raw.adjust);
  assert.equal(data.modelAdjustment, raw.adjust);
  assert.equal(data.dataSource, raw.source);
  assert.equal(data.bars[1].open, null);
  assert.equal(data.firstVisibleAt, null);
  assert.equal(data.freshness, 'not_established');
});

test('US published market identity mismatch fails and model mismatch preserves only correct market', () => {
  assert.throws(() => Reader.marketFromPublished(published('US_AMD'), 'US_NVDA'), /资产身份/);
  const market = Reader.marketFromPublished(published(), 'US_NVDA');
  assert.throws(() => Core.assembleStockData('US_AMD', null, market), /行情资产身份/);
  const result = Core.assembleStockData('US_NVDA', published('US_AMD'), market);
  assert.equal(result.modelStatus, 'error');
  assert.deepEqual(result.top, {});
  assert.equal(result.symbol, 'US_NVDA');
  assert.equal(result.bars.length, 3);
});

test('missing US publication explains missingness without inventing an identity mismatch', () => {
  for (const raw of [null, undefined]) {
    assert.throws(() => Reader.marketFromPublished(raw, 'US_ARM'), error => {
      assert.equal(error.pending, true);
      assert.match(error.message, /当前没有可用的已发布日线/);
      assert.doesNotMatch(error.message, /身份/);
      return true;
    });
  }
});

test('US historical view reads exact frame and published OHLC only; later candles are excluded', async () => {
  const calls = [];
  const frame = { asof: '2026-11-19', close: 135, w: { '6-12m': ['2026-11-23', '2026-12-02'] },
    clusters: { '6-12m': [{ q20_date: '2026-11-23', q80_date: '2026-12-02', n: 4 }] },
    model_version: 'historical-v1', data_version: 'historical-input-v1' };
  const history = { symbol: 'US_NVDA', evidence: 'research_candidate',
    stock_meta: { evidence: 'research_candidate' }, frames: [frame] };
  const adapter = {
    stock: {
      history: async code => { calls.push('history:' + code); return history; },
      latest: async code => { calls.push('latest:' + code); return published(); },
      market: () => { throw Error('US must not call Worker market'); },
      request: () => { throw Error('Must not request a model'); },
    },
    load: () => { throw Error('Must not use index loader'); },
    replay: { request: () => { throw Error('Must not POST replay'); } },
  };
  const context = Core.parseContext('?code=US_NVDA&kind=stock&asof=2026-11-19', indices);
  const result = await Reader.historical(adapter, context);
  assert.deepEqual(calls, ['history:US_NVDA', 'latest:US_NVDA']);
  assert.equal(result.asof, frame.asof);
  assert.equal(result.bars.length, 2);
  assert.equal(result.market.price.length, 2);
  assert.equal(result.market.asof, '2026-11-19');
  assert.equal(result.market.published_asof, '2026-11-20');
  assert.equal(result.priceHistoryOrigin, 'current_published_version');
  assert.match(result.historyNote, /非当时封存/);
  assert.equal(result.raw.model_version, 'historical-v1');
  assert.equal(result.raw.data_version, 'historical-input-v1');
  assert.equal(result.raw.first_visible_at, null);
  assert.deepEqual(result.top.scale_clusters, frame.clusters);
  const assembled = Core.assembleStockData('US_NVDA', result.raw, result.market);
  assert.equal(assembled.bars.length, 2);
  assert.equal(assembled.modelAsOf, '2026-11-19');
  assert.equal(assembled.modelVersion, 'historical-v1');
});

test('US missing exact history never silently selects nearest frame or starts computation', async () => {
  let latestRead = false;
  const adapter = { stock: {
    history: async () => ({ symbol: 'US_NVDA', frames: [{ asof: '2026-11-18' }] }),
    latest: async () => { latestRead = true; return published(); },
  } };
  const context = Core.parseContext('?code=US_NVDA&asof=2026-11-19', indices);
  await assert.rejects(() => Reader.historical(adapter, context), /只读访问未发起计算/);
  assert.equal(latestRead, false);
  adapter.stock.history = async () => ({ symbol: 'US_AMD', frames: [{ asof: '2026-11-19' }] });
  await assert.rejects(() => Reader.historical(adapter, context), /只读访问未发起计算/);
});
