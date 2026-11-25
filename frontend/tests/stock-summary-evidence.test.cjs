'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const TopClusters = require('../app/top-clusters.js');
const RuleLabels = require('../app/rule-labels.js');

// Exercise the actual page renderer, without mounting network/session code.
const html = fs.readFileSync(path.join(__dirname, '..', 'stock.html'), 'utf8');
const inline = html.slice(html.lastIndexOf('  <script>') + '  <script>'.length);
const context = vm.createContext({ CPTopClusters: TopClusters, RuleLabels });
const mountCall = inline.search(/\bStockView\.mount\s*\(/);
vm.runInContext(inline.slice(0, mountCall) + '\nglobalThis.renderSummary = summaryHtml; globalThis.summaryStates = summaryStates;', context);
const render = data => context.renderSummary(data);
const summaryStates = data => context.summaryStates(data);

for (const evidence of [undefined, 'none', 'dev_only', 'dev_failed', 'fail_i_iii']) {
  test(`summary with ${evidence || 'missing'} evidence cannot invent zero fits or no-risk state`, () => {
    const result = render({ top: { signal_status: 'signal', lppls_confidence: { evidence },
      window: { start: '2026-12-01', end: '2026-12-10', evidence },
      indicators: { '1-3m': { n_qualified_standard: 8, evidence } } } });
    assert.match(result, /尚无可显示结果/);
    assert.match(result, /不能解释为没有风险/);
    assert.doesNotMatch(result, /不在风险窗口|0 \/ 6|2026-12-01|2026-12-10|研究候选/);
    assert.match(result, /6–12 月主簇<\/small><b class="">未计算<\/b><span class="sub">这个尺度未计算/);
    assert.doesNotMatch(result, /合格拟合的尺度/);
  });
}

test('not computed and unknown signal statuses are not presented as a negative model finding', () => {
  for (const signal_status of [undefined, 'not_computed', 'unknown']) {
    const result = render({ top: { signal_status, lppls_confidence: { evidence: 'research_candidate' } } });
    assert.match(result, /尚无可显示结果/);
    assert.doesNotMatch(result, /不在风险窗口|没有合格拟合/);
  }
});

test('a completed no-qualified-fit result lists computed scales without implying low risk', () => {
  const result = render({ top: { signal_status: 'no_qualified_fit', lppls_confidence: { evidence: 'research_candidate' },
    indicators: { '1-3m': { n_qualified_standard: 0 }, '3-6m': { n_qualified_standard: 0 } } } });
  assert.match(result, /分析已完成 · 本次未形成符合规则的顶部区间/);
  assert.match(result, /已计算尺度：1–3 月、3–6 月；未计算尺度：2–4 周、6–12 月、12–24 月、2–6 年/);
  assert.match(result, /6–12 月主簇/);
  assert.doesNotMatch(result, /合格拟合的尺度|0 \/ 2/);
  assert.match(result, /这表示当前方法未给出有效区间，不能解释为风险较低。/);
  assert.doesNotMatch(result, /尚无可显示结果|不在风险窗口|不代表不会下跌/);
});

test('the computed-scale note derives its list from published indicators and confidence values', () => {
  const result = render({ top: {
    signal_status: 'no_qualified_fit',
    lppls_confidence: {
      evidence: 'dev',
      '6-12m': 0,
      '12-24m': 0,
      scale_evidence: Object.fromEntries(
        ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'].map(scale => [scale, 'dev']),
      ),
    },
    indicators: {
      '2-4w': { signal_status: 'not_computed' },
      '1-3m': { signal_status: 'not_computed' },
      '3-6m': { signal_status: 'not_computed' },
      '6-12m': { signal_status: 'no_qualified_fit', n_qualified_standard: 0 },
      '12-24m': { signal_status: 'no_qualified_fit', n_qualified_standard: 0 },
      '2-6y': { signal_status: 'not_computed' },
    },
  } });
  assert.match(result, /当前只算了 6–12 月、12–24 月两个尺度/);
});

test('a permitted research interval keeps its dates, evidence and uncalibrated wording', () => {
  const result = render({ top: { signal_status: 'signal', lppls_confidence: { evidence: 'research_candidate' },
    window: { start: '2026-12-01', end: '2026-12-10', evidence: 'research_candidate' },
    scale_windows: [{ scale: '6-12m', q20_date: '2026-12-01', q80_date: '2026-12-10' }],
    indicators: { '1-3m': { n_qualified_standard: 3 } } } });
  assert.match(result, /2026-12-01 – 2026-12-10/);
  assert.match(result, /未校准，仅供参考/);
  assert.doesNotMatch(result, /合格拟合的尺度|1 \/ 1/);
  assert.match(result, /研究候选/);
});

test('visible per-scale clusters drive the escape pill, summary, tiles, and watchlist status', () => {
  const data = {
    top: {
      signal_status: 'signal',
      lppls_confidence: {
        evidence: 'dev_only',
        scale_evidence: { '6-12m': 'dev', '12-24m': 'dev' },
      },
      scale_clusters: {
        '6-12m': [{
          rank: 'main',
          share: 1,
          n: 5,
          n_scale: 5,
          q20_date: '2026-12-28',
          q80_date: '2027-01-11',
        }],
        '12-24m': [],
      },
    },
  };
  const result = render(data);
  const labels = summaryStates(data);

  assert.equal(labels.topState[0], 'hot');
  assert.equal(labels.topState[1], '有顶部聚类区间');
  assert.match(result, /6–12 月主簇 2026-12-28 – 2027-01-11（占该尺度合格拟合 100%）/);
  assert.match(result, /12–24 月 这个尺度未计算/);
  assert.match(result, /区间不是顶部日期，未校准，仅供参考/);
  assert.match(result, /<b class="range-value">2026-12-28 – 2027-01-11<\/b><span class="sub">占 100%<\/span>/);
  assert.match(html, /\.tile\.range-tile b[^}]*white-space:\s*nowrap/);
  assert.match(html, /\.tile\.range-tile b[^}]*font-size:\s*10px/);
});

test('all shown scales computed empty produce an explicit completed-empty state', () => {
  const data = {
    top: {
      signal_status: 'signal',
      lppls_confidence: {
        evidence: 'dev_only',
        scale_evidence: { '6-12m': 'dev', '12-24m': 'dev' },
      },
      scale_clusters: { '6-12m': [], '12-24m': [] },
    },
  };
  const result = render(data);

  assert.equal(summaryStates(data).topState[1], '分析已完成 · 本次未形成顶部聚类区间');
  assert.match(result, /分析已完成 · 本次未形成顶部聚类区间/);
});
