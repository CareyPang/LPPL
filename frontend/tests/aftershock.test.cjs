'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Study=require('../app/aftershock.js');
const data=study=>({symbol:'US_IXIC',modelAsOf:'2026-11-20',raw:{research:{aftershock:study}}});
const source=()=>({schema_version:'aftershock_v1',symbol:'US_IXIC',asof:'2026-11-20',frequency:'15m_and_daily',first_visible_at:null,evidence_state:'historical_reconstruction',source:{label:'Yahoo',mode:'verified_independent_research_archive',input_hash:'abc'},modules:{}});
test('aftershock only displays exact asset and model cutoff; no latest study in historical replay',()=>{
 assert.ok(Study.model(data(source())).study);
 assert.equal(Study.model(data({...source(),symbol:'US_NDX'})).study,null);
 assert.equal(Study.model(data({...source(),asof:'2026-11-23'})).study,null);
 assert.equal(Study.model(data(null)).study,null);
});
test('zero p is retained with no-decay and zero new-shock observations',()=>{
 const html=Study.moduleHTML({status:'available',frequency:'15m_counts_per_daily_session',anchor_date:'2026-10-06',anchor_type:'retrospective_price_peak_not_negative_mainshock',mainshock_date:'2026-11-20',parameters:{p:0,decay_identified:false},samples:{latest_mainshock_after_days:0},summary:'大波动尚未稳定衰减',current_mainshock:{date:'2026-11-20',status:'insufficient_data',observed_after_days:0}},'2026-11-20');
 assert.match(html,/15 分钟大波动/);assert.match(html,/并非负向主震/);assert.match(html,/<dt>衰减参数 p<\/dt><dd>0<\/dd>/);assert.match(html,/<dt>是否识别出衰减<\/dt><dd>否<\/dd>/);assert.match(html,/之后 0 个完整交易日/);
});
test('daily productivity preserves alpha interval including zero and actual training dates',()=>{
 const html=Study.moduleHTML({status:'available',frequency:'daily',samples:{mature_events:52,training_start:'1990-01-01',training_end:'2025-12-31'},parameters:{alpha:0.6333,alpha_ci95:[-0.1458,1.4124],alpha_interval_includes_zero:true}},'2026-11-20');
 assert.match(html,/日线/);assert.match(html,/-0.1458 – 1.4124/);assert.match(html,/1990-01-01/);assert.match(html,/<dd>是<\/dd>/);
});
test('missing modules remain missing and untrusted strings are escaped',()=>{
 assert.match(Study.moduleHTML(null,'2026-11-20'),/暂无对应结果/);
 const html=Study.moduleHTML({status:'failed',summary:'<img src=x onerror=alert(1)>'},'2026-11-20');assert.doesNotMatch(html,/<img/);assert.match(html,/&lt;img/);
});
test('evidence renders recorded provenance and never invents historical first visibility',()=>{
 const html=Study.evidenceHTML(source());assert.match(html,/历史重建/);assert.match(html,/真实首次可见时间<\/dt><dd>未建立/);assert.match(html,/核验过的独立研究归档/);assert.match(html,/abc/);
});
test('future anchors and future training cutoffs cannot leak into an older replay',()=>{
 for(const module of [{anchor_date:'2026-11-23'},{mainshock_date:'2026-11-23'},{samples:{training_end:'2026-12-31'}}]){
  const html=Study.moduleHTML({...module,status:'available',summary:'must not leak'},'2026-11-20');assert.match(html,/截止日之后/);assert.doesNotMatch(html,/must not leak/);
 }
});
test('failed aftershock study exposes its actual failure reason and never marks cards available',()=>{
 const nodes=Object.fromEntries(['terminal-aftershock','terminal-omori','terminal-bath','terminal-productivity','terminal-aftershock-note','terminal-aftershock-evidence','terminal-aftershock-badge'].map(id=>[id,{dataset:{}}]));
 const study={...source(),status:'failed',reason:'当前输入不足，无法完成拟合'};
 Study.attach({document:{getElementById:id=>nodes[id]}}).render(data(study));
 assert.equal(nodes['terminal-aftershock'].dataset.status,'failed');assert.match(nodes['terminal-aftershock-note'].textContent,/当前输入不足/);
 for(const key of ['omori','bath','productivity'])assert.match(nodes['terminal-'+key].innerHTML,/本次计算失败/);
 assert.match(Study.evidenceHTML({...source(),source:{mode:'daily_recalculation'}}),/日线重新计算/);
});
test('each card exposes sample count and key estimate before its collapsed details',()=>{
 const modules={omori:{samples:{observed_after_days:33},parameters:{p:0}},bath:{samples:{observed_after_days:11},parameters:{gap_log10:0.01989}},productivity:{samples:{mature_events:52},parameters:{alpha:0.6333}}};
 for(const [key,module]of Object.entries(modules)){
  const html=Study.moduleHTML({...module,status:'available'},'2026-11-20',key),before=html.split('<details>')[0];
  assert.match(before,/aftershock-key-metrics/);assert.ok(before.includes(String(Object.values(module.samples)[0])));assert.ok(before.includes(String(Object.values(module.parameters)[0])));
 }
});
test('missing or unsupported estimates remain unestimated, while actual zero samples stay zero',()=>{
 for(const status of ['available','insufficient_data','not_available']){
  const before=Study.moduleHTML({status,samples:{observed_after_days:0},parameters:{p:null}},'2026-11-20','omori').split('<details>')[0];
  assert.match(before,/起点后交易日 <strong>0<\/strong>/);assert.match(before,/p <strong>未估计<\/strong>/);
 }
 const missing=Study.moduleHTML({status:'insufficient_data'},'2026-11-20','productivity').split('<details>')[0];
 assert.match(missing,/成熟事件 <strong>未提供/);assert.match(missing,/α <strong>未估计/);
});
