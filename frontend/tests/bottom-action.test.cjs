const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const BottomAction = require('../app/bottom-action.js');

const ROOT = path.resolve(__dirname, '..', '..');

test('bottom-action applies the V2 score tiers', () => {
  const top = BottomAction.evaluate({ sym: 'sh000001', hasTop: true, score: 0 });
  assert.equal(top.tier, 'top_risk');
  assert.equal(top.canBuy, false);

  for (const [score, tier, canBuy] of [
    [0, 'neutral', false],
    [59.9, 'neutral', false],
    [60, 'bottom_probe', true],
  ]) {
    const action = BottomAction.evaluate({
      sym: 'sh000688',
      hasTop: false,
      score,
      factors: { dd_52w: -0.404, valuation: 0.5, clearing: 1 },
    });
    assert.equal(action.tier, tier);
    assert.equal(action.canBuy, canBuy);
    assert.equal(action.targetPct, null);
  }
});

test('bottom-action evaluates all 7 published *_history.json files cleanly', () => {
  const syms = ['sh000001', 'sh000016', 'sh000300', 'sh000905', 'sz399001', 'sz399006', 'sh000688'];
  const out = {};
  for (const sym of syms) {
    const raw = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/mock/data', `${sym}_history.json`), 'utf8'));
    out[sym] = BottomAction.fromHistory(sym, raw);
    assert.ok(out[sym].positionLabel);
    assert.equal(out[sym].targetPct, null);
    // 分档只由最后一帧的已发布分数决定；数据每周更新，不写死某个指数的档位
    const last = raw.frames[raw.frames.length - 1];
    const hasTop = Array.isArray(last.w && last.w['6-12m']) && !!last.w['6-12m'][0];
    const score = Number(last.fco_neg_intensity || 0) * 100;
    const expected = hasTop ? 'top_risk' : score >= 60 ? 'bottom_probe' : 'neutral';
    assert.equal(out[sym].tier, expected, sym);
  }
});

test('home.html, index.html, backtest.html wire overview_latest.json, radar bar and bottom ledger', () => {
  const home = fs.readFileSync(path.join(__dirname, '..', 'home.html'), 'utf8');
  const idx = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  const bt = fs.readFileSync(path.join(__dirname, '..', 'backtest.html'), 'utf8');
  const ov = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/mock/data/overview_latest.json'), 'utf8'));

  assert.equal(ov.indices.length, 7);
  const kcItem = ov.indices.find((x) => x.sym === 'sh000688');
  const kc = BottomAction.fromOverviewItem(kcItem);
  const kcTier = kcItem.bottom_score >= 60 ? 'bottom_probe' : 'neutral';
  assert.ok([kcTier, 'top_risk'].includes(kc.tier));
  assert.equal(kc.targetPct, null);

  assert.match(home, /app\/bottom-action\.js/);
  assert.match(home, /class="act-strip"/);
  assert.match(home, /id="radar-bar"/);
  assert.match(home, /id="radar-sort"/);
  assert.match(idx, /app\/bottom-action\.js/);
  assert.match(idx, /id="action-verdict"/);
  assert.match(idx, /LPPLDecisionPanel\.mount/);
  assert.match(idx, /LPPLDecisionState\.build/);
  assert.doesNotMatch(idx, /class="act-steps"/);
  assert.match(idx, /class="tk-tag"/);
  assert.match(bt, /id="ov-strip"/);
  assert.match(bt, /data-ledger-mode="bottom"/);
  assert.match(bt, /id="bottom-rows"/);
  assert.match(bt, /主簇区间与时间中位数/);
  assert.match(idx, /app\/alert-ledger\.js/);

  const stock = fs.readFileSync(path.join(__dirname, '..', 'stock.html'), 'utf8');
  assert.match(stock, /app\/scen-style\.js/);
  assert.match(stock, /app\/bottom-action\.js/);
  assert.match(stock, /app\/alert-ledger\.js/);
  assert.match(stock, /id="stock-fco-toggle"/);
  assert.match(stock, /id="stock-action-card"/);
});

test('missing bottom score stays missing, while zero and shock risk remain distinct', () => {
  for (const score of [null, undefined, '']) {
    const missing = BottomAction.evaluate({ sym: 'sh000001', score });
    assert.equal(missing.score, null);
    assert.equal(missing.tier, 'unavailable');
    assert.equal(missing.canBuy, false);
  }
  assert.equal(BottomAction.evaluate({ score: 0 }).tier, 'neutral');
  const risk = BottomAction.evaluate({ score: 0, omoriRed: true });
  assert.equal(risk.score, 0);
  assert.equal(risk.tier, 'neutral');
  assert.equal(risk.canBuy, false);
});

