const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const nav = fs.readFileSync(path.join(__dirname, '..', 'app', 'od-nav.js'), 'utf8');
const stockPage = fs.readFileSync(path.join(__dirname, '..', 'app', 'stock-page.js'), 'utf8');

test('index chart link resolves named indices and captures the current return query on click', () => {
  assert.match(nav, /item\.sym === currentCode \|\| item\.code === currentCode \|\| item\.name === currentCode/);
  assert.match(nav, /function updateChartHref\(\) \{[\s\S]*?var source = location\.pathname\.split\('\/'\)\.pop\(\) \+ location\.search;[\s\S]*?encodeURIComponent\(source\)/);
  assert.match(nav, /chartLink\.addEventListener\('click', updateChartHref\)/);
});

test('stock directory opens assets through a navigable URL', () => {
  assert.match(stockPage, /onOpen:\s*\(row\)\s*=>\s*\{\s*location\.href\s*=\s*'stock\.html\?code='\s*\+\s*encodeURIComponent\(row\.code\);\s*\}/);
});
