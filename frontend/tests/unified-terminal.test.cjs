'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Terminal = require('../app/unified-terminal.js');
const Core = require('../app/chart-page-core.js');
test('later index prices reject a response for another symbol', () => {
  assert.throws(() => Core.assembleIndexData('sh000001', {bars:[], raw:{symbol:'sh000300'}}), /身份/);
});
test('archive navigation sorts exact dates, keeps gaps and stops at boundaries', () => {
  const dates = Terminal.datesFrom({frames:[{asof:'2026-10-09'},{asof:'2026-10-02'},{asof:'2026-10-09'}]}, ['2015-06-12']);
  assert.deepEqual(dates, ['2015-06-12','2026-10-02','2026-10-09']);
  assert.equal(Terminal.neighbour(dates,'2026-10-05',-1),'2026-10-02');
  assert.equal(Terminal.neighbour(dates,'2026-10-09',1),'');
});
test('switching assets retains exact cutoff, scale and return origin', () => {
  const url = Terminal.href({code:'sh000001',assetType:'index',scale:'3-6m',asof:'2026-10-02',from:'home.html'}, {code:'US_NVDA',kind:'stock'});
  const p = new URL(url,'http://local/').searchParams;
  assert.equal(p.get('asof'),'2026-10-02'); assert.equal(p.get('from'),'home.html');
  assert.equal(p.get('scale'),'3-6m'); assert.equal(p.get('kind'),'stock');
});
test('international asset options use display codes while retaining canonical values', () => {
  assert.equal(Terminal.optionLabel(Core, 'JP_N225', '日经225'), '日经225 · N225');
  assert.equal(Terminal.optionLabel(Core, 'KR_SKHYNIX', 'SK 海力士'), 'SK 海力士 · 000660');
  assert.equal(Terminal.optionLabel(Core, 'sh000001', '上证指数'), '上证指数 · sh000001');
});
test('expired intervals never become current alerts, but remain visible at original cutoff', () => {
  const data = {modelStatus:'ok',modelAsOf:'2026-11-20',marketAsOf:'2026-11-20'};
  const bands = [{q20_date:'2026-10-20',q80_date:'2026-11-01'}];
  assert.match(Terminal.summary(data,bands,'').status,/区间已过/);
  assert.match(Terminal.summary(data,bands,'2026-10-02').status,/当时有候选/);
});
test('stale model is labelled for update even if its old interval is still in the future', () => {
  const data = {modelStatus:'ok',modelAsOf:'2026-11-13',marketAsOf:'2026-11-20'};
  const bands = [{q20_date:'2026-11-25',q80_date:'2026-12-01'}];
  assert.match(Terminal.summary(data,bands,'').status,/待更新/);
  assert.match(Terminal.summary({...data,modelStatus:'missing'},bands,'').status,/行情可先查看/);
});
test('near-term clusters are not removed by an invented five-day gate', () => {
  const data = {modelStatus:'ok',modelAsOf:'2026-11-20',marketAsOf:'2026-11-20'};
  assert.match(Terminal.summary(data,[{q20_date:'2026-11-20',q80_date:'2026-11-23'}],'').window,/2026-11-20/);
  assert.equal(Terminal.summary(data,[],'').window,'—');
});
