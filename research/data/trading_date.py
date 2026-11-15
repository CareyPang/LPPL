from __future__ import annotations

import pandas as pd


def latest_closed_trading_day(now: pd.Timestamp | None = None) -> str:
    from research.pipeline import stock

    current = stock._now() if now is None else pd.Timestamp(now)
    calendar = stock._reference_calendar(stock._close_cutoff(current))
    if len(calendar) == 0:
        raise RuntimeError("reference calendar has no closed trading days")
    return pd.Timestamp(calendar[-1]).date().isoformat()


if __name__ == "__main__":
    print(latest_closed_trading_day())
