'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app', 'stock-view.js'), 'utf8');
const tradingDaysSource = fs.readFileSync(path.join(__dirname, '..', 'app', 'trading-days.js'), 'utf8');
const scaleBarSource = fs.readFileSync(path.join(__dirname, '..', 'app', 'scale-bar.js'), 'utf8');

function setupView({ search = '', hash = '' } = {}) {
  const listeners = {};
  const elements = new Map();
  const drawCalls = [];
  const context = {
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    globalAlpha: 1,
    font: '',
    textAlign: 'left',
    setTransform() {},
    clearRect() { drawCalls.push({ type: 'clearRect' }); },
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() {},
    fillText(text, x, y, maxWidth) {
      drawCalls.push({ type: 'fillText', text, x, y, maxWidth, textAlign: this.textAlign, font: this.font });
    },
    measureText(text) { return { width: String(text).length * 6 }; },
    setLineDash() {},
    arc() {},
    fill() {},
    fillRect(x, y, width, height) {
      drawCalls.push({ type: 'fillRect', x, y, width, height, fillStyle: this.fillStyle, globalAlpha: this.globalAlpha });
    },
  };
  let doc;

  class Element {
    constructor(id = '') {
      this.id = id;
      this.hidden = false;
      this.disabled = false;
      this.value = '0';
      this.min = '0';
      this.max = '0';
      this.textContent = '';
      this.className = '';
      this.dataset = {};
      this.attributes = {};
      this.handlers = {};
      this.clientWidth = 400;
      this.clientHeight = 260;
      this.style = {};
      this.children = [];
    }

    addEventListener(name, handler) { this.handlers[name] = handler; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] || null; }
    getContext() { return context; }
    getBoundingClientRect() { return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight }; }
    replaceChildren(...children) { this.children = children; }
    querySelectorAll(selector) {
      if (selector === '[data-scale]') return this.children.filter(child => child.dataset.scale);
      return [];
    }
    querySelector(selector) {
      const match = /^\[data-scale="([^"]+)"\]$/.exec(selector);
      return match ? this.children.find(child => child.dataset.scale === match[1]) || null : null;
    }
    focus() { doc.activeElement = this; }
  }

  const rangeButtons = [20, 60, 120, 250].map(days => {
    const button = new Element();
    button.dataset.days = String(days);
    button.textContent = { 20: '1个月', 60: '3个月', 120: '6个月', 250: '1年' }[days];
    button.setAttribute('aria-pressed', String(days === 120));
    return button;
  });
  doc = {
    body: {},
    activeElement: null,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element(id));
      return elements.get(id);
    },
    createElement() { return new Element(); },
    querySelectorAll(selector) {
      if (selector === '[data-days]') return rangeButtons;
      if (selector === '[data-scale]') {
        return [...elements.values()].flatMap(element => element.querySelectorAll(selector));
      }
      return [];
    },
  };
  let onChange;
  const location = new URL(`http://localhost/stock.html${search}${hash}`);
  const window = {
    document: doc,
    getComputedStyle() { return { fontFamily: 'Arial, sans-serif' }; },
    location: {
      href: location.href,
      pathname: location.pathname,
      search: location.search,
      hash: location.hash,
    },
    history: {
      replaceState(_state, _title, url) {
        const next = new URL(String(url), window.location.href);
        window.location.href = next.href;
        window.location.pathname = next.pathname;
        window.location.search = next.search;
        window.location.hash = next.hash;
      },
    },
    devicePixelRatio: 1,
    StockSession: {
      create(options) {
        onChange = options.onChange;
        return { destroy() {}, select() {}, request() {}, resume() {} };
      },
      compatible() { return false; },
      stale() { return false; },
    },
    addEventListener(name, handler) { listeners[name] = handler; },
  };
  vm.runInNewContext(tradingDaysSource, { window, URLSearchParams });
  vm.runInNewContext(scaleBarSource, { window, URLSearchParams });
  vm.runInNewContext(source, { window, URLSearchParams, URL });
  window.StockView.mount({ document: doc, api: {}, renderResult() {} });

  return {
    elements,
    rangeButtons,
    window,
    onChange,
    drawCalls,
    scaleButtons() { return elements.get('stock-scales').children; },
    setState(next) {
      onChange({
        code: '600519',
        market: null,
        current: null,
        history: null,
        tasks: [],
        recent: [],
        issues: {},
        marketStatus: 'ready',
        currentStatus: 'current_ready',
        historyStatus: 'idle',
        ...next,
      });
    },
    setMarket(price, options = {}) {
      const code = options.code || '600519';
      this.setState({
        code,
        market: { name: '测试股票', code, asof: price.at(-1).date, source: 'test', price, ...options.market },
        current: options.current || null,
      });
    },
  };
}

