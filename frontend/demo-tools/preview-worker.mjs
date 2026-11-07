/* Isolated demonstration backend. Never dispatches repository_dispatch or publishes
 * to Pages / stock-results. The two public assets share two reservations per China day. */
const REPO = 'CareyPang/LPPL';
const REF = 'od/stock-async-20261106';
const API = '/api/preview';
const GH = `https://api.github.com/repos/${REPO}`;
const SHA = /^[a-f0-9]{40}$/;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
// D1 caps the entire row (not just one column) at 2,000,000 bytes. Leave
// 100 KB for job identity/metadata and reject by UTF-8 bytes before any bind.
const MAX_JSON = 2_000_000, MAX_BUNDLE = 1_900_000, MAX_ZIP = 2_100_000;
const ASSETS = { sh000001: '上证指数', sh600519: '贵州茅台' };
const text = new TextDecoder('utf-8', { fatal: true });
const encoder = new TextEncoder();
class PreviewError extends Error {
  constructor(code, status = 503) { super(code); this.code = code; this.status = status; }
}
const fail = (code, status) => { throw new PreviewError(code, status); };
const safeMessage = {
  ASSET_UNSUPPORTED: '此独立预览目前支持上证指数与贵州茅台。',
  HISTORY_PREVIEW_DISABLED: '此预览只计算当前分析，历史回放尚未开放。',
  DAILY_PREVIEW_LIMIT: '今日预览计算额度已用完，已有行情和结果仍可查看。',
  JOB_NOT_FOUND: '没有找到该资产的预览任务。',
  RESULT_IDENTITY_MISMATCH: '结果身份校验未通过，本次结果未展示。',
  MARKET_UNAVAILABLE: '行情源暂时不可用，请稍后重试。',
  PREVIEW_NOT_CONFIGURED: '预览计算服务尚未配置完成。',
  ORIGIN_DENIED: '此接口仅供当前预览网站使用。',
  BAD_REQUEST: '请求格式无效。',
};
export function canonicalSymbol(code) {
  const input = String(code ?? '').toLowerCase();
  const symbol = { '000001': 'sh000001', '600519': 'sh600519' }[input] || input;
  if (!Object.hasOwn(ASSETS, symbol)) fail('ASSET_UNSUPPORTED', 400);
  return symbol;
}
export function closedCutoff(now = new Date()) {
  const china = new Date(now.getTime() + 8 * 3_600_000);
  if (china.getUTCHours() * 60 + china.getUTCMinutes() < 15 * 60 + 30) china.setUTCDate(china.getUTCDate() - 1);
  return china.toISOString().slice(0, 10);
}
function validDate(date) {
  return typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) &&
    Number.isFinite(Date.parse(date + 'T00:00:00Z')) && new Date(date + 'T00:00:00Z').toISOString().slice(0, 10) === date;
}
function validBar(row) {
  if (!row || !validDate(row.date)) return false;
  const values = ['open', 'high', 'low', 'close', 'volume'].map(key => row[key]);
  return values.every(Number.isFinite) && Math.min(...values.slice(0, 4)) > 0 && row.volume >= 0 &&
    row.high >= Math.max(row.open, row.close, row.low) && row.low <= Math.min(row.open, row.close, row.high);
}
export function normalizeTencent(payload, symbol, now = new Date()) {
  canonicalSymbol(symbol);
  const node = payload?.data?.[symbol];
  // Chart prices stay in the real quote basis. The fitting job keeps a separate
  // HFQ series for stocks and overlays dates only; adjusted prices never become quotes.
  const sourceRows = node?.day;
  if (!Array.isArray(sourceRows)) fail('MARKET_UNAVAILABLE');
  const cutoff = closedCutoff(now), seen = new Map();
  for (const raw of sourceRows) {
    if (!Array.isArray(raw) || raw.length < 6) continue;
    const values = raw.slice(1, 6).map(value => value === '' || value === null ? NaN : Number(value));
    const [open, close, high, low, volume] = values;
    const row = { date: raw[0], open, high, low, close, volume };
    if (!validBar(row) || row.date > cutoff) continue;
    const day = new Date(row.date + 'T00:00:00Z').getUTCDay();
    if (day === 0 || day === 6) continue;
    if (seen.has(row.date) && JSON.stringify(seen.get(row.date)) !== JSON.stringify(row)) fail('MARKET_UNAVAILABLE');
    seen.set(row.date, row);
  }
  const price = [...seen.values()].sort((a, b) => a.date.localeCompare(b.date)).slice(-1200);
  if (!price.length) fail('MARKET_UNAVAILABLE');
  return { schema_version: 1, code: symbol, symbol, exchange: 'sh', name: ASSETS[symbol],
    source: 'tencent_fqkline', adjustment: 'none', model_adjustment: symbol === 'sh000001' ? 'none' : 'hfq',
    price_basis_note: 'K线为未复权行情；模型对个股使用后复权价格，只叠时间区间，不叠模型价格。',
    frequency: '1d', closed_only: true, cutoff,
    cutoff_policy: 'Asia/Shanghai 15:30; excludes weekends and future bars; not an exchange holiday calendar',
    asof: price.at(-1).date, generated_at: now.toISOString(), latest: price.at(-1), price,
    volume_unit: 'vendor_native', volume_unit_status: 'NOT_VERIFIED', evidence: 'observed', model_computed: false,
    serving_scope: 'ISOLATED_PREVIEW' };
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const value of bytes) {
    crc ^= value;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}
