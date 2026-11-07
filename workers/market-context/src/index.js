const DEFAULT_ORIGIN = 'https://careypang.github.io';
const DEFAULT_SOURCE = 'https://raw.githubusercontent.com/CareyPang/LPPL/main/web/mock/data/market/market_latest.json';
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const JOB_PATTERN = /^[a-f0-9-]{36}$/;
const MAX_BODY = 2048;

function validDate(value) {
  if (!DATE_PATTERN.test(String(value || ''))) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value && date.getUTCDay() > 0 && date.getUTCDay() < 6;
}

function corsHeaders(request, env) {
  const headers = new Headers({ Vary: 'Origin', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type, X-Market-Context-Token', 'Access-Control-Max-Age': '86400' });
  const allowed = env.ALLOWED_ORIGIN || DEFAULT_ORIGIN;
  if (request.headers.get('Origin') === allowed) headers.set('Access-Control-Allow-Origin', allowed);
  return headers;
}

function jsonResponse(request, env, value, status = 200, extra = {}) {
  const headers = corsHeaders(request, env);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  for (const [key, value] of Object.entries(extra)) headers.set(key, value);
  return new Response(JSON.stringify(value), { status, headers });
}

function errorResponse(request, env, error_code, error, status = 400, extra = {}) {
  return jsonResponse(request, env, { error_code, error, ...extra }, status);
}

async function digest(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value, Object.keys(value).sort()));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function fetchSource(env) {
  const source_url = env.MARKET_CONTEXT_SOURCE_URL || DEFAULT_SOURCE;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(source_url, { signal: controller.signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`source_http_${response.status}`);
    const text = await response.text();
    if (text.length > 2_000_000) throw new Error('source_body_too_large');
    const raw = JSON.parse(text);
    if (!raw || typeof raw !== 'object' || !/^\d{4}-\d{2}-\d{2}$/.test(raw.asof || '')) throw new Error('source_invalid_snapshot');
    const fetched_at = new Date().toISOString();
    const sources = raw.sources && typeof raw.sources === 'object' ? raw.sources : {};
    const sourceList = Object.entries(sources).map(([source_id, meta]) => ({
      source_id, source_url, url_host: meta?.url_host || null, fetched_at: meta?.fetched_at || fetched_at,
      status: meta?.ok === true ? 'fresh' : meta?.ok === false ? 'error' : 'unavailable',
      ok: meta?.ok ?? null, stale_reason: meta?.ok === false ? (meta.error || 'source_error') : null,
      raw_sha256: meta?.raw_sha256 || null, license_tier: meta?.license_tier || null, error: meta?.error || null,
    }));
    const failed = sourceList.some((entry) => entry.status !== 'fresh');
    const limit = raw.limit_pools && typeof raw.limit_pools === 'object' ? { ...raw.limit_pools } : {};
    const missing = (stale_reason) => ({ status: 'not_available', asof: raw.asof, window: null, rows: [], stale_reason, evidence: 'descriptive' });
    limit.reasons ??= missing('source did not provide limit-up reason rows');
    limit.topics ??= missing('source did not provide topic labels');
    const context = {
      schema_version: 'market-context.v1', kind: 'market_context', market: 'CN_A_SHARE', snapshot_kind: 'eod',
      asof: raw.asof, generated_at: raw.generated_at || null, requested_at: fetched_at,
      status: failed ? 'partial' : 'fresh', stale_reason: failed ? 'one or more sources failed' : null,
      last_good_asof: failed ? null : raw.asof, evidence: 'descriptive',
      source: { source_id: 'market_latest_wrapper', source_url, fetched_at, status: failed ? 'partial' : 'fresh', stale_reason: failed ? 'one or more sources failed' : null, license_tier: null },
      sources: Object.fromEntries(sourceList.map((entry) => [entry.source_id, entry])),
      board_flow: raw.board_flow || {}, limit_pools: limit,
      history: { progression: missing('prior trading-day limit-pool pair is not available') },
      northbound: raw.northbound || {}, margin: raw.margin || {}, valuation: raw.valuation || {},
    };
    context.snapshot_sha256 = await digest(context);
    return context;
  } finally { clearTimeout(timer); }
}

class SerializedState {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; this.tail = Promise.resolve(); }
  fetch(request) { const operation = this.tail.then(() => this.handle(request)); this.tail = operation.catch(() => {}); return operation; }
}

export class MarketContextState extends SerializedState {
  async handle(request) {
    const url = new URL(request.url);
    if (url.pathname === '/context/snapshot' || url.pathname === '/context') return this.snapshot(url.searchParams.get('date') || 'latest');
    if (url.pathname === '/context/status') return this.status(url.searchParams.get('job_id'));
    if (url.pathname === '/context/refresh' && request.method === 'POST') return this.refresh(request);
    return Response.json({ error_code: 'NOT_FOUND', error: '接口不存在' }, { status: 404 });
  }

  async snapshot(date) {
    if (date !== 'latest' && !validDate(date)) return Response.json({ error_code: 'INVALID_DATE', error: '日期必须是已验证工作日或 latest' }, { status: 400 });
    const key = date === 'latest' ? 'latest' : `snapshot:${date}`;
    const value = await this.ctx.storage.get(key);
    if (!value) return Response.json({ error_code: 'CONTEXT_NOT_READY', error: '该日期尚无已封存市场背景快照', date, status: 'not_ready' }, { status: 404 });
    return Response.json({ ...value, cache: 'hit' });
  }

