'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const frontend = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(frontend, 'backtest-editorial.html'), 'utf8');
const inline = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1].replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(frontend, 'app', 'lppl-data.js'), 'utf8');
const marketModule = fs.readFileSync(path.join(frontend, 'app', 'backtest-market-editorial.js'), 'utf8');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function record(symbol, { evidence = 'dev_only', empty = false } = {}) {
  return {
    symbol, evidence, model_version: 'recorded-model', rule: '情景，非时点', tops: [],
    frames: empty ? [] : [
      { asof: '2020-01-06', split: 'cal', close: 100, conf: { '6-12m': .87 }, w: { '6-12m': ['2020-02-03', '2020-03-02'] } },
      { asof: '2020-01-13', split: 'cal', close: 110, conf: { '6-12m': .91 }, w: { '6-12m': null } },
      { asof: '2020-01-20', split: 'cal', close: 105, conf: { '6-12m': .93 }, w: { '6-12m': ['2020-03-02', '2020-03-16'] } }
    ]
  };
}

function setup({ mobile = false, reducedMotion = false, search = '', waitForMarket = false } = {}) {
  const nodes = new Map(), documentListeners = new Map(), requests = [], marketRequests = [], events = [];
  const drawing = new Proxy({}, { get(target, key) { return key in target ? target[key] : () => {}; } });
  const document = {
    activeElement: null,
    documentElement: {},
    getElementById(id) { return nodes.get(id); },
    querySelectorAll() { return []; },
    addEventListener(type, callback) {
      if (!documentListeners.has(type)) documentListeners.set(type, []);
      documentListeners.get(type).push(callback);
    }
  };
  for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {
    const listeners = new Map();
    const node = {
      id, hidden: ['frame-detail', 'retry', 'tip'].includes(id), disabled: false,
      value: '', innerHTML: '', textContent: '', width: 800, height: 380,
      style: {}, attributes: {}, isConnected: true,
      classList: { add() {}, remove() {} },
      setAttribute(name, value) { this.attributes[name] = String(value); },
      getAttribute(name) { return this.attributes[name]; },
      addEventListener(type, callback) {
        if (!listeners.has(type)) listeners.set(type, []);
        listeners.get(type).push(callback);
      },
      dispatch(type, event = {}) {
        const e = { target: this, currentTarget: this, button: 0, pointerId: 1, isPrimary: true, clientX: 100, clientY: 100, preventDefault() { this.defaultPrevented = true; }, ...event };
        for (const fn of listeners.get(type) || []) fn(e);
        return e;
      },
      focus() { document.activeElement = this; },
      scrollIntoView(options) { this.lastScroll = options; },
      getBoundingClientRect() { return { left: 0, top: 0, width: 800, height: this.id === 'ov' ? 64 : 380 }; },
      getContext() { return drawing; },
      setPointerCapture() {}
    };
    nodes.set(id, node);
  }
  const location = { search, href: 'https://example.test/backtest-editorial.html' + search };
  const context = vm.createContext({
    document, window: { devicePixelRatio: 1, addEventListener() {}, dispatchEvent(event) { events.push(event); } },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    location,
    history: { replaceState(_state, _title, url) { location.href = String(url); location.search = new URL(url).search; } }, URL, URLSearchParams,
    matchMedia(query) { return { matches: query.includes('reduced-motion') ? reducedMotion : mobile }; },
    getComputedStyle() { return { getPropertyValue: () => '#123456' }; },
    CPSCN: { rgba: () => '#123456', isDense: () => false, drawRange() {}, drawTop() {} },
    requestAnimationFrame() {}, cancelAnimationFrame() {}
  });
  vm.runInContext(adapter, context);
  context.LPPL = context.window.LPPL;
  vm.runInContext(marketModule, context);
  context.LPPLMarket = context.window.LPPLMarket;
  context.LPPLMarket.load = symbolAdapter => {
    if (!waitForMarket) return Promise.resolve({ bars: [], ranges: [], snapshots: [], failures: [] });
    const pending = deferred(); marketRequests.push(pending); return pending.promise;
  };
  context.LPPL.history = symbol => { const pending = deferred(); requests.push({ symbol, ...pending }); return pending.promise; };
  const ending = '  load();\n})();';
  assert.ok(inline.includes(ending), 'Expose the actual page functions without starting a network request');
  vm.runInContext(inline.replace(ending, '  globalThis.page = { st, load, selectFrame, closeDetails, detailRows, hitFrame, setView };\n})();'), context);
  return {
    page: context.page, nodes, requests, marketRequests, events, document, location,
    key(event) { const e = { preventDefault() {}, ...event }; for (const fn of documentListeners.get('keydown') || []) fn(e); },
    async load(symbol = 'sh000001', payload = record(symbol)) {
      context.page.st.sym = symbol;
      const promise = context.page.load();
      requests[requests.length - 1].resolve(payload);
      await promise;
    }
  };
}

