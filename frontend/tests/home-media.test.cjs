'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'home.html'), 'utf8');
const start = html.indexOf('/* ================= 帧序列 ================= */');
const end = html.indexOf('/* ================= 数据（', start);
assert.ok(start >= 0 && end > start, 'The media section must be extractable from the real page');
const source = html.slice(start, end);

function setup({ reduced = false, mobile = false } = {}) {
  const requests = [], nodes = new Map();
  let kicks = 0;
  class FakeImage {
    constructor() { this.naturalWidth = 1920; this.naturalHeight = 1080; }
    set src(value) { this.url = value; requests.push(this); }
    decode() { return Promise.resolve(); }
  }
  const context = vm.createContext({
    RM: reduced, MOB: mobile, Image: FakeImage,
    clamp: (x, a, b) => Math.min(b, Math.max(a, x)),
    kick: () => { kicks++; },
    $: selector => {
      if (!nodes.has(selector)) nodes.set(selector, { style: {}, textContent: '' });
      return nodes.get(selector);
    },
    setTimeout: () => 1, clearTimeout: () => {},
  });
  vm.runInContext(source + '\nglobalThis.media = { loadAll, prioritizeFrames, loopFor, loopImage, pauseLoops, frames, LOOPS, STAGE_FRAMES, START_BUFFER, SRC };', context);
  async function complete(request, ok = true) {
    assert.ok(request && !request.finished, 'A requested image must be pending');
    request.finished = true;
    if (ok) request.onload(); else request.onerror();
    await Promise.resolve();
    await Promise.resolve();
  }
  async function initialSea(count, failedIndex = -1) {
    for (let index = 0; index < count; index++) {
      const suffix = `/sea/${mobile ? 'm' : 'd'}/${String(index + 1).padStart(3, '0')}.webp`;
      let request = requests.find(r => !r.finished && r.url.endsWith(suffix));
      assert.ok(request, `Frame ${index} should have been queued sequentially`);
      if (index === failedIndex) {
        await complete(request, false);
        request = requests.find(r => !r.finished && r.url.endsWith(suffix));
        await complete(request, false);
      } else await complete(request);
    }
  }
  async function drain() {
    for (let guard = 0; guard < 400; guard++) {
      const request = requests.find(r => !r.finished);
      if (!request) return;
      await complete(request);
    }
    assert.fail('The startup queue should be finite');
  }
  return { ...context.media, requests, complete, initialSea, drain, nodes, kicks: () => kicks };
}

test('startup favors contiguous sea frames and uses a bounded shared queue', async () => {
  const m = setup();
  m.prioritizeFrames(0);
  assert.equal(m.requests.length, 0, 'Scroll initialization must not start media early');
  m.loadAll();
  assert.deepEqual(m.requests.map(r => r.url), [
    'assets/dive/h/001.webp',
    'assets/dive/loop/sea/d/001.webp',
    'assets/dive/loop/sea/d/002.webp',
    'assets/dive/loop/sea/d/003.webp',
  ]);
  assert.ok(m.requests.every(r => !/under|deep/.test(r.url)));
  await m.drain();
  assert.ok(m.requests.length < 70, 'Startup must not request all dive or sea frames');
  assert.ok(m.requests.every(r => !/under|deep/.test(r.url)));
});

test('a decoded contiguous buffer starts before the entire loop, on its own clock', async () => {
  const m = setup(); m.loadAll();
  await m.initialSea(m.START_BUFFER - 1);
  assert.equal(m.loopImage(m.LOOPS[0], 98765), null, 'A hole in the startup buffer must not count as ready');
  const last = m.requests.find(r => !r.finished && r.url.endsWith('/sea/d/018.webp'));
  await m.complete(last);
  assert.equal(m.LOOPS[0].ok, m.START_BUFFER);
  assert.ok(m.LOOPS[0].ok < m.LOOPS[0].n);
  assert.equal(m.loopImage(m.LOOPS[0], 98765).key, 'sea0', 'The global page clock must not select an unloaded frame');
  assert.equal(m.loopImage(m.LOOPS[0], 98799).key, 'sea1');
  m.pauseLoops(null);
  assert.equal(m.loopImage(m.LOOPS[0], 150000).key, 'sea1', 'Resuming must not jump through time spent paused');
});

