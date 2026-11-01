/* =====================================================================
   临界点实验室 · 共用计算引擎（浏览器端研究原型）
   ---------------------------------------------------------------------
   - 数据：东方财富公开日线（前复权），失败时回退到明确标注的合成演示数据
   - 时间层：LPPLS（Filimonov–Sornette 线性消元 + DE + Nelder–Mead 精修）
             多窗口 DS Confidence、Lagrange 正则选窗、残差块 bootstrap t_c
             纯幂律嵌套对照（F 检验：对数周期是否有独立增量）
   - 统计物理：DFA Hurst、排列熵、临界慢化（AR1 / 方差 + Kendall τ）
   - 价格层：Range-Aware KDE → 经验自由能 F=-ln ρ → 价格井 / 势垒 / 多带宽持续度
   - 首达：平稳块 bootstrap 竞争风险（上 / 下 / 未触达 / 同 bar 歧义）+ iid 基线
   - 回测：滚动 as-of、top10_20_60 事件标签、BASE / LPPLS / LPPLS+物理 Brier
           A 股规则交易回测（T+1、涨跌停不可成交、佣金、印花税、滑点）
   所有概率均为研究输出，未经独立样本外校准。
   ===================================================================== */
(function (global) {
  'use strict';

  const OD = {};
  const yieldUI = () => new Promise((r) => setTimeout(r, 0));

  /* ---------------- 随机数（固定种子，可复现） ---------------- */
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function gauss(r) {
    let u = 0;
    while (u === 0) u = r();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
  }
  OD.rng = mulberry32;

  /* ---------------- 代码解析 ---------------- */
  OD.parseCode = function (input) {
    const s = String(input || '').trim().toUpperCase().replace(/\s+/g, '');
    const m = s.match(/^(SH|SZ|BJ)?(\d{6})(?:\.(SH|SZ|BJ|SS))?$/);
    if (!m) return null;
    const code = m[2];
    let mk = m[1] || m[3] || '';
    if (mk === 'SS') mk = 'SH';
    if (!mk) {
      if (/^(8|4|92)/.test(code)) mk = 'BJ';
      else if (/^(6|9|5)/.test(code)) mk = 'SH';
      else mk = 'SZ';
    }
    let limit = 0.1;
    if (/^(688|689|300|301)/.test(code)) limit = 0.2;
    if (mk === 'BJ') limit = 0.3;
    return { code, market: mk, secid: (mk === 'SH' ? '1.' : '0.') + code, limit, label: code + '.' + mk };
  };

  /* ---------------- 数据获取 ---------------- */
  function jsonp(url, timeout) {
    return new Promise((resolve, reject) => {
      const cb = 'odcb_' + Math.random().toString(36).slice(2);
      const s = document.createElement('script');
      const timer = setTimeout(() => { cleanup(); reject(new Error('请求超时')); }, timeout);
      function cleanup() { clearTimeout(timer); try { delete global[cb]; } catch (e) { global[cb] = undefined; } s.remove(); }
      global[cb] = (d) => { cleanup(); resolve(d); };
      s.onerror = () => { cleanup(); reject(new Error('网络被拦截')); };
      s.src = url + '&cb=' + cb;
      document.head.appendChild(s);
    });
  }

  OD.fetchDaily = async function (info) {
    const url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=' + info.secid +
      '&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg=0&end=20500101&lmt=100000' +
      '&ut=fa5fd1943c7b386f172d6893dbfba10b';
    let d = null;
    try { d = await jsonp(url, 9000); }
    catch (e) {
      try { const r = await fetch(url); d = await r.json(); }
      catch (e2) { throw new Error('行情接口不可达（' + e.message + '）'); }
    }
    if (!d || !d.data || !d.data.klines || !d.data.klines.length) throw new Error('接口未返回该代码的日线数据');
    let bars = d.data.klines.map((k) => {
      const a = k.split(',');
      return { date: a[0], open: +a[1], close: +a[2], high: +a[3], low: +a[4], volume: +a[5], amount: +a[6] };
    });
    // 前复权长序列可能出现非正价格：只保留最后一个非正价格之后的连续段，并记入质量状态
    let cut = -1;
    bars.forEach((b, i) => { if (!(b.close > 0 && b.high > 0 && b.low > 0 && b.open > 0)) cut = i; });
    const truncated = cut >= 0 ? cut + 1 : 0;
    if (cut >= 0) bars = bars.slice(cut + 1);
    return { name: d.data.name || info.label, bars, source: '东方财富 · 前复权日线', synthetic: false, truncated };
  };

  /* ---------------- 合成演示数据（含两段已知 LPPLS 结构） ---------------- */
  OD.syntheticDaily = function (info) {
    const seed = (parseInt(info.code, 10) || 12345) ^ 0x5bd1e995;
    const r = mulberry32(seed);
    const N = 1600;
    const dates = [];
    let d = new Date(Date.UTC(2026, 9, 23));
    while (dates.length < N) {
      const wd = d.getUTCDay();
      if (wd !== 0 && wd !== 6) dates.push(d.toISOString().slice(0, 10));
      d = new Date(d.getTime() - 86400000);
    }
    dates.reverse();
    const lp = (tc, i, B, m, w, C) => { const dt = tc - i; return B * Math.pow(dt, m) * (1 + C * Math.cos(w * Math.log(dt))); };
    const ab = (t0, i, B, m, w, C) => { const dt = i - t0; return B * Math.pow(dt, m) * (1 + C * Math.cos(w * Math.log(dt))); };
    const seg = [
      { a: 0, b: 500, f: (i) => 0.00025 * i },
      { a: 500, b: 820, f: (i) => lp(832, i, -0.055, 0.5, 8.2, 0.09) },
      { a: 820, b: 885, f: (i) => -0.55 * (1 - Math.exp(-(i - 820) / 14)) },
      { a: 885, b: 1250, f: (i) => ab(872, i, -0.026, 0.5, 7.5, 0.1) },
      { a: 1250, b: 1340, f: (i) => 0.0001 * (i - 1250) },
      { a: 1340, b: N, f: (i) => lp(N + 16, i, -0.06, 0.55, 8.8, 0.08) },
    ];
    const T = new Float64Array(N);
    let off = Math.log(12 + r() * 25), prevEnd = null;
    for (const s of seg) {
      const startVal = s.f(s.a);
      const shift = prevEnd === null ? off : prevEnd - startVal;
      for (let i = s.a; i < s.b; i++) T[i] = s.f(i) + shift;
      prevEnd = s.f(s.b - 1) + shift + (s.f(s.b - 1) - s.f(Math.max(s.a, s.b - 2)));
    }
    let ou = 0, h = 0.00025;
    const bars = [];
    let prevClose = Math.exp(T[0]);
    for (let i = 0; i < N; i++) {
      const g = gauss(r);
      h = 0.00003 + 0.75 * h * (0.5 + r());
      h = Math.min(Math.max(h, 0.00005), 0.0009);
      ou = 0.93 * ou + Math.sqrt(h) * g;
      const close = Math.exp(T[i] + ou);
      const open = prevClose * Math.exp(0.25 * Math.log(close / prevClose) + 0.004 * gauss(r));
      const hi = Math.max(open, close) * Math.exp(Math.abs(gauss(r)) * 0.008);
      const lo = Math.min(open, close) * Math.exp(-Math.abs(gauss(r)) * 0.008);
      const ret = Math.abs(Math.log(close / prevClose));
      const vol = Math.round(80000 * (1 + ret / 0.012) * Math.exp(0.3 * gauss(r)) * (1 + 0.6 * Math.max(0, T[i] - T[0])));
      bars.push({ date: dates[i], open: +open.toFixed(3), close: +close.toFixed(3), high: +hi.toFixed(3), low: +lo.toFixed(3), volume: vol, amount: vol * close });
      prevClose = close;
    }
    return { name: '合成演示数据', bars, source: '合成演示数据（非真实行情）', synthetic: true, truncated: 0 };
  };

  /* ---------------- L0 数据质量 ---------------- */
  OD.qualityCheck = function (bars, data) {
    const issues = [];
    let level = 'OK';
    if (bars.length < 260) { issues.push('有效日线不足 260 根（' + bars.length + '），LPPLS 与回测不可用'); level = 'BAN'; }
    let gaps = 0, maxGap = 0, zeroVol = 0;
    for (let i = 1; i < bars.length; i++) {
      const g = (Date.parse(bars[i].date) - Date.parse(bars[i - 1].date)) / 86400000;
      if (g > 15) { gaps++; maxGap = Math.max(maxGap, g); }
      if (!(bars[i].volume > 0)) zeroVol++;
    }
    if (gaps) { issues.push('存在 ' + gaps + ' 处超过 15 个自然日的断档（疑似停牌），最长 ' + Math.round(maxGap) + ' 天'); if (level === 'OK') level = 'WARN'; }
    if (zeroVol) { issues.push(zeroVol + ' 个交易日成交量为 0'); if (level === 'OK') level = 'WARN'; }
    if (data && data.truncated) { issues.push('前复权序列早期出现非正价格，已截去前 ' + data.truncated + ' 根'); if (level === 'OK') level = 'WARN'; }
    if (data && data.synthetic) { issues.push('当前为合成演示数据，任何结论都不适用于真实证券'); if (level === 'OK') level = 'WARN'; }
    issues.push('价格口径：前复权收盘；未做 Point-in-Time 复权因子回放（研究原型限制）');
    return { level, issues, n: bars.length };
  };

  /* =====================================================================
     LPPLS 核心
     ===================================================================== */
  function makeWS(y) {
    const n = y.length;
    const ws = {
      n, y: Float64Array.from(y), t: new Float64Array(n),
      Q: [new Float64Array(n), new Float64Array(n), new Float64Array(n), new Float64Array(n)],
      r: new Float64Array(n), R: new Float64Array(16), z: new Float64Array(4), sst: 0,
    };
    let mu = 0;
    for (let i = 0; i < n; i++) { ws.t[i] = i; mu += y[i]; }
    mu /= n;
    for (let i = 0; i < n; i++) ws.sst += (y[i] - mu) * (y[i] - mu);
    return ws;
  }

  // 条件线性消元：给定 (tc, m, ω) 用改进 Gram–Schmidt QR 求最小二乘，返回 SSE（k=4 LPPLS，k=2 纯幂律）
  function linFit(ws, tc, m, w, k) {
    const n = ws.n, t = ws.t, Q = ws.Q, res = ws.r, R = ws.R, z = ws.z, y = ws.y;
    const q0 = Q[0], q1 = Q[1], q2 = Q[2], q3 = Q[3];
    for (let i = 0; i < n; i++) {
      const dt = tc - t[i];
      if (!(dt > 0)) return Infinity;
      const L = Math.log(dt);
      const f = Math.exp(m * L);
      q0[i] = 1; q1[i] = f;
      if (k === 4) { const ph = w * L; q2[i] = f * Math.cos(ph); q3[i] = f * Math.sin(ph); }
      res[i] = y[i];
    }
    for (let c = 0; c < k; c++) {
      const qc = Q[c];
      let n0 = 0;
      for (let i = 0; i < n; i++) n0 += qc[i] * qc[i];
      n0 = Math.sqrt(n0);
      if (!(n0 > 0)) return Infinity;
      for (let j = 0; j < c; j++) {
        const qj = Q[j];
        let d = 0;
        for (let i = 0; i < n; i++) d += qj[i] * qc[i];
        R[j * 4 + c] = d;
        for (let i = 0; i < n; i++) qc[i] -= d * qj[i];
      }
      let nr = 0;
      for (let i = 0; i < n; i++) nr += qc[i] * qc[i];
      nr = Math.sqrt(nr);
      if (!(nr > 1e-9 * n0)) return Infinity;
      R[c * 4 + c] = nr;
      const inv = 1 / nr;
      for (let i = 0; i < n; i++) qc[i] *= inv;
      let d = 0;
      for (let i = 0; i < n; i++) d += qc[i] * res[i];
      z[c] = d;
      for (let i = 0; i < n; i++) res[i] -= d * qc[i];
    }
    let sse = 0;
    for (let i = 0; i < n; i++) sse += res[i] * res[i];
    return isFinite(sse) ? sse : Infinity;
  }
  function solveBeta(ws, k) {
    const R = ws.R, z = ws.z, b = [0, 0, 0, 0];
    for (let c = k - 1; c >= 0; c--) {
      let s = z[c];
      for (let j = c + 1; j < k; j++) s -= R[c * 4 + j] * b[j];
      b[c] = s / R[c * 4 + c];
    }
    return b;
  }

  // 差分进化 rand/1/bin（抖动 F），越界反射
  function de(fn, lo, hi, opt, rnd) {
    const D = lo.length, NP = Math.max(6, opt.pop), G = opt.gens;
    const pop = [], fit = new Float64Array(NP);
    for (let p = 0; p < NP; p++) {
      const x = new Float64Array(D);
      for (let d = 0; d < D; d++) x[d] = lo[d] + rnd() * (hi[d] - lo[d]);
      pop.push(x); fit[p] = fn(x);
    }
    const trial = new Float64Array(D);
    for (let g = 0; g < G; g++) {
      for (let p = 0; p < NP; p++) {
        let a, b, c;
        do a = (rnd() * NP) | 0; while (a === p);
        do b = (rnd() * NP) | 0; while (b === p || b === a);
        do c = (rnd() * NP) | 0; while (c === p || c === a || c === b);
        const F = 0.5 + 0.5 * rnd(), jr = (rnd() * D) | 0;
        const xa = pop[a], xb = pop[b], xc = pop[c], xp = pop[p];
        for (let d = 0; d < D; d++) {
          if (d === jr || rnd() < 0.9) {
            let v = xa[d] + F * (xb[d] - xc[d]);
            if (v < lo[d]) v = lo[d] + rnd() * (xp[d] - lo[d]);
            if (v > hi[d]) v = hi[d] - rnd() * (hi[d] - xp[d]);
            trial[d] = v;
          } else trial[d] = xp[d];
        }
        const f = fn(trial);
        if (f <= fit[p]) { xp.set(trial); fit[p] = f; }
      }
    }
    let bi = 0;
    for (let p = 1; p < NP; p++) if (fit[p] < fit[bi]) bi = p;
    return { x: Float64Array.from(pop[bi]), f: fit[bi] };
  }

  // 有界 Nelder–Mead（浏览器端替代 L-BFGS-B 精修）
  function nelderMead(fn, x0, lo, hi, iters) {
    const D = x0.length;
    const clamp = (x) => { for (let d = 0; d < D; d++) x[d] = Math.min(hi[d], Math.max(lo[d], x[d])); return x; };
    let S = [Float64Array.from(x0)];
    for (let d = 0; d < D; d++) { const x = Float64Array.from(x0); x[d] += (hi[d] - lo[d]) * 0.04 * (x[d] + (hi[d] - lo[d]) * 0.04 > hi[d] ? -1 : 1); S.push(clamp(x)); }
    let F = S.map(fn);
    for (let it = 0; it < iters; it++) {
      const idx = S.map((_, i) => i).sort((a, b) => F[a] - F[b]);
      S = idx.map((i) => S[i]); F = idx.map((i) => F[i]);
      const c = new Float64Array(D);
      for (let i = 0; i < D; i++) for (let d = 0; d < D; d++) c[d] += S[i][d] / D;
      const wv = S[D];
      const xr = clamp(c.map((v, d) => v + (v - wv[d])));
      const fr = fn(xr);
      if (fr < F[0]) {
        const xe = clamp(c.map((v, d) => v + 2 * (v - wv[d])));
        const fe = fn(xe);
        if (fe < fr) { S[D] = xe; F[D] = fe; } else { S[D] = xr; F[D] = fr; }
      } else if (fr < F[D - 1]) { S[D] = xr; F[D] = fr; }
      else {
        const xc = clamp(c.map((v, d) => v + 0.5 * (wv[d] - v)));
        const fc = fn(xc);
        if (fc < F[D]) { S[D] = xc; F[D] = fc; }
        else for (let i = 1; i <= D; i++) { S[i] = clamp(S[i].map((v, d) => S[0][d] + 0.5 * (v - S[0][d]))); F[i] = fn(S[i]); }
      }
    }
    let bi = 0;
    for (let i = 1; i <= D; i++) if (F[i] < F[bi]) bi = i;
    return { x: S[bi], f: F[bi] };
  }

  // 过滤标准：Sornette DS LPPLS（2015 上证研究） 与 V4.8-R2 严格门
  const FILTERS = {
    ds: (f) => f.B < 0 && f.m >= 0.01 && f.m <= 0.99 && f.w >= 2 && f.w <= 15 && f.ahead <= Math.max(5, 0.1 * f.n) && f.O >= 2.5 && f.D >= 0.5,
    strict: (f) => f.B < 0 && f.m > 0.1 && f.m < 0.9 && f.w > 6 && f.w < 13 && f.ahead <= 90 && f.O >= 2.5 && f.D >= 1 && f.R2 >= 0.9,
  };
  OD.FILTERS = FILTERS;

  function fitWindow(yWin, opt, rnd) {
    const ws = makeWS(yWin);
    const n = ws.n, t2 = n - 1;
    const maxAhead = opt.aheadHi || Math.min(252, Math.max(20, Math.round(0.3 * n)));
    const lo = [t2 + (opt.aheadLo !== undefined ? opt.aheadLo : 0.5), opt.mLo || 0.01, opt.wLo || 2], hi = [t2 + maxAhead, opt.mHi || 0.99, opt.wHi || 25];
    const fn = (x) => linFit(ws, x[0], x[1], x[2], 4);
    const r1 = de(fn, lo, hi, opt, rnd);
    const r2 = nelderMead(fn, r1.x, lo, hi, opt.nm);
    const best = r2.f < r1.f ? r2 : r1;
    const tc = best.x[0], m = best.x[1], w = best.x[2];
    const sse = linFit(ws, tc, m, w, 4);
    const b = solveBeta(ws, 4);
    const C = Math.hypot(b[2], b[3]);
    const fit = {
      n, tc, ahead: tc - t2, m, w, A: b[0], B: b[1], C1: b[2], C2: b[3],
      D: C > 0 ? (m * Math.abs(b[1])) / (w * C) : Infinity,
      O: (w / (2 * Math.PI)) * Math.log(tc / (tc - t2)),
      R2: ws.sst > 0 ? 1 - sse / ws.sst : 0, sse,
    };
    // 纯幂律嵌套对照（POWER）：同窗口、同 tc 搜索域
    if (opt.power !== false) {
      const fp = (x) => linFit(ws, x[0], x[1], 0, 2);
      let bp = null, bf = Infinity;
      for (let a = 0; a < 12; a++) for (let c = 0; c < 8; c++) {
        const x = [lo[0] + (hi[0] - lo[0]) * (a + 0.5) / 12, 0.05 + 0.9 * (c + 0.5) / 8];
        const v = fp(x);
        if (v < bf) { bf = v; bp = x; }
      }
      const rp = nelderMead(fp, bp, [lo[0], 0.01], [hi[0], 0.99], 50);
      const ssePow = Math.max(Math.min(bf, rp.f), sse);
      const nu = Math.max(1, n - 7);
      fit.ssePow = ssePow;
      fit.Fstat = ((ssePow - sse) / 2) / (sse / nu);
      fit.pF = Math.pow(1 + (2 * fit.Fstat) / nu, -nu / 2); // F(2,ν) 精确尾概率（假设残差独立）
    }
    fit.ds = FILTERS.ds(fit);
    fit.strict = FILTERS.strict(fit);
    fit._ws = ws;
    return fit;
  }

  function lpplsCurve(f, n) {
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const dt = f.tc - i, L = Math.log(dt), p = Math.exp(f.m * L);
      out[i] = f.A + f.B * p + f.C1 * p * Math.cos(f.w * L) + f.C2 * p * Math.sin(f.w * L);
    }
    return out;
  }

  // Demos & Sornette (2017) Lagrange 正则：消除 χ² 随样本长度的系统漂移后选择起点
  function lagrangeBest(fits) {
    if (fits.length < 3) return fits.length ? 0 : -1;
    const xs = fits.map((f) => f.n), ys = fits.map((f) => f.sse / Math.max(1, f.n - 7));
    const mx = xs.reduce((a, b) => a + b, 0) / xs.length, my = ys.reduce((a, b) => a + b, 0) / ys.length;
    let sxy = 0, sxx = 0;
    for (let i = 0; i < xs.length; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; }
    const lam = sxx > 0 ? sxy / sxx : 0;
    let bi = 0, bv = Infinity;
    fits.forEach((f, i) => { const v = ys[i] - lam * xs[i]; if (v < bv) { bv = v; bi = i; } });
    return bi;
  }

  async function lpplsScan(logp, dir, windows, opt, rnd, tick) {
    const N = logp.length;
    const y = dir === 'top' ? logp : logp.map((v) => -v);
    const fits = [];
    for (const n of windows) {
      if (n > N) continue;
      const f = fitWindow(y.slice(N - n), opt, rnd);
      f.dir = dir;
      if (!opt.keepWS) delete f._ws;
      fits.push(f);
      if (tick) await tick();
    }
    const ds = fits.filter((f) => f.ds), st = fits.filter((f) => f.strict);
    return {
      dir, fits,
      confDS: fits.length ? ds.length / fits.length : 0,
      confStrict: fits.length ? st.length / fits.length : 0,
      tcDS: ds.map((f) => f.ahead), tcAll: fits.map((f) => f.ahead),
      powerPass: fits.length ? fits.filter((f) => f.pF !== undefined && f.pF < 0.01).length / fits.length : 0,
    };
  }

  function quantile(arr, q) {
    if (!arr.length) return NaN;
    const a = Array.from(arr).sort((x, y) => x - y);
    const p = (a.length - 1) * q, i = Math.floor(p), f = p - i;
    return i + 1 < a.length ? a[i] * (1 - f) + a[i + 1] * f : a[i];
  }
  OD.quantile = quantile;

  // 残差块 bootstrap：t_c 参数不确定性（不是事件概率）
  async function bootstrapTc(logp, dir, fit, B, rnd, tick) {
    const n = fit.n, N = logp.length;
    const y = (dir === 'top' ? logp : logp.map((v) => -v)).slice(N - n);
    const yhat = lpplsCurve(fit, n);
    const e = new Float64Array(n);
    for (let i = 0; i < n; i++) e[i] = y[i] - yhat[i];
    const blk = 10, out = [];
    for (let b = 0; b < B; b++) {
      const ys = new Float64Array(n);
      let i = 0;
      while (i < n) { const s = (rnd() * (n - blk)) | 0; for (let k = 0; k < blk && i < n; k++, i++) ys[i] = yhat[i] + e[s + k]; }
      const f = fitWindow(ys, { pop: 15, gens: 24, nm: 40, power: false }, rnd);
      out.push(f.ahead);
      if (tick) await tick();
    }
    return { n, list: out, q05: quantile(out, 0.05), q50: quantile(out, 0.5), q95: quantile(out, 0.95) };
  }

  /* =====================================================================
     统计物理指标（非均线类）
     ===================================================================== */
  function logReturns(close) {
    const r = new Float64Array(close.length);
    for (let i = 1; i < close.length; i++) r[i] = Math.log(close[i] / close[i - 1]);
    return r;
  }
  // 去趋势波动分析 DFA-1 → Hurst 型标度指数 α
  function dfaAt(r, end, W) {
    if (end - W + 1 < 1) return NaN;
    let mu = 0;
    for (let k = 0; k < W; k++) mu += r[end - W + 1 + k];
    mu /= W;
    const x = new Float64Array(W);
    let c = 0;
    for (let k = 0; k < W; k++) { c += r[end - W + 1 + k] - mu; x[k] = c; }
    const sizes = [8, 11, 16, 22, 32, 45, 60].filter((s) => s <= W / 4);
    const lx = [], lf = [];
    for (const s of sizes) {
      const nseg = Math.floor(W / s), jb = (s - 1) / 2, Sjj = (s * (s * s - 1)) / 12;
      let tot = 0;
      for (let g = 0; g < nseg; g++) {
        let vm = 0;
        for (let j = 0; j < s; j++) vm += x[g * s + j];
        vm /= s;
        let sxy = 0, svv = 0;
        for (let j = 0; j < s; j++) { const v = x[g * s + j] - vm; sxy += (j - jb) * v; svv += v * v; }
        const sl = sxy / Sjj;
        tot += Math.max(0, svv - sl * sl * Sjj);
      }
      lx.push(Math.log(s)); lf.push(0.5 * Math.log(tot / (nseg * s) + 1e-300));
    }
    const mx = lx.reduce((a, b) => a + b, 0) / lx.length, my = lf.reduce((a, b) => a + b, 0) / lf.length;
    let sxy = 0, sxx = 0;
    for (let i = 0; i < lx.length; i++) { sxy += (lx[i] - mx) * (lf[i] - my); sxx += (lx[i] - mx) ** 2; }
    return sxy / sxx;
  }
  // Bandt–Pompe 排列熵（阶数 4，归一化）
  function permEntAt(c, end, W) {
    if (end - W + 1 < 0) return NaN;
    const cnt = new Float64Array(24);
    let tot = 0;
    for (let i = end - W + 1; i <= end - 3; i++) {
      const v0 = c[i], v1 = c[i + 1], v2 = c[i + 2], v3 = c[i + 3];
      const l0 = (v1 < v0) + (v2 < v0) + (v3 < v0), l1 = (v2 < v1) + (v3 < v1), l2 = v3 < v2 ? 1 : 0;
      cnt[l0 * 6 + l1 * 2 + l2]++; tot++;
    }
    let H = 0;
    for (let k = 0; k < 24; k++) if (cnt[k] > 0) { const p = cnt[k] / tot; H -= p * Math.log(p); }
    return H / Math.log(24);
  }
  function ar1VarAt(r, end, W) {
    if (end - W < 1) return [NaN, NaN];
    let mu = 0;
    for (let i = end - W + 1; i <= end; i++) mu += r[i];
    mu /= W;
    let num = 0, den = 0;
    for (let i = end - W + 1; i <= end; i++) { const a = r[i] - mu; den += a * a; if (i > end - W + 1) num += a * (r[i - 1] - mu); }
    return [den > 0 ? num / den : NaN, den / (W - 1)];
  }
  function kendallTau(series, end, L) {
    const xs = [];
    for (let i = Math.max(0, end - L + 1); i <= end; i++) if (isFinite(series[i])) xs.push([i, series[i]]);
    let c = 0, d = 0;
    for (let i = 0; i < xs.length; i++) for (let j = i + 1; j < xs.length; j++) {
      const s = Math.sign(xs[j][1] - xs[i][1]);
      if (s > 0) c++; else if (s < 0) d++;
    }
    return c + d > 0 ? (c - d) / (c + d) : NaN;
  }

  OD.physics = function (bars) {
    const N = bars.length;
    const close = Float64Array.from(bars.map((b) => b.close));
    const r = logReturns(close);
    const hurst = new Float64Array(N).fill(NaN), pe = new Float64Array(N).fill(NaN);
    const ar1 = new Float64Array(N).fill(NaN), vr = new Float64Array(N).fill(NaN);
    for (let i = 0; i < N; i++) {
      if (i >= 240) hurst[i] = dfaAt(r, i, 240);
      if (i >= 120) { pe[i] = permEntAt(close, i, 120); const av = ar1VarAt(r, i, 120); ar1[i] = av[0]; vr[i] = av[1]; }
    }
    const last = N - 1;
    let s60 = 0, m60 = 0, cnt = 0;
    for (let i = Math.max(1, N - 60); i < N; i++) { m60 += r[i]; cnt++; }
    m60 /= Math.max(1, cnt);
    for (let i = Math.max(1, N - 60); i < N; i++) s60 += (r[i] - m60) ** 2;
    const sigma = Math.sqrt(s60 / Math.max(1, cnt - 1));
    return {
      r, hurst, pe, ar1, vr, sigma,
      now: { hurst: hurst[last], pe: pe[last], ar1: ar1[last], vr: vr[last], tauAR1: kendallTau(ar1, last, 120), tauVar: kendallTau(vr, last, 120) },
    };
  };

  /* =====================================================================
     价格层 PPE：Range-Aware KDE → 经验自由能
     ===================================================================== */
  function kdeLandscape(xs, sig2, wts, grid) {
    const G = grid.length, rho = new Float64Array(G);
    for (let i = 0; i < xs.length; i++) {
      const s = Math.sqrt(sig2[i]), a = wts[i] / s, x = xs[i], inv = 1 / (2 * sig2[i]);
      for (let g = 0; g < G; g++) { const d = grid[g] - x; if (d * d * inv < 18) rho[g] += a * Math.exp(-d * d * inv); }
    }
    const dx = grid[1] - grid[0];
    let Z = 0;
    for (let g = 0; g < G; g++) Z += rho[g] * dx;
    for (let g = 0; g < G; g++) rho[g] = rho[g] / Z + 1e-12;
    return rho;
  }
  function findWells(grid, rho) {
    const G = grid.length, F = new Float64Array(G);
    let Fmin = Infinity;
    for (let g = 0; g < G; g++) { F[g] = -Math.log(rho[g]); Fmin = Math.min(Fmin, F[g]); }
    for (let g = 0; g < G; g++) F[g] -= Fmin;
    const mins = [], maxs = [];
    for (let g = 1; g < G - 1; g++) {
      if (F[g] < F[g - 1] && F[g] <= F[g + 1]) mins.push(g);
      if (F[g] > F[g - 1] && F[g] >= F[g + 1]) maxs.push(g);
    }
    const dx = grid[1] - grid[0];
    const wells = mins.map((g) => {
      const lb = maxs.filter((m) => m < g).pop(), rb = maxs.find((m) => m > g);
      const l = lb === undefined ? 0 : lb, r = rb === undefined ? G - 1 : rb;
      let mass = 0;
      for (let k = l; k <= r; k++) mass += rho[k] * dx;
      const barL = lb === undefined ? Infinity : F[lb], barR = rb === undefined ? Infinity : F[rb];
      const depth = Math.min(barL, barR) - F[g];
      return { g, x: grid[g], price: Math.exp(grid[g]), F: F[g], mass, depth: isFinite(depth) ? depth : F[l === 0 ? r : l] - F[g], lo: grid[l], hi: grid[r] };
    }).filter((w) => w.mass > 0.02 && w.depth > 0.04);
    return { F, wells };
  }

  OD.priceLayer = function (bars) {
    const N = bars.length, L = Math.min(500, N), HL = 120;
    const vols = bars.slice(N - L).map((b) => b.volume).filter((v) => v > 0).sort((a, b) => a - b);
    const vmed = vols.length ? vols[(vols.length / 2) | 0] : 1;
    const xs = [], r2 = [], wts = [];
    for (let i = N - L; i < N; i++) {
      const b = bars[i];
      xs.push(Math.log((b.high + b.low + b.close) / 3));
      r2.push(((Math.log(b.high) - Math.log(b.low)) ** 2) / 12);
      const age = N - 1 - i;
      const vw = b.volume > 0 ? Math.min(5, Math.max(0.2, Math.sqrt(b.volume / vmed))) : 0.2;
      wts.push(Math.pow(2, -age / HL) * vw);
    }
    let sw = 0, mu = 0;
    for (let i = 0; i < xs.length; i++) { sw += wts[i]; mu += wts[i] * xs[i]; }
    mu /= sw;
    let v = 0, sw2 = 0;
    for (let i = 0; i < xs.length; i++) { v += wts[i] * (xs[i] - mu) ** 2; sw2 += wts[i] * wts[i]; }
    const sd = Math.sqrt(v / sw), neff = (sw * sw) / sw2;
    const h0 = Math.max(0.006, 0.5 * 1.06 * sd * Math.pow(neff, -0.2));
    const xmin = Math.min(...xs) - 4 * h0, xmax = Math.max(...xs) + 4 * h0;
    const G = 320, grid = new Float64Array(G);
    for (let g = 0; g < G; g++) grid[g] = xmin + ((xmax - xmin) * g) / (G - 1);
    const kappa = 1;
    const bands = [0.7, 1, 1.4].map((k) => {
      const h = h0 * k;
      const sig2 = r2.map((rr) => h * h + kappa * kappa * rr);
      const rho = kdeLandscape(xs, sig2, wts, grid);
      return { k, h, rho, ...findWells(grid, rho) };
    });
    const main = bands[1];
    main.wells.forEach((w) => {
      let c = 0;
      bands.forEach((b) => { if (b.wells.some((o) => Math.abs(o.x - w.x) <= main.h)) c++; });
      w.persistence = c / bands.length;
    });
    const xNow = Math.log(bars[N - 1].close);
    const basin = main.wells.find((w) => xNow >= w.lo && xNow <= w.hi) || null;
    const above = main.wells.filter((w) => w.x > xNow + 0.03).sort((a, b) => a.x - b.x)[0] || null;
    const below = main.wells.filter((w) => w.x < xNow - 0.03).sort((a, b) => b.x - a.x)[0] || null;
    let gNow = 0;
    for (let g = 0; g < G; g++) if (grid[g] <= xNow) gNow = g;
    return { grid, rho: main.rho, F: main.F, wells: main.wells, h: main.h, xNow, Fnow: main.F[gNow], basin, above, below, lookback: L, halfLife: HL };
  };

  /* =====================================================================
     首达竞争风险：上 / 下 / 未触达 / 同 bar 歧义
     ===================================================================== */
  OD.passage = function (bars, U, Lp, H, opt) {
    opt = opt || {};
    const rnd = mulberry32(opt.seed || 7);
    const N = bars.length, look = Math.min(750, N - 1);
    const rr = [], hh = [], ll = [];
    for (let i = N - look; i < N; i++) {
      const pc = bars[i - 1].close;
      rr.push(Math.log(bars[i].close / pc)); hh.push(Math.log(bars[i].high / pc)); ll.push(Math.log(bars[i].low / pc));
    }
    const mu = opt.demean === false ? 0 : rr.reduce((a, b) => a + b, 0) / rr.length;
    const n = rr.length, c0 = bars[N - 1].close;
    const lu = Math.log(U / c0), ld = Math.log(Lp / c0), M = opt.paths || 4000;
    function sim(block) {
      const hu = new Float64Array(H + 1), hd = new Float64Array(H + 1);
      let amb = 0, none = 0;
      for (let p = 0; p < M; p++) {
        let x = 0, k = (rnd() * n) | 0, done = false;
        for (let j = 1; j <= H; j++) {
          if (j > 1) k = block ? (rnd() < 0.2 ? (rnd() * n) | 0 : (k + 1) % n) : (rnd() * n) | 0;
          const up = x + hh[k] - mu >= lu, dn = x + ll[k] - mu <= ld;
          if (up && dn) { amb++; done = true; break; }
          if (up) { hu[j]++; done = true; break; }
          if (dn) { hd[j]++; done = true; break; }
          x += rr[k] - mu;
        }
        if (!done) none++;
      }
      let su = 0, sd = 0;
      for (let j = 1; j <= H; j++) { su += hu[j]; sd += hd[j]; hu[j] /= M; hd[j] /= M; }
      const surv = [1];
      for (let j = 1; j <= H; j++) surv.push(surv[j - 1] - hu[j] - hd[j]);
      return { qU: su / M, qL: sd / M, qN: none / M, qA: amb / M, histU: hu, histL: hd, surv };
    }
    const block = sim(true), iid = sim(false);
    const act = 1 - block.qN - block.qA;
    return { U, L: Lp, H, c0, demean: opt.demean !== false, lookback: n, block, iid, dirUp: act > 0 ? block.qU / act : NaN };
  };

  OD.defaultBarriers = function (bars, ppe, sigma, H) {
    const c0 = bars[bars.length - 1].close;
    const vol = Math.max(0.03, 1.5 * sigma * Math.sqrt(H));
    let up = c0 * Math.exp(vol), dn = c0 * Math.exp(-vol), src = '波动率 ±1.5σ√H';
    if (ppe && ppe.above && ppe.below && ppe.above.price / c0 < 1.3 && c0 / ppe.below.price < 1.3) {
      up = ppe.above.price; dn = ppe.below.price; src = '相邻价格井中心';
    }
    return { up, dn, src };
  };

  /* =====================================================================
     逻辑回归（岭）与回测
     ===================================================================== */
  function solveLin(A, b) {
    const n = b.length, M = A.map((row, i) => [...row, b[i]]);
    for (let c = 0; c < n; c++) {
      let p = c;
      for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      [M[c], M[p]] = [M[p], M[c]];
      if (Math.abs(M[c][c]) < 1e-12) return null;
      for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
    }
    return M.map((row, i) => row[n] / row[i]);
  }
  function logitFit(X, y, lambda) {
    const p = X[0].length;
    let w = new Array(p).fill(0);
    for (let it = 0; it < 30; it++) {
      const Hm = Array.from({ length: p }, () => new Array(p).fill(0)), g = new Array(p).fill(0);
      for (let i = 0; i < X.length; i++) {
        let z = 0;
        for (let k = 0; k < p; k++) z += w[k] * X[i][k];
        const pr = 1 / (1 + Math.exp(-z)), s = pr * (1 - pr);
        for (let a = 0; a < p; a++) { g[a] += (y[i] - pr) * X[i][a]; for (let b = 0; b < p; b++) Hm[a][b] += s * X[i][a] * X[i][b]; }
      }
      for (let a = 1; a < p; a++) { Hm[a][a] += lambda; g[a] -= lambda * w[a]; }
      Hm[0][0] += 1e-6;
      const dlt = solveLin(Hm, g);
      if (!dlt) break;
      let mx = 0;
      w = w.map((v, k) => { mx = Math.max(mx, Math.abs(dlt[k])); return v + dlt[k]; });
      if (mx < 1e-7) break;
    }
    return w;
  }
  const sigm = (z) => 1 / (1 + Math.exp(-z));

  function labelsAt(close, t, dir) {
    const N = close.length;
    if (t + 80 > N - 1) return null;
    let u = 1;
    for (let k = 2; k <= 20; k++) if (dir === 'top' ? close[t + k] > close[t + u] : close[t + k] < close[t + u]) u = k;
    const ref = close[t + u];
    for (let v = u + 1; v <= u + 60; v++) {
      if (dir === 'top' && close[t + v] / ref <= 0.9) return 1;
      if (dir === 'bottom' && close[t + v] / ref >= 1.1) return 1;
    }
    return 0;
  }

  async function backtest(bars, logp, phys, info, opt, rnd, tick) {
    const N = bars.length, close = bars.map((b) => b.close);
    const step = opt.step || 5, span = Math.min(opt.span || 600, N - 320);
    const wins = [80, 125, 180, 250, 350];
    const pts = [];
    const t0 = N - 1 - span;
    const list = [];
    for (let t = t0; t <= N - 1; t += step) list.push(t);
    for (let k = 0; k < list.length; k++) {
      const t = list[k];
      const lp = logp.slice(0, t + 1);
      const ow = wins.filter((w) => w <= t + 1);
      const top = await lpplsScan(lp, 'top', ow, { pop: 10, gens: 14, nm: 24, power: false }, rnd, null);
      const bot = await lpplsScan(lp, 'bottom', ow, { pop: 10, gens: 14, nm: 24, power: false }, rnd, null);
      pts.push({
        t, date: bars[t].date, confTop: top.confDS, confBot: bot.confDS,
        tcTop: top.tcDS.length ? quantile(top.tcDS, 0.5) : NaN, tcBot: bot.tcDS.length ? quantile(bot.tcDS, 0.5) : NaN,
        hurst: phys.hurst[t], pe: phys.pe[t], ar1: phys.ar1[t],
        yTop: labelsAt(close, t, 'top'), yBot: labelsAt(close, t, 'bottom'), mature: t + 80,
      });
      if (tick) await tick(k + 1, list.length);
    }
    // 滚动前推概率：只使用在 t 时刻已经成熟（t_j + 80 ≤ t）的标签
    const feats = (p) => [1, p.conf, isFinite(p.hurst) ? p.hurst - 0.5 : 0, isFinite(p.pe) ? p.pe - 0.9 : 0, isFinite(p.ar1) ? p.ar1 : 0];
    function walk(dir) {
      const key = dir === 'top' ? 'yTop' : 'yBot', ck = dir === 'top' ? 'confTop' : 'confBot';
      const res = [];
      pts.forEach((p) => {
        const train = pts.filter((q) => q.mature <= p.t && q[key] !== null);
        const out = { t: p.t, y: p[key], base: NaN, lp: NaN, ph: NaN, n: train.length };
        if (train.length >= 15) {
          const ys = train.map((q) => q[key]);
          const base = (ys.reduce((a, b) => a + b, 0) + 1) / (ys.length + 2);
          out.base = base; out.lp = base; out.ph = base;
          const both = ys.some((v) => v === 1) && ys.some((v) => v === 0);
          if (both) {
            const w1 = logitFit(train.map((q) => [1, q[ck]]), ys, 0.5);
            out.lp = sigm(w1[0] + w1[1] * p[ck]);
            const X = train.map((q) => feats({ ...q, conf: q[ck] }));
            const w2 = logitFit(X, ys, 2.0);
            const xp = feats({ ...p, conf: p[ck] });
            out.ph = sigm(xp.reduce((a, v, i) => a + v * w2[i], 0));
          }
        }
        res.push(out);
      });
      const ev = res.filter((r) => r.y !== null && isFinite(r.base));
      const bs = (k) => ev.length ? ev.reduce((a, r) => a + (r[k] - r.y) ** 2, 0) / ev.length : NaN;
      const rate = ev.length ? ev.reduce((a, r) => a + r.y, 0) / ev.length : NaN;
      const last = res[res.length - 1];
      return { series: res, n: ev.length, rate, base: bs('base'), lp: bs('lp'), ph: bs('ph'), now: last };
    }
    const evTop = walk('top'), evBot = walk('bottom');

    // A 股规则交易回测：信号阈值事前固定，不做优化
    const thB = 0.3, thT = 0.3, stop = 0.12, maxHold = 60, comm = 0.00025, stamp = 0.0005, slip = 0.0005;
    const lim = info.limit;
    let cash = 1, sh = 0, pos = 0, entry = 0, entryDay = -1, pending = null, pi = 0;
    const eq = [], bh = [], dates = [], marks = [], trades = [];
    let blocked = 0;
    const start = list[0];
    for (let d = start; d < N; d++) {
      const b = bars[d], pc = d > 0 ? bars[d - 1].close : b.open;
      if (pending === 'buy' && d > start) {
        if (b.open >= pc * (1 + lim - 0.003)) blocked++;
        else { const px = b.open * (1 + slip); sh = (cash * (1 - comm)) / px; cash = 0; pos = 1; entry = px; entryDay = d; pending = null; marks.push({ i: d - start, type: 'buy' }); }
      } else if (pending === 'sell') {
        if (b.open <= pc * (1 - lim + 0.003)) blocked++;
        else { const px = b.open * (1 - slip); cash = sh * px * (1 - comm - stamp); trades.push({ ret: px * (1 - comm - stamp) / (entry / (1 - comm)) - 1, days: d - entryDay }); sh = 0; pos = 0; pending = null; marks.push({ i: d - start, type: 'sell' }); }
      }
      eq.push(cash + sh * b.close); bh.push(b.close / bars[start].close); dates.push(b.date);
      while (pi + 1 < pts.length && pts[pi + 1].t <= d) pi++;
      const sg = pts[pi];
      if (!pending) {
        if (!pos && sg.confBot >= thB && sg.confTop < thT && d < N - 1) pending = 'buy';
        else if (pos && d > entryDay && (sg.confTop >= thT || b.close / entry - 1 <= -stop || d - entryDay >= maxHold)) pending = 'sell';
      }
    }
    const mdd = (s) => { let pk = -Infinity, m = 0; s.forEach((v) => { pk = Math.max(pk, v); m = Math.max(m, 1 - v / pk); }); return m; };
    const yrs = eq.length / 252;
    const stats = {
      ret: eq[eq.length - 1] - 1, bhRet: bh[bh.length - 1] - 1,
      ann: Math.pow(Math.max(1e-9, eq[eq.length - 1]), 1 / Math.max(yrs, 0.1)) - 1,
      mdd: mdd(eq), bhMdd: mdd(bh), trades: trades.length,
      win: trades.length ? trades.filter((t) => t.ret > 0).length / trades.length : NaN,
      exposure: 0, blocked, openPos: pos === 1,
    };
    let inPos = 0;
    { let p = 0, mi = 0; for (let i = 0; i < eq.length; i++) { while (mi < marks.length && marks[mi].i === i) { p = marks[mi].type === 'buy' ? 1 : 0; mi++; } inPos += p; } }
    stats.exposure = inPos / eq.length;
    return { pts, top: evTop, bottom: evBot, strat: { eq, bh, dates, marks, trades, stats, rules: { thB, thT, stop, maxHold, comm, stamp, slip, lim } }, step, span, windows: wins };
  }

  /* =====================================================================
     信号治理（Governor）
     ===================================================================== */
  function governor(q, top, bot, ph) {
    if (q.level === 'BAN') return { code: 'BAN', label: '数据阻断', tone: 'ban', reasons: ['数据质量不满足最低要求，禁止使用任何预测'] };
    const reasons = [];
    const ews = ph.now.tauAR1 > 0.3 && ph.now.tauVar > 0.3;
    if (ews) reasons.push('临界慢化：AR(1) 与方差同时呈上升趋势（Kendall τ > 0.3）');
    if (top.confDS >= 0.25) reasons.push('顶部 LPPLS DS 置信度 ' + Math.round(top.confDS * 100) + '%');
    if (bot.confDS >= 0.25) reasons.push('反泡沫底部 DS 置信度 ' + Math.round(bot.confDS * 100) + '%');
    if (top.confDS >= 0.25 || (ews && top.confDS > 0)) return { code: 'WATCH_RISK', label: '顶部风险观察', tone: 'risk', reasons: reasons.concat(bot.confDS >= 0.25 ? ['顶部与底部结构同时出现，信号冲突，优先风控'] : []) };
    if (bot.confDS >= 0.25) return { code: 'PROBE', label: '底部结构候选', tone: 'probe', reasons };
    reasons.push('未出现合格的临界结构，维持观察');
    return { code: 'WATCH', label: '观察', tone: 'watch', reasons };
  }

  /* =====================================================================
     总流程
     ===================================================================== */
  OD.WINDOWS = [60, 80, 100, 125, 150, 180, 225, 250, 300, 350, 400, 450, 500, 600, 700, 750];

  OD.analyze = async function (input, opt, onProgress) {
    opt = opt || {};
    const info = OD.parseCode(input);
    if (!info) throw new Error('代码格式不正确：请输入 6 位 A 股代码，例如 600519 或 000001.SZ');
    const prog = (stage, p) => onProgress && onProgress(stage, Math.min(1, Math.max(0, p)));
    prog('获取日线数据', 0.02);
    let data;
    try { data = opt.forceSynthetic ? OD.syntheticDaily(info) : await OD.fetchDaily(info); }
    catch (e) {
      if (opt.allowSynthetic === false) throw e;
      data = OD.syntheticDaily(info);
      data.fetchError = e.message;
    }
    const bars = data.bars;
    const quality = OD.qualityCheck(bars, data);
    prog('数据质量检查', 0.05);
    await yieldUI();
    if (quality.level === 'BAN') return { info, data, bars, quality, state: governor(quality) };

    const rnd = mulberry32(20261023);
    const logp = bars.map((b) => Math.log(b.close));
    const wins = OD.WINDOWS.filter((w) => w <= bars.length);
    let done = 0;
    const tickScan = (base, span, total) => async () => { done++; prog(base.label, base.p + (span * done) / total); await yieldUI(); };

    done = 0;
    const top = await lpplsScan(logp, 'top', wins, { pop: 24, gens: 45, nm: 120, keepWS: false }, rnd, tickScan({ label: '顶部 LPPLS 多窗口拟合', p: 0.05 }, 0.14, wins.length));
    done = 0;
    const bot = await lpplsScan(logp, 'bottom', wins, { pop: 24, gens: 45, nm: 120, keepWS: false }, rnd, tickScan({ label: '反泡沫（底部）多窗口拟合', p: 0.19 }, 0.14, wins.length));

    top.best = lagrangeBest(top.fits);
    bot.best = lagrangeBest(bot.fits);
    done = 0;
    const B = opt.boot || 20;
    top.boot = top.best >= 0 ? await bootstrapTc(logp, 'top', top.fits[top.best], B, rnd, tickScan({ label: 't_c 残差块 bootstrap（顶部）', p: 0.33 }, 0.05, B)) : null;
    done = 0;
    bot.boot = bot.best >= 0 ? await bootstrapTc(logp, 'bottom', bot.fits[bot.best], B, rnd, tickScan({ label: 't_c 残差块 bootstrap（底部）', p: 0.38 }, 0.05, B)) : null;

    prog('统计物理指标', 0.44);
    await yieldUI();
    const phys = OD.physics(bars);
    prog('价格层自由能地形', 0.46);
    await yieldUI();
    const ppe = OD.priceLayer(bars);
    const H = opt.H || 20;
    const bar = OD.defaultBarriers(bars, ppe, phys.sigma, H);
    prog('首达竞争风险模拟', 0.48);
    await yieldUI();
    const passage = OD.passage(bars, bar.up, bar.dn, H, {});
    passage.src = bar.src;

    let bt = null;
    if (opt.backtest !== false && bars.length >= 420) {
      bt = await backtest(bars, logp, phys, info, { span: opt.span || 600, step: opt.step || 10 }, rnd, async (k, n) => { prog('滚动 as-of 回测 ' + k + '/' + n, 0.5 + (0.49 * k) / n); await yieldUI(); });
    }
    const state = governor(quality, top, bot, phys);
    prog('完成', 1);
    return { info, data, bars, quality, top, bot, phys, ppe, passage, bt, state, ranAt: new Date().toISOString() };
  };

  OD.governor = governor;
  OD.lpplsCurve = lpplsCurve;
  OD._fitWindow = fitWindow;
  OD._lagrangeBest = lagrangeBest;
  OD._kendallTau = kendallTau;
  global.OD = OD;
})(typeof window !== 'undefined' ? window : globalThis);
