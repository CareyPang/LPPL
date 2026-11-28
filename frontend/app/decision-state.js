/* Published-data presentation contract. No fetching, fitting, or new scoring. */
(function (root, factory) {
  'use strict';
  var core = typeof module === 'object' && module.exports ? require('./chart-page-core.js') : root.LPPLChartPageCore;
  var api = factory(core);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLDecisionState = api;
})(typeof window !== 'undefined' ? window : globalThis, function (Core) {
  'use strict';
  var OWN = Object.prototype.hasOwnProperty;
  var LABELS = { '2-4w': '2–4周', '1-3m': '1–3个月', '3-6m': '3–6个月', '6-12m': '6–12个月', '12-24m': '12–24个月', '2-6y': '2–6年' };
  var INDICES = new Set(['sh000001', 'sh000016', 'sh000300', 'sh000905', 'sh000688', 'sz399001', 'sz399006']);
  function own(o, key) { return o != null && OWN.call(o, key); }
  function number(value) {
    if (value == null || value === '' || typeof value === 'boolean') return null;
    var n = Number(value); return Number.isFinite(n) ? n : null;
  }
  function unit(value) { var n = number(value); return n != null && n >= 0 && n <= 1 ? n : null; }
  function explicitlyStale(value) {
    return ['stale', 'expired', 'outdated'].includes(String(value || '').toLowerCase());
  }
  function date(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return '';
    var d = new Date(value + 'T00:00:00Z');
    return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === value ? value : '';
  }
  function sameSymbol(value, expected, context) {
    if (!value) return true;
    var a = String(value).toUpperCase(), b = String(expected || '').toUpperCase();
    if (context.assetType === 'stock' && (!context.market || context.market === 'cn')) {
      a = a.replace(/^(SH|SZ|BJ)(?=\d{6}$)/, ''); b = b.replace(/^(SH|SZ|BJ)(?=\d{6}$)/, '');
    }
    return a === b;
  }
  function scoreOf(record) {
    if (!record || typeof record !== 'object') return null;
    if (own(record, 'bottom_score')) {
      var explicit = number(record.bottom_score);
      if (explicit != null && explicit >= 0 && explicit <= 100) return explicit;
    }
    var intensity = unit(record.fco_neg_intensity);
    // Preserve the published value across threshold checks. Formatting belongs
    // to the renderer: rounding 49.6 to 50 must not create a new stage.
    return intensity == null ? null : intensity * 100;
  }
  function frameEntries(history, cutoff) {
    return (history && Array.isArray(history.frames) ? history.frames : [])
      .filter(function (frame) { return frame && date(frame.asof) && frame.asof <= cutoff; })
      .slice().sort(function (a, b) { return a.asof.localeCompare(b.asof); });
  }
  var VERSION_FIELDS = ['model_version', 'fit_code_version', 'variant', 'score_version'];
  function versionValue(record, key) {
    var value = record && record[key];
    if ((value == null || value === '') && key === 'variant') value = record && record.stock_meta && record.stock_meta.variant;
    return value == null || value === '' ? null : String(value);
  }
  function effectiveVersions(record, fallback) {
    var result = {};
    VERSION_FIELDS.forEach(function (key) {
      var value = versionValue(record, key);
      if (value == null) value = versionValue(fallback, key);
      if (value != null) result[key] = value;
    });
    return result;
  }
  function versionDifferences(current, record, fallback) {
    var other = effectiveVersions(record, fallback);
    // Price download hashes/data_version describe observations, not scientific
    // compatibility. Compare only explicitly provided model/score identifiers.
    // 底分不用 LPPLS 拟合：历史记录声明了自己的 score_version 时，模型版本不同不算不兼容。
    var ownScore = other.score_version != null;
    return VERSION_FIELDS.filter(function (key) {
      if (ownScore && key === 'model_version') return false;
      var a = versionValue(current, key), b = versionValue(other, key);
      return a != null && b != null && a !== b;
    });
  }
  function factorScheme(factors, context, symbol) {
    var cnIndex = context.assetType === 'index' && (!context.market || context.market === 'cn') && INDICES.has(String(symbol).toLowerCase());
    if (!cnIndex || unit(factors.valuation) == null || unit(factors.clearing) == null) {
      return { id: 'unspecified', label: '分项权重未提供', weights: [null, null] };
    }
    return { id: 'valuation_depth', label: '两项方案 · 估值 60 / 回撤深度 40', weights: [0.60, 0.40] };
  }
  function components(factors, scheme) {
    var ids = ['valuation', 'clearing'];
    var labels = ['估值条件', '回撤深度'];
    return ids.map(function (id, i) {
      var value = unit(factors[id]), detail = value == null ? '未覆盖' : '已发布分项 ' + Math.round(value * 100) + '%';
      if (id === 'valuation' && value != null) {
        var parts = [];
        if (unit(factors.erp_pct) != null) parts.push('ERP分位 ' + Math.round(factors.erp_pct * 100) + '%');
        if (unit(factors.pbn_pct) != null) parts.push('破净分位 ' + Math.round(factors.pbn_pct * 100) + '%');
        if (parts.length) detail = parts.join(' · ');
      }
      if (id === 'clearing' && number(factors.dd_52w) != null) detail = '距52周高点 ' + (Number(factors.dd_52w) * 100).toFixed(1) + '%';
      return { id: id, label: labels[i], value: value, weight: scheme.weights[i], detail: detail };
    });
  }
  function publishedSummary(history, cutoff, historical) {
    if (historical || !history || !history.bottom_summary) return null;
    var latest = (history.frames || []).map(function (f) { return date(f && f.asof); }).filter(Boolean).sort().pop();
    // A summary assembled after the model cutoff must not leak into that view.
    if (!latest || latest > cutoff) return null;
    var s = history.bottom_summary, n = number(s.n_with_50w), win = unit(s.win_rate_50w);
    if (!Number.isInteger(n) || n <= 0 || win == null) return null;
    return { n: n, nEvents: number(s.n_events), winRate50w: win,
      baselineWinRate50w: unit(s.baseline_win_rate_50w), medianReturn50w: number(s.median_ret_50w),
      medianDrawdown50w: number(s.median_post_min_50w), label: '50周后上涨比例',
      detail: n + '个事件已有50周结果；按信号周收盘与50周后收盘比较。历史汇总，不参与本次结论。' };
  }
  function bottomState(raw, history, context, symbol, cutoff, historical, invalid, modelStale) {
    var allowed = !invalid && cutoff, entries = allowed ? frameEntries(history, cutoff) : [];
    var rawDate = date(raw.asof), record = null, source = '';
    if (allowed && rawDate && rawDate <= cutoff && (!historical || rawDate === cutoff) && scoreOf(raw) != null) {
      record = raw; source = '已发布模型结果';
    }
    var eligible = entries.filter(function (frame) { return (!historical || frame.asof === cutoff) && scoreOf(frame) != null; });
    var candidate = eligible[eligible.length - 1] || null;
    // Select the requested/latest eligible frame first, then check its own
    // version with catalog fallback. Never silently pick an older compatible
    // frame after the selected one fails compatibility.
    var versionMismatchFields = history ? versionDifferences(raw, candidate || history, candidate ? history : null) : [];
    var versionMismatch = versionMismatchFields.length > 0;
    if (!record && candidate && !versionMismatch) { record = candidate; source = '已发布历史帧'; }
    var summaryMismatch = history && (versionDifferences(raw, history).length > 0 || versionMismatch ||
      entries.some(function (frame) { return versionDifferences(raw, frame, history).length > 0; }));
    var factors = record && record.bottom_factors && typeof record.bottom_factors === 'object' ? record.bottom_factors : {};
    var score = record ? scoreOf(record) : null, scheme = factorScheme(factors, context, symbol);
    var status = score == null ? 'missing' : score < 60 ? 'neutral' : 'candidate';
    var scoreDate = record ? date(record.asof) : '';
    var prior = entries.filter(function (f) { return f.asof < scoreDate && scoreOf(f) != null; }).pop();
    var comparable = prior && !versionMismatch && versionDifferences(raw, prior, history).length === 0 &&
      versionDifferences(effectiveVersions(record, history), prior, history).length === 0 &&
      scheme.id !== 'unspecified' && factorScheme(prior.bottom_factors || {}, context, symbol).id === scheme.id;
    var label = ({ missing: context.assetType === 'stock' ? '个股无底分' : '底分未覆盖', neutral: '底部条件不足', candidate: '底部条件分达标' })[status];
    if (versionMismatch) label = record ? '已发布底分 · 历史评分版本不符' : '评分记录版本不符';
    return { score: score, asof: scoreDate, stale: !!record && (!historical && (scoreDate < cutoff || modelStale)), status: status,
      label: label, notScored: status === 'missing' && context.assetType === 'stock' && !versionMismatch,
      tone: status === 'candidate' ? 'blue' : 'gray',
      components: components(factors, scheme), scheme: scheme.label, schemeId: scheme.id,
      delta: comparable ? score - scoreOf(prior) : null, previousAsOf: prior ? prior.asof : '',
      summary: allowed && !summaryMismatch ? publishedSummary(history, cutoff, historical) : null,
      versionMismatch: versionMismatch, versionMismatchFields: versionMismatchFields,
      summarySuppressedReason: summaryMismatch ? '历史统计与当前模型或评分版本不一致' : '',
      source: source, factors: factors };
  }
  function rawBands(top, scale) {
    var clusters = own(top, 'scale_clusters') ? top.scale_clusters : top.clusters;
    if (clusters && !Array.isArray(clusters) && own(clusters, scale) && Array.isArray(clusters[scale])) return clusters[scale];
    if (Array.isArray(clusters)) return clusters.filter(function (b) { return b && b.scale === scale; });
    var windows = Array.isArray(top.scale_windows) ? top.scale_windows.filter(function (b) { return b && b.scale === scale; }) : [];
    if (windows.length) return windows;
    var w = top.window;
    return scale === '6-12m' && w && w.start && w.end ? [Object.assign({}, w, { q20_date: w.start, q80_date: w.end, scale: scale })] : [];
  }
  function topState(data, context, suppliedBands, reference, invalid) {
    var top = data.top || {}, scale = context.scale || '6-12m';
    var selected = top.indicators && top.indicators[scale] || {};
    var signal = selected.signal_status || (scale === '6-12m' ? top.signal_status : '') || '';
    var evidence = Core ? Core.evidenceFor(data, scale) : 'none';
    var unavailable = invalid || !reference || data.modelStatus !== 'ok' || data.ruleAvailable === false;
    function permitted(s, input) {
      if (unavailable || !Core) return [];
      var indicator = top.indicators && top.indicators[s] || {};
      var currentSignal = indicator.signal_status || (s === '6-12m' ? top.signal_status : '');
      var code = Core.evidenceFor(data, s);
      return input.filter(function (b) {
        return b && date(b.q20_date) && date(b.q80_date) && b.q20_date <= b.q80_date && Core.bandEvidencePolicy(code, b).showDates;
      }).filter(function (b) {
        // An explicit current no-fit result cannot be revived by a stale window.
        return !['no_qualified_fit', 't1_not_qualified', 'not_computed'].includes(currentSignal) || b.q80_date < reference;
      }).map(function (b) { return Object.assign({}, b, { scale: s }); });
    }
    var all = permitted(scale, Array.isArray(suppliedBands) ? suppliedBands : rawBands(top, scale));
    var active = all.filter(function (b) { return b.q80_date >= reference; });
    var expired = all.filter(function (b) { return b.q80_date < reference; });
    var other = [];
    if (!unavailable && Core) Core.SCALES.filter(function (s) { return s !== scale; }).forEach(function (s) {
      other = other.concat(permitted(s, rawBands(top, s)).filter(function (b) { return b.q80_date >= reference; }));
    });
    var structure = signal === 'signal' && Core && Core.NUMERIC_EVIDENCE.has(evidence) && !expired.length;
    var status = unavailable ? 'unavailable' : active.length ? 'active' : other.length ? 'other_scale' : structure ? 'structure' : expired.length ? 'expired' : 'none';
    var labels = { unavailable: '顶部结果未就绪', active: '当前有顶部区间', other_scale: '其他尺度有顶部区间', structure: '有加速迹象，未形成顶部聚类', expired: '旧顶部区间已过', none: '本尺度未形成顶部区间' };
    var details = {
      unavailable: data.ruleAvailable === false ? '该截止日未封存所选口径，可切换已有口径。' : '行情可以继续查看，等待对应模型结果。',
      active: (LABELS[scale] || scale) + '尺度的已发布候选区间，日期与当前图表一致。',
      other_scale: '当前尺度没有区间；' + Array.from(new Set(other.map(function (b) { return LABELS[b.scale] || b.scale; }))).join('、') + '尺度仍有区间，可切换核对。',
      structure: (Number.isFinite(selected.n_qualified_standard) && Number.isFinite(selected.n_qualified_box) && Number.isFinite(selected.n_windows)
        ? (LABELS[scale] || scale) + '尺度 ' + selected.n_windows + ' 个拟合窗口中 ' + selected.n_qualified_standard + ' 个通过标准过滤、' +
          selected.n_qualified_box + ' 个通过形态框规则；时间区间按形态框规则的合格拟合聚类，'
        : '已发布结果有正向结构提示，') + '数量不足以聚成时间区间，所以没有顶部聚类，也没有时间区间。',
      expired: '这些区间保留作历史记录，不继续标为当前有效提醒。',
      none: signal === 'no_qualified_fit' ? '本尺度没有合格拟合，可对照其他尺度与底部条件。' : '按所选尺度与口径，目前没有可展示区间。',
    };
    return { status: status, label: labels[status], tone: status === 'active' || status === 'other_scale' ? 'red' : status === 'structure' ? 'amber' : 'gray',
      windows: active, expiredWindows: expired, otherWindows: other, detail: details[status], structureStatus: signal, evidence: evidence, scale: scale };
  }
  function coolingState(raw, cutoff, invalid) {
    var cs = !invalid && date(raw.asof) && raw.asof <= cutoff ? raw.cooling_state : null;
    var dashboard = cs && cs.dashboard || {}, dimensions = Array.isArray(dashboard.dimensions) ? dashboard.dimensions : [];
    var shock = dimensions.find(function (d) { return d && d.id === 'omori'; });
    var red = shock && shock.light === 'red' || dashboard.verdict_light === 'red' || cs && cs.phase === 'cooling_after_top';
    var light = red ? 'red' : dashboard.verdict_light || shock && shock.light || 'gray';
    return { status: red ? 'blocked' : light === 'green' ? 'clear' : light === 'yellow' ? 'watch' : 'unavailable', light: light,
      detail: red ? '冲击与止跌检查尚未通过。' : light === 'green' ? '已发布冷却检查通过。' : light === 'yellow' ? '部分条件已满足，仍需继续观察。' : '当前未提供独立的冷却检查结果。' };
  }
  function conclusionFor(top, bottom, cooling, data, invalid, modelStale, historical) {
    var f = bottom.factors, blockers = [];
    function result(status, tone, title, detail, next) {
      return { status: status, tone: tone, title: title, detail: detail, next: next, blockers: blockers };
    }
    if (invalid) return result('unavailable', 'gray', '结果暂不可核对', invalid, '重新选择标的或截止日，保留已有行情。');
    if (data.modelStatus !== 'ok' || data.ruleAvailable === false) return result('model_pending', 'gray', '行情可先查看', top.detail, '等待模型结果，或切换已有封存口径。');
    if (top.status === 'active' || top.status === 'other_scale') {
      blockers.push('当前仍有顶部区间');
      return result('top_watch', modelStale ? 'amber' : 'red', modelStale ? '已有顶部区间 · 待更新' : '先关注顶部区间',
        modelStale ? '保留上次已发布区间与评分，等待更新核对；这不是新一期提醒。' :
          bottom.score == null ? top.detail : '底部条件分保留展示；当前仍有顶部区间，不能仅凭分数升级为底部确认。',
        modelStale ? '检查结果更新，核对区间是否仍然有效。' :
          top.status === 'other_scale' ? '切换到有区间的尺度，核对日期与价格变化。' : '查看图表中的区间，并跟踪下一次修订。');
    }
    if (top.status === 'structure') {
      blockers.push('有加速迹象，时间区间未形成');
      return result('structure_watch', 'amber', '有加速迹象，未形成顶部聚类', top.detail, '等合格拟合增多并聚成时间区间，或加速迹象消失。');
    }
    if (modelStale || bottom.stale) {
      blockers.push('模型或底分尚未更新到同一时点');
      return result('stale_watch', 'amber', '已有结果等待更新', '来源状态或各项截止日表明结果仍待更新，保留已有评分与区间供核对。', '检查更新后再判断条件是否同时满足。');
    }
    if (bottom.score == null) {
      if (bottom.versionMismatch) return result('incomplete', 'gray', '评分记录版本不符', '历史评分与当前模型或评分方案的版本不同，未合并使用。', '读取与当前模型同版本的评分记录。');
      if (bottom.status === 'loading') return result('incomplete', 'gray', '评分记录读取中', '行情与顶部结果可以先查看，底部评分独立读取。', '读取完成后自动更新，无需离开图表。');
      if (bottom.status === 'error') return result('incomplete', 'gray', '评分记录读取失败', '行情与已读取的顶部结果仍保留，暂未取得底部评分。', '重试读取评分记录。');
      if (bottom.notScored) return result('incomplete', 'gray', '个股没有底分', '底分按指数发布（估值用指数口径的股权风险溢价与破净率），个股不单独评分。', '继续查看行情和顶部区间；底部条件可对照所属指数。');
      return result('incomplete', 'gray', '底部条件尚未覆盖', '当前结果没有可核对的已发布底分。', '继续查看行情和顶部区间，等待本标的底部分项。');
    }
    if (bottom.score < 60) return result('neutral', 'gray', '条件不足',
      '底分低于 60 分：估值或回撤深度未达到门槛。',
      '等待底分达到 60 分。');
    return result('bottom_probe', 'green', '底部条件满足',
      // 回放某个历史截止日时不引用之后才有的检验结果。
      historical ? '底分 ≥60：估值与回撤深度两个分项加权后达到门槛。' : '底分 ≥60：2022–2025 测试段同档 50 周后上涨的比例比同指数全部回落周高 33 个百分点；只有一个周期，各指数同涨同跌。',
      '查看估值与回撤深度两个分项。');
  }
  function build(options) {
    options = options || {};
    var input = options.data || {}, context = options.context || {}, raw = input.raw || {};
    var symbol = String(context.code || input.symbol || raw.symbol || '');
    var historical = !!context.asof, cutoff = date(context.asof) || date(input.modelAsOf) || date(raw.asof) || '';
    var modelAsOf = date(input.modelAsOf) || date(raw.asof), marketAsOf = date(input.marketAsOf);
    var rule = context.rule || input.researchRule || 'box';
    var data = Object.assign({}, input, { raw: raw, assetType: input.assetType || context.assetType,
      modelStatus: input.modelStatus || (input.top || raw.top ? 'ok' : 'missing') });
    if (Core && data.researchRule !== rule) data = Core.withRule(data, rule);
    var invalid = !symbol ? '缺少资产身份。' : !cutoff ? '缺少有效的数据截止日。' : '';
    if (!sameSymbol(raw.symbol, symbol, context) || !sameSymbol(input.symbol, symbol, context)) invalid = '结果资产与当前标的不一致，已停止展示判断。';
    if (historical && (!date(context.asof) || modelAsOf !== context.asof || date(raw.asof) && raw.asof !== context.asof)) invalid = '没有该截止日的精确模型，未改用最新结果。';
    var history = options.history || null, historyMismatch = history && (!history.symbol || !sameSymbol(history.symbol, symbol, context));
    if (historyMismatch) history = null;
    var modelStale = !historical && (input.stale === true || raw.stale === true ||
      [input.freshness, input.asof_freshness, raw.asof_freshness, raw.freshness].some(explicitlyStale) ||
      !!(marketAsOf && modelAsOf && marketAsOf > modelAsOf));
    var reference = historical ? cutoff : [cutoff, marketAsOf].filter(Boolean).sort().pop() || '';
    var top = topState(data, context, options.bands, reference, invalid);
    top.stale = modelStale;
    if (modelStale && (top.status === 'active' || top.status === 'other_scale')) {
      top.label = top.status === 'active' ? '已有顶部区间 · 待更新' : '其他尺度已有区间 · 待更新';
      top.tone = 'amber';
      top.detail = '保留上次发布的区间；更新状态待核对，不作为新一期提醒。';
    }
    var bottom = bottomState(raw, history, context, symbol, cutoff, historical, invalid, modelStale);
    if (!invalid && !bottom.versionMismatch && bottom.score == null && ['loading', 'error'].includes(options.historyStatus)) {
      bottom.status = options.historyStatus;
      bottom.label = options.historyStatus === 'loading' ? '评分记录读取中' : '评分记录读取失败';
    }
    var cooling = coolingState(raw, cutoff, invalid);
    var conclusion = conclusionFor(top, bottom, cooling, data, invalid, modelStale, historical);
    if (historyMismatch && bottom.score == null) bottom.label = '底分来源身份不匹配';
    var evidenceCode = bottom.score != null ? 'descriptive' : top.evidence || 'none';
    return { symbol: symbol, asof: cutoff, rule: rule, historical: historical, top: top, bottom: bottom, cooling: cooling, conclusion: conclusion,
      evidence: { code: evidenceCode, label: bottom.score != null ? '已发布条件解释' : '按尺度证据展示',
        detail: '底部分读取已发布结果；分数与历史上涨比例分开展示。顶部区间沿用所选尺度和口径的证据等级。' },
      provenance: { modelAsOf: modelAsOf, marketAsOf: marketAsOf, scoreAsOf: bottom.asof,
        modelVersion: input.modelVersion || raw.model_version || '', firstVisibleAt: input.firstVisibleAt || raw.first_visible_at || null,
        dataSource: input.dataSource || raw.source || raw.data_version || '', scoreSource: bottom.source,
        stale: modelStale, staleReason: modelStale ? input.staleReason || raw.stale_reason || '' : '',
        historyStatus: options.historyStatus || (history ? 'ready' : 'unavailable') } };
  }
  return { build: build };
});
