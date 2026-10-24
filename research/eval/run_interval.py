"""T-INT 顶部区间模型的开发段验证（预登记 v1.2 §12.3）。

在已扫描的稀疏 as-of 时点上，取 Y_top=1 的时点为事件；目标 t* = 该时点之后 20 日内第一个被标签确认的共识顶距 as-of 的交易日数。
区间 = 合格窗口 t_c 的加权分位区间（research/eval/interval.py 的 4 种配置）× 合格规则（全部窗口、power、p_ds、p_top、lit1）。
基线 = 固定区间 [1, 20]。主评分 = 区间得分（宽度 + 未覆盖罚分）的事件均值；判定 = 与基线配对的 90% 块 bootstrap 区间不含 0。
无区间（合格窗口 < 5）的事件按基线区间计分并单独报告比例。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..features.lppls_rules import _derived, rules
from ..features.lppls_scan import OUT as SCAN
from ..labels.run_top import OUT as LAB
from ..labels.run_top import SPLITS
from ..labels.top import HORIZON, consensus_tops, drawdown_after, epsilon_tops
from .dataset import price_series
from .interval import BASELINE, CONFIGS, interval_score, intervals_by_date

MASKS = ("all", "power", "p_ds", "p_top", "lit1")


def events_with_tstar(sym: str, split: str, scan_dates: pd.DatetimeIndex) -> pd.DataFrame:
    logp = price_series(sym)
    dates, lp = logp.index, logp.to_numpy()
    lab = pd.read_parquet(LAB / f"{sym}.parquet").reindex(dates)
    tops = consensus_tops(lp, epsilon_tops(lp))
    dd = np.array([drawdown_after(lp, k) for k in tops])
    a, b = (pd.Timestamp(x) for x in SPLITS[split][:2])
    y, thr = lab["main__y"].to_numpy(), lab["main__d_t"].to_numpy()
    sel = (y == 1) & (dates >= a) & (dates <= b) & dates.isin(scan_dates)
    rows = []
    for t in np.flatnonzero(sel):
        m = (tops > t) & (tops <= t + HORIZON) & (dd >= thr[t])
        if m.any():
            rows.append(dict(date=dates[t], t_star=int(tops[m].min() - t)))
    return pd.DataFrame(rows, columns=["date", "t_star"])


def block_ci(delta: np.ndarray, dates: pd.Series, cal: pd.DatetimeIndex, block_days: int = 80, B: int = 1000,
             seed: int = 0, level: float = 0.9) -> tuple[float, float, float]:
    blk = pd.Series(cal.get_indexer(dates) // block_days)
    g = pd.Series(delta).groupby(blk.to_numpy()).agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(B):
        pick = rng.integers(0, len(g), len(g))
        vals.append(g["sum"].to_numpy()[pick].sum() / g["size"].to_numpy()[pick].sum())
    a = (1 - level) / 2
    return float(delta.mean()), float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


def collect(split: str = "dev") -> pd.DataFrame:
    parts = []
    for p in sorted(SCAN.glob("*.parquet")):
        sym = p.stem
        sc = pd.read_parquet(p)
        ev = events_with_tstar(sym, split, pd.DatetimeIndex(sc.date.unique()))
        if ev.empty:
            continue
        logp = price_series(sym)
        pos = pd.Series(np.arange(len(logp)), index=logp.index)
        lp, end = logp.to_numpy(), pos.reindex(sc.date).to_numpy()
        sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
        d = _derived(sc)
        r = rules(d)
        for mname in MASKS:
            mask = pd.Series(True, index=d.index) if mname == "all" else r[mname]
            e = ev.merge(intervals_by_date(d, mask), on="date", how="left")
            e["symbol"], e["mask"] = sym, mname
            parts.append(e)
    return pd.concat(parts, ignore_index=True)


def run(split: str = "dev", tag: str = "tint_dev") -> pd.DataFrame:
    E = collect(split)
    cal = price_series("sh000001").index
    rows = []
    for mname, g in E.groupby("mask"):
        bl = interval_score(*BASELINE, g.t_star)
        if mname == MASKS[0]:
            rows.append(dict(mask="-", config="baseline_1-20", IS=bl.mean(), coverage=g.t_star.between(1, 20).mean(),
                             width_med=19.0, n=len(g), share_with_interval=1.0))
        for name in CONFIGS:
            L, U = g[f"{name}_L"].to_numpy(), g[f"{name}_U"].to_numpy()
            has = np.isfinite(L)
            L, U = np.where(has, L, BASELINE[0]), np.where(has, U, BASELINE[1])
            s = interval_score(L, U, g.t_star)
            d, lo, hi = block_ci(s - bl, g.date, cal)
            rows.append(dict(mask=mname, config=name, IS=s.mean(), coverage=((g.t_star >= L) & (g.t_star <= U)).mean(),
                             width_med=float(np.median((U - L)[has])) if has.any() else np.nan, n=len(g),
                             share_with_interval=float(has.mean()), dIS=d, ci_lo=lo, ci_hi=hi, kept=hi < 0))
    tab = pd.DataFrame(rows)
    tab.to_csv(f"reports/{tag}.csv", index=False)
    with open(f"reports/{tag}.md", "w") as f:
        f.write(f"# T-INT 顶部区间模型（{split}，稀疏时点事件，基线 [1,20]，90% 块 bootstrap）\n\n")
        f.write(f"事件数 {E.groupby('mask').size().iloc[0]}，标的 {E.symbol.nunique()}；配置数 {len(MASKS) * len(CONFIGS)}（多重比较）。\n\n")
        f.write(tab.round(4).to_markdown(index=False) + "\n")
    print(tab.round(4).to_string(), flush=True)
    return tab


if __name__ == "__main__":
    run()
