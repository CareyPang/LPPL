(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLChart = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';
  var TradingDays = root.CPTradingDays;
  var TopClusters = root.CPTopClusters;
  if (typeof module === 'object' && module.exports) {
    TradingDays = TradingDays || require('./trading-days.js');
    TopClusters = TopClusters || require('./top-clusters.js');
  }

  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var time = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
  }

  function dateFromTime(value) {
    if (validDate(value)) return value;
    if (value && Number.isInteger(value.year) && Number.isInteger(value.month) && Number.isInteger(value.day)) {
      var date = value.year + '-' + String(value.month).padStart(2, '0') + '-' + String(value.day).padStart(2, '0');
      return validDate(date) ? date : '';
    }
    if (Number.isFinite(value)) {
      var timestamp = new Date(value * 1000).toISOString().slice(0, 10);
      return validDate(timestamp) ? timestamp : '';
    }
    return '';
  }

  function toCandles(bars) {
    var byDate = new Map();
    (Array.isArray(bars) ? bars : []).forEach(function (bar) {
      if (!bar || !validDate(bar.date)) return;
      if (!['open', 'high', 'low', 'close'].every(function (key) {
        return Number.isFinite(bar[key]);
      })) return;
      if (Math.min(bar.open, bar.high, bar.low, bar.close) <= 0 ||
          bar.high < Math.max(bar.open, bar.close, bar.low) ||
          bar.low > Math.min(bar.open, bar.close)) return;
      if (bar.volume != null && (!Number.isFinite(bar.volume) || bar.volume < 0)) return;
      byDate.set(bar.date, {
        time: bar.date, open: bar.open, high: bar.high, low: bar.low,
        close: bar.close, volume: bar.volume == null ? null : bar.volume,
      });
    });
    return Array.from(byDate.values()).sort(function (a, b) {
      return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
    });
  }

  function futureWhitespace(bars, q80Dates, closures) {
    if (!TradingDays || !Array.isArray(bars) || !bars.length) return [];
    var calendarBars = bars.map(function (bar) { return { date: bar.date || bar.time }; })
      .filter(function (bar) { return validDate(bar.date); });
    if (!calendarBars.length) return [];
    var closed = closures instanceof Set ? closures : new Set(closures || []);
    var last = calendarBars.length - 1, furthest = last;
    (q80Dates || []).forEach(function (date) {
      if (validDate(date)) furthest = Math.max(furthest, TradingDays.idxOf(calendarBars, date, closed) + 3);
    });
    var out = [];
    for (var i = last + 1; i <= Math.min(furthest, last + 260); i++) {
      out.push({ time: TradingDays.dateAt(calendarBars, i, closed) });
    }
    return out;
  }

  function bandsFor(current, scale) {
    var top = current && current.top || {};
    var clusters = TopClusters.forScale(top, scale);
    if (clusters !== null) return clusters;
    var window = (top.scale_windows || []).find(function (item) { return item.scale === scale; });
    return window && validDate(window.q20_date) && validDate(window.q80_date)
      ? [{ rank: 'main', source: 'scale_window', q20_date: window.q20_date, q80_date: window.q80_date }]
      : [];
  }

  function needsCalendarCoverage(bands, lastBarDate, calendar) {
    var future = (bands || []).filter(function (band) {
      return validDate(lastBarDate) && validDate(band.q80_date) && band.q80_date > lastBarDate;
    });
    if (!future.length) return false;
    var coveredThrough = calendar &&
      (calendar.coverage_end || calendar.through || calendar.holidays_through);
    if (!validDate(coveredThrough)) return true;
    return future.some(function (band) { return band.q80_date > coveredThrough; });
  }

  function mapTime(bars, date, closures) {
    var calendarBars = bars.map(function (bar) { return { date: bar.time }; });
    var index = TradingDays.idxOf(calendarBars, date, closures);
    var mapped = TradingDays.dateAt(calendarBars, index, closures);
    if (mapped < date) mapped = TradingDays.dateAt(calendarBars, index + 1, closures);
    return mapped;
  }

  function mount(host, opts) {
    opts = opts || {};
    var lib = root.LPPLLwc && root.LPPLLwc.LightweightCharts;
    if (!lib) throw new Error('LPPLLwc bundle is not loaded');
    var chart = lib.createChart(host, {
      autoSize: true, layout: { attributionLogo: true },
      grid: { vertLines: { color: '#eef1f5' }, horzLines: { color: '#eef1f5' } },
      timeScale: { rightOffset: 4 }, crosshair: { mode: lib.CrosshairMode.Normal },
    });
    var price = chart.addSeries(lib.CandlestickSeries, {
      upColor: '#d6303a', downColor: '#11845a', wickUpColor: '#d6303a',
      wickDownColor: '#11845a', borderVisible: false,
    });
    var volume = chart.addSeries(lib.HistogramSeries, {
      priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false,
    }, 1);
    var pane = chart.panes()[1];
    if (pane) { chart.panes()[0].setHeight(host.clientHeight * 0.78); pane.setHeight(host.clientHeight * 0.22); }
    var emitters = new Map(), candles = [], current = null, scale = '6-12m', closures = new Set();
    var bandPrimitive = null, cutoffPrimitive = null, markerPlugin = null, a11y = null;
    var readout = opts.readout || null;
    function emit(name, value) { (emitters.get(name) || []).forEach(function (fn) { fn(value); }); }
    function detachOverlays() {
      if (bandPrimitive) price.detachPrimitive(bandPrimitive);
      if (cutoffPrimitive) price.detachPrimitive(cutoffPrimitive);
      if (markerPlugin) markerPlugin.detach();
      bandPrimitive = cutoffPrimitive = markerPlugin = null;
    }
    function setData(payload) {
      current = payload || {};
      candles = toCandles(current.bars || []);
      closures = new Set(current.future_calendar && current.future_calendar.closures || []);
      var clusters = bandsFor(current, scale);
      var ws = futureWhitespace(candles, clusters.map(function (item) { return item.q80_date; }), closures);
      price.setData(candles.map(function (bar) {
        return { time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close };
      }).concat(ws));
      volume.setData(candles.filter(function (bar) { return bar.volume != null; }).map(function (bar) {
        return { time: bar.time, value: bar.volume, color: bar.close >= bar.open ? '#d6303a' : '#11845a' };
      }));
      detachOverlays();
      if (clusters.length) {
        bandPrimitive = createBands(chart, candles, clusters, closures);
        price.attachPrimitive(bandPrimitive);
      }
      if (Array.isArray(current.events) && lib.createSeriesMarkers) {
        markerPlugin = lib.createSeriesMarkers(price, current.events.filter(function (event) {
          return validDate(event.date) && candles.length && event.date >= candles[0].time;
        }).map(function (event) {
          return { time: mapTime(candles, event.date, closures), position: 'aboveBar',
            shape: 'circle', color: '#315cf5', text: event.label || '事件' };
        }));
      }
      if (current.asof) setAsof(current.asof);
      if (Number.isFinite(opts.initialBars) && opts.initialBars > 0 && candles.length) {
        chart.timeScale().setVisibleLogicalRange({
          from: Math.max(0, candles.length - opts.initialBars),
          to: candles.length + ws.length - 1,
        });
      } else {
        chart.timeScale().fitContent();
      }
    }
    function setScale(next) { scale = next; if (current) setData(current); emit('scale', next); }
    function setAsof(date) {
      if (!candles.length || !validDate(date)) return;
      if (cutoffPrimitive) price.detachPrimitive(cutoffPrimitive);
      cutoffPrimitive = new root.LPPLLwc.VerticalLine.VerticalLine(
        mapTime(candles, date, closures),
        {
          color: '#596579', width: 1, showLabel: true, labelText: '截止日 ' + date,
          draggable: false, snap: 'nearest', badge: { text: '截止日 ' + date },
        },
      );
      price.attachPrimitive(cutoffPrimitive);
    }
    function on(name, fn) {
      if (!emitters.has(name)) emitters.set(name, []);
      emitters.get(name).push(fn);
      return function () { emitters.set(name, emitters.get(name).filter(function (item) { return item !== fn; })); };
    }
    function crosshair(param) {
      var date = dateFromTime(param && param.time);
      var bar = candles.find(function (item) { return item.time === date; });
      var value = bar ? { date: date, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume }
        : date ? { date: date, future: true } : null;
      if (readout) readout.textContent = !value ? '' : value.future
        ? date + ' 未来交易日 · 无行情'
        : date + ' 开 ' + bar.open + ' 高 ' + bar.high + ' 低 ' + bar.low + ' 收 ' + bar.close +
          ' 量 ' + (bar.volume == null ? '—' : bar.volume) + '（供应商原始单位）';
      emit('crosshair', value);
    }
    chart.subscribeCrosshairMove(crosshair);
    a11y = root.LPPLLwc.Accessibility.addAccessibilityPlugin(chart, { chartTitle: 'LPPL 日线与成交量' });
    return {
      setData: setData, setScale: setScale, setAsof: setAsof, on: on,
      destroy: function () {
        chart.unsubscribeCrosshairMove(crosshair);
        detachOverlays();
        if (a11y) a11y.detach();
        chart.remove();
      },
    };
  }

  function createBands(chart, candles, bands, closures) {
    var views = [{
      zOrder: function () { return 'bottom'; },
      renderer: function () {
        return {
          draw: function () {},
          drawBackground: function (target) {
            target.useBitmapCoordinateSpace(function (scope) {
              var ctx = scope.context, ts = chart.timeScale();
              bands.forEach(function (band) {
                var first = ts.timeToCoordinate(mapTime(candles, band.q20_date, closures));
                var last = ts.timeToCoordinate(mapTime(candles, band.q80_date, closures));
                if (first == null || last == null) return;
                var left = Math.max(0, Math.min(first, last) * scope.horizontalPixelRatio);
                var right = Math.min(scope.bitmapSize.width, Math.max(first, last) * scope.horizontalPixelRatio);
                if (right <= left) return;
                ctx.save();
                ctx.fillStyle = band.rank === 'main' ? 'rgba(49,92,245,.14)' : 'rgba(49,92,245,.045)';
                ctx.fillRect(left, 0, right - left, scope.bitmapSize.height);
                ctx.strokeStyle = 'rgba(49,92,245,.7)';
                ctx.setLineDash(band.rank === 'main' ? [] : [4, 3]);
                ctx.strokeRect(left, 1, right - left, scope.bitmapSize.height - 2);
                ctx.restore();
              });
            });
          },
        };
      },
    }];
    var renderer = views[0].renderer();
    return { paneViews: function () { return views; }, updateAllViews: function () {},
      attached: function (params) { params.requestUpdate && params.requestUpdate(); }, detached: function () {} };
  }

  return {
    mount: mount, toCandles: toCandles, futureWhitespace: futureWhitespace,
    bandsFor: bandsFor, needsCalendarCoverage: needsCalendarCoverage,
    mapTime: mapTime, dateFromTime: dateFromTime,
  };
});
