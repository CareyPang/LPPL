"""Trading-day calendars for future-date display."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

CN_HOLIDAYS_PATH = Path(__file__).with_name("cn_market_holidays.json")


@lru_cache(maxsize=1)
def _holiday_data() -> dict:
    return json.loads(CN_HOLIDAYS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_cn_closures() -> tuple[frozenset[pd.Timestamp], pd.Timestamp]:
    data = _holiday_data()
    closures = frozenset(pd.Timestamp(date).normalize() for date in data["closures"])
    return closures, pd.Timestamp(data["covered_through"]).normalize()


def cn_holiday_source() -> str:
    return str(_holiday_data()["source"])


def future_calendar_metadata(
    calendar: pd.DatetimeIndex,
    market: str = "cn",
    asof: pd.Timestamp | None = None,
) -> dict:
    if market != "cn":
        return {
            "market": market,
            "holidays_through": None,
            "closures": [],
            "source": None,
        }

    closures, covered_through = load_cn_closures()
    last = pd.Timestamp(calendar[-1]).normalize()
    calendar_days = {pd.Timestamp(date).normalize() for date in calendar}
    if asof is None:
        closure_days = {
            date for date in closures if last < date <= covered_through
        }
    else:
        asof = pd.Timestamp(asof).normalize()
        closure_days = {
            date
            for date in pd.date_range(asof + pd.Timedelta(days=1), last, freq="B")
            if date not in calendar_days
        }
        known_after = max(asof, last)
        closure_days.update(
            date for date in closures if known_after < date <= covered_through
        )
    return {
        "market": market,
        "holidays_through": covered_through.date().isoformat(),
        "closures": sorted(
            date.date().isoformat() for date in closure_days
        ),
        "source": cn_holiday_source(),
    }


def future_trading_days(
    last: pd.Timestamp, n: int, market: str = "cn"
) -> pd.DatetimeIndex:
    if n <= 0:
        return pd.DatetimeIndex([])

    last = pd.Timestamp(last).normalize()
    if market == "cn":
        closures, covered_through = load_cn_closures()
    else:
        closures, covered_through = frozenset(), None

    days = []
    candidate = last + pd.Timedelta(days=1)
    while len(days) < n:
        if candidate.weekday() < 5 and not (
            market == "cn"
            and candidate <= covered_through
            and candidate in closures
        ):
            days.append(candidate)
        candidate += pd.Timedelta(days=1)
    return pd.DatetimeIndex(days)
