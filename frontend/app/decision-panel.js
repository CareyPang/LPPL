/* Shared presentation for published top windows and bottom-condition records.
   All data selection and interpretation belongs to decision-state.js. This
   renderer never fetches prices, fits a model or invents an unreported score. */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLDecisionPanel = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var TONES = new Set(['blue', 'green', 'amber', 'red', 'gray']);
  var SCALES = { '2-4w': '2–4 周', '1-3m': '1–3 个月', '3-6m': '3–6 个月', '6-12m': '6–12 个月', '12-24m': '12–24 个月', '2-6y': '2–6 年' };
  var RULES = { box: '形态框', cycles_1_5: '完整周期 1.5' };
  var FACTORS = ['valuation', 'clearing'];
  function finite(value) { return typeof value === 'number' && Number.isFinite(value); }
  function number(value, digits) { return finite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: digits == null ? 1 : digits }) : '—'; }
  function pct(value, signed) { return finite(value) ? (signed && value > 0 ? '+' : '') + number(value * 100, 1) + '%' : '—'; }
  function tone(value) { return TONES.has(value) ? value : 'gray'; }
  function text(value) { return value == null ? '' : String(value); }

  function mount(container, options) {
    options = options || {};
    if (!container) return { render: function () {}, destroy: function () {} };
    var doc = options.document || container.ownerDocument;
    var badge = options.badge;
    var renderKey = '';
    container.classList.add('decision-panel-host');
    function node(tag, className, value) {
      var el = doc.createElement(tag);
      if (className) el.className = className;
      if (value != null) el.textContent = text(value);
      return el;
    }
    function pill(label, value) {
      var p = node('span', 'decision-pill', label);
      p.dataset.tone = tone(value);
      return p;
    }
    function definition(parent, label, value) {
      if (value == null || value === '') return;
      parent.append(node('dt', '', label), node('dd', '', value));
    }
    function details(key, title, open) {
      var el = node('details', 'decision-details');
      el.dataset.decisionDetail = key;
      el.open = Boolean(open);
      var summary = node('summary', 'decision-details-toggle');
      summary.append(node('span', '', title));
      var chevron = node('span', 'decision-chevron', '+');
      chevron.setAttribute('aria-hidden', 'true');
      summary.append(chevron);
      el.append(summary);
      return el;
    }
    function render(view) {
      view = view || {};
      var key = text(view.symbol) + ':' + text(view.asof);
      var opened = new Set();
      if (renderKey === key) container.querySelectorAll('details[open][data-decision-detail]').forEach(function (el) { opened.add(el.dataset.decisionDetail); });
      renderKey = key;
      var conclusion = view.conclusion || {}, bottom = view.bottom || {}, top = view.top || {}, cooling = view.cooling || {}, evidence = view.evidence || {}, provenance = view.provenance || {};
      var wrapper = node('section', 'decision-panel');
      wrapper.dataset.tone = tone(conclusion.tone);
      wrapper.dataset.status = text(conclusion.status || 'unavailable');
      wrapper.dataset.symbol = text(view.symbol);
      wrapper.dataset.asof = text(view.asof);
      wrapper.setAttribute('aria-label', '统一判断与底部条件');

      var heading = node('header', 'decision-heading');
      var headingName = node('div', 'decision-heading-name');
      headingName.append(node('p', 'decision-eyebrow', view.historical ? '回到当时' : '研究判断'), node('h2', 'decision-section-title', '顶部区间与底部条件'));
      var headingMeta = node('div', 'decision-heading-meta');
      if (view.asof) headingMeta.append(node('span', 'decision-cutoff', '判断截至 ' + view.asof));
      if (view.rule) headingMeta.append(node('span', 'decision-rule', RULES[view.rule] || view.rule));
      if (badge && typeof badge.html === 'function') {
        var evidenceNode = node('span', 'decision-evidence');
        // The existing badge owns escaping and the shared evidence vocabulary.
        evidenceNode.innerHTML = badge.html(evidence.code || 'none', { label: evidence.label || '研究证据', detail: evidence.detail || '', n: bottom.summary && bottom.summary.n });
        headingMeta.append(evidenceNode);
      } else if (evidence.label) {
        var fallbackBadge = pill(evidence.label, 'gray');
        if (evidence.detail) fallbackBadge.title = evidence.detail;
        headingMeta.append(fallbackBadge);
      }
      heading.append(headingName, headingMeta);
      wrapper.append(heading);

      var verdict = node('div', 'decision-verdict');
      var verdictBody = node('div', 'decision-verdict-body');
      verdictBody.append(node('p', 'decision-label', '综合判断'), node('h3', 'decision-verdict-title', conclusion.title || '等待当前标的的研究结果'));
      if (conclusion.detail) verdictBody.append(node('p', 'decision-verdict-detail', conclusion.detail));
      verdict.append(verdictBody);
      if (conclusion.next) {
        var next = node('div', 'decision-next');
        next.append(node('p', 'decision-label', '接下来关注'), node('p', 'decision-next-text', conclusion.next));
        verdict.append(next);
      }
      if (options.showSummary !== false) wrapper.append(verdict);

      var grid = node('div', 'decision-grid');
      var scoreCard = node('article', 'decision-score-card');
      scoreCard.dataset.scoreState = bottom.stale ? 'stale' : finite(bottom.score) ? 'available' : 'missing';
      var scoreHeader = node('div', 'decision-card-heading');
      scoreHeader.append(node('h3', 'decision-card-title', '底部条件综合分'), pill(bottom.stale ? '历史条件分' : bottom.label || '暂未覆盖', bottom.stale ? 'amber' : bottom.tone));
      scoreCard.append(scoreHeader);
      var scoreOverview = node('div', 'decision-score-overview');
      var scoreFigure = node('div', 'decision-score-figure');
      scoreFigure.setAttribute('aria-label', finite(bottom.score) ? '底部条件综合分 ' + number(bottom.score) + ' 分，满分 100' : '底部条件分暂无可用数据');
      scoreFigure.append(node('strong', 'decision-score-number', number(bottom.score, 1)), node('span', 'decision-score-total', '/ 100'));
      var scoreContext = node('div', 'decision-score-context');
      scoreContext.append(node('p', 'decision-score-asof', bottom.asof ? '评分截至 ' + bottom.asof : '尚无对应日期的评分记录'));
      if (bottom.stale) scoreContext.append(pill('旧评分 · 待更新', 'amber'));
      if (finite(bottom.delta) && bottom.previousAsOf) {
        scoreContext.append(node('p', 'decision-score-delta', '较 ' + bottom.previousAsOf + ' ' + (bottom.delta > 0 ? '+' : '') + number(bottom.delta) + ' 分'));
      }
      scoreOverview.append(scoreFigure, scoreContext);
      scoreCard.append(scoreOverview);
      if (bottom.scheme) scoreCard.append(node('p', 'decision-scheme', bottom.scheme));
      var components = Array.isArray(bottom.components) ? bottom.components : [];
      if (components.length) {
        var componentGrid = node('div', 'decision-factors');
        components.forEach(function (component, index) {
          var item = node('section', 'decision-factor');
          item.dataset.factor = FACTORS.indexOf(component.id) >= 0 ? component.id : String(index % 4);
          item.dataset.coverage = finite(component.value) ? 'available' : 'missing';
          var line = node('div', 'decision-factor-heading');
          line.append(node('h4', '', component.label || component.id || '评分条件'));
          if (finite(component.weight)) line.append(node('span', 'decision-factor-weight', '权重 ' + pct(component.weight)));
          item.append(line);
          var bar = node('div', 'decision-factor-track');
          if (finite(component.value)) {
            var fraction = Math.max(0, Math.min(1, component.value));
            bar.setAttribute('role', 'meter');
            bar.setAttribute('aria-label', text(component.label || component.id || '评分条件'));
            bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100');
            bar.setAttribute('aria-valuenow', number(fraction * 100));
            bar.setAttribute('aria-valuetext', '本项条件值 ' + pct(component.value));
            var fill = node('span', 'decision-factor-fill');
            fill.style.width = String(fraction * 100) + '%';
            bar.append(fill);
          } else bar.setAttribute('aria-label', text(component.label || component.id || '评分条件') + '未覆盖');
          var foot = node('div', 'decision-factor-foot');
          foot.append(node('strong', 'decision-factor-value', finite(component.value) ? pct(component.value) : '未覆盖'));
          if (component.detail) foot.append(node('span', '', component.detail));
          item.append(bar, foot); componentGrid.append(item);
        });
        scoreCard.append(componentGrid);
      } else {
        var empty = node('div', 'decision-empty');
        empty.append(node('strong', '', '等待可追溯的评分记录'), node('p', '', '行情与顶部区间仍可查看。此处会保留明确的数据状态。'));
        scoreCard.append(empty);
      }
      grid.append(scoreCard);

      var contextStack = node('div', 'decision-context-stack');
      var topCard = node('article', 'decision-top-card');
      topCard.dataset.tone = tone(top.tone);
      var topHeader = node('div', 'decision-card-heading');
      topHeader.append(node('h3', 'decision-card-title', '顶部时间区间'), pill(top.label || '等待研究结果', top.tone));
      topCard.append(topHeader);
      var windows = Array.isArray(top.windows) ? top.windows : [];
      if (windows.length) {
        var windowList = node('ul', 'decision-windows');
        windows.forEach(function (band) {
          var row = node('li', 'decision-window');
          if (band.scale) row.append(node('span', 'decision-window-scale', SCALES[band.scale] || band.scale));
          row.append(node('strong', 'decision-window-dates', text(band.q20_date) + ' — ' + text(band.q80_date)));
          windowList.append(row);
        });
        topCard.append(windowList);
      }
      var otherWindows = Array.isArray(top.otherWindows) ? top.otherWindows : [];
      if (otherWindows.length) {
        topCard.append(node('p', 'decision-other-heading', '其他尺度的区间'));
        var otherList = node('ul', 'decision-windows decision-other-windows');
        otherWindows.forEach(function (band) {
          var row = node('li', 'decision-window');
          row.append(node('span', 'decision-window-scale', '其他尺度 · ' + (SCALES[band.scale] || band.scale || '未标注')));
          row.append(node('strong', 'decision-window-dates', text(band.q20_date) + ' — ' + text(band.q80_date)));
          otherList.append(row);
        });
        topCard.append(otherList, node('p', 'decision-other-note', '切换到对应尺度后，可在 K 线上查看这些区间。'));
      }
      if (top.detail) topCard.append(node('p', 'decision-top-detail', top.detail));
      contextStack.append(topCard);

      var checks = node('article', 'decision-check-card');
      var blockers = Array.isArray(conclusion.blockers) ? conclusion.blockers.filter(Boolean) : [];
      checks.append(node('h3', 'decision-card-title', blockers.length ? '尚需确认' : '条件核对'));
      if (cooling.detail) {
        var coolingLine = node('div', 'decision-cooling');
        var coolingTone = cooling.light === 'yellow' ? 'amber' : tone(cooling.light);
        coolingLine.append(pill('冲击与止跌', coolingTone), node('p', '', cooling.detail));
        checks.append(coolingLine);
      }
      if (blockers.length) {
        var list = node('ul', 'decision-checks');
        blockers.forEach(function (message) { list.append(node('li', '', message)); });
        checks.append(list);
      } else if (!cooling.detail) checks.append(node('p', 'decision-check-empty', '详细条件随当前标的的研究记录展示。'));
      contextStack.append(checks); grid.append(contextStack); wrapper.append(grid);

      if (provenance.historyStatus === 'error') {
        var historyError = node('div', 'decision-history-error');
        historyError.setAttribute('role', 'status');
        var errorCopy = node('div', 'decision-history-error-copy');
        errorCopy.append(node('strong', '', '评分历史暂未读到'), node('p', '', provenance.historyError || '本次读取没有完成，已有行情与结果仍可查看。'));
        historyError.append(errorCopy);
        if (typeof options.onRetry === 'function') {
          var retry = node('button', 'decision-retry', '重试评分记录');
          retry.type = 'button';
          retry.addEventListener('click', function () {
            try { options.onRetry(); }
            catch (error) { errorCopy.querySelector('p').textContent = error && error.message || '本次重试未完成，可继续查看已有结果。'; }
          });
          historyError.append(retry);
        }
        wrapper.append(historyError);
      }

      var disclosure = node('div', 'decision-disclosures');
      var stats = bottom.summary;
      if (stats) {
        var statistics = details('statistics', stats.label || '查看历史样本表现', opened.has('statistics'));
        var statsBody = node('div', 'decision-details-body');
        var numbers = node('dl', 'decision-stats');
        definition(numbers, '成熟的 50 周样本', finite(stats.n) ? number(stats.n, 0) + ' 个' : null);
        definition(numbers, '全部历史事件', finite(stats.nEvents) ? number(stats.nEvents, 0) + ' 个' : null);
        definition(numbers, '50 周后上涨比例', finite(stats.winRate50w) ? pct(stats.winRate50w) : null);
        definition(numbers, '同期基线比例', finite(stats.baselineWinRate50w) ? pct(stats.baselineWinRate50w) : null);
        definition(numbers, '50 周收益中位数', finite(stats.medianReturn50w) ? pct(stats.medianReturn50w, true) : null);
        definition(numbers, '途中再回撤中位数', finite(stats.medianDrawdown50w) ? pct(stats.medianDrawdown50w, true) : null);
        statsBody.append(numbers);
        if (stats.detail) statsBody.append(node('p', 'decision-stats-note', stats.detail));
        statistics.append(statsBody); disclosure.append(statistics);
      }
      var source = details('source', '数据日期、来源与口径', opened.has('source'));
      var sourceBody = node('div', 'decision-details-body');
      var sourceList = node('dl', 'decision-source');
      definition(sourceList, '标的', view.symbol);
      definition(sourceList, '行情截至', provenance.marketAsOf);
      definition(sourceList, '模型截至', provenance.modelAsOf || view.asof);
      definition(sourceList, '评分截至', provenance.scoreAsOf || bottom.asof);
      definition(sourceList, '模型版本', provenance.modelVersion);
      definition(sourceList, '首次可见', provenance.firstVisibleAt || '尚未记录');
      definition(sourceList, '行情 / 模型来源', provenance.dataSource);
      definition(sourceList, '评分来源', provenance.scoreSource);
      sourceBody.append(sourceList);
      if (evidence.detail) sourceBody.append(node('p', 'decision-stats-note', evidence.detail));
      if (view.historical) sourceBody.append(node('p', 'decision-history-note', '当前显示所选截止日的记录，后来行情不会改变本页判断。'));
      source.append(sourceBody); disclosure.append(source); wrapper.append(disclosure);
      container.replaceChildren(wrapper);
      container.hidden = false;
    }
    return { render: render, destroy: function () { container.replaceChildren(); container.classList.remove('decision-panel-host'); } };
  }
  return { mount: mount };
});
