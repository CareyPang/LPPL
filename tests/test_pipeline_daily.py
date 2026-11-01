import json
from pathlib import Path

import pandas as pd
import pytest

from research.eval.export_contract import _price_history
from research.pipeline import daily


def test_price_history_contains_aligned_point_in_time_ohlcv():
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    ohlc = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0, 11.0, 12.0],
            "high": [11.5, 12.5, 13.5],
            "low": [9.5, 10.5, 11.5],
            "close": [11.0, 12.0, 13.0],
            "volume": [1000, 2000, 3000],
        }
    )

    history = _price_history(ohlc, dates, pd.Timestamp("2024-01-03"))

    assert history["dates"] == ["2024-01-02", "2024-01-03"]
    assert all(len(history[key]) == len(history["dates"]) for key in ("open", "high", "low", "close", "volume"))
    assert all(isinstance(value, int) for value in history["volume"])
    for open_, high, low, close in zip(
        history["open"], history["high"], history["low"], history["close"], strict=True
    ):
        assert high >= max(open_, close) >= min(open_, close) >= low

    without_volume = _price_history(ohlc.drop(columns="volume"), dates, pd.Timestamp("2024-01-03"))
    assert without_volume["volume"] == [None, None]


@pytest.mark.skipif(not Path("data/frozen/v20261024").exists(), reason="需要冻结数据")
def test_daily_frozen_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("LPPLS_BOX", "v2")
    p = daily.run("sh000001", frozen=True, asof="2015-06-12", windows=(130, 200, 300), out=tmp_path, trust_boot=2)
    rec = json.loads(p.read_text())
    conf = rec["top"]["lppls_confidence"]
    assert set(["1-3m", "6-12m", "12-24m"]) <= set(conf)
    assert rec["top"]["p20"]["evidence"] == "fail_i_iii"
    assert rec["top"]["bubble"]["evidence"] == "descriptive"
    assert rec["data_version"].startswith("frozen_")
