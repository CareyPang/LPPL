(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CPTradingDays = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var activeClosures = new Set();
  var DAY_MS = 86400000;

  function dayKey(date) {
    return date.toISOString().slice(0, 10);
  }

  function setClosures(values) {
    activeClosures = values instanceof Set ? new Set(values) : new Set(values || []);
  }

  function dateAt(bars, idx, closures) {
    if (idx < bars.length) return bars[Math.max(0, idx)].date;
    var closed = closures || activeClosures;
    var date = new Date(bars[bars.length - 1].date + 'T00:00:00Z');
    var remaining = idx - (bars.length - 1);
    while (remaining > 0) {
      date = new Date(date.getTime() + DAY_MS);
      var weekday = date.getUTCDay();
      if (weekday !== 0 && weekday !== 6 && !closed.has(dayKey(date))) remaining--;
    }
    return dayKey(date);
  }

  function idxOf(bars, value, closures) {
    if (!value) return -1;
    var length = bars.length, last = bars[length - 1].date;
    if (value <= last) {
      var index = bars.findIndex(function (bar) { return bar.date >= value; });
      return index < 0 ? length - 1 : index;
    }
    var closed = closures || activeClosures;
    var indexAfterLast = length - 1;
    var date = new Date(last + 'T00:00:00Z');
    var end = new Date(value + 'T00:00:00Z');
    while (date < end) {
      date = new Date(date.getTime() + DAY_MS);
      var weekday = date.getUTCDay();
      if (weekday !== 0 && weekday !== 6 && !closed.has(dayKey(date))) indexAfterLast++;
    }
    return indexAfterLast;
  }

  return { dateAt: dateAt, idxOf: idxOf, setClosures: setClosures };
});
