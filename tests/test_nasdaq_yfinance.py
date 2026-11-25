"""Offline contracts for the optional yfinance Nasdaq adapter."""

import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from research.data import nasdaq_yfinance as adapter
from research.data.trading_calendar import market_sessions


def raw(dates, *, ticker="^IXIC", layout="single"):
    dates = pd.DatetimeIndex(dates)
    frame = pd.DataFrame({
        "Open": 100.0, "High": 110.0, "Low": 90.0, "Close": 105.0,
        "Adj Close": 104.0, "Volume": 1000.0,
    }, index=dates)
    if layout == "field_first":
        frame.columns = pd.MultiIndex.from_tuples([(field, ticker) for field in frame.columns])
    elif layout == "ticker_first":
        frame.columns = pd.MultiIndex.from_tuples([(ticker, field) for field in frame.columns])
    return frame


def download(frame, root, *, now="2024-11-27T21:30:00+00:00", **kwargs):
    return adapter.download_nasdaq(
        "US_IXIC", root, fetched_at=datetime.fromisoformat(now),
        downloader=lambda **request: frame.copy(), **kwargs,
    )


def with_hash(info):
    return {**info, "normalized_sha256": "a" * 64, "raw_sha256": "b" * 64,
            "metadata_file": "previous.metadata.json"}


@pytest.mark.parametrize("layout", ["single", "field_first", "ticker_first"])
@pytest.mark.parametrize("asset_id,ticker", [("US_IXIC", "^IXIC"), ("US_NDX", "^NDX")])
def test_column_layouts_identity_and_raw_price_basis(tmp_path, layout, asset_id, ticker):
    calls = []

    def mock(**request):
        calls.append(request)
        return raw(["2024-11-26", "2024-11-27"], ticker=ticker, layout=layout)

    blob, frame, info = adapter.download_nasdaq(
        asset_id, tmp_path, fetched_at=datetime(2024, 11, 27, 21, 30, tzinfo=UTC), downloader=mock,
    )
    assert frame.close.tolist() == [105.0, 105.0]
    assert frame.adj_close.tolist() == [104.0, 104.0]
    assert frame.open.tolist() == [100.0, 100.0]
    assert frame.raw_open.equals(frame.open)
    assert frame.raw_close.equals(frame.close)
    assert frame.raw_volume.equals(frame.volume)
    assert info["id"] == asset_id
    assert info["ticker"] == ticker
    assert info["provider"] == "yfinance"
    assert info["normalizer_version"] == adapter.NORMALIZER_VERSION
    assert info["adjustment"] == "none"
    assert info["source"] == "Yahoo Finance via yfinance"
    assert calls[0] == {
        "tickers": ticker, "start": "2000-01-01", "interval": "1d", "auto_adjust": False,
        "repair": False, "threads": False, "progress": False, "ignore_tz": False, "timeout": 30,
    }
    captured = json.loads(blob)
    assert captured["ticker"] == ticker
    assert captured["payload"]["data"][0][3] == 105.0
    assert "latest.json" not in {p.name for p in tmp_path.rglob("*")}


def test_exchange_date_does_not_use_utc_calendar_day(tmp_path):
    timestamps = pd.to_datetime(["2024-11-27T00:30:00Z", "2024-11-28T00:30:00Z"])
    _, frame, info = download(raw(timestamps), tmp_path)
    assert frame.date.dt.strftime("%Y-%m-%d").tolist() == ["2024-11-26", "2024-11-27"]
    assert info["timezone"] == "America/New_York"


@pytest.mark.parametrize("now,expected", [
    ("2024-11-27T21:19:59+00:00", ["2024-11-26"]),
    ("2024-11-27T21:20:00+00:00", ["2024-11-26", "2024-11-27"]),
])
def test_regular_close_has_twenty_minute_grace(tmp_path, now, expected):
    _, frame, _ = download(raw(["2024-11-26", "2024-11-27"]), tmp_path, now=now)
    assert frame.date.dt.strftime("%Y-%m-%d").tolist() == expected


@pytest.mark.parametrize("now,expected", [
    ("2024-11-29T18:19:59+00:00", ["2024-11-27"]),
    ("2024-11-29T18:20:00+00:00", ["2024-11-27", "2024-11-29"]),
])
def test_early_close_holiday_weekend_and_grace(tmp_path, now, expected):
    # Thanksgiving is closed; Black Friday closes at 13:00 New York time.
    _, frame, info = download(
        raw(["2024-11-27", "2024-11-28", "2024-11-29", "2024-11-30"]), tmp_path, now=now,
    )
    assert frame.date.dt.strftime("%Y-%m-%d").tolist() == expected
    assert info["dropped_non_session_rows"] == 2
    assert info["dropped_non_session_dates"] == ["2024-11-28", "2024-11-30"]


def test_missing_optional_ohlcv_is_not_zero_or_fabricated(tmp_path):
    rows = raw(["2024-11-27"]).drop(columns=["Volume", "Open", "Adj Close"])
    blob, frame, _ = download(rows, tmp_path)
    assert frame.volume.isna().all()
    assert frame.raw_volume.isna().all()
    assert frame.open.isna().all()
    assert frame.adj_close.isna().all()
    assert b"NaN" not in blob


