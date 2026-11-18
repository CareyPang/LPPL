(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLChart = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';
  var TradingDays = root.CPTradingDays;
  var TopClusters = root.CPTopClusters;
  var SCALES = ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'];
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

  function toCloses(bars) {
    var byDate = new Map();
    (Array.isArray(bars) ? bars : []).forEach(function (bar) {
      if (!bar || !validDate(bar.date) || !Number.isFinite(bar.close) || bar.close <= 0) return;
      byDate.set(bar.date, { time: bar.date, close: bar.close,
        volume: Number.isFinite(bar.volume) && bar.volume >= 0 ? bar.volume : null });
    });
    return Array.from(byDate.values()).sort(function (a, b) { return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });
  }
  function priceMode(bars) { return toCloses(bars).length > toCandles(bars).length ? 'close' : 'candles'; }

  function futureWhitespace(bars, q80Dates, closures) {
    if (!TradingDays || !Array.isArray(bars) || !bars.length) return [];
    var calendarBars = bars.map(function (bar) { return { date: bar.date || bar.time }; })
      .filter(function (bar) { return validDate(bar.date); });
    if (!calendarBars.length) return [];
    var closed = closures instanceof Set ? closures : new Set(closures || []);
    var last = calendarBars.length - 1, furthest = last;
    (q80Dates || []).forEach(function (date) {
      if (validDate(date)) furthest = Math.max(furthest, TradingDays.idxOf(calendarBars, date, closed) + 6);
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

  function bandsForAllScales(current) {
    return SCALES.flatMap(function (scale) {
      return bandsFor(current, scale).map(function (band) {
        return Object.assign({}, band, { scale: scale });
      });
    });
  }

  function intervalId(scale, band) {
    return 'interval:' + [scale, band && band.rank || 'main',
      band && band.q20_date || '', band && band.q80_date || ''].join(':');
  }

  function bandStyle(band, selected) {
    var primary = !band || band.rank !== 'secondary';
    return {
      fillAlpha: selected ? (primary ? 0.16 : 0.06) : (primary ? 0.045 : 0.018),
      strokeColor: selected
        ? (primary ? 'rgba(36,71,201,.96)' : 'rgba(49,92,245,.68)')
        : (primary ? 'rgba(36,71,201,.42)' : 'rgba(49,92,245,.28)'),
      lineWidth: selected ? (primary ? 2 : 1.25) : 0.75,
      dashed: !primary,
      showLabel: !!selected,
    };
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

  function bandSlotRange(bars, band, closures) {
    if (!TradingDays || !Array.isArray(bars) || !bars.length || !band ||
        !validDate(band.q20_date) || !validDate(band.q80_date) || band.q80_date < band.q20_date) return null;
    var calendarBars = bars.map(function (bar) {
      return { date: bar.date || bar.time };
    }).filter(function (bar) { return validDate(bar.date); });
    if (!calendarBars.length) return null;
    var closed = closures instanceof Set ? closures : closures ? new Set(closures) : undefined;
    var from = TradingDays.idxOf(calendarBars, band.q20_date, closed);
    var through = TradingDays.idxOf(calendarBars, band.q80_date, closed);
    if (from < 0 || through < from) return null;
    var to = Math.max(from + 1, through + 1);
    return {
      from: from,
      to: to,
      start: TradingDays.dateAt(calendarBars, from, closed),
      end: TradingDays.dateAt(calendarBars, to, closed),
    };
  }

  function cutoffIndex(bars, asof, closures) {
    if (!bars.length) return -1;
    if (!validDate(asof)) return bars.length - 1;
    var date = mapTime(bars, asof, closures);
    var index = bars.findIndex(function (bar) { return (bar.time || bar.date) === date; });
    if (index >= 0) return index;
    var calendarBars = bars.map(function (bar) { return { date: bar.date || bar.time }; });
    return Math.max(0, Math.min(bars.length - 1, TradingDays.idxOf(calendarBars, asof, closures)));
  }

  function focusVisibleRange(bars, asof, closures, targetFrom, targetTo, availableTo) {
    if (!bars.length) return null;
    var cutoff = cutoffIndex(bars, asof, closures);
    var from = Math.max(0, cutoff - 120);
    if (Number.isFinite(targetFrom)) from = Math.min(from, Math.max(0, targetFrom - 5));
    var to = Math.max(cutoff, Number.isFinite(targetTo) ? targetTo : cutoff) + 5;
    if (Number.isFinite(availableTo)) {
      from = Math.min(from, availableTo);
      to = Math.min(to, availableTo);
    }
    return { from: from, to: Math.max(from + 1, to) };
  }

  function defaultVisibleRange(bars, bands, asof, closures, availableTo) {
    if (!bars.length) return null;
    var furthest = bars.length - 1;
    (bands || []).forEach(function (band) {
      var slots = bandSlotRange(bars, band, closures);
      if (slots) furthest = Math.max(furthest, slots.to);
    });
    return focusVisibleRange(bars, asof, closures, null, furthest, availableTo);
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
    var candlePrice = price;
    var closePrice = chart.addSeries(lib.LineSeries, { color: '#536b93', lineWidth: 2, visible: false });
    var volume = chart.addSeries(lib.HistogramSeries, {
      priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false,
    }, 1);
    var pane = chart.panes()[1];
    if (pane) { chart.panes()[0].setHeight(host.clientHeight * 0.78); pane.setHeight(host.clientHeight * 0.22); }
    var emitters = new Map(), candles = [], current = null, scale = '6-12m', closures = new Set();
    var currentBands = [], currentWhitespace = [], focusedBandId = '';
    var bandPrimitive = null, cutoffPrimitive = null, markerPlugin = null, a11y = null;
    var readout = opts.readout || null, closeOnly = false;
    function emit(name, value) { (emitters.get(name) || []).forEach(function (fn) { fn(value); }); }
    function detachOverlays() {
      if (bandPrimitive) price.detachPrimitive(bandPrimitive);
      if (cutoffPrimitive) price.detachPrimitive(cutoffPrimitive);
      if (markerPlugin) markerPlugin.detach();
      bandPrimitive = cutoffPrimitive = markerPlugin = null;
    }
    function setData(payload) {
      detachOverlays();
      current = payload || {};
      closeOnly = priceMode(current.bars || []) === 'close';
      candles = closeOnly ? toCloses(current.bars || []) : toCandles(current.bars || []);
      price = closeOnly ? closePrice : candlePrice;
      candlePrice.applyOptions({ visible: !closeOnly }); closePrice.applyOptions({ visible: closeOnly });
      (closeOnly ? candlePrice : closePrice).setData([]);
      closures = new Set(current.future_calendar && current.future_calendar.closures || []);
      currentBands = bandsForAllScales(current);
      var futureDates = currentBands.map(function (item) { return item.q80_date; });
      if (Array.isArray(current.events)) {
        futureDates = futureDates.concat(current.events.map(function (event) { return event.date; }));
      }
      if (Array.isArray(current.eventRows)) {
        futureDates = futureDates.concat(current.eventRows.map(function (event) { return event.date; }));
      }
      currentWhitespace = futureWhitespace(candles,
        futureDates, closures);
      price.setData(candles.map(function (bar) {
        return closeOnly ? { time: bar.time, value: bar.close } : { time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close };
      }).concat(currentWhitespace));
      volume.setData(candles.filter(function (bar) { return bar.volume != null; }).map(function (bar) {
        return { time: bar.time, value: bar.volume, color: closeOnly ? '#7485a9' : bar.close >= bar.open ? '#d6303a' : '#11845a' };
      }));
      attachBands();
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
          to: candles.length + currentWhitespace.length - 1,
        });
      } else {
        var visibleRange = defaultVisibleRange(
          candles, currentBands, current.asof, closures, candles.length + currentWhitespace.length - 1,
        );
        if (visibleRange) chart.timeScale().setVisibleLogicalRange(visibleRange);
        else chart.timeScale().fitContent();
      }
    }
    function setScale(next) { scale = next; if (current) setData(current); emit('scale', next); }
    function attachBands() {
      if (!currentBands.length) return;
      bandPrimitive = createBands(chart, candles, currentBands, closures, scale, focusedBandId);
      price.attachPrimitive(bandPrimitive);
    }
    function focusBand(band) {
      if (!band || !candles.length) return false;
      var slots = bandSlotRange(candles, band, closures);
      if (!slots) return false;
      scale = band.scale || scale;
      focusedBandId = band.id || intervalId(scale, band);
      if (bandPrimitive) price.detachPrimitive(bandPrimitive);
      bandPrimitive = null;
      attachBands();
      var maxTo = candles.length + currentWhitespace.length - 1;
      chart.timeScale().setVisibleLogicalRange(focusVisibleRange(
        candles, current && current.asof, closures, slots.from, slots.to, maxTo,
      ));
      return true;
    }
    function focusDate(date) {
      if (!validDate(date) || !candles.length) return false;
      var calendarBars = candles.map(function (bar) { return { date: bar.time }; });
      var index = TradingDays.idxOf(calendarBars, date, closures);
      if (index < 0) return false;
      var maxTo = candles.length + currentWhitespace.length - 1;
      chart.timeScale().setVisibleLogicalRange(focusVisibleRange(
        candles, current && current.asof, closures, index, index + 1, maxTo,
      ));
      return true;
    }
    function setAsof(date) {
      if (!candles.length || !validDate(date)) return;
      if (cutoffPrimitive) price.detachPrimitive(cutoffPrimitive);
      cutoffPrimitive = new root.LPPLLwc.VerticalLine.VerticalLine(
        mapTime(candles, date, closures),
        {
          color: '#596579', width: 1, showLabel: true, labelText: '截止日 ' + date,
          labelBackgroundColor: '#596579', labelTextColor: '#ffffff',
          draggable: false, snap: 'nearest', badge: { text: '截止日 ' + date, backgroundColor: '#596579', color: '#ffffff' },
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
        : closeOnly ? date + ' 收 ' + bar.close + '（OHLC 未完整提供，仅收盘线）'
        : date + ' 开 ' + bar.open + ' 高 ' + bar.high + ' 低 ' + bar.low + ' 收 ' + bar.close +
          ' 量 ' + (bar.volume == null ? '—' : bar.volume) + '（供应商原始单位）';
      emit('crosshair', value);
    }
    chart.subscribeCrosshairMove(crosshair);
    a11y = root.LPPLLwc.Accessibility.addAccessibilityPlugin(chart, { chartTitle: 'LPPL 日线与成交量' });
    return {
      setData: setData, setScale: setScale, setAsof: setAsof,
      focusBand: focusBand, focusDate: focusDate, on: on,
      // Keep the user's reading position when independent modules arrive.
      getVisibleRange: function () { return chart.timeScale().getVisibleLogicalRange(); },
      setVisibleRange: function (range) { if (range) chart.timeScale().setVisibleLogicalRange(range); },
      takeScreenshot: function () { return chart.takeScreenshot(); },
      destroy: function () {
        chart.unsubscribeCrosshairMove(crosshair);
        detachOverlays();
        if (a11y) a11y.detach();
        chart.remove();
      },
    };
  }

  function createBands(chart, candles, bands, closures, selectedScale, focusedBandId) {
    function projected(scope) {
      var timeScale = chart.timeScale();
      var ratio = scope.horizontalPixelRatio;
      var selectedIndex = 0;
      return bands.map(function (band) {
        var slots = bandSlotRange(candles, band, closures);
        if (!slots) return null;
        var first = timeScale.timeToCoordinate(slots.start);
        var after = timeScale.timeToCoordinate(slots.end);
        if (first == null || after == null) return null;
        var rawLeft = Math.min(first, after) * ratio;
        var rawRight = Math.max(first, after) * ratio;
        var width = scope.bitmapSize.width;
        if (rawRight < 0 || rawLeft > width) return null;
        var left = Math.max(0, Math.min(width, rawLeft));
        var right = Math.max(0, Math.min(width, rawRight));
        var minWidth = Math.max(1, ratio);
        if (right - left < minWidth) {
          if (left + minWidth <= width) right = left + minWidth;
          else { right = width; left = Math.max(0, width - minWidth); }
        }
        if (right <= left) return null;
        var selected = band.scale === selectedScale;
        return {
          band: band,
          index: selected ? selectedIndex++ : -1,
          selected: selected,
          focused: (band.id || intervalId(band.scale, band)) === focusedBandId,
          left: left,
          right: right,
        };
      }).filter(Boolean).sort(function (a, b) {
        return Number(a.selected) - Number(b.selected);
      });
    }
    function dateText(date) {
      return Number(date.slice(5, 7)) + '/' + Number(date.slice(8, 10));
    }
    var views = [{
      zOrder: function () { return 'top'; },
      renderer: function () {
        return {
          draw: function (target) {
            target.useBitmapCoordinateSpace(function (scope) {
              var ctx = scope.context, ratio = scope.horizontalPixelRatio;
              var labelAreaWidth = Math.max(0, scope.bitmapSize.width - 64 * ratio);
              projected(scope).forEach(function (rect) {
                var style = bandStyle(rect.band, rect.selected);
                if (!style.showLabel) return;
                var color = rect.band.rank !== 'secondary'
                  ? 'rgba(36,71,201,.96)' : 'rgba(49,92,245,.72)';
                var label = dateText(rect.band.q20_date) + '–' + dateText(rect.band.q80_date);
                ctx.save();
                ctx.beginPath();
                ctx.rect(0, 0, labelAreaWidth, scope.bitmapSize.height);
                ctx.clip();
                ctx.font = Math.round(11 * scope.verticalPixelRatio) + 'px sans-serif';
                ctx.textBaseline = 'middle';
                var padding = 5 * ratio, boxWidth = ctx.measureText(label).width + 2 * padding;
                var maxLeft = Math.max(2 * ratio, labelAreaWidth - boxWidth - 2 * ratio);
                var x = Math.max(2 * ratio, Math.min(rect.left + 4 * ratio, maxLeft));
                var y = (48 + rect.index * 18) * scope.verticalPixelRatio;
                var boxHeight = 16 * scope.verticalPixelRatio;
                ctx.fillStyle = color;
                ctx.fillRect(x, y, boxWidth, boxHeight);
                ctx.fillStyle = '#fff';
                ctx.fillText(label, x + padding, y + boxHeight / 2);
                ctx.restore();
              });
            });
          },
          drawBackground: function (target) {
            target.useBitmapCoordinateSpace(function (scope) {
              var ctx = scope.context;
              projected(scope).forEach(function (rect) {
                var style = bandStyle(rect.band, rect.selected);
                ctx.save();
                ctx.fillStyle = 'rgba(49,92,245,' + style.fillAlpha + ')';
                ctx.fillRect(rect.left, 0, rect.right - rect.left, scope.bitmapSize.height);
                ctx.strokeStyle = style.strokeColor;
                ctx.lineWidth = style.lineWidth * scope.horizontalPixelRatio;
                ctx.setLineDash(style.dashed ? [4, 3].map(function (value) {
                  return value * scope.horizontalPixelRatio;
                }) : []);
                ctx.strokeRect(rect.left + ctx.lineWidth / 2, ctx.lineWidth / 2,
                  Math.max(1, rect.right - rect.left - ctx.lineWidth),
                  Math.max(1, scope.bitmapSize.height - ctx.lineWidth));
                if (rect.focused) {
                  ctx.setLineDash([]);
                  ctx.strokeStyle = 'rgba(245,158,11,.92)';
                  ctx.lineWidth = 2 * scope.horizontalPixelRatio;
                  ctx.strokeRect(rect.left + ctx.lineWidth / 2, ctx.lineWidth / 2,
                    Math.max(1, rect.right - rect.left - ctx.lineWidth),
                    Math.max(1, scope.bitmapSize.height - ctx.lineWidth));
                }
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
    mount: mount, toCandles: toCandles, toCloses: toCloses, priceMode: priceMode, futureWhitespace: futureWhitespace,
    bandsFor: bandsFor, bandsForAllScales: bandsForAllScales,
    bandStyle: bandStyle, intervalId: intervalId, bandSlotRange: bandSlotRange,
    needsCalendarCoverage: needsCalendarCoverage,
    focusVisibleRange: focusVisibleRange, defaultVisibleRange: defaultVisibleRange,
    mapTime: mapTime, dateFromTime: dateFromTime,
  };
});
