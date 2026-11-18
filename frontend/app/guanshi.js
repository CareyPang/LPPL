/* 观时资产路由、阅读状态与本地自选。行情与模型记录由 GuanshiData 提供。 */
(function () {
  'use strict';
  const byId = id => document.getElementById(id);
  const data = window.GuanshiData;
  const known = new Map(data.assets.map(asset => [asset.id, asset]));
  const recentKey = 'lppl.guanshi.recent.v1';
  function validDay(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
    const day = new Date(value + 'T00:00:00Z');
    return Number.isFinite(day.valueOf()) && day.toISOString().slice(0, 10) === value;
  }
  const compact = matchMedia('(max-width:800px)');
  let request = 0;
  let active = null;
  let dataset = null;
  let view = null;
  let complete = false;
  let quoteJob = 0;
  let reveal = false;
  let list;
  let feedbackTimer;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function tell(text) {
    clearTimeout(feedbackTimer);
    byId('feedback').textContent = text;
    feedbackTimer = setTimeout(() => { byId('feedback').textContent = ''; }, 2800);
  }
  function storage() { try { return window.localStorage; } catch { return null; } }
  function isIndex(asset) {
    return (window.LPPL.SYMS || []).some(index => index.sym === asset.id);
  }
  function savedAssets() {
    const indices = window.IndexWatchlist.read();
    const stocks = window.StockWatchlist.read(storage()).map(code =>
      data.assets.find(asset => asset.code === code && !isIndex(asset))?.id || 'stock' + code);
    return [...indices, ...stocks];
  }
  function assetById(id) {
    if (known.has(id)) return known.get(id);
    const index = (window.LPPL.SYMS || []).find(item => item.sym === id);
    if (index) return { id, name:index.name, code:index.code, exchange:id.startsWith('sh') ? '上交所' : '深交所' };
    if (/^stock\d{6}$/.test(id)) return { id, name:'股票 ' + id.slice(-6), code:id.slice(-6), exchange:'' };
    return null;
  }
  function queryAsset(raw) {
    if (known.has(raw)) return raw;
    const alias = data.assets.find(asset => asset.code === raw);
    return alias ? alias.id : raw;
  }
  function identity(asset) {
    return [asset.code, asset.exchange, isIndex(asset) ? '指数' : '股票'].filter(Boolean).join(' · ');
  }
  function toggleSaved(id) {
    const asset = assetById(id);
    if (!asset) return;
    let result;
    if (isIndex(asset)) {
      result = window.IndexWatchlist.toggle(id);
    } else {
      const codes = window.StockWatchlist.read(storage());
      const found = codes.includes(asset.code);
      if (!found && codes.length >= window.StockWatchlist.MAX) return tell('个股自选已满，请先移除一只标的。');
      const saved = window.StockWatchlist.write(storage(), found ? codes.filter(code => code !== asset.code) : [...codes, asset.code]);
      result = saved === null ? null : saved.includes(asset.code);
      if (saved !== null) window.dispatchEvent(new Event('lppl-watch'));
    }
    tell(result === null ? '无法保存，请检查浏览器存储权限。' : result ? '已加入我的自选' : '已从自选移除');
  }
  function readRecent() {
    try {
      const rows = JSON.parse(storage()?.getItem(recentKey) || '[]');
      return Array.isArray(rows) ? rows.filter(row => row && assetById(row.id)).slice(0, 3) : [];
    } catch { return []; }
  }
  function remember() {
    // An on-demand quote is not an archived date that another visit can replay.
    const day = dataset?.currentQuote?.asof === view?.asof ? null : view?.asof;
    const row = { id:active.id, asof:day || null };
    const rows = [row, ...readRecent().filter(item => item.id !== row.id)].slice(0, 3);
    try { storage()?.setItem(recentKey, JSON.stringify(rows)); } catch { /* 阅读仍可继续。 */ }
  }
  function assetURL(id, asof) {
    const url = new URL('guanshi.html', document.baseURI);
    url.searchParams.set('asset', id);
    if (validDay(asof)) url.searchParams.set('asof', asof);
    return url;
  }
  function assetAnchor(asset, day, origin) {
    const anchor = node('a');
    anchor.href = assetURL(asset.id, day);
    anchor.dataset.asset = asset.id;
    anchor.dataset.origin = origin;
    if (day) anchor.dataset.day = day;
    const label = node('span');
    label.append(node('strong', asset.name), node('small', day ? '读至 ' + day : identity(asset)));
    const arrow = node('span', '↗', 'arrow');
    arrow.setAttribute('aria-hidden', 'true');
    anchor.append(label, arrow);
    return anchor;
  }
  function renderRecent() {
    const target = byId('recent-list');
    target.replaceChildren();
    for (const row of readRecent()) {
      const link = assetAnchor(assetById(row.id), row.asof, 'recent');
      link.className = 'recent-link';
      target.append(link);
    }
    if (!target.childNodes.length) target.append(node('p', '打开一只标的后，可以在这里接着上次的日期阅读。'));
  }
  function saveButton(button, asset, saved, small) {
    button.setAttribute('aria-pressed', String(saved));
    button.setAttribute('aria-label', (saved ? '从自选移除' : '加入自选') + ' · ' + asset.name);
    button.textContent = small ? (saved ? '★' : '☆') : (saved ? '★ 已自选' : '☆ 加自选');
    button.dataset.save = asset.id;
  }
  function renderRows() {
    const saved = savedAssets();
    const mine = list.tab === 'mine';
    byId('my-tab').setAttribute('aria-pressed', String(mine));
    byId('catalog-tab').setAttribute('aria-pressed', String(!mine));
    byId('watch-count').textContent = String(saved.length);
    byId('list-note').textContent = mine ? '自选保存在当前浏览器，与站内自选共用。' : '选一只标的查看档案，点星标加入自己的清单。';
    const target = byId('rows');
    target.replaceChildren();
    const rows = mine ? saved.map(assetById).filter(Boolean) : data.assets;
    const query = list.filter.trim().toLowerCase();
    for (const asset of rows.filter(item => [item.id, item.code, item.name].join(' ').toLowerCase().includes(query))) {
      const row = node('div', null, 'row');
      const star = node('button', null, 'star');
      star.type = 'button';
      saveButton(star, asset, saved.includes(asset.id), true);
      row.append(assetAnchor(asset, null, 'rows'), star);
      target.append(row);
    }
    if (!target.childNodes.length) {
      target.append(node('p', query ? '没有匹配的标的。清除筛选，可查看完整清单。' : '自选还是空的。在「研究标的」点击星标，即可从这里继续。', 'empty'));
    }
  }
  function updateListState() {
    if (!active) history.replaceState({ guanshiList:{ ...list } }, '', location.href);
  }
  function showList(restore) {
    request++;
    resetQuoteControl();
    window.GuanshiChart.clear(byId('guanshi-chart'));
    active = dataset = view = null;
    reveal = false;
    list = history.state?.guanshiList || { tab:savedAssets().length ? 'mine' : 'catalog', filter:'', scroll:0 };
    byId('list-view').hidden = false;
    byId('asset-view').hidden = true;
    byId('filter').value = list.filter;
    byId('feedback').textContent = '';
    document.title = '我的研究 · 观时';
    renderRows();
    renderRecent();
    updateListState();
    if (restore && list.row) {
      requestAnimationFrame(() => {
        if (active) return;
        const links = Array.from(document.querySelectorAll('#list-view [data-asset]'));
        const focus = links.find(link => link.dataset.asset === list.row && link.dataset.origin === list.origin);
        (focus || byId('filter')).focus({ preventScroll:true });
        window.scrollTo(0, list.scroll || 0);
      });
    }
  }
  function openFromList(anchor) {
    list = { ...list, scroll:window.scrollY, row:anchor.dataset.asset, origin:anchor.dataset.origin };
    updateListState();
    history.pushState({ guanshiAsset:true, fromList:true }, '', anchor.href);
    route(false);
  }
  function chooseDay(day) {
    resetQuoteControl();
    reveal = false;
    history.replaceState(history.state, '', assetURL(active.id, day));
    draw();
  }
  function safeSource(url) {
    if (!url) return null;
    try { const parsed = new URL(url, document.baseURI); return /^https?:$/.test(parsed.protocol) ? parsed.href : null; }
    catch { return null; }
  }
  function freshEvidence(v) {
    const target = byId('evidence-body');
    const fields = node('dl');
    [
      ['记录性质', v.provenance || '未提供'], ['模型截止', v.modelAsOf || '无该日记录'],
      ...(v.sealedAt ? [['封存时间', v.sealedAt]] : []),
      ['首次公开可见', v.firstVisible || '尚无可核对的时间'], ['模型版本', v.modelVersion || '未提供'],
      ['数据版本', v.dataVersion || '未提供'],
    ].forEach(([label, value]) => {
      const row = node('div');
      row.append(node('dt', label), node('dd', value));
      fields.append(row);
    });
    const notes = node('ul');
    for (const note of v.evidence || []) notes.append(node('li', note));
    const links = node('div', null, 'sources');
    for (const [label, url] of [['原始模型记录', v.source], ['原始行情记录', v.quoteSource]]) {
      const valid = safeSource(url);
      if (!valid) continue;
      const link = node('a', label + ' ↗');
      link.href = valid; link.target = '_blank'; link.rel = 'noopener noreferrer';
      links.append(link);
    }
    target.replaceChildren(fields, notes, links);
  }
  function empty(v) {
    byId('window-label').textContent = '顶部时间窗';
    byId('headline').textContent = v.headline;
    byId('intervals').replaceChildren();
    byId('date-label').hidden = true;
    byId('example-date').hidden = true;
    byId('later').hidden = true;
    byId('cutoffs').textContent = '';
    byId('quote-note').textContent = '';
    byId('refresh-quote').hidden = true;
    byId('issues').replaceChildren();
    chartMessage('没有可供绘制的归档行情。');
    freshEvidence(v);
  }
  function chartMessage(text) {
    const host = byId('guanshi-chart');
    window.GuanshiChart.clear(host);
    host.replaceChildren(node('p', text, 'empty'));
  }
  function retryButton() {
    const retry = node('button', '重新读取档案', 'text-button');
    retry.type = 'button';
    retry.onclick = () => loadAsset(active);
    return retry;
  }
  function resetQuoteControl() {
    quoteJob++;
    const button = byId('refresh-quote');
    button.disabled = false;
    button.hidden = true;
    button.textContent = '检查更新行情';
    button.setAttribute('aria-busy', 'false');
    byId('quote-feedback').textContent = '';
  }
  function canRefresh() {
    return complete && active?.id === 'sh600519' && view?.asof && view.asof === view.dates[0] && !reveal;
  }
  async function refreshQuote() {
    const button = byId('refresh-quote');
    if (!canRefresh() || button.disabled) return;
    const token = ++quoteJob;
    const snapshot = dataset;
    const anchor = view.asof;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = '检查中…';
    byId('quote-feedback').textContent = '正在核对最新日线，现有图表可继续查看。';
    try {
      const result = await data.refreshQuote(snapshot);
      if (token !== quoteJob || dataset !== snapshot || view?.asof !== anchor) return;
      if (result.status === 'updated') {
        dataset = result.dataset;
        history.replaceState(history.state, '', assetURL(active.id));
        draw();
        remember();
      }
      byId('quote-feedback').textContent = result.message;
    } catch {
      if (token === quoteJob) byId('quote-feedback').textContent = '行情来源暂时无法读取，可继续查看已有行情。';
    } finally {
      if (token === quoteJob) {
        button.disabled = false;
        button.setAttribute('aria-busy', 'false');
        button.textContent = '检查更新行情';
      }
    }
  }
  function datePicker(dates, asof) {
    const select = byId('asof');
    const groups = { '当日封存':[], '当前研究或行情':[], '历史重算':[], '无该日记录':[] };
    for (const day of new Set([...dates, ...(validDay(asof) ? [asof] : [])])) {
      if (dataset.seals.has(day)) groups['当日封存'].push(day);
      else if (dataset.current && (day === dataset.current.asof || day === dates[0] && day > dataset.current.asof)) groups['当前研究或行情'].push(day);
      else if (dataset.frames.has(day)) groups['历史重算'].push(day);
      else if (day === dataset.currentQuote?.asof || day === dataset.allBars.at(-1)?.date) groups['当前研究或行情'].push(day);
      else groups['无该日记录'].push(day);
    }
    const key = JSON.stringify(groups);
    if (select.dataset.groups !== key) {
      const options = document.createDocumentFragment();
      for (const [label, days] of Object.entries(groups)) {
        if (!days.length) continue;
        const group = node('optgroup');
        group.label = label;
        group.append(...days.map(day => new Option(day, day)));
        options.append(group);
      }
      select.replaceChildren(options);
      select.dataset.groups = key;
    }
    select.value = asof || '';
    byId('date-label').hidden = !select.options.length;
  }
  function labelWindow(w) {
    const [year, month, day] = w.start.split('-').map(Number);
    const [lastYear, lastMonth, lastDay] = w.end.split('-').map(Number);
    return year + '年' + month + '月' + day + '日 — ' +
      (year === lastYear ? '' : lastYear + '年') + lastMonth + '月' + lastDay + '日';
  }
  function draw() {
    if (!dataset) return;
    const asked = new URL(location.href).searchParams.get('asof');
    if (asked !== null && !validDay(asked)) {
      view = null;
      empty({ headline:'研究日期无效', evidence:['请从已有归档日期重新打开研究。'] });
      const reset = node('button', '打开最新归档', 'text-button');
      reset.type = 'button'; reset.onclick = () => chooseDay(null);
      byId('issues').append(reset);
      return;
    }
    view = data.view(dataset, asked || undefined, reveal);
    const uniqueWindows = new Map((view.windows || []).map(w => [w.start + '/' + w.end, w]));
    byId('window-label').textContent = uniqueWindows.size ?
      ['候选顶部时间窗', view.provenance].filter(Boolean).join(' · ') : '顶部时间窗';
    byId('headline').textContent = view.headline;
    if (uniqueWindows.size === 1) byId('headline').textContent = labelWindow(uniqueWindows.values().next().value);
    if (uniqueWindows.size > 1) byId('headline').textContent = '有 ' + uniqueWindows.size + ' 个候选区间';
    byId('intervals').replaceChildren(...(view.windows || []).map(w =>
      node('span', w.label + ' · ' + w.start + ' 至 ' + w.end)));
    const bars = view.bars || [];
    const latestKnown = bars.filter(bar => bar.date <= view.asof).at(-1);
    const cutoffs = byId('cutoffs');
    cutoffs.replaceChildren(node('span', '行情截至 ' + (view.quoteAsOf || latestKnown?.date || '暂无')), node('span', '模型截至 ' + (view.modelAsOf || '无该日记录')));
    if (!uniqueWindows.size && view.modelAsOf && view.provenance) cutoffs.append(node('span', view.provenance, 'provenance'));
    const dates = view.dates || [];
    datePicker(dates, view.asof);
    const example = byId('example-date');
    example.hidden = !view.exampleDate || view.exampleDate === view.asof || view.asof !== dates[0];
    example.dataset.day = view.exampleDate || '';
    const later = byId('later');
    later.hidden = !view.hasLater;
    later.setAttribute('aria-pressed', String(reveal));
    later.textContent = reveal ? '收起后来走势' : '查看后来走势';
    if (bars.length) {
      window.GuanshiChart.render(byId('guanshi-chart'), { ...view, revealLater:reveal });
    } else {
      chartMessage('所选日期没有可展示的归档行情。');
    }
    byId('refresh-quote').hidden = !canRefresh();
    byId('quote-note').textContent = bars.length
      ? [view.priceBasis, view.quoteStatus, view.volumeUnit && ('成交量单位 · ' + view.volumeUnit)].filter(Boolean).join('　')
      : '';
    if (reveal && view.laterVolumeNote) byId('quote-note').append('　', view.laterVolumeNote);
    if (reveal && safeSource(view.laterSource)) {
      const link = node('a', '后续行情来源 ↗');
      link.href = safeSource(view.laterSource); link.target = '_blank'; link.rel = 'noopener noreferrer';
      byId('quote-note').append('　', link);
    }
    const issues = byId('issues');
    issues.replaceChildren(...(view.issues || []).map(text => node('p', text)));
    if (view.state === 'unavailable' || (view.issues || []).length) issues.append(retryButton());
    freshEvidence(view);
  }
  async function loadAsset(asset) {
    const token = ++request;
    complete = false;
    resetQuoteControl();
    dataset = view = null;
    byId('window-label').textContent = '顶部时间窗';
    byId('headline').textContent = '正在读取归档记录…';
    byId('intervals').replaceChildren();
    byId('cutoffs').textContent = '';
    byId('evidence-body').replaceChildren(node('p', '正在核对记录来源。'));
    byId('example-date').hidden = byId('date-label').hidden = byId('later').hidden = true;
    byId('quote-note').textContent = '';
    byId('issues').replaceChildren();
    chartMessage('正在读取日线行情…');
    if (!known.has(asset.id)) {
      empty({ headline:'本版尚无该标的的研究档案', provenance:'本版未接入', evidence:['档案缺失，无法判断该标的的顶部区间。'] });
      return;
    }
    const arrived = value => { if (request === token) { dataset = value; draw(); } };
    try {
      const loaded = await data.load(asset.id, arrived);
      if (request !== token) return;
      complete = true;
      arrived(loaded);
      remember();
    } catch {
      if (request !== token) return;
      if (!dataset) empty({ headline:'归档记录暂时无法读取', evidence:['请重试。可以先返回自选或打开其他标的。'] });
      byId('issues').replaceChildren(node('p', '部分档案未能读取。'), retryButton());
    }
  }
  function route(restore) {
    const params = new URL(location.href).searchParams;
    const raw = params.get('asset') || params.get('code');
    if (!raw) return showList(restore);
    const asset = assetById(queryAsset(raw));
    if (!asset) {
      history.replaceState({}, '', new URL('guanshi.html', document.baseURI));
      showList(false); tell('找不到这个标的，请在清单中重新选择。'); return;
    }
    active = asset; reveal = false;
    clearTimeout(feedbackTimer); byId('feedback').textContent = '';
    byId('list-view').hidden = true;
    byId('asset-view').hidden = false;
    byId('asset-name').textContent = asset.name;
    byId('identity').textContent = identity(asset);
    byId('evidence').open = !compact.matches;
    saveButton(byId('asset-save'), asset, savedAssets().includes(asset.id), false);
    document.title = asset.name + ' · 观时';
    window.scrollTo(0, 0);
    byId('asset-name').focus({ preventScroll:true });
    loadAsset(asset);
  }
  function back() {
    if (active && view) remember();
    if (history.state?.fromList) return history.back();
    location.assign(new URL('guanshi.html', document.baseURI));
  }
  document.querySelector('[data-list-link]').addEventListener('click', event => {
    if (active && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); back(); }
  });
  byId('back').onclick = back;
  byId('list-view').addEventListener('click', event => {
    const anchor = event.target.closest('a[data-asset]');
    if (anchor && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      event.preventDefault(); openFromList(anchor); return;
    }
    const star = event.target.closest('[data-save]');
    if (star) {
      toggleSaved(star.dataset.save);
      const button = Array.from(byId('rows').querySelectorAll('[data-save]')).find(item => item.dataset.save === star.dataset.save);
      (button || byId('my-tab')).focus({ preventScroll:true });
    }
  });
  for (const [id, tab] of [['my-tab','mine'],['catalog-tab','catalog']]) {
    byId(id).onclick = () => { list.tab = tab; list.filter = byId('filter').value = ''; renderRows(); updateListState(); };
  }
  byId('filter').oninput = event => { list.filter = event.target.value; renderRows(); updateListState(); };
  byId('asset-save').onclick = () => toggleSaved(active.id);
  byId('asof').onchange = event => { chooseDay(event.target.value); remember(); };
  byId('example-date').onclick = event => { chooseDay(event.currentTarget.dataset.day); remember(); };
  byId('later').onclick = () => { if (view?.hasLater) { reveal = !reveal; draw(); } };
  byId('refresh-quote').onclick = refreshQuote;
  byId('open-evidence').onclick = () => {
    byId('evidence').open = true;
    byId('evidence-toggle').focus({ preventScroll:true });
    byId('evidence').scrollIntoView({ block:'nearest' });
  };
  function syncSaved() {
    if (active) saveButton(byId('asset-save'), active, savedAssets().includes(active.id), false);
    else renderRows();
  }
  window.addEventListener('lppl-watch', syncSaved);
  window.addEventListener('storage', event => {
    if ([window.StockWatchlist.KEY, window.IndexWatchlist.KEY, null].includes(event.key)) syncSaved();
    if (!active && [recentKey, null].includes(event.key)) renderRecent();
  });
  window.addEventListener('popstate', () => route(true));
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  route(true);
})();
