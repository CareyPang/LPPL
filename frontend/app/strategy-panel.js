/* 临界点 · 策略回放报告组件（Open Design 维护）
   数据只来自 LPPL.strategy(sym)（后端静态 strategy/<sym>.json）；未发布时整块显示“策略回测结果未发布”，绝不填假数字。
   口径：事前登记规则的历史回放，不是预测，不是收益承诺。汇总指标按 evidence 门控：LPPL.ev(level).show=false 只显示状态文字。
   纯逻辑（model）可在 node 下测试；mount 负责 DOM。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.StrategyPanel = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var SEGMENTS = [['dev', '开发'], ['cal', '校准'], ['test', '测试'], ['all', '全部']];
  var TABS = [['metrics', '指标'], ['trades', '交易'], ['props', '属性']];
  var HIDE = { none: 1, fail: 1, fail_i: 1, fail_ii: 1, fail_iii: 1, fail_i_iii: 1, dev_only: 1, dev_failed: 1, pending_cal: 1, pending_test: 1 };
  var STATUS_TEXT = { none: '无证据', dev_only: '只在开发段看过', dev_failed: '开发段未通过', pending_cal: '校准段待验证', pending_test: '测试段待验证', fail: '未通过', fail_i: '未通过（I）', fail_ii: '未通过（II）', fail_iii: '未通过（III）', fail_i_iii: '未通过（I/III）', descriptive: '历史回放 · 描述性', pass_test: '测试段通过', test_pass: '测试段通过' };
  var METRIC_DEFS = [
    ['n_trades', '交易次数', 'int'], ['win_rate', '胜率', 'pct'], ['total_return', '区间总收益', 'pct'], ['bh_return', '买入持有收益', 'pct'],
    ['cagr', '年化（CAGR）', 'pct'], ['max_drawdown', '最大回撤', 'pct'], ['bh_max_drawdown', '买入持有最大回撤', 'pct'], ['profit_factor', '盈亏比', 'num'],
    ['avg_trade_return', '平均每笔收益', 'pct'], ['avg_bars', '平均持有交易日', 'num'], ['exposure', '持仓时间占比', 'pct'], ['turnover', '年换手（次）', 'num'],
  ];
  function fmt(v, kind) {
    if (v == null || !Number.isFinite(Number(v))) return '—';
    var x = Number(v);
    if (kind === 'pct') return (x > 0 ? '+' : '') + (x * 100).toFixed(2) + '%';
    if (kind === 'int') return String(Math.round(x));
    return x.toFixed(2);
  }
  function show(level) { return !HIDE[level || 'none']; }
  function statusText(level) { return STATUS_TEXT[level || 'none'] || String(level); }

  /* model(data, seg) → { published, segment, metrics:[{key,label,value,text,shown}], evidence, n, trades, equity, props, note } */
  function model(data, seg) {
    if (!data || typeof data !== 'object' || !data.rule_id) return { published: false, segment: seg || 'test' };
    var segment = seg && (seg === 'all' || (data.metrics && data.metrics[seg])) ? seg : (data.metrics && data.metrics.test ? 'test' : 'all');
    var m = (data.metrics && data.metrics[segment]) || {};
    var level = m.evidence || data.evidence || 'none', ok = show(level);
    var metrics = METRIC_DEFS.filter(function (d) { return d[0] in m; }).map(function (d) {
      return { key: d[0], label: d[1], value: m[d[0]], text: ok ? fmt(m[d[0]], d[2]) : statusText(level), shown: ok };
    });
    var trades = Array.isArray(data.trades) ? data.trades.filter(function (t) { return segment === 'all' || !t.segment || t.segment === segment; }) : [];
    var equity = Array.isArray(data.equity) ? data.equity : [];
    return {
      published: true, segment: segment, level: level, shown: ok, status: statusText(level),
      n: Number.isFinite(Number(m.n_trades)) ? Number(m.n_trades) : trades.length,
      metrics: metrics, trades: trades, equity: equity, segments: data.segments || {}, hasMetrics: data.metrics || {}, props: data.properties || {},
      rule: data.rule_id, prereg: data.prereg_doc || '', asof: data.asof || '', note: data.note || '',
    };
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function equitySvg(eq, segments, w, h) {
    if (!eq.length) return '<p class="sp-empty">净值曲线未发布。</p>';
    var xs = eq.map(function (p) { return Date.parse(p.date); }), x0 = xs[0], x1 = xs[xs.length - 1] || x0 + 1;
    var vals = [];
    eq.forEach(function (p) { vals.push(Number(p.nav)); if (p.bh_nav != null) vals.push(Number(p.bh_nav)); });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals); if (hi === lo) hi = lo + 1;
    var X = function (t) { return ((t - x0) / (x1 - x0)) * (w - 8) + 4; }, Y = function (v) { return h - 6 - ((v - lo) / (hi - lo)) * (h - 12); };
    var path = function (key) { return eq.filter(function (p) { return p[key] != null; }).map(function (p, i) { return (i ? 'L' : 'M') + X(Date.parse(p.date)).toFixed(1) + ' ' + Y(Number(p[key])).toFixed(1); }).join(' '); };
    var bands = ['dev', 'cal', 'test'].map(function (k) {
      var s = segments[k]; if (!s || !s[0] || !s[1]) return '';
      var a = X(Date.parse(s[0])), b = X(Date.parse(s[1]));
      return '<rect class="sp-band ' + k + '" x="' + a.toFixed(1) + '" y="0" width="' + Math.max(0, b - a).toFixed(1) + '" height="' + h + '"/>';
    }).join('');
    var peak = -Infinity, ddPath = '';
    eq.forEach(function (p) { var v = Number(p.nav); if (v > peak) peak = v; });
    return '<svg class="sp-eq" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" role="img" aria-label="净值曲线与买入持有对比，底色为开发/校准/测试段">' + bands +
      '<path class="sp-bh" d="' + path('bh_nav') + '"/><path class="sp-nav" d="' + path('nav') + '"/></svg>' + ddPath;
  }

  function render(M, tab) {
    if (!M.published) {
      return '<div class="sp-unpub"><p class="sp-unpub-t">策略回测结果未发布</p>' +
        '<p>后端还没有产出这只标的的策略回放 JSON。这里将来显示的是<b>事前登记规则的历史回放</b>：净值曲线与买入持有对比、开发 / 校准 / 测试三段分别的汇总、逐笔交易和假设（A 股 T+1、涨跌停不可成交、佣金印花税与滑点）。</p>' +
        '<p class="sp-dim">规则与字段见 <a href="lab/guide.html">用户指南</a>；只开放事前登记的规则，不提供自由调参。历史回放不是预测，也不是收益承诺。</p></div>';
    }
    var head = '<div class="sp-head"><div class="sp-segs" role="group" aria-label="区间">' + SEGMENTS.map(function (s) {
      return '<button type="button" data-seg="' + s[0] + '" aria-pressed="' + (M.segment === s[0]) + '"' + (!M.hasMetrics[s[0]] ? ' disabled' : '') + '>' + s[1] + '</button>';
    }).join('') + '</div><span class="sp-ev ' + (M.shown ? 'ok' : 'off') + '">' + esc(M.status) + '</span><span class="sp-n m">n = ' + M.n + '</span><span class="sp-dim">历史回放，不是预测</span></div>' +
      '<nav class="sp-tabs" aria-label="报告页签">' + TABS.map(function (t) { return '<a href="#" data-tab="' + t[0] + '"' + (tab === t[0] ? ' aria-current="location"' : '') + '>' + t[1] + '</a>'; }).join('') + '</nav>';
    var body = '';
    if (tab === 'metrics') {
      body = (M.shown ? '<div class="sp-chart">' + equitySvg(M.equity, M.segments, 600, 180) + '<div class="sp-lgd"><span><i class="nav"></i>策略净值</span><span><i class="bh"></i>买入持有</span><span><i class="b dev"></i>开发</span><span><i class="b cal"></i>校准</span><span><i class="b test"></i>测试</span></div></div>' : '') +
        (M.shown ? '' : '<p class="sp-gate">该区间证据等级为「' + esc(M.status) + '」，按规则不显示数值，只显示状态。</p>') +
        '<div class="sp-grid">' + M.metrics.map(function (x) { return '<div class="sp-kv"><span>' + esc(x.label) + '</span><b class="m' + (x.shown ? '' : ' off') + '">' + esc(x.text) + '</b></div>'; }).join('') + '</div>';
    } else if (tab === 'trades') {
      body = M.trades.length ? '<div class="sp-tw"><table class="sp-t"><thead><tr><th>#</th><th>买入</th><th>卖出</th><th>持有(日)</th><th>收益</th><th>段</th></tr></thead><tbody>' +
        M.trades.map(function (t, i) { return '<tr data-trade="' + i + '"><td class="m">' + (i + 1) + '</td><td class="m">' + esc(t.entry) + '</td><td class="m">' + esc(t.exit || '持有中') + '</td><td class="m">' + (M.shown && t.bars != null ? t.bars : '—') + '</td><td class="m ' + (Number(t.ret) >= 0 ? 'up' : 'dn') + '">' + (M.shown ? fmt(t.ret, 'pct') : '—') + '</td><td>' + esc(t.segment || '') + '</td></tr>'; }).join('') +
        '</tbody></table></div>' : '<p class="sp-empty">该区间没有交易记录。</p>';
    } else {
      var P = M.props;
      var rows = [['登记规则', M.rule], ['事前登记文档', M.prereg], ['结果截止', M.asof], ['成交假设', P.t_plus_1 === false ? '无 T+1' : 'A 股 T+1：买入次日才能卖出'], ['涨跌停', P.limit_lock === false ? '不处理' : '一字涨跌停当日不可成交，顺延到下一可成交日'],
        ['佣金', P.fee_bps != null ? P.fee_bps + ' bp / 边' : '—'], ['印花税', P.stamp_bps != null ? P.stamp_bps + ' bp（卖出）' : '—'], ['滑点', P.slippage_bps != null ? P.slippage_bps + ' bp / 边' : '—'], ['开发 / 校准 / 测试', ['dev', 'cal', 'test'].map(function (k) { var s = M.segments[k]; return s ? s[0] + '→' + s[1] : '—'; }).join(' · ')]];
      body = '<table class="sp-props">' + rows.map(function (r) { return '<tr><th>' + esc(r[0]) + '</th><td>' + esc(r[1] || '—') + '</td></tr>'; }).join('') + '</table>' + (M.note ? '<p class="sp-dim">' + esc(M.note) + '</p>' : '');
    }
    return head + '<div class="sp-body">' + body + '</div>';
  }

  function mount(o) {
    var el = o.el, state = { seg: o.segment || 'test', tab: o.tab || 'metrics', data: null };
    function draw() { el.innerHTML = render(model(state.data, state.seg), state.tab); }
    el.addEventListener('click', function (e) {
      var s = e.target.closest('button[data-seg]'); if (s) { state.seg = s.dataset.seg; draw(); return; }
      var t = e.target.closest('a[data-tab]'); if (t) { e.preventDefault(); state.tab = t.dataset.tab; draw(); }
    });
    draw();
    return { set: function (data) { state.data = data; draw(); }, state: state, redraw: draw };
  }
  return { SEGMENTS: SEGMENTS, TABS: TABS, METRIC_DEFS: METRIC_DEFS, fmt: fmt, show: show, statusText: statusText, model: model, render: render, mount: mount };
});
