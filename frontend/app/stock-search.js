(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.StockSearch = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function rowRecord(row, fields) {
    if (Array.isArray(row)) {
      return {
        code: String(row[fields.code] || ''),
        name: String(row[fields.name] || ''),
        py: String(row[fields.py] || ''),
        kind: String(row[fields.kind] || ''),
      };
    }
    if (!row || typeof row !== 'object') return null;
    return {
      code: String(row.code || ''),
      name: String(row.name || ''),
      py: String(row.py || ''),
      kind: String(row.kind || ''),
    };
  }

  function codeForms(row) {
    var forms = [row.code.toLowerCase()];
    if (row.kind === 'us' && /^US_/i.test(row.code)) {
      forms.push(row.code.slice(3).toLowerCase());
    }
    if (row.kind === 'index' && /^[a-z]{2}\d{6}$/i.test(row.code)) {
      forms.push(row.code.slice(2).toLowerCase());
    }
    return forms;
  }

  function match(rows, query, limit) {
    var q = String(query == null ? '' : query).trim().replace(/\.(SH|SZ)$/i, '').toLowerCase();
    if (!q) return [];
    var maximum = limit == null ? 10 : Math.max(0, Math.floor(Number(limit) || 0));
    if (!maximum) return [];
    var source = Array.isArray(rows) ? rows : rows && Array.isArray(rows.rows) ? rows.rows : [];
    var fields = { code: 0, name: 1, py: 2, kind: 3 };
    if (!Array.isArray(rows) && rows && Array.isArray(rows.fields)) {
      fields = {
        code: rows.fields.indexOf('code'),
        name: rows.fields.indexOf('name'),
        py: rows.fields.indexOf('py'),
        kind: rows.fields.indexOf('kind'),
      };
    }
    var ranked = [];
    source.forEach(function (raw, index) {
      var row = rowRecord(raw, fields);
      if (!row || !row.code) return;
      var codes = codeForms(row);
      var name = row.name.toLowerCase();
      var py = row.py.toLowerCase();
      var rank = codes.some(function (code) { return code === q; }) ? 0
        : codes.some(function (code) { return code.indexOf(q) === 0; }) ? 1
          : name.indexOf(q) === 0 ? 2
            : py.indexOf(q) === 0 ? 3
              : name.indexOf(q) >= 0 ? 4
                : py.indexOf(q) >= 0 ? 5 : -1;
      if (rank >= 0) ranked.push({ row: row, index: index, rank: rank });
    });
    ranked.sort(function (left, right) {
      return left.rank - right.rank || left.index - right.index;
    });
    var seen = Object.create(null);
    var result = [];
    ranked.forEach(function (item) {
      var key = item.row.kind + ':' + item.row.code.toLowerCase();
      if (seen[key] || result.length >= maximum) return;
      seen[key] = true;
      result.push(item.row);
    });
    return result;
  }

  function selectedMatch(hits, query, hitsQuery, selectedIndex) {
    if (String(query == null ? '' : query) !== String(hitsQuery == null ? '' : hitsQuery) || !Array.isArray(hits)) return null;
    return hits[selectedIndex] || null;
  }

  return { match: match, selectedMatch: selectedMatch };
});
