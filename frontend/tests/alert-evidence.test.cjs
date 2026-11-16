'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const AlertEvidence = require('../app/alert-evidence.js');

test('per-scale dev evidence overrides global dev_only and allows numbers', () => {
  const history = {
    evidence: 'dev_only',
    scale_evidence: { '6-12m': 'dev', '12-24m': 'dev' },
  };

  assert.equal(AlertEvidence.forScale(history, '6-12m'), 'dev');
  assert.equal(AlertEvidence.showsNumbers(history, '6-12m'), true);
});

test('legacy history without scale_evidence falls back to dev_only and masks numbers', () => {
  const history = { evidence: 'dev_only' };

  assert.equal(AlertEvidence.forScale(history, '12-24m'), 'dev_only');
  assert.equal(AlertEvidence.showsNumbers(history, '12-24m'), false);
});

test('none, fail, and dev_failed evidence remain blocked', () => {
  for (const evidence of ['none', 'fail_i_iii', 'dev_failed']) {
    const history = { evidence: 'dev_only', scale_evidence: { '6-12m': evidence } };
    assert.equal(AlertEvidence.blocked(AlertEvidence.forScale(history, '6-12m')), true);
    assert.equal(AlertEvidence.showsNumbers(history, '6-12m'), false);
  }
});
