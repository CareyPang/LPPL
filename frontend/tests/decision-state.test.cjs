'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Decision = require('../app/decision-state.js');

const ASOF = '2026-11-23';
function setup() {
  const factors = { valuation: 0.76, clearing: 0.5,
    erp_pct: 0.442, pbn_pct: 0.888, dd_52w: -0.404 };
  const top = { signal_status: 'no_qualified_fit',
    indicators: { '6-12m': { signal_status: 'no_qualified_fit', evidence: 'dev' } },
    lppls_confidence: { scale_evidence: { '6-12m': 'dev', '12-24m': 'dev' }, evidence: 'dev' },
    scale_clusters: { '6-12m': [], '12-24m': [] } };
  return {
    data: { symbol: 'sh000688', assetType: 'index', market: 'cn', modelStatus: 'ok', modelAsOf: ASOF, marketAsOf: ASOF,
      raw: { symbol: 'sh000688', asof: ASOF, top, model_version: 'published-v1' }, top },
    context: { code: 'sh000688', assetType: 'index', market: 'cn', scale: '6-12m', rule: 'box', asof: '' },
    history: { symbol: 'sh000688', frames: [
      { asof: '2026-11-16', fco_neg_intensity: 0.46, bottom_factors: { ...factors, clearing: 0.01 } },
      { asof: ASOF, fco_neg_intensity: 0.625, bottom_factors: factors },
    ], bottom_summary: { n_events: 9, n_with_50w: 8, win_rate_50w: 0.75, baseline_win_rate_50w: 0.383,
      median_ret_50w: 0.205, median_post_min_50w: -0.141 } },
  };
}
function score(input, value, overrides = {}) {
  const frame = input.history.frames.at(-1);
  frame.fco_neg_intensity = value / 100;
  frame.bottom_factors = { ...frame.bottom_factors, ...overrides };
}
function active(input, start = ASOF, end = '2026-12-01', scale = '6-12m') {
  input.data.raw.top.indicators[scale] = { signal_status: 'signal', evidence: 'dev' };
  input.data.raw.top.scale_clusters[scale] = [{ q20_date: start, q80_date: end, share: 0.7, n: 7 }];
}

test('same-day published score, actual weights and prior change are shown without inventing a position', () => {
  const state = Decision.build(setup());
  assert.equal(state.bottom.score, 62.5);
  assert.equal(state.bottom.asof, ASOF);
  assert.equal(state.bottom.stale, false);
  assert.ok(Math.abs(state.bottom.delta - 16.5) < 1e-10);
  assert.equal(state.bottom.previousAsOf, '2026-11-16');
  assert.deepEqual(state.bottom.components.map(x => x.weight), [0.6, 0.4]);
  assert.equal(state.conclusion.status, 'bottom_probe');
  assert.equal(state.conclusion.tone, 'green');
  assert.equal(state.bottom.summary.n, 8);
  assert.equal(state.bottom.summary.nEvents, 9);
  assert.match(state.bottom.summary.label, /50周/);
  assert.equal(state.provenance.modelVersion, 'published-v1');
  assert.equal('targetPct' in state.conclusion, false);
});

test('an active top interval takes precedence over a high bottom score, including zero-day lead', () => {
  const input = setup(); score(input, 80); active(input);
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 80);
  assert.equal(state.bottom.status, 'candidate');
  assert.equal(state.top.status, 'active');
  assert.equal(state.top.windows[0].q20_date, ASOF);
  assert.equal(state.conclusion.status, 'top_watch');
  assert.equal(state.conclusion.tone, 'red');
  assert.ok(state.conclusion.blockers.length);
});

test('expired windows remain history and an old generic signal cannot turn them into a current warning', () => {
  const input = setup();
  delete input.data.raw.top.indicators['6-12m'];
  input.data.raw.top.signal_status = 'signal';
  input.data.raw.top.scale_clusters['6-12m'] = [{ q20_date: '2026-07-01', q80_date: '2026-07-20', share: 1 }];
  const state = Decision.build(input);
  assert.equal(state.top.status, 'expired');
  assert.equal(state.top.windows.length, 0);
  assert.equal(state.top.expiredWindows.length, 1);
  assert.equal(state.conclusion.status, 'bottom_probe');
});

