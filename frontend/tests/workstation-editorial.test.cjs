const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../workstation-editorial.html'), 'utf8');
const between = (start, end) => html.slice(html.indexOf(start), html.indexOf(end));
const block = name => between('/* EDITORIAL_' + name + '_START', '/* EDITORIAL_' + name + '_END');
const flush = () => new Promise(resolve => setImmediate(resolve));

function nodeMap() {
  const nodes = new Map();
  return id => {
    if (!nodes.has(id)) nodes.set(id, { textContent: '', innerHTML: '', value: '', hidden: false, disabled: false,
      attributes: {}, setAttribute(k, v) { this.attributes[k] = v; } });
    return nodes.get(id);
  };
}

function requestHarness() {
  const calls = [], rendered = [], errors = [], progress = [], pending = new Map();
  let cleared = 0;
  const context = vm.createContext({
    $: nodeMap(), cur: { sym: { label: 'prior' } }, curCode: 'prior', busy: false, want: null, requestId: 0, playing: false,
    getAnalysis(code, asof, onProg) {
      calls.push([code, asof]);
      return new Promise((resolve, reject) => pending.set(code, { resolve, reject, onProg }));
    },
    prog: (s, p) => progress.push([s, p]), err: message => errors.push(message),
    render: result => rendered.push(result.sym.label), stopPlay() {}, schedulePlay() {},
    clearView() { cleared++; context.cur = null; },
  });
  vm.runInContext(block('REQUEST'), context);
  return { context, calls, rendered, errors, progress, pending, get cleared() { return cleared; } };
}

test('a stale failing request cannot clear the view or report an error for a newer selection', async () => {
  const h = requestHarness();
  h.context.request('old', '2007-10-12');
  h.context.request('new', '2015-06-12');
  const progressCount = h.progress.length;
  h.pending.get('old').onProg('stale progress', .8);
  assert.equal(h.progress.length, progressCount);
  h.pending.get('old').reject(new Error('old failure'));
  await flush();
  assert.equal(h.cleared, 0);
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.calls, [['old', '2007-10-12'], ['new', '2015-06-12']]);
  h.pending.get('new').resolve({ sym: { label: 'new' } });
  await flush();
  assert.deepEqual(h.rendered, ['new']);
  assert.equal(h.context.$('go').disabled, false);
  assert.equal(h.context.$('chartwrap').attributes['aria-busy'], 'false');
});

test('rapid selections coalesce and stale successful data never becomes the displayed snapshot', async () => {
  const h = requestHarness();
  h.context.request('first', '');
  h.context.request('skipped', '');
  h.context.request('last', '');
  h.pending.get('first').resolve({ sym: { label: 'first' } });
  await flush();
  assert.deepEqual(h.rendered, []);
  assert.deepEqual(h.calls, [['first', ''], ['last', '']]);
  h.pending.get('last').resolve({ sym: { label: 'last' } });
  await flush();
  assert.deepEqual(h.rendered, ['last']);
  assert.equal(h.context.$('ld').hidden, true);
});

test('the latest failed request clears old data and leaves an honest unloaded state', async () => {
  const h = requestHarness();
  h.context.request('latest', '');
  h.pending.get('latest').reject(new Error('network unavailable'));
  await flush();
  assert.equal(h.cleared, 1);
  assert.deepEqual(h.errors, ['数据未加载：network unavailable']);
  assert.equal(h.context.cur, null);
  assert.equal(h.context.$('ld').hidden, false);
  assert.equal(h.context.$('ld-t').textContent, '数据未加载');
  assert.equal(h.context.busy, false);
});

test('unavailable optional history is explicitly marked while the primary snapshot remains usable', async () => {
  const context = vm.createContext({
    LPPL: { load: async () => ({ sym: { sym: 'sh000001' }, asof: '2026-10-30' }), history: async () => { throw new Error('history unavailable'); } },
    toView: data => ({ asof: data.asof, bars: [{ date: data.asof, close: 3599.02 }] }),
    histView: () => { throw new Error('missing history must not be rendered'); },
  });
  vm.runInContext(between('  async function getAnalysis(', '  /* 历史情景区间'), context);
  const result = await context.getAnalysis('上证指数', '');
  assert.equal(result.asof, '2026-10-30');
  assert.equal(result.bars[0].close, 3599.02);
  assert.equal(result.hist, null);
  assert.equal(result.historyUnavailable, true);
  assert.match(html, /\$\('history-state'\)\.hidden = !R\.historyUnavailable/);
});

