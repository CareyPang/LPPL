'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/visual-suite.js'), 'utf8');

function eventTarget(extra = {}) {
  const listeners = new Map();
  return Object.assign({
    addEventListener(type, listener) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(listener);
    },
    emit(type, event = {}) {
      for (const listener of listeners.get(type) || []) listener(event);
    }
  }, extra);
}

function setup({ reduced = false, fine = true, complete = false, naturalWidth = 0 } = {}) {
  const classes = new Set();
  const properties = new Map();
  const image = eventTarget({ complete, naturalWidth });
  const hero = eventTarget({
    querySelector(selector) { return selector === 'img' ? image : null; },
    classList: {
      add(value) { classes.add(value); },
      remove(value) { classes.delete(value); },
      contains(value) { return classes.has(value); }
    },
    style: {
      setProperty(name, value) { properties.set(name, value); },
      getPropertyValue(name) { return properties.get(name) || ''; }
    },
    getBoundingClientRect() { return { left: 100, top: 200, width: 600, height: 400 }; }
  });
  const motion = eventTarget({ matches: reduced });
  const pointer = eventTarget({ matches: fine });
  const document = eventTarget({
    hidden: false,
    querySelectorAll(selector) { return selector === '.visual-media' ? [hero] : []; },
    querySelector(selector) { return selector === '.hero-art .visual-media' ? hero : null; }
  });
  let requested = 0;
  const pending = new Map();
  const context = {
    document,
    matchMedia(query) { return query.includes('prefers-reduced-motion') ? motion : pointer; },
    requestAnimationFrame(callback) {
      const id = ++requested;
      pending.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id) { pending.delete(id); }
  };
  vm.runInNewContext(source, context, { filename: 'visual-suite.js' });
  return {
    image, hero, document, motion, pointer,
    get requested() { return requested; },
    get pending() { return pending.size; },
    flush() {
      const callbacks = Array.from(pending.values());
      pending.clear();
      callbacks.forEach(callback => callback());
    }
  };
}

test('a successful image reload clears the previously shown fallback', () => {
  const ui = setup();
  ui.image.emit('error');
  assert.equal(ui.hero.classList.contains('art-unavailable'), true);

  // A failed/empty load must not expose a broken image.
  ui.image.emit('load');
  assert.equal(ui.hero.classList.contains('art-unavailable'), true);

  ui.image.naturalWidth = 1536;
  ui.image.complete = true;
  ui.image.emit('load');
  assert.equal(ui.hero.classList.contains('art-unavailable'), false);
});

test('an already-failed cached image can recover without recreating its card', () => {
  const ui = setup({ complete: true });
  assert.equal(ui.hero.classList.contains('art-unavailable'), true);
  ui.image.naturalWidth = 640;
  ui.image.emit('load');
  assert.equal(ui.hero.classList.contains('art-unavailable'), false);
});

test('reduced motion leaves pointer movement static and does not schedule animation', () => {
  const ui = setup({ reduced: true });
  ui.hero.emit('pointermove', { clientX: 650, clientY: 500 });
  ui.hero.emit('pointermove', { clientX: 120, clientY: 240 });
  assert.equal(ui.requested, 0);
  assert.equal(ui.pending, 0);
});

test('coarse pointers do not schedule decorative parallax', () => {
  const ui = setup({ fine: false });
  ui.hero.emit('pointermove', { clientX: 650, clientY: 500 });
  assert.equal(ui.requested, 0);
  assert.equal(ui.pending, 0);
});

test('fine pointer movement stays bounded and leaving cancels pending movement', () => {
  const ui = setup();
  // Extreme coordinates also cover pointer capture / moving outside the frame.
  ui.hero.emit('pointermove', { clientX: -10000, clientY: 10000 });
  ui.hero.emit('pointermove', { clientX: 10000, clientY: -10000 });
  assert.equal(ui.pending, 1, 'rapid events keep only one pending update');
  ui.flush();
  const x = parseFloat(ui.hero.style.getPropertyValue('--art-x'));
  const y = parseFloat(ui.hero.style.getPropertyValue('--art-y'));
  assert.ok(x > 0 && x <= 5, 'horizontal movement stays within the 5px budget');
  assert.ok(y < 0 && y >= -3, 'vertical movement stays within the 3px budget');
  assert.equal(ui.pending, 0, 'no perpetual animation loop');

  ui.hero.emit('pointermove', { clientX: 120, clientY: 240 });
  assert.equal(ui.pending, 1);
  ui.hero.emit('pointerleave');
  assert.equal(ui.pending, 0);
  assert.equal(ui.hero.style.getPropertyValue('--art-x'), '0px');
  assert.equal(ui.hero.style.getPropertyValue('--art-y'), '0px');
  ui.flush();
  assert.equal(ui.hero.style.getPropertyValue('--art-x'), '0px', 'cancelled work cannot move the art after leaving');
});
