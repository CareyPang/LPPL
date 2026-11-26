'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const backtest = fs.readFileSync(path.join(__dirname, '..', 'backtest.html'), 'utf8');
const dataLayer = fs.readFileSync(path.join(__dirname, '..', 'app/lppl-data.js'), 'utf8');
const buildScript = fs.readFileSync(path.join(__dirname, '..', '..', 'scripts/build_site.sh'), 'utf8');

test('backtest evidence table shows the published V2 three-segment results without refetching or recomputing', () => {
  assert.match(backtest, /bottom_score: H\.bottom_score \|\| null/);
  assert.match(backtest, /const meta = st\.H && st\.H\.bottom_score, segs = meta && meta\.segments;/);
  assert.match(backtest, /底分 ≥60 三段检验（7 个 A 股指数，事前登记）/);
  assert.match(backtest, /测试段只有一个下跌—反弹周期/);
  assert.doesNotMatch(backtest, /≥50|30–49|20–49|止跌|四维/);
  for (const sym of ['sh000001', 'sh000688']) {
    const hist = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'web/mock/data', `${sym}_history.json`), 'utf8'));
    assert.equal(hist.bottom_score.version, 'v2');
    assert.equal(hist.bottom_score.green_min, 60);
    assert.deepEqual(Object.keys(hist.bottom_score.segments), ['dev', 'cal', 'test']);
    for (const frame of hist.frames) {
      const s = frame.fco_neg_intensity;
      assert.equal(frame.bottom_bar, s >= 0.6 ? 'green' : s > 0 ? 'weak' : undefined);
      if (frame.bottom_detail) assert.deepEqual(Object.keys(frame.bottom_factors).sort(),
        ['clearing', 'dd_52w', 'erp_pct', 'pbn_pct', 'valuation', 'version']);
    }
  }
});

test('backtest locks each frame from its as-of convergence and distinguishes missing intensity', () => {
  assert.match(backtest, /frame\.topLocked = Boolean\(convergence && convergence\.high_confidence\)/);
  assert.match(backtest, /frame\.fcoNegIntensity = frame\.fco_neg_intensity != null[\s\S]*?: null;/);
  assert.match(backtest, /整轮复盘：高危锁定/);
  assert.match(backtest, /f\.fcoNegIntensity != null && f\.fcoNegIntensity > 0/);
  assert.match(backtest, /f\.fcoNegIntensity == null \? '未覆盖'/);
});
