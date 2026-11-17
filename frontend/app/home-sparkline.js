(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.HomeSparkline = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function numeric(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value !== 'string' || !value.trim()) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function toPct(closes) {
    if (!Array.isArray(closes)) return [];
    const values = closes.map(numeric).filter(value => value !== null);
    const first = values[0];
    if (!Number.isFinite(first) || first === 0) return [];
    return values.map(value => value / first - 1);
  }

  function sharedDomain(seriesList, padding = 0.05) {
    let min = 0;
    let max = 0;
    let hasValue = false;
    if (Array.isArray(seriesList)) {
      for (const series of seriesList) {
        if (!Array.isArray(series)) continue;
        for (const raw of series) {
          const value = numeric(raw);
          if (value === null) continue;
          min = hasValue ? Math.min(min, value) : Math.min(0, value);
          max = hasValue ? Math.max(max, value) : Math.max(0, value);
          hasValue = true;
        }
      }
    }
    if (!hasValue || min === max) return { min: -0.05, max: 0.05 };
    const ratio = Number.isFinite(padding) && padding >= 0 ? padding : 0.05;
    const pad = (max - min) * ratio;
    return { min: min - pad, max: max + pad };
  }

  return Object.freeze({ toPct, sharedDomain });
});
