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
