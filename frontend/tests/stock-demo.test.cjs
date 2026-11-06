'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { create } = require('../app/stock-demo.js');
const Session = require('../app/stock-session.js');
const data = require('../app/stock-demo-data.js');
const JOB = '11111111-1111-4111-8111-111111111111';
async function settle() { for (let i = 0; i < 20; i++) await Promise.resolve(); }

test('bundled sample matches the provenance hash and retains real qfq OHLCV bounds', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../assets/demo/manifest.json'), 'utf8'));
  const js = fs.readFileSync(path.join(__dirname, '../app/stock-demo-data.js'));
  assert.equal(crypto.createHash('sha256').update(js).digest('hex'), manifest.artifact_sha256);
  const market = data.samples['600519'];
  assert.deepEqual(Object.keys(data.samples), ['600519']);
  assert.equal(market.symbol, 'sh600519');
  assert.equal(market.adjustment, 'qfq');
  assert.equal(market.volume_unit, 'vendor_native');
  assert.equal(market.price.length, 250);
  assert.equal(market.price[0].date, '2025-10-14');
  assert.equal(market.price.at(-1).date, '2026-10-23');
  assert.equal(market.price.at(-1).close, 1335);
  assert.equal(market.price.at(-1).volume, 5768593);
  assert.equal(market.provenance.source_sha256, '53f9674375c16b1b898b4a1ccc7d7fdc241a490d34001e4e35ccfa7b22c21c57');
  assert.ok(market.price.every(bar => bar.high >= Math.max(bar.open, bar.close) && bar.low <= Math.min(bar.open, bar.close)));
});

test('explicit demo adapter supplies observed data and no model predictions', async () => {
  let now = Date.parse('2026-11-06T10:00:00Z');
  const api = create(data, { now: () => now, uuid: () => JOB });
  const market = await api.market('600519');
  market.price[0].close = -1;
  assert.ok((await api.market('600519')).price[0].close > 0, 'consumer mutation cannot corrupt source sample');
  assert.equal(await api.latest('600519'), null);
  const job = await api.request('600519');
  assert.equal((await api.request('600519')).job_id, job.job_id, 'running demo tasks deduplicate');
  assert.equal((await api.status('600519', { jobId: job.job_id })).status, 'queued');
  now += 3000;
  assert.equal((await api.status('600519', { jobId: job.job_id })).status, 'in_progress');
  assert.equal(await api.remote('600519', 'latest', { jobId: job.job_id }), null);
  now += 5000;
  const result = await api.remote('600519', 'latest', { jobId: job.job_id });
  assert.equal(result.demo, true);
  assert.equal(result.model_computed, false);
  assert.equal(result.top.window.start, null);
  assert.equal(result.top.window.evidence, 'none');
  assert.equal(result.top.drawdown_price.value, null);
  assert.equal(await api.dipEnv(), null);
  await assert.rejects(() => api.market('000001'), /只包含贵州茅台/);
  await assert.rejects(() => api.request('000001'), /只包含贵州茅台/);
});

test('presentation tasks can recover from separate storage without touching live session keys', async () => {
  const values = new Map([['lppl.stock.jobs.v1', 'protected live state']]);
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  let now = Date.parse('2026-11-06T10:00:00Z');
  const api = create(data, { storage, now: () => now, uuid: () => JOB });
  await api.request('600519'); now += 8000;
  const restored = create(data, { storage, now: () => now });
  assert.equal((await restored.status('600519', { jobId: JOB })).current_ready, true);
  assert.equal((await restored.remote('600519', 'latest', { jobId: JOB })).job_id, JOB);
  assert.equal(values.get('lppl.stock.jobs.v1'), 'protected live state');
});

test('demo keeps the existing independent market/current/history session contract', async () => {
  let now = Date.parse('2026-11-06T10:00:00Z'), serial = 0;
  const timers = new Map();
  const api = create(data, { now: () => now, uuid: () => (++serial).toString(16).padStart(8, '0') + '-1111-4111-8111-111111111111' });
  const session = Session.create({ api, now: () => now, onChange() {}, pollMs: 700,
    setTimeout: fn => { const id = Symbol(); timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id) });
  await session.select('600519'); await settle();
  assert.equal(session.snapshot().market.price.length, 250);
  assert.equal(session.snapshot().currentStatus, 'queued');
  assert.equal(session.snapshot().historyStatus, 'idle');
  now += 8000;
  for (const [id, fn] of [...timers]) { timers.delete(id); fn(); }
  await settle();
  assert.equal(session.snapshot().current.demo, true);
  assert.equal(session.snapshot().currentStatus, 'ready');
  await session.request('600519', 'history'); await settle();
  assert.equal(session.snapshot().currentStatus, 'ready');
  assert.equal(session.snapshot().historyStatus, 'queued');
  now += 8000;
  for (const [id, fn] of [...timers]) { timers.delete(id); fn(); }
  await settle();
  assert.equal(session.snapshot().historyStatus, 'ready');
  assert.equal(Session.compatible(session.snapshot().current, session.snapshot().history), true);
  session.destroy();
});

test('offline adapter has no network fallback, including unknown codes and results', async () => {
  const original = global.fetch;
  let calls = 0;
  global.fetch = () => { calls++; throw Error('Network forbidden in presentation test'); };
  try {
    const api = create(data, { uuid: () => JOB });
    await api.market('600519'); await api.latest('600519'); await api.history('600519');
    await api.dipEnv(); await api.request('600519'); await api.status('600519', { jobId: JOB });
    await api.remote('600519', 'history');
    await assert.rejects(() => api.market('600000'));
    assert.equal(calls, 0);
  } finally { global.fetch = original; }
});
