from __future__ import annotations

import hashlib
import json
import math
import re
from bisect import bisect_right
from datetime import date

import pandas as pd
import requests

from .sources import UA

DAILY_URL = (
    "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/"
    "var/US_MinKService.getDailyK"
)
FACTOR_URL = "https://finance.sina.com.cn/us_stock/company/reinstatement/{ticker}_qfq.js"
REFERER = "https://finance.sina.com.cn/"
LOG_RETURN_LIMIT = math.log(3)


def parse_daily(text: str) -> list[dict]:
    start = text.find("[")
    if start < 0:
        raise ValueError("Sina US daily response has no JSONP array")
    rows, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(rows, list):
        raise ValueError("Sina US daily response is not an array")
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("d", ""))):
            raise ValueError("invalid Sina US daily row")
        day = row["d"]
        if day in seen:
            raise ValueError(f"duplicate Sina US date: {day}")
        seen.add(day)
        parsed = {"date": day}
        for source, dest in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"), ("a", "amount")):
            value = float(row[source])
            if not math.isfinite(value):
                raise ValueError(f"invalid Sina US {source} on {day}")
            parsed[dest] = value
        if min(parsed[k] for k in ("open", "high", "low", "close")) <= 0:
            raise ValueError(f"non-positive Sina US price on {day}")
        out.append(parsed)
    return sorted(out, key=lambda row: row["date"])


def parse_factors(text: str) -> list[dict]:
    _, separator, remainder = text.partition("=")
    if not separator:
        raise ValueError("Sina US factor file has no assignment")
    payload, _ = json.JSONDecoder().raw_decode(remainder.lstrip())
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("Sina US factor file has no data")
    out = []
    seen = set()
    for row in rows:
        day, factor, cash = str(row["d"]), float(row["f"]), float(row["c"])
        if day in seen or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError(f"invalid or duplicate Sina US factor date: {day}")
        if not math.isfinite(factor) or factor <= 0 or not math.isfinite(cash):
            raise ValueError(f"invalid Sina US factor on {day}")
        seen.add(day)
        out.append({"date": day, "factor": factor, "cash": cash})
    return sorted(out, key=lambda row: row["date"])


def recent_segment(rows: list[dict]) -> tuple[list[dict], dict | None]:
    if not rows:
        raise ValueError("Sina US daily response has no rows in the requested range")
    ordered = sorted(rows, key=lambda row: row["date"])
    last_gap = None
    for left, right in zip(ordered, ordered[1:], strict=False):
        days = (date.fromisoformat(right["date"]) - date.fromisoformat(left["date"])).days
        if days > 10:
            last_gap = {"left": left["date"], "right": right["date"], "days": days}
    if last_gap is None:
        return ordered, None
    return [row for row in ordered if row["date"] >= last_gap["right"]], last_gap


def _adjust_segment(rows: list[dict], factors: list[dict]) -> pd.DataFrame:
    if not rows or not factors:
        raise ValueError("US prices and factors must be non-empty")
    rows = sorted(rows, key=lambda row: row["date"])
    factors = sorted(factors, key=lambda row: row["date"])
    all_factor_dates = [row["date"] for row in factors]
    anchor = bisect_right(all_factor_dates, rows[0]["date"]) - 1
    if anchor < 0:
        raise ValueError("Sina US factors do not cover the raw price history")
    active = [
        row for row in factors[anchor:] if row["date"] <= rows[-1]["date"]
    ]
    if not active:
        raise ValueError("Sina US factors do not cover the raw price history")
    dates = [row["date"] for row in active]
    multipliers = {dates[-1]: 1.0}
    boundaries = []
    for index in range(len(active) - 2, -1, -1):
        older, newer = active[index], active[index + 1]
        prior = next((row for row in reversed(rows) if row["date"] < newer["date"]), None)
        split_ratio = older["factor"] / newer["factor"]
        cash = newer["cash"] - older["cash"]
        if cash < 0:
            raise ValueError(f"negative dividend adjustment at {newer['date']}")
        segment = split_ratio
        if prior is not None:
            price = prior["close"] * older["factor"]
            if price <= 0:
                raise ValueError(f"invalid boundary price at {newer['date']}")
            segment *= 1 - cash / price
            after = next((row for row in rows if row["date"] >= newer["date"]), None)
            if after is not None:
                boundaries.append((prior["date"], after["date"]))
        multipliers[older["date"]] = multipliers[newer["date"]] * segment
    adjusted = []
    for row in rows:
        idx = bisect_right(dates, row["date"]) - 1
        if idx < 0:
            raise ValueError(f"no Sina US factor covers {row['date']}")
        multiplier = multipliers[dates[idx]]
        item = dict(row)
        for key in ("open", "high", "low", "close"):
            item[key] = row[key] * multiplier
        if item["close"] <= 0:
            raise ValueError(f"non-positive adjusted close on {row['date']}")
        adjusted.append(item)
    adjusted_by_date = {row["date"]: row["close"] for row in adjusted}
    for before, after in boundaries:
        change = math.log(adjusted_by_date[after] / adjusted_by_date[before])
        if abs(change) > LOG_RETURN_LIMIT:
            raise ValueError(f"factor boundary return exceeds ln(3) at {after}: {change}")
    result = pd.DataFrame(adjusted)
    if not math.isclose(result.close.iloc[-1], rows[-1]["close"], rel_tol=0, abs_tol=1e-12):
        raise ValueError("latest adjusted close does not equal the raw close")
    return result


def _history_meta(rows: list[dict], raw_gap: dict | None) -> dict:
    start = rows[0]["date"]
    note = (
        f"新浪美股日线在 {raw_gap['left']}–{raw_gap['right']} 缺失，只使用 "
        f"{raw_gap['right']} 之后的连续数据"
        if raw_gap
        else None
    )
    return {"history_start": start, "raw_gap": raw_gap, "history_note": note}


def adjust_prices(rows: list[dict], factors: list[dict]) -> pd.DataFrame:
    kept, raw_gap = recent_segment(rows)
    result = _adjust_segment(kept, factors)
    result.attrs.update(_history_meta(kept, raw_gap))
    return result


def load_us_prices(
    ticker: str, start: str = "1990-01-01"
) -> tuple[pd.DataFrame, str, dict]:
    ticker = ticker.upper()
    headers = {**UA, "Referer": REFERER}
    daily = requests.get(
        DAILY_URL, params={"symbol": ticker.lower(), "type": "daily"}, headers=headers, timeout=30
    )
    daily.raise_for_status()
    factor = requests.get(FACTOR_URL.format(ticker=ticker), headers=headers, timeout=30)
    factor.raise_for_status()
    rows = [row for row in parse_daily(daily.text) if row["date"] >= start]
    kept, raw_gap = recent_segment(rows)
    meta = _history_meta(kept, raw_gap)
    if len(kept) < 1000:
        raise ValueError(
            f"US contiguous history has {len(kept)} bars (<1000); "
            f"history_start={meta['history_start']}; raw_gap={raw_gap}"
        )
    factors = parse_factors(factor.text)
    prices = _adjust_segment(kept, factors)
    prices.attrs.update(meta)
    version = hashlib.sha1(
        prices.to_csv(index=False, float_format="%.12g").encode("utf-8")
    ).hexdigest()[:16]
    return prices, version, meta
