"""Offline contracts for global source validation and daily publication."""
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests
import yaml

from research.data import global_terminal as source
from research.data.trading_calendar import completed_market_sessions
from research.pipeline import global_terminal as pipeline

ROOT = Path(__file__).resolve().parents[1]


def _close_frame(dates, values):
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": values})


def test_cross_check_passes_when_relative_differences_are_within_half_percent():
    dates = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"])
    yahoo = _close_frame(dates, [100.0, 101.0, 99.0])
    reference = _close_frame(dates, [100.2, 101.2, 99.3])

    result = source.compare_cross_check(
        yahoo,
        reference,
        "us",
        "fixture",
        datetime(2026, 11, 25, tzinfo=UTC),
        sessions=pd.DatetimeIndex(dates),
    )

    assert result["status"] == "ok"
    assert result["provider"] == "fixture"
    assert result["overlap"] == 3
    assert result["max_rel_diff"] <= 0.005
    assert result["missing_in_yahoo"] == 0


def test_one_percent_cross_check_difference_is_a_mismatch():
    dates = pd.to_datetime(["2026-11-23", "2026-11-24"])
    yahoo = _close_frame(dates, [101.0, 100.0])
    reference = _close_frame(dates, [100.0, 100.0])

    result = source.compare_cross_check(
        yahoo,
        reference,
        "us",
        "fixture",
        datetime(2026, 11, 25, tzinfo=UTC),
        sessions=pd.DatetimeIndex(dates),
    )

    assert result["status"] == "mismatch"
    assert result["max_rel_diff"] == pytest.approx(0.01)
    assert result["mismatches"] == [{
        "date": "2026-11-23",
        "field": "close",
        "primary_value": 101.0,
        "reference_value": 100.0,
        "rel_diff": pytest.approx(0.01),
    }]


def test_second_source_session_missing_in_yahoo_is_a_mismatch():
    dates = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"])
    yahoo = _close_frame(dates[[0, 2]], [100.0, 99.0])
    reference = _close_frame(dates, [100.0, 101.0, 99.0])

    result = source.compare_cross_check(
        yahoo,
        reference,
        "us",
        "fixture",
        datetime(2026, 11, 25, tzinfo=UTC),
        sessions=pd.DatetimeIndex(dates),
    )

    assert result["status"] == "mismatch"
    assert result["overlap"] == 2
    assert result["missing_in_yahoo"] == 1
    assert result["missing_in_yahoo_dates"] == ["2026-11-23"]


def test_reference_sessions_after_yahoo_last_date_are_recorded_as_lag_not_mismatch():
    dates = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"])
    yahoo = _close_frame(dates[:2], [100.0, 101.0])
    reference = _close_frame(dates, [100.0, 101.0, 99.0])

    result = source.compare_cross_check(
        yahoo,
        reference,
        "us",
        "fixture",
        datetime(2026, 11, 25, tzinfo=UTC),
        sessions=pd.DatetimeIndex(dates),
    )

    assert result["status"] == "ok"
    assert result["overlap"] == 2
    assert result["missing_in_yahoo"] == 0
    assert result["missing_in_yahoo_dates"] == []
    assert result["yahoo_lag_sessions"] == 1
    assert result["yahoo_lag_session_dates"] == ["2026-11-24"]


def test_yahoo_secondary_sessions_after_naver_last_date_are_recorded_as_primary_lag():
    dates = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"])
    naver = _close_frame(dates[:2], [100.0, 101.0])
    yahoo = _close_frame(dates, [100.0, 101.0, 99.0])

    result = source.compare_cross_check(
        naver,
        yahoo,
        "kr",
        "yahoo_chart_ohlcv_only",
        datetime(2026, 11, 25, tzinfo=UTC),
        sessions=pd.DatetimeIndex(dates),
        compare_fields=("close",),
        primary_label="naver",
    )

    assert result["status"] == "ok"
    assert result["overlap"] == 2
    assert result["missing_in_primary"] == 0
    assert result["primary_lag_sessions"] == 1
    assert result["primary_lag_session_dates"] == ["2026-11-24"]


