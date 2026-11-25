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
function qualifiedPayload() {
  const p=fixture();p.symbol='US_IXIC';
  p.rules.cycles_1_5.families[0].qualified_windows=[900,925];
  p.rules.cycles_1_5.families[0].member_date_range=['2026-12-01','2026-12-04'];
  p.rules.cycles_1_5.families[1].qualified_windows=[];
  return p;
}
function evidenceFixture() {
  return {
    schema_version:'long_window_pit_v1',
    generated_from:{source_root_rows:{US_IXIC:{first_date:'1971-02-05',last_date:'2026-11-20',rows:14068}}},
    rules:{cycles_1_5:{US_IXIC:{
      long_900:{signal_asofs:12,episodes:[{top_hit:true,tc_est:'2026-12-02'},{top_hit:false},{DD120:-22}],
        metrics:{'DD120_le_-20':{obs:60,rand_p95:30},top_hit:{obs:20,rand_p95:35}}},
      ultra_6600:{signal_asofs:4,episodes:[],metrics:{}},
    }}},
    verdicts:{cycles_1_5:{US_IXIC:{long_900:'pass',ultra_6600:'insufficient'}}},
  };
}
function verdictBadge() {
  return {html:(level,options)=>'<span data-level="'+level+'">'+options.label+'</span>'};
}

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
  assert.match(Long.study(original,{}).error,/没有长窗口研究结果/);
  assert.deepEqual(original,{symbol:'US_IXIC',top:{signal_status:'no_cluster'},raw:{}});
});
test('research 1.5 and old 2.5 render independently without changing the saved result', () => {
  const p=fixture(), before=JSON.stringify(p), research=Long.html(p,'cycles_1_5'), old=Long.html(p,'cycles_2_5');
  assert.match(research,/单窗研究候选/);
  assert.match(research,/2026-12-01 — 2026-12-03/);
  assert.match(old,/没有跨窗口族分组/);
  assert.ok(!old.includes('class="lh-window-state">单窗研究候选'));
  assert.match(old,/合格窗口：0/);
  assert.equal(JSON.stringify(p),before);
});
test('multiple seeds or same-family windows cannot become cross-scale confirmation', () => {
  const p=fixture();p.rules.cycles_1_5.cross_family_clusters[0].members=[{n:900},{n:925}];
  assert.match(Long.html(p,'cycles_1_5'),/没有跨窗口族分组/);
  assert.match(Long.html(p,'cycles_1_5'),/不是预测不确定性/);
});
test('one candidate date is not advertised as a precise top forecast', () => {
  assert.equal(Long.dateRange(['2026-12-01','2026-12-01']),'候选落在同一交易日；未形成日期宽度');
  assert.equal(Long.dateRange(['2026-12-02','2026-12-01']),'');
  assert.equal(Long.aheadRange([null,1]),'');
});
test('history excludes later cutoff snapshots and does not invent first publication time', () => {
  const p=fixture();p.stability.history=[{asof:'2026-11-13',windows:[]},{asof:'2026-11-27',windows:[]}];
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/2026-11-13/);assert.ok(!output.includes('2026-11-27'));
  assert.ok(!output.includes('首次可见：'));
});
test('pending and failed seeds remain explicit and zero counts are preserved', () => {
  const p=fixture();p.status='incomplete';p.counts={expected:12,completed:8,failed:1,pending:3};
  p.windows[0].seeds[0]={seed:11,status:'failed',optimizer_success:false};
  const output=Long.html(p,'cycles_1_5');
  assert.match(output,/8 \/ 12/);assert.match(output,/失败 1/);assert.match(output,/待完成 3/);
  assert.match(output,/优化器收敛：否/);assert.match(output,/tc 相对截止日 —/);
});
test('G3 comparison keeps original results separate and rejects a different cutoff', () => {
  const p=fixture();p.g3_comparison={asof:p.asof,windows:[{n:925,status:'complete',ahead:-54.57,m:.8,omega:7,B:-.003,box_pass:false,cycles_1_5_pass:false}]};
  assert.match(Long.html(p,'cycles_1_5'),/G3 对照 · box 合格 0\/1/);
  assert.match(Long.html(p,'cycles_1_5'),/搜索域与预算不同/);
  p.g3_comparison.asof='2026-11-13';assert.ok(!Long.html(p,'cycles_1_5').includes('G3 对照'));
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
  assert.match(output,/7598 日/);assert.match(output,/当前没有交易所裁定/);
  assert.match(output,/Naver 收盘 625.5000/);assert.match(output,/Yahoo 收盘 636.4000/);
  assert.match(output,/本研究当前源原值 625.5000/);
});

