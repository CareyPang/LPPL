(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLChartPageCore = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var SCALES = ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'];
  var RETURN_PAGES = new Set(['stock.html', 'index.html', 'backtest.html', 'market.html', 'home.html', 'research-workspace.html']);
  var NUMERIC_EVIDENCE = new Set(['dev', 'cal', 'test', 'cal_fragile', 'descriptive', 'descriptive_bubble']);

  function fallbackFrom(assetType, code, stockCode) {
    if (assetType === 'index') {
      return 'index.html?code=' + encodeURIComponent(String(code || ''));
    }
    var normalizedStockCode = stockCode || String(code || '').replace(/^(?:sh|sz|bj)/i, '');
    return 'stock.html?code=' + encodeURIComponent(normalizedStockCode);
  }

  function safeFrom(value, assetType, code, stockCode) {
    var candidate = typeof value === 'string' ? value.trim() : '';
    if (candidate === 'research-workspace') candidate = 'research-workspace.html';
    if (!candidate || candidate.length > 2048 || candidate.charAt(0) === '/' ||
        candidate.indexOf('\\') >= 0 || candidate.indexOf('//') >= 0 ||
        candidate.indexOf('#') >= 0 || /^[a-z][a-z\d+.-]*:/i.test(candidate)) {
      return fallbackFrom(assetType, code, stockCode);
    }
    var page = candidate.split('?')[0];
    return RETURN_PAGES.has(page) ? candidate : fallbackFrom(assetType, code, stockCode);
  }

  function bandEvidencePolicy(evidenceCode, band) {
    var hidden = !NUMERIC_EVIDENCE.has(evidenceCode);
    var missingSampleCount = /^descriptive/.test(evidenceCode) && !(Number.isFinite(band && band.n) && band.n > 0);
    return {
      draw: !hidden && !missingSampleCount,
      showDates: !hidden && !missingSampleCount,
      showShare: !hidden && !missingSampleCount,
      message: hidden ? '证据未建立，不显示数值' : missingSampleCount ? '描述性样本数未记录，不显示数值' : '',
    };
  }

  function filterDescriptiveBands(top, evidenceCodes) {
    var filtered = Object.assign({}, top || {});
    evidenceCodes = evidenceCodes || {};
    ['scale_windows', 'scale_clusters', 'clusters'].forEach(function (key) {
      var entries = filtered[key];
      if (Array.isArray(entries)) {
        filtered[key] = entries.filter(function (band) {
          return bandEvidencePolicy(evidenceCodes[band && band.scale], band).draw;
        });
      } else if (entries && typeof entries === 'object') {
        var byScale = Object.assign({}, entries);
        Object.keys(byScale).forEach(function (scale) {
          if (Array.isArray(byScale[scale])) {
            byScale[scale] = byScale[scale].filter(function (band) {
              return bandEvidencePolicy(evidenceCodes[scale], band).draw;
            });
          }
        });
        filtered[key] = byScale;
      }
    });
    return filtered;
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
    var requestedKind = params.get('kind') || params.get('type') || '';
    var index = requestedKind === 'stock' ? null : indexFor(inputCode, indexSymbols);
    var stockSymbol = /^(?:sh|sz|bj)\d{6}$/i.test(inputCode) ? inputCode.toLowerCase() : '';
    var stockCode = stockSymbol ? stockSymbol.slice(2) : /^\d{6}$/.test(inputCode) ? inputCode : '';
    var code = index ? index.sym : stockSymbol || (stockCode ? stockCode : '');
    var assetType = index ? 'index' : stockCode ? 'stock' : '';
    var requestedScale = params.get('scale') || '';
    var scale = SCALES.indexOf(requestedScale) >= 0 ? requestedScale : '6-12m';
    var requestedAsof = String(params.get('asof') || '');
    var asof = '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(requestedAsof)) {
      var asofDate = new Date(requestedAsof + 'T00:00:00Z');
      if (!Number.isNaN(asofDate.getTime()) && asofDate.toISOString().slice(0, 10) === requestedAsof) {
        asof = requestedAsof;
      }
    }
    var focus = String(params.get('focus') || '').trim().slice(0, 200);
    return {
      valid: !!assetType && !(requestedAsof && !asof) && (!requestedKind || requestedKind === assetType),
      invalidReason: requestedAsof && !asof ? '历史截止日无效，请使用真实的 YYYY-MM-DD 日期；未改看最新。' :
        requestedKind && requestedKind !== assetType ? '资产类别与代码不匹配，请明确选择指数或股票。' : '',
      code: code,
      stockCode: stockCode,
      assetType: assetType,
      name: index ? index.name : '',
      scale: scale,
      focus: focus,
      asof: asof,
      from: safeFrom(params.get('from'), assetType, code || inputCode, stockCode),
    };
  }

  function exchangeFor(symbol) {
    var prefix = String(symbol || '').slice(0, 2).toLowerCase();
    return prefix === 'sh' ? '上海证券交易所'
      : prefix === 'sz' ? '深圳证券交易所'
        : prefix === 'bj' ? '北京证券交易所' : '未记录';
  }

  function inferStockSymbol(symbol) {
    if (/^(?:sh|sz|bj)\d{6}$/i.test(String(symbol || ''))) return String(symbol).toLowerCase();
    var match = String(symbol || '').trim().toLowerCase().match(/^(?:sh|sz|bj)?(\d{6})$/);
    if (!match) return '';
    var code = match[1];
    var first = code.charAt(0);
    return (first === '6' ? 'sh' : first === '0' || first === '3' ? 'sz' : 'bj') + code;
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
    // The legacy adapter fills absent OHLC with close. Restore missingness using
    // the raw published fields so this chart can explicitly show a close line.
    var ph = raw.price_history;
    var bars = ph && Array.isArray(ph.dates) && Array.isArray(ph.close) ? ph.dates.map(function (date, i) {
      return { date: date, close: ph.close[i], open: ph.open && ph.open[i] != null ? ph.open[i] : null,
        high: ph.high && ph.high[i] != null ? ph.high[i] : null, low: ph.low && ph.low[i] != null ? ph.low[i] : null,
        volume: ph.volume && ph.volume[i] != null ? ph.volume[i] : null };
    }).filter(function (bar) { return !result.asof || bar.date <= result.asof; }) : result.bars;
    var symbol = String(result.sym && result.sym.sym || raw.symbol || code || '').toLowerCase();
    var model = modelRecord(raw, result);
    return {
      assetType: 'index',
      symbol: symbol,
      code: symbol,
      name: result.name || raw.name || result.sym && result.sym.name || symbol,
      exchange: exchangeFor(symbol),
      bars: bars,
      asof: result.asof || raw.asof || '',
      modelAsOf: result.asof || raw.asof || '',
      marketAsOf: bars.length ? bars[bars.length - 1].date || bars[bars.length - 1].time || '' : '',
      top: result.top || raw.top || {},
      future_calendar: raw.future_calendar || result.future_calendar || null,
      evidence_levels: raw.evidence_levels || result.evidence_levels || {},
      modelVersion: model.modelVersion,
      predictionId: model.predictionId,
      dataSource: raw.source || raw.price_history && raw.price_history.source || 'LPPL 已发布指数数据（底层源未记录）',
      adjustment: raw.price_history && raw.price_history.adjustment || '未记录',
      volumeUnit: raw.price_history && raw.price_history.volume_unit || '未记录',
      tradingStatus: raw.trading_status || '未记录',
      quoteUnit: '指数点位',
      modelStatus: 'ok',
      priceNote: raw.price_history && raw.price_history.note || '',
      firstVisibleAt: raw.first_visible_at || null,
      modelAdjustment: raw.price_history && raw.price_history.adjustment || '未记录',
      raw: raw,
    };
  }

  function assembleStockData(symbol, latest, market, fallbackCalendar, modelError) {
    if (!market || !Array.isArray(market.price) || !market.price.length) {
      throw new Error('行情接口未返回 K 线；未用模型价格替代行情。');
    }
    var hasLatest = !!latest && typeof latest === 'object';
    var raw = hasLatest ? latest.raw || latest : {};
    var expectedSymbol = inferStockSymbol(symbol);
    if (market.symbol && expectedSymbol && String(market.symbol).toLowerCase() !== expectedSymbol) {
      throw new Error('行情资产身份与请求不匹配，已停止显示。');
    }
    if (hasLatest && raw.symbol && expectedSymbol && inferStockSymbol(raw.symbol) !== expectedSymbol) {
      modelError = new Error('模型资产身份与行情不匹配；仅保留行情。');
      hasLatest = false; raw = {};
    }
    var resolvedSymbol = String(
      hasLatest && inferStockSymbol(latest.symbol) || market.symbol || expectedSymbol || symbol || '',
    ).toLowerCase();
    var model = modelRecord(raw, hasLatest ? latest : null);
    var lastBar = market.price[market.price.length - 1];
    return {
      assetType: 'stock',
      symbol: resolvedSymbol,
      code: resolvedSymbol,
      name: hasLatest && (latest.name || raw.name) || market.name || market.stock_name || resolvedSymbol,
      exchange: exchangeFor(resolvedSymbol),
      bars: market.price,
      asof: hasLatest ? latest.asof || raw.asof || '' : '',
      modelAsOf: hasLatest ? latest.asof || raw.asof || '' : '',
      marketAsOf: market.asof || market.cutoff || lastBar && lastBar.date || '',
      top: hasLatest ? latest.top || raw.top || {} : {},
      future_calendar: hasLatest && (latest.future_calendar || raw.future_calendar) ||
        fallbackCalendar || market.future_calendar || null,
      evidence_levels: hasLatest ? latest.evidence_levels || raw.evidence_levels || {} : {},
      modelVersion: model.modelVersion,
      predictionId: model.predictionId,
      modelStatus: modelError ? 'error' : hasLatest ? 'ok' : 'missing',
      modelMessage: modelError ? String(modelError.message || modelError) : '',
      dataSource: market.source || '未记录',
      adjustment: market.adjustment || '未记录',
      volumeUnit: market.volume_unit || '未记录',
      tradingStatus: market.trading_status || '未记录',
      quoteUnit: 'CNY · 元',
      stale: market.stale === true,
      staleReason: market.stale_reason || '',
      freshness: market.asof_freshness || 'not_established',
      firstVisibleAt: raw.first_visible_at || null,
      modelAdjustment: raw.price_history && raw.price_history.adjustment || '未记录',
      raw: raw,
    };
  }

  function intervalId(scale, band) {
    return 'interval:' + [scale, band && band.rank || 'main',
      band && band.q20_date || '', band && band.q80_date || ''].join(':');
  }

  return {
    SCALES: SCALES,
    NUMERIC_EVIDENCE: NUMERIC_EVIDENCE,
    safeFrom: safeFrom,
    bandEvidencePolicy: bandEvidencePolicy,
    filterDescriptiveBands: filterDescriptiveBands,
    parseContext: parseContext,
    exchangeFor: exchangeFor,
    assembleIndexData: assembleIndexData,
    assembleStockData: assembleStockData,
    intervalId: intervalId,
  };
});
