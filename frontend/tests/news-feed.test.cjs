'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const NewsFeed = require('../app/news-feed.js');

test('news diff recognizes ids and link plus time without recounting known rows', () => {
  const current = {
    cls: [{ id: 'a', title: 'old' }],
    eastmoney: [{ url: 'https://example.test/old', time: '2026-11-17 09:00', title: 'old' }],
  };
  const incoming = {
    cls: [{ id: 'a', title: 'updated' }, { id: 'b', title: 'new' }],
    eastmoney: [
      { url: 'https://example.test/old', time: '2026-11-17 09:00', title: 'old' },
      { url: 'https://example.test/new', time: '2026-11-17 09:01', title: 'new' },
    ],
  };
  const result = NewsFeed.diff(current, incoming);
  assert.equal(result.count, 2);
  assert.deepEqual(result.added.cls.map((row) => row.id), ['b']);
  assert.deepEqual(result.added.eastmoney.map((row) => row.title), ['new']);
});

test('news merge retains existing rows and replaces matching rows by identity', () => {
  const old = { cls: [{ id: '1', title: 'old' }], eastmoney: [] };
  const updated = { cls: [{ id: '1', title: 'revised' }, { id: '2', title: 'new' }], eastmoney: [] };
  assert.deepEqual(NewsFeed.merge(old, updated), {
    cls: [{ id: '1', title: 'revised' }, { id: '2', title: 'new' }],
    eastmoney: [],
  });
});

test('watchlist matcher recognizes stock names and bounded six-digit codes', () => {
  const watchlist = [{ code: '600519', name: '贵州茅台' }];
  assert.equal(NewsFeed.mentions({ title: '贵州茅台发布公告' }, watchlist), true);
  assert.equal(NewsFeed.mentions({ title: '买入 600519 后关注' }, watchlist), true);
  assert.equal(NewsFeed.mentions({ title: '代码 1600519 的记录' }, watchlist), false);
  assert.equal(NewsFeed.mentions({ title: '代码 6005190 的记录' }, watchlist), false);
  assert.equal(NewsFeed.mentions({ title: '其他股票' }, []), false);
});

test('related news count uses the same cross-source deduplication as the feed', () => {
  const story = { title: '贵州茅台 600519 发布公告', time: '2026-11-17 09:00' };
  const rows = { cls: [story], eastmoney: [{ ...story }] };
  const watchlist = [{ code: '600519', name: '贵州茅台' }];
  const dayOf = value => value.slice(0, 10);

  assert.equal(NewsFeed.mentions(rows.cls[0], watchlist) + NewsFeed.mentions(rows.eastmoney[0], watchlist), 2);
  assert.equal(NewsFeed.dedupe(rows, 'all', watchlist, true).length, 1);
  assert.equal(NewsFeed.relatedCount(rows, '2026-11-17', watchlist, dayOf), 1);
});
