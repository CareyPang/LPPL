'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../app/lppl-data.js'), 'utf8');
function response(status, data) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => data,
  };
}
function loadAdapter(fetch) {
  const context = {
    window: {},
    fetch,
    AbortController,
    setTimeout,
    clearTimeout,
    console,
    URL,
    URLSearchParams,
    Intl,
    Date,
  };
  vm.runInNewContext(source, context);
  return context.window.LPPL;
}

test('fetch results expose unpublished, unavailable, empty, and applicable states', async () => {
  const replies = [response(404, {}), response(503, {}), response(200, []), response(200, { rows: [1] })];
  const LPPL = loadAdapter(async () => replies.shift());

  assert.equal((await LPPL.fetchResult('missing.json')).reason, 'unpublished');
  assert.equal((await LPPL.fetchResult('offline.json')).reason, 'unavailable');
  const empty = await LPPL.fetchResult('empty.json');
  assert.equal(empty.reason, 'empty');
  assert.equal(Array.isArray(empty.data), true);
  assert.equal((await LPPL.fetchResult('data.json')).reason, null);
  assert.equal((await LPPL.fetchResult('not-applicable.json', { applicable: false })).reason, 'not_applicable');
});

test('resultOf supports endpoint-specific empty rules without changing fetched data', async () => {
  const LPPL = loadAdapter(async () => response(200, { rows: [] }));
  const result = await LPPL.resultOf(Promise.resolve({ rows: [] }), {
    empty: value => value.rows.length === 0,
  });
  assert.equal(result.reason, 'empty');
  assert.equal(result.data.rows.length, 0);
});

test('stock.kline requests one validated symbol and supported period from the Worker', async () => {
  const calls = [];
  const LPPL = loadAdapter(async (url) => {
    calls.push(String(url));
    return response(200, { schema: 'kline_obv.v1', code: '600519', period: '30' });
  });
  const result = await LPPL.stock.kline('600519', '30');
  assert.equal(result.code, '600519');
  assert.match(calls[0], /\/kline\?code=600519&period=30$/);
  assert.throws(() => LPPL.stock.kline('600519', '5'), /周期无效/);
});
