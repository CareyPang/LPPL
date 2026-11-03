# ruff: noqa: E402, E702, B905, B007
"""§21.2 (b) t_c 区间合成标定：MPL（式 38）vs 普通剖面似然 vs 现行块 bootstrap（intervals.bootstrap_interval, B=50, block=10）。
合成：exp2 设置（m0=0.5, ω0=9, CF=0.1），σ∈{0.5%,1%,2%}，t_c ±5%dt，窗口 {127,252,377,502}，每格 n_seeds 条。
指标：名义 90%/80% 覆盖率、区间宽度中位数。用法：AUDIT_OUT=... LPPLS_BOX=v2 PYTHONPATH=. python exp10_mpl_calibration.py <procs> <n_seeds>"""
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.lppls import core, mpl
from research.lppls.intervals import bootstrap_interval


def init():
    core.ALLOW_INSIDE = True


def one(args):
    seed, n, tc_rel, sigma = args
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float); dt = n - 1; tc0 = dt + tc_rel * dt
    X = core.design(t, tc0, 0.5, 9.0, allow_inside=True); B = -0.6 / (abs(tc0) ** 0.5)
    y = X @ np.array([8.0, B, 0.1 * abs(B), 0.1 * abs(B)]) + rng.normal(0, sigma, n)
    lo = np.array([dt - 0.2 * dt, 0.01, 1.0]); hi = np.array([dt + 0.2 * dt, 2.0, 50.0])
    t0 = time.time()
    pr = mpl.mpl_profile(t, y, mpl.tc_grid(n, 0.5))
    row = dict(seed=seed, n=n, tc_rel=tc_rel, sigma=sigma, tc0=tc0, tc_hat=pr["tc_hat"], tc_hat_mpl=pr["tc_hat_mpl"])
    for lvl in (0.9, 0.8):
        for which in ("lm", "lp"):
            a, b = mpl.interval(pr, lvl, which)
            row[f"{which}_{lvl}_lo"], row[f"{which}_{lvl}_hi"] = a, b
            row[f"{which}_{lvl}_cover"] = bool(a - 0.5 <= tc0 <= b + 0.5); row[f"{which}_{lvl}_width"] = b - a
        a, b, _ = bootstrap_interval(t, y, lo, hi, level=lvl, B=50, block=10, seed=seed)
        row[f"boot_{lvl}_lo"], row[f"boot_{lvl}_hi"] = a, b
        row[f"boot_{lvl}_cover"] = bool(a <= tc0 <= b); row[f"boot_{lvl}_width"] = b - a
    row["secs"] = time.time() - t0
    return row


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    tasks = [(s * 1000 + n, n, tr, sg) for sg in (0.005, 0.01, 0.02) for tr in (0.05, -0.05) for n in (127, 252, 377, 502) for s in range(n_seeds)]
    print(f"tasks={len(tasks)}", flush=True)
    t0 = time.time()
    with Pool(procs, initializer=init) as p:
        rows = list(p.imap_unordered(one, tasks, chunksize=2))
    df = pd.DataFrame(rows); df.to_parquet(f"{OUT}/exp10_mpl.parquet")
    g = df.groupby(["sigma", "tc_rel"]).agg(n=("seed", "size"), mpl90=("lm_0.9_cover", "mean"), pl90=("lp_0.9_cover", "mean"), boot90=("boot_0.9_cover", "mean"),
                                           mpl80=("lm_0.8_cover", "mean"), pl80=("lp_0.8_cover", "mean"), boot80=("boot_0.8_cover", "mean"),
                                           w_mpl90=("lm_0.9_width", "median"), w_boot90=("boot_0.9_width", "median"), secs=("secs", "median"))
    pd.set_option("display.width", 250); print(g.round(3).to_string()); print(f"elapsed {time.time() - t0:.0f}s")
