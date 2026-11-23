const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const BottomAction = require('../app/bottom-action.js');
function adapter(){
  const requests=[];
  const ctx={window:{},AbortController,setTimeout,clearTimeout,URLSearchParams,console,
    fetch:async(url,opts)=>{requests.push({url,method:opts?.method||'GET'});return {ok:true,json:async()=>({symbol:'KR_KOSPI',asof:'2026-11-20',price_history:{dates:['2026-11-20'],close:[3000]}})}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../app/lppl-data.js'),'utf8'),ctx);
  return {api:ctx.window.LPPL,requests};
}
test('international catalog separates markets, index identity, stocks and currencies',()=>{
  const {api}=adapter();
  assert.equal(api.SYMS.filter(s=>s.market==='cn').length,7);
  assert.equal(api.SYMS.filter(s=>s.market==='us').length,4);
  assert.equal(api.SYMS.filter(s=>s.market==='jp').length,1);
  assert.equal(api.SYMS.filter(s=>s.market==='kr').length,2);
  assert.equal(api.resolve('kospi').sym,'KR_KOSPI');
  assert.equal(api.resolve('^N225').currency,'JPY');
  assert.equal(api.resolve('MRVL'),null);
  assert.equal(api.GLOBAL_SYMS.find(s=>s.sym==='US_MRVL').kind,'stock');
  assert.throws(()=>api.stock.latest('US_SPX'),/指数/);
  assert.throws(()=>api.stock.history('US_NDX'),/指数/);
});
test('international current and exact archives use static GET only, never A-share replay dispatch',async()=>{
  const {api,requests}=adapter();
  await api.load('KOSPI');
  await api.load('KOSPI','2026-11-20');
  await api.history('KR_KOSPI');
  await api.stock.latest('MRVL');
  assert.deepEqual(requests.map(x=>x.url),['lab/mock/data/global/KR_KOSPI_latest.json','lab/mock/data/global/KR_KOSPI_2026-11-20.json','lab/mock/data/global/KR_KOSPI_history.json','lab/mock/data/global/US_MRVL_latest.json']);
  assert.ok(requests.every(x=>x.method==='GET'));
  assert.throws(()=>api.global.result('../MRVL','2026-11-20'),/身份/);
});
test('MRVL and invalid stocks never inherit CSI300 background or A-share position advice',()=>{
  for(const code of ['MRVL','US_MRVL','KR_KOSPI','garbage','']){
    assert.equal(BottomAction.boardIndexForStock(code).sym,null);
    const bars=Array.from({length:80},(_,i)=>({date:'2026-01-'+i,close:100-i/10}));
    assert.equal(BottomAction.evaluateStockSeries(bars,{code}).action,null);
  }
  assert.equal(BottomAction.boardIndexForStock('600519').sym,'sh000001');
});
