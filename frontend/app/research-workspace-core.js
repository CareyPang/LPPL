/* Local research state and published-result presentation. No requests or model calculations. */
(function (root, factory) {
  'use strict';
  const RuleLabels = typeof module === 'object' && module.exports
    ? require('./rule-labels.js')
    : root && root.RuleLabels;
  const api = factory(RuleLabels);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ResearchWorkspaceCore = api;
})(typeof window === 'undefined' ? globalThis : window, function (RuleLabels) {
  'use strict';
  const KEY = 'lppl.research-workspace.v1';
  const SCALES = ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'];
  const INDEX_CODES = ['sh000001', 'sh000016', 'sh000300', 'sh000905', 'sh000688', 'sz399001', 'sz399006'];
  const WINDOW_EVIDENCE = new Set(['dev', 'cal', 'test', 'cal_fragile', 'research_candidate', 'descriptive']);
  const STATUS = {
    unavailable: '尚未取得可用分析', not_computed: RuleLabels.EMPTY_REASONS.not_computed,
    no_qualified_fit: RuleLabels.EMPTY_REASONS.no_fit, no_cluster: RuleLabels.EMPTY_REASONS.no_cluster,
    evidence_hidden: RuleLabels.EMPTY_REASONS.not_formal, has_window: '有研究观察区间',
    expired: '已公布区间早于分析截止日',
  };
  const plain = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const text = (value, max = 200) => typeof value === 'string' ? value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').slice(0, max) : '';
  function date(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const millis = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(millis) && new Date(millis).toISOString().slice(0, 10) === value ? value : null;
  }
  function timestamp(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(value)) return null;
    const millis = Date.parse(value);
    return Number.isFinite(millis) ? new Date(millis).toISOString() : null;
  }
  function nowStamp(now) {
    const d = now === undefined ? new Date() : new Date(now);
    return Number.isFinite(d.getTime()) ? d.toISOString() : null;
  }
  function asset(kind, code, name) {
    code = String(code || '').trim();
    if (kind === 'index') code = code.toLowerCase();
    if (kind !== 'index' && kind !== 'stock') return null;
    if (kind === 'index' ? !INDEX_CODES.includes(code) : !/^\d{6}$/.test(code)) return null;
    return { id: kind + ':' + code, kind, code, name: text(name, 80) || code };
  }
  function idAsset(id) {
    if (typeof id !== 'string') return null;
    const parts = id.split(':');
    return parts.length === 2 ? asset(parts[0], parts[1]) : null;
  }
  function validAsset(value) {
    if (!plain(value)) return null;
    const a = asset(value.kind, value.code, value.name);
    return a && (!value.id || value.id === a.id) ? a : null;
  }
  function sourceName(raw) {
    const values = [raw.source, raw.data_source, raw.stock_meta && raw.stock_meta.source];
    return text(values.find(value => typeof value === 'string'), 160) || '来源未提供';
  }
  function evidenceFor(a, raw, scale, own) {
    const confidence = raw.top && raw.top.lppls_confidence || {};
    const levels = confidence.scale_evidence || {};
    // A band cannot upgrade a failed/absent scale gate. An explicit restrictive
    // band label can, however, further restrict an otherwise displayable scale.
    const scoped = text(levels[scale] || confidence.evidence, 40) || 'none';
    if (!WINDOW_EVIDENCE.has(scoped)) return scoped;
    const evidence = text(own || scoped, 40) || 'none';
    if (!WINDOW_EVIDENCE.has(evidence)) return evidence;
    // Descriptive evidence at either level always keeps its sample-count gate.
    // Stock identity is an additional restriction, never permission to upgrade
    // descriptive/failed scale or band evidence into a research date band.
    const descriptive = scoped === 'descriptive' || evidence === 'descriptive';
    if (a.kind === 'stock') {
      const stockEvidence = text(raw.stock_meta && raw.stock_meta.evidence, 40) || 'none';
      if (!WINDOW_EVIDENCE.has(stockEvidence)) return stockEvidence;
      if (descriptive || stockEvidence === 'descriptive') return 'descriptive';
      return stockEvidence === 'research_candidate' ? 'research_candidate' : evidence;
    }
    return descriptive ? 'descriptive' : evidence;
  }
  function allowedWindow(evidence, sampleCount) {
    return WINDOW_EVIDENCE.has(evidence) &&
      (evidence !== 'descriptive' || (Number.isInteger(sampleCount) && sampleCount > 0));
  }
  function summarize(inputAsset, payload, now) {
    const a = validAsset(inputAsset);
    if (!a) return null;
    const raw = plain(payload) && plain(payload.raw) ? payload.raw : payload;
    const result = {
      asset: a, asof: null, modelVersion: null, predictionId: null, generatedAt: null,
      source: '来源未提供', dataVersion: null, status: 'unavailable', statusText: STATUS.unavailable,
      stale: false, staleReason: null, evidence: 'none', coverage: [], windows: [], price: null,
      loadedAt: nowStamp(now), ruleNote: null,
    };
    if (!plain(raw) || !date(raw.asof)) return result;
    const symbol = typeof raw.symbol === 'string' ? raw.symbol.toLowerCase() : '';
    const stockPrefix = a.code.startsWith('6') ? 'sh' : /^[03]/.test(a.code) ? 'sz' : 'bj';
    const matches = a.kind === 'index' ? symbol === a.code : symbol === stockPrefix + a.code;
    if (!matches) return result;
    const top = plain(raw.top) ? raw.top : {};
    const confidence = plain(top.lppls_confidence) ? top.lppls_confidence : {};
    const indicators = plain(top.indicators) ? top.indicators : {};
    result.asof = raw.asof;
    result.asset.name = text(raw.name, 80) || a.name;
    result.modelVersion = text(raw.model_version || raw.code_version || raw.stock_meta && raw.stock_meta.code_version, 120) || null;
    result.predictionId = text(raw.prediction_id, 200) || null;
    result.generatedAt = timestamp(raw.generated_at);
    result.source = sourceName(raw);
    result.dataVersion = text(raw.data_version, 160) || null;
    result.stale = raw.stale === true || Number(raw.stock_meta && raw.stock_meta.trading_days_stale || 0) > 0;
    result.staleReason = result.stale ? text(raw.stale_reason || raw.stock_meta && raw.stock_meta.stale_reason, 240) || '来源标记数据落后，请核对截止日' : null;
    result.evidence = a.kind === 'stock' ? text(raw.stock_meta && raw.stock_meta.evidence, 40) || 'none' : text(confidence.evidence, 40) || 'none';
    result.ruleNote = text(top.rule_note || indicators.rule_note, 1200) || null;
    result.coverage = SCALES.map(scale => {
      const indicator = plain(indicators[scale]) ? indicators[scale] : {};
      const explicit = text(indicator.signal_status, 60);
      const computed = explicit !== 'not_computed' &&
        ((Number.isInteger(indicator.n_windows) && indicator.n_windows > 0) ||
          (typeof confidence[scale] === 'number' && Number.isFinite(confidence[scale])));
      return { scale, status: explicit || (computed ? 'computed' : 'unknown'), computed,
        evidence: evidenceFor(a, raw, scale) };
    });
    let rejectedDates = false;
    function takeWindow(scale, value) {
      if (!plain(value)) return;
      if (indicators[scale] && indicators[scale].signal_status === 'not_computed') return;
      const start = date(value.q20_date || value.start), end = date(value.q80_date || value.end);
      if (!start || !end || start > end) return;
      const evidence = evidenceFor(a, raw, scale, value.evidence);
      if (!allowedWindow(evidence, value.n)) { rejectedDates = true; return; }
      if (result.windows.some(w => w.scale === scale && w.start === start && w.end === end)) return;
      result.windows.push({ scale, start, end, evidence, rank: value.rank === 'secondary' ? 'secondary' : 'main',
        ...(evidence === 'descriptive' ? { n: value.n, note: '历史分位，不是预测' } : {}) });
    }
    const scaleWindows = Array.isArray(top.scale_windows) ? top.scale_windows : [];
    SCALES.forEach(scale => {
      // An explicitly empty cluster list is authoritative; do not revive an older fallback band.
      if (plain(top.scale_clusters) && Array.isArray(top.scale_clusters[scale])) {
        top.scale_clusters[scale].slice(0, 10).forEach(value => takeWindow(scale, value));
      } else {
        scaleWindows.filter(w => plain(w) && w.scale === scale).slice(0, 10).forEach(value => takeWindow(scale, value));
        if (scale === '6-12m' && !scaleWindows.some(w => plain(w) && w.scale === scale)) takeWindow(scale, top.window);
      }
    });
    const price = plain(raw.price_history) ? raw.price_history : {};
    if (Array.isArray(price.dates) && Array.isArray(price.close)) {
      for (let i = Math.min(price.dates.length, price.close.length) - 1; i >= 0; i--) {
        const d = date(price.dates[i]), close = price.close[i];
        if (d && d <= result.asof && typeof close === 'number' && Number.isFinite(close) && close > 0) {
          result.price = { close, date: d, note: '分析序列收盘；' + (text(price.note, 240) || '复权口径请查看原分析') };
          break;
        }
      }
    }
    const calculated = result.coverage.filter(c => c.computed);
    const eligible = calculated.filter(c => WINDOW_EVIDENCE.has(c.evidence));
    if (result.windows.length) result.status = result.windows.every(w => w.end < result.asof) ? 'expired' : 'has_window';
    else if (rejectedDates) result.status = 'evidence_hidden';
    else if (!calculated.length) result.status = 'not_computed';
    else if (!eligible.length) result.status = 'evidence_hidden';
    else if (eligible.every(c => c.status === 'no_qualified_fit')) result.status = 'no_qualified_fit';
    else result.status = 'no_cluster';
    result.statusText = STATUS[result.status];
    return result;
  }
  function initial() {
    return { version: 1, revision: 0, observationSeq: 0, groups: ['观察', '持有'], meta: {}, selectedId: null, query: '', groupFilter: 'all',
      statusFilter: 'all', sort: 'name', compareIds: [], observations: {}, notes: [], recent: [], scrollY: 0, storageIssue: null };
  }
  function cleanSummary(value) {
    if (!plain(value)) return null;
    const a = validAsset(value.asset);
    if (!a || !date(value.asof) || !Object.hasOwn(STATUS, value.status)) return null;
    const coverage = (Array.isArray(value.coverage) ? value.coverage : []).filter(c => plain(c) && SCALES.includes(c.scale))
      .filter((c, i, rows) => rows.findIndex(other => other.scale === c.scale) === i).slice(0, 6)
      .map(c => ({ scale: c.scale, status: text(c.status, 60), computed: c.computed === true, evidence: text(c.evidence, 40) || 'none' }));
    const windows = (Array.isArray(value.windows) ? value.windows : []).filter(w => {
      if (!plain(w) || !SCALES.includes(w.scale) || !date(w.start) || !date(w.end) || w.start > w.end || !allowedWindow(w.evidence, w.n)) return false;
      const gate = coverage.find(c => c.scale === w.scale);
      // Local storage is untrusted too: an old or edited band cannot override
      // the corresponding failed/unknown/not-computed scale evidence.
      return !!gate && gate.status !== 'not_computed' && allowedWindow(gate.evidence, w.n);
    }).slice(0, 60)
      .map(w => ({ scale: w.scale, start: w.start, end: w.end, evidence: w.evidence, rank: w.rank === 'secondary' ? 'secondary' : 'main',
        ...(w.evidence === 'descriptive' ? { n: w.n, note: '历史分位，不是预测' } : {}) }));
    const status = !windows.length && ['has_window', 'expired'].includes(value.status) ? 'evidence_hidden' : value.status;
    return { asset: a, asof: value.asof, modelVersion: text(value.modelVersion, 120) || null,
      predictionId: text(value.predictionId, 200) || null, generatedAt: timestamp(value.generatedAt),
      source: text(value.source, 160) || '来源未提供', dataVersion: text(value.dataVersion, 160) || null,
      status, statusText: STATUS[status], stale: value.stale === true,
      staleReason: value.stale === true ? text(value.staleReason, 240) || '请核对截止日' : null,
      evidence: text(value.evidence, 40) || 'none', coverage, windows,
      price: plain(value.price) && date(value.price.date) && value.price.date <= value.asof &&
        typeof value.price.close === 'number' && Number.isFinite(value.price.close) && value.price.close > 0
        ? { close: value.price.close, date: value.price.date, note: text(value.price.note, 280) } : null,
      loadedAt: timestamp(value.loadedAt), ruleNote: text(value.ruleNote, 1200) || null };
  }
  function context(summary, now) {
    const a = summary && validAsset(summary.asset), at = nowStamp(now);
    if (!a || !at) return null;
    return { assetId: a.id, asset: a, asof: date(summary.asof), predictionId: text(summary.predictionId, 200) || null,
      modelVersion: text(summary.modelVersion, 120) || null, selectedScale: SCALES.includes(summary.selectedScale) ? summary.selectedScale : null,
      visitedAt: at };
  }
  function cleanContext(value) {
    if (!plain(value) || !validAsset(value.asset) || value.assetId !== value.asset.id || !timestamp(value.visitedAt)) return null;
    const c = context(value, value.visitedAt), snapshot = cleanSummary(value.snapshot);
    c.snapshot = snapshot && snapshot.asset.id === c.assetId && snapshot.asof === c.asof &&
      snapshot.predictionId === c.predictionId && snapshot.modelVersion === c.modelVersion ? snapshot : null;
    return c;
  }
  function normalize(value) {
    const out = initial();
    if (!plain(value) || value.version !== 1) return out;
    out.revision = Number.isSafeInteger(value.revision) && value.revision >= 0 ? value.revision : 0;
    out.observationSeq = Number.isSafeInteger(value.observationSeq) && value.observationSeq >= 0 ? value.observationSeq : 0;
    out.groups = [...new Set((Array.isArray(value.groups) ? value.groups : []).filter(v => typeof v === 'string' && v.trim() && v.length <= 24).map(v => v.trim()))].slice(0, 12);
    for (const [key, m] of Object.entries(plain(value.meta) ? value.meta : {})) {
      if (idAsset(key) && plain(m)) out.meta[key] = { group: out.groups.includes(m.group) ? m.group : '' };
    }
    out.selectedId = idAsset(value.selectedId) ? value.selectedId : null;
    out.query = text(value.query, 100);
    out.groupFilter = value.groupFilter === 'all' || value.groupFilter === '' || out.groups.includes(value.groupFilter) ? value.groupFilter : 'all';
    out.statusFilter = ['all', 'has_window', 'needs_check', 'changed'].includes(value.statusFilter) ? value.statusFilter : 'all';
    out.sort = ['name', 'asof', 'changed'].includes(value.sort) ? value.sort : 'name';
    out.compareIds = [...new Set((Array.isArray(value.compareIds) ? value.compareIds : []).filter(v => idAsset(v)))].slice(0, 3);
    out.scrollY = Number.isFinite(value.scrollY) ? Math.max(0, Math.min(1000000, value.scrollY)) : 0;
    for (const [key, values] of Object.entries(plain(value.observations) ? value.observations : {})) {
      if (!idAsset(key) || !Array.isArray(values)) continue;
      const observations = [];
      for (const value of values.slice(-40)) {
        const s = cleanSummary(value), at = timestamp(value && value.observedAt);
        if (s && s.asset.id === key && at) observations.push({ ...s, observedAt: at, id: text(value.id, 100) });
      }
      out.observations[key] = observations;
    }
    out.notes = (Array.isArray(value.notes) ? value.notes : []).filter(n => plain(n) && idAsset(n.assetId) &&
      typeof n.text === 'string' && n.text.length <= 4000 && timestamp(n.createdAt) && Number.isInteger(n.version) && n.version > 0)
      .slice(0, 200).map(n => ({ id: text(n.id, 100), assetId: n.assetId, asof: date(n.asof),
        predictionId: text(n.predictionId, 200) || null, modelVersion: text(n.modelVersion, 120) || null,
        text: text(n.text, 4000), createdAt: timestamp(n.createdAt), version: n.version, ...(n.imported === true ? { imported: true } : {}) }));
    out.recent = (Array.isArray(value.recent) ? value.recent : []).map(cleanContext).filter(Boolean).slice(0, 10);
    return out;
  }
  function load(storage) {
    const empty = initial();
    try {
      if (!storage) return { ...empty, storageIssue: 'read_failed' };
      const serialized = storage.getItem(KEY);
      if (serialized === null) return empty;
      if (typeof serialized !== 'string' || serialized.length > 4000000) return { ...empty, storageIssue: 'invalid' };
      const value = JSON.parse(serialized);
      if (!plain(value)) return { ...empty, storageIssue: 'invalid' };
      if (value.version !== 1) return { ...empty, storageIssue: 'unsupported_version' };
      return normalize(value);
    } catch { return { ...empty, storageIssue: 'read_failed' }; }
  }
  function save(storage, state) {
    try {
      if (!storage || !plain(state) || state.version !== 1 || state.storageIssue) return false;
      // Refuse a known stale tab's overwrite. This is a local conflict check,
      // not an atomic server transaction or a cross-device sync mechanism.
      const existing = storage.getItem(KEY);
      if (existing !== null) {
        const previous = JSON.parse(existing);
        const priorRevision = Number.isSafeInteger(previous && previous.revision) ? previous.revision : 0;
        if (!plain(previous) || previous.version !== 1 || priorRevision !== (state.revision || 0)) return false;
      } else if (state.revision) return false;
      const next = normalize(state);
      next.revision += 1;
      storage.setItem(KEY, JSON.stringify(next));
      state.revision = next.revision;
      return true;
    } catch { return false; }
  }
  function addGroup(state, name) {
    if (!plain(state) || typeof name !== 'string') return false;
    const clean = text(name, 25).trim();
    if (!clean || clean.length > 24 || clean === 'all' || state.groups.includes(clean) || state.groups.length >= 12) return false;
    state.groups.push(clean); return true;
  }
  function setGroup(state, id, group) {
    if (!plain(state) || !idAsset(id) || (group !== '' && !state.groups.includes(group))) return false;
    state.meta[id] = { group }; return true;
  }
  function signature(summary) {
    return JSON.stringify({ asof: summary.asof, model: summary.modelVersion, evidence: summary.evidence,
      status: summary.status, coverage: summary.coverage, windows: summary.windows,
      stale: summary.stale, staleReason: summary.staleReason, dataVersion: summary.dataVersion, ruleNote: summary.ruleNote });
  }
  function observe(state, summary, now) {
    const current = cleanSummary(summary), at = nowStamp(now);
    if (!plain(state) || !current || !at) return { type: 'invalid', changed: false, previous: null, current: null };
    const id = current.asset.id, rows = state.observations[id] || [];
    const previous = rows.length ? rows[rows.length - 1] : null;
    if (previous && (current.asof < previous.asof ||
      (current.asof === previous.asof && current.generatedAt && previous.generatedAt && current.generatedAt < previous.generatedAt))) {
      return { type: 'older', changed: false, previous, current };
    }
    if (previous && signature(previous) === signature(current)) return { type: 'unchanged', changed: false, previous, current: previous };
    state.observationSeq = (state.observationSeq || 0) + 1;
    const entry = { ...current, observedAt: at, id: 'local-' + at + '-' + state.observationSeq };
    state.observations[id] = rows.concat(entry).slice(-40);
    return { type: previous ? 'changed' : 'first', changed: !!previous, previous, current: entry };
  }
  function recordVisit(state, summary, now) {
    const c = context(summary, now);
    if (!plain(state) || !c) return null;
    // Preserve the exact publication identity visited without inventing a model
    // change when a regenerated prediction has identical semantic content.
    c.snapshot = cleanSummary(summary);
    state.recent = [c].concat(state.recent.filter(v => !(v.assetId === c.assetId && v.asof === c.asof &&
      v.predictionId === c.predictionId && v.modelVersion === c.modelVersion))).slice(0, 10);
    return c;
  }
  function saveNote(state, summary, body, now) {
    const c = context(summary, now);
    if (!plain(state) || !c || typeof body !== 'string' || body.length > 4000) return null;
    const versions = state.notes.filter(n => n.assetId === c.assetId && n.asof === c.asof &&
      n.predictionId === c.predictionId && n.modelVersion === c.modelVersion);
    const previous = versions.length ? versions[versions.length - 1] : null;
    const clean = text(body, 4000).trim();
    if (previous && previous.text === clean) return previous;
    if (state.notes.length >= 200) return null; // Never silently discard a user's old note.
    const note = { id: 'note-' + c.visitedAt + '-' + state.notes.length, assetId: c.assetId, asof: c.asof,
      predictionId: c.predictionId, modelVersion: c.modelVersion, text: clean,
      createdAt: c.visitedAt, version: versions.length ? Math.max(...versions.map(n => n.version)) + 1 : 1 };
    state.notes.push(note); return note;
  }
  function notesFor(state, id) {
    return (Array.isArray(state && state.notes) ? state.notes : []).filter(n => n.assetId === id).slice().reverse();
  }
  function route(value) {
    const a = validAsset(value);
    if (!a) return 'research-workspace.html';
    // Existing symbol pages open current data. Historic local snapshots remain in this workspace.
    return (a.kind === 'index' ? 'index.html' : 'stock.html') + '?code=' + encodeURIComponent(a.code) + '&from=research-workspace';
  }
  return { KEY, SCALES, STATUS, asset, summarize, initial, load, save, addGroup, setGroup,
    observe, recordVisit, saveNote, notesFor, route, date, signature, normalize };
});
