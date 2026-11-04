'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'home.html'), 'utf8');
const start = html.indexOf('const SKY_ON =');
const end = html.indexOf('// fi：滚动位置对应的帧', start);
assert.ok(start >= 0 && end > start, 'Extract the actual horizon and scene mapping');
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
function setup({ search = '', n = 241 } = {}) {
  const context = vm.createContext({
    location: { search }, SRC: { n }, clamp,
    sstep: (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
  });
  vm.runInContext(html.slice(start, end) + '\nglobalThis.scene = { sceneSky, hzAt, HZ_LOOP, SUN_X };', context);
  return context.scene;
}

test('a fully visible surface loop retains its measured horizon and sun anchor', () => {
  const s = setup();
  const sky = s.sceneSky(20, { scene: 'sea', key: 'arbitrary-media-id' }, 1);
  assert.equal(sky.hz, s.HZ_LOOP);
  assert.equal(sky.weight, 1);
  assert.equal(sky.sunX, s.SUN_X);
});

test('underwater loops never restore the surface sky at shallow or deep scroll positions', () => {
  const s = setup();
  for (const scene of ['under', 'deep']) {
    for (const fi of [0, 108, 156, 240]) {
      // Deliberately misleading key: mapping must use the explicit scene, not a filename guess.
      assert.equal(s.sceneSky(fi, { scene, key: 'sea0' }, 1).weight, 0);
    }
  }
});

test('underwater fade-in and reverse fade-out are continuous and do not move the sun', () => {
  const s = setup();
  const base = s.sceneSky(20, null, 0);
  for (const scene of ['under', 'deep']) {
    const weights = [0, .25, .5, .75, 1].map(w => s.sceneSky(20, { scene }, w));
    assert.equal(weights[0].weight, base.weight);
    assert.deepEqual(weights.map(x => x.weight), [1, .75, .5, .25, 0]);
    for (const sky of weights) {
      assert.equal(sky.hz, base.hz);
      assert.equal(sky.sunX, base.sunX);
    }
  }
});

test('the original dive horizon remains aligned across desktop and half-rate mobile frames', () => {
  const desktop = setup(), mobile = setup({ n: 121 });
  for (const p of [0, .1, .3, .42, .5, 1]) {
    assert.equal(desktop.hzAt(p * 240), mobile.hzAt(p * 120));
  }
  assert.equal(desktop.sceneSky(240, null, 1).weight, 0);
});

test('the existing video-sky switch disables all procedural sky states', () => {
  const s = setup({ search: '?sky=video' });
  for (const loop of [null, { scene: 'sea' }, { scene: 'under' }, { scene: 'deep' }]) {
    for (const w of [0, .5, 1]) assert.equal(s.sceneSky(0, loop, w).weight, 0);
  }
});

test('loop image and video paths attach the explicit scene used by the renderer', () => {
  const mediaStart = html.indexOf('function loopImage(L,now)');
  const mediaEnd = html.indexOf('function pauseLoops', mediaStart);
  const context = vm.createContext({ videoMedia: null, RM: false, loadLoops() {}, contiguousReady: L => L.frames.length, START_BUFFER: 2 });
  vm.runInContext(html.slice(mediaStart, mediaEnd) + '\nglobalThis.getLoop = loopImage;', context);
  for (const name of ['sea', 'under', 'deep']) {
    const img = { naturalWidth: 1920, naturalHeight: 1080 };
    const L = { name, n: 2, fps: 24, cursor: 0, clock: null, last: null, frames: [{ ok: true, done: true, img }, { ok: true, done: true, img }] };
    assert.equal(context.getLoop(L, 1000).scene, name);
    assert.equal(context.getLoop(L, 1050).scene, name);
    assert.equal(context.getLoop({ name, vidOk: true, vid: { paused: false, videoWidth: 1920, videoHeight: 1080 } }, 1000).scene, name);
  }
});
