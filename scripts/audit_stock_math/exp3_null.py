# ruff: noqa: E402, E702, B905, B007
"""Null false-alarm rate: GBM (drift 0/high), pure power-law (no oscillation), AR(1) regime through fit_one + rules on stk_lite windows.
Reports share of windows qualifying per rule and 'confidence>=0.5' share at the as-of level (16 windows)."""
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.features import lppls_scan
from research.features.lppls_rules import SCALES_FCO6, _derived, grid_rules, rules
from research.lppls import core
from research.pipeline import universe


def init():
    core.ALLOW_INSIDE = True

def series(kind, n, rng):
    if kind == "gbm0":
        return np.cumsum(rng.normal(0.0, 0.02, n))
    if kind == "gbm_drift":   # strong trend, 100% per year-ish
        return np.cumsum(rng.normal(0.004, 0.02, n))
    if kind == "powerlaw":    # super-exponential without oscillation, tc 5% beyond
        t = np.arange(n, dtype=float); dt = n - 1; tc = dt + 0.05 * dt
        return 8 - 0.6 * ((tc - t) / tc) ** 0.5 + rng.normal(0, 0.01, n)
    if kind == "garch":
        e = np.empty(n); s2 = 0.02**2
        for i in range(n):
            e[i] = rng.normal(0, np.sqrt(s2)); s2 = 0.02**2 * 0.05 + 0.1 * e[i]**2 + 0.85 * s2
        return np.cumsum(e)
    raise ValueError(kind)

def one(args):
    kind, seed = args
    rng = np.random.default_rng(seed)
    n_total = max(universe.WINDOWS)
    y_full = series(kind, n_total, rng)
    out = []
    for n in universe.WINDOWS:
        y = y_full[-n:]
        row = lppls_scan.fit_one(y)
        d = dict(zip(lppls_scan.COLS[1:], row)); d.update(kind=kind, seed=seed, y_std=float(np.std(y)))
        out.append(d)
    return out

if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    tasks = [(k, s) for k in ("gbm0", "gbm_drift", "powerlaw", "garch") for s in range(reps)]
    t0 = time.time()
    with Pool(procs, initializer=init) as p:
        rows = [r for rs in p.map(one, tasks, chunksize=1) for r in rs]
    df = pd.DataFrame(rows); df["date"] = pd.Timestamp("2020-01-01")
    df.to_parquet(f"{OUT}/exp3_null.parquet")
    d = _derived(df); r = rules(d); g = grid_rules(d)
    for c in ("box", "lit2"):
        d[c] = r[c]
    for k, c in (("standard", "g_fco_standard"), ("end", "g_fco_end"), ("early", "g_fco_early")):
        d[k] = g[c]
    pd.set_option("display.width", 200)
    print("window-level qualification share by null kind:")
    print(d.groupby("kind")[["box", "standard", "end", "early", "lit2"]].mean().round(3))
    print("\nbound-hitting shares: m<=0.011 | m>=1.99 | w<=1.01 | w>=49.9 | ahead at +-0.2dt edge")
    d["edge"] = (d.ahead.abs() >= 0.2 * d.dt - 1)
    print(d.groupby("kind").apply(lambda x: pd.Series(dict(m_lo=(x.m <= 0.011).mean(), m_hi=(x.m >= 1.99).mean(), w_lo=(x.w <= 1.01).mean(), w_hi=(x.w >= 49.9).mean(), tc_edge=x.edge.mean(), B_neg=(x.B < 0).mean()))).round(3))
    print("\nas-of level confidence (share of 16 windows) >= 0.5 by scale:")
    for sc, (lo, hi) in SCALES_FCO6.items():
        m = d.n.between(lo, hi)
        if not m.any():
            continue
        conf = d[m].groupby(["kind", "seed"])[["box", "standard", "end"]].mean()
        print(sc, (conf >= 0.5).groupby("kind").mean().round(3).to_dict(), " any>0:", (conf > 0).groupby("kind").mean().round(3).to_dict())
    print("elapsed", round(time.time() - t0, 1))
