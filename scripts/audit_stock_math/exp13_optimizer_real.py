# ruff: noqa: E402, E702
"""Phase 1a：真实开发段窗口上的优化器配对对照（6 指数，`_g2` 口径：同窗口同搜索域，比 SSE）。
as-of 从开发段扫描网格每 STRIDE 个取一个，窗口取 IDX_WINDOWS[::5]；方法同 exp12（生产 tcgrid_lm n_random=10 为基准）。
用法：PYTHONPATH=. python scripts/audit_stock_math/exp13_optimizer_real.py <procs> <stride>"""
import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

OUT = os.environ.get("AUDIT_OUT", "/home/ubuntu/audit")
os.environ.setdefault("LPPLS_BOX", "v2")
from research.eval.dataset import price_series
from research.features.lppls_scan import IDX_WINDOWS
from research.lppls import core
from scripts.audit_stock_math.exp12_optimizer_compare import METHODS

SYMS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
SCAN = "data/features/lppls_v2"


def init():
    core.ALLOW_INSIDE = True


def one(args):
    sym, date, n, y = args
    y = np.asarray(y); t = np.arange(n, dtype=float); dt = n - 1
    lo = np.array([dt - 0.2 * dt, 0.01, 1.0]); hi = np.array([dt + 0.2 * dt, 2.0, 50.0])
    rows = []
    for name, f in METHODS.items():
        r = f(t, y, lo, hi, 0)
        rows.append(dict(symbol=sym, date=date, n=n, method=name, tc=float(r.theta[0]), m=float(r.theta[1]), w=float(r.theta[2]), sse=r.sse, sec=r.seconds))
    return rows


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    stride = int(sys.argv[2]) if len(sys.argv) > 2 else 46
    tasks = []
    for s in SYMS:
        sc = pd.read_parquet(f"{SCAN}/{s}.parquet"); dates = sorted(sc.date.unique())[::stride]
        logp = price_series(s); pos = pd.Series(np.arange(len(logp)), index=logp.index); lp = logp.to_numpy()
        for d in dates:
            e = int(pos[d])
            for n in IDX_WINDOWS[::5]:
                if e + 1 - n >= 0:
                    tasks.append((s, d, int(n), lp[e + 1 - n : e + 1].tolist()))
    print(f"tasks={len(tasks)}", flush=True)
    t0 = time.time()
    with Pool(procs, initializer=init) as p:
        rows = [r for rs in p.imap_unordered(one, tasks, chunksize=2) for r in rs]
    df = pd.DataFrame(rows); df.to_parquet(f"{OUT}/exp13_opt_real.parquet")
    print(f"rows={len(df)} elapsed {time.time() - t0:.0f}s", flush=True)
    base = df[df.method == "tcgrid_lm_r10"].set_index(["symbol", "date", "n"]).sse
    df["rel"] = df.sse.to_numpy() / base.reindex(pd.MultiIndex.from_frame(df[["symbol", "date", "n"]])).to_numpy() - 1
    pd.set_option("display.width", 220)
    print(df.groupby("method").agg(n=("sse", "size"), better=("rel", lambda x: (x < -1e-6).mean()), worse=("rel", lambda x: (x > 1e-6).mean()),
                                   rel_med=("rel", "median"), rel_p10=("rel", lambda x: x.quantile(0.1)), rel_min=("rel", "min"), sec=("sec", "median")).round(4).to_string())
