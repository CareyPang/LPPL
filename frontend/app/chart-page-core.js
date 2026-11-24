(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLChartPageCore = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var SCALES = ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'];
  var RETURN_PAGES = new Set(['stock.html', 'index.html', 'backtest.html', 'market.html', 'home.html', 'research-workspace.html']);
  var NUMERIC_EVIDENCE = new Set(['dev', 'cal', 'test', 'cal_fragile', 'research_candidate', 'descriptive']);
  function restrictEvidence(scope, own) {
    scope = typeof scope === 'string' && scope ? scope : 'none';
    if (!NUMERIC_EVIDENCE.has(scope)) return scope;
    var evidence = own == null || own === '' ? scope : own;
    if (!NUMERIC_EVIDENCE.has(evidence)) return evidence;
    if (scope === 'descriptive' || evidence === 'descriptive') return 'descriptive';
    if (scope === 'research_candidate' || evidence === 'research_candidate') return 'research_candidate';
    return evidence;
  }
  function evidenceFor(data, scale, own) {
    var raw = data.raw || data, top = data.top || raw.top || {};
    var confidence = top.lppls_confidence || {}, indicator = top.indicators && top.indicators[scale] || {};
    if (data.modelStatus && data.modelStatus !== 'ok' || indicator.signal_status === 'not_computed') return 'none';
    // Scale evidence is the gate. A top-level or band-level label cannot revive
    // an absent/failed scale; stock identity is an additional restriction.
    var scoped = confidence.scale_evidence && confidence.scale_evidence[scale] || confidence.evidence || 'none';
    var evidence = indicator.evidence == null || indicator.evidence === '' ? scoped : restrictGate(scoped, indicator.evidence);
    evidence = restrictEvidence(evidence, own);
    if (data.assetType === 'stock') evidence = restrictGate(evidence, raw.stock_meta && raw.stock_meta.evidence || 'none');
    return evidence;
  }
  function restrictGate(scope, gate) {
    if (!NUMERIC_EVIDENCE.has(scope)) return scope;
    if (!NUMERIC_EVIDENCE.has(gate)) return gate;
    if (scope === 'descriptive' || gate === 'descriptive') return 'descriptive';
    if (scope === 'research_candidate' || gate === 'research_candidate') return 'research_candidate';
    return scope;
  }
  function bandEvidenceCode(evidenceCode, band) { return restrictEvidence(evidenceCode, band && band.evidence); }

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
    evidenceCode = bandEvidenceCode(evidenceCode, band);
    var hidden = !NUMERIC_EVIDENCE.has(evidenceCode);
    var missingSampleCount = evidenceCode === 'descriptive' && !(Number.isInteger(band && band.n) && band.n > 0);
    return {
      draw: !hidden && !missingSampleCount,
      showDates: !hidden && !missingSampleCount,
      showShare: !hidden && !missingSampleCount,
      message: hidden ? '证据未建立，不显示数值' : missingSampleCount ? '当前数据不支持显示描述性数值' : '',
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
    if (!code) return null;
    var entries = Array.isArray(indexSymbols) ? indexSymbols : [];
    for (var i = 0; i < entries.length; i += 1) {
      var entry = entries[i];
      if (!entry) continue;
      if ([entry.sym, entry.code, entry.name].concat(entry.alias || []).some(function (value) {
        return String(value || '').toLowerCase() === code;
      })) {
        return Object.assign({}, entry, { sym: String(entry.sym || code), name: entry.name || '' });
      }
    }
    return null;
  }

  function parseContext(search, indexSymbols, globalSymbols) {
    var params = new URLSearchParams(String(search || '').replace(/^\?/, ''));
    var inputCode = String(params.get('code') || '').trim();
    var requestedKind = params.get('kind') || params.get('type') || '';
    var knownIndex = indexFor(inputCode, indexSymbols);
    var reservedIndex = knownIndex && /^(US_|JP_|KR_)/i.test(knownIndex.sym);
    var index = requestedKind === 'stock' && !reservedIndex ? null : knownIndex;
    var stockIdentity = indexFor(inputCode, (globalSymbols || []).filter(function (item) { return item.kind === 'stock'; }));
    var usSymbol = /^US_[A-Z.]{1,6}$/i.test(inputCode) ? inputCode.toUpperCase() : '';
    var internationalStock = stockIdentity ? stockIdentity.sym : usSymbol;
    var stockSymbol = internationalStock || (/^(?:sh|sz|bj)\d{6}$/i.test(inputCode) ? inputCode.toLowerCase() : '');
    var stockCode = index ? '' : internationalStock || (stockSymbol ? stockSymbol.slice(2) : /^\d{6}$/.test(inputCode) ? inputCode : '');
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
    var requestedRule = params.get('rule');
    var international = !!(index && index.market && index.market !== 'cn' || stockIdentity && stockIdentity.market !== 'cn');
    return {
      valid: !!assetType && !(requestedAsof && !asof) && (!requestedKind || requestedKind === assetType),
      invalidReason: requestedAsof && !asof ? '历史截止日无效，请使用真实的 YYYY-MM-DD 日期；未改看最新。' :
        requestedKind && requestedKind !== assetType ? '资产类别与代码不匹配，请明确选择指数或股票。' : '',
      code: code,
      stockCode: stockCode,
      assetType: assetType,
      market: index && index.market || stockIdentity && stockIdentity.market || (usSymbol ? 'us' : assetType ? 'cn' : ''),
      currency: index && index.currency || stockIdentity && stockIdentity.currency || (usSymbol ? 'USD' : assetType ? 'CNY' : ''),
      exchange: index && index.exchange || stockIdentity && stockIdentity.exchange || '',
      timezone: index && index.timezone || stockIdentity && stockIdentity.timezone || '',
      name: index ? index.name : stockIdentity && stockIdentity.name || '',
      scale: scale,
      focus: focus,
      rule: requestedRule === 'box' || requestedRule === 'cycles_1_5' ? requestedRule : international ? 'cycles_1_5' : 'box',
      asof: asof,
      from: safeFrom(params.get('from'), assetType, code || inputCode, stockCode),
    };
  }

  function exchangeFor(symbol) {
    if (/^JP_/i.test(String(symbol || ''))) return '日本市场';
    if (/^KR_/i.test(String(symbol || ''))) return '韩国市场';
    if (/^US_[A-Z.]{1,6}$/i.test(String(symbol || ''))) return '美国市场';
    var prefix = String(symbol || '').slice(0, 2).toLowerCase();
    return prefix === 'sh' ? '上海证券交易所'
      : prefix === 'sz' ? '深圳证券交易所'
        : prefix === 'bj' ? '北京证券交易所' : '';
  }

  function inferStockSymbol(symbol) {
    if (/^(US_[A-Z.]{1,6}|KR_SKHYNIX)$/i.test(String(symbol || ''))) return String(symbol).toUpperCase();
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
    if (raw.symbol && String(raw.symbol).toLowerCase() !== String(code).toLowerCase()) {
      throw new Error('指数行情资产身份与请求不匹配，已停止显示。');
    }
    // The legacy adapter fills absent OHLC with close. Restore missingness using
    // the raw published fields so this chart can explicitly show a close line.
    var ph = raw.price_history;
    var bars = ph && Array.isArray(ph.dates) && Array.isArray(ph.close) ? ph.dates.map(function (date, i) {
      return { date: date, close: ph.close[i], open: ph.open && ph.open[i] != null ? ph.open[i] : null,
        high: ph.high && ph.high[i] != null ? ph.high[i] : null, low: ph.low && ph.low[i] != null ? ph.low[i] : null,
        volume: ph.volume && ph.volume[i] != null ? ph.volume[i] : null };
    }).filter(function (bar) { return !result.asof || bar.date <= result.asof; }) : result.bars;
    var symbol = String(result.sym && result.sym.sym || raw.symbol || code || '');
    symbol = /^(US_|JP_|KR_)/i.test(symbol) ? symbol.toUpperCase() : symbol.toLowerCase();
    var identity = result.sym || {};
    var market = raw.market || identity.market || (/^US_/.test(symbol) ? 'us' : /^JP_/.test(symbol) ? 'jp' : /^KR_/.test(symbol) ? 'kr' : 'cn');
    var currency = raw.currency || identity.currency || ({ us: 'USD', jp: 'JPY', kr: 'KRW', cn: 'CNY' })[market] || '';
    var model = modelRecord(raw, result);
    return {
      assetType: 'index',
      market: market,
      currency: currency,
      timezone: raw.timezone || identity.timezone || '',
      symbol: symbol,
      code: symbol,
      name: result.name || raw.name || result.sym && result.sym.name || symbol,
      exchange: raw.exchange || identity.exchange || exchangeFor(symbol),
      bars: bars,
      asof: result.asof || raw.asof || '',
      modelAsOf: result.asof || raw.asof || '',
      marketAsOf: bars.length ? bars[bars.length - 1].date || bars[bars.length - 1].time || '' : '',
      top: result.top || raw.top || {},
      future_calendar: raw.future_calendar || result.future_calendar || null,
      evidence_levels: raw.evidence_levels || result.evidence_levels || {},
      modelVersion: model.modelVersion,
      predictionId: model.predictionId,
      dataSource: raw.source || raw.price_history && raw.price_history.source || '',
      adjustment: raw.price_history && raw.price_history.adjustment || '',
      volumeUnit: raw.price_history && raw.price_history.volume_unit || '',
      tradingStatus: raw.trading_status || '',
      quoteUnit: '指数点位',
      modelStatus: 'ok',
      priceNote: raw.price_history && raw.price_history.note || '',
      firstVisibleAt: raw.first_visible_at || null,
      modelAdjustment: raw.price_history && raw.price_history.adjustment || '',
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
    if (market.symbol && expectedSymbol && inferStockSymbol(market.symbol) !== expectedSymbol) {
      throw new Error('行情资产身份与请求不匹配，已停止显示。');
    }
    if (hasLatest && raw.symbol && expectedSymbol && inferStockSymbol(raw.symbol) !== expectedSymbol) {
      modelError = new Error('模型资产身份与行情不匹配；仅保留行情。');
      hasLatest = false; raw = {};
    }
    var resolvedSymbol = inferStockSymbol(hasLatest && raw.symbol || market.symbol || expectedSymbol || symbol) || String(symbol || '');
    var marketCode = /^US_/.test(resolvedSymbol) ? 'us' : /^KR_/.test(resolvedSymbol) ? 'kr' : 'cn';
    var currency = { us: 'USD', kr: 'KRW', cn: 'CNY' }[marketCode];
    var quoteUnit = { us: 'USD · 美元', kr: 'KRW · 韩元', cn: 'CNY · 元' }[marketCode];
    var model = modelRecord(raw, hasLatest ? latest : null);
    var lastBar = market.price[market.price.length - 1];
    return {
      assetType: 'stock',
      market: marketCode,
      symbol: resolvedSymbol,
      code: resolvedSymbol,
      name: hasLatest && (latest.name || raw.name) || market.name || market.stock_name || resolvedSymbol,
      exchange: marketCode !== 'cn' ? market.exchange || raw.exchange || exchangeFor(resolvedSymbol) : exchangeFor(resolvedSymbol),
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
      dataSource: market.source || '',
      adjustment: market.adjustment || '',
      volumeUnit: market.volume_unit || '',
      tradingStatus: market.trading_status || '',
      quoteUnit: quoteUnit,
      currency: market.currency || raw.currency || currency,
      stale: market.stale === true,
      staleReason: market.stale_reason || '',
      freshness: market.asof_freshness || 'not_established',
      firstVisibleAt: raw.first_visible_at || null,
      modelAdjustment: raw.price_history && raw.price_history.adjustment || raw.adjust || '',
      raw: raw,
    };
  }

  function marketMetadata(data, period, intraday) {
    data = data || {};
    if (period === '30' || period === '60') {
      if (intraday && intraday.period === period && intraday.status === 'ready') {
        var limits = intraday.limits || {};
        return {
          marketDate: limits.last ? '行情时间 ' + limits.last : '',
          dataSource: [displaySource(intraday.source), period + ' 分钟', '不复权'].filter(Boolean).join(' · '),
        };
      }
      if (intraday && intraday.period === period && intraday.status === 'error') {
        return { marketDate: '', dataSource: '' };
      }
      return { marketDate: '行情时间 读取中…', dataSource: '读取中' };
    }
    var source = data.dataSource || '';
    return {
      marketDate: data.marketAsOf ? '行情日期 ' + data.marketAsOf : '',
      dataSource: displaySource(source),
    };
  }

  function displaySource(source) {
    return ({
      'Yahoo Finance v8 chart': 'Yahoo Finance',
      tencent_fqkline: '腾讯行情',
      tencent: '腾讯行情',
      sina: '新浪行情',
    })[source] || source || '';
  }

  function modelAdjustmentLabel(value, assetType) {
    if (value === 'none') return assetType === 'index' ? '不复权' : '未复权';
    if (value === 'provider_adjclose_ratio_OHLC') return '按调整收盘价比例复权';
    if (value === 'provider_index_level_unmodified') return '不复权';
    return /[A-Za-z].*_/.test(String(value || '')) ? '' : value || '';
  }

  function modelVersionLabel(value) {
    if (value === 'global_sparse27_v1_production_v2_box') return '国际市场稀疏窗口研究样本';
    return /[A-Za-z].*_/.test(String(value || '')) ? '' : value || '';
  }

  function volumeUnitLabel(value) {
    if (value === 'vendor_native') return '';
    return ({
      shares: '股',
      lots: '手',
      points: '指数点',
    })[value] || (/[A-Za-z].*_/.test(String(value || '')) ? '' : value || '');
  }

  function currencyLabel(value) {
    return ({
      USD: '美元',
      JPY: '日元',
      KRW: '韩元',
      CNY: '人民币',
    })[value] || value || '';
  }

  function intervalId(scale, band) {
    return 'interval:' + [scale, band && band.rank || 'main',
      band && band.q20_date || '', band && band.q80_date || ''].join(':');
  }

  function withRule(data, rule) {
    var raw = data.raw || {}, selected = rule === 'cycles_1_5' ? 'cycles_1_5' : 'box';
    var research = raw.research || {}, available = selected === 'box' ? !!(raw.top || data.top) :
      !!(research.cycles_1_5 && typeof research.cycles_1_5 === 'object');
    var top = selected === 'box' ? raw.top || data.top || {} : available ? research.cycles_1_5 : {};
    return Object.assign({}, data, { top: top, researchRule: selected, ruleAvailable: available,
      ruleLabel: selected === 'box' ? 'box 口径' : '完整周期 ≥ 1.5 · 未来临界点候选',
      ruleSource: selected === 'box' ? '使用已发布的 box 聚合结果。' : available
        ? '区间来自同一拟合池，并按完整周期 ≥ 1.5 条件筛选。'
        : '该截止日没有完整周期 1.5 口径的区间，可切换 box 口径。' });
  }

  function researchNote(data) {
    var raw = data.raw || {};
    if (raw.schema_version !== 'global_terminal_v1' && !(raw.research && raw.research.sample_scope)) return '';
    var count = raw.params && raw.params.window_count;
    var parts = [Number.isInteger(count) ? count + ' 个稀疏窗口（非 181 窗完整扫描）' : '稀疏窗口研究样本'];
    parts.push('固定截止日小样本重放，未进行样本外预警评分');
    if (raw.future_calendar && raw.future_calendar.note) parts.push(raw.future_calendar.note);
    return parts.join('；');
  }

  return {
    SCALES: SCALES,
    NUMERIC_EVIDENCE: NUMERIC_EVIDENCE,
    evidenceFor: evidenceFor,
    bandEvidenceCode: bandEvidenceCode,
    safeFrom: safeFrom,
    bandEvidencePolicy: bandEvidencePolicy,
    filterDescriptiveBands: filterDescriptiveBands,
    parseContext: parseContext,
    exchangeFor: exchangeFor,
    assembleIndexData: assembleIndexData,
    assembleStockData: assembleStockData,
    marketMetadata: marketMetadata,
    modelAdjustmentLabel: modelAdjustmentLabel,
    modelVersionLabel: modelVersionLabel,
    volumeUnitLabel: volumeUnitLabel,
    currencyLabel: currencyLabel,
    intervalId: intervalId,
    withRule: withRule,
    researchNote: researchNote,
  };
});
