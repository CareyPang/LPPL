(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LPPLNewsFeed = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var SOURCES = ['cls', 'eastmoney'];

  function key(row, source) {
    var id = row && (row.id ?? row.article_id ?? row.articleId);
    if (id != null && String(id).trim()) return source + ':id:' + String(id).trim();
    var link = row && (row.url || row.link);
    var time = row && (row.time || row.datetime) || '';
    if (link) return source + ':link:' + String(link).trim() + '\u0000' + String(time);
    return source + ':time-title:' + String(time) + '\u0000' + String(row && row.title || '');
  }

  function rowsFor(rows, source) {
    return rows && Array.isArray(rows[source]) ? rows[source] : [];
  }

  function diff(current, incoming) {
    var added = { cls: [], eastmoney: [] }, count = 0;
    SOURCES.forEach(function (source) {
      var known = new Set(rowsFor(current, source).map(function (row) { return key(row, source); }));
      added[source] = rowsFor(incoming, source).filter(function (row) {
        if (known.has(key(row, source))) return false;
        known.add(key(row, source));
        count += 1;
        return true;
      });
    });
    return { count: count, added: added };
  }

  function merge(current, incoming) {
    var result = {};
    SOURCES.forEach(function (source) {
      var byKey = new Map();
      rowsFor(current, source).forEach(function (row) { byKey.set(key(row, source), row); });
      rowsFor(incoming, source).forEach(function (row) { byKey.set(key(row, source), row); });
      result[source] = Array.from(byKey.values());
    });
    return result;
  }

  function mentions(row, watchlist) {
    var entries = Array.isArray(watchlist) ? watchlist : [];
    var text = [row && row.title, row && row.content, row && row.summary, row && row.description]
      .filter(Boolean).join(' ');
    return entries.some(function (entry) {
      var code = typeof entry === 'string' ? entry : entry && entry.code;
      var name = typeof entry === 'object' && entry ? entry.name : '';
      if (typeof name === 'string' && name.trim() && text.includes(name.trim())) return true;
      if (typeof code !== 'string' || !/^\d{6}$/.test(code)) return false;
      return new RegExp('(^|\\D)' + code + '(?=\\D|$)').test(text);
    });
  }

  return { key: key, diff: diff, merge: merge, mentions: mentions };
});
