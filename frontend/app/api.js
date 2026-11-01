/* =====================================================================
   临界点 · 数据接口层  (contract v1)
   页面只调用 OD_API.getAnalysis / OD_API.getBench。
   - mode 'local'  : 使用浏览器内置引擎（CP.run），默认
   - mode 'remote' : 请求后端 REST 接口，失败时可回退本地
   配置：window.OD_API_CONFIG = { mode, baseUrl, token, fallback, timeoutMs }
         或网址参数 ?api=http://host:8000 （自动切到 remote）
   字段定义见 docs/api-contract.md
   ===================================================================== */
(function (G) {
  'use strict';
  const q = new URLSearchParams(G.location ? G.location.search : '');
  const user = G.OD_API_CONFIG || {};
  const cfg = {
    mode: user.mode || (q.get('api') ? 'remote' : 'local'),
    baseUrl: (user.baseUrl || q.get('api') || '').replace(/\/+$/, ''),
    token: user.token || '',
    fallback: user.fallback !== false,
    timeoutMs: user.timeoutMs || 120000,
    version: 'v1',
  };

  const CONTRACT = 1;

  // JSON 不能表示 NaN / Infinity，后端用 null；这里还原成 NaN，页面原有判断可继续使用
  const NAN_KEYS = new Set(['recall', 'precision', 'randPrecision', 'medErr', 'topErr', 'dirUp']);
  function revive(o, key) {
    if (o === null) return NAN_KEYS.has(key) ? NaN : null;
    if (Array.isArray(o)) { for (let i = 0; i < o.length; i++) o[i] = revive(o[i], null); return o; }
    if (typeof o === 'object') { for (const k of Object.keys(o)) o[k] = revive(o[k], k); }
    return o;
  }

  class ApiError extends Error {
    constructor(code, message, status) { super(message); this.name = 'ApiError'; this.code = code; this.status = status || 0; }
  }

  function validate(R) {
    const need = ['sym', 'data', 'bars', 'T', 'asof', 'latest', 'scan', 'rm', 'phase', 'tape', 'evalr'];
    for (const k of need) if (R[k] === undefined) throw new ApiError('BAD_SCHEMA', '后端返回缺少字段：' + k);
    if (!Array.isArray(R.bars) || R.bars.length < 2) throw new ApiError('BAD_SCHEMA', 'bars 为空');
    const b = R.bars[0];
    for (const k of ['date', 'open', 'high', 'low', 'close', 'volume']) if (b[k] === undefined) throw new ApiError('BAD_SCHEMA', 'bars[0] 缺少 ' + k);
    if (R.T < 0 || R.T >= R.bars.length) throw new ApiError('BAD_SCHEMA', 'T 越界');
    return R;
  }

  async function http(path, params, signal) {
    const url = new URL(cfg.baseUrl + '/api/' + cfg.version + path, G.location.href);
    Object.keys(params || {}).forEach((k) => { if (params[k] != null && params[k] !== '') url.searchParams.set(k, params[k]); });
    const headers = { Accept: 'application/json' };
    if (cfg.token) headers.Authorization = 'Bearer ' + cfg.token;
    let res;
    try { res = await fetch(url.toString(), { headers, signal }); }
    catch (e) { throw new ApiError('NETWORK', '无法连接后端：' + (e.message || e)); }
    let body = null;
    try { body = await res.json(); } catch (e) { /* 非 JSON */ }
    if (!res.ok) {
      const er = body && body.error;
      throw new ApiError(er && er.code || 'HTTP_' + res.status, er && er.message || '后端错误 ' + res.status, res.status);
    }
    return body;
  }

  // 后端分析可能较慢：支持两种方式
  //  A. 直接返回结果（HTTP 200，{ contract:1, result:{...} }）
  //  B. 返回任务（HTTP 200，{ contract:1, job:{ id, status:'queued|running|done|failed', progress, stage } }），客户端轮询 /jobs/{id}
  async function remoteAnalysis(code, asof, onProg) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), cfg.timeoutMs);
    try {
      onProg && onProg('请求后端分析', 0.02);
      let r = await http('/analysis', { code, asof }, ctl.signal);
      if (r.contract !== CONTRACT) throw new ApiError('CONTRACT', '接口版本不匹配：期望 ' + CONTRACT + '，收到 ' + r.contract);
      while (r.job && r.job.status !== 'done') {
        if (r.job.status === 'failed') throw new ApiError(r.job.errorCode || 'JOB_FAILED', r.job.message || '后端任务失败');
        onProg && onProg(r.job.stage || '后端计算中', r.job.progress || 0.1);
        await new Promise((ok) => setTimeout(ok, 800));
        r = await http('/jobs/' + encodeURIComponent(r.job.id), {}, ctl.signal);
      }
      const R = r.result || (r.job && r.job.result);
      if (!R) throw new ApiError('BAD_SCHEMA', '后端没有返回 result');
      onProg && onProg('完成', 1);
      return validate(revive(R, null));
    } finally { clearTimeout(timer); }
  }

  const API = {
    config: cfg,
    contract: CONTRACT,
    ApiError,
    configure(o) { Object.assign(cfg, o || {}); if (cfg.baseUrl) cfg.baseUrl = cfg.baseUrl.replace(/\/+$/, ''); },

    /** 主入口：返回与 CP.run 同结构的对象 */
    async getAnalysis(code, asof, onProg) {
      if (cfg.mode === 'remote' && cfg.baseUrl) {
        try { const R = await remoteAnalysis(code, asof, onProg); R.backend = 'remote'; return R; }
        catch (e) {
          if (!cfg.fallback || !G.CP || e.code === 'BAD_INPUT') throw e;
          console.warn('[OD_API] 后端失败，回退本地引擎：', e.message);
          const R = await G.CP.run(code, asof, onProg);
          R.backend = 'local'; R.backendError = e.message;
          return R;
        }
      }
      const R = await G.CP.run(code, asof, onProg);
      R.backend = 'local';
      return R;
    },

    /** 三大指数全样本验证（准确率页签） */
    async getBench() {
      if (cfg.mode === 'remote' && cfg.baseUrl) {
        try { const r = await http('/bench', {}); if (r.contract === CONTRACT && Array.isArray(r.result)) return revive(r.result, null); }
        catch (e) { if (!cfg.fallback) throw e; console.warn('[OD_API] bench 回退本地：', e.message); }
      }
      return G.CP.indexBench();
    },

    /** 标的搜索（可选）：后端未实现时返回空数组 */
    async search(keyword) {
      if (cfg.mode === 'remote' && cfg.baseUrl) {
        try { const r = await http('/symbols', { q: keyword }); return r.result || []; } catch (e) { return []; }
      }
      return [];
    },

    /** 健康检查，供设置页或调试使用 */
    async ping() {
      if (!cfg.baseUrl) return { ok: false, reason: '未配置 baseUrl' };
      try { const r = await http('/health', {}); return { ok: true, ...r }; } catch (e) { return { ok: false, reason: e.message }; }
    },
  };
  G.OD_API = API;
})(window);
