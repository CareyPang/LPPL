import assert from 'node:assert/strict';
import { test } from 'node:test';
import worker, { StockQueryState, QueryBudget, normalizeMarket, closedCutoff, fetchJSON } from '../src/index.js';

const ORIGIN = 'https://careypang.github.io';
const SHA = 'a'.repeat(40);
const OTHER_SHA = 'b'.repeat(40);
const TOKEN = 'fixture-secret-never-expose';

class MemoryStorage {
  values = new Map();
  async get(key) { return structuredClone(this.values.get(key)); }
  async put(key, value) {
    if (typeof key === 'object') {
      for (const [k, v] of Object.entries(key)) this.values.set(k, structuredClone(v));
    } else this.values.set(key, structuredClone(value));
  }
}

class Namespace {
  objects = new Map();
  storage = new Map();
  constructor(Type, env) { this.Type = Type; this.env = env; }
  idFromName(name) { return name; }
  get(name) {
    if (!this.storage.has(name)) this.storage.set(name, new MemoryStorage());
    if (!this.objects.has(name)) this.objects.set(name, new this.Type({ storage: this.storage.get(name) }, this.env));
    return this.objects.get(name);
  }
  evict(name) { this.objects.delete(name); }
}

function environment(extra = {}) {
  const env = { GH_TOKEN: TOKEN, ...extra };
  env.STOCK_JOBS = new Namespace(StockQueryState, env);
  env.QUERY_BUDGET = new Namespace(QueryBudget, env);
  return env;
}

function request(path, { method = 'GET', origin = ORIGIN, body, ip = '203.0.113.1' } = {}) {
  const headers = { 'CF-Connecting-IP': ip };
  if (origin !== null) headers.Origin = origin;
  return new Request(`https://worker.test${path}`, { method, headers,
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body) });
}

function query(env, body = { code: '600519' }, ip) {
  return worker.fetch(request('/query', { method: 'POST', body, ip }), env);
}

function marketFixture(symbol = 'sh600519') {
  return { data: { [symbol]: { qt: { [symbol]: ['1', '示例股份'] }, day: [
    ['2026-11-04', '10', '11', '12', '9', '100'],
    ['2026-11-05', '11', '12', '13', '10', '200'],
    ['2026-11-06', '12', '13', '14', '11', '300'],
  ] } } };
}

function upstream(overrides = {}) {
  const calls = [];
  const dispatches = [];
  const outputs = new Map();
  let runs = [];
  return { calls, dispatches, outputs,
    set runs(value) { runs = value; },
    async fetch(url, init = {}) {
      const text = String(url); calls.push(text);
      if (overrides.handle) {
        const value = await overrides.handle(text, init);
        if (value !== undefined) return value;
      }
      if (text.includes('/commits/main')) return Response.json({ sha: SHA });
      if (text.endsWith('/dispatches')) {
        dispatches.push(JSON.parse(init.body).client_payload);
        assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
        return new Response(null, { status: 204 });
      }
      if (text.includes('/contents/')) {
        const path = new URL(text).pathname.split('/contents/')[1];
        return outputs.has(path) ? Response.json(outputs.get(path)) : new Response(null, { status: 404 });
      }
      if (text.includes('/runs?')) return Response.json({ workflow_runs: runs });
      if (text.startsWith('https://web.ifzq.gtimg.cn/')) return Response.json(marketFixture());
      assert.fail(`Unexpected network request: ${text}`);
    },
  };
}

async function withUpstream(server, callback) {
  const previous = globalThis.fetch;
  globalThis.fetch = server.fetch.bind(server);
  try { await callback(server); } finally { globalThis.fetch = previous; }
}

function resultFor(job, extra = {}) {
  return { code: job.code, job_id: job.job_id, mode: job.mode, source_sha: job.source_sha,
    requested_at: job.requested_at, ...extra };
}

