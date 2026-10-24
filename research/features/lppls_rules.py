"""把 LPPLS 多窗口扫描结果（lppls_scan）折算成每个 as-of 时点的候选分数。

R3 POWER：纯幂律合格窗口比例（pow_B<0 且 0<pow_m<1，t_c 在 (t₂, t₂+0.2dt] 内已由搜索域保证）。
R4a P-DS、R4b P-STRICT：原型 `FILTERS.ds/strict` 合格窗口比例。
R4c P-TOP：原型 TOP_RULE 合格比例 + t_c 聚类一致度（合格窗口 t_c 的 IQR 相对宽度）。
R4d LIT-DS：E7 表 3 条件 1（m∈[0.1,0.9]、ω∈[6,13]、t_c≤t₂+0.13dt、(ω/2)ln≥2.5、D≥1.2、相对误差≤0.035）
            与条件 2（m∈[0.01,1.2]、ω∈[2,25]、t_c≤t₂+0.1dt、(ω/2)ln≥2.5、D≥0.8、相对误差≤0.14）的合格比例。
R4f LIT-MS：条件 1 在三尺度窗口（短 125–240、中 240–480、长 480–750；预登记 E4 为 30–120/100–240/200–720，
            受最小窗口 125 限制改为本分组）上的分别比例。
相对误差 = sqrt(sse/n)/|均值对数价格偏差|，按 E7 的"拟合残差 RMSE 相对于价格幅度"用 sqrt(sse/n)/std(y) 近似。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..lppls.core import TOP_RULE


def _derived(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    t2 = d.n - 1
    d["ahead"] = d.tc - t2
    d["dt"] = t2
    C = np.hypot(d.C1, d.C2)
    d["D"] = np.where(C > 0, d.m * d.B.abs() / (d.w * C), np.inf)
    d["osc"] = d.w / 2 * np.log(d.tc / (d.tc - t2))  # (ω/2)·ln(...)，E7 的写法
    d["n_osc"] = d.osc / np.pi
    d["rel_err"] = np.sqrt(d.sse / d.n) / d.y_std
    return d


def rules(d: pd.DataFrame) -> pd.DataFrame:
    r = pd.DataFrame(index=d.index)
    r["power"] = (d.pow_B < 0) & (d.pow_m > 0) & (d.pow_m < 1)
    r["p_ds"] = ((d.B < 0) & d.m.between(0.01, 0.99) & d.w.between(2, 15)
                 & (d.ahead <= np.maximum(5, 0.1 * d.n)) & (d.n_osc >= 2.5) & (d.D >= 0.5))
    r["p_strict"] = ((d.B < 0) & (d.m > 0.1) & (d.m < 0.9) & (d.w > 6) & (d.w < 13)
                     & (d.ahead <= 90) & (d.n_osc >= 2.5) & (d.D >= 1) & (d.r2 >= 0.9))
    tr = TOP_RULE
    r["p_top"] = ((d.B < 0) & d.m.between(*tr["m"]) & d.w.between(*tr["w"]) & d.ahead.between(*tr["horizon"])
                  & (d.n_osc >= tr["n_osc"]) & (d.D >= tr["damping"]) & (d.r2 >= tr["r2"]))
    r["lit1"] = ((d.B < 0) & d.m.between(0.1, 0.9) & d.w.between(6, 13) & (d.ahead <= 0.13 * d.dt)
                 & (d.osc >= 2.5) & (d.D >= 1.2) & (d.rel_err <= 0.035))
    r["lit2"] = ((d.B < 0) & d.m.between(0.01, 1.2) & d.w.between(2, 25) & (d.ahead <= 0.1 * d.dt)
                 & (d.osc >= 2.5) & (d.D >= 0.8) & (d.rel_err <= 0.14))
    return r


def scores(scan: pd.DataFrame) -> pd.DataFrame:
    """scan 需含 y_std 列（窗口内对数价格标准差）。返回以 date 为索引的分数表。"""
    d = _derived(scan)
    r = rules(d)
    g = r.groupby(d.date)
    out = g.mean().add_prefix("s_")
    out["n_windows"] = g.size()
    top = d[r.p_top]
    if len(top):
        q = top.groupby("date").ahead.quantile([0.25, 0.5, 0.75]).unstack()
        out["top_tc_med"] = q[0.5]
        out["top_tc_iqr_rel"] = (q[0.75] - q[0.25]) / q[0.5].clip(lower=1)
    else:
        out["top_tc_med"] = np.nan
        out["top_tc_iqr_rel"] = np.nan
    scale = pd.cut(d.n, [0, 240, 480, 10_000], labels=["s", "m", "l"])
    for sc in ("s", "m", "l"):
        m = scale == sc
        out[f"s_lit1_{sc}"] = r.lit1[m].groupby(d.date[m]).mean()
    out["s_ratio_lppls_pow"] = (d.sse / d.pow_sse).groupby(d.date).median()
    return out
