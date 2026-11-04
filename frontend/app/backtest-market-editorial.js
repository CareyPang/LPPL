/* Historical market display only. Read published OHLCV through LPPL; never synthesize candles. */
(function (G) {
  'use strict';
  const DAY = 864e5;
  const time = d => typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d) ? Date.parse(d + 'T00:00:00Z') : NaN;
  const valid = n => Number.isFinite(n) && n > 0;
  function snapshotBars(snapshot) {
    const raw = snapshot && snapshot.raw, ph = raw && raw.price_history;
    if (!ph || !Array.isArray(ph.dates)) return [];
    const end = time(snapshot.asof || raw.asof);
    if (!Number.isFinite(end)) return [];
    return ph.dates.flatMap((date, i) => {
      const t = time(date), open = ph.open && ph.open[i], high = ph.high && ph.high[i], low = ph.low && ph.low[i], close = ph.close && ph.close[i];
      if (!Number.isFinite(t) || t > end || ![open, high, low, close].every(valid) || high < Math.max(open, close, low) || low > Math.min(open, close, high)) return [];
      const volume = ph.volume && ph.volume[i];
      return [{ date, t, open, high, low, close, volume: Number.isFinite(volume) && volume >= 0 ? volume : null, sourceAsOf: snapshot.asof || raw.asof }];
    });
  }
  function coverageFor(bars) {
    const ranges = [];
    for (const b of bars) {
      const last = ranges[ranges.length - 1];
      // Holidays are not missing market bars; longer gaps are kept visibly separate.
      if (!last || b.t - last[1] > 14 * DAY) ranges.push([b.t, b.t]);
      else last[1] = b.t;
    }
    return ranges;
  }
  const covered = (t, ranges) => ranges.some(([a, b]) => t >= a && t <= b);
  function weeklySegments(frames, ranges) {
    const segments = []; let segment = null;
    for (const f of frames) {
      if (covered(f.t, ranges)) { segment = null; continue; }
      const previous = segment && segment[segment.length - 1];
      if (!previous || f.t - previous.t > 21 * DAY || ranges.some(([a, b]) => previous.t < b && f.t > a)) {
        segment = []; segments.push(segment);
      }
      segment.push(f);
    }
    return segments;
  }
  async function load(adapter, symbol) {
    const dates = ['', ...(adapter.REPLAYS[symbol] || [])];
    const results = await Promise.allSettled(dates.map(asof => adapter.load(symbol, asof)));
    const map = new Map(), snapshots = [], failures = [];
    results.forEach((result, i) => {
      if (result.status !== 'fulfilled') { failures.push(dates[i] || 'latest'); return; }
      const D = result.value;
      if (!D || !D.sym || D.sym.sym !== symbol) { failures.push(dates[i] || 'latest'); return; }
      const bars = snapshotBars(D);
      if (!bars.length) { failures.push(dates[i] || 'latest'); return; }
      // The record's own OHLC fields are required even if the adapter offers close-only fallbacks.
      for (const b of bars) if (!map.has(b.date)) map.set(b.date, b);
      snapshots.push({ asof: D.asof, latest: !dates[i], first: bars[0].date, last: bars[bars.length - 1].date, bars });
    });
    const bars = [...map.values()].sort((a, b) => a.t - b.t);
    return { symbol, bars, ranges: coverageFor(bars), snapshots, failures };
  }
  G.LPPLMarket = { snapshotBars, coverageFor, covered, weeklySegments, load };
})(typeof window === 'undefined' ? globalThis : window);
