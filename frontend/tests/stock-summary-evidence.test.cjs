'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise the actual page renderer, without mounting network/session code.
const html = fs.readFileSync(path.join(__dirname, '..', 'stock.html'), 'utf8');
const inline = html.slice(html.lastIndexOf('  <script>') + '  <script>'.length);
const context = vm.createContext({});
vm.runInContext(inline.slice(0, inline.indexOf('    StockView.mount')) + '\nglobalThis.renderSummary = summaryHtml;', context);
const render = data => context.renderSummary(data);

for (const evidence of [undefined, 'none', 'dev_only', 'dev_failed', 'fail_i_iii']) {
  test(`summary with ${evidence || 'missing'} evidence cannot invent zero fits or no-risk state`, () => {
    const result = render({ top: { signal_status: 'signal', lppls_confidence: { evidence },
      window: { start: '2026-12-01', end: '2026-12-10', evidence },
      indicators: { '1-3m': { n_qualified_standard: 8, evidence } } } });
    assert.match(result, /尚无可显示结果/);
    assert.match(result, /不能解释为没有风险/);
    assert.doesNotMatch(result, /不在风险窗口|0 \/ 6|2026-12-01|2026-12-10|研究候选/);
    assert.match(result, /合格拟合的尺度<\/small><b class="">—/);
  });
}

test('not computed and unknown signal statuses are not presented as a negative model finding', () => {
  for (const signal_status of [undefined, 'not_computed', 'unknown']) {
    const result = render({ top: { signal_status, lppls_confidence: { evidence: 'research_candidate' } } });
    assert.match(result, /尚无可显示结果/);
    assert.doesNotMatch(result, /不在风险窗口|没有合格拟合/);
  }
});

test('a verified no-qualified-fit result remains distinct from missing evidence', () => {
  const result = render({ top: { signal_status: 'no_qualified_fit', lppls_confidence: { evidence: 'research_candidate' },
    indicators: { '1-3m': { n_qualified_standard: 0 }, '3-6m': { n_qualified_standard: 0 } } } });
  assert.match(result, /没有合格拟合/);
  assert.match(result, /0 \/ 2/);
  assert.match(result, /不代表不会下跌/);
  assert.doesNotMatch(result, /尚无可显示结果|不在风险窗口/);
});

test('a permitted research interval keeps its dates, evidence and uncalibrated wording', () => {
  const result = render({ top: { signal_status: 'signal', lppls_confidence: { evidence: 'research_candidate' },
    window: { start: '2026-12-01', end: '2026-12-10', evidence: 'research_candidate' },
    indicators: { '1-3m': { n_qualified_standard: 3 } } } });
  assert.match(result, /2026-12-01 – 2026-12-10/);
  assert.match(result, /未校准，仅供参考/);
  assert.match(result, /1 \/ 1/);
  assert.match(result, /研究候选/);
});
