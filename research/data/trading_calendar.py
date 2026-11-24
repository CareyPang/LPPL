"""Trading-day calendars for future-date display."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import exchange_calendars as xc
import pandas as pd

CN_HOLIDAYS_PATH = Path(__file__).with_name("cn_market_holidays.json")
EXCHANGE_BY_MARKET = {"us": "XNYS", "jp": "XTKS", "kr": "XKRX"}
TIMEZONE_BY_MARKET = {
    "us": "America/New_York",
    "jp": "Asia/Tokyo",
    "kr": "Asia/Seoul",
}


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


@lru_cache(maxsize=32)
def _exchange_calendar(market: str, start_year: int, end_year: int):
    exchange = EXCHANGE_BY_MARKET[market]
    return xc.get_calendar(
        exchange,
        start=f"{start_year}-01-01",
        end=f"{end_year}-12-31",
    )


def _calendar_for(market: str, start: pd.Timestamp, end: pd.Timestamp):
    start_year = max(1900, pd.Timestamp(start).year - 1)
    end_year = max(start_year + 1, pd.Timestamp(end).year + 2)
    return _exchange_calendar(market, start_year, end_year)


def exchange_for_market(market: str) -> str | None:
    return EXCHANGE_BY_MARKET.get(market)


def market_sessions(
    market: str, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DatetimeIndex:
    if market not in EXCHANGE_BY_MARKET:
        raise ValueError(f"No exchange calendar configured for {market!r}")
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    if end < start:
        return pd.DatetimeIndex([])
    return _calendar_for(market, start, end).sessions_in_range(start, end)


def completed_market_sessions(
    market: str,
    fetched_at: pd.Timestamp,
    count: int = 250,
    close_grace_minutes: int = 20,
) -> pd.DatetimeIndex:
    if count < 1:
        raise ValueError("count must be positive")
    now = pd.Timestamp(fetched_at)
    if now.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    now = now.tz_convert("UTC")
    local_date = now.tz_convert(TIMEZONE_BY_MARKET[market]).normalize().tz_localize(None)
    start = local_date - pd.Timedelta(days=count * 2 + 60)
    sessions = market_sessions(market, start, local_date)
    calendar = _calendar_for(market, start, local_date)
    completed = [
        session
        for session in sessions
        if pd.Timestamp(calendar.session_close(session)).tz_convert("UTC")
        + pd.Timedelta(minutes=close_grace_minutes)
        <= now
    ]
    return pd.DatetimeIndex(completed[-count:])


def future_calendar_metadata(
    calendar: pd.DatetimeIndex,
    market: str = "cn",
    asof: pd.Timestamp | None = None,
) -> dict:
    if market != "cn":
        exchange = exchange_for_market(market)
        if exchange is None:
            return {
                "market": market,
                "holidays_through": None,
                "closures": [],
                "source": None,
            }
        last = pd.Timestamp(calendar[-1]).normalize()
        asof = last if asof is None else pd.Timestamp(asof).normalize()
        coverage_end = max(last, asof) + pd.DateOffset(years=2)
        schedule = _calendar_for(market, asof, coverage_end)
        through = pd.Timestamp(schedule.last_session).normalize()
        weekdays = pd.date_range(
            asof + pd.Timedelta(days=1), through, freq="B"
        )
        sessions = set(market_sessions(market, asof, through))
        closures = [
            date.date().isoformat() for date in weekdays if date not in sessions
        ]
        return {
            "market": market,
            "exchange": exchange,
            "holidays_through": through.date().isoformat(),
            "closures": closures,
            "source": f"exchange_calendars=={xc.__version__}:{exchange}",
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
    if market in EXCHANGE_BY_MARKET:
        start = last + pd.Timedelta(days=1)
        end = last + pd.Timedelta(days=max(30, n * 4))
        while True:
            sessions = market_sessions(market, start, end)
            if len(sessions) >= n:
                return sessions[:n]
            end += pd.Timedelta(days=365)

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
