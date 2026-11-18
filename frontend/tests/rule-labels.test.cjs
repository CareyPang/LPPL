'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const RuleLabels = require('../app/rule-labels.js');

function topFor(confidence, signalStatus = 'signal') {
  return {
    indicators: { '6-12m': { signal_status: signalStatus } },
    lppls_confidence: { '6-12m': confidence },
  };
}

test('publishes the specified rules and combined caption footnote', () => {
  assert.deepEqual(RuleLabels.RULES.box, {
    id: 'box',
    name: '形态框',
    short: '区间与占比用“形态框”规则：只看拟合形状，不含振荡次数和阻尼条件',
    source: '区间来源：形态框规则（不含振荡/阻尼条件）',
  });
  assert.deepEqual(RuleLabels.RULES.standard, {
    id: 'standard',
    name: 'FCO 标准过滤',
    short: '“合格拟合数”和“有合格拟合”用 FCO 标准过滤：另要求振荡约 0.8 个周期以上、阻尼与误差达标，比形态框严格',
  });
  assert.equal(
    RuleLabels.renderCaption(['box', 'standard']),
    `${RuleLabels.RULES.box.short}；${RuleLabels.RULES.standard.short}；${RuleLabels.FOOTNOTE}`,
  );
  assert.equal(RuleLabels.renderCaption(['standard']), RuleLabels.RULES.standard.short);
});

test('classifies uncomputed scales when indicators are absent or confidence is null', () => {
  assert.equal(RuleLabels.emptyReason({}, '6-12m', false, true), 'not_computed');
  assert.equal(RuleLabels.emptyReason(topFor(null), '6-12m', false, true), 'not_computed');
  assert.equal(RuleLabels.emptyReason(topFor(0, 'not_computed'), '6-12m', false, true), 'not_computed');
  assert.equal(RuleLabels.reasonText('not_computed'), '这个尺度尚未计算');
});

test('classifies computed scales without fits or clusters', () => {
  assert.equal(RuleLabels.emptyReason(topFor(0), '6-12m', false, true), 'no_fit');
  assert.equal(RuleLabels.reasonText('no_fit'), '已计算，没有合格拟合（不代表风险较低）');
  assert.equal(RuleLabels.emptyReason(topFor(0.25), '6-12m', false, true), 'no_cluster');
  assert.equal(RuleLabels.reasonText('no_cluster'), '有合格拟合，但没有形成聚类区间');
});

test('classifies non-formal intervals without exposing values and accepts displayable clusters', () => {
  assert.equal(RuleLabels.emptyReason(topFor(0.25), '6-12m', true, false), 'not_formal');
  assert.equal(RuleLabels.reasonText('not_formal'), '已形成候选区间，证据不足，不作正式提醒');
  assert.equal(RuleLabels.emptyReason(topFor(0.25), '6-12m', [{ q20_date: '2026-01-01' }], true), null);
  assert.equal(RuleLabels.reasonText('unknown'), '');
});
