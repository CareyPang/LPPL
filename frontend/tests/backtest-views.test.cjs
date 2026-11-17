'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'app/backtest-views.js'), 'utf8');

test('backtest view follows hash changes and preserves initial hash selection', () => {
  assert.match(source, /function showLocationView\(\)[\s\S]*?location\.hash\.match/);
  assert.match(source, /window\.addEventListener\('hashchange', showLocationView\)/);
  assert.match(source, /showLocationView\(\);/);
  assert.match(source, /new URL\(location\.href\)/);
});
