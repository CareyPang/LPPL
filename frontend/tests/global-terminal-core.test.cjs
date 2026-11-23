'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Core = require('../app/chart-page-core.js');
const Reader = require('../app/chart-readonly-data.js');
const Terminal = require('../app/unified-terminal.js');

const host = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/lppl-data.js'), 'utf8'), { window: host, URL, URLSearchParams });
const indices = host.LPPL.SYMS;
const assets = host.LPPL.GLOBAL_SYMS;
const identities = new Map(Array.from(assets, (item) => [item.sym, item]));
function context(code, asof = '') {
  const item = identities.get(code);
  return Core.parseContext('?code=' + code + '&kind=' + item.kind + (asof ? '&asof=' + asof : ''), indices, assets);
}
function raw(code, asof = '2026-11-23') {
  const item = identities.get(code);
  return { symbol: code, name: item.name, market: item.market, currency: item.currency, exchange: item.exchange,
    timezone: item.timezone, asof, model_version: 'fixture-v1', first_visible_at: null,
    top: { lppls_confidence: { evidence: 'research_candidate' } }, stock_meta: { evidence: 'research_candidate' },
    price_history: { dates: ['2026-11-19', '2026-11-20', '2026-11-23'], open: [100, 101, 102],
      high: [103, 104, 105], low: [98, 99, 100], close: [102, 103, 104], volume: [12, 14, 15],
      source: 'test fixture', adjustment: 'none', volume_unit: 'vendor_native' } };
}
function adapter(overrides = {}) {
  const calls = [];
  const prohibited = (name) => () => { calls.push(name); throw Error('unexpected ' + name); };
  const api = { calls, load: prohibited('A-index-load'), history: prohibited('A-index-history'),
    replay: { result: prohibited('A-worker-replay') },
    stock: { latest: prohibited('stock-latest'), history: prohibited('stock-history'), market: prohibited('A-worker-market') },
    global: {
      isAsset: (code) => identities.has(code),
      latest: async (code) => { calls.push(['latest', code]); return raw(code); },
      result: async (code, asof) => { calls.push(['result', code, asof]); return raw(code, asof); },
      history: async (code) => { calls.push(['history', code]); return { symbol: code, frames: [{ asof: '2026-11-20' }] }; },
      ...overrides,
    } };
  return api;
}

test('all seven international indices preserve canonical identity, market and currency', () => {
  for (const item of assets.filter((x) => x.kind === 'index')) {
    const ctx = Core.parseContext('?code=' + item.sym.toLowerCase() + '&kind=index', indices, assets);
    assert.equal(ctx.valid, true, item.sym);
    assert.equal(ctx.code, item.sym);
    assert.equal(ctx.stockCode, '');
    assert.equal(ctx.assetType, 'index');
    assert.equal(ctx.market, item.market);
    assert.equal(ctx.currency, item.currency);
    assert.equal(Reader.sameSymbol(item.sym, ctx), true);
    assert.equal(Core.parseContext('?code=' + item.sym + '&kind=stock', indices, assets).valid, false);
  }
});

test('MRVL remains a stock while unsupported Japanese/Korean identities stay invalid', () => {
  const mrvl = context('US_MRVL');
  assert.equal(mrvl.assetType, 'stock');
  assert.equal(mrvl.stockCode, 'US_MRVL');
  assert.equal(mrvl.exchange, 'NASDAQ');
  assert.equal(mrvl.currency, 'USD');
  for (const code of ['JP_UNKNOWN', 'KR_UNKNOWN']) assert.equal(Core.parseContext('?code=' + code, indices, assets).valid, false);
});

