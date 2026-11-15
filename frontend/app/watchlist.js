/* 临界点 · 本地自选（指数 + 个股）
   个股沿用 StockWatchlist（lppl.watchlist.v1，六位代码），本文件不改它的格式；
   指数单独存放在 lppl.watchlist.idx.v1，值为 LPPL.SYMS 里的 sym（如 sh000001）。
   只存代码，不存任何数值；读不到浏览器存储时一律按空处理。 */
(function (root) {
  'use strict';
  const KEY = 'lppl.watchlist.idx.v1';
  const SYM = /^(sh|sz)\d{6}$/;
  const known = () => ((root.LPPL && root.LPPL.SYMS) || []).map((x) => x.sym);

  function normalize(values) {
    if (!Array.isArray(values)) return [];
    const ok = known(), seen = new Set(), out = [];
    for (const v of values) {
      const s = String(v ?? '').toLowerCase();
      if (!SYM.test(s) || seen.has(s) || (ok.length && !ok.includes(s))) continue;
      seen.add(s); out.push(s);
    }
    return out;
  }
  function storage() {
    try { const s = root.localStorage; s.getItem(KEY); return s; } catch { return null; }
  }
  function read(st = storage()) {
    try { return normalize(JSON.parse((st && st.getItem(KEY)) || '[]')); } catch { return []; }
  }
  function write(values, st = storage()) {
    const list = normalize(values);
    try { if (!st) return null; st.setItem(KEY, JSON.stringify(list)); return list; } catch { return null; }
  }
  const has = (sym) => read().includes(String(sym || '').toLowerCase());
  /* 返回切换后的状态；存储不可用时返回 null */
  function toggle(sym) {
    const s = String(sym || '').toLowerCase(), list = read();
    const next = list.includes(s) ? list.filter((x) => x !== s) : list.concat(s);
    const saved = write(next);
    if (saved === null) return null;
    try { root.dispatchEvent(new CustomEvent('lppl-watch')); } catch { /* 无事件环境 */ }
    return saved.includes(s);
  }
  const stocks = () => (root.StockWatchlist ? root.StockWatchlist.read(storage()) : []);

  const api = { KEY, isValid: (v) => SYM.test(String(v ?? '')), normalize, read, write, has, toggle, stocks, available: () => !!storage() };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.IndexWatchlist = api;
})(typeof window === 'undefined' ? globalThis : window);
