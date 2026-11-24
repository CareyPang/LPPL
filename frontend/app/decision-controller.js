/* One read-only history request per asset/vintage. Prices never wait for it. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LPPLDecisionController = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  function attach(options) {
    var context = options.context, adapter = options.adapter, reader = options.reader;
    var slots = new Map(), current = null, closed = false, revision = 0;
    function key(data) {
      return [context.code, context.assetType, context.asof || data.modelAsOf || data.asof || ''].join('|');
    }
    function emit() {
      if (closed || !current) return;
      var slot = slots.get(key(current));
      var view = options.state.build({ data: current, history: slot && slot.history,
        context: Object.assign({}, context), historyStatus: slot && slot.status || 'loading' });
      view.provenance = Object.assign({}, view.provenance, {
        historyStatus: slot && slot.status || 'loading', historyError: slot && slot.error || ''
      });
      options.onChange(view);
      return view;
    }
    function request(data) {
      var identity = key(data);
      if (slots.has(identity)) return;
      var slot = { status: 'loading', history: null, error: '' };
      slots.set(identity, slot);
      var captured = Object.assign({}, context), token = revision;
      var work = function () {
        if (reader.globalAsset(adapter, captured)) return adapter.global.history(captured.code);
        if (captured.assetType === 'index' && captured.market && captured.market !== 'cn') {
          throw Error('该市场尚无底部评分历史。');
        }
        return captured.assetType === 'index' ? adapter.history(captured.code)
          : adapter.stock.history(captured.stockCode || captured.code);
      };
      slot.promise = Promise.resolve().then(function () { return reader.timed(work, '底部评分记录'); })
        .then(function (history) {
          if (!history || !history.symbol || !reader.sameSymbol(history.symbol, captured)) {
            throw Error('评分记录的资产身份未通过核对。');
          }
          slot.history = history; slot.status = 'ready';
        }).catch(function (error) {
          slot.status = 'error'; slot.error = error.message || '评分记录未读到';
        }).then(function () {
          if (!closed && token === revision && current && key(current) === identity) emit();
        });
    }
    return {
      render: function (data) { current = data; request(data); return emit(); },
      retry: function () {
        if (!current) return;
        slots.delete(key(current)); revision++;
        request(current); return emit();
      },
      close: function () { closed = true; revision++; current = null; }
    };
  }
  return { attach: attach };
});
