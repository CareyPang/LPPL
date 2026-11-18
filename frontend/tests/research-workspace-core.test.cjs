const { test } = require('node:test');
const assert = require('node:assert/strict');
const Core = require('../app/research-workspace-core.js');
const RuleLabels = require('../app/rule-labels.js');
const at = '2026-11-18T04:00:00Z';
const index = Core.asset('index', 'sh000001', '上证指数');
const stock = Core.asset('stock', '600519', '贵州茅台');
function payload(extra = {}) {
  return { symbol: 'sh000001', name: '上证指数', asof: '2026-11-17', model_version: 'v1',
    price_history: { dates: ['2026-11-17'], close: [4000], note: '测试数据' },
    top: { lppls_confidence: { '6-12m': 0.4, evidence: 'dev_only', scale_evidence: { '6-12m': 'dev' } },
      indicators: { '6-12m': { n_windows: 6, signal_status: 'signal' } },
      scale_clusters: { '6-12m': [{ q20_date: '2026-11-20', q80_date: '2026-11-27', rank: 'main' }] } }, ...extra };
}
function memory(value) {
  const values = new Map(value === undefined ? [] : [[Core.KEY, value]]);
  return { getItem: k => values.has(k) ? values.get(k) : null, setItem: (k, v) => values.set(k, v) };
}
test('asset kind prevents Shenzhen stock / Shanghai index code collisions and unsafe routes', () => {
  assert.notEqual(Core.asset('stock', '000001').id, index.id);
  assert.equal(Core.asset('stock', '600519&x=1'), null);
  assert.equal(Core.asset('index', 'sh999999'), null);
  assert.equal(Core.route({ kind: 'stock', code: 'https://evil.example' }), 'research-workspace.html');
  assert.equal(Core.route(stock), 'stock.html?code=600519&from=research-workspace');
});
test('only a matching published asset and valid asof yield model content', () => {
  assert.equal(Core.summarize(stock, payload(), at).status, 'unavailable');
  assert.equal(Core.summarize(Core.asset('stock', '000001'), payload(), at).status, 'unavailable');
  assert.equal(Core.summarize(index, payload({ asof: '2026-02-30' }), at).asof, null);
  assert.equal(Core.summarize(index, null, at).windows.length, 0);
});
test('summary reveals gated intervals, no score, no precise tc, no synthetic prediction id', () => {
  const result = Core.summarize(index, payload(), at);
  assert.equal(result.status, 'has_window');
  assert.equal(result.windows[0].start, '2026-11-20');
  assert.equal(result.predictionId, null);
  assert.equal(result.source, '来源未提供');
  assert.equal(result.coverage.filter(x => x.computed).length, 1);
  assert.equal('confidence' in result, false);
  assert.equal('share' in result.windows[0], false);
});
test('failed, absent and unknown evidence cannot leak interval dates', () => {
  for (const evidence of ['none', 'dev_only', 'dev_failed', 'fail_i', 'pending_test', 'surprise', '']) {
    const raw = payload(); raw.top.lppls_confidence.scale_evidence['6-12m'] = evidence;
    const result = Core.summarize(index, raw, at);
    assert.equal(result.windows.length, 0, evidence);
    assert.equal(result.status, 'evidence_hidden', evidence);
  }
});
test('descriptive dates need positive sample n and carry required text', () => {
  const raw = payload(); raw.top.lppls_confidence.scale_evidence['6-12m'] = 'descriptive';
  assert.equal(Core.summarize(index, raw, at).windows.length, 0);
  raw.top.scale_clusters['6-12m'][0].n = 12;
  const window = Core.summarize(index, raw, at).windows[0];
  assert.equal(window.n, 12); assert.equal(window.note, '历史分位，不是预测');
});
test('band evidence cannot upgrade a restricted scale and not-computed never revives a band', () => {
  const raw = payload(); raw.top.lppls_confidence.scale_evidence['6-12m'] = 'none';
  raw.top.scale_clusters['6-12m'][0].evidence = 'dev';
  assert.equal(Core.summarize(index, raw, at).windows.length, 0);
  raw.top.lppls_confidence.scale_evidence['6-12m'] = 'dev';
  raw.top.indicators['6-12m'].signal_status = 'not_computed';
  assert.equal(Core.summarize(index, raw, at).windows.length, 0);
});
test('stock result is explicitly research candidate, never inherited index dev', () => {
  const raw = payload({ symbol: 'sh600519', stock_meta: { evidence: 'research_candidate', source: 'provider' } });
  assert.equal(Core.summarize(stock, raw, at).windows[0].evidence, 'research_candidate');
  delete raw.stock_meta;
  assert.equal(Core.summarize(stock, raw, at).windows.length, 0);
});
test('stock identity never bypasses descriptive sample-count evidence at any layer', () => {
  for (const layer of ['scale', 'band', 'stock']) {
    const raw = payload({ symbol: 'sh600519', stock_meta: { evidence: 'research_candidate' } });
    if (layer === 'scale') raw.top.lppls_confidence.scale_evidence['6-12m'] = 'descriptive';
    if (layer === 'band') raw.top.scale_clusters['6-12m'][0].evidence = 'descriptive';
    if (layer === 'stock') raw.stock_meta.evidence = 'descriptive';
    assert.equal(Core.summarize(stock, raw, at).windows.length, 0, layer);
    raw.top.scale_clusters['6-12m'][0].n = 12;
    const window = Core.summarize(stock, raw, at).windows[0];
    assert.equal(window.evidence, 'descriptive', layer);
    assert.equal(window.n, 12, layer);
    assert.equal(window.note, '历史分位，不是预测', layer);
  }
});
test('band dev cannot upgrade a descriptive scale and stock failure still blocks descriptive output', () => {
  const raw = payload();
  raw.top.lppls_confidence.scale_evidence['6-12m'] = 'descriptive';
  raw.top.scale_clusters['6-12m'][0].evidence = 'dev';
  assert.equal(Core.summarize(index, raw, at).windows.length, 0);
  raw.top.scale_clusters['6-12m'][0].n = 12;
  assert.equal(Core.summarize(index, raw, at).windows[0].evidence, 'descriptive');
  raw.symbol = 'sh600519'; raw.stock_meta = { evidence: 'fail_i' };
  assert.equal(Core.summarize(stock, raw, at).windows.length, 0);
});
test('explicit empty clusters do not resurrect a stale fallback window', () => {
  const raw = payload(); raw.top.scale_clusters['6-12m'] = [];
  raw.top.scale_windows = [{ scale: '6-12m', q20_date: '2026-11-20', q80_date: '2026-11-27' }];
  assert.equal(Core.summarize(index, raw, at).windows.length, 0);
});
test('unknown scale and invalid/reversed dates are rejected', () => {
  const raw = payload(); raw.top.scale_clusters['6-12m'][0].q20_date = '2026-11-30';
  raw.top.scale_clusters.fake = [{ q20_date: '2026-11-20', q80_date: '2026-11-27' }];
  assert.equal(Core.summarize(index, raw, at).windows.length, 0);
});
test('not computed differs from zero qualified and no cluster', () => {
  const raw = payload(); raw.top.scale_clusters = {};
  raw.top.lppls_confidence['6-12m'] = null;
  raw.top.indicators['6-12m'] = { signal_status: 'not_computed' };
  assert.equal(Core.summarize(index, raw, at).status, 'not_computed');
  raw.top.indicators['6-12m'] = { n_windows: 6, signal_status: 'no_qualified_fit' };
  assert.equal(Core.summarize(index, raw, at).status, 'no_qualified_fit');
  raw.top.indicators['6-12m'].signal_status = 'signal';
  assert.equal(Core.summarize(index, raw, at).status, 'no_cluster');
});
test('unevaluated scales with a numeric confidence do not mask qualified-fit status', () => {
  const raw = payload(); raw.top.scale_clusters = {};
  raw.top.lppls_confidence['6-12m'] = 0;
  raw.top.indicators['6-12m'] = { n_windows: 6, signal_status: 'no_qualified_fit' };
  raw.top.lppls_confidence['2-6y'] = 0.1;
  raw.top.lppls_confidence.scale_evidence['2-6y'] = 'none';
  assert.equal(Core.summarize(index, raw, at).status, 'no_qualified_fit');
});
test('empty-state text matches shared rule labels', () => {
  const raw = payload(); raw.top.scale_clusters = {};
  raw.top.lppls_confidence['6-12m'] = null;
  raw.top.indicators['6-12m'] = { signal_status: 'not_computed' };
  assert.equal(Core.summarize(index, raw, at).statusText, RuleLabels.EMPTY_REASONS.not_computed);

  raw.top.lppls_confidence['6-12m'] = 0;
  raw.top.indicators['6-12m'] = { n_windows: 6, signal_status: 'no_qualified_fit' };
  assert.equal(Core.summarize(index, raw, at).statusText, RuleLabels.EMPTY_REASONS.no_fit);

  raw.top.lppls_confidence['6-12m'] = 0.4;
  raw.top.indicators['6-12m'] = { n_windows: 6, signal_status: 'signal' };
  assert.equal(Core.summarize(index, raw, at).statusText, RuleLabels.EMPTY_REASONS.no_cluster);
  assert.equal(Core.summarize(index, payload(), at).statusText, '有研究观察区间');
  assert.equal(Core.summarize(index, null, at).statusText, '尚未取得可用分析');

  assert.equal(Core.summarize(index, payload(), at).status, 'has_window');
  const expired = payload();
  expired.top.scale_clusters['6-12m'][0] = { q20_date: '2026-11-01', q80_date: '2026-11-05' };
  assert.equal(Core.summarize(index, expired, at).statusText, '已公布区间早于分析截止日');

  assert.equal(Core.summarize(index, payload(), at).status, 'has_window');
  const hidden = payload();
  hidden.top.lppls_confidence.scale_evidence['6-12m'] = 'none';
  assert.equal(Core.summarize(index, hidden, at).statusText, RuleLabels.EMPTY_REASONS.not_formal);
});
test('expired interval remains historical, never represented as future', () => {
  const raw = payload(); raw.top.scale_clusters['6-12m'][0] = { q20_date: '2026-11-01', q80_date: '2026-11-05' };
  assert.equal(Core.summarize(index, raw, at).status, 'expired');
});
test('price reading never includes a future bar or invents zero', () => {
  const raw = payload({ price_history: { dates: ['2026-11-17', '2026-11-18'], close: [4000, 4100] } });
  assert.equal(Core.summarize(index, raw, at).price.close, 4000);
  raw.price_history.close = [null, 4100];
  assert.equal(Core.summarize(index, raw, at).price, null);
});
test('stale respects source flag and does not invent a trading calendar', () => {
  assert.equal(Core.summarize(index, payload(), '2027-01-01').stale, false);
  assert.equal(Core.summarize(index, payload({ stale: true, stale_reason: 'source delayed' }), at).staleReason, 'source delayed');
});
test('local observations are deduplicated and detach from mutable payloads', () => {
  const state = Core.initial(), summary = Core.summarize(index, payload(), at);
  const first = Core.observe(state, summary, at);
  assert.equal(first.type, 'first'); assert.equal(first.changed, false);
  const second = Core.observe(state, summary, '2026-11-18T04:01:00Z');
  assert.equal(second.type, 'unchanged');
  summary.windows[0].start = '2026-11-21';
  assert.equal(state.observations[index.id][0].windows[0].start, '2026-11-20');
  assert.equal(Core.observe(state, summary, at).type, 'changed');
  assert.equal(state.observations[index.id].length, 2);
});
test('failed loads and older asof never replace the latest local observation', () => {
  const state = Core.initial(); Core.observe(state, Core.summarize(index, payload(), at), at);
  assert.equal(Core.observe(state, Core.summarize(index, null, at), at).type, 'invalid');
  const older = Core.summarize(index, payload({ asof: '2026-11-16' }), at);
  assert.equal(Core.observe(state, older, at).type, 'older');
  assert.equal(state.observations[index.id].length, 1);
});
test('regenerated identical output does not become a new notification', () => {
  const state = Core.initial(), raw = payload();
  Core.observe(state, Core.summarize(index, raw, at), at);
  raw.generated_at = '2026-11-18T04:02:00Z'; raw.prediction_id = 'recomputed-unchanged';
  assert.equal(Core.observe(state, Core.summarize(index, raw, at), at).type, 'unchanged');
});
test('bounded observation retention is 40 snapshots per asset', () => {
  const state = Core.initial();
  for (let i = 0; i < 45; i++) {
    const raw = payload({ model_version: 'version-' + i });
    Core.observe(state, Core.summarize(index, raw, at), at);
  }
  assert.equal(state.observations[index.id].length, 40);
  assert.equal(state.observations[index.id][0].modelVersion, 'version-5');
  assert.equal(new Set(state.observations[index.id].map(v => v.id)).size, 40);
});
test('notes preserve revisions, bind exact context, and are plain text', () => {
  const state = Core.initial(), summary = Core.summarize(index, payload(), at);
  const first = Core.saveNote(state, summary, '<script>alert(1)</script>', at);
  assert.equal(first.text, '<script>alert(1)</script>');
  Core.saveNote(state, summary, '后续观点', at);
  assert.equal(state.notes.length, 2); assert.equal(Core.notesFor(state, index.id)[0].version, 2);
  assert.equal(state.notes[0].text, '<script>alert(1)</script>');
  const later = Core.summarize(index, payload({ asof: '2026-11-18' }), at);
  assert.equal(Core.saveNote(state, later, '另一期', at).version, 1);
  assert.equal(Core.saveNote(state, later, 'x'.repeat(4001), at), null);
});
test('recordVisit retains historical context while current-page URL is explicit', () => {
  const state = Core.initial(), summary = Core.summarize(index, payload(), at);
  Core.recordVisit(state, summary, at);
  assert.equal(state.recent[0].asof, '2026-11-17');
  assert.equal(state.recent[0].predictionId, null);
  assert.equal(Core.route(index, state.recent[0]).includes('asof'), false);
});
test('a new publication identity resumes exactly without inventing a model change', () => {
  const storage = memory(), state = Core.initial();
  const first = Core.summarize(index, payload({ prediction_id: 'p1' }), at);
  Core.observe(state, first, at); Core.recordVisit(state, first, at);
  const second = Core.summarize(index, payload({ prediction_id: 'p2' }), at);
  assert.equal(Core.observe(state, second, at).type, 'unchanged');
  Core.recordVisit(state, second, at);
  assert.equal(state.observations[index.id].length, 1);
  assert.equal(Core.save(storage, state), true);
  const restored = Core.load(storage);
  assert.equal(restored.recent[0].predictionId, 'p2');
  assert.equal(restored.recent[0].snapshot.predictionId, 'p2');
  assert.equal(restored.recent[1].snapshot.predictionId, 'p1');
  assert.equal(restored.observations[index.id][0].predictionId, 'p1');
});
test('recent snapshots cannot impersonate a different asset, asof, model or prediction', () => {
  for (const key of ['asset', 'asof', 'modelVersion', 'predictionId']) {
    const state = Core.initial(), summary = Core.summarize(index, payload({ prediction_id: 'p1' }), at);
    Core.recordVisit(state, summary, at);
    const snapshot = state.recent[0].snapshot;
    if (key === 'asset') snapshot.asset = stock;
    else snapshot[key] = key === 'asof' ? '2026-11-16' : 'different';
    assert.equal(Core.load(memory(JSON.stringify(state))).recent[0].snapshot, null, key);
  }
});
test('a recent unavailable result can hold context but never fabricates a snapshot', () => {
  const state = Core.initial();
  Core.recordVisit(state, Core.summarize(stock, null, at), at);
  assert.equal(state.recent[0].asof, null);
  assert.equal(state.recent[0].snapshot, null);
});
test('groups and persisted metadata never create a second watchlist', () => {
  const state = Core.initial(), storage = memory();
  assert.equal(Core.addGroup(state, '待研究'), true);
  assert.equal(Core.setGroup(state, index.id, '待研究'), true);
  assert.equal(Core.setGroup(state, '__proto__', '待研究'), false);
  assert.equal(Core.save(storage, state), true);
  assert.equal(Core.load(storage).meta[index.id].group, '待研究');
  assert.equal('assets' in Core.load(storage), false);
});
test('storage failure is observable and unknown schemas are not overwritten', () => {
  const failing = { getItem: () => { throw Error('blocked'); }, setItem: () => { throw Error('quota'); } };
  assert.equal(Core.load(failing).storageIssue, 'read_failed');
  assert.equal(Core.save(failing, Core.initial()), false);
  const newer = memory('{"version":2,"notes":["preserve"]}');
  const state = Core.load(newer);
  assert.equal(state.storageIssue, 'unsupported_version');
  assert.equal(Core.save(newer, state), false);
  assert.equal(newer.getItem(Core.KEY), '{"version":2,"notes":["preserve"]}');
});
test('an old tab cannot overwrite a newer saved note or resurrect cleared state', () => {
  const storage = memory(), a = Core.load(storage), b = Core.load(storage);
  Core.saveNote(a, Core.summarize(index, payload(), at), '保存的笔记', at);
  assert.equal(Core.save(storage, a), true);
  assert.equal(Core.save(storage, b), false);
  assert.equal(Core.load(storage).notes[0].text, '保存的笔记');
  const cleared = memory();
  assert.equal(Core.save(cleared, a), false);
});
test('persisted data is bounded and prototype keys cannot poison state', () => {
  const input = JSON.parse('{"version":1,"meta":{"__proto__":{"group":"x"}},"query":"abc","compareIds":["stock:600519","stock:600519","bad"],"scrollY":-20}');
  const state = Core.load(memory(JSON.stringify(input)));
  assert.deepEqual(state.compareIds, ['stock:600519']);
  assert.equal(state.scrollY, 0); assert.equal(Object.hasOwn(state.meta, '__proto__'), false);
});
test('changes filter and sorting survive page navigation and reload', () => {
  const storage = memory(), state = Core.initial();
  state.statusFilter = 'changed'; state.sort = 'changed';
  assert.equal(Core.save(storage, state), true);
  assert.equal(Core.load(storage).statusFilter, 'changed');
  assert.equal(Core.load(storage).sort, 'changed');
});
test('loaded local windows cannot override failed, missing or uncomputed coverage', () => {
  for (const mode of ['fail_i', 'none', 'unknown', 'missing', 'not_computed']) {
    const state = Core.initial(), summary = Core.summarize(index, payload(), at);
    Core.observe(state, summary, at);
    const observation = state.observations[index.id][0];
    if (mode === 'missing') observation.coverage = [];
    else if (mode === 'not_computed') observation.coverage.find(c => c.scale === '6-12m').status = 'not_computed';
    else observation.coverage.find(c => c.scale === '6-12m').evidence = mode;
    const restored = Core.load(memory(JSON.stringify(state))).observations[index.id][0];
    assert.equal(restored.windows.length, 0, mode);
    assert.equal(restored.status, 'evidence_hidden', mode);
  }
});
test('roundtrip keeps snapshots, notes and visit context', () => {
  const state = Core.initial(), summary = Core.summarize(index, payload(), at), storage = memory();
  Core.observe(state, summary, at); Core.recordVisit(state, summary, at); Core.saveNote(state, summary, '关注理由', at);
  assert.equal(Core.save(storage, state), true);
  const restored = Core.load(storage);
  assert.equal(restored.observations[index.id][0].windows[0].start, '2026-11-20');
  assert.equal(restored.notes[0].asof, '2026-11-17');
  assert.equal(restored.recent[0].assetId, index.id);
});
test('observations, groups and notes survive for assets beyond the 100th entry', () => {
  const state = Core.initial(), summary = Core.summarize(index, payload(), at);
  for (let i = 1; i <= 120; i++) {
    const code = String(600000 + i);
    const asset = Core.asset('stock', code, '标的 ' + i);
    state.meta[asset.id] = { group: '观察' };
    state.observations[asset.id] = [{ ...summary, asset, observedAt: at, id: 'observation-' + i }];
    state.notes.push({ id: 'note-' + i, assetId: asset.id, asof: summary.asof,
      predictionId: summary.predictionId, modelVersion: summary.modelVersion,
      text: '笔记 ' + i, createdAt: at, version: 1 });
  }
  const storage = memory();
  assert.equal(Core.save(storage, state), true);
  const restored = Core.load(storage), id = 'stock:600101';
  assert.equal(restored.observations[id].length, 1);
  assert.equal(restored.meta[id].group, '观察');
  assert.equal(restored.notes.find(note => note.assetId === id).text, '笔记 101');
});
