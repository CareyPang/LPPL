const DEFAULT_ORIGIN = 'https://careypang.github.io';
const DEFAULT_REPO = 'CareyPang/LPPL';
const CODE_PATTERN = /^(?:60|68|00|30|43|83|87|92)\d{4}$/;
const JOB_PATTERN = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const SHA_PATTERN = /^[a-f0-9]{40}$/;
const ISO_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const SUFFIXES = { latest: '.json', history: '_history.json', error: '_error.json' };
const ACTIVE = new Set(['dispatching', 'dispatch_unknown', 'pending', 'queued', 'requested', 'waiting', 'in_progress']);
const MARKET_TTL_MS = 60_000;
const STATUS_TTL_MS = 10_000;

function timestamp(value) {
  return typeof value === 'string' && ISO_PATTERN.test(value) && Number.isFinite(Date.parse(value))
    ? Date.parse(value) : null;
}

function corsHeaders(request, env) {
  const headers = new Headers({
    Vary: 'Origin', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400',
  });
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

function failure(error_code, error, status = 503, extra = {}) {
  return Response.json({ error_code, error, ...extra }, { status });
}

function githubHeaders(env, accept = 'application/vnd.github+json') {
  return { Accept: accept, Authorization: `Bearer ${env.GH_TOKEN || ''}`,
    'User-Agent': 'lppl-stock-query-worker', 'X-GitHub-Api-Version': '2022-11-28' };
}

function repo(env) { return env.REPO || DEFAULT_REPO; }

// Includes response-body consumption in the deadline; never expose upstream bodies in errors.
export async function fetchJSON(url, init = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (!response.ok) return { status: response.status, data: null };
    const text = await response.text();
    if (text.length > 2_000_000) throw new Error('upstream_body_too_large');
    return { status: response.status, data: text ? JSON.parse(text) : null };
  } finally { clearTimeout(timer); }
}

async function mainSHA(env, timeoutMs = 8000) {
  const response = await fetchJSON(`https://api.github.com/repos/${repo(env)}/commits/main`,
    { headers: githubHeaders(env) }, timeoutMs);
  if (response.status !== 200 || !SHA_PATTERN.test(response.data?.sha || '')) throw new Error('source_unavailable');
  return response.data.sha;
}

function stub(binding, name) { return binding.get(binding.idFromName(name)); }

