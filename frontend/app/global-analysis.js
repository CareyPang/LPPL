/* Explicit single-cutoff job controls. All transport is delegated to LPPL.global. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LPPLGlobalAnalysis = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var STATES = new Set(['queued','fetching','fitting','current_ready','complete','failed']);
  var LABELS = { queued:'已排队', fetching:'正在更新日线', fitting:'正在计算当前截止日', current_ready:'当前结果已可查看，正在补齐资讯', complete:'回测完成', failed:'本次回测失败' };
  function validDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
    var date = new Date(value + 'T00:00:00Z');
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0,10) === value;
  }
  function jobMatches(job, request, id) {
    if (!job || !STATES.has(job.status) || job.symbol !== request.symbol || job.requested_asof !== request.asof ||
        !/^[A-Za-z0-9_-]{1,160}$/.test(job.job_id || '') || id && job.job_id !== id) throw Error('任务身份或截止日不匹配，未替换当前结果。');
    return job;
  }
  function validateResult(raw, request, job) {
    if (!raw || raw.symbol !== request.symbol || !validDate(raw.asof) ||
        request.asof && raw.asof !== request.asof || job.asof && raw.asof !== job.asof) throw Error('结果资产或截止日不匹配，保留已有行情。');
    var ph = raw.price_history;
    if (!ph || !Array.isArray(ph.dates) || !ph.dates.length || !Array.isArray(ph.close) || ph.close.length !== ph.dates.length ||
        ph.dates.some(function (date,index) { return !validDate(date) || date > raw.asof || index>0 && date<=ph.dates[index-1] || !Number.isFinite(ph.close[index]) || ph.close[index]<=0; }) || ph.dates[ph.dates.length - 1] !== raw.asof) throw Error('结果包含截止日之外的数据或缺少精确日线，未替换当前结果。');
    return raw;
  }
  function controller(options) {
    var api = options.api, clock = options.clock || {
      setTimeout:function(fn,delay){return setTimeout(fn,delay);},
      clearTimeout:function(id){clearTimeout(id);}
    };
    var generation = 0, timer = null, disposed = false, active = null, shownStage = '', disconnected = 0;
    function notify(value) { if (!disposed && options.onState) options.onState(value); }
    function stopTimer() { if (timer !== null) clock.clearTimeout(timer); timer = null; }
    function isActive(token) { return !disposed && token === generation; }
    function schedule(token) { stopTimer(); if (isActive(token)) timer = clock.setTimeout(function () { void poll(token); }, options.pollMs || 2000); }
    async function accept(job, token) {
      if (!isActive(token)) return;
      jobMatches(job, active.request, active.id); active.id = job.job_id;
      notify({ status:job.status === 'complete' && shownStage !== 'complete' ? 'reading_result' : job.status, job:job, request:active.request, busy:job.status !== 'failed' && (job.status !== 'complete' || shownStage !== 'complete') });
      if (job.status === 'failed') { stopTimer(); return; }
      if ((job.status === 'current_ready' || job.status === 'complete') && shownStage !== job.status) {
        var request = active.request;
        var raw = await api.analysisResult(job.job_id);
        if (!isActive(token)) return;
        validateResult(raw, request, job);
        api.clearCache(request.symbol, raw.asof);
        if (!request.asof) api.clearCache(request.symbol, null);
        if (options.onResult) await options.onResult(raw, request, job);
        if (!isActive(token)) return;
        shownStage = job.status;
        notify({status:job.status,job:job,request:request,busy:job.status!=='complete'});
      }
      if (job.status !== 'complete') schedule(token);
    }
    async function poll(token) {
      if (!isActive(token) || !active) return;
      try { var job = await api.analysisJob(active.id); if (!isActive(token)) return; await accept(job,token); if (isActive(token)) disconnected = 0; }
      catch (error) {
        if (!isActive(token)) return;
        disconnected++;
        notify({status:'connection_error',message:error.message,busy:disconnected < 3,request:active.request,job_id:active.id});
        if (disconnected < 3) schedule(token);
      }
    }
    return {
      start:async function (request) {
        if (disposed) return;
        stopTimer(); var token = ++generation; shownStage = ''; disconnected = 0;
        active = {request:{symbol:request.symbol,asof:request.asof || null},id:null};
        if (active.request.asof && !validDate(active.request.asof)) { notify({status:'invalid',message:'请选择有效日期，或留空使用最新完整日线。',busy:false}); return; }
        notify({status:'submitting',request:active.request,busy:true});
        try { var job = await api.startAnalysis(active.request); if (isActive(token)) await accept(job,token); }
        catch (error) { if (isActive(token)) notify({status:'connection_error',message:error.message,busy:false,request:active.request,job_id:active.id}); }
      },
      resume:function () { if (active && active.id && !disposed) { disconnected=0; notify({status:'checking',busy:true,job_id:active.id}); void poll(generation); } },
      dispose:function () { disposed=true; generation++; stopTimer(); },
    };
  }
  function attach(options) {
    var doc=options.document, api=options.adapter.global, context=options.context;
    var host=doc.getElementById('global-analysis'), button=doc.getElementById('global-analysis-run'), input=doc.getElementById('global-analysis-asof');
    var status=doc.getElementById('global-analysis-status'), bar=doc.getElementById('global-analysis-progress'), resume=doc.getElementById('global-analysis-resume');
    if (!host || !api || !api.isAsset(context.code)) return { dispose:function () {} };
    host.hidden=true; input.value=context.asof || ''; button.disabled=true;
    var enabled=false, stopped=false;
    var runner=controller({api:api,onResult:options.onResult,onState:function (state) {
      button.disabled=!enabled || state.busy; input.disabled=!!state.busy;
      button.textContent=state.busy ? '计算进行中…' : state.status==='complete' ? '重新运行回测' : '运行回测';
      resume.hidden=!(state.status==='connection_error' && state.job_id && !state.busy);
      host.dataset.status=state.status;
      var labels=Object.assign({submitting:'正在提交所选截止日',checking:'正在查询原任务',reading_result:'计算完成，正在读取结果',invalid:'日期无效',connection_error:'连接暂不可用'},LABELS);
      var text=labels[state.status] || state.status;
      if (state.request) text+=' · '+(state.request.asof || '最新完整交易日');
      var progress=state.job && state.job.progress;
      if (progress && Number.isInteger(progress.expected) && progress.expected>0 && Number.isInteger(progress.completed) && progress.completed>=0) {
        bar.hidden=false; bar.max=progress.expected; bar.value=Math.min(progress.completed,progress.expected); text+=' · '+progress.completed+'/'+progress.expected+' 个窗口';
      } else bar.hidden=true;
      if (state.message) text+='。'+state.message;
      if (state.status==='failed' && state.job && state.job.error) text+='。'+String(state.job.error);
      status.textContent=text+(state.status==='complete' ? '。图表与余震结果已更新。' : '。已有行情仍可操作。');
    }});
    button.addEventListener('click',function () { if (enabled && !button.disabled) void runner.start({symbol:context.code,asof:input.value || null}); });
    resume.addEventListener('click',function () { runner.resume(); });
    api.capabilities().then(function (capabilities) {
      if (stopped) return;
      enabled=!!(capabilities && capabilities.available && Array.isArray(capabilities.symbols) && capabilities.symbols.indexOf(context.code)>=0);
      button.disabled=!enabled;
      host.hidden=!enabled;
      if (!enabled) return;
      status.textContent='只计算所选截止日；留空使用最新完整日线，计算时行情仍可浏览。';
      host.dataset.status=enabled?'available':'unavailable';
    }).catch(function () { if (!stopped) { host.hidden=true;host.dataset.status='unavailable'; } });
    return {dispose:function () { stopped=true;runner.dispose(); }};
  }
  return {validDate:validDate,jobMatches:jobMatches,validateResult:validateResult,controller:controller,attach:attach};
});
