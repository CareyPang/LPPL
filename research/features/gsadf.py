"""R2：Phillips–Shi–Yu（2015）的 BSADF 实时序列（GSADF 的逐时点版本）。

对每个时点 t，在回看窗口 W 内，对所有起点 s ∈ [t−W, t−minw] 计算 ADF 回归
    Δy_u = α + ρ y_{u−1} + ε_u,  u ∈ (s, t]
的 ρ 的 t 统计量，取上确界得到 BSADF_t。滞后阶数固定为 0，这样 OLS 可以用前缀和闭式计算，
逐日逐标的可行。只用 ≤ t 的数据，天然 PIT。

最小窗口 minw 的两种选法（预登记附表）：PSY 公式 r0 = 0.01 + 1.8/√T（T 取 W）或固定 36 日。
"""
from __future__ import annotations

import numpy as np

WINDOWS = (250, 500)


def psy_min_window(W: int) -> int:
    return int(np.ceil((0.01 + 1.8 / np.sqrt(W)) * W))


def _adf_t_closed_form(S: dict, s: np.ndarray, t: int) -> np.ndarray:
    """窗口 (s, t] 上 lag-0 ADF 回归中 ρ 的 t 统计量；s 为向量。"""
    n = (t - s).astype(float)

    def rng(key):
        return S[key][t] - S[key][s]

    sx, sy, sxx, sxy, syy = rng("x"), rng("y"), rng("xx"), rng("xy"), rng("yy")
    mx, my = sx / n, sy / n
    sxx_c = sxx - n * mx * mx
    sxy_c = sxy - n * mx * my
    syy_c = syy - n * my * my
    rho = sxy_c / sxx_c
    ssr = syy_c - rho * sxy_c
    dof = n - 2
    se = np.sqrt(np.maximum(ssr, 0.0) / dof / sxx_c)
    with np.errstate(divide="ignore", invalid="ignore"):
        tstat = rho / se
    tstat[~np.isfinite(tstat)] = np.nan
    return tstat


def bsadf(y: np.ndarray, W: int, minw: int) -> np.ndarray:
    """返回与 y 等长的 BSADF 序列；前 minw 个点为 nan。y 为对数价格。"""
    y = np.asarray(y, float)
    T = len(y)
    out = np.full(T, np.nan)
    x = y[:-1]
    dy = np.diff(y)
    # 观测 u（1..T−1）对应 (x[u−1], dy[u−1])；前缀和 S[k] = sum over first k observations
    pre = {}
    for key, arr in (("x", x), ("y", dy), ("xx", x * x), ("xy", x * dy), ("yy", dy * dy)):
        pre[key] = np.concatenate([[0.0], np.cumsum(arr)])
    # 窗口 (s, t]（按价格索引）包含观测 u = s+1..t，即前缀差 S[t] − S[s]
    for t in range(minw, T):
        s = np.arange(max(0, t - W), t - minw + 1)
        ts = _adf_t_closed_form(pre, s, t)
        if np.any(np.isfinite(ts)):
            out[t] = np.nanmax(ts)
    return out


def bsadf_brute(y: np.ndarray, W: int, minw: int) -> np.ndarray:
    """逐窗口显式 OLS 的参考实现（测试用）。"""
    y = np.asarray(y, float)
    T = len(y)
    out = np.full(T, np.nan)
    for t in range(minw, T):
        best = -np.inf
        for s in range(max(0, t - W), t - minw + 1):
            yy = y[s : t + 1]
            X = np.column_stack([np.ones(len(yy) - 1), yy[:-1]])
            d = np.diff(yy)
            beta, *_ = np.linalg.lstsq(X, d, rcond=None)
            r = d - X @ beta
            dof = len(d) - 2
            cov = r @ r / dof * np.linalg.inv(X.T @ X)
            best = max(best, beta[1] / np.sqrt(cov[1, 1]))
        out[t] = best
    return out
