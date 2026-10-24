"""LPPLS 核心：条件线性消元 + 代价函数 + 参数解包 + 形态过滤。

模型（Filimonov–Sornette 2013 低维参数化）::

    y(t) = A + B (tc-t)^m + C1 (tc-t)^m cos(ω ln(tc-t)) + C2 (tc-t)^m sin(ω ln(tc-t))

非线性参数 θ=(tc, m, ω)，线性参数 β=(A, B, C1, C2) 由最小二乘消去。
时间以样本内 bar 下标 0..n-1 计，tc 以 bar 为单位（tc>n-1 表示未来）。
与浏览器端 engine.js 的 linFit/solveBeta 语义一致：
    - k=4 为完整 LPPLS，k=2 为纯幂律嵌套模型（A + B (tc-t)^m）
    - tc <= 最后一个 t 时代价为 inf
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

K_LPPLS, K_POWER = 4, 2


def design(t: np.ndarray, tc: float, m: float, w: float, k: int = K_LPPLS) -> np.ndarray | None:
    dt = tc - t
    if np.any(dt <= 0):
        return None
    L = np.log(dt)
    f = np.exp(m * L)
    if k == K_POWER:
        return np.column_stack([np.ones_like(t), f])
    ph = w * L
    return np.column_stack([np.ones_like(t), f, f * np.cos(ph), f * np.sin(ph)])


def lin_fit(t: np.ndarray, y: np.ndarray, tc: float, m: float, w: float, k: int = K_LPPLS):
    """返回 (sse, beta)。不可行点返回 (inf, None)。用 lstsq（SVD）而不是显式正规方程。"""
    X = design(t, tc, m, w, k)
    if X is None:
        return np.inf, None
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ beta
    sse = float(r @ r)
    if not np.isfinite(sse):
        return np.inf, None
    return sse, beta


def sse(theta, t, y, k: int = K_LPPLS) -> float:
    return lin_fit(t, y, theta[0], theta[1], theta[2], k)[0]


@dataclass
class Fit:
    tc: float
    m: float
    w: float
    A: float
    B: float
    C1: float
    C2: float
    sse: float
    r2: float
    n: int

    @property
    def C(self) -> float:
        return float(np.hypot(self.C1, self.C2))

    @property
    def damping(self) -> float:
        """Sornette 阻尼比 D = m|B| / (ω|C|)。"""
        return float(self.m * abs(self.B) / (self.w * self.C)) if self.C > 0 else np.inf

    def n_osc(self, t0: float = 0.0) -> float:
        """样本内对数周期振荡个数 (ω/2π) ln((tc-t0)/(tc-t_end))。"""
        return float(self.w / (2 * np.pi) * np.log((self.tc - t0) / (self.tc - (self.n - 1))))

    def curve(self, t: np.ndarray) -> np.ndarray:
        X = design(t, self.tc, self.m, self.w)
        return X @ np.array([self.A, self.B, self.C1, self.C2])


def unpack(theta, t, y) -> Fit | None:
    s, beta = lin_fit(t, y, *theta)
    if beta is None:
        return None
    sst = float(((y - y.mean()) ** 2).sum())
    return Fit(float(theta[0]), float(theta[1]), float(theta[2]), *map(float, beta), s, 1 - s / sst, len(t))


# 形态过滤：与 critical.js 的 CP.TOP_RULE 一致（B<0；0.1≤m≤0.95；4≤ω≤15；1≤距今≤115 日；振荡≥1.5；阻尼≥0.3；R²≥0.8）
TOP_RULE = dict(m=(0.1, 0.95), w=(4.0, 15.0), horizon=(1, 115), n_osc=1.5, damping=0.3, r2=0.8)
# Sornette 经典过滤（long_text 3.5）：0.1<m<0.9，6<ω<13，D≥1，N_osc≥2.5，R²≥0.9
SORNETTE_RULE = dict(m=(0.1, 0.9), w=(6.0, 13.0), horizon=(1, 10**9), n_osc=2.5, damping=1.0, r2=0.9)


def qualifies(f: Fit, rule: dict = TOP_RULE) -> tuple[bool, list[str]]:
    why = []
    if not (f.B < 0):
        why.append("B>=0")
    if not (rule["m"][0] <= f.m <= rule["m"][1]):
        why.append("m")
    if not (rule["w"][0] <= f.w <= rule["w"][1]):
        why.append("w")
    h = f.tc - (f.n - 1)
    if not (rule["horizon"][0] <= h <= rule["horizon"][1]):
        why.append("horizon")
    if f.n_osc() < rule["n_osc"]:
        why.append("n_osc")
    if f.damping < rule["damping"]:
        why.append("damping")
    if f.r2 < rule["r2"]:
        why.append("r2")
    return not why, why


def default_bounds(n: int, horizon: tuple[int, int] = (1, 115)) -> tuple[np.ndarray, np.ndarray]:
    """搜索域：tc∈[n-1+h_lo, n-1+h_hi]（也允许少量样本内 tc 由上层决定），m∈[0.01,1.2]，ω∈[2,25]。
    搜索域刻意比形态过滤域宽，避免把解挤到边界上（long_text 3.5 的区分）。"""
    lo = np.array([n - 1 + horizon[0], 0.01, 2.0])
    hi = np.array([n - 1 + horizon[1], 1.2, 25.0])
    return lo, hi
