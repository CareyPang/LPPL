import numpy as np
import pandas as pd
import pytest

from research.data import cache
from research.data.sources import parse_code


@pytest.mark.parametrize("code,exp", [
    ("600519", ("sh", "600519", False)), ("000001", ("sh", "000001", True)),
    ("sz000001", ("sz", "000001", False)), ("000300", ("sh", "000300", True)),
    ("399006", ("sz", "399006", True)), ("300750", ("sz", "300750", False)),
])
def test_parse_code(code, exp):
    assert parse_code(code) == exp


def test_pit_load_uses_only_vintage_available_at_asof(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "ROOT", tmp_path)
    d = cache._sym_dir("sh000001", "qfq")
    man = []
    for vint, last in [("20240102", "2024-01-02"), ("20250102", "2025-01-02")]:
        dates = pd.bdate_range("2020-01-01", last)
        df = pd.DataFrame({"date": dates, "open": 1.0, "high": 1.0, "low": 1.0,
                           "close": np.linspace(1, 2, len(dates)), "volume": 1.0, "amount": 1.0})
        p = d / f"{vint}.parquet"
        df.to_parquet(p, index=False)
        man.append(dict(vintage=vint, source="test", rows=len(df), last_date=last, sha1="x", path=str(p)))
    (d / "manifest.json").write_text(pd.Series(man).to_json(orient="records"))

    df = cache.load("sh000001", asof="2024-06-30", auto_refresh=False)
    assert df.attrs["vintage"] == "20240102" and not df.attrs["pit_approx"]
    assert df["date"].max() <= pd.Timestamp("2024-06-30")

    df2 = cache.load("sh000001", asof="2023-06-30", auto_refresh=False)
    assert df2.attrs["pit_approx"] and df2.attrs["vintage"] == "20240102"
    assert df2["date"].max() <= pd.Timestamp("2023-06-30")

    df3 = cache.load("sh000001", auto_refresh=False)
    assert df3.attrs["vintage"] == "20250102"


def test_download_falls_through_on_bad_quality(monkeypatch):
    from research.data import sources as S

    dates = pd.bdate_range("2020-01-01", periods=300)
    good = pd.DataFrame({"date": dates, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "amount": 1.0})
    bad = good.assign(close=-1.0)
    calls = []

    def mk(name, df):
        def f(*a, **k):
            calls.append(name)
            return df
        return f

    monkeypatch.setitem(S.SOURCES, "eastmoney", mk("eastmoney", bad))
    monkeypatch.setitem(S.SOURCES, "sina", mk("sina", good))
    df, src = cache.download("600519", retries=1, backoff=0)
    assert src == "sina" and calls[0] == "eastmoney"
