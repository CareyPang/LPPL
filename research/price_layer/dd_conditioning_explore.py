"""探索性（exploratory，非登记检验）：回撤深度的条件变量排序核实——两融 / 涨幅与加速度 / 估值 / 波动率变化。

(1) 事件级：P1 的 PS 顶（drawdown_table.top_events），顶日各特征 vs log(1+max_dd) 的 Spearman 相关与 n。
(2) 周频面板：每个 as-of 日 t，目标 y = 未来 250 交易日最低价相对 P_t 的对数回撤；特征（全部只用 t 及以前、按发布滞后）：
    ret500 = 2 年对数涨幅；accel = GSY 2019 加速度 (P_t/P_{t-500}) − (P_{t-250}/P_{t-500})；dvol = 60 日年化波动率的 1 年变化；
    pe_pct = PE 在过去 10 年（≥36 月）中的分位（月频，滞后 1 月）；margin_yoy = 融资余额 250 日对数变化（A 股 SSE+SZSE，滞后 1 日；
    美股 FINRA debit，月频，滞后 1 月）。
    样本外：逐年扩展窗，训练用 ≤ 年份 Y−2 的 as-of（留 1 年间隔避免 250 日目标重叠），预测年份 Y；单变量线性分位回归 vs 同训练集无条件分位。
    指标：pinball loss 比（<1 = 优于无条件），q ∈ {0.5, 0.2}（0.2 = 深回撤尾部）；同一组共同可用样本上比较。
同一事件/年份在多指数间高度相关，不做显著性声明，只做排序探索。用法：python -m research.price_layer.dd_conditioning_explore
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from statsmodels.regression.quantile_regression import QuantReg

from ..data.valuation import LAG_MONTHS
from ..data.valuation import load as load_pe
from .drawdown_table import A_SHARE, EXT, FLOOR_MISMATCH, load_logp, top_events

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/price_layer/dd_conditioning_explore.md"
H, STEP, QS = 250, 5, (0.5, 0.2)
FEATS = ["ret500", "accel", "dvol", "pe_pct", "margin_yoy"]


def a_margin() -> pd.Series:
    sse = pd.read_parquet(ROOT / "data/cache/margin/sse_margin.parquet").set_index("date")["fin_balance"].astype(float)
    sz = pd.read_parquet(ROOT / "data/cache/margin/szse_margin.parquet").set_index("date")["融资余额"].astype(float) * 1e8
    m = pd.concat([sse, sz], axis=1).dropna()
    m = m[(m.iloc[:, 0] > 0) & (m.iloc[:, 1] > 0)].sum(axis=1)
    m = m.shift(1, freq="D")
    return m[~m.index.duplicated(keep="last")].sort_index()  # T+1 早间发布


def us_margin() -> pd.Series:
    x = pd.read_excel(ROOT / "data/cache/margin_us/finra_margin_statistics.xlsx")
    s = pd.Series(x.iloc[:, 1].to_numpy(float), index=pd.PeriodIndex(x.iloc[:, 0].astype(str), freq="M"))
    s = s.sort_index()
    s.index = (s.index + 2).to_timestamp() - pd.Timedelta(days=1)  # 月 m 的数据在 m+1 月下旬发布 → m+1 月末可用
    return s[~s.index.duplicated(keep="last")]


def pe_pct(sym: str) -> pd.Series | None:
    if sym not in A_SHARE or sym in FLOOR_MISMATCH:
        return None
    pe = load_pe(sym).dropna()
    vals = []
    for i in range(len(pe)):
        w = pe.iloc[max(0, i - 119): i + 1]
        vals.append((w.iloc[-1] >= w).mean() if len(w) >= 36 else np.nan)
    s = pd.Series(vals, index=pe.index + pd.DateOffset(months=LAG_MONTHS))
    return s[~s.index.duplicated(keep="last")].sort_index()


def features(sym: str, lp: pd.Series) -> pd.DataFrame:
    p = np.exp(lp)
    f = pd.DataFrame(index=lp.index)
    f["ret500"] = lp - lp.shift(500)
    f["accel"] = p / p.shift(500) - p.shift(250) / p.shift(500)
    rv = lp.diff().rolling(60).std() * np.sqrt(250)
    f["dvol"] = rv - rv.shift(250)
    pp = pe_pct(sym)
    f["pe_pct"] = pp.reindex(f.index, method="ffill") if pp is not None else np.nan
    m = a_margin() if sym in A_SHARE else (us_margin() if sym in ("SPX", "NDX") else None)
    if m is not None:
        mm = m.reindex(f.index.union(m.index)).ffill().reindex(f.index)
        lm = np.log(mm)
        f["margin_yoy"] = lm - lm.shift(250)
        f.loc[mm.index < m.index.min() + pd.Timedelta(days=380), "margin_yoy"] = np.nan
    else:
        f["margin_yoy"] = np.nan
    x = lp.to_numpy()
    fut = np.full(len(x), np.nan)
    for i in range(len(x) - H):
        fut[i] = x[i + 1: i + H + 1].min() - x[i]
    f["y"] = fut
    f["sym"] = sym
    return f


def pinball(y, q, tau):
    d = y - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def oos(panel: pd.DataFrame, feat: str, tau: float) -> dict | None:
    d = panel[[feat, "y", "sym"]].dropna()
    d = d.assign(yr=d.index.year)
    pm, pu, n, yrs = [], [], 0, []
    for Y in sorted(d.yr.unique()):
        tr, te = d[d.yr <= Y - 2], d[d.yr == Y]
        if len(tr) < 150 or tr.yr.nunique() < 3 or not len(te):
            continue
        X = np.column_stack([np.ones(len(tr)), tr[feat].to_numpy()])
        try:
            b = QuantReg(tr.y.to_numpy(), X).fit(q=tau).params
        except Exception:  # noqa: BLE001
            continue
        qm = b[0] + b[1] * te[feat].to_numpy()
        qu = np.quantile(tr.y, tau)
        pm.append(pinball(te.y.to_numpy(), qm, tau) * len(te))
        pu.append(pinball(te.y.to_numpy(), np.full(len(te), qu), tau) * len(te))
        n += len(te)
        yrs.append(int(Y))
    if not n:
        return None
    return {"ratio": round(sum(pm) / sum(pu), 3), "n_oos": n, "years": f"{yrs[0]}–{yrs[-1]}", "n_years": len(yrs)}


def main() -> None:
    syms = A_SHARE + list(EXT)
    lps = {s: load_logp(s) for s in syms}
    fr = {s: features(s, lps[s]) for s in syms}
    # (1) 事件级
    ev = []
    for s in syms:
        for e in top_events(s, lps[s]):
            t = pd.Timestamp(e["top"])
            row = {"sym": s, "top": e["top"], "max_dd": e["max_dd"], "run_up": e["run_up"]}
            row.update({k: fr[s].loc[t, k] for k in FEATS})
            ev.append(row)
    ev = pd.DataFrame(ev)
    ev["ldd"] = np.log1p(ev.max_dd)
    ev["lrun"] = np.log1p(ev.run_up)
    ev_rows = []
    for k in ["lrun"] + FEATS:
        for grp, d in [("all", ev), ("A", ev[ev.sym.isin(A_SHARE)])]:
            dd = d[[k, "ldd"]].dropna()
            if len(dd) >= 5:
                r, p = spearmanr(dd[k], dd.ldd)
                ev_rows.append({"feat": k, "group": grp, "n": len(dd), "n_top_months": d.loc[dd.index, "top"].str[:7].nunique(),
                                "spearman": round(float(r), 3), "p_naive": round(float(p), 3)})
    # (2) 面板
    res = []
    for name, ss in [("A股6指数", A_SHARE), ("外部4指数", list(EXT)), ("全部", syms)]:
        panel = pd.concat([fr[s].iloc[::STEP] for s in ss])
        for k in FEATS:
            for tau in QS:
                r = oos(panel, k, tau)
                if r:
                    res.append({"sample": name, "feat": k, "tau": tau, **r})
        # 共同样本：A 股 2011+（两融可用）上所有特征同场比较
    common = pd.concat([fr[s].iloc[::STEP] for s in A_SHARE]).dropna(subset=["margin_yoy", "ret500", "accel", "dvol", "y"])
    for k in ["ret500", "accel", "dvol", "margin_yoy", "pe_pct"]:
        for tau in QS:
            r = oos(common, k, tau)
            if r:
                res.append({"sample": "A股共同样本(两融可用)", "feat": k, "tau": tau, **r})
    us = pd.concat([fr[s].iloc[::STEP] for s in ("SPX", "NDX")]).dropna(subset=["margin_yoy", "y"])
    for k in ["ret500", "accel", "dvol", "margin_yoy"]:
        for tau in QS:
            r = oos(us, k, tau)
            if r:
                res.append({"sample": "美股共同样本(FINRA 1998+)", "feat": k, "tau": tau, **r})
    evd, rd = pd.DataFrame(ev_rows), pd.DataFrame(res)
    md = ["# 回撤深度条件变量排序核实（探索性，exploratory；非登记检验）", "",
          "事件级：PS 顶 → 后一谷 log(1+max_dd)（越负越深）与顶日特征的 Spearman；同月多指数非独立，p 值为朴素值仅供参考。", "",
          evd.to_markdown(index=False), "",
          f"面板：周频 as-of，目标 = 未来 {H} 日对数最大回撤；逐年扩展窗（训练 ≤Y−2）单变量分位回归 vs 无条件分位；ratio<1 表示优于无条件。", "",
          rd.to_markdown(index=False), ""]
    OUT.write_text("\n".join(md))
    ev.to_csv(OUT.with_suffix(".events.csv"), index=False)
    print("\n".join(md))
    json.dump({"events": evd.to_dict("records"), "panel": rd.to_dict("records")}, open(OUT.with_suffix(".json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
