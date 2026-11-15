'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { create, identity } = require('../app/stock-visibility.js');

const result = { symbol: 'sh600519', asof: '2026-11-12', job_id: 'job-1', generated_at: '2026-11-12T08:00:00Z' };
function harness() {
  const events = new Map(), frames = new Map(), store = new Map(), observations = [];
  let next = 0, now = Date.parse('2026-11-13T02:00:00Z');
  const eventsTarget = { addEventListener: (name, fn) => events.set(name, fn), removeEventListener: name => events.delete(name) };
  const document = { ...eventsTarget, visibilityState: 'visible' };
  const window = { ...eventsTarget, innerHeight: 800, innerWidth: 1200 };
  let rect = { top: 900, bottom: 1000, left: 0, right: 800, width: 800, height: 100 };
  const element = { isConnected: true, hidden: false, getBoundingClientRect: () => rect };
  const options = { document, window, now: () => now,
    storage: { getItem: key => store.get(key), setItem: (key, value) => store.set(key, value) },
    requestAnimationFrame: fn => { frames.set(++next, fn); return next; },
    cancelAnimationFrame: id => frames.delete(id), onVisible: row => observations.push(row) };
  const tracker = create(options);
  return { tracker, document, element, observations, store, frames,
    visible: () => { rect = { ...rect, top: 100, bottom: 200 }; events.get('scroll')?.(); },
    signal: name => events.get(name)?.(),
    frame() { const entry = frames.entries().next().value; if (entry) { frames.delete(entry[0]); entry[1](); } },
    advance() { now += 60000; }, restart() { return create(options); } };
}

test('receiving data or being below the fold does not create first-visible evidence', () => {
  const h = harness(); h.tracker.observe(h.element, result);
  assert.equal(h.frames.size, 0); assert.equal(h.store.size, 0);
  h.visible(); h.frame();
  assert.equal(h.store.size, 0, 'One animation frame is insufficient for the paint boundary');
  h.frame();
  assert.equal(h.observations.length, 1);
  assert.equal(h.observations[0].first_visible_at_client, '2026-11-13T02:00:00.000Z');
  assert.equal(h.observations[0].client_clock_trust, 'unverified');
  assert.equal(h.observations[0].publication_evidence, 'NOT_ESTABLISHED');
  h.tracker.destroy();
});

test('a hidden document cannot record visibility, even if it becomes hidden between paints', () => {
  const h = harness(); h.document.visibilityState = 'hidden';
  h.tracker.observe(h.element, result); h.visible(); assert.equal(h.frames.size, 0);
  h.document.visibilityState = 'visible'; h.signal('visibilitychange'); h.frame();
  h.document.visibilityState = 'hidden'; h.frame(); assert.equal(h.observations.length, 0);
  h.document.visibilityState = 'visible'; h.signal('visibilitychange'); h.frame(); h.frame();
  assert.equal(h.observations.length, 1); h.tracker.destroy();
});

test('first visible time is append-only per artifact and separate from Worker observation', () => {
  const h = harness(); h.visible();
  const value = { ...result, first_worker_observed_at: '2026-11-12T10:00:00Z' };
  h.tracker.observe(h.element, value); h.frame(); h.frame(); h.advance();
  h.tracker.observe(h.element, value); h.frame(); h.frame();
  assert.equal(h.observations[0].first_visible_at_client, h.observations[1].first_visible_at_client);
  assert.equal(h.observations[0].first_worker_observed_at, '2026-11-12T10:00:00Z');
  h.tracker.destroy(); const restored = h.restart();
  restored.observe(h.element, value); h.frame(); h.frame();
  assert.equal(h.observations[2].first_visible_at_client, h.observations[0].first_visible_at_client);
  restored.observe(h.element, { ...value, job_id: 'job-2' }); h.frame(); h.frame();
  assert.notEqual(h.observations[3].first_visible_at_client, h.observations[0].first_visible_at_client);
  restored.destroy();
});

test('changing stock, detaching the result or destroying tracking invalidates pending paints', () => {
  const h = harness(); h.visible(); h.tracker.observe(h.element, result); h.frame();
  h.tracker.observe(null, null); h.frame(); assert.equal(h.observations.length, 0);
  h.tracker.observe(h.element, result); h.frame(); h.element.isConnected = false; h.frame();
  assert.equal(h.observations.length, 0);
  h.element.isConnected = true; h.tracker.observe(h.element, result); h.tracker.destroy();
  h.frame(); h.frame(); assert.equal(h.observations.length, 0);
  assert.notEqual(identity(result), identity({ ...result, mode: 'history' }));
});
