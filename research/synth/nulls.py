"""零假设序列（没有 LPPLS 泡沫），用于测误报率（预登记方案 §8）。

  gbm        : 带漂移的随机游走（对数价格）
  garch      : GARCH(1,1) 收益
  ar1        : AR(1) 收益
  power_only : 纯幂律加速（C=0，无振荡）+ iid 噪声
  nonnormal  : 非正态二维线性系统（Troude 等 2024 的伪临界机制）：
               dx = A x dt + dW，A 稳定但非正态，瞬态放大产生类似临界慢化的假象；输出第一分量的累计值
"""
from __future__ import annotations

import numpy as np

from ..lppls.core import design
from .lppls_synth import make_noise

NULLS = ("gbm", "garch", "ar1", "power_only", "nonnormal")


def sample_null(kind: str, n: int = 250, sigma: float = 0.02, seed: int = 0, drift: float = 0.0005):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    if kind == "gbm":
        r = drift + sigma * rng.standard_normal(n)
        return t, np.log(3000.0) + np.cumsum(r)
    if kind in ("garch", "ar1"):
        r = drift + make_noise(n, sigma, kind, rng)
        return t, np.log(3000.0) + np.cumsum(r)
    if kind == "power_only":
        tc = n - 1 + rng.uniform(5, 60)
        m = rng.uniform(0.2, 0.8)
        rise = rng.uniform(0.2, 0.8)
        B = -rise / (tc**m - (tc - (n - 1)) ** m)
        y = design(t, tc, m, 7.0) @ np.array([np.log(3000.0), B, 0.0, 0.0])
        return t, y + make_noise(n, sigma, "iid", rng)
    if kind == "nonnormal":
        # 非正态矩阵：特征值 -0.05, -0.05（稳定），但大非对角项 k 造成瞬态增长
        k = rng.uniform(5.0, 20.0)
        a = np.array([[-0.05, k], [0.0, -0.05]])
        x = np.zeros(2)
        out = np.empty(n)
        for i in range(n):
            x = x + a @ x * 0.01 + np.sqrt(0.01) * rng.standard_normal(2) * 0.1
            out[i] = x[0]
        y = out / (np.std(out) + 1e-12) * sigma * np.sqrt(n) / 3
        return t, np.log(3000.0) + y
    raise ValueError(kind)
