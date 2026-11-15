'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const StockSearch = require('../app/stock-search.js');

const rows = [
  ['000001', '平安银行', 'payh', 'a'],
  ['600519', '贵州茅台', 'gzmt', 'a'],
  ['000858', '五粮液', 'wly', 'a'],
  ['300059', '东方财富', 'dfcf', 'a'],
  ['600958', '东方证券', 'dfzq', 'a'],
  ['601555', '东吴证券', 'dwzq', 'a'],
  ['600001', '西藏某东公司', 'xczdgs', 'a'],
  ['US_NVDA', '英伟达', 'ywd', 'us'],
  ['sh000300', '沪深300', 'hs300', 'index'],
];

test('Chinese name prefixes narrow from 东 to 东方', () => {
  const east = StockSearch.match(rows, '东', 3);
  assert.ok(east.length > 0);
  assert.ok(east.every((row) => row.name.startsWith('东')));

  const eastMoney = StockSearch.match(rows, '东方');
  assert.deepEqual(eastMoney.map((row) => row.name), ['东方财富', '东方证券']);
});

test('pinyin initials, code prefixes, and exact codes are ranked', () => {
  assert.equal(StockSearch.match(rows, 'dfcf')[0].code, '300059');
  assert.equal(StockSearch.match(rows, 'gzmt')[0].code, '600519');
  assert.equal(StockSearch.match(rows, '6005')[0].code, '600519');
  assert.equal(StockSearch.match(rows, '600519.SH')[0].code, '600519');
  assert.equal(StockSearch.match(rows, 'NVDA')[0].code, 'US_NVDA');
  assert.equal(StockSearch.match(rows, '沪深300')[0].code, 'sh000300');
  assert.equal(StockSearch.match(rows, '000300')[0].code, 'sh000300');
});

test('exact code wins over an earlier prefix and the result limit is respected', () => {
  const codeRows = [
    ['6005190', '扩展代码', 'kzdm', 'a'],
    ['600519', '贵州茅台', 'gzmt', 'a'],
    ['6005191', '另一个前缀', 'lygqz', 'a'],
  ];
  assert.equal(StockSearch.match(codeRows, '600519')[0].name, '贵州茅台');
  assert.equal(StockSearch.match(rows, '0', 2).length, 2);
  assert.deepEqual(StockSearch.match(rows, '   '), []);
});

test('the selected hit is kept only while its query is current', () => {
  const hits = [{ h: 'stock.html?code=600519' }, { h: 'stock.html?code=000858' }];
  assert.equal(StockSearch.selectedMatch(hits, '五粮液', '五粮液', 1), hits[1]);
  assert.equal(StockSearch.selectedMatch(hits, '五粮液', '贵州茅台', 1), null);
  assert.equal(StockSearch.selectedMatch([], '五粮液', '五粮液', 0), null);
});

test('an unlisted six-digit A-share code retains the raw-code route', () => {
  assert.deepEqual(StockSearch.codeFallback(rows, '920002'), {
    t: '920002',
    s: '个股 · A 股',
    h: 'stock.html?code=920002',
  });
  assert.equal(StockSearch.codeFallback(rows, '600519'), null);
  assert.deepEqual(StockSearch.codeFallback(rows, '920002.SH'), {
    t: '920002',
    s: '个股 · A 股',
    h: 'stock.html?code=920002',
  });
});
