# ruff: noqa: E402, E702, B905, B007
"""Impact of making grid_profile honour ALLOW_INSIDE: refit 600519 stk_full windows at asof with patched grid, compare SSE/theta."""
import os
import sys
import time

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit"); os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("LPPLS_BOX", "v2")
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research.features import lppls_scan
from research.lppls import core
from research.optim import optimizers as opt
from research.pipeline import stock


def grid_profile_old(t, y, tcs, ms, ws, k=opt.K_LPPLS):
    yy = float(y @ y); ms = np.asarray(ms, float); ws = np.asarray(ws, float) if k == opt.K_LPPLS else np.zeros(1)
    out = np.full((len(tcs), len(ms), len(ws)), np.inf); ones = np.ones_like(t)
    for i, tc in enumerate(tcs):
        dt = tc - t
        if np.any(dt <= 0):
            continue
        L = np.log(dt); f = np.exp(np.outer(ms, L))
        if k == opt.K_POWER:
            X = np.stack([np.broadcast_to(ones, f.shape), f], axis=-1)[:, None]
        else:
            ph = np.outer(ws, L); c, s_ = np.cos(ph), np.sin(ph); fm = f[:, None, :]
            X = np.stack([np.broadcast_to(ones, (len(ms), len(ws), len(t))), np.broadcast_to(fm, (len(ms), len(ws), len(t))), fm * c[None], fm * s_[None]], axis=-1)
        U, sv, _ = np.linalg.svd(X, full_matrices=False)
        rank_ok = sv[..., -1] > sv[..., 0] * len(t) * np.finfo(float).eps
        uy = np.einsum("...nk,n->...k", U, y); sse = yy - np.einsum("...k,...k->...", uy, uy)
        out[i] = np.where(rank_ok & np.isfinite(sse), np.maximum(sse, 0.0), np.inf)
    return out

def init(patch):
    core.ALLOW_INSIDE = True
    if not patch:
        opt.grid_profile = grid_profile_old

def one(y):
    return lppls_scan.fit_one(y)

if __name__ == "__main__":
    asof = sys.argv[1] if len(sys.argv) > 1 else "2025-06-30"
    ohlc = pd.read_parquet(f"{OUT}/600519_hfq.parquet")
    logp = stock._fit_logp(ohlc); logp = logp[logp.index <= pd.Timestamp(asof)]
    lp = logp.to_numpy()
    windows = sorted(stock._variant_windows("stk_full", len(logp)))
    ys = [lp[-n:] for n in windows]
    res = {}
    for patch in (False, True):
        t0 = time.time()
        with Pool(4, initializer=init, initargs=(patch,)) as p:
            rows = p.map(one, ys, chunksize=2)
        res[patch] = pd.DataFrame(rows, columns=lppls_scan.COLS[1:])
        print("patch", patch, round(time.time() - t0, 1), "s")
    a, b = res[False], res[True]
    rel = (a.sse - b.sse) / a.sse
    print("windows", len(a), "| patched SSE lower by >1e-6 rel:", int((rel > 1e-6).sum()), "| higher:", int((rel < -1e-6).sum()), "| max rel gain", rel.max().round(4))
    ch = rel.abs() > 1e-6
    print("theta changed rows: tc shift median", (b.tc - a.tc)[ch].abs().median(), "m shift med", (b.m - a.m)[ch].abs().median())
    print("inside tc share before", (a.tc <= a.n - 1).mean().round(3), "after", (b.tc <= b.n - 1).mean().round(3))
    print("power-law SSE lower:", int(((a.pow_sse - b.pow_sse) / a.pow_sse > 1e-6).sum()))
    pd.concat([a.add_suffix("_a"), b.add_suffix("_b")], axis=1).to_parquet(f"{OUT}/exp5_{asof}.parquet")
