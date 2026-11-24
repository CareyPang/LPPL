'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Core = require('../app/chart-page-core.js');
const chartPageSource = fs.readFileSync(path.join(__dirname, '..', 'app', 'chart-page.js'), 'utf8');

const fixtures = path.join(__dirname, 'fixtures');
const indexSymbols = [
  { sym: 'sh000001', code: '000001', name: '上证指数' },
  { sym: 'sz399001', code: '399001', name: '深证成指' },
];

test('context parsing distinguishes the Shanghai index from Shenzhen stock 000001', () => {
  const index = Core.parseContext(
    '?code=sh000001&scale=6-12m&focus=interval%3A6-12m%3Amain&from=index.html%3Fcode%3Dsh000001',
    indexSymbols,
  );
  const stock = Core.parseContext('?code=sz000001&scale=12-24m', indexSymbols);
  const numericIndex = Core.parseContext('?code=000001', indexSymbols);

  assert.equal(index.valid, true);
  assert.equal(index.assetType, 'index');
  assert.equal(index.code, 'sh000001');
  assert.equal(index.scale, '6-12m');
  assert.equal(index.from, 'index.html?code=sh000001');
  assert.equal(stock.assetType, 'stock');
  assert.equal(stock.code, 'sz000001');
  assert.equal(stock.stockCode, '000001');
  assert.equal(stock.scale, '12-24m');
  assert.equal(numericIndex.assetType, 'index');
  assert.equal(numericIndex.code, 'sh000001');
});

test('context parsing rejects unsupported symbols and normalizes invalid scales', () => {
  const invalid = Core.parseContext('?code=outside-symbol&scale=bad', indexSymbols);
  assert.equal(invalid.valid, false);
  assert.equal(invalid.scale, '6-12m');
});

test('context parsing accepts only real YYYY-MM-DD as-of dates', () => {
  const valid = Core.parseContext('?code=sh000001&asof=2015-06-12', indexSymbols);
  assert.equal(valid.asof, '2015-06-12');

  for (const value of ['2015-6-12', '2015-02-29', '2015-13-01', '2015-06-12x']) {
    assert.equal(Core.parseContext(`?code=sh000001&asof=${value}`, indexSymbols).asof, '', value);
  }
});

