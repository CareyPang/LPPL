import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createPreviewWorker, normalizeTencent, unpackBundle, closedCutoff } from './preview-worker.mjs';

const SHA = 'a'.repeat(40), REF = 'od/stock-async-20261106';
const NOW = Date.parse('2026-11-09T09:00:00.000Z');
const ID = '12345678-1234-4123-8123-123456789012';
const encode = value => new TextEncoder().encode(value);
function database() {
  const sqlite = new DatabaseSync(':memory:');
  sqlite.exec(`CREATE TABLE preview_jobs(job_id TEXT PRIMARY KEY,symbol TEXT,requested_at TEXT,source_sha TEXT,status TEXT,run_id TEXT,result_json TEXT,error_code TEXT,day_key TEXT,UNIQUE(symbol,day_key,source_sha));
    CREATE TABLE preview_receipts(result_hash TEXT PRIMARY KEY,first_served_at TEXT NOT NULL);`);
  return { sqlite, prepare(sql) { return { bind(...args) { return {
    async first() { return sqlite.prepare(sql).get(...args) || null; },
    async run() { return { meta: { changes: Number(sqlite.prepare(sql).run(...args).changes) } }; },
  }; } }; } };
}
const environment = () => ({ DB: database(), PREVIEW_SOURCE_SHA: SHA, PREVIEW_REF: REF, PREVIEW_GITHUB_TOKEN: 'secret-test-token' });
function request(path, options = {}) { return new Request('https://preview.example/api/preview' + path, options); }
function query(code, extra = {}) { return request('/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, mode: 'current', history_weeks: 0, ...extra }) }); }
const object = async response => ({ status: response.status, body: await response.json() });
const observed = { date: '2026-11-06', open: 10, close: 12, high: 13, low: 9, volume: 200 };
function bundle(job) { return {
  market: { code: job.symbol, symbol: job.symbol, asof: observed.date, price: [observed], adjustment: 'none', model_adjustment: 'hfq' },
  result: { symbol: job.symbol, source_sha: job.source_sha, job_id: job.job_id, requested_at: job.requested_at,
    asof: observed.date, mode: 'current', evidence: 'research_candidate', model_computed: true,
    top: { window: { start: null, end: null, evidence: 'none' } } },
}; }
function checksum(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) { value ^= byte; for (let i = 0; i < 8; i++) value = (value >>> 1) ^ (0xedb88320 & -(value & 1)); }
  return (value ^ 0xffffffff) >>> 0;
}
function zip(value, { method = 0, descriptor = true, filename = 'bundle.json' } = {}) {
  const name = encode(filename), data = encode(JSON.stringify(value)), crc = checksum(data);
  const dataStart = 30 + name.length, directoryStart = dataStart + data.length + (descriptor ? 16 : 0);
  const directorySize = 46 + name.length, end = directoryStart + directorySize;
  const out = new Uint8Array(end + 22), view = new DataView(out.buffer);
  const w16 = (at, value) => view.setUint16(at, value, true), w32 = (at, value) => view.setUint32(at, value, true);
  w32(0, 0x04034b50); w16(4, 20); w16(6, descriptor ? 8 : 0); w16(8, method); w16(26, name.length);
  if (!descriptor) { w32(14, crc); w32(18, data.length); w32(22, data.length); }
  out.set(name, 30); out.set(data, dataStart);
  if (descriptor) { const d = dataStart + data.length; w32(d, 0x08074b50); w32(d + 4, crc); w32(d + 8, data.length); w32(d + 12, data.length); }
  w32(directoryStart, 0x02014b50); w16(directoryStart + 4, 20); w16(directoryStart + 6, 20); w16(directoryStart + 8, descriptor ? 8 : 0);
  w16(directoryStart + 10, method); w32(directoryStart + 16, crc); w32(directoryStart + 20, data.length); w32(directoryStart + 24, data.length);
  w16(directoryStart + 28, name.length); out.set(name, directoryStart + 46);
  w32(end, 0x06054b50); w16(end + 8, 1); w16(end + 10, 1); w32(end + 12, directorySize); w32(end + 16, directoryStart);
  return out;
}

test('closed chart bars remain unadjusted while declaring the separate HFQ fitting basis for stocks', () => {
  const rows = [['2026-11-06', '10', '12', '13', '9', '200'], ['2026-11-07', 10, 12, 13, 9, 300], ['2026-11-09', 10, 12, 13, 9, 400], ['2026-11-10', 10, 12, 13, 9, 500]];
  const beforeClose = new Date('2026-11-09T07:00:00Z');
  const stock = normalizeTencent({ data: { sh600519: { day: rows, hfqday: [['2026-11-06', 1000, 1200, 1300, 900, 200]] } } }, 'sh600519', beforeClose);
  assert.equal(stock.code, 'sh600519'); assert.equal(stock.adjustment, 'none'); assert.equal(stock.model_adjustment, 'hfq'); assert.equal(stock.price.length, 1);
  assert.equal(stock.price[0].close, 12, 'The chart must not show a 1200 HFQ price as the market quote');
  assert.equal(stock.asof, '2026-11-06'); assert.equal(stock.model_computed, false);
  assert.equal(closedCutoff(new Date('2026-11-09T07:30:00Z')), '2026-11-09');
  assert.throws(() => normalizeTencent({ data: { sh600519: { hfqday: rows, qfqday: rows } } }, 'sh600519', beforeClose), /MARKET_UNAVAILABLE/);
  const index = normalizeTencent({ data: { sh000001: { day: rows } } }, 'sh000001', beforeClose);
  assert.equal(index.adjustment, 'none'); assert.equal(index.model_adjustment, 'none');
});

test('SQLite reservations deduplicate parallel submissions and enforce two daily tasks across source changes', async () => {
  const env = environment(), dispatches = [];
  const worker = createPreviewWorker({ now: () => NOW, cryptoImpl: webcrypto, fetchImpl: async (url, init) => {
    assert.equal(url, 'https://api.github.com/repos/CareyPang/LPPL/actions/workflows/stock_query.yml/dispatches');
    dispatches.push(JSON.parse(init.body)); return new Response(null, { status: 204 });
  } });
  const results = await Promise.all([worker.fetch(query('000001', { source_sha: 'b'.repeat(40), ref: 'main', variant: 'stk_full' }), env), worker.fetch(query('sh000001'), env)]);
  const bodies = await Promise.all(results.map(value => value.json()));
  assert.equal(dispatches.length, 1); assert.equal(bodies[0].job_id, bodies[1].job_id);
  assert.equal(dispatches[0].ref, REF); assert.equal(dispatches[0].inputs.preview_source_sha, SHA);
  assert.equal(dispatches[0].inputs.code, 'sh000001'); assert.equal(dispatches[0].inputs.variant, 'stk_lite');
  assert.equal(dispatches[0].inputs.preview_only, 'true'); assert.equal(dispatches[0].inputs.history_weeks, '0');
  assert.equal((await worker.fetch(query('600519'), env)).status, 202);
  assert.equal(dispatches.length, 2);
  const exhausted = await object(await worker.fetch(query('000001'), { ...env, PREVIEW_SOURCE_SHA: 'b'.repeat(40) }));
  assert.equal(exhausted.status, 429); assert.equal(exhausted.body.error_code, 'DAILY_PREVIEW_LIMIT');
  assert.equal(dispatches.length, 2); assert.equal(env.DB.sqlite.prepare('SELECT count(*) AS n FROM preview_jobs').get().n, 2);
});

test('ambiguous dispatch retains one durable identity and never retries the external write', async () => {
  const env = environment(); let calls = 0;
  const worker = createPreviewWorker({ now: () => NOW, cryptoImpl: webcrypto, fetchImpl: async () => { calls++; throw Error('secret-test-token network body'); } });
  const initial = await (await worker.fetch(query('600519'), env)).json();
  const repeated = await (await worker.fetch(query('600519'), env)).json();
  assert.equal(initial.status, 'dispatch_unknown'); assert.equal(repeated.job_id, initial.job_id);
  assert.equal(repeated.deduped, true); assert.equal(calls, 1);
  assert.doesNotMatch(JSON.stringify(initial), /secret-test-token|network body/);
});

test('ZIP central directory supports data descriptors and rejects corrupt, compressed and unsafe entries', () => {
  const value = { market: {}, result: { identity: 'exact' } };
  assert.deepEqual(unpackBundle(zip(value)), value);
  assert.deepEqual(unpackBundle(zip(value, { descriptor: false })), value);
  assert.throws(() => unpackBundle(zip(value, { method: 8 })), /ARTIFACT_UNSUPPORTED_COMPRESSION/);
  assert.throws(() => unpackBundle(zip(value, { filename: '../bundle.json' })), /ARTIFACT_INVALID/);
  const damaged = zip(value); damaged[45] ^= 1;
  assert.throws(() => unpackBundle(damaged), /ARTIFACT_INVALID/);
  assert.throws(() => unpackBundle(zip(value).subarray(0, 20)), /ARTIFACT_INVALID/);
});

test('an actual official upload-artifact v4.6.2 level-0 archive decodes without a DEFLATE dependency', () => {
  // Generated locally by the official bundled createZipUploadStream module 69186
  // at ea165f8d65b6e75b540449e92b4886f43607fa02, with compressionLevel=0.
  // The action upload entry point was not executed. JSON payload is our test fixture.
  const actual = Buffer.from('UEsDBBQACAAAAH09Z10AAAAAAAAAAAAAAAALAAAAYnVuZGxlLmpzb257Im1hcmtldCI6eyJldmlkZW5jZSI6ImZpeHR1cmUifSwicmVzdWx0Ijp7InRlc3QiOnRydWV9fVBLBwiLY9pfOAAAADgAAABQSwECLQMUAAgAAAB9PWddi2PaXzgAAAA4AAAACwAAAAAAAAAAACAAtoEAAAAAYnVuZGxlLmpzb25QSwUGAAAAAAEAAQA5AAAAcQAAAAAA', 'base64');
  assert.equal(actual.readUInt16LE(6), 8, 'The official archive uses a data descriptor');
  assert.equal(actual.readUInt16LE(8), 0, 'Level 0 is ZIP STORE, not DEFLATE level 0');
  assert.deepEqual(unpackBundle(actual), { market: { evidence: 'fixture' }, result: { test: true } });
});

async function completedFixture({ wrongSHA = false, wrongBundle = false, wrongName = false, padding = null } = {}) {
  const env = environment(); let clock = NOW, calls = [], job;
  const worker = createPreviewWorker({ now: () => clock, cryptoImpl: { randomUUID: () => ID, subtle: webcrypto.subtle }, fetchImpl: async (url, init) => {
    calls.push({ url, init });
    if (url.endsWith('/dispatches')) return new Response(null, { status: 204 });
    if (url.includes('/runs?')) return Response.json({ workflow_runs: [{ id: 12, display_title: wrongName ? 'stock_query production' : 'preview ' + ID,
      event: 'workflow_dispatch', head_branch: REF, head_sha: wrongSHA ? 'b'.repeat(40) : SHA,
      created_at: new Date(NOW).toISOString(), status: 'completed', conclusion: 'success' }] });
    if (url.includes('/runs/12/artifacts')) return Response.json({ artifacts: [{ id: 45, name: 'preview-result-' + ID, expired: false, size_in_bytes: 1000, workflow_run: { id: 12, head_sha: SHA } }] });
    if (url.endsWith('/artifacts/45/zip')) return new Response(null, { status: 302, headers: { Location: 'https://preview.blob.core.windows.net/object?sig=private' } });
    if (url.startsWith('https://preview.blob.core.windows.net/')) {
      const value = bundle(job); if (wrongBundle) value.result.symbol = 'sh000001';
      if (padding !== null) value.result.padding = padding;
      return new Response(zip(value));
    }
    throw Error('unexpected URL');
  } });
  job = { ...(await (await worker.fetch(query('600519'), env)).json()), symbol: 'sh600519' };
  return { worker, env, job, calls, advance(ms) { clock += ms; } };
}

test('exact run and artifact identities produce immutable results with server-bound first-serving receipts', async () => {
  const f = await completedFixture();
  const status = await (await f.worker.fetch(request('/status?code=600519&job_id=' + ID), f.env)).json();
  assert.equal(status.current_ready, true); assert.equal(status.conclusion, 'success');
  assert.equal(status.history_ready, false); assert.equal(status.source_sha, SHA);
  const download = f.calls.find(call => call.url.startsWith('https://preview.blob.core.windows.net/'));
  assert.equal(download.init.headers, undefined, 'Do not forward GitHub credentials to signed artifact storage');
  const resultRequest = () => request('/result?code=sh600519&job_id=' + ID);
  const initial = await (await f.worker.fetch(resultRequest(), f.env)).json();
  assert.equal(initial.delivery_observation.first_observed_at, new Date(NOW).toISOString());
  assert.equal(initial.delivery_observation.public_first_published_at, null);
  assert.equal(initial.evidence, 'research_candidate'); assert.equal(initial.top.window.evidence, 'none');
  f.advance(120_000);
  const repeated = await (await f.worker.fetch(resultRequest(), f.env)).json();
  assert.deepEqual(repeated, initial);
  assert.equal(f.env.DB.sqlite.prepare('SELECT count(*) AS n FROM preview_receipts').get().n, 1);
  assert.equal((await f.worker.fetch(request('/result?code=000001&job_id=' + ID), f.env)).status, 404);
  assert.equal(await (await f.worker.fetch(request('/result?code=600519&kind=history'), f.env)).json(), null);
});

test('wrong run source and wrong result symbol fail closed without exposing a candidate', async () => {
  for (const options of [{ wrongSHA: true }, { wrongBundle: true }]) {
    const f = await completedFixture(options);
    const state = await (await f.worker.fetch(request('/status?code=600519&job_id=' + ID), f.env)).json();
    assert.equal(state.current_ready, false); assert.equal(state.conclusion, 'failure');
    assert.equal(state.error_code, 'RESULT_IDENTITY_MISMATCH');
    assert.equal(await (await f.worker.fetch(request('/result?code=600519&job_id=' + ID), f.env)).json(), null);
  }
});

test('the D1 row budget is enforced in UTF-8 bytes before any large result is stored', async () => {
  // Fewer than 1.9m JavaScript characters, but over 1.9m UTF-8 bytes.
  const f = await completedFixture({ padding: '汉'.repeat(640_000) });
  const state = await (await f.worker.fetch(request('/status?code=600519&job_id=' + ID), f.env)).json();
  assert.equal(state.current_ready, false); assert.equal(state.conclusion, 'failure');
  assert.equal(state.error_code, 'BUNDLE_TOO_LARGE');
  assert.equal(f.env.DB.sqlite.prepare('SELECT result_json FROM preview_jobs WHERE job_id=?').get(ID).result_json, null);
});

test('unrelated workflow run cannot satisfy a queued job or authorize any artifact read', async () => {
  const f = await completedFixture({ wrongName: true });
  const state = await (await f.worker.fetch(request('/status?code=600519&job_id=' + ID), f.env)).json();
  assert.equal(state.current_ready, false); assert.equal(state.status, 'queued');
  assert.equal(f.calls.some(call => call.url.includes('/artifacts')), false);
});

test('market loading is independent of credentials and preserves explicitly stale real bars on outage', async () => {
  let count = 0, clock = NOW;
  const worker = createPreviewWorker({ now: () => clock, fetchImpl: async (url, init) => {
    count++; assert.match(decodeURIComponent(url), /sh000001,day,,,1200,$/); assert.equal(init.headers, undefined);
    if (count > 1) throw Error('upstream outage secret');
    return Response.json({ data: { sh000001: { day: [['2026-11-06', 10, 12, 13, 9, 200]] } } });
  } });
  const initial = await (await worker.fetch(request('/market?code=000001'), {})).json();
  assert.equal(initial.code, 'sh000001'); assert.equal(initial.asof, '2026-11-06');
  assert.equal((await worker.fetch(request('/market?code=000001'), {})).status, 200); assert.equal(count, 1);
  clock += 60_001;
  const stale = await (await worker.fetch(request('/market?code=000001'), {})).json();
  assert.equal(stale.stale, true); assert.equal(stale.cache, 'stale'); assert.equal(stale.price.length, 1);
  assert.doesNotMatch(JSON.stringify(stale), /upstream outage secret/);
});

test('only current two-asset same-origin JSON requests can reserve compute; static routing stays independent', async () => {
  const env = environment(); let calls = 0, staticPath;
  env.ASSETS = { async fetch(request) { staticPath = new URL(request.url).pathname; return new Response('asset'); } };
  const worker = createPreviewWorker({ now: () => NOW, fetchImpl: async () => { calls++; throw Error('unexpected'); } });
  assert.equal((await worker.fetch(query('600519', { mode: 'history', history_weeks: 104 }), env)).status, 400);
  assert.equal((await worker.fetch(query('300001'), env)).status, 400);
  const other = query('600519'); other.headers.set('Origin', 'https://elsewhere.example');
  assert.equal((await worker.fetch(other, env)).status, 403);
  assert.equal((await worker.fetch(query('600519'), { ...env, PREVIEW_REF: 'main' })).status, 503);
  assert.equal(calls, 0); assert.equal(env.DB.sqlite.prepare('SELECT count(*) AS n FROM preview_jobs').get().n, 0);
  assert.equal(await (await worker.fetch(new Request('https://preview.example/'), env)).text(), 'asset');
  assert.equal(staticPath, '/home.html');
});

test('oversized JSON and upstream faults return only bounded sanitized errors', async () => {
  const env = environment();
  const worker = createPreviewWorker({ now: () => NOW, fetchImpl: async () => new Response('{}', { headers: { 'Content-Length': '9000000' } }) });
  assert.equal((await worker.fetch(query('600519', { padding: 'x'.repeat(5000) }), env)).status, 400);
  const response = await object(await worker.fetch(request('/market?code=600519'), env));
  assert.equal(response.status, 503); assert.equal(response.body.error_code, 'MARKET_UNAVAILABLE');
  assert.doesNotMatch(JSON.stringify(response.body), /secret-test-token|Content-Length|9000000/);
});

test('the preview workflow is pinned, read-only and gated away from both preparation and publication', () => {
  const workflow = readFileSync(new URL('../../.github/workflows/stock_query.yml', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  const preview = workflow.split('\n  preview:\n')[1].split('\n  prepare:\n')[0];
  const prepare = workflow.split('\n  prepare:\n')[1].split('\n  query:\n')[0];
  const publish = workflow.split('\n  publish:\n')[1];
  assert.match(preview, /if: github\.event_name == 'workflow_dispatch' && inputs\.preview_only && github\.ref == 'refs\/heads\/od\/stock-async-20261106'/);
  assert.match(preview, /permissions:\s+contents: read/);
  assert.match(preview, /ref: \$\{\{ github\.sha \}\}/);
  assert.match(preview, /assert os\.environ\['PREVIEW_SOURCE_SHA'\] == os\.environ\['GITHUB_SHA'\]/);
  assert.match(preview, /path: output\/bundle\.json\s+compression-level: 0/);
  assert.doesNotMatch(preview, /publish_stock_result|gh workflow|git push|contents: write|actions: write/);
  assert.match(prepare, /if: \$\{\{ !inputs\.preview_only \}\}/);
  assert.match(publish, /always\(\) && !cancelled\(\) && !inputs\.preview_only/);
});
