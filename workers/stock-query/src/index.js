import { AI_SYSTEM_PROMPT, aiBlocked } from './ai-policy.js';

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
const INDEX_TTL_MS = 60_000;
const NEWS_TTL_SECONDS = 60;
const NEWS_TIMEOUT_MS = 8000;
const QUOTE_TTL_SECONDS = 60;
const QUOTE_TIMEOUT_MS = 5000;
const KLINE_TIMEOUT_MS = 8000;
// The chart waits 12 seconds for both sequential minute-data sources combined.
const INTRADAY_SOURCE_TIMEOUT_MS = 5000;
const KLINE_PERIODS = new Set(['30', '60', 'd']);
const AI_TIMEOUT_MS = 60_000;
const AI_MAX_BODY_BYTES = 64 * 1024;
const QUOTE_CODE_PATTERN = /^(?:(?:sh|sz|bj)\d{6}|us[A-Za-z.]{1,10})$/;
const AI_PAGES = new Set(['home', 'stock', 'index', 'backtest', 'market', 'tools']);
const CLS_ROLL_URL = 'https://www.cls.cn/v1/roll/get_roll_list';
const EM_FAST_NEWS_URL = 'https://np-weblist.eastmoney.com/comm/web/getFastNewsList';
const NEWS_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36';
const SUCCESS_STATUSES = new Set([
  'success', 'eligible', 'insufficient_history', 'st_degenerate', 'degenerate',
  'st', 'suspended', 'delisted_or_long_suspended',
]);
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const QUARTER_HOUR_MS = 15 * 60 * 1000;
const WORKER_CRON_SLOTS = [
  { weekdays: [1, 2, 3, 4, 5], minuteOfDay: 15 * 60 + 45, eventTypes: ['market_daily', 'index_daily'] },
  { weekdays: [1, 2, 3, 4, 5], minuteOfDay: 17 * 60, eventTypes: ['dip_env', 'forward_log_seal'] },
  { weekdays: [1, 2, 3, 4, 5], minuteOfDay: 16 * 60 + 30, eventTypes: ['market_daily'] },
  { weekdays: [1, 2, 3, 4, 5], minuteOfDay: 16 * 60 + 45, eventTypes: ['market_daily'] },
  { weekdays: [1, 2, 3, 4, 5], minuteOfDay: 17 * 60 + 30, eventTypes: ['market_daily'] },
  { weekdays: [1, 2, 3, 4, 5], minuteOfDay: 19 * 60, eventTypes: ['market_daily', 'index_daily'] },
  { weekdays: [1, 2, 3, 4, 5], minuteOfDay: 23 * 60 + 15, eventTypes: ['nt_etf_daily'] },
  { weekdays: [2, 3, 4, 5, 6], minuteOfDay: 6 * 60 + 30, eventTypes: ['macro_daily', 'growth_daily', 'us_nightly'] },
  { weekdays: [2, 3, 4, 5, 6], minuteOfDay: 9 * 60 + 15, eventTypes: ['nt_etf_daily'] },
];

function beijingSlot(scheduledTimeMs) {
  if (typeof scheduledTimeMs !== 'number' || !Number.isFinite(scheduledTimeMs)) return null;
  const slotMs = Math.floor((scheduledTimeMs + BEIJING_OFFSET_MS) / QUARTER_HOUR_MS) * QUARTER_HOUR_MS;
  const date = new Date(slotMs);
  return {
    weekday: date.getUTCDay(),
    minuteOfDay: date.getUTCHours() * 60 + date.getUTCMinutes(),
    label: `${date.toISOString().slice(0, 16).replace('T', ' ')} Asia/Shanghai`,
  };
}

export function dispatchesForSlot(scheduledTimeMs) {
  const slot = beijingSlot(scheduledTimeMs);
  if (!slot) return [];
  const match = WORKER_CRON_SLOTS.find(({ weekdays, minuteOfDay }) =>
    weekdays.includes(slot.weekday) && minuteOfDay === slot.minuteOfDay);
  return match ? [...match.eventTypes] : [];
}

export function lastCloseInstant(now = new Date()) {
  const instant = now instanceof Date ? now.getTime() : Number(now);
  if (!Number.isFinite(instant)) return NaN;
  const shanghai = new Date(instant + 8 * 60 * 60 * 1000);
  let cutoff = Date.UTC(shanghai.getUTCFullYear(), shanghai.getUTCMonth(), shanghai.getUTCDate(), 7, 30);
  if (cutoff > instant) cutoff -= 24 * 60 * 60 * 1000;
  while ([0, 6].includes(new Date(cutoff).getUTCDay())) cutoff -= 24 * 60 * 60 * 1000;
  return cutoff;
}

function validAsOfDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

function reusableCurrent(entry, now) {
  const generatedAt = Object.hasOwn(entry || {}, 'current_generated_at')
    ? entry.current_generated_at : entry?.generated_at;
  const lastClose = lastCloseInstant(now);
  const lastCloseDate = new Date(lastClose + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const queryRun = typeof entry?.job_id === 'string' && entry.job_id.length > 0;
  return entry && typeof entry === 'object' && SUCCESS_STATUSES.has(entry.status)
    && validAsOfDate(entry.asof) && typeof entry.fit_code_version === 'string' && entry.fit_code_version.length > 0
    && SHA_PATTERN.test(entry.source_sha || '') && timestamp(generatedAt) !== null
    && Date.parse(generatedAt) >= lastClose
    && (entry.asof >= lastCloseDate || queryRun);
}

async function readPublishedIndex(env) {
  return fetchJSON(`https://api.github.com/repos/${repo(env)}/contents/stock/index.json?ref=stock-results`,
    { headers: githubHeaders(env, 'application/vnd.github.raw') });
}

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

const MD5_SHIFTS = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
  5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
  4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
  6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
];
const MD5_CONSTANTS = Array.from({ length: 64 }, (_unused, i) =>
  Math.floor(Math.abs(Math.sin(i + 1)) * 0x100000000) >>> 0);

