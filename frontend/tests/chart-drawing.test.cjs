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

test('stale writes apply only locally changed ids over the latest stored records', () => {
  const item = (id, text = id) => ({
    createdAt: '2025-05-22',
    drawing: { id, kind: 'horizontal-line', text },
  });
  const merged = Drawing.mergeRecords(
    [item('local', 'stale local copy')],
    [item('local', 'newer in storage'), item('remote'), item('deleted')],
    new Set(['deleted']),
    new Set(['local']),
  );
  assert.deepEqual(merged, [item('local', 'stale local copy'), item('remote')]);
  assert.deepEqual(
    Drawing.mergeRecords(
      [item('local', 'stale local copy')],
      [item('local', 'newer in storage'), item('remote')],
      new Set(),
      new Set(['remote']),
    ),
    [item('local', 'newer in storage'), item('remote')],
  );
});

test('another tab deletion is not resurrected by a stale tab adding a drawing', () => {
  const item = (id) => ({
    createdAt: '2025-05-22',
    drawing: { id, kind: 'horizontal-line' },
  });
  let storage = JSON.stringify(Drawing.wrapStorage([item('deleted'), item('kept')]));
  const openTab = () => ({
    items: Drawing.unwrapStorage(storage),
    changedIds: new Set(),
    deletedIds: new Set(),
  });
  const saveTab = (tab) => {
    const latest = Drawing.unwrapStorage(storage);
    const merged = Drawing.mergeRecords(tab.items, latest, tab.deletedIds, tab.changedIds);
    storage = JSON.stringify(Drawing.wrapStorage(merged));
    tab.changedIds.clear();
    tab.deletedIds.clear();
  };
  const tabA = openTab();
  const tabB = openTab();

  tabB.items = tabB.items.filter((record) => record.drawing.id !== 'deleted');
  tabB.deletedIds.add('deleted');
  saveTab(tabB);

  tabA.items.push(item('new-from-a'));
  tabA.changedIds.add('new-from-a');
  saveTab(tabA);

  assert.deepEqual(
    Drawing.unwrapStorage(storage).map((record) => record.drawing.id),
    ['kept', 'new-from-a'],
  );
});

test('another tab modification survives a stale tab saving a new drawing', () => {
  const item = (id, text = id) => ({
    createdAt: '2025-05-22',
    drawing: { id, kind: 'horizontal-line', text },
  });
  let storage = JSON.stringify(Drawing.wrapStorage([item('shared', 'original')]));
  const openTab = () => ({
    items: Drawing.unwrapStorage(storage),
    changedIds: new Set(),
    deletedIds: new Set(),
  });
  const saveTab = (tab) => {
    const latest = Drawing.unwrapStorage(storage);
    const merged = Drawing.mergeRecords(tab.items, latest, tab.deletedIds, tab.changedIds);
    storage = JSON.stringify(Drawing.wrapStorage(merged));
    tab.changedIds.clear();
    tab.deletedIds.clear();
  };
  const tabA = openTab();
  const tabB = openTab();

  tabB.items = tabB.items.map((record) => item(record.drawing.id, 'updated by b'));
  tabB.changedIds.add('shared');
  saveTab(tabB);

  tabA.items.push(item('new-from-a'));
  tabA.changedIds.add('new-from-a');
  saveTab(tabA);

  const saved = Drawing.unwrapStorage(storage);
  assert.equal(saved.find((record) => record.drawing.id === 'shared').drawing.text, 'updated by b');
  assert.ok(saved.some((record) => record.drawing.id === 'new-from-a'));
});

test('undoing a local deletion can restore the drawing after saving', () => {
  const item = { createdAt: '2025-05-22', drawing: { id: 'restored', kind: 'rectangle' } };
  let storage = JSON.stringify(Drawing.wrapStorage([item]));
  let latest = Drawing.unwrapStorage(storage);

  let afterDelete = Drawing.mergeRecords([], latest, new Set(['restored']), new Set());
  storage = JSON.stringify(Drawing.wrapStorage(afterDelete));
  assert.deepEqual(Drawing.unwrapStorage(storage), []);

  latest = Drawing.unwrapStorage(storage);
  const afterUndo = Drawing.mergeRecords([item], latest, new Set(), new Set(['restored']));
  storage = JSON.stringify(Drawing.wrapStorage(afterUndo));
  assert.deepEqual(Drawing.unwrapStorage(storage), [item]);
});

test('deleting an actively edited text drawing closes its editor and keeps it deleted', () => {
  const item = { createdAt: '2025-05-22', drawing: { id: 'text-1', kind: 'text', text: 'note' } };
  const pendingIds = new Set(['text-1']);
  let editorOpen = true;
  const closed = Drawing.closeEditorIfDeleted(
    { drawing: item.drawing },
    new Set(['text-1']),
    pendingIds,
    () => { editorOpen = false; },
  );
  assert.equal(closed, true);
  assert.equal(editorOpen, false);
  assert.equal(pendingIds.has('text-1'), false);

  const storageAfterDelete = Drawing.mergeRecords([], [item], new Set(['text-1']), new Set());
  assert.deepEqual(storageAfterDelete, []);
});

test('clear-all suppresses every id read from storage', () => {
  const stored = [
    { createdAt: '2025-05-22', drawing: { id: 'local', kind: 'horizontal-line' } },
    { createdAt: '2025-05-22', drawing: { id: 'remote', kind: 'rectangle' } },
  ];
  const deletedIds = new Set(stored.map((item) => item.drawing.id));
  assert.deepEqual(Drawing.mergeRecords([], stored, deletedIds), []);
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
