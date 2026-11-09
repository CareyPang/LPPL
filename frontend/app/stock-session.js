/* Query orchestration only. All business data is obtained through LPPL.stock. */
(function (root) {
  'use strict';
  const STORE = 'lppl.stock.jobs.v1';
  const CODE = /^(?:60|68|00|30|43|83|87|92)\d{4}$/;
  const JOB = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const MODES = ['current', 'history'];
  const symbol = code => (code.startsWith('6') ? 'sh' : /^[03]/.test(code) ? 'sz' : 'bj') + code;
  function compatible(current, history) {
    if (!current || !history || current.symbol !== history.symbol) return false;
    const version = (value) => value.model_version || value.code_version || value.stock_meta?.code_version;
    const variant = (value) => value.variant || value.stock_meta?.variant;
    const a = version(current), b = version(history);
    if (!a || a !== b || !variant(current) || variant(current) !== variant(history)) return false;
    // Static Pages history and a newer API current result may arrive independently.
    // Match the publisher's scientific compatibility checks before combining them.
    for (const key of ['schema_version', 'model_version', 'fit_code_version']) {
      if ((key in current || key in history) && current[key] !== history[key]) return false;
    }
    const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      Number.isFinite(Date.parse(value + 'T00:00:00Z')) &&
      new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
    if (!validDate(current.asof) ||
        (history.asof && (!validDate(history.asof) || history.asof > current.asof)) ||
        !Array.isArray(history.frames) || !history.frames.every(frame =>
          frame && validDate(frame.asof) && frame.asof <= current.asof)) return false;
    if (('data_version' in current || 'data_version' in history) && current.data_version !== history.data_version) {
      const fingerprints = current.history_input_hashes || {};
      if (!history.frames.length || !history.frames.every(frame =>
        typeof frame.fit_input_hash === 'string' && frame.fit_input_hash &&
        frame.fit_input_hash === fingerprints[frame.asof])) return false;
    }
    return true;
  }
  function newer(incoming, previous) {
    if (!previous) return true;
    const a = String(incoming.asof || ''), b = String(previous.asof || '');
    if (a !== b) return a > b;
    const stamp = value => Date.parse(value.requested_at || value.generated_at || '') || 0;
    return stamp(incoming) >= stamp(previous);
  }
  function stale(current, market) {
    if (!current) return true;
    if (!market) return false;
    return String(current.asof || '') < market.asof ||
      !!(market.expected_source_sha && current.source_sha !== market.expected_source_sha);
  }
  function create(options) {
    const api = options.api;
    const validCode = value => api.resolveCode ? (() => {
      try { return api.resolveCode(String(value)) === value; } catch { return false; }
    })() : CODE.test(String(value));
    const assetSymbol = value => api.symbolFor ? api.symbolFor(value) : symbol(value);
    const clock = options.now || Date.now;
    const timer = options.setTimeout || setTimeout;
    const untimer = options.clearTimeout || clearTimeout;
    const interval = options.pollMs || 5000;
    const storage = options.storage;
    const entries = new Map(), jobs = new Map(), watches = new Map();
    let selected = null, closed = false;

    function entry(code) {
      if (!validCode(code)) throw Error('请输入支持的资产代码或名称。');
      if (!entries.has(code)) entries.set(code, {
        code, market: null, current: null, history: null, marketStatus: 'idle',
        currentStatus: 'idle', historyStatus: 'idle', issues: {}, autoAttempted: false,
      });
      return entries.get(code);
    }
    function emit() {
      if (!closed && selected) options.onChange?.({
        ...entry(selected),
        tasks: [...jobs.values()],
        recent: [...entries.keys()].reverse().slice(0, 8),
      });
    }
    function save() {
      try { storage?.setItem(STORE, JSON.stringify([...jobs.values()])); } catch { /* Private browsing. */ }
    }
    try {
      const saved = JSON.parse(storage?.getItem(STORE) || '[]');
      if (Array.isArray(saved)) for (const job of saved.slice(0, 16)) {
        const when = Date.parse(job?.requested_at);
        if (validCode(job?.code) && JOB.test(String(job?.job_id)) &&
            MODES.includes(job.mode) && !(api.historySupported === false && job.mode === 'history') && Number.isFinite(when) &&
            when <= clock() + 60000 && when > clock() - 7 * 86400000) {
          jobs.set(job.code + ':' + job.mode, job);
        }
      }
    } catch { /* Corrupt browser state must not block the page. */ }

    function applyCurrent(e, value, source) {
      if (!value || value.symbol !== assetSymbol(e.code)) return;
      if (newer(value, e.current)) {
        e.current = value;
        e.currentDelivery = { source, received_at_client: new Date(clock()).toISOString() };
        e.stale = stale(value, e.market);
        if (!jobs.has(e.code + ':current') && ['idle', 'ready'].includes(e.currentStatus)) e.currentStatus = 'ready';
        emit();
      }
    }
    function applyHistory(e, value) {
      if (!value || value.symbol !== assetSymbol(e.code)) return;
      if (newer(value, e.history)) {
        e.history = value;
        if (!jobs.has(e.code + ':history') && ['idle', 'ready'].includes(e.historyStatus)) e.historyStatus = 'ready';
        emit();
      }
    }
    function finish(key, e, mode, status, issue) {
      jobs.delete(key);
      watches.delete(key);
      e[mode + 'Status'] = status;
      if (issue) e.issues[mode] = issue;
      else delete e.issues[mode];
      save(); emit();
    }
    function watch(job) {
      const key = job.code + ':' + job.mode;
      if (closed || watches.has(key)) return;
      const e = entry(job.code);
      const watcher = { started: clock(), timer: null, busy: false };
      watches.set(key, watcher);
      e[job.mode + 'Status'] = 'queued';
      emit();
      async function poll() {
        if (closed || watches.get(key) !== watcher || watcher.busy) return;
        watcher.busy = true;
        try {
          const state = await api.status(job.code, { jobId: job.job_id });
          if (closed || watches.get(key) !== watcher) return;
          if (state.job_id && state.job_id !== job.job_id) throw Error('任务标识不匹配，正在重新确认。');
          const ready = job.mode === 'history' ? state.history_ready : state.current_ready;
          if (ready) {
            const result = await api.remote(job.code, job.mode === 'history' ? 'history' : 'latest', { jobId: job.job_id });
            if (closed || watches.get(key) !== watcher) return;
            if (!result || result.job_id !== job.job_id ||
                result.symbol !== assetSymbol(job.code) ||
                (job.source_sha && result.source_sha !== job.source_sha)) {
              throw Error('结果身份或版本尚未核对完成，稍后自动重试。');
            }
            if (job.mode === 'history') applyHistory(e, result); else applyCurrent(e, result, 'job_result');
            finish(key, e, job.mode, 'ready');
            return;
          }
          if (state.status === 'completed' && state.conclusion && state.conclusion !== 'success') {
            finish(key, e, job.mode, 'failed', '本次更新未完成，已有行情和分析仍可查看。');
            return;
          }
          e[job.mode + 'Status'] = state.status === 'queued' || state.status === 'pending' ? 'queued' :
            state.status === 'completed' ? 'publishing' : 'running';
          delete e.issues[job.mode];
          emit();
        } catch (error) {
          if (closed || watches.get(key) !== watcher) return;
          if (error.status === 404 && error.code === 'JOB_NOT_FOUND') {
            if (job.mode === 'current') e.autoAttempted = true;
            finish(key, e, job.mode, 'failed',
              '原任务记录已不可用；已有结果仍可查看，请点击更新重新查询。');
            return;
          }
          e[job.mode + 'Status'] = 'reconnecting';
          e.issues[job.mode] = error.message || '连接暂时中断，任务仍保留。';
          emit();
        } finally { watcher.busy = false; }
        if (closed || watches.get(key) !== watcher) return;
        if (clock() - watcher.started >= (options.maxWatchMs || 30 * 60000)) {
          watches.delete(key);
          e[job.mode + 'Status'] = 'paused';
          e.issues[job.mode] = '已暂停本页查询；任务仍保留，点击继续查看可恢复。';
          emit();
          return;
        }
        watcher.timer = timer(poll, interval);
      }
      void poll();
    }
    async function request(code, mode = 'current') {
      if (!MODES.includes(mode)) throw Error('未知任务类型。');
      if (mode === 'history' && api.historySupported === false) throw Error('当前预览仅运行最新一期，历史回放尚未开放。');
      const e = entry(code), key = code + ':' + mode;
      const pending = jobs.get(key);
      if (pending) { watch(pending); return pending; }
      if (e[mode + 'Status'] === 'submitting') return null;
      e[mode + 'Status'] = 'submitting'; delete e.issues[mode]; emit();
      try {
        const result = await api.request(code, { mode, historyWeeks: mode === 'history' ? 104 : 0 });
        if (!JOB.test(String(result?.job_id)) || !Number.isFinite(Date.parse(result.requested_at))) {
          throw Error('查询服务尚未支持可恢复任务，请稍后重试。');
        }
        const job = {
          code, mode, job_id: result.job_id, requested_at: result.requested_at,
          source_sha: result.source_sha || null,
        };
        jobs.set(key, job); save();
        if (!closed) watch(job);
        return job;
      } catch (error) {
        e[mode + 'Status'] = error.code === 'REQUEST_TIMEOUT' ? 'unconfirmed' : 'failed';
        e.issues[mode] = error.code === 'REQUEST_TIMEOUT' ?
          '提交结果暂未确认，后台任务可能仍在继续。可再次查询，服务端会复用已有任务。' :
          error.message || '暂时不能创建任务，已有结果不受影响。';
        emit();
        return null;
      }
    }
    function select(code) {
      const e = entry(code);
      const generation = e.generation = (e.generation || 0) + 1;
      selected = code;
      e.marketStatus = 'loading'; delete e.issues.market; emit();
      for (const mode of MODES) {
        const job = jobs.get(code + ':' + mode);
        if (job) {
          if (mode === 'current') e.autoAttempted = true;
          watch(job);
        }
      }
      const latest = Promise.resolve().then(() => api.latest(code))
        .then(value => applyCurrent(e, value, 'static_cache')).catch(() => {});
      const remote = Promise.resolve().then(() => api.remote(code, 'latest'))
        .then(value => applyCurrent(e, value, 'remote_cache')).catch(error => { e.issues.cached = error.message; emit(); });
      const market = Promise.resolve().then(() => api.market(code)).then(value => {
        if (generation !== e.generation) return;
        if (!value || value.code !== code || !Array.isArray(value.price)) throw Error('行情返回格式不正确。');
        if (value.symbol && value.symbol !== assetSymbol(code)) throw Error('行情标的身份不匹配。');
        if (!e.market || newer(value, e.market)) e.market = value;
        if (value.stale === true || value.cache === 'stale') {
          e.marketStatus = 'stale';
          const reason = value.warning_code === 'RATE_LIMITED' ? '行情刷新额度暂时用尽' : '行情源暂时无法更新';
          e.issues.market = reason + '，正在显示截至 ' + e.market.asof + ' 的缓存日线。';
        } else {
          e.marketStatus = 'ready'; delete e.issues.market;
        }
        emit();
      }).catch(error => {
        if (generation !== e.generation) return;
        e.marketStatus = e.market ? 'stale' : 'failed';
        e.issues.market = e.market ?
          '行情刷新未完成，保留截至 ' + e.market.asof + ' 的缓存日线。' : error.message;
        emit();
      });
      // History is deliberately outside the readiness barrier.
      if (api.historySupported !== false) {
        void Promise.resolve().then(() => api.history(code)).then(value => applyHistory(e, value)).catch(() => {});
        void Promise.resolve().then(() => api.remote(code, 'history')).then(value => applyHistory(e, value)).catch(() => {});
      }
      return Promise.allSettled([latest, remote, market]).then(async () => {
        if (closed || generation !== e.generation) return;
        e.stale = stale(e.current, e.market);
        emit();
        if (!e.autoAttempted && !jobs.has(code + ':current') && e.stale) {
          e.autoAttempted = true;
          await request(code);
        }
      });
    }
    return {
      select, request,
      snapshot: () => selected ? { ...entry(selected), tasks: [...jobs.values()] } : null,
      resume: (code, mode) => { const job = jobs.get(code + ':' + mode); if (job) watch(job); },
      destroy() {
        closed = true;
        for (const value of watches.values()) if (value.timer !== null) untimer(value.timer);
        watches.clear();
      },
    };
  }
  const exported = { create, compatible, stale };
  if (typeof module === 'object' && module.exports) module.exports = exported;
  else root.StockSession = exported;
})(typeof window === 'object' ? window : globalThis);
