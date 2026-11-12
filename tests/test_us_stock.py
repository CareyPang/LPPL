import json
from pathlib import Path

import pandas as pd
import pytest

from research.data.us_stock import (
    adjust_prices,
    load_us_prices,
    parse_daily,
    parse_factors,
)
from research.pipeline import stock, us_nightly

FIXTURE = Path(__file__).parent / "fixtures/us_stocks/adjustment_boundaries.json"


def _bar(day, close):
    return {
        "date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1,
        "amount": close,
    }


def test_nvda_split_boundary_is_continuous():
    sample = json.loads(FIXTURE.read_text(encoding="utf-8"))["NVDA"]
    adjusted = adjust_prices(sample["rows"], sample["factors"]).set_index("date")
    assert adjusted.loc["2024-06-07", "close"] == pytest.approx(120.888)
    assert adjusted.loc["2024-06-10", "close"] == pytest.approx(121.79)
    assert adjusted.loc["2024-06-10", "close"] / adjusted.loc["2024-06-07", "close"] == pytest.approx(
        1.00746, rel=1e-4
    )


def test_aapl_dividend_only_boundary_uses_multiplicative_cash_ratio():
    sample = json.loads(FIXTURE.read_text(encoding="utf-8"))["AAPL"]
    adjusted = adjust_prices(sample["rows"], sample["factors"]).set_index("date")
    expected = 1 - 0.27 / 313.33
    assert adjusted.loc["2026-08-07", "close"] / 313.33 == pytest.approx(expected)


def test_non_positive_adjusted_close_is_rejected():
    rows = [
        {"date": "2024-01-01", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1, "amount": 100},
        {"date": "2024-01-02", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1, "amount": 100},
    ]
    factors = [
        {"date": "2024-01-01", "factor": 1, "cash": -200},
        {"date": "2024-01-02", "factor": 1, "cash": 0},
    ]
    with pytest.raises(ValueError, match="non-positive adjusted close"):
        adjust_prices(rows, factors)


def test_adjustment_keeps_only_the_recent_contiguous_segment():
    rows = [
        _bar("2004-12-31", 100),
        _bar("2009-09-16", 10),
        _bar("2009-09-17", 5.1),
        _bar("2009-09-18", 5.2),
    ]
    factors = [
        {"date": "1999-01-01", "factor": 0.25, "cash": 0},
        {"date": "2000-01-01", "factor": 0.5, "cash": 0},
        {"date": "2009-09-17", "factor": 1, "cash": 0},
    ]

    adjusted = adjust_prices(rows, factors)

    assert adjusted.date.tolist() == ["2009-09-16", "2009-09-17", "2009-09-18"]
    assert adjusted.close.tolist() == pytest.approx([5, 5.1, 5.2])
    assert adjusted.attrs["history_start"] == "2009-09-16"
    assert adjusted.attrs["raw_gap"] == {
        "left": "2004-12-31",
        "right": "2009-09-16",
        "days": (pd.Timestamp("2009-09-16") - pd.Timestamp("2004-12-31")).days,
    }
    assert adjusted.attrs["history_note"] == (
        "新浪美股日线在 2004-12-31–2009-09-16 缺失，只使用 "
        "2009-09-16 之后的连续数据"
    )


def test_adjustment_without_a_long_gap_is_unchanged():
    rows = [
        _bar("2026-01-05", 10),
        _bar("2026-01-06", 10.1),
        _bar("2026-01-07", 10.2),
    ]
    factors = [{"date": "2026-01-01", "factor": 1, "cash": 0}]

    adjusted = adjust_prices(rows, factors)

    assert adjusted.date.tolist() == [row["date"] for row in rows]
    assert adjusted.close.tolist() == pytest.approx([10, 10.1, 10.2])
    assert adjusted.attrs["history_start"] == "2026-01-05"
    assert adjusted.attrs["raw_gap"] is None
    assert adjusted.attrs["history_note"] is None


def test_loader_fails_when_contiguous_segment_has_fewer_than_1000_bars(monkeypatch):
    response = type(
        "Response",
        (),
        {
            "text": (
                'var([{"d":"2026-01-05","o":"10","h":"10","l":"10",'
                '"c":"10","v":"1","a":"10"}]);'
            ),
            "raise_for_status": lambda self: None,
        },
    )()
    monkeypatch.setattr("research.data.us_stock.requests.get", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="1 bars \\(<1000\\)"):
        load_us_prices("NVDA")


def test_sina_response_parsers_accept_jsonp_and_trailing_factor_comment():
    daily = 'var([{"d":"2024-01-02","o":"10","h":"11","l":"9","c":"10.5","v":"20","a":"210"}]);'
    factor = 'var NVDA_qfq={"data":[{"d":"2024-01-02","f":"1","c":"0"}]}/* base64 */'
    assert parse_daily(daily)[0]["close"] == 10.5
    assert parse_factors(factor)[0] == {
        "date": "2024-01-02",
        "factor": 1.0,
        "cash": 0.0,
    }