async function internal(binding, name, path, body) {
  return stub(binding, name).fetch(new Request(`https://internal${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }));
}

function bindingsReady(env) {
  return [env.STOCK_JOBS, env.QUERY_BUDGET].every((binding) =>
    binding && typeof binding.get === 'function' && typeof binding.idFromName === 'function');
}

function budgetNumber(env, name, fallback, ceiling) {
  const n = Number(env[name] ?? fallback);
  return Number.isInteger(n) && n > 0 && n <= ceiling ? n : fallback;
}

// The queue covers storage AND outbound I/O, so two requests cannot dispatch concurrently
// after reading the same state. Reservations survive eviction/restarts in DO storage.
class SerializedObject {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; this.tail = Promise.resolve(); }
  fetch(request) {
    const operation = this.tail.then(() => this.handle(request));
    this.tail = operation.catch(() => {});
    return operation;
  }
}

export class QueryBudget extends SerializedObject {
  async handle(request) {
    const path = new URL(request.url).pathname;
    if (path === '/source') {
      try {
        const cached = await this.ctx.storage.get('source');
        if (cached && Date.now() - cached.at < 300_000) return Response.json({ source_sha: cached.sha });
        const sha = await mainSHA(this.env, 1000);
        await this.ctx.storage.put('source', { sha, at: Date.now() });
        return Response.json({ source_sha: sha });
      } catch { return Response.json({ source_sha: null }); }
    }
    if (path !== '/reserve') return failure('NOT_FOUND', '接口不存在', 404);
    const { ip, resource = 'query' } = await request.json();
    const now = Date.now();
    const state = await this.ctx.storage.get(resource) || { global: [], ips: {} };
    const windowMs = resource === 'market' ? 60_000 : 600_000;
    const globalWindow = resource === 'market' ? 60_000 : 3_600_000;
    state.global = state.global.filter((at) => at > now - globalWindow);
    for (const key of Object.keys(state.ips)) {
      state.ips[key] = state.ips[key].filter((at) => at > now - windowMs);
      if (!state.ips[key].length) delete state.ips[key];
    }
    const perIP = state.ips[ip] || [];
    const ipLimit = resource === 'market' ? 30 : budgetNumber(this.env, 'QUERIES_PER_IP_10M', 5, 100);
    const globalLimit = resource === 'market' ? 300 : budgetNumber(this.env, 'QUERIES_PER_HOUR', 60, 1000);
    if (perIP.length >= ipLimit || state.global.length >= globalLimit) {
      return failure('RATE_LIMITED', '查询额度暂时用尽，请稍后再试', 429, { retry_after: 60 });
    }
    state.global.push(now);
    state.ips[ip] = [...perIP, now];
    await this.ctx.storage.put(resource, state);
    return Response.json({ allowed: true });
  }
}

async function reserve(env, ip, resource = 'query') {
  return internal(env.QUERY_BUDGET, 'global', '/reserve', { ip, resource });
}

export function closedCutoff(now = new Date()) {
  const shanghai = new Date(now.getTime() + 8 * 3_600_000);
  // Match research.pipeline.stock._close_cutoff: allow a 30-minute vendor settlement buffer.
  if (shanghai.getUTCHours() * 60 + shanghai.getUTCMinutes() < 15 * 60 + 30) {
    shanghai.setUTCDate(shanghai.getUTCDate() - 1);
  }
  return shanghai.toISOString().slice(0, 10);
}

function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
    && date.getUTCDay() !== 0 && date.getUTCDay() !== 6;
}

export function normalizeMarket(payload, code, now = new Date()) {
  const exchange = code.startsWith('6') ? 'sh' : /^(43|83|87|92)/.test(code) ? 'bj' : 'sz';
  const symbol = `${exchange}${code}`;
  const node = payload?.data?.[symbol];
  if (!Array.isArray(node?.day)) throw new Error('market_empty');
  const cutoff = closedCutoff(now);
  const rows = new Map();
  for (const row of node.day) {
    if (!Array.isArray(row) || row.length < 6 || !validDate(row[0]) || row[0] > cutoff) continue;
    const [open, close, high, low, volume] = row.slice(1, 6).map((v) => v === '' || v === null ? NaN : Number(v));
    if (![open, close, high, low, volume].every(Number.isFinite)
      || Math.min(open, close, high, low) <= 0 || volume < 0
      || high < Math.max(open, close, low) || low > Math.min(open, close, high)) continue;
    rows.set(row[0], { date: row[0], open, high, low, close, volume });
  }
  const price = [...rows.values()].sort((a, b) => a.date.localeCompare(b.date)).slice(-640);
  if (!price.length) throw new Error('market_empty');
  const rawName = node.qt?.[symbol]?.[1];
  const name = typeof rawName === 'string' ? rawName.slice(0, 80) : code;
  return { schema_version: 1, code, symbol, exchange, name, source: 'tencent_fqkline',
    adjustment: 'none', frequency: '1d', closed_only: true, cutoff,
    cutoff_policy: 'Asia/Shanghai 15:30; excludes weekends and future bars; no holiday calendar inference',
    asof: price.at(-1).date, generated_at: now.toISOString(), price, latest: price.at(-1),
    volume_unit: 'vendor_native', evidence: 'observed', model_computed: false };
}

async function readResult(env, code, kind, jobId = null) {
  const path = `stock/${jobId ? `jobs/${jobId}/` : ''}${code}${SUFFIXES[kind]}`;
  return fetchJSON(`https://api.github.com/repos/${repo(env)}/contents/${path}?ref=stock-results`,
    { headers: githubHeaders(env, 'application/vnd.github.raw') });
}

async function findRun(env, code, jobId = null, since = null) {
  const title = `stock_query ${code}${jobId ? ` ${jobId}` : ''}`;
  // A dispatch may not appear immediately. Never infer failure from a missing run.
  const base = `https://api.github.com/repos/${repo(env)}/actions/workflows/stock_query.yml/runs?per_page=100`;
  const dateFilter = jobId && since
    ? `&created=${encodeURIComponent(`>=${new Date(since - 60_000).toISOString()}`)}` : '';
  for (let page = 1; page <= (jobId ? 3 : 1); page += 1) {
    const response = await fetchJSON(`${base}${dateFilter}${page > 1 ? `&page=${page}` : ''}`,
      { headers: githubHeaders(env) });
    if (response.status !== 200) throw new Error('status_unavailable');
    const runs = Array.isArray(response.data?.workflow_runs) ? response.data.workflow_runs : [];
    const run = runs.filter((r) => r.display_title === title)
      .filter((r) => since === null || Date.parse(r.created_at) >= since - 60_000)
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))[0];
    if (run) return run;
    if (runs.length < 100) break;
  }
  return null;
}