test('one permanently failed sea image retries once and cannot block playback', async () => {
  const m = setup(); m.loadAll();
  await m.initialSea(m.START_BUFFER, 2);
  assert.equal(m.requests.filter(r => r.url.endsWith('/sea/d/003.webp')).length, 2);
  assert.equal(m.loopImage(m.LOOPS[0], 1000).key, 'sea0');
  assert.equal(m.loopImage(m.LOOPS[0], 1034).key, 'sea1');
  assert.equal(m.loopImage(m.LOOPS[0], 1068).key, 'sea1', 'A failed frame retains the last good image');
  assert.equal(m.loopImage(m.LOOPS[0], 1102).key, 'sea3');
  assert.ok(m.kicks() >= m.START_BUFFER, 'Both success and terminal failure must request repaint');
});

test('out-of-order decoded images cannot substitute for a contiguous startup buffer', async () => {
  const m = setup(); m.loadAll();
  for (let index = 1; index <= m.START_BUFFER; index++) {
    const suffix = `/sea/d/${String(index + 1).padStart(3, '0')}.webp`;
    await m.complete(m.requests.find(r => !r.finished && r.url.endsWith(suffix)));
  }
  assert.equal(m.LOOPS[0].ok, m.START_BUFFER);
  assert.equal(m.loopImage(m.LOOPS[0], 9000), null, 'The unresolved first image keeps the buffer discontinuous');
  await m.complete(m.requests.find(r => !r.finished && r.url.endsWith('/sea/d/001.webp')));
  assert.equal(m.loopImage(m.LOOPS[0], 9034).key, 'sea0');
});

test('temporary buffer starvation holds the last frame without accumulating catch-up jumps', async () => {
  const m = setup(); m.loadAll(); await m.initialSea(m.START_BUFFER);
  let now = 1000;
  m.loopImage(m.LOOPS[0], now);
  for (let i = 1; i < m.START_BUFFER; i++) m.loopImage(m.LOOPS[0], now += 34);
  assert.equal(m.loopImage(m.LOOPS[0], now += 34).key, 'sea17');
  assert.equal(m.loopImage(m.LOOPS[0], now += 34).key, 'sea17');
  await m.complete(m.requests.find(r => !r.finished && r.url.endsWith('/sea/d/019.webp')));
  assert.equal(m.loopImage(m.LOOPS[0], now += 34).key, 'sea18');
});

test('sustained slow rendering advances the loop instead of resetting its clock every frame', async () => {
  const m = setup(); m.loadAll(); await m.drain();
  const keys = [1000, 1300, 1600, 1900].map(now => m.loopImage(m.LOOPS[0], now).key);
  assert.equal(keys[0], 'sea0');
  assert.equal(new Set(keys).size, keys.length, 'Each 300 ms render should make bounded forward progress');
  const positions = keys.map(key => Number(key.slice(3)));
  assert.ok(positions.every((position, index) => index === 0 || position > positions[index - 1]));
  assert.ok(positions.at(-1) < 30, 'A long rendering interval must not cause unbounded catch-up');
});

test('scrolling promotes its target frame ahead of queued offscreen images', async () => {
  const m = setup(); m.loadAll();
  m.prioritizeFrames(.9);
  await m.complete(m.requests[0]);
  assert.equal(m.requests[4].url, 'assets/dive/h/217.webp');
  assert.ok(m.requests.every(r => !/under|deep/.test(r.url)));
  m.loopFor(.9);
  await m.complete(m.requests[1]);
  await m.complete(m.requests[2]);
  await m.complete(m.requests[3]);
  for (let i = 0; i < 8 && !m.requests.some(r => r.url.includes('/deep/')); i++) {
    await m.complete(m.requests.find(r => !r.finished));
  }
  assert.ok(m.requests.some(r => r.url.includes('/deep/')), 'The deep loop is loaded only after activation');
});

test('reduced motion requests only sparse stage stills, including after scrolling', async () => {
  const m = setup({ reduced: true, mobile: true });
  m.prioritizeFrames(.5); m.loadAll(); await m.drain();
  m.prioritizeFrames(.923); await m.drain();
  assert.equal(m.requests.length, m.STAGE_FRAMES.length);
  assert.ok(m.requests.every(r => !r.url.includes('/loop/')));
  const allowed = m.STAGE_FRAMES.map(i => `assets/dive/m2/${String(i + 1).padStart(3, '0')}.webp`);
  assert.ok(m.requests.every(r => allowed.includes(r.url)));
});
