(function (root) {
  'use strict';

  const DAY = 86400000;
  const widthObservers = new WeakMap();
  const prices = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });
  const volumes = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2, notation: 'compact' });
  const svgNS = 'http://www.w3.org/2000/svg';

  function day(date) {
    if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return NaN;
    const tick = Date.parse(date + 'T00:00:00Z');
    return Number.isFinite(tick) && new Date(tick).toISOString().slice(0, 10) === date ? tick / DAY : NaN;
  }

  function dateAt(tick) {
    return new Date(tick * DAY).toISOString().slice(0, 10);
  }

  function hasCandle(bar) {
    return [bar.open, bar.high, bar.low].every(n => Number.isFinite(n) && n > 0)
      && bar.high >= Math.max(bar.open, bar.close) && bar.low <= Math.min(bar.open, bar.close);
  }

  // A fixed review horizon keeps the original cutoff and window coordinates in place on reveal.
  // Dates use a calendar axis; gaps do not manufacture exchange sessions or prices.
  function chartSlice({ bars = [], asof, windows = [], revealLater = false }) {
    const cutoff = day(asof);
    if (!Number.isFinite(cutoff)) return null;
    const byDate = new Map();
    for (const bar of bars) {
      if (bar && Number.isFinite(day(bar.date)) && Number.isFinite(bar.close) && bar.close > 0
          && (revealLater || bar.date <= asof)) byDate.set(bar.date, bar);
    }
    const sorted = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
    const prior = sorted.filter(bar => bar.date <= asof).slice(-50);
    if (!prior.length) return null;
    const bands = windows.filter(window => window && Number.isFinite(day(window.start))
      && Number.isFinite(day(window.end)) && window.start <= window.end);
    const start = Math.min(day(prior[0].date) - 1, ...bands.map(w => day(w.start) - 2));
    const end = Math.max(cutoff + 42, ...bands.map(w => day(w.end) + 2));
    const later = sorted.filter(bar => bar.date > asof && day(bar.date) <= end);
    const visible = prior.concat(later);
    return { cutoff, start, end, bars: visible, priorCount: prior.length, bands,
      candles: prior.some(hasCandle), hasVolume: visible.some(bar => Number.isFinite(bar.volume) && bar.volume >= 0) };
  }

  function add(parent, tag, attrs = {}, label) {
    const node = parent.namespaceURI === svgNS || tag === 'svg'
      ? document.createElementNS(svgNS, tag) : document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (label !== undefined) node.textContent = label;
    parent.appendChild(node);
    return node;
  }

  function draw(host, data, slice, width) {
    host.replaceChildren();
    const figure = add(host, 'figure', { class: 'gs-plot', 'data-cutoff': data.asof || '',
      'data-price-count': slice?.bars.length || 0, 'data-later-count': slice ? slice.bars.length - slice.priorCount : 0 });
    if (!slice) {
      add(figure, 'figcaption', {}, '所选日期尚无可绘制的历史行情。');
      return;
    }
    const { bars, priorCount, candles, bands, start, end, cutoff, hasVolume } = slice;
    const lastKnown = priorCount - 1;
    const left = 4, right = width - 51;
    const top = 25, priceBottom = width < 500 ? 150 : 185;
    const volumeTop = priceBottom + 8, plotBottom = volumeTop + (hasVolume ? 27 : 0);
    const trackTop = plotBottom + 28, height = trackTop + bands.length * 12 + 3;
    const x = tick => left + (tick - start) / (end - start) * (right - left);
    const cutoffX = x(cutoff);
    const activeCandles = bar => candles && hasCandle(bar);
    const high = Math.max(...bars.map(b => activeCandles(b) ? b.high : b.close));
    const low = Math.min(...bars.map(b => activeCandles(b) ? b.low : b.close));
    const pad = Math.max((high - low) * 0.08, high * 0.001);
    const y = value => priceBottom - (value - low + pad) / (high - low + 2 * pad) * (priceBottom - top);
    const yTick = price => (high < 10 ? price.toFixed(2) : prices.format(price));
    const unit = data.priceUnit || '';
    const meta = add(figure, 'div', { class: 'gs-plot-meta' });
    add(meta, 'strong', {}, candles ? '日 K 线' : '日收盘线');
    add(meta, 'span', {}, unit ? '线性坐标 · ' + unit : '线性坐标');
    const svg = add(figure, 'svg', { viewBox: [0, 0, width, height].join(' '), width: '100%', height,
      role: 'img', 'aria-label': '行情及候选时间窗。研究截止 ' + data.asof + '。' });
    if (bars.length > priorCount) {
      add(svg, 'rect', { x: cutoffX, y: top, width: right - cutoffX, height: plotBottom - top, class: 'gs-plot-later' });
    }
    const axisText = (atX, atY, value, anchor = 'start') =>
      add(svg, 'text', { x: atX, y: atY, 'text-anchor': anchor, class: 'gs-plot-tick' }, value);
    for (const price of [high, (high + low) / 2, low].filter((p, i, values) => values.indexOf(p) === i)) {
      add(svg, 'line', { x1: left, x2: right, y1: y(price), y2: y(price), class: 'gs-plot-grid' });
      axisText(right + 4, y(price) + 3.5, yTick(price));
    }
    const candleWidth = Math.min(8, Math.max(0.7, (right - left) / (end - start) * 0.76));
    const maxVolume = Math.max(1, ...bars.map(bar => Number.isFinite(bar.volume) ? bar.volume : 0));
    if (!candles) {
      const segments = [bars.slice(0, priorCount), bars.slice(lastKnown)];
      for (const [i, group] of segments.entries()) {
        if (group.length < 2) continue;
        const points = group.map(bar => [x(day(bar.date)), y(bar.close)].join(',')).join(' ');
        add(svg, 'polyline', { points, class: i ? 'gs-plot-close gs-plot-close-later' : 'gs-plot-close' });
      }
    }
    bars.forEach((bar, i) => {
      const at = x(day(bar.date)), isLater = i >= priorCount;
      const direction = activeCandles(bar) ? (bar.close >= bar.open ? 'rise' : 'fall') : 'plain';
      const group = add(svg, 'g', { class: 'gs-plot-' + direction, 'data-session': bar.date });
      if (activeCandles(bar)) {
        add(group, 'line', { x1: at, x2: at, y1: y(bar.low), y2: y(bar.high), class: 'gs-plot-wick' });
        add(group, 'rect', { x: at - candleWidth / 2, y: Math.min(y(bar.open), y(bar.close)),
          width: candleWidth, height: Math.max(1, Math.abs(y(bar.open) - y(bar.close))), class: 'gs-plot-body' });
      } else if (candles || bars.length === 1) {
        add(group, 'circle', { cx: at, cy: y(bar.close), r: 2, class: 'gs-plot-point' });
      }
      if (hasVolume && Number.isFinite(bar.volume) && bar.volume > 0) {
        const vHeight = Math.max(0.75, 25 * bar.volume / maxVolume);
        add(group, 'rect', { x: at - candleWidth / 2, y: plotBottom - vHeight,
          width: candleWidth, height: vHeight, class: 'gs-plot-volume' });
      }
      if (isLater) group.setAttribute('data-later', '');
    });
    if (hasVolume) axisText(right + 4, volumeTop + 16, '成交量');
    add(svg, 'line', { x1: left, x2: right, y1: plotBottom + 1, y2: plotBottom + 1, class: 'gs-plot-grid' });
    add(svg, 'line', { x1: cutoffX, x2: cutoffX, y1: top - 6, y2: plotBottom + 3, class: 'gs-plot-cutoff' });
    const anchor = cutoffX - left < 53 ? 'start' : 'end';
    add(svg, 'text', { x: cutoffX + (anchor === 'start' ? 2 : -2), y: 13, 'text-anchor': anchor,
      class: 'gs-plot-date' }, '截止 ' + data.asof.slice(5));
    axisText(left, plotBottom + 16, dateAt(start).slice(5));
    if (cutoffX - left > 45 && right - cutoffX > 45) axisText(cutoffX, plotBottom + 16, data.asof.slice(5), 'middle');
    axisText(right, plotBottom + 16, dateAt(end).slice(5), 'end');
    for (const [i, w] of bands.entries()) {
      const from = x(day(w.start)), to = x(day(w.end)), row = trackTop + i * 12;
      add(svg, 'line', { x1: left, x2: right, y1: row, y2: row, class: 'gs-plot-grid' });
      const bracket = add(svg, 'path', { d: 'M ' + from + ' ' + (row - 4) + ' v 8 m 0 -4 H ' + to + ' m 0 -4 v 8',
        class: 'gs-plot-window', 'data-start': w.start, 'data-end': w.end });
      add(bracket, 'title', {}, (w.label || '研究区间') + ' · ' + w.start + ' 至 ' + w.end);
      axisText(right + 4, row + 4, bands.length === 1 ? '时间窗' : '区间 ' + (i + 1));
    }
    const readout = add(figure, 'div', { class: 'gs-plot-readout', role: 'slider', tabindex: '0',
      'aria-label': '逐日行情，使用左右方向键切换日期', 'aria-valuemin': 1, 'aria-valuemax': bars.length });
    const cursor = add(svg, 'line', { y1: top, y2: plotBottom, class: 'gs-plot-cursor', visibility: 'hidden' });
    let current;
    function select(index, cursorVisible) {
      current = Math.max(0, Math.min(index, bars.length - 1));
      const b = bars[current], at = x(day(b.date));
      cursor.setAttribute('x1', at);
      cursor.setAttribute('x2', at);
      cursor.setAttribute('visibility', cursorVisible ? 'visible' : 'hidden');
      const pieces = [b.date, ...(current > lastKnown ? ['后来行情'] : [])];
      if (hasCandle(b)) pieces.push('开 ' + prices.format(b.open), '高 ' + prices.format(b.high), '低 ' + prices.format(b.low));
      pieces.push('收 ' + prices.format(b.close));
      if (hasVolume) pieces.push('量 ' + (Number.isFinite(b.volume) && b.volume >= 0
        ? volumes.format(b.volume) + (data.volumeUnit || '') : '未提供'));
      readout.replaceChildren();
      for (const piece of pieces) add(readout, 'span', {}, piece);
      readout.setAttribute('aria-valuenow', current + 1);
      readout.setAttribute('aria-valuetext', pieces.join('，'));
    }
    select(lastKnown, false);
    readout.addEventListener('keydown', event => {
      const index = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: bars.length - 1 }[event.key];
      if (index === undefined) return;
      event.preventDefault();
      select(index, true);
    });
    function pointerSelect(event) {
      const bounds = svg.getBoundingClientRect();
      const localX = (event.clientX - bounds.left) / bounds.width * width;
      const target = start + (localX - left) / (right - left) * (end - start);
      if (target > day(bars.at(-1).date) + 1 || target < day(bars[0].date) - 1) return select(lastKnown, false);
      const nearest = bars.reduce((best, bar, i) => Math.abs(day(bar.date) - target) < Math.abs(day(bars[best].date) - target) ? i : best, 0);
      select(nearest, true);
    }
    svg.addEventListener('pointermove', event => { if (event.pointerType === 'mouse') pointerSelect(event); });
    svg.addEventListener('pointerleave', () => select(lastKnown, false));
    svg.addEventListener('click', pointerSelect);
    let caption = '横轴为自然日期，仅在有归档行情的交易日绘制。';
    if (data.revealLater) {
      caption += ' 回看范围至 ' + dateAt(end) + '。';
      caption += bars.length > priorCount ? '后续行情实际显示至 ' + bars.at(-1).date + '。' : '此范围内尚无后续行情。';
    }
    if (!hasVolume) caption += ' 该视图缺少成交量。';
    add(figure, 'figcaption', {}, caption);
  }

  function clear(host) {
    widthObservers.get(host)?.disconnect();
    widthObservers.delete(host);
    host.replaceChildren();
  }

  function render(host, data) {
    clear(host);
    const slice = chartSlice(data);
    let previousWidth = 0;
    function resize() {
      const width = Math.round(host.getBoundingClientRect().width);
      if (width < 1 || width === previousWidth) return;
      previousWidth = width;
      draw(host, data, slice, width);
    }
    resize();
    if (typeof ResizeObserver === 'function') {
      const observer = new ResizeObserver(resize);
      observer.observe(host);
      widthObservers.set(host, observer);
    }
  }

  const api = { render, clear, chartSlice };
  root.GuanshiChart = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