export function md5(value) {
  const bytes = new TextEncoder().encode(String(value));
  const length = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(length);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  const bitLength = bytes.length * 8;
  view.setUint32(length - 8, bitLength >>> 0, true);
  view.setUint32(length - 4, Math.floor(bitLength / 0x100000000), true);

  let a0 = 0x67452301;
  let b0 = 0xefcdab89;
  let c0 = 0x98badcfe;
  let d0 = 0x10325476;
  for (let offset = 0; offset < length; offset += 64) {
    let a = a0, b = b0, c = c0, d = d0;
    const words = Array.from({ length: 16 }, (_unused, i) => view.getUint32(offset + i * 4, true));
    for (let i = 0; i < 64; i += 1) {
      let f, g;
      if (i < 16) {
        f = (b & c) | (~b & d);
        g = i;
      } else if (i < 32) {
        f = (d & b) | (~d & c);
        g = (5 * i + 1) % 16;
      } else if (i < 48) {
        f = b ^ c ^ d;
        g = (3 * i + 5) % 16;
      } else {
        f = c ^ (b | ~d);
        g = (7 * i) % 16;
      }
      const sum = (f + a + MD5_CONSTANTS[i] + words[g]) >>> 0;
      const shift = MD5_SHIFTS[i];
      const rotated = ((sum << shift) | (sum >>> (32 - shift))) >>> 0;
      a = d;
      d = c;
      c = b;
      b = (b + rotated) >>> 0;
    }
    a0 = (a0 + a) >>> 0;
    b0 = (b0 + b) >>> 0;
    c0 = (c0 + c) >>> 0;
    d0 = (d0 + d) >>> 0;
  }
  const digest = new Uint8Array(16);
  const digestView = new DataView(digest.buffer);
  [a0, b0, c0, d0].forEach((word, i) => digestView.setUint32(i * 4, word, true));
  return [...digest].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function clsSignature(query) {
  const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(query));
  const sha1 = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return md5(sha1);
}

function shanghaiTime(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

function safeNewsUrl(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

function parseClsNews(payload) {
  const rows = payload?.data?.roll_data;
  if (!Array.isArray(rows)) throw new Error('invalid_response');
  return rows.slice(0, 30).map((item) => {
    if (!item || typeof item !== 'object' || !['title', 'brief', 'ctime'].every((key) => key in item)) {
      throw new Error('invalid_response');
    }
    const timestamp = Number(item.ctime);
    if (!Number.isFinite(timestamp)) throw new Error('invalid_response');
    const row = {
      source: '财联社',
      time: shanghaiTime(new Date(timestamp * 1000)),
      title: String(item.title || String(item.brief || '').slice(0, 80)),
    };
    const url = ['shareurl', 'share_url', 'detail_url', 'url']
      .map((field) => safeNewsUrl(item[field]))
      .find(Boolean);
    if (url) row.url = url;
    return row;
  });
}

function parseEastmoneyNewsTime(value) {
  const text = String(value || '').trim();
  const localTime = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(text);
  const normalized = localTime ? `${text.replace(' ', 'T')}+08:00` : text;
  const date = new Date(normalized);
  if (!Number.isFinite(date.getTime())) throw new Error('invalid_response');
  return shanghaiTime(date);
}

function parseEastmoneyNews(payload) {
  const rows = payload?.data?.fastNewsList;
  if (!Array.isArray(rows)) throw new Error('invalid_response');
  return rows.slice(0, 30).map((item) => {
    if (!item || typeof item !== 'object'
      || !['title', 'summary', 'showTime'].every((key) => key in item)) {
      throw new Error('invalid_response');
    }
    const row = {
      source: '东方财富',
      time: parseEastmoneyNewsTime(item.showTime),
      title: String(item.title || String(item.summary || '').slice(0, 80)),
    };
    const url = ['shareUrl', 'share_url', 'detailUrl', 'detail_url', 'url']
      .map((field) => safeNewsUrl(item[field]))
      .find(Boolean);
    if (url) row.url = url;
    return row;
  });
}

export async function fetchNewsSource(url, headers, parser, timeoutMs = NEWS_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { headers, signal: controller.signal });
    if (!response.ok) return { ok: false, error: `http_${response.status}`, rows: [] };
    let payload;
    try { payload = await response.json(); }
    catch {
      return { ok: false, error: controller.signal.aborted ? 'timeout' : 'invalid_json', rows: [] };
    }
    try { return { ok: true, rows: parser(payload) }; }
    catch { return { ok: false, error: 'invalid_response', rows: [] }; }
  } catch (error) {
    return {
      ok: false,
      error: controller.signal.aborted || error?.name === 'AbortError' ? 'timeout' : 'request_failed',
      rows: [],
    };
  } finally {
    clearTimeout(timer);
  }
}

async function fetchLiveNewsSources() {
  const clsParams = {
    appName: 'CailianpressWeb',
    os: 'web',
    sv: '7.7.5',
    last_time: '',
    refresh_type: '1',
    rn: '50',
  };
  const clsQuery = Object.keys(clsParams).sort().map((key) => `${key}=${clsParams[key]}`).join('&');
  const clsSign = await clsSignature(clsQuery);
  const clsUrl = `${CLS_ROLL_URL}?${clsQuery}&sign=${clsSign}`;
  const clsHeaders = {
    Accept: 'application/json, text/plain, */*',
    Referer: 'https://www.cls.cn/',
    'User-Agent': NEWS_USER_AGENT,
  };

  const emParams = new URLSearchParams({
    client: 'web',
    biz: 'web_724',
    fastColumn: '102',
    sortEnd: '',
    pageSize: '50',
    req_trace: crypto.randomUUID(),
  });
  const emHeaders = {
    Accept: 'application/json, text/plain, */*',
    Referer: 'https://kuaixun.eastmoney.com/',
    'User-Agent': NEWS_USER_AGENT,
  };
  return Promise.all([
    fetchNewsSource(clsUrl, clsHeaders, parseClsNews),
    fetchNewsSource(`${EM_FAST_NEWS_URL}?${emParams}`, emHeaders, parseEastmoneyNews),
  ]);
}

export const REPLAY_SYMS = new Set(['sh000001', 'sh000016', 'sh000300', 'sh000905', 'sh000688', 'sz399001', 'sz399006']);
const REPLAY_MIN_ASOF = '2005-01-04';

