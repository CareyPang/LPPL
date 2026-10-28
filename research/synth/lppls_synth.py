"""合成 LPPLS 序列：已知真值，用于优化器与参数回收检验。

噪声模型三档：
  iid   : 高斯白噪声 σ
  ar1   : AR(1) 残差（φ=0.5），更接近真实日线残差
  garch : GARCH(1,1) 残差（持续波动聚集）
真值参数从 Sornette 形态域内随机抽（m∈[0.2,0.8], ω∈[6,12], 阻尼≥1），
tc 位于样本末尾之后 5–60 bar。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..lppls.core import design


@dataclass
class Truth:
    tc: float
    m: float
    w: float
    A: float
    B: float
    C1: float
    C2: float
    n: int
    sigma: float
    noise: str
    seed: int

    def theta(self):
        return np.array([self.tc, self.m, self.w])


def make_noise(n: int, sigma: float, kind: str, rng: np.random.Generator) -> np.ndarray:
    z = rng.standard_normal(n)
    if kind == "iid":
        return sigma * z
    if kind == "ar1":
        phi = 0.5
        e = np.empty(n)
        e[0] = z[0]
        for i in range(1, n):
            e[i] = phi * e[i - 1] + z[i]
        return sigma * e * np.sqrt(1 - phi**2)
    if kind == "garch":
        a0, a1, b1 = 0.05, 0.1, 0.85
        h = np.empty(n)
        e = np.empty(n)
        h[0] = a0 / (1 - a1 - b1)
        e[0] = np.sqrt(h[0]) * z[0]
        for i in range(1, n):
            h[i] = a0 + a1 * e[i - 1] ** 2 + b1 * h[i - 1]
            e[i] = np.sqrt(h[i]) * z[i]
        return sigma * e / np.sqrt(a0 / (1 - a1 - b1))
    raise ValueError(kind)


def sample(n: int = 250, sigma: float = 0.02, noise: str = "iid", seed: int = 0, horizon=(5, 60)) -> tuple[np.ndarray, np.ndarray, Truth]:
    rng = np.random.default_rng(seed)
    tc = n - 1 + rng.uniform(*horizon)
    m = rng.uniform(0.2, 0.8)
    w = rng.uniform(6.0, 12.0)
    A = np.log(3000.0) + rng.normal(0, 0.1)
    # 让样本内幂律总涨幅在 20%–80% 之间
    rise = rng.uniform(0.2, 0.8)
    B = -rise / (tc**m - (tc - (n - 1)) ** m)
    # 阻尼 D = m|B|/(ω C) >= 1  => C <= m|B|/ω
    C = rng.uniform(0.3, 1.0) * m * abs(B) / w
    ph = rng.uniform(0, 2 * np.pi)
    C1, C2 = C * np.cos(ph), C * np.sin(ph)
    t = np.arange(n, dtype=float)
    y = design(t, tc, m, w) @ np.array([A, B, C1, C2]) + make_noise(n, sigma, noise, rng)
    return t, y, Truth(tc, m, w, A, B, C1, C2, n, sigma, noise, seed)