test('international current reads use only their own global payload and retain exchange/currency', async () => {
  for (const item of assets.filter((x) => x.kind === 'index')) {
    const api = adapter(), ctx = context(item.sym);
    const result = await Reader.currentResult(api, ctx);
    const data = Core.assembleIndexData(ctx.code, result);
    assert.deepEqual(api.calls, [['latest', item.sym]]);
    assert.equal(data.assetType, 'index');
    assert.equal(data.symbol, item.sym);
    assert.equal(data.market, item.market);
    assert.equal(data.currency, item.currency);
    assert.equal(data.exchange, item.exchange);
    assert.equal(data.future_calendar, null);
    assert.equal(data.firstVisibleAt, null);
    if (item.market === 'jp' || item.market === 'kr') assert.notEqual(data.currency, 'CNY');
  }
});

test('global exact history includes only cutoff bars and does not call an A-share Worker', async () => {
  for (const item of assets) {
    const api = adapter(), ctx = context(item.sym, '2026-11-20');
    const result = await Reader.historical(api, ctx);
    assert.deepEqual(api.calls, [['result', item.sym, '2026-11-20']]);
    assert.deepEqual(result.bars.map((bar) => bar.date), ['2026-11-19', '2026-11-20']);
    assert.equal(result.raw.asof, '2026-11-20');
    assert.equal(result.historyFallback, undefined);
    if (item.kind === 'stock') {
      const data = Core.assembleStockData(ctx.code, result.raw, result.market, null);
      assert.equal(data.symbol, 'US_MRVL');
      assert.equal(data.currency, 'USD');
      assert.equal(data.marketAsOf, '2026-11-20');
    }
  }
});

test('missing exact global snapshot cannot fall back to latest, a packed frame or another market', async () => {
  const api = adapter({ result: async () => { throw Error('HTTP 404'); } });
  await assert.rejects(Reader.historical(api, context('KR_KOSPI', '2026-11-20')), (error) => error.pending && /精确封存/.test(error.message));
  assert.deepEqual(api.calls, []);
  const unconnected = adapter({ isAsset: () => false });
  await assert.rejects(Reader.historical(unconnected, context('JP_N225', '2026-11-20')), /国际指数/);
  assert.deepEqual(unconnected.calls, []);
});

test('wrong asset, missing identity and wrong cutoff cannot pass global result validation', async () => {
  const wrongAsset = adapter({ latest: async () => raw('US_NDX'), result: async () => raw('US_NDX', '2026-11-20') });
  await assert.rejects(Reader.currentResult(wrongAsset, context('US_SPX')), /身份/);
  await assert.rejects(Reader.historical(wrongAsset, context('US_SPX', '2026-11-20')), /身份/);
  const noIdentity = adapter({ result: async () => ({ ...raw('US_SPX', '2026-11-20'), symbol: undefined }) });
  await assert.rejects(Reader.historical(noIdentity, context('US_SPX', '2026-11-20')), /身份/);
  const wrongDate = adapter({ result: async () => raw('US_SPX', '2026-11-23') });
  await assert.rejects(Reader.historical(wrongDate, context('US_SPX', '2026-11-20')), /精确封存/);
});

test('later prices and historical directory keep the same global identity and do not mutate cutoff', async () => {
  for (const code of ['US_SPX', 'JP_N225', 'KR_KOSPI', 'US_MRVL']) {
    const api = adapter(), ctx = context(code, '2026-11-20'), before = JSON.stringify(ctx);
    const history = await Terminal.historyFor(api, Reader, ctx);
    const bars = await Terminal.laterBars(api, Reader, Core, ctx);
    assert.equal(history.symbol, code);
    assert.equal(bars[bars.length - 1].date, '2026-11-23');
    assert.equal(JSON.stringify(ctx), before);
    assert.deepEqual(api.calls, [['history', code], ['latest', code]]);
  }
});

test('other US stock failures remain failures instead of using the MRVL global payload', async () => {
  const ctx = Core.parseContext('?code=US_NVDA&kind=stock', indices, assets), api = adapter();
  const reads = [];
  api.stock.latest = async (code) => { reads.push(code); throw Error('NVDA missing'); };
  await assert.rejects(Reader.currentResult(api, ctx), /NVDA missing/);
  assert.deepEqual(reads, ['US_NVDA']);
  assert.deepEqual(api.calls, []);
});

