'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app', 'stock-view.js'), 'utf8');

function setupView() {
  const listeners = {};
  const elements = new Map();
  const context = {
    setTransform() {},
    clearRect() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() {},
    fillText() {},
    setLineDash() {},
    arc() {},
    fill() {},
    fillRect() {},
  };

  class Element {
    constructor(id = '') {
      this.id = id;
      this.hidden = false;
      this.value = '0';
      this.min = '0';
      this.max = '0';
      this.textContent = '';
      this.dataset = {};
      this.attributes = {};
      this.handlers = {};
      this.clientWidth = 400;
      this.clientHeight = 260;
      this.style = {};
    }

    addEventListener(name, handler) { this.handlers[name] = handler; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] || null; }
    getContext() { return context; }
    getBoundingClientRect() { return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight }; }
    replaceChildren(...children) { this.children = children; }
    querySelector() { return null; }
  }

  const doc = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element(id));
      return elements.get(id);
    },
    createElement() { return new Element(); },
    querySelectorAll(selector) {
      if (selector !== '[data-days]') return [];
      return [20, 60, 120, 250].map(days => {
        const button = new Element();
        button.dataset.days = String(days);
        return button;
      });
    },
  };
  let onChange;
  const window = {
    document: doc,
    location: { search: '' },
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
  vm.runInNewContext(source, { window, URLSearchParams });
  window.StockView.mount({ document: doc, api: {} });

  return {
    elements,
    onChange,
    setMarket(price) {
      onChange({
        code: '600519',
        market: { name: '贵州茅台', asof: price.at(-1).date, source: 'test', price },
        current: null,
        history: null,
        tasks: [],
        recent: [],
        issues: {},
        marketStatus: 'ready',
        currentStatus: 'current_ready',
        historyStatus: 'idle',
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