export function replayRequest(sym, asof, now = new Date()) {
  if (!REPLAY_SYMS.has(sym)) return { error_code: 'INVALID_SYM', error: '只支持 7 个站点指数的回看' };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(asof || '')) return { error_code: 'INVALID_ASOF', error: '日期格式应为 YYYY-MM-DD' };
  const d = new Date(`${asof}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== asof) return { error_code: 'INVALID_ASOF', error: '日期无效' };
  if (asof < REPLAY_MIN_ASOF) return { error_code: 'INVALID_ASOF', error: `回看日期不早于 ${REPLAY_MIN_ASOF}` };
  if (asof > closedCutoff(now)) return { error_code: 'INVALID_ASOF', error: '回看日期不能晚于最近已收盘交易日' };
  const day = d.getUTCDay();
  if (day === 0 || day === 6) return { error_code: 'INVALID_ASOF', error: '该日期是周末，不是交易日' };
  return null;
}

const REPLAY_RETRY_AFTER_MS = 30 * 60_000;

/** 失败结果是否仍然“有效”：非交易日等永久失败一直有效；数据源等临时失败 30 分钟后允许重算 */
export function replayFailureActive(data, now = Date.now()) {
  if (!data || data.status !== 'failed') return false;
  if (data.permanent) return true;
  const at = Date.parse(data.failed_at || '');
  return Number.isFinite(at) && now - at < REPLAY_RETRY_AFTER_MS;
}

/** 同一 sym+asof 是否已有排队/运行中的 index_replay（按 run-name 匹配），有则不再 dispatch */
async function replayRunActive(env, sym, asof) {
  const title = `index_replay ${sym} ${asof}`;
  const since = new Date(Date.now() - 45 * 60_000).toISOString();
  const url = `https://api.github.com/repos/${repo(env)}/actions/workflows/index_replay.yml/runs?per_page=30&event=repository_dispatch&created=${encodeURIComponent('>=' + since)}`;
  const response = await fetchJSON(url, { headers: githubHeaders(env) });
  if (response.status !== 200) return false;
  return (response.data?.workflow_runs || []).some((run) => (run.display_title || run.name) === title
    && ['queued', 'in_progress', 'waiting', 'pending', 'requested'].includes(run.status));
}

async function readReplay(env, sym, asof) {
  return fetchJSON(`https://api.github.com/repos/${repo(env)}/contents/index/replay/${sym}_${asof}.json?ref=stock-results`,
    { headers: githubHeaders(env, 'application/vnd.github.raw') });
}

/** 任选指数 + 日期的 as-of 回看：结果已存在直接返回；否则触发 index_replay 工作流（约 10 分钟），页面轮询 /replay/result */
async function indexReplay(request, env, url) {
  const isPost = url.pathname === '/replay';
  if (request.method !== (isPost ? 'POST' : 'GET')) {
    return jsonResponse(request, env, { error_code: 'METHOD_NOT_ALLOWED', error: '请求方法不支持' }, 405);
  }
  let sym, asof;
  if (isPost) {
    let body;
    try { body = await request.json(); } catch { return jsonResponse(request, env, { error_code: 'INVALID_BODY', error: '请求体不是 JSON' }, 400); }
    sym = body?.sym; asof = body?.asof;
  } else {
    sym = url.searchParams.get('sym'); asof = url.searchParams.get('asof');
  }
  sym = String(sym || '').toLowerCase(); asof = String(asof || '');
  const invalid = replayRequest(sym, asof);
  if (invalid) return jsonResponse(request, env, invalid, 400);
  if (!env.GH_TOKEN) return jsonResponse(request, env, { error_code: 'SERVICE_UNAVAILABLE', error: '回看服务未配置' }, 503);
  try {
    const existing = await readReplay(env, sym, asof);
    if (existing.status === 200 && existing.data && typeof existing.data === 'object') {
      const failed = existing.data.status === 'failed';
      if (!failed) {
        return jsonResponse(request, env, { status: 'ready', sym, asof, result: existing.data }, 200, { 'Cache-Control': 'public, max-age=3600' });
      }
      if (replayFailureActive(existing.data)) {
        const left = existing.data.permanent ? null
          : Math.max(1, Math.ceil((REPLAY_RETRY_AFTER_MS - (Date.now() - Date.parse(existing.data.failed_at))) / 60_000));
        return jsonResponse(request, env, { ...existing.data, sym, asof, retry_after_minutes: left }, 200, { 'Cache-Control': 'no-store' });
      }
      /* 过期的临时失败：GET 当作缺失（前端据此 POST 一次），POST 往下走重新 dispatch */
    } else if (existing.status !== 404) {
      throw new Error('replay_store_unavailable');
    }
    if (!isPost) return jsonResponse(request, env, { status: 'missing', sym, asof }, 404, { 'Cache-Control': 'no-store' });
    if (await replayRunActive(env, sym, asof)) {
      return jsonResponse(request, env, { status: 'pending', sym, asof, job_id: null, eta_minutes: 10,
        message: `后台已在按 ${asof} 当日及以前的数据计算，约 10 分钟；算完会保存` }, 202, { 'Cache-Control': 'no-store' });
    }
    const budget = await reserve(env, request.headers.get('CF-Connecting-IP') || 'unknown', 'query');
    if (!budget.ok) return budget;
    const job_id = crypto.randomUUID();
    const response = await fetchJSON(`https://api.github.com/repos/${repo(env)}/dispatches`, {
      method: 'POST', headers: githubHeaders(env),
      body: JSON.stringify({ event_type: 'index_replay', client_payload: { sym, asof, job_id } }),
    });
    if (response.status !== 204) {
      return jsonResponse(request, env, { error_code: 'DISPATCH_FAILED', error: '回看任务未能提交，请稍后重试' }, 502);
    }
    return jsonResponse(request, env, { status: 'pending', sym, asof, job_id, eta_minutes: 10,
      message: `已提交后台计算：只用 ${asof} 当日及以前的数据重新拟合，约 10 分钟；算完会保存，同一日期以后直接显示` }, 202, { 'Cache-Control': 'no-store' });
  } catch {
    return jsonResponse(request, env, { error_code: 'UPSTREAM_UNAVAILABLE', error: '回看服务暂时不可用，请稍后重试' }, 502);
  }
}

