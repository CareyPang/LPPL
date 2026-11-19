'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { view } = require('../app/market-trend-alerts.js');
const day = '2026-11-18';
const now = Date.parse('2026-11-19T04:00:00+08:00');
const alert = {
  kind: 'reversal', level: 'watch', active: true, title: '下跌可能告一段落',
  message: '更多股票开始回升。', reasons: ['越来越多的股票重新站稳。'],
  next_check: '回落时能否守住前低。', evidence: 'experimental',
  trigger_date: day, update_date: day,
};
function snapshot(fields = {}) {
  return { asof: day, latest: { date: day }, trend_alerts: {
    schema: 'breadth-alerts.v1', asof: day, phase: { asof: '2026-11-17', label: '持续下跌' },
    state: 'watch', evidence: 'experimental', alerts: [{ ...alert }], ...fields,
  } };
}

test('surfaces a possible reversal at first observation and a fresh strengthening update', () => {
  const initial = view(snapshot(), day, now);
  assert.match(initial.headline, /下跌可能告一段落（开始留意）/);
  assert.match(initial.phase, /2026-11-17/);
  const enhanced = { ...alert, level: 'strengthening', trigger_date: '2026-11-16' };
  assert.match(view(snapshot({ alerts: [enhanced] }), day, now).headline, /迹象增强/);
});

test('continued or invalidated observations stay accessible without a new headline', () => {
  const held = { ...alert, trigger_date: '2026-11-16', update_date: '2026-11-16' };
  const withdrawn = { ...alert, level: 'invalidated', active: false };
  const result = view(snapshot({ alerts: [held, withdrawn] }), day, now);
  assert.equal(result.alerts.length, 2);
  assert.equal(result.headline, '');
  const mixed = view(snapshot({ alerts: [withdrawn, held, alert] }), day, now);
  assert.deepEqual(mixed.alerts.map(row => row.level), ['watch', 'watch', 'invalidated']);
  assert.equal(mixed.alerts[0].update_date, day);
  assert.equal(mixed.headline, alert.title + '（开始留意）');
});

test('past snapshots, research replays and unverified market dates do not create live headlines', () => {
  const replay = { evidence: 'research_replay', alerts: [{ ...alert, evidence: 'research_replay' }] };
  for (const result of [
    view(snapshot(replay), day, now),
    view({ ...snapshot(), stale: true }, day, now),
    view(snapshot(), '2026-11-19', now),
    view(snapshot(), day, Date.parse('2026-11-30T10:00:00+08:00')),
    view(snapshot(), undefined, now),
  ]) {
    assert.equal(result.headline, '');
    assert.equal(result.alerts.length, 1);
  }
  assert.equal(view(snapshot(replay), day, now).context, '历史回放');
});

test('weekends and documented exchange closures are excluded from the daily publishing deadline', () => {
  const monday = Date.parse('2026-11-23T09:30:00+08:00');
  const calendar = { holidays_through: '2026-12-31', closures: ['2026-11-19', '2026-11-20'] };
  assert.ok(view(snapshot(), day, monday, calendar).headline);
  assert.equal(view(snapshot(), day, monday).headline, '');
});

test('missing assessments and incomplete evidence are distinct from evaluated quiet days', () => {
  assert.match(view({}, day, now).notice, /没有附带趋势评估/);
  assert.match(view(snapshot({ state: 'quiet', alerts: [] }), day, now).notice, /没有触发/);
  assert.match(view(snapshot({ state: 'unavailable', alerts: [], reason: '缺少交易日' }), day, now).notice, /缺少交易日/);
  for (const fields of [{ asof: '2026-11-17' }, { evidence: 'none' }, { state: 'quiet' }]) {
    assert.equal(view(snapshot(fields), day, now).alerts.length, 0);
  }
  for (const fields of [{ evidence: 'none' }, { update_date: '2026-11-19' }, { active: false }, { reasons: [] }]) {
    const result = view(snapshot({ alerts: [{ ...alert, ...fields }] }), day, now);
    assert.equal(result.alerts.length, 0);
    assert.match(result.notice, /缺少完整依据/);
  }
});
