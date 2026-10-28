"""R7：统计物理 / 临界慢化类特征（预登记 §5 R7），滚动窗口 60、120、250 日。

- var：窗口内对数收益方差；
- ar1：收益的一阶自相关；
- dfa：去趋势波动分析的标度指数 α（对数收益的累积剖面，线性去趋势，盒长 4..n/4 的对数等距格点）；
- pe：排列熵（阶数 3、延迟 1，归一化到 [0,1]）；
- tau：对数价格对时间的 Kendall τ（趋势单调性）。
全部只用窗口内（≤t）的数据。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy.stats import kendalltau

WINDOWS = (60, 120, 250)


def dfa_alpha(x: np.ndarray, n_scales: int = 8) -> float:
    x = np.asarray(x, float)
    n = len(x)
    prof = np.cumsum(x - x.mean())
    scales = np.unique(np.geomspace(4, n // 4, n_scales).astype(int))
    F = []
    for s in scales:
        nb = n // s
        seg = prof[: nb * s].reshape(nb, s)
        t = np.arange(s, dtype=float)
        X = np.column_stack([np.ones(s), t])
        beta = np.linalg.lstsq(X, seg.T, rcond=None)[0]
        res = seg.T - X @ beta
        F.append(np.sqrt(np.mean(res**2)))
    F = np.asarray(F)
    ok = F > 0
    if ok.sum() < 3:
        return np.nan
    return float(np.polyfit(np.log(scales[ok]), np.log(F[ok]), 1)[0])


def perm_entropy(x: np.ndarray, order: int = 3) -> float:
    pat = np.argsort(sliding_window_view(np.asarray(x, float), order), axis=1)
    codes = (pat * (order ** np.arange(order))).sum(axis=1)
    _, cnt = np.unique(codes, return_counts=True)
    p = cnt / cnt.sum()
    return float(-(p * np.log(p)).sum() / np.log(float(np.prod(range(1, order + 1)))))


def ar1(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    a, b = x[:-1] - x[:-1].mean(), x[1:] - x[1:].mean()
    d = np.sqrt((a @ a) * (b @ b))
    return float(a @ b / d) if d > 0 else np.nan


def rolling_statphys(logp: pd.Series, windows=WINDOWS) -> pd.DataFrame:
    r = logp.diff().to_numpy()
    lp = logp.to_numpy()
    out = {}
    T = len(lp)
    for w in windows:
        var = np.full(T, np.nan)
        a1 = np.full(T, np.nan)
        dfa = np.full(T, np.nan)
        pe = np.full(T, np.nan)
        tau = np.full(T, np.nan)
        tt = np.arange(w, dtype=float)
        for i in range(w, T):
            rr = r[i - w + 1 : i + 1]
            var[i] = rr.var(ddof=1)
            a1[i] = ar1(rr)
            dfa[i] = dfa_alpha(rr)
            pe[i] = perm_entropy(rr)
            tau[i] = kendalltau(tt, lp[i - w + 1 : i + 1]).statistic
        out[f"var{w}"], out[f"ar1_{w}"], out[f"dfa{w}"], out[f"pe{w}"], out[f"tau{w}"] = var, a1, dfa, pe, tau
    return pd.DataFrame(out, index=logp.index)
