"""tencent_sina：复权因子套用的离线测试 + 可选联网对账（CP_NET=1）。"""
import os

import pandas as pd
import pytest

from research.data import tencent_sina as T


def test_apply_factors_qfq_hfq():
    raw = pd.DataFrame({"date": ["2020-01-02", "2020-06-30", "2021-01-04"], "open": [10.0, 20.0, 30.0], "high": [10, 20, 30],
                        "low": [10, 20, 30], "close": [10.0, 20.0, 30.0], "volume": [1, 1, 1], "amount": [None] * 3})
    f = pd.DataFrame({"date": ["2020-06-20", "2020-12-20"], "factor": [2.0, 1.0]})
    q = T.apply_factors(raw, f, "qfq")
    assert list(q.close.round(3)) == [5.0, 10.0, 30.0]  # 首行无更早因子 → 回填 2.0；6-30 用 2.0；2021 用 1.0
    h = T.apply_factors(raw, f, "hfq")
    assert list(h.close.round(3)) == [20.0, 40.0, 30.0]


@pytest.mark.skipif(os.environ.get("CP_NET") != "1", reason="需要联网")
def test_live_index_matches_frozen():
    fz = pd.read_parquet("data/frozen/v20261024/sh000001_qfq.parquet")
    df = T.fetch_tencent_sina("sh", "000001", True)
    m = fz.assign(date=pd.to_datetime(fz.date)).merge(df.assign(date=pd.to_datetime(df.date)), on="date", suffixes=("_fz", "_tx"))
    assert len(m) > 6000 and ((m.close_fz - m.close_tx).abs() / m.close_fz).max() < 1e-6
