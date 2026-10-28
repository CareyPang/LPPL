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
    d = df.reset_index(drop=True)
    t2 = d.n - 1
    d["ahead"] = d.tc - t2
    d["dt"] = t2
    C = np.hypot(d.C1, d.C2)
    d["D"] = np.where(C > 0, d.m * d.B.abs() / (d.w * C), np.inf)
    # (ω/2)·ln|(t_c−t₁)/(t_c−t₂)|，E7 的写法；取绝对值以支持 t_c 落在 t₂ 之前（§17.4）
    d["osc"] = d.w / 2 * np.log(np.abs(d.tc) / np.maximum(np.abs(d.tc - t2), 1e-3))
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
    r["lit1"] = ((d.B < 0) & d.m.between(0.1, 0.9) & d.w.between(6, 13) & d.ahead.between(-0.15 * d.dt, 0.13 * d.dt)
                 & (d.osc >= 2.5) & (d.D >= 1.2) & (d.rel_err <= 0.035))
    # §17.2 阻尼阈值变体（1.2 为 E7 表 3 条件 1；0.8/1.0 为文献另两档）与"纯形态框"（无阻尼/误差条件）
    r["lit1_d10"] = ((d.B < 0) & d.m.between(0.1, 0.9) & d.w.between(6, 13) & d.ahead.between(-0.15 * d.dt, 0.13 * d.dt)
                     & (d.osc >= 2.5) & (d.D >= 1.0) & (d.rel_err <= 0.035))
    r["lit1_d08"] = ((d.B < 0) & d.m.between(0.1, 0.9) & d.w.between(6, 13) & d.ahead.between(-0.15 * d.dt, 0.13 * d.dt)
                     & (d.osc >= 2.5) & (d.D >= 0.8) & (d.rel_err <= 0.035))
    r["box"] = (d.B < 0) & d.m.between(0.1, 0.9) & d.w.between(6, 13) & d.ahead.between(0, 90)
    r["lit2"] = ((d.B < 0) & d.m.between(0.01, 1.2) & d.w.between(2, 25) & d.ahead.between(-0.2 * d.dt, 0.12 * d.dt)
                 & (d.osc >= 2.5) & (d.D >= 0.8) & (d.rel_err <= 0.14))
    return r


# §17.4 多尺度（E4 §4.1）：短 30–120、中 100–240、长 200–720 日，各算各的置信度，不合并
SCALES = {"S": (30, 120), "M": (100, 240), "L": (200, 720)}
SCALES_XS = {"XS": (15, 30)}  # §17.6 探索尺度，单独扫描、单独报告
# §17.14 产品侧尺度：FCO 公开标签（交接包 F06），窗口长度为本项目工作假设；研究层 SCALES 保持 E4 三尺度以复现已完成的开发段评价。
SCALES_FCO = {"1-3m": (21, 63), "6-12m": (127, 252), "12-24m": (253, 504)}
# FCO 原站六档（F06：2–4 周 / 1–3 月 / 3–6 月 / 6–12 月 / 12–24 月 / 2–6 年），仅产品显示用；评价仍用 SCALES_FCO 三档
SCALES_FCO6 = {"2-4w": (10, 20), "1-3m": (21, 63), "3-6m": (64, 126), "6-12m": (127, 252), "12-24m": (253, 504), "2-6y": (505, 1500)}
SCALE_EVIDENCE = {"2-4w": "none", "1-3m": "none", "3-6m": "none", "6-12m": "dev", "12-24m": "dev", "2-6y": "none"}  # 1–3 月：开发段 0 稳健组合，只作描述性显示
SCALE_NAMES = {"1-3m": "1–3 月（21–63 日）", "6-12m": "6–12 月（127–252 日）", "12-24m": "12–24 月（253–504 日）", "2-4w": "2–4 周（10–20 日）", "3-6m": "3–6 月（64–126 日）", "2-6y": "2–6 年（505–1500 日）"}
# §17.4 阈值网格（不挑单一最优，报告稳健区域）
GRID_D = (0.5, 0.8, 1.0, 1.2)
GRID_W = {"w4_25": (4, 25), "w6_13": (6, 13)}
GRID_M = {"m0_1": (0.0, 1.0), "m01_09": (0.1, 0.9)}
GRID_E = {"eNone": np.inf, "e014": 0.14, "e0035": 0.035}
# Jiang 2010 式 A 股过滤：Lomb 峰频与拟合 ω 一致（相对差 ≤ 0.1）且残差 DF t ≤ −2.86（渐近 5%）
JIANG_TOL, JIANG_DF = 0.10, -2.86


def grid_rules(d: pd.DataFrame) -> pd.DataFrame:
    """E7 条件 1 的框架（B<0、t_c∈[t₂−0.15dt, t₂+0.13dt]、(ω/2)ln≥2.5）× 网格阈值；另加 Jiang 变体。"""
    base = (d.B < 0) & d.ahead.between(-0.15 * d.dt, 0.13 * d.dt) & (d.osc >= 2.5)
    r = {}
    for dk in GRID_D:
        for wk, (wl, wh) in GRID_W.items():
            for mk, (ml, mh) in GRID_M.items():
                for ek, emax in GRID_E.items():
                    r[f"g_D{dk}_{wk}_{mk}_{ek}"] = (base & d.m.between(ml, mh) & d.w.between(wl, wh)
                                                    & (d.D >= dk) & (d.rel_err <= emax))
    if "lomb_w" in d:
        jiang = (base & d.m.between(0.0, 1.0) & d.w.between(4, 25)
                 & ((d.lomb_w - d.w).abs() / d.w <= JIANG_TOL) & (d.df_t <= JIANG_DF))
        r["g_jiang"] = jiang
        r["g_jiang_strict"] = jiang & d.m.between(0.1, 0.9) & d.w.between(6, 13)
    # FCO 平台公开的四套合格过滤集（文献 §16.16，前端原文数值）；公开文字未给 t_c 范围，故只用 B<0 与 m∈(0,1]
    fco = (d.B < 0) & (d.m > 0)
    r["g_fco_standard"] = fco & (d.m <= 1) & d.w.between(2, 25) & (d.D >= 0.5) & (d.osc >= 2.5)
    r["g_fco_early"] = fco & (d.m <= 1) & d.w.between(2, 25) & (d.D >= 0.0) & (d.osc >= 1.5)
    r["g_fco_end"] = fco & (d.m <= 1) & d.w.between(2, 25) & (d.D >= 0.8) & (d.osc >= 2.5)
    r["g_fco_pure"] = fco & (d.m <= 0.9) & d.w.between(5, 13) & (d.D >= 0.5) & (d.osc >= 2.5)
    return pd.DataFrame(r, index=d.index)


