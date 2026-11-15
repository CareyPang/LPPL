/* Browser-local observation only. This is not a server publication timestamp. */
(function (root) {
  'use strict';
  const STORE = 'lppl.stock.visibility.v1';
  function identity(result) {
    if (!result?.symbol || !result.asof) return null;
    return JSON.stringify([result.symbol, result.mode || 'current', result.job_id || null,
      result.asof, result.generated_at || null, result.source_sha || null,
      result.model_version || null, result.data_version || null]);
  }
  function create(options = {}) {
    const doc = options.document || root.document;
    const host = options.window || root;
    const clock = options.now || Date.now;
    const raf = options.requestAnimationFrame || host.requestAnimationFrame.bind(host);
    const cancel = options.cancelAnimationFrame || host.cancelAnimationFrame.bind(host);
    const storage = options.storage;
    let rows = {}, target = null, value = null, generation = 0, frame = null, destroyed = false;
    try {
      const saved = JSON.parse(storage?.getItem(STORE) || '{}');
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) rows = saved;
    } catch { /* Browser persistence is optional. */ }
    function visible() {
      if (destroyed || !target || target.hidden || doc.visibilityState !== 'visible' || !target.isConnected) return false;
      const rect = target.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 &&
        rect.top < host.innerHeight && rect.left < host.innerWidth;
    }
    function check() {
      if (!visible() || frame !== null || !identity(value)) return;
      const token = generation;
      // Two frames permit the result DOM to paint before recording observation.
      frame = raf(() => {
        frame = null;
        if (token !== generation || !visible()) return;
        frame = raf(() => {
          frame = null;
          if (token !== generation || !visible()) return;
          const key = identity(value);
          let record = rows[key];
          if (!record || !Number.isFinite(Date.parse(record.first_visible_at_client))) {
            record = {
              schema_version: 'browser_visibility_v1', symbol: value.symbol,
              job_id: value.job_id || null, mode: value.mode || 'current', asof: value.asof,
              first_visible_at_client: new Date(clock()).toISOString(),
              first_worker_observed_at: value.delivery_observation?.first_worker_observed_at || value.first_worker_observed_at || null,
              client_clock_trust: 'unverified', scope: 'this_browser',
              publication_evidence: 'NOT_ESTABLISHED',
            };
            rows[key] = record;
            try { storage?.setItem(STORE, JSON.stringify(rows)); } catch { /* Keep the in-memory observation. */ }
          }
          options.onVisible?.(record);
        });
      });
    }
    const observer = host.IntersectionObserver ? new host.IntersectionObserver(check) : null;
    doc.addEventListener('visibilitychange', check);
    host.addEventListener('scroll', check, { passive: true });
    host.addEventListener('resize', check, { passive: true });
    return {
      observe(element, result) {
        generation += 1;
        if (frame !== null) { cancel(frame); frame = null; }
        observer?.disconnect(); target = element; value = result;
        if (target) observer?.observe(target);
        check();
      },
      destroy() {
        destroyed = true; generation += 1;
        if (frame !== null) cancel(frame);
        observer?.disconnect();
        doc.removeEventListener('visibilitychange', check);
        host.removeEventListener('scroll', check);
        host.removeEventListener('resize', check);
      },
    };
  }
  const exported = { create, identity };
  if (typeof module === 'object' && module.exports) module.exports = exported;
  else root.StockVisibility = exported;
})(typeof window === 'object' ? window : globalThis);