async function liveNews(request, env) {
  const origin = request.headers.get('Origin') || 'none';
  const cacheKey = new Request(`https://lppl-stock-query.invalid/news?origin=${encodeURIComponent(origin)}`);
  let cache = null;
  try {
    if (typeof caches !== 'undefined' && caches.default) cache = caches.default;
  } catch { cache = null; }
  if (cache) {
    try {
      const cached = await cache.match(cacheKey);
      if (cached) {
        const response = new Response(cached.body, {
          status: cached.status,
          statusText: cached.statusText,
          headers: cached.headers,
        });
        response.headers.set('X-News-Cache', 'HIT');
        return response;
      }
    } catch { cache = null; }
  }

  const [cls, eastmoney] = await fetchLiveNewsSources();
  const fetchedAt = new Date().toISOString();
  const sources = {
    cls: { ok: cls.ok, ...(cls.error ? { error: cls.error } : {}) },
    eastmoney: { ok: eastmoney.ok, ...(eastmoney.error ? { error: eastmoney.error } : {}) },
  };
  if (!cls.ok && !eastmoney.ok) {
    return jsonResponse(request, env, {
      ok: false,
      error_code: 'NEWS_UNAVAILABLE',
      error: '实时快讯来源暂不可用',
      fetched_at: fetchedAt,
      cls: [],
      eastmoney: [],
      sources,
    }, 502, { 'X-News-Cache': cache ? 'MISS' : 'BYPASS' });
  }

  const response = jsonResponse(request, env, {
    ok: true,
    fetched_at: fetchedAt,
    cls: cls.rows,
    eastmoney: eastmoney.rows,
    sources,
  }, 200, {
    'Cache-Control': `public, max-age=${NEWS_TTL_SECONDS}`,
    'X-News-Cache': cache ? 'MISS' : 'BYPASS',
  });
  if (cache) {
    try { await cache.put(cacheKey, response.clone()); }
    catch { /* A cache failure must not hide available live data. */ }
  }
  return response;
}

function aiInput(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
  const question = typeof body.question === 'string' ? body.question.trim() : '';
  const context = body.context;
  const history = Object.hasOwn(body, 'history') ? body.history : [];
  if (!AI_PAGES.has(body.page) || question.length < 1 || question.length > 500
    || typeof context !== 'string' || context.length > 8000
    || !Array.isArray(history) || history.length > 6
    || history.some((item) => !item || typeof item !== 'object' || Array.isArray(item)
      || !['user', 'assistant'].includes(item.role)
      || typeof item.content !== 'string' || item.content.length > 1500)) return null;
  return {
    question,
    context,
    history: history.map((item) => ({ role: item.role, content: item.content })),
  };
}

