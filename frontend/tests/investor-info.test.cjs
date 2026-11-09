const test = require('node:test');
const assert = require('node:assert/strict');
const info = require('../app/investor-info.js');

const DAY = '2026-11-06';
const PRIOR = '2026-11-05';
const MAOTAI = { code: '600519', name: '贵州茅台', streak: 1, limit_time: '10:30:00' };
const PINGAN = { code: '000001', name: '平安银行', streak: 3, limit_time: '09:35:00' };

function market(asof = DAY, limit = {}) {
  return {
    schema_version: 'market-context.v1', asof, status: 'fresh',
    limit_pools: { zt: 1, zb: 1, dt: 0, top20: { zt: [{ ...MAOTAI }] }, ...limit },
    sources: { limit_pools: { source_id: 'archived-pool', asof } },
  };
}
function sourceRows(rows, asof = DAY, status = 'fresh') {
  return { status, asof, rows, publication_eligible: true, source: { source_id: 'archived-source' } };
}
function newsRow(extra = {}) {
  return {
    title: '公司公告标题', url: 'https://disclosure.example/item/1',
    published_at: '2026-11-06T08:01:00+08:00', hash: 'item-1',
    source: '公告来源', symbol: 'sh600519', ...extra,
  };
}
function withInfo({ asof = DAY, asset = 'sh600519', sections = {} } = {}) {
  return {
    ...market(asof), investor_context: {
      schema_version: 'investor-context.v1', asof, symbol: asset,
      publication_eligible: true, purpose: 'publish',
      sections: { news: sourceRows([newsRow()], asof), ...sections },
    },
  };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function apiStub(client, marketRead = async () => market()) {
  const calls = [];
  return {
    calls,
    api: {
      marketContext() { calls.push(['marketContext']); return client; },
      market() { calls.push(['market']); return marketRead(); },
      request() { assert.fail('information reads must never start stock computation'); },
      current() { assert.fail('information reads must never start current LPPL computation'); },
      backtest() { assert.fail('information reads must never start a historical replay'); },
    },
  };
}
function memoryStorage() {
  const values = new Map();
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test('legacy top20 remains explicitly incomplete even when its length equals the reported total', () => {
  const selected = info.review(market());
  assert.equal(selected.sampleCount, 1);
  assert.equal(selected.total, 1);
  assert.equal(selected.complete, false);
  assert.equal(selected.stocks[0].symbol, 'sh600519');
});

test('full pool rows take precedence over the legacy top20 and are sorted by streak', () => {
  const selected = info.review(market(DAY, {
    zt: 2, pool_rows: { zt: [MAOTAI, PINGAN] },
    top20: { zt: [{ code: '300750', name: '旧样本', streak: 9 }] },
  }));
  assert.deepEqual(selected.stocks.map(row => row.code), ['000001', '600519']);
  assert.equal(selected.complete, true);
  assert.equal(selected.sampleCount, 2);
});

test('empty full pool does not silently refill from stale top20', () => {
  const selected = info.review(market(DAY, { zt: 0, pool_rows: { zt: [] } }));
  assert.deepEqual(selected.stocks, []);
  assert.equal(selected.complete, true);
});

test('duplicate or invalid full-pool members cannot support a complete-pool claim', () => {
  for (const pool of [[MAOTAI, MAOTAI], [MAOTAI, { code: '999999', name: 'invalid' }]]) {
    const selected = info.review(market(DAY, { zt: 2, pool_rows: { zt: pool } }));
    assert.equal(selected.complete, false);
    assert.equal(selected.sampleCount, 1);
  }
});

test('reasons and topics must belong to the selected day and an available status', () => {
  for (const [asof, status] of [[PRIOR, 'fresh'], [DAY, 'not_available'], [DAY, 'error']]) {
    const selected = info.review(market(DAY, {
      reasons: sourceRows([{ code: '600519', reason: '另一日归因' }], asof, status),
      topics: sourceRows([{ code: '600519', topic_label: '另一日题材' }], asof, status),
    }));
    assert.equal(selected.stocks[0].reason, null);
    assert.deepEqual(selected.stocks[0].topics, []);
    assert.deepEqual(selected.topics, []);
  }
});

test('dated topics deduplicate membership and source-provided reasons remain descriptive text', () => {
  const selected = info.review(market(DAY, {
    zt: 2, pool_rows: { zt: [MAOTAI, PINGAN] },
    reasons: sourceRows([{ code: '600519', reason: ' 来源叙事，尚非因果证明 ' }]),
    topics: sourceRows([
      { code: '600519', topic_label: '消费' }, { code: '600519', topic_label: '消费' },
      { code: '000001', topic_label: '消费' }, { code: '000001', topic_label: '金融' },
    ]),
  }));
  assert.deepEqual(selected.topics.map(row => [row.name, row.count]), [['消费', 2], ['金融', 1]]);
  assert.equal(info.selectStocks(selected, { query: '茅台', topic: '消费' })[0].reason, '来源叙事，尚非因果证明');
  assert.deepEqual(info.selectStocks(selected, { minStreak: 2 }).map(row => row.code), ['000001']);
});

test('unavailable counts and unmatched historical progression are not rendered as valid zero statistics', () => {
  const snapshot = market(DAY, { zt: null, zb: null, dt: null });
  snapshot.history = { progression: { asof: PRIOR, status: 'fresh', rate: 0.8 } };
  const selected = info.review(snapshot);
  assert.deepEqual(selected.counts, { zt: null, zb: null, dt: null, breakRate: null });
  assert.equal(selected.progression.status, 'not_available');
  assert.equal(selected.progression.rate, undefined);
});

test('review excludes explicitly unpublished, fixture and research-import snapshots', () => {
  for (const flags of [
    { publication_eligible: false }, { evidence_import: true },
    { run_mode: 'fixture' }, { run_mode: 'research_import' },
  ]) assert.equal(info.review({ ...market(), ...flags }), null);
  assert.equal(info.review(market('2026-02-30')), null);
});

test('board selectors preserve independent periods and missing numerical values', () => {
  const snapshot = market();
  snapshot.board_flow = { industry: [
    { name: '银行', main_net: 10, pct_chg: 1, main_net_5d: 300, pct_5d: 4 },
    { name: '消费', main_net: 20, pct_chg: -1, main_net_5d: '500', pct_5d: NaN },
  ] };
  const selected = info.review(snapshot);
  assert.deepEqual(info.boardRows(selected).map(row => row.name), ['消费', '银行']);
  assert.deepEqual(info.boardRows(selected, 'industry', '5d', '消费'), [{ name: '消费', code: '', net: null, pct: null }]);
  assert.deepEqual(info.boardRows(selected, 'unknown', 'today'), []);
  assert.deepEqual(info.boardRows(selected, 'industry', '1y'), []);
});

test('information sections require schema, publication permission, purpose, asset and both dates', () => {
  const cases = [
    snapshot => { delete snapshot.investor_context; },
    snapshot => { snapshot.investor_context.schema_version = 'unknown'; },
    snapshot => { snapshot.investor_context.publication_eligible = false; },
    snapshot => { snapshot.investor_context.publication_eligible = 'true'; },
    snapshot => { snapshot.investor_context.purpose = 'research'; },
    snapshot => { snapshot.investor_context.symbol = 'sz000001'; },
    snapshot => { snapshot.investor_context.asof = PRIOR; },
    snapshot => { snapshot.investor_context.sections.news.asof = PRIOR; },
    snapshot => { snapshot.investor_context.sections.news.publication_eligible = false; },
    snapshot => { snapshot.investor_context.sections.news.status = 'not_available'; },
  ];
  for (const mutate of cases) {
    const snapshot = withInfo(); mutate(snapshot);
    assert.deepEqual(info.section(snapshot, 'news', 'sh600519').rows, []);
    assert.deepEqual(info.newsRows(snapshot, ['news'], { asset: 'sh600519' }), []);
  }
});

test('an outer fixture or unpublished snapshot cannot expose an otherwise public-looking information section', () => {
  for (const flags of [
    { publication_eligible: false }, { evidence_import: true },
    { run_mode: 'fixture' }, { run_mode: 'research_import' },
  ]) {
    const snapshot = { ...withInfo(), ...flags };
    assert.deepEqual(info.section(snapshot, 'news', 'sh600519').rows, []);
  }
});

test('a stale but date-matched information section preserves its source and stale explanation', () => {
  const snapshot = withInfo();
  Object.assign(snapshot.investor_context.sections.news, { status: 'stale', stale_reason: 'upstream_timeout' });
  const selected = info.section(snapshot, 'news', 'sh600519');
  assert.equal(selected.rows.length, 1);
  assert.equal(selected.status, 'stale');
  assert.equal(selected.stale_reason, 'upstream_timeout');
  assert.equal(selected.source.source_id, 'archived-source');
});

test('backend empty and failed sections retain their actual status instead of becoming permission failures', () => {
  for (const status of ['not_available', 'error', 'blocked']) {
    const snapshot = withInfo();
    Object.assign(snapshot.investor_context.sections.news, {
      status, rows: [], publication_eligible: false,
      stale_reason: status === 'not_available' ? 'source_not_connected' : status,
    });
    const selected = info.section(snapshot, 'news', 'sh600519');
    assert.equal(selected.status, status);
    assert.deepEqual(selected.rows, []);
    assert.equal(selected.stale_reason, status === 'not_available' ? 'source_not_connected' : status);
  }
});

test('news rejects executable, plaintext, credentialed and malformed links', () => {
  const urls = ['javascript:alert(1)', 'data:text/html,hello', 'http://example.com/a', 'https://u:p@example.com/a', '/relative', 'not a url'];
  const snapshot = withInfo({ sections: { news: sourceRows(urls.map((url, index) => newsRow({ url, hash: `bad-${index}` }))) } });
  assert.deepEqual(info.newsRows(snapshot, ['news']), []);
});

test('news exports only title metadata, deduplicates by identity and does not pass article bodies through', () => {
  const row = newsRow({ body: 'copyrighted full article', html: '<script>bad()</script>', content: 'full content', secret: 'not-for-display' });
  const snapshot = withInfo({ sections: { news: sourceRows([row]), announcements: sourceRows([row]) } });
  const selected = info.newsRows(snapshot, ['news', 'announcements'], { asset: 'sh600519' });
  assert.equal(selected.length, 1);
  assert.deepEqual(Object.keys(selected[0]).sort(), ['available_at', 'id', 'kind', 'published_at', 'source', 'symbol', 'title', 'url']);
  assert.equal(JSON.stringify(selected).includes('copyrighted full article'), false);
  assert.equal(selected[0].url, row.url);
});

test('news rejects explicit cross-asset rows, invalid times and missing titles and supports saved-only filtering', () => {
  const snapshot = withInfo({ sections: { news: sourceRows([
    newsRow(), newsRow({ hash: 'other', symbol: 'sz000001' }),
    newsRow({ hash: 'bad-time', published_at: 'unknown' }), newsRow({ hash: 'no-title', title: ' ' }),
  ]) } });
  assert.deepEqual(info.newsRows(snapshot, ['news'], { asset: 'sh600519' }).map(row => row.id), ['item-1']);
  assert.deepEqual(info.newsRows(snapshot, ['news'], { asset: 'sh600519', onlySaved: true, saved: [] }), []);
  assert.equal(info.newsRows(snapshot, ['news'], { asset: 'sh600519', onlySaved: true, saved: ['item-1'], query: '公告' }).length, 1);
});

test('enabled reader uses the independent context path and never invokes analysis methods', async () => {
  const reads = [], states = [];
  const client = { isEnabled: () => true, async get(date) { reads.push(date); return { snapshot: market(date) }; }, stop() {} };
  const stub = apiStub(client);
  const reader = info.createReader(stub.api, state => states.push(state));
  await reader.get(PRIOR);
  assert.deepEqual(reads, [PRIOR]);
  assert.deepEqual(stub.calls, [['marketContext']]);
  assert.equal(states.at(-1).snapshot.asof, PRIOR);
  assert.equal(states.at(-1).status, 'ready');
  reader.destroy();
});

test('missing historical context never falls back to market() or latest', async () => {
  const reads = [], states = [];
  const stub = apiStub({ isEnabled: () => true, async get(date) { reads.push(date); throw Error('historical snapshot unavailable'); }, stop() {} });
  const reader = info.createReader(stub.api, state => states.push(state));
  await reader.get(PRIOR);
  assert.deepEqual(reads, [PRIOR]);
  assert.deepEqual(stub.calls, [['marketContext']]);
  assert.equal(states.at(-1).status, 'error');
  assert.equal(states.at(-1).snapshot, null);
  reader.destroy();
});

test('static market fallback refuses to relabel a current snapshot as a requested historical day', async () => {
  const states = [], stub = apiStub({ isEnabled: () => false, stop() {} });
  const reader = info.createReader(stub.api, state => states.push(state));
  await reader.get(PRIOR);
  assert.equal(states.at(-1).status, 'error');
  assert.equal(states.at(-1).snapshot, null);
  assert.match(states.at(-1).error, /未回退到最新/);
  assert.deepEqual(stub.calls, [['marketContext'], ['market']]);
  reader.destroy();
});

test('out-of-order requests for different dates cannot replace the newest selected date', async () => {
  const old = deferred(), current = deferred(), states = [];
  const stub = apiStub({ isEnabled: () => true, get: date => date === PRIOR ? old.promise : current.promise, stop() {} });
  const reader = info.createReader(stub.api, state => states.push(state));
  const first = reader.get(PRIOR), second = reader.get(DAY);
  current.resolve({ snapshot: market(DAY) }); await second;
  old.resolve({ snapshot: market(PRIOR) }); await first;
  assert.deepEqual(states.filter(state => state.status === 'ready').map(state => state.snapshot.asof), [DAY]);
  assert.equal(states.at(-1).date, DAY);
  reader.destroy();
});

test('a late error from an older date cannot erase the newer successful snapshot', async () => {
  const old = deferred(), states = [];
  const stub = apiStub({ isEnabled: () => true, get: date => date === PRIOR ? old.promise : Promise.resolve({ snapshot: market(DAY) }), stop() {} });
  const reader = info.createReader(stub.api, state => states.push(state));
  const first = reader.get(PRIOR); await reader.get(DAY);
  old.reject(Error('old day timeout')); await first;
  assert.equal(states.at(-1).status, 'ready');
  assert.equal(states.at(-1).snapshot.asof, DAY);
  reader.destroy();
});

test('refresh failure retains only the same requested date and never leaks another date cache', async () => {
  let attempt = 0; const states = [];
  const stub = apiStub({ isEnabled: () => true, async get(date) {
    if (++attempt === 1) return { snapshot: market(date) };
    throw Error('offline');
  }, stop() {} });
  const reader = info.createReader(stub.api, state => states.push(state));
  await reader.get(PRIOR); await reader.get(PRIOR);
  assert.equal(states.at(-1).status, 'error');
  assert.equal(states.at(-1).snapshot.asof, PRIOR);
  await reader.get(DAY);
  assert.equal(states.at(-1).snapshot, null);
  assert.equal(states.at(-1).date, DAY);
  reader.destroy();
});

test('reader rejects mismatched context dates and nonpublication fixtures', async () => {
  for (const snapshot of [market(DAY), { ...market(PRIOR), run_mode: 'fixture' }]) {
    const states = [], stub = apiStub({ isEnabled: () => true, async get() { return { snapshot }; }, stop() {} });
    const reader = info.createReader(stub.api, state => states.push(state));
    await reader.get(PRIOR);
    assert.equal(states.at(-1).status, 'error');
    assert.equal(states.at(-1).snapshot, null);
    reader.destroy();
  }
});

test('reader bounds a stalled read and cannot be overwritten by its late result', async () => {
  const pending = deferred(), states = [];
  const stub = apiStub({ isEnabled: () => true, get: () => pending.promise, stop() {} });
  const reader = info.createReader(stub.api, state => states.push(state), { timeoutMs: 10 });
  await reader.get(DAY);
  assert.equal(states.at(-1).status, 'error');
  assert.match(states.at(-1).error, /超时/);
  pending.resolve({ snapshot: market(DAY) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(states.at(-1).status, 'error');
  reader.destroy();
});

test('destroy stops context polling and suppresses in-flight reader updates', async () => {
  let stopped = 0; const pending = deferred(), states = [];
  const stub = apiStub({ isEnabled: () => true, get: () => pending.promise, stop() { stopped += 1; } });
  const reader = info.createReader(stub.api, state => states.push(state));
  const loading = reader.get(DAY); reader.destroy();
  pending.resolve({ snapshot: market(DAY) }); await loading;
  assert.equal(stopped, 1);
  assert.deepEqual(states.map(state => state.status), ['loading']);
});

test('notebook marks user notes separately from model evidence across persistence and export', () => {
  const storage = memoryStorage(), clock = () => '2026-11-09T02:00:00Z';
  const book = info.createNotebook(storage, clock);
  const saved = book.addNote({ asof: DAY, symbol: 'sh600519', body: '  我的观察，不是模型预测  ', snapshotHash: 'snapshot-hash' });
  assert.equal(saved.persistent, true);
  assert.equal(saved.notes[0].kind, 'user_note_not_model_evidence');
  assert.equal(saved.notes[0].snapshot_hash, 'snapshot-hash');
  assert.equal(saved.notes[0].body, '我的观察，不是模型预测');
  const restored = info.createNotebook(storage, clock);
  assert.equal(restored.snapshot().notes[0].kind, 'user_note_not_model_evidence');
  const exported = JSON.parse(restored.exportJSON());
  assert.equal(exported.schema_version, 'investor-notebook.v1');
  assert.equal(exported.notes[0].kind, 'user_note_not_model_evidence');
  saved.notes[0].body = 'external mutation';
  assert.notEqual(book.snapshot().notes[0].body, 'external mutation');
});

test('notebook rejects invalid dates, symbols, empty text and oversized notes without saving', () => {
  const storage = memoryStorage(), book = info.createNotebook(storage);
  for (const value of [
    { asof: '2026-02-30', body: 'x' }, { asof: DAY, body: ' ' },
    { asof: DAY, body: 'x'.repeat(4001) }, { asof: DAY, body: 'x', symbol: 'sh000001' },
  ]) assert.throws(() => book.addNote(value));
  assert.deepEqual(book.snapshot().notes, []);
  assert.equal(storage.values.size, 0);
});

test('restored local notes cannot claim to be model evidence', () => {
  const storage = memoryStorage();
  storage.setItem('lppl.investor.notebook.v1', JSON.stringify({ notes: [
    { id: 'old-note', asof: DAY, body: '用户笔记', created_at: '2026-11-09T02:00:00Z', kind: 'model_prediction_verified' },
  ], bookmarks: [] }));
  const book = info.createNotebook(storage);
  assert.equal(book.snapshot().notes[0].kind, 'user_note_not_model_evidence');
  assert.equal(JSON.parse(book.exportJSON()).notes[0].kind, 'user_note_not_model_evidence');
});

test('storage write failure is reported while notes remain available for export', () => {
  const book = info.createNotebook({ getItem: () => null, setItem() { throw Error('quota exceeded'); } });
  const saved = book.addNote({ asof: DAY, body: '临时保留的笔记' });
  assert.equal(saved.persistent, false);
  assert.equal(saved.notes.length, 1);
  assert.equal(JSON.parse(book.exportJSON()).notes[0].body, '临时保留的笔记');
});

test('storage read failure does not crash the notebook or claim successful persistence', () => {
  const book = info.createNotebook({ getItem() { throw Error('storage blocked'); }, setItem() { throw Error('storage blocked'); } });
  assert.equal(book.snapshot().persistent, false);
  assert.equal(book.addNote({ asof: DAY, body: '仍可记下' }).persistent, false);
  assert.equal(book.snapshot().notes[0].kind, 'user_note_not_model_evidence');
});

test('a browser without storage is labelled memory-only before the first write', () => {
  const book = info.createNotebook(undefined);
  assert.equal(book.snapshot().persistent, false);
  assert.equal(book.addNote({ asof: DAY, body: '可导出的临时记录' }).persistent, false);
  assert.equal(JSON.parse(book.exportJSON()).notes.length, 1);
});

test('bookmarks reject unsafe links and persist only the allowed metadata', () => {
  const storage = memoryStorage(), book = info.createNotebook(storage);
  book.toggleBookmark({ id: 'unsafe', title: 'unsafe', url: 'javascript:alert(1)' });
  assert.deepEqual(book.snapshot().bookmarks, []);
  const item = { id: 'safe', title: '公告', url: 'https://disclosure.example/item/1', body: 'full article' };
  book.toggleBookmark(item);
  assert.equal(book.snapshot().bookmarks.length, 1);
  assert.equal(book.snapshot().bookmarks[0].body, undefined);
  book.toggleBookmark(item);
  assert.deepEqual(book.snapshot().bookmarks, []);
});
