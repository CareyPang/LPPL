const test = require('node:test');
const assert = require('node:assert/strict');
const Reader = require('../app/chart-readonly-data.js');
const context = {code:'sh600519',stockCode:'600519',assetType:'stock',market:'cn'};
const archive = {symbol:'600519',asof:'2026-11-20',adjust:'hfq',price_history:{
  dates:['2026-11-19','2026-11-20','2026-11-23'],close:[10,11,99],
  open:[9,10,98],high:[11,12,100],low:[8,9,97],volume:[100,200,300],source:'archived-source',volume_unit:'股'}};
test('failed live quotes can use identity-checked published archive without future rows',()=>{
  const market=Reader.stockMarketFromArchive(archive,context);
  assert.equal(market.stale,true); assert.equal(market.asof,'2026-11-20');
  assert.equal(market.adjustment,'hfq');assert.equal(market.source,'archived-source');
  assert.deepEqual(market.price.map(x=>x.close),[10,11]);
  assert.deepEqual(market.price.map(x=>x.volume),[100,200]);
});
test('archive fallback rejects another asset, absent identity, international reuse and empty prices',()=>{
  assert.throws(()=>Reader.stockMarketFromArchive({...archive,symbol:'000001'},context));
  assert.throws(()=>Reader.stockMarketFromArchive({...archive,symbol:undefined},context));
  assert.throws(()=>Reader.stockMarketFromArchive(archive,{...context,market:'us'}));
  assert.throws(()=>Reader.stockMarketFromArchive({...archive,price_history:{}},context));
});
test('close-only archive keeps unknown OHLC and volume null instead of fabricating candles',()=>{
  const market=Reader.stockMarketFromArchive({...archive,price_history:{dates:['2026-11-20'],close:[11]}},context);
  assert.deepEqual(market.price[0],{date:'2026-11-20',close:11,open:null,high:null,low:null,volume:null});
});
