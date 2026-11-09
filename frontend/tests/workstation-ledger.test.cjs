'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { create, normalize } = require('../app/workstation-ledger.js');

function storage(seed = {}, failing = false) {
  const values = new Map(Object.entries(seed));
  return {
    getItem(key) { if (failing) throw Error('read failed'); return values.get(key) ?? null; },
    setItem(key, value) { if (failing) throw Error('write failed'); values.set(key, value); },
    values,
  };
}

test('watchlist and recent analysis persist with asof/source/evidence/stale provenance', () => {
  const store = storage(), clock = () => Date.parse('2026-11-08T01:02:03Z');
  const ledger = create({ storage: store, now: clock });
  ledger.toggleWatch({ code: 'sh600519', symbol: 'sh600519', name: '贵州茅台' });
  ledger.touchRecent({ code: 'sh600519', name: '贵州茅台', asof: '2026-11-07', analysis_asof: '2026-11-06',
    source: 'akshare', evidence_status: 'research_candidate', status: 'stale', stale: true });
  const row = ledger.snapshot().recent[0];
  assert.equal(row.code, '600519');
  assert.equal(row.asof, '2026-11-07');
  assert.equal(row.source, 'akshare');
  assert.equal(row.evidence_status, 'research_candidate');
  assert.equal(row.stale, true);
  ledger.touchRecent({ code: '600519', asof: '2026-11-08', stale: false });
  assert.equal(ledger.snapshot().recent[0].stale, false);
  assert.equal(ledger.isWatched({ code: '600519' }), true);
  assert.match(store.values.get('lppl.workstation.ledger.v1'), /workstation-ledger.v1/);
});

test('analysis revision rows are append-only and duplicate windows are ignored', () => {
  const ledger = create({ storage: storage(), now: () => Date.parse('2026-11-08T01:02:03Z') });
  const record = { code: '600519', asof: '2026-11-06', source_sha: 'sha-1', evidence: 'research_candidate',
    analysis: { windows: [{ start: '2026-11-16', end: '2026-11-20', claim_kind: 'new', evidence: 'research_candidate' }] } };
  ledger.recordAnalysis(record); ledger.recordAnalysis(record);
  assert.equal(ledger.snapshot().revisions.length, 1);
  ledger.recordAnalysis({ ...record, source_sha: 'sha-2', analysis: { windows: [
    { start: '2026-11-17', end: '2026-11-24', claim_kind: 'revision', evidence: 'research_candidate' },
  ] } });
  const rows = ledger.snapshot().revisions;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].kind, 'revision');
  assert.equal(rows[1].source, 'sha-1');
});

test('malformed or unavailable storage falls back to memory without throwing', () => {
  const malformed = storage({ 'lppl.workstation.ledger.v1': '{' });
  const ledger = create({ storage: malformed });
  assert.deepEqual(normalize(ledger.snapshot()).watchlist, []);
  ledger.toggleWatch({ code: '000001' });
  assert.equal(ledger.isWatched({ code: '000001' }), true);
  const unavailable = create({ storage: storage({}, true) });
  unavailable.touchRecent({ code: '000001', asof: '2026-11-08', evidence_status: 'NOT_ESTABLISHED' });
  assert.equal(unavailable.snapshot().recent[0].code, '000001');
});

