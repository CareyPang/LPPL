(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CPAlertLedger = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var DAY = 86400000;

  function dateValue(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    var time = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value ? time : null;
  }

  function frameWindow(frame, scale) {
    var value = frame && frame.w && frame.w[scale];
    return Array.isArray(value) && value.length >= 2 ? [value[0], value[1]] : null;
  }

  function episodes(frames, tops, scale) {
    var ordered = (Array.isArray(frames) ? frames : [])
      .map(function (frame, index) { return { frame: frame, index: index }; })
      .filter(function (item) { return item.frame && dateValue(item.frame.asof) !== null; })
      .sort(function (a, b) {
        return a.frame.asof < b.frame.asof ? -1 : a.frame.asof > b.frame.asof ? 1 : a.index - b.index;
      });
    var orderedTops = (Array.isArray(tops) ? tops : [])
      .filter(function (top) { return top && dateValue(top.date) !== null; })
      .slice()
      .sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
    var result = [], run = [];

    function flush() {
      if (!run.length) return;
      var first = run[0], last = run[run.length - 1];
      var firstWindow = first.window, lastWindow = last.window;
      var top = orderedTops.find(function (item) { return item.date > first.frame.asof; }) || null;
      var relation = null;
      if (top && dateValue(firstWindow[0]) !== null && dateValue(firstWindow[1]) !== null) {
        relation = top.date < firstWindow[0] ? 'before' :
          top.date <= firstWindow[1] ? 'inside' : 'after';
      }
      result.push({
        scale: scale,
        first_asof: first.frame.asof,
        last_asof: last.frame.asof,
        weeks: run.length,
        split: first.frame.split,
        window: firstWindow.slice(),
        last_window: lastWindow.slice(),
        next_top: top ? { date: top.date, max_dd: top.max_dd } : null,
        top_vs_window: relation,
        days_to_top: top ? Math.round((dateValue(top.date) - dateValue(first.frame.asof)) / DAY) : null,
      });
      run = [];
    }

    ordered.forEach(function (item) {
      var frame = item.frame, window = frameWindow(frame, scale);
      if (frame.close != null && window) run.push({ frame: frame, window: window });
      else flush();
    });
    flush();
    return result;
  }

  return { episodes: episodes };
});
