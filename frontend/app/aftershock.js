/* Render published aftershock evidence without fitting, combining frequencies or inventing dates. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LPPLAftershock = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var KEYS = ['omori', 'bath', 'productivity'];
  var STATUS = {available:'已计算',insufficient_data:'样本尚不足',not_available:'暂无对应结果',failed:'本次计算失败'};
  var FREQUENCY = {daily:'日线', '15m_and_daily':'15 分钟与日线分项研究', '15m_counts_per_daily_session':'15 分钟大波动，按交易日计数'};
  var ANCHOR = {retrospective_price_peak_not_negative_mainshock:'回顾性价格高点（并非负向主震）',retrospective_largest_daily_decline_since_price_peak:'峰后已观察最大日跌幅（回顾性起点）',historical_causal_negative_shocks_for_productivity:'历史负向冲击样本',causal_negative_daily_shock:'已观察负向日线冲击'};
  var SAMPLE = {observed_after_days:'起点后交易日',baseline_days:'基准交易日',baseline_bars:'基准 K 线',latest_mainshock_after_days:'最新主震后交易日',mature_events:'成熟历史事件',pending_events:'尚未成熟事件',historical_events:'历史事件',training_years:'训练年数',training_start:'训练开始',training_end:'训练结束',current_observed_after_days:'本次冲击后交易日',horizon_days:'观察期交易日',latest5_events:'最近 5 日大波动次数',previous5_events:'此前 5 日大波动次数',latest_day_events:'最近一日大波动次数'};
  var PARAM = {p:'衰减参数 p',c:'时间平移 c',background:'背景次数',amplitude:'增量强度',decay_identified:'是否识别出衰减',gap_log10:'主震 / 最大余震的对数差',mainshock_abs_log_return:'主震绝对对数收益',largest_aftershock_abs_log_return:'最大余震绝对对数收益',alpha:'产出率斜率 α',alpha_ci95:'α 的 95% 估计区间',intercept:'截距',expected_20d_events:'20 日大波动次数的条件均值',alpha_interval_includes_zero:'斜率区间是否含 0'};
  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function value(v) {
    if (v === null || v === undefined) return '未提供';
    if (typeof v === 'boolean') return v ? '是' : '否';
    if (Array.isArray(v)) return v.map(value).join(' – ');
    if (typeof v === 'number') return Number.isFinite(v) ? String(Number(v.toPrecision(5))) : '未提供';
    return String(v);
  }
  function rows(obj, labels) { return Object.keys(labels).filter(function(key){return obj && Object.hasOwn(obj,key);}).map(function(key){return '<dt>'+esc(labels[key])+'</dt><dd>'+esc(value(obj[key]))+'</dd>';}).join(''); }
  function model(data) {
    var study=data && data.raw && data.raw.research && data.raw.research.aftershock;
    if (!study) return {study:null,note:'当前封存未提供三定律研究；已有行情与顶部区间仍可查看。'};
    if (study.schema_version !== 'aftershock_v1' || study.symbol !== data.symbol || study.asof !== data.modelAsOf) return {study:null,note:'余震结果与当前资产或截止日不一致，未混入本页。'};
    return {study:study,note:'数据截至 '+study.asof+' · '+(FREQUENCY[study.frequency] || study.frequency || '频率未提供')+(study.status==='failed'?' · 余震分析失败：'+(study.reason || '本次计算未完成，已有行情仍可查看'):'')};
  }
  function keyMetrics(module,key) {
    var samples=module.samples || {},parameters=module.parameters || {};
    var definition={omori:['observed_after_days','起点后交易日','p','p'],bath:['observed_after_days','起点后交易日','gap_log10','幅度对数差'],productivity:['mature_events','成熟事件','alpha','α']}[key];
    if(!definition)return '';
    var count=samples[definition[0]],parameter=parameters[definition[2]];
    var countText=Number.isInteger(count)&&count>=0?String(count):'未提供';
    var parameterText=module.status==='available'&&typeof parameter==='number'&&Number.isFinite(parameter)?value(parameter):'未估计';
    return '<p class="aftershock-key-metrics">'+esc(definition[1])+' <strong>'+esc(countText)+'</strong> · '+esc(definition[3])+' <strong>'+esc(parameterText)+'</strong></p>';
  }
  function moduleHTML(module, asof, key) {
    if (!module) return '<p class="aftershock-status">暂无对应结果</p>';
    if ([module.anchor_date,module.mainshock_date,module.samples && module.samples.training_end].some(function(date){return date && date > asof;})) return '<p class="aftershock-status">该项含有截止日之后的资料，未纳入当前回放。</p>';
    var status=STATUS[module.status] || '状态未提供';
    var html='<p class="aftershock-status">'+esc(status)+' · '+esc(FREQUENCY[module.frequency] || module.frequency || '频率未提供')+'</p>';
    html+='<p class="aftershock-summary">'+esc(module.summary || module.reason || status)+'</p>';
    html+=keyMetrics(module,key);
    html+='<p class="aftershock-anchor">起点 '+esc(module.anchor_date || '未提供')+' · 截止 '+esc(asof)+'</p>';
    if (module.mainshock_date) html+='<p class="aftershock-anchor">对应主震 '+esc(module.mainshock_date)+'</p>';
    if (module.reason) html+='<p class="aftershock-reason">'+esc(module.reason)+'</p>';
    html+='<details><summary>样本与参数</summary>';
    if (module.anchor_type) html+='<p>'+esc(ANCHOR[module.anchor_type] || module.anchor_type)+'</p>';
    html+='<dl>'+rows(module.samples,SAMPLE)+rows(module.parameters,PARAM)+'</dl>';
    if (module.current_mainshock) html+='<p>最新主震 '+esc(module.current_mainshock.date || '未提供')+'：'+esc(STATUS[module.current_mainshock.status] || '状态未提供')+'，之后 '+esc(value(module.current_mainshock.observed_after_days))+' 个完整交易日。</p>';
    html+='</details>';
    return html;
  }
  function evidenceHTML(study) {
    var source=study.source || {};
    var mode={verified_independent_research_archive:'核验过的独立研究归档',daily_recalculation:'日线重新计算',daily_reconstruction:'日线重建',daily_rebuild:'日线重建'}[source.mode] || source.mode || '未提供';
    var html='<details><summary>来源、版本与证据</summary><dl><dt>来源</dt><dd>'+esc(source.label || '未提供')+'</dd><dt>计算口径</dt><dd>'+esc(mode)+'</dd><dt>方法版本</dt><dd>'+esc(study.method_version || '未提供')+'</dd><dt>证据状态</dt><dd>'+esc(study.evidence_state==='historical_reconstruction'?'历史重建':study.evidence_state || '未提供')+'</dd><dt>真实首次可见时间</dt><dd>'+esc(study.first_visible_at || '未建立')+'</dd><dt>数据版本</dt><dd>'+esc(study.data_version || '未提供')+'</dd><dt>输入哈希</dt><dd>'+esc(source.input_hash || '未提供')+'</dd></dl>';
    if (study.archive_reuse) html+='<p>'+esc(study.archive_reuse.reason || '')+'</p>';
    if (Array.isArray(study.limits)) html+='<ul>'+study.limits.map(function(line){return '<li>'+esc(line)+'</li>';}).join('')+'</ul>';
    return html+'</details>';
  }
  function attach(options) {
    var doc=options.document, host=doc.getElementById('terminal-aftershock');
    return {render:function(data){
      if (!host) return;
      var view=model(data); host.hidden=false;host.dataset.status=view.study?view.study.status==='failed'?'failed':'available':'not_available';
      KEYS.forEach(function(key){var target=doc.getElementById('terminal-'+key);if(target) target.innerHTML=view.study && view.study.status==='failed'?'<p class="aftershock-status">本次计算失败，原因见下方说明。</p>':moduleHTML(view.study && view.study.modules && view.study.modules[key],view.study && view.study.asof,key);});
      doc.getElementById('terminal-aftershock-note').textContent=view.note;
      var evidence=doc.getElementById('terminal-aftershock-evidence');if(evidence) evidence.innerHTML=view.study?evidenceHTML(view.study):'';
      var badge=doc.getElementById('terminal-aftershock-badge');
      if(badge) badge.innerHTML=view.study && options.badge ? options.badge.html('descriptive',{label:view.study.evidence_state==='historical_reconstruction'?'历史重建':'研究统计',detail:'各项使用自己的起点、频率和样本；详细来源与版本可展开核对。',n:view.study.modules && view.study.modules.productivity && view.study.modules.productivity.samples && view.study.modules.productivity.samples.mature_events}) : '';
    }};
  }
  return {model:model,moduleHTML:moduleHTML,evidenceHTML:evidenceHTML,value:value,attach:attach};
});
