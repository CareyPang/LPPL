"""B5 支撑井（原型 engine.js priceLayer 的 PIT 移植）：对 ≤t 的最近 500 根 K 线做时间衰减 + 成交量加权 KDE，
取自由能 F = −ln ρ，输出当前价所在井的深度、当前 F、到下方最近井的距离。每 STEP 个交易日算一次，其间前向填充（as-of 仍成立）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOK, HL, GRID, STEP = 500, 120, 160, 5
MIN_MASS, MIN_DEPTH = 0.02, 0.04


def _landscape(x: np.ndarray, sig2: np.ndarray, w: np.ndarray, grid: np.ndarray) -> np.ndarray:
    d2 = (grid[None, :] - x[:, None]) ** 2 / (2 * sig2[:, None])
    rho = ((w / np.sqrt(sig2))[:, None] * np.exp(-np.minimum(d2, 18.0)) * (d2 < 18)).sum(0)
    dx = grid[1] - grid[0]
    return rho / max(rho.sum() * dx, 1e-300) + 1e-12


def well_features_at(x: np.ndarray, r2: np.ndarray, vol: np.ndarray, x_now: float) -> tuple[float, float, float]:
    """x: 对数典型价（旧→新），r2: 日内对数振幅方差，vol: 成交量；返回 (F_now, basin_depth, dist_below)。"""
    n = len(x)
    age = np.arange(n)[::-1]
    vmed = np.median(vol[vol > 0]) if (vol > 0).any() else 1.0
    vw = np.where(vol > 0, np.clip(np.sqrt(vol / vmed), 0.2, 5.0), 0.2)
    w = 2.0 ** (-age / HL) * vw
    mu = (w * x).sum() / w.sum()
    sd = np.sqrt((w * (x - mu) ** 2).sum() / w.sum())
    neff = w.sum() ** 2 / (w**2).sum()
    h0 = max(0.006, 0.5 * 1.06 * sd * neff ** -0.2)
    grid = np.linspace(x.min() - 4 * h0, x.max() + 4 * h0, GRID)
    rho = _landscape(x, h0**2 + r2, w, grid)
    F = -np.log(rho)
    F -= F.min()
    mins = np.where((F[1:-1] < F[:-2]) & (F[1:-1] <= F[2:]))[0] + 1
    maxs = np.where((F[1:-1] > F[:-2]) & (F[1:-1] >= F[2:]))[0] + 1
    dx = grid[1] - grid[0]
    g_now = int(np.clip(np.searchsorted(grid, x_now) - 1, 0, GRID - 1))
    depth_now, dist_below = 0.0, np.nan
    for g in mins:
        left = maxs[maxs < g]
        right = maxs[maxs > g]
        lo = left[-1] if len(left) else 0
        hi = right[0] if len(right) else GRID - 1
        mass = rho[lo : hi + 1].sum() * dx
        bar = min(F[lo] if len(left) else np.inf, F[hi] if len(right) else np.inf)
        depth = bar - F[g] if np.isfinite(bar) else F[hi if lo == 0 else lo] - F[g]
        if mass <= MIN_MASS or depth <= MIN_DEPTH:
            continue
        if lo <= g_now <= hi:
            depth_now = float(depth)
        if grid[g] < x_now - 0.03:
            dist_below = float(x_now - grid[g]) if np.isnan(dist_below) else min(dist_below, float(x_now - grid[g]))
    return float(F[g_now]), depth_now, dist_below


def rolling_wells(bars: pd.DataFrame, step: int = STEP) -> pd.DataFrame:
    """bars: 列 high/low/close/volume（已复权），索引日期。"""
    x_all = np.log((bars.high + bars.low + bars.close) / 3).to_numpy(float)
    r2_all = ((np.log(bars.high) - np.log(bars.low)) ** 2 / 12).to_numpy(float)
    vol_all = bars.volume.to_numpy(float)
    close = np.log(bars.close.to_numpy(float))
    n = len(bars)
    out = np.full((n, 3), np.nan)
    for t in range(LOOK - 1, n, step):
        s = slice(t - LOOK + 1, t + 1)
        out[t] = well_features_at(x_all[s], r2_all[s], vol_all[s], close[t])
    df = pd.DataFrame(out, index=bars.index, columns=["well_F", "well_depth", "well_dist_below"]).ffill(limit=step - 1)
    return df
