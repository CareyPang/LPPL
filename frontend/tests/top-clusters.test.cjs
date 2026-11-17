'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const TopClusters = require('../app/top-clusters.js');

const cluster = (share, q20_date = '2026-12-01', q80_date = '2026-12-10', extra = {}) => ({
  rank: 'secondary',
  share,
  n: 3,
  n_scale: 10,
  q20_date,
  q80_date,
  tc_mode_date: '2026-12-05',
  representative: { tc: 'forbidden' },
  ...extra,
});

test('normalizes a single cluster as the main cluster', () => {
  const rows = TopClusters.forScale({
    scale_clusters: { '6-12m': [cluster(0.51)] },
  }, '6-12m');

  assert.deepEqual(rows, [{
    rank: 'main',
    share: 0.51,
    n: 3,
    n_scale: 10,
    q20_date: '2026-12-01',
    q80_date: '2026-12-10',
  }]);
  assert.equal(TopClusters.label(rows[0]), '主簇');
  assert.equal(TopClusters.shareText(rows[0]), '占 51%');
});

test('sorts multiple clusters by share and forces the first cluster to main', () => {
  const rows = TopClusters.forScale({
    clusters: { '12-24m': [cluster(0.35), cluster(0.51), cluster(0.14)] },
  }, '12-24m');

  assert.deepEqual(rows.map(row => [row.rank, row.share]), [
    ['main', 0.51],
    ['secondary', 0.35],
    ['secondary', 0.14],
  ]);
  assert.equal(TopClusters.label(rows[1]), '次级簇');
  assert.equal(Object.hasOwn(rows[0], 'tc_mode_date'), false);
  assert.equal(Object.hasOwn(rows[0], 'representative'), false);
});

test('distinguishes missing metadata from an explicit empty cluster list', () => {
  assert.equal(TopClusters.forScale({}, '6-12m'), null);
  assert.equal(TopClusters.forScale({ scale_clusters: {} }, '6-12m'), null);
  assert.deepEqual(TopClusters.forScale({ scale_clusters: { '6-12m': [] } }, '6-12m'), []);
});

test('filters invalid dates and non-finite shares', () => {
  const rows = TopClusters.forScale({
    scale_clusters: {
      '6-12m': [
        cluster(0.4, '2026-02-30'),
        cluster(Infinity),
        cluster(null),
        cluster(0.6, '2026-12-01', '2027-01-01', { unexpected: true }),
      ],
    },
  }, '6-12m');

  assert.equal(rows.length, 1);
  assert.deepEqual(Object.keys(rows[0]).sort(), [
    'n', 'n_scale', 'q20_date', 'q80_date', 'rank', 'share',
  ]);
});

test('classifies main-cluster appearance, disappearance, start and width changes', () => {
  const idx = Object.fromEntries([
    '2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08',
    '2026-01-09', '2026-01-12', '2026-01-13', '2026-01-14',
  ].map((date, i) => [date, i]));
  const indexOf = date => idx[date] ?? -1;
  const frame = (q20, q80) => ({
    clusters: { '6-12m': q20 ? [cluster(1, q20, q80)] : [] },
  });
  const previous = frame('2026-01-06', '2026-01-12');

  assert.equal(TopClusters.classifyChange(frame(null), previous, '6-12m', indexOf), '新出现');
  assert.equal(TopClusters.classifyChange(previous, frame(null), '6-12m', indexOf), '消失');
  assert.equal(TopClusters.classifyChange(previous, frame('2026-01-05', '2026-01-12'), '6-12m', indexOf), '起点前移 1 个交易日');
  assert.equal(TopClusters.classifyChange(previous, frame('2026-01-07', '2026-01-12'), '6-12m', indexOf), '起点后移 1 个交易日');
  assert.equal(TopClusters.classifyChange(previous, frame('2026-01-06', '2026-01-09'), '6-12m', indexOf), '收窄 3 个交易日');
  assert.equal(TopClusters.classifyChange(previous, frame('2026-01-06', '2026-01-14'), '6-12m', indexOf), '变宽 2 个交易日');
  assert.equal(TopClusters.classifyChange(previous, previous, '6-12m', indexOf), '不变');
  assert.equal(TopClusters.classifyChange({}, previous, '6-12m', indexOf), null);
});

test('formats trading-day distance to and since the main-cluster start', () => {
  const idx = { '2026-01-05': 0, '2026-01-06': 1, '2026-01-07': 2, '2026-01-08': 3 };
  const indexOf = date => idx[date] ?? -1;
  assert.equal(TopClusters.startDistanceText('2026-01-08', '2026-01-06', indexOf), '距主簇开始 2 个交易日');
  assert.equal(TopClusters.startDistanceText('2026-01-06', '2026-01-08', indexOf), '主簇已开始 3 个交易日');
});
