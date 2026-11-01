"""开发段探索（dev_only，未登记）：box 6–12 月档合格拟合的 t_c 聚类越紧，t_c 中位数是否越接近实际顶区。

定义：聚类宽度 = 同一 as-of 合格拟合 t_c 提前量的 20–80 分位间距（交易日），要求 ≥5 个合格拟合；
顶 = 现有合格顶标签（top_dates 返回顶后一日，取前一交易日）；顶区 = 顶前后收盘价在峰值 3% 以内的连续段；
命中 = t_c 中位数落在顶区 ±5 个交易日；对照 = 同一批截止日，t_c 提前量从全部截止日随机抽取（500 次）。
用法：LPPLS_BOX=v2 python -m research.eval.tc_cluster_dev
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("LPPLS_BOX", "v2")

from .dataset import price_series  # noqa: E402
from .original_standard import DEV_END, top_dates  # noqa: E402
from .tc_stability_eval import per_date  # noqa: E402

SYMS = ("sh000001", "sz399001", "sh000300", "sz399006", "sh000016", "sh000905")
ZONE = 0.97
TOL = 5
HMAX = 250
OUT = Path("reports/tc_cluster_dev_rows.csv")


def zones(sym: str, cal: pd.DatetimeIndex) -> list[tuple[int, int, int]]:
    close = np.exp(price_series(sym).to_numpy())
    tp = np.sort(cal.get_indexer(top_dates(sym))) - 1
    tp = tp[(tp >= 0) & (cal[np.clip(tp, 0, None)] <= DEV_END + pd.Timedelta(days=365))]
    out = []
    for t in tp:
        a = b = t
        while a > 0 and close[a - 1] >= ZONE * close[t]:
            a -= 1
        while b + 1 < len(close) and close[b + 1] >= ZONE * close[t]:
            b += 1
        out.append((int(t), int(a), int(b)))
    return out


def rows() -> pd.DataFrame:
    out = []
    for sym in SYMS:
        tab, cal = per_date(sym)
        tab = tab[tab.index <= DEV_END].dropna(subset=["med"])
        zs = zones(sym, cal)
        for d, r in tab.iterrows():
            pos = int(r.pos)
            tc = pos + r.med
            cand = [z for z in zs if 0 <= z[0] - pos <= HMAX or z[1] <= pos <= z[2]]
            z = min(cand, key=lambda z: abs(tc - z[0])) if cand else (np.nan,) * 3
            out.append(dict(sym=sym, date=d, conf=r.conf, n_fit=r.n_fit, width=r.q80 - r.q20,
                            pos=pos, tc=tc, top=z[0], za=z[1], zb=z[2]))
    df = pd.DataFrame(out)
    df["has_top"] = df.top.notna()
    df["err"] = df.tc - df.top
    df["hit_top"] = df.err.abs() <= TOL
    df["hit_zone"] = (df.tc >= df.za - TOL) & (df.tc <= df.zb + TOL)
    return df


def summary(df: pd.DataFrame, m: pd.Series, name: str, rng: np.random.Generator, b: int = 500) -> dict:
    s = df[m]
    if not len(s):
        return dict(group=name, n=0)
    ahead = (df.tc - df.pos).to_numpy()
    null = [np.mean((tc >= s.za.to_numpy() - TOL) & (tc <= s.zb.to_numpy() + TOL))
            for tc in (s.pos.to_numpy() + rng.choice(ahead, len(s)) for _ in range(b))]
    return dict(group=name, n=len(s), n_sym=s.sym.nunique(),
                tops_covered=int(s.dropna(subset=["top"]).groupby(["sym", "top"]).ngroups),
                no_top_250d=round(1 - s.has_top.mean(), 3),
                med_abs_err=round(s.err.abs().median(), 1), p80_abs_err=round(s.err.abs().quantile(0.8), 1),
                hit_top_pm5=round(s.hit_top.mean(), 3), hit_zone_pm5=round(s.hit_zone.mean(), 3),
                null_zone_mean=round(float(np.mean(null)), 3), null_zone_p95=round(float(np.quantile(null, 0.95)), 3))


def main() -> None:
    df = rows()
    rng = np.random.default_rng(0)
    tight = (df.n_fit >= 5) & (df.width <= 10)
    groups = [("全部有 t_c 的截止日", df.n_fit >= 3), ("conf≥0.2", df.conf >= 0.2), ("conf≥0.5", df.conf >= 0.5),
              ("聚类宽度≤20 日", (df.n_fit >= 5) & (df.width <= 20)), ("聚类宽度≤10 日", tight),
              ("聚类≤10 日 & conf≥0.5", tight & (df.conf >= 0.5)), ("聚类≤5 日", (df.n_fit >= 5) & (df.width <= 5))]
    print(pd.DataFrame([summary(df, m, n, rng) for n, m in groups]).to_markdown(index=False))
    df.to_csv(OUT, index=False)


if __name__ == "__main__":
    main()