test('the newest index owns the chart and title after responses arrive out of order', async () => {
  const s = setup();
  s.page.st.sym = 'sh000001'; const first = s.page.load();
  s.page.st.sym = 'sh000300'; const second = s.page.load();
  assert.deepEqual(s.requests.map(r => r.symbol), ['sh000001', 'sh000300']);
  s.requests[1].resolve(record('sh000300')); await second;
  s.requests[0].resolve(record('sh000001')); await first;
  assert.equal(s.page.st.H.symbol, 'sh000300');
  assert.equal(s.nodes.get('sym-n').textContent, '沪深300');
  assert.equal(s.nodes.get('ld').hidden, true);
  assert.equal(s.nodes.get('workstation-link').href, 'workstation-editorial.html?code=sh000300');
});

test('an obsolete failure cannot erase a newer success or replace its evidence', async () => {
  const s = setup();
  s.page.st.sym = 'sh000001'; const first = s.page.load();
  s.page.st.sym = 'sh000300'; const second = s.page.load();
  s.requests[1].resolve(record('sh000300')); await second;
  const evidence = s.nodes.get('ev').innerHTML;
  s.requests[0].reject(new Error('old request failed')); await first;
  assert.equal(s.page.st.H.symbol, 'sh000300');
  assert.equal(s.nodes.get('ev').innerHTML, evidence);
  assert.equal(s.nodes.get('retry').hidden, true);
  assert.equal(s.nodes.get('chart').attributes['aria-busy'], 'false');
});

test('the return link preserves a supported replay date and removes it when changing index', async () => {
  const s = setup({ search: '?code=sh000001&asof=2015-06-12' });
  await s.load();
  assert.equal(s.nodes.get('workstation-link').href, 'workstation-editorial.html?code=sh000001&asof=2015-06-12');
  assert.equal(new URL(s.location.href).searchParams.get('asof'), '2015-06-12');
  s.page.st.sym = 'sh000300'; const pending = s.page.load();
  assert.equal(s.nodes.get('workstation-link').href, 'workstation-editorial.html?code=sh000300');
  assert.equal(new URL(s.location.href).searchParams.has('asof'), false, 'Clear unsupported context even before data arrives');
  s.requests[1].resolve(record('sh000300')); await pending;
  await s.load('sh000001');
  assert.equal(new URL(s.location.href).searchParams.has('asof'), false, 'Switching back does not silently revive an old replay');
});

test('unsupported incoming replay dates are removed from both navigation and the page URL', async () => {
  for (const [symbol, date] of [['sh000001', '2020-01-06'], ['sh000300', '2015-06-12']]) {
    const s = setup({ search: '?code=' + symbol + '&asof=' + date });
    await s.load(symbol);
    assert.equal(s.nodes.get('workstation-link').href, 'workstation-editorial.html?code=' + symbol);
    assert.equal(new URL(s.location.href).searchParams.has('asof'), false);
  }
});

