from datetime import date, timedelta

import research.data.growth_monitor as growth_monitor
from research.data.growth_monitor import (
    _fetch_nav,
    _fetch_szse_with_retry,
    _realize_indicator,
    _share_error_notes,
    completed_weekly_flows,
    evaluate_growth_rs,
    evaluate_us10y,
    parse_cnindex_payload,
    parse_nav_payload,
    semi_status,
    share_exclusion_reason,
)


def test_parse_cnindex_descending_daily_rows_by_named_close_column():
    columns = [
        "timestamp",
        "current",
        "high",
        "open",
        "low",
        "close",
        "chg",
        "percent",
        "amount",
        "volume",
        "avg",
    ]

    def row(day, close):
        return [day, 1, 1, 1, 1, close, 0, 0, 0, 0, 0]

    result = parse_cnindex_payload(
        {
            "data": {
                "item": columns,
                "data": [
                    row("2026-11-16", 106),
                    row("2026-11-13", 103),
                    row("2026-11-13", 999),
                    row("2026-11-12", float("nan")),
                    row("invalid", 100),
                ],
            }
        }
    )

    assert result == [
        {"date": "2026-11-13", "close": 103.0},
        {"date": "2026-11-16", "close": 106.0},
    ]


def test_growth_rs_requires_last_ten_sessions_above_ma20():
    start = date(2026, 1, 5)
    dates = []
    day = start
    while len(dates) < 40:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += timedelta(days=1)
    chip = [
        {
            "date": day,
            "close": 1 if index < 25 else 1 + (index - 24) / 100,
        }
        for index, day in enumerate(dates)
    ]
    market = [{"date": day, "close": 1} for day in dates]

    result = evaluate_growth_rs(chip, market)

    assert result["status"] == "met"
    assert result["value"]["consecutive_above_days"] == 15
    assert result["value"]["last_cross_date"] == dates[25]
    assert len(result["recent"]) == 21

    chip[-1]["close"] = 0.5
    assert evaluate_growth_rs(chip, market)["status"] == "not_met"


def test_us10y_requires_five_observations_all_below_threshold():
    rows = [{"date": f"2026-11-{day:02}", "10y": 4.49} for day in range(9, 14)]
    assert evaluate_us10y(rows)["status"] == "met"
    rows[-1]["10y"] = 4.50
    assert evaluate_us10y(rows)["status"] == "not_met"
    assert evaluate_us10y(rows[:4])["status"] == "missing"


def test_weekly_flow_includes_only_ended_weeks():
    daily = [
        {"date": "2026-11-06", "flows": {"159995": 10}},
        {"date": "2026-11-12", "flows": {"159995": 20}},
        {"date": "2026-11-13", "flows": {"159995": 30}},
    ]

    through_thursday = completed_weekly_flows(daily, "2026-11-12", ("159995",))
    through_friday = completed_weekly_flows(daily, "2026-11-13", ("159995",))

    assert [row["week_end"] for row in through_thursday] == ["2026-11-06"]
    assert [row["flow_yuan"] for row in through_thursday] == [10]
    assert [row["week_end"] for row in through_friday] == [
        "2026-11-06",
        "2026-11-13",
    ]
    assert [row["flow_yuan"] for row in through_friday] == [10, 50]


def test_weekly_flow_does_not_skip_an_unobserved_complete_week():
    daily = [
        {"date": "2026-11-06", "flows": {"159995": 10}},
        {"date": "2026-11-20", "flows": {"159995": 20}},
    ]

    result = completed_weekly_flows(daily, "2026-11-23", ("159995",))

    assert [row["week_end"] for row in result[-3:]] == [
        "2026-11-06",
        "2026-11-13",
        "2026-11-20",
    ]
    assert result[-2]["flow_yuan"] is None


def test_share_jumps_and_fund_actions_are_excluded():
    assert share_exclusion_reason(100, 130, False) is None
    assert "超过 30%" in share_exclusion_reason(100, 131, False)
    assert "FHSP/FHFCZ" in share_exclusion_reason(100, 100, True)
    assert share_exclusion_reason(None, 100, False) is None


def test_szse_share_history_retries_transient_failures(monkeypatch):
    calls = []
    delays = []

    def fetch_history(session, code, start, end):
        calls.append((code, start, end))
        if len(calls) < 3:
            raise ConnectionError("reset")
        return {"2026-11-13": 123.0}

    monkeypatch.setattr(growth_monitor, "_szse_history", fetch_history)
    monkeypatch.setattr(growth_monitor.time, "sleep", delays.append)

    result, error = _fetch_szse_with_retry(
        object(), {"code": "159995"}, "2026-08-01", "2026-11-16"
    )

    assert result == {"2026-11-13": 123.0}
    assert error is None
    assert len(calls) == 3
    assert delays == [0.25, 0.5]


