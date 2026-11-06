'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const chart = require('../app/candle-chart.js');

function harness(demo = true, search = '?demo=1', track = false) {
  const nodes = new Map(), values = new Map(), calls = [], renders = [];
  const element = () => ({ hidden: false, textContent: '', value: '',
    events: {}, attrs: {}, classList: { add() {} },
    addEventListener(name, fn) { this.events[name] = fn; },
    setAttribute(name, value) { this.attrs[name] = value; }, replaceChildren() {} });
  const node = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  let config, currentUrl, visibilityConfig;
  const api = { isDemo: demo, codes: ['600519'] };
  const root = { document: { getElementById: node, querySelectorAll: () => [],
    createElement: element, body: element() }, CandleChart: chart,
    localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) },
    location: { href: 'http://localhost/stock.html' + search, search },
    history: { replaceState(_state, _title, url) { currentUrl = url; } }, addEventListener() {},
    StockSession: { compatible: () => true, stale: () => false, create(options) {
      config = options;
      return { select: code => calls.push(code), request() {}, resume() {}, destroy() {} };
    } } };
  if (track) root.StockVisibility = { mount(options) {
    visibilityConfig = options;
    return { set() {}, records: () => [], destroy() {} };
  } };
  vm.runInNewContext(fs.readFileSync(require.resolve('../app/stock-view.js'), 'utf8'),
    { window: root, URL, URLSearchParams });
  root.StockView.mount({ api, renderResult: value => renders.push(value) });
  const current = { code: '600519', asof: '2026-10-23', demo };
  const update = changes => config.onChange({ code: '600519', market: null, marketStatus: 'loading',
    current, currentStatus: 'ready', history: null, historyStatus: 'idle', issues: {}, tasks: [], recent: [], ...changes });
  return { node, values, calls, renders, update, current, config, visibilityConfig, url: () => currentUrl };
}

test('first-visible note belongs to the displayed stock and resets on a different result or stock', () => {
  const h = harness(false, '', true);
  h.update({});
  h.visibilityConfig.onVisible({ identity: { symbol: 'sh600519', window: { start: '2026-11-16', end: '2026-11-20' } },
    first_visible_at_client: '2026-11-06T08:00:00Z', is_cached: true, storage_status: 'BROWSER_LOCAL' });
  assert.match(h.node('visibility-note').textContent, /sh600519.*2026-11-16/);
  h.update({ code: '000001', current: null });
  assert.doesNotMatch(h.node('visibility-note').textContent, /sh600519/);
  assert.match(h.node('visibility-note').textContent, /尚无/);
  h.update({ code: '000001', current: { symbol: 'sz000001', asof: '2026-11-06' } });
  h.visibilityConfig.onVisible({ identity: { symbol: 'sz000001', window: { start: '2026-10-01', end: '2026-10-05' } },
    first_visible_at_client: '2026-11-06T08:00:00Z', is_cached: true, date_relation_at_client_observation: 'PAST_WINDOW', storage_status: 'BROWSER_LOCAL' });
  assert.match(h.node('visibility-note').textContent, /sz000001.*已过期/);
});

test('an active demo task takes precedence over a retained completed result in the overall status', () => {
  const h = harness();
  h.update({});
  assert.match(h.node('query-status').textContent, /演示已完成/);
  h.update({ currentStatus: 'queued', historyStatus: 'running' });
  assert.match(h.node('query-status').textContent, /上一轮演示记录保留；新任务正在演示/);
  assert.doesNotMatch(h.node('query-status').textContent, /演示已完成/);
  assert.match(h.node('current-stage').textContent, /演示排队中/);
  assert.equal(h.renders.length, 1, 'the last completed card stays mounted during subsequent jobs');
  h.update({ historyStatus: 'queued' });
  assert.match(h.node('query-status').textContent, /新任务正在演示/);
  h.update({ historyStatus: 'ready' });
  assert.match(h.node('query-status').textContent, /演示已完成 · 未运行模型/);
});

test('welcome requires a code; unsupported demo input neither selects nor navigates', () => {
  const h = harness();
  assert.deepEqual(h.calls, []);
  h.node('code').value = '000001';
  h.node('search').events.submit({ preventDefault() {} });
  assert.deepEqual(h.calls, []);
  assert.equal(h.url(), undefined);
  assert.match(h.node('search-error').textContent, /仅包含600519/);
  h.node('code').value = '600519';
  h.node('search').events.submit({ preventDefault() {} });
  assert.deepEqual(h.calls, ['600519']);
  assert.equal(h.url().searchParams.get('demo'), '1');
  assert.equal(h.url().searchParams.get('code'), '600519');
});

test('input rejection survives old-asset asynchronous updates until a valid selection', () => {
  const h = harness();
  h.update({});
  h.node('code').value = '000001';
  h.node('search').events.submit({ preventDefault() {} });
  const message = h.node('search-error').textContent;
  assert.match(message, /当前仍显示 600519，未切换至 000001/);
  assert.equal(h.node('code').attrs['aria-invalid'], 'true');
  h.update({ currentStatus: 'queued' });
  h.update({ historyStatus: 'ready' });
  assert.equal(h.node('search-error').textContent, message);
  assert.equal(h.node('search-error').hidden, false);
  assert.deepEqual(h.calls, []);
  assert.equal(h.node('code').value, '000001');
  h.node('code').value = '600519';
  h.node('search').events.submit({ preventDefault() {} });
  assert.equal(h.node('search-error').hidden, true);
  assert.equal(h.node('search-error').textContent, '');
  assert.equal(h.node('code').attrs['aria-invalid'], 'false');
  assert.deepEqual(h.calls, ['600519']);
});

test('demo session persistence cannot overwrite the live job ledger', () => {
  const h = harness();
  h.values.set('lppl.stock.jobs.v1', 'live tasks');
  h.config.storage.setItem('lppl.stock.jobs.v1', 'presentation tasks');
  assert.equal(h.values.get('lppl.stock.jobs.v1'), 'live tasks');
  assert.equal(h.values.get('presentation.lppl.stock.jobs.v1'), 'presentation tasks');
});

test('live mode keeps its adapter, storage and existing result rendering path', () => {
  const h = harness(false, '?code=600519');
  assert.deepEqual(h.calls, ['600519']);
  assert.equal(h.config.api.isDemo, false);
  h.config.storage.setItem('lppl.stock.jobs.v1', 'live tasks');
  assert.equal(h.values.get('lppl.stock.jobs.v1'), 'live tasks');
  h.update({});
  assert.equal(h.renders[0], h.current);
  assert.match(h.node('query-status').textContent, /分析截至 2026-10-23/);
  assert.doesNotMatch(h.node('query-status').textContent, /演示/);
});
