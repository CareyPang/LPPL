(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLUnifiedTerminal = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  function datesFrom(history, extra) {
    return Array.from(new Set((history && history.frames || []).map(function (f) { return f.asof; })
      .concat(extra || []).filter(function (d) { return /^\d{4}-\d{2}-\d{2}$/.test(d || ''); }))).sort();
  }
  function neighbour(dates, date, step) {
    var eligible = dates.filter(function (d) { return step < 0 ? d < date : d > date; });
    return step < 0 ? eligible[eligible.length - 1] || '' : eligible[0] || '';
  }
  function href(context, changes) {
    var values = Object.assign({ code: context.code, kind: context.assetType, scale: context.scale,
      asof: context.asof, from: context.from, mode: context.asof ? 'replay' : 'diagnosis' }, changes);
    var p = new URLSearchParams();
    Object.keys(values).forEach(function (key) { if (values[key]) p.set(key, values[key]); });
    return 'chart.html?' + p.toString();
  }
  function summary(data, bands, historical) {
    var reference = historical || [data.modelAsOf, data.marketAsOf].filter(Boolean).sort().pop() || '';
    var prefix = historical ? '当时' : '截至 ' + (reference || '未记录日期') + ' · ';
    if (data.modelStatus !== 'ok') return { status: '行情可先查看', window: '模型尚未就绪',
      detail: '可以继续缩放和画线，模型状态见右侧证据。' };
    var future = bands.filter(function (b) { return b.q20_date && b.q80_date && b.q80_date >= reference; });
    var old = bands.filter(function (b) { return b.q80_date && b.q80_date < reference; });
    var stale = !historical && data.modelAsOf && data.marketAsOf && data.modelAsOf < data.marketAsOf;
    if (future.length) return {
      status: prefix + (stale ? '区间待更新核对' : '有候选顶部区间'),
      window: future.map(function (b) { return b.q20_date + ' — ' + b.q80_date; }).join(' / '),
      detail: stale ? '行情比模型更新，旧区间保留供核对。' : '重点观察区间内的价格变化；切换尺度可对照其他时间长度。',
    };
    return { status: prefix + (old.length ? '区间已过' : '没有可展示区间'), window: old.length ? '旧区间见证据列表' : '—',
      detail: old.length ? '这些是历史提醒，不再标作当前有效预警。' : '可切换尺度；拟合与证据状态在右侧分别说明。' };
  }
  function attach(options) {
    var doc = options.document, adapter = options.adapter, reader = options.reader, context = options.context;
    var el = function (id) { return doc.getElementById(id); };
    if (!el('terminal-context')) return { render: function () {} };
    var mode = new URLSearchParams(options.search).get('mode') === 'replay' || context.asof ? 'replay' : 'diagnosis';
    var dates = [], historyFailed = false, current = null, futureRun = 0, historyData = null, historyLimit = 12;
    el('terminal-context').hidden = false;
    function go(changes) { options.navigate(href(context, Object.assign({ mode: mode }, changes))); }
    function renderControls() {
      el('terminal-mode-diagnosis').setAttribute('aria-pressed', String(mode === 'diagnosis'));
      el('terminal-mode-replay').setAttribute('aria-pressed', String(mode === 'replay'));
      el('terminal-replay-controls').hidden = mode !== 'replay';
      el('terminal-replay-status').hidden = mode !== 'replay';
      var date = context.asof || current && current.modelAsOf || '';
      el('terminal-asof').value = date;
      el('terminal-asof').min = dates[0] || '';
      el('terminal-asof').max = dates[dates.length - 1] || date;
      el('terminal-prev').disabled = !neighbour(dates, date, -1);
      el('terminal-next').disabled = !neighbour(dates, date, 1);
      el('terminal-show-future').disabled = !context.asof || !current;
      el('terminal-replay-status').textContent = el('terminal-show-future').checked ? '后来行情已展开；模型与证据仍固定在 ' + context.asof + '。' : historyFailed ? '历史目录暂未读到，可重试页面；不会用最新模型替代历史。' :
        dates.length ? dates.length + ' 个已封存截止日 · 前后按钮只切换已有记录。历史重放不等于当时已公开发布。' :
        '尚未读到历史封存日期；不会自动启动回测。';
      renderHistory();
    }
    function renderHistory() {
      if (!el('terminal-history')) return;
      el('terminal-history').hidden = mode !== 'replay';
      el('terminal-backtest-link').href = 'backtest.html?code=' + encodeURIComponent(context.code);
      el('terminal-backtest-link').hidden = context.assetType !== 'index';
      var frames = (historyData && historyData.frames || []).filter(function (f) { return !context.asof || f.asof <= context.asof; })
        .slice().sort(function (a, b) { return b.asof.localeCompare(a.asof); });
      el('terminal-history-note').textContent = frames.length ? '按截止日封存，点击查看当时区间。首次可见时间单独记录，不把历史计算当作提前发布。' : '该标的尚未读到历史记录。';
      el('terminal-history-list').replaceChildren();
      frames.slice(0, historyLimit).forEach(function (frame) {
        var item = doc.createElement('a');
        item.href = href(context, { asof: frame.asof, mode: 'replay' });
        var date = doc.createElement('strong'); date.textContent = frame.asof; item.appendChild(date);
        var description = doc.createElement('span');
        var packed = reader.packedFrame(historyData, frame, context, [], context.name);
        var data = { raw: packed.raw, top: packed.top, assetType: context.assetType, modelStatus: 'ok' };
        var scaleEvidence = options.core.evidenceFor(data, context.scale);
        var clusters = packed.top.scale_clusters && packed.top.scale_clusters[context.scale];
        var windows = Array.isArray(clusters) ? clusters : (packed.top.scale_windows || []).filter(function (b) { return b.scale === context.scale; });
        var allowed = windows.filter(function (b) { return options.core.bandEvidencePolicy(scaleEvidence, b).showDates; });
        description.textContent = allowed.length ? allowed.map(function (b) { return b.q20_date + ' — ' + b.q80_date; }).join(' / ') : '查看拟合与证据状态';
        item.appendChild(description);
        var known = doc.createElement('small'); known.textContent = frame.first_visible_at ? '首次可见 ' + frame.first_visible_at : '首次可见时间未记录';
        item.appendChild(known); el('terminal-history-list').appendChild(item);
      });
      el('terminal-history-more').hidden = frames.length <= historyLimit;
    }
    function option(code, name, kind, group) {
      var existing = Array.from(el('terminal-asset').options).find(function (o) { return o.value === code; });
      if (existing) { existing.textContent = name + ' · ' + code; return; }
      var node = doc.createElement('option'); node.value = code; node.textContent = name + ' · ' + code;
      node.dataset.kind = kind; group.appendChild(node);
      if (code.toUpperCase() === String(context.assetType === 'stock' ? context.stockCode : context.code).toUpperCase()) el('terminal-asset').value = code;
    }
    function group(label) { var node = doc.createElement('optgroup'); node.label = label; el('terminal-asset').appendChild(node); return node; }
    el('terminal-asset').replaceChildren();
    var indices = group('A 股指数');
    (adapter.SYMS || []).forEach(function (item) { option(item.sym, item.name, 'index', indices); });
    var stocks = group('A 股已发布标的'), us = group('美股已发布观察清单');
    if (context.assetType === 'stock') option(context.stockCode, context.name || context.stockCode, 'stock', context.market === 'us' ? us : stocks);
    Promise.allSettled([adapter.stock.index(), adapter.stock.usIndex()]).then(function (results) {
      results.forEach(function (result, i) {
        if (result.status !== 'fulfilled') return;
        var payload = result.value, rows = Array.isArray(payload) ? payload : Object.keys(payload || {}).filter(function (key) {
          return /^\d{6}$/.test(key);
        }).map(function (key) { return Object.assign({ code: key }, payload[key]); });
        rows.forEach(function (item) {
          var code = i ? 'US_' + String(item.ticker || '').toUpperCase() : String(item.code || '');
          if (i ? /^US_[A-Z.]{1,6}$/.test(code) : /^\d{6}$/.test(code)) option(code, item.name || code, 'stock', i ? us : stocks);
        });
      });
    });
    el('terminal-asset').addEventListener('change', function () {
      var selected = el('terminal-asset').selectedOptions[0];
      // Keep the exact cutoff when switching assets; missing archives remain missing.
      go({ code: selected.value, kind: selected.dataset.kind });
    });
    el('terminal-mode-diagnosis').addEventListener('click', function () {
      if (context.asof) return go({ mode: 'diagnosis', asof: '' });
      mode = 'diagnosis'; renderControls(); options.replaceAddress({ mode: mode });
    });
    el('terminal-mode-replay').addEventListener('click', function () {
      mode = 'replay'; renderControls(); options.replaceAddress({ mode: mode });
    });
    el('terminal-asof').addEventListener('change', function () {
      if (el('terminal-asof').value) go({ asof: el('terminal-asof').value, mode: 'replay' });
    });
    [-1, 1].forEach(function (step) {
      el(step < 0 ? 'terminal-prev' : 'terminal-next').addEventListener('click', function () {
        var date = neighbour(dates, context.asof || current && current.modelAsOf || '', step);
        if (date) go({ asof: date, mode: 'replay' });
      });
    });
    el('terminal-latest').addEventListener('click', function () { go({ asof: '', mode: 'diagnosis' }); });
    if (el('terminal-history-more')) el('terminal-history-more').addEventListener('click', function () { historyLimit += 24; renderHistory(); });
    el('terminal-show-future').addEventListener('change', async function () {
      var run = ++futureRun, checkbox = el('terminal-show-future');
      if (!checkbox.checked) { options.showFuture(null); renderControls(); return; }
      checkbox.disabled = true;
      el('terminal-replay-status').textContent = '读取后来行情，历史模型和截止日保持不变…';
      try {
        var market = await reader.timed(function () {
          if (context.assetType === 'index') return adapter.load(context.code);
          if (context.market === 'us') return adapter.stock.latest(context.stockCode).then(function (raw) { return reader.marketFromPublished(raw, context.stockCode); });
          return adapter.stock.market(context.stockCode);
        }, '后来行情');
        if (run !== futureRun) return;
        var bars = context.assetType === 'index' ? options.core.assembleIndexData(context.code, market).bars :
          options.core.assembleStockData(context.code, null, market, null).bars;
        if (!bars || !bars.some(function (b) { return (b.date || b.time) > context.asof; })) throw Error('行情尚未覆盖截止日之后。');
        options.showFuture(bars);
        el('terminal-replay-status').textContent = '正在查看后来走势（当前行情版本）；模型、区间与证据仍固定在 ' + context.asof + '。';
      } catch (error) {
        checkbox.checked = false;
        el('terminal-replay-status').textContent = error.message + ' 原档仍可浏览。';
      } finally { if (run === futureRun) checkbox.disabled = false; }
    });
    renderControls();
    reader.timed(function () { return context.assetType === 'index' ? adapter.history(context.code) : adapter.stock.history(context.stockCode); }, '历史目录')
      .then(function (history) {
        var first = history && history.frames && history.frames[0];
        if (first && !reader.historyFrame(history, Object.assign({}, context, { asof: first.asof }))) throw Error('历史目录资产不匹配');
        historyData = history; dates = datesFrom(history, adapter.REPLAYS && adapter.REPLAYS[context.code]); renderControls();
      })
      .catch(function () { historyFailed = true; dates = datesFrom(null, adapter.REPLAYS && adapter.REPLAYS[context.code]); renderControls(); });
    return { render: function (data, bands) {
      current = data;
      var s = summary(data, bands, context.asof);
      el('terminal-alert-status').textContent = s.status;
      el('terminal-alert-window').textContent = s.window;
      el('terminal-alert-detail').textContent = s.detail;
      var cooling = data.raw && data.raw.cooling_state;
      el('terminal-aftershock').hidden = false;
      var omori = cooling && cooling.dashboard && (cooling.dashboard.dimensions || []).find(function (d) { return d.id === 'omori'; });
      el('terminal-omori').textContent = omori ? omori.value_text || omori.label || omori.status || '已发布余震状态' : '当前封存未提供';
      el('terminal-bath').textContent = '尚未接入真实拟合';
      el('terminal-productivity').textContent = '尚未接入真实拟合';
      el('terminal-aftershock-note').textContent = cooling ? (cooling.note || '已发布的冷却期与余震状态。') + ' · 启发式余震状态，尚非三定律参数拟合 · 数据截至 ' + data.modelAsOf : '三定律区预留真实接口；当前没有对应结果的项目保持空状态。';
      renderControls();
    } };
  }
  return { datesFrom: datesFrom, neighbour: neighbour, href: href, summary: summary, attach: attach };
});
