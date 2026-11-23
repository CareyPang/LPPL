'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Long = require('../app/long-horizon.js');

function fixture() {
  const windows = [900,925,950,6500,6600,6700].map(n => ({
    n, family:n < 1000 ? 'long_900' : 'ultra_6600', seed_gap_days:0.2,
    seed_date_range:['2026-12-01','2026-12-02'], seed_ahead_range:[7.5,7.7],
    eligible:{cycles_1_5:true,cycles_2_5:false},
    seeds:[{seed:11,status:'complete',tc_ahead:7.5,tc_date:'2026-12-01',m:.5,omega:8,r2:.95,damping:.6,full_cycles:2,optimizer_success:true,boundary_status:'interior',passes:{cycles_1_5:true,cycles_2_5:false}}],
  }));
  return {schema_version:'long_horizon_v1',symbol:'US_NDX',asof:'2026-11-20',status:'complete',
    counts:{expected:12,completed:12,failed:0,pending:0},windows,first_visible_at:null,
    source:'frozen close',model_version:'test',rules:{
      cycles_1_5:{definition:'完整周期≥1.5',families:[{family:'long_900',qualified_windows:3,member_date_range:['2026-12-01','2026-12-02']},{family:'ultra_6600',qualified_windows:3,member_date_range:['2026-12-01','2026-12-03']}],cross_family_clusters:[{start:'2026-12-01',end:'2026-12-03',span_trading_days:2,members:[{n:925,family:'long_900'},{n:6600,family:'ultra_6600'}]}]},
      cycles_2_5:{definition:'完整周期≥2.5',families:[{family:'long_900',qualified_windows:0},{family:'ultra_6600',qualified_windows:0}],cross_family_clusters:[]},
    },stability:{history:[]},calendar:{status:'weekday_estimate'},limits:[]};
}
function data(payload) { return {symbol:'US_NDX',modelAsOf:'2026-11-20',raw:{asof:'2026-11-20',research:{long_horizon:payload}}}; }

test('long-window data requires the exact supported asset and cutoff', () => {
  const payload=fixture();
  assert.equal(Long.study(data(payload),{}).payload,payload);
  assert.equal(Long.study({...data(payload),symbol:'US_MRVL'},{}).hidden,true);
  assert.match(Long.study(data({...payload,symbol:'US_IXIC'}),{}).error,/不匹配/);
  assert.match(Long.study(data(payload),{asof:'2026-11-13'}).error,/不匹配/);
  assert.match(Long.study(data({...payload,schema_version:'future_schema'}),{}).error,/不匹配/);
});
test('missing long-window coverage is explicit and does not replace ordinary chart data', () => {
  const original={symbol:'US_IXIC',top:{signal_status:'no_cluster'},raw:{}};
  assert.match(Long.study(original,{}).error,/27/);
  assert.deepEqual(original,{symbol:'US_IXIC',top:{signal_status:'no_cluster'},raw:{}});
});
test('research 1.5 and old 2.5 render independently without changing the saved result', () => {
  const p=fixture(), before=JSON.stringify(p), research=Long.html(p,'cycles_1_5'), old=Long.html(p,'cycles_2_5');
  assert.match(research,/单窗研究候选/);
  assert.match(research,/2026-12-01 — 2026-12-03/);
  assert.match(old,/尚未形成跨窗口族分组/);
  assert.ok(!old.includes('class="lh-window-state">单窗研究候选'));
  assert.match(old,/合格窗口：0/);
  assert.equal(JSON.stringify(p),before);
});
test('multiple seeds or same-family windows cannot become cross-scale confirmation', () => {
  const p=fixture();p.rules.cycles_1_5.cross_family_clusters[0].members=[{n:900},{n:925}];
  assert.match(Long.html(p,'cycles_1_5'),/尚未形成跨窗口族分组/);
  assert.match(Long.html(p,'cycles_1_5'),/不是预测不确定性/);
});
test('one candidate date is not advertised as a precise top forecast', () => {
  assert.equal(Long.dateRange(['2026-12-01','2026-12-01']),'候选落在同一交易日；未形成日期宽度');
  assert.equal(Long.dateRange(['2026-12-02','2026-12-01']),'日期区间未记录');
  assert.equal(Long.aheadRange([null,1]),'提前量未记录');
});
test('history excludes later cutoff snapshots and does not invent first publication time', () => {
  const p=fixture();p.stability.history=[{asof:'2026-11-13',windows:[]},{asof:'2026-11-27',windows:[]}];
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/2026-11-13/);assert.ok(!output.includes('2026-11-27'));
  assert.match(output,/首次可见：未记录；本次查看不补造历史发布时间/);
});
test('pending and failed seeds remain explicit and zero counts are preserved', () => {
  const p=fixture();p.status='incomplete';p.counts={expected:12,completed:8,failed:1,pending:3};
  p.windows[0].seeds[0]={seed:11,status:'failed',optimizer_success:false};
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/8 \/ 12/);assert.match(output,/失败 1/);assert.match(output,/待完成 3/);
  assert.match(output,/优化器收敛：否/);assert.match(output,/tc 相对截止日 未记录/);
});
test('G3 comparison keeps original results separate and rejects a different cutoff', () => {
  const p=fixture();p.g3_comparison={asof:p.asof,windows:[{n:925,status:'complete',ahead:-54.57,m:.8,omega:7,B:-.003,box_pass:false,cycles_1_5_pass:false}]};
  assert.match(Long.html(p,'cycles_1_5'),/原网站 G3 对照 · 旧 box 合格 0\/1/);
  assert.match(Long.html(p,'cycles_1_5'),/搜索域与预算不同/);
  p.g3_comparison.asof='2026-11-13';assert.ok(!Long.html(p,'cycles_1_5').includes('原网站 G3 对照'));
});
test('data-sourced text is escaped instead of becoming executable markup', () => {
  const p=fixture();p.source='<img src=x onerror=alert(1)>';p.limits=['<script>evil()</script>'];
  const output=Long.html(p,'cycles_1_5');
  assert.ok(!output.includes('<img'));assert.ok(!output.includes('<script>'));assert.match(output,/&lt;script&gt;/);
});
test('real source objects and qualified-window lists have readable values', () => {
  const p=fixture();p.source={label:'Yahoo daily close, frozen reconstruction; not contemporaneously published forecast',data_version:'hash'};
  p.rules.cycles_1_5.families[0].qualified_windows=[900,925];
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/合格窗口：2（900、925 日）/);assert.match(output,/Yahoo 日线收盘价/);assert.ok(!output.includes('[object Object]'));
});
test('missing historical archive is not described as queued computation or completed research', () => {
  const p=fixture();p.stability.history=[{asof:'2026-11-11',status:'missing_archive',counts:{expected:12,completed:0,failed:0,pending:12},windows:[]}];
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/2026-11-11 · 原始档案未取得/);assert.ok(!output.includes('待完成 12'));
});
test('disagreeing seeds explain rejection without inventing an averaged candidate', () => {
  const p=fixture(),w=p.windows[3];w.eligible.cycles_1_5=false;w.seed_gap_days=44.16;w.point_date=null;
  w.rejection_reasons={cycles_1_5:['seed_tc_disagreement_gt_2_sessions']};
  const output=Long.html(p,'cycles_1_5');assert.match(output,/临界时间相差超过 2 个交易日/);assert.match(output,/44.160/);
});
test('fixed-tc diagnostic shows saved errors only at the matching cutoff', () => {
  const p=fixture();p.profile_diagnostic={asof:p.asof,n:6600,counts:{expected:2,completed:2},points:[{ahead:1,sse:270.672,delta_sse_pct:.199,completed_seeds:2,converged_seeds:2}]};
  const output=Long.html(p,'cycles_1_5');assert.match(output,/SSE 270.6720/);assert.match(output,/高 0.199%/);assert.match(output,/误差越平坦，日期越难区分/);
  p.profile_diagnostic.asof='2026-11-13';assert.ok(!Long.html(p,'cycles_1_5').includes('SSE 270.6720'));
});

