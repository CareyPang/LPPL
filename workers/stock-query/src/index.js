const DEFAULT_ORIGIN = 'https://careypang.github.io';
const DEFAULT_REPO = 'CareyPang/LPPL';
const CODE_PATTERN = /^(?:60|68|00|30|43|83|87|92)\d{4}$/;

function corsHeaders(request, env) {
  const headers = new Headers({
    'Vary': 'Origin',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  });
  const origin = request.headers.get('Origin');
  const allowedOrigin = env.ALLOWED_ORIGIN || DEFAULT_ORIGIN;
  if (origin === allowedOrigin) headers.set('Access-Control-Allow-Origin', allowedOrigin);
  return headers;
}

function jsonResponse(request, env, value, status = 200, extraHeaders = {}) {
  const headers = corsHeaders(request, env);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  for (const [name, value] of Object.entries(extraHeaders)) headers.set(name, value);
  return new Response(JSON.stringify(value), { status, headers });
}

function apiResponse(request, env, body, status, contentType = 'application/json; charset=utf-8') {
  const headers = corsHeaders(request, env);
  headers.set('Content-Type', contentType);
  headers.set('Cache-Control', 'max-age=30');
  return new Response(body, { status, headers });
}

function isValidCode(code) {
  return typeof code === 'string' && CODE_PATTERN.test(code);
}

function githubHeaders(env, accept = 'application/vnd.github+json') {
  return {
    Accept: accept,
    Authorization: `Bearer ${env.GH_TOKEN || ''}`,
    'User-Agent': 'lppl-stock-query-worker',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

function githubRepo(env) {
  return env.REPO || DEFAULT_REPO;
}

async function dispatch(request, env, code) {
  const kv = env.RL;
  const ratelimit = kv ? 'enabled' : 'disabled';
  const codeKey = `code:${code}`;
  let dedupeReserved = false;

  if (kv) {
    if (typeof kv.get !== 'function' || typeof kv.put !== 'function' || typeof kv.delete !== 'function') {
      return jsonResponse(
        request,
        env,
        { error: 'Rate limiting is unavailable', ratelimit },
        503,
      );
    }
    try {
      if (await kv.get(codeKey)) {
        return jsonResponse(request, env, { queued: true, deduped: true, ratelimit }, 202);
      }
      const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
      const ipKey = `ip:${encodeURIComponent(ip)}`;
      const parsedCount = Number.parseInt((await kv.get(ipKey)) || '0', 10);
      const currentCount = Number.isFinite(parsedCount) && parsedCount > 0 ? parsedCount : 0;
      if (currentCount >= 5) {
        return jsonResponse(
          request,
          env,
          { error: 'Rate limit exceeded', ratelimit },
          429,
          { 'Retry-After': '600' },
        );
      }
      await kv.put(ipKey, String(currentCount + 1), { expirationTtl: 600 });
      await kv.put(codeKey, '1', { expirationTtl: 900 });
      dedupeReserved = true;
    } catch {
      return jsonResponse(request, env, { error: 'Rate limiting is unavailable', ratelimit }, 503);
    }
  }

  try {
    const response = await fetch(
      `https://api.github.com/repos/${githubRepo(env)}/dispatches`,
      {
        method: 'POST',
        headers: githubHeaders(env),
        body: JSON.stringify({
          event_type: 'stock_query',
          client_payload: { code, variant: 'stk_lite', history_weeks: '104' },
        }),
      },
    );
    if (!response.ok) {
      if (dedupeReserved) await kv.delete(codeKey).catch(() => {});
      return jsonResponse(request, env, { error: 'GitHub dispatch failed', ratelimit }, 502);
    }
    return jsonResponse(request, env, { queued: true, ratelimit }, 202);
  } catch {
    if (dedupeReserved) await kv.delete(codeKey).catch(() => {});
    return jsonResponse(request, env, { error: 'GitHub dispatch failed', ratelimit }, 502);
  }
}

async function status(request, env, code) {
  try {
    const response = await fetch(
      `https://api.github.com/repos/${githubRepo(env)}/actions/workflows/stock_query.yml/runs?per_page=30`,
      { headers: githubHeaders(env) },
    );
    if (!response.ok) return jsonResponse(request, env, { error: 'GitHub status lookup failed' }, 502);
    const data = await response.json();
    const runs = Array.isArray(data.workflow_runs) ? data.workflow_runs : [];
    const run = runs
      .filter((item) => item.display_title === `stock_query ${code}`)
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))[0];
    if (!run) return jsonResponse(request, env, { status: 'none' });
    return jsonResponse(request, env, {
      status: run.status || null,
      conclusion: run.conclusion || null,
      created_at: run.created_at || null,
      updated_at: run.updated_at || null,
      run_url: run.html_url || null,
    });
  } catch {
    return jsonResponse(request, env, { error: 'GitHub status lookup failed' }, 502);
  }
}

async function result(request, env, code, kind) {
  const suffixes = { latest: '.json', history: '_history.json', error: '_error.json' };
  if (!Object.hasOwn(suffixes, kind)) {
    return jsonResponse(request, env, { error: 'kind must be latest, history, or error' }, 400);
  }
  const path = `stock/${code}${suffixes[kind]}`;
  try {
    const response = await fetch(
      `https://api.github.com/repos/${githubRepo(env)}/contents/${path}?ref=stock-results`,
      { headers: githubHeaders(env, 'application/vnd.github.raw') },
    );
    if (response.status === 404) {
      return apiResponse(request, env, await response.text(), 404, 'application/json; charset=utf-8');
    }
    if (!response.ok) return jsonResponse(request, env, { error: 'GitHub result lookup failed' }, 502);
    return apiResponse(request, env, await response.text(), 200);
  } catch {
    return jsonResponse(request, env, { error: 'GitHub result lookup failed' }, 502);
  }
}

export default {
  async fetch(request, env = {}) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');
    const allowedOrigin = env.ALLOWED_ORIGIN || DEFAULT_ORIGIN;
    if (origin && origin !== allowedOrigin) {
      return new Response('Forbidden', { status: 403, headers: { Vary: 'Origin' } });
    }
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }

    if (url.pathname === '/query' && request.method === 'POST') {
      let body;
      try {
        body = await request.json();
      } catch {
        return jsonResponse(request, env, { error: 'Invalid JSON body' }, 400);
      }
      const code = body && body.code;
      if (!isValidCode(code)) return jsonResponse(request, env, { error: 'Invalid A-share code' }, 400);
      return dispatch(request, env, code);
    }

    if (url.pathname === '/status' && request.method === 'GET') {
      const code = url.searchParams.get('code');
      if (!isValidCode(code)) return jsonResponse(request, env, { error: 'Invalid A-share code' }, 400);
      return status(request, env, code);
    }

    if (url.pathname === '/result' && request.method === 'GET') {
      const code = url.searchParams.get('code');
      const kind = url.searchParams.get('kind');
      if (!isValidCode(code)) return jsonResponse(request, env, { error: 'Invalid A-share code' }, 400);
      return result(request, env, code, kind);
    }

    return jsonResponse(request, env, { error: 'Not found' }, 404);
  },
};
