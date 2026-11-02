const test = require('node:test');
const assert = require('node:assert/strict');
const { create } = require('../app/home-quality.js');

test('brief decode stalls and returning from a suspended tab do not soften the canvas', () => {
  const q = create();
  for (let i = 0; i < 15; i++) q.sample(50);
  q.sample(5000);
  for (let i = 0; i < 120; i++) q.sample(16.67);
  assert.equal(q.level, 0);
  assert.equal(q.settings.scale, 1);
});

test('effects and frame rate are reduced before the ocean resolution', () => {
  const q = create();
  for (let i = 0; i < 50; i++) q.sample(50);
  assert.equal(q.level, 1);
  assert.equal(q.settings.scale, 1);
  assert.equal(q.settings.particleStride, 2);
  for (let i = 0; i < 50; i++) q.sample(50);
  assert.equal(q.level, 2);
  assert.equal(q.settings.fps, 30);
  assert.equal(q.settings.scale, 1);
  for (let i = 0; i < 36; i++) q.sample(70);
  assert.equal(q.level, 3);
  assert.equal(q.settings.scale, .8);
  // The old implementation repeatedly resized the same 80% canvas here.
  for (let i = 0; i < 200; i++) assert.equal(q.sample(70), false);
});

test('sustained recovery restores full resolution and then effects one step at a time', () => {
  const q = create();
  for (let i = 0; i < 150; i++) q.sample(70);
  assert.equal(q.level, 3);
  for (let i = 0; i < 365; i++) q.sample(33.34);
  assert.equal(q.level, 2);
  assert.equal(q.settings.scale, 1);
  for (let i = 0; i < 365; i++) q.sample(33.34);
  assert.equal(q.level, 1);
  for (let i = 0; i < 725; i++) q.sample(16.67);
  assert.equal(q.level, 0);
});

test('normal 30fps mobile playback does not trigger a quality downgrade', () => {
  const q = create({ mobile: true });
  for (let i = 0; i < 1000; i++) q.sample(33.34);
  assert.equal(q.level, 0);
  assert.equal(q.settings.fps, 30);
});

test('sustained very slow rendering still triggers adaptation', () => {
  const q = create({ mobile: true });
  for (let i = 0; i < 40; i++) q.sample(300);
  assert.equal(q.level, 3);
  assert.equal(q.settings.scale, .8);
  q.reset();
  q.sample(5000);
  assert.equal(q.level, 3);
});
