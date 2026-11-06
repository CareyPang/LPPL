'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Journey = require('../app/home-journey.js');
const html = fs.readFileSync(path.join(__dirname, '..', 'home.html'), 'utf8');

test('reduced motion and local files stay still despite an old animation preference', () => {
  for (const options of [{ reducedMotion: true }, { protocol: 'file:' }]) {
    const policy = Journey.motionPolicy({ ...options, stored: 'on' });
    assert.equal(policy.enabled, false);
    assert.equal(policy.locked, true);
  }
  assert.equal(Journey.motionPolicy().enabled, true);
  assert.equal(Journey.motionPolicy({ stored: 'off' }).enabled, false);
});

test('save-data is a separate static policy with an explicit user opt-in', () => {
  assert.equal(Journey.motionPolicy({ saveData: true }).enabled, false);
  assert.equal(Journey.motionPolicy({ saveData: true, stored: 'on' }).enabled, true);
  assert.equal(Journey.motionPolicy({ saveData: true, stored: 'off' }).enabled, false);
});

test('scroll narrative is reversible, bounded, and yields to document content', () => {
  assert.equal(Journey.scene(0).hero, 1);
  assert.equal(Journey.scene(.43).waterline, 1);
  assert.equal(Journey.scene(.78).underwater, 1);
  assert.equal(Journey.scene(1).underwater, 0);
  const positions = [0, .12, .26, .3, .36, .42, .58, .78, 1];
  const forward = positions.map(Journey.scene);
  const reverse = [...positions].reverse().map(Journey.scene).reverse();
  assert.deepEqual(forward, reverse);
  for (let i = -10; i <= 110; i++) {
    const value = Journey.scene(i / 100);
    for (const name of ['hero', 'waterline', 'underwater']) assert.ok(value[name] >= 0 && value[name] <= 1);
    assert.ok(value.hero + value.waterline + value.underwater <= 1.01);
  }
});

test('workstation links retain demo mode without forwarding unrelated parameters', () => {
  const links = [{ href: 'old' }, { href: 'other' }];
  const document = { querySelectorAll(selector) { assert.equal(selector, '[data-workstation]'); return links; } };
  assert.equal(Journey.prepareLinks(document, '?demo=1&code=600519&redirect=elsewhere'), 'stock.html?demo=1');
  assert.ok(links.every(link => link.href === 'stock.html?demo=1'));
  assert.equal(Journey.workstationHref('?demo=0'), 'stock.html');
  assert.equal(Journey.workstationHref(''), 'stock.html');
});

test('fixed narrative never crossfades two text blocks, in either scroll direction', () => {
  for (let step = 0; step <= 10000; step++) {
    for (const p of [step / 10000, 1 - step / 10000]) {
      const state = Journey.scene(p);
      assert.ok(['hero', 'waterline', 'underwater'].filter(key => state[key] > 0).length <= 1);
    }
  }
});

test('fixed copy finishes before document content and clears immediately on a fast scroll', () => {
  for (const height of [667, 844, 900]) {
    for (const introScale of [2.05, 2.45]) {
      const introHeight = height * introScale;
      const end = Journey.introRunway(introHeight, height);
      assert.ok(introHeight - end >= height * 1.0999);
    }
  }
  for (const progress of [0, .43, .78]) {
    const state = Journey.scene(progress, { contentTopRatio: .85 });
    assert.equal(state.hero + state.waterline + state.underwater, 0);
  }
});

test('scale controls change explanation and selected state without data access', () => {
  const buttons = ['stage', 'local', 'pending'].map(name => ({
    dataset: { scale: name }, attrs: {}, listeners: {},
    setAttribute(key, value) { this.attrs[key] = value; },
    addEventListener(name, handler) { this.listeners[name] = handler; }
  }));
  const panel = { dataset: {}, querySelectorAll() { return buttons; } };
  const elements = new Map([['scale-study', panel], ...['scale-title', 'scale-description', 'scale-note'].map(id => [id, { textContent: '' }])]);
  Journey.bindScales({ getElementById(id) { return elements.get(id); } });
  assert.equal(panel.dataset.selected, 'stage');
  assert.match(elements.get('scale-description').textContent, /1–6 个月上涨/);
  buttons[1].listeners.click();
  assert.equal(panel.dataset.selected, 'local');
  assert.equal(buttons[0].attrs['aria-pressed'], 'false');
  assert.equal(buttons[1].attrs['aria-pressed'], 'true');
  assert.match(elements.get('scale-description').textContent, /数周行情/);
  buttons[2].listeners.click();
  assert.match(elements.get('scale-note').textContent, /不是在给某只股票分类/);
});

test('real homepage has native links but no asset input or market-data dependency', () => {
  const anchors = [...html.matchAll(/<a\b([^>]*)>/g)].map(match => match[1]);
  const destinations = anchors.map(attrs => attrs.match(/href="([^"]+)"/)[1]);
  assert.equal(anchors.filter(attrs => /data-workstation/.test(attrs)).length, 4);
  assert.ok(destinations.every(href => href.startsWith('#') || href === 'stock.html'));
  assert.doesNotMatch(html, /LPPL\.load|lppl-data\.js|combo\[|p0\.1/);
  assert.doesNotMatch(html, /<input\b[^>]*(?:type="(?:text|search)"|name="(?:code|symbol)")/);
  assert.doesNotMatch(html, /<(?:script|link)[^>]*(?:src|href)="https?:/);
  assert.match(html, /<html[^>]+class="home-static"/);
  assert.match(html, /识别能力仍在验证/);
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(inline.length, 1);
  assert.doesNotThrow(() => new vm.Script(inline[0][1]));
});
