/*
 * Optional client for the dated market-context Worker contract.
 *
 * This module is deliberately opt-in.  It does not read static market files,
 * does not fall back from a requested date to `latest`, and does not transform
 * a missing historical snapshot into an empty result.  The host page must
 * explicitly construct the client after the two-snapshot gate has passed.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LPPLMarketContext = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DATE = /^\d{4}-\d{2}-\d{2}$/;

  function validDate(value) {
    if (value === 'latest') return true;
    if (!DATE.test(String(value || ''))) return false;
    const d = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === value;
  }

  function safeError(code, message, status = null, date = null) {
    const error = new Error(message || code);
    error.code = code;
    if (status != null) error.status = status;
    if (date != null) error.date = date;
    return error;
  }

  function validateSnapshot(value, requestedDate) {
    if (!value || typeof value !== 'object') throw safeError('INVALID_SNAPSHOT', '市场背景响应不是对象');
    if (value.error_code) {
      throw safeError(value.error_code, value.error || value.error_code, null, value.date || requestedDate);
    }
    if (typeof value.asof !== 'string' || !DATE.test(value.asof)) {
      throw safeError('INVALID_SNAPSHOT', '市场背景响应缺少有效数据日', null, requestedDate);
    }
    if (requestedDate !== 'latest' && value.asof !== requestedDate) {
      throw safeError('DATE_MISMATCH', '返回数据日与请求日期不一致', null, requestedDate);
    }
    if (value.schema_version && value.schema_version !== 'market-context.v1') {
      throw safeError('SCHEMA_MISMATCH', '市场背景响应版本不受支持', null, requestedDate);
    }
    return value;
  }

  function createMarketContextClient(options = {}) {
    const baseUrl = String(options.baseUrl || '').replace(/\/$/, '');
    const fetchImpl = options.fetchImpl || (typeof fetch === 'function' ? fetch : null);
    const enabled = options.enabled === true;
    const intervalMs = Math.max(1000, Number(options.intervalMs || 300000));
    const onState = typeof options.onState === 'function' ? options.onState : () => {};
    let timer = null;
    let currentDate = 'latest';
    const lastByDate = new Map();

    function state(next) {
      onState(next);
      return next;
    }

    async function get(date = currentDate) {
      if (!validDate(date)) throw safeError('INVALID_DATE', '日期必须是 latest 或 YYYY-MM-DD', null, date);
      currentDate = date;
      if (!enabled) return state({ status: 'disabled', date, snapshot: null });
      if (!baseUrl) throw safeError('CLIENT_NOT_CONFIGURED', '市场背景 Worker 地址尚未配置', null, date);
      if (!fetchImpl) throw safeError('FETCH_UNAVAILABLE', '当前环境不支持网络读取', null, date);
      const response = await fetchImpl(`${baseUrl}/context?date=${encodeURIComponent(date)}`, {
        method: 'GET', cache: 'no-store', headers: { Accept: 'application/json' },
      });
      let body = null;
      try { body = await response.json(); } catch { throw safeError('INVALID_RESPONSE', '市场背景响应不是有效 JSON', response.status, date); }
      if (!response.ok) {
        throw safeError(body?.error_code || 'CONTEXT_UNAVAILABLE', body?.error || '该日期尚无已封存市场背景快照', response.status, date);
      }
      const snapshot = validateSnapshot(body, date);
      lastByDate.set(date, snapshot);
      const stale = snapshot.status === 'stale' || snapshot.source?.status === 'stale';
      return state({
        status: stale ? 'stale' : 'ready',
        date,
        snapshot,
        lastGoodAsOf: snapshot.last_good_asof || snapshot.asof || null,
        staleReason: snapshot.stale_reason || snapshot.source?.stale_reason || null,
        fetchedAt: snapshot.source?.fetched_at || snapshot.fetched_at || null,
      });
    }

    function stop() {
      if (timer != null) clearInterval(timer);
      timer = null;
    }

    function start(date = currentDate) {
      stop();
      currentDate = date;
      void get(date).catch((error) => state({
        status: 'error', date, error, snapshot: lastByDate.get(date) || null,
        retained: lastByDate.has(date),
      }));
      if (enabled) timer = setInterval(() => {
        void get(currentDate).catch((error) => state({
          status: 'error', date: currentDate, error, snapshot: lastByDate.get(currentDate) || null,
          retained: lastByDate.has(currentDate),
        }));
      }, intervalMs);
      return { status: enabled ? 'started' : 'disabled', date };
    }

    return Object.freeze({ get, start, stop, setDate: (date) => get(date), isEnabled: () => enabled });
  }

  return Object.freeze({ createMarketContextClient, validDate, validateSnapshot });
});
