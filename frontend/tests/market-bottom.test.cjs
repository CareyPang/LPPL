const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'market.html'), 'utf8');
const start = html.indexOf('  function renderBottom(data) {');
const end = html.indexOf('\n  function renderAbnormal(data) {', start);
const renderSource = html.slice(start, end);

function render(data) {
  const elements = {
    'src-bottom': { textContent: '' },
    'bottom-body': { innerHTML: '' },
  };
  const context = vm.createContext({
    $: (id) => elements[id],
    esc: (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[ch]),
  });
  vm.runInContext(
    `const bottomBody = $('bottom-body');\n${renderSource}\nglobalThis.renderBottom = renderBottom;`,
    context,
  );
  context.renderBottom(data);
  return elements;
}

function panel(eventDate) {
  return {
    current: {
      erp: 0.05,
      erp_pct: 0.92,
      pbn_ratio: 0.12,
      pbn_pct: 0.91,
      signal: true,
      last_event_date: eventDate,
    },
    events: [{ date: eventDate, ret_250: 0.1, post_min: -0.05 }],
    summary: { n_events: 1, n_up_250: 1, n_with_250d: 1 },
    baseline: { share_up_250: 0.54 },
    notes: ['历史回测样本'],
  };
}

test('bottom signal renders separate HS300 and A500 panels and sample counts', () => {
  const elements = render({
    asof: '2026-11-13',
    current: panel('2024-01-19').current,
    events: panel('2024-01-19').events,
    summary: panel('2024-01-19').summary,
    baseline: panel('2024-01-19').baseline,
    notes: ['HS300 note'],
    sources: { ebs: 'AkShare' },
    a500: { ...panel('2024-06-25'), asof: '2026-11-12' },
  });

  assert.match(elements['bottom-body'].innerHTML, /沪深300/);
  assert.match(elements['bottom-body'].innerHTML, /中证A500/);
  assert.match(elements['bottom-body'].innerHTML, /2024-01-19/);
  assert.match(elements['bottom-body'].innerHTML, /2024-06-25/);
  assert.match(elements['bottom-body'].innerHTML, /截至 2026-11-13/);
  assert.match(
    elements['bottom-body'].innerHTML,
    /截至 2026-11-13 · 样本 n=1/,
  );
  assert.match(
    elements['bottom-body'].innerHTML,
    /截至 2026-11-12，滞后于沪深300（截至 2026-11-13） · 样本 n=1/,
  );
  assert.match(elements['bottom-body'].innerHTML, /历史分位，不是预测。/);
  assert.equal(elements['src-bottom'].textContent, 'AkShare');
});

test('bottom signal shows an unloaded A500 panel when data is absent', () => {
  const elements = render({
    asof: '2026-11-13',
    ...panel('2024-01-19'),
    sources: { ebs: 'AkShare' },
  });

  assert.match(elements['bottom-body'].innerHTML, /沪深300/);
  assert.match(elements['bottom-body'].innerHTML, /中证A500 数据未加载。/);
  assert.equal(elements['src-bottom'].textContent, 'AkShare');
});
