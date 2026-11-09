(function (root) {
  'use strict';
  const I = root.InvestorInfo, $ = id => document.getElementById(id);
  const E = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const F = I.finite, n = value => F(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—';
  const percent = value => F(value) ? (value * 100).toFixed(1) + '%' : '—';
  const amount = value => F(value) ? (value / 1e8).toFixed(2) + '亿' : '—';
  const tint = value => F(value) ? value > 0 ? 'up' : value < 0 ? 'down' : '' : '';
  const titles = { overview: '盘面总览', themes: '题材与连板', news: '资讯与公告', calendar: '事件日历', stocks: '我的自选', notebook: '复盘笔记', sources: '数据与来源' };
  const labels = { fresh: '已取得', partial: '部分数据', stale: '旧数据', blocked: '来源待核验', not_available: '暂无资料', error: '读取失败', source_unavailable: '来源未接通' };
  const sectionNames = { news: '公司与市场新闻', announcements: '公司公告', reports: '研报索引', events: '事件日历', profile: '公司概况', financials: '财务资料', shareholders: '股东信息', unlock: '限售解禁', dragon_tiger: '龙虎榜', fund_flow: '资金流历史' };
  let storage;
  try { storage = root.localStorage; } catch { /* Private browsing remains usable. */ }
  const ledger = root.WorkstationLedger.create({ storage: storage || { getItem() { throw Error('unavailable'); }, setItem() { throw Error('unavailable'); } } });
  const notebook = I.createNotebook(storage);
  let params = new URLSearchParams(location.search);
  let state = { view: titles[params.get('view')] ? params.get('view') : 'overview', date: I.validDate(params.get('date')) ? params.get('date') : 'latest',
    query: (params.get('q') || '').slice(0, 80), snapshot: null, model: null, status: 'loading', topic: '', newsKind: 'all', savedOnly: false, kind: 'industry', period: 'today' };
  let selectedAsset = null, assetGeneration = 0, lastFocus = null, poll = null, newsById = new Map(), drawerPrices = [], drawerMarket = null;
  const noteDrafts = new Map();
  const noteDate = () => state.model?.asof || (state.date === 'latest' ? null : state.date);
  $('workspace-search').value = state.query;
  if (state.date !== 'latest') $('review-date').value = state.date;
  function stamp(value) { try { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }).format(new Date(value)); } catch { return '时间待核验'; } }
  function empty(title, reason, action = '') { return `<div class="empty-state"><span class="pill quiet">暂无已核验资料</span><h3>${E(title)}</h3><p>${E(reason)}</p>${action}</div>`; }
  function head(title, subtitle) { return `<div class="section-head"><div><p class="eyebrow">${E(state.model?.asof || state.date)}</p><h2>${E(title)}</h2></div><p>${E(subtitle)}</p></div>`; }
  function urlState(push = false) {
    const u = new URL(location.href); u.search = ''; u.searchParams.set('view', state.view);
    if (state.date !== 'latest') u.searchParams.set('date', state.date);
    if (state.query) u.searchParams.set('q', state.query);
    history[push ? 'pushState' : 'replaceState'](null, '', u);
  }
  function navigate(view) { if (!titles[view]) return; state.view = view; urlState(true); render(); }
  function knowledgeNotice(snapshot = state.snapshot) {
    const c = snapshot?.investor_context;
    return c ? `<p class="notice">资讯资料日 ${E(c.asof)} · 知识截止 ${E(c.available_at_cutoff || '未记录')}。后来取得的回溯资料不代表当时已知。</p>` : '';
  }
  function stockButton(r) { return `<button type="button" class="asset" data-asset="${E(r.symbol)}"><b>${E(r.name || r.symbol)}</b><span>${E(r.code || r.symbol?.slice(2))}</span></button>`; }
  function stockTable(list) {
    if (!list.length) return empty('没有匹配的股票', state.query || state.topic ? '试着清除搜索或题材筛选。' : '当前快照没有可展示的股票明细。');
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>股票 / 代码</th><th class="right">连板</th><th>首封</th><th>题材与涨停原因</th><th>自选</th></tr></thead><tbody>${list.map(r => `<tr><td>${stockButton(r)}</td><td class="right">${E(r.streak ?? '—')}</td><td>${E(r.limit_time || '—')}</td><td class="reason-cell"><div class="tags">${(r.topics || []).map(t => `<span class="tag">${E(t)}</span>`).join('')}</div>${E(r.reason || '来源未提供原因')}</td><td><button type="button" data-watch="${E(r.symbol)}" aria-label="${E(ledger.isWatched(r) ? '移出自选 ' : '加入自选 ')}${E(r.name)}" aria-pressed="${ledger.isWatched(r)}">${ledger.isWatched(r) ? '★' : '☆'}</button></td></tr>`).join('')}</tbody></table></div>`;
  }
  function coverage() { const m = state.model; return m ? `${m.complete ? '完整涨停池' : '部分明细'} ${m.sampleCount}/${m.total ?? '总数未知'} · 仅描述已封存样本` : '尚无快照'; }
  function boardPanel(limit = 10) {
    const list = I.boardRows(state.model, state.kind, state.period, state.query).slice(0, limit);
    if (!list.length) return empty('该板块分类暂无数据', '源缺失时不使用其他分类替代。');
    const max = Math.max(1, ...list.filter(x => F(x.net)).map(x => Math.abs(x.net)));
    return `<div class="board-list">${list.map(r => `<div class="board-row"><span>${E(r.name)}</span><div class="bar-track" aria-hidden="true">${F(r.net) ? `<div class="bar-fill ${r.net < 0 ? 'negative' : ''}" style="width:${Math.min(100, Math.abs(r.net) / max * 100).toFixed(2)}%"></div>` : ''}</div><small class="${tint(r.net)}">${E(amount(r.net))}</small></div>`).join('')}</div><p class="footnote">供应商资金净额口径，单位人民币；缺值保留“—”。</p>`;
  }
  function overview() {
    const m = state.model, c = m.counts;
    return head('盘面总览', '数据截止日与阅读日分开记录') +
      `<div class="metric-grid">${[['涨停', c.zt, '已封存计数', 'up'], ['跌停', c.dt, '已封存计数', 'down'], ['炸板', c.zb, '触及涨停后未封住', ''], ['炸板率', percent(c.breakRate), '炸板 /（涨停 + 炸板）', '']].map(([title, value, note, color]) => `<article class="metric"><label>${title}</label><strong class="${color}">${typeof value === 'string' ? value : n(value)}</strong><small>${note}</small></article>`).join('')}</div>` +
      `<div class="split-grid"><div><section class="panel"><div class="label"><h3>连板观察</h3><button data-go="themes" class="text-link">查看完整列表 ↗</button></div>${stockTable(I.selectStocks(m, { query: state.query }).slice(0, 7))}<p class="footnote">${E(coverage())}。不据部分明细推断全市场连板排名。</p></section><section class="panel"><div class="label"><h3>次日晋级</h3><span class="pill quiet">历史描述</span></div>${progressionPanel()}</section></div><div><section class="panel"><div class="label"><h3>行业资金一览</h3><a class="text-link" href="market.html#s-board">热力图 ↗</a></div>${boardPanel(8)}</section><section class="panel"><div class="label"><h3>资料进度</h3><button data-go="sources" class="text-link">查看来源 ↗</button></div>${['news', 'announcements', 'events'].map(key => { const s = I.section(state.snapshot, key); return `<div class="event-row"><span>${sectionNames[key]}</span><span class="muted">${E(labels[s.status] || s.status)} · ${s.rows.length} 条</span></div>`; }).join('')}<p class="footnote">未接通的栏目保留真实状态，不用演示文章补齐。</p></section></div></div>`;
  }
  function progressionPanel() {
    const p = state.model.progression;
    if (!p.rows?.length) return empty('晋级结果尚不完整', p.stale_reason || '需要两个相邻交易日完整涨停池；未取得的数据不显示为零。');
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>前日连板</th><th>样本</th><th>晋级</th><th>晋级率</th></tr></thead><tbody>${p.rows.map(r => `<tr><td>${E(r.from_streak ?? '—')} → ${E(r.to_streak ?? '—')}</td><td>${n(r.eligible_count)}</td><td>${n(r.advanced_count)}</td><td>${percent(r.rate)}</td></tr>`).join('')}</tbody></table></div><p class="footnote">${E(p.prior_asof || '前日待核验')} → ${E(p.asof)} · 历史描述，不是下一日晋级概率。</p>`;
  }
  function themes() {
    const m = state.model, list = I.selectStocks(m, { query: state.query, topic: state.topic });
    const levels = [...new Set(list.map(r => r.streak).filter(F))].sort((a, b) => b - a);
    return head('题材与连板', coverage()) +
      `<div class="filters"><button data-topic="" aria-pressed="${!state.topic}">全部题材</button>${state.topic ? `<span class="pill">筛选：${E(state.topic)}</span>` : ''}</div>` +
      (m.topics.length ? `<div class="topic-grid">${m.topics.filter(r => !state.query || r.name.includes(state.query) || r.codes.some(code => code.includes(state.query))).map(r => `<button class="topic-card" data-topic="${E(r.name)}" aria-pressed="${state.topic === r.name}"><strong>${E(r.name)}</strong><span><b>${r.count}</b>个已记录标签</span></button>`).join('')}</div>` : empty('题材标签尚未封存', '只有来源明确提供的标签才会进入题材库，不根据公司名称猜测。')) +
      `<section class="panel"><div class="label"><h3>连板梯队</h3><span class="pill quiet">${m.complete ? '完整涨停池' : '样本视图'}</span></div>${levels.length ? levels.map(level => `<div class="ladder-line"><strong>${level}板</strong><div class="ladder-cards">${list.filter(r => r.streak === level).map(r => `<button data-asset="${E(r.symbol)}">${E(r.name)}<small>${E(r.code)} · ${E(r.limit_time || '首封未知')}</small></button>`).join('')}</div></div>`).join('') : empty('无可展示的梯队', '当前筛选没有带连板数的记录。')}</section>` +
      `<section class="panel"><h3>涨停原因与股票明细</h3>${stockTable(list)}</section>` +
      `<section class="panel"><div class="label"><h3>板块资金</h3><a href="market.html#s-board" class="text-link">完整热力图 ↗</a></div><div class="filters">${Object.entries({ industry: '行业', concept: '概念', region: '地域' }).map(([k, v]) => `<button data-kind="${k}" aria-pressed="${state.kind === k}">${v}</button>`).join('')}${Object.entries({ today: '当日', '5d': '5日', '10d': '10日' }).map(([k, v]) => `<button data-period="${k}" aria-pressed="${state.period === k}">${v}</button>`).join('')}</div>${boardPanel(20)}</section>`;
  }
  function news() {
    const kinds = state.newsKind === 'all' ? ['news', 'announcements', 'reports'] : [state.newsKind];
    const list = I.newsRows(state.snapshot, kinds, { query: state.query, onlySaved: state.savedOnly, saved: notebook.snapshot().bookmarks.map(x => x.id) });
    newsById = new Map(list.map(r => [r.id, r]));
    const statuses = kinds.map(k => ({ key: k, section: I.section(state.snapshot, k) }));
    return head('资讯与公告', '只保存标题与原文索引，按时间排列') + knowledgeNotice() +
      `<div class="filters">${Object.entries({ all: '全部', news: '新闻', announcements: '公告', reports: '研报' }).map(([k, v]) => `<button data-news-kind="${k}" aria-pressed="${state.newsKind === k}">${v}</button>`).join('')}<button id="toggle-saved" aria-pressed="${state.savedOnly}">只看已收藏</button></div>` +
      `<section class="panel">${list.length ? list.map(r => `<article class="news-item"><time datetime="${E(r.published_at)}">${E(stamp(r.published_at))}</time><div><h3><a href="${E(r.url)}" target="_blank" rel="noopener noreferrer">${E(r.title)} ↗</a></h3><p>${E(r.source)} · ${E(sectionNames[r.kind])}${r.symbol ? ` · <button data-asset="${E(r.symbol)}">${E(r.symbol)}</button>` : ''}</p></div><button data-bookmark="${E(r.id)}" aria-label="${E(notebook.snapshot().bookmarks.some(x => x.id === r.id) ? '取消收藏' : '收藏文章')}">${notebook.snapshot().bookmarks.some(x => x.id === r.id) ? '★' : '☆'}</button></article>`).join('') : empty(state.savedOnly ? '当前筛选没有收藏记录' : '当前没有可展示的资讯', state.query ? '可清除搜索后再查看；缺失资料不会从其他日期补入。' : '资讯服务尚未提供可公开展示的索引。接通后可在这里检索、筛选来源并收藏原文。')}</section>` +
      `<div class="source-grid">${statuses.map(({ key, section: s }) => `<article class="source-card"><h3>${sectionNames[key]}</h3><span class="pill quiet">${E(labels[s.status] || s.status)}</span><p>${E(s.source?.source_id || '来源未接通')} · ${E(s.asof || state.model?.asof || '数据日未知')}</p><p>来源取得 ${E(s.source?.available_at || '未记录')}</p><p>${E(s.vintage_status === 'retrieved_after_asof' ? '后来取得的回溯资料，不代表当时已知' : s.stale_reason || '已取得描述性索引，不包含付费正文。')}</p></article>`).join('')}</div>`;
  }
  function calendar() {
    const sections = ['events', 'unlock'].map(key => ({ key, section: I.section(state.snapshot, key) }));
    const list = sections.flatMap(({ key, section: s }) => s.rows.map(row => ({ ...row, kind: key, source: s.source })))
      .filter(r => I.validDate(r.event_date) && (!state.query || JSON.stringify(r).includes(state.query))).sort((a, b) => a.event_date.localeCompare(b.event_date));
    return head('事件日历', '事件发生日与当时已知时间分别展示') + knowledgeNotice() + `<div class="notice">未来日程来自已取得的计划，可能修订；不表示事件结果或交易方向。</div><section class="panel">${list.length ? list.map(r => `<article class="event-row"><time>${E(r.event_date)}</time><div><b>${E(r.title || r.type || '解禁事件')}</b><p>${r.symbol ? `<button data-asset="${E(r.symbol)}">${E(r.symbol)}</button>` : ''} · ${E(r.source?.source_id || '来源待核验')}</p><p>已知时间 ${E(r.known_at || '未记录')} · 来源取得 ${E(r.source?.available_at || '未记录')}</p>${I.safeUrl(r.url) ? `<a class="text-link" href="${E(I.safeUrl(r.url))}" target="_blank" rel="noopener noreferrer">原始公告 ↗</a>` : ''}</div></article>`).join('') : empty('该复盘日没有可读取的事件日历', sections.map(x => `${sectionNames[x.key]}：${x.section.stale_reason || labels[x.section.status] || x.section.status}`).join('；'))}</section>`;
  }
  function stocks() {
    const saved = ledger.snapshot(), matches = saved.watchlist.filter(r => !state.query || `${r.name} ${r.code}`.includes(state.query)).map(r => state.model?.stocks.find(s => s.code === r.code) || { ...r, symbol: I.symbol(r.symbol || r.code), topics: [] }).filter(r => r.symbol);
    return head('我的自选', '与个股工作站共用本机自选记录') + `<section class="panel">${matches.length ? stockTable(matches) : empty('先关注一只股票', '在题材或连板列表点“☆”，也可以在上方输入股票代码查看资料。不会自动启动拟合。')}</section><section class="panel"><h3>最近查看与分析</h3>${saved.recent.length ? `<div class="ladder-cards">${saved.recent.filter(r => I.symbol(r.symbol || r.code)).slice(0, 12).map(r => `<button data-asset="${E(I.symbol(r.symbol || r.code))}">${E(r.name || r.code)}<small>资料 ${E(r.asof || '未知')} · 分析 ${E(r.analysis_asof || '未记录')}</small></button>`).join('')}</div>` : empty('尚无记录', '浏览记录与模型分析记录分别保存。')}<p class="footnote">仅保存在当前浏览器，未启用账户或跨设备同步。</p></section>`;
  }
  function notes() {
    const saved = notebook.snapshot();
    const list = saved.notes.filter(r => (state.date === 'latest' || r.asof === state.date) && (!state.query || `${r.body} ${r.symbol || ''}`.includes(state.query)));
    return head('复盘笔记', '个人记录，不作为模型证据或回测标签') + `<section class="panel"><form id="note-form" class="note-form"><label for="note-body">记录 ${E(state.model?.asof || state.date)} 的盘面与待验证事项</label><textarea id="note-body" maxlength="4000" required placeholder="例如：今天观察到什么？哪些资料仍需查证？明日要核对什么？"></textarea><button type="submit">保存复盘笔记</button><span id="note-feedback" role="status" class="muted">${saved.persistent ? '保存在本机，可导出备份。' : '浏览器存储不可用，当前只保存在内存，请及时导出。'}</span></form></section><section class="panel"><div class="label"><h3>笔记与原文收藏</h3><button id="export-notebook">导出 JSON 备份</button></div>${list.length ? list.map(r => `<article class="note-card"><small>${E(r.asof)} · 记录于 ${E(stamp(r.created_at))}</small><p>${E(r.body)}</p></article>`).join('') : '<p class="muted">当前筛选没有笔记。</p>'}${saved.bookmarks.map(r => I.safeUrl(r.url) ? `<article class="note-card"><a href="${E(I.safeUrl(r.url))}" target="_blank" rel="noopener noreferrer">${E(r.title)} ↗</a><p class="muted">${E(r.source || '原文收藏')} · 收藏于 ${E(stamp(r.saved_at))}</p></article>` : '').join('')}</section>`;
  }
  function sources() {
    const items = Object.entries(state.model?.sources || {});
    return head('数据与来源', '先核对口径，再使用数据') + `<div class="notice">当前资料是 ${E(state.model?.asof || '未知日期')} 的封存数据。抓取时间、事件时间和模型首次可见时间不是同一件事。</div><div class="source-grid">${items.map(([key, s]) => `<article class="source-card"><h3>${E(key)}</h3><span class="pill quiet">${E(labels[s.status] || (s.ok === true ? '已取得' : s.ok === false ? '本次失败' : '状态待核验'))}</span><p>${E(s.url_host || s.source_id || '来源待核验')}</p><p>抓取 ${E(s.fetched_at || '未记录')}</p><details><summary>证据与失败说明</summary><p>哈希 ${E(s.raw_sha256 || '旧快照未记录')}</p><p>${E(s.stale_reason || s.error || '未声明额外失败原因')}</p></details></article>`).join('')}</div><section class="panel"><h3>当前功能边界</h3><p class="muted">盘面与题材由已有日终快照整理；新闻、公告、研报、公司资料和事件由独立资讯契约提供。未取得的栏目单独显示缺失原因。盘中六时点、实时盘口、多用户同步和付费资讯需另行接通。</p><p class="footnote">资讯不修改 LPPL 数据序列、参数、过滤规则或顶部区间。</p></section>`;
  }
  function render() {
    document.querySelectorAll('[data-view]').forEach(a => { if (a.dataset.view === state.view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    if (!state.model && !['stocks', 'notebook'].includes(state.view)) {
      $('workspace-content').innerHTML = head(titles[state.view], '独立信息工作台') + empty(state.status === 'loading' ? '正在读取封存资料' : '这个日期暂无可用快照', state.error || '已有资料会先展示，读取资讯不会启动模型计算。', '<button id="retry-context">重新读取</button>'); return;
    }
    $('workspace-content').innerHTML = ({ overview, themes, news, calendar, stocks, notebook: notes, sources }[state.view])();
    if ($('note-body')) { $('note-body').value = noteDrafts.get(noteDate()) || ''; $('note-body').dataset.asof = noteDate() || ''; }
  }
  const reader = I.createReader(root.LPPL, next => {
    state.status = next.status; state.error = next.error || null; state.snapshot = next.snapshot; state.model = I.review(next.snapshot);
    if (state.model && state.date === 'latest') $('review-date').value = state.model.asof;
    $('snapshot-label').textContent = state.model ? `${state.model.complete ? '完整池' : '部分明细'} · ${state.model.asof}` : '';
    $('context-message').textContent = next.status === 'loading' ? '正在读取，已有同日资料仍可查看…' : next.status === 'error' ? `${next.error}${next.snapshot ? '；保留同日期已有快照' : ''}` : `已读取 ${state.model?.asof} 封存快照 · ${next.status === 'stale' ? '刷新滞后' : '不是实时行情'} · ${reader.pollingEnabled() ? '最新视图每5分钟检查更新' : '当前读取仓库内已有快照'}`;
    render();
  });
  function setDate(date) {
    if (date !== 'latest' && !I.validDate(date)) { $('context-message').textContent = '请选择有效日期'; return; }
    state.date = date; state.topic = ''; assetGeneration++; if ($('stock-dossier').open) $('stock-dossier').close(); urlState(true); void reader.get(date);
  }
  function readAssetInfo(asset, market) {
    const snapshot = market && (state.date === 'latest' || market.asof === state.date) ? market : { asof: state.model?.asof };
    return knowledgeNotice(snapshot) + ['profile', 'financials', 'shareholders', 'dragon_tiger', 'fund_flow', 'unlock', 'announcements', 'news', 'reports', 'events'].map(key => {
      const s = I.section(snapshot, key, asset.symbol);
      return `<details${key === 'profile' ? ' open' : ''}><summary>${sectionNames[key]} <span class="pill quiet">${E(labels[s.status] || s.status)} · ${s.rows.length}</span></summary>${s.rows.length ? `<p class="footnote">${E(s.source?.source_id || '来源待核验')} · 数据 ${E(s.asof)} · 取得 ${E(s.source?.available_at || '未记录')}${s.vintage_status === 'retrieved_after_asof' ? ' · 后来取得的回溯资料，不代表当时已知' : ''}</p>` + s.rows.slice(0, 30).map(row => {
        if (['news', 'announcements', 'reports'].includes(key)) return `<p>${I.safeUrl(row.url) ? `<a href="${E(I.safeUrl(row.url))}" target="_blank" rel="noopener noreferrer">${E(row.title)} ↗</a>` : E(row.title)}<small class="muted"> ${E(row.published_at)}</small></p>`;
        const labels = { name: '名称', industry: '行业', region: '地区', listing_date: '上市日', description: '简介', title: '事件', event_date: '事件日', report_period: '报告期', published_at: '发布时点', known_at: '已知时间', metric: '指标', value: '数值', unit: '单位', currency: '币种', date: '数据日', main_net: '主力净额（元）', net_buy: '净买额（元）', buy_amount: '买入额（元）', sell_amount: '卖出额（元）', turnover_pct: '换手率（%）', reason: '来源说明', type: '类型', holder_name: '股东', shares: '持股（股）', ownership_pct: '持股占比（%）', change_shares: '持股变化（股）', ratio_pct: '占比（%）', quantity: '数量（单位见下）' };
        const fields = Object.entries(row).filter(([k, v]) => Object.hasOwn(labels, k) && ['string', 'number'].includes(typeof v));
        return `<dl>${fields.map(([k, v]) => `<dt>${labels[k]}</dt><dd>${E(v)}</dd>`).join('')}</dl>`;
      }).join('') : `<p class="muted">${E(s.stale_reason || '当前没有可展示的资料')}</p>`}</details>`;
    }).join('');
  }
  function drawDossier() {
    const canvas = $('dossier-chart'); if (!canvas || !drawerPrices.length) return;
    const index = Number($('dossier-range')?.value ?? drawerPrices.length - 1);
    root.CandleChart.draw(canvas, drawerPrices, index);
    $('dossier-bar').textContent = root.CandleChart.describe(drawerPrices[index], drawerMarket?.volume_unit);
  }
  async function openAsset(value) {
    const sym = I.symbol(value); if (!sym) return;
    const asset = state.model?.stocks.find(r => r.symbol === sym) || ledger.snapshot().watchlist.find(r => I.symbol(r.symbol || r.code) === sym) || { name: sym, symbol: sym, code: sym.slice(2) };
    selectedAsset = { ...asset, symbol: sym, code: sym.slice(2) }; const token = ++assetGeneration;
    lastFocus = document.activeElement; $('dossier-title').textContent = asset.name || sym; $('dossier-symbol').textContent = sym;
    $('dossier-watch').textContent = ledger.isWatched(selectedAsset) ? '移出自选' : '加入自选';
    $('dossier-workstation').href = 'stock.html?code=' + encodeURIComponent(sym.slice(2));
    $('dossier-body').innerHTML = `<section class="panel"><h3>已封存盘面资料</h3><p>${E(asset.reason || '当前快照没有该股票的涨停原因')}</p><p class="muted">复盘日 ${E(state.model?.asof || state.date)} · ${E((asset.topics || []).join(' / ') || '题材未记录')}</p></section><div id="dossier-market">${empty('正在独立读取行情', '只读取行情与已有资料，不运行 LPPL。')}</div><div id="dossier-info">${readAssetInfo(selectedAsset, null)}</div>`;
    if (!$('stock-dossier').open) $('stock-dossier').showModal();
    ledger.touchRecent(selectedAsset);
    if (state.date !== 'latest') { $('dossier-market').innerHTML = empty('历史资料仅读取当日封存', '当前没有该资产的当日行情回执；不会以今天的公司资料补填。'); return; }
    try {
      const market = await root.LPPL.stock.market(sym.slice(2));
      if (token !== assetGeneration || !$('stock-dossier').open) return;
      if (market.symbol && market.symbol !== sym) throw Error('行情资产不匹配');
      if (typeof market.name === 'string' && market.name.trim()) { selectedAsset.name = market.name.trim(); $('dossier-title').textContent = selectedAsset.name; ledger.touchRecent(selectedAsset); }
      drawerMarket = market; drawerPrices = root.CandleChart.normalize(market.price).slice(-120);
      $('dossier-info').innerHTML = readAssetInfo(selectedAsset, market);
      $('dossier-market').innerHTML = drawerPrices.length ? `<section class="panel"><h3>日 K 线与成交量</h3><p class="footnote">行情 ${E(market.asof)} · ${E(root.CandleChart.adjustmentLabel(market.adjustment))} · ${E(market.source || '来源待核验')} · ${market.stale ? '旧行情' : '已缓存行情'}</p><canvas id="dossier-chart" aria-label="最近120条日K线与成交量"></canvas><label for="dossier-range" class="sr-only">逐日查看OHLC与成交量</label><input id="dossier-range" type="range" min="0" max="${drawerPrices.length - 1}" value="${drawerPrices.length - 1}"><p id="dossier-bar" class="footnote"></p></section>` : empty('行情暂不可用', '响应没有可展示的日线。');
      drawDossier();
    } catch { if (token === assetGeneration && $('stock-dossier').open) $('dossier-market').innerHTML = empty('行情服务暂未就绪', '当前环境尚未配置可用行情入口，或该请求失败。封存资料和自选仍可使用。'); }
  }
  document.addEventListener('click', event => {
    const target = event.target.closest('button,a'); if (!target) return;
    if (target.dataset.view) { event.preventDefault(); navigate(target.dataset.view); }
    else if (target.dataset.go) navigate(target.dataset.go);
    else if (target.dataset.asset) void openAsset(target.dataset.asset);
    else if (target.dataset.watch) { const asset = state.model?.stocks.find(r => r.symbol === target.dataset.watch) || { symbol: target.dataset.watch, code: target.dataset.watch.slice(2) }; ledger.toggleWatch(asset); render(); }
    else if (target.hasAttribute('data-topic')) { state.topic = target.dataset.topic; render(); }
    else if (target.dataset.kind) { state.kind = target.dataset.kind; render(); }
    else if (target.dataset.period) { state.period = target.dataset.period; render(); }
    else if (target.dataset.newsKind) { state.newsKind = target.dataset.newsKind; render(); }
    else if (target.dataset.bookmark) { notebook.toggleBookmark(newsById.get(target.dataset.bookmark) || {}); render(); }
    else if (target.id === 'toggle-saved') { state.savedOnly = !state.savedOnly; render(); }
    else if (target.id === 'retry-context') void reader.get(state.date);
    else if (target.id === 'export-notebook') { const url = URL.createObjectURL(new Blob([notebook.exportJSON()], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = 'lppl-review-notebook.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  });
  $('search-form').addEventListener('submit', event => {
    event.preventDefault(); state.query = $('workspace-search').value.trim().slice(0, 80); urlState(); render();
    const sym = I.symbol(state.query) || state.model?.stocks.find(r => r.name === state.query)?.symbol; if (sym) void openAsset(sym);
  });
  $('workspace-search').addEventListener('input', event => { state.query = event.target.value.trim().slice(0, 80); urlState(); render(); });
  $('load-date').addEventListener('click', () => setDate($('review-date').value));
  $('load-latest').addEventListener('click', () => setDate('latest'));
  $('refresh-context').addEventListener('click', () => void reader.get(state.date));
  $('close-dossier').addEventListener('click', () => $('stock-dossier').close());
  $('stock-dossier').addEventListener('close', () => { assetGeneration++; drawerPrices = []; lastFocus?.focus?.(); });
  $('dossier-watch').addEventListener('click', () => { if (selectedAsset) { ledger.toggleWatch(selectedAsset); $('dossier-watch').textContent = ledger.isWatched(selectedAsset) ? '移出自选' : '加入自选'; render(); } });
  $('dossier-body').addEventListener('input', event => { if (event.target.id === 'dossier-range') drawDossier(); });
  document.addEventListener('submit', event => {
    if (event.target.id !== 'note-form') return; event.preventDefault();
    try { const asof = $('note-body').dataset.asof; const saved = notebook.addNote({ asof, body: $('note-body').value, snapshotHash: state.snapshot?.snapshot_sha256 || null }); noteDrafts.delete(asof); render(); $('note-feedback').textContent = saved.persistent ? '已保存在本机；这是个人记录，不是模型证据。' : '仅保存在内存，关闭页面将丢失，请导出备份。'; }
    catch (error) { $('note-feedback').textContent = error.message; }
  });
  document.addEventListener('input', event => { if (event.target.id === 'note-body') noteDrafts.set(event.target.dataset.asof || null, event.target.value); });
  root.addEventListener('popstate', () => {
    const p = new URLSearchParams(location.search);
    state.view = titles[p.get('view')] ? p.get('view') : 'overview'; state.query = p.get('q') || ''; state.date = I.validDate(p.get('date')) ? p.get('date') : 'latest';
    $('workspace-search').value = state.query; $('review-date').value = state.date === 'latest' ? '' : state.date; assetGeneration++;
    if ($('stock-dossier').open) $('stock-dossier').close(); void reader.get(state.date);
  });
  root.addEventListener('resize', drawDossier);
  root.addEventListener('storage', () => { if (state.view === 'stocks') render(); });
  function updatePolling() { if (poll) clearInterval(poll); poll = null; if (!document.hidden && reader.pollingEnabled()) poll = setInterval(() => { if (state.date === 'latest') void reader.get('latest'); }, 300000); }
  document.addEventListener('visibilitychange', updatePolling);
  root.addEventListener('pagehide', () => { if (poll) clearInterval(poll); reader.destroy(); assetGeneration++; });
  void reader.get(state.date); updatePolling();
})(window);
