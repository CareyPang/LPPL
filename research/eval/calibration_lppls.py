"""校准段判据 (ii)：LPPLS 置信度报警（产品尺度 SCALES_FCO 两主档；规则 box 与 FCO END；q=0.05 冻结阈值）在 2019–2021 的 A1/A2，
对照 = 报警序列循环平移零分布（与开发段 original_standard 同一函数）。通过 = ≥4/6 指数 A1 p≤0.05 且 A2≥0.5（H=120）。
留出：按指数逐个列出即为 LOCO；按年给出各年 A1。只报告，不调参。
用法：LPPLS_BOX=v2 python -m research.eval.calibration_lppls
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..features.lppls_rules import SCALES_FCO, _derived, grid_rules, rules
from .dataset import price_series
from .original_standard import N_PERM, _alarm_metrics, top_dates

SCAN = Path("data/features/lppls_v2_cal")
OUT = Path("reports/calibration_2019_2021")
CAL = (pd.Timestamp("2019-01-01"), pd.Timestamp("2021-12-31"))
Q = 0.05
HS = (60, 120)
MAIN_SCALES = ("6-12m", "12-24m")


def conf_table(sym: str) -> pd.DataFrame:
    sc = pd.read_parquet(SCAN / f"{sym}.parquet")
    sc = sc[(sc.date >= CAL[0]) & (sc.date <= CAL[1])].reset_index(drop=True)
    logp = price_series(sym)
    pos = pd.Series(np.arange(len(logp)), index=logp.index)
    lp = logp.to_numpy()
    end = pos.reindex(sc.date).to_numpy()
    sc["y_std"] = [lp[e + 1 - n : e + 1].std() for e, n in zip(end, sc.n, strict=True)]
    d = _derived(sc)
    flags = {"box": rules(d).box.to_numpy()}
    g = grid_rules(d)
    for k in ("g_fco_standard", "g_fco_end"):
        if k in g:
            flags[k] = g[k].to_numpy()
    out = {}
    for rule, f in flags.items():
        for scn, (lo, hi) in SCALES_FCO.items():
            if scn not in MAIN_SCALES:
                continue
            m = d.n.between(lo, hi).to_numpy()
            out[f"{rule}__{scn}"] = pd.Series(f[m], index=d.date[m]).groupby(level=0).mean()
    return pd.DataFrame(out).sort_index()


def _null(alarm: np.ndarray, top_pos: np.ndarray, grid_pos: np.ndarray, H: int, rng: np.random.Generator) -> np.ndarray:
    """循环平移零分布；校准段网格短（≈146 点，科创50 更短），最小平移取 min(250 日, 1/4 网格)。"""
    n = len(alarm)
    step = max(1, int(np.median(np.diff(grid_pos))))
    k0 = max(1, min(250 // step, n // 4))
    out = np.empty((N_PERM, 2))
    for b in range(N_PERM):
        out[b] = _alarm_metrics(np.roll(alarm, int(rng.integers(k0, n - k0))), top_pos, grid_pos, H)
    return out


def main() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, by_year = [], []
    for p in sorted(SCAN.glob("*.parquet")):
        sym = p.stem
        ms = conf_table(sym)
        if ms.empty:
            continue
        cal = price_series(sym).index
        gpos = cal.get_indexer(ms.index)
        tpos = np.sort(cal.get_indexer(top_dates(sym)))
        tpos = tpos[(tpos >= gpos.min()) & (tpos <= gpos.max() + max(HS))]
        rng = np.random.default_rng(0)
        for c in ms.columns:
            x = ms[c].fillna(0).to_numpy()
            alarm = x >= Q
            for H in HS:
                a1, a2 = _alarm_metrics(alarm, tpos, gpos, H)
                nul = _null(alarm, tpos, gpos, H, rng) if alarm.sum() >= 3 else np.full((1, 2), np.nan)
                rows.append(dict(symbol=sym, indicator=c, q=Q, H=H, n_grid=len(x), n_alarm=int(alarm.sum()), n_tops=len(tpos),
                                 A1=a1, A1_null=np.nanmean(nul[:, 0]), A1_p=float(np.nanmean(nul[:, 0] >= a1)) if alarm.sum() >= 3 else np.nan,
                                 A2=a2, A2_null=np.nanmean(nul[:, 1]), A2_p=float(np.nanmean(nul[:, 1] >= a2)) if alarm.sum() >= 3 else np.nan))
            for yr, idx in pd.Series(np.arange(len(x)), index=ms.index).groupby(ms.index.year):
                al = alarm[idx.to_numpy()]
                a1, _ = _alarm_metrics(al, tpos, gpos[idx.to_numpy()], 120)
                by_year.append(dict(symbol=sym, indicator=c, year=int(yr), n_alarm=int(al.sum()), A1_H120=a1))
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "lppls_a1a2.csv", index=False)
    pd.DataFrame(by_year).to_csv(OUT / "lppls_by_year.csv", index=False)
    summ = []
    for (c, H), g in tab.groupby(["indicator", "H"]):
        ok = ((g.A1_p <= 0.05) & (g.A2 >= 0.5)).sum()
        summ.append(dict(indicator=c, H=H, n_symbols=len(g), n_pass=int(ok), pass_ii=bool(ok >= 4),
                         A1_med=g.A1.median(), A1_null_med=g.A1_null.median(), A2_med=g.A2.median(), n_alarm_total=int(g.n_alarm.sum())))
    s = pd.DataFrame(summ)
    s.to_csv(OUT / "lppls_summary.csv", index=False)
    print(s.round(3).to_string(index=False), flush=True)
    return s


if __name__ == "__main__":
    main()
