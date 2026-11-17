'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app/bench-view.js'), 'utf8');
const hidden = new Set(['none', 'fail', 'dev_only', 'dev_failed']);
const context = {
  window: {
    LPPL: {
      ev(code, levels) {
        const normalized = code || 'none';
        return {
          code: normalized,
          label: (levels && levels[normalized]) || normalized,
          show: !hidden.has(normalized) && !/^fail/i.test(normalized),
        };
      },
    },
  },
};
vm.runInNewContext(source, context);
const render = context.window.BacktestBenchView.render;

test('bench table renders visible validation metrics and descriptive evidence context', () => {
  const html = render([
    { split: 'test', status: 'descriptive', n: 12, events: 12, hit: 0.5, false_alarm: 0.2, brier: '0.18' },
  ], {});
  assert.match(html, /n=12/);
  assert.match(html, /50%/);
  assert.match(html, /20%/);
  assert.match(html, /历史分位，不是预测/);
});

test('bench table hides all metrics for none, fail, and development-only evidence', () => {
  const html = render(
    ['none', 'fail_custom', 'dev_only', 'dev_failed'].map((status) => ({
      split: 'test',
      status,
      events: 12,
      hit: 0.5,
      false_alarm: 0.2,
      brier: '0.18',
      note: '隐藏详情 99',
    })),
    {},
  );
  const rows = [...html.matchAll(/<tr>(.*?)<\/tr>/g)].slice(1).map((match) => match[1]);
  assert.equal(rows.length, 4);
  rows.forEach((row) => {
    const metrics = [...row.matchAll(/<td>(.*?)<\/td>/g)].map((match) => match[1]).slice(1, 5);
    assert.deepEqual(metrics, ['—', '—', '—', '—']);
    assert.doesNotMatch(row, /12|50%|20%|0\.18|99/);
  });
});
