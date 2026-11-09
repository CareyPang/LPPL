/* Explicit offline presentation adapter. It never calls a network or model API. */
(function (root) {
  'use strict';
  const STORE = 'lppl.presentation.jobs.v1';
  const clone = value => value == null ? null : JSON.parse(JSON.stringify(value));
  function create(data, options = {}) {
    const now = options.now || Date.now;
    const storage = options.storage;
    const duration = options.durationMs ?? 7000;
    const samples = data?.samples || {};
    const jobs = new Map();
    const supported = code => {
      if (!samples[code]) throw Error('此离线演示只包含贵州茅台（600519）的真实冻结行情；没有请求线上服务。');
      return samples[code];
    };
    const save = () => { try { storage?.setItem(STORE, JSON.stringify([...jobs.values()])); } catch { /* Optional persistence. */ } };
    try {
      const saved = JSON.parse(storage?.getItem(STORE) || '[]');
      if (Array.isArray(saved)) for (const job of saved.slice(-16)) {
        if (samples[job?.code] && ['current', 'history'].includes(job.mode) &&
            /^[a-f0-9-]{36}$/i.test(job.job_id || '') && Number.isFinite(job.started) &&
            job.started <= now() && now() - job.started < 7 * 86400000) jobs.set(job.job_id, job);
      }
    } catch { /* Invalid presentation state never affects live state. */ }
    function result(job) {
      const market = supported(job.code);
      return { code: job.code, symbol: market.symbol, name: market.name, asof: market.asof,
        job_id: job.job_id, requested_at: job.requested_at, generated_at: job.requested_at,
        source_sha: job.source_sha, mode: job.mode, data_version: 'frozen_v20261104_presentation',
        model_version: 'presentation_no_model', variant: 'presentation_no_model',
        demo: true, model_computed: false, evidence: 'none', frames: [],
        top: { signal_status: 'not_computed', window: { start: null, end: null, evidence: 'none' },
          lppls_confidence: { evidence: 'none' }, drawdown_price: { value: null, evidence: 'none' } } };
    }
    function latest(code, mode) {
      supported(code);
      const done = [...jobs.values()].filter(job => job.code === code && job.mode === mode && now() - job.started >= duration);
      done.sort((a, b) => b.started - a.started);
      return done.length ? result(done[0]) : null;
    }
    return {
      isDemo: true, codes: Object.keys(samples),
      async market(code) { return clone(supported(code)); },
      async latest(code) { return latest(code, 'current'); },
      async history(code) { return latest(code, 'history'); },
      async dipEnv() { return null; },
      async request(code, request = {}) {
        const market = supported(code), mode = request.mode || 'current';
        if (!['current', 'history'].includes(mode)) throw Error('未知的演示任务。');
        const existing = [...jobs.values()].find(job => job.code === code && job.mode === mode && now() - job.started < duration);
        if (existing) return clone(existing);
        const id = options.uuid ? options.uuid() : root.crypto?.randomUUID?.() ||
          'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, char => {
            const value = Math.floor(Math.random() * 16); return (char === 'x' ? value : (value & 3) | 8).toString(16);
          });
        const job = { code, mode, job_id: id, started: now(), requested_at: new Date(now()).toISOString(),
          source_sha: market.provenance.source_sha256, demo: true };
        jobs.set(id, job); save(); return clone(job);
      },
      async status(code, request = {}) {
        supported(code);
        const job = jobs.get(request.jobId);
        if (!job || job.code !== code) {
          const error = Error('演示任务记录已过期，可以重新演示。');
          error.status = 404; error.code = 'JOB_NOT_FOUND'; throw error;
        }
        const elapsed = now() - job.started, ready = elapsed >= duration;
        return { job_id: job.job_id, status: ready ? 'completed' : elapsed < duration * .3 ? 'queued' : 'in_progress',
          conclusion: ready ? 'success' : null, current_ready: ready && job.mode === 'current',
          history_ready: ready && job.mode === 'history', demo: true, model_computed: false };
      },
      async remote(code, kind = 'latest', request = {}) {
        supported(code);
        if (kind === 'error') return null;
        const mode = kind === 'history' ? 'history' : 'current';
        if (!request.jobId) return latest(code, mode);
        const job = jobs.get(request.jobId);
        return job && job.code === code && job.mode === mode && now() - job.started >= duration ? result(job) : null;
      },
    };
  }
  const api = { create };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.StockDemo = api;
})(typeof window === 'object' ? window : globalThis);
