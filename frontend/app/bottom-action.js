/* 临界点 · 统一底部位置与分批抄底决策引擎（严格基于已发布数据，不做二次拟合）
   输入：最新周度帧 / 顶部红柱状态 / 四维底部因子 / 50周历史实证摘要
   输出：5 档状态机（顶部高危 / 中性非底 / 左侧余震严禁接刀 / 底部共振30%试探 / 右侧确认60%-100%加仓）
         + 建议仓位 + 30%→30%→40% 三段步进索引 + 选品方向指引 */
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

  /**
   * 评估单个指数当前的位置、能不能抄底、建议仓位与买什么
   * @param {Object} input
   * @param {string} [input.sym]
   * @param {boolean} [input.hasTop]      当前是否触发 6-12m 顶部泡沫红柱
   * @param {number}  [input.score]       多维底部综合分（0-100，或 0-1 自动换算）
   * @param {Object}  [input.factors]     { dd_52w, erp_pct, pbn_pct, valuation, clearing, stabilize, right_side }
   * @param {Object}  [input.summary]     bottom_summary（n_events, win_rate_50w, baseline_win_rate_50w, median_ret_50w, median_post_min_50w）
   * @param {boolean} [input.omoriRed]    实时六维仪表盘 Omori 余震是否亮红灯
   */
  function evaluate(input) {
    const cfg = input || {};
    const sym = String(cfg.sym || '').toLowerCase();
    const prof = INDEX_PROFILE[sym] || { kind: 'broad', etf: '对应宽基 ETF', elastic: false };
    const hasTop = Boolean(cfg.hasTop);
    const rawScore = toNum(cfg.score, null);
    const score = rawScore == null ? null : rawScore > 0 && rawScore <= 1 ? Math.round(rawScore * 100) : Math.round(rawScore);
    const f = cfg.factors || {};
    const stab = toNum(f.stabilize, 0);
    const right = toNum(f.right_side, 0);
    const dd52 = f.dd_52w != null ? toNum(f.dd_52w, null) : null;
    const summary = cfg.summary || null;
    const mdd50 = summary && summary.median_post_min_50w != null
      ? Math.round(Math.abs(Number(summary.median_post_min_50w)) * 100)
      : null;
    const win50 = summary && summary.win_rate_50w != null
      ? Math.round(Number(summary.win_rate_50w) * 1000) / 10
      : null;

    if (hasTop) {
      return {
        tier: 'top_risk',
        tone: 'red',
        glyph: '🔴',
        positionLabel: '顶部高危区',
        canBuy: false,
        canBuyLabel: '不能抄底 · 严禁追高',
        targetPct: 0,
        positionText: '减仓 30%–40%',
        shortBadge: '🔴 顶部区 · 分批减仓',
        stepIndex: -1,
        vehicle: '锁定利润，严禁追高高弹性题材股，保留现金等待顶部冷却。',
        reason: '6–12 月主尺度出现正向泡沫红柱，盈亏比已倒挂，应按顶部纪律分批止盈。',
        score,
        dd52,
        win50,
        mdd50,
      };
    }

    if (score == null && !cfg.omoriRed) {
      return { tier: 'unavailable', tone: 'gray', glyph: '—', positionLabel: '底部条件未覆盖',
        canBuy: false, canBuyLabel: '等待已发布评分', targetPct: null, positionText: '评分未提供',
        shortBadge: '评分未覆盖', stepIndex: 0, vehicle: '可以继续查看已有行情和顶部区间。',
        reason: '当前结果没有提供底部条件分，未用零分替代。', score: null, dd52, win50, mdd50 };
    }

    if (score != null && score < 20 && !cfg.omoriRed) {
      return {
        tier: 'neutral',
        tone: 'gray',
        glyph: '⚪',
        positionLabel: '中性非底部区',
        canBuy: false,
        canBuyLabel: '无需抄底',
        targetPct: null,
        positionText: '维持常规仓位',
        shortBadge: '⚪ 非底部区 · 常规持有',
        stepIndex: 0,
        vehicle: '未进超跌底坑，也无顶部红柱；继续按趋势持有原仓位，不刻意左侧加仓。',
        reason: '距 52 周高点回撤未达 -12% 深度出清门槛，不构成底部抄底窗口。',
        score,
        dd52,
        win50,
        mdd50,
      };
    }

    const aftershockBlocked = Boolean(cfg.omoriRed) || stab < 0.5;
    if (score < 50 || aftershockBlocked) {
      const isNear = score >= 40 && !cfg.omoriRed;
      return {
        tier: 'left_wait',
        tone: 'amber',
        glyph: isNear ? '🟡' : '🟠',
        positionLabel: isNear ? '深跌左侧观察区' : '左侧下跌 / 余震未消',
        canBuy: false,
        canBuyLabel: isNear ? '暂缓 · 临门一脚' : '不能抄底 · 防接飞刀',
        targetPct: 0,
        positionText: '建议仓位 0%',
        shortBadge: isNear ? `🟡 左侧观察(${score}分) · 仓位 0%` : `🟠 余震未消(${score}分) · 仓位 0%`,
        stepIndex: 0,
        vehicle: '暂不进场；先将 ' + prof.etf + ' 加入观察，严禁提前重仓押注高弹性小票。',
        reason: aftershockBlocked
          ? '防死猫跳/大森余震未通过（仍在创新低或波动未收敛），此时进场极易被二次杀跌套牢。'
          : `多维底部综合分 ${score}/100 未达到 50 分共振门槛，等待进一步止跌确认后再动用第 1 笔资金。`,
        score,
        dd52,
        win50,
        mdd50,
      };
    }

    if (right < 0.7) {
      const mddHint = mdd50 != null ? `（历史共振后 50 周内仍有约 -${mdd50}% 中位再回撤）` : '';
      return {
        tier: 'bottom_probe',
        tone: 'green',
        glyph: '🟢',
        positionLabel: '底部共振 · 第 1 笔试探区',
        canBuy: true,
        canBuyLabel: '可以抄底 · 启动第 1 笔',
        targetPct: 30,
        positionText: '先买 30% 试探仓',
        shortBadge: `🟢 底部共振(${score}分) · 建仓 30%`,
        stepIndex: 1,
        vehicle: `首选 ${prof.etf} 拿先手打底；因右侧均线未拐头，暂不重仓单押高弹性个股。`,
        reason: `多维底部综合分 ${score}/100 且已初步止跌${mddHint}；用 30% 试探仓防踏空、留 70% 现金防二次探底。`,
        score,
        dd52,
        win50,
        mdd50,
      };
    }

    return {
      tier: 'right_confirm',
      tone: 'emerald',
      glyph: '✅',
      positionLabel: '底部 + 右侧确认区',
      canBuy: true,
      canBuyLabel: '右侧成立 · 分批加仓',
      targetPct: 60,
      positionText: '加至 60% → 回踩打满 100%',
      shortBadge: `✅ 右侧确认(${score}分) · 60%→100%`,
      stepIndex: 2,
      vehicle: prof.elastic
        ? `宽基打底稳固，可将第 2/3 笔逐步切向 ${prof.etf} 及率先站上 20/60 日线的业绩龙头。`
        : `第 2 笔 30% 站稳 20 日线加仓，回踩不破前低且放量至 20 日均量 1.3× 以上打满剩余 40%。`,
      reason: `底部综合分 ${score}/100、余震已消且站上右侧均线，可按 30%→30%→40% 节奏推进至主升仓位。`,
      score,
      dd52,
      win50,
      mdd50,
    };
  }

  /** Compatibility shape for existing cards; all decisions come from one published view. */
  function fromDecision(view) {
    if (!view || !view.conclusion) return null;
    const c = view.conclusion, b = view.bottom || {}, top = view.top || {};
    const tier = c.status === 'top_watch' ? 'top_risk'
      : c.status === 'bottom_probe' || c.status === 'right_confirm' ? c.status
        : c.status === 'neutral' ? 'neutral'
          : ['model_pending', 'unavailable', 'incomplete'].includes(c.status) ? 'unavailable' : 'left_wait';
    const toneMap = { risk: 'red', danger: 'red', warning: 'amber', warn: 'amber', success: 'green',
      teal: 'green', positive: 'green', muted: 'gray', neutral: 'gray' };
    const tone = toneMap[c.tone] || c.tone || 'gray';
    const glyph = ({ red: '🔴', amber: '🟡', green: '🟢', emerald: '🟢', blue: '🔵', gray: '⚪' })[tone] || '•';
    return { tier, tone, glyph, score: b.score == null ? null : b.score,
      scoreAsOf: b.asof || '', scoreStale: !!b.stale,
      positionLabel: c.title, positionText: b.stale ? '底分待更新' : top.status === 'active' ? '查看时间区间' : '',
      canBuy: c.status === 'bottom_probe' || c.status === 'right_confirm', canBuyLabel: c.next || c.detail || '',
      shortBadge: c.title, targetPct: null, stepIndex: 0, vehicle: c.next || '', reason: c.detail || '',
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

  /** 根据 A 股 6 位代码推断所属核心宽基指数 */
  function boardIndexForStock(code) {
    const clean = String(code || '').replace(/^(sh|sz|bj)(?=\d{6}$)/i, '');
    if (!/^\d{6}$/.test(clean)) return { sym: null, board: '市场参考未覆盖', supported: false };
    if (/^(300|301)/.test(clean)) return { sym: 'sz399006', board: '创业板指' };
    if (/^688/.test(clean)) return { sym: 'sh000688', board: '科创50' };
    if (/^(600|601|603|605)/.test(clean)) return { sym: 'sh000001', board: '上证综指' };
    if (/^(000|001|002|003)/.test(clean)) return { sym: 'sz399001', board: '深证成指' };
    return { sym: null, board: '市场参考未覆盖', supported: false };
  }

  /**
   * 严格 PIT 计算个股日线序列的「多维底部出清强度 + Omori 余震红灯 + 右侧均线状态」
   * 输入：prices = [{ date, close, volume? }, ...]（按日期升序）
   * 输出：{ series: [{ date, score, bottomIntensity, omoriRed, clearing, stabilize, rightSide }], latest, board, action }
   */
  function evaluateStockSeries(prices, opts) {
    const bars = Array.isArray(prices) ? prices.filter((b) => b && b.date && Number.isFinite(Number(b.close)) && Number(b.close) > 0) : [];
    const cfg = opts || {};
    const board = boardIndexForStock(cfg.code);
    if (board.supported === false || bars.length < 30) {
      return { series: [], latest: null, board, action: null };
    }
    const closes = bars.map((b) => Number(b.close));
    const rets = [0];
    for (let i = 1; i < closes.length; i += 1) {
      rets.push((closes[i] - closes[i - 1]) / closes[i - 1]);
    }
    const series = [];
    for (let i = 0; i < bars.length; i += 1) {
      const look252 = Math.max(0, i - 251);
      let hi252 = closes[i];
      for (let j = look252; j <= i; j += 1) if (closes[j] > hi252) hi252 = closes[j];
      const dd252 = (closes[i] - hi252) / hi252; // <= 0

      // 1) 超跌出清分（回撤 -15% 起步，-42% 满分）
      const clearing = dd252 >= -0.15 ? 0 : Math.min(1, Math.max(0, (-dd252 - 0.15) / 0.27));

      // 2) 防死猫跳 / Omori 余震检验：近 60 日低点、近 10 日是否刷新低点、近 15 日大阴线次数（<= -5.5% 或该股过去 250 日 5% 分位）
      const look60 = Math.max(0, i - 59);
      let lo60 = closes[i];
      for (let j = look60; j <= i; j += 1) if (closes[j] < lo60) lo60 = closes[j];
      const look10 = Math.max(0, i - 9);
      let lo10 = closes[i];
      for (let j = look10; j <= i; j += 1) if (closes[j] < lo10) lo10 = closes[j];
      const hitNewLow10d = lo10 <= lo60 * 1.005;

      const look15 = Math.max(1, i - 14);
      let bigDrops15d = 0;
      for (let j = look15; j <= i; j += 1) {
        if (rets[j] <= -0.055) bigDrops15d += 1;
      }
      const omoriRed = bigDrops15d >= 2 || (hitNewLow10d && bigDrops15d >= 1);
      const stabilize = omoriRed ? 0.2 : (hitNewLow10d ? 0.45 : (bigDrops15d === 0 ? 1.0 : 0.7));

      // 3) 右侧均线分（MA20 / MA60）
      let ma20 = null, ma60 = null;
      if (i >= 19) {
        let s20 = 0;
        for (let j = i - 19; j <= i; j += 1) s20 += closes[j];
        ma20 = s20 / 20;
      }
      if (i >= 59) {
        let s60 = 0;
        for (let j = i - 59; j <= i; j += 1) s60 += closes[j];
        ma60 = s60 / 60;
      }
      const aboveMa20 = ma20 != null && closes[i] >= ma20;
      const aboveMa60 = ma60 != null && closes[i] >= ma60;
      const rightSide = (aboveMa20 && aboveMa60) ? 1.0 : (aboveMa20 ? 0.55 : 0.0);

      // 个股综合底部出清分（0..1，严格乘数结构：无超跌清零，余震期上限封顶在 0.46 防误判底部共振）
      let rawIntensity = 0;
      if (clearing > 0) {
        rawIntensity = clearing * (0.48 + 0.34 * stabilize + 0.18 * rightSide);
        if (omoriRed) rawIntensity = Math.min(rawIntensity, 0.46);
      }
      const bottomIntensity = Math.max(0, Math.min(1, Number(rawIntensity.toFixed(3))));
      series.push({
        date: bars[i].date,
        close: closes[i],
        dd252,
        lo60,
        hitNewLow10d,
        bigDrops15d,
        omoriRed,
        ma20,
        ma60,
        aboveMa20,
        aboveMa60,
        clearing: Number(clearing.toFixed(2)),
        stabilize: Number(stabilize.toFixed(2)),
        rightSide: Number(rightSide.toFixed(2)),
        bottomIntensity,
        score: Math.round(bottomIntensity * 100),
      });
    }
    const latest = series[series.length - 1];
    const hasTop = Boolean(cfg.hasTop);
    const action = evaluate({
      sym: board.sym,
      hasTop,
      score: latest.score,
      factors: {
        dd_52w: latest.dd252,
        clearing: latest.clearing,
        stabilize: latest.stabilize,
        right_side: latest.rightSide,
      },
      omoriRed: latest.omoriRed,
    });
    return { series, latest, board, action };
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
    boardIndexForStock,
    evaluateStockSeries,
    evaluatePricePhysics,
    STEPS: [
      { idx: 1, pct: '30%', title: '第 1 笔 · 试探仓', cond: '综合分≥50 且止跌（买宽基 ETF 打底）' },
      { idx: 2, pct: '30%', title: '第 2 笔 · 右侧仓', cond: '站稳 20 日均线 + 宽度回升（可切弹性）' },
      { idx: 3, pct: '40%', title: '第 3 笔 · 主升仓', cond: '回踩不破前低 + 放量 1.3× 打满' },
    ],
  };
});
