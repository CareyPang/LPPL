import assert from 'node:assert/strict';
import { test } from 'node:test';
import worker from '../src/index.js';

const ORIGIN = 'https://careypang.github.io';
const TOKEN = 'test-secret';

class MemoryKV {
  values = new Map();
  puts = [];

  async get(key) {
    return this.values.get(key) ?? null;
  }

  async put(key, value, options) {
    this.values.set(key, String(value));
    this.puts.push({ key, value: String(value), options });
  }

  async delete(key) {
    this.values.delete(key);
  }
}

function makeEnv(extra = {}) {
  return { GH_TOKEN: TOKEN, ...extra };
}

function makeRequest(path, { method = 'GET', origin = ORIGIN, headers = {}, body } = {}) {
  const requestHeaders = new Headers(headers);
  if (origin !== null) requestHeaders.set('Origin', origin);
  return new Request(`https://worker.test${path}`, { method, headers: requestHeaders, body });
}

async function withFetchMock(mock, callback) {
  const original = globalThis.fetch;
  globalThis.fetch = mock;
  try {
    await callback();
  } finally {
    globalThis.fetch = original;
  }
}

test('CORS allows the configured origin and answers preflight', async () => {
  const response = await worker.fetch(
    makeRequest('/query', { method: 'OPTIONS', headers: { 'Access-Control-Request-Method': 'POST' } }),
    makeEnv(),
  );
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), ORIGIN);
  assert.match(response.headers.get('Access-Control-Allow-Methods'), /POST/);
  assert.equal(response.headers.get('Vary'), 'Origin');
});

test('CORS rejects another origin', async () => {
  const response = await worker.fetch(makeRequest('/unknown', { origin: 'https://evil.example' }), makeEnv());
  assert.equal(response.status, 403);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), null);
});

test('invalid codes are rejected before dispatch', async () => {
  await withFetchMock(async () => {
    assert.fail('fetch must not be called');
  }, async () => {
    const response = await worker.fetch(
      makeRequest('/query', { method: 'POST', body: JSON.stringify({ code: '123456' }) }),
      makeEnv(),
    );
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { error: 'Invalid A-share code' });
  });
});

test('dispatches with the fixed query parameters and reports disabled rate limiting', async () => {
  await withFetchMock(async (url, init) => {
    assert.equal(url, 'https://api.github.com/repos/CareyPang/LPPL/dispatches');
    assert.equal(init.method, 'POST');
    assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
    assert.equal(init.headers['User-Agent'], 'lppl-stock-query-worker');
    assert.deepEqual(JSON.parse(init.body), {
      event_type: 'stock_query',
      client_payload: { code: '600519', variant: 'stk_lite', history_weeks: '104' },
    });
    return new Response(null, { status: 204 });
  }, async () => {
    const response = await worker.fetch(
      makeRequest('/query', { method: 'POST', body: JSON.stringify({ code: '600519' }) }),
      makeEnv(),
    );
    assert.equal(response.status, 202);
    const body = await response.json();
    assert.deepEqual(body, { queued: true, since: body.since, ratelimit: 'disabled' });
    assert.ok(Number.isFinite(Date.parse(body.since)));
  });
});

test('a repeated code is deduplicated for 15 minutes', async () => {
  const kv = new MemoryKV();
  let dispatches = 0;
  await withFetchMock(async () => {
    dispatches += 1;
    return new Response(null, { status: 204 });
  }, async () => {
    const makeQuery = () => worker.fetch(
      makeRequest('/query', {
        method: 'POST',
        headers: { 'CF-Connecting-IP': '203.0.113.1' },
        body: JSON.stringify({ code: '600519' }),
      }),
      makeEnv({ RL: kv }),
    );
    const first = await makeQuery();
    const second = await makeQuery();
    assert.equal(first.status, 202);
    const firstBody = await first.json();
    assert.deepEqual(firstBody, {
      queued: true,
      since: firstBody.since,
      ratelimit: 'enabled',
    });
    assert.equal(second.status, 202);
    const secondBody = await second.json();
    assert.deepEqual(secondBody, {
      queued: true,
      deduped: true,
      since: firstBody.since,
      ratelimit: 'enabled',
    });
    assert.equal(kv.values.get('code:600519'), firstBody.since);
    assert.equal(dispatches, 1);
    assert.ok(kv.puts.some(({ key, options }) => key === 'code:600519' && options.expirationTtl === 900));
  });
});

test('per-IP limit allows five queries in ten minutes and rejects the sixth', async () => {
  const kv = new MemoryKV();
  let dispatches = 0;
  await withFetchMock(async () => {
    dispatches += 1;
    return new Response(null, { status: 204 });
  }, async () => {
    const statuses = [];
    for (const code of ['600001', '600002', '600003', '600004', '600005', '600006']) {
      const response = await worker.fetch(
        makeRequest('/query', {
          method: 'POST',
          headers: { 'CF-Connecting-IP': '203.0.113.2' },
          body: JSON.stringify({ code }),
        }),
        makeEnv({ RL: kv }),
      );
      statuses.push(response.status);
    }
    assert.deepEqual(statuses, [202, 202, 202, 202, 202, 429]);
    assert.equal(dispatches, 5);
    assert.ok(kv.puts.some(({ key, options }) => key === 'ip:203.0.113.2' && options.expirationTtl === 600));
  });
});

