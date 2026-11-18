'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Core = require('../app/research-personal-core.js');
const NOW = '2026-11-18T08:00:00Z';
const sampleHolding = () => ({ code: '600519', name: '贵州茅台', currency: 'CNY', shares: 100, cost: 1500, updatedAt: NOW });
function storage() { const map = new Map(); return { getItem: key => map.has(key) ? map.get(key) : null, setItem: (key, v) => map.set(key, v) }; }
function observation(extra = {}) { return { id: 'local-1', asset: { id: 'stock:600519', name: '贵州茅台' }, asof: '2026-11-17', observedAt: NOW, status: 'window', evidence: 'descriptive', modelVersion: 'v1', dataVersion: 'data-v1', coverage: [{ scale: 'mid', status: 'computed', computed: true, evidence: 'descriptive' }], windows: [{ scale: 'mid', start: '2026-11-20', end: '2026-11-26', evidence: 'descriptive' }], ...extra }; }
function payload() { return { asof: '2026-11-17', generated: NOW, sources: { lift: { ok: true, provider: 'official-source', stale: false }, dividend: { ok: false, stale: true, stale_reason: 'provider timeout' }, forecast: { ok: true } }, window: { lift: ['2026-11-17', '2026-12-17'] }, lift: [{ code: '600519', name: '贵州茅台', free_date: '2026-11-25', free_shares_type: '限售股份', first_seen_at: '2026-11-16T01:00:00Z' }], dividend: [{ code: '600519', ex_dividend_date: '2026-11-17', plan_text: '10派2元' }], forecast: [{ code: '000001', name: '股票，不是指数', notice_date: '2026-11-16', predict_type: '预增', first_seen_at: '2026-11-18T01:00:00Z' }] }; }
test('holdings persist with revision check; stale tab cannot overwrite', () => {
  const s = storage(), a = Core.load(s), b = Core.load(s); a.holdings.push(sampleHolding());
  assert.equal(Core.save(s, a), true); assert.equal(Core.save(s, b), false);
  assert.deepEqual(Core.load(s).holdings, [sampleHolding()]); assert.equal(a.revision, 1);
});
test('storage failure does not return success or increment revision', () => {
  const s = { getItem: () => null, setItem: () => { throw Error('quota'); } }, state = Core.initial();
  assert.equal(Core.save(s, state), false); assert.equal(state.revision, 0);
  assert.equal(Core.load(null).storageIssue, 'read_failed');
  assert.equal(Core.load({ getItem: () => '{broken' }).storageIssue, 'read_failed');
  assert.equal(Core.load({ getItem: () => '{"version":8}' }).storageIssue, 'unsupported_version');
});
test('holding validation distinguishes blank, null and zero and rejects impossible numbers', () => {
  assert.equal(Core.holding({ ...sampleHolding(), cost: 0 }).cost, 0);
  for (const cost of ['', ' ', null, false, -1, Infinity, 'NaN']) assert.equal(Core.holding({ ...sampleHolding(), cost }), null);
  for (const shares of [0, -2, null, true, 'bad', 1e20]) assert.equal(Core.holding({ ...sampleHolding(), shares }), null);
  assert.equal(Core.holding({ ...sampleHolding(), currency: 'USD' }), null);
  assert.equal(Core.holding({ ...sampleHolding(), code: 'sh600519' }), null);
});
test('normalization deduplicates read ids and holdings and bounds state', () => {
  const state = Core.normalize({ version: 1, readChanges: ['x', 'x', null], holdings: [sampleHolding(), { ...sampleHolding(), shares: 200 }, {}] });
  assert.deepEqual(state.readChanges, ['x']); assert.equal(state.holdings.length, 1); assert.equal(state.holdings[0].shares, 200);
});
test('first observation and metadata-only updates do not become prediction notifications', () => {
  const first = observation(), refreshed = observation({ id: 'local-2', asof: '2026-11-18', dataVersion: 'data-v2', modelVersion: 'v2', source: 'different', stale: true, predictionId: 'new-id' });
  assert.equal(Core.changes({ 'stock:600519': [first] }).length, 0);
  assert.equal(Core.changes({ 'stock:600519': [first, refreshed] }).length, 0);
});
test('substantive changes retain asset identity, observation time and changed basis', () => {
  const first = observation(), changed = observation({ id: 'local-2', modelVersion: 'v2', windows: [], status: 'no_cluster' });
  const rows = Core.changes({ 'stock:600519': [first, changed] });
  assert.equal(rows.length, 1); assert.equal(rows[0].assetId, 'stock:600519'); assert.equal(rows[0].basisChanged, true);
  assert.deepEqual(rows[0].reasons, ['观察区间变化', '结果状态变化']); assert.equal(rows[0].observedAt, NOW);
});
test('event adapter uses real lift/dividend/forecast fields and source states', () => {
  const data = Core.eventData(payload()); assert.equal(data.rows.length, 3); assert.equal(data.asof, '2026-11-17');
  const lift = data.rows.find(x => x.type === 'lift'), dividend = data.rows.find(x => x.type === 'dividend');
  assert.equal(lift.date, '2026-11-25'); assert.equal(lift.status, '快照记为预定，发生情况待核实'); assert.equal(lift.publishedAt, null);
  assert.equal(dividend.status, '已到日程，执行待核实'); assert.equal(dividend.source.stale, true); assert.equal(dividend.source.status, 'failed');
});
test('calendar filters only watched stocks without mixing index 000001 identity', () => {
  const data = Core.eventData(payload());
  assert.equal(Core.filterEvents(data, { codes: ['600519'], month: '2026-11' }).length, 2);
  assert.equal(Core.filterEvents(data, { codes: ['sh000001'], month: '2026-11' }).length, 0);
  assert.equal(Core.filterEvents(data, { codes: ['600519'], day: '2026-11-25' }).length, 1);
  assert.equal(Core.filterEvents(data, { codes: ['600519'], month: '2026-12' }).length, 0);
});
test('current snapshots never masquerade as point-in-time history', () => {
  const data = Core.eventData(payload()), forecast = data.rows.find(r => r.type === 'forecast'), lift = data.rows.find(r => r.type === 'lift');
  assert.match(Core.knowledgeAt(forecast, '2026-11-16'), /之后才采集/);
  assert.match(Core.knowledgeAt(lift, '2026-11-25'), /发布日期未知/);
  assert.match(Core.knowledgeAt({ ...forecast, firstSeen: null }, '2026-11-18'), /当时网站可见未核实/);
});
test('malformed events, impossible dates and missing payload do not create factual records', () => {
  assert.equal(Core.eventData(null), null); assert.equal(Core.eventData({ asof: '2026-11-17' }), null);
  const p = payload(); p.lift.push({ code: '600519', free_date: '2026-02-30' }); p.forecast.push({ code: '<script>', notice_date: '2026-11-15' });
  assert.equal(Core.eventData(p).rows.length, 3); assert.equal(Core.date('2026-02-29'), null); assert.equal(Core.date('2024-02-29'), '2024-02-29');
});
test('amount display preserves zero versus missing and only converts display units', () => {
  assert.equal(Core.amount(null, 'yuan'), '—'); assert.equal(Core.amount(0, 'yuan'), '0.00 元');
  assert.equal(Core.amount(10000, 'wan'), '1.00 万元'); assert.equal(Core.amount(1e8, 'yi'), '1.00 亿元');
});
