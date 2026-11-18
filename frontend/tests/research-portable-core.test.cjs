const { test } = require('node:test');
const assert = require('node:assert/strict');
const Portable = require('../app/research-portable-core.js');
const Workspace = require('../app/research-workspace-core.js');
const Personal = require('../app/research-personal-core.js');

const at = '2026-11-18T04:00:00.000Z';
const [INDEX, STOCK, WORKSPACE, PERSONAL] = Portable.KEYS;
function store(values = {}, hook) {
  const data = new Map(Object.entries(values));
  const api = {
    getItem: key => data.has(key) ? data.get(key) : null,
    setItem(key, value) { if (hook) hook(key, value, data); data.set(key, value); },
    removeItem: key => data.delete(key),
  };
  return api;
}
function bundle(sections) {
  return { format: Portable.FORMAT, version: 1, exportedAt: at,
    privacy: 'PRIVATE_BACKUP', sections };
}
function parse(sections) { return Portable.parse(JSON.stringify(bundle(sections)), Personal); }
function note(id = 'note-1', text = '保留原始研究笔记', extra = {}) {
  return { id, assetId: 'stock:600519', asof: '2026-11-17', predictionId: 'p-1',
    modelVersion: 'v1', text, createdAt: at, version: 1, ...extra };
}
function workspace(notes = [], extra = {}) { return { ...Workspace.initial(), notes, ...extra }; }
function personal(extra = {}) {
  return { ...Personal.initial(), holdings: [{ code: '600519', name: '贵州茅台',
    shares: 100, cost: 0, currency: 'CNY', updatedAt: at }], ...extra };
}
function row(extra = {}) {
  return { ...Workspace.summarize(Workspace.asset('index', 'sh000001', '上证指数'), {
    symbol: 'sh000001', asof: '2026-11-17', model_version: 'v1',
    top: { lppls_confidence: { evidence: 'none' }, indicators: {}, scale_clusters: {} },
  }, at), id: 'obs-1', observedAt: at, ...extra };
}

test('private file backup round-trips all supported partitions and preserves zero cost', () => {
  const values = { [INDEX]: JSON.stringify(['sh000001']), [STOCK]: JSON.stringify(['600519']),
    [WORKSPACE]: JSON.stringify(workspace([note()])), [PERSONAL]: JSON.stringify(personal()) };
  const exported = Portable.create(store(values), at, Personal);
  const imported = Portable.parse(JSON.stringify(exported), Personal);
  assert.equal(imported.privacy, 'PRIVATE_BACKUP');
  assert.equal(imported.sections[PERSONAL].holdings[0].cost, 0);
  assert.equal(imported.sections[WORKSPACE].notes[0].text, '保留原始研究笔记');
  assert.match(exported.observations, /not first public predictions/);
  assert.deepEqual(Object.keys(imported.sections), Portable.KEYS);
});

test('unsupported envelopes, partitions, versions and timestamps are rejected', () => {
  const valid = bundle({ [STOCK]: ['600519'] });
  for (const patch of [{ version: 2 }, { format: 'other' }, { privacy: 'PUBLIC' },
    { exportedAt: 'invalid' }, { sections: [] }, { sections: {} },
    { sections: { unknown: [] } }]) {
    assert.throws(() => Portable.parse(JSON.stringify({ ...valid, ...patch }), Personal));
  }
  assert.throws(() => parse({ [WORKSPACE]: workspace([], { version: 2 }) }));
  assert.throws(() => parse({ [PERSONAL]: personal({ version: 2 }) }));
  assert.throws(() => Portable.parse('{}', Personal));
  assert.throws(() => Portable.parse(null, Personal));
});

test('backup byte limit measures UTF-8 and rejects deeply nested or dangerous keys', () => {
  assert.throws(() => Portable.parse(' '.repeat(Portable.MAX_BYTES + 1), Personal), /6 MB/);
  assert.throws(() => Portable.parse('中'.repeat(Math.floor(Portable.MAX_BYTES / 3) + 1), Personal), /6 MB/);
  for (const key of ['__proto__', 'constructor', 'prototype']) {
    const text = JSON.stringify(bundle({ [STOCK]: ['600519'] }));
    assert.throws(() => Portable.parse(text.slice(0, -1) + ',"' + key + '":{"polluted":true}}', Personal), /字段/);
  }
  assert.equal({}.polluted, undefined);
  const deep = bundle({ [STOCK]: ['600519'] });
  let current = deep;
  for (let i = 0; i < 26; i++) { current.extra = {}; current = current.extra; }
  assert.throws(() => Portable.parse(JSON.stringify(deep), Personal), /过深/);
});

