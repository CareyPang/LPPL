'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const backtest = fs.readFileSync(path.join(__dirname, '..', 'backtest.html'), 'utf8');
const dataLayer = fs.readFileSync(path.join(__dirname, '..', 'app/lppl-data.js'), 'utf8');
const buildScript = fs.readFileSync(path.join(__dirname, '..', '..', 'scripts/build_site.sh'), 'utf8');

test('backtest evidence table reads published calibration and location reports through LPPLData', () => {
  assert.match(dataLayer, /fetchResult\('bottom_calibration\.json'\)/);
  assert.match(dataLayer, /fetchResult\('bottom_location\.json'\)/);
  assert.match(buildScript, /bottom_calibration\.json/);
  assert.match(buildScript, /bottom_location\.json/);
  assert.match(backtest, /LPPL\.bottomEvidence\(\)/);
  assert.match(backtest, /calibration\.tables\[segment\]\[bucket\]\['50w'\]/);
  assert.match(backtest, /location\.segments\[segment\]\.W26\.groups\[bucket\]/);
  assert.match(backtest, /底分分档历史检验（7 个 A 股指数）/);
  assert.match(backtest, /['"]B1['"].*['"]<30['"]/);
  assert.match(backtest, /['"]B2['"].*['"]30–49['"]/);
  assert.match(backtest, /['"]B3['"].*['"]≥50['"]/);
  assert.match(backtest, /if \(!evidence \|\| evidence\.reason \|\| !evidence\.calibration \|\| !evidence\.location\) return;/);
});

test('backtest locks each frame from its as-of convergence and distinguishes missing intensity', () => {
  assert.match(backtest, /frame\.topLocked = Boolean\(convergence && convergence\.high_confidence\)/);
  assert.match(backtest, /frame\.fcoNegIntensity = frame\.fco_neg_intensity != null[\s\S]*?: null;/);
  assert.match(backtest, /整轮复盘：高危锁定/);
  assert.match(backtest, /f\.fcoNegIntensity != null && f\.fcoNegIntensity > 0/);
  assert.match(backtest, /f\.fcoNegIntensity == null \? '未覆盖'/);
});
