'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const api = require('../app/history-comparison-editorial.js');

const frame = (asof, overrides = {}) => ({ asof, close: 1234.56, split: 'dev', w: { '6-12m': ['2007-11-16', '2007-11-30'], '12-24m': null }, ...overrides });
const history = (symbol = 'sh000001') => ({ symbol, evidence: 'dev_only', model_version: 'recorded-v1', frames: [
  frame('2007-10-12'), frame('2015-06-12', { close: 5166.35, w: { '6-12m': ['2015-07-23', '2015-08-17'], '12-24m': ['2015-06-25', '2015-07-16'] } })
] });

test('only real published dates are accepted, sorted, and deduplicated', () => {
  const H = { frames: [frame('2015-06-12'), frame('2007-10-12'), frame('2015-06-12', { close: 55 }), frame('2023-02-29'), frame('2024-02-29'), frame('2024-03-01', { close: null })] };
  const rows = api.records(H);
  assert.deepEqual(rows.map(row => row.asof), ['2007-10-12', '2015-06-12', '2024-02-29']);
  assert.equal(rows[1].close, 55);
  assert.equal(api.comparison(H, '2008-01-01', '2015-06-12'), null);
  assert.equal(api.date('2024-02-29'), true);
  assert.equal(api.date('2024-02-30'), false);
});

test('default comparison uses published 2007 and 2015 cutoffs, never inventing unavailable replay dates', () => {
  assert.deepEqual(api.defaults(api.records(history()), 'sh000001'), ['2007-10-12', '2015-06-12']);
  const H = { frames: [frame('2020-01-06', { w: {} }), frame('2020-01-13'), frame('2020-01-20'), frame('2020-01-27', { w: {} })] };
  assert.deepEqual(api.defaults(api.records(H), 'sh000300'), ['2020-01-13', '2020-01-20']);
  assert.deepEqual(api.defaults([], 'sh000300'), ['', '']);
});

test('changed highlights reflect displayed differences; equal missing data is not a difference', () => {
  const result = api.comparison(history(), '2007-10-12', '2015-06-12');
  assert.deepEqual(result.rows.filter(row => row.changed).map(row => row.key), ['asof', 'close', 'window6', 'window12']);
  assert.equal(result.rows.find(row => row.key === 'model').changed, false);
  assert.equal(result.rows.find(row => row.key === 'sample').a, '记录未提供');
  assert.equal(result.rows.find(row => row.key === 'validation').a, '历史帧未提供独立验证结果');
  const same = api.comparison(history(), '2007-10-12', '2007-10-12');
  assert.equal(same.same, true);
  assert.equal(same.rows.some(row => row.changed), false);
});

test('historical dev_only permits intervals but never confidence or sample numbers; failed and unknown evidence fail closed', () => {
  const H = history();
  const f = frame('2007-10-12', { n: 98765, conf: { '6-12m': .98765 } });
  const dev = api.fieldValues(f, H);
  assert.match(dev.find(row => row[0] === 'window6')[2], /2007-11-16 至 2007-11-30/);
  assert.equal(JSON.stringify(dev).includes('98765'), false);
  for (const ev of ['none', 'fail', 'fail_future', 'dev_failed', 'pending_cal', 'pending_test', 'unknown']) {
    const rows = api.fieldValues({ ...f, evidence: ev }, H);
    assert.equal(rows.find(row => row[0] === 'window6')[2], '当前证据等级不展示区间', ev);
    assert.equal(JSON.stringify(rows).includes('98765'), false, ev);
  }
  assert.match(dev.find(row => row[0] === 'close')[2], /1,234\.56/);
});

test('descriptive intervals require a positive actual sample count and carry interpretation', () => {
  for (const n of [null, undefined, 0, -1]) {
    const rows = api.fieldValues(frame('2007-10-12', { evidence: 'descriptive', n }), history());
    assert.equal(rows.find(row => row[0] === 'window6')[2], '当前证据等级不展示区间');
  }
  const rows = api.fieldValues(frame('2007-10-12', { evidence: 'descriptive', n: 12 }), history());
  assert.equal(rows.find(row => row[0] === 'sample')[2], 'n=12');
  assert.equal(rows.find(row => row[0] === 'interpretation')[2], '历史分位，不是预测');
  assert.match(rows.find(row => row[0] === 'window6')[2], /2007-11-16/);
});

test('full workstation links are restricted to adapter replay availability and retain the selected symbol', () => {
  const replays = { sh000001: ['2007-10-12', '2015-06-12'] };
  assert.equal(api.replayLink('sh000001', '2007-10-12', replays), 'workstation-editorial.html?code=sh000001&asof=2007-10-12');
  assert.equal(api.replayLink('sh000300', '2007-10-12', replays), null);
  assert.equal(api.replayLink('sh000001', '2007-10-19', replays), null);
});

