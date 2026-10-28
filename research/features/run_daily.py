"""逐日特征库（非 LPPLS 候选）：基础/波动率（R1）、BSADF（R2）、统计物理（R7）。

输出 data/features/daily_v1/{symbol}.parquet，索引为日期；全部为 ≤t 可得的 as-of 特征。
"""
from __future__ import annotations

from multiprocessing import Pool
from pathlib import Path

import pandas as pd

from ..eval.dataset import SPLITS, _snapshot, base_features, price_series
from ..labels.run_top import INDEXES
from .gsadf import WINDOWS as GS_WINDOWS
from .gsadf import bsadf, psy_min_window
from .statphys import rolling_statphys

OUT = Path("data/features/daily_v1")
GS_MINW = {"psy": psy_min_window, "36": lambda W: 36}


def build(sym: str) -> pd.DataFrame:
    logp = price_series(sym)
    f = base_features(logp)
    for W in GS_WINDOWS:
        for name, fn in GS_MINW.items():
            f[f"bsadf{W}_{name}"] = bsadf(logp.to_numpy(), W, fn(W))
    f = f.join(rolling_statphys(logp))
    return f


def _one(sym: str):
    p = OUT / f"{sym}.parquet"
    if not p.exists():
        build(sym).to_parquet(p)
    return sym


def main(procs: int = 4):
    OUT.mkdir(parents=True, exist_ok=True)
    syms = list(INDEXES) + sorted({s for *_, csv, _ in SPLITS.values() for s in _snapshot(csv)})
    with Pool(procs) as pool:
        for i, _ in enumerate(pool.imap_unordered(_one, syms)):
            if (i + 1) % 50 == 0 or i < 7:
                print(f"features {i + 1}/{len(syms)}", flush=True)


if __name__ == "__main__":
    main()
