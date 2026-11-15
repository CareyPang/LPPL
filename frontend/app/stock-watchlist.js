(function (root) {
  'use strict';
  const KEY = 'lppl.watchlist.v1';
  const MAX = 50;
  const CODE = /^\d{6}$/;

  function normalize(values) {
    if (!Array.isArray(values)) return [];
    const seen = new Set();
    const result = [];
    for (const value of values) {
      const code = String(value ?? '');
      if (!CODE.test(code) || seen.has(code)) continue;
      seen.add(code);
      result.push(code);
      if (result.length === MAX) break;
    }
    return result;
  }

  function read(storage) {
    try {
      return normalize(JSON.parse(storage?.getItem(KEY) || '[]'));
    } catch {
      return [];
    }
  }

  function write(storage, values) {
    const list = normalize(values);
    try {
      if (!storage) return null;
      storage.setItem(KEY, JSON.stringify(list));
      return list;
    } catch {
      return null;
    }
  }

  const api = { KEY, MAX, isValid: value => CODE.test(String(value ?? '')), normalize, read, write };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.StockWatchlist = api;
})(typeof window === 'undefined' ? globalThis : window);