test('GitHub dispatch errors return a sanitized 502 and release the dedupe key', async () => {
  const kv = new MemoryKV();
  await withFetchMock(async () => new Response('private upstream details', { status: 403 }), async () => {
    const response = await worker.fetch(
      makeRequest('/query', {
        method: 'POST',
        headers: { 'CF-Connecting-IP': '203.0.113.3' },
        body: JSON.stringify({ code: '600519' }),
      }),
      makeEnv({ RL: kv }),
    );
    assert.equal(response.status, 502);
    const body = await response.text();
    assert.doesNotMatch(body, /private upstream details|test-secret/);
    assert.equal(kv.values.has('code:600519'), false);
  });
});

test('status returns the latest run with an exact display-title match', async () => {
  await withFetchMock(async (url, init) => {
    assert.equal(
      url,
      'https://api.github.com/repos/CareyPang/LPPL/actions/workflows/stock_query.yml/runs?per_page=100',
    );
    assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
    return Response.json({
      workflow_runs: [
        { display_title: 'stock_query 600519', status: 'queued', created_at: '2026-11-01T01:00:00Z', html_url: 'old' },
        { display_title: 'stock_query 600519', status: 'completed', conclusion: 'success', created_at: '2026-11-02T01:00:00Z', updated_at: '2026-11-02T02:00:00Z', html_url: 'latest' },
        { display_title: 'stock_query 000001', status: 'completed', conclusion: 'success', created_at: '2026-11-03T01:00:00Z', html_url: 'other' },
      ],
    });
  }, async () => {
    const response = await worker.fetch(makeRequest('/status?code=600519'), makeEnv());
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      status: 'completed',
      conclusion: 'success',
      created_at: '2026-11-02T01:00:00Z',
      updated_at: '2026-11-02T02:00:00Z',
      run_url: 'latest',
    });
  });
});

test('status returns none when no matching run exists', async () => {
  await withFetchMock(async () => Response.json({ workflow_runs: [] }), async () => {
    const response = await worker.fetch(makeRequest('/status?code=600519'), makeEnv());
    assert.deepEqual(await response.json(), { status: 'none' });
  });
});

test('status filters old runs with since and reports pending when none remain', async () => {
  const since = '2026-11-02T12:00:00.000Z';
  await withFetchMock(async (url) => {
    assert.equal(
      url,
      'https://api.github.com/repos/CareyPang/LPPL/actions/workflows/stock_query.yml/runs?per_page=100',
    );
    return Response.json({
      workflow_runs: [
        {
          display_title: 'stock_query 600519',
          status: 'completed',
          conclusion: 'success',
          created_at: '2026-11-02T11:58:59.000Z',
          html_url: 'old-run',
        },
      ],
    });
  }, async () => {
    const response = await worker.fetch(
      makeRequest(`/status?code=600519&since=${encodeURIComponent(since)}`),
      makeEnv(),
    );
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { status: 'pending' });
  });
});

test('status rejects a non-ISO since value before making a GitHub request', async () => {
  await withFetchMock(async () => {
    assert.fail('fetch must not be called');
  }, async () => {
    const response = await worker.fetch(
      makeRequest('/status?code=600519&since=not-a-date'),
      makeEnv(),
    );
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { error: 'Invalid since timestamp' });
  });
});

test('result returns the raw JSON and sets its cache lifetime', async () => {
  const raw = '{"code":"600519"}\n';
  await withFetchMock(async (url, init) => {
    assert.equal(
      url,
      'https://api.github.com/repos/CareyPang/LPPL/contents/stock/600519.json?ref=stock-results',
    );
    assert.equal(init.headers.Accept, 'application/vnd.github.raw');
    return new Response(raw, { status: 200 });
  }, async () => {
    const response = await worker.fetch(makeRequest('/result?code=600519&kind=latest'), makeEnv());
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Cache-Control'), 'max-age=30');
    assert.equal(await response.text(), raw);
  });
});

test('result preserves 404 and rejects unsupported kinds', async () => {
  let calls = 0;
  await withFetchMock(async () => {
    calls += 1;
    return new Response('{"message":"Not Found"}', { status: 404 });
  }, async () => {
    const missing = await worker.fetch(makeRequest('/result?code=600519&kind=latest'), makeEnv());
    assert.equal(missing.status, 404);
    assert.equal(missing.headers.get('Cache-Control'), 'max-age=30');
    const invalidKind = await worker.fetch(makeRequest('/result?code=600519&kind=other'), makeEnv());
    assert.equal(invalidKind.status, 400);
    assert.equal(calls, 1);
  });
});
