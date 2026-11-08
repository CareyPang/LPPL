/* Browser-local P0 workstation ledger. It stores provenance, not model claims. */
(function (root) {
  'use strict';
  const STORE = 'lppl.workstation.ledger.v1';
  const DATE = /^\d{4}-\d{2}-\d{2}$/;
  const MAX_RECENT = 24;
  const MAX_REVISIONS = 120;
  const nowIso = clock => new Date((clock || Date.now)()).toISOString();
  const text = value => typeof value === 'string' && value.trim() ? value.trim() : null;
  const validDate = value => typeof value === 'string' && DATE.test(value) && Number.isFinite(Date.parse(value + 'T00:00:00Z'));
  const codeOf = value => text(value?.code || value?.symbol)?.replace(/^(sh|sz|bj)/i, '') || null;
  const symbolOf = value => text(value?.symbol) || null;
  const safeRecord = (value, fallback) => value && typeof value === 'object' ? value : fallback;

  function normalize(state) {
    const value = safeRecord(state, {});
    const watchlist = Array.isArray(value.watchlist) ? value.watchlist : [];
    const recent = Array.isArray(value.recent) ? value.recent : [];
    const revisions = Array.isArray(value.revisions) ? value.revisions : [];
    return {
      schema_version: 'workstation-ledger.v1',
      updated_at: text(value.updated_at),
      watchlist: watchlist.filter(item => codeOf(item)).slice(0, 50),
      recent: recent.filter(item => codeOf(item)).slice(0, MAX_RECENT),
      revisions: revisions.filter(item => codeOf(item)).slice(0, MAX_REVISIONS),
    };
  }

  function create(options = {}) {
    const storage = options.storage || root.localStorage;
    const clock = options.now || Date.now;
    let memory = normalize({});
    function read() {
      try { return normalize(JSON.parse(storage?.getItem(options.key || STORE) || '{}')); }
      catch { return memory; }
    }
    function write(value) {
      const next = normalize({ ...value, updated_at: nowIso(clock) });
      memory = next;
      try { storage?.setItem(options.key || STORE, JSON.stringify(next)); } catch { /* Memory-only is explicit in snapshot. */ }
      return typeof structuredClone === 'function' ? structuredClone(next) : JSON.parse(JSON.stringify(next));
    }
    function update(fn) { return write(fn(read())); }
    function asset(value) {
      const item = safeRecord(value, {});
      return {
        code: codeOf(item), symbol: symbolOf(item),
        name: text(item.name) || text(item.display_name),
      };
    }
    function touchRecent(value) {
      const item = safeRecord(value, {}), a = asset(item);
      if (!a.code) return read();
      const stamp = nowIso(clock);
      return update(state => {
        const previous = state.recent.find(row => row.code === a.code) || {};
        const row = {
          ...previous, ...a,
          asof: validDate(item.asof) ? item.asof : previous.asof || null,
          analysis_asof: validDate(item.analysis_asof) ? item.analysis_asof : previous.analysis_asof || null,
          source: text(item.source) || text(item.source_url) || text(item.source_sha) || previous.source || null,
          evidence_status: text(item.evidence_status) || text(item.evidence) || previous.evidence_status || 'NOT_ESTABLISHED',
          status: text(item.status) || previous.status || 'viewed',
          stale: typeof item.stale === 'boolean' ? item.stale : previous.stale === true,
          first_seen_at: previous.first_seen_at || stamp,
          last_seen_at: stamp,
        };
        return { ...state, recent: [row, ...state.recent.filter(row => row.code !== a.code)] };
      });
    }
    function isWatched(value) {
      const code = codeOf(value); return !!code && read().watchlist.some(row => row.code === code);
    }
    function toggleWatch(value) {
      const a = asset(value); if (!a.code) return read();
      return update(state => {
        const exists = state.watchlist.some(row => row.code === a.code);
        if (exists) return { ...state, watchlist: state.watchlist.filter(row => row.code !== a.code) };
        return { ...state, watchlist: [{ ...a, added_at: nowIso(clock), last_seen_at: nowIso(clock) }, ...state.watchlist] };
      });
    }
    function recordAnalysis(value) {
      const item = safeRecord(value, {}), a = asset(item);
      if (!a.code) return read();
      const analysis = safeRecord(item.analysis, item);
      const windows = Array.isArray(analysis.windows) ? analysis.windows : [];
      const stamp = nowIso(clock);
      return update(state => {
        const existing = state.revisions;
        const additions = windows.map(window => ({
          ...a,
          kind: text(window.claim_kind || window.claimKind) || 'observation',
          start: validDate(window.start) ? window.start : null,
          end: validDate(window.end) ? window.end : null,
          evidence_status: text(window.evidence) || text(analysis.evidence) || text(item.evidence) || 'NOT_ESTABLISHED',
          asof: validDate(item.asof) ? item.asof : validDate(analysis.as_of) ? analysis.as_of : null,
          source: text(item.source_sha) || text(item.source_url) || text(item.source) || null,
          recorded_at: stamp,
          reason: text(window.reason) || text(window.explanation) || null,
        })).filter(row => row.start && row.end);
        const unique = additions.filter(row => !existing.some(old => old.code === row.code && old.start === row.start && old.end === row.end && old.source === row.source && old.kind === row.kind));
        return { ...state, revisions: [...unique, ...existing].slice(0, MAX_REVISIONS) };
      });
    }
    function snapshot() { return read(); }
    function clear() { return write({}); }
    return { snapshot, touchRecent, toggleWatch, isWatched, recordAnalysis, clear, store: options.key || STORE };
  }

  const exported = { create, normalize, STORE };
  if (typeof module === 'object' && module.exports) module.exports = exported;
  else root.WorkstationLedger = exported;
})(typeof window === 'object' ? window : globalThis);