test('selecting a non-last quote updates all four stats and its date label', () => {
  const view = setupView();
  const prices = [
    { date: '2026-11-11', open: 10, high: 12, low: 9, close: 11, volume: 100 },
    { date: '2026-11-12', open: 11, high: 13, low: 10, close: 12, volume: 110 },
    { date: '2026-11-13', open: 12, high: 14, low: 11, close: 13, volume: 120 },
  ];
  view.setMarket(prices);
  const date = view.elements.get('quote-date');

  date.value = '1';
  date.handlers.input({ target: date });

  assert.equal(view.elements.get('quote-close').textContent, '12.00');
  assert.equal(view.elements.get('quote-open').textContent, '11.00');
  assert.equal(view.elements.get('quote-high').textContent, '13.00');
  assert.equal(view.elements.get('quote-low').textContent, '10.00');
  assert.equal(view.elements.get('quote-selected-date').textContent, '2026-11-12');
  assert.match(view.elements.get('quote-readout').textContent, /2026-11-12/);
});

test('chart zoom and pan clamp to the available bars and a 20-bar minimum', () => {
  const { zoom, pan } = setupView().window.StockChartWindow;

  assert.deepEqual({ ...zoom(10, 110, 200, 2, 0.5) }, { start: 35, end: 85 });
  assert.deepEqual({ ...zoom(5, 25, 100, 100, 0.5) }, { start: 5, end: 25 });
  assert.deepEqual({ ...zoom(0, 100, 100, 0.1, 0.5) }, { start: 0, end: 100 });
  assert.deepEqual({ ...zoom(0, 10, 10, 2, 0.5) }, { start: 0, end: 10 });
  assert.deepEqual({ ...pan(0, 40, 100, -100) }, { start: 0, end: 40 });
  assert.deepEqual({ ...pan(60, 100, 100, 100) }, { start: 60, end: 100 });
});