def test_us_ticker_normalization_and_loader_dispatch(monkeypatch):
    assert stock._validate_code("nvda") == "US_NVDA"
    assert stock._validate_code("US_aapl") == "US_AAPL"
    assert stock._validate_code("600519") == "600519"
    assert stock._name_and_st("US_NVDA") == ("英伟达", False)
    expected = (object(), "version", {})
    monkeypatch.setattr(stock, "load_us_stock", lambda code, start=None: expected)
    assert stock.load_stock("nvda") is expected


def test_us_stock_loader_preserves_gap_metadata(monkeypatch):
    prices = pd.DataFrame(
        {
            "date": ["2026-11-10", "2026-11-11"],
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [10, 11],
        }
    )
    raw_gap = {"left": "2004-12-31", "right": "2009-09-16", "days": 1720}
    history_meta = {
        "history_start": "2009-09-16",
        "raw_gap": raw_gap,
        "history_note": "新浪美股日线在 2004-12-31–2009-09-16 缺失，只使用 2009-09-16 之后的连续数据",
    }
    monkeypatch.setattr(
        stock.us_stock,
        "load_us_prices",
        lambda ticker, start: (prices, "version", history_meta),
    )
    monkeypatch.setattr(stock, "_close_cutoff", lambda now: pd.Timestamp("2026-11-11"))

    _, _, meta = stock.load_us_stock("US_NVDA")

    assert {key: meta[key] for key in history_meta} == history_meta


def test_us_reference_calendar_uses_spy(monkeypatch):
    calls = []
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-11-10", "2026-11-11"])})
    monkeypatch.setattr(
        stock,
        "load_us_stock",
        lambda code: (calls.append(code) or frame, "version", {}),
    )
    stock._us_reference_calendar.cache_clear()
    assert list(stock._us_reference_calendar(pd.Timestamp("2026-11-11"))) == list(
        pd.to_datetime(["2026-11-10", "2026-11-11"])
    )
    assert calls == ["US_SPY"]
    stock._us_reference_calendar.cache_clear()


def test_us_nightly_shard_assignment_uses_watchlist_index_modulo():
    tickers = ("NVDA", "AMD", "MRVL", "AVGO", "TSM", "ARM", "MU")

    shards = [
        us_nightly.shard_tickers(shard, 3, tickers)
        for shard in range(3)
    ]

    assert shards == [
        ("NVDA", "AVGO", "MU"),
        ("AMD", "TSM"),
        ("MRVL", "ARM"),
    ]
    assert sorted(ticker for shard in shards for ticker in shard) == sorted(tickers)
    with pytest.raises(ValueError, match="shard must be in range"):
        us_nightly.shard_tickers(3, 3, tickers)


def test_us_nightly_index_builder_uses_current_and_error_files(tmp_path, monkeypatch):
    monkeypatch.setattr(us_nightly, "US_WATCHLIST", ("NVDA", "AAPL", "AMD"))
    (tmp_path / "US_NVDA.json").write_text(
        json.dumps({"asof": "2026-11-11"}), encoding="utf-8"
    )
    (tmp_path / "US_AAPL.json").write_text(
        json.dumps({"asof": "2026-11-10"}), encoding="utf-8"
    )
    (tmp_path / "US_AAPL_error.json").write_text(
        json.dumps({"error": "refresh failed"}), encoding="utf-8"
    )
    (tmp_path / "US_AMD_error.json").write_text(
        json.dumps({"error": "no current record"}), encoding="utf-8"
    )

    index = us_nightly.build_index(tmp_path)

    assert index == [
        {
            "ticker": "NVDA",
            "name": us_nightly.US_NAMES["NVDA"],
            "asof": "2026-11-11",
            "ok": True,
        },
        {
            "ticker": "AAPL",
            "name": us_nightly.US_NAMES["AAPL"],
            "asof": "2026-11-10",
            "ok": False,
        },
        {
            "ticker": "AMD",
            "name": us_nightly.US_NAMES["AMD"],
            "asof": None,
            "ok": False,
        },
    ]


def test_nightly_continues_after_ticker_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(us_nightly, "US_WATCHLIST", ("NVDA", "AAPL"))

    def fake_predict(code, **kwargs):
        if code == "US_NVDA":
            raise RuntimeError("fixture failure")
        return {"asof": "2026-11-11"}

    monkeypatch.setattr(us_nightly, "predict", fake_predict)
    monkeypatch.setattr(us_nightly, "history", lambda *args, **kwargs: {"frames": []})
    index = us_nightly.run(tmp_path, weeks=8, procs=1)
    assert [row["ok"] for row in index] == [False, True]
    assert (tmp_path / "US_NVDA_error.json").exists()
    assert (tmp_path / "US_AAPL.json").exists()
    assert json.loads((tmp_path / "us_index.json").read_text()) == index
