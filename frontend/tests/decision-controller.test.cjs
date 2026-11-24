const test = require('node:test');
const assert = require('node:assert/strict');
const Controller = require('../app/decision-controller.js');
const Reader = require('../app/chart-readonly-data.js');

const tick = () => new Promise(resolve => setImmediate(resolve));
function setup(load) {
  const context = { code: 'sh000001', assetType: 'index', market: 'cn', asof: '', scale: '6-12m' };
  const views = [], calls = [];
  const controller = Controller.attach({ context,
    adapter: { history: code => { calls.push(code); return load(code); } },
    reader: { ...Reader, timed: work => Promise.resolve().then(work) },
    state: { build: ({data, history, context}) => ({symbol: context.code, asof: data.modelAsOf,
      history, scale: context.scale, provenance: {}}) },
    onChange: view => views.push(view)
  });
  return { context, controller, views, calls };
}
test('prices render immediately and repeated scale changes reuse the history read', async () => {
  let resolve;
  const pending = new Promise(done => { resolve = done; });
  const x = setup(() => pending), data = {modelAsOf:'2026-11-23'};
  const first = x.controller.render(data);
  assert.equal(first.history, null);
  x.context.scale = '1-3m'; x.controller.render(data);
  await tick(); assert.equal(x.calls.length, 1);
  resolve({symbol:'sh000001', frames:[]}); await tick();
  assert.equal(x.views.at(-1).scale, '1-3m');
  assert.equal(x.views.at(-1).provenance.historyStatus, 'ready');
});
test('a late asset response cannot overwrite the new asset', async () => {
  const pending = {};
  const x = setup(code => new Promise(resolve => { pending[code] = resolve; }));
  x.controller.render({modelAsOf:'2026-11-23'}); await tick();
  x.context.code = 'sh000688'; x.controller.render({modelAsOf:'2026-11-23'}); await tick();
  pending.sh000688({symbol:'sh000688', frames:[]}); await tick();
  const n = x.views.length;
  pending.sh000001({symbol:'sh000001', frames:[]}); await tick();
  assert.equal(x.views.length, n);
  assert.equal(x.views.at(-1).history.symbol, 'sh000688');
});
test('identity mismatches and read failures keep prices usable and allow retry', async () => {
  let attempt = 0;
  const x = setup(() => {
    attempt++;
    if (attempt === 1) return {symbol:'sh000688', frames:[]};
    if (attempt === 2) throw Error('offline');
    return {symbol:'sh000001', frames:[]};
  });
  x.controller.render({modelAsOf:'2026-11-23'}); await tick();
  assert.equal(x.views.at(-1).history, null);
  assert.match(x.views.at(-1).provenance.historyError, /身份/);
  x.controller.retry(); await tick();
  assert.equal(x.views.at(-1).provenance.historyError, 'offline');
  x.controller.retry(); await tick();
  assert.equal(x.views.at(-1).provenance.historyStatus, 'ready');
});
test('historical frame retains only its sealed score and cooling fields', () => {
  const history = {symbol:'sh000001', bottom_summary:{win_rate_50w:1},
    cooling_state:{phase:'reentry_watch'}, fco_neg_intensity:1};
  const frame = {asof:'2026-11-20', fco_neg_intensity:.506,
    bottom_factors:{clearing:1,stabilize:.65}, cooling_state:{phase:'cooling_after_top'}};
  const r = Reader.packedFrame(history, frame,
    {code:'sh000001',assetType:'index',asof:'2026-11-20'}, [], '上证指数');
  assert.equal(r.raw.fco_neg_intensity, .506);
  assert.equal(r.raw.cooling_state.phase, 'cooling_after_top');
  assert.equal(r.raw.bottom_summary, undefined);
  const empty = Reader.packedFrame(history, {asof:'2026-11-16'},
    {code:'sh000001',assetType:'index',asof:'2026-11-16'}, [], '上证指数');
  assert.equal(empty.raw.fco_neg_intensity, undefined);
  assert.equal(empty.raw.cooling_state, undefined);
});
