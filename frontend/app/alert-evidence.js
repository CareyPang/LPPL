(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CPAlertEvidence = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function forScale(history, scale) {
    return history && history.scale_evidence && history.scale_evidence[scale] ||
      history && history.evidence || null;
  }

  function blocked(evidence) {
    var value = String(evidence || '');
    return !value || value === 'none' || value === 'dev_failed' || value.indexOf('fail') === 0;
  }

  function showsNumbers(history, scale) {
    var evidence = forScale(history, scale);
    return !!evidence && evidence !== 'dev_only' && !blocked(evidence);
  }

  return { forScale: forScale, blocked: blocked, showsNumbers: showsNumbers };
});
