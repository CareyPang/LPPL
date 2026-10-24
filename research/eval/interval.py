"""顶部区间模型 T-INT（预登记 v1.2 §12.3）。

输入某时点所有合格窗口的 t_c（相对 as-of 日的交易日数 ahead），输出 t_c 经验分布的分位区间；
评分为区间得分 IS_alpha（Gneiting & Raftery 2007），基线为固定区间 [t+1, t+20]。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_WINDOWS = 5
CONFIGS = {f"{wt}_{lo}-{hi}": (wt, lo / 100, hi / 100) for wt in ("eq", "invsse") for lo, hi in ((10, 90), (5, 95))}
BASELINE = (1.0, 20.0)


def wquantile(x: np.ndarray, w: np.ndarray, qs) -> np.ndarray:
    o = np.argsort(x)
    x, w = x[o], w[o]
    cw = (np.cumsum(w) - 0.5 * w) / w.sum()
    return np.interp(qs, cw, x)


def interval(ahead: np.ndarray, sse: np.ndarray | None, weight: str, lo: float, hi: float) -> tuple[float, float]:
    if len(ahead) < MIN_WINDOWS:
        return (np.nan, np.nan)
    w = np.ones(len(ahead)) if weight == "eq" or sse is None else 1.0 / np.maximum(sse, 1e-12)
    a, b = wquantile(np.asarray(ahead, float), w, [lo, hi])
    return float(a), float(b)


def interval_score(L, U, t_star, alpha: float = 0.2) -> np.ndarray:
    L, U, t = (np.asarray(v, float) for v in (L, U, t_star))
    return (U - L) + 2 / alpha * (L - t) * (t < L) + 2 / alpha * (t - U) * (t > U)


def intervals_by_date(d: pd.DataFrame, mask: pd.Series, half_width_scale: float = 1.0) -> pd.DataFrame:
    """d 为 lppls_rules._derived 的输出（含 date、ahead、sse），mask 为合格窗口布尔列。
    返回每个 date × 配置的 (L, U)；half_width_scale 为校准段保形缩放（开发段为 1）。"""
    rows = []
    for date, g in d[mask].groupby("date"):
        row = {"date": date, "n_ok": len(g)}
        for name, (wt, lo, hi) in CONFIGS.items():
            a, b = interval(g.ahead.to_numpy(), g.sse.to_numpy(), wt, lo, hi)
            if half_width_scale != 1.0 and np.isfinite(a):
                mid = 0.5 * (a + b)
                a, b = mid - half_width_scale * (mid - a), mid + half_width_scale * (b - mid)
            row[f"{name}_L"], row[f"{name}_U"] = a, b
        rows.append(row)
    cols = ["date", "n_ok"] + [f"{n}_{e}" for n in CONFIGS for e in ("L", "U")]
    return pd.DataFrame(rows, columns=cols)


def evaluate(iv: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """events: 列 date（as-of，Y_top=1 的时点）、t_star（共识顶距 as-of 的交易日数）。
    只在事件时点上评分；无区间（n_ok<5）的时点按基线区间计（如实计入未输出的代价）。"""
    e = events.merge(iv, on="date", how="left")
    out = []
    bl = interval_score(*BASELINE, e.t_star)
    out.append(dict(config="baseline_1-20", IS=bl.mean(), coverage=((e.t_star >= 1) & (e.t_star <= 20)).mean(),
                    width_med=19.0, n=len(e), n_with_interval=len(e)))
    for name in CONFIGS:
        L, U = e[f"{name}_L"].to_numpy(), e[f"{name}_U"].to_numpy()
        has = np.isfinite(L)
        L = np.where(has, L, BASELINE[0])
        U = np.where(has, U, BASELINE[1])
        s = interval_score(L, U, e.t_star)
        out.append(dict(config=name, IS=s.mean(), coverage=((e.t_star >= L) & (e.t_star <= U)).mean(),
                        width_med=float(np.median((U - L)[has])) if has.any() else np.nan, n=len(e),
                        n_with_interval=int(has.sum()), IS_paired_delta=(s - bl).mean()))
    return pd.DataFrame(out)
