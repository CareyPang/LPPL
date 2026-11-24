'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const AlertLedger = require('../app/alert-ledger.js');

function frame(asof, window = ['2020-02-01', '2020-02-10'], options = {}) {
  return {
    asof,
    split: options.split || 'dev',
    close: options.close === undefined ? 100 : options.close,
    w: { '6-12m': window },
    conf: { '6-12m': 0.75 },
    ...(options.clusters ? { clusters: options.clusters } : {}),
  };
}

test('episodes split at frames without an interval', () => {
  const rows = AlertLedger.episodes([
    frame('2020-01-01'),
    frame('2020-01-08', null),
    frame('2020-01-15', ['2020-02-02', '2020-02-11'], { close: null }),
    frame('2020-01-22', ['2020-02-03', '2020-02-12']),
  ], [], '6-12m');

  assert.deepEqual(rows.map(row => [row.first_asof, row.last_asof, row.weeks]), [
    ['2020-01-01', '2020-01-01', 1],
    ['2020-01-15', '2020-01-22', 2],
  ]);
});

test('frames with a window and no close still form episodes', () => {
  const rows = AlertLedger.episodes([
    frame('2020-01-01', ['2020-02-01', '2020-02-10'], { close: null }),
    frame('2020-01-08', ['2020-02-02', '2020-02-11'], { close: null }),
  ], [], '6-12m');

  assert.equal(rows.length, 1);
  assert.equal(rows[0].weeks, 2);
});

test('frame windows fall back to the leading cluster interval', () => {
  const rows = AlertLedger.episodes([
    frame('2020-01-01', null, {
      clusters: {
        '6-12m': [
          { q20_date: '2020-03-01', q80_date: '2020-03-10', share: 0.4 },
          { q20_date: '2020-02-01', q80_date: '2020-02-10', share: 0.6 },
        ],
      },
    }),
  ], [], '6-12m');

  assert.deepEqual(rows[0].window, ['2020-02-01', '2020-02-10']);
});

test('episode metadata uses the first and last windows and first-frame split', () => {
  const rows = AlertLedger.episodes([
    frame('2020-01-01', ['2020-02-01', '2020-02-10'], { split: 'dev' }),
    frame('2020-01-08', ['2020-02-04', '2020-02-13'], { split: 'test' }),
  ], [], '6-12m');

  assert.deepEqual(rows[0], {
    scale: '6-12m',
    first_asof: '2020-01-01',
    last_asof: '2020-01-08',
    weeks: 2,
    split: 'dev',
    window: ['2020-02-01', '2020-02-10'],
    last_window: ['2020-02-04', '2020-02-13'],
    clusters: null,
    last_clusters: null,
    next_top: null,
    top_vs_window: null,
    top_vs_main: null,
    days_to_top: null,
  });
});

test('next top is the first top strictly after first_asof and reports calendar days', () => {
  const rows = AlertLedger.episodes([frame('2020-01-01')], [
    { date: '2020-01-01', max_dd: 0.5 },
    { date: '2020-01-20', max_dd: 0.2 },
    { date: '2020-01-10', max_dd: 0.3 },
  ], '6-12m');

  assert.deepEqual(rows[0].next_top, { date: '2020-01-10', max_dd: 0.3 });
  assert.equal(rows[0].days_to_top, 9);
  assert.equal(AlertLedger.episodes([frame('2020-01-01')], [
    { date: '2020-01-01', max_dd: 0.5 },
  ], '6-12m')[0].next_top, null);
});

test('top relation classifies before, inclusive bounds, and after', () => {
  const window = ['2020-02-01', '2020-02-10'];
  const relation = date => AlertLedger.episodes([frame('2020-01-01', window)], [
    { date, max_dd: 0.1 },
  ], '6-12m')[0].top_vs_window;

  assert.equal(relation('2020-01-31'), 'before');
  assert.equal(relation('2020-02-01'), 'inside');
  assert.equal(relation('2020-02-10'), 'inside');
  assert.equal(relation('2020-02-11'), 'after');
});