test('watchlists reject unsupported identity, stock/index ambiguity, duplicates and overflow', () => {
  for (const values of [['sh600519'], ['600519', '600519'], ['999999'], ['600519&x=1'], [600519]]) {
    assert.throws(() => parse({ [STOCK]: values }));
  }
  for (const values of [['000001'], ['sh600519'], ['sh000001', 'sh000001']]) {
    assert.throws(() => parse({ [INDEX]: values }));
  }
  assert.deepEqual(parse({ [STOCK]: ['000001'], [INDEX]: ['sh000001'] }).sections[STOCK], ['000001']);
  assert.throws(() => parse({ [STOCK]: Array.from({ length: 51 }, (_, i) => '60' + String(i).padStart(4, '0')) }));
});

test('malformed notes, groups and mismatched observation assets cannot be silently discarded', () => {
  for (const invalid of [note('bad', 'x', { assetId: 'stock:bad' }), note('bad', 'x', { createdAt: 'invalid' }),
    note('bad', 'x', { version: 0 }), note('bad', 'x'.repeat(4001))]) {
    assert.throws(() => parse({ [WORKSPACE]: workspace([invalid]) }));
  }
  assert.throws(() => parse({ [WORKSPACE]: workspace([], { groups: ['a', 'a'] }) }));
  assert.throws(() => parse({ [WORKSPACE]: workspace([], { observations: { 'stock:600519': [row()] } }) }));
  assert.throws(() => parse({ [WORKSPACE]: workspace([], { storageIssue: 'read_failed' }) }));
  assert.throws(() => parse({ [WORKSPACE]: workspace([note('bad-date', '有截止日的笔记', { asof: '2026-02-30' })]) }));
  assert.equal(parse({ [WORKSPACE]: workspace([note('unbound', '未绑定日期', { asof: null })]) })
    .sections[WORKSPACE].notes[0].asof, null);
});

test('personal restore refuses malformed holdings/read ledger rather than clearing them', () => {
  for (const holdings of [{ code: '600519' }, null, '600519', [personal().holdings[0], personal().holdings[0]],
    [{ ...personal().holdings[0], shares: 0 }], [{ ...personal().holdings[0], cost: null }],
    [{ ...personal().holdings[0], currency: 'USD' }]]) {
    assert.throws(() => parse({ [PERSONAL]: personal({ holdings }) }));
  }
  for (const readChanges of ['not-an-array', null, ['same', 'same'], [9], ['x'.repeat(301)]]) {
    assert.throws(() => parse({ [PERSONAL]: personal({ readChanges }) }));
  }
});

test('empty local storage does not create an unusable backup', () => {
  assert.throws(() => Portable.create(store(), at, Personal), /空|记录|没有/);
});

test('workspace import merges recent visits and snapshots by identity, time and cap', () => {
  const base = Date.parse(at), local = workspace(), incoming = workspace();
  const addVisit = (state, predictionId, minute, source) => Workspace.recordVisit(state,
    row({ asof: '2026-11-17', predictionId, source }),
    new Date(base + minute * 60_000).toISOString());
  for (let i = 0; i < 6; i++) addVisit(local, 'local-' + i, i, 'local snapshot');
  addVisit(incoming, 'local-0', 20, 'newer imported snapshot');
  for (let i = 0; i < 5; i++) addVisit(incoming, 'remote-' + i, 21 + i, 'imported snapshot');
  const merged = Portable.mergeWorkspace(local, incoming);
  const keys = merged.recent.map(recent => [recent.assetId, recent.asof, recent.predictionId, recent.modelVersion].join('|'));
  assert.equal(merged.recent.length, 10);
  assert.equal(new Set(keys).size, 10);
  assert.deepEqual(merged.recent.map(recent => recent.visitedAt),
    merged.recent.map(recent => recent.visitedAt).slice().sort().reverse());
  assert.ok(merged.recent.some(recent => recent.predictionId === 'remote-4' &&
    recent.snapshot.source === 'imported snapshot'));
  assert.equal(merged.recent.find(recent => recent.predictionId === 'local-0').visitedAt,
    new Date(base + 20 * 60_000).toISOString());
  assert.equal(merged.recent.find(recent => recent.predictionId === 'local-0').snapshot.source,
    'newer imported snapshot');
  assert.equal(merged.recent.some(recent => recent.predictionId === 'local-1'), false);
});

