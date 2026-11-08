import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { MarketContextState, digest, digestRawJson } from '../src/index.js';

class Storage {
  constructor() { this.map = new Map(); }
  async get(key) { return this.map.get(key); }
  async put(key, value) { this.map.set(key, value); }
  async delete(key) { this.map.delete(key); }
}

class State {
  constructor() { this.storage = new Storage(); this.waits = []; }
  waitUntil(promise) { this.waits.push(promise); }
}

function binding(state, sourceUrl = 'https://source.test/market.json') {
  const workerEnv = { MARKET_CONTEXT_REFRESH_TOKEN: 'secret', MARKET_CONTEXT_SEED_TOKEN: 'seed-secret' };
  if (sourceUrl) workerEnv.MARKET_CONTEXT_SOURCE_URL = sourceUrl;
  return { idFromName: () => 'global', get: () => ({ fetch: (request) => new MarketContextState(state, workerEnv).fetch(request) }) };
}

function env(state, sourceUrl = 'https://source.test/market.json') {
  return { ALLOWED_ORIGIN: 'https://example.test', MARKET_CONTEXT: binding(state, sourceUrl), MARKET_CONTEXT_REFRESH_TOKEN: 'secret', MARKET_CONTEXT_SEED_TOKEN: 'seed-secret' };
}

async function seedSnapshot(asof) {
  const prior = asof === '2026-11-06' ? '2026-11-05' : null;
  const snapshot = {
    schema_version: 'market-context.v1', kind: 'market_context', market: 'CN_A_SHARE', snapshot_kind: 'eod',
    asof, generated_at: `${asof}T15:30:00Z`, requested_at: `${asof}T15:31:00Z`, status: 'partial', stale_reason: null,
    last_good_asof: asof, evidence: 'descriptive', source: { source_id: 'controlled_fixture', status: 'partial' },
    calendar: { calendar_status: 'provided', asof_status: 'exchange_verified', prior_status: prior ? 'exchange_verified' : 'not_available', calendar_source_sha256: 'c'.repeat(64), calendar_version: 'fixture-v1', prior_asof: prior },
    sources: { limit_pools: { source_id: 'eastmoney_yesterday_zt_pool', status: 'fresh', raw_sha256: 'a'.repeat(64) } },
    limit_pools: { zt: 1, top20: { zt: [{ code: '000001', name: '示例', streak: 2 }] }, reasons: { status: 'fresh', rows: [] }, topics: { status: 'fresh', rows: [] } },
    history: { progression: { status: 'not_available', rows: [] } }, board_flow: {}, northbound: {}, margin: {}, valuation: {},
  };
  snapshot.snapshot_sha256 = await digest(snapshot);
  return snapshot;
}

const snapshot = {
  asof: '2026-11-02', generated_at: '2026-11-02T23:47:50Z',
  calendar: { calendar_status: 'provided', asof_status: 'exchange_verified', prior_status: 'not_available', calendar_source_sha256: 'c'.repeat(64), calendar_version: 'fixture-v1', prior_asof: null },
  sources: { limit_pools: { url_host: 'push2ex.eastmoney.com', fetched_at: '2026-11-02T23:46:52Z', ok: true } },
  limit_pools: { zt: 125, top20: { zt: [{ code: '000001', name: '示例', streak: 2 }] } },
  board_flow: {}, northbound: {}, margin: {}, valuation: {},
};

test('refresh is protected, asynchronous and returns a stable snapshot after completion', async () => {
  const state = new State();
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json(snapshot);
  try {
    const forbidden = await worker.fetch(new Request('https://worker.test/context/refresh', { method: 'POST', body: '{}' }), env(state));
    assert.equal(forbidden.status, 403);
    const response = await worker.fetch(new Request('https://worker.test/context/refresh', { method: 'POST', headers: { 'X-Market-Context-Token': 'secret' }, body: '{}' }), env(state));
    assert.equal(response.status, 202);
    const job = await response.json();
    await Promise.all(state.waits);
    const read = await worker.fetch(new Request('https://worker.test/context?date=latest'), env(state));
    const body = await read.json();
    assert.equal(read.status, 200);
    assert.equal(body.schema_version, 'market-context.v1');
    assert.equal(body.limit_pools.reasons.status, 'not_available');
    assert.equal(body.history.progression.status, 'not_available');
    assert.equal(body.cache, 'hit');
    const status = await worker.fetch(new Request(`https://worker.test/context/status?job_id=${job.job_id}`), env(state));
    assert.equal((await status.json()).status, 'completed');
  } finally { globalThis.fetch = original; }
});

