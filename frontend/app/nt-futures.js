/* 宽基ETF 页“期指席位与基差”：只读已发布的 nt_etf.futures，列当日读数和登记检验的历史次数，不产生结论。 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.NtFutures = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var PRODUCTS = ['IF', 'IH', 'IC', 'IM'];
  var COLORS = { IF: '#2962FF', IH: '#F7931A', IC: '#8E24AA', IM: '#00897B' };
  var MIN_EVENTS = 15;
  var num = function (v) { return typeof v === 'number' && isFinite(v); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var signed = function (v, digits, unit) {
    if (!num(v)) return '—';
    v = Number(v.toFixed(digits)) + 0;
    return (v > 0 ? '+' : '') + v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) + (unit || '');
  };
  var pct = function (fraction, digits) { return num(fraction) ? signed(fraction * 100, digits == null ? 1 : digits, '%') : '—'; };
  var share = function (fraction) { return num(fraction) ? Math.round(fraction * 100) + '%' : '—'; };
  var tone = function (v) { return num(v) ? (v > 0 ? 'up' : v < 0 ? 'dn' : '') : ''; };

  /* 登记的判定：事件数不足 15 只能写“样本不足”，其余未通过的写“没有可分辨的差别” */
  function verdict(event) {
    if (!event || !event.n) return '从未出现';
    if (event.n < MIN_EVENTS) return '样本不足';
    return event.passed ? '通过登记检验' : '之后走势与任选一天没有可分辨的差别';
  }

  function eventLine(event, baseline) {
    if (!event.n) return event.label + '：历史上从未出现。';
    return event.label + '：历史上出现 ' + event.n + ' 次，之后 20 日沪深300 中位 ' + pct(event.median_20) + '、上涨 ' + share(event.up_20) +
      '（任选一天 ' + pct(baseline.median_20) + '、' + share(baseline.up_20) + '）；' + verdict(event) + '。';
  }

  /* 近 n 日序列：中信 IF+IH 多单日变化、前 20 净空、四个品种基差 */
  function series(rows, n) {
    var out = [];
    for (var i = 1; i < rows.length; i++) {
      var a = rows[i - 1], b = rows[i], seat = b.IF.cl + b.IH.cl - a.IF.cl - a.IH.cl, net = 0, basis = {};
      PRODUCTS.forEach(function (p) { net += b[p].ts - b[p].tl; basis[p] = b[p].basis; });
      out.push({ d: b.date, seat: seat, net: net, basis: basis });
    }
    return out.slice(-(n || 60));
  }

  function cards(today) {
    var b = today.basis || {}, p = today.basis_previous || {};
    return [
      { label: '中信期货 IF+IH 多单', value: signed(today.seat_long_chg, 0, ' 手'), tone: tone(today.seat_long_chg), detail: '较前一交易日' },
      { label: '前 20 会员净空（四品种合计）', value: num(today.net_short) ? today.net_short.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) + ' 手' : '—', tone: '', detail: '较前一交易日 ' + signed(today.net_short_chg, 0, ' 手') },
      { label: 'IC 主力合约基差', value: signed(b.IC, 2, '%'), tone: tone(b.IC), detail: '前一交易日 ' + signed(p.IC, 2, '%') },
      { label: '沪深300', value: signed(today.index_pct, 2, '%'), tone: tone(today.index_pct), detail: '当日涨跌' }
    ];
  }

  function html(f) {
    var today = f && f.today, ev = f && f.evidence;
    if (!today || !ev) return '<p class="sub">期指席位与基差数据暂未发布。</p>';
    var byKey = {};
    ev.events.forEach(function (e) { byKey[e.key] = e; });
    var hits = (today.events || []).map(function (k) { return byKey[k]; }).filter(Boolean);
    var span = String(ev.first).slice(0, 7) + ' 至 ' + String(ev.last).slice(0, 7);
    return '<div class="kpis ntf-kpis">' + cards(today).map(function (c) {
      return '<div class="kpi"><small>' + esc(c.label) + '</small><strong class="' + c.tone + '">' + esc(c.value) + '</strong><small>' + esc(c.detail) + '</small></div>';
    }).join('') + '</div>' +
      '<p class="sub">各品种主力合约基差：' + PRODUCTS.map(function (p) { return p + ' ' + signed(today.basis[p], 2, '%'); }).join('　') + '</p>' +
      '<h3>' + esc(today.date) + ' 出现的情况</h3>' +
      (hits.length ? '<ul class="ntf-hits">' + hits.map(function (e) { return '<li>' + esc(eventLine(e, ev.baseline)) + '</li>'; }).join('') + '</ul>'
        : '<p class="sub">当日没有出现登记的 6 种情况。</p>') +
      '<details class="ntf-all"><summary>6 种情况的历史统计（' + esc(span) + '）</summary><div class="scroll"><table><thead><tr><th>情况</th><th>次数（20 日内只计一次）</th><th>之后 20 日中位</th><th>上涨比例</th><th>判定</th></tr></thead><tbody>' +
      '<tr><td>任选一天（基准）</td><td>' + ev.baseline.n + '</td><td>' + pct(ev.baseline.median_20) + '</td><td>' + share(ev.baseline.up_20) + '</td><td>—</td></tr>' +
      ev.events.map(function (e) {
        return '<tr><td>' + esc(e.label) + '</td><td>' + e.n + '</td><td>' + pct(e.median_20) + '</td><td>' + share(e.up_20) + '</td><td>' + esc(verdict(e)) + '</td></tr>';
      }).join('') + '</tbody></table></div></details>' +
      '<p class="disclaimer">' + esc(ev.note) + ' 中信期货席位是全部客户合计，不代表国家队。</p>';
  }

  /* 上栏：中信 IF+IH 多单日变化柱；下栏：四个品种基差线 */
  function draw(canvas, rows) {
    var w = canvas.clientWidth, h = canvas.clientHeight, dpr = (typeof devicePixelRatio === 'number' && devicePixelRatio) || 1;
    if (!w || !h || !rows.length) return;
    canvas.width = w * dpr; canvas.height = h * dpr;
    var c = canvas.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
    var left = 8, right = 56, top = 18, bottom = 20, mid = Math.round(h * .46), gap = 26;
    var pw = w - left - right, n = rows.length, x = function (i) { return left + (i + .5) / n * pw; };
    var bw = Math.max(1, pw / n * .6);
    c.font = '11px sans-serif'; c.lineWidth = 1;
    var seatMax = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.seat); }).concat([5000])) * 1.1;
    var ys = function (v) { return top + (seatMax - v) / (2 * seatMax) * (mid - top); };
    c.fillStyle = '#6a6d78'; c.fillText('中信 IF+IH 多单日变化（手）', left, 12);
    [5000, 0, -5000].forEach(function (g) {
      c.strokeStyle = g ? '#d5d9e2' : '#aab3c2'; c.setLineDash(g ? [4, 4] : []);
      c.beginPath(); c.moveTo(left, ys(g)); c.lineTo(w - right, ys(g)); c.stroke(); c.setLineDash([]);
      c.fillStyle = '#6a6d78'; c.fillText(g ? (g > 0 ? '+' : '') + g : '0', w - right + 6, ys(g) + 4);
    });
    rows.forEach(function (r, i) {
      c.fillStyle = r.seat >= 0 ? '#d6303a' : '#11845a';
      c.fillRect(x(i) - bw / 2, Math.min(ys(0), ys(r.seat)), bw, Math.max(1, Math.abs(ys(r.seat) - ys(0))));
    });
    var bTop = mid + gap, bBottom = h - bottom, lo = 0, hi = 0;
    rows.forEach(function (r) { PRODUCTS.forEach(function (p) { if (num(r.basis[p])) { lo = Math.min(lo, r.basis[p]); hi = Math.max(hi, r.basis[p]); } }); });
    var pad = Math.max((hi - lo) * .1, .1); lo -= pad; hi += pad;
    var yb = function (v) { return bTop + (hi - v) / (hi - lo) * (bBottom - bTop); };
    var lx = left;
    c.fillStyle = '#6a6d78'; c.fillText('主力合约基差（%）', lx, bTop - 8); lx += c.measureText('主力合约基差（%）').width + 10;
    PRODUCTS.forEach(function (p) { c.fillStyle = COLORS[p]; c.fillText(p, lx, bTop - 8); lx += c.measureText(p).width + 8; });
    c.strokeStyle = '#aab3c2'; c.beginPath(); c.moveTo(left, yb(0)); c.lineTo(w - right, yb(0)); c.stroke();
    c.fillStyle = '#6a6d78'; c.fillText('0', w - right + 6, yb(0) + 4);
    c.fillText(hi.toFixed(1), w - right + 6, bTop + 8); c.fillText(lo.toFixed(1), w - right + 6, bBottom);
    PRODUCTS.forEach(function (p) {
      c.strokeStyle = COLORS[p]; c.lineWidth = 1.3; c.beginPath();
      var started = false;
      rows.forEach(function (r, i) {
        if (!num(r.basis[p])) { started = false; return; }
        if (started) c.lineTo(x(i), yb(r.basis[p])); else { c.moveTo(x(i), yb(r.basis[p])); started = true; }
      });
      c.stroke();
    });
    c.fillStyle = '#6a6d78'; c.textAlign = 'left'; c.fillText(rows[0].d, left, h - 5);
    c.textAlign = 'right'; c.fillText(rows[n - 1].d, w - right, h - 5); c.textAlign = 'left';
  }

  return { verdict: verdict, eventLine: eventLine, series: series, cards: cards, html: html, draw: draw };
});
