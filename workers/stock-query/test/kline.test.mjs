import assert from 'node:assert/strict';
import { test } from 'node:test';
import worker, { QueryBudget, klineCacheTtl, obvDivergence } from '../src/index.js';

const ORIGIN = 'https://careypang.github.io';

function environment() {
  const values = new Map();
  const storage = { get: async key => values.get(key), put: async (key, value) => values.set(key, value) };
  const budget = new QueryBudget({ storage }, {});
  return { QUERY_BUDGET: { idFromName: name => name, get: () => budget } };
}

function request(path, method = 'GET') {
  return new Request(`https://worker.test${path}`, {
    method,
    headers: { Origin: ORIGIN },
  });
}

async function withFetch(fetcher, callback) {
  const previous = globalThis.fetch;
  globalThis.fetch = fetcher;
  try { await callback(); }
  finally { globalThis.fetch = previous; }
}

function sinaBars(count = 16) {
  return Array.from({ length: count }, (_unused, index) => {
    const time = new Date(Date.UTC(2026, 10, 19, 2, index * 30)).toISOString().slice(0, 19).replace('T', ' ');
    const close = 10 + index / 100;
    return {
      day: time,
      open: String(close - 0.01),
      high: String(close + 0.1),
      low: String(close - 0.1),
      close: String(close),
      volume: '100',
    };
  });
}

function divergenceBars(type) {
  const bars = Array.from({ length: 27 }, (_unused, index) => ({
    t: String(index),
    o: 10,
    h: type === 'top' ? 12 - index * 0.05 : 12 + index * 0.05,
    l: type === 'bottom' ? 8 + index * 0.05 : 8 - index * 0.05,
    c: 10,
    v: 100,
  }));
  if (type === 'top') {
    bars[6] = { ...bars[6], h: 18, c: 11 };
    bars[7] = { ...bars[7], c: 9 };
    bars[8] = { ...bars[8], c: 8 };
    bars[16] = { ...bars[16], h: 19, c: 9 };
  } else {
    bars[6] = { ...bars[6], l: 2, c: 9 };
    bars[7] = { ...bars[7], c: 8 };
    bars[8] = { ...bars[8], c: 9 };
    bars[15] = { ...bars[15], c: 8 };
    bars[16] = { ...bars[16], l: 1, c: 9 };
  }
  return bars;
}

function memoryCache() {
  const entries = new Map();
  return {
    async match(key) { return entries.get(String(key.url))?.clone(); },
    async put(key, response) { entries.set(String(key.url), response.clone()); },
  };
}

test('OBV divergence detects price-only pivot highs and lows against OBV', () => {
  const top = obvDivergence(divergenceBars('top'));
  assert.deepEqual(top.divergences.map(({ type, p1, p2, confirmed_at }) =>
    ({ type, p1, p2, confirmed_at })), [
    { type: 'top', p1: '6', p2: '16', confirmed_at: '21' },
  ]);
  assert.ok(top.bars[6].obv > top.bars[16].obv);

  const bottom = obvDivergence(divergenceBars('bottom'));
  assert.deepEqual(bottom.divergences.map(({ type, p1, p2, confirmed_at }) =>
    ({ type, p1, p2, confirmed_at })), [
    { type: 'bottom', p1: '6', p2: '16', confirmed_at: '21' },
  ]);
  assert.ok(bottom.bars[16].obv > bottom.bars[6].obv);
});

test('OBV divergence does not confirm pivots in the last five bars or equal-OBV highs', () => {
  const unconfirmed = divergenceBars('top').slice(0, 17);
  unconfirmed[12] = { ...unconfirmed[12], h: 20 };
  assert.deepEqual(obvDivergence(unconfirmed).divergences, []);

  const equalObv = divergenceBars('top');
  equalObv[8] = { ...equalObv[8], c: 10 };
  equalObv[16] = { ...equalObv[16], c: 10 };
  assert.deepEqual(obvDivergence(equalObv).divergences, []);
});

test('an in-progress minute bar retains its price but cannot confirm an OBV divergence', async (t) => {
  t.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-11-19T06:45:00Z') });
  const rows = divergenceBars('top').slice(0, 22).map((bar, index) => ({
    day: new Date(Date.UTC(2026, 10, 19, 15, (index - 21) * 30)).toISOString().slice(0, 19).replace('T', ' '),
    open: bar.o, high: bar.h, low: bar.l, close: bar.c, volume: bar.v
  }));
  await withFetch(async () => Response.json(rows), async () => {
    const read = async () => (await worker.fetch(request('/kline?code=600519&period=30'), environment())).json();
    const during = await read();
    assert.equal(during.asof, '2026-11-19 15:00:00');
    assert.equal(during.fetched_at, '2026-11-19T06:45:00.000Z');
    assert.equal(during.last_bar_ended, false);
    assert.deepEqual(during.divergences, []);
    t.mock.timers.tick(15 * 60 * 1000);
    const after = await read();
    assert.equal(after.last_bar_ended, true);
    assert.equal(after.divergences[0].confirmed_at, after.asof);
  });
});

