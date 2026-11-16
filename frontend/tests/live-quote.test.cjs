'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const adapterSource = fs.readFileSync(path.join(__dirname, '..', 'app', 'lppl-data.js'), 'utf8');
const headerSource = fs.readFileSync(path.join(__dirname, '..', 'app', 'stock-header.js'), 'utf8');

function response(value, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => value };
}

function setup(handler = async () => response({ quotes: {} })) {
  const requests = [], timers = new Map();
  let nextTimer = 0;
  const window = { LPPL_DATA_BASE: '/snapshots/', LPPL_QUERY_API: 'https://query.example.test/' };
  const context = vm.createContext({
    window, AbortController, Date, Intl,
    fetch: (url, options) => { requests.push({ url, options }); return handler(url, options); },
    setTimeout: (fn, delay) => { const id = ++nextTimer; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(adapterSource, context, { filename: 'lppl-data.js' });
  vm.runInContext(headerSource, context, { filename: 'stock-header.js' });
  return { api: window.LPPL, header: window.StockHeader, requests, timers };
}

test('LPPL.quote maps supported symbols to worker codes and maps results back', async () => {
  const payload = {
    source: 'tencent',
    fetched_at: '2026-11-13T08:15:00.000Z',
    quotes: {
      sh600519: { price: 100 },
      sz000001: { price: 10 },
      sh000688: { price: 20 },
      usAAPL: { price: 200 },
    },
    missing: [],
  };
  const h = setup(async () => response(payload));
  const result = await h.api.quote(['sh600519', 'sz000001', 'sh000688', 'US_AAPL', 'us_aapl', 'not-a-symbol']);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url,
    'https://query.example.test/quote?codes=sh600519%2Csz000001%2Csh000688%2CusAAPL');
  assert.deepEqual(Object.keys(result.quotes), ['sh600519', 'sz000001', 'sh000688', 'US_AAPL']);
  assert.equal(result.quotes.US_AAPL.price, 200);
  assert.equal(result.source, 'tencent');
});

test('LPPL.quote maps missing codes and skips unsupported or empty symbol lists', async () => {
  const h = setup(async () => response({
    quotes: { sh600519: { price: 100 } },
    missing: ['sh000688'],
  }));
  const result = await h.api.quote(['sh600519', 'sh000688', 'SPY']);
  assert.equal(result.quotes.sh600519.price, 100);
  assert.equal(result.missing[0], 'sh000688');
  assert.equal(JSON.stringify(await h.api.quote([])), '{"quotes":{}}');
  assert.equal(JSON.stringify(await h.api.quote(['unsupported'])), '{"quotes":{}}');
  assert.equal(h.requests.length, 1);
});

test('quote time labels require same-day trading-session timestamps in the exchange timezone', () => {
  const label = setup().header.quoteTimeLabel;
  const shanghai = label('20261113103000', 'Asia/Shanghai', new Date('2026-11-13T02:31:00Z'));
  assert.equal(shanghai.label, '盘中');
  assert.equal(shanghai.time, '11-13 10:30');
  assert.equal(shanghai.short, '10:30');
  assert.equal(label('20261113103000', 'Asia/Shanghai', new Date('2026-11-13T08:00:00Z')).label, '最新成交');
  assert.equal(label('20261113103000', 'Asia/Shanghai', new Date('2026-11-16T02:31:00Z')).label, '最新成交');
  assert.equal(label('2026-11-13 10:00:00', 'America/New_York', new Date('2026-11-13T15:01:00Z')).label, '盘中');
  assert.equal(label('2026-11-13 10:00:00', 'America/New_York', new Date('2026-11-13T21:01:00Z')).label, '最新成交');
});
