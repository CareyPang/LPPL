"""起涨确认特征库（prereg §15.1）：python -m research.features.run_thrust
→ data/features/thrust_v1/{symbol}.parquet（放量、余震后首个上涨冲击、ret5）与 data/features/thrust_v1/_breadth.parquet（2010 快照成分股自算宽度）。"""
from __future__ import annotations

from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.dataset import SPLITS, _snapshot, price_series
from ..labels.run_top import INDEXES
from .run_bottom_feats import OUT as BFEAT
from .run_bottom_feats import inputs
from .thrust import breadth, thrust_features

OUT = Path("data/features/thrust_v1")


def _one(sym: str):
    p = OUT / f"{sym}.parquet"
    if not p.exists():
        logp, amt = inputs(sym)
        after = pd.read_parquet(BFEAT / f"{sym}.parquet")["after_ratio_25"].reindex(logp.index)
        thrust_features(logp, amt, after).to_parquet(p)
    return sym


def main(procs: int = 2):
    OUT.mkdir(parents=True, exist_ok=True)
    syms = list(INDEXES) + sorted({s for *_, csv, _ in SPLITS.values() for s in _snapshot(csv)})
    with Pool(procs) as pool:
        for i, _ in enumerate(pool.imap_unordered(_one, syms)):
            if (i + 1) % 100 == 0:
                print(f"thrust {i + 1}/{len(syms)}", flush=True)
    members = sorted(_snapshot(SPLITS["dev"][2]))
    px = pd.concat({s: price_series(s) for s in members if (BFEAT / f"{s}.parquet").exists()}, axis=1)
    px = px.where(px.notna() & (px.diff() != 0) | px.diff().isna())  # 停牌日（价格不变）视为缺失
    breadth(px.astype(float)).to_parquet(OUT / "_breadth.parquet")
    print("breadth done", np.round(len(px)), flush=True)


if __name__ == "__main__":
    main()
