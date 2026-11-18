(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ScaleBar = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  var SCALES = ['2-4w', '1-3m', '3-6m', '6-12m', '12-24m', '2-6y'];
  var DEFAULT_SCALE = '6-12m';

  function classify(evidence, confidence, scaleWindows, top, clustersForScale, rules) {
    var levels = evidence || {};
    var values = confidence || {};
    var windows = new Set((scaleWindows || []).map(function (item) { return item.scale; }));
    return SCALES.map(function (scale) {
      var selectable = levels[scale] === 'dev';
      var clusters = typeof clustersForScale === 'function' ? clustersForScale(top, scale) : null;
      var hasWindow = windows.has(scale) || Array.isArray(clusters) && clusters.length > 0;
      var reason = top && rules
        ? rules.emptyReason(top, scale, hasWindow, selectable)
        : null;
      return {
        scale: scale,
        selectable: selectable,
        hasWindow: hasWindow,
        confidence: selectable && Number.isFinite(values[scale]) ? values[scale] : null,
        status: hasWindow && selectable ? '有区间'
          : reason ? rules.reasonText(reason) : !selectable ? '无证据' : '无合格拟合',
      };
    });
  }

  function parseHash(hash, states) {
    var requested = new URLSearchParams(String(hash || '').replace(/^#/, '')).get('scale');
    var allowed = Array.isArray(states)
      ? states.filter(function (state) { return state.selectable; }).map(function (state) { return state.scale; })
      : SCALES;
    return allowed.includes(requested) ? requested : DEFAULT_SCALE;
  }

  return { SCALES: SCALES, DEFAULT_SCALE: DEFAULT_SCALE, classify: classify, parseHash: parseHash };
});
