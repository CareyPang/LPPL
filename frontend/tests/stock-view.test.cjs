'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const chart = require('../app/candle-chart.js');
const analysis = require('../app/stock-analysis.js');
const workstationLedger = require('../app/workstation-ledger.js');

function harness(demo = true, search = '?demo=1', track = false, apiOverrides = {}) {
  const nodes = new Map(), values = new Map(), calls = [], renders = [], requests = [], chartCalls = [];
  const element = () => ({ hidden: false, textContent: '', value: '',
    events: {}, attrs: {}, classList: { add() {} },
    addEventListener(name, fn) { this.events[name] = fn; },
    focus(options) { this.focusOptions = options; }, scrollIntoView(options) { this.scrollOptions = options; },
    setAttribute(name, value) { this.attrs[name] = value; }, replaceChildren(...nodes) { this.children = nodes; } });
  const node = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  let config, currentUrl, visibilityConfig;
  const api = { isDemo: demo, codes: ['600519'], ...apiOverrides };
  const root = { document: { getElementById: node, querySelectorAll: () => [],
    querySelector: selector => selector.startsWith('#analysis-summary ') ? node('focused-analysis-card') : null,
    createElement: element, body: element() }, CandleChart: { ...chart, draw(canvas, bars, selected, options) {
      chartCalls.push({ bars, selected, options });
      return { indexAt: () => 0, isFutureAt: x => x > 250 };
    } }, StockAnalysis: { normalize: analysis.normalize, render(node, view) { node.analysis = view; } },
    WorkstationLedger: workstationLedger,
    localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value),
      get length() { return values.size; }, key: index => [...values.keys()][index] ?? null },
    location: { href: 'http://localhost/stock.html' + search, search },
    history: { replaceState(_state, _title, url) { currentUrl = url; } }, addEventListener() {},
    StockSession: { compatible: () => true, stale: () => false, create(options) {
      config = options;
      return { select: code => calls.push(code), request: (...args) => requests.push(args), resume() {}, destroy() {} };
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
  return { node, values, calls, renders, requests, chartCalls, update, current, config, visibilityConfig, url: () => currentUrl };
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

test('research preview storage isolates resumable jobs and visibility exports from production and presentation', () => {
  const h = harness(false, '', false, { isResearchPreview: true });
  h.values.set('lppl.stock.jobs.v1', 'production jobs');
  h.values.set('presentation.lppl.stock.jobs.v1', 'demo jobs');
  h.values.set('lppl.stock.first-visible.v1.prod', 'production observation');
  assert.equal(h.config.storage.getItem('lppl.stock.jobs.v1'), undefined);
  h.config.storage.setItem('lppl.stock.jobs.v1', 'preview jobs');
  h.config.storage.setItem('lppl.stock.first-visible.v1.preview', 'preview observation');
  assert.equal(h.values.get('research-preview.lppl.stock.jobs.v1'), 'preview jobs');
  assert.equal(h.values.get('lppl.stock.jobs.v1'), 'production jobs');
  assert.equal(h.values.get('presentation.lppl.stock.jobs.v1'), 'demo jobs');
  assert.equal(h.config.storage.length, 2);
  assert.deepEqual(Array.from({ length: h.config.storage.length }, (_, i) => h.config.storage.key(i)),
    ['lppl.stock.jobs.v1', 'lppl.stock.first-visible.v1.preview']);
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

test('preview names resolve to canonical assets and ambiguous bare index codes retain the displayed asset', () => {
  const h = harness(false, '', false, { resolveCode(input) {
    if (input === '贵州茅台' || input === '600519') return 'sh600519';
    if (input === '上证指数' || input === 'sh000001') return 'sh000001';
    throw Error('000001 有歧义，请选择上证指数或带交易所前缀的代码。');
  } });
  h.node('code').value = '贵州茅台';
  h.node('search').events.submit({ preventDefault() {} });
  assert.deepEqual(h.calls, ['sh600519']);
  assert.equal(h.url().searchParams.get('code'), 'sh600519');
  h.update({ code: 'sh600519', current: null });
  h.node('code').value = '000001';
  h.node('search').events.submit({ preventDefault() {} });
  assert.equal(h.calls.length, 1);
  assert.match(h.node('search-error').textContent, /有歧义.*当前仍显示 sh600519/);
});

test('a preview without history support never starts an implicit or clicked 104-week task', () => {
  const h = harness(false, '', false, { historySupported: false });
  h.update({});
  assert.equal(h.node('compute-history').hidden, true);
  assert.equal(h.node('compute-history').disabled, true);
  h.node('compute-history').events.click();
  assert.deepEqual(h.requests, []);
  assert.match(h.node('history-note').textContent, /不会自动启动104周/);
});

test('a real candidate reaches both the summary and candle options; future hover never invents a price readout', () => {
  const h = harness(false, '');
  const result = { symbol: 'sh600519', asof: '2026-11-06', analysis: {
    status: 'research_candidate', evidence: 'research_candidate', as_of: '2026-11-06', minimum_full_cycles: 1.5,
    windows: [{ start: '2026-11-16', end: '2026-11-20', evidence: 'research_candidate' }] } };
  h.update({ current: result, marketStatus: 'ready', market: { symbol: 'sh600519', asof: '2026-11-06',
    adjustment: 'qfq', price: [{ date: '2026-11-06', open: 10, high: 11, low: 9, close: 10, volume: 30 }] } });
  assert.equal(h.node('analysis-summary').analysis.windows[0].start, '2026-11-16');
  assert.equal(h.chartCalls.at(-1).options.analysis.windows[0].end, '2026-11-20');
  const legend = h.node('forecast-legend');
  assert.equal(legend.hidden, false);
  assert.equal(legend.children[0].children[0].textContent, '观察①');
  assert.equal(legend.children[0].children[1].textContent, '2026-11-16 — 2026-11-20');
  legend.children[0].events.click();
  assert.equal(h.node('focused-analysis-card').tabIndex, -1);
  assert.equal(h.node('focused-analysis-card').focusOptions.preventScroll, true);
  assert.equal(h.node('focused-analysis-card').scrollOptions.block, 'center');
  h.node('market-plot').events.pointermove({ clientX: 300, clientY: 100,
    currentTarget: { getBoundingClientRect: () => ({ left: 0, top: 0 }) } });
  assert.match(h.node('quote-readout').textContent, /没有未来价格或成交量/);
  assert.equal(h.node('chart-tooltip').hidden, true);
  assert.equal(h.chartCalls.at(-1).selected, -1);
});

test('P0 ledger is connected to the workstation view and exposes watch/revision provenance', () => {
  const h = harness(false, '');
  const result = { symbol: 'sh600519', asof: '2026-11-06', source_sha: 'sha-1', evidence: 'research_candidate', analysis: {
    status: 'research_candidate', evidence: 'research_candidate', as_of: '2026-11-06',
    windows: [{ start: '2026-11-16', end: '2026-11-20', claim_kind: 'new', evidence: 'research_candidate' }],
  } };
  h.update({ current: result, marketStatus: 'ready', market: { symbol: 'sh600519', name: '贵州茅台', asof: '2026-11-06', source: 'fixture', price: [] } });
  assert.equal(h.node('workstation-ledger').hidden, false);
  assert.match(h.node('ledger-meta').textContent, /行情截至 2026-11-06.*来源 fixture.*证据 research_candidate/);
  assert.equal(h.node('revision-ledger').children.length, 1);
  h.node('watch-toggle').events.click();
  assert.match(h.node('watch-toggle').textContent, /移出自选/);
  assert.equal(h.node('watchlist').children.length, 1);
});