test('plain wheel scrolls normally while Ctrl or Meta wheel zooms into a custom range', () => {
  const view = setupView();
  view.setMarket(Array.from({ length: 250 }, (_, i) => ({
    date: String(i + 1), open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 1000 + i,
  })));
  const canvas = view.elements.get('market-plot');
  let prevented = false;
  canvas.handlers.wheel({ deltaY: 200, clientX: 200, ctrlKey: false, metaKey: false, preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
  assert.equal(view.elements.get('range-mode').textContent, '6个月');

  canvas.handlers.wheel({ deltaY: 200, clientX: 200, ctrlKey: true, metaKey: false, preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(view.elements.get('range-mode').textContent, '自定义');
  assert.ok(view.rangeButtons.every(button => button.getAttribute('aria-pressed') === 'false'));

  view.rangeButtons[1].handlers.click();
  assert.equal(view.elements.get('range-mode').textContent, '3个月');
  assert.deepEqual(view.rangeButtons.map(button => button.getAttribute('aria-pressed')), ['false', 'true', 'false', 'false']);

  canvas.handlers.wheel({ deltaY: 200, clientX: 200, ctrlKey: false, metaKey: true, preventDefault() { prevented = true; } });
  assert.equal(view.elements.get('range-mode').textContent, '自定义');
});

test('zooming at the latest candle keeps the real-data window at the latest edge with future slots', () => {
  const view = setupView();
  const price = barsEnding('2026-11-16', 120);
  const windows = [{ scale: '6-12m', q20_date: '2026-12-30', q80_date: '2027-01-07', n: 4 }];
  const evidence = { '6-12m': 'dev' };
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, evidence, { closures: [] }),
  });

  const states = view.window.ScaleBar.classify(evidence, {}, windows);
  const bands = view.window.StockChartWindow.mapScenarioBands(price, windows, states, new Set());
  const future = view.window.StockChartWindow.futureSlots(price.length, bands, true);
  assert.ok(future > 0);
  const domain = view.window.StockChartWindow.domainSlots(0, price.length, future);
  const canvas = view.elements.get('market-plot');
  const lastCandleX = 10 + (price.length - .5) / domain * (canvas.clientWidth - 68);

  canvas.handlers.wheel({
    deltaY: -200,
    clientX: lastCandleX,
    ctrlKey: true,
    metaKey: false,
    preventDefault() {},
  });

  assert.equal(Number(view.elements.get('quote-date').max), price.length - 1);
});

test('dragging and two-finger pinch mark changed windows as custom', () => {
  const dragView = setupView();
  dragView.setMarket(Array.from({ length: 250 }, (_, i) => ({
    date: String(i + 1), open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 1000 + i,
  })));
  const dragCanvas = dragView.elements.get('market-plot');
  dragCanvas.handlers.pointerdown({ pointerType: 'mouse', button: 0, clientX: 200 });
  dragCanvas.handlers.pointermove({ pointerType: 'mouse', buttons: 1, clientX: 300 });
  assert.equal(dragView.elements.get('range-mode').textContent, '自定义');
  assert.ok(dragView.rangeButtons.every(button => button.getAttribute('aria-pressed') === 'false'));

  const pinchView = setupView();
  pinchView.setMarket(Array.from({ length: 250 }, (_, i) => ({
    date: String(i + 1), open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 1000 + i,
  })));
  const pinchCanvas = pinchView.elements.get('market-plot');
  pinchCanvas.handlers.pointerdown({ pointerType: 'touch', pointerId: 1, clientX: 100, clientY: 100 });
  pinchCanvas.handlers.pointerdown({ pointerType: 'touch', pointerId: 2, clientX: 300, clientY: 100 });
  pinchCanvas.handlers.pointermove({ pointerType: 'touch', pointerId: 2, clientX: 340, clientY: 100 });
  assert.equal(pinchView.elements.get('range-mode').textContent, '自定义');
  assert.ok(pinchView.rangeButtons.every(button => button.getAttribute('aria-pressed') === 'false'));
});

function barsEnding(lastDate, count) {
  const dates = [];
  let date = new Date(`${lastDate}T00:00:00Z`);
  while (dates.length < count) {
    const weekday = date.getUTCDay();
    if (weekday !== 0 && weekday !== 6) dates.push(date.toISOString().slice(0, 10));
    date = new Date(date.getTime() - 86400000);
  }
  return dates.reverse().map((value, index) => ({
    date: value,
    open: 100 + index,
    high: 102 + index,
    low: 99 + index,
    close: 101 + index,
    volume: 1000 + index,
  }));
}

function currentRecord(code, windows, evidence, futureCalendar = { closures: [] }) {
  return {
    symbol: 'sh' + code,
    asof: '2026-11-16',
    future_calendar: futureCalendar,
    top: {
      scale_windows: windows,
      lppls_confidence: { scale_evidence: evidence },
    },
  };
}

function marketRecord(code, price) {
  return { code, name: '测试股票', asof: price.at(-1).date, source: 'test', price };
}

function latestDraw(view) {
  const start = view.drawCalls.findLastIndex(call => call.type === 'clearRect');
  return view.drawCalls.slice(start + 1);
}

function radio(view, scale) {
  return view.scaleButtons().find(button => button.dataset.scale === scale);
}

test('future scenario bands reserve weekday slots with closures and draw no future candles or volume', () => {
  const view = setupView();
  const price = barsEnding('2026-12-30', 30);
  const windows = [{ scale: '12-24m', q20_date: '2027-01-04', q80_date: '2027-01-06', n: 4 }];
  const evidence = { '12-24m': 'dev' };
  const current = currentRecord('601838', windows, evidence, { closures: ['2027-01-01'] });
  view.setState({ code: '601838', market: marketRecord('601838', price), current });

  const states = view.window.ScaleBar.classify(evidence, {}, windows);
  const bands = view.window.StockChartWindow.mapScenarioBands(
    price, windows, states, new Set(['2027-01-01']),
  );
  assert.deepEqual({ ...bands[0] }, {
    scale: '12-24m', lo: price.length + 1, hi: price.length + 3,
    q20_date: '2027-01-04', q80_date: '2027-01-06',
  });
  assert.equal(view.window.StockChartWindow.futureSlots(price.length, bands, true), 7);
  assert.equal(view.window.StockChartWindow.domainSlots(0, price.length, 7), 37);

  const calls = latestDraw(view);
  const barFills = calls.filter(call =>
    call.type === 'fillRect' && ['#D6303A', '#11845A'].includes(call.fillStyle));
  assert.equal(barFills.length, 60);
  const futureArea = calls.find(call => call.type === 'fillRect' && call.fillStyle === '#F8FAFC');
  assert.ok(futureArea);
  assert.ok(barFills.every(call => call.x + call.width <= futureArea.x + .01));
  assert.ok(calls.some(call => call.type === 'fillText' && call.text === '未来交易日 · 无行情'));
});

test('narrow chart uses a bounded short band label, left-aligns its first date, and moves the future note down', () => {
  const view = setupView();
  const price = barsEnding('2026-11-13', 120);
  const windows = [{ scale: '6-12m', q20_date: '2026-12-30', q80_date: '2027-01-07', n: 4 }];
  const canvas = view.elements.get('market-plot');
  canvas.clientWidth = 390;
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, { '6-12m': 'dev' }, { closures: [] }),
  });

  const calls = latestDraw(view);
  const label = calls.find(call => call.type === 'fillText' && call.text === '12/30–1/7');
  assert.ok(label);
  const measuredWidth = label.text.length * 6;
  const labelX = label.textAlign === 'right' ? label.x - measuredWidth : label.x;
  assert.equal(label.textAlign, 'right');
  assert.ok(labelX >= 10);
  assert.ok(labelX + measuredWidth <= canvas.clientWidth - 58);
  const labelBackground = calls.find(call =>
    call.type === 'fillRect' && call.fillStyle === 'rgba(255,255,255,.88)');
  assert.ok(labelBackground);
  assert.equal(labelBackground.height, 16);
  assert.equal(labelBackground.width, measuredWidth + 6);
  assert.ok(labelBackground.x >= 10);
  assert.ok(labelBackground.x + labelBackground.width <= canvas.clientWidth - 58);
  assert.ok(calls.indexOf(labelBackground) < calls.indexOf(label));
  assert.equal(label.font, '11px Arial, sans-serif');
  const firstDate = calls.find(call => call.type === 'fillText' && call.text === price[0].date);
  assert.ok(firstDate);
  assert.equal(firstDate.textAlign, 'left');
  assert.equal(calls.find(call => call.type === 'fillText' && call.text === '成交量').font,
    '11px Arial, sans-serif');
  const futureLabel = calls.find(call => call.type === 'fillText' && call.text === '未来交易日 · 无行情');
  assert.equal(futureLabel.font, '11px Arial, sans-serif');
  assert.ok(futureLabel.y >= canvas.clientHeight * .77);
  assert.ok(calls.filter(call => call.type === 'fillText' && /^\d{4}-\d{2}-\d{2}$/.test(call.text))
    .every(call => call.font === '11px Consolas, monospace'));
});

