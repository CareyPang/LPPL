/* Browser-local observation evidence. Never a publication clock or a model signal. */
(function (root) {
  'use strict';
  const PREFIX = 'lppl.stock.first-visible.v1.';
  const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value + 'T00:00:00Z')) &&
    new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
  const allowedEvidence = value => typeof value === 'string' && value !== 'none' &&
    !value.startsWith('fail') && !['dev_only', 'dev_failed'].includes(value) && value.length > 0;
  function candidates(record) {
    if (!record || record.demo === true || record.mode === 'history' || !validDate(record.asof) ||
        !/^(sh|sz|bj)\d{6}$/.test(record.symbol || '')) return [];
    const top = record.top || {}, confidence = top.lppls_confidence || {}, window = top.window || {};
    if ([record.evidence, top.evidence_override].some(value => value && !allowedEvidence(value)) ||
        String(record.claim_origin || '').startsWith('HYPOTHETICAL')) return [];
    if (record.analysis) {
      const policy = root.StockAnalysis || (typeof module === 'object' && module.exports ? require('./stock-analysis.js') : null);
      if (!policy) return [];
      return policy.normalize(record).windows.map((row, index) => ({ slot: 'analysis-' + index,
        start: row.start, end: row.end, evidence: row.evidence, scale: null }));
    }
    const rows = [{ slot: 'window', start: window.start, end: window.end,
      evidence: window.evidence || confidence.evidence, scale: null }];
    (top.scenarios || []).forEach((scenario, index) => rows.push({ slot: 'scenario-' + index,
      start: scenario.q20_date, end: scenario.q80_date, scale: scenario.scale || null,
      evidence: scenario.evidence || confidence.scale_evidence?.[scenario.scale] || confidence.evidence }));
    return rows.filter(row => validDate(row.start) && validDate(row.end) &&
      row.start <= row.end && row.start > record.asof && allowedEvidence(row.evidence));
  }
  function identity(record, window) {
    return { symbol: record.symbol, asof: record.asof, job_id: record.job_id || null,
      original_prediction_id: record.prediction_id || null, source_sha: record.source_sha || null,
      model_version: record.analysis?.model_version || record.model_version || record.code_version || null,
      fit_code_version: record.analysis?.fit_code_version || record.fit_code_version || null, data_version: record.data_version || null,
      fit_input_hash: record.fit_input_hash || null, generated_at: record.generated_at || null,
      window };
  }
  async function sha256(value, crypto) {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)));
    return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  function create(options = {}) {
    const storage = options.storage, now = options.now || Date.now;
    const crypto = options.crypto || root.crypto;
    const locks = options.locks || root.navigator?.locks;
    const entries = new Map();
    let queue = Promise.resolve();
    async function recordVisible(record, window, delivery, stillVisible) {
      if (!candidates(record).some(row => JSON.stringify(row) === JSON.stringify(window)) || !stillVisible()) return null;
      const observedMs = now(), observed = new Date(observedMs).toISOString();
      const chinaDate = new Date(observedMs + 8 * 3600000).toISOString().slice(0, 10);
      const resultIdentity = identity(record, window);
      const digest = await sha256(resultIdentity, crypto);
      if (!stillVisible()) return null; // Selection/tab/viewport may have changed while hashing.
      const key = PREFIX + digest;
      let old = entries.get(key);
      try { old = old || JSON.parse(storage?.getItem(key) || 'null'); } catch {
        // Do not overwrite a damaged saved observation with a later "first" time.
        return null;
      }
      if (old && (old.identity_sha256 !== digest || old.event_type !== 'CURRENT_RESEARCH_WINDOW_FIRST_VISIBLE')) return null;
      if (old?.identity_sha256 === digest && old?.event_type === 'CURRENT_RESEARCH_WINDOW_FIRST_VISIBLE') {
        entries.set(key, old); options.onVisible?.(old); return old;
      }
      const receipt = record.delivery_observation;
      const server = receipt?.schema === 'result_observation_v1' &&
        receipt.job_id === record.job_id && receipt.source_sha === record.source_sha && receipt.mode === 'current'
        ? receipt : null;
      const value = { schema: 'browser_visibility_v1', event_type: 'CURRENT_RESEARCH_WINDOW_FIRST_VISIBLE',
        identity_sha256: digest, identity: resultIdentity, first_visible_at_client: observed,
        client_clock_trust: 'UNTRUSTED_DEVICE_CLOCK', scope: 'THIS_ORIGIN_BROWSER_PROFILE',
        coordination: locks ? 'ORIGIN_WEB_LOCK' : 'THIS_PAGE_ONLY_CROSS_TAB_ORDER_NOT_ESTABLISHED',
        acquisition: delivery?.source || 'unknown', is_cached: delivery?.source !== 'job_result',
        date_relation_at_client_observation: window.end < chinaDate ? 'PAST_WINDOW'
          : window.start <= chinaDate ? 'WINDOW_IN_PROGRESS' : 'FUTURE_WINDOW',
        received_at_client: delivery?.received_at_client || null,
        server_first_observed_at: server?.first_observed_at || null,
        server_result_sha256: server?.result_sha256 || null,
        public_first_published_at: null, original_prediction_identity: record.prediction_id ? 'PRESENT' : 'NOT_ESTABLISHED',
        evidence_status: 'CLIENT_OBSERVATION_NOT_PROOF_OF_ADVANCE_PUBLICATION',
        storage_status: 'MEMORY_ONLY' };
      try {
        if (storage) { value.storage_status = 'BROWSER_LOCAL'; storage.setItem(key, JSON.stringify(value)); }
      } catch { value.storage_status = 'MEMORY_ONLY'; }
      entries.set(key, value);
      options.onRecord?.(value);
      options.onVisible?.(value);
      return value;
    }
    return {
      recordVisible(record, window, delivery, stillVisible = () => false) {
        const task = queue.then(() => locks
          ? locks.request(PREFIX, () => recordVisible(record, window, delivery, stillVisible))
          : recordVisible(record, window, delivery, stillVisible));
        queue = task.catch(() => {}); return task;
      },
      records() {
        try {
          for (let i = 0; i < (storage?.length || 0); i++) {
            const key = storage.key(i);
            if (!key?.startsWith(PREFIX)) continue;
            const value = JSON.parse(storage.getItem(key));
            if (value?.schema === 'browser_visibility_v1' && key === PREFIX + value.identity_sha256) entries.set(key, value);
          }
        } catch { /* Keep available in-memory observations. */ }
        return [...entries.values()].sort((a, b) => a.first_visible_at_client.localeCompare(b.first_visible_at_client));
      },
    };
  }
  function mount(options) {
    const doc = options.document || root.document;
    const ledger = create(options);
    const containers = (options.containers || [options.container]).filter(Boolean);
    let current = null, delivery = null, targets = [], epoch = 0, pending = false, destroyed = false;
    const visible = node => {
      if (destroyed || doc.visibilityState !== 'visible' || !node?.isConnected ||
          node.closest('[hidden], [aria-hidden="true"]')) return false;
      const rect = node.getBoundingClientRect(), style = root.getComputedStyle(node);
      for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const parentStyle = root.getComputedStyle(parent);
        if (parentStyle.display === 'none' || parentStyle.visibility !== 'visible' || Number(parentStyle.opacity) === 0) return false;
      }
      const pointsClear = [rect.left + 1, (rect.left + rect.right) / 2, rect.right - 1].every(x => {
        const top = doc.elementFromPoint(x, (rect.top + rect.bottom) / 2);
        return top === node || node.contains(top);
      });
      return pointsClear &&
        style.display !== 'none' && style.visibility === 'visible' && Number(style.opacity) > 0 &&
        rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.bottom <= root.innerHeight &&
        rect.left >= 0 && rect.right <= root.innerWidth;
    };
    function check() {
      pending = false;
      const version = epoch, record = current, received = delivery;
      for (const { node, window } of targets) {
        const stillVisible = () => epoch === version && current === record && visible(node);
        if (stillVisible()) void ledger.recordVisible(record, window, received, stillVisible).catch(() => {});
      }
    }
    function schedule() {
      if (destroyed || pending || !root.requestAnimationFrame) return;
      pending = true;
      // Two frame boundaries: DOM insertion alone must not count as displayed.
      root.requestAnimationFrame(() => root.requestAnimationFrame(check));
    }
    const observer = root.IntersectionObserver ? new root.IntersectionObserver(schedule) : null;
    doc.addEventListener('visibilitychange', schedule);
    root.addEventListener('scroll', schedule, { passive: true });
    root.addEventListener('resize', schedule);
    return {
      set(record, received) {
        epoch++; current = record; delivery = received; observer?.disconnect(); targets = [];
        for (const window of candidates(record)) {
          const node = containers.map(container => container.querySelector('[data-forecast-window="' + window.slot + '"]')).find(Boolean);
          if (node) { targets.push({ node, window }); observer?.observe(node); }
        }
        schedule();
      },
      records: () => ledger.records(),
      destroy() {
        destroyed = true; epoch++; observer?.disconnect();
        doc.removeEventListener('visibilitychange', schedule);
        root.removeEventListener('scroll', schedule); root.removeEventListener('resize', schedule);
      },
    };
  }
  const exported = { create, candidates, mount };
  if (typeof module === 'object' && module.exports) module.exports = exported;
  else root.StockVisibility = exported;
})(typeof window === 'object' ? window : globalThis);
