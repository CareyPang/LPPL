'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { create, compatible, stale } = require('../app/stock-session.js');

const STORE = 'lppl.stock.jobs.v1';
const NOW = Date.parse('2026-11-06T08:00:00Z');
const SHA = 'a'.repeat(40);
const JOB = '11111111-1111-4111-8111-111111111111';
const OTHER_JOB = '22222222-2222-4222-8222-222222222222';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function settle() {
  for (let i = 0; i < 15; i++) await Promise.resolve();
}

function current(code = '000001', extra = {}) {
  return {
    symbol: (code.startsWith('6') ? 'sh' : 'sz') + code,
    asof: '2026-11-05', generated_at: '2026-11-05T09:00:00Z',
    model_version: 'model-a', variant: 'stk_lite', source_sha: SHA,
    ...extra,
  };
}

function market(code = '000001', extra = {}) {
  return { code, asof: '2026-11-05', price: [{ date: '2026-11-05', close: 10 }], expected_source_sha: SHA, ...extra };
}

function harness(overrides = {}, saved = []) {
  const events = [], requests = [], statuses = [], timers = new Map();
  const store = new Map([[STORE, JSON.stringify(saved)]]);
  let timerId = 0, now = NOW;
  const api = {
    latest: async () => null,
    history: async () => null,
    market: async code => market(code),
    remote: async () => null,
    request: async (code, options) => {
      requests.push({ code, options });
      return { job_id: JOB, requested_at: '2026-11-06T08:00:00Z', source_sha: SHA };
    },
    status: async (code, options) => {
      statuses.push({ code, options });
      return { job_id: options.jobId, status: 'queued' };
    },
    ...overrides,
  };
  const session = create({
    api, now: () => now, pollMs: 100,
    storage: { getItem: key => store.get(key), setItem: (key, value) => store.set(key, value) },
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id),
    onChange: state => events.push(structuredClone(state)),
  });
  return {
    api, session, requests, statuses, events, store, timers,
    async poll() {
      const next = timers.entries().next().value;
      assert.ok(next, 'A pending task should schedule another poll');
      timers.delete(next[0]);
      now += next[1].delay;
      await next[1].fn();
      await settle();
    },
  };
}

test('slow history never blocks available market/current or starts historical calculation', async t => {
  const history = deferred();
  const h = harness({
    latest: async () => current(),
    history: () => history.promise,
    remote: (_code, kind) => kind === 'history' ? history.promise : Promise.resolve(current()),
  });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  assert.equal(h.session.snapshot().marketStatus, 'ready');
  assert.equal(h.session.snapshot().current.symbol, 'sz000001');
  assert.equal(h.session.snapshot().history, null);
  assert.equal(h.requests.length, 0);
  history.resolve({ ...current(), frames: [] });
  await settle();
  assert.ok(h.session.snapshot().history);
});

test('available market renders while current-cache requests are still pending', async t => {
  const latest = deferred();
  const h = harness({ latest: () => latest.promise, remote: (_code, kind) => kind === 'latest' ? latest.promise : Promise.resolve(null) });
  t.after(() => h.session.destroy());
  const selecting = h.session.select('000001');
  await settle();
  assert.equal(h.session.snapshot().marketStatus, 'ready');
  assert.equal(h.session.snapshot().current, null);
  latest.resolve(current());
  await selecting;
  assert.equal(h.requests.length, 0);
});

test('stale upstream cache stays readable but exposes its cutoff and failed-refresh warning', async t => {
  const quote = market('000001', { stale: true, cache: 'stale', warning_code: 'MARKET_UNAVAILABLE' });
  const h = harness({ latest: async () => current(), market: async () => quote });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  const state = h.session.snapshot();
  assert.equal(state.market, quote);
  assert.equal(state.marketStatus, 'stale');
  assert.match(state.issues.market, /行情源暂时无法更新/);
  assert.match(state.issues.market, /2026-11-05.*缓存日线/);
  assert.equal(state.currentStatus, 'current_ready');
  assert.equal(h.requests.length, 0, 'A quote cache refresh failure alone does not require refitting');
});

