/* Read-only presentation of the separately computed long-window study.
   No fitting, filtering, probability estimation or replacement of the 27-window chart. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LPPLLongHorizon = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var ASSETS = new Set(['US_IXIC', 'US_NDX', 'KR_KOSPI', 'KR_KOSDAQ']);
  var WINDOWS = new Set([900, 925, 950, 6500, 6600, 6700]);
  var RULES = ['cycles_1_5', 'cycles_2_5'];
  var NOTES = {
    'Selected retrospective research, not out-of-sample accuracy measurement.':'本批为选定历史样本的研究，尚未衡量样本外预警效果。',
    'Seed agreement measures numerical stability, not probability.':'seed 一致性只衡量数值稳定性，不是概率。',
    'No fixed-tc profile, bootstrap or price forecast was run.':'本批未运行固定 tc 剖面、bootstrap 或价格预测。',
    'One adjacent-window family is one scale, even if several lengths pass.':'相邻长度属于一个窗口族，多窗通过也只算一个尺度。',
    'Frozen historic input replay; no first-publication claim. Compare raw ahead and consistently mapped dates.':'使用冻结输入进行历史重放；对照交易日提前量和统一映射的日期，不视为当时首次发布。',
    'Yahoo daily close, frozen reconstruction; not contemporaneously published forecast':'Yahoo 日线收盘价 · 冻结输入历史重建',
  };
  var GATES = { optimizer_not_converged:'优化器未收敛', m_gate:'m 超出门槛', omega_gate:'ω 超出门槛', top_sign:'不符合顶部方向', damping_below_1:'阻尼不足 1', r2_below_0_9:'R² 不足 0.9', rank_or_condition:'矩阵秩或数值条件未通过', parameter_boundary:'参数触及边界' };
  var WINDOW_GATES = { incomplete_seed_pair:'两个 seed 尚未齐备', seed_tc_disagreement_gt_2_sessions:'两个 seed 的临界时间相差超过 2 个交易日', parameter_boundary:'存在参数触界', seed_quality_gate_failed:'seed 参数质量门槛未通过' };
  function note(value) { return NOTES[value] || value || ''; }
  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (s) { return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[s]; }); }
  function date(value) { return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : ''; }
  function number(value, digits) { return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits == null ? 2 : digits) : '未记录'; }
  function count(value) { return Number.isInteger(value) && value >= 0 ? String(value) : '未记录'; }
  function family(value) { return value === 'long_900' ? '约 900 日窗口族' : value === 'ultra_6600' ? '约 6600 日窗口族' : '窗口族未记录'; }
  function familyCount(value) { return Array.isArray(value) ? String(value.length) : count(value); }
  function state(value) { return ({running:'计算中',complete:'本批计算完成',complete_with_data_gaps:'可计算部分完成，仍有历史数据缺口',incomplete:'部分结果未完成',pending:'待计算',failed:'失败',missing_archive:'原始档案缺失',unavailable:'原始档案未取得',not_available:'原始档案未取得',not_established:'尚未核实'})[value] || value || '未记录'; }
  function missingArchive(row) { return /missing|unavailable|not_available|not_established/i.test(row.status || ''); }
  function dateRange(values) {
    if (!Array.isArray(values) || values.length !== 2 || !date(values[0]) || !date(values[1]) || values[0] > values[1]) return '日期区间未记录';
    return values[0] === values[1] ? '候选落在同一交易日；未形成日期宽度' : values[0] + ' — ' + values[1];
  }
  function aheadRange(values) {
    if (!Array.isArray(values) || values.length !== 2 || values.some(function (v) { return typeof v !== 'number' || !Number.isFinite(v); })) return '提前量未记录';
    return number(values[0]) + ' — ' + number(values[1]) + ' 个交易日';
  }
  function eligible(window, rule) { return !!(window.eligible && window.eligible[rule] === true); }
  function windowState(window, rule) {
    var seeds = window.seeds || [];
    if (window.data_reason && seeds.some(function (s) { return s.status === 'not_available'; })) return '真实历史不足此窗口';
    if (seeds.some(function (s) { return missingArchive(s); })) return '原始档案未取得';
    if (seeds.some(function (s) { return s.status === 'failed'; })) return '部分 seed 失败';
    if (!seeds.length || seeds.some(function (s) { return s.status !== 'complete'; })) return '计算尚未完成';
    return eligible(window, rule) ? '单窗研究候选' : '未形成该规则候选';
  }
  function study(data, context) {
    var symbol = data && data.symbol || context.code;
    if (!ASSETS.has(symbol)) return { hidden: true };
    var raw = data && data.raw || {}, payload = raw.research && raw.research.long_horizon;
    if (!payload) return { hidden: false, error: '本截止日尚未接入长窗口研究结果。原有 27 窗口分析仍可使用。' };
    var cutoff = context.asof || data.modelAsOf || data.asof || raw.asof;
    if (payload.schema_version !== 'long_horizon_v1' || payload.symbol !== symbol || !date(payload.asof) || payload.asof !== cutoff) {
      return { hidden: false, error: '长窗口档案的资产或截止日不匹配，未显示其他日期的研究结果。' };
    }
    return { hidden: false, payload: payload, cutoff: cutoff };
  }
  function budget(counts) {
    counts = counts || {};
    return '<div class="lh-budget"><span>已完成 <strong>' + count(counts.completed) + ' / ' + count(counts.expected) + '</strong></span><span>失败 ' + count(counts.failed) + '</span><span>待完成 ' + count(counts.pending) + '</span><span>数据不足 ' + count(counts.not_available == null ? 0 : counts.not_available) + '</span><span>单位：窗口 × seed</span></div>';
  }
  function windowRange(window, rule) {
    return eligible(window, rule) ? dateRange(window.seed_date_range) : '未形成该规则的未来候选';
  }
  function seedHtml(seed, rule) {
    var passed = seed.passes && seed.passes[rule] === true;
    return '<p><strong>seed ' + esc(seed.seed) + ' · ' + esc(state(seed.status)) + '</strong><br>' +
      '本 seed 参数过滤：' + (passed ? '通过' : '未通过 / 尚未完成') + ' · 优化器收敛：' + (seed.optimizer_success === true ? '是' : seed.optimizer_success === false ? '否' : '未记录') + '<br>' +
      'tc 相对截止日 ' + number(seed.tc_ahead) + ' 个交易日 · ' + esc(seed.boundary_status === 'INTERIOR' || seed.boundary_status === 'interior' ? '未触界' : seed.boundary_status ? '参数触界' : '边界状态未记录') + '<br>' +
      'm ' + number(seed.m, 4) + ' · ω ' + number(seed.omega, 4) + ' · R² ' + number(seed.r2, 4) + '<br>' +
      '阻尼 ' + number(seed.damping, 3) + ' · 完整周期 ' + number(seed.full_cycles, 3) +
      ((seed.failed_gates || []).length ? '<br>未通过项：' + esc(seed.failed_gates.map(function (g) { return GATES[g] || g; }).join('、')) : '') + '</p>';
  }
  function windowHtml(window, rule) {
    var reasons = window.rejection_reasons && window.rejection_reasons[rule] || [];
    return '<article class="lh-window"><h4>' + count(window.n) + ' 日<span>' + family(window.family) + '</span></h4>' +
      '<p class="lh-window-state">' + windowState(window, rule) + '</p>' +
      (window.data_reason ? '<p class="lh-note">' + esc(window.data_reason) + '</p>' : '') +
      (reasons.length ? '<p>' + esc(reasons.map(function (r) { return WINDOW_GATES[r] || r; }).join('；')) + '</p>' : '') +
      '<p>' + esc(windowRange(window, rule)) + '</p><p>多 seed 提前量跨度：' + esc(aheadRange(window.seed_ahead_range)) + '</p>' +
      '<p>seed 差 ' + number(window.seed_gap_days, 3) + ' 个交易日</p>' +
      '<details><summary>查看 seed 与拟合参数</summary><div class="lh-seeds">' + (window.seeds || []).map(function (seed) { return seedHtml(seed, rule); }).join('') + '</div></details></article>';
  }
  function ruleHtml(snapshot, rule) {
    var data = snapshot.rules && snapshot.rules[rule] || {}, families = data.families || [];
    var clusters = (data.cross_family_clusters || []).filter(function (cluster) {
      var memberFamilies = new Set((cluster.members || []).map(function (member) {
        var n = typeof member === 'number' ? member : member.n;
        var window = (snapshot.windows || []).find(function (w) { return w.n === n; });
        return window && window.family;
      }).filter(function (key) { return key === 'long_900' || key === 'ultra_6600'; }));
      return memberFamilies.size === 2;
    });
    // Membership is provided by the backend; never create a cluster from seeds here.
    var cross = clusters.length ? clusters.map(function (c) {
      return '<p><strong>' + esc(dateRange([c.start, c.end])) + '</strong> · 跨度 ' + number(c.span_trading_days, 1) + ' 个交易日</p>' +
        '<p>成员：' + esc((c.members || []).map(function (m) { return typeof m === 'number' ? m + '日' : count(m.n) + '日 · ' + family(m.family); }).join('；')) + '</p>';
    }).join('') : '<p>尚未形成跨窗口族分组。单窗候选和同一窗口的多个 seed 不算跨尺度确认。</p>';
    return '<div class="lh-cross"><h3>真正跨尺度分组</h3>' + cross + '</div><div class="lh-families">' +
      ['long_900', 'ultra_6600'].map(function (key) {
        var f = families.find(function (item) { return item.family === key; });
        return '<article class="lh-family"><h3>' + family(key) + '</h3><p>合格窗口：' + (f ? familyCount(f.qualified_windows) : '未记录') +
          (f && Array.isArray(f.qualified_windows) && f.qualified_windows.length ? '（' + f.qualified_windows.map(count).join('、') + ' 日）' : '') + '</p><p>' +
          esc(f ? dateRange(f.member_date_range) : '成员日期区间未记录') + '</p><small>相邻窗只算一个窗口族；成员日期跨度不是概率或置信区间。</small></article>';
      }).join('') + '</div>';
  }
  function historyHtml(payload, rule) {
    var rows = payload.stability && payload.stability.history || [];
    rows = rows.filter(function (r) { return date(r.asof) && r.asof <= payload.asof; }).slice().sort(function (a,b) { return b.asof.localeCompare(a.asof); });
    function one(r) {
        if (missingArchive(r)) return '<details class="lh-history-date"><summary>' + esc(r.asof) + ' · 原始档案未取得</summary><p class="lh-note">本期尚未完成原档核对，没有补造结果，也不计作已完成历史回放。</p></details>';
        return '<details class="lh-history-date"><summary>' + esc(r.asof) + ' · ' + esc(state(r.status)) + '</summary>' + budget(r.counts) + '<ul>' +
        (r.windows || []).filter(function (w) { return WINDOWS.has(w.n); }).map(function (w) {
          return '<li><strong>' + count(w.n) + '日 · ' + windowState(w, rule) + '</strong><br>' + esc(windowRange(w, rule)) + '<br>提前量 ' + esc(aheadRange(w.seed_ahead_range)) + '</li>';
        }).join('') + '</ul></details>';
    }
    var recent = rows.slice(0,6).map(one).join('');
    var earlier = rows.length > 6 ? '<details class="lh-history-earlier"><summary>展开更早 ' + (rows.length-6) + ' 期</summary>' + rows.slice(6).map(one).join('') + '</details>' : '';
    return '<details class="lh-history"><summary>历史截止日对照 · ' + rows.length + ' 期</summary><p class="lh-note">每期可独立展开；加上当前截止日共 ' + (rows.length+1) + ' 期。历史重建不等于当时提前发布。</p>' +
      (rows.length ? recent + earlier : '<p class="lh-note">尚无完成的历史截止日对照。</p>') +
      '<p class="lh-note">' + esc(note(payload.stability && payload.stability.note)) + '</p></details>';
  }
  function g3Html(payload) {
    var comparison = payload.g3_comparison;
    if (!comparison || comparison.asof !== payload.asof) return '';
    var rows = (comparison.windows || []).filter(function (w) { return WINDOWS.has(w.n); });
    var finished = rows.filter(function (w) { return w.status === 'complete'; });
    var box = finished.filter(function (w) { return w.box_pass === true; }).length;
    var cycles = finished.filter(function (w) { return w.cycles_1_5_pass === true; }).length;
    return '<details class="lh-method"><summary>原网站 G3 对照 · 旧 box 合格 ' + box + '/' + finished.length + ' · 1.5 周期合格 ' + cycles + '/' + finished.length + '</summary>' +
      '<p class="lh-note">同一截止日、补齐这六个窗口。G3 允许样本内 tc；上方研究臂仅搜索未来 tc，搜索域与预算不同，不能把两臂视为等价拟合或用信号数量判优。</p><ul>' +
      rows.map(function (w) { return '<li>' + count(w.n) + '日 · ' + esc(w.status) + ' · tc 相对截止日 ' + number(w.ahead) + ' 交易日 · m ' + number(w.m,4) + ' · ω ' + number(w.omega,4) + ' · B ' + number(w.B,6) + '</li>'; }).join('') + '</ul></details>';
  }
  function profileHtml(payload) {
    var profile = payload.profile_diagnostic;
    if (!profile || profile.asof !== payload.asof || profile.n !== 6600) return '';
    var points = profile.points || [], selected = points.filter(function (_, i) { return i % 5 === 0 || i === points.length - 1; });
    var counts = profile.counts || {};
    return '<details class="lh-method lh-profile"><summary>把顶部放在不同时间，误差变化多大？ · 6600 日窗</summary>' +
      '<p class="lh-note">固定 tc 后，其余参数重新拟合。误差越平坦，日期越难区分。这里只展示拟合误差，没有计算概率、bootstrap 或校准后的置信区间。</p>' +
      '<p class="lh-note">已完成 ' + count(counts.completed) + '/' + count(counts.expected) + ' 次；下面展示 ' + selected.length + '/' + points.length + ' 个网格点。粗网格仍可能漏掉窄的局部最优点。</p>' +
      '<div class="lh-profile-rows">' + selected.map(function (p) {
        return '<p><strong>未来 ' + number(p.ahead,0) + ' 个交易日</strong><span>SSE ' + number(p.sse,4) + '</span><span>比最低误差高 ' + number(p.delta_sse_pct,3) + '%</span><span>收敛 seed ' + count(p.converged_seeds) + '/' + count(p.completed_seeds) + '</span></p>';
      }).join('') + '</div></details>';
  }
  function html(payload, rule, badge) {
    rule = RULES.indexOf(rule) >= 0 ? rule : 'cycles_1_5';
    var ruleData = payload.rules && payload.rules[rule] || {};
    var source = typeof payload.source === 'object' && payload.source ? payload.source.label : payload.source;
    var definition = /^Both seeds converge;/.test(ruleData.definition || '') ? '两 seed 均收敛且未触界；B<0、0.1<m<0.9、6<ω<13、阻尼≥1、R²≥0.9，矩阵秩与数值条件通过；seed 临界时间差≤2个交易日；完整周期≥' + (rule === 'cycles_1_5' ? '1.5' : '2.5') + '。' : ruleData.definition;
    var calendar = payload.calendar || {};
    var quality = payload.source && payload.source.data_quality;
    var qualityText = quality && quality.status === 'unresolved_cross_source_discrepancy' ? '来源核验待完成：' + (date(quality.affected_date) || '某历史交易日') + ' 在不同来源的收盘值存在差异。本研究保留当前来源原值，尚未取得交易所裁定。' : '';
    var calendarText = calendar.status === 'us_cash_exchange_reference' ? '2026年采用纳斯达克已核对假日；2027年参考NYSE，尚未完成纳斯达克全年核验。交易日提前量为原始值。' : calendar.status === 'weekday_estimate' ? '按周一至周五外推，尚未扣除交易所休市日。' : calendar.status === 'observed_historical_sessions_else_weekday_estimate' ? '历史评分使用该标的实际交易日；尚未发生的日期按平日估算，未核对交易所休市日，韩股不套用美股日历。' : calendar.note || calendar.status;
    return '<div class="lh-heading"><p>截至 ' + esc(payload.asof) + ' · ' + esc(state(payload.status)) + '</p>' +
      (badge ? badge.html('research_candidate', { label:'长窗研究', detail:'独立长窗历史重建，未进行盲测预警效果验证。多 seed 差异只反映数值稳定性。' }) : '') + '</div>' + budget(payload.counts) +
      (qualityText ? '<p class="lh-note">' + esc(qualityText) + '</p>' : '') +
      (calendar.status === 'observed_historical_sessions_else_weekday_estimate' ? '<p class="lh-note">未来日期为平日估算，交易所休市日尚未核验；请同时查看交易日提前量。</p>' : '') +
      '<div class="lh-rule-switch" role="group" aria-label="长窗口过滤规则"><button type="button" data-lh-rule="cycles_1_5" aria-pressed="' + (rule === 'cycles_1_5') + '">完整周期 1.5 · 研究</button>' +
      '<button type="button" data-lh-rule="cycles_2_5" aria-pressed="' + (rule === 'cycles_2_5') + '">完整周期 2.5 · 对照</button></div>' +
      '<p class="lh-note">' + esc(definition || '仅切换后端已计算的独立过滤结果；主图的 27 个窗口与原尺度不变。') + '</p>' + ruleHtml(payload, rule) +
      '<div class="lh-windows">' + (payload.windows || []).filter(function (w) { return WINDOWS.has(w.n); }).map(function (w) { return windowHtml(w, rule); }).join('') + '</div>' +
      '<p class="lh-note">多 seed 的窄差仅表示优化结果接近，不是预测不确定性；成员日期跨度不是统计置信区间。</p>' + historyHtml(payload, rule) + g3Html(payload) + profileHtml(payload) +
      '<details class="lh-method"><summary>数据与证据说明</summary><ul><li>来源：' + esc(note(source) || '未记录') + '</li><li>版本：' + esc(payload.model_version || '未记录') + '</li>' +
      (payload.source && typeof payload.source === 'object' && payload.source.rows != null ? '<li>真实日线：' + count(payload.source.rows) + ' 日 · ' + esc(date(payload.source.first_date) || '起日未记录') + ' 至 ' + esc(payload.asof) + '</li>' : '') +
      (qualityText ? '<li>来源差异（未裁定）：' + esc(date(quality.affected_date)) + ' · Naver 收盘 ' + number(quality.observed_naver_close,4) + ' · Yahoo 收盘 ' + number(quality.observed_yahoo_close,4) + ' · 本研究当前源原值 ' + number(quality.current_source_close,4) + '。未将另一来源值拼接或替换进本序列。</li>' : '') +
      '<li>首次可见：' + esc(payload.first_visible_at || '未记录；本次查看不补造历史发布时间') + '</li><li>交易日历：' + esc(calendarText || '未记录') + '</li>' +
      (payload.limits || []).map(function (text) { return '<li>' + esc(note(text)) + '</li>'; }).join('') + '</ul></details>';
  }
  function attach(options) {
    var doc = options.document, host = doc.getElementById('long-horizon-card'), body = doc.getElementById('long-horizon-content'), summary = doc.getElementById('long-horizon-summary');
    var current = null, rule = 'cycles_1_5';
    if (!host || !body || !summary) return { render:function () {} };
    var view = doc.defaultView, direct = !!(view && view.location.hash === '#long-horizon-card'), scrolled = false;
    if (direct) host.open = true;
    function reveal() {
      if (!direct || scrolled) return;
      scrolled = true;
      view.requestAnimationFrame(function () { host.scrollIntoView({ block:'start' }); });
    }
    function paint() { if (current) body.innerHTML = html(current, rule, options.badge); }
    body.addEventListener('click', function (event) {
      var button = event.target.closest('[data-lh-rule]');
      if (!button || RULES.indexOf(button.dataset.lhRule) < 0) return;
      rule = button.dataset.lhRule; paint();
      var active = body.querySelector('[data-lh-rule="' + rule + '"]'); if (active) active.focus({ preventScroll:true });
    });
    return { render:function (data) {
      var value = study(data, options.context); host.hidden = value.hidden;
      if (value.hidden) { current = null; body.replaceChildren(); return; }
      if (value.error) { current = null; summary.textContent = '当前截止日未就绪'; body.innerHTML = '<p class="lh-empty">' + esc(value.error) + '</p>'; reveal(); return; }
      current = value.payload;
      summary.textContent = current.asof + ' · ' + count(current.counts && current.counts.completed) + '/' + count(current.counts && current.counts.expected) + ' 已完成' + (current.counts && current.counts.not_available ? ' · 数据不足 ' + current.counts.not_available : '');
      paint();
      reveal();
    } };
  }
  return { study:study, html:html, dateRange:dateRange, aheadRange:aheadRange, attach:attach };
});
