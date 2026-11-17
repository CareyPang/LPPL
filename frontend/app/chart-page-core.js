(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLChartPageCore = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var SCALES = ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'];
  var RETURN_PAGES = new Set(['stock.html', 'index.html', 'backtest.html', 'market.html', 'home.html']);

  function fallbackFrom(assetType, code, stockCode) {
    if (assetType === 'index') {
      return 'index.html?code=' + encodeURIComponent(String(code || ''));
    }
    var normalizedStockCode = stockCode || String(code || '').replace(/^(?:sh|sz|bj)/i, '');
    return 'stock.html?code=' + encodeURIComponent(normalizedStockCode);
  }

  function safeFrom(value, assetType, code, stockCode) {
    var candidate = typeof value === 'string' ? value.trim() : '';
    if (!candidate || candidate.length > 2048 || candidate.charAt(0) === '/' ||
        candidate.indexOf('\\') >= 0 || candidate.indexOf('//') >= 0 ||
        candidate.indexOf('#') >= 0 || /^[a-z][a-z\d+.-]*:/i.test(candidate)) {
      return fallbackFrom(assetType, code, stockCode);
    }
    var page = candidate.split('?')[0];
    return RETURN_PAGES.has(page) ? candidate : fallbackFrom(assetType, code, stockCode);
  }

  function indexFor(value, indexSymbols) {
    var code = String(value || '').toLowerCase();
    var entries = Array.isArray(indexSymbols) ? indexSymbols : [];
    for (var i = 0; i < entries.length; i += 1) {
      var entry = entries[i];
      if (!entry) continue;
      if (String(entry.sym || '').toLowerCase() === code ||
          String(entry.code || '').toLowerCase() === code) {
        return { sym: String(entry.sym || code).toLowerCase(), name: entry.name || '' };
      }
    }
    return null;
  }

  function parseContext(search, indexSymbols) {
    var params = new URLSearchParams(String(search || '').replace(/^\?/, ''));
    var inputCode = String(params.get('code') || '').trim();
    var index = indexFor(inputCode, indexSymbols);
    var stockSymbol = /^(?:sh|sz|bj)\d{6}$/i.test(inputCode) ? inputCode.toLowerCase() : '';
    var stockCode = stockSymbol ? stockSymbol.slice(2) : /^\d{6}$/.test(inputCode) ? inputCode : '';
    var code = index ? index.sym : stockSymbol || (stockCode ? stockCode : '');
    var assetType = index ? 'index' : stockCode ? 'stock' : '';
    var requestedScale = params.get('scale') || '';
    var scale = SCALES.indexOf(requestedScale) >= 0 ? requestedScale : '6-12m';
    var focus = String(params.get('focus') || '').trim().slice(0, 200);
    return {
      valid: !!assetType,
      code: code,
      stockCode: stockCode,
      assetType: assetType,
      name: index ? index.name : '',
      scale: scale,
      focus: focus,
      from: safeFrom(params.get('from'), assetType, code || inputCode, stockCode),
    };
  }

  function exchangeFor(symbol) {
    var prefix = String(symbol || '').slice(0, 2).toLowerCase();
    return prefix === 'sh' ? '上海证券交易所'
      : prefix === 'sz' ? '深圳证券交易所'
        : prefix === 'bj' ? '北京证券交易所' : '未记录';
  }

  function modelRecord(raw, fallback) {
    raw = raw || {};
    return {
      modelVersion: raw.model_version || fallback && fallback.model_version || null,
      predictionId: raw.prediction_id || fallback && fallback.prediction_id || null,
    };
  }

  function assembleIndexData(code, result) {
    if (!result || !Array.isArray(result.bars)) throw new Error('指数适配器未返回日线');
    var raw = result.raw || result;
    var symbol = String(result.sym && result.sym.sym || raw.symbol || code || '').toLowerCase();
    var model = modelRecord(raw, result);
    return {
      assetType: 'index',
      symbol: symbol,
      code: symbol,
      name: result.name || raw.name || result.sym && result.sym.name || symbol,
      exchange: exchangeFor(symbol),
      bars: result.bars,
      asof: result.asof || raw.asof || '',
      modelAsOf: result.asof || raw.asof || '',
      marketAsOf: '',
      top: result.top || raw.top || {},
      future_calendar: raw.future_calendar || result.future_calendar || null,
      evidence_levels: raw.evidence_levels || result.evidence_levels || {},
      modelVersion: model.modelVersion,
      predictionId: model.predictionId,
      dataSource: 'LPPL 已发布指数数据',
      adjustment: raw.price_history && raw.price_history.note || '已发布指数日线',
      raw: raw,
    };
  }

  function assembleStockData(symbol, latest, market, fallbackCalendar) {
    if (!latest || typeof latest !== 'object') throw new Error('该标的没有已发布模型结果');
    if (!market || !Array.isArray(market.price) || !market.price.length) {
      throw new Error('行情接口未返回 K 线；未用模型价格替代行情。');
    }
    var raw = latest.raw || latest;
    var resolvedSymbol = String(latest.symbol || symbol || '').toLowerCase();
    var model = modelRecord(raw, latest);
    var lastBar = market.price[market.price.length - 1];
    return {
      assetType: 'stock',
      symbol: resolvedSymbol,
      code: resolvedSymbol,
      name: latest.name || raw.name || resolvedSymbol,
      exchange: exchangeFor(resolvedSymbol),
      bars: market.price,
      asof: latest.asof || raw.asof || '',
      modelAsOf: latest.asof || raw.asof || '',
      marketAsOf: market.asof || market.cutoff || lastBar && lastBar.date || '',
      top: latest.top || raw.top || {},
      future_calendar: latest.future_calendar || raw.future_calendar || fallbackCalendar || null,
      evidence_levels: latest.evidence_levels || raw.evidence_levels || {},
      modelVersion: model.modelVersion,
      predictionId: model.predictionId,
      dataSource: market.source || '未记录',
      adjustment: market.adjustment || '未记录',
      raw: raw,
    };
  }

  function intervalId(scale, band) {
    return 'interval:' + [scale, band && band.rank || 'main',
      band && band.q20_date || '', band && band.q80_date || ''].join(':');
  }

  return {
    SCALES: SCALES,
    safeFrom: safeFrom,
    parseContext: parseContext,
    exchangeFor: exchangeFor,
    assembleIndexData: assembleIndexData,
    assembleStockData: assembleStockData,
    intervalId: intervalId,
  };
});
