"""顶部事件标签：C 定位 + B 过滤（预登记 v1.0 §3）。

C  epsilon_tops     : ε-回撤分段（Gerlach–Demos–Sornette 2019）。每组 (ε₀, w) 把对数价切成交替的上涨/下跌段，
                      上涨段终点为候选顶。ε = ε₀·σ_w，σ_w 为截至当日过去 w 日对数收益标准差（PIT）。
   consensus_tops   : 候选顶在 ±2 日内出现于 ≥ share（默认 50%）的参数组合 → 共识顶；相邻共识日合并，取段内最高价日。
B  label_top        : 顶后 60 日内最低点的跌幅 dd；时点 t 的门槛 d_t = max(floor, Q90{dd_k : 顶 k 在 t 前 5 年内且 dd_k 已在 t 时可知})。
                      Y(t)=1 ⇔ (t, t+20] 内有跌幅 ≥ d_t 的共识顶。成熟期 80 日：t+80 超出样本则 Y=NaN。
辅助：max_drawdown_ahead（t 后 60 日最大回撤）；event_segments（连续 Y=1 合并为一段）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS0 = np.round(np.arange(0.1, 5.01, 0.1), 2)  # 50 个
WS = tuple(range(10, 61, 5))  # 11 个
TOL = 2
SHARE = 0.5
LOOK = 60
HORIZON = 20
MATURITY = 80
FLOOR = 0.10
QUANT = 0.90
YEARS = 5
MIN_TOPS_FOR_Q = 5


def rolling_sigma(logp: np.ndarray, w: int) -> np.ndarray:
    r = pd.Series(np.diff(logp, prepend=np.nan))
    return r.rolling(w).std(ddof=1).to_numpy()


def epsilon_tops(logp: np.ndarray, eps0=EPS0, ws=WS) -> np.ndarray:
    """返回 hits[n]：各日作为候选顶出现的参数组合数（已含 ±TOL 日容差）。"""
    n = len(logp)
    eps0 = np.asarray(eps0, float)
    k = len(eps0)
    hits = np.zeros(n)
    for w in ws:
        sig = rolling_sigma(logp, w)
        up = np.ones(k, bool)
        ext = np.full(k, logp[0])  # 上涨段的峰值 / 下跌段的谷值
        ext_i = np.zeros(k, int)
        cand = np.zeros((k, n), bool)
        for i in range(1, n):
            p = logp[i]
            s = sig[i] if np.isfinite(sig[i]) else np.nan
            if not np.isfinite(s):
                # 还没有 σ_w：只跟踪极值，不切段
                hi = up & (p > ext)
                lo = ~up & (p < ext)
                ext[hi | lo] = p
                ext_i[hi | lo] = i
                continue
            eps = eps0 * s
            # 上涨段：创新高则更新峰；回撤超过 ε 则峰为候选顶，切到下跌段
            new_hi = up & (p > ext)
            ext[new_hi] = p
            ext_i[new_hi] = i
            end_up = up & ~new_hi & (ext - p > eps)
            cand[end_up, ext_i[end_up]] = True
            # 下跌段：创新低则更新谷；反弹超过 ε 则切到上涨段
            new_lo = ~up & (p < ext)
            ext[new_lo] = p
            ext_i[new_lo] = i
            end_dn = ~up & ~new_lo & (p - ext > eps)
            up = (up & ~end_up) | end_dn
            ext[end_up | end_dn] = p
            ext_i[end_up | end_dn] = i
        # ±TOL 日容差
        dil = cand.copy()
        for d in range(1, TOL + 1):
            dil[:, d:] |= cand[:, :-d]
            dil[:, :-d] |= cand[:, d:]
        hits += dil.sum(axis=0)
    return hits


def consensus_tops(logp: np.ndarray, hits: np.ndarray, share: float = SHARE, n_combo: int = len(EPS0) * len(WS)) -> np.ndarray:
    flag = hits >= share * n_combo
    tops = []
    i = 0
    n = len(flag)
    while i < n:
        if flag[i]:
            j = i
            while j + 1 < n and flag[j + 1]:
                j += 1
            tops.append(i + int(np.argmax(logp[i : j + 1])))
            i = j + 1
        else:
            i += 1
    return np.array(tops, int)


def drawdown_after(logp: np.ndarray, idx: int, look: int = LOOK) -> float:
    seg = logp[idx + 1 : idx + 1 + look]
    if len(seg) < look:
        return np.nan
    return float(1 - np.exp(seg.min() - logp[idx]))


def label_top(
    dates: pd.DatetimeIndex, logp: np.ndarray, tops: np.ndarray,
    floor: float = FLOOR, quant: float | None = QUANT, fixed_sigma_k: float | None = None,
) -> pd.DataFrame:
    """返回 DataFrame(index=dates)：y（0/1/NaN）、d_t、n_hist_tops、dd_ahead（辅助连续标签）。
    quant=None 且 fixed_sigma_k=None → 固定门槛 floor；fixed_sigma_k=k → d_t = max(floor, k·σ_t·√20)。"""
    n = len(logp)
    dd = np.array([drawdown_after(logp, k) for k in tops])
    known_at = tops + LOOK  # dd_k 在该索引之后可知
    top_dates = dates[tops]
    sig20 = rolling_sigma(logp, 20)
    y = np.full(n, np.nan)
    d_t = np.full(n, np.nan)
    nh = np.zeros(n, int)
    for t in range(n):
        if t + MATURITY >= n:
            break
        if quant is not None:
            lo_date = dates[t] - pd.DateOffset(years=YEARS)
            m = (known_at <= t) & (top_dates >= lo_date) & np.isfinite(dd)
            nh[t] = int(m.sum())
            q = np.quantile(dd[m], quant) if nh[t] >= MIN_TOPS_FOR_Q else -np.inf
            thr = max(floor, q)
        elif fixed_sigma_k is not None:
            thr = max(floor, fixed_sigma_k * sig20[t] * np.sqrt(HORIZON)) if np.isfinite(sig20[t]) else floor
        else:
            thr = floor
        d_t[t] = thr
        m2 = (tops > t) & (tops <= t + HORIZON)
        y[t] = float(np.any(dd[m2] >= thr)) if m2.any() else 0.0
    ahead = np.full(n, np.nan)
    for t in range(n - LOOK):
        ahead[t] = 1 - np.exp(logp[t + 1 : t + 1 + LOOK].min() - logp[t])
    return pd.DataFrame(dict(y=y, d_t=d_t, n_hist_tops=nh, dd_ahead=ahead), index=dates)


def event_segments(y: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    v = (y == 1).to_numpy()
    segs, i, n = [], 0, len(v)
    while i < n:
        if v[i]:
            j = i
            while j + 1 < n and v[j + 1]:
                j += 1
            segs.append((y.index[i], y.index[j]))
            i = j + 1
        else:
            i += 1
    return segs
