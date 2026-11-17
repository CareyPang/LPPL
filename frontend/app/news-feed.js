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

  function dateValue(value) {
    var text = typeof value === 'string' ? value.trim() : '';
    var date = new Date(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(text)
      ? text.slice(0, 16).replace(' ', 'T') + ':00+08:00' : text);
    return Number.isFinite(date.getTime()) ? date : null;
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

  function dedupe(rows, filter, watchlist, watchOnly) {
    var items = [
      ...(filter === 'em' ? [] : rowsFor(rows, 'cls').map(function (row) { return Object.assign({}, row, { k: 'cls' }); })),
      ...(filter === 'cls' ? [] : rowsFor(rows, 'eastmoney').map(function (row) { return Object.assign({}, row, { k: 'em' }); })),
    ].map(function (row) {
      return Object.assign({}, row, { d: dateValue(row.time), ks: [row.k] });
    }).filter(function (row) {
      return !watchOnly || mentions(row, watchlist);
    }).sort(function (a, b) {
      return (b.d ? b.d.getTime() : 0) - (a.d ? a.d.getTime() : 0);
    });
    var seen = new Map();
    items.forEach(function (row) {
      var title = String(row.title || '')
        .replace(/^财联社\d+月\d+日电[，,]?/, '')
        .replace(/[\s，,。！!：:；;“”"'（）()【】\[\]]/g, '')
        .slice(0, 40);
      var previous = seen.get(title);
      if (previous && Math.abs((previous.d ? previous.d.getTime() : 0) - (row.d ? row.d.getTime() : 0)) <= 6 * 3600 * 1000) {
        if (!previous.ks.includes(row.k)) previous.ks.push(row.k);
        if (!/^https?:\/\//i.test(previous.url) && /^https?:\/\//i.test(row.url)) previous.url = row.url;
        if (!previous.d && row.d) previous.d = row.d;
        row.dup = true;
      } else seen.set(title, row);
    });
    return items.filter(function (row) { return !row.dup; });
  }

  function relatedCount(rows, today, watchlist, dayOf) {
    var dateOf = typeof dayOf === 'function'
      ? dayOf
      : function (value) { return dateValue(value)?.toISOString().slice(0, 10) || ''; };
    return dedupe(rows, 'all', watchlist, true)
      .filter(function (row) { return dateOf(row.time) === today; }).length;
  }

  return {
    key: key,
    diff: diff,
    merge: merge,
    mentions: mentions,
    dateValue: dateValue,
    dedupe: dedupe,
    relatedCount: relatedCount,
  };
});
