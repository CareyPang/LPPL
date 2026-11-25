/* 根据已发布底分与顶部区间生成底部状态标签。 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.BottomAction = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const INDEX_PROFILE = {
    sh000001: { kind: 'broad', etf: '上证综指 / 红利低波 ETF', elastic: false },
    sh000016: { kind: 'broad', etf: '上证50 / 央企红利 ETF', elastic: false },
    sh000300: { kind: 'broad', etf: '沪深300 ETF（国家队压舱石）', elastic: false },
    sh000905: { kind: 'mid',   etf: '中证500 ETF（胜率最高·回撤最稳）', elastic: true },
    sz399001: { kind: 'mid',   etf: '深证成指 / 沪深300 ETF', elastic: false },
    sz399006: { kind: 'growth', etf: '创业板 ETF → 右侧切高弹性成长龙头', elastic: true },
    sh000688: { kind: 'growth', etf: '科创50 ETF → 右侧切硬科技龙头', elastic: true },
  };

  function toNum(v, fallback) {
    if (v == null || v === '' || typeof v === 'boolean') return fallback;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  /** 评估单个指数当前的顶部状态与底分档位。 */
  function evaluate(input) {
    const cfg = input || {};
    const hasTop = Boolean(cfg.hasTop);
    const rawScore = toNum(cfg.score, null);
    const score = rawScore == null ? null : rawScore > 0 && rawScore <= 1 ? rawScore * 100 : rawScore;

    if (hasTop) {
      return {
        tier: 'top_risk',
        tone: 'red',
        glyph: '🔴',
        positionLabel: '顶部区间内 · 不抄底',
        canBuy: false,
        canBuyLabel: '查看顶部区间和价格变化。',
        targetPct: null,
        positionText: '',
        shortBadge: '顶部区间内 · 不抄底',
        vehicle: '查看顶部区间和价格变化。',
        reason: '当前仍有顶部区间。',
        score: score,
      };
    }

    if (score == null) {
      return {
        tier: 'unavailable',
        tone: 'gray',
        glyph: '—',
        positionLabel: '底分未覆盖',
        canBuy: false,
        canBuyLabel: '等待底分记录。',
        targetPct: null,
        positionText: '',
        shortBadge: '底分未覆盖',
        vehicle: '查看已有行情和顶部区间。',
        reason: '当前结果没有可核对的已发布底分。',
        score: null,
      };
    }

    if (score < 30) {
      return {
        tier: 'neutral',
        tone: 'gray',
        glyph: '⚪',
        positionLabel: '暂不进场',
        canBuy: false,
        canBuyLabel: '等待底分回到 30 分以上。',
        targetPct: null,
        positionText: '',
        shortBadge: '暂不进场',
        vehicle: '等待底分回到 30 分以上。',
        reason: '底分低于 30 分：历史同档价格多在区间中上部，最终低点通常还要再过约 3 个月。',
        score: score,
      };
    }

    if (score < 50) {
      return {
        tier: 'bottom_watch',
        tone: 'amber',
        glyph: '🟡',
        positionLabel: '底部观察',
        canBuy: false,
        canBuyLabel: '跟踪底分能否达到 50 分。',
        targetPct: null,
        positionText: '',
        shortBadge: '底部观察',
        vehicle: '跟踪底分变化。',
        reason: '底分 30–49 分：历史同档表现与随机回撤周接近。',
        score: score,
      };
    }

    return {
      tier: 'bottom_probe',
      tone: 'green',
      glyph: '🟢',
      positionLabel: '底部附近',
      canBuy: true,
      canBuyLabel: '冷却、止跌与企稳分项作参考，不作为进场条件。',
      targetPct: null,
      positionText: '',
      shortBadge: '底部附近',
      vehicle: '查看历史同档表现与分项信息。',
      reason: '底分 ≥50：历史同档比随机回撤周更靠近底部，价格距前后半年最低点中位约 10–14%。',
      score: score,
    };
  }

  /** Compatibility shape for existing cards; all decisions come from one published view. */
  function fromDecision(view) {
    if (!view || !view.conclusion) return null;
    const c = view.conclusion, b = view.bottom || {}, top = view.top || {};
    const tier = c.status === 'top_watch' ? 'top_risk'
      : ['bottom_probe', 'bottom_watch', 'neutral'].includes(c.status) ? c.status : 'unavailable';
    const toneMap = { risk: 'red', danger: 'red', warning: 'amber', warn: 'amber', success: 'green',
      teal: 'green', positive: 'green', muted: 'gray', neutral: 'gray' };
    const tone = toneMap[c.tone] || c.tone || 'gray';
    const glyph = ({ red: '🔴', amber: '🟡', green: '🟢', emerald: '🟢', blue: '🔵', gray: '⚪' })[tone] || '•';
    return { tier, tone, glyph, score: b.score == null ? null : b.score,
      scoreAsOf: b.asof || '', scoreStale: !!b.stale,
      positionLabel: c.title, positionText: b.stale ? '底分待更新' : top.status === 'active' ? '查看时间区间' : '',
      canBuy: c.status === 'bottom_probe', canBuyLabel: c.next || c.detail || '',
      shortBadge: c.title, targetPct: null, vehicle: c.next || '', reason: c.detail || '',
      decisionStatus: c.status };
  }

  /** 从 *_history.json 直接提取最新一帧并评估 */
  function fromHistory(sym, hist, opts) {
    const frames = (hist && Array.isArray(hist.frames)) ? hist.frames : [];
    const last = frames.length ? frames[frames.length - 1] : null;
    if (!last) return evaluate({ sym, ...(opts || {}) });
    const w6 = last.w && last.w['6-12m'];
    const hasTop = Boolean((opts && opts.hasTop) || (Array.isArray(w6) && w6.length === 2 && w6[0]));
    return evaluate({
      sym,
      hasTop,
      score: last.fco_neg_intensity != null ? last.fco_neg_intensity : null,
      factors: last.bottom_factors || null,
      summary: hist.bottom_summary || null,
      omoriRed: Boolean(opts && opts.omoriRed),
    });
  }

  /** 从 overview_latest.json 中的单条指数摘要直接评估（免下载完整历史帧） */
  function fromOverviewItem(item, opts) {
    if (!item) return evaluate(opts || {});
    return evaluate({
      sym: item.sym,
      hasTop: Boolean((opts && opts.hasTop) || item.has_top),
      score: item.bottom_score != null ? item.bottom_score : (item.fco_neg_intensity != null ? item.fco_neg_intensity : null),
      factors: item.bottom_factors || null,
      summary: item.bottom_summary || null,
      omoriRed: Boolean(opts && opts.omoriRed),
    });
  }

  /**
   * 价格层物理微观结构评估（严格 PIT，与 research/price_layer/physics_price.py 同源）：
   * 基于 ≤asof 的日线 OHLCV 计算：
   * 1) 自由能筹码势阱（500日时间衰减+成交量加权 KDE，高自由能+下方无旧势阱 = 跌穿套牢区进入出清真空区）
   * 2) 250日筹码均价折价率（vwap_gap）
   * 3) OBV 20日量价底背离（obv_div）
   * 4) Amihud 流动性枯竭比（amihud_ratio）
   * 明确剔除未通过 2019+ 样本外检验的排列信息熵与 DFA 权重。
   */
  function evaluatePricePhysics(prices) {
    const bars = Array.isArray(prices)
      ? prices.filter((b) => b && Number.isFinite(Number(b.close)) && Number(b.close) > 0)
      : [];
    if (bars.length < 120) return null;
    const n = bars.length;
    const c = bars.map((b) => Number(b.close));
    const h = bars.map((b) => Number.isFinite(Number(b.high)) && Number(b.high) > 0 ? Number(b.high) : Number(b.close));
    const l = bars.map((b) => Number.isFinite(Number(b.low)) && Number(b.low) > 0 ? Number(b.low) : Number(b.close));
    const v = bars.map((b) => Number.isFinite(Number(b.volume)) && Number(b.volume) > 0 ? Number(b.volume) : 1);

    // 1) 500日时间衰减 + 成交量加权 KDE 自由能势阱
    const wLen = Math.min(n, 500);
    const start = n - wLen;
    const x = [], r2 = [], vol = [];
    for (let i = start; i < n; i += 1) {
      x.push(Math.log((h[i] + l[i] + c[i]) / 3));
      const hl = Math.log(Math.max(h[i], 1e-12)) - Math.log(Math.max(l[i], 1e-12));
      r2.push((hl * hl) / 12);
      vol.push(v[i]);
    }
    const sortedV = vol.slice().sort((a, b) => a - b);
    const vmed = sortedV[Math.floor(sortedV.length / 2)] || 1;
    const w = [];
    let wSum = 0, wSqSum = 0, mu = 0;
    for (let i = 0; i < wLen; i += 1) {
      const age = wLen - 1 - i;
      const vw = Math.max(0.2, Math.min(5.0, Math.sqrt(vol[i] / vmed)));
      const wi = Math.pow(2, -age / 120) * vw;
      w.push(wi);
      wSum += wi;
      wSqSum += wi * wi;
      mu += wi * x[i];
    }
    mu /= wSum || 1;
    let varX = 0;
    for (let i = 0; i < wLen; i += 1) varX += w[i] * (x[i] - mu) * (x[i] - mu);
    const sd = Math.sqrt(varX / (wSum || 1));
    const neff = (wSum * wSum) / (wSqSum || 1);
    const h0 = Math.max(0.006, 0.5 * 1.06 * sd * Math.pow(neff, -0.2));
    const xMin = Math.min(...x) - 4 * h0;
    const xMax = Math.max(...x) + 4 * h0;
    const GRID = 80;
    const dx = (xMax - xMin) / (GRID - 1) || 1e-6;
    const rho = new Array(GRID).fill(0);
    for (let i = 0; i < wLen; i += 1) {
      const sig2 = h0 * h0 + r2[i];
      const invSig = w[i] / Math.sqrt(sig2);
      for (let g = 0; g < GRID; g += 1) {
        const gx = xMin + g * dx;
        const d2 = ((gx - x[i]) * (gx - x[i])) / (2 * sig2);
        if (d2 < 18) rho[g] += invSig * Math.exp(-d2);
      }
    }
    let area = 0;
    for (let g = 0; g < GRID; g += 1) area += rho[g] * dx;
    const F = rho.map((val) => -Math.log(val / Math.max(area, 1e-300) + 1e-12));
    const fMin = Math.min(...F);
    for (let g = 0; g < GRID; g += 1) F[g] -= fMin;

    const xNow = Math.log(c[n - 1]);
    const gNow = Math.max(0, Math.min(GRID - 1, Math.round((xNow - xMin) / dx)));
    const wellF = F[gNow];
    let hasWellBelow = false;
    for (let g = 1; g < GRID - 1; g += 1) {
      if (F[g] < F[g - 1] && F[g] <= F[g + 1]) {
        const gx = xMin + g * dx;
        if (gx < xNow - 0.03 && F[g] < wellF - 0.04) hasWellBelow = true;
      }
    }
    const noWellBelow = !hasWellBelow;

    // 2) 250日筹码均价折价率
    const vLen = Math.min(n, 250);
    let pvSum = 0, vSum250 = 0;
    for (let i = n - vLen; i < n; i += 1) {
      pvSum += c[i] * v[i];
      vSum250 += v[i];
    }
    const vwap250 = vSum250 > 0 ? pvSum / vSum250 : c[n - 1];
    const vwapGap = c[n - 1] / vwap250 - 1;

    // 3) OBV 20日量价底背离
    const r = [0];
    const obv = [0];
    for (let i = 1; i < n; i += 1) {
      r.push(Math.log(c[i] / c[i - 1]));
      const s = c[i] > c[i - 1] ? 1 : (c[i] < c[i - 1] ? -1 : 0);
      obv.push(obv[i - 1] + s * v[i]);
    }
    const stdArr = (arr) => {
      if (arr.length < 2) return 0;
      const m = arr.reduce((a, b) => a + b, 0) / arr.length;
      const vr = arr.reduce((a, b) => a + (b - m) * (b - m), 0) / arr.length;
      return Math.sqrt(vr);
    };
    const obvDiffs = [];
    for (let i = Math.max(1, n - 120); i < n; i += 1) obvDiffs.push(obv[i] - obv[i - 1]);
    const obvStd = stdArr(obvDiffs) * Math.sqrt(20) + 1e-12;
    const pxStd = stdArr(r.slice(Math.max(1, n - 120))) * Math.sqrt(20) + 1e-12;
    const obvDiv = ((obv[n - 1] - obv[n - 21]) / obvStd) - ((c[n - 1] / c[n - 21] - 1) / pxStd);

    // 4) Amihud 流动性枯竭比（20日 / 120日）
    const am = [];
    for (let i = Math.max(1, n - 120); i < n; i += 1) {
      const dv = c[i] * v[i];
      if (dv > 0) am.push(Math.abs(r[i]) / dv);
    }
    const med = (arr) => {
      if (!arr.length) return null;
      const s = arr.slice().sort((a, b) => a - b);
      return s[Math.floor(s.length / 2)];
    };
    const am20 = med(am.slice(-20));
    const am120 = med(am);
    const amRatio = (am20 != null && am120 != null && am120 > 0) ? am20 / am120 : null;

    const inVacuum = wellF >= 1.25 && noWellBelow;
    const inTrappedWell = wellF <= 0.55;
    const deepDiscount = vwapGap <= -0.10;
    const obvBullDiv = obvDiv >= 0.65;
    const liquidityDry = amRatio != null && amRatio >= 1.25;

    let label = '价格物理结构中性';
    if (inVacuum && (deepDiscount || obvBullDiv)) label = '跌穿旧筹码势阱 · 高自由能出清区';
    else if (inTrappedWell) label = '位于半山腰旧筹码密集区（套牢阻力阱）';
    else if ((inVacuum ? 1 : 0) + (deepDiscount ? 1 : 0) + (obvBullDiv ? 1 : 0) + (liquidityDry ? 1 : 0) >= 2) {
      label = '价格空间接近出清区';
    }

    return {
      label,
      wellF: Number(wellF.toFixed(2)),
      noWellBelow,
      vwap250: Number(vwap250.toFixed(2)),
      vwapGap: Number(vwapGap.toFixed(4)),
      obvDiv: Number(obvDiv.toFixed(2)),
      amRatio: amRatio != null ? Number(amRatio.toFixed(2)) : null,
      inVacuum,
      inTrappedWell,
      deepDiscount,
      obvBullDiv,
      liquidityDry,
    };
  }

  return {
    evaluate,
    fromDecision,
    fromHistory,
    fromOverviewItem,
    evaluatePricePhysics,
  };
});
