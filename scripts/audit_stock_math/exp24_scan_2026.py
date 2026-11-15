# ruff: noqa: E402, E702
"""描述性：2025-09—2026-10 前瞻期 LPPLS 扫描（v2.1 生产代码 = lppls_v2_g2 口径，box v2；窗口同 lppls_v2_g2 的 145 个），
6 个 A 股指数 + NDX + IXIC，as-of 每 10 个交易日。只描述，不评价、不调参。
用法：LPPLS_BOX=v2 PYTHONPATH=. python scripts/audit_stock_math/exp24_scan_2026.py <outdir> [procs]"""
import os
import sys
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("LPPLS_BOX", "v2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import pandas as pd

from research.eval.dataset import price_series
from research.features import lppls_scan as S
from research.lppls import core as _core

A_SH = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
EXT = {"NDX": "data/frozen/ext_v20261029/NDX.parquet", "IXIC": "/home/ubuntu/audit/IXIC_yahoo.parquet"}
LO, HI, STEP = pd.Timestamp("2025-09-01"), pd.Timestamp("2026-10-29"), 10
WINDOWS = tuple(int(n) for n in sorted(pd.read_parquet("data/features/lppls_v2_g2/sh000300.parquet", columns=["n"]).n.unique()))


def logp(sym: str) -> pd.Series:
    if sym in EXT:
        d = pd.read_parquet(EXT[sym]); d = d[d.close > 0]
        return pd.Series(np.log(d.close.to_numpy(float)), index=pd.DatetimeIndex(d.date)).sort_index()
    return price_series(sym)


def task(a):
    sym, i = a
    _core.ALLOW_INSIDE = bool(S.BOXES[S.BOX]["inside"])
    lp = logp(sym); rows = []
    for n in WINDOWS:
        if i + 1 >= n:
            seg = lp.iloc[i + 1 - n : i + 1].to_numpy()
            rows.append((lp.index[i], *S.fit_one(seg), float(seg.std())))
    return sym, rows


if __name__ == "__main__":
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); procs = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    jobs = []
    for sym in A_SH + tuple(EXT):
        lp = logp(sym); idx = np.flatnonzero((lp.index >= LO) & (lp.index <= HI))
        jobs += [(sym, int(i)) for i in idx[::STEP]] + ([(sym, int(idx[-1]))] if (len(idx) - 1) % STEP else [])
    print("jobs", len(jobs), "windows", len(WINDOWS), flush=True)
    res = {}
    with Pool(procs) as p:
        for k, (sym, rows) in enumerate(p.imap_unordered(task, jobs, chunksize=1)):
            res.setdefault(sym, []).extend(rows)
            if k % 20 == 0:
                print(k, flush=True)
    for sym, rows in res.items():
        pd.DataFrame(rows, columns=S.COLS + ["y_std"]).sort_values(["date", "n"]).to_parquet(out / f"{sym}.parquet", index=False)
    print("done", flush=True)
