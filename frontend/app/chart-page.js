(function (root) {
  'use strict';

  var LPPL = root.LPPL;
  var Core = root.LPPLChartPageCore;
  var Clusters = root.CPTopClusters;
  var page = document.getElementById('chart-page');
  if (!LPPL || !Core || !page) return;

  var el = function (id) { return document.getElementById(id); };
  var context = Core.parseContext(root.location.search, LPPL.SYMS || []);
  var chart = null;
  var current = null;
  var sequence = 0;
  var scales = Core.SCALES;
  var scaleLabels = {
    '2-4w': '2–4 周', '1-3m': '1–3 个月', '3-6m': '3–6 个月',
    '6-12m': '6–12 个月', '12-24m': '12–24 个月', '2-6y': '2–6 年',
  };

  function evidenceCode(data, scale) {
    var top = data.top || {};
    var confidence = top.lppls_confidence || {};
    var indicators = top.indicators || {};
    var indicator = indicators[scale] || {};
    return confidence.scale_evidence && confidence.scale_evidence[scale] ||
      indicator.evidence || confidence.evidence || top.evidence ||
      data.raw && data.raw.evidence || data.evidence;
  }

  function evidenceFor(data, scale) {
    return LPPL.ev(evidenceCode(data, scale), data.evidence_levels || {});
  }

  function chartPayload(data) {
    var top = Object.assign({}, data.top || {});
    var visible = new Set(scales.filter(function (scale) {
      var evidence = evidenceFor(data, scale);
      return evidence && evidence.show;
    }));
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
    var list = el('interval-list');
    var note = el('evidence-note');
    var evidence = evidenceFor(data, selectedScale);
    var bands = intervalRows(data, selectedScale);
    list.replaceChildren();
    state.textContent = '证据：' + (evidence && evidence.label || '证据状态未记录');
    note.textContent = '';
    if (!evidence || !evidence.show) {
      note.textContent = '当前证据不允许显示区间数值。';
      return;
    }
    if (!bands.length) {
      state.textContent = '计算完成，当前尺度没有合格区间';
      return;
    }
    bands.forEach(function (band, index) {
      var id = Core.intervalId(selectedScale, band);
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'interval-row';
      row.dataset.bandId = id;
      row.dataset.scale = selectedScale;
      row.setAttribute('aria-pressed', String(context.focus === id));
      var title = document.createElement('strong');
      title.textContent = band.source === 'scale_window'
        ? '已发布区间' : Clusters.label(band) || (index ? '次级簇' : '主簇');
      var dates = document.createElement('span');
      dates.textContent = dateRange(band);
      row.append(title, dates);
      var share = Clusters.shareText(band);
      var extra = document.createElement('small');
      if (evidence.code === 'descriptive') {
        if (Number.isFinite(band.n)) {
          extra.textContent = (share ? share + '；' : '') + 'n=' + band.n + '；历史分位，不是预测';
        } else {
          extra.textContent = '描述性样本数未记录；历史分位，不是预测';
        }
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
    el(id).textContent = String(value || '未记录');
  }

  function drawHeader(data) {
    setText('asset-name', data.name);
    setText('asset-code', data.symbol);
    setText('asset-exchange', data.exchange);
    setText('model-date', '模型日期 ' + (data.modelAsOf || '未记录'));
    if (data.assetType === 'stock') {
      setText('market-date', '行情日期 ' + (data.marketAsOf || '未记录'));
      setText('data-source', data.dataSource + ' · ' +
        (data.adjustment === 'none' ? '未复权' : data.adjustment));
    } else {
      el('market-date').textContent = '';
      setText('data-source', data.dataSource + ' · ' + data.adjustment);
    }
    setText('model-version', data.modelVersion || '未记录');
    setText('prediction-id', data.predictionId || '未记录');
    el('index-replay').hidden = data.assetType !== 'index';
    el('index-replay').href = 'index.html?code=' + encodeURIComponent(data.symbol);
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

  async function eventRowsFor(code) {
    var payload = await LPPL.events();
    if (!payload) return [];
    var definitions = [
      ['lift', 'free_date'], ['dividend', 'ex_dividend_date'], ['forecast', 'notice_date'],
    ];
    return definitions.flatMap(function (definition) {
      var type = definition[0], dateField = definition[1];
      return (payload[type] || []).filter(function (row) {
        return row.code === code;
      }).map(function (row, index) {
        return { id: type + ':' + row[dateField] + ':' + index, date: row[dateField] };
      });
    });
  }

  async function loadData() {
    if (context.assetType === 'index') {
      var result = await LPPL.load(context.code);
      return Core.assembleIndexData(context.code, result);
    }
    var results = await Promise.all([
      LPPL.stock.latest(context.stockCode),
      LPPL.stock.market(context.stockCode),
    ]);
    var latest = results[0], market = results[1], calendar = null;
    if (!(latest && latest.future_calendar)) {
      // Individual A-share results use the published shared CN trading calendar.
      calendar = await LPPL.history('sh000001').then(function (history) {
        return history && history.future_calendar || null;
      }).catch(function () { return null; });
    }
    var data = Core.assembleStockData(context.code, latest, market, calendar);
    if (/^(lift|dividend|forecast):/.test(context.focus)) {
      data.eventRows = await eventRowsFor(data.symbol.slice(2)).catch(function () { return []; });
    }
    return data;
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

  async function load() {
    var request = ++sequence;
    el('error-panel').hidden = true;
    el('loading').hidden = false;
    el('retry-button').hidden = true;
    try {
      if (!context.valid) throw new Error('缺少有效的指数或 A 股代码。');
      var timeoutId;
      var timeout = new Promise(function (_, reject) {
        timeoutId = root.setTimeout(function () {
          reject(new Error('读取超时（12 秒），请重试。'));
        }, 11000);
      });
      var data;
      try {
        data = await Promise.race([loadData(), timeout]);
      } finally {
        root.clearTimeout(timeoutId);
      }
      if (request !== sequence) return;
      current = data;
      var visibleData = chartPayload(data);
      var lastBar = data.bars[data.bars.length - 1] || {};
      page.dataset.code = data.symbol;
      page.dataset.barCount = String(data.bars.length);
      page.dataset.lastBarDate = String(lastBar.date || lastBar.time || '');
      page.dataset.lastClose = String(lastBar.close == null ? '' : lastBar.close);
      page.dataset.modelAsOf = String(data.modelAsOf || '');
      page.dataset.marketAsOf = String(data.marketAsOf || '');
      drawHeader(data);
      chart.setScale(context.scale);
      chart.setData(visibleData);
      chart.setAsof(data.asof);
      renderEvidence(data, context.scale);
      renderCalendarNotice(data);
      applyInitialFocus(data);
      el('loading').hidden = true;
      page.dataset.loaded = 'true';
    } catch (error) {
      if (request !== sequence) return;
      el('loading').hidden = true;
      el('error-message').textContent = '图表加载失败：' + (error && error.message || '未知错误');
      el('error-panel').hidden = false;
      el('retry-button').hidden = false;
    }
  }

  try {
    chart = LPPLChart.mount(el('chart-host'), { height: 520 });
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
})(window);
