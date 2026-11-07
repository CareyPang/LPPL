const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const page = fs.readFileSync(path.join(__dirname, '..', 'market.html'), 'utf8');

test('market page exposes the opening-style research entry points without promising live data', () => {
  assert.match(page, /id="s-toolkit"/);
  assert.match(page, /今日盘面/);
  assert.match(page, /历史复盘/);
  assert.match(page, /题材库/);
  assert.match(page, /全球宏观/);
  assert.match(page, /日终快照 · 不等同实时行情/);
});

test('market page renders a descriptive review switch and ladder from the saved snapshot', () => {
  assert.match(page, /id="s-review"/);
  assert.match(page, /data-review="overview"/);
  assert.match(page, /data-review="direction"/);
  assert.match(page, /data-review="reason"/);
  assert.match(page, /id="s-ladder"/);
  assert.match(page, /function renderLadder\(\)/);
  assert.match(page, /function renderReview\(\)/);
  assert.match(page, /LPPL\.market\(\)/);
});

test('unsupported screenshot modules remain explicit evidence boundaries', () => {
  assert.match(page, /涨停原因/);
  assert.match(page, /当前快照没有题材标签和原因字段/);
  assert.match(page, /不称为官方 FedWatch/);
  assert.match(page, /直播属于盘中数据产品/);
});
