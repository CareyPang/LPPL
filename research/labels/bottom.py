"""有效底标签（阶段 5 设计 v1.3 §2，三重障碍；参数已由用户确认：时间障碍 60 日、窗口 20 日、PIT 分位数阈值）。

本文件只实现与合成数据测试；在候选名单冻结（§12.7）前不在真实数据上运行。
- 候选底：对 −log P 做与顶部相同的 ε-回撤共识扫描（C 法对称）。
- 障碍（PIT）：d_up(b) = max(FLOOR, 过去 YEARS 年所有"候选底后 LOOK 日最大涨幅"的 Q90)，d_dn = DN_RATIO·d_up；只用截至 b 可知的数据。
- 三重障碍：从 b 次日起 LOOK 日内，先触 +d_up 且未先触 −d_dn → 有效底；先触 −d_dn 或到期 → 非有效底（半山腰）。
- 标签：Y(t)=1 当且仅当 (t, t+HORIZON] 内出现有效底；成熟期 MATURITY = LOOK + HORIZON。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .top import MIN_TOPS_FOR_Q, consensus_tops, epsilon_tops

LOOK, HORIZON, MATURITY = 60, 20, 80
FLOOR, QUANT, YEARS, DN_RATIO = 0.10, 0.90, 5, 0.5


def candidate_bottoms(logp: np.ndarray) -> np.ndarray:
    neg = -logp
    return consensus_tops(neg, epsilon_tops(neg))


def runup_after(logp: np.ndarray, idx: int, look: int = LOOK) -> float:
    seg = logp[idx + 1 : idx + 1 + look]
    return float(np.exp(seg.max() - logp[idx]) - 1) if len(seg) else np.nan


def triple_barrier(logp: np.ndarray, b: int, d_up: float, d_dn: float, look: int = LOOK) -> tuple[int, int]:
    """返回 (结果, 触及日偏移)：结果 1=先触上障碍（有效底）、−1=先触下障碍、0=到期未触。"""
    seg = np.exp(logp[b + 1 : b + 1 + look] - logp[b]) - 1
    up = np.flatnonzero(seg >= d_up)
    dn = np.flatnonzero(seg <= -d_dn)
    iu = up[0] if len(up) else np.inf
    idn = dn[0] if len(dn) else np.inf
    if iu == np.inf and idn == np.inf:
        return 0, len(seg)
    return (1, int(iu)) if iu < idn else (-1, int(idn))


def label_bottom(dates: pd.DatetimeIndex, logp: np.ndarray, bottoms: np.ndarray | None = None,
                 floor: float = FLOOR, quant: float | None = QUANT, dn_ratio: float = DN_RATIO,
                 look: int = LOOK) -> pd.DataFrame:
    """返回 DataFrame(index=dates)：y、d_up、n_hist、以及按候选底给出的 outcome（1/−1/0，非候选日为 NaN）。"""
    n = len(logp)
    bottoms = candidate_bottoms(logp) if bottoms is None else bottoms
    ru = np.array([runup_after(logp, k, look) for k in bottoms])
    known_at = bottoms + look
    b_dates = dates[bottoms]
    outcome = np.zeros(len(bottoms), int)
    d_up_b = np.full(len(bottoms), np.nan)
    for i, b in enumerate(bottoms):
        if quant is not None:
            m = (known_at <= b) & (b_dates >= dates[b] - pd.DateOffset(years=YEARS)) & np.isfinite(ru)
            q = np.quantile(ru[m], quant) if m.sum() >= MIN_TOPS_FOR_Q else -np.inf
            d_up_b[i] = max(floor, q)
        else:
            d_up_b[i] = floor
        outcome[i], _ = triple_barrier(logp, b, d_up_b[i], dn_ratio * d_up_b[i], look)
    valid = bottoms[outcome == 1]
    y = np.full(n, np.nan)
    for t in range(n - MATURITY):
        y[t] = float(np.any((valid > t) & (valid <= t + HORIZON)))
    out = pd.DataFrame(dict(y=y), index=dates)
    out["outcome"] = np.nan
    out["d_up"] = np.nan
    out.iloc[bottoms, out.columns.get_loc("outcome")] = outcome
    out.iloc[bottoms, out.columns.get_loc("d_up")] = d_up_b
    out.attrs["halfway_share"] = float(np.mean(outcome == -1)) if len(outcome) else np.nan
    return out
