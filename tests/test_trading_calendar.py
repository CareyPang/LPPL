import pandas as pd

from research.data.trading_calendar import (
    cn_holiday_source,
    cn_sessions,
    future_calendar_metadata,
    future_trading_days,
    load_cn_closures,
)


def _dates(days):
    return days.strftime("%Y-%m-%d").tolist()


def test_cn_future_days_exclude_2027_exchange_closures():
    assert _dates(future_trading_days(pd.Timestamp("2026-12-31"), 2)) == [
        "2027-01-04",
        "2027-01-05",
    ]
    assert _dates(future_trading_days(pd.Timestamp("2027-02-04"), 1)) == ["2027-02-15"]
    assert _dates(future_trading_days(pd.Timestamp("2027-09-30"), 1)) == ["2027-10-08"]


def test_cn_sessions_use_xshg_for_2025_and_holiday_file_for_2027():
    sessions = cn_sessions("2025-09-29", "2025-10-13")
    assert isinstance(sessions, pd.DatetimeIndex)
    assert sessions.tz is None and sessions.equals(sessions.normalize())
    assert _dates(sessions) == [
        "2025-09-29",
        "2025-09-30",
        "2025-10-09",
        "2025-10-10",
        "2025-10-13",
    ]
    assert pd.Timestamp("2027-02-05") in load_cn_closures()[0]
    assert "2027-02-05" not in _dates(cn_sessions("2027-02-04", "2027-02-08"))


def test_cn_calendar_is_cached_and_reports_source_and_coverage():
    closures, covered_through = load_cn_closures()

    assert isinstance(closures, frozenset)
    assert pd.Timestamp("2027-02-05") in closures
    assert covered_through == pd.Timestamp("2027-12-31")
    assert cn_holiday_source().startswith("国务院办公厅关于2027年部分节假日安排的通知")


def test_cn_dates_after_coverage_use_plain_weekdays():
    last = pd.Timestamp("2027-12-31")
    expected = pd.bdate_range(last + pd.Timedelta(days=1), periods=20)

    assert future_trading_days(last, 20).equals(expected)


def test_us_future_days_skip_presidents_day():
    assert _dates(future_trading_days(pd.Timestamp("2027-02-04"), 10, "us")) == [
        "2027-02-05",
        "2027-02-08",
        "2027-02-09",
        "2027-02-10",
        "2027-02-11",
        "2027-02-12",
        "2027-02-16",
        "2027-02-17",
        "2027-02-18",
        "2027-02-19",
    ]


def test_replay_calendar_metadata_includes_missing_weekdays_until_calendar_end():
    asof = pd.Timestamp("2026-09-25")
    absent = pd.to_datetime(
        ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
    )
    calendar = pd.bdate_range("2026-09-01", "2026-10-15").difference(absent)

    metadata = future_calendar_metadata(calendar, asof=asof)

    expected = {date.strftime("%Y-%m-%d") for date in absent}
    expected.update(date.date().isoformat() for date in load_cn_closures()[0])
    assert metadata["closures"] == sorted(expected)


def test_xnys_skips_thanksgiving_2026_and_reports_calendar_coverage():
    assert _dates(future_trading_days(pd.Timestamp("2026-11-25"), 2, "us")) == [
        "2026-11-27",
        "2026-11-30",
    ]
    metadata = future_calendar_metadata(
        pd.DatetimeIndex([pd.Timestamp("2026-11-25")]),
        market="us",
        asof=pd.Timestamp("2026-11-25"),
    )
    assert "2026-11-26" in metadata["closures"]
    assert metadata["source"] == "exchange_calendars==4.13.3:XNYS"
    assert metadata["holidays_through"] > "2026-11-25"


def test_xtks_skips_new_years_day_2027():
    assert _dates(future_trading_days(pd.Timestamp("2026-12-31"), 1, "jp")) == [
        "2027-01-04"
    ]


def test_xkrx_skips_labor_day_2026():
    assert _dates(future_trading_days(pd.Timestamp("2026-04-30"), 1, "kr")) == [
        "2026-05-04"
    ]
