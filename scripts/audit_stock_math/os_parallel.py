# ruff: noqa: E402
"""按标的并行运行 research.eval.original_standard（同一 evaluate_symbol / write_report，只是多进程），
每个标的结果先落盘到 REPORT/parts/，全部完成后用同一 write_report 聚合。
用法：LPPLS_BOX=v2 LPPLS_OUT_TAG=_g2 PYTHONPATH=. python scripts/audit_stock_math/os_parallel.py <procs> sym1 sym2 ..."""
import os
import sys
import time

os.environ.setdefault("LPPLS_BOX", "v2")
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

from research.eval import original_standard as os_


def one(sym: str) -> str:
    parts = os_.REPORT / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    ft, fw = parts / f"{sym}_tab.parquet", parts / f"{sym}_win.parquet"
    if ft.exists() and fw.exists():
        return f"{sym}: cached"
    t0 = time.time()
    t, w = os_.evaluate_symbol(sym)
    t.to_parquet(ft)
    w.to_parquet(fw)
    return f"{sym}: {len(t)} rows, {len(w)} windows, {time.time() - t0:.0f}s"


if __name__ == "__main__":
    procs = int(sys.argv[1])
    syms = sys.argv[2:]
    syms = [s for s in syms if (os_.SCAN / f"{s}.parquet").exists()]
    print(f"SCAN={os_.SCAN} REPORT={os_.REPORT} symbols={syms} procs={procs}", flush=True)
    with Pool(procs) as p:
        for msg in p.imap_unordered(one, syms):
            print(msg, flush=True)
    parts = Path(os_.REPORT) / "parts"
    tab = pd.concat([pd.read_parquet(parts / f"{s}_tab.parquet") for s in syms], ignore_index=True)
    win = pd.concat([pd.read_parquet(parts / f"{s}_win.parquet") for s in syms], ignore_index=True)
    os_.write_report(tab, win, syms)
