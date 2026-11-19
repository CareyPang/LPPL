const assert = require('node:assert/strict');
const test = require('node:test');
const { archiveView, sourceLink } = require('../app/watchlist-archive.js');

test('receipt time of a job or a later seal cannot be promoted into an at-close record', () => {
  const mk = (asof, sealed_at) => ({ asof, sealed_at, generated_at: asof + 'T13:30:00+08:00' });
  const observations = [
    mk('2026-11-16', '2026-11-16T15:00:00+08:00'),
    mk('2026-11-17', null),
    mk('2026-11-18', '2026-11-18T07:00:01Z')
  ];
  const events = observations.map((_, i) => ({ current: i, previous: i ? i - 1 : null, kind: 'state_changed' }));
  const doc = { observations, events };
  assert.equal(archiveView(doc, '', false).events.length, 3);
  assert.deepEqual(archiveView(doc, '2026-11-18', true).observations, [observations[0]]);
  assert.deepEqual(archiveView(doc, '2026-11-16', true).observations, [observations[0]]);
  assert.equal(archiveView(doc, '2026-11-19', true).events.length, 1);
  assert.equal(archiveView(doc, '2026-02-31', true).observations.length, 0);
});

test('original links must identify a commit from this repository', () => {
  const sha = '3'.repeat(40);
  const url = 'https://github.com/CareyPang/LPPL/blob/' + sha + '/forward_log/test.json';
  assert.equal(sourceLink(url), url);
  for (const other of [url.replace(sha, 'main'), url.replace('/test.json', '/../other'), 'javascript:alert(1)']) {
    assert.equal(sourceLink(other), null);
  }
});
