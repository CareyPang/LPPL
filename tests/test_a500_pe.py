import pandas as pd

from research.data import a500_pe


def test_aggregate_excludes_zero_pe_and_keeps_negative_pe():
    rows = pd.DataFrame(
        [
            {
                "SECURITY_CODE": "000001",
                "TRADE_DATE": "2026-11-16",
                "TOTAL_MARKET_CAP": "100",
                "PE_TTM": "10",
            },
            {
                "SECURITY_CODE": "000002",
                "TRADE_DATE": "2026-11-16",
                "TOTAL_MARKET_CAP": "200",
                "PE_TTM": "0",
            },
            {
                "SECURITY_CODE": "000003",
                "TRADE_DATE": "2026-11-17",
                "TOTAL_MARKET_CAP": "50",
                "PE_TTM": "-5",
            },
        ]
    )

    result = a500_pe.aggregate(rows)

    assert result.loc["2026-11-16", "n"] == 2
    assert result.loc["2026-11-16", "mcap"] == 100
    assert result.loc["2026-11-16", "earn"] == 10
    assert result.loc["2026-11-16", "pe_ttm"] == 10
    assert result.loc["2026-11-17", "mcap"] == 50
    assert result.loc["2026-11-17", "earn"] == -10
    assert result.loc["2026-11-17", "pe_ttm"] == -5


def test_update_appends_only_new_dates_with_95_percent_coverage():
    history = pd.DataFrame(
        {
            "n": [495],
            "mcap": [100.0],
            "earn": [10.0],
            "pe_ttm": [10.0],
        },
        index=pd.DatetimeIndex(["2026-11-13"], name="date"),
    )
    rows = pd.DataFrame(
        [
            {
                "SECURITY_CODE": f"{code:06}",
                "TRADE_DATE": "2026-11-12",
                "TOTAL_MARKET_CAP": 100,
                "PE_TTM": 10,
            }
            for code in range(1, 5)
        ]
        + [
            {
                "SECURITY_CODE": f"{code:06}",
                "TRADE_DATE": "2026-11-16",
                "TOTAL_MARKET_CAP": 100,
                "PE_TTM": 10,
            }
            for code in range(1, 5)
        ]
        + [
            {
                "SECURITY_CODE": f"{code:06}",
                "TRADE_DATE": "2026-11-17",
                "TOTAL_MARKET_CAP": 100,
                "PE_TTM": 10,
            }
            for code in range(1, 4)
        ]
    )

    result = a500_pe.update(history, n_constituents=4, rows=rows)

    assert result.index.strftime("%Y-%m-%d").tolist() == [
        "2026-11-13",
        "2026-11-16",
    ]
    assert result.loc["2026-11-13", "mcap"] == 100
    assert result.loc["2026-11-16", "n"] == 4


def test_fetch_recent_retries_with_required_params_and_timeout(monkeypatch):
    calls = []

    class Response:
        def json(self):
            return {"result": {"data": [{"TRADE_DATE": "2026-11-13"}]}}

    def request(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers, timeout))
        if len(calls) < 3:
            raise OSError("temporary")
        return Response()

    monkeypatch.setattr(a500_pe._EM_CLIENT, "_request_once", request)
    monkeypatch.setattr(a500_pe.time, "sleep", lambda seconds: None)

    result = a500_pe.fetch_recent("1")

    assert len(calls) == 3
    assert calls[-1][1] == {
        "reportName": "RPT_VALUEANALYSIS_DET",
        "columns": "TRADE_DATE,TOTAL_MARKET_CAP,PE_TTM",
        "filter": '(SECURITY_CODE="000001")',
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
        "pageSize": "30",
        "pageNumber": "1",
        "source": "WEB",
        "client": "WEB",
    }
    assert calls[-1][3] == 30
    assert result.loc[0, "SECURITY_CODE"] == "000001"


def test_load_history_uses_baseline_when_incremental_file_is_missing(monkeypatch, tmp_path):
    expected = pd.DataFrame(
        {"n": [179], "mcap": [100.0], "earn": [10.0], "pe_ttm": [10.0]},
        index=pd.DatetimeIndex(["2005-01-04"], name="date"),
    )
    baseline = tmp_path / "baseline.parquet"
    expected.to_parquet(baseline)
    monkeypatch.setattr(a500_pe, "BASELINE_HISTORY", baseline)

    result = a500_pe.load_history(tmp_path / "missing.csv")

    pd.testing.assert_frame_equal(result, expected)
