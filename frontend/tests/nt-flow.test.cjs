const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const F = require('../app/nt-flow.js');

const rows = [
  { d: '2025-12-30', flow: 5 }, { d: '2026-01-05', flow: 10 }, { d: '2026-01-06', flow: null }, { d: '2026-01-07', flow: -30 },
];

test('cumulative restarts at the range start and skips days without an estimate', () => {
  assert.equal(F.rangeStart(rows, 'ytd'), '2026-01-01');
  assert.equal(F.rangeStart(rows, 'all'), null);
  const out = F.cumulative(rows, '2026-01-01');
  assert.deepEqual(out.map(r => r.cum), [10, 10, -20]);
  assert.equal(out[1].flow, null);
  assert.deepEqual(F.cumulative(rows, null).map(r => r.cum), [5, 15, 15, -15]);
});

test('shade is red for inflow, green for outflow, and deeper for larger amounts within a column', () => {
  const alpha = s => Number(s.match(/,([\d.]+)\)$/)[1]);
  assert.match(F.shade(50, 100), /214,48,58/);
  assert.match(F.shade(-50, 100), /17,132,90/);
  assert.ok(alpha(F.shade(100, 100)) > alpha(F.shade(50, 100)));
  assert.ok(alpha(F.shade(-100, 100)) > alpha(F.shade(-10, 100)));
  assert.equal(F.shade(null, 100), '');
  assert.equal(F.shade(0, 100), '');
});

test('heat table lists newest day first, total column first, and keeps missing days as a dash', () => {
  const html = F.heat(rows, [
    { name: '小', rows: [{ d: '2026-01-05', flow: 1 }, { d: '2026-01-07', flow: -2 }] },
    { name: '大', rows: [{ d: '2026-01-05', flow: 9 }, { d: '2026-01-07', flow: null }] },
  ], 21);
  assert.ok(html.indexOf('2026-01-07') < html.indexOf('2026-01-05'));
  assert.ok(html.indexOf('合计') < html.indexOf('大') && html.indexOf('大') < html.indexOf('小'));
  assert.doesNotMatch(html, /2026-01-06/);
  assert.match(html, /—/);
  assert.match(html, /\+10\.0/);
  assert.match(html, /-30\.0/);
  assert.equal(F.signed(-0.0004, 1), '0.0');
});

test('nt.html loads the module and states the colour convention', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'nt.html'), 'utf8');
  assert.match(page, /<script src="app\/nt-flow\.js"><\/script>/);
  assert.match(page, /红柱 = 净申购，绿柱 = 净赎回/);
  assert.match(page, /\['成交额','latest\.amount_yi'\],\['成交占比','latest\.amount_share'\]/);
  assert.doesNotMatch(page.match(/id="netflow"[\s\S]*?<\/section>/)[0], /信号|买入|卖出|进场/);
});