test('refresh fails closed when the source URL is not configured', async () => {
  const state = new State();
  let networkCalls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => { networkCalls += 1; return Response.json(snapshot); };
  try {
    const response = await worker.fetch(new Request('https://worker.test/context/refresh', {
      method: 'POST', headers: { 'X-Market-Context-Token': 'secret' }, body: '{}',
    }), env(state, null));
    assert.equal(response.status, 202);
    const job = await response.json();
    await Promise.all(state.waits);
    assert.equal(networkCalls, 0);
    const latest = await worker.fetch(new Request('https://worker.test/context?date=latest'), env(state, null));
    assert.equal(latest.status, 404);
    const dated = await worker.fetch(new Request('https://worker.test/context?date=2026-11-02'), env(state, null));
    assert.equal(dated.status, 404);
    const status = await worker.fetch(new Request(`https://worker.test/context/status?job_id=${job.job_id}`), env(state, null));
    const statusBody = await status.json();
    assert.equal(statusBody.status, 'failed');
    assert.equal(statusBody.error_code, 'CONTEXT_REFRESH_FAILED');
  } finally { globalThis.fetch = original; }
});

test('historical reads never fall back to latest and requested dates are validated', async () => {
  const state = new State();
  const e = env(state);
  const missing = await worker.fetch(new Request('https://worker.test/context/snapshot?date=2026-11-03'), e);
  assert.equal(missing.status, 404);
  const weekend = await worker.fetch(new Request('https://worker.test/context/snapshot?date=2026-11-01'), e);
  assert.equal(weekend.status, 400);
});

test('controlled seed imports dated snapshots and never overwrites a sealed date', async () => {
  const state = new State();
  const e = env(state);
  const snapshot = await seedSnapshot('2026-11-05');
  const forbidden = await worker.fetch(new Request('https://worker.test/context/seed', { method: 'POST', body: JSON.stringify(snapshot) }), e);
  assert.equal(forbidden.status, 403);
  const seeded = await worker.fetch(new Request('https://worker.test/context/seed', {
    method: 'POST', headers: { 'X-Market-Context-Seed-Token': 'seed-secret' }, body: JSON.stringify({ snapshot }),
  }), e);
  assert.equal(seeded.status, 201);
  assert.equal((await seeded.json()).latest_updated, true);
  const read = await worker.fetch(new Request('https://worker.test/context?date=2026-11-05'), e);
  assert.equal((await read.json()).snapshot_sha256, snapshot.snapshot_sha256);
  const duplicate = await worker.fetch(new Request('https://worker.test/context/seed', {
    method: 'POST', headers: { 'X-Market-Context-Seed-Token': 'seed-secret' }, body: JSON.stringify(snapshot),
  }), e);
  assert.equal(duplicate.status, 409);
  assert.equal((await duplicate.json()).error_code, 'SNAPSHOT_EXISTS');
});

test('controlled seed rejects snapshots without an exchange-verified calendar', async () => {
  const state = new State();
  const e = env(state);
  const snapshot = await seedSnapshot('2026-11-05');
  delete snapshot.calendar;
  snapshot.snapshot_sha256 = await digest(snapshot);
  const response = await worker.fetch(new Request('https://worker.test/context/seed', {
    method: 'POST', headers: { 'X-Market-Context-Seed-Token': 'seed-secret' }, body: JSON.stringify(snapshot),
  }), e);
  assert.equal(response.status, 422);
  assert.equal((await response.json()).error_code, 'CALENDAR_UNVERIFIED');
});

