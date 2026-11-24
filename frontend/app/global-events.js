(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.LPPLGlobalEvents=api;})(typeof window!=='undefined'?window:globalThis,function(){
  'use strict';
  var REASONS={historical_news_not_archived:'该截止日没有当时保存的新闻档案',news_not_fetched:'暂无新闻',news_refresh_due:'新闻已超过六小时刷新周期',source_access_denied:'来源拒绝本次访问，保留已有可读资料',source_fetch_failed:'本次来源读取失败',corporate_actions_not_archived:'没有当时封存的公司行动资料'};
  function dateParts(instant,timezone){
    if(typeof instant!=='string'||!/(Z|[+-]\d{2}:\d{2})$/.test(instant)||!Number.isFinite(Date.parse(instant)))return null;
    try {var values={};new Intl.DateTimeFormat('en-CA',{timeZone:timezone||'UTC',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(instant)).forEach(function(p){values[p.type]=p.value;});return {date:values.year+'-'+values.month+'-'+values.day,time:values.hour+':'+values.minute+':'+values.second};}catch(_){return null;}
  }
  function beforeCutoff(instant,asof,context){var p=dateParts(instant,context.timezone);return !!p&&(p.date<asof||p.date===asof&&p.time<=((context.market==='us'?'16:00':'15:30')+':00'));}
  function safeURL(value){try{var url=new URL(value);return /^https?:$/.test(url.protocol)&&!url.username&&!url.password?url.href:null;}catch(_){return null;}}
  function model(data,context){
    var payload=data&&data.raw&&data.raw.research&&data.raw.research.market_events;
    if(!payload)return {rows:[],markers:[],status:'unavailable',note:'当前结果没有对应的资讯档案。'};
    if(payload.schema_version!=='global_events_v1'||payload.symbol!==data.symbol||payload.model_asof!==data.modelAsOf||context.asof&&payload.mode!=='historical')return {rows:[],markers:[],status:'unavailable',note:'资讯资产、截止日或历史口径不一致，未替换为当前新闻。'};
    var excluded=0,rows=[];
    (payload.items||[]).forEach(function(item){
      var url=safeURL(item.url), published=dateParts(item.published_at,context.timezone), known=dateParts(item.known_at,context.timezone),effective=dateParts(item.event_at,context.timezone);
      if(!url||!item.title||!item.source||!known||context.asof&&(!beforeCutoff(item.known_at,data.modelAsOf,context)||item.published_at&&!beforeCutoff(item.published_at,data.modelAsOf,context))){excluded++;return;}
      var after=!beforeCutoff(item.known_at,data.modelAsOf,context);
      rows.push({id:item.id||item.hash,date:effective?effective.date:published?published.date:known.date,label:item.title,source:item.source,url:url,publishedAt:item.published_at||null,knownAt:item.known_at,effectiveAt:item.event_at||null,afterModel:after,hash:item.hash||null});
    });
    var note=(context.asof?'历史当时已保存资料':'当前资讯')+' · 模型截至 '+data.modelAsOf+' · 资讯获取 '+(payload.news_asof||payload.fetched_at||'未取得');
    if(payload.stale_reason)note+=' · '+(REASONS[payload.stale_reason]||'来源状态待核对');
    if(excluded)note+=' · 已排除 '+excluded+' 条身份、时间或链接不符合条件的记录';
    return {rows:rows,markers:rows.filter(function(row){return !row.afterModel&&row.date<=data.modelAsOf;}),status:payload.status||'unavailable',note:note};
  }
  function render(doc,view,onFocus){
    var list=doc.getElementById('event-list');list.replaceChildren();
    view.rows.slice(0,24).forEach(function(row){
      var article=doc.createElement('article');article.className='global-event';
      var link=doc.createElement('a');link.href=row.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=row.label;article.appendChild(link);
      var metaParts=['来源 '+row.source,row.publishedAt?'发布时间 '+row.publishedAt:'',row.knownAt?'首次留存 '+row.knownAt:''].filter(Boolean);
      if(metaParts.length){var meta=doc.createElement('p');meta.textContent=metaParts.join(' · ');article.appendChild(meta);}
      if(row.effectiveAt){var effective=doc.createElement('p');effective.textContent='生效日 '+row.date+'（不是公告发布时间）';article.appendChild(effective);}
      var state=doc.createElement('p');state.className='global-event-scope';state.textContent=row.afterModel?'模型截止日之后取得的当前资讯':'模型截止日前已留存的资料';article.appendChild(state);
      if(!row.afterModel&&onFocus){var button=doc.createElement('button');button.type='button';button.textContent='在图表中定位 '+row.date;button.addEventListener('click',function(){onFocus(row);});article.appendChild(button);}
      list.appendChild(article);
    });
    doc.getElementById('events-note').textContent=view.note;
    doc.getElementById('events-status').textContent=({ok:'资讯已读取',empty:'来源未返回可展示资讯',partial:'部分资料可读',stale:'已有资讯可读，等待更新',unavailable:'资讯档案未取得'})[view.status]||'资讯状态待核对';
    doc.getElementById('events-retry').disabled=false;
  }
  return {model:model,render:render,beforeCutoff:beforeCutoff,safeURL:safeURL};
});
