/* 临界点 · 全站两层顶栏（Open Design 维护）
   第一层：主页签（首页 / 终端 / 回测 / 市场 / 个股）+ 帮助 + 页面日期
   第二层：当前栏目的子页签 + 页面自己的工具
   用法：在页面 <main> 之前放
     <script src="app/od-nav.js" data-section="terminal|backtest|market|nt|stock|home"></script>
   页面可用以下标记把已有元素交给顶栏（元素本身与其脚本逻辑不变）：
     [data-od-sub]   其子元素移入第二层左侧（作为子页签）
     [data-od-tools] 其子元素移入第二层右侧（页面工具）
     [data-od-asof]  该元素移入第一层右侧（数据日期）
   本模块不读取、不计算任何业务数据。 */
(function () {
  'use strict';
  var me = document.currentScript;
  var section = (me && me.dataset.section) || 'home';
  var theme = (me && me.dataset.theme) || 'light';

  var MAIN = [
    { k: 'home', t: '首页', h: 'home.html' },
    { k: 'terminal', t: '图表', h: 'index.html' },
    { k: 'market', t: '市场', h: 'market.html', also: ['nt'] },
    { k: 'backtest', t: '回测', h: 'backtest.html' },
    { k: 'stock', t: '标的', h: 'stock.html' }
  ];
  var SUB_MAX = 7; /* 子页签最多 7 项，其余收进「更多 ▾」 */
  var HELP = [
    { t: '用户指南', h: 'lab/guide.html' },
    { t: '研究仪表盘', h: 'lab/dashboard.html' },
    { t: '更新日志', h: 'changelog.html' }
  ];
  /* 子页签：t 文字；h 链接；ids 属于该组的页面锚点（用于滚动高亮） */
  var MARKET_SUB = [
    { t: '事件日历', h: '#s-events', ids: ['s-events'] },
    { t: '资金流', h: '#s-board', ids: ['s-board'] },
    { t: '情绪', h: '#s-limit', ids: ['s-limit', 's-sentiment', 's-ladder', 's-strength', 's-themes', 's-hot', 's-lhb'] },
    { t: '快讯', h: '#s-news', ids: ['s-news'] },
    { t: '北向与两融', h: '#s-nb', ids: ['s-nb', 's-mg'] },
    { t: '估值与宏观', h: '#s-val', ids: ['s-val', 's-macro'] },
    { t: '成长监控', h: '#s-growth', ids: ['s-growth'] },
    { t: '信号与统计', h: '#s-bottom', ids: ['s-bottom', 's-abnormal', 's-range'] },
    { t: '数据状态', h: '#s-fresh', ids: ['s-fresh'] },
    { t: '国家队ETF', h: 'nt.html', page: 'nt' }
  ];
  var SUB = {
    market: MARKET_SUB,
    nt: MARKET_SUB.map(function (x) { return x.page ? x : { t: x.t, h: 'market.html' + x.h }; }),
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
'.odn-asof{display:flex;align-items:center}.odn-asof>*{margin:0!important;font:12px Consolas,"Cascadia Mono",monospace!important;color:#8c8c8c!important;white-space:nowrap}' +
'.odn details{position:relative}' +
'.odn summary{list-style:none;cursor:pointer;display:grid;place-items:center;height:34px;min-width:34px;padding:0 10px;border-radius:999px;color:#b2b5be;font-weight:600}' +
'.odn summary::-webkit-details-marker{display:none}' +
'.odn summary:hover,.odn details[open] summary{color:#fff;background:#2a2a2a}' +
'.odn-help summary{padding:0;width:34px;border:1px solid #333;font:700 15px/1 system-ui,sans-serif}' +
'.odn-pop{position:absolute;right:0;top:calc(100% + 8px);min-width:180px;padding:6px;background:#1e1e1e;border:1px solid #333;border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.55);z-index:70}' +
'.odn-pop a{display:block;padding:9px 12px;border-radius:8px;color:#dbdbdb;white-space:nowrap}.odn-pop a:hover{background:#2e2e2e;color:#fff}' +
'.odn-pop a[aria-current]{color:#0f0f0f;background:#f2f2f2}' +
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
'@media (max-width:1100px){.odn-asof{display:none}}' +
'@media (max-width:760px){.odn-q input{width:150px}.odn-q input:focus{width:180px}.odn-q kbd{display:none}}' +
'@media (max-width:420px){.odn-q input{width:110px}}' +
'@media (max-width:860px){.odn-l2{flex-wrap:wrap;padding:0 12px}.odn-tools{max-width:none;width:100%;padding-bottom:10px}.odn-tools .cmd{min-width:0;width:100%}.odn-brand{margin-right:8px}}' +
'@media (max-width:520px){.odn-main{display:none}.odn-menu{display:block}.odn-ql{left:auto;right:0;width:min(300px,calc(100vw - 120px));max-width:calc(100vw - 24px)}}' +
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
'.odn-light .odn-pop{background:#fff;border-color:#e6e9ef;box-shadow:0 16px 40px rgba(19,23,34,.14)}.odn-light .odn-pop a{color:#131722}.odn-light .odn-pop a:hover{background:#f0f3fa}.odn-light .odn-pop a[aria-current]{background:#131722;color:#fff}' +
'.odn-light .odn-asof>*{color:#6a6d78!important}' +
'.odn-star{height:34px;padding:0 12px;border:1px solid #333;border-radius:999px;background:transparent;color:#b2b5be;font:600 13px/1 inherit;cursor:pointer;white-space:nowrap}' +
'.odn-star:hover{color:#fff;background:#2a2a2a}.odn-light .odn-star{border-color:#d6dae3;color:#4c525e}.odn-light .odn-star:hover{background:#f0f3fa;color:#131722}' +
'.odn-star b{font-weight:600;margin-left:4px;color:#2962ff}.odn-light .odn-star b{color:#1f5fd6}' +
'@media (max-width:520px){.odn-star span{display:none}.odn-star{padding:0 10px}}' +
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
  function isMain(m) { return m.k === section || (m.also && m.also.indexOf(section) >= 0); }

  var hdr = el('header', 'odn' + (theme === 'light' ? ' odn-light' : ''));
  var file = (location.pathname.split('/').pop() || 'index.html');
  hdr.setAttribute('role', 'banner');

  /* ---------- 第一层 ---------- */
  var l1 = el('div', 'odn-l1');
  l1.appendChild(el('a', 'odn-brand', '<i>C</i>临界点')).href = 'home.html';
  var nav = el('nav', 'odn-main');
  nav.setAttribute('aria-label', '主页签');
  MAIN.forEach(function (m) {
    var a = el('a', '', esc(m.t));
    a.href = m.h;
    if (isMain(m)) a.setAttribute('aria-current', 'page');
    nav.appendChild(a);
  });
  l1.appendChild(nav);
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
  var publishedPromise = null, publishedCodes = null;
  function loadPublished() {
    if (publishedCodes) return Promise.resolve(publishedCodes);
    if (publishedPromise) return publishedPromise;
    if (!window.LPPL || !window.LPPL.stock || typeof window.LPPL.stock.index !== 'function') return Promise.resolve(null);
    publishedPromise = window.LPPL.stock.index().then(function (J) {
      var codes = [];
      if (Array.isArray(J)) codes = J.map(function (r) { return r && (r.code || r.symbol || r); });
      else if (J && Array.isArray(J.rows)) codes = J.rows.map(function (r) { return r && (r.code || r.symbol || r[0]); });
      else if (J && Array.isArray(J.stocks)) codes = J.stocks.map(function (r) { return r && (r.code || r); });
      else if (J && typeof J === 'object') codes = Object.keys(J).filter(function (k) { return /^(\d{6}|US_[A-Z.]+)$/.test(k); });
      publishedCodes = new Set(codes.filter(function (c) { return typeof c === 'string'; }));
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

  /* ---------- 全局「☆ 自选」抽屉（app/od-watch.js 按需加载） ---------- */
  var star = el('button', 'odn-star', '☆<span> 自选</span>');
  star.type = 'button';
  star.title = '自选：任意页面查看，按行情或模型状态';
  star.setAttribute('aria-label', '打开自选');
  star.addEventListener('click', function () {
    (window.OdWatch ? Promise.resolve(true) : loadScript('od-watch.js')).then(function () {
      if (window.OdWatch) window.OdWatch.toggle();
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
      mHits = S.recentHits(store()).map(function (h) { if (h.kind !== 'index' && h.t === h.code) { var n = nameOf(h.code); if (n) h.t = n; } return h; });
      if (mFilter !== 'all') mHits = mHits.filter(function (h) { return mFilter === 'index' ? h.kind === 'index' : h.kind !== 'index'; });
      if (mSel >= mHits.length) mSel = 0;
      ml.innerHTML = mHits.length
        ? '<li class="odm-g">最近访问</li>' + mHits.map(function (h, i) { return hitHtml(h, i, i === mSel); }).join('')
        : '<li class="odm-e">输入股票名、拼音首字母、6 位代码或指数名；美股输代码（如 NVDA）。</li>';
    } else {
      mHits = S.search({ idx: IDX, rows: stockRows || [], query: q, filter: mFilter, limit: 10, published: publishedCodes });
      if (mSel >= mHits.length) mSel = 0;
      ml.innerHTML = mHits.length
        ? mHits.map(function (h, i) { return hitHtml(h, i, i === mSel); }).join('')
        : '<li class="odm-e">没有匹配：可输入股票名、拼音、6 位代码或美股代码' + (stockRows ? '' : '（股票清单加载中…）') + '</li>';
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
    MAIN.map(function (m) { return '<a href="' + m.h + '"' + (isMain(m) ? ' aria-current="page"' : '') + '>' + esc(m.t) + '</a>'; }).join('') + '</div>';
  right.appendChild(menu);
  var help = el('details', 'odn-help');
  help.innerHTML = '<summary aria-label="帮助" title="帮助：用户指南、研究仪表盘、更新日志">?</summary><div class="odn-pop">' +
    HELP.map(function (h) { return '<a href="' + h.h + '">' + esc(h.t) + '</a>'; }).join('') + '</div>';
  right.appendChild(help);
  l1.appendChild(right);
  hdr.appendChild(l1);

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
  document.body.insertBefore(hdr, document.body.firstChild);

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
    var DEF = 1; /* 默认：资金流 */
    var groupOf = function (id) {
      for (var i = 0; i < subTabs.length; i++) if (subTabs[i].ids.indexOf(id) >= 0) return i;
      return -1;
    };
    /* 首屏：正文还没解析，先用 id 选择器隐藏其他组，避免整页闪一下 */
    var g0 = groupOf(decodeURIComponent(location.hash.slice(1)));
    if (g0 < 0) g0 = DEF;
    var pre = [];
    subTabs.forEach(function (t, i) { if (i !== g0) t.ids.forEach(function (id) { pre.push('#' + id); }); });
    var gStyle = el('style');
    gStyle.textContent = '.odn-gh{display:none!important}' + (pre.length ? pre.join(',') + '{display:none!important}' : '');
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
      showGroup(groupOf(id), groupOf(id) >= 0 ? id : '', false);
    };
    subTabs.forEach(function (t, i) {
      t.a.addEventListener('click', function (e) { e.preventDefault(); showGroup(i, '', true); });
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