test('rate-limited market fallback is distinct from fresh data and recovers on a successful refresh', async t => {
  let staleQuote = true;
  const h = harness({ latest: async () => current(), market: async () => market('000001', staleQuote ?
    { stale: true, cache: 'stale', warning_code: 'RATE_LIMITED' } : { stale: false, cache: 'miss' }) });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  assert.equal(h.session.snapshot().marketStatus, 'stale');
  assert.match(h.session.snapshot().issues.market, /额度暂时用尽/);
  staleQuote = false;
  await h.session.select('000001');
  assert.equal(h.session.snapshot().marketStatus, 'ready');
  assert.equal(h.session.snapshot().issues.market, undefined);
});

test('market request failure retains existing quote and explicitly marks the cache stale', async t => {
  let failQuote = false;
  const quote = market();
  const h = harness({ latest: async () => current(), market: async () => {
    if (failQuote) throw Error('connection lost');
    return quote;
  } });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  failQuote = true;
  await h.session.select('000001');
  const state = h.session.snapshot();
  assert.equal(state.market, quote); assert.equal(state.marketStatus, 'stale');
  assert.match(state.issues.market, /刷新未完成.*2026-11-05.*缓存日线/);
});

test('late requests from another selected stock cannot replace the visible stock', async t => {
  const first = deferred();
  const h = harness({
    latest: code => code === '000001' ? first.promise : Promise.resolve(current(code)),
    remote: (code, kind) => kind === 'history' ? Promise.resolve(null) :
      code === '000001' ? first.promise : Promise.resolve(current(code)),
  });
  t.after(() => h.session.destroy());
  const a = h.session.select('000001');
  await h.session.select('600000');
  const boundary = h.events.length;
  first.resolve(current('000001'));
  await a;
  assert.equal(h.session.snapshot().code, '600000');
  assert.equal(h.session.snapshot().current.symbol, 'sh600000');
  assert.ok(h.events.slice(boundary).every(event => event.code === '600000'));
});

test('a later response carrying older data cannot replace a newer current result', async t => {
  const old = deferred();
  const h = harness({
    latest: () => old.promise,
    remote: async (_code, kind) => kind === 'latest' ? current('000001', { asof: '2026-11-06' }) : null,
    market: async () => market('000001', { asof: '2026-11-06' }),
  });
  t.after(() => h.session.destroy());
  const selecting = h.session.select('000001');
  await settle();
  assert.equal(h.session.snapshot().current.asof, '2026-11-06');
  old.resolve(current());
  await selecting;
  assert.equal(h.session.snapshot().current.asof, '2026-11-06');
  assert.equal(h.requests.length, 0);
});

test('cold cache creates only current analysis with zero history weeks', async t => {
  const h = harness();
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  assert.equal(h.requests.length, 1);
  assert.deepEqual(h.requests[0], { code: '000001', options: { mode: 'current', historyWeeks: 0 } });
  assert.equal(h.session.snapshot().marketStatus, 'ready');
  assert.equal(h.session.snapshot().historyStatus, 'idle');
  assert.equal(h.session.snapshot().tasks[0].job_id, JOB);
});

test('fresh cached analysis does not dispatch a new calculation', async t => {
  const h = harness({ latest: async () => current() });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  assert.equal(h.requests.length, 0);
  assert.equal(h.session.snapshot().stale, false);
});

test('same-day result ordering compares timestamp instants across legacy timezone formats', async t => {
  const remote = deferred();
  const saved = current('000001', { generated_at: '2026-11-05T09:01:00Z' });
  const h = harness({ latest: async () => saved,
    remote: (_code, kind) => kind === 'latest' ? remote.promise : Promise.resolve(null) });
  t.after(() => h.session.destroy());
  const selected = h.session.select('000001'); await settle();
  remote.resolve(current('000001', { generated_at: '2026-11-05T17:00:00+08:00' }));
  await selected;
  assert.equal(h.session.snapshot().current, saved, 'An earlier instant must not overwrite a newer result');
});

