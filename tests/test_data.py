import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from research.data import cache, sources
from research.data.mx_check import _mx_close_rows
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


def _prices(periods=300):
    dates = pd.bdate_range("2020-01-01", periods=300)
    return pd.DataFrame(
        {
            "date": dates[:periods],
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
            "amount": 1.0,
        }
    )


def test_download_falls_back_when_source_raises(monkeypatch):
    good = _prices()
    calls = []

    def fail(*args, **kwargs):
        calls.append("first")
        raise RuntimeError("source unavailable")

    def succeed(*args, **kwargs):
        calls.append("second")
        return good

    monkeypatch.setitem(sources.SOURCES, "ak_em_stock", fail)
    monkeypatch.setitem(sources.SOURCES, "tencent_sina", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setitem(sources.SOURCES, "ak_sina_stock", succeed)
    df, src = cache.download("600519", retries=1, backoff=0)
    assert src == "ak_sina_stock"
    assert len(df) == len(good)
    assert calls == ["first", "second"]


def test_tencent_negative_stock_prices_fail_quality_gate_and_fallback(monkeypatch):
    good = _prices()
    bad = good.assign(close=-1.0)
    monkeypatch.setitem(sources.SOURCES, "tencent", lambda *args, **kwargs: bad)
    monkeypatch.setitem(sources.SOURCES, "ak_sina_stock", lambda *args, **kwargs: good)
    df, src = cache.download(
        "600519", order=("tencent", "ak_sina_stock"), retries=1, backoff=0
    )
    assert src == "ak_sina_stock"
    assert len(df) == len(good)


def test_default_source_orders_are_market_specific():
    assert sources.DEFAULT_ORDER == (
        "ak_em_index",
        "tencent_sina",
        "ak_tx_index",
        "ak_sina_index",
        "eastmoney",
        "tencent",
    )
    assert sources.STOCK_ORDER == (
        "ak_em_stock",
        "tencent_sina",
        "ak_sina_stock",
        "eastmoney",
        "ak_tx_stock",
        "tencent",
    )


@pytest.mark.parametrize(
    ("function_name", "fetcher", "expected_kwargs"),
    [
        (
            "stock_zh_a_hist",
            sources.fetch_ak_em_stock,
            {"symbol": "600519", "period": "daily", "adjust": "qfq"},
        ),
        (
            "stock_zh_a_hist_tx",
            sources.fetch_ak_tx_stock,
            {"symbol": "sh600519", "adjust": "qfq"},
        ),
    ],
)
def test_ak_stock_fetchers_forward_timeout_and_normalize(
    monkeypatch, function_name, fetcher, expected_kwargs
):
    import akshare as ak

    calls = []

    def fake_ak_fetcher(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "date": ["2024-01-02"],
                "open": ["1.0"],
                "high": ["2.0"],
                "low": ["0.5"],
                "close": ["1.5"],
                "volume": ["10"],
                "amount": ["15"],
            }
        )

    monkeypatch.setattr(ak, function_name, fake_ak_fetcher)
    result = fetcher("sh", "600519", False, adjust="qfq")

    assert calls == [{**expected_kwargs, "timeout": 15}]
    assert list(result.columns) == sources.COLS
    assert result.iloc[0].to_dict() == {
        "date": pd.Timestamp("2024-01-02"),
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10.0,
        "amount": 15.0,
    }


def test_rate_limit_enforces_interval(monkeypatch):
    clock = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setenv("CP_MIN_INTERVAL", "2")
    monkeypatch.setattr(sources, "_last_request", None)
    monkeypatch.setattr(sources.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sources.time, "sleep", sleep)
    monkeypatch.setattr(sources.random, "uniform", lambda low, high: 0.25)
    sources.rate_limit()
    sources.rate_limit()
    assert sleeps == [2.25]


def test_refresh_manifest_contains_download_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "ROOT", tmp_path)
    monkeypatch.setattr(
        cache,
        "_download_with_attempts",
        lambda *args, **kwargs: (
            _prices(),
            "test-source",
            [{"source": "failed-source", "error": "ConnectionError: offline"}],
        ),
    )
    record = cache.refresh("600519")
    manifest = cache._manifest(tmp_path / "sh600519" / "qfq")
    entry = manifest[0]
    assert record.source == "test-source"
    assert entry["adjust"] == "qfq"
    assert entry["downloaded_at"].endswith("+00:00")
    assert len(entry["sha256"]) == 64
    assert entry["first_date"] == "2020-01-01"
    assert entry["last_date"] == _prices().date.iloc[-1].strftime("%Y-%m-%d")
    assert entry["attempts"] == [
        {"source": "failed-source", "error": "ConnectionError: offline"}
    ]


def test_frozen_load_verifies_sha256_and_truncates_by_asof(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "FROZEN_ROOT", tmp_path)
    directory = tmp_path / "v20261024"
    directory.mkdir()
    data = _prices()
    path = directory / "sh600519_qfq.parquet"
    data.to_parquet(path, index=False)
    entry = {
        "symbol": "sh600519",
        "adjust": "qfq",
        "source": "test",
        "vintage": "20261024",
        "downloaded_at": "2026-10-24T00:00:00+00:00",
        "rows": len(data),
        "first_date": data.date.iloc[0].strftime("%Y-%m-%d"),
        "last_date": data.date.iloc[-1].strftime("%Y-%m-%d"),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "quality_check": cache.quality_check(data),
    }
    (directory / "manifest.json").write_text(json.dumps([entry]))

    loaded = cache.load("600519", asof="2020-06-01", frozen="v20261024")
    assert loaded.date.max() <= pd.Timestamp("2020-06-01")
    assert loaded.attrs["frozen"] == "v20261024"
    assert loaded.attrs["pit_approx"]

    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="校验失败"):
        cache.load("600519", frozen="v20261024")


def test_mx_parser_handles_units_and_weekday_suffixes():
    response = {
        "status": 0,
        "data": {
            "data": {
                "searchDataResultDTO": {
                    "dataTableDTOList": [
                        {
                            "nameMap": {"325898": "收盘价"},
                            "table": {
                                "headName": ["2026-10-23(日)", "2026-10-22(日)"],
                                "325898": ["3690.4753点", "3658.0256点"],
                            },
                        }
                    ]
                }
            }
        },
    }
    rows = _mx_close_rows(response)
    assert rows["date"].tolist() == [
        pd.Timestamp("2026-10-22"),
        pd.Timestamp("2026-10-23"),
    ]
    assert rows["mx_close"].tolist() == [3658.0256, 3690.4753]
