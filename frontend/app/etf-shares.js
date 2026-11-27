/* 宽基 ETF 份额与规模图：份额面积 + 规模线 + 每日明细。只读已发布的 nt_etf 数据，不参与任何结论。 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EtfShares = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var num = function (v) { return typeof v === 'number' && isFinite(v); };

  /* 历史归档行 [日期, 份额亿份, 收盘, 申赎估算] 与日更行合并；同一天以日更为准，缺份额的日子不画 */
  function merge(liveRows, histRows) {
    var by = {};
    (histRows || []).forEach(function (r) { if (r && r[0]) by[r[0]] = [r[0], r[1], r[2], r[3]]; });
    (liveRows || []).forEach(function (r) { if (r && r[0] && (num(r[1]) || !by[r[0]])) by[r[0]] = [r[0], r[1], r[2], r[3]]; });
    return Object.keys(by).sort().map(function (d) {
      var r = by[d], s = num(r[1]) ? r[1] : null, c = num(r[2]) ? r[2] : null;
      return { d: d, shares: s, close: c, value: s != null && c != null ? s * c : null, flow: num(r[3]) ? r[3] : null };
    });
  }

  /* 多只 ETF 按日相加；某只当天缺份额时沿用它上一次已知份额，首次出现前不计入。
     申赎估算取各只已发布值之和，任一只当天没有估算时合计记为缺失 */
  function sum(list) {
    var days = {}, last = list.map(function () { return null; });
    list.forEach(function (rows) { rows.forEach(function (r) { days[r.d] = 1; }); });
    var maps = list.map(function (rows) { var m = {}; rows.forEach(function (r) { m[r.d] = r; }); return m; });
    return Object.keys(days).sort().map(function (d) {
      var shares = 0, value = 0, n = 0, vn = 0, flow = 0, fn = 0, seen = 0;
      maps.forEach(function (m, i) {
        var r = m[d];
        if (r && r.shares != null) seen++;
        if (r && r.shares != null) last[i] = { shares: r.shares, close: r.close != null ? r.close : (last[i] && last[i].close) };
        else if (r && r.close != null && last[i]) last[i] = { shares: last[i].shares, close: r.close };
        if (last[i]) { shares += last[i].shares; n++; if (r && r.flow != null) { flow += r.flow; fn++; } if (last[i].close != null) { value += last[i].shares * last[i].close; vn++; } }
      });
      return { d: d, shares: n ? shares : null, close: null, value: n && vn === n ? value : null, flow: n && fn === n ? flow : null, n: n, seen: seen };
    });
  }

  /* 归档文件按列存放（公共日期表 + 每只 ETF 的起始下标），展开成某只 ETF 的行 */
  function historyRows(hist, code) {
    var e = hist && hist.etfs && hist.etfs[code], dates = hist && hist.dates;
    if (!e || !dates || !e.shares) return [];
    return e.shares.map(function (s, i) { return [dates[e.from + i], s, e.close[i], e.flow[i]]; })
      .filter(function (r) { return r[0] && (num(r[1]) || num(r[2])); });
  }

  function sliceRange(rows, range) {
    var known = rows.filter(function (r) { return r.shares != null; });
    if (!known.length || range === 'all') return known;
    var end = new Date(known[known.length - 1].d + 'T00:00:00Z');
    var months = range === '3m' ? 3 : range === '6m' ? 6 : range === '3y' ? 36 : 12;
    end.setUTCMonth(end.getUTCMonth() - months);
    var from = end.toISOString().slice(0, 10);
    return known.filter(function (r) { return r.d >= from; });
  }

  /* 合计行只有在前后两天成分相同且每只当天都有份额时才可相减 */
  function comparable(p, r) { return r.n == null || (p.n === r.n && p.seen === p.n && r.seen === r.n); }

  /* 明细表：新的在前。变动只与紧邻的上一交易日比，上一日缺份额时记为缺失；申赎估算用已发布值，不在前端重算 */
  function tableRows(rows, from) {
    var out = [];
    rows.forEach(function (r, i) {
      if (r.shares == null || (from && r.d < from)) return;
      var p = i ? rows[i - 1] : null;
      out.push({ d: r.d, shares: r.shares, chg: p && p.shares != null && comparable(p, r) ? r.shares - p.shares : null, value: r.value, flow: r.flow });
    });
    return out.reverse();
  }

  function ticks(min, max, n) {
    if (!(max > min)) { max = min + 1; }
    var raw = (max - min) / n, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), f = raw / mag;
    var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * mag, out = [];
    for (var v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  var fmt = function (v, d) { return num(v) ? v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—'; };

  function draw(canvas, rows, hover) {
    var w = canvas.clientWidth, h = canvas.clientHeight, dpr = (typeof devicePixelRatio === 'number' && devicePixelRatio) || 1;
    canvas.width = w * dpr; canvas.height = h * dpr;
    var c = canvas.getContext('2d'); c.scale(dpr, dpr); c.clearRect(0, 0, w, h);
    var L = 46, R = 52, T = 10, B = 22, pw = w - L - R, ph = h - T - B;
    c.font = '10px Inter,system-ui,sans-serif'; c.textBaseline = 'middle';
    if (!rows.length || pw <= 0) { c.fillStyle = '#6a6d78'; c.fillText('暂无份额数据', L, h / 2); return null; }
    var sh = rows.map(function (r) { return r.shares; }), va = rows.map(function (r) { return r.value; }).filter(num);
    var sMax = Math.max.apply(null, sh) * 1.05, sT = ticks(0, sMax, 4);
    var vMin = va.length ? Math.min.apply(null, va) : 0, vMax = va.length ? Math.max.apply(null, va) : 1, pad = (vMax - vMin) * 0.08 || 1;
    vMin = Math.max(0, vMin - pad); vMax += pad;
    var vT = ticks(vMin, vMax, 4);
    var x = function (i) { return L + (rows.length > 1 ? i / (rows.length - 1) : 0.5) * pw; };
    var ys = function (v) { return T + ph - v / sMax * ph; }, yv = function (v) { return T + ph - (v - vMin) / (vMax - vMin) * ph; };
    c.strokeStyle = '#eef1f6'; c.lineWidth = 1;
    sT.forEach(function (t) { var y = Math.round(ys(t)) + 0.5; c.beginPath(); c.moveTo(L, y); c.lineTo(L + pw, y); c.stroke(); });
    c.textAlign = 'right'; c.fillStyle = '#b36a00';
    sT.forEach(function (t) { c.fillText(fmt(t, 0), L - 6, ys(t)); });
    c.textAlign = 'left'; c.fillStyle = '#1f5fd6';
    vT.forEach(function (t) { c.fillText(fmt(t, 0), L + pw + 6, yv(t)); });
    c.beginPath(); c.moveTo(x(0), ys(0));
    rows.forEach(function (r, i) { c.lineTo(x(i), ys(r.shares)); });
    c.lineTo(x(rows.length - 1), ys(0)); c.closePath(); c.fillStyle = 'rgba(240,160,75,.55)'; c.fill();
    c.beginPath(); rows.forEach(function (r, i) { i ? c.lineTo(x(i), ys(r.shares)) : c.moveTo(x(i), ys(r.shares)); });
    c.strokeStyle = '#e08a2b'; c.lineWidth = 1.2; c.stroke();
    c.beginPath(); var open = false;
    rows.forEach(function (r, i) {
      if (r.value == null) { open = false; return; }
      open ? c.lineTo(x(i), yv(r.value)) : c.moveTo(x(i), yv(r.value)); open = true;
    });
    c.strokeStyle = '#1f5fd6'; c.lineWidth = 1.6; c.stroke();
    c.fillStyle = '#6a6d78'; c.textBaseline = 'alphabetic';
    var n = Math.min(5, rows.length), seen = {};
    for (var k = 0; k < n; k++) {
      var i = n > 1 ? Math.round(k * (rows.length - 1) / (n - 1)) : 0;
      if (seen[i]) continue; seen[i] = 1;
      c.textAlign = k === 0 ? 'left' : k === n - 1 ? 'right' : 'center';
      c.fillText(rows[i].d, x(i), h - 6);
    }
    if (hover != null && rows[hover]) {
      var hx = Math.round(x(hover)) + 0.5;
      c.strokeStyle = '#9aa0ad'; c.lineWidth = 1; c.beginPath(); c.moveTo(hx, T); c.lineTo(hx, T + ph); c.stroke();
      c.fillStyle = '#e08a2b'; c.beginPath(); c.arc(x(hover), ys(rows[hover].shares), 3, 0, 6.3); c.fill();
      if (rows[hover].value != null) { c.fillStyle = '#1f5fd6'; c.beginPath(); c.arc(x(hover), yv(rows[hover].value), 3, 0, 6.3); c.fill(); }
    }
    return { left: L, width: pw };
  }

  function indexAt(geom, n, px) {
    if (!geom || !n) return null;
    var t = (px - geom.left) / geom.width;
    return Math.max(0, Math.min(n - 1, Math.round(t * (n - 1))));
  }

  return { merge: merge, historyRows: historyRows, sum: sum, sliceRange: sliceRange, tableRows: tableRows, ticks: ticks, fmt: fmt, draw: draw, indexAt: indexAt };
});
