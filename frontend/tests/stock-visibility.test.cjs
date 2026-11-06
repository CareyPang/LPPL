'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const { create, candidates } = require('../app/stock-visibility.js');

const NOW = Date.parse('2026-11-06T08:00:00Z');
const source = 'a'.repeat(40);
function result(extra = {}) {
  return { symbol: 'sh600519', asof: '2026-11-05', job_id: '11111111-1111-4111-8111-111111111111',
    mode: 'current', source_sha: source, model_version: 'fixture-only', generated_at: '2026-11-06T07:50:00Z',
    top: { window: { start: '2026-11-16', end: '2026-11-20', evidence: 'test' } }, ...extra };
}
function storage() {
  const values = new Map();
  return { values, get length() { return values.size; }, key: index => [...values.keys()][index],
    getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value) };
}
const delivery = { source: 'remote_cache', received_at_client: '2026-11-06T07:59:00Z' };

test('demo, hidden evidence, historical, malformed and nonfuture windows cannot enter the live observation ledger', () => {
  assert.equal(candidates(result()).length, 1);
  for (const value of [result({ demo: true }), result({ mode: 'history' }), result({ evidence: 'dev_only' }),
    result({ claim_origin: 'HYPOTHETICAL_REPLAY_CLAIM_NOT_ORIGINAL' }), result({ symbol: '000001' }),
    ...['none', 'fail', 'fail_cal', 'dev_only', 'dev_failed', ''].map(evidence => result({ top: {
      window: { start: '2026-11-16', end: '2026-11-20', evidence } } })),
    result({ top: { evidence_override: 'dev_only', window: { start: '2026-11-16', end: '2026-11-20', evidence: 'test' } } }),
    result({ top: { window: { start: '2026-11-05', end: '2026-11-20', evidence: 'test' } } }),
    result({ top: { window: { start: '2026-11-31', end: '2026-12-01', evidence: 'test' } } }),
    result({ top: { window: { start: '2026-11-20', end: '2026-11-16', evidence: 'test' } } }),
  ]) assert.deepEqual(candidates(value), []);
});

test('cached first viewing preserves the original identity and is idempotent through rerender, refresh and history changes', async () => {
  const store = storage(), events = [], visible = [];
  const record = result(), window = candidates(record)[0];
  const ledger = create({ storage: store, now: () => NOW, crypto: webcrypto,
    onRecord: value => events.push(value), onVisible: value => visible.push(value) });
  const first = await ledger.recordVisible(record, window, delivery, () => true);
  assert.equal(first.is_cached, true);
  assert.equal(first.identity.generated_at, record.generated_at);
  assert.equal(first.public_first_published_at, null);
  assert.equal(first.original_prediction_identity, 'NOT_ESTABLISHED');
  assert.equal(first.first_visible_at_client, '2026-11-06T08:00:00.000Z');
  await ledger.recordVisible({ ...record }, window, { source: 'job_result' }, () => true);
  assert.equal(events.length, 1);
  assert.equal(visible.length, 2, 'a previously saved observation still refreshes the current card');
  const refresh = create({ storage: store, now: () => NOW + 60000, crypto: webcrypto });
  const seen = await refresh.recordVisible(record, window, { source: 'job_result' }, () => true);
  assert.equal(seen.first_visible_at_client, first.first_visible_at_client);
  assert.equal(seen.acquisition, 'remote_cache', 'late delivery metadata never rewrites the first viewing');
  assert.equal(refresh.records().length, 1);
  const revision = result({ job_id: '22222222-2222-4222-8222-222222222222' });
  await refresh.recordVisible(revision, candidates(revision)[0], { source: 'job_result' }, () => true);
  assert.equal(refresh.records().length, 2, 'distinct immutable results retain their own observations');
  const late = create({ storage: storage(), now: () => Date.parse('2026-12-01T08:00:00Z'), crypto: webcrypto });
  const oldWindow = await late.recordVisible(record, window, delivery, () => true);
  assert.equal(oldWindow.date_relation_at_client_observation, 'PAST_WINDOW', 'old cached windows are not fresh future alerts');
});