test('merging keeps both conflicting note bodies and their dates without changing local controls', () => {
  const local = workspace([note('shared', '本机旧笔记')], { revision: 3, selectedId: 'stock:600519', query: '贵州', groups: ['观察'] });
  const incoming = workspace([note('shared', '另一台设备的笔记')], { groups: ['持有'], selectedId: 'index:sh000001' });
  const merged = Portable.mergeWorkspace(local, incoming);
  assert.deepEqual(new Set(merged.notes.map(n => n.text)), new Set(['本机旧笔记', '另一台设备的笔记']));
  assert.equal(Workspace.notesFor(merged, 'stock:600519')[0].text, '本机旧笔记');
  assert.equal(new Set(merged.notes.map(n => n.id)).size, 2);
  assert.equal(merged.notes[0].createdAt, at);
  assert.equal(merged.selectedId, 'stock:600519');
  assert.equal(merged.query, '贵州');
  assert.deepEqual(merged.groups, ['观察', '持有']);
  assert.equal(Portable.mergeWorkspace(merged, incoming).notes.length, 2);
  assert.equal(merged.notes.find(n => n.text === '另一台设备的笔记').imported, true);
  assert.notEqual(merged.notes.find(n => n.text === '本机旧笔记').imported, true);
  assert.equal(local.notes.length, 1);
});

test('note and observation capacity rejects the whole merge without deleting old records', () => {
  const local = workspace(Array.from({ length: 200 }, (_, i) => note('n-' + i, '旧记录-' + i)));
  assert.throws(() => Portable.mergeWorkspace(local, workspace([note('new', '新增')])), /200/);
  assert.equal(local.notes.length, 200);
  const history = Array.from({ length: 40 }, (_, i) => row({ id: 'o-' + i,
    observedAt: new Date(Date.parse(at) + i * 1000).toISOString() }));
  assert.throws(() => Portable.mergeWorkspace(workspace([], { observations: { 'index:sh000001': history } }),
    workspace([], { observations: { 'index:sh000001': [row({ id: 'later', observedAt: '2026-11-19T00:00:00Z' })] } })), /40/);
  assert.equal(history.length, 40);
});

test('an older imported note cannot become the current note for an already newer context', () => {
  const local = workspace([note('local-new', '较新的本机判断', { version: 3 })]);
  const incoming = workspace([note('remote-old', '旧设备的较早判断', {
    createdAt: '2026-11-10T04:00:00.000Z', version: 1,
  })]);
  const merged = Portable.mergeWorkspace(local, incoming);
  assert.equal(merged.notes.length, 2);
  assert.equal(Workspace.notesFor(merged, 'stock:600519')[0].text, '较新的本机判断');
});

test('new note version advances beyond imported versions without rewriting their provenance', () => {
  const local = workspace([note('local', '本机判断', { version: 3 })]);
  const incoming = workspace([note('remote', '更早创建但版本更多的设备记录', {
    createdAt: '2026-11-10T04:00:00.000Z', version: 8,
  })]);
  const merged = Portable.mergeWorkspace(local, incoming);
  const saved = Workspace.saveNote(merged, { asset: Workspace.asset('stock', '600519', '贵州茅台'),
    asof: '2026-11-17', predictionId: 'p-1', modelVersion: 'v1' }, '综合后的新判断', '2026-11-18T05:00:00.000Z');
  assert.equal(saved.version, 9);
  assert.notEqual(saved.imported, true);
  assert.equal(merged.notes.find(n => n.id === 'remote').version, 8);
  assert.equal(merged.notes.find(n => n.id === 'remote').imported, true);
});