function jobResponse(job, deduped = false) {
  return { schema_version: 'stock_query_v1', queued: true, deduped, code: job.code, job_id: job.job_id, mode: job.mode,
    requested_at: job.requested_at, since: job.requested_at, source_sha: job.source_sha,
    history_weeks: job.history_weeks, variant: 'stk_lite', ratelimit: 'enabled',
    status: job.status, phase: job.snapshot?.phase || 'queued', current_ready: false, history_ready: false,
    stale: false, stale_reason: null, last_success_at: null,
    first_worker_observed_at: job.first_worker_observed_at || null,
    first_visible_at: null, first_visible_at_source: 'browser_client_required',
    ...(job.status === 'dispatch_unknown' ? {
      error_code: 'DISPATCH_UNCONFIRMED', message: '提交回执暂未确认，保留原任务并继续检查，请勿重复提交',
    } : {}) };
}

function sameResult(data, job) {
  return resultIdentity(data, job.code) && data.code === job.code && data.job_id === job.job_id
    && data.source_sha === job.source_sha && data.mode === job.mode;
}

function resultIdentity(data, code) {
  const symbol = `${code.startsWith('6') ? 'sh' : /^(43|83|87|92)/.test(code) ? 'bj' : 'sz'}${code}`;
  return data && typeof data === 'object' && !Array.isArray(data)
    && (data.code === code || data.symbol === symbol)
    && (data.code === undefined || data.code === code)
    && (data.symbol === undefined || data.symbol === symbol);
}

export class StockQueryState extends SerializedObject {
  async handle(request) {
    const path = new URL(request.url).pathname;
    const input = await request.json();
    if (path === '/market') return this.market(input);
    if (path === '/query') return this.query(input);
    if (path === '/status') return this.status(input);
    if (path === '/result') return this.result(input);
    return failure('NOT_FOUND', '接口不存在', 404);
  }

