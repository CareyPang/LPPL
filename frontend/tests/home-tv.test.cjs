const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const H = require('../app/home-tv.js');

const root = path.join(__dirname, '..');
const frame = (asof, close, extra = {}) => ({ asof, close, ...extra });

test('weeklySeries keeps dated closes in order and never invents a drawdown', () => {
  const s = H.weeklySeries({ frames: [
    frame('2026-11-26', 3476.88, { dd_52w: -0.168, first_alert_flag: false }),
    frame('2026-06-04', 3900, { first_alert_flag: true, dd_52w: null }),
    frame('bad-date', 1), frame('2026-07-01', null), frame('2026-07-02', 0),
  ] });
  assert.deepEqual(s.map((p) => p.d), ['2026-06-04', '2026-11-26']);
  assert.equal(s[0].a, true);
  assert.equal(s[0].dd, null);
  assert.equal(s[1].dd, -0.168);
  assert.deepEqual(H.weeklySeries(null), []);
});

test('ranges slice the published weeks and label the change honestly', () => {
  const s = Array.from({ length: 300 }, (_, i) => ({ d: `20${String(10 + Math.floor(i / 52)).padStart(2, '0')}-01-01`, c: 100 + i, a: false }));
  assert.equal(H.sliceRange(s, '52').length, 52);
  assert.equal(H.sliceRange(s, '260').length, 260);
  assert.equal(H.sliceRange(s, 'all').length, 300);
  assert.equal(H.normRange('7'), 'all');
  assert.equal(H.rangeLabel(s, '52'), '近 1 年');
  assert.equal(H.rangeLabel(s, 'all'), '2010 年以来');
  assert.equal(H.change([{ c: 100 }, { c: 110 }]).toFixed(4), '0.1000');
  assert.equal(H.change([{ c: 100 }]), null);
});

test('today answer reads only the published has_top flags', () => {
  assert.equal(H.answer(null), null);
  const none = H.answer({ asof: '2026-11-26', indices: [{ sym: 'sh000001', name: '上证指数', has_top: false }, { sym: 'sh000300', name: '沪深300', has_top: false }] });
  assert.equal(none.text, '今天：2 个主要指数都未出现顶部区间');
  assert.equal(none.tone, 'off');
  const some = H.answer({ asof: '2026-11-26', indices: [{ sym: 'sh000001', name: '上证指数', has_top: true }, { sym: 'sh000300', name: '沪深300', has_top: 'yes' }] });
  assert.equal(some.text, '今天：上证指数 出现顶部区间');
  assert.equal(some.count, 1);
  assert.equal(H.longDate('2026-11-26'), '11 月 26 日 周四');
});

test('recent first alerts are one per index, newest first, with whole weeks elapsed', () => {
  const items = [
    { sym: 'sh000001', name: '上证指数', series: [{ d: '2026-06-04', c: 1, a: true }, { d: '2026-11-26', c: 1, a: false }] },
    { sym: 'sh000688', name: '科创50', series: [{ d: '2026-07-10', c: 1, a: true }] },
    { sym: 'sh000016', name: '上证50', series: [{ d: '2026-07-10', c: 1, a: false }] },
  ];
  const list = H.recentAlerts(items, '2026-11-26', 5);
  assert.deepEqual(list.map((x) => [x.sym, x.date, x.weeks]), [['sh000688', '2026-07-10', 19], ['sh000001', '2026-06-04', 25]]);
  assert.equal(H.weeksBetween('2026-11-26', '2026-06-04'), null);
  const dd = H.drawdowns([{ sym: 'a', name: 'A', series: [{ d: '2026-11-26', dd: -0.1 }] }, { sym: 'b', name: 'B', series: [{ d: '2026-11-26', dd: -0.4 }] }, { sym: 'c', name: 'C', series: [] }]);
  assert.deepEqual(dd.map((x) => x.sym), ['b', 'a']);
});

test('chart svg marks every published first alert and keeps a price tag inside the axis', () => {
  const s = Array.from({ length: 120 }, (_, i) => ({ d: new Date(Date.UTC(2020, 0, 6) + i * 7 * 864e5).toISOString().slice(0, 10), c: 3000 + i * 5, a: i % 40 === 5 }));
  const out = H.renderChart(s, 640, 300);
  assert.equal((out.html.match(/class="al"/g) || []).length, 3);
  assert.match(out.html, /class="tag"/);
  assert.ok(out.model.pw < 640 && out.model.pts.every(([x]) => x >= 0 && x <= out.model.pw));
  assert.ok(H.xLabels(s, out.model.pw).length >= 2);
  assert.deepEqual(H.renderChart([s[0]], 640, 300), { html: '', model: null });
  assert.deepEqual(H.niceTicks(1500, 6400, 5), [2000, 3000, 4000, 5000, 6000]);
});

test('index links keep identity and badges fall back without guessing a market', () => {
  const href = new URL(H.chartHref('sh000300'), 'https://local.example/');
  assert.equal(href.pathname, '/chart.html');
  assert.equal(href.searchParams.get('kind'), 'index');
  assert.equal(href.searchParams.get('from'), 'home.html');
  assert.equal(href.searchParams.get('code'), 'sh000300');
  assert.deepEqual(H.badgeFor('sh000001'), { text: '上', color: '#e03c31' });
  assert.equal(H.badgeFor('US_SPX', '标普500').text, '标');
  assert.match(H.badgeFor('US_SPX', '标普500').color, /^hsl\(/);
});

test('home page keeps the shared hooks and stays within the data contract', () => {
  const html = fs.readFileSync(path.join(root, 'home.html'), 'utf8');
  const js = fs.readFileSync(path.join(root, 'app', 'home-tv.js'), 'utf8');
  for (const hook of ['id="rows"', 'id="spark-range"', 'id="pfn"', 'id="hs-i"', 'id="market-tabs"', 'class="pseg', 'id="wl"', 'class="hero-copy"']) {
    assert.ok(html.includes(hook), hook);
  }
  assert.match(html, /<body class="vs-home home-tv">/);
  assert.match(html, /<script src="app\/home-tv\.js"><\/script>\s*<script src="app\/ai-assistant\.js" data-page="home">/);
  assert.doesNotMatch(html, /hero-art|visual-suite|id="cases"/);
  assert.doesNotMatch(html + js, /bubbleScore|bubbleMultiScaleScore|bubbleProgress|tcOffset/);
  assert.doesNotMatch(js, /lab\/mock\/data|\.json['"]/);
  assert.doesNotMatch(html + js, new RegExp('REDAC' + 'TED'));
});
