'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const ScaleBar = require('../app/scale-bar.js');
const RuleLabels = require('../app/rule-labels.js');

test('classifies scales as fit, no-window, or no-evidence', () => {
  const states = ScaleBar.classify(
    { '6-12m': 'dev', '12-24m': 'dev', '2-4w': 'none' },
    { '6-12m': 0.42, '12-24m': 0.17, '2-4w': 0.9 },
    [{ scale: '6-12m', q20_date: '2026-12-01', q80_date: '2026-12-10' }],
  );
  assert.deepEqual(states.find(state => state.scale === '6-12m'), {
    scale: '6-12m', selectable: true, hasWindow: true, confidence: 0.42, status: '有区间',
  });
  assert.deepEqual(states.find(state => state.scale === '12-24m'), {
    scale: '12-24m', selectable: true, hasWindow: false, confidence: 0.17, status: '无合格拟合',
  });
  assert.deepEqual(states.find(state => state.scale === '2-4w'), {
    scale: '2-4w', selectable: false, hasWindow: false, confidence: null, status: '无证据',
  });
});

test('uses shared empty reasons for computed scale statuses', () => {
  const top = {
    indicators: {
      '6-12m': { signal_status: 'signal' },
      '12-24m': { signal_status: 'no_qualified_fit' },
    },
    lppls_confidence: { '6-12m': 0.25, '12-24m': 0 },
  };
  const states = ScaleBar.classify(
    { '6-12m': 'dev', '12-24m': 'dev' },
    top.lppls_confidence,
    [],
    top,
    () => [],
    RuleLabels,
  );
  assert.equal(states.find(state => state.scale === '6-12m').status, '有合格拟合，但没有形成聚类区间');
  assert.equal(states.find(state => state.scale === '12-24m').status, '已计算，没有合格拟合（不代表风险较低）');
});

test('parses valid scale hashes and falls back on invalid or disabled scales', () => {
  const states = ScaleBar.classify(
    { '6-12m': 'dev', '12-24m': 'dev' },
    {},
    [],
  );
  assert.equal(ScaleBar.parseHash('#scale=12-24m', states), '12-24m');
  assert.equal(ScaleBar.parseHash('#scale=2-4w', states), '6-12m');
  assert.equal(ScaleBar.parseHash('#scale=unknown', states), '6-12m');
  assert.equal(ScaleBar.parseHash('', states), '6-12m');
});
