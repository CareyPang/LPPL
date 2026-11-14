import pandas as pd

from research.data import trading_date
from research.pipeline import stock


def test_saturday_0130_uses_fridays_closed_bar(monkeypatch):
    cutoffs = []
    monkeypatch.setattr(
        stock,
        "_reference_calendar",
        lambda cutoff: cutoffs.append(cutoff) or pd.DatetimeIndex(["2026-11-13"]),
    )

    result = trading_date.latest_closed_trading_day(
        pd.Timestamp("2026-11-14 01:30", tz="Asia/Shanghai")
    )

    assert result == "2026-11-13"
    assert cutoffs == [pd.Timestamp("2026-11-13")]


def test_monday_1000_uses_previous_fridays_closed_bar(monkeypatch):
    cutoffs = []
    monkeypatch.setattr(
        stock,
        "_reference_calendar",
        lambda cutoff: cutoffs.append(cutoff) or pd.DatetimeIndex(["2026-11-13"]),
    )

    result = trading_date.latest_closed_trading_day(
        pd.Timestamp("2026-11-16 10:00", tz="Asia/Shanghai")
    )

    assert result == "2026-11-13"
    assert cutoffs == [pd.Timestamp("2026-11-15")]


def test_monday_1600_uses_mondays_closed_bar(monkeypatch):
    cutoffs = []
    monkeypatch.setattr(
        stock,
        "_reference_calendar",
        lambda cutoff: cutoffs.append(cutoff) or pd.DatetimeIndex(["2026-11-16"]),
    )

    result = trading_date.latest_closed_trading_day(
        pd.Timestamp("2026-11-16 16:00", tz="Asia/Shanghai")
    )

    assert result == "2026-11-16"
    assert cutoffs == [pd.Timestamp("2026-11-16")]


def test_holiday_gap_uses_calendar_instead_of_inventing_cutoff_date(monkeypatch):
    cutoffs = []
    monkeypatch.setattr(
        stock,
        "_reference_calendar",
        lambda cutoff: cutoffs.append(cutoff) or pd.DatetimeIndex(["2026-09-30"]),
    )

    result = trading_date.latest_closed_trading_day(
        pd.Timestamp("2026-10-08 10:00", tz="Asia/Shanghai")
    )

    assert result == "2026-09-30"
    assert cutoffs == [pd.Timestamp("2026-10-07")]
