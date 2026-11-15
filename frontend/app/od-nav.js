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
  var theme = (me && me.dataset.theme) || 'dark';

  var MAIN = [
    { k: 'home', t: '首页', h: 'home.html' },
    { k: 'terminal', t: '终端', h: 'index.html' },
    { k: 'backtest', t: '回测', h: 'backtest.html' },
    { k: 'market', t: '市场', h: 'market.html', also: ['nt'] },
    { k: 'stock', t: '个股', h: 'stock.html' }
  ];
  var HELP = [
    { t: '用户指南', h: 'lab/guide.html' },
    { t: '研究仪表盘', h: 'lab/dashboard.html' }
  ];
  /* 子页签：t 文字；h 链接；ids 属于该组的页面锚点（用于滚动高亮） */
  var MARKET_SUB = [
    { t: '事件日历', h: '#s-events', ids: ['s-events'] },
    { t: '资金流', h: '#s-board', ids: ['s-board'] },
    { t: '情绪', h: '#s-limit', ids: ['s-limit', 's-sentiment', 's-ladder', 's-strength', 's-themes', 's-hot', 's-lhb'] },
    { t: '快讯', h: '#s-news', ids: ['s-news'] },
    { t: '北向与两融', h: '#s-nb', ids: ['s-nb', 's-mg'] },
    { t: '估值与宏观', h: '#s-val', ids: ['s-val', 's-macro'] },
    { t: '信号与统计', h: '#s-bottom', ids: ['s-bottom', 's-abnormal', 's-range'] },
    { t: '数据状态', h: '#s-fresh', ids: ['s-fresh'] },
    { t: '国家队ETF', h: 'nt.html', page: 'nt' }
  ];
  var SUB = {
    market: MARKET_SUB,
    nt: MARKET_SUB.map(function (x) { return x.page ? x : { t: x.t, h: 'market.html' + x.h }; }),
    home: [
      { t: '首页风格', h: '#', label: true },
      { t: '蓝白（正式）', h: 'home.html', file: 'home.html' },
      { t: 'TradingView', h: 'home-tv.html', file: 'home-tv.html' },
      { t: '彭博', h: 'home-bbg.html', file: 'home-bbg.html' },
      { t: '海面', h: 'home-ocean.html', file: 'home-ocean.html' }
    ],
    stock: [
      { t: '查询', h: '#search', ids: ['search'] },
      { t: '本地自选', h: '#watch-section', ids: ['watch-section'] },
      { t: '近期事件', h: '#recent-events', ids: ['recent-events', 'stock-events'] },
      { t: '逃顶', h: '#sec-top', ids: ['sec-top'] },
      { t: '抄底', h: '#sec-dip', ids: ['sec-dip'] }
    ]
  };

  /* 视觉参照 TradingView：主页签一直可见；子页签为圆角胶囊，选中为实心高亮 */
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
'.odn-sub>*{flex:none}' +
'.odn-sub a.odn-t,.odn-sub .tk,.odn-sub .chip{display:inline-flex!important;flex-direction:row!important;align-items:center!important;gap:8px!important;height:36px!important;min-height:36px!important;padding:0 16px!important;margin:0!important;border:0!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:#b2b5be!important;font:600 14px/36px "Microsoft YaHei UI","PingFang SC",system-ui,sans-serif!important;white-space:nowrap;cursor:pointer;transition:background .15s,color .15s}' +
'.odn-sub a.odn-t:hover,.odn-sub .tk:hover,.odn-sub .chip:hover{background:#2a2a2a!important;color:#fff!important}' +
'.odn-sub a.odn-t[aria-current],.odn-sub .tk[aria-current=true],.odn-sub .tk[aria-pressed=true],.odn-sub .chip[aria-current=true],.odn-sub .chip[aria-pressed=true]{background:#f2f2f2!important;color:#0f0f0f!important}' +
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
'@media (max-width:1100px){.odn-asof{display:none}}' +
'@media (max-width:860px){.odn-l2{flex-wrap:wrap;padding:0 12px}.odn-tools{max-width:none;width:100%;padding-bottom:10px}.odn-tools .cmd{min-width:0;width:100%}.odn-brand{margin-right:8px}}' +
'@media (max-width:520px){.odn-main{display:none}.odn-menu{display:block}}' +
'.odn.odn-light{background:#fff;border-bottom-color:#e6e9ef;color:#131722}' +
'.odn-light .odn-brand{color:#131722}.odn-light .odn-brand i{background:#1f5fd6}' +
'.odn-light .odn-main a{color:#4c525e}.odn-light .odn-main a:hover{color:#131722;background:#f0f3fa}.odn-light .odn-main a[aria-current]{color:#131722;background:#e9edf5}' +
'.odn-light .odn-l2{background:#fff;border-top-color:#f0f3fa}' +
'.odn-light .odn-subw::before{background:linear-gradient(90deg,#fff,rgba(255,255,255,0))}.odn-light .odn-subw::after{background:linear-gradient(270deg,#fff,rgba(255,255,255,0))}' +
'.odn-light .odn-sub a.odn-t{color:#4c525e!important}.odn-light .odn-sub a.odn-t:hover{background:#f0f3fa!important;color:#131722!important}' +
'.odn-light .odn-sub a.odn-t[aria-current]{background:#131722!important;color:#fff!important}' +
'.odn-light .odn-sub .odn-sep{background:#e0e3eb}.odn-light .odn-sub .odn-lb{color:#6a6d78}' +
'.odn-light summary{color:#4c525e}.odn-light .odn-help summary{border-color:#d6dae3}.odn-light summary:hover,.odn-light details[open] summary{background:#f0f3fa;color:#131722}' +
'.odn-light .odn-pop{background:#fff;border-color:#e6e9ef;box-shadow:0 16px 40px rgba(19,23,34,.14)}.odn-light .odn-pop a{color:#131722}.odn-light .odn-pop a:hover{background:#f0f3fa}.odn-light .odn-pop a[aria-current]{background:#131722;color:#fff}' +
'.odn-light .odn-asof>*{color:#6a6d78!important}' +
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
  var menu = el('details', 'odn-menu');
  menu.innerHTML = '<summary aria-label="打开导航菜单">☰</summary><div class="odn-pop">' +
    MAIN.map(function (m) { return '<a href="' + m.h + '"' + (isMain(m) ? ' aria-current="page"' : '') + '>' + esc(m.t) + '</a>'; }).join('') + '</div>';
  right.appendChild(menu);
  var help = el('details', 'odn-help');
  help.innerHTML = '<summary aria-label="帮助" title="帮助：用户指南、研究仪表盘">?</summary><div class="odn-pop">' +
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
    if (subDefs) {
      subDefs.forEach(function (d) {
        if (d.label) { sub.appendChild(el('span', 'odn-lb', esc(d.t))); return; }
        if (d.page) sub.appendChild(el('span', 'odn-sep'));
        var a = el('a', 'odn-t', esc(d.t));
        a.href = d.h;
        if ((d.page && d.page === section) || (d.file && d.file === file)) a.setAttribute('aria-current', 'page');
        sub.appendChild(a);
        if (d.ids && d.h.charAt(0) === '#') subTabs.push({ a: a, ids: d.ids });
      });
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
  document.addEventListener('click', function (e) {
    [menu, help].forEach(function (d) { if (d.open && !d.contains(e.target)) d.open = false; });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') [menu, help].forEach(function (d) { if (d.open) { d.open = false; d.querySelector('summary').focus(); } });
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

  /* ---------- 子页签滚动高亮 ---------- */
  if (subTabs.length) {
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
            if (l < s.scrollLeft || l + w > s.scrollLeft + s.clientWidth) s.scrollLeft = l - 24;
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
        var n = document.getElementById(t.ids[0]);
        if (!n || !n.getClientRects().length) { e.preventDefault(); return; }
        n.style.scrollMarginTop = off() + 'px';
      });
    });
  }
})();
