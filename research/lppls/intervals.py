"""t_c 区间的两种方法（预登记方案 §8）。

profile_interval : 对 t_c 做剖面似然（Filimonov、Demos & Sornette 2017 的思路；本版未含 modified 校正项）。
                   高斯似然下 L_p(tc) = -(n/2)·ln(SSE_min(tc)/n)，区间 = {tc : 2[L_max − L_p(tc)] ≤ χ²₁(level)}。
bootstrap_interval: 残差块 bootstrap（循环块，默认块长 10），每条替代序列重新拟合，取分位数区间。
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.stats import chi2

from ..optim.optimizers import METHODS
from .core import lin_fit


def _profile_sse(t, y, tc, lo, hi) -> float:
    ms = np.linspace(lo[1], hi[1], 10)
    ws = np.linspace(lo[2], hi[2], 12)
    best, bx = np.inf, None
    for m in ms:
        for w in ws:
            s, _ = lin_fit(t, y, tc, m, w)
            if s < best:
                best, bx = s, (m, w)
    if bx is None:
        return np.inf
    r = minimize(lambda x: lin_fit(t, y, tc, x[0], x[1])[0], bx, method="L-BFGS-B",
                 bounds=[(lo[1], hi[1]), (lo[2], hi[2])])
    return float(min(best, r.fun))


def profile_interval(t, y, lo, hi, level=0.9, step=1.0):
    n = len(t)
    grid = np.arange(lo[0], hi[0] + 1e-9, step)
    s = np.array([_profile_sse(t, y, tc, lo, hi) for tc in grid])
    ok = np.isfinite(s)
    lp = np.full_like(s, -np.inf)
    lp[ok] = -(n / 2) * np.log(s[ok] / n)
    cut = lp.max() - chi2.ppf(level, 1) / 2
    inside = grid[lp >= cut]
    return float(inside.min()), float(inside.max()), float(grid[np.argmax(lp)])


def bootstrap_interval(t, y, lo, hi, level=0.9, B=50, block=10, method="tcgrid_lm", seed=0):
    rng = np.random.default_rng(seed)
    fit = METHODS[method](t, y, lo, hi, seed=seed)
    s, beta = lin_fit(t, y, *fit.theta)
    from .core import design

    yhat = design(t, *fit.theta) @ beta
    res = y - yhat
    n = len(t)
    tcs = []
    for _ in range(B):
        idx = np.concatenate([(np.arange(block) + rng.integers(n)) % n for _ in range(n // block + 1)])[:n]
        yb = yhat + res[idx]
        tcs.append(METHODS[method](t, yb, lo, hi, seed=int(rng.integers(1 << 30))).theta[0])
    a = (1 - level) / 2
    return float(np.quantile(tcs, a)), float(np.quantile(tcs, 1 - a)), float(fit.theta[0])