test('index changes clear both dates and selected frame; stale loads/selections cannot repopulate them', () => {
  const controller = api.createState(), oldH = history(), newH = history('sh000300');
  controller.reset('sh000001');
  assert.equal(controller.ready({ symbol: 'sh000001', H: oldH }, { symbol: 'sh000001', H: oldH }), true);
  assert.equal(controller.select({ symbol: 'sh000001', H: oldH, frame: oldH.frames[0] }), true);
  controller.reset('sh000300');
  assert.deepEqual([controller.state.a, controller.state.b, controller.state.selected], ['', '', '']);
  assert.equal(controller.ready({ symbol: 'sh000001', H: oldH }, { symbol: 'sh000300', H: null }), false);
  assert.equal(controller.select({ symbol: 'sh000001', H: oldH, frame: oldH.frames[0] }), false);
  assert.equal(controller.ready({ symbol: 'sh000300', H: newH }, { symbol: 'sh000300', H: newH }), true);
  assert.equal(controller.ready({ symbol: 'sh000300', H: newH }, { symbol: 'sh000300', H: null }), false);
  assert.equal(controller.set('a', '2010-01-01'), false);
  controller.swap();
  assert.deepEqual([controller.state.a, controller.state.b], ['2015-06-12', '2007-10-12']);
});

function domHarness() {
  const nodes = new Map(), listeners = new Map();
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, { id, value: '', innerHTML: '', textContent: '', hidden: false, disabled: false, handlers: {},
      addEventListener(type, fn) { this.handlers[type] = fn; },
      dispatch(type, extra = {}) { const event = { target: this, currentTarget: this, ...extra }; this.handlers[type](event); },
      scrollIntoView() { this.scrolled = true; }
    });
    return nodes.get(id);
  }
  const host = { innerHTML: '', classList: { add() {} }, querySelector(selector) { return node(selector.slice(1)); } };
  const calls = [], win = {
    LPPL: { resolve: code => ({ name: code === 'sh000001' ? '上证指数' : '沪深300' }), REPLAYS: { sh000001: ['2007-10-12', '2015-06-12'] } },
    document: { getElementById: node }, matchMedia: () => ({ matches: true }),
    current: { symbol: 'sh000001', H: null },
    addEventListener(name, fn) { listeners.set(name, fn); },
    removeEventListener(name) { listeners.delete(name); },
    dispatch(name, detail) { listeners.get(name)({ detail }); }
  };
  win.LPPLHistoryPreview = { getContext: () => win.current, selectFrame: (...args) => calls.push(['select', ...args]), showDates: (...args) => calls.push(['both', ...args]) };
  const mount = api.mount(host, win);
  return { host, win, node, calls, mount, listeners };
}

test('live controls update comparison, selection pin, swap, and chart links without fetching or losing current index', () => {
  const h = domHarness(), H = history();
  assert.equal(h.node('hc-body').hidden, true);
  h.win.current = { symbol: 'sh000001', H };
  h.win.dispatch('lppl-history-ready', h.win.current);
  assert.equal(h.node('hc-body').hidden, false);
  assert.equal(h.node('hc-date-a').value, '2007-10-12');
  assert.equal(h.node('hc-date-b').value, '2015-06-12');
  h.win.dispatch('lppl-history-select', { ...h.win.current, frame: H.frames[1] });
  assert.equal(h.node('hc-selected').textContent, '最近查看：2015-06-12');
  assert.equal(h.node('hc-use-a').disabled, false);
  h.node('hc-use-a').dispatch('click');
  assert.match(h.node('hc-status').textContent, /同一截止日/);
  h.node('hc-date-a').value = '2007-10-12'; h.node('hc-date-a').dispatch('change');
  h.node('hc-swap').dispatch('click');
  assert.equal(h.node('hc-date-b').value, '2007-10-12');
  h.node('hc-show-b').dispatch('click');
  assert.equal(h.calls[0][1], '2007-10-12');
  h.node('hc-show-both').dispatch('click');
  assert.deepEqual(h.calls[1], ['both', '2015-06-12', '2007-10-12']);
  assert.equal(h.node('chart').scrolled, true);
  h.win.current = { symbol: 'sh000300', H: null };
  h.win.dispatch('lppl-history-reset', h.win.current);
  assert.equal(h.node('hc-body').hidden, true);
  assert.equal(h.node('hc-rows').innerHTML, '');
  assert.equal(h.node('hc-use-a').disabled, true);
  h.mount.destroy();
  assert.equal(h.listeners.size, 0);
});

test('record strings are escaped in markup; arbitrary model/data text never becomes executable HTML', () => {
  const h = domHarness(), H = history();
  H.model_version = '<img src=x onerror="alert(1)">';
  h.win.current = { symbol: 'sh000001', H };
  h.win.dispatch('lppl-history-ready', h.win.current);
  const markup = h.node('hc-rows').innerHTML;
  assert.equal(markup.includes('<img'), false);
  assert.match(markup, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
  assert.equal(api.E("<>&\"'"), '&lt;&gt;&amp;&quot;&#39;');
});
