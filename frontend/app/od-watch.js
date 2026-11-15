/* 临界点 · 全局「☆ 自选」抽屉（Open Design 维护）
   任意页面从右侧滑出；指数自选读 IndexWatchlist（lppl.watchlist.idx.v1），个股自选读 StockWatchlist（lppl.watchlist.v1）。
   行情 = 后端日更的收盘价与涨跌幅（不是实时价）；模型状态 = 已发布 JSON 的 signal_status 文案。
   所有数据只经 window.LPPL 读取，本文件不计算任何模型值。 */
(function () {
  'use strict';
  var me = document.currentScript;
  var base = me && me.src ? me.src.replace(/[^/]*$/, '') : 'app/';
  var SIG = { signal: '顶部结构', no_qualified_fit: '无合格拟合', t1_not_qualified: '起点未达标', not_computed: '未计算', insufficient_data: '数据不足' };
  var CSS = '' +
'.odw-bg{position:fixed;inset:0;z-index:80;background:rgba(19,23,34,.35);opacity:0;pointer-events:none;transition:opacity .18s}' +
'.odw-bg.on{opacity:1;pointer-events:auto}' +
'.odw{position:fixed;top:0;right:0;bottom:0;z-index:81;width:min(400px,100vw);background:#fff;color:#131722;box-shadow:-12px 0 40px rgba(19,23,34,.16);transform:translateX(104%);transition:transform .2s;display:flex;flex-direction:column;font:14px/1.45 "Microsoft YaHei UI","PingFang SC","Noto Sans SC",system-ui,sans-serif}' +
'.odw.on{transform:none}' +
'.odw-h{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid #e6e9ef}' +
'.odw-h b{font-size:16px}.odw-h .n{color:#6a6d78;font-size:12px}' +
'.odw-x{margin-left:auto;width:32px;height:32px;border:1px solid #e0e3eb;border-radius:999px;background:#fff;color:#4c525e;cursor:pointer;font:16px/1 system-ui}' +
'.odw-x:hover{background:#f0f3fa;color:#131722}' +
'.odw-v{display:flex;gap:6px;padding:10px 16px 0}' +
'.odw-v button{font:600 12px/1 inherit;padding:7px 12px;border:1px solid #e0e3eb;border-radius:999px;background:#fff;color:#4c525e;cursor:pointer}' +
'.odw-v button[aria-pressed=true]{background:#131722;border-color:#131722;color:#fff}' +
'.odw-b{flex:1;overflow-y:auto;padding:8px 8px 16px}' +
'.odw-g{margin:8px 8px 2px;font-size:12px;color:#6a6d78}' +
'.odw-i{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:10px;padding:10px 8px;border-radius:10px;color:inherit;text-decoration:none}' +
'.odw-i:hover{background:#f0f3fa}' +
'.odw-i .nm{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.odw-i .cd{font:12px Consolas,"Cascadia Mono",monospace;color:#6a6d78}' +
'.odw-i .px{text-align:right;font:500 13px Consolas,"Cascadia Mono",monospace;font-variant-numeric:tabular-nums;white-space:nowrap}' +
'.odw-i .px small{display:block;font-size:11px;color:#6a6d78}' +
'.odw-i .up{color:#d6303a}.odw-i .dn{color:#11845a}' +
'.odw-i .st{font-size:12px;color:#4c525e;text-align:right;max-width:140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
'.odw-i .rm{width:28px;height:28px;border:0;border-radius:999px;background:transparent;color:#9aa0ab;cursor:pointer;font:14px/1 system-ui}' +
'.odw-i .rm:hover{background:#fde8ea;color:#d6303a}' +
'.odw-e{padding:24px 16px;color:#6a6d78;font-size:13px;line-height:1.7}' +
'.odw-f{padding:10px 16px;border-top:1px solid #e6e9ef;font-size:11px;color:#6a6d78}' +
'@media (prefers-reduced-motion:reduce){.odw,.odw-bg{transition:none}}';
  var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function load(name) {
    if (name === 'watchlist.js' && window.IndexWatchlist) return Promise.resolve(true);
    if (name === 'stock-watchlist.js' && window.StockWatchlist) return Promise.resolve(true);
    return new Promise(function (resolve) {
      var s = document.createElement('script'); s.src = base + name;
      s.onload = function () { resolve(true); }; s.onerror = function () { resolve(false); };
      document.head.appendChild(s);
    });
  }
  var deps = null;
  function ready() {
    if (!deps) deps = Promise.all([load('stock-watchlist.js'), load('watchlist.js')]);
    return deps;
  }

  var bg = document.createElement('div'); bg.className = 'odw-bg';
  var box = document.createElement('aside'); box.className = 'odw'; box.setAttribute('aria-label', '自选'); box.hidden = true;
  var view = 'quote';
  box.innerHTML = '<div class="odw-h"><b>☆ 自选</b><span class="n" id="odw-n"></span><button type="button" class="odw-x" aria-label="关闭自选">×</button></div>' +
    '<div class="odw-v" role="group" aria-label="显示"><button type="button" data-v="quote" aria-pressed="true">行情</button><button type="button" data-v="model" aria-pressed="false">模型状态</button></div>' +
    '<div class="odw-b" id="odw-b"></div>' +
    '<div class="odw-f">行情为后端日更收盘价，不是实时价；模型状态来自已发布结果，描述历史结构，不是预测。自选只存在本浏览器。</div>';
  document.body.appendChild(bg); document.body.appendChild(box);
  var body = box.querySelector('#odw-b'), nEl = box.querySelector('#odw-n');

  function pct(last, prev) {
    if (!last || !prev || !prev.c) return '';
    var p = (last.c / prev.c - 1) * 100;
    return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
  }
  function row(h) {
    var right = view === 'quote'
      ? '<span class="px ' + (h.cls || '') + '">' + esc(h.px || '—') + '<small>' + esc(h.chg || (h.asof ? '收盘 ' + h.asof : '')) + '</small></span>'
      : '<span class="st" title="' + esc(h.status || '') + '">' + esc(h.status || '—') + '</span>';
    return '<div class="odw-i"><a class="nm" href="' + esc(h.h) + '" style="color:inherit;text-decoration:none;min-width:0">' + esc(h.name) + '<br><span class="cd">' + esc(h.code) + (h.asof && view === 'model' ? ' · ' + esc(h.asof) : '') + '</span></a>' +
      right + '<button type="button" class="rm" data-rm="' + esc(h.key) + '" data-kind="' + h.kind + '" aria-label="移除 ' + esc(h.name) + '">×</button></div>';
  }
  var cache = {};
  function idxItem(sym) {
    var L = window.LPPL, S = L && L.resolve ? L.resolve(sym) : null;
    var base0 = { key: sym, kind: 'index', code: (S && S.code) || sym, name: (S && S.name) || sym, h: 'index.html?code=' + encodeURIComponent(sym) };
    if (!L || !L.load) return Promise.resolve(base0);
    if (cache[sym]) return cache[sym];
    cache[sym] = L.load(sym).then(function (D) {
      var lb = D.bars[D.bars.length - 1], pb = D.bars[D.bars.length - 2], t = D.top || {};
      var last = lb ? { c: lb.close } : null, prev = pb ? { c: pb.close } : null;
      var chg = pct(last, prev);
      return Object.assign(base0, { name: D.name, asof: D.asof, px: last ? String(Math.round(last.c * 100) / 100) : '—', chg: chg ? chg + ' · 收盘 ' + D.asof : '', cls: chg.charAt(0) === '+' ? 'up' : chg ? 'dn' : '', status: SIG[t.signal_status] || t.signal_status || '无状态' });
    }).catch(function () { return Object.assign(base0, { status: '数据未加载' }); });
    return cache[sym];
  }
  function stkItem(code) {
    var L = window.LPPL;
    var base0 = { key: code, kind: 'stock', code: code, name: code, h: 'stock.html?code=' + encodeURIComponent(code) };
    if (!L || !L.stock) return Promise.resolve(base0);
    if (cache[code]) return cache[code];
    cache[code] = L.stock.latest(code).then(function (J) {
      if (!J) return Object.assign(base0, { status: '未发布结果', chg: '未发布结果' });
      var ph = J.price_history || {}, c = ph.close || [], n = c.length, t = J.top || {};
      var last = n ? { c: c[n - 1] } : null, prev = n > 1 ? { c: c[n - 2] } : null, chg = pct(last, prev);
      return Object.assign(base0, { name: J.name || code, asof: J.asof, px: last ? String(Math.round(last.c * 100) / 100) : '—', chg: chg ? chg + ' · 收盘 ' + J.asof : '', cls: chg.charAt(0) === '+' ? 'up' : chg ? 'dn' : '', status: SIG[t.signal_status] || t.signal_status || '无状态' });
    }).catch(function () { return Object.assign(base0, { status: '数据未加载' }); });
    return cache[code];
  }
  var seq = 0;
  function render() {
    var my = ++seq;
    ready().then(function () {
      var IW = window.IndexWatchlist, SW = window.StockWatchlist;
      var idx = IW ? IW.read() : [], stocks = IW ? IW.stocks() : (SW ? SW.read(window.localStorage) : []);
      nEl.textContent = (idx.length + stocks.length) ? idx.length + stocks.length + ' 个' : '';
      if (!idx.length && !stocks.length) {
        body.innerHTML = '<div class="odw-e">还没有自选。在图表页或标的页点「☆ 加自选」，这里就会按行情或模型状态列出来。</div>';
        return;
      }
      body.innerHTML = '<div class="odw-e">加载中…</div>';
      Promise.all([Promise.all(idx.map(idxItem)), Promise.all(stocks.map(stkItem))]).then(function (r) {
        if (my !== seq) return;
        var html = '';
        if (r[0].length) html += '<div class="odw-g">指数</div>' + r[0].map(row).join('');
        if (r[1].length) html += '<div class="odw-g">个股</div>' + r[1].map(row).join('');
        body.innerHTML = html;
      });
    });
  }
  function open() {
    box.hidden = false;
    requestAnimationFrame(function () { box.classList.add('on'); bg.classList.add('on'); });
    render();
    var x = box.querySelector('.odw-x'); if (x) x.focus();
    document.dispatchEvent(new CustomEvent('odw-open'));
  }
  function close() {
    box.classList.remove('on'); bg.classList.remove('on');
    setTimeout(function () { if (!box.classList.contains('on')) box.hidden = true; }, 220);
  }
  function isOpen() { return box.classList.contains('on'); }
  bg.addEventListener('click', close);
  box.querySelector('.odw-x').addEventListener('click', close);
  box.querySelector('.odw-v').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-v]'); if (!b) return;
    view = b.dataset.v;
    box.querySelectorAll('.odw-v button').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
    render();
  });
  body.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-rm]'); if (!b) return;
    e.preventDefault();
    if (b.dataset.kind === 'index' && window.IndexWatchlist) window.IndexWatchlist.toggle(b.dataset.rm);
    else if (window.StockWatchlist) {
      var sw = window.StockWatchlist, list = sw.read(window.localStorage).filter(function (c) { return c !== b.dataset.rm; });
      sw.write(window.localStorage, list);
      try { window.dispatchEvent(new CustomEvent('lppl-watch')); } catch (err) { /* 无事件环境 */ }
    }
    render();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && isOpen()) close(); });
  window.addEventListener('lppl-watch', function () { if (isOpen()) render(); });
  window.addEventListener('storage', function () { if (isOpen()) render(); });

  window.OdWatch = { open: open, close: close, toggle: function () { isOpen() ? close() : open(); }, isOpen: isOpen, render: render };
})();