  async observeResult(data, kind) {
    // Observation time is server-side read evidence, not publication or human
    // visibility. Do not mutate the immutable scientific result itself.
    const bytes = new TextEncoder().encode(JSON.stringify(data));
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const hash = [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('');
    const key = `observed:${kind}:${hash}`;
    let first = await this.ctx.storage.get(key);
    if (!first) {
      first = new Date().toISOString();
      await this.ctx.storage.put(key, first);
    }
    return { result_hash: hash, first_worker_observed_at: first,
      first_visible_at: null, first_visible_at_source: 'browser_client_required',
      evidence: 'worker_read_observation_only', public_first_published_at: null };
  }

  async result({ code, kind, job_id }) {
    const result = await readResult(this.env, code, kind, job_id);
    if (result.status === 404) return failure('RESULT_NOT_FOUND', '结果尚未生成', 404);
    if (result.status !== 200) return failure('RESULT_UNAVAILABLE', '结果暂时无法读取', 502);
    const data = result.data;
    if (!resultIdentity(data, code) || (job_id && (data?.job_id !== job_id || data?.code !== code))) {
      return failure('RESULT_MISMATCH', '结果身份不匹配', 502);
    }
    if (job_id && (!SHA_PATTERN.test(data.source_sha || '') ||
        !['current', 'history'].includes(data.mode) ||
        (kind !== 'error' && data.mode !== (kind === 'history' ? 'history' : 'current')))) {
      return failure('RESULT_MISMATCH', '结果任务类型或版本字段不完整', 502);
    }
    const job = job_id ? await this.ctx.storage.get(`job:${job_id}`) : null;
    if (job && !sameResult(data, job)) return failure('RESULT_MISMATCH', '结果版本不匹配', 502);
    const delivery = await this.observeResult(data, kind);
    return Response.json({ ...data, delivery_observation: { ...delivery,
      identity_verified_against: job ? 'retained_job' : 'artifact_metadata_only' } });
  }

  async market({ code, ip }) {
    const cached = await this.ctx.storage.get('market');
    let data;
    if (cached && Date.now() - cached.at < MARKET_TTL_MS) {
      data = { ...cached.data, cache: 'hit', stale: false };
    } else {
      const budget = await reserve(this.env, ip, 'market');
      if (!budget.ok) {
        if (!cached) return budget;
        data = { ...cached.data, cache: 'stale', stale: true, warning_code: 'RATE_LIMITED' };
      } else {
        try {
          const symbol = `${code.startsWith('6') ? 'sh' : /^(43|83|87|92)/.test(code) ? 'bj' : 'sz'}${code}`;
          const url = new URL('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get');
          url.searchParams.set('param', `${symbol},day,,,640,`);
          const response = await fetchJSON(url.toString());
          if (response.status !== 200) throw new Error('market_unavailable');
          const fresh = normalizeMarket(response.data, code);
          await this.ctx.storage.put('market', { at: Date.now(), data: fresh });
          data = { ...fresh, cache: 'miss', stale: false };
        } catch {
          if (!cached) return failure('MARKET_UNAVAILABLE', '暂时无法取得有效已收盘日线，请稍后重试', 502);
          data = { ...cached.data, cache: 'stale', stale: true, warning_code: 'MARKET_UNAVAILABLE' };
        }
      }
    }
    let expected = null;
    try {
      const response = await internal(this.env.QUERY_BUDGET, 'global', '/source', {});
      expected = (await response.json()).source_sha || null;
    } catch { /* Market availability is independent from GitHub metadata. */ }
    return Response.json({ ...data, expected_source_sha: expected,
      asof_freshness: 'not_established',
      stale_reason: data.stale ? data.warning_code || 'MARKET_UNAVAILABLE' : null,
      cache_age_seconds: Math.max(0, Math.floor((Date.now() - Date.parse(data.generated_at)) / 1000)) });
  }

  async query({ code, mode, history_weeks, ip }) {
    const activeId = await this.ctx.storage.get(`active:${mode}`);
    if (activeId) {
      const active = await this.ctx.storage.get(`job:${activeId}`);
      if (active && ACTIVE.has(active.status)) {
        try { await this.refresh(active); } catch { /* Fail closed: reuse rather than risk another dispatch. */ }
        if (ACTIVE.has(active.status)) return Response.json(jobResponse(active, true), { status: 202 });
      }
    }
    const budget = await reserve(this.env, ip);
    if (!budget.ok) return budget;
    let source_sha;
    try { source_sha = await mainSHA(this.env); }
    catch { return failure('SOURCE_UNAVAILABLE', '暂时无法确认计算代码版本，请稍后重试', 502); }
    const job = { code, mode, history_weeks, job_id: crypto.randomUUID(),
      requested_at: new Date().toISOString(), source_sha, status: 'dispatching', checked_at: Date.now() };
    await this.ctx.storage.put({ [`job:${job.job_id}`]: job, [`active:${mode}`]: job.job_id });
    try {
      const response = await fetchJSON(`https://api.github.com/repos/${repo(this.env)}/dispatches`, {
        method: 'POST', headers: githubHeaders(this.env), body: JSON.stringify({
          event_type: 'stock_query', client_payload: { code, variant: 'stk_lite', mode,
            history_weeks: String(history_weeks), job_id: job.job_id,
            requested_at: job.requested_at, source_sha },
        }),
      });
      if (response.status >= 500) {
        job.status = 'dispatch_unknown';
      } else if (response.status !== 204) {
        job.status = 'failed';
        await this.ctx.storage.put(`job:${job.job_id}`, job);
        return failure('DISPATCH_FAILED', '计算任务未能提交，请稍后重试', 502, { job_id: job.job_id });
      } else {
        job.status = 'pending';
      }
    } catch {
      // GitHub may have accepted the POST before its response was lost. Keep its identity.
      job.status = 'dispatch_unknown';
    }
    await this.ctx.storage.put(`job:${job.job_id}`, job);
    return Response.json(jobResponse(job), { status: 202 });
  }

  async refresh(job) {
    if (job.snapshot && Date.now() - job.checked_at < STATUS_TTL_MS) return job.snapshot;
    const outputs = await Promise.all(['latest', 'history', 'error'].map((kind) => readResult(this.env, job.code, kind, job.job_id)));
    if (outputs.some((r) => ![200, 404].includes(r.status))) throw new Error('result_lookup_failed');
    if (outputs.some((r) => r.status === 200 && !sameResult(r.data, job))) throw new Error('result_identity_mismatch');
    const [current_ready, history_ready, error_ready] = outputs.map((r) => r.status === 200);
    const targetReady = job.mode === 'current' ? current_ready : history_ready;
    const run = targetReady ? null : await findRun(this.env, job.code, job.job_id, timestamp(job.requested_at));
    let status = run?.status || (job.status === 'dispatch_unknown' ? 'dispatch_unknown' : 'pending');
    if (status !== 'completed' && !ACTIVE.has(status)) status = 'in_progress';
    let conclusion = run?.conclusion || null;
    let phase = status;
    let stale = false;
    let stale_reason = null;
    let last_success_at = null;
    let result_asof = null;
    const artifact = job.mode === 'history' ? outputs[1].data : outputs[0].data;
    if (targetReady) {
      status = 'completed'; conclusion = 'success'; phase = `${job.mode}_ready`;
      last_success_at = artifact?.generated_at || artifact?.requested_at || null;
      result_asof = artifact?.asof || null;
      const observation = await this.observeResult(artifact, job.mode === 'history' ? 'history' : 'latest');
      job.first_worker_observed_at = observation.first_worker_observed_at;
    }
    else if (error_ready) { status = 'completed'; conclusion = 'failure'; phase = 'failed'; }
    else if (run?.status === 'completed') {
      const recentlyCompleted = Number.isFinite(Date.parse(run.updated_at))
        && Date.now() - Date.parse(run.updated_at) < 120_000;
      if (run.conclusion === 'success' && recentlyCompleted) {
        status = 'in_progress'; conclusion = null; phase = 'publishing';
      } else {
        status = 'completed'; conclusion = 'failure'; phase = run.conclusion === 'success' ? 'publish_failed' : 'failed';
      }
    }
    // A refresh failure does not erase an older readable result. Keep the
    // failed job separate from that fallback; never mark this job ready.
    if (!targetReady && ['failed', 'publish_failed'].includes(phase)) {
      try {
        const prior = await readResult(this.env, job.code, job.mode === 'history' ? 'history' : 'latest');
        if (prior.status === 200 && resultIdentity(prior.data, job.code) &&
            prior.data.job_id !== job.job_id) {
          stale = true;
          stale_reason = 'refresh_failed_previous_result_retained';
          last_success_at = prior.data.generated_at || prior.data.requested_at || null;
          result_asof = prior.data.asof || null;
          phase = 'stale';
        }
      } catch { /* The verified failure remains terminal if fallback lookup fails. */ }
    }
    if (!targetReady && job.mode === 'history' && status === 'in_progress' && phase !== 'publishing') {
      phase = 'history_running';
    } else if (!targetReady && ACTIVE.has(status) && status !== 'in_progress') {
      phase = 'queued';
    } else if (!targetReady && phase === 'in_progress') {
      phase = 'current_running';
    }
    const snapshot = { schema_version: 'stock_query_v1', code: job.code, job_id: job.job_id, mode: job.mode, requested_at: job.requested_at,
      source_sha: job.source_sha, status, conclusion, phase, current_ready, history_ready, error_ready,
      created_at: run?.created_at || job.requested_at, updated_at: run?.updated_at || null,
      workflow_status: run?.status || null, workflow_conclusion: run?.conclusion || null,
      run_url: run?.html_url || null,
      asof: result_asof, stale, stale_reason, last_success_at,
      first_worker_observed_at: job.first_worker_observed_at || null,
      first_visible_at: null, first_visible_at_source: 'browser_client_required',
      retry_after: status !== 'completed' ? 10 : null,
      reconciliation_required: !run && !targetReady && !error_ready &&
        Date.now() - Date.parse(job.requested_at) > 30 * 60_000,
      ...(phase === 'publish_failed' ? { error_code: 'RESULT_NOT_PUBLISHED', error: '计算结束，但本任务结果尚未发布' } : {}) };
    job.status = status;
    job.snapshot = snapshot;
    job.checked_at = Date.now();
    await this.ctx.storage.put(`job:${job.job_id}`, job);
    return snapshot;
  }

  async status({ code, job_id }) {
    const job = await this.ctx.storage.get(`job:${job_id}`);
    if (!job || job.code !== code) return failure('JOB_NOT_FOUND', '找不到该资产的计算任务', 404);
    if (job.status === 'failed') return Response.json({ code, job_id, mode: job.mode,
      source_sha: job.source_sha, requested_at: job.requested_at, status: 'completed', conclusion: 'failure',
      phase: 'dispatch_failed', current_ready: false, history_ready: false, error_ready: false,
      stale: false, stale_reason: null, last_success_at: null,
      first_worker_observed_at: null, first_visible_at: null,
      first_visible_at_source: 'browser_client_required',
      error_code: 'DISPATCH_FAILED', error: '计算任务未能提交，请稍后重试' });
    try { return Response.json(await this.refresh(job)); }
    catch { return failure('STATUS_UNAVAILABLE', '暂时无法核实任务状态，已保留原任务', 502, { job_id }); }
  }
}

async function legacyStatus(request, env, code, since) {
  try {
    const run = await findRun(env, code, null, since);
    if (!run) return jsonResponse(request, env, { status: since === null ? 'none' : 'pending' });
    return jsonResponse(request, env, { status: run.status || null, conclusion: run.conclusion || null,
      created_at: run.created_at || null, updated_at: run.updated_at || null, run_url: run.html_url || null });
  } catch { return jsonResponse(request, env, { error_code: 'STATUS_UNAVAILABLE', error: '暂时无法查询历史任务状态' }, 502); }
}

export default {
  async fetch(request, env = {}) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');
    if (origin && origin !== (env.ALLOWED_ORIGIN || DEFAULT_ORIGIN)) {
      return jsonResponse(request, env, { error_code: 'ORIGIN_FORBIDDEN', error: '来源未获允许' }, 403);
    }
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    const routes = { '/market': 'GET', '/query': 'POST', '/status': 'GET', '/result': 'GET' };
    if (!routes[url.pathname]) return jsonResponse(request, env, { error_code: 'NOT_FOUND', error: '接口不存在' }, 404);
    if (request.method !== routes[url.pathname]) return jsonResponse(request, env, { error_code: 'METHOD_NOT_ALLOWED', error: '请求方法不支持' }, 405);
    let body = {};
    if (url.pathname === '/query') {
      try {
        const raw = await request.text();
        if (raw.length > 2048) return jsonResponse(request, env, { error_code: 'BODY_TOO_LARGE', error: '请求内容过长' }, 413);
        body = JSON.parse(raw);
      }
      catch { return jsonResponse(request, env, { error_code: 'INVALID_JSON', error: '请求内容不是有效JSON' }, 400); }
    }
    const code = url.pathname === '/query' ? body?.code : url.searchParams.get('code');
    if (typeof code !== 'string' || !CODE_PATTERN.test(code)) {
      return jsonResponse(request, env, { error_code: 'INVALID_CODE', error: '请输入有效的六位A股代码' }, 400);
    }
    const job_id = url.searchParams.get('job_id');
    if (job_id !== null && !JOB_PATTERN.test(job_id)) {
      return jsonResponse(request, env, { error_code: 'INVALID_JOB_ID', error: '任务编号无效' }, 400);
    }
    if (url.pathname !== '/market' && !env.GH_TOKEN) {
      return jsonResponse(request, env, { error_code: 'SERVICE_UNAVAILABLE', error: '查询服务尚未完成配置' }, 503);
    }
    try {
      if (url.pathname === '/result') {
        const kind = url.searchParams.get('kind') || 'latest';
        if (!Object.hasOwn(SUFFIXES, kind)) return jsonResponse(request, env, { error_code: 'INVALID_KIND', error: '结果类型无效' }, 400);
        if (bindingsReady(env)) {
          const response = await internal(env.STOCK_JOBS, code, '/result', { code, kind, job_id });
          return jsonResponse(request, env, await response.json(), response.status);
        }
        const result = await readResult(env, code, kind, job_id);
        if (result.status === 404) return jsonResponse(request, env, { error_code: 'RESULT_NOT_FOUND', error: '结果尚未生成' }, 404);
        if (result.status !== 200) throw new Error('result_unavailable');
        if (!resultIdentity(result.data, code) || (job_id && (result.data?.job_id !== job_id || result.data?.code !== code))) {
          return jsonResponse(request, env, { error_code: 'RESULT_MISMATCH', error: '结果身份不匹配' }, 502);
        }
        return jsonResponse(request, env, result.data, 200, { 'Cache-Control': job_id ? 'public, max-age=300' : 'max-age=30' });
      }
      if (url.pathname === '/status' && !job_id) {
        const since = url.searchParams.get('since');
        if (since !== null && timestamp(since) === null) return jsonResponse(request, env, { error_code: 'INVALID_SINCE', error: '查询时间格式无效' }, 400);
        return legacyStatus(request, env, code, since === null ? null : timestamp(since));
      }
      if (!bindingsReady(env)) return jsonResponse(request, env, { error_code: 'COORDINATOR_UNAVAILABLE', error: '任务协调与额度服务尚未配置，暂不接受新查询' }, 503);
      let input = { code, job_id, ip: request.headers.get('CF-Connecting-IP') || 'unknown' };
      if (url.pathname === '/query') {
        const mode = body.mode ?? 'current';
        const history_weeks = mode === 'current' ? 0 : Number(body.history_weeks ?? 104);
        if (!['current', 'history'].includes(mode) || (mode === 'history' && (!Number.isInteger(history_weeks) || history_weeks < 1 || history_weeks > 156))) {
          return jsonResponse(request, env, { error_code: 'INVALID_MODE', error: '请选择当前分析，或1至156周历史回放' }, 400);
        }
        input = { ...input, mode, history_weeks };
      }
      // Quotes must not wait behind a slow GitHub dispatch or status lookup for this stock.
      const objectName = url.pathname === '/market' ? `market:${code}` : code;
      const response = await internal(env.STOCK_JOBS, objectName, url.pathname, input);
      const output = await response.json();
      return jsonResponse(request, env, output, response.status,
        response.status === 429 ? { 'Retry-After': String(output.retry_after || 60) } : {});
    } catch {
      return jsonResponse(request, env, { error_code: 'UPSTREAM_UNAVAILABLE', error: '服务暂时不可用，请稍后重试' }, 502);
    }
  },
};
