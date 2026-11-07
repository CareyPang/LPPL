"""Versioned SSE 2026 scheduled sessions, with a hard evidence boundary.

Holiday notice checked against archived official response bytes. This schedule
does not claim coverage of 2027 or unscheduled future trading suspensions.
"""
from __future__ import annotations

import pandas as pd

SOURCE_URL = "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml"
SOURCE_SHA256 = "ff188c710b8904758c185eb955e9eaa2c9bd7c2061af984d4f1d743f899c12a4"
VERSION = "sse_2026_20251222_v1"
HOLIDAY_RANGES = (("2026-01-01", "2026-01-03"), ("2026-02-15", "2026-02-23"),
                  ("2026-04-04", "2026-04-06"), ("2026-05-01", "2026-05-05"),
                  ("2026-06-19", "2026-06-21"), ("2026-09-25", "2026-09-27"),
                  ("2026-10-01", "2026-10-07"))


def weekday_estimate(asof: str, horizon: int = 100) -> dict:
    return {"status": "weekday_estimate", "version": "weekdays_no_exchange_holidays_v1",
            "dates": [str(date.date()) for date in pd.bdate_range(asof, periods=horizon + 1)],
            "note": "未来日期按周一至周五估算，未核验交易所节假日；不据此声称提前5个真实交易日。"}


def sessions_2026() -> list[str]:
    holidays = {date for start, end in HOLIDAY_RANGES for date in pd.date_range(start, end)}
    return [str(date.date()) for date in pd.bdate_range("2026-01-01", "2026-12-31") if date not in holidays]


def calendar_for(asof: str) -> dict:
    dates = sessions_2026()
    if asof not in dates:
        return weekday_estimate(asof)
    return {"status": "exchange_verified", "version": VERSION, "source_url": SOURCE_URL,
            "source_sha256": SOURCE_SHA256, "source_published_at": "2025-12-22",
            "coverage_start": "2026-01-01", "coverage_end": "2026-12-31",
            "dates": dates[dates.index(asof):],
            "note": "上交所官方2026年度休市安排，排除周末；仅覆盖2026，不代表已知2027安排或未来临时停市。"}
