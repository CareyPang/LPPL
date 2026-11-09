'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Analysis = require('../app/stock-analysis.js');

function record(overrides = {}) {
  return { symbol: 'sh600519', asof: '2026-11-06', model_version: 'research-1.5',
    analysis: { schema: 'stock_analysis_v1', status: 'research_candidate', evidence: 'research_candidate',
      as_of: '2026-11-06', model_version: 'research-1.5', minimum_full_cycles: 1.5,
      calendar: { status: 'weekday_estimate', dates: Analysis.weekdays('2026-11-06', '2026-12-31') },
      windows: [{ id: 'main', start: '2026-11-16', end: '2026-11-20', width_sessions: 5,
        lead_sessions: 5, evidence: 'research_candidate', claim_kind: 'new', tier: 'formal_research_window' }] }, ...overrides };
}

test('real research intervals preserve exact dates and never assert five trading days on an estimated calendar', () => {
  const view = Analysis.normalize(record(), { asof: '2026-11-06' });
  assert.equal(view.status, 'research_candidate');
  assert.equal(view.fullCycles, 1.5);
  assert.equal(view.windows[0].start, '2026-11-16');
  assert.equal(view.windows[0].end, '2026-11-20');
  assert.equal(view.windows[0].geometryQualified, false);
  assert.equal(view.windows[0].tier, 'early_observation');
  assert.match(view.calendarLabel, /节假日尚未核验/);
  assert.ok(view.futureDates.includes('2026-11-20'));
});

test('verified session geometry is measured from the next actionable session with inclusive width', () => {
  const value = record();
  value.analysis.calendar = { status: 'exchange_verified', version: 'fixture-calendar',
    coverage_start: '2026-01-01', coverage_end: '2026-12-31',
    dates: ['2026-11-06', ...Analysis.weekdays('2026-11-06', '2026-12-31')] };
  const window = Analysis.normalize(value).windows[0];
  assert.equal(window.width, 5);
  assert.equal(window.lead, 5);
  assert.equal(window.geometryQualified, true);
  value.analysis.calendar.dates = value.analysis.calendar.dates.filter(date => date !== '2026-11-16');
  assert.equal(Analysis.normalize(value).windows[0].geometryQualified, false, 'incomplete endpoint calendar cannot certify lead');
});

test('estimated calendar uses the same outward endpoint arithmetic, without promoting single-scale observations', () => {
  const value = record();
  value.analysis.calendar.dates.unshift('2026-11-06');
  value.analysis.windows[0] = { start: '2026-12-11', end: '2026-12-24', width_sessions: 9, lead_sessions: 25,
    evidence: 'research_candidate', tier: 'early_observation', reason: '仅单尺度研究观察' };
  const window = Analysis.normalize(value).windows[0];
  assert.equal(window.width, 10);
  assert.equal(window.lead, 24);
  assert.equal(window.calendarVerified, false);
  assert.equal(window.geometryQualified, false);
  value.analysis.calendar.status = 'exchange_verified';
  value.analysis.calendar.version = 'fixture-only';
  value.analysis.calendar.coverage_start = '2026-01-01';
  value.analysis.calendar.coverage_end = '2026-12-31';
  assert.equal(Analysis.normalize(value).windows[0].geometryQualified, false, 'time geometry cannot override the backend observation tier');
});

test('an official 2026 calendar does not certify 2027 windows or override a per-window estimated calendar', () => {
  const value = record();
  value.analysis.calendar = { status: 'exchange_verified', version: 'fixture-2026',
    coverage_start: '2026-01-01', coverage_end: '2026-12-31',
    dates: ['2026-11-06', ...Analysis.weekdays('2026-11-06', '2027-01-15')] };
  value.analysis.windows[0].end = '2027-01-05';
  assert.equal(Analysis.normalize(value).windows[0].calendarVerified, false, 'appended dates do not extend verified coverage');
  value.analysis.windows[0].end = '2026-11-20';
  value.analysis.windows[0].calendar = { ...value.analysis.calendar, status: 'weekday_estimate' };
  assert.equal(Analysis.normalize(value).windows[0].calendarVerified, false, 'local calendar status takes precedence over global status');
  delete value.analysis.windows[0].calendar;
  delete value.analysis.calendar.coverage_end;
  assert.equal(Analysis.normalize(value).windows[0].calendarVerified, false, 'missing coverage cannot be called a verified exchange calendar');
});

test('calendar verification cannot upgrade a single-scale or search-boundary candidate to a formal window', () => {
  const value = record();
  value.analysis.calendar = { status: 'exchange_verified', version: 'fixture-2026',
    coverage_start: '2026-01-01', coverage_end: '2026-12-31',
    dates: ['2026-11-06', ...Analysis.weekdays('2026-11-06', '2026-12-31')] };
  value.analysis.windows[0].cross_scale = false;
  assert.equal(Analysis.normalize(value).windows[0].geometryQualified, false);
  value.analysis.windows[0].cross_scale = true;
  value.analysis.windows[0].search_boundary_members = [130, 170];
  const window = Analysis.normalize(value).windows[0];
  assert.equal(window.geometryQualified, false);
  assert.match(window.boundaryNote, /触及搜索范围边界/);
});

