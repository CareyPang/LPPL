const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const market = fs.readFileSync(path.join(root, 'market.html'), 'utf8');
const nav = fs.readFileSync(path.join(root, 'app/od-nav.js'), 'utf8');
const adapter = fs.readFileSync(path.join(root, 'app/lppl-data.js'), 'utf8');

test('growth monitor is a market section linked from the existing nav', () => {
  const section = market.match(/<section class="sec wide" id="s-growth"[\s\S]*?<\/section>/);
  const renderer = market.match(/function renderGrowth\(data\) \{[\s\S]*?\n  \}\n\n  function renderAll/);
  assert.ok(section);
  assert.ok(renderer);
  assert.match(section[0], /成长股监控/);
  assert.doesNotMatch(section[0], /class="ev">descriptive/);
  assert.match(renderer[0], /核心条件满足/);
  assert.match(renderer[0], /确认项：/);
  assert.match(renderer[0], /pending_definition: '暂无数据'/);
  assert.match(renderer[0], /missing: '缺数据'/);
  assert.match(renderer[0], /partial: '数据不全'/);
  assert.doesNotMatch(renderer[0], /不是预测|不构成买卖建议/);
  assert.match(renderer[0], /近两周净申购：/);
  assert.match(renderer[0], /week\.week_start/);
  assert.match(renderer[0], /item\.note === status/);
  assert.match(renderer[0], /最近 \$\{observations\.length\} 个观测：/);
  assert.match(renderer[0], /row\.date.*Number\(row\.value\)/);
  assert.doesNotMatch(renderer[0], /可用观测 n=|历史分位/);
  assert.match(renderer[0], /数据日期：/);
  assert.match(renderer[0], /来源：/);
  assert.match(renderer[0], /规则：/);
  assert.match(renderer[0], /缺失原因：/);
  assert.doesNotMatch(`${section[0]}\n${renderer[0]}`, /允许试探|加仓|买入|卖出|入场/);
  assert.match(nav, /\{ t: '宏观', h: '#s-val', ids: \['s-val', 's-macro', 's-growth'\] \}/);
  assert.match(nav, /SUB_MAX = 7/);
  assert.match(nav, /l \+ w - s\.clientWidth \+ 24/);
  assert.match(market, /#s-growth \.growth-card-head \{ flex-wrap: wrap/);
  assert.match(market, /#s-growth \.growth-state \{ flex: 0 1 auto/);
});

test('growth data is loaded only through the LPPL adapter', async () => {
  let requested = '';
  const payload = { schema: 1, asof: '2026-11-16' };
  const context = {
    AbortController,
    clearTimeout,
    fetch: async (url) => {
      requested = url;
      return { ok: true, json: async () => payload };
    },
    Promise,
    setTimeout,
    URL,
    window: { LPPL_DATA_BASE: 'lab/mock/data/' },
  };

  vm.runInNewContext(adapter, context);
  assert.equal(typeof context.window.LPPL.market, 'function');
  const result = await context.window.LPPL.growthMonitor();

  assert.equal(requested, 'lab/mock/data/growth/growth_latest.json');
  assert.equal(result.asof, '2026-11-16');
});
