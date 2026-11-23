'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Routes = require('../app/od-nav.js');
const Search = require('../app/od-search.js');

const rows = JSON.parse(fs.readFileSync(path.join(__dirname, '../../web/mock/data/market/stock_list.json'), 'utf8')).rows;
const chineseIndices = [
  { sym: 'sh000001', name: '上证指数', code: '000001', alias: ['上证'] },
  { sym: 'sh000300', name: '沪深300', code: '000300', alias: ['沪深300'] },
];
const idx = Routes.catalog(chineseIndices);
function search(query, options = {}) {
  return Routes.search(Search, { idx, rows, query, filter: 'all', limit: 20, ...options });
}

test('real stock-list MRVL keeps its US stock identity and opens the shared chart', () => {
  for (const query of ['MRVL', 'mrvl', 'US_MRVL', '迈威尔']) {
    const hit = search(query)[0];
    assert.ok(hit, query);
    assert.equal(hit.code, 'US_MRVL');
    assert.equal(hit.kind, 'us');
    const href = new URL(hit.h, 'https://example.test/');
    assert.equal(href.pathname, '/chart.html');
    assert.equal(href.searchParams.get('code'), 'US_MRVL');
    assert.equal(href.searchParams.get('kind'), 'stock');
    assert.ok(!hit.h.includes('sh000300'));
  }
});

test('known global aliases select explicit index namespaces, never a US stock ticker', () => {
  const cases = [
    ['SPX', 'US_SPX'], ['S&P500', 'US_SPX'], ['^GSPC', 'US_SPX'],
    ['IXIC', 'US_IXIC'], ['纳指综合', 'US_IXIC'], ['NDX', 'US_NDX'],
    ['NASDAQ 100', 'US_NDX'], ['道琼斯', 'US_DJI'], ['DJI', 'US_DJI'],
    ['日经225', 'JP_N225'], ['^N225', 'JP_N225'], ['KOSPI', 'KR_KOSPI'],
    ['KOPSI', 'KR_KOSPI'], ['^KS11', 'KR_KOSPI'], ['KOSDAQ', 'KR_KOSDAQ'], ['^KQ11', 'KR_KOSDAQ'],
  ];
  for (const [query, code] of cases) {
    const hits = search(query);
    assert.equal(hits.length, 1, query);
    assert.equal(hits[0].kind, 'index', query);
    assert.equal(hits[0].sym, code, query);
    assert.equal(new URL(hits[0].h, 'https://example.test/').searchParams.get('kind'), 'index');
  }
});

test('mixed global catalog never registers MRVL as an index and keeps explicit aliases', () => {
  const mixed = Routes.catalog(chineseIndices, [
    { sym: 'US_SPX', name: '标普500', kind: 'index', market: 'us' },
    { sym: 'US_MRVL', name: '迈威尔科技', kind: 'stock', market: 'us' },
  ]);
  assert.equal(Routes.findIndex('US_MRVL', mixed), null);
  assert.equal(Routes.findIndex('^GSPC', mixed).code, 'US_SPX');
  assert.equal(mixed.filter((x) => x.sym === 'US_SPX').length, 1);
});

test('same A-share numeric identifier preserves the stock/index distinction', () => {
  const hits = search('000001');
  const index = hits.find((h) => h.kind === 'index');
  const stock = hits.find((h) => h.kind === 'stock');
  assert.equal(index.sym, 'sh000001');
  assert.equal(stock.code, '000001');
  assert.equal(new URL(index.h, 'https://example.test/').searchParams.get('kind'), 'index');
  assert.equal(new URL(stock.h, 'https://example.test/').searchParams.get('kind'), 'stock');
});

test('unknown symbols and invalid recent index identities produce no default-index navigation', () => {
  for (const query of ['不存在的指数', 'ZQZZQ', 'US_ZQZZQ', 'JP_UNKNOWN', 'KR_UNKNOWN']) {
    assert.deepEqual(search(query), [], query);
  }
  assert.equal(Routes.route({ code: 'US_MRVL', kind: 'index', h: 'index.html?code=US_MRVL' }, idx, rows), null);
  assert.equal(Routes.route({ code: 'JP_UNKNOWN', kind: 'index' }, idx, rows), null);
});

test('a US ticker is offered during row-loading only when its published catalog identifies it', () => {
  assert.deepEqual(search('MRVL', { rows: [] }), []);
  const hit = search('MRVL', { rows: [], published: new Set(['US_MRVL']) })[0];
  assert.equal(hit.code, 'US_MRVL');
  assert.match(hit.h, /kind=stock/);
  assert.deepEqual(search('ZQZZQ', { rows: [], published: new Set(['US_MRVL']) }), []);
});

test('existing recent records are normalized away from the legacy index/stock page paths', () => {
  const oldStock = Routes.route({ code: 'US_MRVL', kind: 'us', t: '迈威尔科技', h: 'stock.html?code=US_MRVL' }, idx, rows);
  const oldIndex = Routes.route({ code: '000300', sym: 'sh000300', kind: 'index', h: 'index.html?code=sh000300' }, idx, rows);
  assert.match(oldStock.h, /^chart\.html\?code=US_MRVL&kind=stock/);
  assert.match(oldIndex.h, /^chart\.html\?code=sh000300&kind=index/);
});

test('stock/index type filters remain distinct for global assets', () => {
  assert.deepEqual(search('MRVL', { filter: 'index' }), []);
  assert.deepEqual(search('KOSPI', { filter: 'stock' }), []);
  assert.equal(search('MRVL', { filter: 'stock' })[0].kind, 'us');
});
