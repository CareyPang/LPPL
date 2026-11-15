from types import SimpleNamespace

import pandas as pd
import pytest

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


@pytest.mark.parametrize("n_failures", [1, 2])
def test_fetch_recent_many_skips_failures_and_update_applies_coverage_gate(
    monkeypatch, n_failures
):
    codes = [f"{code:06}" for code in range(1, 21)]
    failed_codes = set(codes[:n_failures])

    def fetch(code):
        if code in failed_codes:
            raise RuntimeError("synthetic fetch failure")
        return pd.DataFrame(
            [
                {
                    "SECURITY_CODE": code,
                    "TRADE_DATE": "2026-11-16",
                    "TOTAL_MARKET_CAP": 100,
                    "PE_TTM": 10,
                }
            ]
        )

    monkeypatch.setattr(a500_pe, "fetch_recent", fetch)
    monkeypatch.setattr(a500_pe.time, "sleep", lambda seconds: None)

    rows, failed_count = a500_pe.fetch_recent_many(codes)
    history = pd.DataFrame(
        {"n": [20], "mcap": [2000.0], "earn": [200.0], "pe_ttm": [10.0]},
        index=pd.DatetimeIndex(["2026-11-13"], name="date"),
    )
    updated = a500_pe.update(history, n_constituents=20, rows=rows)

    assert failed_count == n_failures
    assert len(rows) == 20 - n_failures
    if n_failures == 1:
        assert updated.index.strftime("%Y-%m-%d").tolist() == [
            "2026-11-13",
            "2026-11-16",
        ]
        assert updated.loc["2026-11-16", "n"] == 19
    else:
        assert updated.index.strftime("%Y-%m-%d").tolist() == ["2026-11-13"]


def test_fetch_recent_many_aborts_after_20_consecutive_failures(monkeypatch):
    calls = []

    def fail(code):
        calls.append(code)
        raise RuntimeError("synthetic fetch failure")

    monkeypatch.setattr(a500_pe, "fetch_recent", fail)
    monkeypatch.setattr(a500_pe.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="东财估值连续失败"):
        a500_pe.fetch_recent_many([f"{code:06}" for code in range(1, 30)])

    assert len(calls) == 20


def test_fetch_recent_many_enforces_overall_deadline(monkeypatch):
    class FakeClock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = FakeClock()

    def fetch(code):
        clock.now += 3
        return pd.DataFrame()

    monkeypatch.setattr(
        a500_pe,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep),
    )
    monkeypatch.setattr(a500_pe, "fetch_recent", fetch)

    with pytest.raises(RuntimeError, match="东财估值整体获取超过时限"):
        a500_pe.fetch_recent_many(["000001", "000002"], deadline_s=5)


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
