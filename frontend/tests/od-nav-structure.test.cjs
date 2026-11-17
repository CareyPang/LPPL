'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const nav = fs.readFileSync(path.join(root, 'app/od-nav.js'), 'utf8');
const market = fs.readFileSync(path.join(root, 'market.html'), 'utf8');
const home = fs.readFileSync(path.join(root, 'home.html'), 'utf8');
const index = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const watch = fs.readFileSync(path.join(root, 'app/od-watch.js'), 'utf8');

test('main navigation has the five user-task entries and their intended sections', () => {
  const main = nav.match(/var MAIN = \[([\s\S]*?)\n  \];/);
  assert.ok(main);
  assert.deepEqual(
    [...main[1].matchAll(/\{ k: '([^']+)', t: '([^']+)'/g)].map((match) => [match[1], match[2]]),
    [
      ['home', '首页'],
      ['stock', '标的'],
      ['market', '市场'],
      ['backtest', '历史检验'],
      ['tools', '工具'],
    ],
  );
  assert.match(main[1], /sections: \['stock', 'terminal', 'chart'\]/);
  assert.match(main[1], /sections: \['market', 'nt'\]/);
  assert.match(main[1], /index\.html\?code=sh000001/);
  assert.match(main[1], /backtest\.html#view=scenario/);
  assert.match(main[1], /backtest\.html#view=strategy/);
  assert.match(main[1], /index\.html#p-bench/);
  assert.doesNotMatch(main[1], /chart\.html/);
});

test('market groups preserve every scroll id and keep freshness outside the groups', () => {
  const groups = nav.match(/var MARKET_SUB = \[([\s\S]*?)\n  \];/);
  assert.ok(groups);
  const actual = [...groups[1].matchAll(/ids: \[([^\]]+)\]/g)]
    .map((match) => [...match[1].matchAll(/'([^']+)'/g)].map((id) => id[1]));
  assert.deepEqual(actual, [
    ['s-news', 's-events'],
    ['s-board', 's-nb', 's-mg'],
    ['s-limit', 's-sentiment', 's-ladder', 's-strength', 's-themes', 's-hot', 's-lhb', 's-bottom', 's-abnormal', 's-range'],
    ['s-val', 's-macro', 's-growth'],
  ]);
  const pageIds = new Set([...market.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));
  const required = [...new Set(actual.flat())];
  assert.deepEqual(required.filter((id) => !pageIds.has(id)), []);
  assert.doesNotMatch(groups[1], /s-fresh|tools\.html|nt\.html/);
  assert.match(nav, /\{ t: '数据状态', h: 'market\.html#s-fresh' \}/);
  assert.match(nav, /addSideLink\(sub, \{ t: '国家队ETF', h: 'nt\.html', page: 'nt' \}/);
});

test('home navigation anchors and assistant context remain on the published page', () => {
  assert.match(home, /id="index-overview"[^>]*data-ai-context="指数风险概览"/);
  assert.match(home, /id="today" data-ai-context="今日摘要"/);
  assert.match(home, /<section id="mine"/);
  assert.match(home, /class="btn pri" href="stock\.html">查看标的/);
  assert.match(home, /class="btn sec" href="backtest\.html">历史检验/);
  assert.match(index, /function syncBenchHash\(\) \{\s*if \(location\.hash === '#p-bench'\) selectBottom\(1\);/);
});

test('sidebar watchlist reads through the existing watch module', () => {
  assert.match(nav, /watch\.list\(\)\.then\(function \(items\)/);
  assert.match(watch, /function list\(\) \{/);
  assert.match(watch, /window\.OdWatch = \{[\s\S]*?list: list \}/);
});
