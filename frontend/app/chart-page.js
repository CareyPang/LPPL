(function (root) {
  'use strict';

  var LPPL = root.LPPL;
  var Core = root.LPPLChartPageCore;
  var Clusters = root.CPTopClusters;
  var RuleLabels = root.RuleLabels;
  var Reader = root.LPPLChartReadOnly;
  var Share = root.LPPLChartResearchCard;
  var page = document.getElementById('chart-page');
  if (!LPPL || !Core || !page) return;

  var el = function (id) { return document.getElementById(id); };
  var context = Core.parseContext(root.location.search, LPPL.SYMS || []);
  var chart = null;
  var drawing = null;
  var current = null;
  var sequence = 0;
  var activeMarket = null;
  var activeModel = null;
  var activeEvents = [];
  var modelStatus = 'loading';
  var modelError = null;
  var modelRequest = 0;
  var eventRequest = 0;
  var scales = Core.SCALES;
  var scaleLabels = {
    '2-4w': '2–4 周', '1-3m': '1–3 个月', '3-6m': '3–6 个月',
    '6-12m': '6–12 个月', '12-24m': '12–24 个月', '2-6y': '2–6 年',
  };

  function evidenceCode(data, scale) {
    return Core.evidenceFor(data, scale);
  }

  function evidenceFor(data, scale) {
    if (data.modelStatus && data.modelStatus !== 'ok') return { code: 'none', label: '模型未就绪', show: false };
    var result = LPPL.ev(evidenceCode(data, scale), data.evidence_levels || {});
    if (result.code === 'research_candidate') result.label = '研究候选（非正式提醒）';
    return Object.assign({}, result, { show: !!result && Core.NUMERIC_EVIDENCE.has(result.code) });
  }

  function chartPayload(data) {
    if (data.assetType === 'stock' && data.modelStatus !== 'ok') {
      return Object.assign({}, data, { top: {} });
    }
    var top = Object.assign({}, data.top || {});
    var visible = new Set();
    var evidenceCodes = {};
    scales.forEach(function (scale) {
      var evidence = evidenceFor(data, scale);
      evidenceCodes[scale] = evidence && evidence.code;
      if (evidence && evidence.show) visible.add(scale);
    });
    if (Array.isArray(top.scale_windows)) {
      top.scale_windows = top.scale_windows.filter(function (item) {
        return visible.has(item.scale);
      });
    }
    ['scale_clusters', 'clusters'].forEach(function (key) {
      var clusters = top[key];
      if (Array.isArray(clusters)) {
        top[key] = clusters.filter(function (item) { return visible.has(item.scale); });
      } else if (clusters && typeof clusters === 'object') {
        top[key] = Object.assign({}, clusters);
        Object.keys(top[key]).forEach(function (scale) {
          if (scales.indexOf(scale) >= 0 && !visible.has(scale)) delete top[key][scale];
        });
      }
    });
    top = Core.filterDescriptiveBands(top, evidenceCodes);
    return Object.assign({}, data, { top: top });
  }

  function intervalRows(data, scale) {
    var top = data.top || {};
    var clusters = Clusters.forScale(top, scale);
    if (clusters !== null) return clusters;
    var window = (top.scale_windows || []).find(function (item) { return item.scale === scale; });
    return window && window.q20_date && window.q80_date
      ? [Object.assign({ rank: 'main', source: 'scale_window' }, window)] : [];
  }

  function dateRange(band) {
    return String(band.q20_date || '—') + '–' + String(band.q80_date || '—');
  }

  function renderEvidence(data, selectedScale) {
    var state = el('evidence-state');
    var ruleSource = el('evidence-rule-source');
    var list = el('interval-list');
    var note = el('evidence-note');
    list.replaceChildren();
    note.replaceChildren();
    ruleSource.hidden = true;
    ruleSource.textContent = '';
    if (data.modelStatus && data.modelStatus !== 'ok') {
      state.textContent = data.modelStatus === 'loading' ? '行情可先浏览，模型结果独立读取中…' : data.modelStatus === 'error'
        ? '模型结果读取失败：' + (data.modelMessage || '未知错误')
        : '没有读到已发布的模型结果（可能尚未发布，或读取失败）';
      var retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'retry-button evidence-retry-button';
      retry.textContent = '重试读取';
      retry.addEventListener('click', function () { void loadModel(sequence); });
      note.appendChild(retry);
      var action = document.createElement('a');
      action.href = context.assetType === 'stock' ? 'stock.html?code=' + encodeURIComponent(context.stockCode) : context.from;
      action.textContent = '回标的页发起计算';
      note.appendChild(action);
      return;
    }
    ruleSource.hidden = false;
    ruleSource.textContent = RuleLabels.RULES.box.source;
    var evidence = evidenceFor(data, selectedScale);
    var bands = intervalRows(data, selectedScale);
    state.textContent = '证据：' + (evidence && evidence.label || '证据状态未记录');
    if (!evidence || !evidence.show) {
      // Keep main's four explicit reason labels, but missing fields alone do not
      // prove that an archived scale was never computed.
      var hiddenIndicator = data.top && data.top.indicators && data.top.indicators[selectedScale];
      var hiddenReason = bands.length ? 'not_formal' : hiddenIndicator && RuleLabels.emptyReason(data.top, selectedScale, false, false);
      state.textContent = RuleLabels.reasonText(hiddenReason) || state.textContent;
      note.textContent = '当前证据不允许显示区间数值。';
      return;
    }
    if (!bands.length) {
      var indicator = data.top && data.top.indicators && data.top.indicators[selectedScale];
      var signal = indicator && (indicator.empty_reason || indicator.signal_status) || data.top && data.top.signal_status;
      var emptyReason = signal === 'no_qualified_fit' ? 'no_fit' :
        signal === 'not_computed' ? 'not_computed' : indicator && RuleLabels.emptyReason(data.top, selectedScale, false, true);
      state.textContent = RuleLabels.reasonText(emptyReason) || '当前尺度未提供可核对区间';
      note.textContent = '没有区间不等于没有风险；可切换尺度，或在标的页检查拟合及过滤明细。';
      return;
    }
    bands.forEach(function (band, index) {
      var policy = Core.bandEvidencePolicy(evidence.code, band);
      var bandEvidence = Core.bandEvidenceCode(evidence.code, band);
      var id = policy.draw
        ? Core.intervalId(selectedScale, band) : 'unrecorded:' + selectedScale + ':' + index;
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'interval-row';
      row.dataset.bandId = id;
      row.dataset.scale = selectedScale;
      row.setAttribute('aria-pressed', String(context.focus === id));
      var title = document.createElement('strong');
      title.textContent = band.source === 'scale_window'
        ? '已发布区间' : Clusters.label(band) || (index ? '次级簇' : '主簇');
      row.disabled = !policy.draw;
      row.appendChild(title);
      if (policy.showDates) {
        var dates = document.createElement('span');
        dates.textContent = dateRange(band);
        row.appendChild(dates);
      }
      var share = policy.showShare ? Clusters.shareText(band) : '';
      var extra = document.createElement('small');
      if (!policy.draw) {
        extra.textContent = policy.message;
      } else if (bandEvidence === 'descriptive') {
        extra.textContent = (share ? share + '；' : '') + 'n=' + band.n + '；历史分位，不是预测';
      } else if (bandEvidence === 'research_candidate') {
        extra.textContent = (share ? share + '；' : '') + '研究候选区间，非正式提醒；占比不是概率';
      } else if (band.source === 'scale_window') {
        extra.textContent = '发布的时间窗，不代表概率';
      } else {
        extra.textContent = share ? share + '；不是概率' : '不是概率';
      }
      row.appendChild(extra);
      row.addEventListener('click', function () {
        selectScale(selectedScale, true);
        context.focus = id;
        chart.focusBand(Object.assign({}, band, { scale: selectedScale, id: id }));
        updateAddress(selectedScale, id);
        renderEvidence(current, selectedScale);
      });
      list.appendChild(row);
    });
    note.textContent = Clusters.NOTE || '区间占比不是概率。';
  }

  function updateAddress(scale, focus) {
    var params = new URLSearchParams(root.location.search);
    params.set('scale', scale);
    if (focus) params.set('focus', focus);
    else params.delete('focus');
    root.history.replaceState(null, '', root.location.pathname + '?' + params.toString());
  }

  function selectScale(scale, preserveFocus) {
    context.scale = scale;
    scales.forEach(function (value) {
      var button = document.querySelector('[data-scale="' + value + '"]');
      button.setAttribute('aria-pressed', String(value === scale));
    });
    if (chart) chart.setScale(scale);
    if (!preserveFocus) {
      context.focus = '';
      updateAddress(scale, '');
    }
    if (current) renderEvidence(current, scale);
  }

  function setText(id, value) {
    el(id).textContent = String(value == null || value === '' ? '未记录' : value);
  }

  function drawHeader(data) {
    setText('asset-name', data.name);
    setText('asset-code', data.symbol);
    setText('asset-exchange', data.exchange);
    setText('asset-type', data.assetType === 'index' ? '指数 · 指数点位' : 'A 股 · CNY · 元');
    setText('trading-status', '交易状态：' + (data.tradingStatus === '未记录' ? '未知（源未提供）' : data.tradingStatus));
    setText('identity-strip-name', data.name);
    setText('identity-strip-code', data.symbol);
    setText('identity-strip-meta', data.exchange + ' · ' + data.quoteUnit + ' · 交易状态：' +
      (data.tradingStatus === '未记录' ? '未知（源未提供）' : data.tradingStatus));
    updateIdentityStrip();
    setText('model-date', '模型日期 ' +
      (data.modelStatus === 'loading' ? '读取中' : data.modelStatus !== 'ok' ? '未读到' : data.modelAsOf || '未记录'));
    var asofTag = el('asof-tag');
    asofTag.hidden = !context.asof;
    asofTag.textContent = context.asof
      ? '历史截止日 ' + context.asof + ' · 封存回放' : '';
    if (data.assetType === 'stock') {
      setText('market-date', '行情日期 ' + (data.marketAsOf || '未记录'));
      setText('data-source', data.dataSource + ' · ' +
        (data.adjustment === 'none' ? '未复权' : data.adjustment));
    } else {
      setText('market-date', '行情日期 ' + (data.marketAsOf || '未记录'));
      setText('data-source', data.dataSource + ' · ' + data.adjustment);
    }
    setText('model-version', data.modelVersion || '未记录');
    setText('prediction-id', data.predictionId || '未记录');
    setText('volume-unit', data.volumeUnit === 'vendor_native' ? '供应商原始单位，股/手换算未核验' : data.volumeUnit);
    setText('model-adjustment', data.modelAdjustment + '；显示设置不改变模型输入');
    setText('first-visible', data.firstVisibleAt || '未记录；本次读取不作为提前发布证明');
    setText('stale-state', data.stale ? '已过期：' + (data.staleReason || '来源未说明原因') :
      data.freshness === 'not_established' ? '行情新鲜度未核验' : '按已发布截止日查看；不代表实时行情');
    el('index-replay').hidden = data.assetType !== 'index';
    el('index-replay').href = 'index.html?code=' + encodeURIComponent(data.symbol) +
      (data.assetType === 'index' && context.asof ? '&asof=' + encodeURIComponent(context.asof) : '');
  }

  function renderAsofNotice(data) {
    var notice = el('asof-notice');
    var visible = !!context.asof;
    notice.hidden = !visible;
    notice.textContent = visible
      ? (data.historyFallback ? '使用精确日期的历史封存帧；价格截自当前已发布历史行情，其修订时点未记录。' : '只读查看此日期的封存结果。') +
        '历史重放与真实提前发布分开；未记录首次可见时间时，不声称当时已发布。'
      : '';
  }

  function renderCalendarNotice(data) {
    var bands = LPPLChart.bandsForAllScales(chartPayload(data));
    var last = data.bars[data.bars.length - 1];
    var lastDate = last && (last.date || last.time);
    var missing = LPPLChart.needsCalendarCoverage(bands, lastDate, data.future_calendar);
    el('calendar-notice').hidden = !missing;
  }

  function findEvent(data, focus) {
    var events = data && data.eventRows || [];
    return events.find(function (event) { return event.id === focus; }) || null;
  }

  function moduleState(id, text) { el(id).textContent = text; }

  function present(data, preserveView) {
    var view = preserveView && chart.getVisibleRange ? chart.getVisibleRange() : null;
    current = data;
    var lastBar = data.bars[data.bars.length - 1] || {};
    page.dataset.code = data.symbol;
    page.dataset.barCount = String(data.bars.length);
    page.dataset.lastBarDate = String(lastBar.date || lastBar.time || '');
    page.dataset.lastClose = String(lastBar.close == null ? '' : lastBar.close);
    page.dataset.modelAsOf = String(data.modelAsOf || '');
    page.dataset.marketAsOf = String(data.marketAsOf || '');
    page.dataset.modelStatus = String(data.modelStatus || '');
    var displayMode = LPPLChart.priceMode(data.bars);
    page.dataset.priceMode = displayMode;
    el('price-mode-note').textContent = displayMode === 'close'
      ? 'OHLC 未完整提供：当前显示真实收盘线，不补造 K 线。成交量保留来源原值。'
      : '日线 K 线与成交量；模型时间区间使用蓝色，截止日使用灰色。';
    drawHeader(data);
    if (drawing) drawing.setContext({ symbol: data.symbol || context.code, asof: context.asof || '' });
    chart.setData(chartPayload(data));
    if (data.asof) chart.setAsof(data.asof);
    renderEvidence(data, context.scale);
    renderCalendarNotice(data);
    renderAsofNotice(data);
    if (view && chart.setVisibleRange) chart.setVisibleRange(view);
    else applyInitialFocus(data);
    el('loading').hidden = true;
    el('share-card').disabled = false;
    el('share-screenshot').disabled = false;
    page.dataset.loaded = 'true';
  }

  function presentStock() {
    if (!activeMarket) return;
    var data = Core.assembleStockData(context.code, activeModel, activeMarket, null, modelError);
    if (data.modelStatus !== 'error') data.modelStatus = modelStatus;
    else moduleState('model-status', '模型读取失败；行情仍可用');
    data.eventRows = activeEvents;
    data.events = activeEvents;
    present(data, !!current);
  }

  async function loadMarket(request) {
    moduleState('market-status', '行情读取中');
    try {
      var market = await Reader.timed(function () { return LPPL.stock.market(context.stockCode); }, '行情');
      if (request !== sequence) return;
      Core.assembleStockData(context.code, null, market, null);
      activeMarket = market;
      moduleState('market-status', market.stale ? '行情：过期缓存可浏览' : '行情已就绪');
      el('error-panel').hidden = true;
      presentStock();
    } catch (error) {
      if (request !== sequence) return;
      moduleState('market-status', '行情读取失败');
      showError(error);
    }
  }

  async function loadModel(request) {
    if (context.asof || context.assetType === 'index') return load();
    var run = ++modelRequest;
    modelStatus = 'loading'; modelError = null;
    moduleState('model-status', '模型独立读取中');
    if (current) renderEvidence(Object.assign({}, current, { modelStatus: 'loading' }), context.scale);
    try {
      var model = await Reader.timed(function () { return LPPL.stock.latest(context.stockCode); }, '模型');
      if (request !== sequence || run !== modelRequest) return;
      activeModel = model;
      modelStatus = model ? 'ok' : 'missing';
      moduleState('model-status', model ? '模型已读取' : '模型尚未读到');
    } catch (error) {
      if (request !== sequence || run !== modelRequest) return;
      modelStatus = 'error'; modelError = error;
      moduleState('model-status', '模型读取失败；行情仍可用');
    }
    presentStock();
  }

  function renderEvents(result) {
    var list = el('event-list'); list.replaceChildren();
    result.rows.slice(0, 20).forEach(function (event) {
      var button = document.createElement('button');
      button.type = 'button'; button.className = 'event-row';
      button.textContent = event.date + ' · ' + event.label + ' · 来源 ' + event.source +
        ' · 发布时间 ' + (event.knownAt || '未记录');
      button.addEventListener('click', function () {
        if (chart) chart.focusDate(event.date, event.id);
        context.focus = event.id; updateAddress(context.scale, event.id);
      });
      list.appendChild(button);
    });
    el('events-note').textContent = result.excluded ? '历史视图排除了 ' + result.excluded + ' 条未证明在截止日已知的事件。' :
      result.rows.length ? '事件来源与时间分别保留；未知发布时间不作为当时已知的证据。' : '没有读到可展示事件，不等于该标的没有事件。';
  }

  async function loadEvents(request) {
    var run = ++eventRequest;
    if (context.assetType !== 'stock') {
      el('events-note').textContent = '当前数据入口未提供指数事件；没有将个股事件套用到指数。';
      el('events-retry').disabled = true;
      moduleState('events-status', '指数事件接口未提供'); return;
    }
    moduleState('events-status', '事件独立读取中');
    try {
      var payload = await Reader.timed(function () { return LPPL.events(); }, '事件');
      if (request !== sequence || run !== eventRequest) return;
      var result = Reader.eventsFor(payload, context.stockCode, context.asof);
      activeEvents = result.rows;
      moduleState('events-status', payload ? '事件已读取' : '事件快照未读到');
      renderEvents(result);
      if (current) {
        current.eventRows = activeEvents; current.events = activeEvents;
        present(current, true);
        var focused = findEvent(current, context.focus);
        if (focused) chart.focusDate(focused.date, focused.id);
      }
    } catch (error) {
      if (request !== sequence || run !== eventRequest) return;
      moduleState('events-status', '事件读取失败；行情仍可用');
      el('events-note').textContent = error.message;
    }
  }

  function applyInitialFocus(data) {
    if (!context.focus) return;
    for (var i = 0; i < scales.length; i += 1) {
      var scale = scales[i];
      var rows = intervalRows(chartPayload(data), scale);
      for (var j = 0; j < rows.length; j += 1) {
        var id = Core.intervalId(scale, rows[j]);
        if (id === context.focus) {
          selectScale(scale, true);
          chart.focusBand(Object.assign({}, rows[j], { scale: scale, id: id }));
          renderEvidence(data, scale);
          return;
        }
      }
    }
    var event = findEvent(data, context.focus);
    if (event && event.date) chart.focusDate(event.date, event.id);
  }

  function sameOriginReturn() {
    if (!document.referrer) return false;
    try {
      var referrer = new URL(document.referrer);
      var relative = referrer.pathname.split('/').pop() + referrer.search;
      return referrer.origin === root.location.origin && relative === context.from;
    } catch (_) { return false; }
  }

  el('return-link').href = context.from;
  el('return-link').addEventListener('click', function (event) {
    if (sameOriginReturn()) {
      event.preventDefault();
      root.history.back();
    }
  });

  scales.forEach(function (scale) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'scale-button';
    button.dataset.scale = scale;
    button.setAttribute('aria-pressed', String(scale === context.scale));
    button.textContent = scaleLabels[scale];
    button.addEventListener('click', function () { selectScale(scale, false); });
    el('scale-selector').appendChild(button);
  });

  el('retry-button').addEventListener('click', function () { void load(); });
  el('events-retry').addEventListener('click', function () { void loadEvents(sequence); });

  var drawer = el('evidence-panel');
  var identityStrip = el('identity-strip');
  var identityFrame = 0;
  function updateIdentityStrip() {
    if (!identityStrip) return;
    var anchor = page.querySelector('.asset-line');
    var nav = document.querySelector('.odn');
    var navBottom = nav ? Math.max(0, Math.min(160, nav.getBoundingClientRect().bottom)) : 0;
    var bounds = page.getBoundingClientRect();
    identityStrip.hidden = !current || !anchor || anchor.getBoundingClientRect().bottom > navBottom;
    identityStrip.style.top = (navBottom + 8) + 'px';
    identityStrip.style.left = Math.max(12, bounds.left + 20) + 'px';
    identityStrip.style.width = Math.max(280, Math.min(780, bounds.width - 40)) + 'px';
  }
  function scheduleIdentityStrip() {
    if (identityFrame) return;
    identityFrame = root.requestAnimationFrame(function () { identityFrame = 0; updateIdentityStrip(); });
  }
  root.addEventListener('scroll', scheduleIdentityStrip, { passive: true });
  root.addEventListener('resize', scheduleIdentityStrip, { passive: true });
  if (root.ResizeObserver) new root.ResizeObserver(scheduleIdentityStrip).observe(page);
  var evidenceToggle = el('evidence-toggle');
  var mobile = root.matchMedia('(max-width:600px)');
  function evidenceOpen(open) {
    drawer.hidden = !open;
    evidenceToggle.setAttribute('aria-expanded', String(open));
    evidenceToggle.textContent = open ? '收起证据' : '查看区间与证据';
    drawer.setAttribute('role', open && mobile.matches ? 'dialog' : 'complementary');
    if (open && mobile.matches) drawer.setAttribute('aria-modal', 'true');
    else drawer.removeAttribute('aria-modal');
    document.body.classList.toggle('chart-modal-lock', open && mobile.matches);
    if (open && mobile.matches) el('evidence-close').focus();
    if (!open) evidenceToggle.focus({ preventScroll: true });
  }
  drawer.hidden = mobile.matches;
  evidenceToggle.setAttribute('aria-expanded', String(!drawer.hidden));
  evidenceToggle.textContent = drawer.hidden ? '查看区间与证据' : '收起证据';
  evidenceToggle.addEventListener('click', function () { evidenceOpen(drawer.hidden); });
  el('evidence-close').addEventListener('click', function () { evidenceOpen(false); });
  drawer.addEventListener('keydown', function (event) {
    if (!mobile.matches || drawer.hidden || event.key !== 'Tab') return;
    var targets = Array.from(drawer.querySelectorAll('button:not(:disabled),a[href]')).filter(function (node) { return !node.hidden; });
    var first = targets[0], last = targets[targets.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  mobile.addEventListener('change', function () { evidenceOpen(!mobile.matches); });

  var fullscreenCard = el('chart-card');
  function fullscreenState(active) {
    el('fullscreen-exit').hidden = !active;
    el('chart-fullscreen').setAttribute('aria-pressed', String(active));
    el('chart-fullscreen').textContent = active ? '退出全屏' : '全屏图表';
    if (active) el('fullscreen-exit').focus();
    else el('chart-fullscreen').focus({ preventScroll: true });
  }
  async function exitFullscreen() {
    if (document.fullscreenElement) await document.exitFullscreen();
    fullscreenCard.classList.remove('chart-expanded'); fullscreenState(false);
  }
  el('chart-fullscreen').addEventListener('click', async function () {
    if (document.fullscreenElement || fullscreenCard.classList.contains('chart-expanded')) return exitFullscreen();
    try {
      if (!fullscreenCard.requestFullscreen) throw new Error('fullscreen unavailable');
      await fullscreenCard.requestFullscreen();
    } catch (_) { fullscreenCard.classList.add('chart-expanded'); }
    fullscreenState(true);
  });
  el('fullscreen-exit').addEventListener('click', function () { void exitFullscreen(); });
  document.addEventListener('fullscreenchange', function () { fullscreenState(!!document.fullscreenElement); });
  document.addEventListener('keydown', function (event) {
    var targetTag = event.target && event.target.tagName;
    if (event.key !== 'Escape' || event.isComposing || event.keyCode === 229 ||
        targetTag === 'INPUT' || targetTag === 'TEXTAREA') return;
    if (fullscreenCard.classList.contains('chart-expanded')) { void exitFullscreen(); return; }
    if (!drawer.hidden && mobile.matches) evidenceOpen(false);
  });

  function researchCard() {
    return Share.record(current, context, evidenceFor(current, context.scale), intervalRows(current, context.scale), Core.bandEvidencePolicy, Core.bandEvidenceCode);
  }
  function download(blob, suffix) {
    var url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'LPPL-' + current.symbol + '-' + (current.modelAsOf || current.marketAsOf || 'undated') + suffix;
    document.body.appendChild(link); link.click(); link.remove();
    root.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  el('share-card').addEventListener('click', function () {
    if (!current) return;
    download(new Blob([Share.svg(researchCard())], { type: 'image/svg+xml;charset=utf-8' }), '-research.svg');
    el('action-feedback').textContent = '匿名研究卡已下载，含来源、截止日、模型版本和证据；不含自选、笔记或持仓。';
  });
  el('share-screenshot').addEventListener('click', async function () {
    if (!current || !chart) return;
    var includeDrawings = el('include-drawings').checked;
    var restoreDrawings = drawing && drawing.drawingsVisible();
    try {
      if (drawing) drawing.setVisibleForScreenshot(includeDrawings);
      if (drawing) await new Promise(function (resolve) {
        requestAnimationFrame(function () { requestAnimationFrame(resolve); });
      });
      var shot = chart.takeScreenshot(includeDrawings);
      if (includeDrawings && drawing) drawing.composeScreenshot(shot);
      var lines = Share.lines(researchCard());
      var width = Math.max(1280, shot.width), header = 100 + lines.length * 38;
      var canvas = document.createElement('canvas'); canvas.width = width; canvas.height = header + shot.height;
      var ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#172033'; ctx.font = '24px Microsoft YaHei, sans-serif';
      ctx.fillText(includeDrawings ? 'LPPL · 研究截图（含个人标注）' : 'LPPL · 匿名研究截图', 32, 45);
      ctx.font = '17px Microsoft YaHei, sans-serif';
      lines.forEach(function (line, i) { ctx.fillText(line, 32, 90 + 38 * i, width - 64); });
      ctx.drawImage(shot, 0, header);
      var blob = await new Promise(function (resolve) { canvas.toBlob(resolve, 'image/png'); });
      if (!blob) throw new Error('图片编码失败');
      download(blob, '-chart.png');
      el('action-feedback').textContent = includeDrawings
        ? '当前图表与证据截图已下载，包含你选择的个人标注。'
        : '当前图表与证据截图已下载；不含私人研究资料。';
    } catch (error) { el('action-feedback').textContent = '截图未完成：' + error.message + '。可使用匿名研究卡。'; }
    finally {
      if (drawing) {
        drawing.setVisibleForScreenshot(restoreDrawings);
        await new Promise(function (resolve) {
          requestAnimationFrame(function () { requestAnimationFrame(resolve); });
        });
      }
    }
  });

  function latestResultsHref() {
    var params = new URLSearchParams(root.location.search);
    params.delete('asof');
    var query = params.toString();
    return root.location.pathname + (query ? '?' + query : '') + root.location.hash;
  }

  function showError(error) {
    el('loading').hidden = true;
    el('error-message').textContent = error && error.pending ? error.message : '读取失败：' + (error && error.message || '未知错误');
    el('error-panel').hidden = false;
    el('retry-button').hidden = false;
    var latestLink = el('latest-results-link');
    latestLink.hidden = !context.asof;
    latestLink.href = latestResultsHref();
  }

  async function load() {
    var request = ++sequence;
    if (drawing) drawing.setContext({ symbol: current && current.symbol || context.code, asof: context.asof || '' });
    el('error-panel').hidden = true;
    el('loading').hidden = !!current;
    if (!context.valid) { showError(new Error(context.invalidReason || '缺少有效的指数或 A 股代码。')); return; }
    if (!context.asof && context.assetType === 'stock') {
      void loadMarket(request); void loadModel(request); void loadEvents(request);
      return;
    }
    moduleState('market-status', context.asof ? '读取封存行情' : '指数行情读取中');
    moduleState('model-status', context.asof ? '只读核对历史截止日' : '指数模型读取中');
    void loadEvents(request);
    try {
      var result = context.asof ? await Reader.historical(LPPL, context) :
        await Reader.timed(function () { return LPPL.load(context.code); }, '指数数据');
      if (request !== sequence) return;
      var data;
      if (context.assetType === 'stock') {
        var market = Object.assign({}, result.market, { price: result.bars, asof: context.asof, cutoff: context.asof });
        data = Core.assembleStockData(context.code, result.raw, market, null);
      } else data = Core.assembleIndexData(context.code, result);
      data.historyFallback = !!result.historyFallback;
      data.eventRows = activeEvents; data.events = activeEvents;
      data.marketAsOf = data.bars.length ? data.bars[data.bars.length - 1].date : '';
      moduleState('market-status', '行情已就绪');
      moduleState('model-status', context.asof ? '精确截止日封存已读取' : '模型已读取');
      present(data, !!current);
    } catch (error) {
      if (request !== sequence) return;
      moduleState('model-status', context.asof ? '该日封存未就绪；未触发计算' : '指数数据读取失败');
      showError(error);
    }
  }

  try {
    chart = LPPLChart.mount(el('chart-host'), { height: 520 });
    chart.setScale(context.scale);
    drawing = root.ChartDrawing.attach(chart, { symbol: context.code, asof: context.asof });
    chart.on('scale', function (scale) {
      if (scale !== context.scale) context.scale = scale;
    });
    void load();
  } catch (error) {
    el('loading').hidden = true;
    el('error-message').textContent = '图表初始化失败：' + (error && error.message || '未知错误');
    el('error-panel').hidden = false;
    el('retry-button').hidden = false;
  }
  root.addEventListener('pagehide', function (event) {
    if (!event.persisted && drawing) { drawing.detach(); drawing = null; }
  });
})(window);