test('passing 900-day evidence renders its verdict, metrics and date range without an exact top date', () => {
  const p=qualifiedPayload(),e=evidenceFixture(),result=Long.verdict(p,e,'cycles_1_5');
  assert.equal(result.title,'大跌风险窗口');
  assert.equal(result.range,'2026-12-01 — 2026-12-04');
  assert.match(result.text,/60\.0%（随机 95% 分位 30\.0%，12 个截止日 \/ 2 轮）/);
  assert.match(result.text,/顶部落在窗口 ±20 个交易日内的比例 20\.0%，不高于随机（95% 分位 35\.0%）/);
  const output=Long.html(p,'cycles_1_5',verdictBadge(),e);
  const start=output.indexOf('<section class="lh-verdict"'),end=output.indexOf('</section>',start);
  const block=output.slice(start,end);
  assert.ok(start >= 0);
  assert.ok(output.indexOf('</div>',output.indexOf('class="lh-heading"')) < start);
  assert.match(block,/大跌风险窗口/);
  assert.match(block,/风险窗口 2026-12-01 — 2026-12-04/);
  assert.match(block,/data-level="descriptive">历史回测/);
  assert.ok(!block.includes('2026-12-02'));
});

test('failing and insufficient 900-day verdicts remain candidates without date claims', () => {
  for (const [status,signalCount] of [['fail',12],['insufficient',7]]) {
    const p=qualifiedPayload(),e=evidenceFixture();
    e.verdicts.cycles_1_5.US_IXIC.long_900=status;
    e.rules.cycles_1_5.US_IXIC.long_900.signal_asofs=signalCount;
    const result=Long.verdict(p,e,'cycles_1_5');
    assert.equal(result.title,'约 900 日窗口候选');
    assert.equal(result.text,'历史同类信号未显著优于随机日期（'+signalCount+' 个截止日）。');
    const output=Long.html(p,'cycles_1_5',verdictBadge(),e);
    const start=output.indexOf('<section class="lh-verdict"'),end=output.indexOf('</section>',start);
    assert.match(output.slice(start,end),/data-level="none">未经验证/);
    assert.ok(!output.slice(start,end).includes('2026-12-02'));
  }
});

test('6600-day-only evidence is research display and no qualifying family gets a plain message', () => {
  const p=qualifiedPayload(),e=evidenceFixture();
  p.rules.cycles_1_5.families[0].qualified_windows=[];
  p.rules.cycles_1_5.families[1].qualified_windows=[6600];
  let result=Long.verdict(p,e,'cycles_1_5');
  assert.equal(result.title,'');
  assert.equal(result.additionalText,'约 6600 日窗口：研究展示。需 26 年以上数据，历史可检验信号 4 个截止日，无法验证。');
  let output=Long.html(p,'cycles_1_5',verdictBadge(),e);
  let start=output.indexOf('<section class="lh-verdict"'),end=output.indexOf('</section>',start);
  assert.match(output.slice(start,end),/data-level="none">未经验证/);
  assert.ok(!output.slice(start,end).includes('大跌风险窗口'));
  p.rules.cycles_1_5.families[1].qualified_windows=[];
  result=Long.verdict(p,e,'cycles_1_5');
  assert.equal(result.text,'本截止日没有合格的长窗顶部聚类。');
  output=Long.html(p,'cycles_1_5',verdictBadge(),e);
  assert.match(output,/本截止日没有合格的长窗顶部聚类。/);
});

test('missing or invalid evidence schema adds no verdict block', () => {
  const p=qualifiedPayload(),e=evidenceFixture(),incomplete=evidenceFixture();
  delete incomplete.rules.cycles_1_5.US_IXIC.ultra_6600;
  assert.equal(Long.verdict(p,null,'cycles_1_5'),null);
  assert.equal(Long.verdict(p,{schema_version:'other'},'cycles_1_5'),null);
  assert.equal(Long.verdict(p,incomplete,'cycles_1_5'),null);
  assert.ok(!Long.html(p,'cycles_1_5',verdictBadge()).includes('class="lh-verdict"'));
  assert.ok(Long.html(p,'cycles_1_5',verdictBadge(),e).includes('class="lh-verdict"'));
});

test('PIT verdicts do not use evidence beyond its source cutoff', () => {
  const p=qualifiedPayload(),e=evidenceFixture();
  assert.ok(Long.verdict(p,e,'cycles_1_5'));
  const later=qualifiedPayload();later.asof='2026-11-21';
  assert.ok(Long.verdict(later,e,'cycles_1_5'));
  const earlier=qualifiedPayload();earlier.asof='2026-11-19';
  assert.equal(Long.verdict(earlier,e,'cycles_1_5'),null);
  assert.ok(!Long.html(earlier,'cycles_1_5',verdictBadge(),e).includes('class="lh-verdict"'));
  const missing=structuredClone(e);delete missing.generated_from;
  assert.equal(Long.verdict(p,missing,'cycles_1_5'),null);
  const invalid=structuredClone(e);invalid.generated_from.source_root_rows.US_IXIC.last_date='2026-02-30';
  assert.equal(Long.verdict(p,invalid,'cycles_1_5'),null);
});