test('historical chart routes through the read-only reader and keeps explicit latest navigation', () => {
  assert.match(chartPageSource, /Reader\.historical\(LPPL, context\)/);
  assert.doesNotMatch(chartPageSource, /LPPL\.load\(context\.code, /);
  assert.match(chartPageSource, /params\.delete\('asof'\)/);
  assert.match(chartPageSource, /latestLink\.hidden = !context\.asof/);
});

test('missing published model copy is uncertain and offers retry plus stock-page action', () => {
  assert.match(
    chartPageSource,
    /当前没有可用的已发布模型结果/,
  );
  assert.match(chartPageSource, /模型结果读取失败：/);
  assert.match(chartPageSource, /retry\.textContent = '重试读取'/);
  assert.match(chartPageSource, /retry\.addEventListener\('click', function \(\) \{ void loadModel\(sequence\); \}\)/);
  assert.match(chartPageSource, /action\.textContent = '回标的页发起计算'/);
});

test('from allowlist rejects external, protocol, backslash, and non-asset paths', () => {
  const unsafe = [
    'https://evil.example/',
    '//evil.example',
    'javascript:alert(1)',
    '/\\evil',
    'tools.html?x=1',
    '../stock.html?code=600519',
  ];
  for (const value of unsafe) {
    assert.equal(Core.safeFrom(value, 'stock', 'sh600519', '600519'), 'stock.html?code=600519', value);
    assert.equal(Core.safeFrom(value, 'index', 'sh000001', ''), 'index.html?code=sh000001', value);
    const stockQuery = '?code=sh600519&from=' + encodeURIComponent(value);
    const indexQuery = '?code=sh000001&from=' + encodeURIComponent(value);
    assert.equal(Core.parseContext(stockQuery, indexSymbols).from, 'stock.html?code=600519', value);
    assert.equal(Core.parseContext(indexQuery, indexSymbols).from, 'index.html?code=sh000001', value);
  }
  assert.equal(Core.safeFrom('stock.html?code=600519', 'stock', 'sh600519', '600519'), 'stock.html?code=600519');
  assert.equal(Core.safeFrom('home.html?tab=market', 'index', 'sh000001'), 'home.html?tab=market');
  assert.equal(Core.parseContext('?code=sh600519', indexSymbols).from, 'stock.html?code=600519');
  assert.equal(Core.parseContext('?code=sh000001', indexSymbols).from, 'index.html?code=sh000001');
});

test('descriptive bands without finite n are hidden from charts and values', () => {
  const top = {
    scale_windows: [
      { scale: '6-12m', n: 4 },
      { scale: '6-12m', n: NaN },
    ],
    scale_clusters: {
      '6-12m': [{ n: 5 }, { n: undefined }],
      '3-6m': [{ n: undefined }],
    },
    clusters: [
      { scale: '6-12m', n: 2 },
      { scale: '6-12m', n: null },
      { scale: '3-6m', n: null },
    ],
  };
  const filtered = Core.filterDescriptiveBands(top, {
    '6-12m': 'descriptive',
    '3-6m': 'test',
  });

  assert.equal(filtered.scale_windows.length, 1);
  assert.equal(filtered.scale_clusters['6-12m'].length, 1);
  assert.equal(filtered.scale_clusters['3-6m'].length, 1);
  assert.equal(filtered.clusters.length, 2);
  assert.equal(top.scale_windows.length, 2);
  assert.deepEqual(Core.bandEvidencePolicy('descriptive', { n: NaN }), {
    draw: false,
    showDates: false,
    showShare: false,
    message: '当前数据不支持显示描述性数值',
  });
  assert.equal(Core.bandEvidencePolicy('descriptive', { n: 5 }).draw, true);
  assert.equal(Core.bandEvidencePolicy('test', {}).draw, true);
  assert.match(chartPageSource, /top = Core\.filterDescriptiveBands\(top, evidenceCodes\)/);
  assert.match(chartPageSource, /if \(policy\.showDates\)[\s\S]*?dates\.textContent = dateRange\(band\)/);
  assert.match(chartPageSource, /if \(!policy\.draw\) \{\s*extra\.textContent = policy\.message/);
});

test('index assembly uses the adapted published bars and metadata without mixing sources', () => {
  const raw = JSON.parse(fs.readFileSync(path.join(fixtures, 'sh000001_latest.json'), 'utf8'));
  raw.display_code = 'N225';
  const bars = raw.price_history.dates.map((date, index) => ({
    date,
    open: raw.price_history.open[index] ?? raw.price_history.close[index],
    high: raw.price_history.high[index] ?? raw.price_history.close[index],
    low: raw.price_history.low[index] ?? raw.price_history.close[index],
    close: raw.price_history.close[index],
    volume: raw.price_history.volume[index] ?? null,
  }));
  const data = Core.assembleIndexData('sh000001', {
    raw, bars, top: raw.top, asof: raw.asof, name: raw.name,
    sym: { sym: raw.symbol, name: raw.name },
  });
  assert.equal(data.assetType, 'index');
  assert.equal(data.symbol, 'sh000001');
  assert.equal(data.displayCode, 'N225');
  assert.equal(data.name, '上证指数');
  assert.equal(data.asof, raw.asof);
  assert.deepEqual(data.bars, bars);
  assert.equal(data.modelVersion, raw.model_version);
  assert.equal(data.predictionId, null);
});

test('stock assembly keeps unadjusted market bars separate from the model cutoff', () => {
  const latest = JSON.parse(fs.readFileSync(path.join(fixtures, 'stock_600519.json'), 'utf8'));
  const market = JSON.parse(fs.readFileSync(path.join(fixtures, 'stock_600519_market.json'), 'utf8'));
  const data = Core.assembleStockData('sh600519', latest, market, null);

  assert.equal(data.assetType, 'stock');
  assert.equal(data.symbol, 'sh600519');
  assert.equal(data.asof, latest.asof);
  assert.equal(data.modelAsOf, latest.asof);
  assert.equal(data.marketAsOf, market.asof);
  assert.equal(data.adjustment, 'none');
  assert.equal(data.dataSource, market.source);
  assert.deepEqual(data.bars, market.price);
  assert.equal(data.modelVersion, latest.model_version);
  assert.equal(data.predictionId, null);
  assert.equal(data.modelStatus, 'ok');
});

test('market metadata follows the selected intraday source and restores daily metadata', () => {
  const daily = {
    assetType: 'stock',
    marketAsOf: '2026-11-17',
    dataSource: 'tencent_fqkline',
    adjustment: 'none',
  };
  const intraday = {
    period: '30',
    status: 'ready',
    source: 'sina',
    limits: { last: '2026-11-18 15:00:00' },
  };
  assert.deepEqual(Core.marketMetadata(daily, '30', intraday), {
    marketDate: '行情时间 2026-11-18 15:00:00',
    dataSource: '新浪行情 · 30 分钟 · 不复权',
  });
  assert.deepEqual(Core.marketMetadata(daily, '60', {
    period: '60',
    status: 'ready',
    source: 'tencent',
    limits: { last: '2026-11-18 14:30:00' },
  }), {
    marketDate: '行情时间 2026-11-18 14:30:00',
    dataSource: '腾讯行情 · 60 分钟 · 不复权',
  });
  assert.deepEqual(Core.marketMetadata(daily, 'd', intraday), {
    marketDate: '行情日期 2026-11-17',
    dataSource: '腾讯行情',
  });
});

test('international terminal metadata uses Chinese labels instead of provider codes', () => {
  assert.deepEqual(Core.marketMetadata({
    assetType: 'index',
    marketAsOf: '2026-11-23',
    dataSource: 'Yahoo Finance v8 chart',
    adjustment: 'none',
  }, 'd'), {
    marketDate: '行情日期 2026-11-23',
    dataSource: 'Yahoo Finance',
  });
  assert.equal(Core.modelAdjustmentLabel('none', 'index'), '不复权');
  assert.equal(Core.modelAdjustmentLabel('provider_adjclose_ratio_OHLC', 'stock'), '按调整收盘价比例复权');
  assert.equal(Core.modelVersionLabel('global_sparse27_v1_production_v2_box'), '国际市场稀疏窗口研究样本');
  assert.equal(Core.volumeUnitLabel('vendor_native'), '');
  assert.equal(Core.currencyLabel('JPY'), '日元');
  assert.match(chartPageSource, /setText\('asset-code', data\.displayCode \|\| data\.symbol\)/);
  assert.match(chartPageSource, /setText\('identity-strip-code', data\.displayCode \|\| data\.symbol\)/);
});

test('stock assembly keeps market bars when the latest model is missing and requires market data', () => {
  const market = JSON.parse(fs.readFileSync(path.join(fixtures, 'stock_600519_market.json'), 'utf8'));
  const data = Core.assembleStockData('sh600519', null, market, null);

  assert.equal(data.modelStatus, 'missing');
  assert.equal(data.modelAsOf, '');
  assert.deepEqual(data.top, {});
  assert.deepEqual(data.evidence_levels, {});
  assert.equal(data.modelVersion, null);
  assert.equal(data.predictionId, null);
  assert.equal(data.name, market.name || market.stock_name || 'sh600519');
  assert.deepEqual(data.bars, market.price);
  assert.throws(
    () => Core.assembleStockData('sh600519', null, null, null),
    /行情接口未返回 K 线；未用模型价格替代行情。/,
  );
});

test('stock assembly preserves or infers exchange prefixes for numeric codes', () => {
  const market = JSON.parse(fs.readFileSync(path.join(fixtures, 'stock_600519_market.json'), 'utf8'));
  const publishedSymbol = Core.assembleStockData('600519', null, market, null);
  assert.equal(publishedSymbol.symbol, 'sh600519');
  assert.equal(publishedSymbol.exchange, '上海证券交易所');

  const marketWithoutSymbol = Object.assign({}, market);
  delete marketWithoutSymbol.symbol;
  const inferredSymbol = Core.assembleStockData('600519', null, marketWithoutSymbol, null);
  assert.equal(inferredSymbol.symbol, 'sh600519');
  assert.equal(inferredSymbol.exchange, '上海证券交易所');
});

test('stock assembly reports a rejected latest model without dropping market bars', () => {
  const market = JSON.parse(fs.readFileSync(path.join(fixtures, 'stock_600519_market.json'), 'utf8'));
  const data = Core.assembleStockData('sh600519', null, market, null, new Error('读取失败'));

  assert.equal(data.modelStatus, 'error');
  assert.equal(data.modelMessage, '读取失败');
  assert.deepEqual(data.bars, market.price);
});

test('stock calendar prefers the published result and accepts the shared-calendar fallback', () => {
  const latest = JSON.parse(fs.readFileSync(path.join(fixtures, 'stock_601838.json'), 'utf8'));
  const market = JSON.parse(fs.readFileSync(path.join(fixtures, 'stock_601838_market.json'), 'utf8'));
  const published = latest.future_calendar;
  const fallback = { holidays_through: '2027-12-31', source: 'shared CN calendar' };
  assert.deepEqual(Core.assembleStockData('sh601838', latest, market, fallback).future_calendar, published);

  const withoutCalendar = { asof: latest.asof, top: latest.top };
  assert.deepEqual(
    Core.assembleStockData('sh601838', withoutCalendar, market, fallback).future_calendar,
    fallback,
  );
});