test('GET /kline reads one Sina symbol, computes OBV, and reports source and limits', async () => {
  const calls = [];
  await withFetch(async (url, init) => {
    calls.push({ url: new URL(String(url)), init });
    return Response.json(sinaBars());
  }, async () => {
    const response = await worker.fetch(request('/kline?code=600519&period=30'), environment());
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), ORIGIN);
    const maxAge = /^public, max-age=(\d+)$/.exec(response.headers.get('Cache-Control'));
    assert.ok(maxAge && Number(maxAge[1]) <= 600);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url.hostname, 'money.finance.sina.com.cn');
    assert.equal(calls[0].url.searchParams.get('symbol'), 'sh600519');
    assert.equal(calls[0].url.searchParams.get('scale'), '30');
    assert.equal(calls[0].url.searchParams.get('datalen'), '1023');
    assert.ok(calls[0].init.signal instanceof AbortSignal);
    const result = await response.json();
    assert.equal(result.schema, 'kline_obv.v1');
    assert.equal(result.source, 'sina');
    assert.equal(result.code, '600519');
    assert.equal(result.period, '30');
    assert.equal(result.bars.length, 16);
    assert.equal(result.bars[0].obv, 0);
    assert.equal(result.limits.n_bars, 16);
    assert.equal(result.limits.first, result.bars[0].t);
    assert.equal(result.limits.last, result.bars.at(-1).t);
    assert.equal(result.note, '历史形态描述，不是买卖信号');
  });
});

test('GET /kline falls back to Tencent when Sina fails', async () => {
  const calls = [];
  const rows = sinaBars().map((bar) =>
    `${bar.day.replace(/[- :]/g, '').slice(0, 12)},${bar.open},${bar.close},${bar.high},${bar.low},${bar.volume},0`);
  await withFetch(async (url) => {
    const parsed = new URL(String(url));
    calls.push(parsed);
    if (parsed.hostname === 'money.finance.sina.com.cn') return new Response('', { status: 503 });
    assert.equal(parsed.hostname, 'ifzq.gtimg.cn');
    assert.equal(parsed.searchParams.get('param'), 'sh600519,m60,,640');
    return Response.json({ code: 0, data: { sh600519: { m60: rows } } });
  }, async () => {
    const response = await worker.fetch(request('/kline?code=600519&period=60'), environment());
    assert.equal(response.status, 200);
    const result = await response.json();
    assert.equal(result.source, 'tencent');
    assert.equal(result.period, '60');
    assert.equal(result.bars.length, rows.length);
    assert.deepEqual(calls.map((item) => item.hostname), [
      'money.finance.sina.com.cn', 'ifzq.gtimg.cn',
    ]);
  });
});

test('GET /kline daily uses Tencent qfq bars and never asks for a market-wide list', async () => {
  let calledUrl;
  await withFetch(async (url) => {
    calledUrl = new URL(String(url));
    return Response.json({ data: { sh600519: { qfqday: [
      ['2026-11-17', '10', '10.5', '11', '9.5', '100'],
      ['2026-11-18', '10.5', '11', '11.5', '10', '200'],
    ] } } });
  }, async () => {
    const response = await worker.fetch(request('/kline?code=600519&period=d'), environment());
    assert.equal(response.status, 200);
    const result = await response.json();
    assert.equal(result.source, 'tencent_fqkline_qfq');
    assert.equal(result.bars.length, 2);
    assert.equal(result.bars[1].t, '2026-11-18');
    assert.equal(result.bars[1].c, 11);
    assert.match(calledUrl.searchParams.get('param'), /^sh600519,day,,,500,qfq$/);
  });
});

test('GET /kline reports specific source failures as KLINE_UNAVAILABLE', async () => {
  await withFetch(async (url) => String(url).includes('sina')
    ? new Response('private upstream body', { status: 503 })
    : new Response('private upstream body', { status: 429 }), async () => {
    const response = await worker.fetch(request('/kline?code=600519&period=30'), environment());
    assert.equal(response.status, 502);
    const result = await response.json();
    assert.equal(result.error_code, 'KLINE_UNAVAILABLE');
    assert.equal(result.error, 'Sina: http_503; Tencent: http_429');
    assert.doesNotMatch(JSON.stringify(result), /private upstream body/);
  });
});

