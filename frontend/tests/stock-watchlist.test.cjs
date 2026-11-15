'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Watchlist = require('../app/stock-watchlist.js');

class MemoryStorage {
  constructor(value = null) { this.value = value; }
  getItem(key) { return key === Watchlist.KEY ? this.value : null; }
  setItem(key, value) {
    if (key !== Watchlist.KEY) throw Error('unexpected key');
    this.value = value;
  }
}

test('watchlist validates six-digit A-share codes and drops other stored values', () => {
  const storage = new MemoryStorage(JSON.stringify([
    '600519', 'US_NVDA', '12345', '600519', ' 301196', 301196, null,
  ]));
  assert.equal(Watchlist.isValid('600519'), true);
  assert.equal(Watchlist.isValid('US_NVDA'), false);
  assert.deepEqual(Watchlist.read(storage), ['600519', '301196']);
});

test('watchlist reads corrupt or non-array storage as empty', () => {
  assert.deepEqual(Watchlist.read(new MemoryStorage('{')), []);
  assert.deepEqual(Watchlist.read(new MemoryStorage('{"code":"600519"}')), []);
});

test('watchlist writes unique valid codes in order and caps the list at 50', () => {
  const storage = new MemoryStorage();
  const codes = Array.from({ length: 55 }, (_, index) => String(index).padStart(6, '0'));
  const written = Watchlist.write(storage, ['600519', ...codes, '600519', 'US_NVDA']);
  assert.equal(written.length, Watchlist.MAX);
  assert.equal(written[0], '600519');
  assert.equal(new Set(written).size, Watchlist.MAX);
  assert.deepEqual(JSON.parse(storage.value), written);
  assert.deepEqual(Watchlist.write(storage, ['600519', '600519', '12345']), ['600519']);
});

test('watchlist reads are safe when browser storage is unavailable', () => {
  assert.deepEqual(Watchlist.read(null), []);
  assert.equal(Watchlist.write(null, ['600519']), null);
});
