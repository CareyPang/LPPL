import sys
from types import SimpleNamespace

import pandas as pd

from research.data import sources


def test_csindex_index_source_returns_open_ohlc_without_network(monkeypatch):
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "日期": ["2026-11-17"],
                "开盘": [100.0],
                "最高": [102.0],
                "最低": [99.0],
                "收盘": [101.0],
                "成交量": [1000],
                "成交额": [100000],
            }
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_zh_index_hist_csindex=fetch),
    )

    result = sources.fetch_ak_csindex_index(
        "sh", "000852", True, start="2005-01-01", end="2026-11-18"
    )

    assert calls == [
        {
            "symbol": "000852",
            "start_date": "20050101",
            "end_date": "20261118",
        }
    ]
    assert list(result.columns) == sources.COLS
    assert result.loc[0, "open"] == 100.0
    assert result.loc[0, "close"] == 101.0
