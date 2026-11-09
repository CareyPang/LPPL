'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { create: createSession } = require('../app/stock-session.js');

const NOW = Date.parse('2026-11-07T08:00:00Z');
const SHA = 'a'.repeat(40);
const JOBS = { sh000001: '11111111-1111-4111-8111-111111111111', sh600519: '22222222-2222-4222-8222-222222222222' };
const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
const result = (code, extra = {}) => ({ symbol: code, asof: '2026-11-06',
  model_version: 'research-preview', source_sha: SHA, generated_at: '2026-11-07T07:00:00Z', ...extra });
const market = code => ({ code, symbol: code, asof: '2026-11-06', expected_source_sha: SHA,
  price: [{ date: '2026-11-06', open: 10, high: 12, low: 9, close: 11, volume: 123 }] });

function transport(handler, base = 'https://preview.example/api/preview') {
  const calls = [];
  const root = { location: { href: 'https://preview.example/stock.html', origin: 'https://preview.example' }, LPPL_QUERY_API: base };
  const context = vm.createContext({ window: root, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    fetch: async (input, options = {}) => {
      const url = new URL(input, root.location.href);
      const call = { url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null };
      calls.push(call);
      const value = await handler(call);
      return value === null ? { ok: false, status: 404, json: async () => ({}) }
        : { ok: true, status: 200, json: async () => value };
    } });
  for (const name of ['lppl-data.js', 'stock-preview-api.js'])
    vm.runInContext(fs.readFileSync(require.resolve('../app/' + name), 'utf8'), context);
  return { root, calls, createApi: () => root.StockPreviewApi.create(root.LPPL.stock) };
}
function session(api, saved = []) {
  const values = new Map([['lppl.stock.jobs.v1', JSON.stringify(saved)]]), events = [], timers = new Map();
  let id = 0;
  const options = { api, now: () => NOW, pollMs: 10,
    storage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) },
    setTimeout(fn) { const key = ++id; timers.set(key, fn); return key; }, clearTimeout(key) { timers.delete(key); },
    onChange(value) { events.push(structuredClone(value)); } };
  return { value: createSession(options), values, timers, events, options,
    async poll() { const item = timers.entries().next().value; assert.ok(item); timers.delete(item[0]); await item[1](); await tick(); } };
}
function server(call, extra = {}) {
  assert.equal(call.url.origin, 'https://preview.example');
  assert.match(call.url.pathname, /^\/api\/preview\//);
  const raw = call.body?.code || call.url.searchParams.get('code');
  assert.ok(['000001', '600519'].includes(raw), 'only the isolated route transports six digit codes');
  const code = 'sh' + raw;
  switch (call.url.pathname.split('/').at(-1)) {
    case 'market': return market(code);
    case 'result': return result(code, extra);
    case 'query': return { job_id: JOBS[code], source_sha: SHA, requested_at: new Date(NOW).toISOString() };
    case 'status': return { job_id: JOBS[code], status: 'queued', current_ready: false };
    default: throw Error('Unexpected route');
  }
}

test('preview identity is pinned to the same-origin isolated route; bare 000001 never means the index', async () => {
  const h = transport(server), api = h.createApi();
  assert.equal(api.resolveCode('上证指数'), 'sh000001');
  assert.equal(api.resolveCode('贵州茅台'), 'sh600519');
  assert.equal(api.resolveCode('600519'), 'sh600519');
  assert.throws(() => api.resolveCode('000001'), /平安银行/);
  assert.throws(() => api.resolveCode('sz000001'), /本次真实预览支持/);
  assert.equal((await api.market('sh000001')).symbol, 'sh000001');
  assert.equal(h.calls[0].url.searchParams.get('code'), '000001');
  for (const base of ['https://worker.example/api/preview', 'https://preview.example/api',
    'https://lppl-stock-query.careypang.workers.dev']) assert.throws(() => transport(server, base).createApi(), /隔离接口/);
});

test('the real old adapter carries canonical index and stock results through the session without leaking static history', async t => {
  const h = transport(server), s = session(h.createApi()); t.after(() => s.value.destroy());
  await s.value.select('sh000001');
  assert.equal(s.value.snapshot().market.code, 'sh000001');
  assert.equal(s.value.snapshot().current.symbol, 'sh000001');
  await s.value.select('sh600519');
  assert.equal(s.value.snapshot().market.code, 'sh600519');
  assert.equal(s.value.snapshot().current.symbol, 'sh600519');
  await s.value.select('sh000001');
  assert.equal(s.value.snapshot().current.symbol, 'sh000001');
  assert.ok(h.calls.every(call => call.url.pathname.startsWith('/api/preview/')));
  assert.ok(h.calls.every(call => call.url.searchParams.get('kind') !== 'history'));
  assert.ok(h.calls.every(call => call.method !== 'POST'), 'fresh cache does not recompute or launch history');
  assert.throws(() => s.value.select('000001'), /资产代码/);
});

test('wrong-asset caches and delayed index responses never populate a selected stock', async t => {
  const waiting = deferred(); let deferredOnce = true, badCache = false;
  const h = transport(call => {
    if (call.url.pathname.endsWith('/result') && call.url.searchParams.get('code') === '000001') {
      if (badCache) return result('sz000001');
      if (deferredOnce) { deferredOnce = false; return waiting.promise; }
    }
    return server(call);
  });
  const s = session(h.createApi()); t.after(() => s.value.destroy());
  const selectIndex = s.value.select('sh000001'); await tick();
  await s.value.select('sh600519');
  waiting.resolve(result('sh000001')); await selectIndex;
  assert.equal(s.value.snapshot().code, 'sh600519');
  assert.equal(s.value.snapshot().current.symbol, 'sh600519');
  badCache = true;
  const fresh = session(h.createApi()); t.after(() => fresh.value.destroy());
  await fresh.value.select('sh000001'); await tick();
  assert.equal(fresh.value.snapshot().current, null, 'Ping An Bank cannot stand in for the Shanghai index');
  assert.ok(fresh.events.every(event => !event.current || event.current.symbol === event.code));
  assert.equal(h.calls.filter(call => call.method === 'POST').length, 1, 'missing valid current data triggers only current analysis');
  assert.deepEqual(h.calls.find(call => call.method === 'POST').body,
    { code: '000001', mode: 'current', history_weeks: 0 });
});

test('refresh restores the canonical current job and verifies symbol, job and source before accepting its result', async t => {
  let ready = false, mismatch = 'symbol';
  const h = transport(call => {
    if (call.url.pathname.endsWith('/status')) return { job_id: JOBS.sh000001, status: ready ? 'completed' : 'queued',
      current_ready: ready, conclusion: ready ? 'success' : null };
    if (call.url.pathname.endsWith('/result')) {
      if (!call.url.searchParams.get('job_id')) return null;
      return result(mismatch === 'symbol' ? 'sz000001' : 'sh000001',
        { job_id: mismatch === 'job' ? JOBS.sh600519 : JOBS.sh000001,
          source_sha: mismatch === 'source' ? 'b'.repeat(40) : SHA });
    }
    return server(call);
  });
  const saved = [{ code: 'sh000001', mode: 'current', job_id: JOBS.sh000001, source_sha: SHA,
    requested_at: new Date(NOW - 60000).toISOString() }];
  const s = session(h.createApi(), saved); t.after(() => s.value.destroy());
  await s.value.select('sh000001'); await tick();
  assert.equal(h.calls.filter(call => call.method === 'POST').length, 0, 'reload resumes instead of submitting a duplicate job');
  ready = true; await s.poll();
  assert.equal(s.value.snapshot().current, null);
  assert.equal(s.value.snapshot().currentStatus, 'reconnecting');
  mismatch = 'job'; await s.poll();
  assert.equal(s.value.snapshot().current, null);
  mismatch = 'source'; await s.poll();
  assert.equal(s.value.snapshot().current, null);
  mismatch = null; await s.poll();
  assert.equal(s.value.snapshot().current.symbol, 'sh000001');
  assert.equal(s.value.snapshot().current.job_id, JOBS.sh000001);
  assert.equal(s.value.snapshot().currentStatus, 'ready');
  assert.deepEqual(JSON.parse(s.values.get('lppl.stock.jobs.v1')), []);
});

test('preview does not load, calculate or resume unsupported historical jobs', async t => {
  const h = transport(server), api = h.createApi();
  const s = session(api, [{ code: 'sh000001', mode: 'history', job_id: JOBS.sh000001, source_sha: SHA,
    requested_at: new Date(NOW - 60000).toISOString() }]);
  t.after(() => s.value.destroy());
  await s.value.select('sh000001'); await tick();
  assert.equal(s.value.snapshot().history, null);
  assert.equal(h.calls.some(call => call.url.pathname.endsWith('/status')), false);
  assert.equal(s.value.snapshot().tasks.some(job => job.mode === 'history'), false);
  assert.equal(await api.history('sh000001'), null);
  assert.equal(await api.remote('sh000001', 'history'), null);
  await assert.rejects(api.request('sh000001', { mode: 'history' }), /历史回放尚未开放/);
  assert.equal(h.calls.some(call => call.method === 'POST'), false);
});
