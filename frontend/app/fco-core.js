/* 多尺度 LPPLS 置信度（FCO 风格）核心计算
   参考：Sornette, Demos, Zhang, Cauwels, Filimonov & Zhang (2015) 上证 2015 泡沫实时预测；
        Zhang, Zhang & Sornette (2016) PLOS ONE 多尺度置信度；Filimonov & Sornette (2013) 稳定标定。
   置信度 = 某一尺度下，拟合结果通过筛选条件的窗口占比。正泡沫拟合 log P，负泡沫拟合 -log P。
   与原版差异：窗口数更少（每尺度 7 个），差分进化预算更低，没有 Trust（残差重抽样）指标。
   依赖 engine.js 的 OD._fitWindow / OD.rng / OD.lpplsCurve。浏览器与 Node 通用。 */
(function (G) {
  'use strict';
  const FC = {};
  FC.SCALES = [
    { k: 's', name: '短期', note: '30–105 日窗口', wins: [30, 40, 50, 60, 75, 90, 105] },
    { k: 'm', name: '中期', note: '120–250 日窗口', wins: [120, 140, 160, 180, 200, 225, 250] },
    { k: 'l', name: '长期', note: '300–700 日窗口', wins: [300, 350, 400, 450, 500, 600, 700] },
  ];
  FC.ALL = FC.SCALES.flatMap((s) => s.wins);
  FC.FIT = { pop: 10, gens: 12, nm: 24, power: false, aheadLo: 0.5, wLo: 2, wHi: 15 };
  FC.aheadHi = (n) => Math.max(10, Math.round(0.2 * n));
  // 本站筛选：比 DS LPPLS 原文略宽（A 股振荡较少，原文条件下几乎不出信号）
  FC.RULE = 'B<0；0.1≤m≤0.95；2≤ω≤15；tc 距今 ≤ max(10, 0.2×窗口)；振荡数≥1.5；阻尼≥0.3；R²≥0.7';
  FC.DS_RULE = 'B<0；0.01≤m≤0.99；2≤ω≤15；tc 距今 ≤ max(5, 0.1×窗口)；振荡数≥2.5；阻尼≥0.5';
  FC.qual = (f, n) => f.B < 0 && f.m >= 0.1 && f.m <= 0.95 && f.w >= 2 && f.w <= 15 && f.ahead <= FC.aheadHi(n) && f.O >= 1.5 && f.D >= 0.3 && f.R2 >= 0.7;
  FC.qualDS = (f, n) => f.B < 0 && f.m >= 0.01 && f.m <= 0.99 && f.w >= 2 && f.w <= 15 && f.ahead <= Math.max(5, 0.1 * n) && f.O >= 2.5 && f.D >= 0.5;

  FC.fitAt = function (lp, T, n, dir) {
    const s = dir === 'bot' ? -1 : 1;
    const y = new Array(n);
    for (let i = 0; i < n; i++) y[i] = s * lp[T + 1 - n + i];
    const rnd = G.OD.rng(9176 + T * 31 + n * 7 + (s < 0 ? 5 : 0));
    const f = G.OD._fitWindow(y, { ...FC.FIT, aheadHi: FC.aheadHi(n) }, rnd);
    delete f._ws;
    f.dir = dir; f.q = FC.qual(f, n); f.qds = FC.qualDS(f, n);
    return f;
  };
  // 一个截止日的完整扫描（含参数，用于情景曲线）
  FC.scanFull = function (lp, T) {
    const fits = [];
    for (const dir of ['top', 'bot']) for (const n of FC.ALL) if (n <= T + 1) fits.push(FC.fitAt(lp, T, n, dir));
    return fits;
  };
  // 精简记录：[T, [顶 s,m,l 合格数], [底 s,m,l], 顶 DS 合格数, 底 DS 合格数, [顶 tc 距今], [底 tc 距今]]
  FC.pack = function (T, fits) {
    const cnt = { top: [0, 0, 0], bot: [0, 0, 0] }, ds = { top: 0, bot: 0 }, tc = { top: [], bot: [] };
    for (const f of fits) {
      const si = f.n < 120 ? 0 : f.n < 300 ? 1 : 2;
      if (f.q) { cnt[f.dir][si]++; tc[f.dir].push(Math.round(f.ahead)); }
      if (f.qds) ds[f.dir]++;
    }
    return [T, cnt.top, cnt.bot, ds.top, ds.bot, tc.top, tc.bot];
  };
  FC.scanPacked = (lp, T) => FC.pack(T, FC.scanFull(lp, T));
  // 每个尺度在截止日 T 可用的窗口数（分母）
  FC.denom = (T) => FC.SCALES.map((s) => s.wins.filter((n) => n <= T + 1).length);
  // 把精简记录转成置信度
  FC.conf = function (rec) {
    const d = FC.denom(rec[0]);
    const tot = d[0] + d[1] + d[2];
    const top = rec[1].map((c, i) => d[i] ? c / d[i] : 0), bot = rec[2].map((c, i) => d[i] ? c / d[i] : 0);
    return {
      T: rec[0], top, bot,
      // 综合指标（本站合成规则，未校准）：三个尺度置信度的几何加权——多个尺度同时亮才会高
      comboTop: combo(top), comboBot: combo(bot),
      dsTop: rec[3] / tot, dsBot: rec[4] / tot, tcTop: rec[5], tcBot: rec[6],
    };
  };
  function combo(v) {
    const on = v.filter((x) => x > 0).length;
    const mean = (v[0] + v[1] + v[2]) / 3;
    return mean * (on / 3);
  }
  // tc 概率密度（核平滑，单位：交易日距今）
  FC.tcDensity = function (aheads, H) {
    H = H || 140;
    const d = new Float64Array(H + 1);
    if (!aheads.length) return d;
    let s = 0;
    for (let a = 0; a <= H; a++) {
      let v = 0;
      for (const x of aheads) { const z = (a - x) / Math.max(2, 0.15 * Math.max(1, x)); v += Math.exp(-0.5 * z * z); }
      d[a] = v; s += v;
    }
    if (s > 0) for (let a = 0; a <= H; a++) d[a] /= s;
    return d;
  };
  FC.quantiles = function (a, ps) {
    if (!a.length) return ps.map(() => NaN);
    const b = a.slice().sort((x, y) => x - y);
    return ps.map((p) => { const i = (b.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return b[lo] + (b[hi] - b[lo]) * (i - lo); });
  };
  FC.curve = (f) => G.OD.lpplsCurve(f, f.n + Math.max(1, Math.floor(f.ahead)));

  G.FC = FC;
  if (typeof module !== 'undefined' && module.exports) module.exports = FC;
})(typeof window !== 'undefined' ? window : globalThis);