test('no qualifying bands keep the chart domain at real prices only', () => {
  const view = setupView();
  const price = barsEnding('2026-12-30', 30);
  const evidence = { '6-12m': 'dev' };
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', [], evidence),
  });
  const slots = view.window.StockChartWindow.futureSlots(price.length, [], true);
  assert.equal(slots, 0);
  assert.equal(view.window.StockChartWindow.domainSlots(0, price.length, slots), price.length);
  assert.ok(!latestDraw(view).some(call =>
    call.type === 'fillText' && call.text === '未来交易日 · 无行情'));
});

test('historical chart windows do not get future slots', () => {
  const view = setupView();
  const price = barsEnding('2026-12-30', 250);
  const windows = [{ scale: '12-24m', q20_date: '2027-01-04', q80_date: '2027-01-06', n: 4 }];
  const evidence = { '12-24m': 'dev' };
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, evidence, { closures: ['2027-01-01'] }),
  });
  const canvas = view.elements.get('market-plot');
  canvas.handlers.pointerdown({ pointerType: 'mouse', button: 0, clientX: 200 });
  canvas.handlers.pointermove({ pointerType: 'mouse', buttons: 1, clientX: 300 });
  canvas.handlers.pointerup({ pointerType: 'mouse', clientX: 300, clientY: 100 });

  assert.ok(Number(view.elements.get('quote-date').max) < price.length - 1);
  const bands = view.window.StockChartWindow.mapScenarioBands(
    price, windows, view.window.ScaleBar.classify(evidence, {}, windows), new Set(['2027-01-01']),
  );
  assert.equal(view.window.StockChartWindow.futureSlots(price.length, bands, false), 0);
  assert.ok(!latestDraw(view).some(call =>
    call.type === 'fillText' && call.text === '未来交易日 · 无行情'));
});