test('explicit current no-fit overrides an old signal and a stale future window', () => {
  const input = setup(); input.data.raw.top.signal_status = 'signal';
  input.data.raw.top.scale_clusters['6-12m'] = [{ q20_date: '2026-11-26', q80_date: '2026-12-02', share: 1 }];
  const state = Decision.build(input);
  assert.equal(state.top.structureStatus, 'no_qualified_fit');
  assert.equal(state.top.status, 'none');
  assert.equal(state.top.windows.length, 0);
  assert.equal(state.conclusion.status, 'bottom_probe');
});

test('positive structure without a current interval is not described as an active cluster', () => {
  const input = setup(); input.data.raw.top.indicators['6-12m'].signal_status = 'signal';
  const state = Decision.build(input);
  assert.equal(state.top.status, 'structure');
  assert.equal(state.top.windows.length, 0);
  assert.equal(state.conclusion.status, 'structure_watch');
  assert.match(state.top.label, /尚无当前区间/);
});

test('cooling stays descriptive when the score is below 60', () => {
  const input = setup(); score(input, 0);
  input.data.raw.cooling_state = { dashboard: { verdict_light: 'red', dimensions: [{ id: 'omori', light: 'red' }] } };
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 0);
  assert.equal(state.bottom.status, 'neutral');
  assert.equal(state.cooling.status, 'blocked');
  assert.equal(state.conclusion.status, 'neutral');
});

test('scores 59.9 and 60 use the unrounded bottom tiers', () => {
  for (const [n, bottomStatus, conclusionStatus] of [
    [0, 'neutral', 'neutral'],
    [59.9, 'neutral', 'neutral'],
    [60, 'candidate', 'bottom_probe'],
  ]) {
    const input = setup(); score(input, n);
    const state = Decision.build(input);
    assert.equal(state.bottom.score, n);
    assert.equal(state.bottom.status, bottomStatus);
    assert.equal(state.conclusion.status, conclusionStatus);
  }
});

test('red cooling does not gate a score of 65', () => {
  const input = setup(); score(input, 65);
  input.data.raw.cooling_state = { dashboard: { verdict_light: 'red', dimensions: [{ id: 'omori', light: 'red' }] } };
  const state = Decision.build(input);
  assert.equal(state.cooling.status, 'blocked');
  assert.equal(state.conclusion.status, 'bottom_probe');
});

test('display values stay precise at the 60 point boundary', () => {
  for (const [intensity, expectedStatus, expectedConclusion] of [
    [0.599, 'neutral', 'neutral'], [0.6, 'candidate', 'bottom_probe'],
  ]) {
    const input = setup(); input.history.frames.at(-1).fco_neg_intensity = intensity;
    const state = Decision.build(input);
    assert.equal(state.bottom.score, intensity * 100);
    assert.equal(state.bottom.status, expectedStatus);
    assert.equal(state.conclusion.status, expectedConclusion);
  }
});

test('loading and failed score reads are distinguished from genuinely missing coverage', () => {
  const input = setup(); input.history = null; input.historyStatus = 'loading';
  let state = Decision.build(input);
  assert.equal(state.bottom.score, null);
  assert.equal(state.bottom.status, 'loading');
  assert.equal(state.bottom.label, '评分记录读取中');
  assert.match(state.conclusion.title, /读取中/);
  assert.doesNotMatch(state.conclusion.detail, /未覆盖/);
  input.historyStatus = 'error';
  state = Decision.build(input);
  assert.equal(state.bottom.status, 'error');
  assert.equal(state.bottom.label, '评分记录读取失败');
  assert.match(state.conclusion.next, /重试/);
  input.historyStatus = 'ready';
  assert.equal(Decision.build(input).bottom.status, 'missing');
});

test('score loading does not conceal a top interval or erase a valid score in the model record', () => {
  const input = setup(); input.history = null; input.historyStatus = 'loading'; active(input);
  const pending = Decision.build(input);
  assert.equal(pending.bottom.status, 'loading');
  assert.equal(pending.conclusion.status, 'top_watch');
  input.data.raw.bottom_score = 61.7;
  input.data.raw.bottom_factors = setup().history.frames.at(-1).bottom_factors;
  input.historyStatus = 'error';
  const retained = Decision.build(input);
  assert.equal(retained.bottom.score, 61.7);
  assert.equal(retained.bottom.status, 'candidate');
  assert.equal(retained.conclusion.status, 'top_watch');
  assert.equal(retained.provenance.historyStatus, 'error');
});

