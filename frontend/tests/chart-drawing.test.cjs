'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Drawing = require('../app/chart-drawing.js');

const allowed = Drawing.TYPES.map((kind, index) => ({ id: String(index), kind }));

test('drawing imports keep exactly the five supported tool kinds', () => {
  const filtered = Drawing.filterDrawings(allowed.concat([
    { id: 'circle', kind: 'circle' },
    null,
    { id: 'missing-kind' },
  ]));
  assert.deepEqual(filtered, allowed);
});

test('storage wrapper preserves local Shanghai creation dates and rejects unsupported entries', () => {
  const createdAt = Drawing.shanghaiDate('2025-05-23T16:30:00Z');
  assert.equal(createdAt, '2025-05-24');
  const wrapped = Drawing.wrapStorage([
    { createdAt: '2025-05-22', drawing: allowed[0] },
    allowed[1],
    { kind: 'circle' },
  ], createdAt);
  assert.deepEqual(wrapped, {
    v: 1,
    items: [
      { createdAt: '2025-05-22', drawing: allowed[0] },
      { createdAt: createdAt, drawing: allowed[1] },
    ],
  });
  assert.deepEqual(Drawing.unwrapStorage(JSON.stringify(wrapped)), wrapped.items);
  assert.deepEqual(Drawing.unwrapStorage({ v: 2, items: wrapped.items }), []);
  assert.deepEqual(Drawing.unwrapStorage({
    v: 1,
    items: [{ createdAt: '2025-02-30', drawing: allowed[0] }],
  }), []);
});

test('storage key lowercases resolved symbols', () => {
  assert.equal(Drawing.storageKey(' SH600519 '), 'lppl.drawings.v1:sh600519');
});

test('history drawings start hidden and only later creation dates are captioned', () => {
  assert.equal(Drawing.historyVisibility('2025-05-23'), false);
  assert.equal(Drawing.historyVisibility(null), true);
  assert.deepEqual(Drawing.lateDrawingDates([
    { createdAt: '2025-05-23' },
    { createdAt: '2025-05-24' },
    { createdAt: '2025-05-24' },
    { createdAt: '2025-05-22' },
  ], '2025-05-23'), ['2025-05-24']);
});

test('undo snapshots retain only the newest fifty entries', () => {
  const stack = Array.from({ length: 60 }, (_, index) => JSON.stringify(index));
  const capped = Drawing.pushUndo(stack, JSON.stringify(60));
  assert.equal(capped.length, 50);
  assert.equal(capped[0], JSON.stringify(11));
  assert.equal(capped[49], JSON.stringify(60));
  assert.equal(Drawing.pushUndo(capped, JSON.stringify(60)).length, 50);
});

test('stale writes merge unseen storage ids without restoring local deletions', () => {
  const item = (id, text = id) => ({
    createdAt: '2025-05-22',
    drawing: { id, kind: 'horizontal-line', text },
  });
  const merged = Drawing.mergeRecords(
    [item('local', 'edited locally')],
    [item('local', 'newer in storage'), item('remote'), item('deleted')],
    new Set(['deleted']),
  );
  assert.deepEqual(merged, [item('local', 'edited locally'), item('remote')]);
});

test('text editor recognizes IME composition key events', () => {
  assert.equal(Drawing.isImeCompositionKey({ isComposing: true, keyCode: 13 }), true);
  assert.equal(Drawing.isImeCompositionKey({ isComposing: false, keyCode: 229 }), true);
  assert.equal(Drawing.isImeCompositionKey({ isComposing: false, keyCode: 13 }), false);
});

test('text drawings require non-whitespace content before submission', () => {
  assert.equal(Drawing.hasTextContent(' note '), true);
  assert.equal(Drawing.hasTextContent(' \n\t'), false);
});