def test_yahoo_secondary_missing_common_range_session_is_a_mismatch():
    dates = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"])
    naver = _close_frame(dates, [100.0, 101.0, 99.0])
    yahoo = _close_frame(dates[[0, 2]], [100.0, 99.0])

    result = source.compare_cross_check(
        naver,
        yahoo,
        "kr",
        "yahoo_chart_ohlcv_only",
        datetime(2026, 11, 25, tzinfo=UTC),
        sessions=pd.DatetimeIndex(dates),
        primary_label="naver",
        yahoo_source_is_reference=True,
    )

    assert result["status"] == "mismatch"
    assert result["missing_in_yahoo"] == 1
    assert result["missing_in_yahoo_dates"] == ["2026-11-23"]


def test_cross_check_records_unavailable_provider_reason(monkeypatch):
    def fail(*_args, **_kwargs):
        raise requests.ConnectionError("offline fixture")

    monkeypatch.setattr(source.requests, "get", fail)
    yahoo = _close_frame(["2026-11-23"], [100.0])

    result = source.fetch_cross_check(
        "JP_N225", yahoo, datetime(2026, 11, 24, tzinfo=UTC)
    )

    assert result["status"] == "unavailable"
    assert result["provider"] == "fredgraph_csv"
    assert "offline fixture" in result["reason"]


def test_fred_cross_check_parses_daily_csv_and_skips_missing_values(monkeypatch):
    calls = []

    class Response:
        content = b"observation_date,SP500\n2026-11-20,100\n2026-11-23,.\n2026-11-24,101\n"

        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(source.requests, "get", get)
    frame = source._fetch_fred_cross_check("US_SPX")

    assert calls[0][0] == "https://fred.stlouisfed.org/graph/fredgraph.csv"
    assert calls[0][1]["params"] == {"id": "SP500"}
    assert frame.date.dt.strftime("%Y-%m-%d").tolist() == ["2026-11-20", "2026-11-24"]
    assert frame.close.tolist() == [100.0, 101.0]


def test_sina_daily_jsonp_uses_skill_endpoint_params_and_fields(monkeypatch):
    calls = []

    class Response:
        text = 'var([{"d":"2026-11-23","o":"100","h":"102","l":"99","c":"101","v":"8"}]);'

        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(source.requests, "get", get)
    frame = source._fetch_sina_cross_check("US_MRVL")

    assert calls[0][0] == "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK"
    assert calls[0][1]["params"] == {"symbol": "MRVL", "num": 260}
    assert calls[0][1]["headers"] == {"Referer": "https://finance.sina.com.cn/"}
    assert frame.date.dt.strftime("%Y-%m-%d").tolist() == ["2026-11-23"]
    assert frame.close.tolist() == [101.0]


def test_nasdaq_failure_marks_sox_cross_check_unavailable(monkeypatch):
    monkeypatch.setattr(source, "_fetch_nasdaq_cross_check", lambda *_args: (_ for _ in ()).throw(requests.HTTPError("offline")))
    result = source.fetch_cross_check(
        "US_SOX", _close_frame(["2026-11-23"], [100.0]), datetime(2026, 11, 24, tzinfo=UTC)
    )

    assert result["provider"] == "nasdaq_api"
    assert result["status"] == "unavailable"
    assert "offline" in result["reason"]


def test_hynix_cross_check_uses_naver_sise_json_stock_symbol(monkeypatch):
    calls = []
    response_data = [
        ["날짜", "시가", "고가", "저가", "종가", "거래량", "외국인소진율"],
        ["20261123", 100, 102, 99, 101, 1000, 0],
    ]

    class Response:
        content = repr(response_data).encode("utf-8")

        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(source.requests, "get", get)
    frame = source._fetch_naver_cross_check(
        "KR_SKHYNIX", datetime(2026, 11, 24, tzinfo=UTC)
    )

    assert calls[0][0] == "https://api.finance.naver.com/siseJson.naver"
    assert calls[0][1]["params"]["symbol"] == "000660"
    assert calls[0][1]["params"]["timeframe"] == "day"
    assert frame.close.tolist() == [101.0]


