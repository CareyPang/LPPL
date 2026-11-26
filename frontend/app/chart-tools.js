/* 临界点 · 指数页行情工具：均线与副图指标。只作行情工具，不参与任何信号或结论。
   每个值只用当日及之前的收盘/最高/最低，缺数据处返回 null。 */
(function (root) {
  'use strict';
  var DEFAULT_MA = [20, 60];
  var MA_COLORS = ['#B26A00', '#1F5FD6', '#7A3FB8', '#0E7C86', '#5B6270'];
  function parsePeriods(text) {
    var seen = {}, out = [];
    String(text == null ? '' : text).split(/[^0-9]+/).forEach(function (part) {
      var n = parseInt(part, 10);
      if (n >= 2 && n <= 500 && !seen[n] && out.length < 5) { seen[n] = true; out.push(n); }
    });
    return out;
  }
  function sma(values, n) {
    var out = new Array(values.length).fill(null), sum = 0;
    for (var i = 0; i < values.length; i++) {
      sum += values[i];
      if (i >= n) sum -= values[i - n];
      if (i >= n - 1) out[i] = sum / n;
    }
    return out;
  }
  function ema(values, n) {
    var out = new Array(values.length), k = 2 / (n + 1);
    for (var i = 0; i < values.length; i++) out[i] = i ? values[i] * k + out[i - 1] * (1 - k) : values[i];
    return out;
  }
  function macd(close) {
    var fast = ema(close, 12), slow = ema(close, 26);
    var dif = close.map(function (_, i) { return fast[i] - slow[i]; }), dea = ema(dif, 9);
    return { dif: dif, dea: dea, hist: dif.map(function (v, i) { return 2 * (v - dea[i]); }) };
  }
  function rsi(close, n) {
    n = n || 14;
    var out = new Array(close.length).fill(null), up = 0, dn = 0;
    for (var i = 1; i < close.length; i++) {
      var d = close[i] - close[i - 1], u = d > 0 ? d : 0, v = d < 0 ? -d : 0;
      if (i <= n) { up += u / n; dn += v / n; } else { up = (up * (n - 1) + u) / n; dn = (dn * (n - 1) + v) / n; }
      if (i >= n) out[i] = up + dn === 0 ? 50 : 100 * up / (up + dn);
    }
    return out;
  }
  function kdj(bars, n) {
    n = n || 9;
    var k = [], d = [], j = [], pk = 50, pd = 50;
    for (var i = 0; i < bars.length; i++) {
      var hi = -Infinity, lo = Infinity;
      for (var m = Math.max(0, i - n + 1); m <= i; m++) { hi = Math.max(hi, bars[m].high); lo = Math.min(lo, bars[m].low); }
      var rsv = hi > lo ? (bars[i].close - lo) / (hi - lo) * 100 : 50;
      pk = (2 * pk + rsv) / 3; pd = (2 * pd + pk) / 3;
      k.push(pk); d.push(pd); j.push(3 * pk - 2 * pd);
    }
    return { k: k, d: d, j: j };
  }
  var api = { DEFAULT_MA: DEFAULT_MA, MA_COLORS: MA_COLORS, parsePeriods: parsePeriods, sma: sma, ema: ema, macd: macd, rsi: rsi, kdj: kdj };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CPChartTools = api;
})(typeof window !== 'undefined' ? window : globalThis);