test('server first-observed receipt persists across status, result reads and object eviction without becoming publication time', async () => {
  await withUpstream(upstream(), async server => {
    const env = environment(), job = await (await query(env)).json();
    const value = resultFor(job, { asof: '2026-11-05', generated_at: '2026-11-05T09:00:00Z' });
    server.outputs.set(`stock/jobs/${job.job_id}/600519.json`, value);
    const status = await (await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env)).json();
    const receipt = status.delivery_observation;
    assert.equal(receipt.meaning, 'FIRST_WORKER_READ_NOT_PUBLICATION_OR_USER_VISIBILITY');
    assert.match(receipt.result_sha256, /^[a-f\d]{64}$/);
    assert.equal(receipt.published_at, undefined);
    assert.notEqual(receipt.first_observed_at, value.generated_at);
    env.STOCK_JOBS.evict('600519');
    const fetched = await (await worker.fetch(request(`/result?code=600519&job_id=${job.job_id}`), env)).json();
    assert.deepEqual(fetched.delivery_observation, receipt);
    assert.deepEqual(server.outputs.get(`stock/jobs/${job.job_id}/600519.json`), value, 'upstream immutable artifact is untouched');
    server.outputs.set(`stock/jobs/${job.job_id}/600519.json`, { ...value, changed: true });
    const changed = await worker.fetch(request(`/result?code=600519&job_id=${job.job_id}`), env);
    assert.equal(changed.status, 502, 'an immutable result mutation cannot inherit its old observation');
  });
});

test('legacy or unregistered results remain readable without manufactured server observation receipts', async () => {
  await withUpstream(upstream(), async server => {
    const env = environment();
    server.outputs.set('stock/600519.json', { code: '600519', mode: 'current',
      job_id: '11111111-1111-4111-8111-111111111111', source_sha: SHA });
    const response = await worker.fetch(request('/result?code=600519'), env);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).delivery_observation, null);
    assert.equal(server.dispatches.length, 0);
  });
});

test('CORS, methods and invalid inputs fail before upstream requests', async () => {
  await withUpstream({ fetch: async () => assert.fail('no upstream expected') }, async () => {
    const env = environment();
    const options = await worker.fetch(request('/query', { method: 'OPTIONS' }), env);
    assert.equal(options.status, 204);
    assert.equal(options.headers.get('Access-Control-Allow-Origin'), ORIGIN);
    const forbidden = await worker.fetch(request('/market?code=600519', { origin: 'https://evil.test' }), env);
    assert.equal(forbidden.status, 403);
    assert.equal(forbidden.headers.get('Access-Control-Allow-Origin'), null);
    for (const code of ['123456', 'sh600519', 600519, '../600519', '', null]) {
      assert.equal((await query(env, { code })).status, 400);
    }
    for (const body of [{ code: '600519', mode: 'all' }, { code: '600519', mode: 'history', history_weeks: 157 },
      { code: '600519', mode: 'history', history_weeks: 0 }, { code: '600519', mode: 'history', history_weeks: 1.5 }]) {
      assert.equal((await query(env, body)).status, 400);
    }
    assert.equal((await query(env, '{')).status, 400);
    assert.equal((await worker.fetch(request('/status?code=600519&job_id=../../bad'), env)).status, 400);
    assert.equal((await worker.fetch(request('/status?code=600519&since=yesterday'), env)).status, 400);
    assert.equal((await worker.fetch(request('/market?code=600519', { method: 'POST' }), env)).status, 405);
  });
});

test('missing or broken coordination and secret fail closed', async () => {
  await withUpstream({ fetch: async () => assert.fail('no upstream expected') }, async () => {
    for (const env of [{ GH_TOKEN: TOKEN }, { ...environment(), STOCK_JOBS: null },
      { ...environment(), QUERY_BUDGET: {} }, environment({ GH_TOKEN: '' })]) {
      const response = await query(env);
      assert.equal(response.status, 503);
      assert.match((await response.json()).error_code, /UNAVAILABLE/);
    }
  });
});

