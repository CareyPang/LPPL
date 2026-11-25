/* 临界点 · 首页备选版共用取数（Open Design 维护）
   只通过 window.LPPL 读后端已发布的静态 JSON，不做任何模型计算。
   须在 app/lppl-data.js 之前引入：非本站域名（如设计预览）时把数据根指向已发布站点。 */
(function (G) {
  'use strict';
  var h = location.hostname;
  if (!G.LPPL_DATA_BASE && !/\.github\.io$/.test(h) && !/^(localhost|127\.0\.0\.1)$/.test(h)) {
    G.LPPL_DATA_BASE = 'https://careypang.github.io/LPPL/lab/mock/data/';
  }
  /* One published decision contract is shared with chart.html and the legacy terminal. */
  function rowFrom(s, D, H, historyStatus) {
    var b = D.bars;
    if (!b || !b.length) throw new Error('尚无可用日线');
    if (!G.LPPLDecisionState || !G.LPPLChartPageCore) throw new Error('统一结论组件未加载');
    var international = s.market && s.market !== 'cn';
    var rule = international ? 'cycles_1_5' : 'box';
    var data = G.LPPLChartPageCore.withRule(G.LPPLChartPageCore.assembleIndexData(s.sym, D), rule);
    var context = { code: s.sym, assetType: 'index', market: s.market || 'cn', asof: '', scale: '6-12m', rule: rule };
    var decision = G.LPPLDecisionState.build({ data: data, history: H, historyStatus: historyStatus, context: context });
    var windows = (decision.top.windows || []).concat(decision.top.otherWindows || []);
    var win = windows.map(function (w) { return (w.scale || '') + ' · ' + w.q20_date + ' – ' + w.q80_date; }).join(' / ');
    return {
      name: D.name, sym: D.sym.sym, code: D.sym.code, market: s.market || 'cn', asof: D.asof, bars: b,
      last: b[b.length - 1], prev: b[b.length - 2],
      status: decision.top.label, statusTitle: decision.top.detail,
      windowText: win, decision: decision, historyStatus: historyStatus,
      // A late history response enriches the card; it never blocks prices or invents a zero score.
      action: G.BottomAction && historyStatus !== 'loading' ? G.BottomAction.fromDecision(decision) : null,
    };
  }
  function one(s, onUpdate) {
    var D = null, H = null, historyStatus = 'loading';
    var loadMain = G.LPPL.load(s.sym);
    var loadHist = G.LPPL.history ? G.LPPL.history(s.sym) : Promise.resolve(null);
    function finishHistory(value, failed) {
      H = value; historyStatus = failed ? 'error' : 'ready';
      if (D && typeof onUpdate === 'function') onUpdate(rowFrom(s, D, H, historyStatus));
    }
    loadHist.then(function (history) { finishHistory(history, false); }, function () { finishHistory(null, true); });
    return loadMain.then(function (result) {
      var row = rowFrom(s, result, H, historyStatus);
      D = result;
      return row;
    }).catch(function (e) { return { sym: s.sym, name: s.name, code: s.code, market: s.market || 'cn', error: e && e.message || '数据未加载' }; });
  }
  function all(selectedMarket, onUpdate) {
    if (!G.LPPL) return Promise.resolve([]);
    return Promise.all(G.LPPL.SYMS.filter(function (s) {
      return !selectedMarket || (s.market || 'cn') === selectedMarket;
    }).map(function (s) { return one(s, onUpdate); }));
  }
  G.HOMEDATA = { one: one, all: all };
})(window);
