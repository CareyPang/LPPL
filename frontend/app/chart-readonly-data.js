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
    var ph = raw && raw.price_history || {};
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
  function marketFromPublished(raw, code) {
    raw = raw && (raw.raw || raw);
    if (raw == null) throw missing('该标的当前没有可用的已发布日线。');
    if (!/^(US_[A-Z.]{1,6}|JP_N225|KR_KOSPI|KR_KOSDAQ)$/i.test(String(code || '')) ||
        String(raw.symbol || '').toUpperCase() !== String(code).toUpperCase()) {
      throw new Error('已发布行情的资产身份与请求不匹配，已停止显示。');
    }
    var bars = barsFrom(raw);
    if (raw.asof) bars = cutoffBars(bars, raw.asof);
    if (!bars.length) throw missing('该标的当前没有可用的已发布日线。');
    var ph = raw.price_history || {};
    var market = raw.market || (/^JP_/i.test(code) ? 'jp' : /^KR_/i.test(code) ? 'kr' : 'us');
    return {
      symbol: String(code).toUpperCase(), name: raw.name || String(code).toUpperCase(),
      market: market, timezone: raw.timezone || '',
      price: bars, asof: bars[bars.length - 1].date,
      source: ph.source || raw.source || '',
      adjustment: ph.adjustment || raw.adjust || '',
      volume_unit: ph.volume_unit || '', currency: raw.currency || ({ us: 'USD', jp: 'JPY', kr: 'KRW' })[market] || '',
      exchange: raw.exchange || (({ us: '美国', jp: '日本', kr: '韩国' })[market] || '') + (({ us: '美国', jp: '日本', kr: '韩国' })[market] ? '市场' : ''),
      trading_status: raw.trading_status || '', future_calendar: raw.future_calendar || null,
      asof_freshness: raw.asof_freshness || 'not_established', stale: raw.stale === true,
      stale_reason: raw.stale_reason || '', published_asof: raw.asof || null,
      data_version: raw.data_version || null, price_note: '已发布复权日线；并非实时成交价。',
    };
  }
  function exactResult(raw, context) {
    raw = raw && (raw.raw || raw);
    if (!raw || raw.asof !== context.asof) throw missing('没有该截止日的精确封存结果，未替换成最新结果。');
    if (raw.symbol && !sameSymbol(raw.symbol, context)) {
      throw new Error('历史结果的资产身份不匹配，已停止显示。');
    }
    var bars = cutoffBars(barsFrom(raw), context.asof);
    if (!bars.length) throw missing('该日模型已封存，但当前没有可核对的历史行情。');
    return { raw: raw, top: raw.top || {}, bars: bars, asof: raw.asof, name: raw.name || context.name,
      sym: { sym: context.code, market: context.market, currency: context.currency, exchange: context.exchange, timezone: context.timezone }, historical: true };
  }
  function sameSymbol(symbol, context) {
    if (context.assetType === 'index') return String(symbol).toUpperCase() === String(context.code).toUpperCase();
    if (context.market === 'us' || /^US_/i.test(context.stockCode || '')) {
      return String(symbol).toUpperCase() === String(context.stockCode).toUpperCase();
    }
    return context.assetType === 'stock'
      ? String(symbol).replace(/^(sh|sz|bj)/i, '') === context.stockCode
      : String(symbol).toLowerCase() === context.code.toLowerCase();
  }
  function globalAsset(adapter, context) {
    return !!(adapter.global && typeof adapter.global.isAsset === 'function' && adapter.global.isAsset(context.code));
  }
  async function currentResult(adapter, context) {
    if (!context.valid) throw new Error('资产身份无效。');
    if (globalAsset(adapter, context)) {
      var raw = await timed(function () { return adapter.global.latest(context.code); }, '国际已发布数据');
      if (!raw || !raw.asof) throw missing('该国际标的尚无带截止日的已发布结果。');
      if (!sameSymbol(raw.symbol, context)) throw new Error('已发布结果的资产身份不匹配。');
      if (context.assetType === 'stock') return raw;
      var result = exactResult(raw, Object.assign({}, context, { asof: raw.asof }));
      result.historical = false; return result;
    }
    if (context.assetType === 'index') {
      if (context.market && context.market !== 'cn') throw missing('该国际指数当前没有可用的已发布数据。');
      return timed(function () { return adapter.load(context.code); }, '指数数据');
    }
    if (context.market === 'us') return timed(function () { return adapter.stock.latest(context.stockCode); }, '已发布美股数据');
    throw new Error('此读取入口不启动个股行情查询。');
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
    var stockMeta = frame.stock_meta || history.stock_meta;
    if (!stockMeta && (frame.stock_evidence || history.stock_evidence)) {
      stockMeta = { evidence: frame.stock_evidence || history.stock_evidence };
    }
    var raw = { symbol: history.symbol || context.code, name: name || context.name, asof: frame.asof, top: top,
      model_version: frame.model_version || history.model_version || null,
      prediction_id: frame.prediction_id || null, first_visible_at: frame.first_visible_at || null,
      evidence_levels: history.evidence_levels || {}, future_calendar: history.future_calendar || null,
      research: frame.research || null, params: frame.params || null };
    if (stockMeta) raw.stock_meta = stockMeta;
    return { raw: raw, top: top, asof: frame.asof, bars: cutoffBars(bars, context.asof),
      sym: { sym: context.code }, name: raw.name, historical: true, historyFallback: true };
  }
  async function historical(adapter, context) {
    if (!context.asof || !context.valid) throw new Error('历史截止日无效。');
    if (globalAsset(adapter, context)) {
      var archived;
      try { archived = await timed(function () { return adapter.global.result(context.code, context.asof); }, '国际精确历史封存'); }
      catch (error) { throw missing('未读到 ' + context.asof + ' 的国际标的精确封存，未替换成最新或其他市场数据。（' + error.message + '）'); }
      if (archived && !sameSymbol(archived.symbol, context)) throw new Error('国际历史封存的资产身份不匹配。');
      var exact = exactResult(archived, context);
      if (context.assetType === 'stock') exact.market = marketFromPublished(exact.raw, context.stockCode);
      return exact;
    }
    if (context.assetType === 'index' && context.market && context.market !== 'cn') {
      throw missing('该国际指数尚无可读取的精确历史封存。');
    }
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
    var isUS = context.market === 'us' || /^US_/i.test(context.stockCode || '');
    var market = await timed(function () {
      if (isUS) return adapter.stock.latest(context.stockCode).then(function (raw) {
        return marketFromPublished(raw, context.stockCode);
      });
      return context.assetType === 'index' ? adapter.load(context.code) : adapter.stock.market(context.stockCode);
    }, '历史行情');
    var bars = context.assetType === 'index' ? market.raw && market.raw.price_history ? barsFrom(market.raw) : market.bars : market.price;
    var result = packedFrame(history, frame, context, bars, market.name);
    if (!result.bars.length) throw missing('封存模型存在，但行情未覆盖该截止日。');
    if (isUS) {
      // A history frame does not seal its OHLC payload. Keep that distinction
      // explicit and never pass later bars to chart assembly.
      market = Object.assign({}, market, { price: result.bars,
        asof: result.bars[result.bars.length - 1].date,
        price_note: '历史模型配合当前已发布版本行情；行情已截断至所选日期，非当时封存的 OHLC。' });
      result.priceHistoryOrigin = 'current_published_version';
      result.historyNote = market.price_note;
      result.raw.adjust = market.adjustment;
      result.raw.data_version = frame.data_version || history.data_version || null;
    }
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
              label: definition[2], knownAt: knownAt, source: row.source || payload.source || '' };
          }).filter(Boolean);
      });
    return { rows: rows, excluded: excluded };
  }
  return { timed: timed, historical: historical, currentResult: currentResult, globalAsset: globalAsset, sameSymbol: sameSymbol, exactResult: exactResult, historyFrame: historyFrame,
    packedFrame: packedFrame, eventsFor: eventsFor, cutoffBars: cutoffBars,
    barsFrom: barsFrom, marketFromPublished: marketFromPublished };
});
