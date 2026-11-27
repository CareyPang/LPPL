/* 临界点 · 全站侧栏与页面导航（Open Design 维护）
   桌面侧栏提供五个任务入口，窄屏保留页面级导航条
   用法：在页面 <main> 之前放
     <script src="app/od-nav.js" data-section="home|stock|terminal|chart|market|nt|backtest|tools"></script>
   页面可用以下标记把已有元素交给顶栏（元素本身与其脚本逻辑不变）：
     [data-od-sub]   其子元素移入第二层左侧（作为子页签）
     [data-od-tools] 其子元素移入第二层右侧（页面工具）
     [data-od-asof]  该元素移入第一层右侧（数据日期）
   本模块不读取、不计算任何业务数据。 */
(function () {
  'use strict';
  var KOREAN_STOCK = { sym: 'KR_SKHYNIX', code: '000660.KS', name: 'SK 海力士',
    market: 'kr', kind: 'stock', exchange: 'KRX KOSPI', currency: 'KRW', timezone: 'Asia/Seoul',
    provider_symbol: '000660.KS', alias: ['SK Hynix', '海力士', 'SK하이닉스'] };
  /* Identity-only routing: a search hit must keep its asset kind. A missing
     match is never replaced with a default index or a guessed market. */
  var SearchRoutes = (function () {
    var GLOBAL_INDICES = [
      { sym: 'US_SPX', code: 'US_SPX', name: '标普500', alias: ['SPX', '^GSPC', 'SP500', 'S&P500', 'S&P 500', '标普'] },
      { sym: 'US_IXIC', code: 'US_IXIC', name: '纳斯达克综合指数', alias: ['IXIC', '^IXIC', 'NASDAQ Composite', '纳指综合', '纳斯达克综合'] },
      { sym: 'US_NDX', code: 'US_NDX', name: '纳斯达克100', alias: ['NDX', '^NDX', 'NASDAQ100', 'NASDAQ 100', '纳指100'] },
      { sym: 'US_DJI', code: 'US_DJI', name: '道琼斯工业指数', alias: ['DJI', '^DJI', 'DOW', '道琼斯', '道指'] },
      { sym: 'JP_N225', code: 'JP_N225', name: '日经225', alias: ['N225', '^N225', 'NIKKEI', 'NIKKEI225', '日经'] },
      { sym: 'KR_KOSPI', code: 'KR_KOSPI', name: '韩国综合指数', alias: ['KOSPI', 'KOPSI', '^KS11', '韩国综合', '韩综指'] },
      { sym: 'KR_KOSDAQ', code: 'KR_KOSDAQ', name: '韩国创业板', alias: ['KOSDAQ', '^KQ11', '韩国创业板指数'] }
    ];
    function key(value) { return String(value || '').trim().toUpperCase().replace(/\s+/g, ''); }
    function catalog(indices, extra) {
      var out = [], seen = Object.create(null);
      (indices || []).concat(extra || [], GLOBAL_INDICES).forEach(function (item) {
        if (!item || !item.sym || item.kind && item.kind !== 'index' || seen[key(item.sym)]) return;
        var fallback = GLOBAL_INDICES.find(function (entry) { return key(entry.sym) === key(item.sym); }) || {};
        seen[key(item.sym)] = true;
        out.push(Object.assign({}, fallback, item, { code: item.code || item.sym,
          alias: Array.from(new Set((fallback.alias || []).concat(item.alias || []))) }));
      });
      return out;
    }
    function findIndex(value, indices) {
      var target = key(value);
      return target && (indices || []).find(function (item) {
        return [item.sym, item.code, item.name].concat(item.alias || []).some(function (alias) { return key(alias) === target; });
      }) || null;
    }
    function rowCode(row) { return String(Array.isArray(row) ? row[0] : row && row.code || ''); }
    function knownStock(code, rows, published) {
      return (rows || []).some(function (row) { return key(rowCode(row)) === key(code); }) ||
        !!(published && typeof published.has === 'function' && published.has(code));
    }
    function route(hit, indices, rows, published) {
      if (!hit) return null;
      var code = String(hit.code || ''), index = findIndex(hit.sym || code, indices);
      var reservedIndex = index && /^(US_|JP_|KR_)/.test(index.sym);
      if (hit.kind === 'index' || reservedIndex) {
        if (!index) return null;
        return Object.assign({}, hit, { code: index.code, sym: index.sym, t: index.name,
          kind: 'index', tags: ['指数'], h: 'chart.html?code=' + encodeURIComponent(index.sym) + '&kind=index&from=home.html',
          chart: 'chart.html?code=' + encodeURIComponent(index.sym) + '&kind=index&from=home.html' });
      }
      if (/^US_[A-Z][A-Z.]{0,5}$/i.test(code)) {
        code = code.toUpperCase();
        if (!knownStock(code, rows, published)) return null;
        return Object.assign({}, hit, { code: code, sym: '', kind: 'us', tags: ['美股'],
          h: 'chart.html?code=' + encodeURIComponent(code) + '&kind=stock&from=home.html' });
      }
      if (key(code) === KOREAN_STOCK.sym) {
        return Object.assign({}, hit, { code: KOREAN_STOCK.sym, sym: '', t: KOREAN_STOCK.name,
          kind: 'kr', tags: ['韩股', KOREAN_STOCK.code], s: '韩股 · ' + KOREAN_STOCK.code,
          h: 'chart.html?code=KR_SKHYNIX&kind=stock&from=home.html%3Fmarket%3Dkr' });
      }
      if (/^(?:(?:sh|sz|bj))?\d{6}$/i.test(code)) {
        return Object.assign({}, hit, { kind: 'stock', h: 'chart.html?code=' + encodeURIComponent(code) + '&kind=stock&from=stock.html' });
      }
      // Preserve explicitly typed industry entries. Unknown index/stock
      // identifiers cannot be sent into a legacy page's default selection.
      return hit.kind === 'industry' && /^BK\d+$/i.test(code) ? hit : null;
    }
    function search(engine, options) {
      var result = [], seen = Object.create(null);
      var query = key(options.query);
      if (query && options.filter !== 'index' && [KOREAN_STOCK.sym, KOREAN_STOCK.code, KOREAN_STOCK.name]
        .concat(KOREAN_STOCK.alias).some(function (value) { return key(value).includes(query); })) {
        var korean = route({ code: KOREAN_STOCK.sym }, options.idx, options.rows, options.published);
        result.push(korean); seen[korean.h] = true;
      }
      engine.search(options).forEach(function (hit) {
        var resolved = route(hit, options.idx, options.rows, options.published);
        if (!resolved || seen[resolved.h]) return;
        seen[resolved.h] = true; result.push(resolved);
      });
      return result.slice(0, options.limit || result.length);
    }
    return { catalog: catalog, findIndex: findIndex, route: route, search: search };
  })();
  if (typeof module === 'object' && module.exports) module.exports = SearchRoutes;
  if (typeof document === 'undefined') return;
  // Extend the shared adapter registry before the home and chart controllers initialize.
  var registered = window.LPPL && window.LPPL.GLOBAL_SYMS;
  if (registered && !registered.some(function (item) { return item.sym === KOREAN_STOCK.sym; })) {
    registered.push(KOREAN_STOCK);
  }
  window.OdNavRoutes = SearchRoutes;
  var me = document.currentScript;
  var section = (me && me.dataset.section) || 'home';
  var theme = (me && me.dataset.theme) || 'light';

  var MARKET_SUB = [
    { t: '今日', h: '#s-summary', ids: ['s-summary', 's-news', 's-events'] },
    { t: '资金', h: '#s-breadth', ids: ['s-breadth', 's-board', 's-nb', 's-mg', 's-lhb', 's-lhb-seats'] },
    { t: '宽基ETF', h: 'nt.html', page: 'nt', nested: true },
    { t: '情绪', h: '#s-limit', ids: ['s-limit', 's-sentiment', 's-ladder', 's-strength', 's-themes', 's-hot'] },
    { t: '风险', h: '#s-top-risk', ids: ['s-top-risk', 's-bottom', 's-abnormal', 's-range'] },
    { t: '宏观', h: '#s-val', ids: ['s-val', 's-macro', 's-growth'] }
  ];
  var MAIN = [
    { k: 'home', t: '首页', h: 'home.html', sections: ['home'], sub: [
      { t: '指数风险概览', h: 'home.html#index-overview', ids: ['index-overview'] },
      { t: '今日摘要', h: 'home.html#today', ids: ['today'] },
      { t: '我的自选', h: 'home.html#mine', ids: ['mine'] },
      { t: '我的研究', h: 'research-workspace.html', page: 'research-workspace.html' }
    ] },
  { k: 'stock', t: '标的', h: 'stock.html', sections: ['stock', 'terminal', 'chart'], sub: [
    { t: '指数终端', h: 'index.html?code=sh000001', page: 'terminal' },
    { t: '标的目录', h: 'stock.html', page: 'stock' }
    ] },
    { k: 'market', t: '市场', h: 'market.html', sections: ['market', 'nt'], sub: MARKET_SUB },
    { k: 'backtest', t: '方法与证据', h: 'backtest.html#view=bench', sections: ['backtest'], sub: [
      { t: '三段验证', h: 'backtest.html#view=bench', key: 'bench' },
      { t: '策略与冷却期', h: 'backtest.html#view=strategy', key: 'strategy' }
    ] },
    { k: 'tools', t: '工具', h: 'tools.html', sections: ['tools'], sub: [] }
  ];
  var SUB_MAX = 7; /* 子页签最多 7 项，其余收进「更多 ▾」 */
  var HELP = [
    { t: '用户指南', h: 'guide.html' },
    { t: '研究仪表盘', h: 'lab/dashboard.html' },
    { t: '数据状态', h: 'market.html#s-fresh' }
  ];
  var SUB = {
    market: MARKET_SUB,
    nt: MARKET_SUB.map(function (x) {
      return x.page === 'nt'
        ? { t: x.t, h: 'nt.html', page: 'nt' }
        : { t: x.t, h: 'market.html' + x.h };
    }),
    /* 标的页的页签由页面自己的吸顶头部提供（app/stock-header.js），顶栏不再重复一层 */
    stock: null
  };

  /* 视觉参照 TradingView：主页签一直可见；页面级子页签用底边下划线（切换视图），筛选器/指数条仍是圆角胶囊 */
  var CSS = '' +
'.odn{position:sticky;top:0;z-index:60;background:#0f0f0f;border-bottom:1px solid #2a2a2a;font:14px/1.4 "Microsoft YaHei UI","PingFang SC","Noto Sans SC",system-ui,sans-serif;color:#dbdbdb}' +
'.odn a{color:inherit;text-decoration:none}' +
'.odn :focus-visible{outline:2px solid #2962ff;outline-offset:1px;border-radius:8px}' +
'.odn-l1{display:flex;align-items:center;gap:4px;height:52px;padding:0 16px}' +
'.odn-brand{flex:none;display:flex;align-items:center;gap:8px;font-weight:700;font-size:16px;color:#fff;margin-right:16px;white-space:nowrap}' +
'.odn-brand i{width:24px;height:24px;border-radius:7px;background:#2962ff;display:grid;place-items:center;font:700 13px Consolas,monospace;font-style:normal;color:#fff}' +
'.odn-main{display:flex;flex-wrap:nowrap;gap:2px;align-items:center;min-width:0;overflow-x:auto;scrollbar-width:none;font-size:15px;color:inherit}' +
'.odn-main::-webkit-scrollbar{display:none}' +
'.odn-main a{flex:none;display:flex;align-items:center;height:36px;padding:0 14px;border-radius:8px;color:#b2b5be;font-weight:600;white-space:nowrap;transition:color .15s,background .15s}' +
'.odn-main a:hover{color:#fff;background:#1f1f1f}' +
'.odn-main a[aria-current]{color:#fff;background:#2a2a2a}' +
'.odn-r{flex:none;margin-left:auto;display:flex;align-items:center;gap:10px;padding-left:12px}' +
'.odn-chart-link{display:inline-flex;align-items:center;min-height:44px;white-space:nowrap;padding:0 10px;border:1px solid #315cf5;border-radius:8px;color:#315cf5;background:#fff;text-decoration:none;font-size:13px;font-weight:650}' +
'.odn-chart-link:hover,.odn-chart-link:focus-visible{border-color:#2447c9;outline:3px solid rgba(49,92,245,.16)}' +
'.odn-asof{display:flex;align-items:center}.odn-asof>*{margin:0!important;font:12px Consolas,"Cascadia Mono",monospace!important;color:#8c8c8c!important;white-space:nowrap}' +
'.odn details{position:relative}' +
'.odn summary{list-style:none;cursor:pointer;display:grid;place-items:center;height:34px;min-width:34px;padding:0 10px;border-radius:999px;color:#b2b5be;font-weight:600}' +
'.odn summary::-webkit-details-marker{display:none}' +
'.odn summary:hover,.odn details[open] summary{color:#fff;background:#2a2a2a}' +
'.odn-help summary{padding:0;width:34px;border:1px solid #333;font:700 15px/1 system-ui,sans-serif}' +
'.odn-pop{position:absolute;right:0;top:calc(100% + 8px);min-width:180px;padding:6px;background:#1e1e1e;border:1px solid #333;border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.55);z-index:70}' +
'.odn-pop a{display:block;padding:9px 12px;border-radius:8px;color:#dbdbdb;white-space:nowrap}.odn-pop a:hover{background:#2e2e2e;color:#fff}' +
'.odn-pop a[aria-current]{color:#0f0f0f;background:#f2f2f2}' +
'.odn-menu-sep{height:1px;margin:4px 6px;background:#333}' +
'.odn-menu{display:none}' +
'.odn-l2{display:flex;align-items:center;gap:12px;min-height:52px;padding:0 16px;border-top:1px solid #1c1c1c;background:#0f0f0f}' +
'.odn-subw{position:relative;min-width:0;flex:1 1 auto}' +
'.odn-subw::before,.odn-subw::after{content:"";position:absolute;top:0;bottom:0;width:28px;pointer-events:none;z-index:1;opacity:0;transition:opacity .15s}' +
'.odn-subw::before{left:0;background:linear-gradient(90deg,#0f0f0f,rgba(15,15,15,0))}' +
'.odn-subw::after{right:0;background:linear-gradient(270deg,#0f0f0f,rgba(15,15,15,0))}' +
'.odn-subw.fl::before,.odn-subw.fr::after{opacity:1}' +
'.odn-sub{display:flex;flex-wrap:nowrap;font-size:14px;align-items:center;gap:6px;min-width:0;overflow-x:auto;scrollbar-width:none;padding:8px 0}' +
'.odn-sub::-webkit-scrollbar{display:none}' +
'.odn-sub>*{flex:none}.odn-sub [hidden],.odn-tools [hidden]{display:none!important}' +
'.odn-sub a.odn-t,.odn-sub .tk,.odn-sub .chip{display:inline-flex!important;flex-direction:row!important;align-items:center!important;gap:8px!important;height:36px!important;min-height:36px!important;padding:0 16px!important;margin:0!important;border:0!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:#b2b5be!important;font:600 14px/36px "Microsoft YaHei UI","PingFang SC",system-ui,sans-serif!important;white-space:nowrap;cursor:pointer;transition:background .15s,color .15s}' +
'.odn-sub a.odn-t{position:relative;border-radius:0!important;padding:0 6px!important;margin:0 6px!important;background:transparent!important;color:#b2b5be!important;font-weight:600}' +
'.odn-sub a.odn-t::after{content:"";position:absolute;left:0;right:0;bottom:-8px;height:2px;border-radius:2px;background:transparent}' +
'.odn-sub a.odn-t:hover{color:#fff!important}.odn-sub a.odn-t[aria-current]{color:#fff!important}.odn-sub a.odn-t[aria-current]::after{background:#2962ff}' +
'.odn-sub .tk:hover,.odn-sub .chip:hover{background:#2a2a2a!important;color:#fff!important}' +
'.odn-more{position:relative;flex:none}.odn-more summary{height:36px;padding:0 10px;border-radius:0;font-weight:600;color:#b2b5be;display:flex;align-items:center;gap:4px;white-space:nowrap}' +
'.odn-more summary::after{content:"▾";font-size:11px}.odn-more[data-on] summary{color:#fff;box-shadow:inset 0 -2px #2962ff}' +
'.odn-more .odn-pop{left:0;right:auto}.odn-more .odn-pop a[aria-current]{color:#fff;background:#2a2a2a}' +
'.odn-sub .tk[aria-current=true],.odn-sub .tk[aria-pressed=true],.odn-sub .chip[aria-current=true],.odn-sub .chip[aria-pressed=true]{background:#f2f2f2!important;color:#0f0f0f!important}' +
'.odn-sub a.odn-t.odn-off{color:#5c5c5c!important}' +
'.odn-sub .odn-sep{width:1px;height:20px;background:#333;margin:0 8px}' +
'.odn-sub .od-row,.odn-sub .chips{display:flex!important;align-items:center;gap:6px!important;padding:0!important;margin:0!important;flex-wrap:nowrap}' +
'.odn-sub .strip-k,.odn-sub .odn-lb{font-size:12px;color:#8c8c8c;padding:0 4px 0 2px;white-space:nowrap;font-weight:400}' +
'.odn-sub .tk{padding:0 14px 0 16px!important}' +
'.odn-sub .tk .tk-n{font-size:14px!important;font-weight:600!important;color:inherit!important}' +
'.odn-sub .tk .tk-s{display:block;width:56px;height:20px;flex:none}' +
'.odn-sub .tk .tk-s path{fill:none;stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}' +
'.odn-sub .tk .tk-v{font:500 12px/1 Consolas,"Cascadia Mono",monospace!important}' +
'.odn-sub .tk .tk-v span{margin-left:6px!important}' +
'.odn-sub .tk[aria-current=true] .tk-v.up,.odn-sub .tk[aria-current=true] .tk-v .up{color:#c2101f!important}.odn-sub .tk[aria-current=true] .tk-v.dn,.odn-sub .tk[aria-current=true] .tk-v .dn{color:#0a7d5e!important}' +
'.odn-tools{flex:none;display:flex;align-items:center;gap:8px;max-width:55%;overflow-x:auto;scrollbar-width:none}' +
'.odn-tools .cmd{min-width:400px;border-radius:999px;overflow:hidden}' +
'.odn-tools .strip-k{font-size:12px;color:#8c8c8c;white-space:nowrap}' +
'.odn-tools .chips{display:flex;gap:4px;padding:0!important}' +
'.odn-tools .chip{border-radius:999px!important}' +
'.odn-vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}' +
'.odn-q{position:relative;display:flex;align-items:center}' +
'.odn-q input{width:220px;height:34px;padding:0 64px 0 34px;border:1px solid #333;border-radius:999px;background:#1a1a1a url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2716%27 height=%2716%27 fill=%27none%27 stroke=%27%238c8c8c%27 stroke-width=%272%27%3E%3Ccircle cx=%277%27 cy=%277%27 r=%275%27/%3E%3Cpath d=%27M11 11l3.5 3.5%27/%3E%3C/svg%3E") no-repeat 12px 50%;color:#fff;font:14px "Microsoft YaHei UI","PingFang SC",system-ui,sans-serif;transition:border-color .15s,width .15s}' +
'.odn-q input::placeholder{color:#8c8c8c}.odn-q input:focus{outline:none;border-color:#2962ff;width:260px}' +
'.odn-q input::-webkit-search-cancel-button{display:none}' +
'.odn-q kbd{position:absolute;right:10px;font:11px/16px Consolas,monospace;color:#8c8c8c;border:1px solid #444;border-radius:4px;padding:0 5px;pointer-events:none}' +
'.odn-q input:focus+kbd{display:none}' +
'.odn-ql{list-style:none;margin:0;left:0;right:auto;min-width:100%;width:300px}' +
'.odn-ql a{display:flex!important;justify-content:space-between;gap:12px}.odn-ql a span{color:#8c8c8c;font-size:12px}' +
'.odn-ql li[aria-selected=true] a{background:#2e2e2e;color:#fff}' +
'.odn-qe{padding:9px 12px;color:#8c8c8c;font-size:13px}' +
'.odn-light .odn-q input{background-color:#f0f3fa;border-color:#e0e3eb;color:#131722}.odn-light .odn-q input::placeholder{color:#6a6d78}.odn-light .odn-q input:focus{background-color:#fff;border-color:#1f5fd6}' +
'.odn-light .odn-q kbd{color:#6a6d78;border-color:#d6dae3}.odn-light .odn-ql a span{color:#6a6d78}.odn-light .odn-ql li[aria-selected=true] a{background:#f0f3fa;color:#131722}' +
  '.odn-main-row{display:none}' +
  '.odn-mobile-toggle{display:none;align-items:center;border:1px solid #333;border-radius:10px;overflow:hidden}' +
  '.odn-mobile-toggle button{height:34px;padding:0 10px;border:0;background:transparent;color:#b2b5be;font:600 13px/1 inherit;white-space:nowrap}' +
  '.odn-mobile-toggle button[aria-pressed=true]{background:#2a2a2a;color:#fff}' +
  '.odn-light .odn-mobile-toggle{border-color:#d6dae3}.odn-light .odn-mobile-toggle button{color:#4c525e}.odn-light .odn-mobile-toggle button[aria-pressed=true]{background:#eaf1fd;color:#1f5fd6}' +
  '.odn-sidebar{display:none;box-sizing:border-box;position:fixed;inset:0 auto 0 0;width:208px;z-index:70;overflow-y:auto;flex-direction:column;padding:14px 10px;background:#0f0f0f;color:#dbdbdb;border-right:1px solid #2a2a2a;font:14px/1.45 "Microsoft YaHei UI","PingFang SC","Noto Sans SC",system-ui,sans-serif}' +
  '.odn-side-brand{display:flex;align-items:center;gap:8px;padding:4px 8px 14px;color:inherit;text-decoration:none;font-weight:700;font-size:17px;white-space:nowrap}' +
  '.odn-side-brand i{width:24px;height:24px;display:grid;place-items:center;border-radius:7px;background:#2962ff;color:#fff;font:700 13px Consolas,monospace;font-style:normal}' +
  '.odn-side-nav{display:block;min-height:0}' +
  '.odn-side-group{margin:4px 0 2px}' +
  '.odn-side-main{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:8px;color:inherit;text-decoration:none;font-weight:650;white-space:nowrap}' +
  '.odn-side-main i{width:14px;height:14px;flex:none;border:1.5px solid currentColor;border-radius:4px;font-style:normal}' +
  '.odn-side-main:hover,.odn-side-main[aria-current=page]{background:#2a2a2a;color:#fff}' +
  '.odn-side-sub{display:grid;gap:1px;padding:1px 0 5px 26px}' +
  '.odn-side-link{display:block;min-width:0;padding:3px 7px;border-radius:6px;color:#b2b5be;text-decoration:none;font-size:12px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
  '.odn-side-link:hover,.odn-side-link[aria-current=location]{color:#fff;font-weight:600}' +
  '.odn-side-link[aria-current=location]{background:#1f1f1f}' +
  '.odn-side-link.odn-side-nested{padding-left:16px}' +
  '.odn-side-footer{margin-top:auto;padding-top:10px;border-top:1px solid #2a2a2a}' +
  '.odn-side-watch-title{padding:0 8px 4px;color:#8c8c8c;font-size:12px}' +
  '.odn-side-watch-list{display:grid;gap:1px}' +
  '.odn-side-watch-empty{padding:4px 8px;color:#8c8c8c;font-size:12px}' +
  '.odn-side-watch-item{display:block;min-width:0;padding:4px 8px;border-radius:6px;color:inherit;text-decoration:none;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
  '.odn-side-watch-item:hover{background:#1f1f1f}' +
  '.odn-side-replay{display:grid;gap:1px;margin-bottom:10px}' +
  '.odn-side-replay a{display:block;min-width:0;padding:5px 8px;border-radius:6px;color:inherit;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
  '.odn-side-replay a b{display:block;font-size:12.5px;font-weight:650}' +
  '.odn-side-replay a small{display:block;color:#8c8c8c;font-size:11px}' +
  '.odn-side-replay a:hover{background:#1f1f1f}' +
  '.odn-side-replay a[aria-current=location]{background:#1f1f1f}' +
  '.odn-side-help{display:grid;grid-template-columns:1fr 1fr;gap:2px 4px;margin-top:10px;padding-top:8px;border-top:1px solid #2a2a2a}' +
  '.odn-side-help a{padding:4px 6px;border-radius:6px;color:#8c8c8c;text-decoration:none;font-size:11px;white-space:nowrap}' +
  '.odn-side-help a:hover{background:#1f1f1f;color:#fff}' +
  '.odn-sidebar-light{background:#fff;color:#131722;border-right-color:#e3e7ef}' +
  '.odn-sidebar-light .odn-side-brand i{background:#1f5fd6}' +
  '.odn-sidebar-light .odn-side-main:hover,.odn-sidebar-light .odn-side-main[aria-current=page]{background:#eaf1fd;color:#1f5fd6}' +
  '.odn-sidebar-light .odn-side-link{color:#5a6478}' +
  '.odn-sidebar-light .odn-side-link:hover,.odn-sidebar-light .odn-side-link[aria-current=location]{color:#1f5fd6}' +
  '.odn-sidebar-light .odn-side-link[aria-current=location]{background:#eef3fd}' +
  '.odn-sidebar-light .odn-side-footer,.odn-sidebar-light .odn-side-help{border-color:#eef1f6}' +
  '.odn-sidebar-light .odn-side-watch-title,.odn-sidebar-light .odn-side-watch-empty,.odn-sidebar-light .odn-side-help a{color:#8a93a6}' +
  '.odn-sidebar-light .odn-side-watch-item:hover,.odn-sidebar-light .odn-side-help a:hover{background:#f0f3fa;color:#131722}' +
  '.odn-sidebar-light .odn-side-replay a:hover,.odn-sidebar-light .odn-side-replay a[aria-current=location]{background:#f0f3fa;color:#131722}' +
  '.odn-sidebar-light .odn-side-replay a small{color:#8a93a6}' +
'.odn.odn-light{background:#fff;border-bottom-color:#e6e9ef;color:#131722}' +
'.odn-light .odn-brand{color:#131722}.odn-light .odn-brand i{background:#1f5fd6}' +
'.odn-light .odn-main a{color:#4c525e}.odn-light .odn-main a:hover{color:#131722;background:#f0f3fa}.odn-light .odn-main a[aria-current]{color:#131722;background:#e9edf5}' +
'.odn-light .odn-l2{background:#fff;border-top-color:#f0f3fa}' +
'.odn-light .odn-subw::before{background:linear-gradient(90deg,#fff,rgba(255,255,255,0))}.odn-light .odn-subw::after{background:linear-gradient(270deg,#fff,rgba(255,255,255,0))}' +
'.odn-light .odn-sub a.odn-t{color:#4c525e!important}.odn-light .odn-sub a.odn-t:hover{color:#131722!important}' +
'.odn-light .odn-sub a.odn-t[aria-current]{color:#1f5fd6!important}.odn-light .odn-sub a.odn-t[aria-current]::after{background:#1f5fd6}' +
'.odn-light .odn-more summary{color:#4c525e}.odn-light .odn-more[data-on] summary{color:#1f5fd6;box-shadow:inset 0 -2px #1f5fd6}' +
'.odn-light .odn-more .odn-pop a[aria-current]{color:#1f5fd6;background:#eef3fd}' +
'.odn-light .odn-sub .tk,.odn-light .odn-sub .chip{color:#4c525e!important}' +
'.odn-light .odn-sub .tk:hover,.odn-light .odn-sub .chip:hover{background:#f0f3fa!important;color:#131722!important}' +
'.odn-light .odn-sub .tk[aria-current=true],.odn-light .odn-sub .tk[aria-pressed=true],.odn-light .odn-sub .chip[aria-current=true],.odn-light .odn-sub .chip[aria-pressed=true]{background:#e9f0fd!important;color:#1f5fd6!important}' +
'.odn-light .odn-sub .tk[aria-current=true] .tk-v.up,.odn-light .odn-sub .tk[aria-current=true] .tk-v .up{color:#d6303a!important}.odn-light .odn-sub .tk[aria-current=true] .tk-v.dn,.odn-light .odn-sub .tk[aria-current=true] .tk-v .dn{color:#11845a!important}' +
'.odn-light .odn-sub .strip-k,.odn-light .odn-tools .strip-k{color:#6a6d78}' +
'.odn-light .odn-sub .odn-sep{background:#e0e3eb}.odn-light .odn-sub .odn-lb{color:#6a6d78}' +
'.odn-light summary{color:#4c525e}.odn-light .odn-help summary{border-color:#d6dae3}.odn-light summary:hover,.odn-light details[open] summary{background:#f0f3fa;color:#131722}' +
'.odn-light .odn-pop{background:#fff;border-color:#e6e9ef;box-shadow:0 16px 40px rgba(19,23,34,.14)}.odn-light .odn-pop a{color:#131722}.odn-light .odn-pop a:hover{background:#f0f3fa}.odn-light .odn-pop a[aria-current]{background:#131722;color:#fff}.odn-light .odn-menu-sep{background:#e6e9ef}' +
'.odn-light .odn-asof>*{color:#6a6d78!important}' +
'.odn-star{height:34px;padding:0 12px;border:1px solid #333;border-radius:999px;background:transparent;color:#b2b5be;font:600 13px/1 inherit;cursor:pointer;white-space:nowrap}' +
'.odn-star:hover{color:#fff;background:#2a2a2a}.odn-light .odn-star{border-color:#d6dae3;color:#4c525e}.odn-light .odn-star:hover{background:#f0f3fa;color:#131722}' +
'.odn-star b{font-weight:600;margin-left:4px;color:#2962ff}.odn-light .odn-star b{color:#1f5fd6}' +
'@media (max-width:520px){.odn-star span{display:none}.odn-star{padding:0 10px}.odn-sub{gap:2px}.odn-sub a.odn-t{font-size:12px!important;padding:0 3px!important;margin:0 2px!important}.odn-sub .odn-sep{display:none}}' +
'@media (min-width:1200px){body.odn-sidebar-page{padding-left:572px}.odn-sidebar{display:flex}.odn-l1{padding:0 16px}.odn-brand,.odn-main-row{display:none}.odn-r{width:100%;gap:10px}.odn-q{width:300px}.odn-q input,.odn-light .odn-q input{box-sizing:border-box;width:100%;background-color:#fff;border-color:#9aa3b2;color:#131722}.odn-q input:focus,.odn-light .odn-q input:focus{width:100%;background-color:#fff}.odn-q input:hover,.odn-q input:focus-visible,.odn-light .odn-q input:hover,.odn-light .odn-q input:focus-visible{border-color:#315CF5;box-shadow:0 0 0 3px rgba(49,92,245,.18)}}' +
'@media (min-width:1200px){body.odn-sidebar-page.vs-home:not(.ai-open){padding-left:208px}}' +
'@media (min-width:1200px){body.odn-sidebar-page.ai-closed{padding-left:208px}}' +
'@media (min-width:761px) and (max-width:1199px){body.odn-sidebar-page{padding-left:208px}.odn-sidebar{display:flex}.odn-brand,.odn-main-row{display:none}.odn-r{gap:8px}.odn-q{width:220px}.odn-l2{flex-wrap:wrap;padding:0 12px}.odn-tools{max-width:none;width:100%;padding-bottom:10px}.odn-tools .cmd{min-width:0;width:100%}.odn-asof{display:none}}' +
'@media (max-width:760px){body.odn-sidebar-page{padding-left:0}.odn-sidebar{display:none}.odn-l1{height:52px;padding:0 12px;gap:8px}.odn-brand{display:flex;margin-right:0}.odn-mobile-toggle{display:flex;margin-left:auto}.odn-r{margin-left:0;gap:4px;padding-left:0}.odn-q,.odn-asof,.odn-star,.ai-btn{display:none!important}.odn-menu{display:block}.odn-help{display:none}.odn-main-row{display:block}.odn-main{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;width:100%;overflow:visible;background:inherit}.odn-main a{box-sizing:border-box;justify-content:center;min-width:0;height:40px;padding:0 2px;border-radius:0;font-size:13px;overflow:hidden;text-overflow:ellipsis}.odn-main a[aria-current]{background:transparent;color:#2962ff;border-bottom:2px solid #2962ff}.odn-light .odn-main a[aria-current]{background:transparent;color:#1f5fd6;border-bottom-color:#1f5fd6}.odn-main-row{border-top:1px solid #1c1c1c}.odn-light .odn-main-row{border-color:#e6e9ef}.odn-l2{flex-wrap:wrap;padding:0 12px}.odn-tools{max-width:none;width:100%;padding-bottom:10px}.odn-tools .cmd{min-width:0;width:100%}.odn-ql{left:auto;right:0;width:min(300px,calc(100vw - 24px));max-width:calc(100vw - 24px)}body.ai-mobile-open .odn{z-index:130}body.ai-mobile-open .odn-main-row,body.ai-mobile-open .odn-l2{display:none}}' +
'.odm-bg{position:fixed;inset:0;z-index:90;background:rgba(19,23,34,.42);display:none;align-items:flex-start;justify-content:center;padding:8vh 12px 12px}' +
'.odm-bg.on{display:flex}' +
'.odm{width:min(640px,100%);max-height:84vh;display:flex;flex-direction:column;background:#fff;color:#131722;border-radius:14px;box-shadow:0 24px 64px rgba(19,23,34,.28);overflow:hidden;font:14px/1.45 "Microsoft YaHei UI","PingFang SC","Noto Sans SC",system-ui,sans-serif}' +
'.odm-in{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid #e6e9ef}' +
'.odm-in input{flex:1;min-width:0;height:40px;border:0;outline:0;font:16px/1 inherit;color:#131722;background:transparent}' +
'.odm-in kbd{font:11px/16px Consolas,monospace;color:#6a6d78;border:1px solid #d6dae3;border-radius:4px;padding:0 5px}' +
'.odm-f{display:flex;gap:6px;padding:10px 14px 0;flex-wrap:wrap}' +
'.odm-f button{font:600 12px/1 inherit;padding:7px 12px;border:1px solid #e0e3eb;border-radius:999px;background:#fff;color:#4c525e;cursor:pointer}' +
'.odm-f button[aria-pressed=true]{background:#131722;border-color:#131722;color:#fff}' +
'.odm-l{list-style:none;margin:0;padding:8px;overflow-y:auto}' +
'.odm-g{padding:8px 8px 2px;font-size:12px;color:#6a6d78}' +
'.odm-l li a{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;padding:10px 10px;border-radius:10px;color:#131722;text-decoration:none}' +
'.odm-l li[aria-selected=true] a,.odm-l li a:hover{background:#f0f3fa}' +
'.odm-l .t{display:flex;align-items:baseline;gap:8px;min-width:0}.odm-l .t b{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
'.odm-l .t code{font:12px Consolas,"Cascadia Mono",monospace;color:#6a6d78}' +
'.odm-l .g{display:flex;gap:4px;align-items:center;white-space:nowrap}' +
'.odm-l .g i{font-style:normal;font-size:11px;line-height:18px;padding:0 7px;border-radius:999px;border:1px solid #e0e3eb;color:#4c525e}' +
'.odm-l .g i.pub{border-color:#1f5fd6;color:#1f5fd6}.odm-l .g i.ch{background:#131722;border-color:#131722;color:#fff}' +
'.odm-e{padding:18px 14px;color:#6a6d78;font-size:13px}' +
'.odm-h{padding:8px 14px 12px;border-top:1px solid #e6e9ef;font-size:11px;color:#6a6d78;display:flex;gap:14px;flex-wrap:wrap}' +
'@media (max-width:520px){.odm-bg{padding:0;align-items:stretch}.odm{max-height:none;border-radius:0}.odm-h{display:none}}' +
'@media (prefers-reduced-motion:reduce){.odn *,.odn *::before,.odn *::after{transition:none!important}}';

  var st = document.createElement('style');
  st.textContent = CSS;
  document.head.appendChild(st);

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function isMain(m) { return m.sections.indexOf(section) >= 0; }

  var hdr = el('header', 'odn' + (theme === 'light' ? ' odn-light' : ''));
  var file = (location.pathname.split('/').pop() || 'index.html');
  hdr.setAttribute('role', 'banner');
  document.body.classList.add('odn-sidebar-page');

  var sidebarLinks = [];
  var sidebar = el('aside', 'odn-sidebar' + (theme === 'light' ? ' odn-sidebar-light' : ''));
  sidebar.setAttribute('aria-label', '全站导航');
  var sideBrand = el('a', 'odn-side-brand', '<i>C</i>临界点');
  sideBrand.href = 'home.html';
  sidebar.appendChild(sideBrand);
  var sideNav = el('nav', 'odn-side-nav');
  sideNav.setAttribute('aria-label', '主导航');
  function addSideLink(parent, def, mainKey, nested) {
    var a = el('a', 'odn-side-link' + (nested ? ' odn-side-nested' : ''), esc(def.t));
    a.href = def.h;
    if (def.page === section || def.page === file) {
      a.setAttribute('aria-current', 'location');
    }
    parent.appendChild(a);
    sidebarLinks.push({ a: a, mainKey: mainKey, ids: def.ids || [], key: def.key || '', page: def.page || '' });
    return a;
  }
  MAIN.forEach(function (m) {
    var group = el('div', 'odn-side-group');
    var mainLink = el('a', 'odn-side-main', '<i aria-hidden="true"></i>' + esc(m.t));
    mainLink.href = m.h;
    mainLink.dataset.navMain = m.k;
    if (isMain(m)) mainLink.setAttribute('aria-current', 'page');
    group.appendChild(mainLink);
    if (m.sub.length) {
      var sub = el('div', 'odn-side-sub');
      m.sub.forEach(function (item) {
        var def = Object.assign({}, item);
        if (m.k === 'market' && item.h.charAt(0) === '#') def.h = 'market.html' + item.h;
        addSideLink(sub, def, m.k, !!item.nested);
      });
      group.appendChild(sub);
    }
    sideNav.appendChild(group);
  });
  sidebar.appendChild(sideNav);
  var sideFooter = el('div', 'odn-side-footer');
  /* 历史回放：只列已发布的回放截止日（与 lppl-data.js 的 REPLAYS 一致），不触发后台现算 */
  var SIDE_REPLAYS = [
    { sym: 'sh000001', name: '上证指数', asof: '2007-10-12', t: '2007 · 上证指数', d: '截止日收盘 5,903 · 2007.10' },
    { sym: 'sh000001', name: '上证指数', asof: '2015-06-12', t: '2015 · 上证指数', d: '高点 5,166 · 2015.06' }
  ];
  var replayTitle = el('div', 'odn-side-watch-title', '历史回放');
  var replayList = el('nav', 'odn-side-replay');
  replayList.setAttribute('aria-label', '历史回放');
  var replayAsof = new URLSearchParams(location.search).get('asof') || '';
  SIDE_REPLAYS.forEach(function (r) {
    var a = el('a', '', '<b>' + esc(r.t) + '</b><small>' + esc(r.d) + '</small>');
    var q = new URLSearchParams({ kind: 'index', from: 'home.html', asof: r.asof });
    q.set('code', r.sym);
    a.href = 'chart.html?' + q.toString();
    a.title = r.name + ' · 截止 ' + r.asof + ' 的回放';
    if (section === 'chart' && replayAsof === r.asof) a.setAttribute('aria-current', 'location');
    replayList.appendChild(a);
  });
  sideFooter.appendChild(replayTitle);
  sideFooter.appendChild(replayList);
  var watchTitle = el('div', 'odn-side-watch-title', '自选');
  var watchList = el('div', 'odn-side-watch-list');
  watchList.id = 'odn-side-watch-list';
  watchList.innerHTML = '<div class="odn-side-watch-empty">还没有自选</div>';
  sideFooter.appendChild(watchTitle);
  sideFooter.appendChild(watchList);
  var sideHelp = el('nav', 'odn-side-help');
  sideHelp.setAttribute('aria-label', '帮助与状态');
  HELP.forEach(function (item) {
    var a = el('a', '', esc(item.t));
    a.href = item.h;
    sideHelp.appendChild(a);
  });
  sideFooter.appendChild(sideHelp);
  sidebar.appendChild(sideFooter);

  /* ---------- 第一层 ---------- */
  var l1 = el('div', 'odn-l1');
  var brand = el('a', 'odn-brand', '<i>C</i>临界点');
  brand.href = 'home.html';
  l1.appendChild(brand);
  var mobileToggle = el('div', 'odn-mobile-toggle');
  mobileToggle.hidden = true;
  mobileToggle.setAttribute('role', 'group');
  mobileToggle.setAttribute('aria-label', '页面视图');
  mobileToggle.innerHTML = '<button type="button" data-mode="data" aria-pressed="true">数据</button>' +
    '<button type="button" data-mode="assistant" aria-pressed="false">研究助手</button>';
  mobileToggle.addEventListener('click', function (e) {
    var button = e.target.closest('button[data-mode]');
    if (!button) return;
    if (button.dataset.mode === 'assistant') {
      if (window.LPPLAssistant && window.LPPLAssistant.open) window.LPPLAssistant.open();
      else document.dispatchEvent(new Event('lppl:assistant-open'));
    } else if (window.LPPLAssistant && window.LPPLAssistant.close) window.LPPLAssistant.close();
    else document.dispatchEvent(new Event('lppl:assistant-close'));
  });
  document.addEventListener('lppl:assistant-state', function (e) {
    var open = !!(e.detail && e.detail.open);
    mobileToggle.querySelectorAll('button[data-mode]').forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === (open ? 'assistant' : 'data')));
    });
  });
  l1.appendChild(mobileToggle);
  function syncMobileToggle() {
    if (document.querySelector('script[src*="ai-assistant.js"]')) mobileToggle.hidden = false;
    else mobileToggle.remove();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncMobileToggle, { once: true });
  } else {
    syncMobileToggle();
  }
  var nav = el('nav', 'odn-main');
  nav.setAttribute('aria-label', '主导航');
  MAIN.forEach(function (m) {
    var a = el('a', '', esc(m.t));
    a.href = m.h;
    a.dataset.navMain = m.k;
    if (isMain(m)) a.setAttribute('aria-current', 'page');
    nav.appendChild(a);
  });
  var mainRow = el('div', 'odn-main-row');
  mainRow.appendChild(nav);
  var right = el('div', 'odn-r');
  var asofSlot = el('div', 'odn-asof');
  right.appendChild(asofSlot);

  /* ---------- 全站搜索：指数名/代码 → 终端；6 位代码或美股代码 → 个股 ---------- */
  var IDX = (window.LPPL && window.LPPL.SYMS) || [
    { sym: 'sh000001', name: '上证指数', code: '000001', alias: ['上证', '上证综指'] },
    { sym: 'sh000016', name: '上证50', code: '000016', alias: [] },
    { sym: 'sh000300', name: '沪深300', code: '000300', alias: [] },
    { sym: 'sh000905', name: '中证500', code: '000905', alias: [] },
    { sym: 'sh000688', name: '科创50', code: '000688', alias: ['科创板50'] },
    { sym: 'sz399001', name: '深证成指', code: '399001', alias: ['深证'] },
    { sym: 'sz399006', name: '创业板指', code: '399006', alias: ['创业板'] }
  ];
  IDX = SearchRoutes.catalog(IDX, window.LPPL && window.LPPL.GLOBAL_SYMS);
  var stockSearchUrl = me && me.src ? new URL('stock-search.js', me.src).href : 'app/stock-search.js';
  var stockSearchScriptPromise = null, stockRowsPromise = null, stockRows = null;
  function loadStockSearchModule() {
    if (window.StockSearch) return Promise.resolve(true);
    if (stockSearchScriptPromise) return stockSearchScriptPromise;
    stockSearchScriptPromise = new Promise(function (resolve) {
      var script = document.createElement('script');
      script.src = stockSearchUrl;
      script.onload = function () {
        var loaded = !!window.StockSearch;
        if (!loaded) stockSearchScriptPromise = null;
        resolve(loaded);
      };
      script.onerror = function () {
        stockSearchScriptPromise = null;
        resolve(false);
      };
      document.head.appendChild(script);
    });
    return stockSearchScriptPromise;
  }
  function loadStockSearchRows() {
    if (stockRows) return Promise.resolve(stockRows);
    if (stockRowsPromise) return stockRowsPromise;
    stockRowsPromise = loadStockSearchModule().then(function (loaded) {
      if (!loaded || !window.LPPL || typeof window.LPPL.stockList !== 'function') return null;
      return window.LPPL.stockList();
    }).then(function (data) {
      stockRows = data && Array.isArray(data.rows) ? data.rows : null;
      if (!stockRows) stockRowsPromise = null;
      return stockRows;
    }).catch(function () {
      stockRowsPromise = null;
      return null;
    });
    return stockRowsPromise;
  }
  function loadScript(name) {
    var url = me && me.src ? new URL(name, me.src).href : 'app/' + name;
    return new Promise(function (resolve) {
      var script = document.createElement('script');
      script.src = url;
      script.onload = function () { resolve(true); };
      script.onerror = function () { resolve(false); };
      document.head.appendChild(script);
    });
  }
  var watchModulePromise = null;
  function loadOdWatch() {
    if (window.OdWatch && window.OdWatch.list) return Promise.resolve(window.OdWatch);
    if (!watchModulePromise) {
      watchModulePromise = (window.OdWatch ? Promise.resolve(true) : loadScript('od-watch.js'))
        .then(function () { return window.OdWatch || null; });
    }
    return watchModulePromise;
  }
  function renderSidebarWatchlist() {
    loadOdWatch().then(function (watch) {
      if (!watch || typeof watch.list !== 'function') {
        watchList.innerHTML = '<div class="odn-side-watch-empty">还没有自选</div>';
        return;
      }
      return watch.list().then(function (items) {
        watchList.textContent = '';
        if (!items.length) {
          watchList.innerHTML = '<div class="odn-side-watch-empty">还没有自选</div>';
          return;
        }
        items.forEach(function (item) {
          var a = el('a', 'odn-side-watch-item');
          a.href = item.h;
          a.textContent = item.name + (item.code ? ' · ' + item.code : '');
          a.title = item.name + (item.code ? ' · ' + item.code : '');
          watchList.appendChild(a);
        });
      });
    });
  }
  var searchDepsPromise = null;
  function loadSearchDeps() {
    if (window.OdSearch) return Promise.resolve(true);
    if (!searchDepsPromise) {
      searchDepsPromise = (window.StockSearch ? Promise.resolve(true) : loadScript('stock-search.js'))
        .then(function () { return window.OdSearch ? true : loadScript('od-search.js'); })
        .then(function () { if (!window.OdSearch) searchDepsPromise = null; return !!window.OdSearch; });
    }
    return searchDepsPromise;
  }
  var publishedPromise = null, publishedCodes = null, usSearchRows = [];
  function searchRows() {
    var globalStocks = (window.LPPL && window.LPPL.GLOBAL_SYMS || []).filter(function (item) {
      return item.kind === 'stock' && /^US_[A-Z][A-Z.]{0,5}$/i.test(item.sym || '');
    }).map(function (item) { return { code: item.sym, name: item.name, py: '', kind: 'us' }; });
    return (stockRows || []).concat(usSearchRows, globalStocks);
  }
  function searchIndices() { return SearchRoutes.catalog(window.LPPL && window.LPPL.SYMS || IDX, window.LPPL && window.LPPL.GLOBAL_SYMS); }
  function loadPublished() {
    if (publishedCodes) return Promise.resolve(publishedCodes);
    if (publishedPromise) return publishedPromise;
    if (!window.LPPL || !window.LPPL.stock || typeof window.LPPL.stock.index !== 'function') return Promise.resolve(null);
    var stockAPI = window.LPPL.stock;
    publishedPromise = Promise.allSettled([
      Promise.resolve().then(function () { return stockAPI.index(); }),
      Promise.resolve().then(function () { return typeof stockAPI.usIndex === 'function' ? stockAPI.usIndex() : null; })
    ]).then(function (results) {
      var codes = [], gotCatalog = false;
      results.forEach(function (result, catalogIndex) {
        if (result.status !== 'fulfilled' || !result.value) return;
        gotCatalog = true;
        var J = result.value, rows = Array.isArray(J) ? J : Array.isArray(J.rows) ? J.rows : Array.isArray(J.stocks) ? J.stocks :
          Object.keys(J).filter(function (k) { return /^(\d{6}|US_[A-Z.]+)$/.test(k); }).map(function (k) { return { code: k }; });
        rows.forEach(function (r) {
          var code = Array.isArray(r) ? r[0] : typeof r === 'string' ? r : r && (r.code || r.symbol || r.ticker);
          if (typeof code !== 'string') return;
          if (catalogIndex === 1 && /^[A-Z][A-Z.]{0,5}$/i.test(code)) code = 'US_' + code.toUpperCase();
          if (!/^(\d{6}|US_[A-Z][A-Z.]{0,5})$/i.test(code)) return;
          if (/^US_/i.test(code)) {
            code = code.toUpperCase();
            if (!usSearchRows.some(function (row) { return row.code === code; })) {
              usSearchRows.push({ code: code, name: (Array.isArray(r) ? r[1] : r && r.name) || code.slice(3), py: '', kind: 'us' });
            }
          }
          codes.push(code);
        });
      });
      if (!gotCatalog) { publishedPromise = null; return null; }
      publishedCodes = new Set(codes);
      return publishedCodes;
    }).catch(function () { publishedPromise = null; return null; });
    return publishedPromise;
  }
  function nameOf(code) {
    if (!stockRows) return '';
    for (var i = 0; i < stockRows.length; i++) {
      var r = stockRows[i], c = Array.isArray(r) ? r[0] : r && r.code;
      if (c === code) return Array.isArray(r) ? r[1] : r.name;
    }
    return '';
  }
  function store() { try { var st0 = window.localStorage; st0.getItem('x'); return st0; } catch (e) { return null; } }

  /* ---------- 顶栏搜索框：只是触发器，真正的搜索在居中弹窗里 ---------- */
  var srch = el('form', 'odn-q');
  srch.setAttribute('role', 'search');
  srch.innerHTML = '<label class="odn-vh" for="odn-q-i">搜索指数、股票名称或拼音</label>' +
    '<input id="odn-q-i" type="search" autocomplete="off" spellcheck="false" placeholder="搜索指数、股票或拼音" readonly aria-haspopup="dialog">' +
    '<kbd aria-hidden="true">Ctrl K</kbd>';
  right.appendChild(srch);
  var qi = srch.querySelector('input');
  srch.addEventListener('submit', function (e) { e.preventDefault(); openSearch(''); });
  qi.addEventListener('focus', function () { openSearch(''); });
  qi.addEventListener('click', function () { openSearch(''); });
  function appendIndexChartLink() {
    if (section !== 'terminal' || !/(?:^|\/)index\.html$/.test(location.pathname)) return;
    var chartLink = el('a', 'odn-chart-link', '完整图表 ›');
    function validAsof(value) {
      value = String(value || '');
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return '';
      var date = new Date(value + 'T00:00:00Z');
      return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : '';
    }
    function currentIndexSymbol() {
      var currentCode = String(new URLSearchParams(location.search).get('code') || '').trim();
      if (!currentCode) return 'sh000001';
      var indexItem = SearchRoutes.findIndex(currentCode, searchIndices());
      return indexItem && indexItem.sym || 'sh000001';
    }
    function updateChartHref() {
      var enteredCode = new URLSearchParams(location.search).get('code');
      if (enteredCode && !SearchRoutes.findIndex(enteredCode, searchIndices())) {
        chartLink.removeAttribute('href'); chartLink.setAttribute('aria-disabled', 'true');
        chartLink.textContent = '未识别的指数'; return;
      }
      chartLink.removeAttribute('aria-disabled'); chartLink.textContent = '完整图表 ›';
      var source = location.pathname.split('/').pop() + location.search;
      var asof = validAsof(new URLSearchParams(location.search).get('asof'));
      chartLink.href = 'chart.html?code=' + encodeURIComponent(currentIndexSymbol()) +
        '&kind=index&from=' + encodeURIComponent(source) + (asof ? '&asof=' + encodeURIComponent(asof) : '');
    }
    updateChartHref();
    ['click', 'focus', 'pointerenter'].forEach(function (name) {
      chartLink.addEventListener(name, updateChartHref);
    });
    right.appendChild(chartLink);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', appendIndexChartLink);
  } else appendIndexChartLink();

  /* ---------- 全局「☆ 自选」抽屉（app/od-watch.js 按需加载） ---------- */
  var star = el('button', 'odn-star', '☆<span> 自选</span>');
  star.type = 'button';
  star.title = '自选：任意页面查看，按行情或模型状态';
  star.setAttribute('aria-label', '打开自选');
  star.addEventListener('click', function () {
    loadOdWatch().then(function (watch) {
      if (watch) watch.toggle();
    });
  });
  right.appendChild(star);

  /* ---------- 搜索弹窗 ---------- */
  var FILTERS = [['all', '全部'], ['index', '指数'], ['stock', '个股']];
  var modal = el('div', 'odm-bg');
  modal.innerHTML = '<div class="odm" role="dialog" aria-modal="true" aria-label="搜索标的">' +
    '<div class="odm-in"><label class="odn-vh" for="odm-i">搜索标的</label>' +
    '<input id="odm-i" type="text" autocomplete="off" spellcheck="false" placeholder="名称、拼音首字母或代码，如 茅台 / gzmt / 600519" aria-controls="odm-l" aria-expanded="true" role="combobox" aria-autocomplete="list">' +
    '<kbd aria-hidden="true">Esc</kbd>' +
    '<button type="button" class="odm-x" aria-label="关闭搜索" style="margin-left:6px;border:0;background:none;font-size:22px;line-height:1;color:inherit;cursor:pointer;padding:0 6px">×</button></div>' +
    '<div class="odm-f" role="group" aria-label="类型">' + FILTERS.map(function (f) {
      return '<button type="button" data-f="' + f[0] + '" aria-pressed="' + (f[0] === 'all') + '">' + f[1] + '</button>';
    }).join('') + '</div>' +
    '<ul id="odm-l" class="odm-l" role="listbox"></ul>' +
    '<div class="odm-h"><span>↑ ↓ 选择</span><span>Enter 打开</span><span>Esc 关闭</span><span>在页面上直接打字也会打开搜索</span></div></div>';
  document.body.appendChild(modal);
  var mi = modal.querySelector('#odm-i'), ml = modal.querySelector('#odm-l');
  var mFilter = 'all', mHits = [], mSel = 0, lastFocus = null;
  function hitHtml(h, i, selected) {
    var tags = (h.tags || []).map(function (t) { return '<i>' + esc(t) + '</i>'; }).join('');
    if (h.published && h.kind !== 'index') tags += '<i class="pub">已发布</i>';
    if (h.kind === 'index') tags += '<i class="ch">图表 ›</i>';
    return '<li role="option" id="odm-o-' + i + '" aria-selected="' + selected + '" data-i="' + i + '"><a href="' + esc(h.h) + '">' +
      '<span class="t"><b>' + esc(h.t) + '</b><code>' + esc(h.code) + '</code></span><span class="g">' + tags + '</span></a></li>';
  }
  function drawModal() {
    var S = window.OdSearch;
    if (!S) { ml.innerHTML = '<li class="odm-e">搜索组件加载中…</li>'; return; }
    var q = mi.value.trim();
    if (!q) {
      mHits = S.recentHits(store()).map(function (h) {
        if (h.kind !== 'index' && h.t === h.code) { var n = nameOf(h.code); if (n) h.t = n; }
        return SearchRoutes.route(h, searchIndices(), searchRows(), publishedCodes);
      }).filter(Boolean);
      if (mFilter !== 'all') mHits = mHits.filter(function (h) { return mFilter === 'index' ? h.kind === 'index' : h.kind !== 'index'; });
      if (mSel >= mHits.length) mSel = 0;
      ml.innerHTML = mHits.length
        ? '<li class="odm-g">最近访问</li>' + mHits.map(function (h, i) { return hitHtml(h, i, i === mSel); }).join('')
        : '<li class="odm-e">输入股票名、拼音首字母、6 位代码或指数名；美股输代码（如 NVDA）。</li>';
    } else {
      mHits = SearchRoutes.search(S, { idx: searchIndices(), rows: searchRows(), query: q, filter: mFilter, limit: 10, published: publishedCodes });
      if (mSel >= mHits.length) mSel = 0;
      ml.innerHTML = mHits.length
        ? mHits.map(function (h, i) { return hitHtml(h, i, i === mSel); }).join('')
        : '<li class="odm-e">没有匹配的标的。请核对名称、代码和市场；不会自动改为其他指数。' + (stockRows ? '' : '（股票清单加载中…）') + '</li>';
    }
    if (mHits.length) mi.setAttribute('aria-activedescendant', 'odm-o-' + mSel); else mi.removeAttribute('aria-activedescendant');
  }
  function go(h) {
    if (!h) return;
    if (window.OdSearch) window.OdSearch.pushRecent(store(), { code: h.code, sym: h.sym, name: h.t, kind: h.kind });
    location.href = h.h;
  }
  function openSearch(seed) {
    if (modal.classList.contains('on')) { if (seed) { mi.value += seed; drawModal(); } return; }
    lastFocus = document.activeElement;
    modal.classList.add('on');
    mi.value = seed || '';
    mSel = 0;
    drawModal();
    mi.focus();
    try { mi.setSelectionRange(mi.value.length, mi.value.length); } catch (err) { /* 某些输入类型不支持 */ }
    loadSearchDeps().then(drawModal);
    loadStockSearchRows().then(function () { if (modal.classList.contains('on')) drawModal(); });
    loadPublished().then(function () { if (modal.classList.contains('on')) drawModal(); });
  }
  window.OdNav = window.OdNav || {};
  window.OdNav.openSearch = openSearch;

  function closeSearch() {
    if (!modal.classList.contains('on')) return;
    modal.classList.remove('on');
    mi.blur(); /* 不能把焦点留在隐藏的输入框里，否则全局“直接打字呼出搜索”会失效 */
    if (lastFocus && lastFocus.focus && lastFocus !== qi && lastFocus !== mi) lastFocus.focus();
    else if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  }
  mi.addEventListener('input', function () { mSel = 0; drawModal(); });
  mi.addEventListener('keydown', function (e) {
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!mHits.length) return;
      e.preventDefault();
      mSel = (mSel + (e.key === 'ArrowDown' ? 1 : mHits.length - 1)) % mHits.length;
      drawModal();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (mHits[mSel]) go(mHits[mSel]);
      else if (stockRows === null) loadStockSearchRows().then(function () { drawModal(); if (mHits[mSel]) go(mHits[mSel]); });
    } else if (e.key === 'Escape') { e.preventDefault(); closeSearch(); }
  });
  modal.addEventListener('click', function (e) {
    if (e.target === modal || e.target.closest('.odm-x')) { closeSearch(); return; }
    var f = e.target.closest('button[data-f]');
    if (f) {
      mFilter = f.dataset.f;
      modal.querySelectorAll('button[data-f]').forEach(function (b) { b.setAttribute('aria-pressed', String(b === f)); });
      mSel = 0; drawModal(); mi.focus();
      return;
    }
    var li = e.target.closest('li[data-i]');
    if (li) { e.preventDefault(); go(mHits[Number(li.dataset.i)]); }
  });
  ml.addEventListener('mousemove', function (e) {
    var li = e.target.closest('li[data-i]');
    if (li && Number(li.dataset.i) !== mSel) { mSel = Number(li.dataset.i); drawModal(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.isComposing || e.keyCode === 229 || e.defaultPrevented) return; /* 图表等组件已处理（如按 0 复位）的按键不再呼出搜索 */
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openSearch(''); return; }
    if (modal.classList.contains('on')) {
      if (e.key === 'Escape') { closeSearch(); return; }
      /* 弹窗刚打开、焦点还没落到输入框时继续敲的字符也要收进去 */
      if (e.target !== mi && !e.ctrlKey && !e.metaKey && !e.altKey && e.key.length === 1) { e.preventDefault(); mi.value += e.key; mi.focus(); mSel = 0; drawModal(); }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target, tag = t && t.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
    if (document.querySelector('.odw.on')) return;
    if (e.key === '/') { e.preventDefault(); openSearch(''); return; }
    /* TradingView 式：焦点不在输入框时直接敲字母、数字或汉字就打开搜索并带入首字符 */
    if (e.key.length === 1 && /[0-9A-Za-z\u4e00-\u9fff]/.test(e.key)) { e.preventDefault(); openSearch(e.key); }
  });
  /* 记录“最近访问”：图表页 / 标的页带 code 参数时 */
  (function () {
    var code = new URLSearchParams(location.search).get('code');
    if (!code || (section !== 'terminal' && section !== 'stock')) return;
    loadSearchDeps().then(function (ok) {
      if (!ok) return;
      if (section === 'terminal') {
        var x = IDX.filter(function (i) { return i.sym === code || i.code === code; })[0];
        if (x) window.OdSearch.pushRecent(store(), { code: x.code, sym: x.sym, name: x.name, kind: 'index' });
      } else if (/^(\d{6}|US_[A-Za-z.]+)$/.test(code)) {
        window.OdSearch.pushRecent(store(), { code: code, name: code, kind: /^US_/i.test(code) ? 'us' : 'stock' });
      }
    });
  })();
  var menu = el('details', 'odn-menu');
  menu.innerHTML = '<summary aria-label="打开导航菜单">☰</summary><div class="odn-pop">' +
    HELP.map(function (h) { return '<a href="' + h.h + '">' + esc(h.t) + '</a>'; }).join('') +
    '<div class="odn-menu-sep"></div>' +
    Array.prototype.map.call(replayList.querySelectorAll('a'), function (a) { return '<a href="' + esc(a.getAttribute('href')) + '">回放 ' + esc(a.querySelector('b').textContent) + '</a>'; }).join('') + '</div>';
  right.appendChild(menu);
  var help = el('details', 'odn-help');
  help.innerHTML = '<summary aria-label="帮助" title="帮助：用户指南、研究仪表盘、数据状态">?</summary><div class="odn-pop">' +
    HELP.map(function (h) { return '<a href="' + h.h + '">' + esc(h.t) + '</a>'; }).join('') + '</div>';
  right.appendChild(help);
  l1.appendChild(right);
  hdr.appendChild(l1);
  hdr.appendChild(mainRow);

  /* ---------- 第二层 ---------- */
  var subDefs = SUB[section] || null;
  var adoptSub = document.querySelectorAll('[data-od-sub]');
  var adoptTools = document.querySelectorAll('[data-od-tools]');
  var subTabs = [];
  if (subDefs || adoptSub.length || adoptTools.length) {
    var l2 = el('div', 'odn-l2');
    var sub = el('nav', 'odn-sub');
    sub.setAttribute('aria-label', '子页签');
    var more = null, moreSum = null, morePop = null, shown = 0;
    if (subDefs) {
      subDefs.forEach(function (d) {
        if (d.label) { sub.appendChild(el('span', 'odn-lb', esc(d.t))); return; }
        var a = el('a', 'odn-t', esc(d.t));
        a.href = d.h;
        if ((d.page && d.page === section) || (d.file && d.file === file)) a.setAttribute('aria-current', 'page');
        if (shown < SUB_MAX) {
          if (d.page) sub.appendChild(el('span', 'odn-sep'));
          sub.appendChild(a);
          shown++;
        } else {
          if (!more) {
            more = el('details', 'odn-more');
            moreSum = el('summary', '', '更多');
            morePop = el('div', 'odn-pop');
            more.appendChild(moreSum); more.appendChild(morePop);
            sub.appendChild(more);
          }
          morePop.appendChild(a);
        }
        if (d.ids && d.h.charAt(0) === '#') subTabs.push({ a: a, ids: d.ids });
      });
    }
    var syncMore = function () {
      if (!more) return;
      var cur = morePop.querySelector('a[aria-current]');
      if (cur) {
        more.setAttribute('data-on', '1'); moreSum.textContent = '更多：' + cur.textContent;
        var l = more.offsetLeft, w = more.offsetWidth;
        if (l + w > sub.scrollLeft + sub.clientWidth || l < sub.scrollLeft) sub.scrollLeft = l + w - sub.clientWidth + 12;
      }
      else { more.removeAttribute('data-on'); moreSum.textContent = '更多'; }
    };
    if (more) {
      new MutationObserver(syncMore).observe(morePop, { attributes: true, subtree: true, attributeFilter: ['aria-current'] });
      morePop.addEventListener('click', function () { more.open = false; });
      /* .odn-sub 横向可滚动会把下拉裁掉：打开时改为 fixed 定位，贴在按钮下方 */
      var placeMore = function () {
        if (!more.open) { morePop.style.cssText = ''; return; }
        var r = moreSum.getBoundingClientRect();
        morePop.style.cssText = 'position:fixed;top:' + (r.bottom + 6) + 'px;left:' + Math.max(8, Math.min(r.left, window.innerWidth - 200)) + 'px;right:auto';
      };
      more.addEventListener('toggle', placeMore);
      addEventListener('resize', placeMore);
      addEventListener('scroll', function () { if (more.open) more.open = false; }, { passive: true });
      syncMore();
    }
    var first = true;
    Array.prototype.forEach.call(adoptSub, function (box) {
      if (!first) sub.appendChild(el('span', 'odn-sep'));
      first = false;
      while (box.firstChild) sub.appendChild(box.firstChild);
      box.remove();
    });
    var subw = el('div', 'odn-subw');
    subw.appendChild(sub);
    l2.appendChild(subw);
    /* 左右渐隐：提示可横向滑动 */
    var fade = function () {
      subw.classList.toggle('fl', sub.scrollLeft > 2);
      subw.classList.toggle('fr', sub.scrollLeft + sub.clientWidth < sub.scrollWidth - 2);
    };
    sub.addEventListener('scroll', fade, { passive: true });
    addEventListener('resize', fade);
    if (window.MutationObserver) new MutationObserver(fade).observe(sub, { childList: true, subtree: true });
    setTimeout(fade, 0);
    if (adoptTools.length) {
      var tools = el('div', 'odn-tools');
      Array.prototype.forEach.call(adoptTools, function (box) {
        while (box.firstChild) tools.appendChild(box.firstChild);
        box.remove();
      });
      l2.appendChild(tools);
    }
    hdr.appendChild(l2);
  }

  var asof = document.querySelector('[data-od-asof]');
  if (asof) asofSlot.appendChild(asof);

  /* 去掉页面里已经清空的旧顶栏 */
  Array.prototype.forEach.call(document.querySelectorAll('header.bar'), function (h) {
    if (!h.textContent.trim() && !h.querySelector('input,button,canvas')) h.remove();
  });
  var skipLink = document.querySelector('body > .skip-link');
  var navAnchor = skipLink ? skipLink.nextSibling : document.body.firstChild;
  document.body.insertBefore(sidebar, navAnchor);
  document.body.insertBefore(hdr, navAnchor);
  renderSidebarWatchlist();
  window.addEventListener('lppl-watch', renderSidebarWatchlist);
  window.addEventListener('storage', renderSidebarWatchlist);

  function syncSidebarActive() {
    sidebarLinks.forEach(function (item) { item.a.removeAttribute('aria-current'); });
    var selected = null;
    if (section === 'market') {
      var hashId = '';
      try { hashId = decodeURIComponent(location.hash.slice(1)); } catch (err) { hashId = ''; }
      var marketLinks = sidebarLinks.filter(function (item) { return item.mainKey === 'market'; });
      selected = marketLinks.filter(function (item) {
        return item.mainKey === 'market' && item.ids.indexOf(hashId) >= 0;
      })[0];
      if (!selected) {
        var threshold = hdr.getBoundingClientRect().height + 16;
        marketLinks.forEach(function (item) {
          item.ids.forEach(function (id) {
            var target = document.getElementById(id);
            if (target && target.getClientRects().length && target.getBoundingClientRect().top <= threshold) selected = item;
          });
        });
        if (!selected) selected = marketLinks[0] || null;
      }
    } else if (section === 'nt') {
      selected = sidebarLinks.filter(function (item) { return item.page === 'nt'; })[0];
    } else if (section === 'stock' || section === 'terminal') {
      selected = sidebarLinks.filter(function (item) { return item.page === section || item.page === file; })[0];
    } else if (section === 'backtest') {
      var view = new URLSearchParams(location.hash.slice(1)).get('view') || 'bench';
      selected = sidebarLinks.filter(function (item) { return item.key === view; })[0];
    } else {
      selected = sidebarLinks.filter(function (item) { return item.page === file; })[0];
      var activeMain = selected ? null : MAIN.filter(isMain)[0];
      if (activeMain) {
        var candidates = sidebarLinks.filter(function (item) {
          return item.mainKey === activeMain.k && item.ids.length;
        });
        var threshold = hdr.getBoundingClientRect().height + 16;
        candidates.forEach(function (item) {
          item.ids.forEach(function (id) {
            var target = document.getElementById(id);
            if (target && target.getClientRects().length && target.getBoundingClientRect().top <= threshold) selected = item;
          });
        });
        if (!selected) selected = candidates[0] || null;
      }
    }
    if (selected) selected.a.setAttribute('aria-current', 'location');
  }
  window.addEventListener('hashchange', syncSidebarActive);
  window.addEventListener('popstate', syncSidebarActive);
  window.addEventListener('scroll', syncSidebarActive, { passive: true });
  syncSidebarActive();

  /* 点页面空白处关闭下拉 */
  var dds = function () { return [menu, help].concat(Array.prototype.slice.call(hdr.querySelectorAll('details.odn-more'))); };
  document.addEventListener('click', function (e) {
    dds().forEach(function (d) { if (d.open && !d.contains(e.target)) d.open = false; });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') dds().forEach(function (d) { if (d.open) { d.open = false; d.querySelector('summary').focus(); } });
  });

  /* ---------- 回放按钮高亮：跟随地址中的 asof ---------- */
  function syncReplay() {
    var q = new URLSearchParams(location.search), d = q.get('asof') || '';
    Array.prototype.forEach.call(hdr.querySelectorAll('.odn-sub .chip[data-d]'), function (c) {
      c.setAttribute('aria-current', String(!!d && c.dataset.d === d));
    });
  }
  if (history.replaceState) {
    var rs = history.replaceState;
    history.replaceState = function () { var r = rs.apply(this, arguments); syncReplay(); return r; };
  }
  syncReplay();

  /* ---------- 市场页：子页签＝分组，只显示当前组；地址 hash 记住所在组 ---------- */
  var GROUPED = section === 'market' && subTabs.length;
  if (GROUPED) {
    var DEF = 0; /* 默认：今日 */
    var groupOf = function (id) {
      for (var i = 0; i < subTabs.length; i++) if (subTabs[i].ids.indexOf(id) >= 0) return i;
      return -1;
    };
    var groupedIds = [];
    subTabs.forEach(function (t) { groupedIds = groupedIds.concat(t.ids); });
    /* 首屏：正文还没解析，先用 id 选择器隐藏其他组，避免整页闪一下 */
    var g0 = groupOf(decodeURIComponent(location.hash.slice(1)));
    if (g0 < 0) g0 = DEF;
    var pre = [];
    subTabs.forEach(function (t, i) { if (i !== g0) t.ids.forEach(function (id) { pre.push('#' + id); }); });
    pre.push('main > section.sec[id]' + groupedIds.map(function (id) { return ':not(#' + id + ')'; }).join('') + ':not(:target)');
    var gStyle = el('style');
    gStyle.textContent = '.odn-gh{display:none!important}' + pre.join(',') + '{display:none!important}';
    document.head.appendChild(gStyle);
    var curG = -1;
    var showGroup = function (g, anchor, push) {
      if (g < 0) g = DEF;
      var changed = g !== curG;
      curG = g;
      subTabs.forEach(function (t, i) {
        t.ids.forEach(function (id) { var n = document.getElementById(id); if (n) n.classList.toggle('odn-gh', i !== g); });
        if (i === g) {
          t.a.setAttribute('aria-current', 'location');
          var s = t.a.parentNode, l = t.a.offsetLeft, w = t.a.offsetWidth;
          if (l < s.scrollLeft) s.scrollLeft = Math.max(0, l - 24);
          else if (l + w > s.scrollLeft + s.clientWidth) s.scrollLeft = l + w - s.clientWidth + 24;
        } else t.a.removeAttribute('aria-current');
      });
      var target = anchor && document.getElementById(anchor);
      var showUngrouped = !!(target && target.matches('main > section.sec[id]') && groupOf(target.id) < 0);
      Array.prototype.forEach.call(document.querySelectorAll('main > section.sec[id]'), function (n) {
        if (groupOf(n.id) < 0) n.classList.toggle('odn-gh', !showUngrouped || n !== target);
      });
      var h = '#' + (anchor || subTabs[g].ids[0]);
      if (push && location.hash !== h && history.pushState) history.pushState(null, '', h);
      if (changed) setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 0); /* 让热力图等按新宽度重绘 */
      var n = anchor && anchor !== subTabs[g].ids[0] ? document.getElementById(anchor) : null;
      if (n) { n.style.scrollMarginTop = (hdr.getBoundingClientRect().height + 12) + 'px'; n.scrollIntoView(); }
      else if (changed && push) window.scrollTo(0, 0);
    };
    var fromHash = function () {
      gStyle.textContent = '.odn-gh{display:none!important}';
      var id = decodeURIComponent(location.hash.slice(1));
      var target = id && document.getElementById(id);
      showGroup(groupOf(id), groupOf(id) >= 0 || (target && target.matches('main > section.sec[id]')) ? id : '', false);
    };
    subTabs.forEach(function (t, i) {
      t.a.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        showGroup(i, '', true);
        syncSidebarActive();
      });
    });
    sidebarLinks.filter(function (item) {
      return item.mainKey === 'market' && item.ids.length;
    }).forEach(function (item) {
      var linkId = decodeURIComponent(item.a.hash.slice(1));
      if (groupOf(linkId) < 0) return;
      item.a.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        var id = decodeURIComponent(item.a.hash.slice(1));
        var g = groupOf(id);
        if (g < 0) return;
        var first = id === subTabs[g].ids[0];
        showGroup(g, first ? '' : id, true);
        if (first) window.scrollTo(0, 0);
        syncSidebarActive();
      });
    });
    addEventListener('hashchange', fromHash);
    addEventListener('popstate', fromHash);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fromHash); else fromHash();
  }

  /* ---------- 子页签滚动高亮 ---------- */
  if (subTabs.length && !GROUPED) {
    var off = function () { return hdr.getBoundingClientRect().height + 12; };
    var targets = function () {
      var list = [];
      subTabs.forEach(function (t, i) {
        t.ids.forEach(function (id) { var n = document.getElementById(id); if (n) list.push({ n: n, i: i }); });
      });
      return list;
    };
    var update = function () {
      var o = off(), cur = -1, best = -Infinity;
      subTabs.forEach(function (t) {
        var vis = t.ids.some(function (id) { var n = document.getElementById(id); return n && n.getClientRects().length; });
        t.a.classList.toggle('odn-off', !vis);
      });
      targets().forEach(function (x) {
        if (!x.n.getClientRects().length) return;
        x.n.style.scrollMarginTop = o + 'px';
        var top = x.n.getBoundingClientRect().top;
        if (top - o <= 1 && top > best) { best = top; cur = x.i; }
      });
      if (cur < 0) {
        var firstVis = subTabs.findIndex(function (t) { return !t.a.classList.contains('odn-off'); });
        cur = firstVis;
      }
      subTabs.forEach(function (t, i) {
        if (i === cur) {
          if (!t.a.hasAttribute('aria-current')) {
            t.a.setAttribute('aria-current', 'location');
            var s = t.a.parentNode, l = t.a.offsetLeft, w = t.a.offsetWidth;
            if (l < s.scrollLeft) s.scrollLeft = Math.max(0, l - 24);
            else if (l + w > s.scrollLeft + s.clientWidth) s.scrollLeft = l + w - s.clientWidth + 24;
          }
        } else t.a.removeAttribute('aria-current');
      });
    };
    var raf = 0;
    var later = function () { if (!raf) raf = requestAnimationFrame(function () { raf = 0; update(); }); };
    addEventListener('scroll', later, { passive: true });
    addEventListener('resize', later);
    addEventListener('hashchange', later);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', update); else update();
    setInterval(update, 1500); /* 个股页的板块在查询后才出现 */
    subTabs.forEach(function (t) {
      t.a.addEventListener('click', function (e) {
        var id = null, n = null;
        for (var i = 0; i < t.ids.length; i++) {
          var candidate = document.getElementById(t.ids[i]);
          if (candidate && candidate.getClientRects().length) {
            id = t.ids[i];
            n = candidate;
            break;
          }
        }
        if (!n) { e.preventDefault(); return; }
        n.style.scrollMarginTop = off() + 'px';
        if (id !== t.ids[0]) {
          e.preventDefault();
          location.hash = id;
          n.scrollIntoView();
        }
      });
    });
  }
})();
