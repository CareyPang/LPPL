(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLChartResearchCard = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  function str(value) { return value == null || value === '' ? '未记录' : String(value); }
  function wrapLines(text, limit) {
    return text.flatMap(function (line) {
      return String(line).split(/\r?\n/).flatMap(function (part) {
        var chars = Array.from(part), output = [];
        if (!chars.length) return [''];
        for (var i = 0; i < chars.length; i += limit) output.push(chars.slice(i, i + limit).join(''));
        return output;
      });
    });
  }
  function record(data, context, evidence, bands, policy, bandEvidenceCode) {
    // Explicit allowlist: never export notes, positions, account identifiers or return URLs.
    var intervals = evidence.show ? bands.filter(function (band) { return policy(evidence.code, band).draw; })
      .map(function (band) {
        var code = bandEvidenceCode ? bandEvidenceCode(evidence.code, band) :
          evidence.code === 'descriptive' || band.evidence === 'descriptive' ? 'descriptive' : band.evidence || evidence.code;
        return { start: band.q20_date, end: band.q80_date, n: band.n == null ? null : band.n, evidence: code,
          note: code === 'descriptive' ? '历史分位，不是预测' : code === 'research_candidate' ? '研究候选，非正式提醒' : '研究区间，不是概率' };
      }) : [];
    return { schema: 'lppl.anonymous-research-card.v1', symbol: str(data.symbol), name: str(data.name),
      assetType: str(data.assetType), exchange: str(data.exchange), unit: str(data.quoteUnit),
      marketAsOf: str(data.marketAsOf || data.asof), modelAsOf: str(data.modelAsOf), scale: context.scale,
      source: str(data.dataSource), adjustment: str(data.adjustment), volumeUnit: str(data.volumeUnit),
      modelVersion: str(data.modelVersion), predictionId: str(data.predictionId), firstVisibleAt: str(data.firstVisibleAt),
      evidence: str(evidence.code), evidenceLabel: str(evidence.label), intervals: intervals,
      mode: context.asof ? '历史重放；不等同于提前发布预测' : '已发布研究结果',
      archiveSha256: context.archive || null,
      note: evidence.code === 'descriptive' || intervals.some(function (item) { return item.evidence === 'descriptive'; })
        ? '历史分位，不是预测' : evidence.code === 'research_candidate' ? '研究候选，非正式提醒；区间不是概率；无价格目标' : '区间不是概率；无价格目标',
      stale: data.stale === true, staleReason: str(data.staleReason), exportedAt: new Date().toISOString() };
  }
  function lines(item) {
    if (item.schema === 'lppl.anonymous-intraday-card.v1') {
      return wrapLines([
        item.name + ' · ' + item.symbol + ' · ' + item.exchange + ' · ' + item.unit,
        item.period + ' 分钟行情 · ' + item.source + ' · 不复权',
        '覆盖 ' + item.first + ' — ' + item.last + '（上海时间） · ' + item.count + ' 根' +
          (item.lastBarEnded === false ? ' · 末根未收盘' : ''),
        '行情抓取时间 ' + item.fetchedAt,
        '成交量使用供应商原始单位；OBV 背离为历史形态描述。',
        '本图仅展示分钟行情，未计算分钟级 LPPLS。导出 ' + item.exportedAt
      ], 66);
    }
    var text = [item.name + ' · ' + item.symbol + ' · ' + item.exchange + ' · ' + item.unit,
      '行情截止 ' + item.marketAsOf + ' ｜ 模型截止 ' + item.modelAsOf + ' ｜ 尺度 ' + item.scale,
      '来源 ' + item.source + ' ｜ 行情复权 ' + item.adjustment + ' ｜ 成交量 ' + item.volumeUnit,
      '证据 ' + item.evidenceLabel + ' (' + item.evidence + ') ｜ ' + item.mode,
      '模型 ' + item.modelVersion + ' ｜ Prediction ID ' + item.predictionId,
      '首次可见时间 ' + item.firstVisibleAt + ' ｜ 导出 ' + item.exportedAt]
      .concat(item.archiveSha256 ? ['原档 SHA-256 ' + item.archiveSha256] : [])
      .concat(item.intervals.length ? item.intervals.map(function (interval, i) {
        return '区间 ' + (i + 1) + '：' + interval.start + ' — ' + interval.end +
          (interval.n != null ? ' ｜ n=' + interval.n : '') + ' ｜ ' + interval.note;
      }) : ['当前尺度没有可展示区间；请查看证据状态'])
      .concat(item.stale ? ['缓存已过期：' + item.staleReason] : [], [item.note]);
    // 66 full-width glyphs at 17px fit the 1184px content width. Both exports
    // use these same lines; long IDs and sources remain complete, never ellipsized.
    return wrapLines(text, 66);
  }
  function escape(value) { return String(value).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c];
  }); }
  function svg(item) {
    var text = lines(item), height = 130 + text.length * 38;
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="' + height + '" viewBox="0 0 1280 ' + height + '">' +
      '<rect width="1280" height="100%" fill="#f6f8fc"/><rect x="20" y="20" width="1240" height="' + (height - 40) + '" rx="18" fill="white" stroke="#dce2ed"/>' +
      '<g font-family="Microsoft YaHei, sans-serif" fill="#172033"><text x="48" y="65" font-size="25">匿名研究卡 · ' +
      (item.schema === 'lppl.anonymous-intraday-card.v1' ? '分钟行情' : '区间与证据') + '</text>' +
      text.map(function (line, i) { return '<text x="48" y="' + (110 + i * 38) + '" font-size="17">' + escape(line) + '</text>'; }).join('') +
      '</g></svg>';
  }
  function intradayRecord(data, meta) {
    return {
      schema: 'lppl.anonymous-intraday-card.v1', symbol: str(data.symbol), name: str(data.name),
      exchange: str(data.exchange), unit: str(data.quoteUnit), period: meta.period, source: str(meta.source),
      first: str(meta.limits.first), last: str(meta.limits.last), count: str(meta.limits.n_bars),
      lastBarEnded: meta.lastBarEnded, fetchedAt: str(meta.fetchedAt),
      exportedAt: new Date().toISOString()
    };
  }
  return { record: record, intradayRecord: intradayRecord, lines: lines, svg: svg, wrapLines: wrapLines };
});
