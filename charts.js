/* 临界点实验室 · SVG 图表（主题由页面 CSS 通过 class 控制） */
(function (global) {
  'use strict';
  const C = {};
  const f2 = (v) => (Math.round(v * 100) / 100).toString();
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  C.esc = esc;

  function scale(d0, d1, r0, r1) { const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0); return (v) => r0 + (v - d0) * k; }
  function niceTicks(lo, hi, n) {
    const span = hi - lo || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const st = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || mag * 10;
    const out = [];
    for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) out.push(+v.toFixed(10));
    return out;
  }
  function path(xs, ys) {
    let d = '', pen = false;
    for (let i = 0; i < xs.length; i++) {
      if (!isFinite(ys[i]) || !isFinite(xs[i])) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + f2(xs[i]) + ' ' + f2(ys[i]);
      pen = true;
    }
    return d;
  }
  function fmtP(v) { return v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2); }

  /* 主图：对数坐标价格 + LPPLS 拟合 + t_c 分布带 */
  C.priceChart = function (o) {
    const W = o.w || 960, H = o.h || 380, pl = 8, pr = 56, pt = 16, pb = 26;
    const bars = o.bars, N = bars.length, show = Math.min(o.show || 500, N), s0 = N - show;
    const future = o.future || 60;
    const tot = show + future;
    const X = scale(0, tot - 1, pl, W - pr);
    let lo = Infinity, hi = -Infinity;
    for (let i = s0; i < N; i++) { lo = Math.min(lo, bars[i].low); hi = Math.max(hi, bars[i].high); }
    const curves = (o.curves || []).map((c) => {
      const xs = [], ys = [];
      c.points.forEach((p) => { if (p.i >= s0) { xs.push(X(p.i - s0)); ys.push(p.v); lo = Math.min(lo, Math.exp(p.v)); hi = Math.max(hi, Math.exp(p.v)); } });
      return { ...c, xs, ys };
    });
    const pad = (Math.log(hi) - Math.log(lo)) * 0.06;
    const Y = scale(Math.log(lo) - pad, Math.log(hi) + pad, H - pb, pt);
    let s = `<svg class="ch ch-price" viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="none" role="img" aria-label="${esc(o.label || '价格与 LPPLS 拟合')}">`;
    // 网格
    const tv = niceTicks(lo, hi, 5);
    tv.forEach((v) => { if (v <= 0) return; const y = Y(Math.log(v)); if (y < pt || y > H - pb) return; s += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${f2(y)}" y2="${f2(y)}"/><text class="ax" x="${W - pr + 6}" y="${f2(y + 4)}">${fmtP(v)}</text>`; });
    const yr = {};
    for (let i = s0; i < N; i++) { const yy = bars[i].date.slice(0, 7); if (!yr[yy] && /-(01|04|07|10)$/.test(yy)) yr[yy] = i; }
    Object.entries(yr).forEach(([k, i]) => { const x = X(i - s0); s += `<line class="grid v" x1="${f2(x)}" x2="${f2(x)}" y1="${pt}" y2="${H - pb}"/><text class="ax" x="${f2(x + 3)}" y="${H - 8}">${k}</text>`; });
    // 未来区
    const xn = X(show - 1);
    s += `<rect class="future" x="${f2(xn)}" y="${pt}" width="${f2(W - pr - xn)}" height="${H - pt - pb}"/>`;
    // t_c 区间带
    (o.bands || []).forEach((b) => {
      if (!isFinite(b.q05)) return;
      const a = X(show - 1 + Math.max(0, b.q05)), c = X(show - 1 + Math.min(future, b.q95));
      if (c > a) s += `<rect class="band ${b.cls}" x="${f2(a)}" y="${pt}" width="${f2(c - a)}" height="${H - pt - pb}"/>`;
      if (isFinite(b.q50) && b.q50 <= future) { const m = X(show - 1 + b.q50); s += `<line class="band-mid ${b.cls}" x1="${f2(m)}" x2="${f2(m)}" y1="${pt}" y2="${H - pb}"/>`; }
    });
    (o.ticks || []).forEach((t) => { if (t.v <= future && t.v >= 0) { const x = X(show - 1 + t.v); s += `<line class="tick ${t.cls}" x1="${f2(x)}" x2="${f2(x)}" y1="${H - pb - 10}" y2="${H - pb}"/>`; } });
    // 价格：K 线或收盘线
    if (o.candles && show <= 260) {
      const bw = Math.max(1, ((W - pl - pr) / tot) * 0.62);
      for (let i = s0; i < N; i++) {
        const b = bars[i], x = X(i - s0), up = b.close >= b.open;
        s += `<line class="wick ${up ? 'up' : 'dn'}" x1="${f2(x)}" x2="${f2(x)}" y1="${f2(Y(Math.log(b.high)))}" y2="${f2(Y(Math.log(b.low)))}"/>`;
        const y1 = Y(Math.log(Math.max(b.open, b.close))), y2 = Y(Math.log(Math.min(b.open, b.close)));
        s += `<rect class="body ${up ? 'up' : 'dn'}" x="${f2(x - bw / 2)}" y="${f2(y1)}" width="${f2(bw)}" height="${f2(Math.max(0.8, y2 - y1))}"/>`;
      }
    } else {
      const xs = [], ys = [];
      for (let i = s0; i < N; i++) { xs.push(X(i - s0)); ys.push(Y(Math.log(bars[i].close))); }
      s += `<path class="price" d="${path(xs, ys)}"/>`;
    }
    curves.forEach((c) => { s += `<path class="fit ${c.cls}" d="${path(c.xs, c.ys.map(Y))}"/>`; });
    (o.marks || []).forEach((m) => { if (m.i < s0) return; const x = X(m.i - s0), y = Y(Math.log(bars[m.i].close)); s += m.type === 'buy' ? `<path class="mk buy" d="M${f2(x)} ${f2(y + 6)}l-5 8h10z"/>` : `<path class="mk sell" d="M${f2(x)} ${f2(y - 6)}l-5 -8h10z"/>`; });
    const last = bars[N - 1];
    const yl = Y(Math.log(last.close));
    s += `<line class="now" x1="${pl}" x2="${W - pr}" y1="${f2(yl)}" y2="${f2(yl)}"/><rect class="now-tag" x="${W - pr + 1}" y="${f2(yl - 9)}" width="${pr - 2}" height="18" rx="2"/><text class="now-txt" x="${W - pr + 6}" y="${f2(yl + 4)}">${fmtP(last.close)}</text>`;
    s += `<text class="ax future-lbl" x="${f2(xn + 6)}" y="${pt + 12}">未来 ${future} 交易日</text>`;
    return s + '</svg>';
  };

  /* 自由能地形（横向：价格为纵轴） */
  C.energyChart = function (o) {
    const W = o.w || 320, H = o.h || 380, pl = 52, pr = 12, pt = 16, pb = 26;
    const g = o.ppe.grid, F = o.ppe.F, G = g.length;
    let Fmax = 0;
    for (let i = 0; i < G; i++) Fmax = Math.max(Fmax, F[i]);
    Fmax = Math.min(Fmax, 8);
    const Y = scale(g[0], g[G - 1], H - pb, pt), X = scale(0, Fmax, pl, W - pr);
    let s = `<svg class="ch ch-energy" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="经验自由能地形">`;
    niceTicks(Math.exp(g[0]), Math.exp(g[G - 1]), 6).forEach((v) => { if (v <= 0) return; const y = Y(Math.log(v)); if (y < pt || y > H - pb) return; s += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${f2(y)}" y2="${f2(y)}"/><text class="ax" x="${pl - 6}" y="${f2(y + 4)}" text-anchor="end">${fmtP(v)}</text>`; });
    const xs = [], ys = [];
    for (let i = 0; i < G; i++) { xs.push(X(Math.min(F[i], Fmax))); ys.push(Y(g[i])); }
    s += `<path class="area" d="M${pl} ${f2(ys[0])}${path(xs, ys).replace(/^M/, 'L')}L${pl} ${f2(ys[G - 1])}Z"/>`;
    s += `<path class="fe" d="${path(xs, ys)}"/>`;
    o.ppe.wells.forEach((w, k) => {
      const y = Y(w.x);
      s += `<line class="well" x1="${pl}" x2="${W - pr}" y1="${f2(y)}" y2="${f2(y)}"/><circle class="well-dot" cx="${f2(X(w.F))}" cy="${f2(y)}" r="4"/><text class="well-lbl" x="${W - pr - 4}" y="${f2(y - 5)}" text-anchor="end">井${k + 1} ${fmtP(w.price)} · ${Math.round(w.mass * 100)}%</text>`;
    });
    const yn = Y(o.ppe.xNow);
    s += `<line class="now" x1="${pl}" x2="${W - pr}" y1="${f2(yn)}" y2="${f2(yn)}"/><text class="now-txt2" x="${pl + 4}" y="${f2(yn - 5)}">现价</text>`;
    s += `<text class="ax" x="${pl}" y="${H - 8}">低 F = 历史停留密集</text><text class="ax" x="${W - pr}" y="${H - 8}" text-anchor="end">F = −ln ρ</text>`;
    return s + '</svg>';
  };

  /* 首达累计概率曲线 */
  C.passageChart = function (o) {
    const W = o.w || 420, H = o.h || 200, pl = 36, pr = 12, pt = 12, pb = 24, p = o.passage, Hh = p.H;
    const X = scale(0, Hh, pl, W - pr), Y = scale(0, 1, H - pb, pt);
    let s = `<svg class="ch ch-pass" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="首达累计概率">`;
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => { const y = Y(v); s += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${f2(y)}" y2="${f2(y)}"/><text class="ax" x="${pl - 6}" y="${f2(y + 4)}" text-anchor="end">${Math.round(v * 100)}%</text>`; });
    [0, 5, 10, 15, 20, 30, 40, 60].filter((v) => v <= Hh).forEach((v) => s += `<text class="ax" x="${f2(X(v))}" y="${H - 6}" text-anchor="middle">${v}</text>`);
    const cum = (h) => { const a = [0]; for (let j = 1; j <= Hh; j++) a.push(a[j - 1] + h[j]); return a; };
    const xs = [];
    for (let j = 0; j <= Hh; j++) xs.push(X(j));
    const cu = cum(p.block.histU), cd = cum(p.block.histL), iu = cum(p.iid.histU), id = cum(p.iid.histL);
    s += `<path class="pu base" d="${path(xs, iu.map(Y))}"/><path class="pd base" d="${path(xs, id.map(Y))}"/>`;
    s += `<path class="pu" d="${path(xs, cu.map(Y))}"/><path class="pd" d="${path(xs, cd.map(Y))}"/>`;
    s += `<path class="pn" d="${path(xs, p.block.surv.map(Y))}"/>`;
    return s + '</svg>';
  };

  /* 时间序列（多线，0–1 或自定义域） */
  C.seriesChart = function (o) {
    const W = o.w || 960, H = o.h || 160, pl = 8, pr = 56, pt = 10, pb = 22;
    const n = o.dates.length;
    const X = scale(0, n - 1, pl, W - pr);
    let lo = o.lo, hi = o.hi;
    if (lo === undefined) { lo = Infinity; hi = -Infinity; o.lines.forEach((l) => l.v.forEach((v) => { if (isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } })); const pd = (hi - lo) * 0.08 || 0.1; lo -= pd; hi += pd; }
    const Y = scale(lo, hi, H - pb, pt);
    let s = `<svg class="ch ch-series" viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="none" role="img" aria-label="${esc(o.label || '时间序列')}">`;
    niceTicks(lo, hi, 3).forEach((v) => { const y = Y(v); if (y < pt - 1 || y > H - pb + 1) return; s += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${f2(y)}" y2="${f2(y)}"/><text class="ax" x="${W - pr + 6}" y="${f2(y + 4)}">${o.pct ? Math.round(v * 100) + '%' : (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2))}</text>`; });
    (o.refs || []).forEach((r) => { const y = Y(r.v); s += `<line class="ref" x1="${pl}" x2="${W - pr}" y1="${f2(y)}" y2="${f2(y)}"/>`; });
    let lastY = '';
    for (let i = 0; i < n; i += Math.max(1, Math.floor(n / 6))) { const yy = o.dates[i].slice(0, 7); if (yy !== lastY) { s += `<text class="ax" x="${f2(X(i))}" y="${H - 6}">${yy}</text>`; lastY = yy; } }
    o.lines.forEach((l) => {
      const xs = l.v.map((_, i) => X(i)), ys = l.v.map((v) => (isFinite(v) ? Y(v) : NaN));
      if (l.fill) s += `<path class="${l.cls} fill" d="M${f2(xs[0])} ${f2(Y(lo))}${path(xs, ys).replace(/^M/, 'L')}L${f2(xs[xs.length - 1])} ${f2(Y(lo))}Z"/>`;
      s += `<path class="${l.cls}" d="${path(xs, ys)}"/>`;
    });
    (o.marks || []).forEach((m) => { const x = X(m.i); s += `<line class="mk-line ${m.type}" x1="${f2(x)}" x2="${f2(x)}" y1="${pt}" y2="${H - pb}"/>`; });
    return s + '</svg>';
  };

  /* t_c 分布直方图（窗口点 + bootstrap） */
  C.tcHist = function (o) {
    const W = o.w || 420, H = o.h || 150, pl = 8, pr = 8, pt = 10, pb = 22, maxD = o.max || 120;
    const X = scale(0, maxD, pl, W - pr);
    const bins = 24, bw = maxD / bins;
    const hist = (arr) => { const h = new Array(bins).fill(0); arr.forEach((v) => { if (v >= 0 && v < maxD) h[Math.floor(v / bw)]++; }); return h; };
    const sets = o.sets.map((st) => ({ ...st, h: hist(st.v) }));
    const mx = Math.max(1, ...sets.map((st) => Math.max(...st.h)));
    const Y = scale(0, mx, H - pb, pt);
    let s = `<svg class="ch ch-hist" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(o.label || 't_c 分布')}">`;
    s += `<line class="grid" x1="${pl}" x2="${W - pr}" y1="${H - pb}" y2="${H - pb}"/>`;
    [0, 20, 40, 60, 90, 120].filter((v) => v <= maxD).forEach((v) => s += `<text class="ax" x="${f2(X(v))}" y="${H - 6}" text-anchor="middle">${v}</text>`);
    sets.forEach((st, k) => {
      st.h.forEach((c, i) => {
        if (!c) return;
        const w = (X(bw) - X(0)) / sets.length - 1;
        const x = X(i * bw) + k * (w + 1);
        s += `<rect class="hb ${st.cls}" x="${f2(x)}" y="${f2(Y(c))}" width="${f2(Math.max(1, w))}" height="${f2(H - pb - Y(c))}"/>`;
      });
    });
    return s + '</svg>';
  };

  /* 环形图（mobile 多空） */
  C.donut = function (o) {
    const R = 60, r = 42, cx = 70, cy = 70;
    let a0 = -Math.PI / 2, s = `<svg class="ch ch-donut" viewBox="0 0 140 140" width="140" height="140" role="img" aria-label="${esc(o.label || '')}">`;
    const tot = o.parts.reduce((a, p) => a + p.v, 0) || 1;
    o.parts.forEach((p) => {
      const a1 = a0 + (2 * Math.PI * p.v) / tot - 0.02;
      if (p.v <= 0) return;
      const lg = a1 - a0 > Math.PI ? 1 : 0;
      const P = (rad, a) => `${f2(cx + rad * Math.cos(a))} ${f2(cy + rad * Math.sin(a))}`;
      s += `<path class="seg ${p.cls}" d="M${P(R, a0)}A${R} ${R} 0 ${lg} 1 ${P(R, a1)}L${P(r, a1)}A${r} ${r} 0 ${lg} 0 ${P(r, a0)}Z"/>`;
      a0 = a1 + 0.02;
    });
    return s + '</svg>';
  };

  global.OC = C;
})(window);
