const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const Core = require('../app/chart-page-core.js');
const Decision = require('../app/decision-state.js');
const BottomAction = require('../app/bottom-action.js');

function fixture(symbol = 'sh000688', market = 'cn') {
  const top = { signal_status: 'no_qualified_fit', indicators: {
    '6-12m': { signal_status: 'no_qualified_fit', direction: 'positive' },
  }, lppls_confidence: { evidence: 'dev', scale_evidence: { '6-12m': 'dev' } }, scale_windows: [] };
  const raw = { symbol, asof: '2026-11-23', top, model_version: 'fixture-v1',
    price_history: { dates: ['2026-11-20', '2026-11-23'], close: [1231, 1228] } };
  if (market !== 'cn') raw.research = { cycles_1_5: top };
  const result = { raw, top, asof: raw.asof, sym: { sym: symbol, market }, name: symbol,
    bars: [{ date: '2026-11-20', close: 1231 }, { date: '2026-11-23', close: 1228 }] };
  const history = { symbol, frames: [{ asof: '2026-11-20', fco_neg_intensity: 0.506,
    bottom_factors: { valuation: .22, clearing: 1, stabilize: .65, right_side: 0 } }] };
  return { result, history, asset: { sym: symbol, name: symbol, market } };
}

async function homeView(f) {
  const calls = [];
  const root = { LPPLChartPageCore: Core, LPPLDecisionState: Decision, BottomAction,
    LPPL: { load: async symbol => { calls.push(['load', symbol]); return f.result; },
      history: async symbol => { calls.push(['history', symbol]); return f.history; } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/home-data.js'), 'utf8'), {
    window: root, location: { hostname: '127.0.0.1' }, Promise,
  });
  return { row: await root.HOMEDATA.one(f.asset), calls };
}

function terminalDecision(f, historical = false) {
  const source = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
  const start = source.indexOf('  function decisionFor(R) {');
  const end = source.indexOf('  function renderUnifiedDecision(R)', start);
  const ctx = { window: { LPPLChartPageCore: Core, LPPLDecisionState: Decision }, selectedScale: '6-12m' };
  vm.runInNewContext(source.slice(start, end), ctx);
  return ctx.decisionFor({ J: f.result.raw, top: f.result.top, bars: f.result.bars, asof: f.result.asof,
    sym: { code: f.asset.sym, label: f.asset.name }, latest: !historical, historyData: f.history });
}

test('home and legacy terminal preserve the same dated bottom score and conclusion', async () => {
  const f = fixture();
  const { row, calls } = await homeView(f);
  assert.equal(row.error, undefined);
  const terminal = terminalDecision(f);
  assert.equal(row.action.score, 50.6);
  assert.equal(row.action.scoreAsOf, '2026-11-20');
  assert.equal(row.action.scoreStale, true);
  assert.equal(row.action.canBuy, false);
  assert.equal(row.action.positionLabel, terminal.conclusion.title);
  assert.equal(row.action.decisionStatus, terminal.conclusion.status);
  assert.deepEqual(calls, [['load', 'sh000688'], ['history', 'sh000688']]);
});

test('historical terminal never substitutes a nearby or later score', () => {
  const f = fixture();
  f.result.asof = f.result.raw.asof = '2026-11-19';
  f.result.bars = [{ date: '2026-11-18', close: 1230 }, { date: '2026-11-19', close: 1220 }];
  f.result.raw.price_history = { dates: ['2026-11-18', '2026-11-19'], close: [1230, 1220] };
  const result = terminalDecision(f, true);
  assert.equal(result.bottom.score, null);
  assert.equal(result.bottom.summary, null);
});

test('international home entry does not borrow a Chinese bottom score', async () => {
  const f = fixture('KR_KOSPI', 'kr');
  f.history.symbol = 'sh000688';
  const { row } = await homeView(f);
  assert.equal(row.market, 'kr');
  assert.equal(row.action.score, null);
  assert.equal(row.action.canBuy, false);
  assert.equal(row.action.targetPct, null);
});

test('missing history still leaves the home price and current model available', async () => {
  const f = fixture();
  f.history = null;
  const { row } = await homeView(f);
  assert.equal(row.error, undefined);
  assert.equal(row.last.close, 1228);
  assert.equal(row.action.score, null);
  assert.equal(row.decision.top.status, 'none');
});

test('home prices resolve before delayed history, which updates only evidence later', { timeout: 2000 }, async () => {
  const f = fixture();
  let resolveHistory, receiveUpdate;
  const history = new Promise(resolve => { resolveHistory = resolve; });
  const updated = new Promise(resolve => { receiveUpdate = resolve; });
  const root = { LPPLChartPageCore: Core, LPPLDecisionState: Decision, BottomAction,
    LPPL: { load: async () => f.result, history: () => history } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/home-data.js'), 'utf8'), {
    window: root, location: { hostname: '127.0.0.1' }, Promise,
  });
  const initial = await root.HOMEDATA.one(f.asset, receiveUpdate);
  assert.equal(initial.last.close, 1228);
  assert.equal(initial.historyStatus, 'loading');
  assert.equal(initial.decision.bottom.status, 'loading');
  assert.equal(initial.action, null);
  resolveHistory(f.history);
  const final = await updated;
  assert.equal(final.bars, initial.bars);
  assert.equal(final.action.score, 50.6);
  assert.equal(final.action.scoreAsOf, '2026-11-20');
  assert.equal(final.historyStatus, 'ready');
});

test('late history failure preserves prices and reports a missing score, not zero', { timeout: 2000 }, async () => {
  const f = fixture();
  let rejectHistory, receiveUpdate;
  const history = new Promise((_, reject) => { rejectHistory = reject; });
  const updated = new Promise(resolve => { receiveUpdate = resolve; });
  const root = { LPPLChartPageCore: Core, LPPLDecisionState: Decision, BottomAction,
    LPPL: { load: async () => f.result, history: () => history } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/home-data.js'), 'utf8'), {
    window: root, location: { hostname: '127.0.0.1' }, Promise,
  });
  const initial = await root.HOMEDATA.one(f.asset, receiveUpdate);
  rejectHistory(new Error('offline'));
  const final = await updated;
  assert.equal(final.last.close, initial.last.close);
  assert.equal(final.error, undefined);
  assert.equal(final.historyStatus, 'error');
  assert.equal(final.decision.bottom.status, 'error');
  assert.equal(final.action.score, null);
});
