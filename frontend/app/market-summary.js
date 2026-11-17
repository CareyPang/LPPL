(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LPPLMarketSummary = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var REASONS = {
    unpublished: '尚未发布',
    unavailable: '暂时无法读取',
    empty: '数据源返回空结果',
    not_applicable: '不适用',
    hidden_evidence: '证据不足，不显示',
  };

  function selectIndexRows(liveRows, publishedRows, reason) {
    var live = Array.isArray(liveRows) ? liveRows : [];
    var published = Array.isArray(publishedRows) ? publishedRows : [];
    var liveBySymbol = new Map(live.map(function (row) { return [row.symbol || row.name, row]; }));
    var publishedBySymbol = new Map(published.map(function (row) { return [row.symbol || row.name, row]; }));
    var order = Array.from(new Set(published.concat(live).map(function (row) { return row.symbol || row.name; })));
    var rows = order.map(function (symbol) { return liveBySymbol.get(symbol) || publishedBySymbol.get(symbol); });
    var hasLive = rows.some(function (row) { return liveBySymbol.get(row.symbol || row.name) === row; });
    var hasPublished = rows.some(function (row) { return publishedBySymbol.get(row.symbol || row.name) === row; });
    return {
      rows: rows,
      source: hasLive && hasPublished ? 'mixed' : hasLive ? 'live' : hasPublished ? 'published' : 'none',
      reason: rows.length ? null : (reason || 'empty'),
    };
  }

  function historyPair(frames, asof) {
    var eligible = (Array.isArray(frames) ? frames : [])
      .filter(function (frame) { return frame && typeof frame.asof === 'string' && frame.asof <= asof; })
      .slice()
      .sort(function (a, b) { return b.asof.localeCompare(a.asof); });
    return { current: eligible[0] || null, previous: eligible[1] || null };
  }

  function build(input) {
    var indices = Array.isArray(input.indices) ? input.indices : [];
    var events = Array.isArray(input.events) ? input.events : [];
    var watchlist = Array.isArray(input.watchlist) ? input.watchlist : [];
    var relatedCount = Number(input.relatedCount) || 0;
    var models = Array.isArray(input.models) ? input.models : [];
    var comparable = models.filter(function (item) { return !item.reason; });
    var changed = comparable.filter(function (item) { return item.change !== '不变'; }).length;
    var indexText = indices.length
      ? indices.map(function (item) { return item.name + ' ' + item.change; }).join(' · ')
      : REASONS[input.indicesReason] || '暂无指数表现数据';
    var eventText = input.eventsReason && !events.length
      ? REASONS[input.eventsReason]
      : '今日 ' + events.length + ' 项' + (events.length ? '：' + events.slice(0, 2).join('；') : '');
    var watchText = watchlist.length
      ? '今日 ' + relatedCount + ' 条自选相关快讯'
      : '自选为空 · 先加自选';
    var modelText = comparable.length
      ? '最近发布主簇：' + changed + ' 项变化，' + (comparable.length - changed) + ' 项不变'
      : REASONS[input.modelsReason] || '暂无可比较的模型区间';

    return {
      lines: [
        { key: 'indices', label: '指数表现', text: indexText, href: '#s-sentiment', reason: indices.length ? null : input.indicesReason },
        { key: 'events', label: '今日事件', text: eventText, href: '#s-events', reason: input.eventsReason || (!events.length ? 'empty' : null) },
        { key: 'watchlist', label: '自选相关', text: watchText, href: '#s-news', action: 'watch', reason: watchlist.length ? null : 'not_applicable' },
        { key: 'models', label: '模型区间', text: modelText, href: '#model-range-details', reason: comparable.length ? null : input.modelsReason },
      ],
      modelDetails: models,
    };
  }

  return { REASONS: REASONS, build: build, historyPair: historyPair, selectIndexRows: selectIndexRows };
});
