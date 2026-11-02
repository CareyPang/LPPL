# ruff: noqa: E402, E702, B905, B007
"""Synthetic LPPLS parameter recovery through the production chain (fit_one, v2 box) + Confidence via rules.
Scenarios: tc ahead (+5%dt), tc inside (-5%dt); noise sigma in {0.5%,1%,2%} of log-price; windows 127..502 step 25 (stk_lite).
"""
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.features import lppls_scan
from research.features.lppls_rules import _derived, grid_rules, rules
from research.lppls import core
from research.pipeline import universe


def init():
    core.ALLOW_INSIDE = True

def one(args):
    seed, n, tc_rel, sigma, m0, w0, CF = args
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float); dt = n - 1
    tc0 = dt + tc_rel * dt
    X = core.design(t, tc0, m0, w0, allow_inside=True)
    # amplitude chosen so that log-price rises ~0.6 over the window (typical bubble)
    B = -0.6 / (abs(tc0) ** m0)
    beta = np.array([8.0, B, CF * abs(B), CF * abs(B)])
    y = X @ beta + rng.normal(0, sigma, n)
    row = lppls_scan.fit_one(y)
    d = dict(zip(lppls_scan.COLS[1:], row))
    d.update(seed=seed, tc0=tc0, m0=m0, w0=w0, sigma=sigma, tc_rel=tc_rel, y_std=float(np.std(y)))
    return d

if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    tasks = []
    windows = tuple(universe.WINDOWS)
    for tc_rel in (0.05, -0.05):
      pass
    CF = float(sys.argv[2]) if len(sys.argv) > 2 else 0.1
    for tc_rel in (0.05, -0.05):
        for sigma in (0.005, 0.01, 0.02):
            for seed in range(8):
                for n in windows[::2]:   # 127,177,...,477 (8 windows)
                    tasks.append((seed * 1000 + n, n, tc_rel, sigma, 0.5, 9.0, CF))
    t0 = time.time()
    with Pool(procs, initializer=init) as p:
        rows = p.map(one, tasks, chunksize=4)
    df = pd.DataFrame(rows)
    df["date"] = pd.Timestamp("2020-01-01")
    df.to_parquet(f"{OUT}/exp2_synth_%s.parquet" % CF)
    d = _derived(df)
    r = rules(d); g = grid_rules(d)
    d["err_tc"] = d.tc - d.tc0; d["err_m"] = d.m - d.m0; d["err_w"] = d.w - d.w0
    d["box"] = r.box; d["standard"] = g.g_fco_standard; d["end"] = g.g_fco_end; d["cond2"] = (
        (d.B < 0) & d.m.between(0.1, 0.9) & d.w.between(6, 13) & d.ahead.between(-0.2 * d.dt, 0.12 * d.dt) & (d.osc >= 2.5) & (d.D >= 1) & (d.rel_err <= 0.14))
    summ = d.groupby(["tc_rel", "sigma"]).agg(n=("tc", "size"), tc_mae=("err_tc", lambda x: x.abs().mean()), tc_med=("err_tc", "median"),
        m_mae=("err_m", lambda x: x.abs().mean()), w_mae=("err_w", lambda x: x.abs().mean()),
        m_at_bound=("m", lambda x: ((x <= 0.011) | (x >= 1.99)).mean()), w_at_bound=("w", lambda x: ((x <= 1.01) | (x >= 49.9)).mean()),
        tc_at_bound=("ahead", lambda x: ((x <= -0.2 * 126 + 1) | (x >= 0.2 * 126 - 1)).mean()),
        box=("box", "mean"), standard=("standard", "mean"), end=("end", "mean"), cond2=("cond2", "mean"), r2=("r2", "median"))
    pd.set_option("display.width", 200)
    print(summ.round(3))
    print("elapsed", round(time.time() - t0, 1), "s; per fit", round((time.time() - t0) / len(tasks) * procs, 2), "s")
    summ.to_csv(f"{OUT}/exp2_summary_%s.csv" % CF)
