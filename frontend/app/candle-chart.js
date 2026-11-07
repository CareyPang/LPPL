/* Observed OHLCV plus supplied research intervals. No fitting or invented future OHLC. */
(function (root) {
  'use strict';
  const COLORS = { up: '#F08086', down: '#63C5A4', flat: '#D3DCE8',
    grid: '#203044', text: '#A9B9CE', cross: '#8295AD', missing: '#77879C',
    observation: '#B6A1D2', observationFill: 'rgba(162, 139, 195, .17)' };
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const px = value => finite(value) ? value.toFixed(2) : '—';
  function volume(value) {
    if (!finite(value) || value < 0) return '缺失';
    if (value === 0) return '0';
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value);
  }
  function unitLabel(unit) {
    return ({ shares: '股', lots: '手', shares_verified: '股' })[unit] || '源单位未核验';
  }
  function adjustmentLabel(adjustment) {
    return ({ none: '未复权', qfq: '前复权', hfq: '后复权' })[adjustment] || '复权口径未核验';
  }
  function normalize(bars) {
    const dates = new Map();
    for (const bar of bars || []) {
      if (!bar || typeof bar.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(bar.date)) continue;
      const stamp = Date.parse(bar.date + 'T00:00:00Z');
      if (!Number.isFinite(stamp) || new Date(stamp).toISOString().slice(0, 10) !== bar.date) continue;
      if (!finite(bar.close) || bar.close <= 0) continue;
      const valid = ['open', 'high', 'low'].every(key => finite(bar[key]) && bar[key] > 0) &&
        bar.high >= Math.max(bar.open, bar.close) && bar.low <= Math.min(bar.open, bar.close);
      dates.set(bar.date, { date: bar.date, close: bar.close,
        open: valid ? bar.open : null, high: valid ? bar.high : null, low: valid ? bar.low : null,
        volume: finite(bar.volume) && bar.volume >= 0 ? bar.volume : null, ohlcValid: valid });
    }
    return [...dates.values()].sort((a, b) => a.date.localeCompare(b.date));
  }
  function geometry(bars, width, height, options = {}) {
    const left = 12, right = width < 500 ? 54 : 66, top = 58;
    const priceBottom = Math.max(top + 60, Math.round(height * .68));
    const volumeTop = priceBottom + 38, bottom = height - 30;
    const plotWidth = Math.max(1, width - left - right);
    const latest = bars.at(-1)?.date;
    const futureDates = [...new Set((options.analysis?.futureDates || []).filter(date =>
      typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) && date > latest))].sort();
    const dates = [...bars.map(bar => bar.date), ...futureDates];
    const dateIndices = new Map(dates.map((date, index) => [date, index]));
    const step = plotWidth / Math.max(1, dates.length);
    const lows = bars.map(bar => bar.ohlcValid ? bar.low : bar.close);
    const highs = bars.map(bar => bar.ohlcValid ? bar.high : bar.close);
    const low = lows.length ? Math.min(...lows) : 0, high = highs.length ? Math.max(...highs) : 1;
    const pad = Math.max((high - low) * .08, Math.abs(high) * .003, .01);
    const min = low - pad, max = high + pad;
    const maxVolume = Math.max(1, ...bars.map(bar => bar.volume ?? 0));
    return { left, right, top, priceBottom, volumeTop, bottom, plotWidth, step, min, max, maxVolume, dates,
      futureDates, observedCount: bars.length,
      x: index => left + (index + .5) * step,
      xDate: date => dateIndices.has(date) ? left + (dateIndices.get(date) + .5) * step : null,
      y: value => top + (max - value) / (max - min) * (priceBottom - top),
      vy: value => bottom - value / maxVolume * Math.max(1, bottom - volumeTop),
      isFutureAt: x => futureDates.length > 0 && x >= left + bars.length * step && x <= left + plotWidth,
      indexAt: x => Math.max(0, Math.min(bars.length - 1, Math.floor((x - left) / step))) };
  }
  function describe(bar, unit) {
    if (!bar) return '';
    return `${bar.date}　开 ${px(bar.open)}　高 ${px(bar.high)}　低 ${px(bar.low)}　收 ${px(bar.close)}` +
      `　成交量 ${volume(bar.volume)}${bar.volume == null ? '' : `（${unitLabel(unit)}）`}` +
      (bar.ohlcValid ? '' : '　OHLC不完整，仅显示收盘标记');
  }
  function intervalLabels(analysis) {
    return (analysis?.windows || []).map((window, index) => ({ window, index }))
      .filter(({ window }) => !window.expired && window.start && window.end)
      .map(({ window, index }) => ({ index, id: window.id, start: window.start, end: window.end,
        badge: (window.geometryQualified ? '候选' : '观察') + ('①②③④⑤⑥⑦⑧⑨⑩'[index] || String(index + 1)),
        dates: `${window.start} — ${window.end}` }));
  }
  function draw(canvas, bars, selected, options = {}) {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height || !bars.length) return null;
    const dpr = Math.min(options.pixelRatio || root.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
    const g = geometry(bars, width, height, options);
    const line = (x1, y1, x2, y2) => { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); };
    ctx.font = '11px "Cascadia Mono", Consolas, monospace'; ctx.lineWidth = 1;
    if (g.futureDates.length) {
      const boundary = g.left + bars.length * g.step;
      ctx.fillStyle = 'rgba(155, 171, 196, .035)';
      ctx.fillRect(boundary, g.top, width - g.right - boundary, g.bottom - g.top);
      ctx.fillStyle = COLORS.text; ctx.textAlign = 'right';
      ctx.fillText(width < 500 ? '未来 · 无行情' : '未来日期区域 · 无未来行情', width - g.right, g.top - 12);
    }
    const analysis = options.analysis;
    for (const { index, badge } of intervalLabels(analysis)) {
      const window = analysis.windows[index];
      if (window.expired) continue;
      const start = g.xDate(window.start), end = g.xDate(window.end);
      // Never clip a candidate into a narrower, apparently more precise interval.
      if (start == null || end == null) continue;
      const isFormal = window.geometryQualified === true;
      const x = start - g.step / 2, bandWidth = Math.max(g.step, end - start + g.step);
      ctx.fillStyle = COLORS.observationFill;
      ctx.fillRect(x, g.top, bandWidth, g.priceBottom - g.top);
      ctx.strokeStyle = COLORS.observation;
      ctx.setLineDash(isFormal ? [] : [4, 4]);
      line(x, g.top, x, g.priceBottom); line(x + bandWidth, g.top, x + bandWidth, g.priceBottom);
      ctx.setLineDash([]);
      ctx.fillStyle = COLORS.observation;
      ctx.fillRect(x, g.top - 4, bandWidth, 3);
      const badgeWidth = (ctx.measureText ? ctx.measureText(badge).width : badge.length * 11) + 12;
      const badgeX = Math.max(g.left, Math.min(x + bandWidth / 2 - badgeWidth / 2, width - g.right - badgeWidth));
      const badgeY = g.top + 7 + Math.min(index, 5) * 20;
      ctx.fillStyle = '#272338'; ctx.fillRect(badgeX, badgeY, badgeWidth, 18);
      ctx.fillStyle = COLORS.observation; ctx.textAlign = 'left';
      ctx.fillText(badge, badgeX + 6, badgeY + 12);
    }
    ctx.textAlign = 'left'; ctx.strokeStyle = COLORS.grid;
    for (let i = 0; i <= 4; i++) {
      const p = g.min + (g.max - g.min) * i / 4;
      line(g.left, g.y(p), width - g.right, g.y(p));
      ctx.fillStyle = COLORS.text; ctx.fillText(px(p), width - g.right + 8, g.y(p) + 4);
    }
    ctx.strokeStyle = COLORS.grid; line(g.left, g.priceBottom + 17, width - 10, g.priceBottom + 17);
    ctx.fillStyle = COLORS.text; ctx.fillText('成交量', g.left, g.volumeTop - 10);
    const maxLabel = g.maxVolume >= 10000 ? `${(g.maxVolume / 10000).toFixed(1)}万` : String(g.maxVolume);
    ctx.fillText(maxLabel, width - g.right + 8, g.volumeTop + 7);
    const bodyWidth = Math.max(1, Math.min(11, g.step * .64));
    bars.forEach((bar, index) => {
      const x = g.x(index);
      const color = !bar.ohlcValid || bar.close === bar.open ? COLORS.flat : bar.close > bar.open ? COLORS.up : COLORS.down;
      ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1;
      if (bar.ohlcValid) {
        line(x, g.y(bar.high), x, g.y(bar.low));
        const top = Math.min(g.y(bar.open), g.y(bar.close));
        const bodyHeight = Math.max(1, Math.abs(g.y(bar.open) - g.y(bar.close)));
        if (bar.close > bar.open && bodyWidth >= 3) ctx.strokeRect(x - bodyWidth / 2, top, bodyWidth, bodyHeight);
        else ctx.fillRect(x - bodyWidth / 2, top, bodyWidth, bodyHeight);
      } else line(x - bodyWidth / 2, g.y(bar.close), x + bodyWidth / 2, g.y(bar.close));
      ctx.globalAlpha = .68;
      if (bar.volume != null) {
        const volumeHeight = bar.volume === 0 ? 1 : Math.max(1.5, g.bottom - g.vy(bar.volume));
        ctx.fillRect(x - bodyWidth / 2, g.bottom - volumeHeight, bodyWidth, volumeHeight);
      } else {
        ctx.strokeStyle = COLORS.missing;
        line(x - 2, g.bottom - 5, x + 2, g.bottom - 1); line(x - 2, g.bottom - 1, x + 2, g.bottom - 5);
      }
      ctx.globalAlpha = 1;
    });
    const cutoff = analysis?.asOf && g.xDate(analysis.asOf);
    if (typeof cutoff === 'number') {
      const cutoffX = cutoff + g.step / 2;
      ctx.strokeStyle = '#D7C6A5'; ctx.setLineDash([5, 4]);
      line(cutoffX, g.top - 5, cutoffX, g.bottom); ctx.setLineDash([]);
      ctx.fillStyle = '#D7C6A5'; ctx.textAlign = cutoffX > width / 2 ? 'right' : 'left';
      ctx.fillText(width < 500 ? '分析截止' : '分析截止 ' + analysis.asOf, cutoffX, 24);
      ctx.textAlign = 'left';
    }
    const bar = bars[selected];
    if (bar) {
      ctx.strokeStyle = COLORS.cross; ctx.lineWidth = 1; ctx.setLineDash([3, 4]);
      line(g.x(selected), g.top - 5, g.x(selected), g.bottom);
      const pointer = options.pointerY;
      const y = finite(pointer) && pointer >= g.top && pointer <= g.priceBottom ? pointer : g.y(bar.close);
      line(g.left, y, width - g.right, y); ctx.setLineDash([]);
      const label = px(g.max - (y - g.top) / (g.priceBottom - g.top) * (g.max - g.min));
      ctx.fillStyle = '#314660'; ctx.fillRect(width - g.right + 3, y - 9, g.right - 6, 18);
      ctx.fillStyle = '#F5F0E7'; ctx.fillText(label, width - g.right + 8, y + 4);
    }
    ctx.fillStyle = COLORS.text; ctx.textAlign = 'left';
    ctx.fillText(bars[0].date, g.left, height - 9);
    ctx.textAlign = 'right'; ctx.fillText(g.dates.at(-1), width - g.right, height - 9);
    ctx.textAlign = 'left';
    return g;
  }
  const api = { normalize, geometry, draw, describe, intervalLabels, volume, unitLabel, adjustmentLabel, COLORS };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CandleChart = api;
})(typeof window === 'object' ? window : globalThis);