def test_daum_daily_response_parses_unadjusted_chart_rows(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{
                "date": "2026-11-23T00:00:00+09:00",
                "openingPrice": "1,500,000",
                "highPrice": "1,510,000",
                "lowPrice": "1,490,000",
                "tradePrice": "1,500,000",
                "candleAccTradeVolume": "500",
            }]}

    calls = []
    monkeypatch.setattr(source.requests, "get", lambda url, **kwargs: (calls.append((url, kwargs)) or Response()))
    frame = source._fetch_daum_cross_check("KR_SKHYNIX")
    assert calls[0][0] == "https://finance.daum.net/api/charts/A000660/days"
    assert calls[0][1]["params"] == {"limit": 300, "adjusted": "false"}
    assert calls[0][1]["headers"] == {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120 Safari/537.36"
        ),
        "Referer": "https://finance.daum.net/quotes/A000660",
        "Accept": "application/json, text/plain, */*",
    }
    assert frame.date.dt.strftime("%Y-%m-%d").tolist() == ["2026-11-23"]
    assert frame[["open", "high", "low", "close", "volume"]].iloc[0].tolist() == [
        1500000, 1510000, 1490000, 1500000, 500
    ]


def test_daum_cross_check_compares_ohlc_and_flags_shared_session_gaps(monkeypatch):
    dates = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"])
    primary = pd.DataFrame({
        "date": dates,
        "open": [100.0, 101.0, 102.0],
        "high": [102.0, 103.0, 104.0],
        "low": [99.0, 100.0, 101.0],
        "close": [101.0, 102.0, 103.0],
        "volume": [1000.0, 1100.0, 1200.0],
    })
    reference = primary.iloc[[0, 2]].copy()
    reference.loc[2, "high"] = 102.0
    monkeypatch.setattr(source, "_fetch_daum_cross_check", lambda *_args: reference)

    result = source.fetch_cross_check(
        "KR_SKHYNIX", primary, datetime(2026, 11, 25, tzinfo=UTC)
    )

    assert result["provider"] == "daum_finance_daily"
    assert result["status"] == "mismatch"
    assert result["missing_in_reference_dates"] == ["2026-11-23"]
    assert result["comparison_fields"] == ["open", "high", "low", "close"]
    assert result["excluded_fields"] == ["volume"]
    assert result["mismatches"] == [{
        "date": "2026-11-24",
        "field": "high",
        "primary_value": 104.0,
        "reference_value": 102.0,
        "rel_diff": pytest.approx(2 / 102),
    }]


def test_skhynix_yahoo_fallback_compares_ohl_only_and_records_exclusions(monkeypatch):
    dates = pd.to_datetime(["2026-11-23"])
    primary = pd.DataFrame({
        "date": dates, "close": [101.0], "raw_close": [101.0],
        "open": [99.0], "high": [103.0], "low": [98.0], "volume": [4928269.0],
    })
    reference = pd.DataFrame({
        "date": dates, "raw_close": [90.0], "raw_open": [99.0],
        "raw_high": [103.0], "raw_low": [98.0], "raw_volume": [151.0],
    })
    monkeypatch.setattr(source.time_module, "sleep", lambda *_args: None)
    monkeypatch.setattr(
        source,
        "_fetch_daum_cross_check",
        lambda *_args: (_ for _ in ()).throw(requests.HTTPError("403")),
    )
    monkeypatch.setattr(source, "_fetch_yahoo_cross_check", lambda *_args: reference)

    result = source.fetch_cross_check("KR_SKHYNIX", primary, datetime(2026, 11, 24, tzinfo=UTC))

    assert result["provider"] == "yahoo_chart_ohl_only"
    assert result["status"] == "ok"
    assert result["max_rel_diff"] == 0
    assert result["missing_in_yahoo"] == 0
    assert result["missing_in_yahoo_dates"] == []
    assert result["mismatches"] == []
    assert result["comparison_fields"] == ["open", "high", "low"]
    assert result["excluded_fields"] == ["close", "volume"]
    assert "close and volume are unreliable" in result["excluded_fields_reason"]
    assert "403" in result["fallback_reason"]

    mismatch_reference = reference.copy()
    mismatch_reference.loc[0, "raw_high"] = 102.0
    monkeypatch.setattr(source, "_fetch_yahoo_cross_check", lambda *_args: mismatch_reference)
    mismatch = source.fetch_cross_check("KR_SKHYNIX", primary, datetime(2026, 11, 24, tzinfo=UTC))

    assert mismatch["status"] == "mismatch"
    assert mismatch["mismatches"] == [{
        "date": "2026-11-23",
        "field": "high",
        "primary_value": 103.0,
        "reference_value": 102.0,
        "rel_diff": pytest.approx(1 / 102),
    }]


