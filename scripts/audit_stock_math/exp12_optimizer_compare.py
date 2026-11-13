# ruff: noqa: E402, E702
"""Phase 1a：优化器/起点对比（合成 LPPLS，v2 搜索域、允许窗内 t_c）。
方法：tcgrid_lm n_random∈{0,3,10}（10 = 生产 full、3 = lite）、ms_lm（30 起点）、cmaes、de_lbfgsb。
场景：m0∈{0.3,0.5,0.7} × ω0∈{6,9,12} × σ∈{0.5%,1%,2%} × t_c_rel∈{+5%,−5%} × n∈{127,227,327,477} × seeds；CF=0.1，B 使窗口内对数涨幅≈0.6。
记录：θ̂、SSE、SSE(θ0)（真参数处的线性最优 SSE，用于判定是否找到全局最小：found_global = SSE ≤ SSE(θ0)·(1+1e-3)）、耗时、撞边界。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp12_optimizer_compare.py <procs> <seeds>"""
import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
from research.lppls import core
from research.lppls.core import lin_fit
from research.optim import optimizers as O

METHODS = {
    "tcgrid_lm_r10": lambda t, y, lo, hi, s: O.tcgrid_lm(t, y, lo, hi, seed=s, n_random=10),
    "tcgrid_lm_r3": lambda t, y, lo, hi, s: O.tcgrid_lm(t, y, lo, hi, seed=s, n_random=3),
    "tcgrid_lm_r0": lambda t, y, lo, hi, s: O.tcgrid_lm(t, y, lo, hi, seed=s, n_random=0),
    "ms_lm30": lambda t, y, lo, hi, s: O.ms_lm(t, y, lo, hi, seed=s),
    "cmaes": lambda t, y, lo, hi, s: O.cmaes(t, y, lo, hi, seed=s),
    "de_lbfgsb": lambda t, y, lo, hi, s: O.de_lbfgsb(t, y, lo, hi, seed=s),
}


def init():
    core.ALLOW_INSIDE = True


def synth(seed, n, tc_rel, sigma, m0, w0, CF=0.1):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float); dt = n - 1
    tc0 = dt + tc_rel * dt
    X = core.design(t, tc0, m0, w0, allow_inside=True)
    B = -0.6 / (abs(tc0) ** m0)
    return t, X @ np.array([8.0, B, CF * abs(B), CF * abs(B)]) + rng.normal(0, sigma, n), tc0


def one(args):
    seed, n, tc_rel, sigma, m0, w0 = args
    t, y, tc0 = synth(seed, n, tc_rel, sigma, m0, w0)
    dt = n - 1
    lo = np.array([dt - 0.2 * dt, 0.01, 1.0]); hi = np.array([dt + 0.2 * dt, 2.0, 50.0])
    sse0 = lin_fit(t, y, tc0, m0, w0)[0]
    rows = []
    for name, f in METHODS.items():
        try:
            r = f(t, y, lo, hi, seed)
        except Exception as ex:  # noqa: BLE001
            rows.append(dict(method=name, seed=seed, n=n, tc_rel=tc_rel, sigma=sigma, m0=m0, w0=w0, error=repr(ex)[:80])); continue
        tc, m, w = map(float, r.theta)
        rows.append(dict(method=name, seed=seed, n=n, tc_rel=tc_rel, sigma=sigma, m0=m0, w0=w0, tc0=tc0,
                         tc=tc, m=m, w=w, sse=r.sse, sse0=sse0, found_global=r.sse <= sse0 * (1 + 1e-3), nfev=r.nfev, sec=r.seconds,
                         err_tc=tc - tc0, err_m=m - m0, err_w=w - w0,
                         at_bound=(abs(tc - lo[0]) < 1) | (abs(tc - hi[0]) < 1) | (m <= 0.011) | (m >= 1.99) | (w <= 1.01) | (w >= 49.9)))
    return rows


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    tasks = [(s * 7919 + n, n, tc_rel, sigma, m0, w0) for m0 in (0.3, 0.5, 0.7) for w0 in (6.0, 9.0, 12.0) for sigma in (0.005, 0.01, 0.02)
             for tc_rel in (0.05, -0.05) for n in (127, 227, 327, 477) for s in range(seeds)]
    print(f"tasks={len(tasks)} methods={list(METHODS)}", flush=True)
    t0 = time.time()
    with Pool(procs, initializer=init) as p:
        rows = [r for rs in p.imap_unordered(one, tasks, chunksize=2) for r in rs]
    df = pd.DataFrame(rows); df.to_parquet(f"{OUT}/exp12_opt.parquet")
    print(f"rows={len(df)} elapsed {time.time() - t0:.0f}s", flush=True)
    d = df[df.error.isna()] if "error" in df else df
    pd.set_option("display.width", 220)
    print(d.groupby("method").agg(n=("sse", "size"), found_global=("found_global", "mean"), tc_mae=("err_tc", lambda x: x.abs().mean()),
                                  tc_med=("err_tc", lambda x: x.abs().median()), m_mae=("err_m", lambda x: x.abs().mean()),
                                  w_mae=("err_w", lambda x: x.abs().mean()), at_bound=("at_bound", "mean"), sec=("sec", "median")).round(3).to_string())