for (const [reason, cached, quote] of [
  ['newer market date', current(), market('000001', { asof: '2026-11-06' })],
  ['different model source', current('000001', { source_sha: 'b'.repeat(40) }), market()],
]) {
  test(`stale analysis refreshes automatically for ${reason}`, async t => {
    const h = harness({ latest: async () => cached, market: async () => quote });
    t.after(() => h.session.destroy());
    await h.session.select('000001');
    assert.equal(h.requests.length, 1);
    assert.equal(h.session.snapshot().current, cached, 'Old analysis remains available while updating');
    assert.equal(h.session.snapshot().stale, true);
  });
}

test('stored running jobs are resumed without re-dispatching', async t => {
  const saved = [{ code: '000001', mode: 'current', job_id: JOB, requested_at: '2026-11-06T07:55:00Z', source_sha: SHA }];
  const h = harness({}, saved);
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  assert.equal(h.requests.length, 0);
  assert.equal(h.statuses.length, 1);
  assert.deepEqual(h.statuses[0], { code: '000001', options: { jobId: JOB } });
  assert.equal(h.session.snapshot().tasks[0].job_id, JOB);
});

test('a restored failed job is shown as failed instead of automatically dispatching again', async t => {
  const saved = [{ code: '000001', mode: 'current', job_id: JOB, requested_at: '2026-11-06T07:55:00Z', source_sha: SHA }];
  const h = harness({
    latest: async () => current(),
    market: async () => market('000001', { asof: '2026-11-06' }),
    status: async () => ({ job_id: JOB, status: 'completed', conclusion: 'failure' }),
  }, saved);
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  await settle();
  assert.equal(h.requests.length, 0, 'Restoring a task must not retry its failed computation without a new request');
  assert.equal(h.session.snapshot().currentStatus, 'failed');
  assert.equal(h.session.snapshot().current.asof, '2026-11-05');
});

test('a confirmed missing restored job releases only the local reference and allows explicit retry', async t => {
  const saved = [{ code: '000001', mode: 'current', job_id: JOB, requested_at: '2026-11-06T07:55:00Z', source_sha: SHA }];
  const h = harness({
    latest: async () => current(),
    market: async () => market('000001', { asof: '2026-11-06' }),
    status: async () => { const error = Error('HTTP 404'); error.code = 'JOB_NOT_FOUND'; error.status = 404; throw error; },
  }, saved);
  t.after(() => h.session.destroy());
  await h.session.select('000001'); await settle();
  assert.equal(h.requests.length, 0, 'No automatic redispatch after a missing restored job');
  assert.equal(h.session.snapshot().tasks.length, 0);
  assert.deepEqual(JSON.parse(h.store.get(STORE)), []);
  assert.equal(h.session.snapshot().currentStatus, 'failed');
  assert.equal(h.session.snapshot().current.asof, '2026-11-05');
  assert.match(h.session.snapshot().issues.current, /原任务记录已不可用/);
  h.api.status = async () => ({ job_id: JOB, status: 'queued' });
  await h.session.request('000001'); await settle();
  assert.equal(h.requests.length, 1, 'An explicit retry can reach server-side deduplication');
  assert.equal(h.session.snapshot().tasks.length, 1);
});

test('an unclassified 404 or transient status error does not discard a recoverable job', async t => {
  const saved = [{ code: '000001', mode: 'current', job_id: JOB, requested_at: '2026-11-06T07:55:00Z', source_sha: SHA }];
  const h = harness({ status: async () => { const error = Error('HTTP 404'); error.status = 404; throw error; } }, saved);
  t.after(() => h.session.destroy());
  await h.session.select('000001'); await settle();
  assert.equal(h.session.snapshot().currentStatus, 'reconnecting');
  assert.equal(h.session.snapshot().tasks[0].job_id, JOB);
  assert.equal(h.requests.length, 0);
});

test('dispatch timeout is shown as unconfirmed and manual retry can recover the server job', async t => {
  let attempts = 0;
  const h = harness({ latest: async () => current(), request: async () => {
    attempts += 1;
    if (attempts === 1) { const error = Error('timeout'); error.code = 'REQUEST_TIMEOUT'; throw error; }
    return { job_id: JOB, requested_at: '2026-11-06T08:00:00Z', source_sha: SHA };
  } });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  await h.session.request('000001');
  assert.equal(h.session.snapshot().currentStatus, 'unconfirmed');
  assert.match(h.session.snapshot().issues.current, /后台任务可能仍在继续/);
  assert.equal(h.session.snapshot().current.asof, '2026-11-05');
  await h.session.request('000001'); await settle();
  assert.equal(attempts, 2);
  assert.equal(h.session.snapshot().tasks[0].job_id, JOB);
});