function aiEvent(value) {
  return new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`);
}

async function aiChat(request, env) {
  if (!env.DEEPSEEK_API_KEY) {
    return jsonResponse(request, env,
      { error_code: 'SERVICE_UNAVAILABLE', error: '研究助手未配置' }, 503);
  }

  const contentLength = request.headers.get('Content-Length');
  if (contentLength !== null && Number(contentLength) > AI_MAX_BODY_BYTES) {
    return jsonResponse(request, env,
      { error_code: 'PAYLOAD_TOO_LARGE', error: '请求内容过长' }, 413);
  }

  let raw;
  try { raw = await request.arrayBuffer(); }
  catch {
    return jsonResponse(request, env,
      { error_code: 'BAD_REQUEST', error: '请求内容不符合要求' }, 400);
  }
  if (raw.byteLength > AI_MAX_BODY_BYTES) {
    return jsonResponse(request, env,
      { error_code: 'PAYLOAD_TOO_LARGE', error: '请求内容过长' }, 413);
  }
  let body;
  try { body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw)); }
  catch {
    return jsonResponse(request, env,
      { error_code: 'BAD_REQUEST', error: '请求内容不符合要求' }, 400);
  }
  const input = aiInput(body);
  if (!input) {
    return jsonResponse(request, env,
      { error_code: 'BAD_REQUEST', error: '请求内容不符合要求' }, 400);
  }

  let reservation;
  try {
    reservation = await reserve(env, request.headers.get('CF-Connecting-IP') || 'unknown', 'ai');
  } catch {
    return jsonResponse(request, env,
      { error_code: 'SERVICE_UNAVAILABLE', error: '研究助手暂时不可用' }, 503);
  }
  if (!reservation.ok) {
    let result = {};
    try { result = await reservation.json(); } catch { /* Keep a stable public error. */ }
    return jsonResponse(request, env, {
      error_code: result.error_code || 'SERVICE_UNAVAILABLE',
      error: result.error || '研究助手暂时不可用',
    }, reservation.status, reservation.status === 429
      ? { 'Retry-After': String(result.retry_after || 60) } : {});
  }

  const abortController = new AbortController();
  const timeout = setTimeout(() => abortController.abort(), AI_TIMEOUT_MS);
  const messages = [
    { role: 'system', content: AI_SYSTEM_PROMPT },
    ...input.history,
    {
      role: 'user',
      content: `〈页面数据〉\n${input.context || '（页面没有提供数据）'}\n〈/页面数据〉\n\n问题：${input.question}`,
    },
  ];
  let upstream;
  try {
    upstream = await fetch('https://api.deepseek.com/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: env.AI_MODEL || 'deepseek-flash',
        stream: true,
        thinking: { type: 'disabled' },
        temperature: 0.3,
        max_tokens: 1200,
        messages,
      }),
      signal: abortController.signal,
    });
  } catch {
    clearTimeout(timeout);
    return jsonResponse(request, env, {
      error_code: 'UPSTREAM_FAILED',
      error: '研究助手暂时不可用',
    }, 502);
  }
  if (!upstream.ok) {
    clearTimeout(timeout);
    return jsonResponse(request, env, {
      error_code: 'UPSTREAM_FAILED',
      error: upstream.status === 429 ? '模型服务繁忙，请稍后再试' : '研究助手暂时不可用',
    }, 502);
  }

  const headers = corsHeaders(request, env);
  headers.set('Content-Type', 'text/event-stream; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  if (!upstream.body) {
    clearTimeout(timeout);
    return new Response(aiEvent({ done: true }), { headers });
  }

  const reader = upstream.body.getReader();
  let accumulated = '';
  let closed = false;
  const stream = new ReadableStream({
    start(controller) {
      const close = () => {
        if (closed) return;
        closed = true;
        clearTimeout(timeout);
        try { controller.close(); } catch { /* Client may have cancelled the stream. */ }
      };
      const fail = () => {
        if (closed) return;
        abortController.abort();
        void reader.cancel().catch(() => {});
        try { controller.enqueue(aiEvent({ error: '研究助手连接中断' })); } catch {}
        close();
      };
      const emitLine = (line) => {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) return false;
        const data = trimmed.slice(5).trim();
        if (!data) return false;
        if (data === '[DONE]') {
          controller.enqueue(aiEvent({ done: true }));
          void reader.cancel().catch(() => {});
          close();
          return true;
        }
        const event = JSON.parse(data);
        const piece = event?.choices?.[0]?.delta?.content;
        if (typeof piece !== 'string') return false;
        accumulated += piece;
        if (aiBlocked(accumulated)) {
          abortController.abort();
          void reader.cancel().catch(() => {});
          controller.enqueue(aiEvent({ blocked: true }));
          close();
          return true;
        }
        controller.enqueue(aiEvent({ delta: piece }));
        return false;
      };
      const pump = async () => {
        const decoder = new TextDecoder();
        let pending = '';
        try {
          while (!closed) {
            const { done, value } = await reader.read();
            pending += decoder.decode(value || new Uint8Array(), { stream: !done });
            const lines = pending.split('\n');
            pending = lines.pop() || '';
            for (const line of lines) {
              if (emitLine(line.replace(/\r$/, ''))) return;
            }
            if (done) {
              if (pending && emitLine(pending.replace(/\r$/, ''))) return;
              controller.enqueue(aiEvent({ done: true }));
              close();
              return;
            }
          }
        } catch {
          fail();
        } finally {
          try { reader.releaseLock(); } catch { /* The reader may already be released. */ }
        }
      };
      void pump();
    },
    cancel() {
      closed = true;
      abortController.abort();
      clearTimeout(timeout);
      void reader.cancel().catch(() => {});
    },
  });
  return new Response(stream, { headers });
}

function normalizeQuoteCode(value) {
  if (typeof value !== 'string') return null;
  if (/^(?:sh|sz|bj)\d{6}$/.test(value)) return value;
  if (/^us[A-Za-z.]{1,10}$/.test(value)) return 'us' + value.slice(2).toUpperCase();
  return null;
}

function normalizeQuoteCodes(value) {
  if (typeof value !== 'string' || !value) return null;
  const rawCodes = value.split(',').map(code => code.trim());
  if (!rawCodes.length || rawCodes.length > 60 || rawCodes.some(code => !QUOTE_CODE_PATTERN.test(code))) return null;
  const codes = rawCodes.map(normalizeQuoteCode);
  if (codes.some(code => !code)) return null;
  return [...new Set(codes)].sort();
}

function quoteNumber(fields, index) {
  const raw = String(fields[index] ?? '').trim();
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function parseTencentQuotes(text, codes) {
  const requested = new Set(codes);
  const quotes = {};
  let matched = false;
  for (const row of String(text).matchAll(/v_([A-Za-z0-9.]+)="([^"]*)"/g)) {
    const code = row[1];
    if (!requested.has(code)) continue;
    matched = true;
    const fields = row[2].split('~');
    const price = quoteNumber(fields, 3);
    if (price === null || price <= 0) continue;
    quotes[code] = {
      price,
      prev_close: quoteNumber(fields, 4),
      open: quoteNumber(fields, 5),
      high: quoteNumber(fields, 33),
      low: quoteNumber(fields, 34),
      change: quoteNumber(fields, 31),
      pct: quoteNumber(fields, 32),
      time: String(fields[30] ?? ''),
      tz: code.startsWith('us') ? 'America/New_York' : 'Asia/Shanghai',
    };
  }
  return { matched, quotes, missing: codes.filter(code => !Object.hasOwn(quotes, code)) };
}

async function fetchTencentQuotes(codes) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), QUOTE_TIMEOUT_MS);
  try {
    const response = await fetch(`https://qt.gtimg.cn/q=${codes.join(',')}`, { signal: controller.signal });
    if (!response.ok) throw new Error(`http_${response.status}`);
    const parsed = parseTencentQuotes(await response.text(), codes);
    if (!parsed.matched) throw new Error('invalid_response');
    return parsed;
  } finally {
    clearTimeout(timeout);
  }
}

async function liveQuote(request, env, url) {
  const codes = normalizeQuoteCodes(url.searchParams.get('codes'));
  if (!codes) {
    return jsonResponse(request, env, { error_code: 'INVALID_CODES', error: '请输入有效的标的代码（最多 60 个）' }, 400);
  }
  const origin = request.headers.get('Origin') || 'none';
  const cacheKey = new Request(`https://lppl-stock-query.invalid/quote?codes=${encodeURIComponent(codes.join(','))}&origin=${encodeURIComponent(origin)}`);
  let cache = null;
  try {
    if (typeof caches !== 'undefined' && caches.default) cache = caches.default;
  } catch { cache = null; }
  if (cache) {
    try {
      const cached = await cache.match(cacheKey);
      if (cached) {
        const response = new Response(cached.body, {
          status: cached.status,
          statusText: cached.statusText,
          headers: cached.headers,
        });
        response.headers.set('X-Quote-Cache', 'HIT');
        return response;
      }
    } catch { cache = null; }
  }

  try {
    const data = await fetchTencentQuotes(codes);
    const response = jsonResponse(request, env, {
      source: 'tencent',
      fetched_at: new Date().toISOString(),
      quotes: data.quotes,
      missing: data.missing,
    }, 200, {
      'Cache-Control': `public, max-age=${QUOTE_TTL_SECONDS}`,
      'X-Quote-Cache': cache ? 'MISS' : 'BYPASS',
    });
    if (cache) {
      try { await cache.put(cacheKey, response.clone()); }
      catch { /* A cache failure must not hide available quote data. */ }
    }
    return response;
  } catch {
    return jsonResponse(request, env, {
      error_code: 'QUOTE_UPSTREAM_FAILED',
      error: '腾讯行情暂时不可用',
    }, 502, { 'X-Quote-Cache': cache ? 'MISS' : 'BYPASS' });
  }
}