test('current dispatch fixes variant, zero history and trusted source; returns identity', async () => {
  await withUpstream(upstream(), async (server) => {
    const response = await query(environment(), { code: '600519', variant: 'expensive', history_weeks: 156,
      source_sha: OTHER_SHA, job_id: 'client-forged' });
    assert.equal(response.status, 202);
    const body = await response.json();
    assert.equal(body.mode, 'current'); assert.equal(body.history_weeks, 0);
    assert.equal(body.source_sha, SHA); assert.equal(body.ratelimit, 'enabled');
    assert.equal(body.since, body.requested_at);
    assert.match(body.job_id, /^[a-f\d-]{36}$/);
    assert.equal(server.dispatches.length, 1);
    assert.deepEqual(server.dispatches[0], { code: '600519', variant: 'stk_lite', mode: 'current',
      history_weeks: '0', job_id: body.job_id, requested_at: body.requested_at, source_sha: SHA });
    assert.doesNotMatch(JSON.stringify(body), new RegExp(TOKEN));
  });
});

test('history is a separate explicit job, default 104 and allowed maximum 156', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment();
    const current = await (await query(env)).json();
    const history = await (await query(env, { code: '600519', mode: 'history' })).json();
    assert.notEqual(current.job_id, history.job_id); assert.equal(history.history_weeks, 104);
    const maximum = await (await query(env, { code: '600520', mode: 'history', history_weeks: 156 })).json();
    assert.equal(maximum.history_weeks, 156); assert.equal(server.dispatches.length, 3);
  });
});

test('concurrent same-code queries dispatch once and survive object eviction', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment();
    const responses = await Promise.all(Array.from({ length: 12 }, () => query(env)));
    const bodies = await Promise.all(responses.map((r) => r.json()));
    assert.ok(responses.every((r) => r.status === 202));
    assert.equal(new Set(bodies.map((r) => r.job_id)).size, 1);
    assert.equal(bodies.filter((r) => r.deduped).length, 11);
    env.STOCK_JOBS.evict('600519');
    const afterRestart = await (await query(env)).json();
    assert.equal(afterRestart.job_id, bodies[0].job_id);
    assert.equal(server.dispatches.length, 1);
  });
});

test('global budget is atomic across different stock objects and persists after eviction', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment({ QUERIES_PER_HOUR: '3' });
    const responses = await Promise.all(Array.from({ length: 8 }, (_, i) =>
      query(env, { code: `60000${i}` }, `203.0.113.${i}`)));
    assert.equal(responses.filter((r) => r.status === 202).length, 3);
    assert.equal(responses.filter((r) => r.status === 429).length, 5);
    env.QUERY_BUDGET.evict('global');
    assert.equal((await query(env, { code: '600099' }, '203.0.113.99')).status, 429);
    assert.equal(server.dispatches.length, 3);
  });
});

test('IP budget counts new jobs, not repeated active-job reads', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment();
    for (let i = 0; i < 5; i += 1) assert.equal((await query(env, { code: `60000${i}` })).status, 202);
    assert.equal((await query(env, { code: '600006' })).status, 429);
    assert.equal((await query(env, { code: '600000' })).status, 202);
    assert.equal(server.dispatches.length, 5);
  });
});

test('definite dispatch rejection is sanitized and permits a subsequent attempt', async () => {
  let attempts = 0;
  const server = upstream({ handle: async (url) => {
    if (url.endsWith('/dispatches') && attempts++ === 0) return new Response(`private ${TOKEN}`, { status: 403 });
  } });
  await withUpstream(server, async () => {
    const env = environment();
    const failed = await query(env); assert.equal(failed.status, 502);
    const text = await failed.text(); assert.doesNotMatch(text, /private|fixture-secret/);
    assert.equal(JSON.parse(text).error_code, 'DISPATCH_FAILED');
    const status = await (await worker.fetch(request(`/status?code=600519&job_id=${JSON.parse(text).job_id}`), env)).json();
    assert.equal(status.phase, 'dispatch_failed'); assert.equal(status.conclusion, 'failure');
    assert.equal((await query(env)).status, 202);
    assert.equal(attempts, 2);
  });
});

