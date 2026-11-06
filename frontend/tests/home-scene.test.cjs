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
  vm.runInContext(html.slice(start, end) + '\nglobalThis.scene = { sceneSky, sourceSky, hzAt, HZ_LOOP, SUN_X };', context);
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


test('the last visible strip of sky stays opaque rather than revealing the source sun', () => {
  const sky = setup();
  for (const index of [107, 110, 114, 116]) {
    const source = sky.sourceSky({ scene: 'dive', progress: index / 240 });
    assert.ok(source.hz > 0 && source.hz < .13);
    assert.equal(source.weight, 1);
  }
  assert.equal(sky.sourceSky({ scene: 'dive', progress: 1 }).weight, 0);
});

test('decoded dive frames and sea loops retain separate masks during crossfade', () => {
  const uniforms = new Map();
  const gl = { TEXTURE0: 0, TEXTURE1: 1, TEXTURE_2D: 2, TRIANGLES: 3,
    activeTexture() {}, bindTexture() {}, uniform1f() {}, uniform2f() {}, uniform4f() {}, drawArrays() {},
    uniform3f(name, ...values) { uniforms.set(name, values); }
  };
  const held = { scene: 'dive', progress: 110 / 240, src: {}, key: 'held' };
  const context = vm.createContext({ location: { search: '' }, SRC: { n: 241, w: 1920, h: 1080 }, clamp,
    sstep: (a, b, x) => { const t = clamp((x-a)/(b-a),0,1); return t*t*(3-2*t); },
    RM: false, videoMedia: { status: () => 'ready', getDive: () => held }, heldDive: null,
    WATERLINE: .3, SUBMERGED: .42, nearestLoaded: () => -1, frameItem: () => null,
    W: 1280, H: 720, useGL: true, tex: item => item.key, gl, clk: () => 5,
    U: { uSkyA: 'A', uSkyB: 'B' }, quality: { settings: { cloud: 1 } }, TINT: [1,.69,.43,.035],
    stage: { classList: { add() {} } }
  });
  const renderEnd = html.indexOf('/* ================= 水下漂浮颗粒', start);
  vm.runInContext(html.slice(start, renderEnd) + '\nglobalThis.draw = render;', context);
  context.draw(1000, 200, 1, 0, { scene: 'sea', key: 'sea' }, .5);
  assert.ok(uniforms.get('A')[0] < .1, 'The held dive frame owns its horizon, not the requested frame');
  assert.equal(uniforms.get('A')[1], 1);
  assert.equal(uniforms.get('B')[0], .4296);
  assert.equal(uniforms.get('B')[1], 1);
});

test('Canvas fallback paints a moving sky before compositing but leaves underwater footage intact', () => {
  const calls = [];
  const gradient = { addColorStop() {} };
  const ctx = {
    drawImage(source) { calls.push(['image',source]); }, save() {}, restore() {}, beginPath() {}, rect() {}, clip() {},
    createLinearGradient() { calls.push(['sky']); return gradient; },
    createRadialGradient(x,y) { calls.push(['cloud',x,y]); return gradient; },
    fillRect() {}, translate() {}, scale() {}, arc() {}, fill() {}
  };
  const context = vm.createContext({ location: { search: '' }, SRC: { n: 241 }, clamp,
    sstep: () => 1, RM: false, clk: value => value / 1000, W: 1280, H: 720,
    document: { createElement: () => ({ width:0, height:0, getContext: () => ctx }) }
  });
  vm.runInContext(html.slice(start,end) + '\nglobalThis.paint = paintFallbackSource;', context);
  const original = {};
  context.paint({src:original},{hz:.43,weight:1,sunX:.771},1000,0,0,1280,720);
  const firstCloud = calls.filter(x=>x[0]==='cloud')[1];
  assert.equal(calls[0][1], original);
  assert.equal(calls.filter(x=>x[0]==='sky').length,1);
  calls.length=0;
  context.paint({src:original},{hz:.43,weight:1,sunX:.771},6000,0,0,1280,720);
  assert.notEqual(calls.filter(x=>x[0]==='cloud')[1][1],firstCloud[1]);
  calls.length=0;
  context.paint({src:original},{hz:0,weight:0,sunX:.771},6000,0,0,1280,720);
  assert.deepEqual(calls,[['image',original]]);
});
