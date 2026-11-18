'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Reader = require('../app/chart-readonly-data.js');
test('only an explicit adapter static date may pass asof to load', async () => {
  const calls = [];
  const adapter = { REPLAYS: { sh000001: ['2015-06-12'] },
    load: async (...args) => { calls.push(args); return { raw: { symbol: 'sh000001', asof: '2015-06-12', price_history: { dates: ['2015-06-12'], close: [5000] } } }; },
    replay: { result: async () => { throw Error('static archive must not reach Worker'); } } };
  const data = await Reader.historical(adapter, { valid: true, assetType: 'index', code: 'sh000001', asof: '2015-06-12' });
  assert.equal(data.asof, '2015-06-12'); assert.deepEqual(calls, [['sh000001', '2015-06-12']]);
});
test('non-whitelisted dates never invoke task-capable load with asof', async () => {
  let count = 0;
  const adapter = { REPLAYS: { sh000001: ['2015-06-12'] },
    load: async () => { count++; throw Error('must not call'); },
    replay: { result: async () => ({ status: 'missing' }) }, history: async () => ({ frames: [] }) };
  await assert.rejects(() => Reader.historical(adapter, { valid: true, assetType: 'index', code: 'sh000001', asof: '2026-06-26' }), /只读访问未发起计算/);
  assert.equal(count, 0);
});
