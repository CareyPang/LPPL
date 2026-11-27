'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const nav = fs.readFileSync(path.join(root, 'app/od-nav.js'), 'utf8');
const market = fs.readFileSync(path.join(root, 'market.html'), 'utf8');
const nt = fs.readFileSync(path.join(root, 'nt.html'), 'utf8');
const home = fs.readFileSync(path.join(root, 'home.html'), 'utf8');
const index = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const backtest = fs.readFileSync(path.join(root, 'backtest.html'), 'utf8');
const backtestViews = fs.readFileSync(path.join(root, 'app/backtest-views.js'), 'utf8');
const stock = fs.readFileSync(path.join(root, 'stock.html'), 'utf8');
const chart = fs.readFileSync(path.join(root, 'chart.html'), 'utf8');
const watch = fs.readFileSync(path.join(root, 'app/od-watch.js'), 'utf8');
const workspace = fs.readFileSync(path.join(root, 'research-workspace.html'), 'utf8');

test('main navigation has the five user-task entries and their intended sections', () => {
  const main = nav.match(/var MAIN = \[([\s\S]*?)\n  \];/);
  assert.ok(main);
  assert.deepEqual(
    [...main[1].matchAll(/\{ k: '([^']+)', t: '([^']+)'/g)].map((match) => [match[1], match[2]]),
    [
      ['home', '首页'],
      ['stock', '标的'],
      ['market', '市场'],
      ['backtest', '方法与证据'],
      ['tools', '工具'],
    ],
  );
  assert.match(main[1], /sections: \['stock', 'terminal', 'chart'\]/);
  assert.match(main[1], /sections: \['market', 'nt'\]/);
  assert.match(main[1], /index\.html\?code=sh000001/);
  assert.doesNotMatch(main[1], /view=scenario|FCO 历史回测/);
  assert.match(main[1], /backtest\.html#view=strategy/);
  assert.match(main[1], /backtest\.html#view=bench/);
  assert.doesNotMatch(main[1], /chart\.html/);
});

test('market groups use ordered anchors and cover every section except freshness', () => {
  const groups = nav.match(/var MARKET_SUB = \[([\s\S]*?)\n  \];/);
  assert.ok(groups);
  const actual = [...groups[1].matchAll(/\{ t: '([^']+)', h: '([^']+)', ids: \[([^\]]+)\] \}/g)]
    .map((match) => ({
      t: match[1],
      h: match[2],
      ids: [...match[3].matchAll(/'([^']+)'/g)].map((id) => id[1]),
    }));
  assert.deepEqual(actual, [
    { t: '今日', h: '#s-summary', ids: ['s-summary', 's-news', 's-events'] },
    { t: '资金', h: '#s-breadth', ids: ['s-breadth', 's-board', 's-nb', 's-mg', 's-lhb', 's-lhb-seats'] },
    { t: '情绪', h: '#s-limit', ids: ['s-limit', 's-sentiment', 's-ladder', 's-strength', 's-themes', 's-hot'] },
    { t: '风险', h: '#s-top-risk', ids: ['s-top-risk', 's-bottom', 's-abnormal', 's-range'] },
    { t: '宏观', h: '#s-val', ids: ['s-val', 's-macro', 's-growth'] },
  ]);
  const etfLink = groups[1].match(/\{ t: '宽基ETF'[^}]*\}/);
  assert.ok(etfLink);
  assert.match(etfLink[0], /h: 'nt\.html'/);
  assert.match(etfLink[0], /page: 'nt'/);
  assert.match(etfLink[0], /nested: true/);
  assert.doesNotMatch(etfLink[0], /ids:/);
  assert.ok(groups[1].indexOf("t: '资金'") < groups[1].indexOf("t: '宽基ETF'"));
  assert.ok(groups[1].indexOf("t: '宽基ETF'") < groups[1].indexOf("t: '情绪'"));
  assert.match(nav, /market: MARKET_SUB,/);
  assert.match(
    nav,
    /nt: MARKET_SUB\.map\(function \(x\) \{[\s\S]*?return x\.page === 'nt'[\s\S]*?h: 'nt\.html', page: 'nt'[\s\S]*?h: 'market\.html' \+ x\.h/,
  );
  assert.match(nt, /app\/od-nav\.js" data-section="nt"/);
  assert.match(nav, /addSideLink\(sub, def, m\.k, !!item\.nested\)/);
  assert.doesNotMatch(nav, /addSideLink\(sub, \{ t: '宽基ETF'/);
  const main = market.match(/<main\b[^>]*>([\s\S]*?)<\/main>/);
  assert.ok(main);
  const sectionIds = [...main[1].matchAll(
    /<section\b(?=[^>]*\bclass="[^"]*\bsec\b[^"]*")(?=[^>]*\bid="([^"]+)")[^>]*>/g,
  )].map((match) => match[1]);
  const groupIds = actual.flatMap((group) => group.ids);
  assert.equal(new Set(groupIds).size, groupIds.length, 'group ids must be unique');
  assert.deepEqual(groupIds.filter((id) => !sectionIds.includes(id)), []);
  const groupCounts = new Map();
  groupIds.forEach((id) => groupCounts.set(id, (groupCounts.get(id) || 0) + 1));
  actual.forEach((group) => {
    const positions = group.ids.map((id) => sectionIds.indexOf(id));
    assert.ok(
      positions.every((position, i) => i === 0 || positions[i - 1] < position),
      `${group.t} sections must follow their tab order`,
    );
  });
  sectionIds.forEach((id) => {
    assert.equal(groupCounts.get(id) || 0, id === 's-fresh' ? 0 : 1, id);
  });
  assert.deepEqual(sectionIds.filter((id) => !groupCounts.has(id)), ['s-fresh']);
  assert.doesNotMatch(groups[1], /s-fresh|tools\.html/);
  assert.match(nav, /\{ t: '数据状态', h: 'market\.html#s-fresh' \}/);
});

test('home navigation anchors and assistant context remain on the published page', () => {
  assert.match(home, /id="index-overview"[^>]*data-ai-context="指数风险概览"/);
  assert.match(home, /id="today" data-ai-context="今日摘要"/);
  assert.match(home, /<section id="mine"/);
  assert.match(home, /class="btn pri" href="chart\.html\?kind=index&from=home\.html&code=sh000001">上证指数图表/);
  assert.match(home, /class="btn sec" href="backtest\.html#view=bench">回测结果/);
  assert.match(nav, /var SIDE_REPLAYS = \[/);
  assert.match(nav, /sideFooter\.appendChild\(replayList\)/);
  assert.doesNotMatch(index, /id="p-bench"|data-p="p-bench"|function renderBench/);
  assert.match(index, /location\.hash !== '#p-bench'/);
  assert.match(index, /target\.searchParams\.set\('sym', symbol\)/);
  assert.match(index, /location\.replace\(target\.href\)/);
  assert.match(index, /方法与证据 ›/);
  assert.match(index, /link\.href = 'backtest\.html#view=bench'/);
  assert.match(index, /appendEvidenceHelp\(\$\('vs'\)\)/);
  assert.match(index, /appendEvidenceHelp\(\$\('ph-tip'\)\)/);
  assert.doesNotMatch(backtest, /class="bench-explainer"/);
  assert.match(backtest, /location\.replace\(target\.href\)/);
  assert.match(backtestViews, /LPPL\.load\(S\.sym\)/);
  assert.match(stock, /class="evidence-help" href="backtest\.html#view=bench">证据等级是什么？/);
  assert.match(chart, /class="evidence-help" href="backtest\.html#view=bench">证据等级是什么？/);
});

test('sidebar watchlist reads through the existing watch module', () => {
  assert.match(nav, /watch\.list\(\)\.then\(function \(items\)/);
  assert.match(watch, /function list\(\) \{/);
  assert.match(watch, /window\.OdWatch = \{[\s\S]*?list: list \}/);
});

test('research workspace uses the shared home navigation and its route is current', () => {
  assert.match(nav, /\{ t: '我的研究', h: 'research-workspace\.html', page: 'research-workspace\.html' \}/);
  assert.match(nav, /if \(def\.page === section \|\| def\.page === file\)/);
  assert.match(nav, /item\.page === section \|\| item\.page === file/);
  assert.match(nav, /selected = sidebarLinks\.filter\(function \(item\) \{ return item\.page === file; \}\)\[0\];\s*var activeMain = selected \? null : MAIN\.filter\(isMain\)\[0\];/);
  assert.match(nav, /mobileToggle\.hidden = true;/);
  assert.match(nav, /document\.querySelector\('script\[src\*="ai-assistant\.js"\]'\)/);
  assert.match(nav, /document\.readyState === 'loading'[\s\S]*?DOMContentLoaded', syncMobileToggle, \{ once: true \}/);
  assert.match(nav, /else mobileToggle\.remove\(\);/);
  assert.match(workspace, /<body class="research-workspace-page">/);
  assert.match(workspace, /<script src="app\/od-nav\.js" data-section="home" data-theme="light"><\/script>/);
  assert.match(workspace, /<script src="app\/rule-labels\.js"><\/script>\s*<script src="app\/research-workspace-core\.js"><\/script>/);
  assert.match(workspace, /<title>我的研究 · 临界点<\/title>/);
  assert.doesNotMatch(workspace, /class="site-header"/);
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
