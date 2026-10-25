"""§17.6-5 价值分数（泡沫 ≠ 高估，Sornette–Cauwels 2015 §3.6）：指数市盈率的 PIT 滚动分位。

数据源：乐咕乐股（经 akshare）月频 PE——上证 1999 起（stock_market_pe_lg），上证50/沪深300/中证500/创业板 2005 起
（stock_index_pe_lg，滚动市盈率）。限制：序列由数据商事后整理，非严格 PIT；使用时加 1 个月发布滞后，并只用当时已有的历史做分位。
缓存：data/cache/valuation/<key>.parquet。用法：python -m research.data.valuation
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path("data/cache/valuation")
INDEX_MAP = {"sh000001": ("market", "上证"), "sh000016": ("index", "上证50"), "sh000300": ("index", "沪深300"),
             "sh000905": ("index", "中证500"), "sz399006": ("index", "创业板50"), "sz399001": ("market", "深证")}
LAG_MONTHS, LOOKBACK_YEARS, MIN_MONTHS = 1, 10, 36


def fetch(sym: str) -> pd.Series:
    import akshare as ak

    kind, name = INDEX_MAP[sym]
    if kind == "market":
        df = ak.stock_market_pe_lg(symbol=name)
        s = pd.Series(df["平均市盈率"].to_numpy(float), index=pd.to_datetime(df["日期"]))
    else:
        df = ak.stock_index_pe_lg(symbol=name)
        col = "滚动市盈率" if "滚动市盈率" in df else df.columns[3]
        s = pd.Series(df[col].to_numpy(float), index=pd.to_datetime(df["日期"]))
    s = s[~s.index.duplicated(keep="last")]
    return s.sort_index().rename("pe")


def load(sym: str, refresh: bool = False) -> pd.Series:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{sym}.parquet"
    if p.exists() and not refresh:
        return pd.read_parquet(p)["pe"]
    s = fetch(sym)
    s.to_frame().to_parquet(p)
    return s


def value_score(pe: pd.Series, daily_index: pd.DatetimeIndex) -> pd.Series:
    """PIT 分位：第 k 个月的 PE 相对其前 LOOKBACK_YEARS 年（含）历史的分位；发布滞后 LAG_MONTHS 个月后前向填充到日频。"""
    vals = pe.to_numpy(float)
    out = np.full(len(pe), np.nan)
    for k in range(len(pe)):
        lo = pe.index[k] - pd.DateOffset(years=LOOKBACK_YEARS)
        hist = vals[(pe.index <= pe.index[k]) & (pe.index >= lo)]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= MIN_MONTHS and np.isfinite(vals[k]):
            out[k] = (hist <= vals[k]).mean()
    s = pd.Series(out, index=pe.index + pd.DateOffset(months=LAG_MONTHS))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.reindex(s.index.union(daily_index)).ffill().reindex(daily_index).rename("value_pct")


if __name__ == "__main__":
    import time

    from ..eval.dataset import price_series

    for sym in INDEX_MAP:
        try:
            pe = load(sym)
            vs = value_score(pe, price_series(sym).index)
            a, b, c = vs.loc["2000":"2018"].mean(), vs.get(pd.Timestamp("2007-10-16"), np.nan), vs.get(pd.Timestamp("2015-06-12"), np.nan)
            print(sym, "months", len(pe), pe.index[0].date(), "->", pe.index[-1].date(), f"| value_pct dev mean {a:.2f}  2007-10 {b:.2f}  2015-06 {c:.2f}")
        except Exception as e:  # noqa: BLE001
            print(sym, "FAIL", type(e).__name__, str(e)[:100])
        time.sleep(3)