async function fetchKlinePayload(url, timeoutMs = KLINE_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json, text/plain, */*' },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`http_${response.status}`);
    const text = await response.text();
    if (text.length > 2_000_000) throw new Error('upstream_body_too_large');
    try { return JSON.parse(text); }
    catch { throw new Error(controller.signal.aborted ? 'timeout' : 'invalid_json'); }
  } catch (error) {
    if (controller.signal.aborted || error?.name === 'AbortError') throw new Error('timeout');
    throw new Error(/^(http_\d+|upstream_body_too_large|invalid_json)$/.test(error?.message || '')
      ? error.message : 'request_failed');
  } finally {
    clearTimeout(timer);
  }
}

async function fetchIntradayKline(code, period) {
  const symbol = klineSymbol(code);
  const sina = new URL('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData');
  sina.searchParams.set('symbol', symbol);
  sina.searchParams.set('scale', period);
  sina.searchParams.set('ma', 'no');
  sina.searchParams.set('datalen', '1023');
  try {
    const payload = await fetchKlinePayload(sina.toString(), INTRADAY_SOURCE_TIMEOUT_MS);
    return { bars: normalizeKlineBars(payload, period), source: 'sina' };
  } catch (sinaError) {
    const tencent = new URL('https://ifzq.gtimg.cn/appstock/app/kline/mkline');
    tencent.searchParams.set('param', `${symbol},m${period},,640`);
    try {
      const payload = await fetchKlinePayload(tencent.toString(), INTRADAY_SOURCE_TIMEOUT_MS);
      const rows = payload?.data?.[symbol]?.[`m${period}`];
      return { bars: normalizeKlineBars(rows, period), source: 'tencent' };
    } catch (tencentError) {
      throw new Error(`Sina: ${sinaError.message}; Tencent: ${tencentError.message}`);
    }
  }
}

async function fetchDailyKline(code) {
  const symbol = klineSymbol(code);
  const url = new URL('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get');
  url.searchParams.set('param', `${symbol},day,,,500,qfq`);
  const payload = await fetchKlinePayload(url.toString());
  const rows = payload?.data?.[symbol]?.qfqday;
  return { bars: normalizeKlineBars(rows, 'd'), source: 'tencent_fqkline_qfq' };
}

async function liveKline(request, env, url) {
  if (request.method !== 'GET') {
    return jsonResponse(request, env, { error_code: 'METHOD_NOT_ALLOWED', error: '请求方法不支持' }, 405);
  }
  const codes = url.searchParams.getAll('code');
  const periods = url.searchParams.getAll('period');
  const code = codes.length === 1 ? codes[0] : '';
  const period = periods.length === 1 ? periods[0] : '';
  if (!CODE_PATTERN.test(code)) {
    return jsonResponse(request, env, { error_code: 'INVALID_CODE', error: '请输入有效的六位A股代码' }, 400);
  }
  if (!KLINE_PERIODS.has(period)) {
    return jsonResponse(request, env, { error_code: 'INVALID_PERIOD', error: '周期应为 30、60 或 d' }, 400);
  }

  const origin = request.headers.get('Origin') || 'none';
  const cacheKey = new Request(`https://lppl-stock-query.invalid/kline-v2?code=${code}&period=${period}&origin=${encodeURIComponent(origin)}`);
  let cache = null;
  try {
    if (typeof caches !== 'undefined' && caches.default) cache = caches.default;
  } catch { cache = null; }
  if (cache) {
    try {
      const cached = await cache.match(cacheKey);
      const ttlRemaining = cached && Math.floor((Date.parse(cached.headers.get('Expires')) - Date.now()) / 1000);
      if (ttlRemaining > 0) {
        const response = new Response(cached.body, {
          status: cached.status,
          statusText: cached.statusText,
          headers: cached.headers,
        });
        response.headers.set('X-Kline-Cache', 'HIT');
        response.headers.set('Cache-Control', `public, max-age=${Math.min(ttlRemaining, klineCacheTtl())}`);
        return response;
      }
    } catch { cache = null; }
  }

  try {
    const budget = await reserve(env, request.headers.get('CF-Connecting-IP') || 'unknown', 'kline');
    if (!budget.ok) {
      const detail = await budget.json();
      return jsonResponse(request, env, detail, budget.status,
        budget.status === 429 ? { 'Retry-After': String(detail.retry_after || 60) } : {});
    }
  } catch {
    return jsonResponse(request, env, { error_code: 'SERVICE_UNAVAILABLE', error: '行情额度服务暂时不可用' }, 503);
  }

  try {
    const result = period === 'd' ? await fetchDailyKline(code) : await fetchIntradayKline(code, period);
    const computed = obvDivergence(result.bars);
    const first = computed.bars[0]?.t || null;
    const last = computed.bars.at(-1)?.t || null;
    const now = new Date();
    // Minute providers can label the active, still-changing bar with its future end.
    const localNow = new Date(now.getTime() + BEIJING_OFFSET_MS).toISOString().slice(0, 19).replace('T', ' ');
    const intraday = period !== 'd';
    const ttl = klineCacheTtl(now);
    const response = jsonResponse(request, env, {
      schema: 'kline_obv.v1',
      code,
      period,
      source: result.source,
      asof: last,
      fetched_at: now.toISOString(),
      ...(intraday && { last_bar_ended: last <= localNow }),
      bars: computed.bars,
      divergences: intraday ? computed.divergences.filter(event => event.confirmed_at <= localNow) : computed.divergences,
      note: '历史形态描述，不是买卖信号',
      limits: { n_bars: computed.bars.length, first, last },
    }, 200, {
      'Cache-Control': `public, max-age=${ttl}`,
      'Expires': new Date(now.getTime() + ttl * 1000).toUTCString(),
      'X-Kline-Cache': cache ? 'MISS' : 'BYPASS',
    });
    if (cache && ttl > 0) {
      try { await cache.put(cacheKey, response.clone()); }
      catch { /* A cache failure must not hide available kline data. */ }
    }
    return response;
  } catch (error) {
    return jsonResponse(request, env, {
      error_code: 'KLINE_UNAVAILABLE',
      error: error?.message || '上游数据暂时不可用',
    }, 502, { 'X-Kline-Cache': cache ? 'MISS' : 'BYPASS' });
  }
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
    const quoteResource = resource === 'market' || resource === 'kline';
    const windowMs = quoteResource ? 60_000 : 600_000;
    const globalWindow = quoteResource ? 60_000 : resource === 'ai' ? 86_400_000 : 3_600_000;
    state.global = state.global.filter((at) => at > now - globalWindow);
    for (const key of Object.keys(state.ips)) {
      state.ips[key] = state.ips[key].filter((at) => at > now - windowMs);
      if (!state.ips[key].length) delete state.ips[key];
    }
    const perIP = state.ips[ip] || [];
    const ipLimit = quoteResource ? 30 : resource === 'ai'
      ? budgetNumber(this.env, 'AI_PER_IP_10M', 10, 100)
      : budgetNumber(this.env, 'QUERIES_PER_IP_10M', 5, 100);
    const globalLimit = quoteResource ? 300 : resource === 'ai'
      ? budgetNumber(this.env, 'AI_PER_DAY', 200, 5000)
      : budgetNumber(this.env, 'QUERIES_PER_HOUR', 60, 1000);
    if (perIP.length >= ipLimit || state.global.length >= globalLimit) {
      return failure('RATE_LIMITED',
        resource === 'ai' ? '研究助手提问次数暂时用尽，请稍后再试' : '查询额度暂时用尽，请稍后再试',
        429, { retry_after: 60 });
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

function klineSymbol(code) {
  const exchange = code.startsWith('6') ? 'sh' : /^(43|83|87|92)/.test(code) ? 'bj' : 'sz';
  return `${exchange}${code}`;
}

function validKlineTime(value, period) {
  const text = String(value || '').trim().replace('T', ' ');
  if (period === 'd') return /^\d{4}-\d{2}-\d{2}$/.test(text) && validDate(text) ? text : null;
  const compact = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})$/.exec(text);
  const normalized = compact
    ? `${compact[1]}-${compact[2]}-${compact[3]} ${compact[4]}:${compact[5]}`
    : text;
  const match = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::(\d{2}))?$/.exec(normalized);
  if (!match || !validDate(match[1])) return null;
  const hour = Number(match[2].slice(0, 2)), minute = Number(match[2].slice(3, 5));
  const second = Number(match[3] || 0);
  if (hour > 23 || minute > 59 || second > 59) return null;
  return `${match[1]} ${match[2]}:${String(second).padStart(2, '0')}`;
}