test('main-cluster relation classifies tops before, inside, and after the first cluster', () => {
  const cluster = {
    rank: 'main',
    share: 0.6,
    q20_date: '2020-02-01',
    q80_date: '2020-02-10',
  };
  const relation = date => AlertLedger.episodes([
    frame('2020-01-01', ['2020-01-20', '2020-02-20'], {
      clusters: { '6-12m': [cluster] },
    }),
  ], [{ date, max_dd: -0.2 }], '6-12m')[0].top_vs_main;

  assert.equal(relation('2020-01-31'), 'before');
  assert.equal(relation('2020-02-01'), 'inside');
  assert.equal(relation('2020-02-10'), 'inside');
  assert.equal(relation('2020-02-11'), 'after');
});

test('episodes preserve first and last cluster arrays and fall back for legacy frames', () => {
  const first = {
    rank: 'secondary',
    share: 0.4,
    q20_date: '2020-02-05',
    q80_date: '2020-02-15',
  };
  const main = {
    rank: 'main',
    share: 0.6,
    q20_date: '2020-02-01',
    q80_date: '2020-02-10',
  };
  const rows = AlertLedger.episodes([
    frame('2020-01-01', ['2020-01-20', '2020-02-20'], {
      clusters: { '6-12m': [first, main] },
    }),
    frame('2020-01-08', ['2020-01-22', '2020-02-22'], {
      clusters: { '6-12m': [main] },
    }),
  ], [{ date: '2020-02-12', max_dd: -0.2 }], '6-12m');

  assert.deepEqual(rows[0].clusters.map(cluster => cluster.rank), ['main', 'secondary']);
  assert.deepEqual(rows[0].last_clusters, [main]);
  assert.equal(rows[0].top_vs_window, 'inside');
  assert.equal(rows[0].top_vs_main, 'after');

  const legacy = AlertLedger.episodes([
    frame('2020-01-01'),
  ], [{ date: '2020-02-05', max_dd: -0.2 }], '6-12m')[0];
  assert.equal(legacy.clusters, null);
  assert.equal(legacy.top_vs_window, 'inside');
  assert.equal(legacy.top_vs_main, null);
});

test('lockedAsOf reflects each episode prefix and ignores later appended frames', () => {
  const frames = [
    frame('2020-01-01'),
    frame('2020-01-08'),
    frame('2020-01-15'),
    frame('2020-01-22'),
  ];
  const locked = AlertLedger.lockedAsOf(frames, [], '6-12m');

  assert.equal(locked.get('2020-01-01').high_confidence, false);
  assert.equal(locked.get('2020-01-08').high_confidence, false);
  assert.equal(locked.get('2020-01-15').high_confidence, true);
  assert.equal(locked.get('2020-01-22').high_confidence, true);

  const withFuture = AlertLedger.lockedAsOf([
    ...frames,
    frame('2020-01-29'),
  ], [], '6-12m');
  frames.forEach((item) => {
    assert.deepEqual(withFuture.get(item.asof), locked.get(item.asof));
  });
});

test('an explicit empty cluster list is not treated as missing metadata', () => {
  const episode = AlertLedger.episodes([
    frame('2020-01-01', undefined, { clusters: { '6-12m': [] } }),
  ], [{ date: '2020-02-05', max_dd: -0.2 }], '6-12m')[0];

  assert.deepEqual(episode.clusters, []);
  assert.equal(episode.top_vs_main, null);
});

test('unsorted frames are ordered by asof and confidence is never returned', () => {
  const rows = AlertLedger.episodes([
    frame('2020-01-15'),
    frame('2020-01-01'),
    frame('2020-01-08'),
  ], [], '6-12m');

  assert.equal(rows.length, 1);
  assert.equal(rows[0].first_asof, '2020-01-01');
  assert.equal(rows[0].last_asof, '2020-01-15');
  assert.equal(rows[0].weeks, 3);
  assert.equal(Object.hasOwn(rows[0], 'conf'), false);
  assert.equal(JSON.stringify(rows).includes('"conf"'), false);
});

test('sh000001 v2.2 history keeps 134 frozen weeks and 141 total weeks with a 6–12 month interval', () => {
  const fixturePath = path.join(__dirname, '../../web/mock/data/sh000001_history.json');
  const history = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const frozenFrames = history.frames.filter((frame) => frame.split !== 'live');
  const frozenRows = AlertLedger.episodes(frozenFrames, history.tops, '6-12m');
  const allRows = AlertLedger.episodes(history.frames, history.tops, '6-12m');

  assert.equal(frozenRows.reduce((sum, row) => sum + row.weeks, 0), 134);
  assert.equal(allRows.reduce((sum, row) => sum + row.weeks, 0), 141);
});
