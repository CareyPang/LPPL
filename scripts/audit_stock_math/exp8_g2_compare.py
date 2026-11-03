# ruff: noqa: E402, E702, B905, B007
"""§20 第 2 条敏感性对照：开发段原扫描 lppls_v2（基线评价 _g2base）vs 修复后重扫 lppls_v2_g2（评价 _g2）。
窗口级：按 (date,n) 配对比较 SSE、t_c、窗内 t_c 占比、box/standard 合格率（按 E4 三尺度与 FCO 六档）。
评价级：读取两份 original_standard 报告的 alarm_grid_agg.csv / quantile_windows.csv，并列稳健区域数、按尺度 A1/A2 中位、分位窗覆盖。
用法：LPPLS_BOX=v2 PYTHONPATH=. python scripts/audit_stock_math/exp8_g2_compare.py [old_dir new_dir old_report new_report]"""
import os
import sys

os.environ.setdefault("LPPLS_BOX", "v2")
from pathlib import Path

import numpy as np
import pandas as pd

from research.features.lppls_rules import SCALES, SCALES_FCO6, _derived, grid_rules, rules
from research.lppls import core

core.ALLOW_INSIDE = True
OLD = Path(sys.argv[1] if len(sys.argv) > 1 else "data/features/lppls_v2")
NEW = Path(sys.argv[2] if len(sys.argv) > 2 else "data/features/lppls_v2_g2")
ROLD = Path(sys.argv[3] if len(sys.argv) > 3 else "reports/original_standard_dev_v2_g2base")
RNEW = Path(sys.argv[4] if len(sys.argv) > 4 else "reports/original_standard_dev_v2_g2")
OUT = Path(os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"))
SYMS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")


def _ystd(df: pd.DataFrame, sym: str) -> pd.Series:
    from research.eval.dataset import price_series
    lp = price_series(sym); lpv = lp.to_numpy(float); pos = lp.index.get_indexer(pd.to_datetime(df.date))
    return pd.Series([float(lpv[i + 1 - n : i + 1].std()) for i, n in zip(pos, df.n)], index=df.index)


def window_level() -> tuple[pd.DataFrame, pd.DataFrame]:
    recs, scale_recs = [], []
    for sym in SYMS:
        if not (NEW / f"{sym}.parquet").exists():
            print("skip", sym); continue
        o = pd.read_parquet(OLD / f"{sym}.parquet"); n_ = pd.read_parquet(NEW / f"{sym}.parquet")
        m = o.merge(n_, on=["date", "n"], suffixes=("_o", "_n"))
        rel = (m.sse_n - m.sse_o) / m.sse_o
        chg = rel < -1e-6
        recs.append({"symbol": sym, "n_old": len(o), "n_new": len(n_), "n_paired": len(m), "share_sse_down": round(float(chg.mean()), 4),
                     "share_sse_up": round(float((rel > 1e-6).mean()), 4), "share_equal": round(float((rel.abs() <= 1e-6).mean()), 4),
                     "max_rel_down": round(float(rel.min()), 4), "max_rel_up": round(float(rel.max()), 4),
                     "tc_shift_med_changed": round(float((m.tc_n - m.tc_o).abs()[chg].median()), 2) if chg.any() else np.nan,
                     "inside_old": round(float((m.tc_o < m.n - 1).mean()), 4), "inside_new": round(float((m.tc_n < m.n - 1).mean()), 4)})
        for tag, df in (("old", o), ("new", n_)):
            df = df.copy(); df["y_std"] = _ystd(df, sym); d = _derived(df); r = rules(d); g = grid_rules(d)
            for sc, (lo, hi) in {**SCALES, **SCALES_FCO6}.items():
                mm = d.n.between(lo, hi)
                if mm.any():
                    scale_recs.append({"symbol": sym, "version": tag, "scale": sc, "n": int(mm.sum()), "box": round(float(r.box[mm].mean()), 4),
                                       "standard": round(float(g.g_fco_standard[mm].mean()), 4), "end": round(float(g.g_fco_end[mm].mean()), 4),
                                       "lit2": round(float(r.lit2[mm].mean()), 4)})
    return pd.DataFrame(recs), pd.DataFrame(scale_recs)


def eval_level() -> dict:
    out = {}
    for tag, rep in (("old", ROLD), ("new", RNEW)):
        if not (rep / "alarm_grid_agg.csv").exists():
            print("missing report", rep); continue
        agg = pd.read_csv(rep / "alarm_grid_agg.csv"); agg["scale"] = agg.indicator.str.split("__").str[-1]
        out[tag] = {"n_combo": len(agg), "n_robust": int(agg.robust.sum()),
                    "by_scale": agg.groupby(["scale", "H"]).agg(A1=("A1", "median"), A1_null=("A1_null", "median"), A2=("A2", "median"), A2_null=("A2_null", "median"), robust=("robust", "sum")).round(3),
                    "robust_set": set(agg[agg.robust].apply(lambda x: f"{x.indicator}|q{x.q}|H{x.H}", axis=1))}
        qw = rep / "quantile_windows.csv"
        if qw.exists():
            w = pd.read_csv(qw)
            if "cover" in w:
                out[tag]["windows"] = w.groupby(["rule", "kind"]).agg(n=("cover", "size"), cover=("cover", "mean"), cover_naive=("cover_naive", "mean"), width_med=("width", "median")).round(3)
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    wl, sl = window_level()
    wl.to_csv(OUT / "exp8_window_level.csv", index=False); sl.to_csv(OUT / "exp8_scale_rates.csv", index=False)
    print("## window level\n", wl.to_string(index=False))
    piv = sl.pivot_table(index=["scale"], columns="version", values=["box", "standard", "end", "lit2"], aggfunc="mean").round(4)
    print("\n## scale rates (mean over symbols)\n", piv.to_string())
    ev = eval_level()
    for tag, v in ev.items():
        print(f"\n## eval {tag}: combos {v['n_combo']} robust {v['n_robust']}\n", v["by_scale"].to_string())
        if "windows" in v:
            print(v["windows"].to_string())
    if {"old", "new"} <= set(ev):
        a, b = ev["old"]["robust_set"], ev["new"]["robust_set"]
        print(f"\nrobust overlap: both {len(a & b)}, only_old {len(a - b)}, only_new {len(b - a)}")
