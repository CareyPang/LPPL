const test = require('node:test');
const assert = require('node:assert/strict');
const { buildView, renderView, stageOf, mount } = require('../app/validation-evidence-editorial.js');
const record = validation => ({ J: { validation }, sym: { label: '上证指数' }, top: { lppls_confidence: { evidence: 'dev_only' } }, asof: '2007-10-12', latest: false });
test('calibration and final test are mapped by stage, never by row order or metric values', () => {
  const v = buildView(record([{ split: '最终测试 2022–2025', status: 'fail' }, { split: '开发段', status: 'dev' }, { split: '校准段', status: 'fail_i' }]));
  assert.equal(v.stages[0].rows[0].status, 'fail_i');
  assert.equal(v.stages[1].rows[0].status, 'fail');
  assert.equal(v.stages[0].rows[0].source, 'validation[2]');
  assert.equal(stageOf({ split: 'cal' }), 'cal');
  assert.equal(stageOf({ split: 'test' }), 'test');
});
test('failed, pending, unknown and development-only evidence cannot leak raw numeric metrics or notes', () => {
  for (const status of ['fail', 'fail_future', 'dev_only', 'dev_failed', 'none', 'unknown', 'pending_cal', 'descriptive']) {
    const v = buildView(record([{ split: '校准段', status, events: 98765, hit: .9123, false_alarm: .8765, brier: 'SECRET 54321', note: 'SECRET 67890' }]));
    const html = renderView(v);
    for (const secret of ['98765', '91%', '88%', '54321', '67890', 'SECRET']) assert.ok(!html.includes(secret), status + ': ' + secret);
  }
});
test('allowed metrics preserve real zeroes and descriptive rows require an explicit sample count', () => {
  const v = buildView(record([{ split: '测试', status: 'test', events: 0, hit: 0, false_alarm: 0, brier: 0 }, { split: '校准', status: 'descriptive', n: 23, hit: .5 }]));
  assert.deepEqual(v.stages[1].rows[0].metrics, [['事件样本','n=0'], ['提前报警比例','0%'], ['报警后未见顶比例','0%'], ['Brier 记录','0']]);
  assert.match(renderView(v), /n=23 · 历史分位，不是预测/);
});
test('historical snapshot validation is explicitly retrospective and missing stages stay missing', () => {
  const html = renderView(buildView(record([])));
  assert.match(html, /不属于当时已知信息/);
  assert.match(html, /不是这一条结论的单独检验成绩/);
  assert.equal((html.match(/当前快照没有提供这一阶段/g) || []).length, 2);
  assert.ok(!html.includes('未通过'));
});
test('record text and conclusion are escaped before insertion', () => {
  const r = record([{ split: '校准 <img src=x>', status: 'cal', note: '<script>bad()</script>' }]);
  r.J.model_version = '<svg onload=x>';
  const html = renderView(buildView(r, '<b>signal</b>'));
  assert.ok(!html.includes('<script>')); assert.ok(!html.includes('<svg'));
  assert.match(html, /&lt;b&gt;signal/);
});
test('snapshot reset closes evidence and blocks stale reopen until a new snapshot is supplied', () => {
  const nodes = new Map();
  function get(id) {
    if (!nodes.has(id)) nodes.set(id, { disabled: true, innerHTML: '', open: false, handlers: {}, addEventListener(e, fn) { this.handlers[e] = fn; }, showModal() { this.open = true; }, close() { this.open = false; }, focus() {}, click() { this.handlers.click?.({ target: this }); }, scrollIntoView() {} });
    return nodes.get(id);
  }
  const api = mount({ getElementById: get });
  api.update(record([]), 'old'); get('conclusion-open').click();
  assert.equal(get('validation-evidence').open, true);
  api.reset(); assert.equal(get('validation-evidence').open, false); assert.equal(get('conclusion-open').disabled, true);
  get('conclusion-open').click(); assert.equal(get('validation-evidence').open, false);
  api.update(record([]), 'new'); get('conclusion-open').click();
  assert.match(get('validation-content').innerHTML, /new/);
  assert.ok(!get('validation-content').innerHTML.includes('old'));
});
