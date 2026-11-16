from datetime import date, timedelta

from research.data.growth_monitor import (
    _realize_indicator,
    completed_weekly_flows,
    evaluate_growth_rs,
    evaluate_us10y,
    parse_nav_payload,
    semi_status,
    share_exclusion_reason,
)


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
    assert "沿用上次数据" in result["note"]

    previous["indicators"][0].update(
        {"status": "missing", "asof": None, "value": None}
    )
    assert _realize_indicator(
        previous, "us10y", "美债 10 年", "core", "美国财政部", fail
    )["status"] == "missing"