test('controlled seed rejects a missing or incorrect snapshot hash and keeps latest monotonic', async () => {
  const state = new State();
  const e = env(state);
  const valid = await seedSnapshot('2026-11-06');
  const bad = { ...valid, snapshot_sha256: 'b'.repeat(64) };
  const mismatch = await worker.fetch(new Request('https://worker.test/context/seed', {
    method: 'POST', headers: { 'X-Market-Context-Seed-Token': 'seed-secret' }, body: JSON.stringify(bad),
  }), e);
  assert.equal(mismatch.status, 422);
  assert.equal((await mismatch.json()).error_code, 'SNAPSHOT_HASH_MISMATCH');
  const first = await worker.fetch(new Request('https://worker.test/context/seed', {
    method: 'POST', headers: { 'X-Market-Context-Seed-Token': 'seed-secret' }, body: JSON.stringify(valid),
  }), e);
  assert.equal(first.status, 201);
  const older = await seedSnapshot('2026-11-05');
  const second = await worker.fetch(new Request('https://worker.test/context/seed', {
    method: 'POST', headers: { 'X-Market-Context-Seed-Token': 'seed-secret' }, body: JSON.stringify(older),
  }), e);
  assert.equal(second.status, 201);
  assert.equal((await second.json()).latest_updated, false);
  const latest = await worker.fetch(new Request('https://worker.test/context?date=latest'), e);
  assert.equal((await latest.json()).asof, '2026-11-06');
});

test('refresh never overwrites an already sealed dated snapshot', async () => {
  const state = new State();
  const e = env(state);
  const sealed = await seedSnapshot('2026-11-05');
  const seedResponse = await worker.fetch(new Request('https://worker.test/context/seed', {
    method: 'POST', headers: { 'X-Market-Context-Seed-Token': 'seed-secret' }, body: JSON.stringify(sealed),
  }), e);
  assert.equal(seedResponse.status, 201);
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ ...snapshot, asof: '2026-11-05', generated_at: '2026-11-05T23:00:00Z' });
  try {
    const response = await worker.fetch(new Request('https://worker.test/context/refresh', {
      method: 'POST', headers: { 'X-Market-Context-Token': 'secret' }, body: JSON.stringify({ date: '2026-11-05' }),
    }), e);
    assert.equal(response.status, 202);
    await Promise.all(state.waits);
  } finally { globalThis.fetch = original; }
  const read = await worker.fetch(new Request('https://worker.test/context?date=2026-11-05'), e);
  assert.equal((await read.json()).snapshot_sha256, sealed.snapshot_sha256);
});

test('raw seed hashing preserves Python decimal lexical values', async () => {
  assert.equal(await digestRawJson('{"a":1.0,"b":2}'), '3a5fc11441293773f44e7207ddf4783fdcfc50b78e63e3e484cfcbfe61a8508c');
});

test('a failed refresh keeps the last snapshot and marks it stale', async () => {
  const state = new State();
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    if (calls === 1) return Response.json(snapshot);
    return new Response('upstream failed', { status: 502 });
  };
  try {
    const start = (headers = {}) => worker.fetch(new Request('https://worker.test/context/refresh', { method: 'POST', headers: { 'X-Market-Context-Token': 'secret', ...headers }, body: '{}' }), env(state));
    await start(); await Promise.all(state.waits.splice(0));
    await start(); await Promise.all(state.waits.splice(0));
    const read = await worker.fetch(new Request('https://worker.test/context?date=latest'), env(state));
    const body = await read.json();
    assert.equal(body.status, 'stale');
    assert.equal(body.last_good_asof, '2026-11-02');
    assert.equal(body.stale_reason, 'CONTEXT_REFRESH_FAILED');
    const dated = await worker.fetch(new Request('https://worker.test/context?date=2026-11-02'), env(state));
    assert.equal((await dated.json()).status, 'fresh');
  } finally { globalThis.fetch = original; }
});
