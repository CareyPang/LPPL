'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Core = require('../app/chart-page-core.js');
const Reader = require('../app/chart-readonly-data.js');
const Share = require('../app/chart-research-card.js');
const Chart = require('../app/lppl-chart.js');
const indices = [{ sym: 'sh000001', code: '000001', name: '上证指数' }];
const context = Core.parseContext('?code=sh000001&asof=2026-06-26', indices);
const raw = { symbol: 'sh000001', asof: '2026-06-26', name: '上证指数',
  price_history: { dates: ['2026-06-25', '2026-06-26', '2026-06-29'], close: [10, 11, 12] }, top: {} };

test('invalid dates are rejected, and explicit stock kind disambiguates 000001', () => {
  for (const date of ['2026-02-29', 'yesterday', '2026-13-01']) {
    const value = Core.parseContext('?code=sh000001&asof=' + date, indices);
    assert.equal(value.valid, false); assert.match(value.invalidReason, /未改看最新/);
  }
  assert.equal(Core.parseContext('?code=000001&kind=stock', indices).assetType, 'stock');
  assert.equal(Core.safeFrom('research-workspace', 'index', 'sh000001'), 'research-workspace.html');
  const from = 'research-workspace.html?asof=2026-06-26&focus=interval%3A1';
  assert.equal(Core.safeFrom(from, 'index', 'sh000001'), from);
});
test('history reads an exact archived result, trims later bars and never starts a job', async () => {
  const calls = [];
  const adapter = { replay: { result: async (code, asof) => { calls.push([code, asof]); return { status: 'ready', result: raw }; },
    request: () => { throw new Error('POST forbidden'); } }, load: () => { throw new Error('latest forbidden'); } };
  const result = await Reader.historical(adapter, context);
  assert.deepEqual(result.bars.map(x => x.date), ['2026-06-25', '2026-06-26']);
  assert.deepEqual(calls, [['sh000001', '2026-06-26']]);
  assert.equal(result.bars[0].open, null);
  assert.equal(Chart.priceMode(result.bars), 'close');
  assert.deepEqual(Chart.toCandles(result.bars), []);
});
test('wrong cutoff or symbol cannot pass as an archived match', () => {
  assert.throws(() => Reader.exactResult({ ...raw, asof: '2026-06-25' }, context), /精确封存/);
  assert.throws(() => Reader.exactResult({ ...raw, symbol: 'sh000300' }, context), /身份不匹配/);
});
test('missing historical date never loads latest or posts, even when nearby frames exist', async () => {
  const adapter = { replay: { result: async () => ({ status: 'missing' }), request: () => assert.fail('POST') },
    history: async () => ({ symbol: 'sh000001', frames: [{ asof: '2026-06-25' }] }),
    load: () => assert.fail('latest model must not substitute') };
  await assert.rejects(Reader.historical(adapter, context), /只读访问未发起计算/);
});
test('exact history fallback uses only the stored frame and flags revised market history', async () => {
  const frame = { asof: '2026-06-26', w: { '6-12m': ['2026-07-01', '2026-07-10'] }, clusters: {} };
  const adapter = { replay: { result: async () => ({ status: 'missing' }) },
    history: async () => ({ symbol: 'sh000001', frames: [frame], evidence: 'test' }),
    load: async (...args) => { assert.deepEqual(args, ['sh000001']); return { name: '上证指数', bars: [{ date: '2026-06-26', close: 10 }, { date: '2026-06-29', close: 12 }], top: { forbidden: true } }; } };
  const result = await Reader.historical(adapter, context);
  assert.equal(result.historyFallback, true); assert.equal(result.top.forbidden, undefined);
  assert.equal(result.bars.length, 1); assert.equal(result.raw.first_visible_at, null);
});
test('historical events require a known publication date and retain future scheduled events known then', () => {
  const payload = { lift: [
    { code: '600519', free_date: '2026-07-15', published_at: '2026-06-25' },
    { code: '600519', free_date: '2026-06-15' },
    { code: '600519', free_date: '2026-07-15', published_at: '2026-06-27' }
  ] };
  const result = Reader.eventsFor(payload, '600519', '2026-06-26');
  assert.equal(result.rows.length, 1); assert.equal(result.excluded, 2);
  assert.equal(result.rows[0].date, '2026-07-15');
});
test('unknown, rule and failure evidence is fail-closed; descriptive needs positive n', () => {
  for (const code of ['none', 'rule', 'fail_future', 'dev_only', 'madeup', undefined]) {
    assert.equal(Core.bandEvidencePolicy(code, { n: 100 }).draw, false);
  }
  for (const n of [null, 0, -1, NaN]) assert.equal(Core.bandEvidencePolicy('descriptive', { n }).draw, false);
  assert.equal(Core.bandEvidencePolicy('descriptive', { n: 3 }).draw, true);
});
test('metadata reports unknown units and model adjustment instead of inferring from note', () => {
  const data = Core.assembleStockData('600519', { symbol: 'sh600519', price_history: { note: 'daily' } },
    { price: [{ date: '2026-06-26', close: 10 }] });
  assert.equal(data.modelAdjustment, '未记录'); assert.equal(data.volumeUnit, '未记录');
  assert.equal(data.quoteUnit, 'CNY · 元'); assert.equal(data.tradingStatus, '未记录');
});
test('a mismatched model cannot relabel market bars and a mismatched quote is rejected', () => {
  const market = { symbol: 'sh600519', price: [{ date: '2026-06-26', close: 10 }] };
  const data = Core.assembleStockData('600519', { symbol: 'sh600520', top: { forbidden: true } }, market);
  assert.equal(data.symbol, 'sh600519'); assert.equal(data.modelStatus, 'error');
  assert.deepEqual(data.top, {});
  assert.throws(() => Core.assembleStockData('600520', null, market), /行情资产身份/);
});
test('anonymous card allowlist excludes private data, escapes SVG and hides forbidden intervals', () => {
  const data = { symbol: 'sh600519', name: '<script>bad</script>', assetType: 'stock', source: 'source',
    note: 'PRIVATE_NOTE', positions: 'PRIVATE_POSITION', account: 'PRIVATE_ACCOUNT' };
  const bands = [{ q20_date: '2026-07-01', q80_date: '2026-07-10', n: 3 }];
  const item = Share.record(data, { scale: '6-12m', from: 'PRIVATE_URL' }, { code: 'none', show: false }, bands, Core.bandEvidencePolicy);
  assert.equal(item.intervals.length, 0);
  assert.doesNotMatch(JSON.stringify(item), /PRIVATE_/);
  assert.doesNotMatch(Share.svg(item), /<script>/);
  assert.match(Share.svg(item), /&lt;script&gt;/);
  const descriptive = Share.record(data, { scale: '6-12m', asof: '2026-06-26' },
    { code: 'descriptive', show: true }, bands, Core.bandEvidencePolicy);
  assert.equal(descriptive.intervals[0].n, 3); assert.match(descriptive.note, /不是预测/);
  assert.match(descriptive.mode, /不等同于提前发布/);
});
test('long source and ID fields are complete and wrap inside SVG and PNG content width', () => {
  const source = '来源甲'.repeat(150), id = 'prediction-'.repeat(80), version = '模型版本'.repeat(100);
  const item = Share.record({ dataSource: source, predictionId: id, modelVersion: version },
    { scale: '6-12m' }, { code: 'none', show: false }, [], Core.bandEvidencePolicy);
  const lines = Share.lines(item);
  assert.equal(item.source, source); assert.equal(item.predictionId, id); assert.equal(item.modelVersion, version);
  assert.ok(lines.every(line => Array.from(line).length <= 66));
  assert.ok(lines.join('').includes(source)); assert.ok(lines.join('').includes(id));
  assert.ok(lines.join('').includes(version));
  const svg = Share.svg(item);
  assert.ok(svg.includes('height="' + (130 + lines.length * 38) + '"'));
  assert.equal((svg.match(/<text /g) || []).length, lines.length + 1);
});
test('raw close-only history cannot become synthetic OHLC via a legacy adapter', () => {
  const result = { raw, asof: raw.asof, bars: [{ date: '2026-06-26', open: 11, high: 11, low: 11, close: 11 }] };
  const data = Core.assembleIndexData('sh000001', result);
  assert.equal(data.bars[0].open, null); assert.equal(Chart.priceMode(data.bars), 'close');
  assert.equal(Chart.toCloses(data.bars).length, 2);
});
test('independent module timeout rejects without cancelling other completed work', async () => {
  const market = Reader.timed(async () => 'market-ready', '行情', 100);
  const model = Reader.timed(() => new Promise(() => {}), '模型', 10);
  assert.equal(await market, 'market-ready');
  await assert.rejects(model, /模型读取超时/);
});
