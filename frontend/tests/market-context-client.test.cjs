const test = require('node:test');
const assert = require('node:assert/strict');
const { createMarketContextClient, validDate, validateSnapshot } = require('../app/market-context-client.js');

test('market-context client accepts latest and ISO dates only', () => {
  assert.equal(validDate('latest'), true);
  assert.equal(validDate('2026-11-06'), true);
  assert.equal(validDate('2026-11-07'), true);
  assert.equal(validDate('2026-2-6'), false);
  assert.equal(validDate('2026-11-06T00:00:00Z'), false);
});

test('disabled client never performs a network request', async () => {
  let calls = 0;
  const client = createMarketContextClient({ enabled: false, fetchImpl: async () => { calls += 1; } });
  assert.deepEqual(await client.get('latest'), { status: 'disabled', date: 'latest', snapshot: null });
  assert.equal(calls, 0);
});

test('historical request does not fall back to latest and preserves error code', async () => {
  const calls = [];
  const client = createMarketContextClient({
    enabled: true, baseUrl: 'https://context.example', fetchImpl: async (url) => {
      calls.push(url);
      return new Response(JSON.stringify({ error_code: 'CONTEXT_NOT_READY', error: '该日期尚无已封存市场背景快照', date: '2026-11-05' }), { status: 404 });
    },
  });
  await assert.rejects(() => client.get('2026-11-05'), (error) => error.code === 'CONTEXT_NOT_READY' && error.date === '2026-11-05');
  assert.deepEqual(calls, ['https://context.example/context?date=2026-11-05']);
});

test('ready snapshot must match the requested historical date', async () => {
  assert.throws(() => validateSnapshot({ asof: '2026-11-06', schema_version: 'market-context.v1' }, '2026-11-05'), (error) => error.code === 'DATE_MISMATCH');
  const snapshot = validateSnapshot({ asof: '2026-11-05', schema_version: 'market-context.v1', status: 'partial', sources: {}, snapshot_sha256: 'a'.repeat(64) }, '2026-11-05');
  assert.equal(snapshot.asof, '2026-11-05');
});

test('stale snapshot preserves last-good date, reason and fetched time', async () => {
  const states = [];
  const client = createMarketContextClient({
    enabled: true, baseUrl: 'https://context.example', onState: state => states.push(state),
    fetchImpl: async () => new Response(JSON.stringify({
      schema_version: 'market-context.v1', asof: '2026-11-06', status: 'stale',
      stale_reason: 'source_unavailable', last_good_asof: '2026-11-05',
      source: { source_id: 'p1', status: 'stale', stale_reason: 'source_unavailable', fetched_at: '2026-11-06T08:00:00Z' },
    }), { status: 200 }),
  });
  const state = await client.get('latest');
  assert.equal(state.status, 'stale');
  assert.equal(state.lastGoodAsOf, '2026-11-05');
  assert.equal(state.staleReason, 'source_unavailable');
  assert.equal(state.fetchedAt, '2026-11-06T08:00:00Z');
  assert.equal(states.at(-1).snapshot.asof, '2026-11-06');
});