test('evidence gates fail closed and descriptive values require a real sample count', () => {
  const context = vm.createContext({});
  vm.runInContext(block('EVIDENCE'), context);
  for (const code of ['none', 'fail', 'fail_i', 'fail_future', 'dev_only', 'dev_failed', 'rule', 'pending_cal', undefined, 'unknown']) {
    assert.equal(context.evidenceAllowsValues(code), false, code);
  }
  for (const code of ['dev', 'cal', 'test', 'cal_fragile', 'descriptive']) assert.equal(context.evidenceAllowsValues(code), true);
  for (const n of [undefined, null, 0, -1, NaN]) assert.equal(context.descriptiveWithSample({ evidence: 'descriptive', n }), false);
  assert.equal(context.descriptiveWithSample({ evidence: 'descriptive', n: 11 }), true);
  assert.equal(context.descriptiveWithSample({ evidence: 'dev_only', n: 11 }), false);
});

test('failed validation and unsupported scale parameters never leak raw model numbers or numeric notes', () => {
  const context = vm.createContext({ $: nodeMap(), E: x => String(x ?? ''), U: { pct: x => x == null ? '—' : String(x) },
    SCALES: ['2-4w'], SCN: { '2-4w': '2–4 周' }, SIG: {}, evb: x => x || '', EV: code => ({ label: code || 'none', show: false }) });
  vm.runInContext(block('EVIDENCE') + between('  function renderBench(R)', '  /* ================= 行情带'), context);
  context.renderBench({ J: { validation: [{ split: '测试段', events: 987, hit: .876, false_alarm: .765, brier: 'leak 12345', status: 'fail_future', note: 'leak 54321' }] } });
  const bench = context.$('p-bench').innerHTML;
  for (const number of ['987', '0.876', '0.765', '12345', '54321']) assert.equal(bench.includes(number), false, number);
  context.renderExpert({ top: { indicators: { '2-4w': { n_windows: 9999, n_qualified_standard: 8888, best_t1: '2001-01-01', t1_qualified: true } }, lppls_confidence: { scale_evidence: { '2-4w': 'dev_only' } } } });
  const expert = context.$('p-expert').innerHTML;
  for (const value of ['9999', '8888', '2001-01-01']) assert.equal(expert.includes(value), false, value);
  assert.match(expert, /dev_only/);
});

test('snapshot choices follow adapter availability and unsupported URL dates are not silently changed to latest', () => {
  const context = vm.createContext({ $: nodeMap(), E: String, LPPL: {
    resolve: code => ['上证指数', 'sh000001'].includes(code) ? { sym: 'sh000001' } : code === '沪深300' ? { sym: 'sh000300' } : null,
    REPLAYS: { sh000001: ['2007-10-12', '2015-06-12'] },
  } });
  vm.runInContext(block('SNAPSHOTS'), context);
  context.syncDates('上证指数', '2015-06-12');
  assert.equal(context.$('asof').value, '2015-06-12');
  assert.match(context.$('asof').innerHTML, /2007-10-12/);
  context.syncDates('沪深300', '2015-06-12');
  assert.equal(context.$('asof').value, '');
  assert.equal(context.$('asof').innerHTML.includes('2015-06-12'), false);
  context.syncDates('上证指数', '2010-01-01', true);
  assert.equal(context.$('asof').value, '2010-01-01');
  assert.match(context.$('asof').innerHTML, /disabled>未开放/);
});

test('navigation preserves code and available asof and removes stale asof for latest', () => {
  const links = ['home-editorial.html', 'backtest-editorial.html', 'index.html'].map(href => ({ href, getAttribute() { return this.href; }, setAttribute(k, v) { this[k] = v; } }));
  const context = vm.createContext({ URL, location: { href: 'http://localhost:8000/workstation-editorial.html' }, document: { querySelectorAll: () => links } });
  vm.runInContext(block('SNAPSHOTS'), context);
  context.syncContextLinks('sh000001', '2015-06-12');
  for (const link of links) assert.match(link.href, /code=sh000001&asof=2015-06-12$/);
  context.syncContextLinks('sh000300', '');
  for (const link of links) { assert.match(link.href, /code=sh000300$/); assert.equal(link.href.includes('asof'), false); }
});

test('independent preview scripts parse, DOM ids stay unique, and the disabled timeline is not exposed', () => {
  for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) if (match[1].trim()) new vm.Script(match[1]);
  const body = between('<body', '<script>'), ids = [...body.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length);
  assert.match(html, /<body data-page="workstation">/);
  assert.match(html, /name="robots" content="noindex,nofollow"/);
  assert.match(html, /class="tl od-row" hidden aria-hidden="true"/);
  assert.match(html, /<select[^>]*id="asof"/);
  assert.equal(html.includes('id="asof" type="date"'), false);
  assert.equal(html.includes('fetch('), false);
  assert.ok(html.indexOf('app/research-editorial.css') < html.indexOf('app/workstation-editorial.css'));
});
