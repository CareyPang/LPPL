/* =====================================================================
   临界点 2.0 · 顶底分离引擎（依赖 engine.js 中的 OD）
   ---------------------------------------------------------------------
   顶部引擎：LPPLS 多窗口（38 个窗口，30–700 日）→ 合格拟合 → t_c 聚类
             → 主 / 次见顶窗口 + 窗口一致度（参与聚类的窗口占比）
   底部引擎：不依赖单一反泡沫拟合。需要“深度 + 时间 + 恐慌释放 + 止跌 +
             支撑井 + 反泡沫结构”多条件共振才允许分批进场（防半山腰）
   路线图：  见顶窗口 → 历史同类回撤的幅度 / 时长分布 → 底部时间与价格区间
   回放：    任意截止日只用截止日之前的数据，再与真实后续走势对照打分
   全部规则事前固定；没有针对任何日期调参。
   ===================================================================== */
(function (G) {
  'use strict';
  const OD = G.OD;
  const CP = {};
  const q = OD.quantile;
  const yieldUI = () => new Promise((r) => setTimeout(r, 0));

  /* ---------------- 标的解析与数据 ---------------- */
  const INDEX = {
    sh000001: { key: 'sh000001', label: '上证指数', code: '000001.SH', secid: '1.000001' },
    sh000300: { key: 'sh000300', label: '沪深300', code: '000300.SH', secid: '1.000300' },
    sz399006: { key: 'sz399006', label: '创业板指', code: '399006.SZ', secid: '0.399006' },
  };
  CP.INDEX = INDEX;
  CP.resolve = function (input) {
    const s = String(input || '').trim().toLowerCase().replace(/\s+/g, '');
    const alias = {
      '上证指数': 'sh000001', '上证': 'sh000001', '上证综指': 'sh000001', 'sh000001': 'sh000001', '000001.sh': 'sh000001', '1.000001': 'sh000001',
      '沪深300': 'sh000300', 'hs300': 'sh000300', 'sh000300': 'sh000300', '000300': 'sh000300', '000300.sh': 'sh000300',
      '创业板指': 'sz399006', '创业板': 'sz399006', 'sz399006': 'sz399006', '399006': 'sz399006', '399006.sz': 'sz399006',
    };
    if (alias[s]) { const ix = INDEX[alias[s]]; return { ...ix, isIndex: true, limit: 0.1, market: ix.secid[0] === '1' ? 'SH' : 'SZ' }; }
    const info = OD.parseCode(input);
    if (!info) return null;
    return { key: info.secid, label: info.label, code: info.label, secid: info.secid, isIndex: false, limit: info.limit, market: info.market };
  };

  function snapBars(key) {
    const S = G.OD_SNAP && G.OD_SNAP[key];
    if (!S) return null;
    const bars = S.rows.split(';').map((r) => {
      const a = r.split(',');
      return { date: a[0].slice(0, 4) + '-' + a[0].slice(4, 6) + '-' + a[0].slice(6, 8), open: +a[1], close: +a[2], high: +a[3], low: +a[4], volume: +a[5] * 1000 };
    });
    return { name: S.name, bars, source: '内置快照（东方财富日线，截至 ' + bars[bars.length - 1].date + '）', snapshot: true };
  }
  CP.load = async function (sym, opt) {
    opt = opt || {};
    if (sym.isIndex && opt.preferSnapshot) { const s = snapBars(sym.key); if (s) return s; }
    try {
      const d = await OD.fetchDaily({ secid: sym.secid, label: sym.label });
      d.source = '东方财富实时接口 · ' + (sym.isIndex ? '指数日线' : '前复权日线');
      if (sym.isIndex) d.name = sym.label;
      return d;
    } catch (e) {
      const s = sym.isIndex ? snapBars(sym.key) : null;
      if (s) { s.fetchError = e.message; return s; }
      throw e;
    }
  };

  /* ---------------- 基础统计 ---------------- */
  function sigmaAt(close, T, W) {
    W = W || 60;
    const a = Math.max(1, T - W + 1);
    let m = 0, n = 0;
    for (let i = a; i <= T; i++) { m += Math.log(close[i] / close[i - 1]); n++; }
    m /= Math.max(1, n);
    let v = 0;
    for (let i = a; i <= T; i++) v += (Math.log(close[i] / close[i - 1]) - m) ** 2;
    return Math.sqrt(v / Math.max(1, n - 1));
  }
  CP.sigmaAt = sigmaAt;

  // 交易日推算：已知日期直接用；超出数据范围按工作日外推（不含节假日，界面标注“约”）
  function dateAt(bars, idx) {
    if (idx < bars.length) return bars[Math.max(0, idx)].date;
    let d = new Date(bars[bars.length - 1].date + 'T00:00:00Z'), k = idx - (bars.length - 1);
    while (k > 0) { d = new Date(d.getTime() + 86400000); const w = d.getUTCDay(); if (w !== 0 && w !== 6) k--; }
    return d.toISOString().slice(0, 10);
  }
  CP.dateAt = dateAt;

  /* =====================================================================
     顶部引擎
     ===================================================================== */
  CP.WIN = (() => { const w = []; for (let n = 30; n < 200; n += 10) w.push(n); for (let n = 200; n <= 700; n += 25) w.push(n); return w; })();
  const TOP_OPT = { pop: 18, gens: 28, nm: 50, power: false, aheadLo: 1, aheadHi: 120, mLo: 0.05, mHi: 0.99, wLo: 3, wHi: 16 };
  CP.TOP_RULE = 'B<0；0.1≤m≤0.95；4≤ω≤15；1≤距今≤115 日；振荡数≥1.5；阻尼≥0.3；R²≥0.8';
  function qualifyTop(f) {
    return f.B < 0 && f.m >= 0.1 && f.m <= 0.95 && f.w >= 4 && f.w <= 15 && f.ahead >= 1 && f.ahead <= 115 && f.O >= 1.5 && f.D >= 0.3 && f.R2 >= 0.8;
  }

  function clusterTc(ok, total) {
    if (!ok.length) return [];
    const dens = new Float64Array(122);
    for (let a = 1; a <= 120; a++) {
      let s = 0;
      for (const f of ok) { const d = (a - f.ahead) / Math.max(3, 0.12 * f.ahead); s += Math.exp(-0.5 * d * d); }
      dens[a] = s;
    }
    const peaks = [];
    for (let a = 1; a <= 120; a++) if (dens[a] >= dens[a - 1] && dens[a] > dens[a + 1] && dens[a] >= 0.8) peaks.push(a);
    const cl = peaks.map((p) => ({ p, m: [] }));
    for (const f of ok) {
      let b = null, bd = Infinity;
      for (const c of cl) { const d = Math.abs(f.ahead - c.p); if (d < bd) { bd = d; b = c; } }
      if (b) b.m.push(f);
    }
    return cl.filter((c) => c.m.length).map((c) => {
      const a = c.m.map((f) => f.ahead);
      return {
        n: c.m.length, conf: c.m.length / total,
        lo: Math.max(1, Math.floor(q(a, 0.1)) - 2), hi: Math.ceil(q(a, 0.9)) + 2, mid: Math.round(q(a, 0.5)),
        wins: c.m.map((f) => f.n).sort((x, y) => x - y),
      };
    }).sort((x, y) => y.n - x.n || x.mid - y.mid);
  }

  // 窗口集合：固定尺度 + “锚定窗口”（以截止日前已确认的最近两个波段低点为泡沫起点，
  // 起点在低点前 4 日到低点后 12 日之间滑动）。Sornette 体系里泡沫起点 t1 本来就应当
  // 落在上一轮低点附近；锚定窗口让 15–40 日的短泡沫也能被捕获。
  CP.windowsAt = function (logp, T) {
    const set = new Set(CP.WIN.filter((n) => n <= T + 1));
    const close = logp.map(Math.exp);
    const lo = Math.max(0, T - 900);
    const sub = close.slice(lo, T + 1);
    const thr = CP.zzThreshold(close, T);
    const bots = CP.zigzag(sub, sub.length - 1, thr).filter((e) => e.type === 'bot').slice(-2);
    const anch = [];
    for (const b of bots) {
      const i = b.i + lo;
      for (let off = -4; off <= 12; off += 2) { const n = T - (i + off) + 1; if (n >= 15 && n <= T + 1) { set.add(n); anch.push(n); } }
    }
    return { wins: Array.from(set).sort((a, b) => a - b), anchors: anch, bots: bots.map((b) => b.i + lo) };
  };
  // 在截止日 T（含）做一次顶部扫描。只使用 logp[0..T]
  CP.topScan = function (logp, T, opt) {
    opt = opt || {};
    const rnd = OD.rng(1000003 + T * 7);
    const o = { ...TOP_OPT, ...(opt.fit || {}) };
    const W = CP.windowsAt(logp, T), wins = W.wins;
    const fits = [];
    for (const n of wins) {
      const f = OD._fitWindow(logp.slice(T + 1 - n, T + 1), o, rnd);
      f.q = qualifyTop(f);
      delete f._ws;
      fits.push(f);
    }
    const ok = fits.filter((f) => f.q);
    const clusters = clusterTc(ok, wins.length);
    return { T, total: wins.length, nq: ok.length, conf: wins.length ? ok.length / wins.length : 0, clusters, fits, anchors: W.bots };
  };
  CP.topScanAsync = async function (logp, T, opt, onTick) {
    const o = { ...TOP_OPT, ...((opt && opt.fit) || {}) };
    const rnd = OD.rng(1000003 + T * 7);
    const W = CP.windowsAt(logp, T), wins = W.wins;
    const fits = [];
    for (let i = 0; i < wins.length; i++) {
      const f = OD._fitWindow(logp.slice(T + 1 - wins[i], T + 1), o, rnd);
      f.q = qualifyTop(f);
      delete f._ws;
      fits.push(f);
      if (onTick) { onTick(i + 1, wins.length); if (i % 3 === 2) await yieldUI(); }
    }
    const ok = fits.filter((f) => f.q);
    return { T, total: wins.length, nq: ok.length, conf: wins.length ? ok.length / wins.length : 0, clusters: clusterTc(ok, wins.length), fits, anchors: W.bots };
  };
  // 信号带：每 step 个交易日一次扫描的精简记录
  CP.tapeEntry = function (s) {
    const c = s.clusters;
    const pick = (x) => x ? [x.lo, x.hi, x.mid, x.n] : null;
    return [s.T, s.total, s.nq, pick(c[0]), pick(c[1])];
  };
  CP.buildTape = async function (logp, from, to, step, onTick) {
    const tape = [];
    const list = [];
    for (let t = to; t >= from; t -= step) list.unshift(t);
    for (let k = 0; k < list.length; k++) {
      tape.push(CP.tapeEntry(CP.topScan(logp, list[k])));
      if (onTick) { onTick(k + 1, list.length); await yieldUI(); }
    }
    return tape;
  };

  /* =====================================================================
     历史转折事件（ZigZag）：只用于统计分布与事后评估
     ===================================================================== */
  CP.zigzag = function (close, T, thr) {
    const ev = [];
    let dir = 0, ext = 0, extI = 0, lastI = 0;
    ext = close[0];
    for (let i = 1; i <= T; i++) {
      const c = close[i];
      if (dir >= 0) {
        if (c > ext) { ext = c; extI = i; }
        else if (c <= ext * (1 - thr)) { if (dir === 1 || ev.length === 0) ev.push({ type: 'top', i: extI, p: ext }); dir = -1; ext = c; extI = i; }
      }
      if (dir === -1) {
        if (c < ext) { ext = c; extI = i; }
        else if (c >= ext * (1 + thr)) { ev.push({ type: 'bot', i: extI, p: ext }); dir = 1; ext = c; extI = i; }
      }
      if (dir === 0 && c < close[lastI] * (1 - thr)) dir = -1;
    }
    return ev;
  };
  CP.zzThreshold = function (close, T) {
    const s = sigmaAt(close, T, Math.min(T, 2000));
    return Math.min(0.3, Math.max(0.06, 1.6 * s * Math.sqrt(20)));
  };
  // 截止日之前已经完成的“顶 → 底”样本：回撤幅度、时长、反弹比例
  CP.crashStats = function (close, T) {
    const thr = CP.zzThreshold(close, T);
    const ev = CP.zigzag(close, T, thr);
    const legs = [];
    for (let k = 0; k + 1 < ev.length; k++) {
      if (ev[k].type !== 'top' || ev[k + 1].type !== 'bot') continue;
      const tp = ev[k], bt = ev[k + 1];
      if (bt.i - tp.i > 160) continue;
      let reb = bt.p;
      for (let i = bt.i + 1; i <= Math.min(T, bt.i + 60); i++) reb = Math.max(reb, close[i]);
      legs.push({ top: tp.i, bot: bt.i, depth: 1 - bt.p / tp.p, days: bt.i - tp.i, rebound: (reb - bt.p) / (tp.p - bt.p) });
    }
    const recent = legs.slice(-24);
    const d = recent.map((l) => l.depth), t = recent.map((l) => l.days), r = recent.map((l) => l.rebound);
    return {
      thr, n: recent.length, legs: recent,
      depth: [q(d, 0.25), q(d, 0.5), q(d, 0.75)], days: [q(t, 0.25), q(t, 0.5), q(t, 0.75)], rebound: [q(r, 0.25), q(r, 0.5), q(r, 0.75)],
    };
  };

  /* =====================================================================
     底部引擎：多条件共振
     ===================================================================== */
  // ctx：{ bars, close, T, peakI, sigma }，只用 [0..T]
  CP.bottomCheck = function (bars, T, peakI, opt) {
    opt = opt || {};
    const close = bars.map((b) => b.close);
    const s = sigmaAt(close, peakI, 60);
    let lowI = peakI;
    for (let i = peakI; i <= T; i++) if (close[i] < close[lowI]) lowI = i;
    const dd = 1 - close[lowI] / close[peakI];
    const ddNow = 1 - close[T] / close[peakI];
    let panic = 0;
    for (let i = Math.max(peakI + 1, T - 12); i <= T; i++) { const r = Math.log(close[i] / close[i - 1]); if (r <= -2.2 * s) panic++; }
    let rv = 0, nrv = 0;
    for (let i = Math.max(1, T - 4); i <= T; i++) { rv += Math.log(close[i] / close[i - 1]) ** 2; nrv++; }
    rv = Math.sqrt(rv / Math.max(1, nrv));
    const items = [];
    items.push({ k: 'depth', name: '跌幅到位', need: true, ok: dd >= 2.5 * s * Math.sqrt(10), detail: '自高点回撤 ' + (dd * 100).toFixed(1) + '%，门槛 ' + (2.5 * s * Math.sqrt(10) * 100).toFixed(1) + '%' });
    items.push({ k: 'time', name: '时间到位', need: true, ok: T - peakI >= 10, detail: '已调整 ' + (T - peakI) + ' 个交易日，门槛 10 日' });
    items.push({ k: 'panic', name: '恐慌释放', need: false, ok: panic >= 1 && rv < 1.6 * s, detail: panic ? '近 12 日出现 ' + panic + ' 次 ≥2.2σ 的急跌，' + (rv < 1.6 * s ? '波动已回落' : '波动尚未回落') : '尚未出现恐慌性急跌' });
    items.push({ k: 'turn', name: '止跌企稳', need: true, ok: T - lowI >= 2 && close[T] >= close[lowI] * (1 + s), detail: T - lowI >= 2 ? '低点已过 ' + (T - lowI) + ' 日，较低点 ' + ((close[T] / close[lowI] - 1) * 100).toFixed(1) + '%' : '仍在创新低' });
    let well = null;
    const mandOk = items.filter((x) => x.need).every((x) => x.ok);
    if (!mandOk && !opt.full) {
      items.push({ k: 'well', name: '落入支撑井', need: false, ok: false, detail: '必要条件未满足，暂不评估' });
      items.push({ k: 'anti', name: '反泡沫结构', need: false, ok: false, detail: '必要条件未满足，暂不评估' });
      return { items, score: items.filter((x) => x.ok).length, max: items.length, pass: false, dd, ddNow, lowI, peakI, sigma: s, well };
    }
    if (opt.ppe !== false) {
      const ppe = OD.priceLayer(bars.slice(0, T + 1));
      const lowX = Math.log(close[lowI]);
      well = ppe.wells.filter((w) => w.x < Math.log(close[peakI]) - 0.02).sort((a, b) => Math.abs(a.x - lowX) - Math.abs(b.x - lowX))[0] || null;
      items.push({ k: 'well', name: '落入支撑井', need: false, ok: !!well && Math.abs(well.x - lowX) <= Math.max(0.025, 2 * ppe.h), detail: well ? '最近支撑井 ' + well.price.toFixed(2) + '，低点距其 ' + ((close[lowI] / well.price - 1) * 100).toFixed(1) + '%' : '下方没有明显的价格密集区' });
    }
    if (opt.anti !== false && T - peakI >= 12) {
      const y = [];
      for (let i = peakI; i <= T; i++) y.push(-Math.log(close[i]));
      const rnd = OD.rng(77 + T);
      const f = OD._fitWindow(y, { pop: 14, gens: 22, nm: 40, power: false, aheadLo: 0, aheadHi: 30, mLo: 0.05, mHi: 0.99, wLo: 3, wHi: 16 }, rnd);
      const ok = f.B < 0 && f.m >= 0.1 && f.m <= 0.95 && f.w >= 4 && f.w <= 15 && f.R2 >= 0.75 && f.ahead <= 10;
      items.push({ k: 'anti', name: '反泡沫结构', need: false, ok, detail: ok ? '下跌段呈加速衰竭结构，临界点约在 ' + Math.max(0, Math.round(f.ahead)) + ' 日内' : '下跌段未呈现合格的衰竭结构' });
    }
    const score = items.filter((x) => x.ok).length;
    const mand = items.filter((x) => x.need).every((x) => x.ok);
    return { items, score, max: items.length, pass: mand && score >= 4, dd, ddNow, lowI, peakI, sigma: s, well };
  };

  /* =====================================================================
     截止日路线图：见顶窗口 → 回撤分布 → 底部区间 → 二波
     ===================================================================== */
  CP.roadmap = function (bars, T, scan) {
    const close = bars.map((b) => b.close);
    const st = CP.crashStats(close, T);
    const s = sigmaAt(close, T, 60);
    const c0 = close[T];
    let hiI = T;
    for (let i = Math.max(0, T - 60); i <= T; i++) if (close[i] > close[hiI]) hiI = i;
    // 少于 4 个尺度、或一致度低于 6% 的聚类视为噪声，不给出见顶窗口
    const sig = scan.clusters.filter((c) => c.n >= 4 && c.conf >= 0.06);
    const main = sig[0] || null, alt = sig[1] || null;
    const conf = main ? main.conf : 0;
    let level = 'none';
    if (main && conf >= 0.15) level = conf >= 0.3 ? 'high' : 'mid';
    else if (main) level = 'low';
    const mk = (c) => c && {
      lo: T + c.lo, hi: T + c.hi, mid: T + c.mid, n: c.n, conf: c.conf,
      loDate: dateAt(bars, T + c.lo), hiDate: dateAt(bars, T + c.hi), midDate: dateAt(bars, T + c.mid), wins: c.wins,
    };
    const topW = mk(main), altW = mk(alt);
    // 顶部价格：按当前波动给出到达窗口中点时的 1σ 区间（不是目标价）
    let topPx = null;
    if (topW) {
      const h = Math.max(1, topW.mid - T), sd = s * Math.sqrt(h);
      const drift = Math.max(0, Math.log(c0 / close[Math.max(0, T - 20)]) / 20) * h * 0.5;
      topPx = [c0 * Math.exp(drift - 0.5 * sd), c0 * Math.exp(drift + sd)];
      topPx[0] = Math.max(topPx[0], c0 * 0.98);
    }
    let crash = null;
    if (topW && st.n >= 3) {
      const ref = topPx ? Math.sqrt(topPx[0] * topPx[1]) : c0;
      crash = {
        depth: st.depth, days: st.days, rebound: st.rebound, n: st.n,
        botLo: topW.mid + Math.round(st.days[0]), botHi: topW.mid + Math.round(st.days[2]),
        botLoDate: dateAt(bars, topW.mid + Math.round(st.days[0])), botHiDate: dateAt(bars, topW.mid + Math.round(st.days[2])),
        pxHi: ref * (1 - st.depth[0]), pxLo: ref * (1 - st.depth[2]), pxMid: ref * (1 - st.depth[1]), ref,
      };
      crash.wave2 = crash.pxMid + st.rebound[1] * (ref - crash.pxMid);
    }
    const ppe = OD.priceLayer(bars.slice(0, T + 1));
    const wellsBelow = ppe.wells.filter((w) => w.x < Math.log(c0) - 0.02).sort((a, b) => b.x - a.x).slice(0, 2);
    return { T, date: bars[T].date, close: c0, sigma: s, scan, topW, altW, conf, level, topPx, crash, stats: st, wellsBelow, hi60: close[hiI], hi60I: hiI };
  };

  /* =====================================================================
     策略执行（规则事前固定）
     ---------------------------------------------------------------------
     从满仓开始，逐日推进（决策用当日收盘信息，次日开盘成交）：
       1. 顶部预警：最近一次扫描的主窗口一致度 ≥ 15%，且窗口起点在 10 个交易日内
          → 次日减仓一半；剩余一半用移动止盈（自预警后最高收盘回落 1.5σ√3）退出
       2. 预警窗口结束 5 日后仍未破位、且价格高于减仓价 → 视为误报，买回
       3. 破裂：自 60 日高点回撤 ≥ 2σ√10 → 进入底部监测
       4. 底部共振通过 → 第一批 1/3；较首批价上涨 σ√5 或 5 日不破低 → 第二批 1/3；
          收复跌幅一半 → 第三批 1/3（进入二波）
       5. 进场后收盘跌破调整低点 1.5σ → 全部止损，重新监测
     成本：佣金 2.5‱（双边）、印花税 5‱（卖出）、滑点 5‱（双边）
     ===================================================================== */
  CP.RULES = {
    alertConf: 0.15, alertLead: 10, firstCut: 0.5, trail: 1.5, falseAlarmDays: 5,
    crashK: 2.0, comm: 0.00025, stamp: 0.0005, slip: 0.0005,
  };
  function scanAt(tape, d) {
    let lo = 0, hi = tape.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (tape[m][0] <= d) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans >= 0 ? tape[ans] : null;
  }
  CP.scanAt = scanAt;

  CP.simulate = function (bars, tape, from, to, opt) {
    opt = opt || {};
    const R = { ...CP.RULES, ...(opt.rules || {}) };
    const close = bars.map((b) => b.close);
    to = Math.min(to, bars.length - 1);
    let cash = 0, sh = 1 / bars[from].close, pos = 1;
    const eq = [], bh = [], phase = [], acts = [];
    let pending = null;
    let st = 'hold', alert = null, trailMax = 0, cutPx = 0, peakI = -1, tranche = 0, entry1 = 0, entryI = -1, lowRef = 0, crashLow = 0;
    const s0 = bars[from].close;
    const setPos = (target, d, why) => { pending = { target, why, d }; };
    for (let d = from; d <= to; d++) {
      const b = bars[d];
      if (pending && d > pending.d) {
        const px = b.open;
        const val = cash + sh * px;
        const want = pending.target;
        if (want < pos - 1e-9) {
          const sell = sh * (1 - want / pos);
          const got = sell * px * (1 - R.slip) * (1 - R.comm - R.stamp);
          cash += got; sh -= sell;
        } else if (want > pos + 1e-9) {
          const spend = Math.min(cash, val * (want - pos));
          sh += (spend * (1 - R.comm)) / (px * (1 + R.slip)); cash -= spend;
        }
        acts.push({ i: d, date: b.date, px, from: pos, to: want, why: pending.why });
        pos = want; pending = null;
      }
      eq.push(cash + sh * b.close); bh.push(b.close / s0);
      const s = sigmaAt(close, d, 60);
      const tp = scanAt(tape, d);
      const c1 = tp && tp[3];
      const conf1 = c1 ? c1[3] / tp[1] : 0;
      const winLo = c1 ? tp[0] + c1[0] : -1, winHi = c1 ? tp[0] + c1[1] : -1;
      const alertNow = c1 && conf1 >= R.alertConf && winLo - d <= R.alertLead && winHi >= d;
      let hiI = d;
      for (let i = Math.max(0, d - 60); i <= d; i++) if (close[i] > close[hiI]) hiI = i;
      const ddHi = 1 - close[d] / close[hiI];
      const crashNow = ddHi >= R.crashK * s * Math.sqrt(10);
      if (pending) { phase.push(st); continue; }
      if (st === 'hold' || st === 'wave2') {
        if (alertNow && pos > 0) {
          alert = { d, winLo, winHi, conf: conf1 }; trailMax = close[d]; cutPx = close[d];
          st = 'alert'; setPos(pos * (1 - R.firstCut), d, '顶部预警：减仓一半');
        } else if (crashNow && pos > 0 && st === 'hold') {
          st = 'crash'; peakI = hiI; setPos(0, d, '已破位：清仓等待底部'); tranche = 0;
        }
      } else if (st === 'alert') {
        trailMax = Math.max(trailMax, close[d]);
        if (close[d] <= trailMax * Math.exp(-R.trail * s * Math.sqrt(3))) {
          st = 'crash'; peakI = hiI; tranche = 0; setPos(0, d, '跌破移动止盈：清仓');
        } else if (d > alert.winHi + R.falseAlarmDays && close[d] > cutPx && !crashNow) {
          st = 'hold'; setPos(1, d, '窗口过后未破位：误报买回');
        }
      } else if (st === 'crash' || st === 'base') {
        if (peakI < 0) peakI = hiI;
        if (st === 'crash') {
          if (close[d] > close[peakI]) { st = 'hold'; setPos(1, d, '收复前高：恢复持仓'); }
          else if (d - peakI >= 10) {
            const chk = CP.bottomCheck(bars, d, peakI, { ppe: opt.ppe !== false, anti: opt.anti !== false });
            if (chk.pass) { st = 'base'; tranche = 1; entry1 = close[d]; entryI = d; crashLow = close[chk.lowI]; lowRef = close[peakI]; setPos(1 / 3, d, '底部共振：第一批 1/3'); }
          }
        } else {
          const sNow = s;
          if (close[d] < crashLow * Math.exp(-1.5 * sNow)) { st = 'crash'; tranche = 0; setPos(0, d, '跌破调整低点：止损'); }
          else if (tranche === 1 && (close[d] >= entry1 * Math.exp(sNow * Math.sqrt(5)) || d - entryI >= 5)) { tranche = 2; setPos(2 / 3, d, '底部确认：第二批 1/3'); }
          else if (tranche === 2 && close[d] >= crashLow + 0.5 * (lowRef - crashLow)) { tranche = 3; st = 'wave2'; setPos(1, d, '收复一半跌幅：第三批，进入二波'); }
        }
      }
      phase.push(st);
    }
    const mdd = (x) => { let pk = -Infinity, m = 0; x.forEach((v) => { pk = Math.max(pk, v); m = Math.max(m, 1 - v / pk); }); return m; };
    return {
      from, to, eq, bh, phase, acts,
      ret: eq[eq.length - 1] - 1, bhRet: bh[bh.length - 1] - 1, mdd: mdd(eq), bhMdd: mdd(bh),
      dates: bars.slice(from, to + 1).map((b) => b.date), state: st, pos,
    };
  };

  /* =====================================================================
     命中评估：用全部数据的真实转折检验顶部窗口（仅用于事后打分）
     ===================================================================== */
  CP.evaluate = function (bars, tape) {
    const close = bars.map((b) => b.close);
    const N = close.length;
    const thr = CP.zzThreshold(close, N - 1);
    const ev = CP.zigzag(close, N - 1, thr).filter((e) => e.type === 'top' && e.i >= tape[0][0] + 10);
    const alerts = [];
    for (const tp of tape) {
      const c = tp[3];
      if (!c || c[3] / tp[1] < CP.RULES.alertConf) continue;
      alerts.push({ t: tp[0], lo: tp[0] + c[0], hi: tp[0] + c[1], conf: c[3] / tp[1] });
    }
    // 合并重叠的预警为一次“预警段”
    const eps = [];
    for (const a of alerts) {
      const last = eps[eps.length - 1];
      if (last && a.lo <= last.hi + 5) { last.hi = Math.max(last.hi, a.hi); last.n++; last.conf = Math.max(last.conf, a.conf); }
      else eps.push({ start: a.t, lo: a.lo, hi: a.hi, n: 1, conf: a.conf });
    }
    const tol = 5;
    let hitEv = 0;
    const errs = [];
    ev.forEach((e) => {
      const ok = alerts.filter((a) => a.t < e.i && e.i - a.t <= 60 && e.i >= a.lo - tol && e.i <= a.hi + tol);
      e.hit = ok.length > 0;
      if (e.hit) { hitEv++; errs.push(Math.min(...ok.map((a) => Math.abs(e.i - (a.lo + a.hi) / 2)))); }
    });
    let goodEp = 0;
    eps.forEach((p) => {
      const near = ev.some((e) => e.i >= p.lo - tol && e.i <= p.hi + tol);
      let mx = p.lo;
      for (let i = Math.max(0, p.lo - tol); i <= Math.min(N - 1, p.hi + tol); i++) if (close[i] > close[mx]) mx = i;
      let mn = close[mx];
      for (let i = mx; i <= Math.min(N - 1, mx + 40); i++) mn = Math.min(mn, close[i]);
      p.drop = 1 - mn / close[mx];
      p.good = near || p.drop >= thr * 0.75;
      if (p.good) goodEp++;
    });
    // 随机基线：同样宽度、同样数量的窗口随机放置时命中一个真实顶部的概率
    const span = tape[tape.length - 1][0] - tape[0][0];
    const avgW = eps.length ? eps.reduce((a, p) => a + (p.hi - p.lo + 2 * tol), 0) / eps.length : 0;
    const density = span > 0 ? ev.length / span : 0;
    const randHit = 1 - Math.exp(-density * avgW);
    return { thr, events: ev, episodes: eps, recall: ev.length ? hitEv / ev.length : NaN, precision: eps.length ? goodEp / eps.length : NaN, randPrecision: randHit, medErr: errs.length ? q(errs, 0.5) : NaN, nEv: ev.length, nEp: eps.length };
  };

  /* ---------------- 白话解读 ---------------- */
  CP.PHASES = [
    { k: 'acc', name: '积累', tip: '没有临界结构，趋势平稳' },
    { k: 'accel', name: '加速', tip: '上涨在加速，开始出现泡沫结构' },
    { k: 'crit', name: '临界', tip: '多个尺度指向同一见顶窗口' },
    { k: 'crash', name: '破裂', tip: '泡沫破裂，回撤进行中' },
    { k: 'base', name: '筑底', tip: '底部条件共振，分批进场' },
    { k: 'wave2', name: '二波', tip: '收复一半跌幅，持有第二波' },
  ];
  CP.phaseNow = function (bars, T, rm) {
    const close = bars.map((b) => b.close);
    const s = rm.sigma;
    const ddHi = 1 - close[T] / rm.hi60;
    if (ddHi >= 2 * s * Math.sqrt(10)) {
      const chk = CP.bottomCheck(bars, T, rm.hi60I, { full: true });
      if (chk.pass) {
        const recov = (close[T] - close[chk.lowI]) / (rm.hi60 - close[chk.lowI]);
        return { k: recov >= 0.5 ? 'wave2' : 'base', chk };
      }
      return { k: 'crash', chk };
    }
    if (rm.topW && rm.conf >= 0.15 && rm.topW.lo - T <= 10) return { k: 'crit' };
    const r60 = Math.log(close[T] / close[Math.max(0, T - 60)]);
    if ((rm.topW && rm.conf >= 0.08) || r60 > 1.5 * s * Math.sqrt(60)) return { k: 'accel' };
    return { k: 'acc' };
  };

  /* =====================================================================
     回放：截止日之后的真实走势（只用于打分，不参与预测）
     ===================================================================== */
  CP.replay = function (bars, T, rm, tape) {
    const N = bars.length, close = bars.map((b) => b.close);
    if (T >= N - 3) return null;
    const H = Math.min(N - 1, T + 120);
    // 用全样本 ZigZag 找截止日之后的第一个真实顶部 → 随后的底部 → 第二波高点
    const zz = CP.zigzag(close, N - 1, CP.zzThreshold(close, T));
    let k0 = zz.findIndex((e) => e.type === 'top' && e.i >= T - 2);
    let pk, bt, w2;
    if (k0 >= 0 && zz[k0].i - T <= 80) {
      pk = Math.max(T, zz[k0].i);
      const nb = zz[k0 + 1], nt = zz[k0 + 2];
      bt = nb ? nb.i : pk;
      if (!nb) for (let i = pk; i <= N - 1; i++) if (close[i] < close[bt]) bt = i;
      w2 = nt ? nt.i : bt;
      if (!nt) for (let i = bt; i <= Math.min(N - 1, bt + 60); i++) if (close[i] > close[w2]) w2 = i;
    } else {
      pk = T;
      for (let i = T; i <= Math.min(N - 1, T + 60); i++) if (close[i] > close[pk]) pk = i;
      bt = pk;
      for (let i = pk; i <= Math.min(N - 1, pk + 60); i++) if (close[i] < close[bt]) bt = i;
      w2 = bt;
      for (let i = bt; i <= Math.min(N - 1, bt + 60); i++) if (close[i] > close[w2]) w2 = i;
    }
    const out = {
      T, end: H, peak: { i: pk, date: bars[pk].date, px: close[pk], gain: close[pk] / close[T] - 1 },
      bottom: { i: bt, date: bars[bt].date, px: close[bt], dd: 1 - close[bt] / close[pk] },
      wave2: { i: w2, date: bars[w2].date, px: close[w2], gain: close[w2] / close[bt] - 1 },
    };
    if (rm.topW) {
      out.topHit = pk >= rm.topW.lo - 3 && pk <= rm.topW.hi + 3;
      out.topErr = pk < rm.topW.lo ? pk - rm.topW.lo : pk > rm.topW.hi ? pk - rm.topW.hi : 0;
    }
    if (rm.crash) {
      out.botTimeHit = bt >= rm.crash.botLo - 3 && bt <= rm.crash.botHi + 3;
      out.botPxHit = close[bt] >= rm.crash.pxLo * 0.98 && close[bt] <= rm.crash.pxHi * 1.02;
    }
    // 截止日之后，模型最早何时指向真实顶部（信号带回看）
    if (tape) {
      const after = tape.filter((e) => e[0] > T && e[0] <= pk);
      for (const e of after) {
        const c = e[3];
        if (c && c[3] >= 4 && pk >= e[0] + c[0] - 3 && pk <= e[0] + c[1] + 3) { out.firstSig = { i: e[0], date: bars[e[0]].date, conf: c[3] / e[1], lead: pk - e[0] }; break; }
      }
    }
    out.sim = CP.simulate(bars, tape, T, H, {});
    return out;
  };

  /* =====================================================================
     总流程
     ===================================================================== */
  function idxOnOrBefore(bars, date) {
    let lo = 0, hi = bars.length - 1, a = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (bars[m].date <= date) { a = m; lo = m + 1; } else hi = m - 1; }
    return a;
  }
  CP.idxOnOrBefore = idxOnOrBefore;

  CP.run = async function (input, asof, onProg) {
    const prog = (s, p) => onProg && onProg(s, Math.max(0, Math.min(1, p)));
    const sym = CP.resolve(input);
    if (!sym) throw new Error('无法识别：请输入 6 位 A 股代码（如 600519），或“上证指数 / 沪深300 / 创业板指”。');
    prog('获取日线数据', 0.02);
    let data = await CP.load(sym, {});
    let bars = data.bars;
    const pre = G.OD_TAPE && G.OD_TAPE[sym.key];
    const snap = G.OD_SNAP && G.OD_SNAP[sym.key];
    if (sym.isIndex && snap && !data.snapshot) {
      // 与内置快照对齐起点，使预计算信号带的下标可直接复用
      const first = snap.rows.slice(0, 8);
      const d0 = first.slice(0, 4) + '-' + first.slice(4, 6) + '-' + first.slice(6, 8);
      const k = bars.findIndex((b) => b.date === d0);
      if (k > 0) bars = bars.slice(k);
    }
    const N = bars.length;
    if (N < 320) throw new Error('有效日线不足 320 根（' + N + '），无法做多尺度分析。');
    let T = asof ? idxOnOrBefore(bars, asof) : N - 1;
    if (T < 300) T = Math.min(N - 1, 300);
    const logp = bars.map((b) => Math.log(b.close));
    prog('顶部引擎：多尺度 LPPLS 扫描', 0.05);
    const scan = await CP.topScanAsync(logp, T, {}, (k, n) => prog('顶部引擎：第 ' + k + '/' + n + ' 个窗口', 0.05 + 0.3 * k / n));
    const rm = CP.roadmap(bars, T, scan);
    const phase = CP.phaseNow(bars, T, rm);
    // 信号带
    let tape = [];
    let tapeSrc = '';
    if (pre && bars[pre.n - 1] && bars[pre.n - 1].date === pre.end) {
      tape = pre.tape.slice();
      tapeSrc = '预计算（与本页同一规则，截至 ' + pre.end + '）';
      const need = [];
      for (let t = pre.tape[pre.tape.length - 1][0] + 5; t <= N - 1; t += 5) need.push(t);
      if (need[need.length - 1] !== N - 1 && N - 1 > pre.tape[pre.tape.length - 1][0]) need.push(N - 1);
      for (let k = 0; k < need.length; k++) { tape.push(CP.tapeEntry(CP.topScan(logp, need[k]))); prog('补算最新信号带 ' + (k + 1) + '/' + need.length, 0.36 + 0.5 * (k + 1) / need.length); await yieldUI(); }
      if (need.length) tapeSrc += '，并补算至 ' + bars[N - 1].date;
    } else {
      const a = Math.max(300, Math.min(T, N - 1) - 250), b = N - 1;
      const step = Math.max(5, Math.ceil((b - a) / 70));
      tape = await CP.buildTape(logp, a, b, step, (k, n) => prog('滚动验证：第 ' + k + '/' + n + ' 个截止日', 0.36 + 0.58 * k / n));
      tapeSrc = '本次实时计算（每 ' + step + ' 个交易日一个截止日）';
    }
    prog('回放与打分', 0.96);
    await yieldUI();
    const replay = CP.replay(bars, T, rm, tape);
    const evalr = CP.evaluate(bars, tape);
    const chk = phase.chk || (rm.hi60I < T ? CP.bottomCheck(bars, T, rm.hi60I, { full: true }) : null);
    prog('完成', 1);
    return { sym, data, bars, T, asof: bars[T].date, latest: T === N - 1, scan, rm, phase, chk, tape, tapeSrc, replay, evalr };
  };

  // 三个指数的整体验证（使用内置快照与预计算信号带，计算很快）
  CP.indexBench = function () {
    const out = [];
    for (const key of Object.keys(INDEX)) {
      const S = snapBars(key), pre = G.OD_TAPE && G.OD_TAPE[key];
      if (!S || !pre) continue;
      const bars = S.bars;
      const ev = CP.evaluate(bars, pre.tape);
      const i16 = idxOnOrBefore(bars, '2016-01-04') + 1, i19 = idxOnOrBefore(bars, '2019-01-02') + 1, i24 = idxOnOrBefore(bars, '2024-01-02') + 1;
      const run = (a) => { const s = CP.simulate(bars, pre.tape, a, bars.length - 1, {}); return { ret: s.ret, bh: s.bhRet, mdd: s.mdd, bhMdd: s.bhMdd }; };
      out.push({ key, label: INDEX[key].label, ev, s16: run(i16), s19: run(i19), s24: run(i24), end: bars[bars.length - 1].date, start: bars[pre.tape[0][0]].date });
    }
    return out;
  };

  G.CP = CP;
})(typeof window !== 'undefined' ? window : globalThis);
