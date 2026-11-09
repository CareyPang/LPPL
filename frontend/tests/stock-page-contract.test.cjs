'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'stock.html'), 'utf8');
const siteBuilder = fs.readFileSync(path.join(__dirname, '..', 'demo-tools', 'prepare_real_site.py'), 'utf8');

test('workstation copy and controls stay focused on the asset workflow', () => {
  assert.doesNotMatch(html, /看清行情[，,]?\s*<em>再研究时间/);
  assert.doesNotMatch(html, /id="workspace-motion"/);
  assert.match(html, /href="market\.html">市场背景/);
});

test('workstation exposes a switchable top, bottom and market analysis surface', () => {
  for (const view of ['top', 'bottom', 'market']) {
    assert.match(html, new RegExp(`data-analysis-view="${view}"`));
  }
  assert.match(html, /id="bottom-dashboard"/);
  assert.match(html, /data-market-context-card/);
});

test('the independent preview packages the linked descriptive market page and snapshot', () => {
  assert.match(siteBuilder, /"market\.html"/);
  assert.match(siteBuilder, /web\/mock\/data\/market\/market_latest\.json/);
  assert.match(siteBuilder, /lab\/mock\/data\/market/);
});
