const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const BS = require('../app/breadth-state.js');

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/breadth_latest.json'), 'utf8'));
const market = fs.readFileSync(path.join(__dirname, '../market.html'), 'utf8');

test('renders the published state, its meaning and recent days without trade wording', () => {
  const html = BS.render(fixture.state, { mark: 'oversold' });
  const latest = fixture.state.latest;
  assert.match(html, new RegExp(fixture.state.labels[latest.state]));
  assert.ok(html.includes(BS.MEANING[latest.state]));
  assert.ok(html.includes(latest.date));
  assert.equal((html.match(/<tr><td>\d{4}-\d{2}-\d{2}<\/td><td><span class="bs-tag/g) || []).length, 20);
  assert.match(html, /data-bs-mark="oversold" aria-pressed="true"/);
  assert.match(html, /不是买卖信号/);
  assert.doesNotMatch(html.replace(/不是买卖信号/g, ''), /抄底|逃顶|买入|卖出信号|建议/);
});

test('consecutive flagged days collapse into one episode', () => {
  const rows = ['a', 'b', 'c', 'd'].map((date, i) => ({
    date, sh: 100 + i, state: i === 3 ? 'panic' : 'mixed', flags: i < 2 ? ['oversold'] : [],
  }));
  assert.deepEqual(BS.episodes(rows, 'oversold').map((e) => [e.start, e.end, e.days]), [['a', 'b', 2]]);
  assert.deepEqual(BS.episodes(rows, 'panic').map((e) => [e.start, e.days]), [['d', 1]]);
});

test('missing state renders nothing and the page only reads the backend field', () => {
  assert.equal(BS.render(null), '');
  assert.equal(BS.render({ latest: {} }), '');
  assert.match(market, /CPBreadthState\.render\(breadthStateData/);
  assert.match(market, /<script src="app\/breadth-state\.js"><\/script>/);
});
