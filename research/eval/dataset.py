"""逐日 as-of 样本集（预登记 §1、§3、§4）：标签 + 只用 ≤ t 价格算出的基础特征。
样本范围规则与 research/labels/run_top.py 一致：个股只在所属快照段、上市满 5 年后进入；成熟期未满的 t 不进入。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.stocks import CACHE
from ..labels.run_top import FROZEN, INDEXES, SPLITS, _snapshot
from ..labels.run_top import OUT as LABELS

VOL_WINDOWS = (20, 60, 120)
RET_WINDOWS = (20, 60, 120, 250)


def price_series(sym: str) -> pd.Series:
    if sym in INDEXES:
        d = pd.read_parquet(FROZEN / f"{sym}_qfq.parquet")
        return pd.Series(np.log(d.close.to_numpy(float)), index=pd.DatetimeIndex(d.date))
    d = pd.read_parquet(CACHE / f"{sym}.parquet")
    d = d[d.close_hfq > 0]
    return pd.Series(np.log(d.close_hfq.to_numpy(float)), index=pd.DatetimeIndex(d.date))


def base_features(logp: pd.Series) -> pd.DataFrame:
    r = logp.diff()
    f = {f"rv{w}": r.rolling(w).std(ddof=1) * np.sqrt(250) for w in VOL_WINDOWS}
    f.update({f"ret{w}": logp - logp.shift(w) for w in RET_WINDOWS})
    f["dd_from_max250"] = logp - logp.rolling(250).max()
    f["du_from_min250"] = logp - logp.rolling(250).min()
    f["rv_ratio"] = f["rv20"] / f["rv120"]
    return pd.DataFrame(f)


def assemble(split: str, variant: str = "main") -> pd.DataFrame:
    a, b, csv, entry = SPLITS[split]
    rows = []
    for group, syms in (("index", INDEXES), ("stock", sorted(_snapshot(csv)))):
        for sym in syms:
            p = LABELS / f"{sym}.parquet"
            if not p.exists():
                continue
            lab = pd.read_parquet(p)
            logp = price_series(sym)
            lo = pd.Timestamp(a)
            if group == "stock":
                lo = max(lo, pd.Timestamp(entry), logp.index[0] + pd.DateOffset(years=5))
            df = base_features(logp)
            df["y"] = lab[f"{variant}__y"].reindex(df.index)
            df["dd_ahead"] = lab[f"{variant}__dd_ahead"].reindex(df.index)
            df = df[(df.index >= lo) & (df.index <= pd.Timestamp(b))].dropna(subset=["y", "rv120"])
            df["symbol"] = sym
            df["group"] = group
            rows.append(df)
    out = pd.concat(rows).rename_axis("date").reset_index()
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)
