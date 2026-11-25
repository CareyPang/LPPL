'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Events=require('../app/global-events.js');
const context={code:'US_IXIC',market:'us',timezone:'America/New_York',asof:''};
const item=(patch={})=>({id:'a',hash:'aaa',title:'标题',source:'来源',published_at:'2026-11-20T17:00:00Z',known_at:'2026-11-20T18:00:00Z',url:'https://example.com/news',...patch});
const data=(items,patch={})=>({symbol:'US_IXIC',modelAsOf:'2026-11-20',raw:{research:{market_events:{schema_version:'global_events_v1',symbol:'US_IXIC',model_asof:'2026-11-20',mode:'current',status:'ok',items,...patch}}}});
test('current news after model date stays explicitly separate from model chart markers',()=>{
 const view=Events.model(data([item(),item({known_at:'2026-11-23T10:00:00Z',after_model_asof:false})]),context);
 assert.equal(view.rows.length,2);assert.equal(view.markers.length,1);assert.equal(view.rows[1].afterModel,true);assert.match(view.note,/当前资讯/);
});
test('historical view rejects both known-later and published-later news including same-day after close',()=>{
 const history={...context,asof:'2026-11-20'};
 const view=Events.model(data([item(),item({known_at:'2026-11-20T21:01:00Z'}),item({published_at:'2026-11-20T21:01:00Z'})],{mode:'historical'}),history);
 assert.equal(view.rows.length,1);assert.match(view.note,/排除 2 条/);
 assert.equal(Events.model(data([item()]),history).rows.length,0);
});
test('market cutoff respects US daylight saving and Tokyo local trading time',()=>{
 assert.equal(Events.beforeCutoff('2026-06-26T20:00:00Z','2026-06-26',context),true);
 assert.equal(Events.beforeCutoff('2026-06-26T20:00:01Z','2026-06-26',context),false);
 const jp={market:'jp',timezone:'Asia/Tokyo'};
 assert.equal(Events.beforeCutoff('2026-11-20T06:30:00Z','2026-11-20',jp),true);
 assert.equal(Events.beforeCutoff('2026-11-20T06:30:01Z','2026-11-20',jp),false);
});
test('foreign symbol/cutoff, unsafe URLs and unknown first observation cannot enter timeline',()=>{
 assert.equal(Events.model(data([item()],{symbol:'US_NDX'}),context).rows.length,0);
 assert.equal(Events.model(data([item()],{model_asof:'2026-11-19'}),context).rows.length,0);
 const view=Events.model(data([item({url:'javascript:alert(1)'}),item({known_at:null}),item({url:'https://name:secret@example.com/'})]),context);
 assert.equal(view.rows.length,0);
});
test('corporate actions distinguish effective date from missing announcement timestamp',()=>{
 const view=Events.model(data([item({published_at:null,event_at:'2026-11-19T14:30:00Z',type:'split'})]),context);
 assert.equal(view.rows[0].publishedAt,null);assert.equal(view.rows[0].date,'2026-11-19');assert.ok(view.rows[0].effectiveAt);
});
test('missing historical news and failed current refresh retain truthful status',()=>{
 const historical=Events.model(data([],{mode:'historical',status:'unavailable',stale_reason:'historical_news_not_archived'}),{...context,asof:'2026-11-20'});
 assert.match(historical.note,/没有当时保存/);
 const stale=Events.model(data([item()],{status:'stale',stale_reason:'source_access_denied'}),context);assert.equal(stale.rows.length,1);assert.match(stale.note,/来源拒绝/);
});
