/* Personal research workspace. All market/model reads go through LPPL.
   Browser observations are not a server revision ledger or a publication record. */
(function () {
  'use strict';
  const Core = window.ResearchWorkspaceCore;
  const API = window.LPPL;
  const $ = id => document.getElementById(id);
  if (!Core || !API) {
    $('global-message').hidden = false;
    $('global-message').textContent = '工作台组件未加载，请刷新页面。';
    return;
  }
  let storage = null;
  try { storage = window.localStorage; } catch { /* Inform the user below. */ }
  const state = Core.load(storage);
  const summaries = new Map(), errors = new Map(), drafts = new Map();
  let assets = [], generation = 0, busy = false, queuedRefresh = false, inspectRecord = null, activeNoteKey = null;
  let focusedBeforeDialog = null, restoringScroll = false;

  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const prettyTime = value => {
    const d = new Date(value || '');
    if (!Number.isFinite(d.getTime())) return '时间未提供';
    return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d);
  };
  const dateLabel = value => value || '未提供';
  const windowEvidence = w => (w.evidence === 'descriptive' ? ' · n=' + w.n + '，历史分位，不是预测' : '') +
    ' · ' + window.RuleLabels.RULES.box.source;
  const displayRuleNote = note => /占比|比例|lppls_confidence/i.test(note || '') && !String(note).includes('占比不是概率')
    ? note + '；占比不是概率'
    : note;
  const windowLabel = summary => summary?.windows?.length ? summary.windows.map(w => w.start + ' — ' + w.end + windowEvidence(w)).join('；') : '暂无可展示区间';
  const noteKey = summary => [summary?.asset?.id || '', summary?.asof || '', summary?.predictionId || '', summary?.modelVersion || ''].join('|');
  const recordList = id => Array.isArray(state.observations[id]) ? state.observations[id] : [];
  const hasChange = id => recordList(id).length > 1;
  const needsCheck = asset => errors.has(asset.id) || summaries.get(asset.id)?.stale || summaries.get(asset.id)?.status === 'unavailable';
  const groupOf = id => state.meta[id]?.group || '';
  const selectedAsset = () => assets.find(a => a.id === state.selectedId) || null;
  const summaryOf = asset => summaries.get(asset.id) || Core.summarize(asset, null, new Date().toISOString());
  const lastNote = summary => Core.notesFor(state, summary.asset.id).find(n => n.asof === summary.asof && n.predictionId === summary.predictionId && n.modelVersion === summary.modelVersion);

  function focusToken() {
    const element = document.activeElement;
    if (!element) return null;
    for (const key of ['select', 'group', 'compare', 'resume', 'inspect']) {
      if (element.dataset && element.dataset[key] !== undefined) return { element, key, value: element.dataset[key] };
    }
    return null;
  }
  function restoreFocus(token) {
    // Preserve a replaced control without taking focus from an untouched editor.
    if (!token || token.element.isConnected) return;
    const replacement = [...document.querySelectorAll('[data-' + token.key + ']')].find(el => el.dataset[token.key] === token.value);
    replacement?.focus({ preventScroll: true });
  }

  function notify(text) { $('global-message').textContent = text; $('global-message').hidden = !text; }
  function storageWarning() {
    $('storage-warning').hidden = false;
    $('storage-warning').textContent = state.storageIssue
      ? '本机研究记录无法读取，暂未覆盖。仍可浏览已发布结果；重要笔记请自行复制保存。'
      : '本次修改未保存：存储不可用、空间不足，或其他标签页已更新。请先复制重要笔记，再重新载入。';
  }
  function persist() {
    const ok = Core.save(storage, state);
    if (!ok) storageWarning();
    return ok;
  }
  function saveDraft() {
    if (activeNoteKey) drafts.set(activeNoteKey, $('research-note').value);
  }
  function announceWatch() {
    window.dispatchEvent(new CustomEvent('lppl-watch', { detail: { origin: 'research-workspace' } }));
  }
  function syncAssets() {
    const indices = window.IndexWatchlist.read(storage).map(code => {
      const known = API.SYMS.find(s => s.sym === code);
      return Core.asset('index', code, known?.name || code);
    });
    const stocks = window.StockWatchlist.read(storage).map(code => {
      const id = 'stock:' + code, old = summaries.get(id) || recordList(id).at(-1);
      return Core.asset('stock', code, old?.asset?.name || code);
    });
    assets = indices.concat(stocks).filter(Boolean);
    state.compareIds = state.compareIds.filter(id => assets.some(a => a.id === id)).slice(0, 3);
    if (!assets.some(a => a.id === state.selectedId)) state.selectedId = assets[0]?.id || null;
    if (!assets.some(a => a.id === inspectRecord?.asset?.id)) inspectRecord = null;
  }
  function groupsHTML(current, all) {
    const names = ['', ...state.groups];
    return (all ? '<option value="all">全部分组</option>' : '') + names.map(name => '<option value="' + esc(name) + '"' + (name === current ? ' selected' : '') + '>' + esc(name || '未分组') + '</option>').join('');
  }
  function renderGroups() {
    const options = [{ key: 'all', label: '全部', count: assets.length }, { key: '', label: '未分组', count: assets.filter(a => !groupOf(a.id)).length }, ...state.groups.map(name => ({ key: name, label: name, count: assets.filter(a => groupOf(a.id) === name).length }))];
    $('group-tabs').innerHTML = options.map(x => '<button type="button" data-group="' + esc(x.key) + '" aria-pressed="' + (state.groupFilter === x.key) + '">' + esc(x.label) + '<small>' + x.count + '</small></button>').join('');
  }
  function visibleAssets() {
    const q = state.query.trim().toLowerCase();
    const list = assets.filter(a => (state.groupFilter === 'all' || groupOf(a.id) === state.groupFilter) && (!q || (a.name + ' ' + a.code).toLowerCase().includes(q)) && (state.statusFilter === 'all' || (state.statusFilter === 'has_window' && summaryOf(a).windows.length > 0) || (state.statusFilter === 'needs_check' && needsCheck(a)) || (state.statusFilter === 'changed' && hasChange(a.id))));
    return list.sort((a, b) => {
      if (state.sort === 'asof') return String(summaryOf(b).asof || '').localeCompare(String(summaryOf(a).asof || '')) || a.name.localeCompare(b.name, 'zh-CN');
      if (state.sort === 'changed') return Number(hasChange(b.id)) - Number(hasChange(a.id)) || a.name.localeCompare(b.name, 'zh-CN');
      return a.name.localeCompare(b.name, 'zh-CN');
    });
  }
  function row(asset) {
    const s = summaryOf(asset), loading = busy && !summaries.has(asset.id), changed = hasChange(asset.id);
    const text = loading ? '正在读取结果' : errors.has(asset.id) ? '本次读取未成功' : s.statusText;
    const tone = errors.has(asset.id) || s.stale ? ' warning' : s.windows.length ? ' window' : '';
    return '<div class="watch-row' + (state.selectedId === asset.id ? ' is-selected' : '') + '" data-row="' + esc(asset.id) + '"><button type="button" class="asset-select" data-select="' + esc(asset.id) + '" aria-pressed="' + (state.selectedId === asset.id) + '"><strong>' + esc(asset.name) + '</strong><small>' + esc(asset.code) + ' · ' + (asset.kind === 'index' ? '指数' : 'A 股') + '</small></button><div class="row-date">' + esc(s.asof || '—') + '<small>' + esc(groupOf(asset.id) || '未分组') + '</small></div><div class="row-state"><span class="state-pill' + tone + '">' + esc(text || '未取得已发布结果') + '</span>' + (s.windows.length ? '<small>' + esc(s.windows[0].start + ' — ' + s.windows[0].end + windowEvidence(s.windows[0])) + (s.windows.length > 1 ? ' 等 ' + s.windows.length + ' 个区间' : '') + '</small>' : '') + (changed ? '<span class="change-dot">本机记录有变化</span>' : '') + '</div><label class="compare-check"><span class="sr-only">比较 ' + esc(asset.name) + '</span><input type="checkbox" data-compare="' + esc(asset.id) + '"' + (state.compareIds.includes(asset.id) ? ' checked' : '') + '></label></div>';
  }
  function renderList() {
    const focused = focusToken();
    renderGroups();
    const list = visibleAssets();
    $('watch-list').innerHTML = list.map(row).join('');
    $('empty-watch').hidden = assets.length !== 0;
    $('empty-filter').hidden = assets.length === 0 || list.length !== 0;
    $('shown-count').textContent = list.length + ' / ' + assets.length + ' 个标的';
    $('watch-count').textContent = assets.length;
    $('change-count').textContent = assets.filter(a => hasChange(a.id)).length;
    $('review-count').textContent = assets.filter(needsCheck).length;
    restoreFocus(focused);
  }
  function renderResume() {
    const focused = focusToken();
    const recent = state.recent.map((context, index) => ({ context, index })).filter(({ context }) => assets.some(a => a.id === context.assetId)).slice(0, 3);
    $('resume-section').hidden = recent.length === 0;
    $('resume-items').innerHTML = recent.map(({ context: r, index }) => {
      const a = assets.find(x => x.id === r.assetId);
      return '<button type="button" class="resume-item" data-resume="' + index + '"><span><strong>' + esc(a.name) + '</strong><small>上次研究截至 ' + esc(r.asof || '未提供') + '</small></span><span aria-hidden="true">↗</span></button>';
    }).join('');
    restoreFocus(focused);
  }
  function renderDetail() {
    const focused = focusToken();
    const asset = selectedAsset();
    $('detail-empty').hidden = !!asset;
    $('detail-content').hidden = !asset;
    if (!asset) { activeNoteKey = null; return; }
    const s = inspectRecord?.asset?.id === asset.id ? inspectRecord : summaryOf(asset);
    $('detail-kind').textContent = inspectRecord ? 'SAVED OBSERVATION · 本机历史记录' : 'RESEARCH DESK · 当前结果';
    $('detail-heading').textContent = asset.name;
    $('detail-code').textContent = asset.code + ' · ' + (asset.kind === 'index' ? '指数' : 'A 股股票');
    const incomplete = s.coverage.filter(c => !c.computed).length;
    let html = '<div class="summary-banner' + (!s.windows.length ? ' neutral' : '') + '"><h3>' + (s.status === 'expired' ? '已过去的观察区间' : s.windows.length ? '顶部观察区间' : '当前研究状态') + '</h3><p>' + esc(s.windows.length ? s.windows[0].start + ' — ' + s.windows[0].end : s.statusText) + '</p><small>' + (s.windows.length ? esc(s.windows[0].scale || '综合区间') + ' · 研究观察，不是确定见顶日' + esc(windowEvidence(s.windows[0])) : '未展示区间不等于没有风险。') + '</small></div>';
    if (s.status === 'expired') html += '<p class="notice notice-warning">该区间已早于分析截止日，仅供回看，不是新的未来提醒。</p>';
    if (s.windows.length > 1) html += '<details class="record-details"><summary>全部可展示区间 <span>' + s.windows.length + '</span></summary>' + s.windows.map(w => '<div class="record-item"><strong>' + esc(w.scale || '综合区间') + '</strong><p>' + esc(w.start + ' — ' + w.end) + '</p><small>证据：' + esc(w.evidence + windowEvidence(w)) + '</small></div>').join('') + '</details>';
    if (errors.has(asset.id) && !inspectRecord) html += '<p class="notice notice-warning">本次未取得新的已发布结果。已有本机记录与笔记仍保留。</p>';
    if (s.stale) html += '<p class="notice notice-warning">数据待更新：' + esc(s.staleReason || '来源标记为 stale') + '</p>';
    html += '<dl class="summary-facts"><div><dt>分析截止日</dt><dd>' + esc(dateLabel(s.asof)) + '</dd></div><div><dt>模型版本</dt><dd>' + esc(s.modelVersion || '未提供') + '</dd></div><div><dt>生成时间</dt><dd>' + esc(s.generatedAt ? prettyTime(s.generatedAt) + ' 北京时间' : '未提供') + '</dd></div>';
    if (s.price && asset.kind === 'index') html += '<div><dt>分析序列收盘</dt><dd>' + esc(s.price.close.toLocaleString('zh-CN', { maximumFractionDigits: 3 })) + ' 点 <small>(' + esc(s.price.date) + ')</small></dd></div>';
    if (s.price && asset.kind === 'stock') html += '<div><dt>股票行情</dt><dd><a href="' + esc(Core.route(asset)) + '">前往分析页查看</a></dd></div>';
    html += '<div><dt>预测记录 ID</dt><dd>' + esc(s.predictionId || '未提供') + '</dd></div></dl>';
    html += '<p class="source-note">来源：' + esc(s.source || '未提供') + (s.price && asset.kind === 'stock' ? '<br>现有价格为拟合序列，复权口径未单独提供；此处不将其作为股票现价展示。' : s.price?.note ? '<br>' + esc(s.price.note) : '') + '</p>';
    if (s.ruleNote) html += '<details class="record-details"><summary>结果口径说明</summary><p class="record-caption">' + esc(displayRuleNote(s.ruleNote)) + '</p></details>';
    if (s.coverage.length) html += '<div class="coverage-list" aria-label="计算覆盖">' + s.coverage.map(c => '<span class="' + (c.computed ? 'completed' : '') + '">' + esc(c.scale) + ' · ' + (c.computed ? '已计算' : c.status === 'not_computed' ? '未计算' : '状态待核对') + '</span>').join('') + '</div><p class="source-note">' + (incomplete ? '仍有尺度未计算或状态待核对；不等于这些尺度没有信号。' : '尺度表示拟合数据跨度，不是必然见顶的等待时间。') + '</p>';
    $('detail-summary').innerHTML = html;
    $('asset-group').innerHTML = groupsHTML(groupOf(asset.id), false);
    $('open-analysis').href = Core.route(asset);
    $('context-note').textContent = inspectRecord ? '正在查看本机保存的历史摘要。上方链接会打开站点最新分析，不会恢复该历史日期。' : '打开站点最新分析；返回后保留本页分组、筛选与研究记录。';
    const key = noteKey(s), note = lastNote(s);
    if (key !== activeNoteKey) {
      saveDraft(); activeNoteKey = key;
      $('research-note').value = drafts.has(key) ? drafts.get(key) : note?.text || '';
    }
    $('note-state').textContent = drafts.has(key) && drafts.get(key) !== (note?.text || '') ? '未保存草稿' : note ? '已保存 · v' + note.version : '尚未保存';
    $('note-context').textContent = s.asof ? '绑定分析截至 ' + s.asof : '未关联分析的关注理由；以后不会自动改绑';
    $('save-note').disabled = false;
    const notes = Core.notesFor(state, asset.id);
    $('note-version-count').textContent = notes.length;
    $('note-history').innerHTML = notes.length ? notes.map(n => '<article class="record-item"><strong>版本 ' + n.version + ' · ' + (n.asof ? '分析截至 ' + esc(n.asof) : '未关联分析') + '</strong><time>' + esc(prettyTime(n.createdAt)) + ' 北京时间</time><p>' + esc(n.text) + '</p><small>模型 ' + esc(n.modelVersion || '未提供') + ' · 记录 ID ' + esc(n.predictionId || '未提供') + '</small></article>').join('') : '<p class="record-caption">还没有保存笔记。</p>';
    const records = recordList(asset.id);
    $('observation-count').textContent = records.length;
    $('observation-history').innerHTML = records.length ? records.slice().reverse().map((r, reverseIndex) => {
      const index = records.length - 1 - reverseIndex, prior = records[index - 1];
      return '<article class="record-item"><strong>' + (index ? '结果摘要发生变化' : '开始本机记录') + '</strong><time>本机取得：' + esc(prettyTime(r.observedAt)) + ' 北京时间</time><p>分析截至 ' + esc(r.asof) + '<br>' + esc(windowLabel(r)) + '</p>' + (prior ? '<small>上次：' + esc(prior.asof) + ' · ' + esc(windowLabel(prior)) + '</small>' : '') + '<button type="button" class="text-button" data-inspect="' + index + '">查看这次摘要</button></article>';
    }).join('') + (inspectRecord ? '<button type="button" class="text-button" id="show-current">回到当前结果</button>' : '') : '<p class="record-caption">取得有效结果后，从本次开始记录，不补造历史。</p>';
    restoreFocus(focused);
  }
  function renderCompare() {
    const selected = state.compareIds.map(id => assets.find(a => a.id === id)).filter(Boolean);
    $('clear-compare').hidden = !selected.length;
    if (selected.length < 2) {
      $('compare-content').innerHTML = '<p class="compare-empty">' + (selected.length ? '已选择 ' + esc(selected[0].name) + '。再选择一个标的即可比较。' : '在清单右侧勾选 2–3 个标的，开始结构化比较。') + '</p>';
      return;
    }
    const values = selected.map(summaryOf);
    const mismatch = new Set(values.map(s => s.asof || 'missing')).size > 1 || new Set(values.map(s => s.modelVersion || 'missing')).size > 1;
    const fields = [
      ['分析截止', s => dateLabel(s.asof)], ['模型版本', s => s.modelVersion || '未提供'],
      ['研究状态', s => s.statusText], ['顶部观察区间', windowLabel],
      ['计算覆盖', s => s.coverage.length ? s.coverage.map(c => c.scale + '：' + (c.computed ? '已计算' : '未计算 / 待核对')).join('；') : '未提供'],
      ['数据来源', s => s.source || '未提供']
    ];
    $('compare-content').innerHTML = (mismatch ? '<p class="compare-warning">这些结果的截止日或模型版本不同，请分别理解，不能直接当作同一时点、同一口径的比较。</p>' : '') + '<table class="compare-table"><caption class="sr-only">自选标的研究结果比较</caption><thead><tr><th scope="col">比较项目</th>' + selected.map(a => '<th scope="col">' + esc(a.name) + '<small>' + esc(a.code) + '</small></th>').join('') + '</tr></thead><tbody>' + fields.map(([label, value]) => '<tr><th scope="row">' + esc(label) + '</th>' + values.map(s => '<td>' + esc(value(s)) + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
  }
  function render() { renderList(); renderDetail(); renderResume(); renderCompare(); }
  function selectAsset(id, scroll) {
    if (!assets.some(a => a.id === id)) return;
    saveDraft(); state.selectedId = id; inspectRecord = null; persist(); render();
    if (scroll && window.innerWidth <= 800) $('research-detail').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }
  async function refresh() {
    // Coalesce updates that arrive while a frozen batch is loading. In particular,
    // adding a stock after an index request starts must not leave it unrequested.
    if (busy) { queuedRefresh = true; return; }
    queuedRefresh = false;
    const thisGeneration = ++generation;
    syncAssets(); busy = true; $('refresh-results').disabled = true;
    $('refresh-state').textContent = assets.length ? '正在读取已发布结果…' : '尚未添加关注标的';
    render();
    const work = assets.slice(); let cursor = 0;
    async function worker() {
      while (cursor < work.length) {
        const asset = work[cursor++];
        try {
          const raw = asset.kind === 'index' ? (await API.load(asset.code)).raw : await API.stock.latest(asset.code);
          if (thisGeneration !== generation || !assets.some(a => a.id === asset.id)) continue;
          if (!raw) throw new Error('未取得已发布结果');
          const freshAsset = Core.asset(asset.kind, asset.code, raw.name || asset.name);
          const summary = Core.summarize(freshAsset, raw, new Date().toISOString());
          if (summary.status === 'unavailable') throw new Error('结果身份或日期未能核对');
          const observation = Core.observe(state, summary, new Date().toISOString());
          if (observation.type === 'older') {
            errors.set(asset.id, '返回的结果早于已保存记录');
          } else {
            summaries.set(asset.id, summary); errors.delete(asset.id);
            const at = assets.findIndex(a => a.id === asset.id); if (at >= 0) assets[at] = freshAsset;
            persist();
          }
        } catch {
          if (thisGeneration !== generation) continue;
          errors.set(asset.id, '未取得新的已发布结果');
          if (!summaries.has(asset.id)) summaries.set(asset.id, recordList(asset.id).at(-1) || Core.summarize(asset, null, new Date().toISOString()));
        }
        if (thisGeneration === generation) render();
      }
    }
    await Promise.all(Array.from({ length: Math.min(4, work.length) }, worker));
    if (thisGeneration !== generation) return;
    busy = false; $('refresh-results').disabled = false;
    $('refresh-state').textContent = assets.length ? '本机读取于 ' + prettyTime(new Date().toISOString()) + (errors.size ? ' · 部分结果待检查' : '') : '尚未添加关注标的';
    render();
    if (queuedRefresh) return refresh();
  }
  function addAsset(kind, code) {
    const known = kind === 'index' ? API.SYMS.find(s => s.sym === code) : null;
    if (kind === 'index' && !known) return '请选择站点支持的指数。';
    if (kind === 'stock' && !/^(?:60|68|00|30|43|83|87|92)\d{4}$/.test(code)) return '请输入支持的六位 A 股股票代码。';
    const asset = Core.asset(kind, code, known?.name || code);
    if (!asset) return '无法识别这个标的。';
    const list = kind === 'index' ? window.IndexWatchlist.read(storage) : window.StockWatchlist.read(storage);
    if (!list.includes(code) && kind === 'stock' && list.length >= window.StockWatchlist.MAX) return '个股自选已达 50 个，请先整理清单。';
    const next = list.includes(code) ? list : list.concat(code);
    const saved = kind === 'index' ? window.IndexWatchlist.write(next, storage) : window.StockWatchlist.write(storage, next);
    if (saved === null) { storageWarning(); return '未能保存自选，请检查浏览器存储。'; }
    state.selectedId = asset.id; state.groupFilter = 'all'; state.query = ''; state.statusFilter = 'all';
    $('list-search').value = ''; $('status-filter').value = 'all'; inspectRecord = null;
    syncAssets(); persist(); announceWatch(); render();
    if (busy) notify('标的已加入。当前读取完成后，会自动更新新增标的的结果。');
    refresh();
    return null;
  }
  function openDialog(id) {
    focusedBeforeDialog = document.activeElement;
    $(id).showModal();
  }
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('close', () => focusedBeforeDialog?.focus()));
  $('open-add').addEventListener('click', () => { $('add-error').textContent = ''; openDialog('add-dialog'); });
  $('add-index').innerHTML = API.SYMS.map(s => '<option value="' + esc(s.sym) + '">' + esc(s.name + ' · ' + s.sym) + '</option>').join('');
  $('add-kind').addEventListener('change', () => {
    const index = $('add-kind').value === 'index';
    $('stock-code-label').hidden = index; $('index-code-label').hidden = !index;
    $('add-code').required = !index; $('add-code').disabled = index;
    $('add-error').textContent = '';
  });
  $('add-code').required = true;
  $('add-form').addEventListener('submit', event => {
    event.preventDefault();
    const kind = $('add-kind').value, code = kind === 'index' ? $('add-index').value : $('add-code').value.trim();
    const error = addAsset(kind, code);
    if (error) $('add-error').textContent = error;
    else { $('add-dialog').close(); $('add-code').value = ''; }
  });
  document.querySelectorAll('[data-add-sample]').forEach(button => button.addEventListener('click', () => {
    const [kind, code] = button.dataset.addSample.split(':');
    const error = addAsset(kind, code); if (error) notify(error);
  }));
  $('open-group').addEventListener('click', () => { $('group-error').textContent = ''; openDialog('group-dialog'); });
  $('group-form').addEventListener('submit', event => {
    event.preventDefault();
    const name = $('group-name').value.trim();
    if (['全部', '未分组'].includes(name)) { $('group-error').textContent = '这个名称已用于系统分组，请换一个名称。'; return; }
    if (!Core.addGroup(state, name)) { $('group-error').textContent = '请填写不重复的分组名称（最多 24 字）；分组数量达到上限时请使用已有分组。'; return; }
    persist(); render(); $('group-dialog').close(); $('group-name').value = '';
  });
  $('group-tabs').addEventListener('click', event => {
    const button = event.target.closest('[data-group]'); if (!button) return;
    state.groupFilter = button.dataset.group; persist(); renderList();
  });
  $('list-search').value = state.query;
  $('status-filter').value = state.statusFilter;
  $('sort-order').value = state.sort;
  $('list-search').addEventListener('input', () => { state.query = $('list-search').value; persist(); renderList(); });
  $('status-filter').addEventListener('change', () => { state.statusFilter = $('status-filter').value; persist(); renderList(); });
  $('sort-order').addEventListener('change', () => { state.sort = $('sort-order').value; persist(); renderList(); });
  $('reset-filter').addEventListener('click', () => {
    state.query = ''; state.groupFilter = 'all'; state.statusFilter = 'all';
    $('list-search').value = ''; $('status-filter').value = 'all';
    persist(); renderList(); $('list-search').focus();
  });
  $('watch-list').addEventListener('click', event => {
    const button = event.target.closest('[data-select]'); if (button) selectAsset(button.dataset.select, true);
  });
  $('watch-list').addEventListener('change', event => {
    const input = event.target.closest('[data-compare]'); if (!input) return;
    const id = input.dataset.compare;
    if (input.checked && state.compareIds.length >= 3) { input.checked = false; notify('最多同时比较 3 个标的，请先取消一个。'); return; }
    state.compareIds = input.checked ? [...new Set(state.compareIds.concat(id))] : state.compareIds.filter(x => x !== id);
    persist(); renderCompare();
  });
  $('clear-compare').addEventListener('click', () => { state.compareIds = []; persist(); renderList(); renderCompare(); });
  $('asset-group').addEventListener('change', () => { if (state.selectedId && Core.setGroup(state, state.selectedId, $('asset-group').value)) { persist(); renderList(); } });
  $('research-note').addEventListener('input', () => { saveDraft(); $('note-state').textContent = '未保存草稿'; });
  $('save-note').addEventListener('click', () => {
    const asset = selectedAsset(); if (!asset) return;
    const s = inspectRecord?.asset?.id === asset.id ? inspectRecord : summaryOf(asset);
    const priorNotes = state.notes.slice();
    const note = Core.saveNote(state, s, $('research-note').value, new Date().toISOString());
    if (!note) { notify('笔记未保存：请填写内容并确认分析日期有效；本机笔记版本达到上限时请先自行备份。'); return; }
    const saved = persist();
    if (saved) { drafts.delete(noteKey(s)); notify('笔记已保存在此浏览器，并保留历史版本。'); }
    else { state.notes = priorNotes; drafts.set(noteKey(s), $('research-note').value); }
    renderDetail();
    if (!saved) $('note-state').textContent = '保存失败，请复制笔记';
  });
  $('observation-history').addEventListener('click', event => {
    const button = event.target.closest('[data-inspect]');
    if (button) { saveDraft(); inspectRecord = recordList(state.selectedId)[Number(button.dataset.inspect)] || null; renderDetail(); $('detail-heading').scrollIntoView({ block: 'nearest' }); }
    if (event.target.closest('#show-current')) { saveDraft(); inspectRecord = null; renderDetail(); }
  });
  $('open-analysis').addEventListener('click', () => {
    saveDraft(); const asset = selectedAsset();
    if (asset) Core.recordVisit(state, inspectRecord?.asset?.id === asset.id ? inspectRecord : summaryOf(asset), new Date().toISOString());
    state.scrollY = window.scrollY; persist(); renderResume();
  });
  $('resume-items').addEventListener('click', event => {
    const button = event.target.closest('[data-resume]'); if (!button) return;
    const recent = state.recent[Number(button.dataset.resume)];
    if (!recent || !assets.some(a => a.id === recent.assetId)) return;
    const sameContext = r => r && r.asset?.id === recent.assetId && r.asof === recent.asof && r.predictionId === recent.predictionId && r.modelVersion === recent.modelVersion;
    const record = sameContext(recent.snapshot) ? recent.snapshot : recordList(recent.assetId).findLast(r => sameContext(r) && r.observedAt <= recent.visitedAt);
    if (!record) { notify('本机未保留与这次访问完全一致的摘要，无法恢复该历史上下文。可从清单选择标的查看当前结果。'); return; }
    saveDraft(); state.selectedId = recent.assetId; inspectRecord = record; persist(); render();
    if (window.innerWidth <= 800) $('research-detail').scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  });
  $('remove-asset').addEventListener('click', () => {
    const asset = selectedAsset(); if (!asset) return;
    const current = asset.kind === 'index' ? window.IndexWatchlist.read(storage) : window.StockWatchlist.read(storage);
    const next = current.filter(code => code !== asset.code);
    const saved = asset.kind === 'index' ? window.IndexWatchlist.write(next, storage) : window.StockWatchlist.write(storage, next);
    if (saved === null) { storageWarning(); return; }
    saveDraft(); inspectRecord = null; syncAssets(); persist(); announceWatch(); render();
    notify('已从自选移除 ' + asset.name + '。本机笔记和观测记录保留，重新添加后可查看。');
  });
  $('close-detail').addEventListener('click', () => {
    saveDraft(); state.selectedId = null; inspectRecord = null; persist(); renderDetail(); renderList();
    $('watch-heading').scrollIntoView({ block: 'nearest' });
    $('watch-heading').focus({ preventScroll: true });
  });
  $('refresh-results').addEventListener('click', () => { notify(''); refresh(); });
  window.addEventListener('storage', event => {
    if (![window.IndexWatchlist.KEY, window.StockWatchlist.KEY].includes(event.key)) return;
    syncAssets(); render();
    notify('其他页面更新了自选清单，正在读取新增标的的结果。');
    refresh();
  });
  window.addEventListener('pagehide', () => { state.scrollY = window.scrollY; persist(); });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    syncAssets(); render(); restoringScroll = true;
    requestAnimationFrame(() => { window.scrollTo(0, state.scrollY || 0); restoringScroll = false; });
  });
  if (!storage || state.storageIssue) storageWarning();
  syncAssets();
  for (const a of assets) { const latest = recordList(a.id).at(-1); if (latest) summaries.set(a.id, latest); }
  render();
  if (state.scrollY) requestAnimationFrame(() => window.scrollTo(0, state.scrollY));
  refresh();
})();