test('current update failure preserves existing result and the error state', async t => {
  const h = harness({
    latest: async () => current(),
    market: async () => market('000001', { asof: '2026-11-06' }),
    status: async () => ({ job_id: JOB, status: 'completed', conclusion: 'failure' }),
  });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  await settle();
  assert.equal(h.session.snapshot().current.asof, '2026-11-05');
  assert.equal(h.session.snapshot().currentStatus, 'stale');
  assert.match(h.session.snapshot().issues.current, /已有行情和分析仍可查看/);
  assert.equal(h.session.snapshot().tasks.length, 0);
});

test('a completed matching job updates data, clears staleness and persisted task', async t => {
  let ready = false;
  const h = harness({
    latest: async () => current(),
    market: async () => market('000001', { asof: '2026-11-06' }),
    status: async () => ({ job_id: JOB, status: ready ? 'completed' : 'in_progress', current_ready: ready, conclusion: ready ? 'success' : null }),
    remote: async (_code, kind, options) => kind === 'latest' && options?.jobId ?
      current('000001', { asof: '2026-11-06', job_id: JOB, requested_at: '2026-11-06T08:00:00Z' }) : null,
  });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  await settle();
  ready = true;
  await h.poll();
  assert.equal(h.session.snapshot().current.asof, '2026-11-06');
  assert.equal(h.session.snapshot().currentStatus, 'current_ready');
  assert.equal(h.session.snapshot().stale, false);
  assert.equal(h.session.snapshot().tasks.length, 0);
  assert.deepEqual(JSON.parse(h.store.get(STORE)), []);
});

test('mismatching status job id cannot be adopted', async t => {
  let jobFetches = 0;
  const h = harness({
    status: async () => ({ job_id: OTHER_JOB, current_ready: true }),
    remote: async (_code, _kind, options) => { if (options?.jobId) jobFetches++; return null; },
  });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  await settle();
  assert.equal(jobFetches, 0);
  assert.equal(h.session.snapshot().currentStatus, 'reconnecting');
  assert.equal(h.session.snapshot().tasks.length, 1);
});

for (const [reason, invalid] of [
  ['job id', current('000001', { job_id: OTHER_JOB })],
  ['stock identity', current('600000', { job_id: JOB })],
  ['exchange identity', current('000001', { symbol: 'sh000001', job_id: JOB })],
  ['source revision', current('000001', { job_id: JOB, source_sha: 'b'.repeat(40) })],
]) {
  test(`a ready result with mismatching ${reason} remains pending instead of being adopted`, async t => {
    const h = harness({
      status: async () => ({ job_id: JOB, current_ready: true }),
      remote: async (_code, _kind, options) => options?.jobId ? invalid : null,
    });
    t.after(() => h.session.destroy());
    await h.session.select('000001');
    await settle();
    assert.equal(h.session.snapshot().current, null);
    assert.equal(h.session.snapshot().currentStatus, 'reconnecting');
    assert.equal(h.session.snapshot().tasks.length, 1);
  });
}

test('explicit history generation is separate and its failure retains current analysis', async t => {
  const h = harness({
    latest: async () => current(),
    status: async () => ({ job_id: JOB, status: 'completed', conclusion: 'failure' }),
  });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  await h.session.request('000001', 'history');
  await settle();
  assert.deepEqual(h.requests, [{ code: '000001', options: { mode: 'history', historyWeeks: 104 } }]);
  assert.equal(h.session.snapshot().currentStatus, 'current_ready');
  assert.equal(h.session.snapshot().historyStatus, 'failed');
  assert.equal(h.session.snapshot().current.symbol, 'sz000001');
});

