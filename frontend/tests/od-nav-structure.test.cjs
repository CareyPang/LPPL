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
const backtest = fs.readFileSync(path.join(root, 'backtest.html'), 'utf8');
const backtestViews = fs.readFileSync(path.join(root, 'app/backtest-views.js'), 'utf8');
const stock = fs.readFileSync(path.join(root, 'stock.html'), 'utf8');
const chart = fs.readFileSync(path.join(root, 'chart.html'), 'utf8');
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
  assert.match(main[1], /backtest\.html#view=bench/);
  assert.doesNotMatch(main[1], /chart\.html/);
});

test('market groups preserve every scroll id and keep freshness outside the groups', () => {
  const groups = nav.match(/var MARKET_SUB = \[([\s\S]*?)\n  \];/);
  assert.ok(groups);
  const actual = [...groups[1].matchAll(/ids: \[([^\]]+)\]/g)]
    .map((match) => [...match[1].matchAll(/'([^']+)'/g)].map((id) => id[1]));
  assert.deepEqual(actual, [
    ['s-summary', 's-news', 's-events'],
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
  assert.doesNotMatch(index, /id="p-bench"|data-p="p-bench"|function renderBench/);
  assert.match(index, /location\.hash !== '#p-bench'/);
  assert.match(index, /target\.searchParams\.set\('sym', symbol\)/);
  assert.match(index, /location\.replace\(target\.href\)/);
  assert.match(index, /看三段验证/);
  assert.match(index, /link\.href = 'backtest\.html#view=bench'/);
  assert.match(index, /appendEvidenceHelp\(\$\('vs'\)\)/);
  assert.match(index, /appendEvidenceHelp\(\$\('ph-tip'\)\)/);
  assert.match(backtest, /开发段：.*最早的一段历史，用来设计规则、调参数。/);
  assert.match(backtest, /校准段：.*中间一段，规则定下后只用来确定门槛。/);
  assert.match(backtest, /测试段：.*只有这段的成绩才算“没看过答案”/);
  assert.match(backtestViews, /LPPL\.load\(S\.sym\)/);
  assert.match(stock, /class="evidence-help" href="backtest\.html#view=bench">证据等级是什么？/);
  assert.match(chart, /class="evidence-help" href="backtest\.html#view=bench">证据等级是什么？/);
});

test('sidebar watchlist reads through the existing watch module', () => {
  assert.match(nav, /watch\.list\(\)\.then\(function \(items\)/);
  assert.match(watch, /function list\(\) \{/);
  assert.match(watch, /window\.OdWatch = \{[\s\S]*?list: list \}/);
});

test('index chart links retain only valid as-of dates and chart layout follows its container', () => {
  assert.match(nav, /function validAsof\(value\) \{[\s\S]*?toISOString\(\)\.slice\(0, 10\) === value/);
  assert.match(nav, /validAsof\(new URLSearchParams\(location\.search\)\.get\('asof'\)\)/);
  assert.match(nav, /asof \? '&asof=' \+ encodeURIComponent\(asof\) : ''/);
  assert.match(chart, /\.chart-page \{[^}]*container-type: inline-size/);
  assert.match(chart, /@container \(max-width: 900px\)/);
  assert.match(chart, /@container \(max-width: 600px\)/);
  assert.match(chart, /@media \(max-width: 520px\)/);
});