test('GET /kline cache hits never extend past the next Shanghai session or require upstream budget', async (t) => {
  t.mock.timers.enable({ apis: ['Date'], now: Date.parse('2026-11-16T04:59:20Z') });
  const previous = globalThis.caches;
  const previousHas = Object.hasOwn(globalThis, 'caches');
  const cache = memoryCache();
  const calls = [];
  globalThis.caches = { default: cache };
  try {
    await withFetch(async () => {
      calls.push(true);
      return Response.json(sinaBars());
    }, async () => {
      const first = await worker.fetch(request('/kline?code=600519&period=30'), environment());
      assert.equal(first.headers.get('Cache-Control'), 'public, max-age=40');
      t.mock.timers.tick(35000);
      const second = await worker.fetch(request('/kline?code=600519&period=30'), {});
      assert.equal(first.headers.get('X-Kline-Cache'), 'MISS');
      assert.equal(second.headers.get('X-Kline-Cache'), 'HIT');
      assert.equal(second.headers.get('Cache-Control'), 'public, max-age=5');
      assert.equal((await first.json()).source, 'sina');
      assert.equal((await second.json()).source, 'sina');
      assert.equal(calls.length, 1);
      t.mock.timers.tick(5000);
      const third = await worker.fetch(request('/kline?code=600519&period=30'), environment());
      assert.equal(third.headers.get('X-Kline-Cache'), 'MISS');
      assert.equal(third.headers.get('Cache-Control'), 'public, max-age=60');
      assert.equal(calls.length, 2);
    });
  } finally {
    if (previousHas) globalThis.caches = previous;
    else delete globalThis.caches;
  }
});

test('GET /kline validates method, one six-digit code, and supported period', async () => {
  assert.equal((await worker.fetch(request('/kline?code=600519&period=30', 'POST'), {})).status, 405);
  assert.equal((await worker.fetch(request('/kline?code=600519,600520&period=30'), {})).status, 400);
  assert.equal((await worker.fetch(request('/kline?code=600519&period=30&period=60'), {})).status, 400);
  assert.equal((await worker.fetch(request('/kline?code=600519&period=w'), {})).status, 400);
});

test('kline cache is short during mainland trading sessions and longer otherwise', () => {
  assert.equal(klineCacheTtl(new Date('2026-11-16T01:30:00Z')), 60);
  assert.equal(klineCacheTtl(new Date('2026-11-16T03:00:00Z')), 60);
  assert.equal(klineCacheTtl(new Date('2026-11-16T04:00:00Z')), 600);
  assert.equal(klineCacheTtl(new Date('2026-11-15T02:00:00Z')), 600);
  assert.equal(klineCacheTtl(new Date('2026-11-16T01:29:20Z')), 40);
  assert.equal(klineCacheTtl(new Date('2026-11-16T04:59:55Z')), 5);
  assert.equal(klineCacheTtl(new Date('2026-11-16T04:59:59.900Z')), 0);
});

test('uncached kline reads require a functioning budget and stop upstream work at the per-IP limit', async () => {
  const path = '/kline?code=600519&period=60';
  const env = environment();
  let calls = 0;
  await withFetch(async () => { calls += 1; return Response.json(sinaBars()); }, async () => {
    assert.equal((await worker.fetch(request(path), {})).status, 503);
    assert.equal(calls, 0);
    for (let i = 0; i < 30; i++) assert.equal((await worker.fetch(request(path), env)).status, 200);
    const limited = await worker.fetch(request(path), env);
    assert.equal(limited.status, 429);
    assert.equal(limited.headers.get('Retry-After'), '60');
    assert.equal(calls, 30);
  });
});

test('Sina timeout leaves time for Tencent before the chart deadline', async (t) => {
  const rows = [['202611191130', '10', '10.5', '11', '9.5', '100']];
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let beginSina, beginTencent;
  const sinaStarted = new Promise(resolve => { beginSina = resolve; });
  const tencentStarted = new Promise(resolve => { beginTencent = resolve; });
  await withFetch(async (url, init) => {
    if (String(url).includes('sina')) {
      beginSina();
      return new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(new Error('timeout'))));
    }
    beginTencent();
    return new Promise((resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new Error('timeout')));
      setTimeout(() => resolve(Response.json({ data: { sh600519: { m60: rows } } })), 4500);
    });
  }, async () => {
    const pending = worker.fetch(request('/kline?code=600519&period=60'), environment());
    await sinaStarted;
    t.mock.timers.tick(5000);
    await tencentStarted;
    t.mock.timers.tick(4500);
    assert.equal((await (await pending).json()).source, 'tencent');
  });
});
