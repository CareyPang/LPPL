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
});
