/* 宽基ETF：每日净流入与累计、分类热力表。只汇总已发布的申赎估算，不重算。红 = 净申购，绿 = 净赎回 */
(function (root) {
  'use strict';
  var num = function (v) { return typeof v === 'number' && isFinite(v); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var UP = '214,48,58', DN = '17,132,90';
  var signed = function (v, digits) { return num(v) ? (v > 0 ? '+' : '') + (Number(v.toFixed(digits)) + 0).toFixed(digits) : '—'; };

  /* 从 from 起累计；缺估算的日子不加，累计线保持上一个值 */
  function cumulative(rows, from) {
    var total = 0;
    return rows.filter(function (r) { return !from || r.d >= from; }).map(function (r) {
      if (num(r.flow)) total += r.flow;
      return { d: r.d, flow: num(r.flow) ? r.flow : null, cum: total };
    });
  }

  function rangeStart(rows, range) {
    if (!rows.length || range === 'all') return null;
    var last = rows[rows.length - 1].d;
    if (range === 'ytd') return last.slice(0, 4) + '-01-01';
    var end = new Date(last + 'T00:00:00Z');
    end.setUTCMonth(end.getUTCMonth() - (range === '3y' ? 36 : 12));
    return end.toISOString().slice(0, 10);
  }

  /* 颜色深浅按本列绝对值最大者归一 */
  function shade(v, max) {
    if (!num(v) || !max || v === 0) return '';
    return 'background:rgba(' + (v > 0 ? UP : DN) + ',' + (0.08 + 0.62 * Math.min(1, Math.abs(v) / max)).toFixed(2) + ')';
  }

  /* total: 合计行；cats: [{name, rows}]，rows 为按日 {d, flow}。列按近 days 日绝对额从大到小排 */
  function heat(total, cats, days) {
    var dates = total.filter(function (r) { return num(r.flow); }).slice(-(days || 21)).map(function (r) { return r.d; }).reverse();
    if (!dates.length) return '<p class="sub">暂无申赎估算。</p>';
    var cols = [{ name: '合计', rows: total }].concat(cats.map(function (c) {
      var m = {}; c.rows.forEach(function (r) { m[r.d] = r.flow; });
      return { name: c.name, map: m, size: dates.reduce(function (s, d) { return s + (num(m[d]) ? Math.abs(m[d]) : 0); }, 0) };
    }).sort(function (a, b) { return b.size - a.size; }));
    var tm = {}; total.forEach(function (r) { tm[r.d] = r.flow; }); cols[0].map = tm;
    cols.forEach(function (c) { c.max = Math.max.apply(null, dates.map(function (d) { return num(c.map[d]) ? Math.abs(c.map[d]) : 0; })); });
    return '<table class="nf-heat"><thead><tr><th>日期</th>' + cols.map(function (c) { return '<th>' + esc(c.name) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      dates.map(function (d) {
        return '<tr><td>' + d + '</td>' + cols.map(function (c, i) {
          var v = c.map[d];
          return '<td style="' + shade(v, c.max) + '">' + signed(v, i ? 2 : 1) + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table>';
  }

  function ticks(min, max, n) {
    var span = max - min || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), f = raw / mag;
    var step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag, out = [];
    for (var v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Number(v.toFixed(6)));
    return out;
  }

  function draw(canvas, rows, hover) {
    var w = canvas.clientWidth, h = canvas.clientHeight, dpr = (typeof devicePixelRatio === 'number' && devicePixelRatio) || 1;
    canvas.width = w * dpr; canvas.height = h * dpr;
    var c = canvas.getContext('2d'); c.scale(dpr, dpr); c.clearRect(0, 0, w, h);
    var L = 46, R = 56, T = 10, B = 22, pw = w - L - R, ph = h - T - B;
    c.font = '10px Inter,system-ui,sans-serif'; c.textBaseline = 'middle';
    if (!rows.length || pw <= 0) { c.fillStyle = '#6a6d78'; c.fillText('暂无申赎估算', L, h / 2); return null; }
    var flows = rows.map(function (r) { return r.flow || 0; }), cums = rows.map(function (r) { return r.cum; });
    var fMax = Math.max.apply(null, flows.concat(0)), fMin = Math.min.apply(null, flows.concat(0));
    var fp = (fMax - fMin) * 0.06 || 1; fMax += fp; fMin -= fp;
    var cMax = Math.max.apply(null, cums.concat(0)), cMin = Math.min.apply(null, cums.concat(0));
    var cp = (cMax - cMin) * 0.06 || 1; cMax += cp; cMin -= cp;
    var bw = pw / rows.length, x = function (i) { return L + (i + 0.5) * bw; };
    var yf = function (v) { return T + ph - (v - fMin) / (fMax - fMin) * ph; }, yc = function (v) { return T + ph - (v - cMin) / (cMax - cMin) * ph; };
    c.strokeStyle = '#eef1f6'; c.lineWidth = 1; c.textAlign = 'right'; c.fillStyle = '#6a6d78';
    ticks(fMin, fMax, 4).forEach(function (t) {
      var y = Math.round(yf(t)) + 0.5; c.beginPath(); c.moveTo(L, y); c.lineTo(L + pw, y); c.stroke(); c.fillText(t.toLocaleString('zh-CN'), L - 6, yf(t));
    });
    c.textAlign = 'left'; c.fillStyle = '#131722';
    ticks(cMin, cMax, 4).forEach(function (t) { c.fillText(t.toLocaleString('zh-CN'), L + pw + 6, yc(t)); });
    var zero = yf(0);
    rows.forEach(function (r, i) {
      if (!num(r.flow) || r.flow === 0) return;
      c.fillStyle = 'rgb(' + (r.flow > 0 ? UP : DN) + ')';
      var y = yf(r.flow);
      c.fillRect(x(i) - Math.max(0.5, bw * 0.38), Math.min(y, zero), Math.max(1, bw * 0.76), Math.max(1, Math.abs(y - zero)));
    });
    c.strokeStyle = '#9aa0ad'; c.beginPath(); c.moveTo(L, Math.round(zero) + 0.5); c.lineTo(L + pw, Math.round(zero) + 0.5); c.stroke();
    c.beginPath(); rows.forEach(function (r, i) { i ? c.lineTo(x(i), yc(r.cum)) : c.moveTo(x(i), yc(r.cum)); });
    c.strokeStyle = '#131722'; c.lineWidth = 1.8; c.stroke();
    c.fillStyle = '#6a6d78'; c.textBaseline = 'alphabetic';
    var n = Math.min(pw < 360 ? 3 : 4, rows.length), seen = {};
    for (var k = 0; k < n; k++) {
      var i = n > 1 ? Math.round(k * (rows.length - 1) / (n - 1)) : 0;
      if (seen[i]) continue; seen[i] = 1;
      c.textAlign = k === 0 ? 'left' : k === n - 1 ? 'right' : 'center';
      c.fillText(rows[i].d, k === 0 ? L : k === n - 1 ? L + pw : x(i), h - 6);
    }
    if (hover != null && rows[hover]) {
      var hx = Math.round(x(hover)) + 0.5;
      c.strokeStyle = '#9aa0ad'; c.lineWidth = 1; c.beginPath(); c.moveTo(hx, T); c.lineTo(hx, T + ph); c.stroke();
      c.fillStyle = '#131722'; c.beginPath(); c.arc(x(hover), yc(rows[hover].cum), 3, 0, 6.3); c.fill();
    }
    return { left: L, width: pw };
  }

  function indexAt(geom, n, px) {
    if (!geom || !n) return null;
    return Math.max(0, Math.min(n - 1, Math.floor((px - geom.left) / geom.width * n)));
  }

  function readout(r) {
    return r ? r.d + '　当日 ' + signed(r.flow, 1) + ' 亿元　区间累计 ' + signed(r.cum, 1) + ' 亿元' : '';
  }

  var api = { cumulative: cumulative, rangeStart: rangeStart, shade: shade, heat: heat, draw: draw, indexAt: indexAt, readout: readout, signed: signed };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.NtFlow = api;
})(typeof self !== 'undefined' ? self : this);
