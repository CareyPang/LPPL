/* 临界点 · 标的页吸顶头部与页签（Open Design 维护）
   只展示页面已经拿到的后端数据（render(d, name) 传入的 d）与 LPPL.catalog() 的归属信息；不计算模型。
   页签条本身 sticky（高度固定），头部滚出视口后在页签条左侧补一行“名称 · 收盘”，不改变任何容器高度，滚动不跳。 */
(function (root) {
  'use strict';
  /* 地址兼容：?s=sh600519 → ?code=600519（在 StockView.mount 读取 ?code 之前执行） */
  try {
    var q0 = new URLSearchParams(root.location.search), s0 = q0.get('s');
    if (s0 && !q0.get('code')) {
      var c0 = String(s0).replace(/^(sh|sz)/i, '');
      if (/^(\d{6}|US_[A-Za-z.]+)$/.test(c0)) { q0.delete('s'); q0.set('code', c0); root.location.replace(root.location.pathname + '?' + q0 + root.location.hash); }
    }
  } catch (e) { /* 非浏览器环境 */ }
  var TABS = [['overview', '概览', 'summary'], ['top', '逃顶', 'sec-top'], ['dip', '抄底', 'sec-dip'], ['events', '事件', 'recent-events'], ['data', '数据与证据', 'stock-meta']];
  var catalogPromise = null, catalogRows = null;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function loadCatalog() {
    if (catalogRows) return Promise.resolve(catalogRows);
    if (catalogPromise) return catalogPromise;
    if (!root.LPPL || typeof root.LPPL.catalog !== 'function') return Promise.resolve(null);
    catalogPromise = root.LPPL.catalog().then(function (J) { catalogRows = (J && J.rows) || []; catalogRows.names = (J && J.index_names) || {}; return catalogRows; })
      .catch(function () { catalogPromise = null; return null; });
    return catalogPromise;
  }
  function code6(sym) { var m = String(sym || '').match(/\d{6}$/); return m ? m[0] : String(sym || ''); }
  function board(code) {
    var c = String(code || '');
    if (/^US_/i.test(c)) return '美股';
    if (/^(60|601|603|605)/.test(c)) return '沪主'; if (/^68/.test(c)) return '科创'; if (/^30/.test(c)) return '创业'; if (/^00/.test(c)) return '深主'; if (/^(4|8|92)/.test(c)) return '北交';
    return '';
  }
  function daysSince(ymd) {
    var t = Date.parse(ymd + 'T00:00:00+08:00');
    return Number.isFinite(t) ? Math.floor((Date.now() - t) / 86400000) : NaN;
  }
  function mount(opts) {
    var doc = (opts && opts.document) || root.document;
    var host = doc.getElementById('sym-head');
    if (!host) return null;
    host.innerHTML =
      '<div class="sh-main" id="sh-main"><div class="sh-l"><div class="sh-name"><h2 id="sh-name">—</h2><span class="sh-code m" id="sh-code"></span></div>' +
      '<div class="sh-tags" id="sh-tags"></div><div class="sh-mem" id="sh-mem"></div></div>' +
      '<div class="sh-r"><div class="sh-px"><b class="m" id="sh-close">—</b><span class="m" id="sh-chg"></span></div><div class="sh-asof" id="sh-asof"></div>' +
      '<div class="sh-act"><button type="button" class="sh-star" id="sh-star" aria-pressed="false">☆ 加自选</button><a class="sh-chart" id="sh-chart" hidden>完整图表 ›</a></div></div></div>' +
      '<nav class="sh-tabs" id="sh-tabs" aria-label="标的页签"><div class="sh-mini" id="sh-mini" aria-hidden="true"></div>' +
      TABS.map(function (t) { return '<a href="#' + t[2] + '" data-tab="' + t[0] + '" data-target="' + t[2] + '">' + t[1] + '</a>'; }).join('') + '</nav>';
    var $ = function (id) { return doc.getElementById(id); };
    var tabs = $('sh-tabs'), main = $('sh-main'), star = $('sh-star'), pageToggle = $('watch-toggle');
    /* ☆ 复用页面已有的自选按钮逻辑（StockWatchlist），这里只做镜像 */
    if (pageToggle) {
      var mirror = function () {
        var on = pageToggle.getAttribute('aria-pressed') === 'true';
        star.setAttribute('aria-pressed', String(on)); star.textContent = on ? '★ 已自选' : '☆ 加自选'; star.disabled = pageToggle.disabled;
      };
      new MutationObserver(mirror).observe(pageToggle, { attributes: true, attributeFilter: ['aria-pressed', 'disabled'] });
      star.addEventListener('click', function () { pageToggle.click(); });
      mirror();
    }
    function navH() { var h = doc.querySelector('header.odn'); return h ? h.getBoundingClientRect().height : 0; }
    function setActive(id) {
      tabs.querySelectorAll('a[data-tab]').forEach(function (a) {
        var on = a.dataset.target === id;
        if (on) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
      });
    }
    tabs.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-tab]'); if (!a) return;
      var n = $(a.dataset.target); if (!n) return;
      e.preventDefault();
      n.style.scrollMarginTop = (navH() + tabs.getBoundingClientRect().height + 12) + 'px';
      n.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setActive(a.dataset.target);
      if (root.history.replaceState) {
        var u = new URL(root.location.href); u.hash = 'tab=' + a.dataset.tab; root.history.replaceState(null, '', u);
      }
    });
    var ticking = false;
    function onScroll() {
      if (ticking) return; ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        var r = main.getBoundingClientRect(), nh = navH();
        tabs.classList.toggle('compact', r.bottom <= nh + 2);
        tabs.style.top = nh + 'px';
        var off = nh + tabs.getBoundingClientRect().height + 16, best = null;
        TABS.forEach(function (t) {
          var n = $(t[2]); if (!n || n.hidden || !n.getClientRects().length) return;
          var top = n.getBoundingClientRect().top;
          if (top - off <= 1 && (best === null || top > best.top)) best = { id: t[2], top: top };
        });
        if (best) setActive(best.id);
        tabs.querySelectorAll('a[data-tab]').forEach(function (a) { var n = $(a.dataset.target); a.classList.toggle('sh-off', !n || n.hidden || !n.getClientRects().length); });
      });
    }
    root.addEventListener('scroll', onScroll, { passive: true });
    root.addEventListener('resize', onScroll);
    setInterval(onScroll, 1200);
    onScroll();

    function update(d, name) {
      if (!d) return;
      var code = code6(d.symbol), nm = name || code;
      $('sh-name').textContent = nm; $('sh-code').textContent = code;
      var ph = d.price_history || {}, c = ph.close || [], n = c.length;
      var last = n ? c[n - 1] : null, prev = n > 1 ? c[n - 2] : null;
      var chg = last != null && prev ? (last / prev - 1) * 100 : null;
      $('sh-close').textContent = last != null ? Number(last).toFixed(2) : '—';
      var chgEl = $('sh-chg');
      chgEl.textContent = chg != null ? (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '';
      chgEl.className = 'm ' + (chg == null ? '' : chg >= 0 ? 'up' : 'dn');
      var age = daysSince(d.asof), stale = Number.isFinite(age) && age > 5;
      $('sh-asof').innerHTML = '<span class="' + (stale ? 'sh-stale' : '') + '">收盘 ' + esc(d.asof || '—') + (stale ? ' · 距今 ' + age + ' 天' : '') + '</span><span class="sh-dim"> · 后复权 · 不是实时价</span>';
      $('sh-mini').textContent = nm + ' ' + (last != null ? Number(last).toFixed(2) : '') + (chg != null ? ' ' + (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '');
      var us = /^US_/i.test(d.symbol || '');
      var tags = [us ? '美股' : '个股']; var b = board(code); if (b && !us) tags.push(b);
      if (d.stock_meta && d.stock_meta.st) tags.push('ST');
      $('sh-tags').innerHTML = tags.map(function (t) { return '<i>' + esc(t) + '</i>'; }).join('');
      var chart = $('sh-chart'), S = root.LPPL && root.LPPL.resolve ? root.LPPL.resolve(code) : null;
      if (S && S.sym) { chart.hidden = false; chart.href = 'index.html?code=' + encodeURIComponent(S.sym); } else chart.hidden = true;
      $('sh-mem').innerHTML = '';
      loadCatalog().then(function (rows) {
        if (!rows) return;
        var row = null;
        for (var i = 0; i < rows.length; i++) if (rows[i].code === code) { row = rows[i]; break; }
        if (!row || !row.member_of || !row.member_of.length) return;
        $('sh-mem').innerHTML = '属于：' + row.member_of.map(function (m) {
          return '<a href="index.html?code=' + encodeURIComponent(m) + '">' + esc(rows.names[m] || m) + '</a>';
        }).join(' · ');
      });
      onScroll();
    }
    return { update: update, setActive: setActive };
  }
  root.StockHeader = { mount: mount, TABS: TABS };
})(typeof window !== 'undefined' ? window : globalThis);