def lagrange_pick(d: pd.DataFrame, p: int = 7) -> pd.Series:
    """§17.4-5 Lagrange 正则选窗（Demos–Sornette 2019 式 (4)）：对固定 t₂ 的全部窗口，
    χ²_np = SSE/(dt−p)，λ = χ²_np 对 dt 的 OLS 斜率（经验估计的"过拟合倾向"），
    χ²_λ = χ²_np − λ·dt；返回每个 as-of 日期 χ²_λ 最小窗口的行索引。"""
    chi = d.sse / (d.n - p).clip(lower=1)
    picks = {}
    for date, idx in d.groupby("date").indices.items():
        x, c = d.n.to_numpy(float)[idx], chi.to_numpy(float)[idx]
        if len(idx) < 3:
            picks[date] = d.index[idx[int(np.argmin(c))]]
            continue
        lam = np.polyfit(x, c, 1)[0]
        picks[date] = d.index[idx[int(np.argmin(c - lam * x))]]
    return pd.Series(picks)


def multiscale_scores(scan: pd.DataFrame) -> pd.DataFrame:
    """每个 as-of 日期、每个尺度一行一组列：置信度 = 该尺度窗口中合格比例（E4 定义）。
    列名 <rule>__<S|M|L>；另给 n_<scale>。"""
    d = _derived(scan)
    r = pd.concat([rules(d), grid_rules(d)], axis=1)
    out = {}
    for sc, (lo, hi) in SCALES.items():
        msk = d.n.between(lo, hi)
        g = r[msk].groupby(d.date[msk])
        m = g.mean()
        m.columns = [f"{c}__{sc}" for c in m.columns]
        out[sc] = m
        out[sc][f"n_{sc}"] = g.size()
    return pd.concat(out.values(), axis=1)


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
    gr = grid_rules(d)
    for c in ("g_jiang", "g_jiang_strict", "g_D0.8_w4_25_m0_1_e014", "g_D1.0_w6_13_m01_09_e014"):
        if c in gr:
            out[f"s_{c}"] = gr[c].groupby(d.date).mean()
    for sc_, (lo, hi) in SCALES.items():
        msk = d.n.between(lo, hi)
        out[f"s_box__{sc_}"] = r.box[msk].groupby(d.date[msk]).mean() if msk.any() else np.nan
    ms_cols = [f"s_box__{k}" for k in SCALES]
    ms = out[ms_cols].fillna(0.0)
    out["s_combo_mean"] = ms.mean(axis=1)
    out["s_combo_max"] = ms.max(axis=1)
    out["s_combo_n2"] = ((ms >= 0.1).sum(axis=1) >= 2).astype(float)
    pick = lagrange_pick(d)
    lagf = d.loc[pick.to_numpy()].set_index(pick.index)
    lagr = r.loc[pick.to_numpy()].set_index(pick.index)
    out["lag_dt"] = lagf.n.reindex(out.index)
    if "y_first" in lagf and "y_last" in lagf:
        out["lag_size"] = (np.exp(lagf.y_last - lagf.y_first) - 1).reindex(out.index)
    out["lag_ahead"] = lagf.ahead.reindex(out.index)
    for c in ("box", "p_strict", "lit1", "lit2"):
        out[f"lag_{c}"] = lagr[c].astype(float).reindex(out.index)
    return out.astype(float)


def rules_ab(d: pd.DataFrame) -> pd.DataFrame:
    """§17.4-7 Johansen–Sornette 1999 反泡沫合格条件（LPPLS_ANCHOR=start 扫描；t_c 在窗口起点之前，t₁=0）：
    t_c<0、B<0（峰后衰减）、m∈(0,1)、ω∈[2,25]、D≥0.5、振荡数 (ω/2)·ln((t₂−t_c)/(t₁−t_c))≥2.5；
    ab_strict 另加 m∈[0.1,0.9]、ω∈[5,13]（对应 FCO PURE 的窄域）。"""
    t2 = d.n - 1
    osc_ab = d.w / 2 * np.log(np.maximum(t2 - d.tc, 1e-3) / np.maximum(-d.tc, 1e-3))
    base = (d.tc < 0) & (d.B < 0) & d.m.between(0.01, 0.99) & (d.D >= 0.5) & (osc_ab >= 2.5)
    return pd.DataFrame({"ab": base & d.w.between(2, 25), "ab_strict": base & d.m.between(0.1, 0.9) & d.w.between(5, 13),
                         "ab_loose": (d.tc < 0) & (d.B < 0) & d.m.between(0.01, 0.99) & d.w.between(2, 25)}, index=d.index)