def test_nasdaq_sox_parser_uses_official_history_response(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"tradesTable": {"rows": [{
                "date": "11/23/2026", "close": "1,234.50", "open": "1,200.00",
                "high": "1,250.00", "low": "1,190.00", "volume": "--",
            }]}}}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(source.requests, "get", get)
    frame = source._fetch_nasdaq_cross_check("US_SOX", datetime(2026, 11, 24, tzinfo=UTC))
    assert calls[0][0] == "https://api.nasdaq.com/api/quote/SOX/historical"
    assert calls[0][1]["params"]["assetclass"] == "index"
    assert frame.close.tolist() == [1234.5]
    assert np.isnan(frame.volume.iloc[0])


def test_yahoo_session_validation_drops_non_sessions_and_counts_missing_rows():
    fetched_at = datetime(2026, 12, 1, tzinfo=UTC)
    expected = completed_market_sessions("us", pd.Timestamp(fetched_at))
    valid_dates = expected.delete(17)
    dates = pd.DatetimeIndex([*valid_dates, pd.Timestamp("2026-11-29")]).sort_values()
    frame = pd.DataFrame({"date": dates, "close": 100.0, "raw_close": 100.0})

    filtered, metadata = source.validate_market_sessions(frame, "us", fetched_at)

    assert len(filtered) == 249
    assert metadata["dropped_non_session_rows"] == 1
    assert metadata["dropped_non_session_dates"] == ["2026-11-29"]
    assert metadata["missing_sessions_last_250"] == 1
    assert metadata["missing_sessions_last_250_dates"] == [
        expected[17].date().isoformat()
    ]


