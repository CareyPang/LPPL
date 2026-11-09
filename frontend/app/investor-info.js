/* Descriptive selectors and read orchestration. Business reads use LPPL only. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.InvestorInfo = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const available = new Set(['fresh', 'partial', 'stale']);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
  const clean = value => typeof value === 'string' ? value.trim() : '';
  const rows = value => Array.isArray(value) ? value.filter(row => row && typeof row === 'object') : [];
  const textMatch = (row, term) => Object.values(row).filter(v => typeof v === 'string').join(' ').toLowerCase().includes(clean(term).toLowerCase());
  function symbol(value) {
    const s = clean(value).toLowerCase();
    const digits = s.replace(/^(sh|sz|bj)/, '');
    if (!/^(?:60|68|00|30|43|83|87|92)\d{4}$/.test(digits)) return null;
    const result = (/^6/.test(digits) ? 'sh' : /^[03]/.test(digits) ? 'sz' : 'bj') + digits;
    return /^\d{6}$/.test(s) || s === result ? result : null;
  }
  function safeUrl(value) {
    try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null; }
    catch { return null; }
  }
  function missing(reason, asof = null) {
    return { status: 'not_available', asof, rows: [], source: {}, stale_reason: reason, evidence: 'descriptive' };
  }
  function publicationBlocked(value) {
    return !value || value.publication_eligible === false || value.evidence_import ||
      ['fixture', 'research_import'].includes(value.run_mode) || value.origin === 'fixture';
  }
  function section(snapshot, key, asset = null) {
    if (publicationBlocked(snapshot)) return missing('该快照未获准展示', snapshot?.asof);
    const context = snapshot?.investor_context;
    if (!context || context.schema_version !== 'investor-context.v1') return missing('该栏目尚无已核验资讯快照', snapshot?.asof);
    if (context.publication_eligible !== true || context.purpose !== 'publish') return missing('研究导入尚未获准展示', snapshot?.asof);
    if (context.asof !== snapshot.asof || (asset && context.symbol !== asset)) return missing('资讯的日期或资产与当前视图不一致', snapshot?.asof);
    const item = context.sections?.[key];
    if (item && item.asof !== context.asof) return missing('栏目日期与资讯快照不一致', context.asof);
    if (!item || item.publication_eligible !== true || !available.has(item.status)) return { ...missing(item?.stale_reason || '该栏目未取得获准展示的数据', context.asof), status: item?.publication_eligible === false && available.has(item?.status) ? 'blocked' : item?.status || 'not_available' };
    return { ...item, rows: rows(item.rows) };
  }
  function review(snapshot) {
    if (!snapshot || !validDate(snapshot.asof)) return null;
    if (publicationBlocked(snapshot)) return null;
    const asof = snapshot.asof, limit = snapshot.limit_pools || {};
    const fromFull = Array.isArray(limit.pool_rows?.zt);
    const raw = rows(fromFull ? limit.pool_rows.zt : limit.top20?.zt);
    const dated = (s) => s && available.has(s.status) && s.asof === asof ? rows(s.rows) : [];
    const reasons = new Map(dated(limit.reasons).map(r => [r.code, clean(r.reason)]));
    const topicLabels = new Map();
    for (const r of dated(limit.topics)) if (clean(r.topic_label)) {
      const items = topicLabels.get(r.code) || []; if (!items.includes(r.topic_label)) items.push(r.topic_label); topicLabels.set(r.code, items);
    }
    const seen = new Set(), stocks = [];
    for (const r of raw) {
      const s = symbol(r.code); if (!s || seen.has(s)) continue;
      seen.add(s);
      stocks.push({ code: s.slice(2), symbol: s, name: clean(r.name) || s, streak: finite(r.streak) ? r.streak : null,
        limit_time: clean(r.limit_time), reason: reasons.get(r.code) || null, topics: topicLabels.get(r.code) || [],
        pct: finite(r.pct) ? r.pct : null, industry: clean(r.industry) || null });
    }
    stocks.sort((a, b) => (b.streak || 0) - (a.streak || 0) || a.code.localeCompare(b.code));
    const total = Number.isInteger(limit.zt) && limit.zt >= 0 ? limit.zt : null;
    const complete = fromFull && total != null && stocks.length === total && raw.length === total;
    const topicCounts = new Map();
    for (const r of dated(limit.topics)) {
      if (!symbol(r.code) || !clean(r.topic_label)) continue;
      const members = topicCounts.get(r.topic_label) || new Set(); members.add(r.code); topicCounts.set(r.topic_label, members);
    }
    const topics = [...topicCounts].map(([name, members]) => ({ name, count: members.size, codes: [...members] })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    const zt = total, zb = Number.isInteger(limit.zb) && limit.zb >= 0 ? limit.zb : null;
    const dt = Number.isInteger(limit.dt) && limit.dt >= 0 ? limit.dt : null;
    const breakRate = zt != null && zb != null && zt + zb > 0 ? zb / (zt + zb) : null;
    const progression = snapshot.history?.progression;
    return { asof, stocks, topics, complete, sampleCount: stocks.length, total, counts: { zt, zb, dt, breakRate },
      progression: progression?.asof === asof && available.has(progression.status) ? progression : missing('缺少相邻交易日完整配对快照', asof),
      boardFlow: snapshot.board_flow || {}, sources: snapshot.sources || {},
      sourceStatus: snapshot.status || 'archived', sourceReason: snapshot.stale_reason || null,
      generatedAt: snapshot.generated_at || null, raw: snapshot };
  }
  function selectStocks(model, { query = '', topic = '', minStreak = 0 } = {}) {
    return (model?.stocks || []).filter(r => (!topic || r.topics.includes(topic)) && (r.streak || 0) >= minStreak &&
      textMatch({ ...r, topics: r.topics.join(' ') }, query));
  }
  function boardRows(model, kind = 'industry', period = 'today', query = '') {
    if (!['industry', 'concept', 'region'].includes(kind)) return [];
    const fields = { today: ['main_net', 'pct_chg'], '5d': ['main_net_5d', 'pct_5d'], '10d': ['main_net_10d', 'pct_10d'] };
    if (!fields[period]) return [];
    const [net, pct] = fields[period];
    return rows(model?.boardFlow?.[kind]).filter(r => textMatch(r, query)).map(r => ({ name: clean(r.name), code: clean(r.code),
      net: finite(r[net]) ? r[net] : null, pct: finite(r[pct]) ? r[pct] : null })).filter(r => r.name)
      .sort((a, b) => (b.net ?? -Infinity) - (a.net ?? -Infinity));
  }
  function newsRows(snapshot, kinds, { query = '', asset = null, onlySaved = false, saved = [] } = {}) {
    const unique = new Set(), out = [];
    for (const kind of kinds) for (const row of section(snapshot, kind, asset).rows) {
      const url = safeUrl(row.url || row.link), title = clean(row.title), time = row.published_at;
      if (!url || !title || typeof time !== 'string' || !Number.isFinite(Date.parse(time))) continue;
      const id = clean(row.hash || row.content_hash || row.sha256) || `${url}|${time}`;
      const item = { id, title, url, published_at: time, source: clean(row.source) || clean(row.source_name) || section(snapshot, kind, asset).source?.source_id || '来源待核验', kind,
        symbol: symbol(row.symbol), available_at: row.available_at || null };
      if (unique.has(id) || !textMatch(item, query) || (onlySaved && !saved.includes(id))) continue;
      if (asset && item.symbol && item.symbol !== asset) continue;
      unique.add(id); out.push(item);
    }
    return out.sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at));
  }
  function createNotebook(storage, clock = () => new Date().toISOString()) {
    const key = 'lppl.investor.notebook.v1'; let memory = { notes: [], bookmarks: [] }, persistent = !!storage;
    try {
      const raw = JSON.parse(storage?.getItem(key) || '{}');
      memory = {
        notes: rows(raw.notes).filter(r => validDate(r.asof) && clean(r.body) && r.body.length <= 4000 && (!r.symbol || symbol(r.symbol))).slice(0, 300)
          .map(r => ({ id: clean(r.id), asof: r.asof, symbol: symbol(r.symbol), body: r.body.trim(), created_at: clean(r.created_at), snapshot_hash: clean(r.snapshot_hash) || null, kind: 'user_note_not_model_evidence' })),
        bookmarks: rows(raw.bookmarks).filter(r => safeUrl(r.url) && clean(r.id) && clean(r.title)).slice(0, 300)
          .map(r => ({ id: r.id, url: safeUrl(r.url), title: r.title, published_at: clean(r.published_at), source: clean(r.source), saved_at: clean(r.saved_at) })),
      };
    } catch { persistent = false; }
    function snapshot() { return JSON.parse(JSON.stringify({ ...memory, persistent })); }
    function save() { try { if (!storage) throw Error('unavailable'); storage.setItem(key, JSON.stringify(memory)); } catch { persistent = false; } return snapshot(); }
    function addNote({ asof, symbol: asset, body, snapshotHash = null }) {
      if (!validDate(asof) || !clean(body) || body.length > 4000 || (asset && !symbol(asset))) throw Error('请填写有效日期与不超过4000字的笔记');
      const created = clock();
      memory.notes.unshift({ id: created + '-' + memory.notes.length, asof, symbol: asset || null, body: body.trim(), created_at: created, snapshot_hash: snapshotHash, kind: 'user_note_not_model_evidence' });
      memory.notes = memory.notes.slice(0, 300); return save();
    }
    function toggleBookmark(item) {
      const url = safeUrl(item.url); if (!url || !clean(item.id) || !clean(item.title)) return snapshot();
      const found = memory.bookmarks.some(x => x.id === item.id);
      memory.bookmarks = found ? memory.bookmarks.filter(x => x.id !== item.id) : [{ id: item.id, url, title: item.title, published_at: item.published_at || null, source: item.source || null, saved_at: clock() }, ...memory.bookmarks].slice(0, 300);
      return save();
    }
    return { snapshot, addNote, toggleBookmark, exportJSON: () => JSON.stringify({ schema_version: 'investor-notebook.v1', exported_at: clock(), ...memory }, null, 2) };
  }
  function createReader(api, onState, { timeoutMs = 12000 } = {}) {
    let generation = 0, closed = false, client;
    const cache = new Map();
    try { client = api.marketContext(); } catch { /* No context client is configured. */ }
    function bounded(operation) {
      let timer;
      return Promise.race([operation, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('读取超时，可重试；不会启动模型')), timeoutMs); })]).finally(() => clearTimeout(timer));
    }
    async function get(date = 'latest') {
      if (date !== 'latest' && !validDate(date)) throw Error('日期无效');
      const token = ++generation;
      const emit = value => { if (!closed && token === generation) onState(value); };
      emit({ status: 'loading', date, snapshot: cache.get(date) || null });
      try {
        let snapshot;
        if (client?.isEnabled()) snapshot = (await bounded(client.get(date))).snapshot;
        else { snapshot = await bounded(api.market()); if (date !== 'latest' && snapshot?.asof !== date) throw Error('该日期没有可读取的封存快照，未回退到最新数据'); }
        if (!review(snapshot)) throw Error('市场快照缺失或尚未获准展示');
        if (date !== 'latest' && snapshot.asof !== date) throw Error('返回日期不匹配');
        if (token !== generation || closed) return;
        cache.set(date, snapshot); emit({ status: snapshot.status === 'stale' ? 'stale' : 'ready', date, snapshot });
      } catch (error) { emit({ status: 'error', date, snapshot: cache.get(date) || null, error: error.message || '读取失败' }); }
    }
    return { get, destroy: () => { closed = true; generation++; client?.stop(); }, pollingEnabled: () => client?.isEnabled() === true };
  }
  return { review, selectStocks, boardRows, section, newsRows, symbol, validDate, safeUrl, finite, createNotebook, createReader };
});