test('current stays ready while an explicit history task moves from queued to history_running', async t => {
  let phase = 'queued';
  const h = harness({ latest: async () => current(), status: async () => ({
    job_id: JOB, phase, status: phase === 'queued' ? 'queued' : 'in_progress',
    current_ready: false, history_ready: false,
  }) });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  await h.session.request('000001', 'history'); await settle();
  assert.equal(h.session.snapshot().historyStatus, 'queued');
  phase = 'history_running'; await h.poll();
  assert.equal(h.session.snapshot().historyStatus, 'history_running');
  assert.equal(h.session.snapshot().currentStatus, 'current_ready');
  assert.equal(h.session.snapshot().current.symbol, 'sz000001');
});

test('stale terminal state keeps its reason and successful cutoff without pretending the failed job is ready', async t => {
  const h = harness({ latest: async () => current(), status: async () => ({
    job_id: JOB, phase: 'stale', status: 'completed', conclusion: 'failure', current_ready: false,
    stale: true, stale_reason: 'refresh_failed_previous_result_retained',
    last_success_at: '2026-11-05T09:00:00Z',
  }) });
  t.after(() => h.session.destroy());
  await h.session.select('000001'); await h.session.request('000001'); await settle();
  assert.equal(h.session.snapshot().currentStatus, 'stale');
  assert.equal(h.session.snapshot().stale_reason, 'refresh_failed_previous_result_retained');
  assert.equal(h.session.snapshot().last_success_at, '2026-11-05T09:00:00Z');
  assert.equal(h.session.snapshot().current.asof, '2026-11-05');
  assert.equal(h.session.snapshot().tasks.length, 0);
  await h.session.select('000001');
  assert.equal(h.session.snapshot().currentStatus, 'stale', 'Reloading the same old data cannot erase the refresh failure');
});

test('history compatibility rejects mixed symbols, model versions, variants and future frames', () => {
  const c = current();
  const hist = { ...current(), frames: [{ asof: '2026-11-04' }] };
  assert.equal(compatible(c, hist), true);
  assert.equal(compatible(c, { ...hist, symbol: 'sh600000' }), false);
  assert.equal(compatible(c, { ...hist, model_version: 'model-b' }), false);
  assert.equal(compatible(c, { ...hist, variant: 'stk_full' }), false);
  assert.equal(compatible(c, { ...hist, asof: '2026-11-06' }), false);
  const legacy = { ...hist, frames: [{ asof: '2026-11-06' }] };
  delete legacy.asof;
  assert.equal(compatible(c, legacy), false, 'Legacy frame dates must not be from the future');
});

test('history compatibility checks schema and fitting code versions on both independently fetched results', () => {
  const c = current('000001', { schema_version: 'stock_result_v1', fit_code_version: 'fit-a' });
  const hist = { ...c, frames: [{ asof: '2026-11-04' }] };
  assert.equal(compatible(c, hist), true);
  for (const key of ['schema_version', 'fit_code_version']) {
    assert.equal(compatible(c, { ...hist, [key]: 'different' }), false);
    const missing = { ...hist };
    delete missing[key];
    assert.equal(compatible(c, missing), false, `A missing history ${key} cannot prove compatibility`);
    assert.equal(compatible(missing, hist), false, `A missing current ${key} cannot prove compatibility`);
  }
});

test('append-only data updates retain history only when every historical input fingerprint still matches', () => {
  const c = current('000001', { data_version: 'new-data', history_input_hashes: {
    '2026-10-30': 'hash-oct30', '2026-11-04': 'hash-nov04',
  } });
  const hist = { ...current(), data_version: 'old-data', frames: [
    { asof: '2026-10-30', fit_input_hash: 'hash-oct30' },
    { asof: '2026-11-04', fit_input_hash: 'hash-nov04' },
  ] };
  assert.equal(compatible(c, hist), true);
  assert.equal(compatible({ ...c, history_input_hashes: undefined }, hist), false);
  assert.equal(compatible(c, { ...hist, frames: [] }), false);
  assert.equal(compatible(c, { ...hist, frames: [hist.frames[0], { asof: '2026-11-04' }] }), false);
  assert.equal(compatible(c, { ...hist, frames: [hist.frames[0], {
    asof: '2026-11-04', fit_input_hash: 'restated-data',
  }] }), false);
});

test('same data versions and scientific metadata permit history across unrelated repository commits', () => {
  const c = current('000001', { data_version: 'same-data', fit_code_version: 'same-fit' });
  const hist = { ...c, source_sha: 'b'.repeat(40), frames: [{ asof: '2026-11-04' }] };
  assert.equal(compatible(c, hist), true, 'source_sha alone is not a scientific input version');
});