test('lost dispatch acknowledgement retains its job instead of dispatching twice', async () => {
  let attempts = 0;
  await withUpstream(upstream({ handle: async (url) => {
    if (url.endsWith('/dispatches')) { attempts += 1; throw new Error(`private ${TOKEN}`); }
  } }), async () => {
    const env = environment();
    const first = await (await query(env)).json();
    const again = await (await query(env)).json();
    assert.equal(first.status, 'dispatch_unknown'); assert.equal(again.job_id, first.job_id);
    assert.equal(again.deduped, true); assert.equal(attempts, 1);
  });
});

test('source lookup failure never dispatches unpinned computation', async () => {
  await withUpstream(upstream({ handle: async (url) => {
    if (url.includes('/commits/main')) return Response.json({ sha: 'main' });
  } }), async (server) => {
    const response = await query(environment());
    assert.equal(response.status, 502); assert.equal((await response.json()).error_code, 'SOURCE_UNAVAILABLE');
    assert.equal(server.dispatches.length, 0);
  });
});

test('upstream 5xx acknowledgement is uncertain and must not trigger a duplicate dispatch', async () => {
  let attempts = 0;
  await withUpstream(upstream({ handle: async (url) => {
    if (url.endsWith('/dispatches')) { attempts += 1; return new Response(null, { status: 503 }); }
  } }), async () => {
    const env = environment();
    const first = await (await query(env)).json();
    const again = await (await query(env)).json();
    assert.equal(first.status, 'dispatch_unknown'); assert.equal(again.job_id, first.job_id);
    assert.equal(attempts, 1);
  });
});

test('job status uses exact run identity, never an older same-code success', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.runs = [{ display_title: 'stock_query 600519', status: 'completed', conclusion: 'success', created_at: job.requested_at },
      { display_title: `stock_query 600519 ${job.job_id}`, status: 'in_progress', created_at: job.requested_at }];
    const response = await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env);
    const status = await response.json(); assert.equal(status.status, 'in_progress');
    assert.equal(status.current_ready, false); assert.equal(status.history_ready, false);
    assert.equal((await worker.fetch(request(`/status?code=600520&job_id=${job.job_id}`), env)).status, 404);
  });
});

test('current is ready from its verified artifact without waiting for whole workflow', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.outputs.set(`stock/jobs/${job.job_id}/600519.json`, resultFor(job));
    const status = await (await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env)).json();
    assert.equal(status.status, 'completed'); assert.equal(status.conclusion, 'success');
    assert.equal(status.current_ready, true); assert.equal(status.history_ready, false);
    assert.equal(status.phase, 'current_ready');
    assert.equal(server.calls.filter((url) => url.includes('/runs?')).length, 0);
  });
});

test('approval-waiting Actions runs remain active and cannot be duplicated', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.runs = [{ display_title: `stock_query 600519 ${job.job_id}`, status: 'waiting', created_at: job.requested_at }];
    const repeated = await (await query(env)).json();
    assert.equal(repeated.job_id, job.job_id); assert.equal(repeated.status, 'waiting');
    assert.equal(server.dispatches.length, 1);
    const queryURL = new URL(server.calls.find((url) => url.includes('/runs?')));
    assert.match(queryURL.searchParams.get('created'), /^>=/);
  });
});

test('history-only artifact makes history ready without requiring another current result', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env, { code: '600519', mode: 'history' })).json();
    server.outputs.set(`stock/jobs/${job.job_id}/600519_history.json`, resultFor(job));
    const status = await (await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env)).json();
    assert.equal(status.history_ready, true); assert.equal(status.current_ready, false);
    assert.equal(status.phase, 'history_ready'); assert.equal(status.conclusion, 'success');
  });
});

test('wrong result source or job identity cannot become a ready state', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.outputs.set(`stock/jobs/${job.job_id}/600519.json`, resultFor(job, { source_sha: OTHER_SHA }));
    const response = await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env);
    assert.equal(response.status, 502);
    assert.equal((await (await query(env)).json()).job_id, job.job_id);
    assert.equal(server.dispatches.length, 1);
  });
});

