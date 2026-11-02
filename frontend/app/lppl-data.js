/* 临界点 · 数据适配层（Devin 维护，Open Design 不改）
   只读后端静态 JSON（站点 lab/mock/data/），不做任何模型计算；取数失败直接抛错，页面显示"数据未加载"。
   字段含义：docs/frontend_contract.md、docs/od_field_mapping.md */
(function (G) {
  'use strict';
  const BASE = (G.LPPL_DATA_BASE || 'lab/mock/data/');
  const QUERY_API = (G.LPPL_QUERY_API || '').replace(/\/$/, '');
  const SYMS = [
    { sym: 'sh000001', name: '上证指数', code: '000001', alias: ['上证', '上证综指', '上证指数'] },
    { sym: 'sh000016', name: '上证50', code: '000016', alias: ['上证50'] },
    { sym: 'sh000300', name: '沪深300', code: '000300', alias: ['沪深300'] },
    { sym: 'sh000905', name: '中证500', code: '000905', alias: ['中证500'] },
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

  async function getJSON(path) {
    if (cache.has(path)) return cache.get(path);
    const p = fetch(BASE + path, { cache: 'no-cache' }).then((r) => {
      if (!r.ok) throw new Error('数据未加载：' + path + '（HTTP ' + r.status + '）');
      return r.json();
    });
    cache.set(path, p);
    p.catch(() => cache.delete(path));
    return p;
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
      if (!ok.includes(asof)) throw new Error('该日期没有回放数据' + (ok.length ? '（' + S.name + '只开放 ' + ok.join('、') + '）' : '（' + S.name + '暂无回放）'));
      file = S.sym + '_' + asof + '.json'; latest = false;
    }
    const J = await getJSON(file);
    const B = bars(J.price_history);
    return { raw: J, top: J.top || {}, bottom: J.bottom || {}, sym: S, name: J.name || S.name, asof: J.asof, latest, bars: B, T: B.length - 1 };
  }

  /** 证据等级 → {label, show}；show=false 时不得显示数值 */
  function ev(code, levels) {
    const c = code || 'none';
    return { code: c, label: (levels && levels[c]) || c, show: !HIDE.has(c) };
  }

  const catalog = () => getJSON('catalog.json');
  const history = (sym) => getJSON(sym + '_history.json');
  const opt = (p) => getJSON(p).catch(() => null);
  const okCode = (c) => { if (!/^\d{6}$/.test(String(c))) throw new Error('股票代码须为 6 位数字'); return String(c); };
  const queryApi = () => {
    if (!QUERY_API) throw new Error('个股公开查询 API 尚未配置');
    return QUERY_API;
  };
  const queryJSON = async (path, options) => {
    const response = await fetch(queryApi() + path, options);
    if (!response.ok) throw new Error('个股查询失败（HTTP ' + response.status + '）');
    return response.json();
  };
  /** 按需个股结果（stock-results 分支经 Pages 叠加）；缺文件返回 null。证据恒为 research_candidate，置信度按 dev_only 不显示数值 */
  const stock = {
    index: () => opt('stock/index.json'),
    latest: (c) => opt('stock/' + okCode(c) + '.json'),
    history: (c) => opt('stock/' + okCode(c) + '_history.json'),
    error: (c) => opt('stock/' + okCode(c) + '_error.json'),
    api: () => queryApi(),
    request: (c) => {
      const code = okCode(c);
      return queryJSON('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
    },
    status: (c, since) => {
      const code = okCode(c);
      const sinceParam = since == null ? '' : '&since=' + encodeURIComponent(since);
      return queryJSON('/status?code=' + encodeURIComponent(code) + sinceParam);
    },
    remote: async (c, kind = 'latest') => {
      const code = okCode(c);
      if (!['latest', 'history', 'error'].includes(kind)) throw new Error('个股结果类型无效');
      const response = await fetch(
        queryApi() + '/result?code=' + encodeURIComponent(code) + '&kind=' + encodeURIComponent(kind),
      );
      if (response.status === 404) return null;
      if (!response.ok) throw new Error('个股结果读取失败（HTTP ' + response.status + '）');
      return response.json();
    },
    /** 成分股广度（夜间预算库，descriptive）：有合格拟合的成分股比例与 n；不是预测、不进模型 */
    breadth: (idx) => { if (!/^(sh|sz)\d{6}$/.test(String(idx))) throw new Error('指数代码须为 sh/sz + 6 位数字'); return opt('stock/breadth_' + idx + '.json'); },
  };
  /** 市场背景（descriptive）；缺文件返回 null */
  const market = () => opt('market/market_latest.json');
  G.LPPL = { BASE, SYMS, REPLAYS, resolve, load, ev, catalog, history, stock, market };
})(window);
