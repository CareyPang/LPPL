(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ResearchPersonalCore = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  const KEY = 'lppl.research-personal.v1';
  const plain = v => !!v && typeof v === 'object' && !Array.isArray(v);
  const text = (v, max = 200) => typeof v === 'string' ? v.trim().slice(0, max) : '';
  function date(v) {
    if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
    const d = new Date(v + 'T00:00:00Z');
    return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === v ? v : null;
  }
  function instant(v) { return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v) && date(v.slice(0, 10)) && Number.isFinite(Date.parse(v)) ? v.slice(0, 60) : null; }
  function assetId(v) { return typeof v === 'string' && /^(?:stock:\d{6}|index:(?:sh|sz|bj)\d{6})$/.test(v) ? v : null; }
  function initial() { return { version: 1, revision: 0, readChanges: [], holdings: [], storageIssue: null }; }
  function holding(v) {
    if (!plain(v) || !/^\d{6}$/.test(v.code || '') || v.currency !== 'CNY') return null;
    if (![v.shares, v.cost].every(n => (typeof n === 'number' || typeof n === 'string') && String(n).trim() !== '')) return null;
    const shares = Number(v.shares), cost = Number(v.cost);
    if (v.shares === '' || v.cost === '' || !Number.isFinite(shares) || shares <= 0 || shares > 1e12 || !Number.isFinite(cost) || cost < 0 || cost > 1e9 || shares * cost > 1e15) return null;
    if (!instant(v.updatedAt)) return null;
    return { code: v.code, name: text(v.name, 80) || v.code, shares, cost, currency: 'CNY', updatedAt: instant(v.updatedAt) };
  }
  function normalize(v) {
    const out = initial();
    if (!plain(v) || v.version !== 1) return { ...out, storageIssue: 'unsupported_version' };
    out.revision = Number.isSafeInteger(v.revision) && v.revision >= 0 ? v.revision : 0;
    out.readChanges = [...new Set((Array.isArray(v.readChanges) ? v.readChanges : []).filter(x => typeof x === 'string' && x.length <= 300))].slice(-4000);
    const rows = new Map();
    for (const item of (Array.isArray(v.holdings) ? v.holdings : []).slice(0, 100)) { const row = holding(item); if (row) rows.set(row.code, row); }
    out.holdings = [...rows.values()];
    return out;
  }
  function load(storage) {
    try {
      if (!storage) return { ...initial(), storageIssue: 'read_failed' };
      const raw = storage.getItem(KEY);
      if (raw === null) return initial();
      if (typeof raw !== 'string' || raw.length > 1000000) return { ...initial(), storageIssue: 'invalid' };
      return normalize(JSON.parse(raw));
    } catch { return { ...initial(), storageIssue: 'read_failed' }; }
  }
  function save(storage, state) {
    try {
      if (!storage || !plain(state) || state.version !== 1 || state.storageIssue) return false;
      const raw = storage.getItem(KEY);
      if (raw !== null) {
        const current = JSON.parse(raw);
        if (!plain(current) || current.version !== 1 || (current.revision || 0) !== state.revision) return false;
      } else if (state.revision) return false;
      const next = normalize(state); next.revision += 1;
      storage.setItem(KEY, JSON.stringify(next)); state.revision = next.revision;
      return true;
    } catch { return false; }
  }
  function structural(v) {
    return JSON.stringify({ status: text(v.status), evidence: text(v.evidence),
      windows: (Array.isArray(v.windows) ? v.windows : []).map(w => ({ scale: text(w.scale), start: date(w.start), end: date(w.end), evidence: text(w.evidence) })).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))),
      coverage: (Array.isArray(v.coverage) ? v.coverage : []).map(c => ({ scale: text(c.scale), status: text(c.status), computed: c.computed === true, evidence: text(c.evidence) })).sort((a, b) => a.scale.localeCompare(b.scale)) });
  }
  function changes(observations) {
    const output = [];
    for (const [id, rows] of Object.entries(plain(observations) ? observations : {})) {
      if (!assetId(id) || !Array.isArray(rows)) continue;
      // The first saved result is a baseline, never a newly issued prediction.
      for (let i = 1; i < rows.length; i += 1) {
        const previous = rows[i - 1], current = rows[i];
        if (!plain(previous) || !plain(current) || !instant(current.observedAt) || !text(current.id) || structural(previous) === structural(current)) continue;
        const reasons = [];
        if (JSON.stringify(previous.windows || []) !== JSON.stringify(current.windows || [])) reasons.push('观察区间变化');
        if (previous.status !== current.status) reasons.push('结果状态变化');
        if (previous.evidence !== current.evidence) reasons.push('证据状态变化');
        if (!reasons.length) reasons.push('计算覆盖变化');
        output.push({ id: id + ':' + text(current.id, 100), assetId: id, name: text(current.asset && current.asset.name, 80) || id.split(':')[1],
          observedAt: instant(current.observedAt), asof: date(current.asof), reasons,
          basisChanged: previous.modelVersion !== current.modelVersion || previous.dataVersion !== current.dataVersion,
          previousAsOf: date(previous.asof) });
      }
    }
    return output.sort((a, b) => Date.parse(b.observedAt) - Date.parse(a.observedAt));
  }
  const EVENT_TYPES = [ ['lift', 'free_date', '限售解禁'], ['dividend', 'ex_dividend_date', '除权除息'], ['forecast', 'notice_date', '业绩预告'] ];
  function eventData(payload) {
    if (!plain(payload)) return null;
    const asof = date(payload.asof), generated = instant(payload.generated), sources = plain(payload.sources) ? payload.sources : {}, rows = [];
    if (!asof || !EVENT_TYPES.some(([type]) => Array.isArray(payload[type]))) return null;
    const sourceStates = EVENT_TYPES.map(([type, , label]) => {
      const s = plain(sources[type]) ? sources[type] : {};
      return { type, label, source: text(s.provider), status: s.ok === true ? 'ok' : s.ok === false ? 'failed' : 'unknown', stale: s.stale === true, staleReason: text(s.stale_reason || s.error, 400) || null, fetchedAt: instant(s.fetched_at) };
    });
    for (const [type, field, label] of EVENT_TYPES) {
      const source = sourceStates.find(s => s.type === type);
      (Array.isArray(payload[type]) ? payload[type] : []).slice(0, 10000).forEach((r, i) => {
        if (!plain(r) || !/^\d{6}$/.test(r.code || '') || !date(r[field])) return;
        const publishedAt = instant(r.published_at || r.notice_at), publicationDate = date(r.notice_date);
        const firstSeen = instant(r.first_seen_at), eventDate = date(r[field]);
        const description = type === 'dividend' ? text(r.plan_text, 500) : type === 'forecast' ? text(r.predict_type, 100) : text(r.free_shares_type, 200);
        rows.push({ id: type + ':' + r.code + ':' + eventDate + ':' + i, type, label, code: r.code, name: text(r.name, 80) || r.code,
          date: eventDate, asof, publishedAt, publicationDate, firstSeen, description, source,
          futureAsOf: eventDate > asof, status: type === 'forecast' ? '公告日期记录' : eventDate > asof ? '快照记为预定，发生情况待核实' : '已到日程，执行待核实' });
      });
    }
    return { asof, generated, rows: rows.sort((a, b) => a.date.localeCompare(b.date) || a.code.localeCompare(b.code)), sources: sourceStates,
      coverage: plain(payload.window) ? Object.fromEntries(EVENT_TYPES.map(([type]) => [type, Array.isArray(payload.window[type]) ? payload.window[type].map(date).filter(Boolean).slice(0, 2) : []])) : {} };
  }
  function filterEvents(data, options) {
    if (!data) return [];
    const codes = new Set((options.codes || []).filter(c => /^\d{6}$/.test(c)));
    return data.rows.filter(r => codes.has(r.code) && (!options.asset || options.asset === 'all' || r.code === options.asset)
      && (!options.month || r.date.slice(0, 7) === options.month) && (!options.day || r.date === options.day));
  }
  function knowledgeAt(event, cutoff) {
    const day = date(cutoff);
    if (!day) return '当前事件快照';
    // Provider publication and collection timestamps are NOT user-visible prediction timestamps.
    if (event.firstSeen && event.firstSeen.slice(0, 10) > day) return '该日之后才采集，不能作为当时已知';
    const pub = event.publishedAt ? event.publishedAt.slice(0, 10) : event.publicationDate;
    if (pub && pub > day) return '该日之后发布，不能作为当时已知';
    if (!pub) return '发布日期未知，当时可知未建立';
    return '发布日期不晚于所选日；当时网站可见未核实';
  }
  function amount(value, unit) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
    const factor = unit === 'yi' ? 1e8 : unit === 'wan' ? 1e4 : 1;
    const suffix = unit === 'yi' ? '亿元' : unit === 'wan' ? '万元' : '元';
    return (value / factor).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ' + suffix;
  }
  return { KEY, initial, normalize, load, save, holding, changes, eventData, filterEvents, knowledgeAt, amount, date };
});
