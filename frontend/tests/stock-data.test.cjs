'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app', 'lppl-data.js'), 'utf8');
const JOB = '11111111-1111-4111-8111-111111111111';

function response(value, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => value };
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function settle() {
  for (let i = 0; i < 15; i++) await Promise.resolve();
}

function setup(handler = async () => response({ ok: true }), marketContext = null) {
  const requests = [], timers = new Map();
  let now = 0, nextTimer = 0;
  class ClockDate extends Date { static now() { return now; } }
  const window = { LPPL_DATA_BASE: '/snapshots/', LPPL_QUERY_API: 'https://query.example.test/' };
  if (marketContext) window.LPPLMarketContext = marketContext;
  const context = vm.createContext({
    window, Date: ClockDate, AbortController,
    fetch: (url, options) => { requests.push({ url, options }); return handler(url, options); },
    setTimeout: (fn, delay) => { const id = ++nextTimer; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(source, context, { filename: 'lppl-data.js' });
  return {
    api: window.LPPL, requests, timers,
    advance(milliseconds) { now += milliseconds; },
    expire() { for (const [id, timer] of [...timers]) { timers.delete(id); timer.fn(); } },
  };
}

test('market-context wrapper is opt-in and forwards Worker configuration', () => {
  let received = null;
  const h = setup(undefined, { createMarketContextClient: options => { received = options; return { start() {}, stop() {} }; } });
  const client = h.api.marketContext({ enabled: true, baseUrl: 'https://context.example', intervalMs: 5000 });
  assert.equal(typeof client.start, 'function');
  assert.equal(received.enabled, true);
  assert.equal(received.baseUrl, 'https://context.example');
  assert.equal(received.intervalMs, 5000);
});

test('market and saved results use the configured unified adapter endpoints', async () => {
  const h = setup(async url => response({ path: url }));
  await h.api.stock.market('000001');
  await h.api.stock.latest('000001');
  await h.api.stock.history('000001');
  assert.deepEqual(h.requests.map(r => r.url), [
    'https://query.example.test/market?code=000001',
    '/snapshots/stock/000001.json',
    '/snapshots/stock/000001_history.json',
  ]);
  assert.ok(h.requests.every(r => r.options.signal instanceof AbortSignal));
});

test('default dispatch asks only for current analysis', async () => {
  const h = setup();
  await h.api.stock.request('000001');
  const request = h.requests[0];
  assert.equal(request.url, 'https://query.example.test/query');
  assert.equal(request.options.method, 'POST');
  assert.deepEqual(JSON.parse(request.options.body), { code: '000001', mode: 'current', history_weeks: 0 });
});

test('history dispatch has an explicit mode and independently selectable history length', async () => {
  const h = setup();
  await h.api.stock.request('000001', { mode: 'history' });
  await h.api.stock.request('600000', { mode: 'history', historyWeeks: 52 });
  assert.deepEqual(h.requests.map(r => JSON.parse(r.options.body)), [
    { code: '000001', mode: 'history', history_weeks: 104 },
    { code: '600000', mode: 'history', history_weeks: 52 },
  ]);
});

test('status supports a unique job id and the existing code/since interface', async () => {
  const h = setup();
  await h.api.stock.status('000001', { jobId: JOB });
  await h.api.stock.status('000001', '2026-11-06T08:00:00+00:00');
  await h.api.stock.status('000001');
  const urls = h.requests.map(r => new URL(r.url));
  assert.equal(urls[0].searchParams.get('job_id'), JOB);
  assert.equal(urls[0].searchParams.has('since'), false);
  assert.equal(urls[1].searchParams.get('since'), '2026-11-06T08:00:00+00:00');
  assert.equal(urls[1].searchParams.has('job_id'), false);
  assert.equal(urls[2].searchParams.has('since'), false);
});

test('job-scoped result reads preserve identity and always revalidate', async () => {
  const h = setup();
  await h.api.stock.remote('000001', 'history', { jobId: JOB });
  await h.api.stock.remote('000001', 'history', { jobId: JOB });
  assert.equal(h.requests.length, 2);
  const url = new URL(h.requests[0].url);
  assert.equal(url.searchParams.get('code'), '000001');
  assert.equal(url.searchParams.get('kind'), 'history');
  assert.equal(url.searchParams.get('job_id'), JOB);
  assert.equal(h.requests[0].options.cache, 'no-cache');
});

test('static result cache refreshes after 30 seconds instead of remaining stale for the page lifetime', async () => {
  let version = 0;
  const h = setup(async () => response({ version: ++version }));
  const first = await h.api.stock.latest('000001');
  h.advance(29999);
  const cached = await h.api.stock.latest('000001');
  assert.equal(first.version, 1);
  assert.equal(cached.version, 1);
  assert.equal(h.requests.length, 1);
  h.advance(1);
  const updated = await h.api.stock.latest('000001');
  assert.equal(updated.version, 2);
  assert.equal(h.requests.length, 2);
});

test('concurrent reads share a pending static request', async () => {
  const data = deferred();
  const h = setup(() => data.promise);
  const first = h.api.stock.latest('000001');
  const second = h.api.stock.latest('000001');
  assert.equal(h.requests.length, 1);
  data.resolve(response({ version: 1 }));
  assert.equal((await first).version, 1);
  assert.equal((await second).version, 1);
});

test('a failed static request is removed from cache so a retry can succeed', async () => {
  let count = 0;
  const h = setup(async () => ++count === 1 ? response({}, 503) : response({ version: 2 }));
  assert.equal(await h.api.stock.latest('000001'), null);
  assert.equal((await h.api.stock.latest('000001')).version, 2);
  assert.equal(h.requests.length, 2);
});

test('missing remote result returns null but other server failures are not silently treated as absent', async () => {
  const h = setup(async url => response({}, url.includes('kind=history') ? 404 : 502));
  assert.equal(await h.api.stock.remote('000001', 'history'), null);
  await assert.rejects(h.api.stock.remote('000001'), /数据服务暂时不可用/);
});

test('invalid stock codes and result kinds do not create network requests', async () => {
  const h = setup();
  assert.throws(() => h.api.stock.market('../000001'), /六位|6 位/);
  await assert.rejects(h.api.stock.remote('000001', 'secret'), /类型无效/);
  assert.equal(h.requests.length, 0);
});

test('query failures give usable messages without returning arbitrary server error text', async () => {
  const h = setup(async () => response({ error: 'PRIVATE SERVER DETAIL' }, 429));
  await assert.rejects(h.api.stock.request('000001'), error => {
    assert.match(error.message, /查询较多/);
    assert.doesNotMatch(error.message, /PRIVATE/);
    return true;
  });
});

test('known missing-job errors preserve only safe code and status for recovery', async () => {
  const h = setup(async () => response({ error_code: 'JOB_NOT_FOUND', error: 'PRIVATE SERVER DETAIL' }, 404));
  await assert.rejects(h.api.stock.status('000001', { jobId: JOB }), error => {
    assert.equal(error.status, 404);
    assert.equal(error.code, 'JOB_NOT_FOUND');
    assert.doesNotMatch(error.message, /PRIVATE/);
    return true;
  });
  const unknown = setup(async () => response({ error_code: 'PRIVATE_SECRET', error: 'PRIVATE SERVER DETAIL' }, 502));
  await assert.rejects(unknown.api.stock.status('000001', { jobId: JOB }), error => {
    assert.equal(error.status, 502); assert.equal(error.code, undefined);
    assert.doesNotMatch(error.message, /PRIVATE/);
    return true;
  });
});

for (const [name, invoke, deadline] of [
  ['query', api => api.stock.request('000001'), 60000],
  ['job status', api => api.stock.status('000001', { jobId: JOB }), 45000],
  ['legacy status', api => api.stock.status('000001'), 45000],
  ['market', api => api.stock.market('000001'), 12000],
  ['result', api => api.stock.remote('000001'), 12000],
]) {
  test(`${name} uses its own deadline without mistaking timeout for task failure`, async () => {
    const h = setup(() => new Promise(() => {}));
    const pending = invoke(h.api);
    assert.deepEqual([...h.timers.values()].map(timer => timer.delay), [deadline]);
    const rejected = assert.rejects(pending, error => {
      assert.equal(error.code, 'REQUEST_TIMEOUT');
      assert.match(error.message, /尚未确认/);
      assert.doesNotMatch(error.message, /已取消|已失败|任务失败/);
      return true;
    });
    h.expire();
    await rejected;
    assert.equal(h.timers.size, 0);
  });
}

test('a request stalled before headers times out and aborts the network request', async () => {
  let signal;
  const h = setup((_url, options) => {
    signal = options.signal;
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => {
      const error = new Error('aborted'); error.name = 'AbortError'; reject(error);
    }, { once: true }));
  });
  const result = h.api.stock.market('000001');
  h.expire();
  await assert.rejects(result, /超时/);
  assert.equal(signal.aborted, true);
  assert.equal(h.timers.size, 0);
});

test('a JSON body stalled after headers is bounded by the same timeout', async () => {
  const body = deferred();
  let signal;
  const h = setup(async (_url, options) => {
    signal = options.signal;
    return { ok: true, status: 200, json: () => body.promise };
  });
  let outcome;
  const result = h.api.stock.market('000001').then(
    value => { outcome = { value }; }, error => { outcome = { error }; },
  );
  await settle();
  h.expire();
  await settle();
  try {
    assert.ok(outcome?.error, 'Headers alone must not disable the JSON-read deadline');
    assert.match(outcome.error.message, /超时/);
    assert.equal(signal.aborted, true);
  } finally {
    body.resolve({ late: true });
    await result;
  }
});

test('successful JSON reads clean up their timeout', async () => {
  const h = setup();
  await h.api.stock.market('000001');
  assert.equal(h.timers.size, 0);
});