def test_szse_share_history_reports_error_after_three_attempts(monkeypatch):
    calls = []
    delays = []

    def fail(session, code, start, end):
        calls.append(code)
        raise ConnectionError("reset")

    monkeypatch.setattr(growth_monitor, "_szse_history", fail)
    monkeypatch.setattr(growth_monitor.time, "sleep", delays.append)

    result, error = _fetch_szse_with_retry(
        object(), {"code": "159995"}, "2026-08-01", "2026-11-16"
    )

    assert result == {}
    assert error == "159995: ConnectionError: reset"
    assert calls == ["159995", "159995", "159995"]
    assert delays == [0.25, 0.5]


def test_nav_split_fields_mark_action_days():
    result = parse_nav_payload(
        {
            "Data": {
                "LSJZList": [
                    {
                        "FSRQ": "2026-11-13",
                        "DWJZ": "1.2345",
                        "FHSP": "1",
                        "FHFCZ": "",
                    },
                    {
                        "FSRQ": "2026-11-12",
                        "DWJZ": "",
                        "FHSP": "",
                        "FHFCZ": "派息",
                    },
                    {"FSRQ": "invalid", "DWJZ": "1.0"},
                ]
            }
        }
    )

    assert result == {
        "2026-11-12": {"nav": None, "action": True},
        "2026-11-13": {"nav": 1.2345, "action": True},
    }


def test_fetch_nav_paginates_until_page_reaches_start_date(monkeypatch):
    class Response:
        def __init__(self, rows):
            self.rows = rows

        def raise_for_status(self):
            return None

        def json(self):
            return {"Data": {"LSJZList": self.rows}}

    class Session:
        def __init__(self):
            self.pages = [
                [
                    {"FSRQ": "2026-11-13", "DWJZ": "1.13"},
                    {"FSRQ": "2026-10-25", "DWJZ": "1.10"},
                ],
                [
                    {"FSRQ": "2026-10-20", "DWJZ": "1.08"},
                    {"FSRQ": "2026-10-19", "DWJZ": "1.07"},
                ],
            ]
            self.params = []

        def get(self, url, *, params, headers, timeout):
            self.params.append(params)
            return Response(self.pages.pop(0))

    delays = []
    monkeypatch.setattr(growth_monitor.time, "sleep", delays.append)
    session = Session()

    result = _fetch_nav(session, "512480", "2026-10-20")

    assert result == {
        "2026-11-13": {"nav": 1.13, "action": False},
        "2026-10-25": {"nav": 1.10, "action": False},
        "2026-10-20": {"nav": 1.08, "action": False},
    }
    assert [params["pageIndex"] for params in session.params] == [1, 2]
    assert all(params["pageSize"] == 20 for params in session.params)
    assert delays == [0.2]


def test_share_error_notes_hide_unpublished_dates_and_raw_errors():
    result = _share_error_notes(
        "上交所",
        [
            "2026-11-16: RuntimeError: not published",
            "2026-11-12: RuntimeError: connection reset",
        ],
        "2026-11-13",
    )

    assert result == ["上交所份额 2026-11-12 未发布"]


def test_semi_etf_status_reports_partial_and_all_missing():
    weeks = [
        {"flow_yuan": 1},
        {"flow_yuan": 2},
    ]

    assert semi_status(weeks, ["512480"], ("159995", "512480"))[0] == "partial"
    assert semi_status(weeks, ["159995", "512480"], ("159995", "512480"))[0] == "missing"
    assert semi_status(weeks, [], ("159995", "512480")) == ("met", None)
    assert semi_status([{"flow_yuan": 0}], [], ("159995", "512480"))[0] == "missing"


def test_failed_source_falls_back_to_previous_value_as_partial():
    def fail():
        raise RuntimeError("暂不可用")

    previous = {
        "indicators": [
            {
                "id": "us10y",
                "status": "met",
                "asof": "2026-11-13",
                "note": "",
            }
        ]
    }

    result = _realize_indicator(
        previous,
        "us10y",
        "美债 10 年",
        "core",
        "美国财政部",
        fail,
    )

    assert result["status"] == "partial"
    assert result["asof"] == "2026-11-13"
    assert "本次取数失败，沿用上次 2026-11-13 数据" in result["note"]

    previous["indicators"][0].update(
        {"status": "met", "asof": None, "value": {"last_five": [4.2]}}
    )
    missing = _realize_indicator(
        previous, "us10y", "美债 10 年", "core", "美国财政部", fail
    )
    assert missing["status"] == "missing"
    assert missing["value"] is None