test('successful workflow without published result is not reported as a successful analysis', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.runs = [{ display_title: `stock_query 600519 ${job.job_id}`, status: 'completed', conclusion: 'success',
      created_at: job.requested_at, updated_at: '2020-01-01T00:00:00Z' }];
    const status = await (await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env)).json();
    assert.equal(status.conclusion, 'failure'); assert.equal(status.phase, 'publish_failed');
    assert.equal(status.error_code, 'RESULT_NOT_PUBLISHED');
  });
});

test('recent completion allows a bounded publication visibility grace period', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.runs = [{ display_title: `stock_query 600519 ${job.job_id}`, status: 'completed', conclusion: 'success',
      created_at: job.requested_at, updated_at: new Date().toISOString() }];
    const status = await (await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env)).json();
    assert.equal(status.status, 'in_progress'); assert.equal(status.phase, 'publishing');
  });
});

test('job-specific error results distinguish a completed failure from no result', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.outputs.set(`stock/jobs/${job.job_id}/600519_error.json`, resultFor(job, { error_code: 'DATA_MISSING' }));
    const status = await (await worker.fetch(request(`/status?code=600519&job_id=${job.job_id}`), env)).json();
    assert.equal(status.error_ready, true); assert.equal(status.conclusion, 'failure');
  });
});

test('legacy since status and unscoped result remain readable', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment();
    server.runs = [{ display_title: 'stock_query 600519', status: 'completed', conclusion: 'success', created_at: '2026-11-01T00:00:00Z' }];
    assert.equal((await (await worker.fetch(request('/status?code=600519'), env)).json()).status, 'completed');
    assert.equal((await (await worker.fetch(request('/status?code=600519&since=2026-11-02T00:00:00Z'), env)).json()).status, 'pending');
    server.outputs.set('stock/600519.json', { code: '600519', old_schema: true });
    const result = await worker.fetch(request('/result?code=600519&kind=latest'), env);
    assert.equal(result.status, 200); assert.equal(result.headers.get('Cache-Control'), 'max-age=30');
    assert.equal((await result.json()).old_schema, true);
    const missing = await worker.fetch(request('/result?code=600519&kind=history'), env);
    assert.equal(missing.status, 404); assert.equal((await missing.json()).error_code, 'RESULT_NOT_FOUND');
  });
});

test('job result reads cannot fall back to another job or the latest pointer', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment(); const job = await (await query(env)).json();
    server.outputs.set('stock/600519.json', resultFor(job));
    const url = `/result?code=600519&kind=latest&job_id=${job.job_id}`;
    assert.equal((await worker.fetch(request(url), env)).status, 404);
    server.outputs.set(`stock/jobs/${job.job_id}/600519.json`, resultFor(job, { code: '600520' }));
    assert.equal((await worker.fetch(request(url), env)).status, 502);
    server.outputs.set(`stock/jobs/${job.job_id}/600519.json`, resultFor(job));
    assert.equal((await worker.fetch(request(url), env)).status, 200);
  });
});

test('market excludes unclosed, future, weekend and malformed bars, preserving raw OHLC', () => {
  const payload = marketFixture();
  payload.data.sh600519.day.push(['2026-11-07', '12', '13', '14', '11', '300'],
    ['2026-11-09', '12', '13', '14', '11', '300'], ['2026-02-30', '12', '13', '14', '11', '300'],
    ['2026-11-03', '12', '13', '10', '11', '300'], ['2026-11-02', '', '13', '14', '11', '300']);
  const before = normalizeMarket(payload, '600519', new Date('2026-11-06T07:29:59Z'));
  assert.equal(before.asof, '2026-11-05'); assert.equal(before.price.length, 2);
  assert.equal(before.adjustment, 'none'); assert.equal(before.model_computed, false);
  const after = normalizeMarket(payload, '600519', new Date('2026-11-06T07:30:00Z'));
  assert.equal(after.asof, '2026-11-06'); assert.equal(after.price.length, 3);
  assert.equal(after.latest.open, 12); assert.equal(after.latest.close, 13);
  assert.equal(closedCutoff(new Date('2026-11-06T07:29:59Z')), '2026-11-05');
});