test('same-code market refresh preserves a history window by date and advances a latest window by span', () => {
  const historyView = setupView();
  const oldBars = barsEnding('2026-11-16', 250);
  historyView.setMarket(oldBars, { code: '601838' });
  const canvas = historyView.elements.get('market-plot');
  canvas.handlers.pointerdown({ pointerType: 'mouse', button: 0, clientX: 200 });
  canvas.handlers.pointermove({ pointerType: 'mouse', buttons: 1, clientX: 300 });
  canvas.handlers.pointerup({ pointerType: 'mouse', clientX: 300, clientY: 100 });
  const slider = historyView.elements.get('quote-date');
  const preservedDates = [
    oldBars[Number(slider.min)].date,
    oldBars[Number(slider.max)].date,
    oldBars[Number(slider.value)].date,
  ];
  const refreshedBars = barsEnding('2026-11-30', 260);
  historyView.setMarket(refreshedBars, { code: '601838' });
  assert.deepEqual([
    refreshedBars[Number(slider.min)].date,
    refreshedBars[Number(slider.max)].date,
    refreshedBars[Number(slider.value)].date,
  ], preservedDates);

  const latestView = setupView();
  latestView.setMarket(oldBars, { code: '601838' });
  latestView.setMarket(refreshedBars, { code: '601838' });
  const latestSlider = latestView.elements.get('quote-date');
  assert.equal(Number(latestSlider.max), refreshedBars.length - 1);
  assert.equal(Number(latestSlider.max) - Number(latestSlider.min) + 1, 120);
});

test('a result for a different symbol cannot display scenario bands or its scale bar', () => {
  const view = setupView();
  const price = barsEnding('2026-11-16', 30);
  const windows = [{ scale: '6-12m', q20_date: '2026-11-10', q80_date: '2026-11-16', n: 4 }];
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('600519', windows, { '6-12m': 'dev' }),
  });
  assert.equal(view.elements.get('stock-scales').hidden, true);
  assert.ok(!latestDraw(view).some(call =>
    call.type === 'fillRect' && String(call.fillStyle).startsWith('rgba(31,95,214')));
});

test('a window with no evidence stays disabled, says no evidence, and is not drawn', () => {
  const view = setupView();
  const price = barsEnding('2026-11-16', 30);
  const windows = [{ scale: '12-24m', q20_date: '2026-11-12', q80_date: '2026-11-16', n: 4 }];
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, { '6-12m': 'dev', '12-24m': 'none' }),
  });
  const button = radio(view, '12-24m');
  assert.ok(button.disabled);
  assert.match(button.textContent, /无证据/);
  assert.ok(!latestDraw(view).some(call =>
    call.type === 'fillRect' && String(call.fillStyle).startsWith('rgba(31,95,214')));
});

test('a click on a visible scenario band selects its scale and updates the query parameter', () => {
  const view = setupView({ search: '?code=601838&scale=6-12m', hash: '#tab=top' });
  const price = barsEnding('2026-11-16', 30);
  const windows = [
    { scale: '6-12m', q20_date: '2026-11-09', q80_date: '2026-11-11', n: 4 },
    { scale: '12-24m', q20_date: '2026-11-12', q80_date: '2026-11-16', n: 4 },
  ];
  const evidence = { '6-12m': 'dev', '12-24m': 'dev' };
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, evidence),
  });
  assert.equal(radio(view, '6-12m').getAttribute('aria-checked'), 'true');
  const bands = view.window.StockChartWindow.mapScenarioBands(
    price, windows, view.window.ScaleBar.classify(evidence, {}, windows), new Set(),
  );
  const band = bands.find(item => item.scale === '12-24m');
  const center = (band.lo + band.hi + 1) / 2;
  const x = 10 + center / price.length * 332;
  const canvas = view.elements.get('market-plot');
  canvas.handlers.pointerdown({ pointerType: 'mouse', button: 0, clientX: x, clientY: 70 });
  canvas.handlers.pointerup({ pointerType: 'mouse', clientX: x, clientY: 70 });

  assert.equal(radio(view, '12-24m').getAttribute('aria-checked'), 'true');
  const url = new URL(view.window.location.href);
  assert.equal(url.searchParams.get('scale'), '12-24m');
  assert.equal(url.hash, '#tab=top');
});