test('red cooling does not gate a score of 65', () => {
  const action = BottomAction.evaluate({
    score: 65,
    omoriRed: true,
  });
  assert.equal(action.tier, 'bottom_probe');
  assert.equal(action.canBuy, true);
  assert.equal(action.targetPct, null);
});

test('bottom-action strings contain no position sizing or add/reduce instructions', () => {
  const tiers = [
    BottomAction.evaluate({ hasTop: true, score: 55 }),
    BottomAction.evaluate({ score: null }),
    BottomAction.evaluate({ score: 59.9 }),
    BottomAction.evaluate({ score: 60 }),
  ];
  assert.deepEqual(tiers.map((action) => action.tier),
    ['top_risk', 'unavailable', 'neutral', 'bottom_probe']);
  for (const action of tiers) {
    const text = Object.values(action).filter((value) => typeof value === 'string').join(' ');
    assert.doesNotMatch(text, /30%|60%|100%|加仓|减仓|仓位|试探仓|打满|%仓/);
    assert.equal(action.targetPct, null);
  }
  assert.equal('STEPS' in BottomAction, false);
});

test('published decision compatibility preserves stale date and never invents a position', () => {
  const view = { top: { status: 'none' }, bottom: { score: 51, asof: '2026-11-20', stale: true },
    conclusion: { status: 'stale_watch', tone: 'amber', title: '评分待更新', detail: '旧档', next: '核对更新' } };
  const action = BottomAction.fromDecision(view);
  assert.equal(action.score, 51);
  assert.equal(action.scoreAsOf, '2026-11-20');
  assert.equal(action.scoreStale, true);
  assert.equal(action.canBuy, false);
  assert.equal(action.targetPct, null);
  assert.equal(action.positionLabel, view.conclusion.title);
  assert.equal(action.canBuyLabel, view.conclusion.next);
});

test('alert-ledger detects locked non-drifting top cluster vs drifting cluster with median_date', () => {
  const AlertLedger = require('../app/alert-ledger.js');
  // 连续 4 周预测中位数稳定钉在 2025-06-15 附近（不往后漂移）
  const lockedFrames = [
    { asof: '2025-05-02', close: 3200, w: { '6-12m': ['2025-06-01', '2025-07-01'] } },
    { asof: '2025-05-09', close: 3250, w: { '6-12m': ['2025-06-02', '2025-06-28'] } },
    { asof: '2025-05-16', close: 3300, w: { '6-12m': ['2025-06-04', '2025-06-26'] } },
    { asof: '2025-05-23', close: 3340, w: { '6-12m': ['2025-06-05', '2025-06-25'] } },
  ];
  const lockedEps = AlertLedger.episodes(lockedFrames, [], '6-12m');
  assert.equal(lockedEps.length, 1);
  assert.equal(lockedEps[0].convergence.status, 'locked');
  assert.equal(lockedEps[0].convergence.high_confidence, true);
  assert.equal(lockedEps[0].convergence.stable_weeks, 4);
  assert.ok(lockedEps[0].median_date && lockedEps[0].median_date.startsWith('2025-06'));

  // 连续 4 周每次往后推 10 天（典型追涨漂移伪信号）
  const driftFrames = [
    { asof: '2025-05-02', close: 3200, w: { '6-12m': ['2025-06-01', '2025-07-01'] } },
    { asof: '2025-05-09', close: 3250, w: { '6-12m': ['2025-06-11', '2025-07-11'] } },
    { asof: '2025-05-16', close: 3300, w: { '6-12m': ['2025-06-21', '2025-07-21'] } },
    { asof: '2025-05-23', close: 3340, w: { '6-12m': ['2025-07-01', '2025-07-31'] } },
  ];
  const driftEps = AlertLedger.episodes(driftFrames, [], '6-12m');
  assert.equal(driftEps[0].convergence.status, 'drifting');
  assert.equal(driftEps[0].convergence.high_confidence, false);
});

test('bottom-action evaluatePricePhysics identifies cleared vacuum below dense cost well', () => {
  const bars = [];
  for (let i = 0; i < 200; i += 1) {
    const px = 100 + Math.sin(i / 5) * 1.5;
    bars.push({ date: `2025-01-${String((i % 28) + 1).padStart(2, '0')}`, high: px * 1.01, low: px * 0.99, close: px, volume: 2e6 });
  }
  for (let i = 0; i < 50; i += 1) {
    const px = 98 - i * 0.65;
    bars.push({ date: `2025-10-${String((i % 28) + 1).padStart(2, '0')}`, high: px * 1.01, low: px * 0.99, close: px, volume: 8e5 });
  }
  const pp = BottomAction.evaluatePricePhysics(bars);
  assert.ok(pp);
  assert.ok(pp.wellF >= 1.25);
  assert.equal(pp.noWellBelow, true);
  assert.ok(pp.vwapGap < -0.10);
  assert.equal(pp.inVacuum, true);
});
