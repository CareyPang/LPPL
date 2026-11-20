const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const desk = require('../app/guanshi-data.js');

const archiveRoot = path.join(__dirname, '../../web/mock/data');
async function readArchive(file) {
  try {
    const data = JSON.parse(await fs.readFile(path.join(archiveRoot, file), 'utf8'));
    return { data, reason: null };
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return { data: null, reason: 'unpublished' };
  }
}

async function load(symbol, getter = readArchive) {
  global.LPPL = { BASE: 'lab/mock/data/', fetchResult: getter };
  return desk.load(symbol);
}

test('observed prices and research windows use different source vintages and independent cutoff dates', async () => {
  const dataset = await load('sh600519');
  const now = desk.view(dataset);
  assert.equal(now.asof, '2026-11-17');
  assert.equal(now.modelAsOf, '2026-10-30');
  assert.equal(now.bars.length, 640);
  assert.equal(now.bars.at(-1).close, 1457.7);
  assert.equal(now.priceUnit, '元');
  assert.match(now.quoteSource, /market\/archives\//);
  assert.match(now.source, /stock\/600519.json/);
  assert.equal(now.state, 'no_window');
  assert.equal(now.exampleDate, '2025-05-23');
  assert.equal(now.firstVisible, null);
});

for (const [id, day, start, end] of [
  ['sh600519', '2025-05-23', '2025-06-20', '2025-07-08'],
  ['sh000001', '2025-07-07', '2025-07-09', '2025-07-16'],
]) {
  test(id + ' reveals only subsequent observed prices; the selected historical record is invariant', async () => {
    const d = await load(id);
    const before = desk.view(d, day);
    const after = desk.view(d, day, true);
    assert.equal(before.state, 'window');
    assert.equal(before.provenance, '历史重算');
    assert.equal(before.firstVisible, null);
    assert.equal(before.modelAsOf, day);
    assert.deepEqual(before.windows.map(w => [w.start, w.end]), [[start, end]]);
    assert.equal(before.bars.at(-1).date, day);
    assert.ok(after.bars.length > before.bars.length);
    assert.deepEqual(before.bars, after.bars.slice(0, before.bars.length));
    for (const key of Object.keys(before).filter(key => key !== 'bars')) assert.deepEqual(after[key], before[key], key);
    const noRecord = desk.view(d, '2025-05-22');
    assert.equal(noRecord.state, 'no_record');
    assert.equal(noRecord.modelAsOf, null);
    assert.equal(noRecord.windows.length, 0);
    assert.ok(noRecord.bars.every(b => b.date <= '2025-05-22'));
  });
}

test('a confirmed coverage miss is different from a failed archive read', async () => {
  const stocks = await readArchive('market/stock_list.json');
  assert.ok(stocks.data.rows.some(row => row[0] === '600320' && row[1] === '振华重工'));
  const missing = desk.view(await load('sh600320'));
  assert.equal(missing.state, 'uncovered');
  assert.equal(missing.asof, null);
  assert.deepEqual(missing.bars, []);
  const network = desk.view(await load('sh600320', async () => ({ data: null, reason: 'unavailable' })));
  assert.equal(network.state, 'unavailable');
  assert.equal(network.windows.length, 0);
});

test('non-displayable, single-day and mismatched-price historical windows never become numeric recommendations', async () => {
  for (const [change, expected] of [
    [d => { d.scale_evidence['6-12m'] = 'dev_only'; }, 'restricted'],
    [d => { d.frames.find(f => f.asof === '2025-07-07').w['6-12m'] = ['2025-07-09', '2025-07-09']; }, 'restricted'],
    [d => { d.frames.find(f => f.asof === '2025-07-07').close *= 2; }, 'no_record'],
  ]) {
    const d = await load('sh000001', async file => {
      const result = await readArchive(file);
      if (file.endsWith('_history.json')) change(result.data);
      return result;
    });
    const v = desk.view(d, '2025-07-07');
    assert.equal(v.state, expected);
    assert.deepEqual(v.windows, []);
  }
});

test('manual raw quote updates only the current view and leaves replay prices, model and source intact', async () => {
  const dataset = await load('sh600519');
  const before = desk.view(dataset, '2025-05-23', true);
  const source = await readArchive('market/archives/sh600519_2026-11-17.json');
  const next = structuredClone(source.data);
  // Synthetic provider response for refresh semantics, independent of the real price archive.
  next.asof = next.cutoff = '2026-11-18';
  next.generated_at = '2026-11-18T09:00:00Z';
  next.price = [...next.price.slice(1), { ...next.latest, date: next.asof }];
  next.price[0].close = next.price[0].open;
  next.latest = next.price.at(-1);
  const now = Date.parse(next.generated_at) + 1000;
  global.LPPL.stock = {
    market: async code => { assert.equal(code, '600519'); return next; },
    api: () => 'https://example.test',
  };
  const changed = await desk.refreshQuote(dataset, now);
  assert.equal(changed.status, 'updated');
  const current = desk.view(changed.dataset);
  assert.equal(current.quoteAsOf, next.asof);
  assert.equal(current.modelAsOf, '2026-10-30');
  assert.equal(current.quoteSource, 'https://example.test/market?code=600519');
  assert.match(current.quoteStatus, /时效未独立核验/);
  assert.deepEqual(current.bars.at(-1), next.latest);
  assert.equal(current.windows.length, 0);
  const reopened = await desk.load('sh600519');
  assert.equal(desk.view(reopened).quoteAsOf, next.asof);
  for (const historicalDay of ['2025-05-23', '2026-11-17']) {
    const archived = desk.view(dataset, historicalDay, true);
    const revisited = desk.view(changed.dataset, historicalDay, true);
    for (const key of Object.keys(archived).filter(key => key !== 'dates')) assert.deepEqual(revisited[key], archived[key], key);
  }
  assert.deepEqual(before.bars, desk.view(dataset, '2025-05-23', true).bars);
  assert.equal((await desk.refreshQuote(changed.dataset, now)).status, 'unchanged');
  global.LPPL.stock.market = async () => source.data;
  assert.equal((await desk.refreshQuote(changed.dataset, now)).dataset, changed.dataset);
  global.LPPL.stock.market = async () => next;
  next.stale = true;
  assert.equal((await desk.refreshQuote(dataset, now)).dataset, dataset);
  next.stale = false; next.adjustment = 'hfq';
  assert.equal((await desk.refreshQuote(dataset, now)).status, 'unavailable');
  next.adjustment = 'none'; next.generated_at = '2026-11-18T07:29:59Z';
  assert.equal((await desk.refreshQuote(dataset, now)).status, 'unavailable');
  global.LPPL.stock.market = async () => { throw new Error('offline'); };
  assert.equal((await desk.refreshQuote(dataset, now)).dataset, dataset);
});

test('a slow history read leaves genuine current prices available', async () => {
  let resolveHistory, firstQuote;
  const quote = new Promise(resolve => { firstQuote = resolve; });
  const deferred = new Promise(resolve => { resolveHistory = resolve; });
  global.LPPL = { BASE: 'lab/mock/data/', fetchResult: file =>
    file.endsWith('_history.json') ? deferred : readArchive(file) };
  const reading = desk.load('sh600519', d => { if (d.allBars.length) firstQuote(desk.view(d)); });
  assert.equal((await quote).bars.at(-1).close, 1457.7);
  resolveHistory(await readArchive('stock/600519_history.json'));
  assert.equal((await reading).exampleDate, '2025-05-23');
});

test('a market response generated during the GET is valid on arrival, a future timestamp is not', async t => {
  const file = 'market/archives/sh600519_2026-11-17.json';
  const { data: response } = await readArchive(file);
  // Use the actual Worker payload for the later close. Trim one real session
  // from the local input to reproduce an update without synthesizing prices.
  const previous = structuredClone(response);
  previous.price.pop();
  previous.latest = previous.price.at(-1);
  previous.asof = previous.cutoff = previous.latest.date;
  const d = await load('sh600519', async name => {
    if (name === file) return { data: previous, reason: null };
    const result = await readArchive(name);
    // The nightly model can already be dated today when the saved quote still ends yesterday.
    if (name === 'stock/600519.json') result.data.asof = response.asof;
    return result;
  });
  assert.equal(desk.view(d, response.asof).quoteAsOf, previous.asof);
  const generated = Date.parse(response.generated_at);
  let clock = generated - 1000;
  t.mock.method(Date, 'now', () => clock);
  let deliver;
  global.LPPL.stock = {
    api: () => 'https://example.test',
    market: () => new Promise(resolve => { deliver = resolve; }),
  };
  const reading = desk.refreshQuote(d);
  clock = generated + 1000;
  deliver(response);
  const updated = await reading;
  assert.equal(updated.status, 'updated');
  assert.deepEqual(desk.view(updated.dataset).bars.at(-1), response.latest);
  assert.deepEqual(desk.view(updated.dataset, response.asof).bars.at(-1), response.latest);

  const subsequent = desk.refreshQuote(updated.dataset);
  deliver({ ...response, generated_at: new Date(clock + 3_600_000).toISOString() });
  const rejected = await subsequent;
  assert.equal(rejected.status, 'unavailable');
  assert.deepEqual(desk.view(rejected.dataset).bars, desk.view(updated.dataset).bars);
});

test('a sealed day shows original vintage bars even when the later archive revises its candle', async () => {
  const dir = path.join(archiveRoot, '../../../forward_log');
  const ledger = (await fs.readFile(path.join(dir, 'ledger.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  const records = [];
  for (const day of ['2026-11-16', '2026-11-17']) {
    const entry = ledger.find(row => row.symbol === 'sh000001' && row.asof === day);
    const record = JSON.parse(await fs.readFile(path.join(dir, day, 'sh000001.json'), 'utf8'));
    records.push({ ...entry, record, path: 'forward_log/' + day + '/sh000001.json' });
  }
  const originalClose = records[0].record.price_history.close.at(-1);
  const later = structuredClone(records[1].record);
  const i = later.price_history.dates.indexOf('2026-11-16');
  later.price_history.close[i] += 10;
  const d = await load('sh000001', async file => {
    if (file.includes('_seals')) return { data: { symbol: 'sh000001', records } };
    if (file.endsWith('_latest.json')) return { data: later };
    return readArchive(file);
  });
  const sealed = desk.view(d, '2026-11-16');
  const revealed = desk.view(d, '2026-11-16', true);
  assert.equal(sealed.provenance, '当日封存');
  assert.equal(sealed.sealedAt, '2026-11-16T12:07:14+00:00');
  assert.equal(sealed.firstVisible, null);
  assert.equal(sealed.bars.at(-1).close, originalClose);
  assert.equal(revealed.bars.at(-2).close, originalClose);
  assert.deepEqual(sealed.evidence, revealed.evidence);
  assert.deepEqual(sealed.windows, revealed.windows);
  assert.equal(revealed.bars.at(-1).date, '2026-11-17');
  assert.equal(revealed.bars.length, sealed.bars.length + 1);

  const incompatible = structuredClone(records[1].record);
  incompatible.price_history.volume[i] *= 100;
  const difference = await load('sh000001', async file => {
    if (file.includes('_seals')) return { data: { symbol: 'sh000001', records: [records[0]] } };
    if (file.endsWith('_latest.json')) return { data: incompatible };
    return readArchive(file);
  });
  const chart = desk.view(difference, '2026-11-16', true);
  assert.match(chart.laterVolumeNote, /后续成交量留空/);
  assert.equal(chart.bars.at(-1).volume, null);
  assert.equal(chart.bars.at(-1).close, incompatible.price_history.close.at(-1));
  assert.equal(chart.bars.at(-2).volume, sealed.bars.at(-1).volume);
});