// Verified against upload-artifact v4.6.2, ea165f8d65b6e75b540449e92b4886f43607fa02:
// artifact -> archiver -> zip-stream sets store=true for zlib level 0 without
// forceZip64. Keep the workflow action pinned to that tested implementation.
// Central directory sizes are authoritative; real local headers use descriptors.
export function unpackBundle(zip) {
  const bytes = zip instanceof Uint8Array ? zip : new Uint8Array(zip);
  if (bytes.length < 22 || bytes.length > MAX_ZIP) fail('ARTIFACT_INVALID');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  for (let at = bytes.length - 22; at >= Math.max(0, bytes.length - 65_557); at--) {
    if (view.getUint32(at, true) === 0x06054b50 && at + 22 + view.getUint16(at + 20, true) === bytes.length) { eocd = at; break; }
  }
  if (eocd < 0) fail('ARTIFACT_INVALID');
  const count = view.getUint16(eocd + 10, true), size = view.getUint32(eocd + 12, true), start = view.getUint32(eocd + 16, true);
  if (view.getUint16(eocd + 4, true) || view.getUint16(eocd + 6, true) ||
      view.getUint16(eocd + 8, true) !== count || count < 1 || count > 16 || start + size !== eocd) fail('ARTIFACT_INVALID');
  let cursor = start, found = null;
  const names = new Set();
  for (let entry = 0; entry < count; entry++) {
    if (cursor + 46 > eocd || view.getUint32(cursor, true) !== 0x02014b50) fail('ARTIFACT_INVALID');
    const flags = view.getUint16(cursor + 8, true), method = view.getUint16(cursor + 10, true);
    const packed = view.getUint32(cursor + 20, true), unpacked = view.getUint32(cursor + 24, true);
    const nameLength = view.getUint16(cursor + 28, true), extra = view.getUint16(cursor + 30, true), comment = view.getUint16(cursor + 32, true);
    const offset = view.getUint32(cursor + 42, true), next = cursor + 46 + nameLength + extra + comment;
    if (next > eocd || view.getUint16(cursor + 34, true) || flags & 1) fail('ARTIFACT_INVALID');
    if (method !== 0) fail('ARTIFACT_UNSUPPORTED_COMPRESSION');
    const name = text.decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength));
    if (names.has(name) || name.includes('..') || name.includes('\\') || name.startsWith('/')) fail('ARTIFACT_INVALID');
    names.add(name);
    if (name !== 'bundle.json' && !name.endsWith('/')) fail('ARTIFACT_INVALID');
    if (offset + 30 > start || view.getUint32(offset, true) !== 0x04034b50 || view.getUint16(offset + 8, true) !== method ||
      view.getUint16(offset + 6, true) !== flags || packed !== unpacked) fail('ARTIFACT_INVALID');
    if (unpacked > MAX_BUNDLE) fail('BUNDLE_TOO_LARGE');
    const localNameLength = view.getUint16(offset + 26, true), localExtra = view.getUint16(offset + 28, true);
    const dataStart = offset + 30 + localNameLength + localExtra;
    if (dataStart + packed > start || text.decode(bytes.subarray(offset + 30, offset + 30 + localNameLength)) !== name) fail('ARTIFACT_INVALID');
    if (name === 'bundle.json') {
      const data = bytes.subarray(dataStart, dataStart + packed);
      if (crc32(data) !== view.getUint32(cursor + 16, true)) fail('ARTIFACT_INVALID');
      found = JSON.parse(text.decode(data));
    }
    cursor = next;
  }
  if (cursor !== eocd || !found) fail('ARTIFACT_INVALID');
  return found;
}

