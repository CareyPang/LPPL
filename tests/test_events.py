import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from research.data import events

FIXTURES = Path(__file__).parent / "fixtures" / "events"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PageClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_json(self, _url, params=None, **_kwargs):
        page = params["pageNumber"]
        self.calls.append(page)
        key = f"page{page}"
        return deepcopy(self.pages[key] if key in self.pages else self.pages[page])


def test_event_fetch_paginates_all_pages():
    page_fixture = fixture("lift_pages.json")
    client = PageClient(page_fixture)

    rows = events._fetch_rows(
        client,
        "RPT_LIFT_STAGE",
        "(FREE_DATE>='2026-11-13')",
        events.LIFT_SORT_COLUMNS,
        ("1",) * len(events.LIFT_SORT_COLUMNS),
        page_size=2,
    )

    assert [row["SECURITY_CODE"] for row in rows] == ["002202", "002209", "002982"]
    assert client.calls == ["1", "2"]


def test_event_fetch_rejects_duplicate_rows():
    row = fixture("lift_pages.json")["page1"]["result"]["data"][0]
    payload = {"code": 0, "result": {"pages": 1, "count": 2, "data": [row, row]}}
    client = PageClient({"page1": payload})

    with pytest.raises(RuntimeError, match="不唯一|重复"):
        events._fetch_rows(
            client,
            "RPT_LIFT_STAGE",
            "",
            events.LIFT_SORT_COLUMNS,
            ("1",) * len(events.LIFT_SORT_COLUMNS),
            page_size=2,
        )


def test_event_fetch_rejects_out_of_range_rows():
    row = fixture("lift_pages.json")["page1"]["result"]["data"][0]
    row["FREE_DATE"] = "2026-12-14 00:00:00"

    with pytest.raises(RuntimeError, match="超出请求区间"):
        events._normalize_lift(
            [row],
            date.fromisoformat("2026-11-13"),
            date.fromisoformat("2026-12-13"),
        )


def test_lift_shares_use_current_free_shares_without_rescaling():
    row = fixture("lift_pages.json")["page1"]["result"]["data"][1]

    normalized = events._normalize_lift(
        [row],
        date.fromisoformat("2026-11-13"),
        date.fromisoformat("2026-12-13"),
    )[0]

    assert normalized["current_free_shares_10k"] == 11.2
    assert normalized["free_shares_raw"] == 15782.2788
    assert normalized["free_shares_raw_label"] == "东财 FREE_SHARES（口径未核实）"
    assert "free_shares_10k" not in normalized


def test_forecast_groups_indicator_rows_with_004_as_headline():
    rows = fixture("forecast_rows.json")["result"]["data"]
    rows[0]["CHANGE_REASON_EXPLAIN"] = "原因" * 120

    result = events._normalize_forecast(
        rows,
        date.fromisoformat("2026-10-14"),
        date.fromisoformat("2026-11-13"),
    )

    assert len(result) == 1
    assert result[0]["headline"]["indicator_code"] == "004"
    assert result[0]["headline"]["amount_lower"] == 140000000
    assert len(result[0]["headline"]["reason"]) == 200
    assert [row["indicator_code"] for row in result[0]["other_indicators"]] == ["005"]


def test_by_date_aggregates_lift_cap_and_dividend_count():
    raw_lifts = [
        *fixture("lift_pages.json")["page1"]["result"]["data"],
        *fixture("lift_pages.json")["page2"]["result"]["data"],
    ]
    raw_dividends = fixture("dividend_rows.json")["result"]["data"]
    lifts = events._normalize_lift(
        raw_lifts,
        date.fromisoformat("2026-11-13"),
        date.fromisoformat("2026-12-13"),
    )
    dividends = events._normalize_dividend(
        raw_dividends,
        date.fromisoformat("2026-11-13"),
        date.fromisoformat("2026-12-13"),
    )

    result = events._by_date(lifts, dividends)

    assert result["2026-11-13"] == {
        "lift_n": 3,
        "lift_cap": pytest.approx(3911.893526),
        "dividend_n": 2,
    }


def test_failed_source_keeps_only_its_previous_rows():
    dividend = fixture("dividend_rows.json")
    forecast = fixture("forecast_rows.json")

    class Client:
        def get_json(self, _url, params=None, **_kwargs):
            report = params["reportName"]
            if report == "RPT_LIFT_STAGE":
                raise ConnectionError("fixture source failure")
            return deepcopy(
                dividend if report == "RPT_SHAREBONUS_DET" else forecast
            )

    result = events.fetch_events(
        "2026-11-13",
        client=Client(),
        previous_path=FIXTURES / "events_previous.json",
    )

    assert result["lift"] == fixture("events_previous.json")["lift"]
    assert result["sources"]["lift"]["ok"] is False
    assert result["sources"]["lift"]["stale"] is True
    assert "fixture source failure" in result["sources"]["lift"]["error"]
    assert result["sources"]["dividend"]["ok"] is True
    assert result["sources"]["forecast"]["ok"] is True
