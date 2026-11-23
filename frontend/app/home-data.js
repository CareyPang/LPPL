/* 临界点 · 首页备选版共用取数（Open Design 维护）
   只通过 window.LPPL 读后端已发布的静态 JSON，不做任何模型计算。
   须在 app/lppl-data.js 之前引入：非本站域名（如设计预览）时把数据根指向已发布站点。 */
(function (G) {
  'use strict';
  var h = location.hostname;
  if (!G.LPPL_DATA_BASE && !/\.github\.io$/.test(h) && !/^(localhost|127\.0\.0\.1)$/.test(h)) {
    G.LPPL_DATA_BASE = 'https://careypang.github.io/LPPL/lab/mock/data/';
  }
  var SIG = { signal: '有合格拟合：顶部结构', no_qualified_fit: '主尺度没有合格拟合', t1_not_qualified: '泡沫起点未达标准', not_computed: '未计算' };

  /* 返回 { name, sym, code, asof, bars, last, prev, status, windowText, action }；失败返回 { sym, name, error } */
  function one(s, ovMap) {
    var loadMain = G.LPPL.load(s.sym);
    var ovItem = ovMap && ovMap[s.sym] ? ovMap[s.sym] : null;
    var loadHist = !ovItem && G.LPPL.history ? G.LPPL.history(s.sym).catch(function () { return null; }) : Promise.resolve(null);
    return Promise.all([loadMain, loadHist]).then(function (pair) {
      var D = pair[0], H = pair[1];
      var international = s.market && s.market !== 'cn';
      var t = international ? D.raw && D.raw.research && D.raw.research.cycles_1_5 || {} : D.top || {};
      var w = t.window || {}, b = D.bars;
      if (!b || !b.length) throw new Error('尚无可用日线');
      var ev = G.LPPL.ev(w.evidence, D.raw.evidence_levels);
      var win = '';
      if (w.start && w.end && ev.show) win = '情景区间 ' + w.start + ' – ' + w.end + '（' + ev.label + '，未校准）';
      if (international) {
        var scales = ['6-12m','3-6m','1-3m','12-24m','2-6y','2-4w'];
        for (var scale of scales) {
          var cluster = (t.scale_clusters && t.scale_clusters[scale] || []).find(function(c) { return c.q20_date && c.q80_date && c.q80_date >= D.asof; });
          if (cluster) { win = scale + ' · ' + cluster.q20_date + ' – ' + cluster.q80_date; break; }
        }
      }
      var cs = (D.raw && D.raw.cooling_state) || null;
      var dash = cs && cs.dashboard ? cs.dashboard : null;
      var omoriDim = dash && Array.isArray(dash.dimensions) ? dash.dimensions.find(function (d) { return d && d.id === 'omori'; }) : null;
      var actOpts = {
        hasTop: t.signal_status === 'signal' || Boolean(w.start && ev.show),
        omoriRed: Boolean(omoriDim && omoriDim.light === 'red'),
      };
      var action = (!s.market || s.market === 'cn') && G.BottomAction
        ? (ovItem ? G.BottomAction.fromOverviewItem(ovItem, actOpts) : (H ? G.BottomAction.fromHistory(s.sym, H, actOpts) : null))
        : null;
      return {
        name: D.name, sym: D.sym.sym, code: D.sym.code, market: s.market || 'cn', asof: D.asof, bars: b,
        last: b[b.length - 1], prev: b[b.length - 2],
        status: international ? (win ? '完整周期1.5 · 有候选区间' : t.signal_status ? '完整周期1.5 · 尚无顶部聚类' : '完整周期1.5 · 结果未就绪') : SIG[t.signal_status] || (t.signal_status ? '状态：' + t.signal_status : '无状态'),
        statusTitle: international ? '完整周期1.5 · 27窗研究样本；未来日期未核验交易所节假日' : t.signal_status === 'signal' ? '按 FCO 标准过滤' : '',
        windowText: win,
        action: action
      };
    }).catch(function (e) { return { sym: s.sym, name: s.name, code: s.code, market: s.market || 'cn', error: e && e.message || '数据未加载' }; });
  }
  function all(selectedMarket) {
    if (!G.LPPL) return Promise.resolve([]);
    var ovPromise = G.LPPL.overview ? G.LPPL.overview().catch(function () { return null; }) : Promise.resolve(null);
    return ovPromise.then(function (ov) {
      var ovMap = {};
      if (ov && Array.isArray(ov.indices)) {
        ov.indices.forEach(function (it) { if (it && it.sym) ovMap[it.sym] = it; });
      }
      return Promise.all(G.LPPL.SYMS.filter(function(s) { return !selectedMarket || (s.market || 'cn') === selectedMarket; }).map(function (s) { return one(s, ovMap); }));
    });
  }
  G.HOMEDATA = { one: one, all: all };
})(window);