@pytest.mark.parametrize("field,value", [
    ("Close", 0), ("Close", -1), ("Close", np.nan), ("Close", np.inf),
    ("Open", -1), ("High", 102), ("Low", 106), ("Volume", -1), ("High", np.inf),
])
def test_bad_prices_are_rejected(tmp_path, field, value):
    rows = raw(["2024-11-27"])
    rows[field] = value
    with pytest.raises(ValueError):
        download(rows, tmp_path)


def test_duplicate_exchange_dates_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="Duplicate exchange dates"):
        download(raw(["2024-11-27", "2024-11-27"]), tmp_path)


def test_mixed_or_wrong_ticker_is_rejected(tmp_path):
    for layout in ("field_first", "ticker_first"):
        with pytest.raises(ValueError, match="identity"):
            download(raw(["2024-11-27"], ticker="^NDX", layout=layout), tmp_path)
    mixed = pd.concat([
        raw(["2024-11-27"], layout="field_first"),
        raw(["2024-11-27"], ticker="^NDX", layout="field_first"),
    ], axis=1)
    with pytest.raises(ValueError, match="mixed tickers"):
        download(mixed, tmp_path)
    single = raw(["2024-11-27"])
    single.attrs["symbol"] = "MRVL"
    with pytest.raises(ValueError, match="identity"):
        download(single, tmp_path)