test('visibility is checked again after hashing and no timestamp is inferred from rendering alone', async () => {
  let resolveHash, visible = true;
  const ledger = create({ storage: storage(), now: () => NOW,
    crypto: { subtle: { digest: () => new Promise(resolve => { resolveHash = resolve; }) } } });
  const value = result(), window = candidates(value)[0];
  assert.equal(await ledger.recordVisible(value, window, delivery), null);
  const pending = ledger.recordVisible(value, window, delivery, () => visible);
  await Promise.resolve(); await Promise.resolve();
  visible = false; resolveHash(new Uint8Array(32).buffer);
  assert.equal(await pending, null);
  assert.equal(ledger.records().length, 0);
});

test('server first-observed clock remains separate and must match the displayed result identity', async () => {
  const record = result({ delivery_observation: { schema: 'result_observation_v1', job_id: result().job_id,
    source_sha: source, mode: 'current', first_observed_at: '2026-11-06T07:58:00Z', result_sha256: 'b'.repeat(64) } });
  const ledger = create({ storage: storage(), now: () => NOW, crypto: webcrypto });
  const seen = await ledger.recordVisible(record, candidates(record)[0], { source: 'job_result' }, () => true);
  assert.equal(seen.server_first_observed_at, '2026-11-06T07:58:00Z');
  assert.equal(seen.public_first_published_at, null);
  const wrong = result({ ...record, job_id: 'other-job' });
  const other = await ledger.recordVisible(wrong, candidates(wrong)[0], delivery, () => true);
  assert.equal(other.server_first_observed_at, null);
});

test('storage failure is memory-only and damaged prior observations are not overwritten', async () => {
  const fail = { getItem: () => null, setItem() { throw Error('quota'); } };
  const ledger = create({ storage: fail, now: () => NOW, crypto: webcrypto });
  const record = result(), window = candidates(record)[0];
  assert.equal((await ledger.recordVisible(record, window, delivery, () => true)).storage_status, 'MEMORY_ONLY');
  const damaged = create({ storage: { getItem: () => '{', setItem() { assert.fail('Do not replace'); } }, crypto: webcrypto });
  assert.equal(await damaged.recordVisible(record, window, delivery, () => true), null);
});

test('DOM observer excludes hidden tabs, offscreen windows, opaque overlays and stale selections until actually visible', async () => {
  const store = storage(), frames = [], events = [], handlers = {};
  let rect = { left: 10, right: 200, top: 900, bottom: 940, width: 190, height: 40 }, covered = false;
  const node = { isConnected: true, closest: () => false, parentElement: null,
    getBoundingClientRect: () => rect, contains: () => false };
  const doc = { visibilityState: 'visible', addEventListener(name, fn) { handlers[name] = fn; },
    removeEventListener() {}, elementFromPoint: () => covered ? {} : node };
  const root = { document: doc, crypto: webcrypto, innerHeight: 800, innerWidth: 1280,
    getComputedStyle: () => ({ display: 'block', visibility: 'visible', opacity: '1' }),
    requestAnimationFrame: callback => frames.push(callback), addEventListener(name, fn) { handlers[name] = fn; }, removeEventListener() {} };
  vm.runInNewContext(fs.readFileSync(require.resolve('../app/stock-visibility.js'), 'utf8'),
    { window: root, TextEncoder, Date, Uint8Array });
  const view = root.StockVisibility.mount({ document: doc, container: { querySelector: () => node },
    storage: store, now: () => NOW, crypto: webcrypto, onRecord: record => events.push(record) });
  const flush = async () => { while (frames.length) frames.shift()(); await new Promise(resolve => setTimeout(resolve, 10)); };
  view.set(result(), delivery); await flush(); assert.equal(events.length, 0);
  rect = { ...rect, top: 100, bottom: 140 };
  doc.visibilityState = 'hidden'; handlers.visibilitychange(); await flush(); assert.equal(events.length, 0);
  doc.visibilityState = 'visible'; covered = true; handlers.visibilitychange(); await flush(); assert.equal(events.length, 0);
  covered = false; rect.left = -5; handlers.scroll(); await flush(); assert.equal(events.length, 0);
  rect.left = 10;
  covered = false; handlers.scroll(); await flush(); assert.equal(events.length, 1);
  view.set(result({ symbol: 'sz000001' }), delivery); view.set(null, null); await flush(); assert.equal(events.length, 1);
  view.destroy(); handlers.scroll(); await flush(); assert.equal(events.length, 1);
});
