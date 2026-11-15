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
      { t: 'TradingView', h: 'home-tv.html', file: 'home-tv.html' },
      { t: '彭博', h: 'home-bbg.html', file: 'home-bbg.html' },
      { t: '蓝白', h: 'home-blue.html', file: 'home-blue.html' },
      { t: '海面（线上）', h: 'home.html', file: 'home.html' }
    ],
    stock: [
      { t: '查询', h: '#search', ids: ['search'] },
      { t: '本地自选', h: '#watch-section', ids: ['watch-section'] },
      { t: '近期事件', h: '#recent-events', ids: ['recent-events', 'stock-events'] },
      { t: '逃顶', h: '#sec-top', ids: ['sec-top'] },
      { t: '抄底', h: '#sec-dip', ids: ['sec-dip'] }
    ]
  };

  var CSS = '' +
'.odn{position:sticky;top:0;z-index:60;background:#0f1012;border-bottom:1px solid #26282d;font:14px/1.4 "Microsoft YaHei UI","PingFang SC","Noto Sans SC",system-ui,sans-serif;color:#d6d9df}' +
'.odn a{color:inherit;text-decoration:none}' +
'.odn :focus-visible{outline:2px solid #4d8dff;outline-offset:-2px;border-radius:6px}' +
'.odn-l1{display:flex;align-items:center;gap:8px;height:48px;padding:0 16px}' +
'.odn-brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px;color:#fff;margin-right:12px;white-space:nowrap}' +
'.odn-brand i{width:22px;height:22px;border-radius:6px;background:#2962ff;display:grid;place-items:center;font:700 12px Consolas,monospace;font-style:normal;color:#fff}' +
'.odn-main{display:flex;flex-wrap:nowrap;gap:0;align-items:stretch;height:100%;font-size:14px;color:inherit}' +
'.odn-main a{position:relative;display:flex;align-items:center;padding:0 14px;color:#a4a9b3;font-weight:500;transition:color .15s}' +
'.odn-main a:hover{color:#fff}' +
'.odn-main a[aria-current]{color:#fff}' +
'.odn-main a[aria-current]::after{content:"";position:absolute;left:10px;right:10px;bottom:0;height:2px;border-radius:2px 2px 0 0;background:#2962ff}' +
'.odn-r{margin-left:auto;display:flex;align-items:center;gap:12px}' +
'.odn-asof{display:flex;align-items:center}.odn-asof>*{margin:0!important;font:12px Consolas,"Cascadia Mono",monospace!important;color:#8b919c!important}' +
'.odn details{position:relative}' +
'.odn summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:4px;height:32px;padding:0 12px;border-radius:999px;color:#a4a9b3;border:1px solid #2c2f36}' +
'.odn summary::-webkit-details-marker{display:none}' +
'.odn summary:hover,.odn details[open] summary{color:#fff;background:#1c1e23}' +
'.odn-pop{position:absolute;right:0;top:calc(100% + 6px);min-width:168px;padding:6px;background:#17191d;border:1px solid #2c2f36;border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.5);z-index:70}' +
'.odn-pop a{display:block;padding:8px 12px;border-radius:6px;color:#d6d9df}.odn-pop a:hover{background:#24272d;color:#fff}' +
'.odn-pop a[aria-current]{color:#fff;background:#1e2a4a}' +
'.odn-menu{display:none}' +
'.odn-l2{display:flex;align-items:center;gap:12px;min-height:44px;padding:0 16px;border-top:1px solid #1d1f24;background:#121316}' +
'.odn-sub{display:flex;flex-wrap:nowrap;font-size:13px;align-items:center;gap:4px;min-width:0;flex:1 1 auto;overflow-x:auto;scrollbar-width:none;padding:6px 0}' +
'.odn-sub::-webkit-scrollbar{display:none}' +
'.odn-sub>*{flex:none}' +
'.odn-sub a.odn-t{display:inline-flex;align-items:center;height:30px;padding:0 12px;border-radius:999px;color:#a4a9b3;white-space:nowrap;font-size:13px;transition:background .15s,color .15s}' +
'.odn-sub a.odn-t:hover{color:#fff;background:#1f2126}' +
'.odn-sub a.odn-t[aria-current]{color:#fff;background:#25324f}' +
'.odn-sub a.odn-t.odn-off{color:#5f646e}' +
'.odn-sub .odn-sep{width:1px;height:18px;background:#2c2f36;margin:0 6px}' +
/* 页面交来的子页签（行情按钮、回放按钮）统一成页签外观 */
'.odn-sub .od-row,.odn-sub .chips{display:flex!important;align-items:center;gap:4px!important;padding:0!important;margin:0!important;flex-wrap:nowrap}' +
'.odn-sub .tk,.odn-sub .chip{display:inline-flex!important;flex-direction:row!important;align-items:baseline;gap:8px!important;height:30px;min-height:30px!important;padding:0 12px!important;margin:0!important;border:0!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:#a4a9b3!important;font-size:13px!important;white-space:nowrap;cursor:pointer;line-height:30px!important}' +
'.odn-sub .tk:hover,.odn-sub .chip:hover{background:#1f2126!important;color:#fff!important}' +
'.odn-sub .tk[aria-current=true],.odn-sub .tk[aria-pressed=true],.odn-sub .chip[aria-current=true],.odn-sub .chip[aria-pressed=true]{background:#25324f!important;color:#fff!important}' +
'.odn-sub .tk .tk-n{font-size:13px!important;color:inherit!important}' +
'.odn-sub .tk .tk-v{font-size:12px!important;font-weight:500!important}' +
'.odn-sub .tk .tk-v span{margin-left:4px!important}' +
'.odn-sub .strip-k{font-size:12px;color:#6c727d;padding:0 4px 0 8px;white-space:nowrap}' +
'.odn-tools{flex:none;display:flex;align-items:center;gap:8px;max-width:60%;overflow-x:auto;scrollbar-width:none}' +
'.odn-tools .cmd{min-width:420px}' +
'.odn-tools .strip-k{font-size:12px;color:#6c727d;white-space:nowrap}' +
'.odn-tools .chips{display:flex;gap:4px;padding:0!important}' +
'@media (max-width:860px){' +
'.odn-main{display:none}.odn-menu{display:block}' +
'.odn-l2{flex-wrap:wrap;padding:0 12px}.odn-tools{max-width:none;width:100%;padding-bottom:8px}.odn-tools .cmd{min-width:0;width:100%}' +
'.odn-asof{display:none}}' +
/* 浅色主题（蓝白首页用） */'.odn.odn-light{background:#fff;border-bottom-color:#e3e8ef;color:#1b2433}.odn-light .odn-brand{color:#1b2433}.odn-light .odn-main a{color:#4a5568}.odn-light .odn-main a:hover,.odn-light .odn-main a[aria-current]{color:#1b2433}.odn-light .odn-main a[aria-current]::after{background:#1f5fd6}.odn-light .odn-l2{background:#f6f8fb;border-top-color:#e3e8ef}.odn-light .odn-sub a.odn-t{color:#4a5568}.odn-light .odn-sub a.odn-t:hover{background:#e9eef5;color:#1b2433}.odn-light .odn-sub a.odn-t[aria-current]{background:#1f5fd6;color:#fff}.odn-light summary{color:#4a5568;border-color:#d8dee8}.odn-light summary:hover,.odn-light details[open] summary{background:#eef2f7;color:#1b2433}.odn-light .odn-pop{background:#fff;border-color:#e3e8ef;box-shadow:0 12px 32px rgba(27,36,51,.15)}.odn-light .odn-pop a{color:#1b2433}.odn-light .odn-pop a:hover{background:#eef2f7;color:#1b2433}.odn-light .odn-asof>*{color:#6b7689!important}' +
'@media (prefers-reduced-motion:reduce){.odn *{transition:none!important}}';

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
  menu.innerHTML = '<summary aria-label="打开导航菜单">菜单 ▾</summary><div class="odn-pop">' +
    MAIN.map(function (m) { return '<a href="' + m.h + '"' + (isMain(m) ? ' aria-current="page"' : '') + '>' + esc(m.t) + '</a>'; }).join('') + '</div>';
  right.appendChild(menu);
  var help = el('details', 'odn-help');
  help.innerHTML = '<summary>帮助 ▾</summary><div class="odn-pop">' +
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
        if (d.label) { var lb = el('span', 'strip-k', esc(d.t)); lb.style.cssText = 'font-size:12px;opacity:.7;padding:0 6px'; sub.appendChild(lb); return; }
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
    l2.appendChild(sub);
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
