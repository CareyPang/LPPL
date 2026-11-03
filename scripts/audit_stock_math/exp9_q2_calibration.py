# ruff: noqa: E402, E702, B905, B007
"""§21.1 (a) Q2 合成标定：六类零假设（exp7 同 series/种子）× lite 16 窗 → 现行过滤集（box / standard）通过的窗口上计算
嵌套 LR p（块长 5/10/20，B=200）与 Lomb p（ar1 / ar1_t5，n_sim=1000）；合成泡沫集（exp2 设置：m0=0.5, ω0=9, CF=0.1, σ=1%，
t_c ±5%dt）同样计算。网格 α_LR∈{0.05,0.01} × α_L∈{0.05,0.01} 事后应用。
用法：AUDIT_OUT=/tmp/audit LPPLS_BOX=v2 PYTHONPATH=. python exp9_q2_calibration.py <procs> <null_reps> <bubble_seeds>"""
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
from research.lppls import core, q2
from research.pipeline import universe
from scripts.audit_stock_math.exp7_null_calibration import KINDS, REAL, load_real, series

BLOCKS = (5, 10, 20)
B_LR = int(os.environ.get("Q2_B", "200"))
N_SIM = int(os.environ.get("Q2_NSIM", "1000"))


def init(real):
    core.ALLOW_INSIDE = True
    REAL.update(real)


def bubble(seed, n, tc_rel, sigma=0.01, m0=0.5, w0=9.0, CF=0.1):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float); dt = n - 1; tc0 = dt + tc_rel * dt
    X = core.design(t, tc0, m0, w0, allow_inside=True)
    B = -0.6 / (abs(tc0) ** m0)
    return X @ np.array([8.0, B, CF * abs(B), CF * abs(B)]) + rng.normal(0, sigma, n), tc0


def one(args):
    kind, seed, tc_rel = args
    windows = tuple(universe.WINDOWS)
    rng = np.random.default_rng(seed)
    if kind == "bubble":
        ys = {n: bubble(seed, n, tc_rel)[0] for n in windows}
    else:
        y_full = series(kind, max(windows), rng)
        ys = {n: y_full[-n:] for n in windows}
    out = []
    for n, y in ys.items():
        row = lppls_scan.fit_one(y)
        d = dict(zip(lppls_scan.COLS[1:], row)); d.update(kind=kind, seed=seed, tc_rel=tc_rel, y_std=float(np.std(y)), date=pd.Timestamp("2020-01-01"))
        df = _derived(pd.DataFrame([d])); r = rules(df); g = grid_rules(df)
        d["box"] = bool(r.box.iloc[0]); d["standard"] = bool(g.g_fco_standard.iloc[0])
        if d["box"] or d["standard"]:
            t = np.arange(n, dtype=float); dt = n - 1
            lo = np.array([dt - 0.2 * dt, 0.01, 1.0]); hi = np.array([dt + 0.2 * dt, 2.0, 50.0])
            fit = q2.fit_both(t, y, lo, hi, seed=seed, budget=q2.FAST_BUDGET)
            d["lam"] = q2.lr_stat(n, fit["sse_pl"], fit["sse"])
            for blk in BLOCKS:
                d[f"lr_p_b{blk}"] = q2.nested_lr_test(t, y, lo, hi, block=blk, B=B_LR, seed=seed + blk, fit=fit)["p"]
            theta = np.array([d["tc"], d["m"], d["w"]]); beta = np.array([d["A"], d["B"], d["C1"], d["C2"]])
            for nm in ("ar1", "ar1_t5"):
                lb = q2.lomb_test(t, y, theta, beta, null_model=nm, n_sim=N_SIM, seed=seed)
                d[f"lomb_p_{nm}"] = lb["p"]; d["lomb_rel"] = lb["rel_dw"]; d["lomb_w"] = lb["w_peak"]
        out.append(d)
    return out


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    null_reps = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    bub_seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    real = load_real()
    tasks = [(k, s, 0.0) for k in KINDS for s in range(null_reps)] + [("bubble", 5000 + s, tr) for tr in (0.05, -0.05) for s in range(bub_seeds)]
    print(f"tasks={len(tasks)} B_LR={B_LR} N_SIM={N_SIM}", flush=True)
    t0 = time.time()
    with Pool(procs, initializer=init, initargs=(real,)) as p:
        rows = [r for rs in p.imap_unordered(one, tasks, chunksize=1) for r in rs]
    df = pd.DataFrame(rows); df.to_parquet(f"{OUT}/exp9_q2.parquet")
    print(f"rows={len(df)} elapsed {time.time() - t0:.0f}s", flush=True)