def test_mismatched_asset_preserves_previous_latest_and_history(tmp_path, monkeypatch):
    root = tmp_path / "run"
    global_dir = root / "global"
    global_dir.mkdir(parents=True)
    latest_path = global_dir / "US_SPX_latest.json"
    history_path = global_dir / "US_SPX_history.json"
    latest_bytes = b'{"symbol":"US_SPX","asof":"2026-11-20"}\n'
    history_bytes = b'{"symbol":"US_SPX","frames":[{"asof":"2026-11-20"}]}\n'
    latest_path.write_bytes(latest_bytes)
    history_path.write_bytes(history_bytes)
    dates = pd.bdate_range("2026-11-02", periods=15)
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "raw_close": 100.0,
            "adj_close": 100.0,
            "volume": 1000.0,
        }
    )
    metadata = {
        "fetched_at": datetime(2026, 11, 24, tzinfo=UTC).isoformat(),
        "source": "fixture",
        "asof": str(dates[-1].date()),
        "timezone": "America/New_York",
        "exchange": "NMS",
        "adjustment": "none",
        "volume_unit": "vendor_native",
        "public_redistribution": "NOT_ESTABLISHED",
    }
    fetch_calls = []

    def fetch(*_args, **kwargs):
        fetch_calls.append(kwargs)
        return frame, metadata.copy()

    monkeypatch.setattr(pipeline, "method_identity", lambda: {"hash": "fixture"})
    monkeypatch.setattr(pipeline, "fetch_snapshot", fetch)
    monkeypatch.setattr(
        pipeline,
        "fetch_cross_check",
        lambda *_args, **_kwargs: {
            "provider": "fixture",
            "overlap": 250,
            "max_rel_diff": 0.01,
            "missing_in_yahoo": 0,
            "status": "mismatch",
        },
    )
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_args: None)

    result = pipeline.run(root, ["US_SPX"], workers=1, budget_seconds=60)

    assert result["status"] == "complete"
    assert fetch_calls[0]["provider"] == "yahoo"
    assert latest_path.read_bytes() == latest_bytes
    assert history_path.read_bytes() == history_bytes
    catalog = json.loads((global_dir / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["assets"][0]["status"] == "source_mismatch"
    assert catalog["assets"][0]["asof"] == "2026-11-20"
    assert catalog["assets"][0]["source_meta"]["cross_check"]["status"] == "mismatch"


def test_global_daily_workflow_schedule_assets_and_stock_results_publish():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/global_daily.yml").read_text(encoding="utf-8")
    )
    triggers = workflow.get("on", workflow.get(True, {}))
    assert triggers["schedule"] == [
        {"cron": "30 22 * * 1-5"},
        {"cron": "30 7 * * 1-5"},
    ]
    assert "workflow_dispatch" in triggers
    assert triggers["repository_dispatch"] == {"types": ["global_daily"]}
    steps = workflow["jobs"]["publish"]["steps"]
    run = next(step["run"] for step in steps if step.get("name") == "Run global daily pipeline")
    assert '--assets "${{ steps.asset-list.outputs.assets }}"' in run
    asset_step = next(step for step in steps if step.get("id") == "asset-list")
    assert '"$SCHEDULE" == "30 7 * * 1-5"' in asset_step["run"]
    assert 'JP_N225,KR_KOSPI,KR_KOSDAQ,KR_SKHYNIX' in asset_step["run"]
    assert 'US_SPX,US_IXIC,US_NDX,US_DJI,US_SOX,JP_N225,KR_KOSPI,KR_KOSDAQ,KR_SKHYNIX,US_MRVL' in asset_step["run"]
    assert "--budget-seconds 900" in run
    assert workflow["jobs"]["publish"]["timeout-minutes"] == 25
    assert source.ASSETS["US_SOX"]["ticker"] == "^SOX"
    assert source.ASSETS["US_SOX"]["name"] == "费城半导体指数"
    assert source.ASSETS["KR_SKHYNIX"]["display_code"] == "000660"
    assert {
        asset_id: asset["display_code"] for asset_id, asset in source.ASSETS.items()
    } == {
        "US_SPX": "SPX", "US_IXIC": "IXIC", "US_NDX": "NDX", "US_DJI": "DJI",
        "US_SOX": "SOX", "JP_N225": "N225", "KR_KOSPI": "KOSPI",
        "KR_KOSDAQ": "KOSDAQ", "KR_SKHYNIX": "000660", "US_MRVL": "MRVL",
    }
    assert pipeline.primary_provider_for_asset("KR_SKHYNIX") == "naver"
    assert pipeline.primary_provider_for_asset("KR_KOSPI") == "yahoo"
    assert pipeline.primary_provider_for_asset("US_SOX") == "yahoo"
    assert "US_SOX" not in source.SINA_US_SYMBOLS
    assert source.NASDAQ_SYMBOLS["US_SOX"] == "SOX"
    assert source.ASSETS["JP_N225"]["display_exchange"] == "东京证券交易所"
    publish = next(step["run"] for step in steps if step.get("name") == "Publish to stock-results")
    assert "git rebase FETCH_HEAD" in publish
    assert "git push origin HEAD:stock-results" in publish
    assert 'gh workflow run pages.yml --ref main' in publish
    build = (ROOT / "scripts/build_site.sh").read_text(encoding="utf-8")
    assert "stock-results:global/catalog.json" in build
    assert 'git -C "$ROOT" archive stock-results global' in build
    assert 'cp -a "$RUNNER_TEMP/gt/global/." global/' in publish
    assert "rm -rf global" not in publish


def test_partial_pipeline_run_preserves_unselected_catalog_entries(tmp_path):
    output = tmp_path / "global"
    output.mkdir()
    existing = {
        "assets": [
            {"id": "US_SPX", "status": "complete_sample", "asof": "2026-11-20"},
            {"id": "JP_N225", "status": "complete_sample", "asof": "2026-11-20"},
        ]
    }
    (output / "catalog.json").write_text(json.dumps(existing), encoding="utf-8")

    assert pipeline.preserved_catalog_entries(output, ["JP_N225"]) == {
        "US_SPX": {"id": "US_SPX", "status": "complete_sample", "asof": "2026-11-20"}
    }