function normalizeKlineBars(rows, period) {
  if (!Array.isArray(rows)) throw new Error('invalid_response');
  const unique = new Map();
  for (const row of rows) {
    const values = Array.isArray(row) ? row
      : typeof row === 'string' ? row.split(',')
        : null;
    const time = validKlineTime(values ? values[0] : row?.day, period);
    const open = Number(values ? values[1] : row?.open);
    const close = Number(values ? values[2] : row?.close);
    const high = Number(values ? values[3] : row?.high);
    const low = Number(values ? values[4] : row?.low);
    const volume = Number(values ? values[5] : row?.volume);
    if (!time || ![open, high, low, close, volume].every(Number.isFinite)
      || Math.min(open, high, low, close) <= 0 || volume < 0
      || high < Math.max(open, close, low) || low > Math.min(open, close, high)) continue;
    unique.set(time, { t: time, o: open, h: high, l: low, c: close, v: volume });
  }
  const bars = [...unique.values()].sort((a, b) => a.t.localeCompare(b.t));
  if (!bars.length) throw new Error('empty_data');
  return bars;
}

export function obvDivergence(bars, { pivot = 5, lookback = 60 } = {}) {
  const values = Array.isArray(bars) ? bars : [];
  const withObv = [];
  let obv = 0;
  for (let i = 0; i < values.length; i += 1) {
    const bar = values[i];
    if (i > 0) {
      const previous = Number(values[i - 1]?.c);
      const close = Number(bar?.c);
      const volume = Number(bar?.v);
      if (Number.isFinite(previous) && Number.isFinite(close) && Number.isFinite(volume)) {
        obv += Math.sign(close - previous) * volume;
      }
    }
    withObv.push({ ...bar, obv });
  }

  const highs = [], lows = [];
  for (let i = pivot; i < withObv.length - pivot; i += 1) {
    const high = Number(withObv[i]?.h), low = Number(withObv[i]?.l);
    if (!Number.isFinite(high) || !Number.isFinite(low)) continue;
    let isHigh = true, isLow = true;
    for (let j = i - pivot; j <= i + pivot; j += 1) {
      if (j === i) continue;
      if (Number(withObv[j]?.h) > high) isHigh = false;
      if (Number(withObv[j]?.l) < low) isLow = false;
    }
    if (isHigh) highs.push(i);
    if (isLow) lows.push(i);
  }

  const divergences = [];
  function appendPairs(indices, type, priceChange, oppositeObv) {
    for (let i = 1; i < indices.length; i += 1) {
      const first = indices[i - 1], second = indices[i];
      if (second - first > lookback ||
          !priceChange(withObv[first], withObv[second]) ||
          !oppositeObv(withObv[first].obv, withObv[second].obv)) continue;
      divergences.push({
        type,
        p1: withObv[first].t,
        p2: withObv[second].t,
        confirmed_at: withObv[second + pivot].t,
      });
    }
  }
  appendPairs(highs, 'top',
    (first, second) => Number(second.h) > Number(first.h),
    (first, second) => second < first,
  );
  appendPairs(lows, 'bottom',
    (first, second) => Number(second.l) < Number(first.l),
    (first, second) => second > first,
  );
  divergences.sort((a, b) => a.confirmed_at.localeCompare(b.confirmed_at));
  return { bars: withObv, divergences };
}

