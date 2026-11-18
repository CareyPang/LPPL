(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLChartReadOnly = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  function missing(message) { var error = new Error(message); error.pending = true; return error; }
  function timed(work, label, ms) {
    var timer;
    return Promise.race([Promise.resolve().then(work), new Promise(function (_, reject) {
      timer = setTimeout(function () { reject(new Error(label + '读取超时，请单独重试。')); }, ms || 11000);
    })]).finally(function () { clearTimeout(timer); });
  }
  function barsFrom(raw) {
    var ph = raw.price_history || {};
    if (!Array.isArray(ph.dates) || !Array.isArray(ph.close)) return [];
    return ph.dates.map(function (date, i) {
      var close = ph.close[i];
      return { date: date, close: close, open: ph.open && ph.open[i] != null ? ph.open[i] : null,
        high: ph.high && ph.high[i] != null ? ph.high[i] : null,
        low: ph.low && ph.low[i] != null ? ph.low[i] : null,
        volume: ph.volume && ph.volume[i] != null ? ph.volume[i] : null };
    });
  }
  function cutoffBars(bars, asof) {
    return (bars || []).filter(function (bar) { return (bar.date || bar.time) <= asof; });
  }
  function exactResult(raw, context) {
    raw = raw && (raw.raw || raw);
    if (!raw || raw.asof !== context.asof) throw missing('没有该截止日的精确封存结果，未替换成最新结果。');
    if (raw.symbol && !sameSymbol(raw.symbol, context)) {
      throw new Error('历史结果的资产身份不匹配，已停止显示。');
    }
    var bars = cutoffBars(barsFrom(raw), context.asof);
    if (!bars.length) throw missing('该日模型已封存，但未提供可核对的历史行情。');
    return { raw: raw, top: raw.top || {}, bars: bars, asof: raw.asof, name: raw.name || context.name,
      sym: { sym: context.code }, historical: true };
  }
  function sameSymbol(symbol, context) {
    return context.assetType === 'stock'
      ? String(symbol).replace(/^(sh|sz|bj)/i, '') === context.stockCode
      : String(symbol).toLowerCase() === context.code.toLowerCase();
  }
  function historyFrame(history, context) {
    if (!history || history.symbol && !sameSymbol(history.symbol, context)) return null;
    return (history.frames || []).find(function (frame) { return frame.asof === context.asof; }) || null;
  }
  function packedFrame(history, frame, context, bars, name) {
    var windows = Object.keys(frame.w || {}).filter(function (scale) {
      return Array.isArray(frame.w[scale]) && frame.w[scale].length === 2;
    }).map(function (scale) { return { scale: scale, q20_date: frame.w[scale][0], q80_date: frame.w[scale][1] }; });
    var top = frame.top || { scale_windows: windows, scale_clusters: frame.clusters || {},
      lppls_confidence: { scale_evidence: frame.scale_evidence || history.scale_evidence || {},
        evidence: frame.evidence || history.evidence || 'none' } };
    var raw = { symbol: history.symbol || context.code, name: name || context.name, asof: frame.asof, top: top,
      model_version: frame.model_version || history.model_version || null,
      prediction_id: frame.prediction_id || null, first_visible_at: frame.first_visible_at || null,
      evidence_levels: history.evidence_levels || {}, future_calendar: history.future_calendar || null };
    return { raw: raw, top: top, asof: frame.asof, bars: cutoffBars(bars, context.asof),
      sym: { sym: context.code }, name: raw.name, historical: true, historyFallback: true };
  }
  async function historical(adapter, context) {
    if (!context.asof || !context.valid) throw new Error('历史截止日无效。');
    // The adapter's explicit REPLAYS allowlist takes its static-JSON branch.
    // Never pass an arbitrary date to load(): its other branch can POST a job.
    var staticDates = adapter.REPLAYS && adapter.REPLAYS[context.code];
    if (context.assetType === 'index' && Array.isArray(staticDates) && staticDates.indexOf(context.asof) >= 0) {
      var saved = await timed(function () { return adapter.load(context.code, context.asof); }, '静态历史封存');
      return exactResult(saved, context);
    }
    var replayError = null;
    if (context.assetType === 'index' && adapter.replay && adapter.replay.result) {
      try {
        var response = await timed(function () { return adapter.replay.result(context.code, context.asof); }, '历史封存');
        if (response && response.status === 'ready' && response.result) return exactResult(response.result, context);
        replayError = response && response.status || 'missing';
      } catch (error) { replayError = error.message; }
    }
    // Only an exact existing frame is eligible; no nearest-day or latest-model fallback.
    var history = await timed(function () {
      return context.assetType === 'index' ? adapter.history(context.code) : adapter.stock.history(context.stockCode);
    }, '历史记录');
    var frame = historyFrame(history, context);
    if (!frame) throw missing('没有 ' + context.asof + ' 的封存模型。只读访问未发起计算。' +
      (replayError ? '（封存服务状态：' + replayError + '）' : ''));
    if (frame.price_history && context.assetType === 'index') return exactResult(Object.assign({}, frame, { symbol: context.code }), context);
    var market = await timed(function () {
      return context.assetType === 'index' ? adapter.load(context.code) : adapter.stock.market(context.stockCode);
    }, '历史行情');
    var bars = context.assetType === 'index' ? market.raw && market.raw.price_history ? barsFrom(market.raw) : market.bars : market.price;
    var result = packedFrame(history, frame, context, bars, market.name);
    if (!result.bars.length) throw missing('封存模型存在，但行情未覆盖该截止日。');
    result.market = market;
    return result;
  }
  function eventsFor(payload, code, asof) {
    var excluded = 0;
    var rows = [['lift', 'free_date', '解禁'], ['dividend', 'ex_dividend_date', '除权除息'], ['forecast', 'notice_date', '业绩预告']]
      .flatMap(function (definition) {
        return (payload && payload[definition[0]] || []).filter(function (row) { return row.code === code; })
          .map(function (row, i) {
            var knownAt = row.published_at || row.announced_at || row.notice_date || null;
            if (asof && (!knownAt || String(knownAt).slice(0, 10) > asof)) { excluded++; return null; }
            return { id: definition[0] + ':' + row[definition[1]] + ':' + i, date: row[definition[1]],
              label: definition[2], knownAt: knownAt, source: row.source || payload.source || '未记录' };
          }).filter(Boolean);
      });
    return { rows: rows, excluded: excluded };
  }
  return { timed: timed, historical: historical, exactResult: exactResult, historyFrame: historyFrame,
    packedFrame: packedFrame, eventsFor: eventsFor, cutoffBars: cutoffBars };
});