test('old failure and none evidence never becomes a numeric preview by wrapping it in analysis', () => {
  for (const evidence of ['none', 'fail', 'fail_cal', 'dev_only', 'dev_failed']) {
    for (const scope of ['record', 'top', 'analysis', 'window']) {
      const value = record();
      if (scope === 'record') value.evidence = evidence;
      if (scope === 'top') value.top = { evidence_override: evidence };
      if (scope === 'analysis') value.analysis.evidence = evidence;
      if (scope === 'window') value.analysis.windows[0].evidence = evidence;
      const view = Analysis.normalize(value);
      assert.equal(view.windows.length, 0, scope + '/' + evidence);
      assert.equal(view.status, 'withheld');
    }
  }
});

test('demo, retrospective replay and mismatched as-of cannot become a current forecast band', () => {
  for (const extra of [{ demo: true }, { model_computed: false }, { mode: 'history' },
    { claim_origin: 'HYPOTHETICAL_REPLAY_CLAIM_NOT_ORIGINAL' }, { asof: '2026-11-05' }]) {
    assert.equal(Analysis.normalize(record(extra)).windows.length, 0);
  }
  const value = record();
  value.analysis.windows.push({ start: '2026-02-30', end: '2026-11-20', evidence: 'research_candidate' });
  value.analysis.windows.push({ start: '2026-11-05', end: '2026-11-20', evidence: 'research_candidate' });
  assert.equal(Analysis.normalize(value).windows.length, 1);
});

test('wide candidates remain whole observations and an empty successful run is different from failure', () => {
  const value = record();
  value.analysis.windows[0].end = '2026-12-31';
  value.analysis.windows[0].width_sessions = 34;
  const window = Analysis.normalize(value).windows[0];
  assert.equal(window.end, '2026-12-31');
  assert.equal(window.width, 34);
  assert.equal(window.geometryQualified, false);
  value.analysis.status = 'no_signal';
  assert.equal(Analysis.normalize(value).status, 'no_signal');
  assert.equal(Analysis.normalize(value).windows.length, 0);
  value.analysis.status = 'failed';
  assert.equal(Analysis.normalize(value).status, 'failed');
  assert.equal(Analysis.normalize(null, null, 'failed').status, 'failed');
  assert.equal(Analysis.normalize(null).status, 'pending');
});

test('old cached intervals keep dates and are explicitly expired rather than recycled as a new alert', () => {
  const view = Analysis.normalize(record(), { asof: '2026-11-23' });
  assert.equal(view.stale, true);
  assert.equal(view.windows[0].expired, true);
  assert.equal(view.windows[0].start, '2026-11-16');
  assert.match(view.windows[0].label, /已过期/);
});

test('re-exporting saved fits is a presentation revision rather than a newly issued model candidate', () => {
  const value = record({ execution_origin: 'FIXED_FIT_EXPORT_REVISION' });
  assert.match(Analysis.normalize(value).windows[0].claimKind, /展示修订.*未重新拟合/);
  delete value.execution_origin;
  value.analysis.windows[0].claim_kind_scope = 'fixed_fit_export_revision_not_new_forecast';
  assert.match(Analysis.normalize(value).windows[0].claimKind, /展示修订/);
});

test('raw chart prices and adjusted model input are disclosed as separate bases', () => {
  const value = record({ market_adjustment: 'none', model_adjustment: 'hfq' });
  assert.match(Analysis.normalize(value).priceBasis, /行情 未复权.*模型 后复权.*不叠加/);
});

test('visible copy distinguishes candidate, no signal and failure without HTML injection', () => {
  const doc = { createElement(tag) { return { tag, children: [], attrs: {},
    appendChild(node) { this.children.push(node); }, setAttribute(key, value) { this.attrs[key] = value; } }; } };
  const container = { ownerDocument: doc, setAttribute() {}, replaceChildren(...nodes) { this.nodes = nodes; } };
  const text = node => [node.textContent || '', ...(node.children || node.nodes || []).map(text)].join(' ');
  const value = record({ model_version: '<script>fixture</script>' });
  Analysis.render(container, Analysis.normalize(value));
  assert.match(text(container), /不保证命中、提前5个交易日或随后跌幅/);
  assert.match(text(container), /估算观测日/);
  value.analysis.status = 'no_signal';
  Analysis.render(container, Analysis.normalize(value));
  assert.match(text(container), /没有合格区间不代表不会见顶/);
  assert.doesNotMatch(text(container), /2026-11-16/);
  Analysis.render(container, Analysis.normalize(null, null, 'failed'));
  assert.match(text(container), /未产生有效分析结论/);
});
