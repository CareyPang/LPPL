# ruff: noqa: E402, E702
"""Phase 2：逃顶价格——报警后"剩余涨幅"（开发段 6 指数 + 100 成分股样本；不重拟合；描述性，dev_only）。
报警 = FCO 尺度 box 置信度 ≥ 0.10（合格窗 ≥ 3）的 as-of t。目标 y = max_{t<s≤t+250} P_s / P_t − 1（250 日内的最大剩余涨幅）。
2a：LPPLS 渐近值 A（合格窗口中位）→ 隐含顶价 exp(A)，隐含剩余涨幅 u_A = exp(A)/P_t − 1；报 u_A 与 y 的偏差分布、Spearman、
    以及若 250 日内有合格顶时 exp(A)/P_top 的分布。
2b：剩余涨幅条件分位 τ∈{0.2,0.5,0.8}：特征 [u_A, run-up（尺度最短窗涨幅）, m 中位, ω 中位, t_c 提前量中位]，逐年扩展窗（训练 ≤Y−2 且标签终点早于测试年），
    pinball 比值 vs 无条件分位，250 日块 bootstrap 90% 区间；通过参考 §21.5 口径：τ=0.5 比值 90% 上界 < 1。
用法：LPPLS_BOX=v2 PYTHONPATH=. python scripts/audit_stock_math/exp15_remaining_upside.py"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import QuantileRegressor

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.eval.dataset import price_series
from research.eval.precision_baseline import INDEXES, OUT, SCALES, event_dates
from research.features.lppls_rules import _derived, rules
from research.price_layer.e_dev import block_ci, pinball

EX = {2007, 2008, 2014, 2015}
H = 250
FEATS = ["u_A", "runup", "m_med", "w_med", "ahead_med"]


def panel(sym: str, feat_dir: str, lo_date: str) -> pd.DataFrame:
    logp = price_series(sym); cal = logp.index; lp = logp.to_numpy(); close = np.exp(lp)
    sc = pd.read_parquet(f"data/features/{feat_dir}/{sym}.parquet"); sc = sc[(sc.date >= lo_date) & (sc.date <= "2018-12-31")]
    if sc.empty:
        return pd.DataFrame()
    pos = pd.Series(np.arange(len(lp)), index=cal); end = pos.reindex(sc.date).to_numpy()
    sc = sc.assign(y_std=[lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)])
    d = _derived(sc); d["box"] = rules(d).box.to_numpy()
    tops = np.sort(cal.get_indexer(event_dates(sym, "top"))); tops = tops[tops >= 0]
    rows = []
    for scn, (lo, hi) in SCALES.items():
        m = d.n.between(lo, hi)
        for date, g in d[m].groupby("date"):
            ok = g[g.box]
            if len(ok) / len(g) < 0.10 or len(ok) < 3:
                continue
            tp = int(pos[date])
            if tp + H >= len(close):
                continue
            pt = close[tp]
            A_med = float(np.median(ok.A))
            nmin = int(ok.n.min())
            nxt = tops[tops > tp]; has = len(nxt) > 0 and nxt[0] - tp <= H
            rows.append(dict(symbol=sym, scale=scn, date=date, yr=date.year, yend=cal[tp + H], n_ok=len(ok),
                             u_A=np.exp(A_med) / pt - 1, runup=float(lp[tp] - lp[tp + 1 - nmin]), m_med=float(ok.m.median()), w_med=float(ok.w.median()),
                             ahead_med=float(ok.ahead.median()), y=float(close[tp + 1 : tp + H + 1].max() / pt - 1),
                             has_top=bool(has), top_ratio=(np.exp(A_med) / close[nxt[0]] if has else np.nan), up_to_top=(close[nxt[0]] / pt - 1 if has else np.nan)))
    return pd.DataFrame(rows)


def qreg(P: pd.DataFrame, tau: float):
    d = P.set_index("date").sort_index(); d = d.assign(yr=d.index.year)
    rows = []
    for Y in sorted(d.yr.unique()):
        te = d[d.yr == Y]; tr = d[(d.yr <= Y - 2) & (d.yend < te.index.min())]
        if len(tr) < 100 or tr.yr.nunique() < 3 or not len(te):
            continue
        mdl = QuantileRegressor(quantile=tau, alpha=0.0, solver="highs").fit(tr[FEATS].to_numpy(), tr.y.to_numpy())
        lm = pinball(te.y.to_numpy(), mdl.predict(te[FEATS].to_numpy()), tau)
        lb = pinball(te.y.to_numpy(), np.full(len(te), np.quantile(tr.y, tau)), tau)
        rows.append(pd.DataFrame(dict(loss_m=lm, loss_b=lb, sym=te.symbol.to_numpy(), yr=Y), index=te.index))
    return pd.concat(rows) if rows else None


if __name__ == "__main__":
    P = pd.concat([panel(s, "lppls_v2", "2000-01-01").assign(group="index") for s in INDEXES]
                  + [panel(p.stem, "lppls_v2_lite_stk100", "2010-01-01").assign(group="stock") for p in sorted(Path("data/features/lppls_v2_lite_stk100").glob("*.parquet"))])
    P = P[P.u_A.notna() & np.isfinite(P.u_A)]
    OUT.mkdir(parents=True, exist_ok=True); P.to_csv(OUT / "remaining_upside_panel.csv", index=False)
    pd.set_option("display.width", 220)
    print("panel", P.groupby(["group", "scale"]).size().to_dict())
    print("\n== 2a 隐含剩余涨幅 u_A 与实际 250 日最大剩余涨幅 y")
    for (grp, scn), g in P.groupby(["group", "scale"]):
        ex = g[~g.yr.isin(EX)]
        r = spearmanr(g.u_A, g.y).statistic; rx = spearmanr(ex.u_A, ex.y).statistic if len(ex) > 10 else np.nan
        ht = g[g.has_top]
        print(grp, scn, dict(n=len(g), uA_med=round(g.u_A.median(), 3), y_med=round(g.y.median(), 3), uA_minus_y_med=round((g.u_A - g.y).median(), 3),
                             share_uA_ge_y=round((g.u_A >= g.y).mean(), 3), spearman=round(r, 3), spearman_ex=round(rx, 3),
                             n_top=len(ht), expA_over_Ptop_q20_50_80=[round(x, 3) for x in ht.top_ratio.quantile([0.2, 0.5, 0.8])] if len(ht) else None))
    print("\n== 2b 条件分位 pinball 比值（250 日块 bootstrap 90% 区间）")
    res = []
    for grp, g in P.groupby("group"):
        for tau in (0.2, 0.5, 0.8):
            oos = qreg(g, tau)
            if oos is None:
                continue
            pt, lo, hi = block_ci(oos, lambda d: d.loss_m.sum() / d.loss_b.sum())
            ex = oos[~oos.yr.isin(EX)]
            ptx = ex.loss_m.sum() / ex.loss_b.sum() if len(ex) else np.nan
            res.append(dict(group=grp, tau=tau, n_oos=len(oos), years=f"{oos.yr.min()}–{oos.yr.max()}", ratio=round(pt, 3), ci_lo=round(lo, 3), ci_hi=round(hi, 3), ratio_ex=round(ptx, 3)))
            print(res[-1])
    pd.DataFrame(res).to_csv(OUT / "remaining_upside_qreg.csv", index=False)