test('missing score and missing factors stay null while a genuine zero remains zero', () => {
  const input = setup(); input.history = null;
  let state = Decision.build(input);
  assert.equal(state.bottom.score, null);
  assert.equal(state.bottom.status, 'missing');
  assert.ok(state.bottom.components.every(c => c.value === null && c.weight === null));
  assert.equal(state.conclusion.status, 'incomplete');
  input.data.raw.fco_neg_intensity = 0;
  state = Decision.build(input);
  assert.equal(state.bottom.score, 0);
  assert.equal(state.bottom.components[0].value, null);
});

test('an absent valuation leaves the weights unspecified without changing score', () => {
  const input = setup(); score(input, 63, { valuation: null, erp_pct: null, pbn_pct: null });
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 63);
  assert.equal(state.bottom.schemeId, 'unspecified');
  assert.deepEqual(state.bottom.components.map(x => x.weight), [null, null]);
  assert.equal(state.bottom.components[0].value, null);
  assert.equal(state.bottom.delta, null, 'different weighting schemes cannot produce an apparent improvement');
});

test('historical replay reads the exact score, excludes later frames and hides full-history outcome statistics', () => {
  const input = setup(); input.context.asof = '2026-11-16';
  input.data.modelAsOf = input.data.raw.asof = '2026-11-16';
  // Later prices may be shown by replay, but must not alter the historical decision.
  input.data.marketAsOf = '2026-11-23';
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 46);
  assert.equal(state.bottom.asof, '2026-11-16');
  assert.equal(state.bottom.stale, false);
  assert.equal(state.bottom.summary, null);
  assert.equal(state.conclusion.status, 'neutral');
  input.context.asof = input.data.modelAsOf = input.data.raw.asof = '2026-11-17';
  const missing = Decision.build(input);
  assert.equal(missing.bottom.score, null);
  assert.equal(missing.bottom.summary, null);
});

test('current view can show the latest eligible weekly score but cannot promote stale data into a current buy state', () => {
  const input = setup(); input.history.frames[1].asof = '2026-11-20';
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 62.5);
  assert.equal(state.bottom.asof, '2026-11-20');
  assert.equal(state.bottom.stale, true);
  assert.equal(state.conclusion.status, 'stale_watch');
});

test('raw stale publication is respected when index assembly has omitted the stale flag and dates match', () => {
  const input = setup(); input.data.raw.stale = true;
  input.data.raw.stale_reason = 'update_failed_existing_result_retained';
  const state = Decision.build(input);
  assert.equal(state.provenance.stale, true);
  assert.equal(state.provenance.staleReason, 'update_failed_existing_result_retained');
  assert.equal(state.bottom.stale, true);
  assert.equal(state.conclusion.status, 'stale_watch');
  assert.match(state.conclusion.detail, /来源状态/);
});

test('explicit stale freshness is respected but not_established is not reclassified as stale', () => {
  for (const [owner, key] of [['raw', 'asof_freshness'], ['raw', 'freshness'], ['data', 'freshness']]) {
    const input = setup(), record = owner === 'raw' ? input.data.raw : input.data;
    record[key] = 'stale';
    assert.equal(Decision.build(input).conclusion.status, 'stale_watch');
    record[key] = 'not_established';
    assert.equal(Decision.build(input).provenance.stale, false);
    assert.equal(Decision.build(input).conclusion.status, 'bottom_probe');
  }
});

test('stale active top intervals stay visible with an update label rather than a new-alert presentation', () => {
  const input = setup(); active(input); input.data.raw.stale = true;
  const state = Decision.build(input);
  assert.equal(state.top.windows.length, 1);
  assert.equal(state.top.stale, true);
  assert.equal(state.top.tone, 'amber');
  assert.match(state.top.label, /已有.*待更新/);
  assert.equal(state.conclusion.status, 'top_watch');
  assert.equal(state.conclusion.tone, 'amber');
  assert.match(state.conclusion.title, /已有.*待更新/);
  assert.match(state.conclusion.detail, /不是新一期提醒/);
});