export function klineCacheTtl(now = new Date()) {
  const instant = now instanceof Date ? now : new Date(now);
  const shanghai = new Date(instant.getTime() + 8 * 60 * 60 * 1000);
  const weekday = shanghai.getUTCDay();
  if (weekday === 0 || weekday === 6) return 600;
  const minute = shanghai.getUTCHours() * 60 + shanghai.getUTCMinutes();
  for (const [open, close] of [[570, 690], [780, 900]]) {
    if (minute < open) {
      const untilOpenMs = (open - minute) * 60000 - shanghai.getUTCSeconds() * 1000 - shanghai.getUTCMilliseconds();
      return Math.min(600, Math.floor(untilOpenMs / 1000));
    }
    if (minute < close) return 60;
  }
  return 600;
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
    const indexKey = 'published_stock_index';
    let cachedIndex = await this.ctx.storage.get(indexKey);
    if (!cachedIndex || Date.now() - cachedIndex.at >= INDEX_TTL_MS) {
      let value = null;
      try {
        const response = await readPublishedIndex(this.env);
        if (response.status === 200 && response.data && typeof response.data === 'object'
            && !Array.isArray(response.data)) value = response.data[code] ?? null;
      } catch { /* An unavailable or malformed index falls through to normal dispatch. */ }
      cachedIndex = { at: Date.now(), value };
      await this.ctx.storage.put(indexKey, cachedIndex);
    }
    const published = cachedIndex.value;
    if (reusableCurrent(published, Date.now()) &&
        (mode === 'current' || (published.history_compatible === true
          && published.history_asof === published.asof
          && Number.isInteger(published.history_weeks) && published.history_weeks >= history_weeks))) {
      return Response.json({
        schema_version: 'stock_query_v1',
        queued: false,
        cached: true,
        deduped: false,
        code,
        mode,
        history_weeks: mode === 'history' ? published.history_weeks : 0,
        asof: published.asof,
        generated_at: Object.hasOwn(published, 'current_generated_at')
          ? published.current_generated_at : published.generated_at,
        job_id: published.job_id ?? null,
        source_sha: published.source_sha,
        phase: `${mode}_ready`,
        current_ready: true,
        history_ready: mode === 'history',
        reuse_reason: 'published_after_last_close',
      });
    }
    const activeId = await this.ctx.storage.get(`active:${mode}`);
    if (activeId) {
      const active = await this.ctx.storage.get(`job:${activeId}`);
      if (active && ACTIVE.has(active.status)) {
        try { await this.refresh(active); } catch { /* Fail closed: reuse rather than risk another dispatch. */ }
        const sufficientHistory = mode !== 'history' || active.history_weeks >= history_weeks;
        if (ACTIVE.has(active.status) && sufficientHistory) {
          return Response.json(jobResponse(active, true), { status: 202 });
        }
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
  async scheduled(event, env = {}, ctx) {
    const eventTypes = dispatchesForSlot(event?.scheduledTime);
    if (!eventTypes.length) return;
    if (!env.GH_TOKEN) {
      console.error('worker_cron dispatch skipped', { reason: 'GH_TOKEN is missing' });
      return;
    }
    const slot = beijingSlot(event.scheduledTime).label;
    const dispatches = eventTypes.map(async (event_type) => {
      try {
        const response = await fetchJSON(`https://api.github.com/repos/${repo(env)}/dispatches`, {
          method: 'POST',
          headers: githubHeaders(env),
          body: JSON.stringify({
            event_type,
            client_payload: { source: 'worker_cron', slot },
          }),
        });
        if (response.status !== 204) {
          console.error('worker_cron dispatch failed', { event_type, status: response.status });
        }
      } catch {
        console.error('worker_cron dispatch failed', { event_type, status: 'throw' });
      }
    });
    ctx.waitUntil(Promise.allSettled(dispatches));
  },
  async fetch(request, env = {}) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');
    if (origin && origin !== (env.ALLOWED_ORIGIN || DEFAULT_ORIGIN)) {
      return jsonResponse(request, env, { error_code: 'ORIGIN_FORBIDDEN', error: '来源未获允许' }, 403);
    }
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    if (url.pathname === '/health') {
      if (request.method !== 'GET') {
        return jsonResponse(request, env, { error_code: 'METHOD_NOT_ALLOWED', error: '请求方法不支持' }, 405);
      }
      const gh_token = !!env.GH_TOKEN;
      const ok = bindingsReady(env) && gh_token;
      return jsonResponse(request, env, {
        ok,
        service: 'lppl-stock-query',
        time: new Date().toISOString(),
        bindings: { STOCK_JOBS: !!env.STOCK_JOBS, QUERY_BUDGET: !!env.QUERY_BUDGET },
        gh_token,
        ai_key: !!env.DEEPSEEK_API_KEY,
        repo: repo(env),
        allowed_origin: env.ALLOWED_ORIGIN || DEFAULT_ORIGIN,
        routes: ['/health', '/market', '/news', '/ai', '/quote', '/kline', '/query', '/status', '/result', '/replay', '/replay/result'],
      }, ok ? 200 : 503);
    }
    if (url.pathname === '/kline') return liveKline(request, env, url);
    if (url.pathname === '/news') {
      if (request.method !== 'GET') {
        return jsonResponse(request, env, { error_code: 'METHOD_NOT_ALLOWED', error: '请求方法不支持' }, 405);
      }
      return liveNews(request, env);
    }
    if (url.pathname === '/ai') {
      if (request.method !== 'POST') {
        return jsonResponse(request, env, { error_code: 'METHOD_NOT_ALLOWED', error: '请求方法不支持' }, 405);
      }
      return aiChat(request, env);
    }
    if (url.pathname === '/quote') {
      if (request.method !== 'GET') {
        return jsonResponse(request, env, { error_code: 'METHOD_NOT_ALLOWED', error: '请求方法不支持' }, 405);
      }
      return liveQuote(request, env, url);
    }
    if (url.pathname === '/replay' || url.pathname === '/replay/result') {
      return indexReplay(request, env, url);
    }
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
