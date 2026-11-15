/* 临界点 · 全站搜索弹窗的纯逻辑（Open Design 维护）
   不读任何业务 JSON：候选行由页面通过 LPPL.stockList()/LPPL.SYMS 取好后传入。
   match 复用 stock-search.js（名称 / 拼音首字母 / 代码前缀），本文件只负责
   类型筛选、板块标签、链接目标与“最近访问”。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./stock-search.js'));
  else root.OdSearch = factory(root.StockSearch);
})(typeof window !== 'undefined' ? window : globalThis, function (StockSearch) {
  'use strict';
  var RECENT_KEY = 'lppl.recent.v1', RECENT_MAX = 8;
  var KIND_LABEL = { index: '指数', industry: '行业', stock: '个股', us: '美股' };

  /* 6 位 A 股代码 → 板块；指数/美股返回空 */
  function board(code) {
    var c = String(code || '');
    if (!/^\d{6}$/.test(c)) return '';
    if (/^(60|601|603|605)/.test(c)) return '沪主';
    if (/^68/.test(c)) return '科创';
    if (/^30/.test(c)) return '创业';
    if (/^00/.test(c)) return '深主';
    if (/^(4|8|92)/.test(c)) return '北交';
    return '';
  }
  function kindOf(row) {
    if (!row) return 'stock';
    if (row.kind === 'index' || row.type === 'index') return 'index';
    if (row.type === 'industry') return 'industry';
    if (row.kind === 'us' || /^US_/i.test(row.code || '')) return 'us';
    return 'stock';
  }
  function href(kind, code, sym) {
    if (kind === 'index') return 'index.html?code=' + encodeURIComponent(sym || code);
    return 'stock.html?code=' + encodeURIComponent(code);
  }
  function hit(kind, code, sym, name, opts) {
    var o = opts || {}, b = kind === 'stock' ? board(code) : '';
    var tags = [KIND_LABEL[kind] || kind];
    if (b) tags.push(b);
    return {
      t: name, code: code, sym: sym || '', kind: kind, board: b,
      tags: tags, published: !!o.published,
      s: tags.join(' · ') + ' · ' + code,
      h: href(kind, code, sym),
      chart: kind === 'index' ? 'index.html?code=' + encodeURIComponent(sym || code) : ''
    };
  }

  /* search({ idx, rows, query, filter, limit, published })
     idx：LPPL.SYMS 形状 [{sym,name,code,alias}]；rows：stock_list 行；
     filter：all | index | stock；published：Set/数组（已发布结果的代码），只用于标记 */
  function search(p) {
    var q = String(p.query == null ? '' : p.query).trim().replace(/\.(SH|SZ)$/i, '');
    var filter = p.filter || 'all', limit = p.limit || 10, out = [], seen = Object.create(null);
    if (!q) return out;
    var lo = q.toLowerCase();
    var pub = p.published ? (p.published instanceof Set ? p.published : new Set(p.published)) : new Set();
    function add(h) { if (!seen[h.h]) { seen[h.h] = true; out.push(h); } }
    if (filter === 'all' || filter === 'index') {
      (p.idx || []).forEach(function (x) {
        var names = [x.name, x.code, x.sym].concat(x.alias || []);
        if (names.some(function (n) { return String(n).toLowerCase().indexOf(lo) >= 0; })) {
          add(hit('index', x.code, x.sym, x.name, { published: true }));
        }
      });
    }
    if (filter === 'all' || filter === 'stock') {
      var rows = p.rows || [];
      if (rows.length && StockSearch) {
        StockSearch.match(rows, q, limit).forEach(function (row) {
          var k = kindOf(row);
          if (k === 'index') { if (filter === 'stock') return; add(hit('index', row.code, row.code, row.name, { published: true })); return; }
          add(hit(k, row.code, '', row.name, { published: pub.has(row.code) }));
        });
        var fb = StockSearch.codeFallback(rows, q);
        if (fb && !seen[fb.h]) add(hit('stock', q, '', fb.t, { published: pub.has(q) }));
      } else if (/^\d{6}$/.test(q)) add(hit('stock', q, '', q, { published: pub.has(q) }));
      else if (/^(US_)?[A-Za-z.]{1,6}$/.test(q)) {
        var u = q.replace(/^US_/i, '').toUpperCase();
        add(hit('us', 'US_' + u, '', u, { published: pub.has('US_' + u) }));
      }
    }
    return out.slice(0, limit);
  }

  /* 最近访问：只存 {code, sym, name, kind}，不存任何数值 */
  function readRecent(storage) {
    try {
      var list = JSON.parse((storage && storage.getItem(RECENT_KEY)) || '[]');
      if (!Array.isArray(list)) return [];
      return list.filter(function (x) { return x && typeof x.code === 'string' && typeof x.name === 'string'; }).slice(0, RECENT_MAX);
    } catch (e) { return []; }
  }
  function pushRecent(storage, item) {
    if (!storage || !item || !item.code) return readRecent(storage);
    var rec = { code: String(item.code), sym: String(item.sym || ''), name: String(item.name || item.code), kind: item.kind || kindOf(item) };
    var old = readRecent(storage), prev = old.filter(function (x) { return x.code === rec.code; })[0];
    if (prev) {
      if (rec.name === rec.code && prev.name !== prev.code) rec.name = prev.name; /* 页面只知道代码时沿用已记住的名称 */
      if (!rec.sym && prev.sym) rec.sym = prev.sym;
    }
    var list = old.filter(function (x) { return x.code !== rec.code; });
    list.unshift(rec);
    list = list.slice(0, RECENT_MAX);
    try { storage.setItem(RECENT_KEY, JSON.stringify(list)); } catch (e) { /* 存储不可用 */ }
    return list;
  }
  function recentHits(storage) {
    return readRecent(storage).map(function (r) { return hit(r.kind || 'stock', r.code, r.sym, r.name, {}); });
  }

  return { RECENT_KEY: RECENT_KEY, RECENT_MAX: RECENT_MAX, KIND_LABEL: KIND_LABEL, board: board, kindOf: kindOf, href: href, search: search, readRecent: readRecent, pushRecent: pushRecent, recentHits: recentHits };
});
