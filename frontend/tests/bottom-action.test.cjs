const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const BottomAction = require('../app/bottom-action.js');

const ROOT = path.resolve(__dirname, '..', '..');

test('bottom-action 5-tier state machine covers top, neutral, left_wait, bottom_probe, right_confirm', () => {
  const top = BottomAction.evaluate({ sym: 'sh000001', hasTop: true, score: 0 });
  assert.equal(top.tier, 'top_risk');
  assert.equal(top.canBuy, false);

  const neutral = BottomAction.evaluate({ sym: 'sh000001', hasTop: false, score: 0 });
  assert.equal(neutral.tier, 'neutral');
  assert.equal(neutral.canBuy, false);

  const left = BottomAction.evaluate({
    sym: 'sh000905',
    hasTop: false,
    score: 28,
    factors: { dd_52w: -0.313, stabilize: 0, right_side: 0 },
  });
  assert.equal(left.tier, 'left_wait');
  assert.equal(left.canBuy, false);
  assert.equal(left.targetPct, 0);

  const probe = BottomAction.evaluate({
    sym: 'sh000688',
    hasTop: false,
    score: 51,
    factors: { dd_52w: -0.404, stabilize: 0.65, right_side: 0 },
    summary: { win_rate_50w: 0.75, median_post_min_50w: -0.141 },
  });
  assert.equal(probe.tier, 'bottom_probe');
  assert.equal(probe.canBuy, true);
  assert.equal(probe.targetPct, 30);
  assert.equal(probe.stepIndex, 1);

  const confirm = BottomAction.evaluate({
    sym: 'sz399006',
    hasTop: false,
    score: 68,
    factors: { dd_52w: -0.38, stabilize: 0.65, right_side: 1.0 },
  });
  assert.equal(confirm.tier, 'right_confirm');
  assert.equal(confirm.canBuy, true);
  assert.equal(confirm.targetPct, 60);
  assert.equal(confirm.stepIndex, 2);
});

test('bottom-action evaluates all 7 published *_history.json files cleanly', () => {
  const syms = ['sh000001', 'sh000016', 'sh000300', 'sh000905', 'sz399001', 'sz399006', 'sh000688'];
  const out = {};
  for (const sym of syms) {
    const raw = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/mock/data', `${sym}_history.json`), 'utf8'));
    out[sym] = BottomAction.fromHistory(sym, raw);
    assert.ok(out[sym].positionLabel);
    assert.ok(out[sym].positionText);
  }
  assert.equal(out.sh000688.tier, 'bottom_probe');
  assert.equal(out.sh000688.targetPct, 30);
  assert.equal(out.sh000905.tier, 'left_wait');
  assert.equal(out.sh000001.tier, 'neutral');
});

test('home.html, index.html, backtest.html wire overview_latest.json, radar bar and bottom ledger', () => {
  const home = fs.readFileSync(path.join(__dirname, '..', 'home.html'), 'utf8');
  const idx = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  const bt = fs.readFileSync(path.join(__dirname, '..', 'backtest.html'), 'utf8');
  const ov = JSON.parse(fs.readFileSync(path.join(ROOT, 'web/mock/data/overview_latest.json'), 'utf8'));

  assert.equal(ov.indices.length, 7);
  const kc = BottomAction.fromOverviewItem(ov.indices.find((x) => x.sym === 'sh000688'));
  assert.equal(kc.tier, 'bottom_probe');
  assert.equal(kc.targetPct, 30);

  assert.match(home, /app\/bottom-action\.js/);
  assert.match(home, /class="act-strip"/);
  assert.match(home, /id="radar-bar"/);
  assert.match(home, /id="radar-sort"/);
  assert.match(idx, /app\/bottom-action\.js/);
  assert.match(idx, /id="action-verdict"/);
  assert.match(idx, /class="act-steps"/);
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

test('bottom-action evaluateStockSeries maps board index and blocks heavy entry under Omori aftershocks', () => {
  const bars = [];
  let px = 160;
  for (let i = 0; i < 80; i += 1) {
    const dt = new Date(Date.UTC(2026, 7, 1 + i)).toISOString().slice(0, 10);
    if (i > 40 && i < 65) px *= 0.985;
    if (i === 72 || i === 75) px *= 0.93; // 近 15 日连续大阴线
    bars.push({ date: dt, close: Number(px.toFixed(2)) });
  }
  const res = BottomAction.evaluateStockSeries(bars, { code: '300843', hasTop: false });
  assert.equal(res.board.sym, 'sz399006');
  assert.equal(res.latest.omoriRed, true);
  assert.ok(res.latest.score <= 46);
  assert.equal(res.action.canBuy, false);
  assert.equal(res.action.tier, 'left_wait');
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
