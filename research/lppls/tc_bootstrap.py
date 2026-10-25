"""§17.4-7 t_c 的残差区块 bootstrap 区间（Jiang 等 2010 §2.2 的 bootstrap 思路）。

给定一个窗口的拟合 (tc, m, ω, β)，对拟合残差做循环区块重抽样（区块长度 BLOCK），
把重抽残差加回拟合值得到伪样本，在同一搜索域内重新拟合，取 t_c−t₂ 的分位数。
只对 Lagrange 选中的窗口或报警日的合格窗口运行（计算量：B 次 LM）。
"""
from __future__ import annotations

import numpy as np

from ..lppls.core import design, lin_fit
from ..optim.optimizers import tcgrid_lm

BLOCK, B_DEFAULT = 10, 30
QS = (0.05, 0.2, 0.5, 0.8, 0.95)


def _block_resample(e: np.ndarray, rng: np.random.Generator, block: int = BLOCK) -> np.ndarray:
    n = len(e)
    out = np.empty(n)
    k = 0
    while k < n:
        s = int(rng.integers(0, n))
        seg = np.take(e, np.arange(s, s + block) % n)
        m = min(block, n - k)
        out[k : k + m] = seg[:m]
        k += m
    return out


def tc_interval(y: np.ndarray, theta: np.ndarray, lo: np.ndarray, hi: np.ndarray, B: int = B_DEFAULT, seed: int = 0) -> dict:
    t = np.arange(len(y), dtype=float)
    X = design(t, *theta)
    _, beta = lin_fit(t, y, *theta)
    fit = X @ beta
    e = y - fit
    rng = np.random.default_rng(seed)
    tcs = []
    for _ in range(B):
        yb = fit + _block_resample(e, rng)
        r = tcgrid_lm(t, yb, lo, hi, seed=int(rng.integers(1 << 30)), n_random=3,
                      budget=dict(n_tc=20, n_m=8, n_w=10, topk=3))
        tcs.append(float(r.theta[0]) - (len(y) - 1))
    q = np.quantile(tcs, QS)
    return dict(B=B, ahead_hat=float(theta[0]) - (len(y) - 1), q05=q[0], q20=q[1], q50=q[2], q80=q[3], q95=q[4],
                sd=float(np.std(tcs)))