  async refresh(request) {
    const expected = this.env.MARKET_CONTEXT_REFRESH_TOKEN;
    if (!expected || request.headers.get('X-Market-Context-Token') !== expected) return Response.json({ error_code: 'REFRESH_FORBIDDEN', error: '刷新接口只允许服务端任务调用' }, { status: 403 });
    let body = {};
    try {
      const raw = await request.text();
      if (raw.length > MAX_BODY) return Response.json({ error_code: 'BODY_TOO_LARGE', error: '请求内容过长' }, { status: 413 });
      body = raw ? JSON.parse(raw) : {};
    } catch { return Response.json({ error_code: 'INVALID_JSON', error: '请求内容不是有效JSON' }, { status: 400 }); }
    const date = body.date || 'latest';
    if (date !== 'latest' && !validDate(date)) return Response.json({ error_code: 'INVALID_DATE', error: '日期必须是已验证工作日或 latest' }, { status: 400 });
    const active = await this.ctx.storage.get(`active:${date}`);
    if (active) return Response.json({ queued: true, deduped: true, job_id: active.job_id, date, status: active.status }, { status: 202 });
    const job = { job_id: crypto.randomUUID(), date, status: 'queued', requested_at: new Date().toISOString(), asof: null, error_code: null, error: null };
    await this.ctx.storage.put(`active:${date}`, job);
    await this.ctx.storage.put(`job:${job.job_id}`, job);
    const work = this.run(job).catch(() => {});
    if (typeof this.ctx.waitUntil === 'function') this.ctx.waitUntil(work);
    else work.catch(() => {});
    return Response.json({ queued: true, deduped: false, job_id: job.job_id, date, status: 'queued', requested_at: job.requested_at }, { status: 202 });
  }

  async run(job) {
    job.status = 'running'; await this.ctx.storage.put(`job:${job.job_id}`, job);
    try {
      const snapshot = await fetchSource(this.env);
      if (job.date !== 'latest' && snapshot.asof !== job.date) throw new Error('DATE_NOT_AVAILABLE');
      const key = `snapshot:${snapshot.asof}`;
      await this.ctx.storage.put(key, snapshot);
      await this.ctx.storage.put('latest', snapshot);
      job.status = 'completed'; job.asof = snapshot.asof;
    } catch (error) {
      job.status = 'failed'; job.error_code = String(error?.message || 'CONTEXT_REFRESH_FAILED') === 'DATE_NOT_AVAILABLE' ? 'DATE_NOT_AVAILABLE' : 'CONTEXT_REFRESH_FAILED'; job.error = job.error_code === 'DATE_NOT_AVAILABLE' ? '请求日期没有对应封存快照' : '市场背景刷新失败';
      const previous = await this.ctx.storage.get('latest');
      if (previous && job.error_code !== 'DATE_NOT_AVAILABLE') {
        const stale = { ...previous, status: 'stale', stale_reason: job.error_code, last_good_asof: previous.asof,
          requested_at: new Date().toISOString(), source: { ...previous.source, status: 'stale', stale_reason: job.error_code } };
        stale.snapshot_sha256 = await digest(stale);
        await this.ctx.storage.put('latest', stale);
        await this.ctx.storage.put(`snapshot:${previous.asof}`, stale);
      }
    }
    await this.ctx.storage.put(`job:${job.job_id}`, job);
    await this.ctx.storage.delete(`active:${job.date}`);
  }

  async status(jobId) {
    if (!JOB_PATTERN.test(String(jobId || ''))) return Response.json({ error_code: 'INVALID_JOB_ID', error: '任务编号无效' }, { status: 400 });
    const job = await this.ctx.storage.get(`job:${jobId}`);
    if (!job) return Response.json({ error_code: 'JOB_NOT_FOUND', error: '找不到市场背景刷新任务' }, { status: 404 });
    return Response.json(job);
  }
}

export default {
  async fetch(request, env = {}) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');
    if (origin && origin !== (env.ALLOWED_ORIGIN || DEFAULT_ORIGIN)) return jsonResponse(request, env, { error_code: 'ORIGIN_FORBIDDEN', error: '来源未获允许' }, 403);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    const route = url.pathname;
    const methods = { '/context': 'GET', '/context/snapshot': 'GET', '/context/status': 'GET', '/context/refresh': 'POST' };
    if (!methods[route]) return errorResponse(request, env, 'NOT_FOUND', '接口不存在', 404);
    if (methods[route] !== request.method) return errorResponse(request, env, 'METHOD_NOT_ALLOWED', '请求方法不支持', 405);
    if (!env.MARKET_CONTEXT || typeof env.MARKET_CONTEXT.get !== 'function') return errorResponse(request, env, 'SERVICE_UNAVAILABLE', '市场背景服务尚未配置', 503);
    const body = request.method === 'POST' ? await request.clone().text() : '{}';
    if (body.length > MAX_BODY) return errorResponse(request, env, 'BODY_TOO_LARGE', '请求内容过长', 413);
    const id = env.MARKET_CONTEXT.idFromName('global');
    const internal = new Request(`https://internal${route}${url.search}`, { method: request.method, headers: request.headers, body: request.method === 'POST' ? body : undefined });
    const response = await env.MARKET_CONTEXT.get(id).fetch(internal);
    return jsonResponse(request, env, await response.json(), response.status, response.status === 202 ? { 'Retry-After': '2' } : {});
  },
};
