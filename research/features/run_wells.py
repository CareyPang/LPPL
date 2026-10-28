"""B5 支撑井特征库：python -m research.features.run_wells → data/features/wells_v1/{symbol}.parquet（不入 git）。"""
from __future__ import annotations

from multiprocessing import Pool
from pathlib import Path

import pandas as pd

from ..data.stocks import CACHE
from ..eval.dataset import SPLITS, _snapshot
from ..labels.run_top import FROZEN, INDEXES
from .wells import rolling_wells

OUT = Path("data/features/wells_v1")


def bars_for(sym: str) -> pd.DataFrame:
    if sym in INDEXES:
        d = pd.read_parquet(FROZEN / f"{sym}_qfq.parquet")
    else:
        d = pd.read_parquet(CACHE / f"{sym}.parquet")
        d = d[d.close_hfq > 0].copy()
        for c in ("high", "low", "close"):
            d[c] = d[c] * d.hfq_factor
    return d.set_index(pd.DatetimeIndex(d.date))[["high", "low", "close", "volume"]].astype(float)


def _one(sym: str):
    p = OUT / f"{sym}.parquet"
    if not p.exists():
        rolling_wells(bars_for(sym)).to_parquet(p)
    return sym


def main(procs: int = 2):
    OUT.mkdir(parents=True, exist_ok=True)
    syms = list(INDEXES) + sorted({s for *_, csv, _ in SPLITS.values() for s in _snapshot(csv)})
    with Pool(procs) as pool:
        for i, _ in enumerate(pool.imap_unordered(_one, syms)):
            if (i + 1) % 50 == 0 or i < 7:
                print(f"wells {i + 1}/{len(syms)}", flush=True)


if __name__ == "__main__":
    main()