test('stock zero/absent OHLC remains explicit and JP/KR published metadata is not changed to USD', () => {
  for (const code of ['JP_N225', 'KR_KOSDAQ']) {
    const source = raw(code); delete source.price_history.open; source.price_history.volume[0] = 0;
    const market = Reader.marketFromPublished(source, code);
    assert.equal(market.currency, identities.get(code).currency);
    assert.equal(market.price[0].open, null);
    assert.equal(market.price[0].volume, 0);
  }
});

test('new international assets default to complete cycles 1.5; A-share and other US paths retain box', () => {
  for (const item of assets) assert.equal(context(item.sym).rule, 'cycles_1_5');
  assert.equal(Core.parseContext('?code=sh000001&kind=index', indices, assets).rule, 'box');
  assert.equal(Core.parseContext('?code=US_NVDA&kind=stock', indices, assets).rule, 'box');
  assert.equal(Core.parseContext('?code=US_SPX&kind=index&rule=box', indices, assets).rule, 'box');
  const target = new URL(Terminal.href(context('US_SPX', '2026-11-20'), { code: 'JP_N225' }), 'https://example.test/');
  assert.equal(target.searchParams.get('rule'), 'cycles_1_5');
  assert.equal(target.searchParams.get('asof'), '2026-11-20');
});

test('rule switch selects only the saved aggregate and leaves source evidence and prices untouched', () => {
  const source = raw('US_SPX');
  const savedCycles = { lppls_confidence: { evidence: 'research_candidate' },
    scale_windows: [{ scale: '6-12m', q20_date: '2026-12-01', q80_date: '2026-12-08', n: 2 }] };
  source.research = { cycles_1_5: savedCycles };
  const input = { raw: source, top: source.top, bars: Reader.barsFrom(source), modelStatus: 'ok' };
  const before = JSON.stringify(source);
  const cycles = Core.withRule(input, 'cycles_1_5'), box = Core.withRule(cycles, 'box');
  assert.equal(cycles.top, savedCycles);
  assert.equal(cycles.raw, source);
  assert.equal(cycles.bars, input.bars);
  assert.equal(box.top, source.top);
  assert.equal(JSON.stringify(source), before);
  assert.equal(cycles.ruleAvailable, true);
});

test('a missing cycles aggregate is not substituted with box in the chart or historical ledger', () => {
  const source = raw('US_SPX');
  source.top.scale_windows = [{ scale: '6-12m', q20_date: '2026-12-01', q80_date: '2026-12-08', n: 4 }];
  const result = Core.withRule({ raw: source, top: source.top }, 'cycles_1_5');
  assert.deepEqual(result.top, {});
  assert.equal(result.ruleAvailable, false);
  const history = { symbol: 'US_SPX', frames: [{ asof: '2026-11-20', top: source.top }] };
  const packed = Reader.packedFrame(history, history.frames[0], context('US_SPX', '2026-11-20'), [], '标普500');
  assert.equal(Core.withRule({ raw: packed.raw, top: packed.top }, 'cycles_1_5').ruleAvailable, false);
  history.frames[0].research = { cycles_1_5: { scale_windows: [] } };
  const sealed = Reader.packedFrame(history, history.frames[0], context('US_SPX', '2026-11-20'), [], '标普500');
  assert.deepEqual(Core.withRule({ raw: sealed.raw, top: sealed.top }, 'cycles_1_5').top, { scale_windows: [] });
});

test('research note explicitly separates sparse fits, historical samples and calendar verification', () => {
  const source = raw('KR_KOSPI');
  source.schema_version = 'global_terminal_v1';
  source.params = { window_count: 27 };
  source.future_calendar = { note: '工作日外推，未核验本市场节假日。' };
  const note = Core.researchNote({ raw: source });
  assert.match(note, /27 个稀疏窗口/);
  assert.match(note, /非 181 窗/);
  assert.match(note, /尚未进行样本外预警评分/);
  assert.match(note, /未核验本市场节假日/);
});
