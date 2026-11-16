(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ChartLab = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  var scaleBar = root.ScaleBar;
  var tradingDays = root.CPTradingDays;
  if (typeof module === 'object' && module.exports) {
    scaleBar = scaleBar || require('./scale-bar.js');
    tradingDays = tradingDays || require('./trading-days.js');
  }

  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var time = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
  }

  function toCandles(bars) {
    var byDate = new Map();
    (Array.isArray(bars) ? bars : []).forEach(function (bar) {
      if (!bar || !validDate(bar.date)) return;
      if (!['open', 'high', 'low', 'close', 'volume'].every(function (key) {
        return Number.isFinite(bar[key]);
      })) return;
      if (Math.min(bar.open, bar.high, bar.low, bar.close) <= 0 || bar.volume < 0) return;
      if (bar.high < Math.max(bar.open, bar.close, bar.low) ||
          bar.low > Math.min(bar.open, bar.close)) return;
      byDate.set(bar.date, {
        time: bar.date,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        volume: bar.volume,
      });
    });
    return Array.from(byDate.values()).sort(function (a, b) {
      return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
    });
  }

  function futureWhitespace(bars, q80Dates, closures) {
    if (!tradingDays || !Array.isArray(bars) || !bars.length) return [];
    var byDate = new Map();
    bars.forEach(function (bar) {
      var date = bar && (bar.date || bar.time);
      if (validDate(date)) byDate.set(date, { date: date });
    });
    var calendarBars = Array.from(byDate.values()).sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    });
    if (!calendarBars.length) return [];

    var excluded = closures instanceof Set ? closures : new Set(closures || []);
    var lastIndex = calendarBars.length - 1, furthestIndex = lastIndex;
    (Array.isArray(q80Dates) ? q80Dates : []).forEach(function (date) {
      if (!validDate(date)) return;
      var index = tradingDays.idxOf(calendarBars, date, excluded);
      if (index >= 0) furthestIndex = Math.max(furthestIndex, index + 3);
    });

    var endIndex = Math.min(furthestIndex, lastIndex + 260), result = [];
    for (var index = lastIndex + 1; index <= endIndex; index++) {
      var date = tradingDays.dateAt(calendarBars, index, excluded);
      if (date > calendarBars[lastIndex].date) result.push({ time: date });
    }
    return result;
  }

  function bandsFor(current) {
    if (!scaleBar) return [];
    var top = current && current.top || {};
    var confidence = top.lppls_confidence || {};
    var windows = Array.isArray(top.scale_windows) ? top.scale_windows : [];
    var states = scaleBar.classify(confidence.scale_evidence, confidence, windows);
    return states.filter(function (state) {
      return state.selectable && state.hasWindow;
    }).flatMap(function (state) {
      var band = windows.find(function (window) {
        return window && window.scale === state.scale &&
          validDate(window.q20_date) && validDate(window.q80_date);
      });
      return band ? [{
        scale: state.scale,
        q20_date: band.q20_date,
        q80_date: band.q80_date,
      }] : [];
    });
  }

  function pickCurrent(a, b) {
    if (!a) return b || null;
    if (!b) return a;
    var aAsOf = String(a.asof || ''), bAsOf = String(b.asof || '');
    if (aAsOf !== bAsOf) return aAsOf > bAsOf ? a : b;
    function stamp(value) {
      return Date.parse(value.requested_at || value.generated_at || '') || 0;
    }
    return stamp(a) > stamp(b) ? a : b;
  }

  return {
    toCandles: toCandles,
    futureWhitespace: futureWhitespace,
    bandsFor: bandsFor,
    pickCurrent: pickCurrent,
  };
});