test('scale radio arrows, Enter, and Space preserve focus after rerender', () => {
  const view = setupView();
  const price = barsEnding('2026-11-16', 30);
  const windows = [
    { scale: '6-12m', q20_date: '2026-11-09', q80_date: '2026-11-11', n: 4 },
    { scale: '12-24m', q20_date: '2026-11-12', q80_date: '2026-11-16', n: 4 },
  ];
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, { '6-12m': 'dev', '12-24m': 'dev' }),
  });
  radio(view, '6-12m').focus();
  let prevented = false;
  radio(view, '6-12m').handlers.keydown({
    key: 'ArrowRight',
    preventDefault() { prevented = true; },
  });
  assert.ok(prevented);
  assert.equal(view.window.document.activeElement.dataset.scale, '12-24m');
  assert.equal(radio(view, '12-24m').getAttribute('aria-checked'), 'true');

  radio(view, '12-24m').handlers.keydown({ key: 'Enter', preventDefault() {} });
  assert.equal(view.window.document.activeElement.dataset.scale, '12-24m');
  radio(view, '12-24m').handlers.keydown({ key: ' ', preventDefault() {} });
  assert.equal(view.window.document.activeElement.dataset.scale, '12-24m');
  radio(view, '12-24m').handlers.keydown({ key: 'ArrowLeft', preventDefault() {} });
  assert.equal(view.window.document.activeElement.dataset.scale, '6-12m');
  assert.equal(radio(view, '6-12m').getAttribute('aria-checked'), 'true');
});

test('legacy results without future_calendar use weekday estimates and show the note', () => {
  const view = setupView();
  const price = barsEnding('2026-11-16', 30);
  const windows = [{ scale: '6-12m', q20_date: '2026-11-17', q80_date: '2026-11-19', n: 4 }];
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, { '6-12m': 'dev' }, null),
  });
  const note = view.elements.get('stock-calendar-note');
  assert.equal(note.hidden, false);
  assert.equal(note.textContent, '该结果未附休市日表，未来日期按工作日估算');
  assert.equal(view.window.CPTradingDays.dateAt(price, price.length, new Set()), '2026-11-17');
});

test('hovering or tapping future slots shows a no-quote readout without extending the date slider', () => {
  const view = setupView();
  const price = barsEnding('2026-12-30', 30);
  const windows = [{ scale: '6-12m', q20_date: '2027-01-04', q80_date: '2027-01-06', n: 4 }];
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, { '6-12m': 'dev' }, { closures: ['2027-01-01'] }),
  });
  const canvas = view.elements.get('market-plot');
  const x = 10 + (30.5 / 37) * 332;
  canvas.handlers.pointermove({ pointerType: 'mouse', buttons: 0, clientX: x, clientY: 100 });
  assert.match(view.elements.get('quote-readout').textContent, /^2026-12-31 · 未来交易日，无行情$/);
  assert.equal(view.elements.get('quote-close').textContent, '—');
  assert.equal(Number(view.elements.get('quote-date').max), price.length - 1);

  canvas.handlers.pointerdown({ pointerType: 'mouse', button: 0, clientX: x, clientY: 100 });
  canvas.handlers.pointerup({ pointerType: 'mouse', clientX: x, clientY: 100 });
  assert.match(view.elements.get('quote-selected-date').textContent, /^2026-12-31 · 未来交易日，无行情$/);
});

test('selecting an out-of-view scale moves to latest while range presets count only real bars', () => {
  const view = setupView();
  const price = barsEnding('2026-12-30', 250);
  const windows = [
    { scale: '6-12m', q20_date: price[110].date, q80_date: price[115].date, n: 4 },
    { scale: '12-24m', q20_date: '2027-01-04', q80_date: '2027-01-06', n: 4 },
  ];
  view.setState({
    code: '601838',
    market: marketRecord('601838', price),
    current: currentRecord('601838', windows, { '6-12m': 'dev', '12-24m': 'dev' }, { closures: ['2027-01-01'] }),
  });
  const canvas = view.elements.get('market-plot');
  canvas.handlers.pointerdown({ pointerType: 'mouse', button: 0, clientX: 200 });
  canvas.handlers.pointermove({ pointerType: 'mouse', buttons: 1, clientX: 300 });
  canvas.handlers.pointerup({ pointerType: 'mouse', clientX: 300, clientY: 100 });
  radio(view, '12-24m').handlers.click();
  const slider = view.elements.get('quote-date');
  assert.equal(Number(slider.max), price.length - 1);
  assert.equal(Number(slider.max) - Number(slider.min) + 1, 120);

  view.rangeButtons[0].handlers.click();
  assert.equal(Number(slider.max), price.length - 1);
  assert.equal(Number(slider.max) - Number(slider.min) + 1, 20);
});