test('Korean studies are supported with exact asset identity and their own calendar', () => {
  for(const symbol of ['KR_KOSPI','KR_KOSDAQ']) {
    const p={...fixture(),symbol,calendar:{status:'observed_historical_sessions_else_weekday_estimate'}};
    assert.equal(Long.study({...data(p),symbol},{}).payload,p);
    const output=Long.html(p,'cycles_1_5');
    assert.match(output,/该标的实际交易日/);assert.match(output,/韩股不套用美股日历/);
    assert.ok(!output.includes('2026年采用纳斯达克已核对假日'));
  }
});

test('insufficient real history is counted separately from pending computation', () => {
  const p=fixture();p.symbol='KR_KOSDAQ';p.status='complete_with_data_gaps';
  p.counts={expected:12,completed:6,failed:0,pending:0,not_available:6};
  p.source={label:'Naver daily',rows:6432,first_date:'2000-10-16'};
  for(const w of p.windows.filter(w=>w.n>1000)) {
    w.eligible={cycles_1_5:false,cycles_2_5:false};w.data_reason='历史不足所选窗口；未填充';
    w.seeds=[{seed:11,status:'not_available'},{seed:29,status:'not_available'}];
  }
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/数据不足 6/);assert.match(output,/待完成 0/);
  assert.match(output,/真实历史不足此窗口/);assert.match(output,/仍有历史数据缺口/);
  assert.match(output,/真实日线：6432 日/);
});

test('fifty-two endpoint replay stays collapsed by period and older group', () => {
  const p=fixture();
  p.stability.history=Array.from({length:51},(_,i)=>({asof:new Date(Date.UTC(2026,10,19-i*5)).toISOString().slice(0,10),status:'complete',windows:[],counts:p.counts}));
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/加上当前截止日共 52 期/);assert.match(output,/展开更早 45 期/);
  assert.equal((output.match(/<details class="lh-history-date">/g)||[]).length,51);
  assert.ok(!output.includes('<details class="lh-history-date" open'));
  assert.ok(!output.includes('<details class="lh-history-earlier" open'));
});

test('unresolved cross-source discrepancy is visible with actual source identity', () => {
  const p=fixture();p.symbol='KR_KOSDAQ';p.source={label:'Naver Finance siseJson daily · 冻结输入历史重建',
    rows:7598,first_date:'1996-07-02',data_quality:{status:'unresolved_cross_source_discrepancy',affected_date:'2001-11-01',observed_naver_close:625.5,observed_yahoo_close:636.4,current_source_close:625.5}};
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/来源核验待完成：2001-11-01/);assert.match(output,/Naver Finance/);
  assert.match(output,/7598 日/);assert.match(output,/尚未取得交易所裁定/);
  assert.match(output,/Naver 收盘 625.5000/);assert.match(output,/Yahoo 收盘 636.4000/);
  assert.match(output,/本研究当前源原值 625.5000/);
});
