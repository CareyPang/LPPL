const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const nav = fs.readFileSync(path.join(__dirname, '..', 'app', 'od-nav.js'), 'utf8');
const stockPage = fs.readFileSync(path.join(__dirname, '..', 'app', 'stock-page.js'), 'utf8');

test('index chart link resolves the current URL code and falls back to the index default', () => {
  assert.match(nav, /function appendIndexChartLink\(\) \{[\s\S]*?var chartLink = el\('a', 'odn-chart-link'/);
  assert.match(nav, /function currentIndexSymbol\(\) \{[\s\S]*?new URLSearchParams\(location\.search\)\.get\('code'\)/);
  assert.match(nav, /return indexItem && indexItem\.sym \|\| 'sh000001'/);
  assert.match(nav, /function updateChartHref\(\) \{[\s\S]*?var source = location\.pathname\.split\('\/'\)\.pop\(\) \+ location\.search;[\s\S]*?encodeURIComponent\(currentIndexSymbol\(\)\)[\s\S]*?encodeURIComponent\(source\)/);
  assert.match(nav, /\['click', 'focus', 'pointerenter'\]\.forEach\(function \(name\) \{[\s\S]*?chartLink\.addEventListener\(name, updateChartHref\)/);
});

test('stock directory opens assets through a navigable URL', () => {
  assert.match(stockPage, /onOpen:\s*\(row\)\s*=>\s*\{\s*location\.href\s*=\s*'stock\.html\?code='\s*\+\s*encodeURIComponent\(row\.code\);\s*\}/);
});
