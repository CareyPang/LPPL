/* Display policy only: no fitting, clustering, inferred price targets or calibrated probabilities. */
(function (root) {
  'use strict';
  const day = 86400000;
  const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
  const allowedEvidence = value => typeof value === 'string' && value.length > 0 && value !== 'none' &&
    !value.startsWith('fail') && !['dev_only', 'dev_failed'].includes(value);
  const count = value => Number.isInteger(value) && value >= 0 ? value : null;
  const reasonLabels = {
    EVIDENCE_WITHHELD: '证据等级不允许展示日期数值', INVALID_INTERVAL: '区间日期无效',
    NOT_FUTURE_AT_ASOF: '区间不是分析截止日之后的未来区间', INVALID_ASOF: '分析截止日缺失或不一致',
    NO_QUALIFIED_FIT: '本次没有通过过滤的拟合', NO_CANDIDATE: '本次没有可显示的候选区间',
    OBSERVATION_ONLY: '区间仅用于观察', HISTORICAL_REPLAY: '历史重放不作为当前预测',
    DISPLAY_RANGE_EXCEEDED: '候选超出图表日期范围，未裁窄区间',
    nonfinite_parameters: '拟合结果不可用', not_positive_bubble_shape: '未形成顶部模型要求的上涨形态',
    m_outside_filter: '增长形态参数未通过过滤', omega_outside_filter: '振荡参数未通过过滤',
    future_horizon_outside_filter: '临界区间超出允许的未来范围',
    fewer_than_1_5_complete_cycles: '不足1.5个完整振荡周期',
  };
  function weekdays(after, through, minimum = 12) {
    if (!validDate(after)) return [];
    const result = [], start = Date.parse(after + 'T00:00:00Z');
    const end = validDate(through) ? Date.parse(through + 'T00:00:00Z') : start;
    for (let i = 1; i <= 370 && (result.length < minimum || start + i * day <= end); i++) {
      const date = new Date(start + i * day);
      if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) result.push(date.toISOString().slice(0, 10));
    }
    return result;
  }
  function normalize(record, market, taskStatus) {
    const view = { status: 'pending', title: '当前分析尚未完成', windows: [], exclusions: [], futureDates: [],
      asOf: null, modelVersion: null, fitVersion: null, fullCycles: null, calendarVerified: false,
      calendarLabel: '未来交易日历尚未核验', stale: false, historical: false };
    if (!record) {
      if (taskStatus === 'failed') { view.status = 'failed'; view.title = '本次计算未完成'; }
      return view;
    }
    if (record.demo === true || record.model_computed === false) {
      view.status = 'not_computed'; view.title = '流程演示 · 未运行模型'; return view;
    }
    const analysis = record.analysis, top = record.top || {}, confidence = top.lppls_confidence || {};
    view.asOf = analysis?.as_of || record.asof;
    view.modelVersion = analysis?.model_version || record.model_version || null;
    view.fitVersion = analysis?.fit_code_version || record.fit_code_version || null;
    view.fullCycles = typeof analysis?.minimum_full_cycles === 'number' ? analysis.minimum_full_cycles : null;
    const adjustment = value => ({ none: '未复权', qfq: '前复权', hfq: '后复权' })[value] || '口径未核验';
    view.priceBasis = record.market_adjustment || record.model_adjustment
      ? `行情 ${adjustment(record.market_adjustment)} · 模型 ${adjustment(record.model_adjustment)}；图上只叠加日期区间，不叠加另一口径的价格曲线。` : null;
    view.stale = validDate(market?.asof) && validDate(view.asOf) && market.asof > view.asOf;
    view.historical = record.mode === 'history' || String(record.claim_origin || '').startsWith('HYPOTHETICAL');
    if (view.historical) {
      view.status = 'withheld'; view.title = '历史重放 · 不作为当前区间';
      view.exclusions.push({ reason: 'HISTORICAL_REPLAY' }); return view;
    }
    if (analysis?.status === 'failed') { view.status = 'failed'; view.title = '本次计算失败'; return view; }
    if (!validDate(view.asOf) || (analysis?.as_of && record.asof && analysis.as_of !== record.asof)) {
      view.status = 'withheld'; view.title = '结果身份待核对';
      view.exclusions.push({ reason: 'INVALID_ASOF' }); return view;
    }
    if ([record.evidence, top.evidence_override, analysis?.evidence].some(value => value && !allowedEvidence(value))) {
      view.status = 'withheld'; view.title = '已完成分析 · 日期区间未开放';
      view.exclusions.push({ reason: 'EVIDENCE_WITHHELD' }); return view;
    }
    const calendar = analysis?.calendar || {};
    const calendarDates = [...new Set((calendar.dates || []).filter(validDate))].sort();
    const calendarCovers = (value, start, end) => value.status === 'exchange_verified' && !!value.version &&
      validDate(value.coverage_start) && validDate(value.coverage_end) &&
      start >= value.coverage_start && end <= value.coverage_end;
    view.calendarVerified = calendarCovers(calendar, view.asOf, view.asOf) && calendarDates.length > 0;
    view.calendarLabel = view.calendarVerified ? `交易日历 ${calendar.version}` : '未来日期按工作日估算；交易所节假日尚未核验';
    view.calendarVersion = calendar.version || null;
    const rows = analysis ? (Array.isArray(analysis.windows) ? analysis.windows : []) : [
      { ...top.window, id: 'window', evidence: top.window?.evidence || confidence.evidence },
      ...(top.scenarios || []).map((row, index) => ({ ...row, id: 'scenario-' + index,
        start: row.q20_date, end: row.q80_date,
        evidence: row.evidence || confidence.scale_evidence?.[row.scale] || confidence.evidence })),
    ];
    if (Array.isArray(analysis?.exclusions)) view.exclusions.push(...analysis.exclusions.map(row =>
      typeof row === 'string' ? { reason: row } : { reason: String(row.reason || row.code || 'NO_CANDIDATE'), count: count(row.count) }));
    const seen = new Set();
    for (const row of rows) {
      if (!row?.start && !row?.end) continue;
      let reason;
      if (!allowedEvidence(row.evidence || analysis?.evidence)) reason = 'EVIDENCE_WITHHELD';
      else if (!validDate(row.start) || !validDate(row.end) || row.start > row.end) reason = 'INVALID_INTERVAL';
      else if (row.start <= view.asOf) reason = 'NOT_FUTURE_AT_ASOF';
      if (reason) { view.exclusions.push({ reason }); continue; }
      const identity = row.start + '/' + row.end;
      if (seen.has(identity)) continue;
      seen.add(identity);
      let width = count(row.width_sessions), lead = count(row.lead_sessions);
      const windowCalendar = row.calendar || calendar;
      const windowDates = row.calendar ? [...new Set((row.calendar.dates || []).filter(validDate))].sort() : calendarDates;
      const covers = windowDates.includes(view.asOf) && windowDates.includes(row.start) && windowDates.includes(row.end);
      const verified = calendarCovers(windowCalendar, view.asOf, row.end) && covers && row.calendar_verified !== false;
      if (covers) {
        width = windowDates.indexOf(row.end) - windowDates.indexOf(row.start) + 1;
        // Action is the first exchange session after the data cutoff, never the cutoff itself.
        lead = windowDates.indexOf(row.start) - windowDates.indexOf(view.asOf) - 1;
      }
      const boundaryMembers = row.search_boundary_members || analysis?.search_boundary_members || [];
      const formal = row.tier === 'formal_research_window' && row.cross_scale !== false && !boundaryMembers.length &&
        verified && width >= 1 && width <= 10 && lead >= 5 &&
        windowDates.indexOf(row.end) - windowDates.indexOf(view.asOf) - 1 <= 63;
      const expired = validDate(market?.asof) && row.end <= market.asof;
      const exportRevision = record.execution_origin === 'FIXED_FIT_EXPORT_REVISION' ||
        row.claim_kind_scope === 'fixed_fit_export_revision_not_new_forecast';
      view.windows.push({ id: String(row.id || 'window-' + view.windows.length), start: row.start, end: row.end,
        evidence: row.evidence || analysis?.evidence, width, lead, calendarVerified: verified,
        tier: formal ? 'formal_research_window' : 'early_observation',
        label: expired ? '已有研究区间 · 已过期' : formal ? '研究候选 · 符合时间门槛' : '研究候选 · 观察区间',
        claimKind: exportRevision ? '展示修订 · 未重新拟合' : row.claim_kind === 'revision' ? '修订' : row.claim_kind === 'new' ? '新候选' : null,
        expired, geometryQualified: formal, publishedAt: row.first_published_at || null });
      view.windows.at(-1).reason = typeof row.reason === 'string' ? row.reason : '';
      view.windows.at(-1).boundaryNote = boundaryMembers.length
        ? '部分拟合触及搜索范围边界，日期仍需进一步检查；当前保留为观察区间。' : '';
    }
    if (analysis?.status === 'no_signal' || analysis?.status === 'no_qualified_fit') {
      view.windows = [];
      view.status = 'no_signal'; view.title = '分析完成 · 当前没有合格顶部区间';
    } else if (view.windows.length) {
      view.status = 'research_candidate'; view.title = '分析完成 · 顶部时间研究候选';
    } else if (view.exclusions.some(row => row.reason === 'EVIDENCE_WITHHELD' || row.reason === 'INVALID_INTERVAL')) {
      view.status = 'withheld'; view.title = '分析完成 · 候选暂不可显示';
    } else {
      view.status = 'no_signal'; view.title = '分析完成 · 当前没有合格顶部区间';
    }
    const anchor = validDate(market?.asof) ? market.asof : view.asOf;
    if (view.calendarVerified && view.windows.some(row => !row.calendarVerified)) {
      view.calendarVerified = false;
      view.calendarLabel = '交易日历未覆盖完整区间；未来日期与提前量仍待核验';
    }
    const latestEnd = view.windows.reduce((value, row) => row.end > value ? row.end : value, anchor);
    const estimatedDates = weekdays(anchor, latestEnd);
    const globalCalendarVerified = calendarCovers(calendar, view.asOf, view.asOf);
    // Preserve verified exchange closures inside coverage even when a later window needs estimation.
    const future = globalCalendarVerified ? [
      ...calendarDates.filter(date => date > anchor),
      ...estimatedDates.filter(date => date > calendar.coverage_end),
    ] : estimatedDates;
    // Original interval endpoints always survive. They are date coordinates, never invented price bars.
    for (const row of view.windows) for (const date of [row.start, row.end]) {
      if (date > anchor && Date.parse(date) - Date.parse(anchor) <= 370 * day) future.push(date);
    }
    if (view.windows.some(row => Date.parse(row.end) - Date.parse(anchor) > 370 * day)) {
      view.exclusions.push({ reason: 'DISPLAY_RANGE_EXCEEDED' });
    }
    view.futureDates = [...new Set(future)].sort();
    return view;
  }
  function render(container, view) {
    if (!container) return;
    const doc = container.ownerDocument || root.document;
    const el = (tag, className, text) => {
      const node = doc.createElement(tag); node.className = className; node.textContent = text; return node;
    };
    container.hidden = false;
    container.className = 'analysis-summary';
    container.setAttribute('data-analysis-status', view.status);
    const children = [el('h3', 'analysis-status', view.title)];
    if (view.asOf) children.push(el('p', 'analysis-meta', `数据截止 ${view.asOf}` +
      (view.modelVersion ? ` · 模型 ${view.modelVersion}` : '') +
      (view.fullCycles !== null ? ` · 完整周期 ≥ ${view.fullCycles}` : '') +
      (view.stale ? ' · 已有结果较行情旧，更新完成前保留原日期' : '')));
    if (view.priceBasis) children.push(el('p', 'analysis-meta', view.priceBasis));
    for (const [index, row] of view.windows.entries()) {
      const card = el('div', 'analysis-window', '');
      card.setAttribute('data-analysis-window', row.id);
      card.setAttribute('data-forecast-window', 'analysis-' + index);
      card.appendChild(el('strong', '', `${row.start} — ${row.end}`));
      card.appendChild(el('span', 'analysis-window-label', `${row.label}${row.claimKind ? ' · ' + row.claimKind : ''}`));
      const unit = row.calendarVerified ? '交易日' : '估算观测日';
      card.appendChild(el('p', 'analysis-meta',
        `${row.width == null ? '区间宽度待核验' : `含端点宽度 ${row.width} ${unit}`} · ` +
        `${row.lead == null ? '提前量待核验' : `最早日距行动日 ${row.lead} ${unit}`}`));
      if (row.reason) card.appendChild(el('p', 'analysis-reasons', row.reason));
      if (row.boundaryNote) card.appendChild(el('p', 'analysis-reasons', row.boundaryNote));
      if (row.expired) card.appendChild(el('p', 'analysis-reasons', '相对当前行情该区间已过期，不能作为新的提前提醒。'));
      children.push(card);
    }
    if (view.windows.length) {
      children.push(el('p', 'analysis-meta', view.calendarLabel));
      children.push(el('p', 'analysis-meta', '行动日按数据截止后的下一观测日计算；不是实际收到结果后的可交易提前量。'));
      children.push(el('p', 'analysis-reasons', '这些是模型研究候选区间，尚未验证能可靠识别阶段顶部；不保证命中、提前5个交易日或随后跌幅。'));
    } else if (view.status === 'no_signal') children.push(el('p', 'analysis-reasons', '本次计算已结束。没有合格区间不代表不会见顶，也不代表价格安全。'));
    else if (view.status === 'failed') children.push(el('p', 'analysis-reasons', '未产生有效分析结论。行情仍可查看，可以重试当前分析。'));
    else if (view.status === 'pending') children.push(el('p', 'analysis-reasons', '行情与计算独立加载；当前没有可展示的分析结果。'));
    const exclusions = view.exclusions.filter(row => row.count !== 0);
    if (exclusions.length) {
      const details = el('details', 'analysis-reasons', '');
      details.appendChild(el('summary', '', '查看过滤与显示说明'));
      details.appendChild(el('p', '', [...new Set(exclusions.map(row =>
        (reasonLabels[row.reason] || row.reason) + (row.count == null ? '' : `（${row.count} 个窗口）`)))].join('；')));
      if (exclusions.some(row => row.count != null)) details.appendChild(el('p', '', '同一个拟合窗口可能有多项未通过原因，数量不作相加。'));
      children.push(details);
    }
    container.replaceChildren(...children);
  }
  const api = { normalize, render, allowedEvidence, validDate, weekdays };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.StockAnalysis = api;
})(typeof window === 'object' ? window : globalThis);