(function (root) {
  'use strict';
  if (!root || !root.document) return;

  var doc = root.document;
  var $ = function (id) { return doc.getElementById(id); };
  var scaleNames = {
    '2-4w': '2–4 周',
    '1-3m': '1–3 月',
    '3-6m': '3–6 月',
    '6-12m': '6–12 月',
    '12-24m': '12–24 月',
    '2-6y': '2–6 年',
  };
  var code = new URLSearchParams(root.location.search).get('code') || '601838';
  if (!/^\d{6}$/.test(code)) code = '601838';
  var existingFrame = $('existing-frame');
  function scrollExistingChartIntoView() {
    var startedAt = Date.now();
    function poll() {
      try {
        var frameDocument = existingFrame.contentDocument;
        var plot = frameDocument && frameDocument.getElementById('market-plot');
        if (plot) {
          var style = frameDocument.defaultView.getComputedStyle(plot);
          var rect = plot.getBoundingClientRect();
          if (!plot.hidden && style.display !== 'none' && style.visibility !== 'hidden' &&
              rect.width > 0 && rect.height > 0) {
            plot.scrollIntoView({ block: 'start' });
            return;
          }
        }
      } catch (_) {}
      if (Date.now() - startedAt < 15000) root.setTimeout(poll, 100);
    }
    poll();
  }
  existingFrame.addEventListener('load', scrollExistingChartIntoView);
  existingFrame.src = 'stock.html?code=' + encodeURIComponent(code);

  var chart = null, candleSeries = null, volumeSeries = null, primitive = null;
  var candles = [], calendarBars = [], bands = [], states = [], closures = new Set();
  var selectedScale = null, chartStartDate = null, chartEndDate = null, chartFutureCount = 0;
  var gzipUrl = 'vendor/lightweight-charts/5.2.1/lightweight-charts.standalone.production.js';

  function statesFor(current) {
    var top = current && current.top || {};
    var confidence = top.lppls_confidence || {};
    var windows = Array.isArray(top.scale_windows) ? top.scale_windows : [];
    return root.ScaleBar.classify(confidence.scale_evidence, confidence, windows);
  }

  function dateOnly(time) {
    if (typeof time === 'string') return time;
    if (typeof time === 'number') return new Date(time * 1000).toISOString().slice(0, 10);
    if (time && typeof time === 'object' && time.year && time.month && time.day) {
      return String(time.year).padStart(4, '0') + '-' +
        String(time.month).padStart(2, '0') + '-' + String(time.day).padStart(2, '0');
    }
    return '';
  }

  function plusDays(date, days) {
    var value = new Date(date + 'T00:00:00Z');
    value.setUTCDate(value.getUTCDate() + days);
    return value.toISOString().slice(0, 10);
  }

  function renderChips() {
    var bandByScale = new Map(bands.map(function (band) { return [band.scale, band]; }));
    $('scale-chips').innerHTML = states.map(function (state) {
      var available = bandByScale.has(state.scale);
      var suffix = !state.selectable ? ' · 无证据' : available ? '' : ' · 无合格拟合';
      return '<button class="scale-chip" type="button" data-scale="' + state.scale + '"' +
        ' aria-pressed="' + String(state.scale === selectedScale) + '"' +
        (available ? '' : ' disabled') + '>' +
        scaleNames[state.scale] + suffix + '</button>';
    }).join('');
  }

  function bandLabel(band) {
    return band.q20_date.slice(5).replace('-', '/') + '–' + band.q80_date.slice(5).replace('-', '/');
  }

  function createBandPrimitive(activeChart, band) {
    var renderer = {
      draw: function () {},
      drawBackground: function (target) {
        target.useBitmapCoordinateSpace(function (scope) {
          var timeScale = activeChart.timeScale();
          var first = timeScale.timeToCoordinate(band.q20_date);
          var last = timeScale.timeToCoordinate(band.q80_date);
          if (first == null || last == null) return;
          var left = Math.max(0, Math.min(first, last) * scope.horizontalPixelRatio);
          var right = Math.min(scope.bitmapSize.width, Math.max(first, last) * scope.horizontalPixelRatio);
          if (right <= left) return;
          var context = scope.context;
          context.save();
          context.fillStyle = 'rgba(214, 153, 51, 0.16)';
          context.fillRect(left, 0, right - left, scope.bitmapSize.height);
          context.font = (12 * scope.verticalPixelRatio) + 'px sans-serif';
          context.textAlign = 'left';
          var label = bandLabel(band);
          var labelWidth = context.measureText(label).width;
          var padding = 4 * scope.horizontalPixelRatio;
          var labelX = Math.max(padding, Math.min(left + padding, scope.bitmapSize.width - padding - labelWidth));
          context.fillStyle = 'rgba(255, 255, 255, 0.88)';
          context.fillRect(labelX - padding / 2, 2 * scope.verticalPixelRatio,
            labelWidth + padding, 17 * scope.verticalPixelRatio);
          context.fillStyle = '#85580c';
          context.fillText(
            label,
            labelX,
            16 * scope.verticalPixelRatio,
          );
          context.restore();
        });
      },
    };
    var view = {
      zOrder: function () { return 'bottom'; },
      renderer: function () { return renderer; },
    };
    var views = [view];
    return {
      paneViews: function () { return views; },
      updateAllViews: function () {},
      attached: function (parameters) {
        if (parameters.requestUpdate) parameters.requestUpdate();
      },
      detached: function () {},
    };
  }

  function candleData() {
    return candles.map(function (bar) {
      return { time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close };
    });
  }

  function applyBand(scale, fit) {
    selectedScale = scale;
    var band = bands.find(function (item) { return item.scale === selectedScale; }) || null;
    var future = root.ChartLab.futureWhitespace(calendarBars, band ? [band.q80_date] : [], closures);
    candleSeries.setData(candleData().concat(future));
    if (primitive) candleSeries.detachPrimitive(primitive);
    primitive = band ? createBandPrimitive(chart, band) : null;
    if (primitive) candleSeries.attachPrimitive(primitive);
    chartFutureCount = future.length;
    chartEndDate = future.length ? future[future.length - 1].time : candles[candles.length - 1].time;
    renderChips();
    if (fit) {
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, candles.length - 120),
        to: candles.length + future.length + 3,
      });
    }
  }

  function makeChart() {
    var host = $('lwc-chart');
    chart = root.LightweightCharts.createChart(host, {
      autoSize: true,
      layout: { attributionLogo: true },
      grid: {
        vertLines: { color: '#f0f2f5' },
        horzLines: { color: '#f0f2f5' },
      },
      rightPriceScale: { borderColor: '#d9dde4' },
      timeScale: { borderColor: '#d9dde4', rightOffset: 4 },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });
    candleSeries = chart.addSeries(root.LightweightCharts.CandlestickSeries, {
      upColor: '#D6303A',
      downColor: '#11845A',
      wickUpColor: '#D6303A',
      wickDownColor: '#11845A',
      borderVisible: false,
    });
    volumeSeries = chart.addSeries(root.LightweightCharts.HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
      visible: false,
    });
    candleSeries.setData(candleData());
    volumeSeries.setData(candles.map(function (bar) {
      return {
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? '#D6303A' : '#11845A',
      };
    }));
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove(function (parameter) {
      var date = dateOnly(parameter && parameter.time);
      if (!date) return;
      var bar = candles.find(function (item) { return item.time === date; });
      if (!bar && date > candles[candles.length - 1].time) {
        $('crosshair-readout').textContent = date + ' 未来交易日 · 无行情';
        return;
      }
      if (!bar) return;
      $('crosshair-readout').textContent = date + ' 开 ' + bar.open.toFixed(2) +
        ' 高 ' + bar.high.toFixed(2) + ' 低 ' + bar.low.toFixed(2) +
        ' 收 ' + bar.close.toFixed(2) + ' 量 ' + bar.volume.toFixed(2) + '（供应商原始单位）';
    });
    applyBand(selectedScale, true);
  }

  function locateDate() {
    if (!chart || !chartStartDate || !chartEndDate) return;
    var date = $('focus-date').value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
    var focusDate = date < chartStartDate ? chartStartDate : date > chartEndDate ? chartEndDate : date;
    var from = plusDays(focusDate, -30);
    var to = plusDays(focusDate, 30);
    if (from < chartStartDate) from = chartStartDate;
    if (to > chartEndDate) to = chartEndDate;
    function setLatestRange() {
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, candles.length - 120),
        to: candles.length + chartFutureCount + 3,
      });
    }
    if (from >= to) {
      setLatestRange();
      return;
    }
    if (focusDate > candles[candles.length - 1].time || to > candles[candles.length - 1].time) {
      setLatestRange();
      return;
    }
    try {
      chart.timeScale().setVisibleRange({ from: from, to: to });
    } catch (_) {
      setLatestRange();
    }
  }

  async function updateGzipSize() {
    var target = $('gzip-size');
    if (typeof root.CompressionStream !== 'function') {
      target.textContent = '不可用';
      return;
    }
    try {
      var response = await root.fetch(gzipUrl);
      if (!response.ok || !response.body) throw new Error('bundle unavailable');
      var compressed = await new root.Response(
        response.body.pipeThrough(new root.CompressionStream('gzip')),
      ).arrayBuffer();
      target.textContent = (compressed.byteLength / 1024).toFixed(1) + ' KB';
    } catch (_) {
      target.textContent = '不可用';
    }
  }

  async function load() {
    try {
      var results = await Promise.allSettled([
        Promise.resolve().then(function () { return root.LPPL.stock.market(code); }),
        Promise.resolve().then(function () { return root.LPPL.stock.latest(code); }),
        Promise.resolve().then(function () { return root.LPPL.stock.remote(code, 'latest'); }),
      ]);
      var market = results[0].status === 'fulfilled' ? results[0].value : null;
      var localCurrent = results[1].status === 'fulfilled' ? results[1].value : null;
      var remoteCurrent = results[2].status === 'fulfilled' ? results[2].value : null;
      var current = root.ChartLab.pickCurrent(localCurrent, remoteCurrent);
      if (!market || !current || !Array.isArray(market.price)) throw new Error('missing');
      candles = root.ChartLab.toCandles(market.price);
      if (!candles.length) throw new Error('missing');
      calendarBars = candles.map(function (bar) { return { date: bar.time }; });
      chartStartDate = candles[0].time;
      closures = new Set(current.future_calendar && current.future_calendar.closures || []);
      bands = root.ChartLab.bandsFor(current);
      states = statesFor(current);
      selectedScale = bands.some(function (band) { return band.scale === root.ScaleBar.DEFAULT_SCALE; })
        ? root.ScaleBar.DEFAULT_SCALE
        : bands.length ? bands[0].scale : null;
      $('focus-date').value = candles[candles.length - 1].time;
      renderChips();
      $('lab-status').textContent = '';
      makeChart();
    } catch (_) {
      states = root.ScaleBar.classify({}, {}, []);
      bands = [];
      selectedScale = null;
      renderChips();
      $('lab-status').textContent = '行情或模型结果未加载';
    }
  }

  $('scale-chips').addEventListener('click', function (event) {
    var button = event.target.closest('[data-scale]');
    if (button && !button.disabled && candleSeries) applyBand(button.dataset.scale, true);
  });
  $('locate-date').addEventListener('click', locateDate);
  $('focus-date').addEventListener('keydown', function (event) {
    if (event.key === 'Enter') locateDate();
  });
  updateGzipSize();
  load();
})(typeof window !== 'undefined' ? window : null);