test('historical exact snapshots are unaffected by current freshness flags', () => {
  const input = setup(); active(input); input.context.asof = ASOF;
  input.data.stale = input.data.raw.stale = true;
  input.data.freshness = input.data.raw.asof_freshness = 'stale';
  input.data.marketAsOf = '2026-11-24';
  const state = Decision.build(input);
  assert.equal(state.provenance.stale, false);
  assert.equal(state.top.stale, false);
  assert.equal(state.bottom.stale, false);
  assert.equal(state.top.windows.length, 1);
  assert.equal(state.conclusion.tone, 'red');
  assert.doesNotMatch(state.conclusion.title, /待更新/);
  assert.equal(state.bottom.summary, null);
});

test('wrong asset or unidentified history cannot fill a score, but does not erase an independent valid raw score', () => {
  const input = setup(); input.history.symbol = 'sh000905';
  assert.equal(Decision.build(input).bottom.score, null);
  delete input.history.symbol;
  assert.equal(Decision.build(input).bottom.score, null);
  input.data.raw.bottom_score = 57;
  input.data.raw.bottom_factors = setup().history.frames[1].bottom_factors;
  assert.equal(Decision.build(input).bottom.score, 57);
  input.data.raw.symbol = 'sh000905';
  const invalid = Decision.build(input);
  assert.equal(invalid.bottom.score, null);
  assert.equal(invalid.top.status, 'unavailable');
  assert.equal(invalid.conclusion.status, 'unavailable');
});

test('same asset and date with incompatible model, fit, variant or scoring versions cannot combine records', () => {
  for (const field of ['model_version', 'fit_code_version', 'variant', 'score_version']) {
    const input = setup(); input.data.raw[field] = 'current'; input.history[field] = 'different';
    const state = Decision.build(input);
    assert.equal(state.bottom.score, null, field);
    assert.equal(state.bottom.summary, null, field);
    assert.equal(state.bottom.versionMismatch, true, field);
    assert.ok(state.bottom.versionMismatchFields.includes(field));
    assert.match(state.bottom.label, /版本不符/);
    assert.match(state.conclusion.title, /版本不符/);
  }
});

test('a frame-specific version is checked after selection and does not fall back to an older matching score', () => {
  const input = setup(); input.history.model_version = 'published-v1';
  input.history.frames[1].model_version = 'other-v2';
  const state = Decision.build(input);
  assert.equal(state.bottom.score, null);
  assert.equal(state.bottom.summary, null);
  assert.equal(state.bottom.versionMismatch, true);
  input.history.frames[1].model_version = 'published-v1';
  input.history.model_version = 'catalog-v2';
  const matchingFrame = Decision.build(input);
  assert.equal(matchingFrame.bottom.score, 62.5, 'the selected frame can explicitly override a newer catalog version');
  assert.equal(matchingFrame.bottom.versionMismatch, false);
  assert.equal(matchingFrame.bottom.summary, null, 'catalog-wide outcomes still have a different version');
});

test('an independent raw score survives incompatible history while comparison and mixed-version statistics are suppressed', () => {
  const input = setup(); input.data.raw.bottom_score = 63;
  input.data.raw.bottom_factors = input.history.frames.at(-1).bottom_factors;
  input.history.model_version = 'different-v2';
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 63);
  assert.equal(state.bottom.source, '已发布模型结果');
  assert.match(state.bottom.label, /版本不符/);
  assert.equal(state.bottom.summary, null);
  assert.equal(state.bottom.delta, null);
  assert.equal(state.conclusion.status, 'bottom_probe');
});

test('version compatibility accepts absent metadata and differing data hashes, but rejects nested variant conflicts', () => {
  const input = setup(); input.data.raw.data_version = 'current-download'; input.history.data_version = 'older-snapshot';
  input.data.raw.fit_code_version = 'fit-v1'; // History does not provide this optional field.
  assert.equal(Decision.build(input).bottom.score, 62.5);
  input.data.raw.stock_meta = { variant: 'variant-a' }; input.history.stock_meta = { variant: 'variant-b' };
  assert.equal(Decision.build(input).bottom.score, null);
});

