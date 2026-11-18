(function () {
  'use strict';
  const Core = window.ResearchPersonalCore, Workspace = window.ResearchWorkspaceCore, host = document.getElementById('research-personal');
  if (!Core || !Workspace || !host) return;
  let storage; try { storage = window.localStorage; } catch { storage = null; }
  let state = Core.load(storage), events = null, eventStatus = 'idle', eventSeq = 0, undoHolding = null;
  const $ = id => document.getElementById(id);
  const node = (tag, cls, value) => { const el = document.createElement(tag); if (cls) el.className = cls; if (value !== undefined) el.textContent = value; return el; };
  const clear = el => el.replaceChildren();
  const localDay = () => { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
  function button(label, fn, cls = 'personal-button') { const b = node('button', cls, label); b.type = 'button'; b.addEventListener('click', fn); return b; }
  function message(value, error) { $('personal-message').textContent = value; $('personal-message').classList.toggle('personal-error', !!error); }
  function persisted(next, success) {
    if (!Core.save(storage, next)) { message('未保存：存储不可用或另一页已有修改。请重新读取本机记录后再试。', true); return false; }
    state = next; message(success, false); window.dispatchEvent(new CustomEvent('research-personal-change')); return true;
  }
  function update(mutator, success) { const next = Core.normalize(state); if (state.storageIssue) next.storageIssue = state.storageIssue; mutator(next); return persisted(next, success); }
  function stocks() {
    try { const rows = window.StockWatchlist ? window.StockWatchlist.read(storage) : []; return Array.isArray(rows) ? rows : []; } catch { return []; }
  }
  function workspace() { return Workspace.load(storage); }
  function select(id) { window.dispatchEvent(new CustomEvent('workspace-select', { detail: { assetId: id } })); }
  function renderChanges() {
    const rows = Core.changes(workspace().observations), read = new Set(state.readChanges), unread = rows.filter(x => !read.has(x.id));
    $('personal-unread').textContent = unread.length + ' 条未读';
    $('changes-mark-all').disabled = unread.length === 0;
    const filtered = $('changes-filter').value === 'unread' ? unread : rows;
    clear($('personal-changes'));
    if (!filtered.length) $('personal-changes').append(node('p', 'personal-empty', rows.length ? '当前没有未读变化，可切换查看全部。' : '还没有可比较的结果变化。首次读取建立基线；只有后续区间、状态、证据或计算覆盖变化才进入这里。'));
    for (const row of filtered.slice(0, 50)) {
      const item = node('article', 'personal-change' + (read.has(row.id) ? ' is-read' : ''));
      const title = node('div', 'personal-row-title'); title.append(button(row.name, () => select(row.assetId), 'personal-link'), node('span', 'personal-tag', read.has(row.id) ? '已读' : '未读'));
      item.append(title, node('p', '', row.reasons.join(' · ')), node('p', 'personal-meta', '本机观测于 ' + row.observedAt.replace('T', ' ') + ' · 分析截止 ' + (row.asof || '未知')));
      if (row.basisChanged) item.append(node('p', 'personal-meta', '模型版本或数据版本也有变化，需要核对比较口径。'));
      item.append(button(read.has(row.id) ? '标为未读' : '标为已读', () => {
        if (update(next => { next.readChanges = read.has(row.id) ? next.readChanges.filter(x => x !== row.id) : next.readChanges.concat(row.id); }, '已更新本机已读状态。')) renderChanges();
      }));
      $('personal-changes').append(item);
    }
    if (filtered.length > 50) $('personal-changes').append(node('p', 'personal-meta', '显示最近 50 条；原始本机观测仍保留在工作台。'));
  }
  function renderAssetFilter() {
    const selectEl = $('calendar-asset'), selected = selectEl.value, ids = stocks(), saved = workspace().observations;
    clear(selectEl); const all = node('option', '', '全部自选股票'); all.value = 'all'; selectEl.append(all);
    for (const code of ids) { const obs = saved['stock:' + code] || [], name = obs.length && obs[obs.length - 1].asset.name; const option = node('option', '', (name || code) + (name ? ' · ' + code : '')); option.value = code; selectEl.append(option); }
    selectEl.value = ids.includes(selected) ? selected : 'all';
  }
  function renderEvents() {
    const el = $('personal-events'); clear(el);
    $('events-retry').disabled = eventStatus === 'loading';
    $('events-retry').textContent = eventStatus === 'loading' ? '正在读取…' : eventStatus === 'error' ? '重新读取事件' : '刷新事件';
    if (eventStatus === 'loading' && !events) { el.append(node('p', 'personal-empty', '读取事件数据，工作台其他功能可继续操作。')); return; }
    if (eventStatus === 'error' && !events) { el.append(node('p', 'personal-empty', '未取得可用的事件快照。请稍后重试；此状态不表示没有公司事件。')); return; }
    if (!events) { el.append(node('p', 'personal-empty', '展开日历时读取自选股票的事件快照。')); return; }
    $('events-asof').textContent = '快照截止 ' + events.asof + ' · 生成于 ' + (events.generated || '未知') + (eventStatus === 'error' ? ' · 刷新失败，保留上次读取内容' : '');
    const sourceBox = $('events-sources'); clear(sourceBox);
    for (const source of events.sources) {
      const coverage = events.coverage[source.type] || [];
      const status = source.status === 'ok' ? (source.stale ? '旧快照' : '源返回成功') : source.status === 'failed' ? '源读取失败' : '源状态未知';
      sourceBox.append(node('p', 'personal-meta', source.label + ' · ' + source.source + ' · ' + status + (source.staleReason ? '：' + source.staleReason : '') + ' · 采集 ' + (source.fetchedAt || '未知') + ' · 覆盖 ' + (coverage.length === 2 ? coverage.join(' 至 ') : '未提供')));
    }
    const codes = stocks(), month = $('calendar-month').value, day = $('calendar-day').value;
    const rows = Core.filterEvents(events, { codes, asset: $('calendar-asset').value, month, day });
    $('calendar-count').textContent = rows.length + ' 项';
    if (!codes.length) { el.append(node('p', 'personal-empty', '先把股票加入自选，即可查看关联事件。指数没有个股公司事件。')); return; }
    if (!rows.length) { el.append(node('p', 'personal-empty', '本快照与所选日期中没有匹配的自选事件。这不代表全量公告为空；可以清除日期筛选并查看来源覆盖范围。')); return; }
    for (const event of rows.slice(0, 100)) {
      const card = node('article', 'personal-event'), head = node('div', 'personal-row-title');
      head.append(button(event.name + ' · ' + event.code, () => select('stock:' + event.code), 'personal-link'), node('time', 'personal-date', event.date));
      card.append(head, node('p', '', event.label + ' · ' + event.status));
      if (event.description) card.append(node('p', 'personal-event-description', event.description));
      card.append(node('p', 'personal-meta', '来源 ' + event.source.source + ' · 截止 ' + event.asof), node('p', 'personal-meta', '发布 ' + (event.publishedAt || event.publicationDate || '未知') + ' · 首次采集 ' + (event.firstSeen || '未知')));
      if (day) card.append(node('p', 'personal-knowledge', Core.knowledgeAt(event, day)));
      if (event.source.status !== 'ok' || event.source.stale) card.append(node('p', 'personal-knowledge', event.source.staleReason || '该来源当前不可确认新鲜度，请核对原始公告。'));
      el.append(card);
    }
    if (rows.length > 100) el.append(node('p', 'personal-meta', '显示前 100 项，请按日期或资产缩小范围。'));
  }
  async function loadEvents() {
    if (eventStatus === 'loading') return;
    const seq = ++eventSeq; eventStatus = 'loading'; renderEvents();
    try {
      const payload = window.LPPL && typeof window.LPPL.events === 'function' ? await window.LPPL.events() : null;
      if (seq !== eventSeq) return;
      const data = Core.eventData(payload);
      if (!data) throw new Error('unavailable');
      events = data; eventStatus = 'ready'; renderEvents();
    } catch { if (seq === eventSeq) { eventStatus = 'error'; renderEvents(); } }
  }
  function renderHoldings() {
    const el = $('personal-holdings'), unit = $('holding-unit').value; clear(el);
    $('holding-count').textContent = state.holdings.length + ' 项记录';
    const total = state.holdings.reduce((sum, row) => sum + row.shares * row.cost, 0);
    $('holdings-total').textContent = state.holdings.length ? Core.amount(total, unit) : '—';
    if (!state.holdings.length) el.append(node('p', 'personal-empty', '还没有手动持仓记录。可以只填写股票代码、数量与每股成本；不会查询账户或行情。'));
    for (const row of state.holdings) {
      const card = node('article', 'personal-holding'), head = node('div', 'personal-row-title');
      const link = node('a', 'personal-link', row.name + (row.name !== row.code ? ' · ' + row.code : '')); link.href = 'stock.html?code=' + encodeURIComponent(row.code) + '&from=research-workspace';
      head.append(link, node('span', 'personal-tag', 'CNY'));
      const facts = node('dl', 'holding-facts');
      for (const [label, value] of [['数量（股）', row.shares.toLocaleString('zh-CN', { maximumFractionDigits: 6 })], ['每股成本', Core.amount(row.cost, 'yuan')], ['记录成本投入', Core.amount(row.shares * row.cost, unit)]]) { const d = node('div'); d.append(node('dt', '', label), node('dd', '', value)); facts.append(d); }
      const actions = node('div', 'personal-actions');
      actions.append(button('编辑', () => { $('holding-code').value = row.code; $('holding-name').value = row.name; $('holding-shares').value = row.shares; $('holding-cost').value = row.cost; $('holding-form-details').open = true; $('holding-code').focus(); }), button('删除记录', () => {
        if (update(next => { next.holdings = next.holdings.filter(x => x.code !== row.code); }, '记录已删除，可撤销。')) { undoHolding = row; $('holding-undo').hidden = false; renderHoldings(); }
      }));
      card.append(head, facts, node('p', 'personal-meta', '手动记录更新 ' + row.updatedAt.replace('T', ' ')), actions); el.append(card);
    }
  }
  $('changes-filter').addEventListener('change', renderChanges);
  $('changes-mark-all').addEventListener('click', () => { const ids = Core.changes(workspace().observations).map(r => r.id); if (update(next => { next.readChanges = [...new Set(next.readChanges.concat(ids))].slice(-4000); }, '变化已在本机标为已读。')) renderChanges(); });
  $('personal-reload').addEventListener('click', () => { state = Core.load(storage); message(state.storageIssue ? '仍无法读取本机存储。请先备份浏览器中的重要记录。' : '已重新读取本机记录。', !!state.storageIssue); renderChanges(); renderHoldings(); });
  $('personal-calendar').addEventListener('toggle', () => { if ($('personal-calendar').open && eventStatus === 'idle') loadEvents(); });
  $('events-retry').addEventListener('click', loadEvents);
  $('calendar-month').value = localDay().slice(0, 7);
  $('calendar-month').addEventListener('change', () => { $('calendar-day').value = ''; renderEvents(); });
  $('calendar-day').addEventListener('change', () => { if ($('calendar-day').value) $('calendar-month').value = $('calendar-day').value.slice(0, 7); renderEvents(); });
  $('calendar-asset').addEventListener('change', renderEvents);
  $('calendar-clear').addEventListener('click', () => { $('calendar-month').value = ''; $('calendar-day').value = ''; $('calendar-asset').value = 'all'; renderEvents(); });
  $('holding-unit').addEventListener('change', renderHoldings);
  $('holding-form').addEventListener('submit', event => {
    event.preventDefault();
    const row = Core.holding({ code: $('holding-code').value.trim(), name: $('holding-name').value, shares: $('holding-shares').value, cost: $('holding-cost').value, currency: 'CNY', updatedAt: new Date().toISOString() });
    if (!row) { $('holding-error').textContent = '请填写六位代码、正数股数和非负每股成本；仅支持人民币记录，数量与金额需在合理数值范围内。'; return; }
    if (state.holdings.length >= 100 && !state.holdings.some(x => x.code === row.code)) { $('holding-error').textContent = '本机最多保存 100 项持仓记录。'; return; }
    if (update(next => { next.holdings = next.holdings.filter(x => x.code !== row.code).concat(row); }, '持仓记录已保存在此浏览器。')) { $('holding-error').textContent = ''; $('holding-form').reset(); undoHolding = null; $('holding-undo').hidden = true; renderHoldings(); }
  });
  $('holding-undo').addEventListener('click', () => {
    if (!undoHolding) return;
    if (state.holdings.some(x => x.code === undoHolding.code)) { message('该股票已有新记录，撤销不会覆盖它。请手动核对。', true); return; }
    if (state.holdings.length >= 100) { message('记录已满，请先整理后再撤销。', true); return; }
    if (update(next => { next.holdings.push(undoHolding); }, '已恢复删除的持仓记录。')) { undoHolding = null; $('holding-undo').hidden = true; renderHoldings(); }
  });
  function onWorkspaceChange() { renderChanges(); renderAssetFilter(); renderEvents(); }
  window.addEventListener('workspace-change', onWorkspaceChange);
  window.addEventListener('lppl-watch', onWorkspaceChange);
  window.addEventListener('research-personal-restored', () => { state = Core.load(storage); renderChanges(); renderHoldings(); });
  window.addEventListener('storage', event => { if (event.key === Core.KEY || event.key === null) { state = Core.load(storage); undoHolding = null; $('holding-undo').hidden = true; renderHoldings(); } onWorkspaceChange(); });
  if (state.storageIssue) message('本机记录读取失败，暂不能确认保存状态。', true);
  renderChanges(); renderAssetFilter(); renderHoldings(); renderEvents();
})();
