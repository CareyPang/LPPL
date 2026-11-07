import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { MarketContextState } from '../src/index.js';

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

function binding(state) {
  return { idFromName: () => 'global', get: () => ({ fetch: (request) => new MarketContextState(state, { MARKET_CONTEXT_SOURCE_URL: 'https://source.test/market.json', MARKET_CONTEXT_REFRESH_TOKEN: 'secret' }).fetch(request) }) };
}

function env(state) {
  return { ALLOWED_ORIGIN: 'https://example.test', MARKET_CONTEXT: binding(state), MARKET_CONTEXT_REFRESH_TOKEN: 'secret' };
}

const snapshot = {
  asof: '2026-11-02', generated_at: '2026-11-02T23:47:50Z',
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

test('historical reads never fall back to latest and requested dates are validated', async () => {
  const state = new State();
  const e = env(state);
  const missing = await worker.fetch(new Request('https://worker.test/context/snapshot?date=2026-11-03'), e);
  assert.equal(missing.status, 404);
  const weekend = await worker.fetch(new Request('https://worker.test/context/snapshot?date=2026-11-01'), e);
  assert.equal(weekend.status, 400);
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
  } finally { globalThis.fetch = original; }
});
