/* 临界点 · 数据适配层（Devin 维护，Open Design 不改）
   只读后端静态 JSON（站点 lab/mock/data/），不做任何模型计算；取数失败直接抛错，页面显示"数据未加载"。
   字段含义：docs/frontend_contract.md、docs/od_field_mapping.md */
(function (G) {
  'use strict';
  const BASE = (G.LPPL_DATA_BASE || 'lab/mock/data/');
  const QUERY_API = (G.LPPL_QUERY_API || 'https://lppl-stock-query.careypang.workers.dev').replace(/\/$/, '');
  const SYMS = [
    { sym: 'sh000001', name: '上证指数', code: '000001', alias: ['上证', '上证综指', '上证指数'] },
    { sym: 'sh000016', name: '上证50', code: '000016', alias: ['上证50'] },
    { sym: 'sh000300', name: '沪深300', code: '000300', alias: ['沪深300'] },
    { sym: 'sh000905', name: '中证500', code: '000905', alias: ['中证500'] },
    { sym: 'sh000688', name: '科创50', code: '000688', alias: ['科创50', '科创板50'], history: false },
    { sym: 'sz399001', name: '深证成指', code: '399001', alias: ['深证', '深证成指'] },
    { sym: 'sz399006', name: '创业板指', code: '399006', alias: ['创业板', '创业板指'] },
  ];
  const REPLAYS = { sh000001: ['2007-10-12', '2015-06-12'] };
  const HIDE = new Set(['none', 'fail', 'fail_i', 'fail_i_iii', 'dev_only', 'dev_failed', 'pending_cal', 'pending_test']);
  const cache = new Map();

  function resolve(input) {
    const s = String(input || '').trim().replace(/\.(SH|SZ)$/i, '');
    return SYMS.find((x) => x.sym === s.toLowerCase() || x.code === s || x.name === s || x.alias.includes(s)) || null;
  }

  async function fetchJSONBounded(url, options = {}, allowMissing = false, deadlineMs = 12000) {
    const controller = new AbortController();
    let timeout;
    const timeoutError = () => {
      const error = Error('连接暂时超时，任务状态尚未确认；已有结果仍可查看。');
      error.code = 'REQUEST_TIMEOUT';
      return error;
    };
    const deadline = new Promise((resolve, reject) => {
      timeout = setTimeout(() => {
        controller.abort();
        reject(timeoutError());
      }, deadlineMs);
    });
    const operation = async () => {
      const response = await fetch(url, { ...options, signal: controller.signal });
      if (allowMissing && response.status === 404) return null;
      if (!response.ok) {
        const messages = {
          400: '查询参数无效，请检查股票代码。',
          429: '查询较多，请稍后重试；已有结果仍可查看。',
          502: '数据服务暂时不可用，请稍后重试。',
          503: '查询服务暂不可用；已有结果仍可查看。',
        };
        const error = Error(messages[response.status] || '数据读取失败（HTTP ' + response.status + '）');
        error.status = response.status;
        // Preserve only known machine-readable codes; never display the server's raw message.
        const safeCodes = new Set(['JOB_NOT_FOUND', 'RATE_LIMITED', 'DISPATCH_FAILED',
          'SOURCE_UNAVAILABLE', 'SERVICE_UNAVAILABLE', 'COORDINATOR_UNAVAILABLE', 'STATUS_UNAVAILABLE']);
        try {
          const payload = await response.json();
          if (safeCodes.has(payload?.error_code)) error.code = payload.error_code;
        } catch { /* An invalid error body must not obscure the HTTP status. */ }
        throw error;
      }
      return await response.json();
    };
    try { return await Promise.race([operation(), deadline]); }
    catch (error) {
      if (error.name === 'AbortError') throw timeoutError();
      throw error;
    } finally { clearTimeout(timeout); }
  }

  async function getJSON(path) {
    const cached = cache.get(path);
    if (cached && Date.now() - cached.at < 30000) return cached.promise;
    const p = fetchJSONBounded(BASE + path, { cache: 'no-cache' });
    cache.set(path, { at: Date.now(), promise: p });
    p.catch(() => { if (cache.get(path)?.promise === p) cache.delete(path); });
    return p;
  }

  function emptyPayload(data) {
    if (data == null) return true;
    if (Array.isArray(data)) return data.length === 0;
    return typeof data === 'object' && Object.keys(data).length === 0;
  }

  function resultOf(promise, options = {}) {
    if (options.applicable === false) return Promise.resolve({ data: null, reason: 'not_applicable' });
    return Promise.resolve(promise).then((data) => ({
      data,
      reason: (options.empty || emptyPayload)(data) ? 'empty' : null,
    })).catch((error) => ({
      data: null,
      reason: Number(error && error.status) === 404 ? 'unpublished' : 'unavailable',
    }));
  }

  function fetchResult(path, options = {}) {
    if (options.applicable === false) return Promise.resolve({ data: null, reason: 'not_applicable' });
    return resultOf(getJSON(path), options);
  }

  function bars(ph) {
    const n = ph.dates.length, out = new Array(n);
    for (let i = 0; i < n; i++) {
      const c = ph.close[i];
      out[i] = {
        date: ph.dates[i],
        open: ph.open && ph.open[i] != null ? ph.open[i] : c,
        high: ph.high && ph.high[i] != null ? ph.high[i] : c,
        low: ph.low && ph.low[i] != null ? ph.low[i] : c,
        close: c,
        volume: ph.volume ? ph.volume[i] : null,
      };
    }
    return out;
  }

  /** load(input, asof?)：asof 为空取最新；回放只开放 REPLAYS 中的日期 */
  async function load(input, asof) {
    const S = resolve(input);
    if (!S) throw new Error('无法识别：目前只支持 ' + SYMS.map((x) => x.name).join(' / '));
    let file = S.sym + '_latest.json', latest = true;
    if (asof) {
      const ok = REPLAYS[S.sym] || [];
      if (!ok.includes(asof)) {
        const key = S.sym + '@' + asof;
        let R = await replay.result(S.sym, asof);
        if (R.status === 'ready' && R.result) return pack(R.result, S, asof, false, true);
        if (R.status === 'missing' && !replayRequested.has(key)) {
          R = await replay.request(S.sym, asof);
          if (R.status === 'ready' && R.result) return pack(R.result, S, asof, false, true);
          if (R.status === 'pending') replayRequested.add(key);
        }
        if (R.status === 'failed') {
          throw new Error('该日期回看计算失败：' + (R.error || '未知原因') + (R.permanent ? '。请换一个交易日' : '。' + (R.retry_after_minutes || 30) + ' 分钟后可重试'));
        }
        const e = new Error(R.message || ('该日期的回看结果还没有算过，已提交后台按 ' + asof + ' 当日及以前的数据现算，约 10 分钟'));
        e.pending = true; e.sym = S.sym; e.asof = asof; e.job_id = R.job_id || null;
        throw e;
      }
      file = S.sym + '_' + asof + '.json'; latest = false;
    }
    return pack(await getJSON(file), S, asof, latest, false);
  }
  function pack(J, S, asof, latest, replayed) {
    const B = bars(J.price_history);
    return { raw: J, top: J.top || {}, bottom: J.bottom || {}, sym: S, name: J.name || S.name, asof: J.asof || asof, latest, replayed, bars: B, T: B.length - 1 };
  }

  /** 通用回看：任选站点指数 + 日期。result() 只读已存结果（404 → missing，不触发计算）；
      request() 触发一次后台计算，同一页面对同一 sym+asof 只 POST 一次，之后每 30 秒只 GET */
  const replayRequested = new Set();
  const replay = {
    result: async (sym, asof) => {
      const q = '?sym=' + encodeURIComponent(sym) + '&asof=' + encodeURIComponent(asof);
      const r = await fetch(queryApi() + '/replay/result' + q, { cache: 'no-store' });
      if (r.status === 200) return r.json();
      if (r.status === 404) return { status: 'missing', sym, asof };
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || ('回看服务错误 ' + r.status));
    },
    request: async (sym, asof) => {
      const r = await fetch(queryApi() + '/replay', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sym, asof }) });
      const J = await r.json().catch(() => ({}));
      if (r.status === 200 || r.status === 202) return J;
      throw new Error(J.error || ('回看请求失败 ' + r.status));
    },
  };

  /** 证据等级 → {label, show}；show=false 时不得显示数值 */
  function ev(code, levels) {
    const c = code || 'none';
    return { code: c, label: (levels && levels[c]) || c, show: !HIDE.has(c) };
  }

  const catalog = () => getJSON('catalog.json');
  const history = (sym) => getJSON(sym + '_history.json');
  /** 策略回放（事前登记规则的历史回放，不是预测）：未发布时返回 null，页面须显示“策略回测结果未发布” */
  const strategy = (sym) => getJSON('strategy/' + sym + '.json').catch((e) => {
    if (e && (e.status === 404 || /\b404\b/.test(String(e.message || e)))) return null; /* 未发布 */
    throw e; /* 超时 / 5xx：是读取失败，不是未发布 */
  });
  const opt = (p) => getJSON(p).catch(() => null);
  const okCode = (c) => {
    const code = String(c).trim();
    if (/^\d{6}$/.test(code)) return code;
    if (/^US_[A-Z.]{1,6}$/i.test(code)) return 'US_' + code.slice(3).toUpperCase();
    if (/^[A-Z.]{1,6}$/i.test(code)) return 'US_' + code.toUpperCase();
    throw new Error('股票代码须为 6 位数字或 US_ 美股代码');
  };
  const workerCode = (c) => {
    const code = okCode(c);
    if (code.startsWith('US_')) throw new Error('美股仅支持观察清单的预计算数据');
    return code;
  };
  const queryApi = () => {
    if (!QUERY_API) throw new Error('个股公开查询 API 尚未配置');
    return QUERY_API;
  };
  const queryJSON = async (path, options, deadlineMs = 12000) => {
    return fetchJSONBounded(queryApi() + path, options, false, deadlineMs);
  };
  /** 按需个股结果（stock-results 分支经 Pages 叠加）；缺文件返回 null。证据恒为 research_candidate，置信度按 dev_only 不显示数值 */
  const stock = {
    index: () => opt('stock/index.json'),
    usIndex: () => opt('stock/us_index.json'),
    latest: (c) => opt('stock/' + okCode(c) + '.json'),
    history: (c) => opt('stock/' + okCode(c) + '_history.json'),
    dipEnv: () => opt('stock/_dip_env.json'),
    error: (c) => opt('stock/' + okCode(c) + '_error.json'),
    api: () => queryApi(),
    market: (c) => queryJSON('/market?code=' + encodeURIComponent(workerCode(c))),
    request: (c, options = {}) => {
      const code = workerCode(c);
      return queryJSON('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code, mode: options.mode || 'current',
          history_weeks: options.mode === 'history' ? (options.historyWeeks ?? 104) : 0,
        }),
      }, 60000);
    },
    status: (c, since) => {
      const code = workerCode(c);
      if (since && typeof since === 'object') {
        return queryJSON('/status?code=' + encodeURIComponent(code) +
          '&job_id=' + encodeURIComponent(since.jobId), undefined, 45000);
      }
      const sinceParam = since == null ? '' : '&since=' + encodeURIComponent(since);
      return queryJSON('/status?code=' + encodeURIComponent(code) + sinceParam, undefined, 45000);
    },
    remote: async (c, kind = 'latest', options = {}) => {
      const code = workerCode(c);
      if (!['latest', 'history', 'error'].includes(kind)) throw new Error('个股结果类型无效');
      return fetchJSONBounded(
        queryApi() + '/result?code=' + encodeURIComponent(code) + '&kind=' + encodeURIComponent(kind) +
          (options.jobId ? '&job_id=' + encodeURIComponent(options.jobId) : ''),
        { cache: 'no-cache' },
        true,
      );
    },
    /** 成分股广度（夜间预算库，descriptive）：有合格拟合的成分股比例与 n；不是预测、不进模型 */
    breadth: (idx) => { if (!/^(sh|sz)\d{6}$/.test(String(idx))) throw new Error('指数代码须为 sh/sz + 6 位数字'); return opt('stock/breadth_' + idx + '.json'); },
  };
  /** 市场背景（descriptive）；缺文件返回 null */
  const market = () => opt('market/market_latest.json');
  const liveNews = () => queryJSON('/news');
  /** 研究助手：POST /ai，SSE 流式返回；onText(累计文本)。只发送页面上已显示的内容 */
  const askAI = async (payload, onText, signal) => {
    const res = await fetch(queryApi() + '/ai', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal,
    });
    if (!res.ok || !res.body) {
      let msg = '研究助手暂时不可用';
      try { const j = await res.json(); if (j && j.error) msg = j.error; } catch { /* keep default */ }
      const e = new Error(msg); e.status = res.status; throw e;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '', text = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, cut); buf = buf.slice(cut + 2);
        for (const line of block.split('\n')) {
          if (!line.startsWith('data:')) continue;
          let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
          if (typeof ev.delta === 'string') { text += ev.delta; onText?.(text); }
          else if (ev.blocked) return { text, blocked: true };
          else if (ev.error) { const e = new Error(ev.error); e.partial = text; throw e; }
          else if (ev.done) return { text, done: true };
        }
      }
    }
    return { text, done: false };
  };
  const quoteWorkerCode = (symbol) => {
    const value = String(symbol ?? '');
    if (/^(?:sh|sz|bj)\d{6}$/i.test(value)) return value.toLowerCase();
    if (/^US_[A-Za-z.]{1,10}$/i.test(value)) return 'us' + value.slice(3).toUpperCase();
    return null;
  };
  const quoteSymbol = (code) => {
    if (/^(?:sh|sz|bj)\d{6}$/.test(code)) return code;
    if (/^us[A-Za-z.]{1,10}$/.test(code)) return 'US_' + code.slice(2).toUpperCase();
    return null;
  };
  const quoteTimeLabel = (time, tz, now) => {
    const us = tz === 'America/New_York';
    const zone = us ? 'America/New_York' : 'Asia/Shanghai';
    const match = us
      ? /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::\d{2})?$/.exec(String(time || ''))
      : /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(?:\d{2})?$/.exec(String(time || ''));
    if (!match) return { label: '最新成交', time: '—', short: '—' };
    const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
    const hour = Number(match[4]), minute = Number(match[5]);
    const stamp = new Date(Date.UTC(year, month - 1, day, hour, minute));
    if (stamp.getUTCFullYear() !== year || stamp.getUTCMonth() !== month - 1 ||
        stamp.getUTCDate() !== day || hour > 23 || minute > 59) {
      return { label: '最新成交', time: '—', short: '—' };
    }
    const options = { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
    const parts = {};
    new Intl.DateTimeFormat('en-US', options).formatToParts(now == null ? new Date() : new Date(now))
      .forEach((part) => { if (part.type !== 'literal') parts[part.type] = part.value; });
    const sameDay = parts.year === match[1] && parts.month === match[2] && parts.day === match[3];
    const inSession = (value) => us
      ? value >= 570 && value <= 960
      : (value >= 555 && value <= 690) || (value >= 780 && value <= 900);
    const quoteMinute = hour * 60 + minute, currentMinute = Number(parts.hour) * 60 + Number(parts.minute);
    const short = match[4] + ':' + match[5];
    return {
      label: sameDay && inSession(quoteMinute) && inSession(currentMinute) ? '盘中' : '最新成交',
      time: match[2] + '-' + match[3] + ' ' + short,
      short,
    };
  };
  const quote = async (symbols) => {
    const codes = new Map();
    for (const value of Array.isArray(symbols) ? symbols : []) {
      const code = quoteWorkerCode(value);
      if (code && !codes.has(code)) codes.set(code, quoteSymbol(code));
    }
    if (!codes.size) return { quotes: {} };
    const data = await queryJSON('/quote?codes=' + encodeURIComponent([...codes.keys()].join(',')));
    const result = data && typeof data === 'object' ? data : {};
    const quotes = {};
    for (const [code, value] of Object.entries(result.quotes || {})) {
      const symbol = codes.get(code) || quoteSymbol(code);
      if (symbol) quotes[symbol] = value;
    }
    const missing = (Array.isArray(result.missing) ? result.missing : [])
      .map((code) => codes.get(code) || quoteSymbol(code))
      .filter(Boolean);
    return { ...result, quotes, missing };
  };
  const stockList = () => opt('market/stock_list.json');
  const breadth = () => opt('market/breadth_latest.json');
  const ntEtf = () => opt('nt_etf/nt_etf_latest.json');
  const events = () => opt('events/events_latest.json');
  const abnormal = () => opt('market/abnormal_latest.json');
  const bottomSignal = () => opt('market/bottom_signal_latest.json');
  const rangeStats = () => opt('market/range_latest.json');
  const macro = () => opt('macro/macro_latest.json');
  const growthMonitor = () => opt('growth/growth_latest.json');
  const changelog = () => opt('changelog.json');
  G.LPPL = { BASE, SYMS, REPLAYS, resolve, load, replay, strategy, ev, catalog, history, stock, stockList, breadth, liveNews, askAI, quote, quoteTimeLabel, ntEtf, events, abnormal, bottomSignal, rangeStats, macro, market, growthMonitor, changelog, resultOf, fetchResult };
})(window);