test('loading clears old selections, and retry belongs to the current failed index', async () => {
  const s = setup(); await s.load();
  s.page.selectFrame('2020-01-06', s.nodes.get('cv'));
  s.page.st.sym = 'sh000300'; const failed = s.page.load();
  assert.equal(s.page.st.H, null);
  assert.equal(s.nodes.get('frame-detail').hidden, true);
  assert.equal(s.nodes.get('frame-select').disabled, true);
  assert.equal(s.nodes.get('chart').attributes['aria-busy'], 'true');
  s.requests[1].reject(new Error('HTTP 503')); await failed;
  assert.match(s.nodes.get('load-message').textContent, /沪深300.*数据未加载/);
  assert.equal(s.nodes.get('retry').hidden, false);
  s.nodes.get('retry').dispatch('click');
  assert.equal(s.requests[2].symbol, 'sh000300');
  s.requests[2].resolve(record('sh000300'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(s.page.st.H.symbol, 'sh000300');
  assert.equal(s.nodes.get('retry').hidden, true);
});

test('empty history has a truthful empty state rather than a market signal or stale chart', async () => {
  const s = setup(); await s.load('sh000001', record('sh000001', { empty: true }));
  assert.equal(s.page.st.H, null);
  assert.match(s.nodes.get('load-message').textContent, /没有可展示的截止日/);
  assert.match(s.nodes.get('ev').textContent, /不据此判断有无市场信号/);
  assert.equal(s.nodes.get('frame-open').disabled, true);
});

test('details use the selected recorded interval and do not expose dev-only confidence or invent sample size', async () => {
  const s = setup(); await s.load();
  const trigger = s.nodes.get('frame-open');
  assert.equal(s.page.selectFrame('2020-01-06', trigger), true);
  assert.equal(s.page.st.selected.asof, '2020-01-06');
  assert.match(s.nodes.get('detail-fields').innerHTML, /2020-02-03 至 2020-03-02/);
  assert.match(s.nodes.get('detail-fields').innerHTML, /样本数<\/dt><dd>记录未提供/);
  assert.doesNotMatch(s.nodes.get('detail-fields').innerHTML, /87%|0\.87|91%|0\.91/);
  assert.equal(s.page.selectFrame('2020-01-07', trigger), false, 'No fabricated daily records');
  assert.equal(s.page.st.selected.asof, '2020-01-06');
  assert.equal(s.document.activeElement.id, 'detail-heading');
  assert.equal(s.nodes.get('detail-heading').lastScroll.block, 'nearest', 'Desktop headings also scroll into view');
  s.key({ key: 'Escape' });
  assert.equal(s.nodes.get('frame-detail').hidden, true);
  assert.equal(s.document.activeElement, trigger);
  assert.equal(trigger.lastScroll.block, 'nearest', 'The restored trigger is visible');
});

test('native date selection and adjacent-date buttons only visit available records', async () => {
  const s = setup(); await s.load();
  const select = s.nodes.get('frame-select');
  select.value = '2020-01-13'; select.focus(); select.dispatch('change');
  assert.equal(s.page.st.selected.asof, '2020-01-13');
  assert.match(s.nodes.get('detail-fields').innerHTML, /该日未提供区间/);
  assert.equal(s.document.activeElement, select);
  s.nodes.get('frame-prev').dispatch('click');
  assert.equal(s.page.st.selected.asof, '2020-01-06');
  assert.equal(s.nodes.get('frame-prev').disabled, true);
  s.nodes.get('frame-next').dispatch('click');
  assert.equal(s.page.st.selected.asof, '2020-01-13');
});

test('sample counts obey evidence visibility and descriptive text accompanies any displayed count', async () => {
  const s = setup(); await s.load();
  const f = { ...s.page.st.H.fr[0], n: 12 };
  for (const evidence of ['none', 'dev_only', 'dev_failed', 'fail_i', 'fail_new']) {
    assert.ok(!JSON.stringify(s.page.detailRows(f, { evidence })).includes('n=12'), evidence);
  }
  const rows = JSON.stringify(s.page.detailRows(f, { evidence: 'descriptive' }));
  assert.match(rows, /n=12/);
  assert.match(rows, /历史分位，不是预测/);
});

test('none and failure evidence hide interval dates and sample counts while dev-only keeps only its historical interval exception', async () => {
  const s = setup(); await s.load();
  const f = { ...s.page.st.H.fr[0], n: 12 };
  for (const evidence of ['none', 'dev_failed', 'fail', 'fail_i', 'fail_i_iii', 'fail_new', 'pending_cal', 'pending_test']) {
    const rows = JSON.stringify(s.page.detailRows(f, { evidence }));
    assert.doesNotMatch(rows, /2020-02-03|2020-03-02|n=12/, evidence);
    assert.match(rows, /当前证据等级不展示区间/, evidence);
  }
  const exception = JSON.stringify(s.page.detailRows(f, { evidence: 'dev_only' }));
  assert.match(exception, /2020-02-03 至 2020-03-02/);
  assert.doesNotMatch(exception, /n=12|87%|0\.87/);
  const frameFailure = JSON.stringify(s.page.detailRows({ ...f, evidence: 'fail_i' }, { evidence: 'dev_only' }));
  assert.doesNotMatch(frameFailure, /2020-02-03|2020-03-02|n=12/, 'Frame-level failure takes precedence over the file-level exception');
});

test('unknown evidence and descriptive records without positive samples hide interval and model counts consistently', async () => {
  const s = setup(); await s.load();
  for (const [evidence, n] of [['unknown', 12], ['rule', 12], ['descriptive', 0], ['descriptive', undefined], ['descriptive', -1]]) {
    const f = { ...s.page.st.H.fr[0], evidence, n };
    const rows = JSON.stringify(s.page.detailRows(f, s.page.st.H));
    assert.doesNotMatch(rows, /2020-02-03|2020-03-02|n=/, `${evidence}/${n}`);
    assert.match(rows, /当前证据等级不展示区间/);
  }
  const supported = JSON.stringify(s.page.detailRows({ ...s.page.st.H.fr[0], evidence: 'descriptive', n: 12 }, s.page.st.H));
  assert.match(supported, /2020-02-03 至 2020-03-02/); assert.match(supported, /n=12/); assert.match(supported, /历史分位，不是预测/);
});

test('chart hit testing selects the touched interval rather than the nearest origin date', async () => {
  const s = setup(); await s.load();
  const f = s.page.st.H.fr[0], G = s.page.st.G;
  const x = G.X(Date.parse('2020-02-24T00:00:00Z')), y = G.Y(f.close);
  assert.equal(s.page.hitFrame(x, y).asof, '2020-01-06');
  const cv = s.nodes.get('cv');
  cv.dispatch('pointerdown', { clientX: x, clientY: y, pointerType: 'touch' });
  cv.dispatch('pointerup', { clientX: x, clientY: y, pointerType: 'touch' });
  assert.equal(s.page.st.selected.asof, '2020-01-06');
  assert.equal(s.document.activeElement.id, 'detail-heading');
});

test('vertical touch and cancelled gestures do not select or pan the chart', async () => {
  const s = setup(); await s.load();
  const cv = s.nodes.get('cv'), before = [s.page.st.va, s.page.st.vb];
  cv.dispatch('pointerdown', { pointerType: 'touch' });
  cv.dispatch('pointermove', { clientX: 102, clientY: 140, pointerType: 'touch' });
  cv.dispatch('pointerup', { clientX: 102, clientY: 140, pointerType: 'touch' });
  assert.equal(s.page.st.selected, null);
  assert.deepEqual([s.page.st.va, s.page.st.vb], before);
  cv.dispatch('pointerdown', { pointerType: 'touch' });
  cv.dispatch('pointercancel', { pointerType: 'touch' });
  cv.dispatch('pointerup', { pointerType: 'touch' });
  assert.equal(s.page.st.selected, null);
  assert.match(html, /\.chart canvas[^}]+touch-action: pan-y/);
});

test('keyboard Enter opens a recorded frame and reduced motion uses immediate mobile scrolling', async () => {
  const s = setup({ mobile: true, reducedMotion: true }); await s.load();
  s.nodes.get('cv').dispatch('keydown', { key: 'Enter' });
  assert.equal(s.page.st.selected.asof, '2020-01-20');
  assert.equal(s.nodes.get('detail-heading').lastScroll.behavior, 'auto');
  assert.equal(s.nodes.get('detail-heading').lastScroll.block, 'start', 'Mobile opens the details at the top, not just the last screen pixel');
  s.nodes.get('detail-close').dispatch('click');
  assert.equal(s.document.activeElement.id, 'cv');
  assert.equal(s.nodes.get('cv').lastScroll.behavior, 'auto');
});

test('a slow old OHLC response cannot replace the new index after its history already arrived', async () => {
  const s = setup({ waitForMarket: true });
  s.page.st.sym = 'sh000001'; const first = s.page.load();
  s.requests[0].resolve(record('sh000001')); await new Promise(resolve => setImmediate(resolve));
  s.page.st.sym = 'sh000300'; const second = s.page.load();
  s.requests[1].resolve(record('sh000300'));
  const emptyMarket = symbol => ({ symbol, bars: [], ranges: [], snapshots: [], failures: [] });
  s.marketRequests[1].resolve(emptyMarket('sh000300')); await second;
  s.marketRequests[0].resolve(emptyMarket('sh000001')); await first;
  assert.equal(s.page.st.H.symbol, 'sh000300'); assert.equal(s.page.st.market.symbol, 'sh000300');
  const ready = s.events.filter(e => e.type === 'lppl-history-ready');
  assert.equal(ready.length, 1); assert.equal(ready[0].detail.symbol, 'sh000300');
});

test('published OHLC renders a separate volume pane and missing volume is explicitly labelled', async () => {
  const s = setup({ waitForMarket: true }); const pending = s.page.load(); s.requests[0].resolve(record('sh000001'));
  const bar = { date: '2020-01-13', t: Date.parse('2020-01-13T00:00:00Z'), open: 102, high: 112, low: 100, close: 110, volume: null };
  s.marketRequests[0].resolve({ symbol: 'sh000001', bars: [bar], ranges: [[bar.t, bar.t]], snapshots: [{ latest: true, asof: bar.date, bars: [bar] }], failures: [] });
  await pending;
  assert.equal(s.page.st.G.visibleBars.length, 1);
  assert.ok(s.page.st.G.priceBottom < s.page.st.G.Hh - s.page.st.G.pb);
  assert.match(s.nodes.get('market-readout').innerHTML, /开 102.00.*高 112.00.*低 100.00.*收 110.00/);
  assert.match(s.nodes.get('market-readout').innerHTML, /量 未提供/);
  assert.match(s.nodes.get('market-coverage').textContent, /真实日 K/);
  s.nodes.get('volume-toggle').dispatch('click');
  assert.equal(s.page.st.G.priceBottom, s.page.st.G.Hh - s.page.st.G.pb);
});

test('the initial recent backtest view stays near the last model record instead of jumping into later unmodelled行情', async () => {
  const s = setup({ waitForMarket: true }); const pending = s.page.load(); s.requests[0].resolve(record('sh000001'));
  const bars = ['2020-01-13', '2020-01-20', '2026-10-30'].map(date => ({ date, t: Date.parse(date + 'T00:00:00Z'), open: 102, high: 112, low: 100, close: 110, volume: 1000 }));
  s.marketRequests[0].resolve({ symbol: 'sh000001', bars, ranges: [[bars[0].t, bars[1].t], [bars[2].t, bars[2].t]], snapshots: [{ latest: true, asof: bars[2].date, bars }], failures: [] });
  await pending;
  assert.ok(s.page.st.vb < bars[2].t);
  assert.ok(s.page.st.va <= bars[1].t && s.page.st.vb >= bars[1].t);
  assert.match(s.nodes.get('market-coverage').textContent, /情景记录截至 2020-01-20/);
});

test('selecting a historical cutoff brings its entire future scenario interval into view and clears stale OHLC hover', async () => {
  const s = setup({ waitForMarket: true }); const pending = s.page.load();
  const H = record('sh000001'); H.frames = [{ asof: '2007-10-12', split: 'dev', close: 100, w: { '6-12m': ['2007-11-16', '2007-11-30'] } }];
  s.requests[0].resolve(H);
  const bars = ['2007-02-01', '2007-10-12'].map(date => ({ date, t: Date.parse(date + 'T00:00:00Z'), open: 100, high: 112, low: 98, close: 105, volume: 1000 }));
  s.marketRequests[0].resolve({ symbol: 'sh000001', bars, ranges: [[bars[0].t, bars[1].t]], snapshots: [{ latest: true, asof: bars[1].date, bars }], failures: [] });
  await pending;
  const end = Date.parse('2007-11-30T00:00:00Z'); assert.ok(s.page.st.vb < end, 'Initial OHLC range precedes the future interval end');
  s.page.st.marketHover = bars[0]; s.page.selectFrame('2007-10-12', s.nodes.get('frame-open'), false);
  assert.ok(s.page.st.vb >= end); assert.ok(s.page.st.va <= bars[1].t);
  assert.equal(s.page.st.marketHover, null);
  const G = s.page.st.G; assert.ok(G.X(end) <= G.W - G.pr); assert.ok(G.X(bars[1].t) >= G.pl);
});