export function createPreviewWorker({ fetchImpl = globalThis.fetch, now = Date.now, cryptoImpl = globalThis.crypto } = {}) {
  const marketCache = new Map(), statusCache = new Map(), statusFlights = new Map();
  const date = () => new Date(now());
  const dayKey = () => new Date(now() + 8 * 3_600_000).toISOString().slice(0, 10);
  const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'X-LPPL-Scope': 'isolated-preview',
  } });
  const configuration = (env, token = false) => {
    if (!SHA.test(env.PREVIEW_SOURCE_SHA || '') || env.PREVIEW_REF !== REF || !env.DB?.prepare ||
        (token && !env.PREVIEW_GITHUB_TOKEN)) fail('PREVIEW_NOT_CONFIGURED');
  };
  const githubHeaders = env => ({ Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${env.PREVIEW_GITHUB_TOKEN}`, 'User-Agent': 'lppl-isolated-preview', 'X-GitHub-Api-Version': '2022-11-28' });
  async function readBytes(response, limit) {
    const length = Number(response.headers.get('Content-Length'));
    if (length > limit) fail('UPSTREAM_TOO_LARGE');
    if (!response.body) return new Uint8Array();
    const reader = response.body.getReader(), chunks = [];
    let size = 0;
    try {
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        size += part.value.byteLength;
        if (size > limit) { await reader.cancel(); fail('UPSTREAM_TOO_LARGE'); }
        chunks.push(part.value);
      }
    } finally { reader.releaseLock(); }
    const all = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.length; }
    return all;
  }
  async function outbound(url, init = {}, limit = MAX_JSON, timeout = 12_000) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetchImpl(url, { ...init, signal: controller.signal, redirect: 'manual' });
      const bytes = response.status >= 200 && response.status < 300 ? await readBytes(response, limit) : new Uint8Array();
      return { status: response.status, bytes, location: response.headers.get('Location') };
    } finally { clearTimeout(timer); }
  }
  async function githubJSON(env, path) {
    const response = await outbound(GH + path, { headers: githubHeaders(env) });
    if (response.status !== 200) fail('GITHUB_UNAVAILABLE');
    return JSON.parse(text.decode(response.bytes));
  }
  const first = (env, sql, ...args) => env.DB.prepare(sql).bind(...args).first();
  const runSQL = (env, sql, ...args) => env.DB.prepare(sql).bind(...args).run();
  async function getJob(env, symbol, jobId) {
    if (jobId && !UUID.test(jobId)) fail('BAD_REQUEST', 400);
    return jobId
      ? first(env, 'SELECT * FROM preview_jobs WHERE job_id = ? AND symbol = ? AND source_sha = ?', jobId, symbol, env.PREVIEW_SOURCE_SHA)
      : first(env, 'SELECT * FROM preview_jobs WHERE symbol = ? AND source_sha = ? ORDER BY requested_at DESC LIMIT 1', symbol, env.PREVIEW_SOURCE_SHA);
  }
  function jobResponse(job, deduped = false) {
    return { code: job.symbol, symbol: job.symbol, job_id: job.job_id, requested_at: job.requested_at,
      source_sha: job.source_sha, mode: 'current', history_weeks: 0, variant: 'stk_lite', status: job.status,
      queued: !['completed', 'failed'].includes(job.status), deduped, serving_scope: 'ISOLATED_PREVIEW', daily_global_limit: 2 };
  }
  async function query(request, env) {
    configuration(env, true);
    if (!request.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) fail('BAD_REQUEST', 415);
    let body;
    try { body = JSON.parse(text.decode(await readBytes(request, 4096))); } catch { fail('BAD_REQUEST', 400); }
    const symbol = canonicalSymbol(body?.code);
    if ((body.mode && body.mode !== 'current') || Number(body.history_weeks || 0) !== 0) fail('HISTORY_PREVIEW_DISABLED', 400);
    // Request fields can neither select a workflow/ref nor override the pinned source.
    const existing = await first(env, 'SELECT * FROM preview_jobs WHERE symbol = ? AND day_key = ? AND source_sha = ?', symbol, dayKey(), env.PREVIEW_SOURCE_SHA);
    if (existing) return json(jobResponse(existing, true));
    const job = { job_id: cryptoImpl.randomUUID(), symbol, requested_at: date().toISOString(),
      source_sha: env.PREVIEW_SOURCE_SHA, status: 'dispatching', day_key: dayKey() };
    const inserted = await runSQL(env, `INSERT INTO preview_jobs (job_id,symbol,requested_at,source_sha,status,day_key)
      SELECT ?,?,?,?,?,? WHERE (SELECT COUNT(*) FROM preview_jobs WHERE day_key = ?) < 2
      ON CONFLICT(symbol,day_key,source_sha) DO NOTHING`, job.job_id, job.symbol, job.requested_at, job.source_sha, job.status, job.day_key, job.day_key);
    if (!inserted.meta?.changes) {
      const concurrent = await first(env, 'SELECT * FROM preview_jobs WHERE symbol = ? AND day_key = ? AND source_sha = ?', symbol, job.day_key, job.source_sha);
      if (concurrent) return json(jobResponse(concurrent, true));
      fail('DAILY_PREVIEW_LIMIT', 429);
    }
    try {
      const response = await outbound(GH + '/actions/workflows/stock_query.yml/dispatches', {
        method: 'POST', headers: { ...githubHeaders(env), 'Content-Type': 'application/json' }, body: JSON.stringify({ ref: REF, inputs: {
          code: symbol, variant: 'stk_lite', mode: 'current', history_weeks: '0', preview_job_id: job.job_id,
          preview_requested_at: job.requested_at, preview_source_sha: job.source_sha, preview_only: 'true',
        } }),
      });
      job.status = response.status === 204 ? 'queued' : response.status >= 400 && response.status < 500 ? 'failed' : 'dispatch_unknown';
      job.error_code = job.status === 'failed' ? 'DISPATCH_REJECTED' : job.status === 'dispatch_unknown' ? 'DISPATCH_UNCONFIRMED' : null;
    } catch { job.status = 'dispatch_unknown'; job.error_code = 'DISPATCH_UNCONFIRMED'; }
    await runSQL(env, 'UPDATE preview_jobs SET status = ?, error_code = ? WHERE job_id = ?', job.status, job.error_code, job.job_id);
    return json(jobResponse(job), 202);
  }
  function validateBundle(bundle, job) {
    const result = bundle?.result, market = bundle?.market;
    if (!result || !market || result.symbol !== job.symbol || result.source_sha !== job.source_sha ||
        result.job_id !== job.job_id || result.requested_at !== job.requested_at || result.demo === true ||
        market.symbol !== job.symbol || market.adjustment !== 'none' || !validDate(result.asof) || !validDate(market.asof) ||
        result.asof !== market.asof || result.asof > closedCutoff(date()) || !Array.isArray(market.price) ||
        market.price.length < 1 || market.price.length > 5000 || !market.price.every(validBar) ||
        market.price.some((bar, i) => bar.date > market.asof || (i > 0 && bar.date <= market.price[i - 1].date))) fail('RESULT_IDENTITY_MISMATCH');
    if (market.price.at(-1).date !== market.asof) fail('RESULT_IDENTITY_MISMATCH');
    return { market: { ...market, code: job.symbol }, result };
  }
  async function archive(env, artifactId) {
    let response = await outbound(`${GH}/actions/artifacts/${artifactId}/zip`, { headers: githubHeaders(env) }, MAX_ZIP, 20_000);
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      let signed;
      try { signed = new URL(response.location); } catch { fail('ARTIFACT_UNAVAILABLE'); }
      if (signed.protocol !== 'https:' || signed.username || signed.password ||
          !['.blob.core.windows.net', '.actions.githubusercontent.com', '.githubusercontent.com'].some(suffix => signed.hostname.endsWith(suffix))) fail('ARTIFACT_UNAVAILABLE');
      // Never forward the GitHub token to the object store, or follow another redirect.
      response = await outbound(signed.href, {}, MAX_ZIP, 20_000);
    }
    if (response.status !== 200) fail('ARTIFACT_UNAVAILABLE');
    return unpackBundle(response.bytes);
  }
  async function refreshJob(env, job) {
    if (job.result_json || job.status === 'failed') return job;
    const key = job.job_id, cached = statusCache.get(key);
    if (cached && now() - cached.at < 10_000) return cached.job;
    if (statusFlights.has(key)) return statusFlights.get(key);
    const work = (async () => {
      const wanted = 'preview ' + job.job_id;
      const runs = await githubJSON(env, `/actions/workflows/stock_query.yml/runs?branch=${encodeURIComponent(REF)}&event=workflow_dispatch&per_page=100`);
      const matching = (runs.workflow_runs || []).filter(value => value.display_title === wanted && value.head_branch === REF && value.event === 'workflow_dispatch');
      if (matching.length > 1) fail('RESULT_IDENTITY_MISMATCH');
      const execution = matching[0];
      if (!execution) {
        if (now() - Date.parse(job.requested_at) > 30 * 60_000) {
          job.status = 'failed'; job.error_code = 'DISPATCH_NOT_OBSERVED';
          await runSQL(env, 'UPDATE preview_jobs SET status = ?, error_code = ? WHERE job_id = ?', job.status, job.error_code, job.job_id);
        }
        return job;
      }
      if (execution.head_sha !== job.source_sha || !Number.isSafeInteger(execution.id) || execution.id <= 0 ||
          !Number.isFinite(Date.parse(execution.created_at)) || Date.parse(execution.created_at) > now() + 60_000 ||
          Date.parse(execution.created_at) < Date.parse(job.requested_at) - 60_000 ||
          (job.run_id && String(job.run_id) !== String(execution.id))) fail('RESULT_IDENTITY_MISMATCH');
      job.run_id = String(execution.id);
      if (execution.status !== 'completed') {
        job.status = execution.status === 'queued' || execution.status === 'waiting' ? 'queued' : 'in_progress';
        await runSQL(env, 'UPDATE preview_jobs SET status = ?, run_id = ? WHERE job_id = ?', job.status, job.run_id, job.job_id);
        return job;
      }
      if (execution.conclusion !== 'success') {
        job.status = 'failed'; job.error_code = 'COMPUTATION_FAILED';
        await runSQL(env, 'UPDATE preview_jobs SET status = ?, error_code = ?, run_id = ? WHERE job_id = ?', job.status, job.error_code, job.run_id, job.job_id);
        return job;
      }
      const listing = await githubJSON(env, `/actions/runs/${execution.id}/artifacts?per_page=100`);
      const artifacts = (listing.artifacts || []).filter(value => value.name === 'preview-result-' + job.job_id && !value.expired);
      if (artifacts.length !== 1 || !Number.isSafeInteger(artifacts[0].id) || artifacts[0].id <= 0 || artifacts[0].size_in_bytes > MAX_ZIP) fail('ARTIFACT_UNAVAILABLE');
      const artifact = artifacts[0];
      if (artifact.workflow_run && (artifact.workflow_run.id !== execution.id || artifact.workflow_run.head_sha !== job.source_sha)) fail('RESULT_IDENTITY_MISMATCH');
      const bundle = validateBundle(await archive(env, artifact.id), job);
      job.result_json = JSON.stringify(bundle);
      if (encoder.encode(job.result_json).length > MAX_BUNDLE) fail('BUNDLE_TOO_LARGE');
      job.status = 'completed'; job.error_code = null;
      await runSQL(env, 'UPDATE preview_jobs SET status = ?, run_id = ?, result_json = ?, error_code = NULL WHERE job_id = ? AND result_json IS NULL', job.status, job.run_id, job.result_json, job.job_id);
      // Another isolate may have completed first. Always serve the immutable DB winner.
      return getJob(env, job.symbol, job.job_id);
    })();
    statusFlights.set(key, work);
    try {
      const fresh = await work;
      if (statusCache.size > 16) statusCache.delete(statusCache.keys().next().value);
      statusCache.set(key, { at: now(), job: fresh });
      return fresh;
    } catch (error) {
      if (['RESULT_IDENTITY_MISMATCH', 'ARTIFACT_INVALID', 'ARTIFACT_UNSUPPORTED_COMPRESSION', 'BUNDLE_TOO_LARGE'].includes(error.code)) {
        job.status = 'failed'; job.error_code = error.code;
        await runSQL(env, 'UPDATE preview_jobs SET status = ?, error_code = ? WHERE job_id = ?', job.status, job.error_code, job.job_id);
        return job;
      }
      throw error;
    } finally { statusFlights.delete(key); }
  }
  async function status(env, url) {
    configuration(env, true);
    const symbol = canonicalSymbol(url.searchParams.get('code'));
    let job = await getJob(env, symbol, url.searchParams.get('job_id'));
    if (!job) fail('JOB_NOT_FOUND', 404);
    job = await refreshJob(env, job);
    return json({ ...jobResponse(job), status: job.status === 'failed' ? 'completed' : job.status,
      conclusion: job.status === 'failed' ? 'failure' : job.result_json ? 'success' : null,
      current_ready: !!job.result_json, history_ready: false, error_code: job.error_code || null, run_id: job.run_id || null });
  }
  async function seed(env, request, symbol) {
    if (!env.ASSETS?.fetch) return null;
    try {
      const response = await env.ASSETS.fetch(new Request(new URL(`/preview-results/${symbol}.json`, request.url)));
      if (!response.ok || !response.headers.get('Content-Type')?.includes('json')) return null;
      const bundle = JSON.parse(text.decode(await readBytes(response, MAX_BUNDLE)));
      if (!UUID.test(bundle?.result?.job_id || '') || !Number.isFinite(Date.parse(bundle.result.requested_at))) return null;
      return validateBundle(bundle, { symbol, source_sha: env.PREVIEW_SOURCE_SHA,
        job_id: bundle.result.job_id, requested_at: bundle.result.requested_at });
    } catch { return null; }
  }
  async function result(request, env, url) {
    configuration(env);
    const symbol = canonicalSymbol(url.searchParams.get('code')), kind = url.searchParams.get('kind') || 'latest';
    if (kind === 'history' || kind === 'error') return json(null);
    if (kind !== 'latest') fail('BAD_REQUEST', 400);
    const jobId = url.searchParams.get('job_id');
    let job = await getJob(env, symbol, jobId);
    if (jobId && !job) fail('JOB_NOT_FOUND', 404);
    let bundle = job?.result_json ? validateBundle(JSON.parse(job.result_json), job) : null;
    if (!bundle && !jobId) {
      // A pending refresh never hides the last completed version from this source.
      job = await first(env, 'SELECT * FROM preview_jobs WHERE symbol = ? AND source_sha = ? AND result_json IS NOT NULL ORDER BY requested_at DESC LIMIT 1', symbol, env.PREVIEW_SOURCE_SHA);
      if (job) bundle = validateBundle(JSON.parse(job.result_json), job);
      if (!bundle) bundle = await seed(env, request, symbol);
    }
    if (!bundle) return json(null);
    const value = { ...bundle.result };
    delete value.delivery_observation;
    const digest = await cryptoImpl.subtle.digest('SHA-256', encoder.encode(JSON.stringify(value)));
    const hash = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
    await runSQL(env, 'INSERT INTO preview_receipts (result_hash,first_served_at) VALUES (?,?) ON CONFLICT(result_hash) DO NOTHING', hash, date().toISOString());
    const receipt = await first(env, 'SELECT first_served_at FROM preview_receipts WHERE result_hash = ?', hash);
    return json({ ...value, serving_scope: 'ISOLATED_PREVIEW', delivery_observation: {
      schema: 'result_observation_v1', job_id: value.job_id, source_sha: value.source_sha, mode: 'current',
      first_observed_at: receipt.first_served_at, result_sha256: hash, scope: 'ISOLATED_PREVIEW_SERVICE',
      public_first_published_at: null, evidence_status: 'SERVER_RESPONSE_NOT_PROOF_OF_CLIENT_VISIBILITY_OR_ADVANCE_PUBLICATION',
    } });
  }
  async function market(request, env, url) {
    const symbol = canonicalSymbol(url.searchParams.get('code')), cached = marketCache.get(symbol);
    if (cached && now() - cached.at < 60_000) return json({ ...cached.value, expected_source_sha: env.PREVIEW_SOURCE_SHA || null, cache: 'fresh' });
    try {
      const response = await outbound('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + encodeURIComponent(`${symbol},day,,,1200,`), {}, MAX_JSON, 10_000);
      if (response.status !== 200) fail('MARKET_UNAVAILABLE');
      const value = normalizeTencent(JSON.parse(text.decode(response.bytes)), symbol, date());
      marketCache.set(symbol, { at: now(), value });
      return json({ ...value, expected_source_sha: env.PREVIEW_SOURCE_SHA || null, cache: 'miss' });
    } catch {
      let fallback = cached?.value;
      if (!fallback && env.DB?.prepare && SHA.test(env.PREVIEW_SOURCE_SHA || '')) {
        try {
          const previous = await first(env, 'SELECT * FROM preview_jobs WHERE symbol = ? AND source_sha = ? AND result_json IS NOT NULL ORDER BY requested_at DESC LIMIT 1', symbol, env.PREVIEW_SOURCE_SHA);
          if (previous) fallback = validateBundle(JSON.parse(previous.result_json), previous).market;
        } catch { /* Preserve a sanitized market error, never DB or upstream bodies. */ }
      }
      if (!fallback) fallback = (await seed(env, request, symbol))?.market;
      if (fallback) return json({ ...fallback, code: symbol, expected_source_sha: env.PREVIEW_SOURCE_SHA || null,
        cache: 'stale', stale: true, warning_code: 'MARKET_REFRESH_UNAVAILABLE' });
      fail('MARKET_UNAVAILABLE');
    }
  }
  return { async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== API && !url.pathname.startsWith(API + '/')) {
      if (!env.ASSETS?.fetch) return json({ error_code: 'NOT_FOUND', error: '页面不存在。' }, 404);
      if (url.pathname === '/' || url.pathname === '/index.html') url.pathname = '/home.html';
      return env.ASSETS.fetch(new Request(url, request));
    }
    try {
      const origin = request.headers.get('Origin');
      if (origin && origin !== url.origin) fail('ORIGIN_DENIED', 403);
      if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: { 'Allow': 'GET, POST, OPTIONS' } });
      if (url.pathname === API + '/query' && request.method === 'POST') return await query(request, env);
      if (request.method !== 'GET') fail('BAD_REQUEST', 405);
      if (url.pathname === API + '/market') return await market(request, env, url);
      if (url.pathname === API + '/status') return await status(env, url);
      if (url.pathname === API + '/result') return await result(request, env, url);
      fail('BAD_REQUEST', 404);
    } catch (error) {
      const code = error instanceof PreviewError ? error.code : 'PREVIEW_UNAVAILABLE';
      return json({ error_code: code, error: safeMessage[code] || '预览服务暂时不可用，请稍后重试。' }, error instanceof PreviewError ? error.status : 503);
    }
  } };
}
export default createPreviewWorker();
