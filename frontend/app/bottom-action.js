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
    const rawScore = toNum(cfg.score, 0);
    const score = rawScore > 0 && rawScore <= 1 ? Math.round(rawScore * 100) : Math.round(rawScore);
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

    if (score < 20) {
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
          ? '防死猫跳/大森余震尚未通过（仍在创新低或波动未收敛），此时进场极易被二次杀跌套牢。'
          : `多维底部综合分 ${score}/100 尚未达到 50 分共振门槛，等待进一步止跌确认后再动用第 1 笔资金。`,
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
      score: last.fco_neg_intensity || 0,
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
      score: item.bottom_score != null ? item.bottom_score : (item.fco_neg_intensity || 0),
      factors: item.bottom_factors || null,
      summary: item.bottom_summary || null,
      omoriRed: Boolean(opts && opts.omoriRed),
    });
  }

  return {
    evaluate,
    fromHistory,
    fromOverviewItem,
    STEPS: [
      { idx: 1, pct: '30%', title: '第 1 笔 · 试探仓', cond: '综合分≥50 且止跌（买宽基 ETF 打底）' },
      { idx: 2, pct: '30%', title: '第 2 笔 · 右侧仓', cond: '站稳 20 日均线 + 宽度回升（可切弹性）' },
      { idx: 3, pct: '40%', title: '第 3 笔 · 主升仓', cond: '回踩不破前低 + 放量 1.3× 打满' },
    ],
  };
});
