'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const StockCatalog = require('../app/stock-catalog.js');

const catalog = {
  n: 5,
  index_names: { sh000300: '沪深300', sh000016: '上证50', sh000001: '上证指数', sh000928: '中证能源' },
  rows: [
    { symbol: 'sh000001', code: '000001', name: '上证指数', exchange: 'SSE', type: 'index', board: null, member_of: [], dashboard: true },
    { symbol: 'sh000928', code: '000928', name: '中证能源', exchange: 'SSE', type: 'industry', board: null, member_of: [], dashboard: false },
    { symbol: 'sh600519', code: '600519', name: '贵州茅台', exchange: 'SSE', type: 'stock', board: '沪市主板', member_of: ['sh000016', 'sh000300'], dashboard: false },
    { symbol: 'sz300059', code: '300059', name: '东方财富', exchange: 'SZSE', type: 'stock', board: '创业板', member_of: ['sh000300'], dashboard: false },
    { symbol: 'sh688981', code: '688981', name: '中芯国际', exchange: 'SSE', type: 'stock', board: '科创板', member_of: ['sh000300'], dashboard: false },
  ],
};
const published = { 600519: { name: '贵州茅台' }, 300059: { name: '东方财富' } };

test('normalize maps type, board short label, membership names, published flag and links', () => {
  const rows = StockCatalog.normalize(catalog, published);
  assert.equal(rows.length, 5);
  const mt = rows.find((r) => r.code === '600519');
  assert.equal(mt.typeLabel, '个股');
  assert.equal(mt.boardShort, '沪主');
  assert.deepEqual(mt.memberNames, ['上证50', '沪深300']);
  assert.equal(mt.published, true);
  assert.equal(mt.href, 'stock.html?code=600519');
  const idx = rows.find((r) => r.type === 'index');
  assert.equal(idx.published, true);
  assert.equal(idx.href, 'index.html?code=sh000001');
  const ind = rows.find((r) => r.type === 'industry');
  assert.equal(ind.href, '');
  assert.equal(ind.published, false);
  assert.equal(rows.find((r) => r.code === '688981').published, false);
});

test('filter combines type, board, membership, published and query; counts follow the filtered set', () => {
  const rows = StockCatalog.normalize(catalog, published);
  assert.equal(StockCatalog.filter(rows, { type: 'stock' }).length, 3);
  assert.equal(StockCatalog.filter(rows, { type: 'stock', board: '科创板' })[0].code, '688981');
  assert.equal(StockCatalog.filter(rows, { member: 'sh000016' }).length, 1);
  assert.deepEqual(StockCatalog.filter(rows, { published: 'yes' }).map((r) => r.code).sort(), ['000001', '300059', '600519']);
  assert.equal(StockCatalog.filter(rows, { q: '茅台' })[0].code, '600519');
  assert.equal(StockCatalog.filter(rows, { q: '3000' }).length, 1);
  assert.deepEqual(
    StockCatalog.filter(rows, { board: '沪市主板' }).map((r) => r.code).sort(),
    ['600519'],
  );
  assert.deepEqual(StockCatalog.counts(StockCatalog.filter(rows, { type: 'all' })), { index: 1, industry: 1, stock: 3, published: 3 });
});

test('mount works without an injected window', () => {
  const el = { innerHTML: '', addEventListener() {} };
  StockCatalog.mount({ el, catalog, published });
  assert.match(el.innerHTML, /标的目录/);
});

test('index navigation preserves its saved scroll position', async () => {
  let click, onScroll, value = null, scrollY = 800;
  const el = {
    innerHTML: '',
    addEventListener(type, listener) { if (type === 'click') click = listener; },
  };
  const win = {
    get scrollY() { return scrollY; },
    addEventListener(type, listener) { if (type === 'scroll') onScroll = listener; },
  };
  const storage = {
    getItem() { return null; },
    setItem(_key, raw) { value = raw; },
  };
  StockCatalog.mount({ el, catalog, published, window: win, storage });
  onScroll();
  const index = el.__rows.findIndex(row => row.type === 'index');
  const anchor = { dataset: { i: String(index) } };
  click({
    target: { closest: selector => selector === 'a[data-i]' ? anchor : null },
    button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false,
  });
  scrollY = 0;
  onScroll();
  await new Promise(resolve => setTimeout(resolve, 150));
  assert.equal(JSON.parse(value).scrollY, 800);
});

test('sort orders by column with code as tiebreaker and supports descending', () => {
  const rows = StockCatalog.normalize(catalog, published);
  assert.deepEqual(StockCatalog.sort(rows, 'type').map((r) => r.type), ['index', 'industry', 'stock', 'stock', 'stock']);
  assert.deepEqual(StockCatalog.sort(rows, 'code', 'desc').map((r) => r.code), ['688981', '600519', '300059', '000928', '000001']);
  assert.equal(StockCatalog.sort(rows, 'published')[0].published, true);
  assert.equal(StockCatalog.sort(rows, 'board').slice(-2).every((r) => !r.board), true);
});

test('catalog state serialization validates fields and drops unknown keys', () => {
  const raw = StockCatalog.serializeState({
    q: '茅台', type: 'stock', board: '创业板', member: 'sh000300',
    published: 'yes', sort: 'name', dir: 'desc', dense: true, injected: 'ignored',
  }, 812.9);
  assert.deepEqual(JSON.parse(raw), {
    q: '茅台', type: 'stock', board: '创业板', member: 'sh000300',
    published: 'yes', sort: 'name', dir: 'desc', dense: true, scrollY: 812,
  });
  assert.deepEqual(StockCatalog.parseState(raw), {
    state: {
      q: '茅台', type: 'stock', board: '创业板', member: 'sh000300',
      published: 'yes', sort: 'name', dir: 'desc', dense: true,
    },
    scrollY: 812,
  });
});

test('catalog state parsing validates corrupt values and URL query overrides stored q', () => {
  assert.deepEqual(StockCatalog.parseState(JSON.stringify({
    q: 'stored', type: 'unknown', board: 'unknown', member: 'unknown',
    published: 'unknown', sort: 'unknown', dir: 'sideways', dense: 'yes',
    scrollY: -1, extra: true,
  }), 'from-url'), {
    state: {
      q: 'from-url', type: 'all', board: 'all', member: 'all',
      published: 'all', sort: 'code', dir: 'asc', dense: false,
    },
    scrollY: 0,
  });
  assert.equal(StockCatalog.parseState('{bad json').scrollY, 0);
});
