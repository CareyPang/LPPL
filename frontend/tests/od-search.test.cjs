'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const OdSearch = require('../app/od-search.js');

const idx = [
  { sym: 'sh000001', name: '上证指数', code: '000001', alias: ['上证', '上证综指'] },
  { sym: 'sh000688', name: '科创50', code: '000688', alias: ['科创板50'] },
];
const rows = [
  ['000001', '平安银行', 'payh', 'a'],
  ['600519', '贵州茅台', 'gzmt', 'a'],
  ['300059', '东方财富', 'dfcf', 'a'],
  ['688981', '中芯国际', 'zxgj', 'a'],
  ['US_NVDA', '英伟达', 'ywd', 'us'],
  ['sh000001', '上证指数', 'szzs', 'index'],
];

class MemoryStorage {
  constructor() { this.m = new Map(); }
  getItem(k) { return this.m.has(k) ? this.m.get(k) : null; }
  setItem(k, v) { this.m.set(k, String(v)); }
}

test('board labels follow A-share code prefixes', () => {
  assert.equal(OdSearch.board('600519'), '沪主');
  assert.equal(OdSearch.board('000001'), '深主');
  assert.equal(OdSearch.board('300059'), '创业');
  assert.equal(OdSearch.board('688981'), '科创');
  assert.equal(OdSearch.board('sh000001'), '');
});

test('search merges indices and stocks, dedupes the same target and tags published results', () => {
  const all = OdSearch.search({ idx, rows, query: '上证', filter: 'all', published: ['600519'] });
  assert.equal(all.filter((h) => h.kind === 'index').length, 1);
  assert.equal(all[0].h, 'index.html?code=sh000001');
  assert.equal(all[0].chart, 'index.html?code=sh000001');

  const mt = OdSearch.search({ idx, rows, query: 'gzmt', published: new Set(['600519']) });
  assert.equal(mt[0].code, '600519');
  assert.equal(mt[0].published, true);
  assert.deepEqual(mt[0].tags, ['个股', '沪主']);
  assert.equal(mt[0].h, 'stock.html?code=600519');
});

test('index filter still matches index pinyin from the stock list rows', () => {
  const hits = OdSearch.search({ idx, rows, query: 'szzs', filter: 'index' });
  assert.equal(hits.length, 1);
  assert.equal(hits[0].kind, 'index');
  assert.equal(hits[0].h, 'index.html?code=sh000001');
});

test('filter restricts kinds: index only / stock only', () => {
  const onlyIdx = OdSearch.search({ idx, rows, query: '000001', filter: 'index' });
  assert.ok(onlyIdx.length === 1 && onlyIdx[0].kind === 'index');
  const onlyStock = OdSearch.search({ idx, rows, query: '000001', filter: 'stock' });
  assert.ok(onlyStock.every((h) => h.kind !== 'index'));
  assert.equal(onlyStock[0].code, '000001');
});

test('six-digit code without a list row still opens the stock page; US tickers map to the watch list', () => {
  assert.equal(OdSearch.search({ idx, rows: [], query: '601888' })[0].h, 'stock.html?code=601888');
  const us = OdSearch.search({ idx, rows: [], query: 'nvda' })[0];
  assert.equal(us.kind, 'us');
  assert.equal(us.h, 'stock.html?code=US_NVDA');
});

test('recent list dedupes, keeps newest first and caps at RECENT_MAX', () => {
  const st = new MemoryStorage();
  OdSearch.pushRecent(st, { code: '600519', name: '贵州茅台', kind: 'stock' });
  OdSearch.pushRecent(st, { code: 'sh000001', sym: 'sh000001', name: '上证指数', kind: 'index' });
  OdSearch.pushRecent(st, { code: '600519', name: '贵州茅台', kind: 'stock' });
  const list = OdSearch.readRecent(st);
  assert.deepEqual(list.map((x) => x.code), ['600519', 'sh000001']);
  OdSearch.pushRecent(st, { code: '600519', name: '600519', kind: 'stock' });
  assert.equal(OdSearch.readRecent(st)[0].name, '贵州茅台');
  OdSearch.pushRecent(st, { code: '000001', name: '平安银行', kind: 'stock' });
  OdSearch.pushRecent(st, { code: '000001', sym: 'sh000001', name: '上证指数', kind: 'index' });
  assert.deepEqual(OdSearch.readRecent(st).slice(0, 2).map((x) => x.kind), ['index', 'stock']);
  for (let i = 0; i < 12; i += 1) OdSearch.pushRecent(st, { code: String(100000 + i), name: 'x' + i });
  assert.equal(OdSearch.readRecent(st).length, OdSearch.RECENT_MAX);
  const hits = OdSearch.recentHits(st);
  assert.equal(hits[0].h, 'stock.html?code=100011');
  assert.equal(OdSearch.readRecent(null).length, 0);
});
