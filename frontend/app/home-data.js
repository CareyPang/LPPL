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

  /* 返回 { name, sym, code, asof, bars, last, prev, status, windowText }；失败返回 { sym, name, error } */
  function one(s) {
    return G.LPPL.load(s.sym).then(function (D) {
      var t = D.top || {}, w = t.window || {}, b = D.bars;
      var ev = G.LPPL.ev(w.evidence, D.raw.evidence_levels);
      var win = '';
      if (w.start && w.end && ev.show) win = '情景区间 ' + w.start + ' – ' + w.end + '（' + ev.label + '，未校准，不是峰值日预测）';
      return {
        name: D.name, sym: D.sym.sym, code: D.sym.code, asof: D.asof, bars: b,
        last: b[b.length - 1], prev: b[b.length - 2],
        status: SIG[t.signal_status] || (t.signal_status ? '状态：' + t.signal_status : '无状态'),
        statusTitle: t.signal_status === 'signal' ? '按 FCO 标准过滤' : '',
        windowText: win
      };
    }).catch(function (e) { return { sym: s.sym, name: s.name, code: s.code, error: e && e.message || '数据未加载' }; });
  }
  function all() {
    if (!G.LPPL) return Promise.resolve([]);
    return Promise.all(G.LPPL.SYMS.map(one));
  }
  G.HOMEDATA = { one: one, all: all };
})(window);
