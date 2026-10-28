"""阶段 3b 加难度合成数据（预登记方案 §8）。

场景（scenario）：
  base       : 与 lppls_synth.sample 相同的参数分布
  weak_osc   : 振荡幅度 |C| 只有阻尼上限的 5%–20%（弱对数周期）
  short      : 窗口长度 n=60 或 90
  boundary   : m 接近 0.1 或 0.9，ω 接近 6 或 13（过滤器边界）
  far_tc     : t_c 距窗口末端 60–150 日（搜索域更宽）
"""
from __future__ import annotations

import numpy as np

from ..lppls.core import design
from .lppls_synth import Truth, make_noise

SCENARIOS = ("base", "weak_osc", "short", "boundary", "far_tc")


def sample_hard(scenario: str, sigma: float = 0.02, noise: str = "iid", seed: int = 0, n: int = 250):
    rng = np.random.default_rng(seed)
    horizon = (5, 60)
    m_lo, m_hi, w_lo, w_hi, c_lo, c_hi = 0.2, 0.8, 6.0, 12.0, 0.3, 1.0
    if scenario == "weak_osc":
        c_lo, c_hi = 0.05, 0.2
    elif scenario == "short":
        n = int(rng.choice([60, 90]))
        horizon = (3, 30)
    elif scenario == "boundary":
        m_lo, m_hi = (0.1, 0.15) if rng.random() < 0.5 else (0.85, 0.9)
        w_lo, w_hi = (6.0, 6.5) if rng.random() < 0.5 else (12.5, 13.0)
    elif scenario == "far_tc":
        horizon = (60, 150)
    elif scenario != "base":
        raise ValueError(scenario)
    tc = n - 1 + rng.uniform(*horizon)
    m, w = rng.uniform(m_lo, m_hi), rng.uniform(w_lo, w_hi)
    A = np.log(3000.0) + rng.normal(0, 0.1)
    rise = rng.uniform(0.2, 0.8)
    B = -rise / (tc**m - (tc - (n - 1)) ** m)
    C = rng.uniform(c_lo, c_hi) * m * abs(B) / w
    ph = rng.uniform(0, 2 * np.pi)
    C1, C2 = C * np.cos(ph), C * np.sin(ph)
    t = np.arange(n, dtype=float)
    y = design(t, tc, m, w) @ np.array([A, B, C1, C2]) + make_noise(n, sigma, noise, rng)
    return t, y, Truth(tc, m, w, A, B, C1, C2, n, sigma, noise, seed)
