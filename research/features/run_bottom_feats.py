"""底部候选特征库：python -m research.features.run_bottom_feats → data/features/bottom_v1/{symbol}.parquet（不入 git）。
成交额：指数用 amount；个股用 volume × 未复权 close 近似（prereg §14.2）。"""
from __future__ import annotations

from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.stocks import CACHE
from ..eval.dataset import SPLITS, _snapshot
from ..labels.run_top import FROZEN, INDEXES
from .bottom_feats import build

OUT = Path("data/features/bottom_v1")


def inputs(sym: str) -> tuple[pd.Series, pd.Series]:
    if sym in INDEXES:
        d = pd.read_parquet(FROZEN / f"{sym}_qfq.parquet")
        idx = pd.DatetimeIndex(d.date)
        amt = pd.Series(d.amount.to_numpy(float), idx)
        if not (amt > 0).any():  # 冻结指数数据 amount 为空时退回 volume × close（prereg §14.2 近似）
            amt = pd.Series((d.volume * d.close).to_numpy(float), idx)
        return pd.Series(np.log(d.close.to_numpy(float)), idx), amt
    d = pd.read_parquet(CACHE / f"{sym}.parquet")
    d = d[d.close_hfq > 0]
    idx = pd.DatetimeIndex(d.date)
    return pd.Series(np.log(d.close_hfq.to_numpy(float)), idx), pd.Series((d.volume * d.close).to_numpy(float), idx)


def _one(sym: str):
    p = OUT / f"{sym}.parquet"
    if not p.exists():
        logp, amt = inputs(sym)
        rv20 = logp.diff().rolling(20).std(ddof=1) * np.sqrt(250)
        build(logp, amt, rv20).to_parquet(p)
    return sym


def main(procs: int = 2):
    OUT.mkdir(parents=True, exist_ok=True)
    syms = list(INDEXES) + sorted({s for *_, csv, _ in SPLITS.values() for s in _snapshot(csv)})
    with Pool(procs) as pool:
        for i, _ in enumerate(pool.imap_unordered(_one, syms)):
            if (i + 1) % 100 == 0 or i < 7:
                print(f"bottom feats {i + 1}/{len(syms)}", flush=True)


if __name__ == "__main__":
    main()