test('market routes Beijing exchange explicitly rather than treating it as Shenzhen', () => {
  const result = normalizeMarket(marketFixture('bj920001'), '920001', new Date('2026-11-06T08:00:00Z'));
  assert.equal(result.symbol, 'bj920001'); assert.equal(result.exchange, 'bj');
  assert.throws(() => normalizeMarket(marketFixture('sz920001'), '920001'), /market_empty/);
});

test('market is independent of fitting, deduplicates concurrent downloads and caches expected source', async () => {
  await withUpstream(upstream(), async (server) => {
    const env = environment();
    const responses = await Promise.all(Array.from({ length: 4 }, () => worker.fetch(request('/market?code=600519'), env)));
    const bodies = await Promise.all(responses.map((r) => r.json()));
    assert.ok(responses.every((r) => r.status === 200));
    assert.equal(bodies[0].cache, 'miss'); assert.equal(bodies[1].cache, 'hit');
    assert.equal(bodies[0].expected_source_sha, SHA);
    assert.equal(server.calls.filter((url) => url.includes('gtimg.cn')).length, 1);
    assert.equal(server.calls.filter((url) => url.includes('/commits/main')).length, 1);
    assert.equal(server.dispatches.length, 0);
  });
});

test('market remains readable when optional GitHub metadata is unavailable', async () => {
  await withUpstream(upstream({ handle: async (url) => {
    if (url.includes('/commits/main')) return new Response(null, { status: 403 });
  } }), async () => {
    const response = await worker.fetch(request('/market?code=600519'), environment({ GH_TOKEN: '' }));
    assert.equal(response.status, 200); assert.equal((await response.json()).expected_source_sha, null);
  });
});

test('slow same-stock dispatch does not serialize an independent market response behind it', async () => {
  let release;
  let signalStarted;
  const started = new Promise((resolve) => { signalStarted = resolve; });
  const held = new Promise((resolve) => { release = resolve; });
  let sourceCalls = 0;
  await withUpstream(upstream({ handle: async (url) => {
    if (url.includes('/commits/main') && sourceCalls++ === 0) {
      signalStarted(); return held;
    }
  } }), async () => {
    const env = environment();
    const submitting = query(env);
    await started;
    let timer;
    try {
      const response = await Promise.race([
        worker.fetch(request('/market?code=600519'), env),
        new Promise((_resolve, reject) => { timer = setTimeout(() => reject(new Error('market blocked')), 500); }),
      ]);
      assert.equal(response.status, 200);
    } finally {
      clearTimeout(timer);
      release(Response.json({ sha: SHA }));
      await submitting;
    }
  });
});

test('expired market cache is explicitly stale on upstream failure and is never overwritten', async () => {
  let failMarket = false;
  await withUpstream(upstream({ handle: async (url) => {
    if (failMarket && url.includes('gtimg.cn')) return new Response('vendor private error', { status: 500 });
  } }), async () => {
    const env = environment();
    const first = await (await worker.fetch(request('/market?code=600519'), env)).json();
    const storage = env.STOCK_JOBS.storage.get('market:600519');
    const cached = await storage.get('market'); cached.at -= 120_000; await storage.put('market', cached);
    failMarket = true;
    const stale = await (await worker.fetch(request('/market?code=600519'), env)).json();
    assert.equal(stale.stale, true); assert.equal(stale.warning_code, 'MARKET_UNAVAILABLE');
    assert.equal(stale.asof, first.asof); assert.equal(stale.generated_at, first.generated_at);
    assert.deepEqual(await storage.get('market'), cached);
    assert.doesNotMatch(JSON.stringify(stale), /vendor private/);
  });
});

test('fetch helper aborts overdue requests instead of allowing an unbounded upstream wait', async () => {
  await withUpstream({ fetch: async (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
  }) }, async () => {
    await assert.rejects(fetchJSON('https://fixture.test', {}, 5), /aborted/);
  });
});
