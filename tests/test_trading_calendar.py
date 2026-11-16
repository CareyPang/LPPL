import pandas as pd

from research.data.trading_calendar import (
    cn_holiday_source,
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


def test_non_cn_market_keeps_plain_weekday_behavior():
    last = pd.Timestamp("2027-02-04")
    expected = pd.bdate_range(last + pd.Timedelta(days=1), periods=10)

    assert future_trading_days(last, 10, market="us").equals(expected)


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