def test_explicit_lazy_yfinance_cache_configuration(tmp_path, monkeypatch):
    calls = []
    fake_yf = SimpleNamespace(
        set_tz_cache_location=lambda location: calls.append(("cache", location)),
        download=lambda **request: (calls.append(("download", request)), raw(["2024-11-27"]))[1],
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    adapter.download_nasdaq(
        "US_IXIC", tmp_path, fetched_at=datetime(2024, 11, 27, 21, 30, tzinfo=UTC),
    )
    assert calls[0] == ("cache", str(tmp_path.resolve() / ".cache" / "yfinance"))
    assert calls[1][0] == "download"
    assert (tmp_path / ".cache" / "yfinance").is_dir()


def test_full_history_then_increment_preserves_over_6600_rows(tmp_path):
    dates = market_sessions("us", pd.Timestamp("1997-01-01"), pd.Timestamp("2024-11-26"))
    initial = raw(dates)
    requests = []

    def first(**request):
        requests.append(request)
        return initial

    _, previous, info = adapter.download_nasdaq(
        "US_IXIC", tmp_path, full_history=True,
        fetched_at=datetime(2024, 11, 26, 21, 30, tzinfo=UTC), downloader=first,
    )
    assert len(previous) > 6600
    assert requests[0]["period"] == "max"
    first_overlap = previous.date.iloc[-10]
    refreshed_dates = market_sessions("us", first_overlap, pd.Timestamp("2024-11-27"))
    refreshed = raw(refreshed_dates)
    refreshed.loc[first_overlap, "Close"] = 106.0

    def update(**request):
        requests.append(request)
        return refreshed

    blob, result, new_info = adapter.download_nasdaq(
        "US_IXIC", tmp_path, previous=previous, previous_info=with_hash(info),
        fetched_at=datetime(2024, 11, 27, 21, 30, tzinfo=UTC), downloader=update,
    )
    assert requests[1]["start"] == first_overlap.date().isoformat()
    assert "period" not in requests[1]
    assert len(result) == len(previous) + 1
    pd.testing.assert_frame_equal(result.iloc[:-11], previous.iloc[:-10])
    assert result.loc[result.date == first_overlap, "close"].iloc[0] == 106.0
    assert new_info["full_history_requested"] is True
    assert new_info["download_mode"] == "incremental_overlap"
    assert new_info["previous_normalized_sha256"] == "a" * 64
    assert new_info["previous_raw_sha256"] == "b" * 64
    assert new_info["overlap_revisions"]["changed_rows"] == 1
    assert new_info["overlap_revisions"]["changed_cells"] == 1
    assert len(json.loads(blob)["payload"]["data"]) == 11
    assert new_info["session_coverage"]["status"] == "complete"
    assert new_info["session_coverage"]["expected_sessions"] == len(result)
    assert new_info["session_coverage"]["observed_sessions"] == len(result)
    assert new_info["session_coverage"]["missing_sessions"] == 0
    assert new_info["session_coverage"]["through"] == "2024-11-27"


@pytest.mark.parametrize("failure", ["empty", "missing_old", "missing_new", "lagging"])
def test_incomplete_increment_never_overwrites_or_discards_previous(tmp_path, failure):
    dates = market_sessions("us", pd.Timestamp("2024-11-01"), pd.Timestamp("2024-11-25"))
    _, previous, info = download(raw(dates), tmp_path, now="2024-11-25T21:30:00+00:00")
    untouched = previous.copy(deep=True)
    incoming = raw(market_sessions("us", previous.date.iloc[-10], pd.Timestamp("2024-11-27")))
    if failure == "empty":
        incoming = incoming.iloc[:0]
    elif failure == "missing_old":
        incoming = incoming.drop(index=previous.date.iloc[-3])
    elif failure == "missing_new":
        incoming = incoming.drop(index=pd.Timestamp("2024-11-26"))
    else:
        incoming = incoming.loc[incoming.index <= pd.Timestamp("2024-11-25")]
    with pytest.raises(ValueError):
        download(incoming, tmp_path, previous=previous, previous_info=with_hash(info))
    pd.testing.assert_frame_equal(previous, untouched)
    assert not list(tmp_path.rglob("latest.json"))


@pytest.mark.parametrize("change", ["provider", "normalizer_version"])
def test_different_provider_or_normalizer_forces_independent_full_download(tmp_path, change):
    _, previous, info = download(raw(["2024-11-26", "2024-11-27"]), tmp_path, full_history=True)
    previous_info = with_hash(info)
    previous_info[change] = "other"
    requests = []

    def mock(**request):
        requests.append(request)
        result = raw(["2024-11-26", "2024-11-27"])
        result["Close"] = 107.0
        return result

    _, result, meta = adapter.download_nasdaq(
        "US_IXIC", tmp_path, previous=previous, previous_info=previous_info,
        fetched_at=datetime(2024, 11, 27, 21, 30, tzinfo=UTC), downloader=mock,
    )
    assert requests[0]["period"] == "max"
    assert "start" not in requests[0]
    assert result.close.tolist() == [107.0, 107.0]
    assert meta["previous_prefix_rows_preserved"] == 0
    assert meta["download_mode"] == "full"


def test_cache_mismatch_and_unaware_timestamp_rejected_before_network(tmp_path):
    _, previous, info = download(raw(["2024-11-26", "2024-11-27"]), tmp_path)

    def forbidden(**request):
        pytest.fail("Downloader called before validating the cache")

    for bad in ({**with_hash(info), "id": "US_NDX"}, {**with_hash(info), "ticker": "^NDX"},
                {**with_hash(info), "rows": 999}, {**with_hash(info), "normalized_sha256": None}):
        with pytest.raises(ValueError):
            adapter.download_nasdaq("US_IXIC", tmp_path, previous=previous, previous_info=bad, downloader=forbidden)
    with pytest.raises(ValueError, match="timezone-aware"):
        adapter.download_nasdaq("US_IXIC", tmp_path, fetched_at=datetime(2024, 11, 27), downloader=forbidden)
    with pytest.raises(ValueError, match="Only US_IXIC"):
        adapter.download_nasdaq("US_MRVL", tmp_path, downloader=forbidden)


def test_request_upgrade_to_full_history_does_not_reuse_short_cache(tmp_path):
    _, previous, info = download(raw(["2024-11-26", "2024-11-27"]), tmp_path)
    requests = []

    def mock(**request):
        requests.append(request)
        return raw(["2024-11-25", "2024-11-26", "2024-11-27"])

    _, frame, meta = adapter.download_nasdaq(
        "US_IXIC", tmp_path, previous=previous, previous_info=with_hash(info), full_history=True,
        fetched_at=datetime(2024, 11, 27, 21, 30, tzinfo=UTC), downloader=mock,
    )
    assert requests[0]["period"] == "max"
    assert len(frame) == 3
    assert meta["full_history_requested"] is True


def test_increment_refuses_unrequested_old_prefix_instead_of_duplicating_dates(tmp_path):
    dates = market_sessions("us", pd.Timestamp("2024-11-01"), pd.Timestamp("2024-11-27"))
    _, previous, info = download(raw(dates), tmp_path)
    with pytest.raises(ValueError, match="before the requested overlap"):
        download(raw(dates), tmp_path, previous=previous, previous_info=with_hash(info))


def test_full_download_rejects_internal_session_gap(tmp_path):
    with pytest.raises(ValueError, match="Full history coverage incomplete.*2024-11-26"):
        download(raw(["2024-11-25", "2024-11-27"]), tmp_path, full_history=True)
    assert not list(tmp_path.rglob("latest.json"))


def test_increment_rechecks_old_prefix_for_internal_session_gap(tmp_path):
    dates = market_sessions("us", pd.Timestamp("2024-11-01"), pd.Timestamp("2024-11-27"))
    _, previous, info = download(raw(dates), tmp_path, full_history=True)
    # Simulate an older checksum-verified cache with a gap outside the overlap.
    old = previous.loc[previous.date != pd.Timestamp("2024-11-05")].reset_index(drop=True)
    old_info = {**with_hash(info), "rows": len(old)}
    refreshed = raw(market_sessions("us", old.date.iloc[-10], pd.Timestamp("2024-11-27")))
    with pytest.raises(ValueError, match="Full history coverage incomplete.*2024-11-05"):
        download(refreshed, tmp_path, previous=old, previous_info=old_info)
    assert not list(tmp_path.rglob("latest.json"))
