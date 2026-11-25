'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const Jobs=require('../app/global-analysis.js');
const symbol='US_IXIC', asof='2026-11-20';
const record=(s=symbol,date=asof)=>({symbol:s,asof:date,price_history:{dates:['2026-11-18',date],close:[100,101]}});
const job=(status,patch={})=>({job_id:'f'.repeat(32),symbol,requested_asof:asof,asof,status,progress:{completed:27,expected:27},...patch});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function clock(){let callbacks=[];return {setTimeout(fn){callbacks.push(fn);return fn;},clearTimeout(fn){callbacks=callbacks.filter(item=>item!==fn);},async tick(){assert.ok(callbacks.length,'a bounded poll was scheduled');callbacks.shift()();await flush();},count(){return callbacks.length;}};}
function harness(overrides={}){const time=clock(),states=[],shown=[],clears=[];const api={startAnalysis:async()=>job('queued'),analysisJob:async()=>job('complete'),analysisResult:async()=>record(),clearCache:(...args)=>clears.push(args),...overrides};const c=Jobs.controller({api,clock:time,onState:x=>states.push(x),onResult:(...args)=>shown.push(args)});return {c,time,states,shown,clears,api};}
test('single endpoint moves through stages; only ready/final results replace chart',async()=>{
 const stages=['fetching','fitting','current_ready','current_ready','complete'];let posts=0,results=0;
 const h=harness({startAnalysis:async()=>{posts++;return job('queued');},analysisJob:async()=>job(stages.shift()),analysisResult:async()=>{results++;return record();}});
 await h.c.start({symbol,asof});assert.equal(h.shown.length,0);
 for(let i=0;i<5;i++)await h.time.tick();
 assert.equal(posts,1);assert.equal(results,2);assert.equal(h.shown.length,2);assert.equal(h.time.count(),0);
 assert.deepEqual(h.clears,[[symbol,asof],[symbol,asof]]);
 assert.equal(h.states.at(-1).status,'complete');assert.equal(h.states.at(-1).busy,false);
 h.c.dispose();
});
test('latest full-day request clears only own latest and exact archive caches',async()=>{
 const h=harness({startAnalysis:async()=>job('complete',{requested_asof:null})});
 await h.c.start({symbol,asof:null});assert.equal(h.shown.length,1);
 assert.deepEqual(h.clears,[[symbol,asof],[symbol,null]]);
});
test('late result from an older request cannot replace the new cutoff',async()=>{
 let release;const pending=new Promise(resolve=>{release=resolve;});
 const h=harness({startAnalysis:async req=>job('complete',{requested_asof:req.asof,asof:req.asof,job_id:req.asof===asof?'old':'new'}),analysisResult:id=>id==='old'?pending:Promise.resolve(record(symbol,'2026-11-19'))});
 const old=h.c.start({symbol,asof});await flush();await h.c.start({symbol,asof:'2026-11-19'});
 release(record());await old;
 assert.equal(h.shown.length,1);assert.equal(h.shown[0][0].asof,'2026-11-19');
});
test('wrong asset, cutoff or job id is rejected without changing current result',async()=>{
 for(const patch of [{symbol:'US_NDX'},{requested_asof:'2026-11-19'},{job_id:'../private'}]){
  const h=harness({startAnalysis:async()=>job('complete',patch)});await h.c.start({symbol,asof});assert.equal(h.shown.length,0);assert.equal(h.states.at(-1).busy,false);
 }
 assert.throws(()=>Jobs.jobMatches(job('fitting'),{symbol,asof},'another-id'),/身份/);
});
test('untrusted result URL is never fetched and future bars never enter the view',async()=>{
 const h=harness({startAnalysis:async()=>job('complete',{result_url:'https://untrusted.test/result'}),analysisResult:async id=>{assert.equal(id,'f'.repeat(32));return { ...record(),price_history:{dates:['2026-11-20','2026-11-23'],close:[100,102]}};}});
 await h.c.start({symbol,asof});assert.equal(h.shown.length,0);assert.equal(h.clears.length,0);assert.match(h.states.at(-1).message,/截止日/);
});
test('invalid close values and duplicated/out-of-order dates cannot corrupt the existing chart',()=>{
 for(const price_history of [{dates:[asof,asof],close:[100,101]},{dates:['2026-11-19',asof],close:[100,null]},{dates:['2026-11-19',asof],close:[100,NaN]}])assert.throws(()=>Jobs.validateResult({...record(),price_history},{symbol,asof},job('complete')),/精确日线/);
});
test('failed calculation leaves an already delivered current result intact',async()=>{
 const h=harness({startAnalysis:async()=>job('current_ready'),analysisJob:async()=>job('failed',{error:'数据源连接失败'})});
 await h.c.start({symbol,asof});await h.time.tick();assert.equal(h.shown.length,1);assert.equal(h.states.at(-1).status,'failed');assert.equal(h.time.count(),0);
});
test('status disconnection retries a bounded three times then resumes same job without POST',async()=>{
 let posts=0,gets=0;
 const h=harness({startAnalysis:async()=>{posts++;return job('queued');},analysisJob:async()=>{gets++;if(gets<=3)throw Error('offline');return job('complete');}});
 await h.c.start({symbol,asof});for(let i=0;i<3;i++)await h.time.tick();
 assert.equal(h.time.count(),0);assert.equal(h.states.at(-1).busy,false);assert.ok(h.states.at(-1).job_id);
 h.c.resume();await flush();assert.equal(posts,1);assert.equal(gets,4);assert.equal(h.shown.length,1);
});
test('repeated result download failure stops after three polls even when job status succeeds',async()=>{
 let posts=0,results=0;
 const h=harness({startAnalysis:async()=>{posts++;return job('queued');},analysisJob:async()=>job('complete'),analysisResult:async()=>{results++;if(results<=3)throw Error('result unavailable');return record();}});
 await h.c.start({symbol,asof});for(let i=0;i<3;i++)await h.time.tick();
 assert.equal(h.time.count(),0);assert.equal(h.states.at(-1).status,'connection_error');assert.equal(h.states.at(-1).busy,false);assert.equal(h.shown.length,0);
 h.c.resume();await flush();assert.equal(posts,1);assert.equal(results,4);assert.equal(h.shown.length,1);assert.equal(h.states.at(-1).status,'complete');
});
test('dispose ignores network results and cancels all polling',async()=>{
 let release;const h=harness({startAnalysis:()=>new Promise(resolve=>{release=resolve;})});
 const pending=h.c.start({symbol,asof});h.c.dispose();release(job('complete'));await pending;assert.equal(h.shown.length,0);assert.equal(h.time.count(),0);
});
test('invalid dates are rejected before submission; leap-day dates remain valid',async()=>{
 assert.equal(Jobs.validDate('2026-02-30'),false);assert.equal(Jobs.validDate('2024-02-29'),true);
 const h=harness({startAnalysis:()=>{throw Error('must not submit');}});await h.c.start({symbol,asof:'2026-02-30'});assert.equal(h.states.at(-1).status,'invalid');
});
test('unavailable replay service hides the cutoff and run controls',async()=>{
 const ids=['global-analysis','global-analysis-run','global-analysis-asof','global-analysis-status','global-analysis-progress','global-analysis-resume'];
 const nodes=Object.fromEntries(ids.map(id=>[id,{hidden:false,dataset:{},addEventListener(){}}]));
 const adapter={global:{isAsset:()=>true,capabilities:async()=>({available:false,reason:'unavailable'})}};
 Jobs.attach({document:{getElementById:id=>nodes[id]},adapter,context:{code:symbol,asof:null}});
 await flush();
 assert.equal(nodes['global-analysis'].hidden,true);
 assert.equal(nodes['global-analysis-run'].disabled,true);
});
test('default browser timer is not invoked with the private clock object as receiver',async()=>{
 const browser={module:{exports:{}},setTimeout:function(fn){assert.equal(this,undefined,'native browser timer requires no private receiver');return fn;},clearTimeout:function(){assert.equal(this,undefined);}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../app/global-analysis.js'),'utf8'),browser);
 const states=[];const c=browser.module.exports.controller({api:{startAnalysis:async()=>job('queued')},onState:s=>states.push(s)});
 await c.start({symbol,asof});assert.equal(states.at(-1).status,'queued');c.dispose();
});
function dataAdapter(hostname='localhost'){
 const calls=[];const window={location:{hostname}};
 const fetch=async(url,options={})=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({available:true,symbols:[symbol],url})};};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../app/lppl-data.js'),'utf8'),{window,URL,URLSearchParams,fetch,AbortController,setTimeout,clearTimeout});
 return {api:window.LPPL.global,calls};
}
test('public static website does not probe or POST local-only API',async()=>{
 const {api,calls}=dataAdapter('careypang.github.io');assert.equal((await api.capabilities()).available,false);
 await assert.rejects(api.startAnalysis({symbol}),/本机后端/);assert.equal(calls.length,0);
});
test('unified API sends only canonical asset and one chosen endpoint; polling uses GET',async()=>{
 const {api,calls}=dataAdapter();await api.capabilities();await api.startAnalysis({symbol:'us_ixic',asof});await api.analysisJob('a'.repeat(32));await api.analysisResult('a'.repeat(32));
 assert.equal(calls[0].url,'/api/global-analysis');assert.equal(calls[1].options.method,'POST');
 assert.deepEqual(JSON.parse(calls[1].options.body),{symbol,asof,refresh:true});
 assert.equal(calls[2].options.method,undefined);assert.equal(calls[3].url,'/api/global-analysis/'+'a'.repeat(32)+'/result');
 assert.throws(()=>api.startAnalysis({symbol:'NOPE'}),/身份/);await assert.rejects(api.analysisJob('../escape'),/编号/);assert.equal(calls.length,4);
});
test('cache invalidation preserves other assets and all other historical dates',async()=>{
 const {api,calls}=dataAdapter();
 await api.latest(symbol);await api.latest('US_NDX');await api.result(symbol,asof);await api.result(symbol,'2026-11-19');await api.history(symbol);
 const first=calls.length;api.clearCache(symbol,asof);
 await api.latest(symbol);await api.latest('US_NDX');await api.result(symbol,'2026-11-19');assert.equal(calls.length,first);
 await api.result(symbol,asof);await api.history(symbol);assert.equal(calls.length,first+2);
 api.clearCache(symbol,null);await api.latest(symbol);assert.equal(calls.length,first+3);
});
