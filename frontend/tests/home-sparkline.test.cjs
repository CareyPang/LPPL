'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { toPct, sharedDomain } = require('../app/home-sparkline.js');

test('toPct normalizes closes to the first close and handles empty and single-point series', () => {
  const values = toPct([100, 102.5, 95]);
  assert.equal(values[0], 0);
  assert.ok(Math.abs(values[1] - 0.025) < 1e-12);
  assert.ok(Math.abs(values[2] + 0.05) < 1e-12);
  assert.deepEqual(toPct([]), []);
  assert.deepEqual(toPct([123]), [0]);
});

test('sharedDomain includes zero and pads the combined range by five percent', () => {
  const domain = sharedDomain([[0, 0.1], [-0.2]]);
  assert.ok(Math.abs(domain.min + 0.215) < 1e-12);
  assert.ok(Math.abs(domain.max - 0.115) < 1e-12);
  assert.ok(domain.min < 0 && domain.max > 0);
});

test('sharedDomain remains finite and spans zero for single-point and empty series', () => {
  for (const domain of [sharedDomain([toPct([100])]), sharedDomain([]), sharedDomain([[]])]) {
    assert.ok(Number.isFinite(domain.min));
    assert.ok(Number.isFinite(domain.max));
    assert.ok(domain.min < 0 && domain.max > 0);
  }
});