test('same selected-frame version does not legitimize a summary or delta mixing other model versions', () => {
  const input = setup(); input.history.model_version = 'published-v1';
  input.history.frames[0].model_version = 'old-v0';
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 62.5);
  assert.equal(state.bottom.delta, null);
  assert.equal(state.bottom.summary, null);
  assert.match(state.bottom.summarySuppressedReason, /版本/);
});

test('international assets without their own score do not inherit an A-share score', () => {
  const input = setup();
  input.data.symbol = input.data.raw.symbol = input.context.code = 'US_MRVL';
  input.data.assetType = input.context.assetType = 'stock';
  input.context.market = 'us'; input.data.raw.stock_meta = { evidence: 'research_candidate' };
  const state = Decision.build(input);
  assert.equal(state.symbol, 'US_MRVL');
  assert.equal(state.bottom.score, null);
  assert.equal(state.conclusion.status, 'incomplete');
});

test('failed scale evidence cannot be revived by caller bands or a positive signal', () => {
  const input = setup(); active(input);
  input.bands = input.data.raw.top.scale_clusters['6-12m'];
  input.data.raw.top.lppls_confidence.scale_evidence['6-12m'] = 'fail_i';
  const state = Decision.build(input);
  assert.equal(state.top.windows.length, 0);
  assert.notEqual(state.top.status, 'structure');
  assert.notEqual(state.conclusion.status, 'top_watch');
});

test('explicit empty cluster arrays do not fall back to an old aggregate window', () => {
  const input = setup();
  input.data.raw.top.indicators['6-12m'].signal_status = 'signal';
  input.data.raw.top.window = { start: ASOF, end: '2026-12-02', evidence: 'dev' };
  const state = Decision.build(input);
  assert.equal(state.top.windows.length, 0);
  assert.equal(state.top.status, 'structure');
});

test('future history scores and later-generated statistics are excluded', () => {
  const input = setup();
  input.history.frames.push({ ...input.history.frames[1], asof: '2026-11-24', fco_neg_intensity: 0.99 });
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 62.5);
  assert.equal(state.bottom.summary, null);
});

test('missing 1.5-cycle publication never borrows box intervals', () => {
  const input = setup(); active(input); input.context.rule = 'cycles_1_5';
  const state = Decision.build(input);
  assert.equal(state.rule, 'cycles_1_5');
  assert.equal(state.top.status, 'unavailable');
  assert.equal(state.top.windows.length, 0);
  assert.equal(state.conclusion.status, 'model_pending');
});

test('a valid other-scale window remains explicit when selected scale has no interval', () => {
  const input = setup(); active(input, '2026-11-24', '2026-12-04', '12-24m');
  const state = Decision.build(input);
  assert.equal(state.top.windows.length, 0);
  assert.equal(state.top.otherWindows.length, 1);
  assert.equal(state.top.status, 'other_scale');
  assert.equal(state.conclusion.status, 'top_watch');
  assert.match(state.top.detail, /12–24个月/);
});

test('historical model date mismatch is rejected instead of using current analysis', () => {
  const input = setup(); input.context.asof = '2026-11-16';
  const state = Decision.build(input);
  assert.equal(state.conclusion.status, 'unavailable');
  assert.equal(state.bottom.score, null);
  assert.equal(state.top.windows.length, 0);
});

test('building the display state does not mutate published inputs or recalculate a supplied score', () => {
  const input = setup(); input.data.raw.bottom_score = 1;
  const before = JSON.stringify(input);
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 1, 'an explicit 0–100 score of one is not normalized to 100');
  assert.equal(JSON.stringify(input), before);
});

test('a history that declares its own score version stays usable when only the LPPLS model version differs', () => {
  const input = setup(); input.history.model_version = 'published-v0';
  assert.equal(Decision.build(input).bottom.score, null);
  input.history.score_version = 'bottom_v2';
  const state = Decision.build(input);
  assert.equal(state.bottom.score, 62.5);
  assert.equal(state.bottom.versionMismatch, false);
  input.data.raw.score_version = 'bottom_v1';
  assert.equal(Decision.build(input).bottom.score, null);
});