test('legacy results keep compatible version metadata but cannot masquerade as a new declared model', () => {
  const c = current();
  delete c.model_version;
  c.stock_meta = { code_version: 'legacy-v1', variant: 'stk_lite' };
  const hist = { ...c, frames: [{ asof: '2026-11-04' }] };
  assert.equal(compatible(c, hist), true);
  assert.equal(compatible({ ...c, model_version: 'legacy-v1' }, hist), false);
});

test('history compatibility rejects malformed or impossible trading dates', () => {
  const c = current();
  for (const asof of ['', '2026-02-30', '2026-11', '2026-11-99', null]) {
    assert.equal(compatible(c, { ...c, frames: [{ asof }] }), false);
  }
  assert.equal(compatible({ ...c, asof: undefined }, { ...c, frames: [] }), false);
});

test('staleness detects source changes separately from price dates', () => {
  assert.equal(stale(current(), market()), false);
  assert.equal(stale(current(), market('000001', { expected_source_sha: 'b'.repeat(40) })), true);
  assert.equal(stale(null, market()), true);
});

test('a double click while dispatch is pending creates one job', async t => {
  const dispatch = deferred();
  let count = 0;
  const h = harness({ latest: async () => current(), request: () => { count++; return dispatch.promise; } });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  const a = h.session.request('000001');
  const b = h.session.request('000001');
  dispatch.resolve({ job_id: JOB, requested_at: '2026-11-06T08:00:00Z', source_sha: SHA });
  await Promise.all([a, b]);
  assert.equal(count, 1);
  assert.equal(h.session.snapshot().tasks.length, 1);
});

test('destroy prevents late data from emitting or starting a calculation', async () => {
  const delayed = deferred();
  const h = harness({ market: () => delayed.promise });
  const selecting = h.session.select('000001');
  await settle();
  const boundary = h.events.length;
  h.session.destroy();
  delayed.resolve(market());
  await selecting;
  assert.equal(h.events.length, boundary);
  assert.equal(h.requests.length, 0);
  assert.equal(h.timers.size, 0);
});

test('destroy stops polling but preserves the task so a new page can resume it', async () => {
  const h = harness();
  await h.session.select('000001');
  await settle();
  assert.equal(h.timers.size, 1);
  h.session.destroy();
  assert.equal(h.timers.size, 0);
  assert.equal(JSON.parse(h.store.get(STORE))[0].job_id, JOB);
});

test('an older market response cannot overwrite newer quotes for the same stock', async t => {
  const old = deferred();
  let calls = 0;
  const h = harness({
    latest: async () => current('000001', { asof: '2026-11-06' }),
    market: () => ++calls === 1 ? old.promise : Promise.resolve(market('000001', { asof: '2026-11-06' })),
  });
  t.after(() => h.session.destroy());
  const first = h.session.select('000001');
  await settle();
  await h.session.select('000001');
  assert.equal(h.session.snapshot().market.asof, '2026-11-06');
  old.resolve(market());
  await first;
  assert.equal(h.session.snapshot().market.asof, '2026-11-06');
});

test('cached results from another exchange are rejected even when the numeric code matches', async t => {
  const h = harness({ latest: async () => current('000001', { symbol: 'sh000001' }) });
  t.after(() => h.session.destroy());
  await h.session.select('000001');
  assert.equal(h.session.snapshot().current, null);
  assert.equal(h.requests.length, 1);
});

test('canonical Shanghai, Shenzhen and Beijing symbols remain eligible for cached results', async t => {
  for (const [code, symbol] of [
    ['600000', 'sh600000'], ['688001', 'sh688001'],
    ['000001', 'sz000001'], ['300750', 'sz300750'],
    ['830799', 'bj830799'], ['920001', 'bj920001'],
  ]) {
    const h = harness({ latest: async () => current(code, { symbol }) });
    t.after(() => h.session.destroy());
    await h.session.select(code);
    assert.equal(h.session.snapshot().current?.symbol, symbol);
    assert.equal(h.requests.length, 0);
  }
});