test('imported historical observations keep original retrieval times and cannot overwrite newer rows', () => {
  const newest = row({ id: 'new', asof: '2026-11-17' });
  const old = row({ id: 'old', asof: '2026-11-10', observedAt: '2026-11-11T00:00:00Z' });
  const merged = Portable.mergeWorkspace(workspace([], { observations: { 'index:sh000001': [newest] } }),
    workspace([], { observations: { 'index:sh000001': [old] } }));
  const rows = merged.observations['index:sh000001'];
  assert.equal(rows.at(-1).id, 'new');
  assert.equal(rows[0].observedAt, '2026-11-11T00:00:00.000Z');
  assert.equal(rows.length, 2);
  assert.equal('first_published_at' in rows[0], false);
});

test('only selected partitions change, workspace notes merge and revisions advance', () => {
  const s = store({ [INDEX]: '["sh000001"]', [STOCK]: '["600519"]',
    [WORKSPACE]: JSON.stringify(workspace([note('old')], { revision: 7 })) });
  const before = Portable.snapshot(s);
  const imported = parse({ [STOCK]: ['000001'], [WORKSPACE]: workspace([note('new', '新笔记')], { revision: 2 }) });
  assert.equal(Portable.apply(s, before, imported, [WORKSPACE, WORKSPACE], Personal), 1);
  assert.equal(s.getItem(STOCK), before[STOCK]);
  assert.equal(s.getItem(INDEX), before[INDEX]);
  const current = JSON.parse(s.getItem(WORKSPACE));
  assert.equal(current.notes.length, 2);
  assert.equal(current.revision, 8);
});

test('preview becomes stale after another tab edits any tracked key; no writes occur', () => {
  const s = store({ [STOCK]: '["600519"]' });
  const before = Portable.snapshot(s);
  s.setItem(INDEX, '["sh000001"]');
  assert.throws(() => Portable.apply(s, before, parse({ [STOCK]: ['000001'] }), [STOCK], Personal), /重新预览/);
  assert.equal(s.getItem(STOCK), '["600519"]');
  assert.equal(s.getItem(INDEX), '["sh000001"]');
});

test('unsupported or corrupt local workspace is retained byte-for-byte on import', () => {
  for (const local of [workspace([note('broken', '旧笔记', { createdAt: 'invalid' })]),
    workspace([note()], { version: 2 })]) {
    const raw = JSON.stringify(local), s = store({ [WORKSPACE]: raw });
    const before = Portable.snapshot(s);
    assert.throws(() => Portable.apply(s, before, parse({ [WORKSPACE]: workspace([note('new', '新')] ) }), [WORKSPACE], Personal));
    assert.equal(s.getItem(WORKSPACE), raw);
  }
});

test('invalid selection and preflight failure do not write any key', () => {
  const s = store({ [STOCK]: '["600519"]' }), before = Portable.snapshot(s);
  const b = parse({ [STOCK]: ['000001'] });
  assert.throws(() => Portable.apply(s, before, b, [], Personal));
  assert.throws(() => Portable.apply(s, before, b, [STOCK, 'bad'], Personal));
  assert.deepEqual(Portable.snapshot(s), before);
});

test('multi-partition storage failure rolls back earlier writes including originally missing keys', () => {
  for (const initial of [{ [INDEX]: '["sh000300"]', [STOCK]: '["600519"]' }, { [STOCK]: '["600519"]' }]) {
    const s = store(initial, key => { if (key === STOCK) throw new Error('quota'); });
    const before = Portable.snapshot(s);
    assert.throws(() => Portable.apply(s, before, parse({ [INDEX]: ['sh000001'], [STOCK]: ['000001'] }), [INDEX, STOCK], Personal), /已恢复原记录/);
    assert.deepEqual(Portable.snapshot(s), before);
  }
});

test('rollback never overwrites a concurrent edit and reports partial recovery', () => {
  const s = store({ [INDEX]: '["sh000300"]', [STOCK]: '["600519"]' }, (key, value, map) => {
    if (key === STOCK) { map.set(INDEX, '["sz399006"]'); throw new Error('quota'); }
  });
  const before = Portable.snapshot(s);
  assert.throws(() => Portable.apply(s, before, parse({ [INDEX]: ['sh000001'], [STOCK]: ['000001'] }), [INDEX, STOCK], Personal), /部分记录未能自动恢复/);
  assert.equal(s.getItem(INDEX), '["sz399006"]');
  assert.equal(s.getItem(STOCK), '["600519"]');
});
