"""Small, explicit global daily-data snapshots for local research previews.

Yahoo v8 transport follows global-stock-data's exchange-timezone approach.
This module does not establish redistribution rights. Raw/provider data stays
under the caller's output root; it is never bundled into the source repository.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time as time_module
import uuid
from datetime import UTC, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .trading_calendar import completed_market_sessions, market_sessions

NORMALIZER_VERSION = "global_yahoo_v3_raw_ohlcv"
NAVER_NORMALIZER_VERSION = "global_naver_index_v1_unmodified_close"
NAVER_HYNIX_NORMALIZER_VERSION = "global_naver_hynix_v1_provider_close"
NAVER_SYMBOLS = {"KR_KOSDAQ": "KOSDAQ", "KR_SKHYNIX": "000660"}
FULL_HISTORY_PERIOD1 = -2208988800  # 1900-01-01; range=max may downgrade daily bars.
CROSS_CHECK_LOOKBACK_SESSIONS = 250
CROSS_CHECK_MAX_REL_DIFF = 0.005
SINA_US_SYMBOLS = {
    "US_MRVL": "MRVL",
}
FRED_SERIES = {
    "US_SPX": "SP500",
    "US_IXIC": "NASDAQCOM",
    "US_NDX": "NASDAQ100",
    "US_DJI": "DJIA",
    "JP_N225": "NIKKEI225",
}
NASDAQ_SYMBOLS = {"US_SOX": "SOX"}

ASSETS = {
    "US_SPX": dict(ticker="^GSPC", name="标普500", display_code="SPX", kind="index", market="us", currency="USD", timezone="America/New_York", display_exchange="纽约证券交易所"),
    "US_IXIC": dict(ticker="^IXIC", name="纳斯达克综合指数", display_code="IXIC", kind="index", market="us", currency="USD", timezone="America/New_York", display_exchange="纳斯达克"),
    "US_NDX": dict(ticker="^NDX", name="纳斯达克100", display_code="NDX", kind="index", market="us", currency="USD", timezone="America/New_York", display_exchange="纳斯达克"),
    "US_DJI": dict(ticker="^DJI", name="道琼斯工业平均", display_code="DJI", kind="index", market="us", currency="USD", timezone="America/New_York", display_exchange="纽约证券交易所"),
    "US_SOX": dict(ticker="^SOX", name="费城半导体指数", display_code="SOX", kind="index", market="us", currency="USD", timezone="America/New_York", display_exchange="纳斯达克"),
    "JP_N225": dict(ticker="^N225", name="日经225", display_code="N225", kind="index", market="jp", currency="JPY", timezone="Asia/Tokyo", display_exchange="东京证券交易所"),
    "KR_KOSPI": dict(ticker="^KS11", name="韩国综合指数", display_code="KOSPI", kind="index", market="kr", currency="KRW", timezone="Asia/Seoul", display_exchange="韩国交易所"),
    "KR_KOSDAQ": dict(ticker="^KQ11", name="韩国科斯达克", display_code="KOSDAQ", kind="index", market="kr", currency="KRW", timezone="Asia/Seoul", display_exchange="韩国交易所"),
    "KR_SKHYNIX": dict(ticker="000660.KS", name="SK 海力士", display_code="000660", kind="stock", market="kr", currency="KRW", timezone="Asia/Seoul", display_exchange="韩国交易所"),
    "US_MRVL": dict(ticker="MRVL", name="迈威尔科技", display_code="MRVL", kind="stock", market="us", currency="USD", timezone="America/New_York", display_exchange="纳斯达克"),
}


def normalise(payload: dict, asset_id: str, fetched_at: datetime) -> tuple[pd.DataFrame, dict]:
    """Use exchange dates; remove incomplete sessions and preserve missing OHLC."""
    asset = ASSETS[asset_id]
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise ValueError("Yahoo did not return a usable chart result")
    result = chart["result"][0]
    meta = result.get("meta", {})
    if str(meta.get("symbol", "")).upper() != asset["ticker"].upper():
        raise ValueError("Yahoo asset identity mismatch")
    if meta.get('dataGranularity') not in (None, '1d'):
        raise ValueError('Provider returned a non-daily interval')
    zone = ZoneInfo(meta.get("exchangeTimezoneName") or asset["timezone"])
    local_now = fetched_at.astimezone(zone)
    quote_data = result["indicators"]["quote"][0]
    timestamps = result.get("timestamp") or []
    adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    if asset["kind"] == "stock" and not adj:
        raise ValueError("Stock adjusted closes unavailable; refusing unlabelled input change")
    close_hour, close_minute = (16, 0) if asset["market"] == "us" else (15, 30)
    latest_close = datetime.combine(local_now.date(), time(close_hour, close_minute), zone)
    regular = meta.get("currentTradingPeriod", {}).get("regular", {})
    if regular.get("end"):
        provider_close = datetime.fromtimestamp(regular["end"], UTC).astimezone(zone)
        if provider_close.date() == local_now.date():
            latest_close = provider_close
    rows, dropped = [], 0
    for i, timestamp in enumerate(timestamps):
        date = datetime.fromtimestamp(timestamp, UTC).astimezone(zone).date()
        if date > local_now.date() or (date == local_now.date() and local_now < latest_close + timedelta(minutes=20)):
            dropped += 1
            continue
        raw_close = quote_data.get("close", [])[i]
        if raw_close is None or not np.isfinite(raw_close) or raw_close <= 0:
            continue
        adjusted = adj[i] if adj and i < len(adj) else raw_close
        if adjusted is None or not np.isfinite(adjusted) or adjusted <= 0:
            continue
        ratio = float(adjusted / raw_close) if asset["kind"] == "stock" else 1.0
        row = {"date": pd.Timestamp(date), "close": float(raw_close) * ratio,
               "raw_close": float(raw_close), "adj_close": float(adjusted)}
        for column in ("open", "high", "low", "volume"):
            values = quote_data.get(column) or []
            value = values[i] if i < len(values) else None
            valid = value is not None and np.isfinite(value) and (column == "volume" or value > 0)
            row[column] = float(value) * (ratio if column != "volume" else 1) if valid else np.nan
            row[f"raw_{column}"] = float(value) if valid else np.nan
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("No completed positive daily bars")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return frame, {
        "id": asset_id, **asset, "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "未记录",
        "timezone": str(zone), "fetched_at": fetched_at.isoformat(),
        "provider_symbol": meta.get("symbol"), "provider_currency": meta.get("currency"),
        "dropped_unclosed_bars": dropped, "rows": len(frame),
        "first_date": str(frame.date.iloc[0].date()), "asof": str(frame.date.iloc[-1].date()),
        "source": "Yahoo Finance v8 chart", "adjustment": "provider_adjclose_ratio_OHLC" if asset["kind"] == "stock" else "none",
        "volume_unit": "vendor_native", "public_redistribution": "NOT_ESTABLISHED",
        "history_vintage": "current_download_reconstruction",
        "close_cutoff_policy": "exchange date; regular close plus 20 minutes; previous dates retained",
    }


def validate_market_sessions(
    frame: pd.DataFrame, market: str, fetched_at: datetime
) -> tuple[pd.DataFrame, dict]:
    """Drop non-session bars and count recent completed sessions absent from Yahoo."""
    if market not in {"us", "jp", "kr"}:
        return frame.copy(), {
            "dropped_non_session_rows": 0,
            "dropped_non_session_dates": [],
            "missing_sessions_last_250": 0,
            "missing_sessions_last_250_dates": [],
        }
    if frame.empty:
        raise ValueError("Cannot validate an empty market history")
    dates = pd.to_datetime(frame.date).dt.normalize()
    sessions = market_sessions(market, dates.min(), dates.max())
    valid = dates.isin(sessions)
    dropped_dates = sorted(
        {date.date().isoformat() for date in dates.loc[~valid]}
    )
    filtered = frame.loc[valid].copy().sort_values("date").reset_index(drop=True)
    if filtered.empty:
        raise ValueError("No bars remain on exchange sessions")
    expected = completed_market_sessions(
        market, pd.Timestamp(fetched_at), CROSS_CHECK_LOOKBACK_SESSIONS
    )
    present = pd.DatetimeIndex(pd.to_datetime(filtered.date).dt.normalize())
    missing = expected.difference(present)
    filtered_dates = pd.to_datetime(filtered.date)
    return filtered, {
        "dropped_non_session_rows": int((~valid).sum()),
        "dropped_non_session_dates": dropped_dates,
        "missing_sessions_last_250": len(missing),
        "missing_sessions_last_250_dates": [
            date.date().isoformat() for date in missing
        ],
        "rows": len(filtered),
        "first_date": str(filtered_dates.iloc[0].date()),
        "asof": str(filtered_dates.iloc[-1].date()),
    }


def compare_cross_check(
    yahoo_frame: pd.DataFrame,
    reference_frame: pd.DataFrame,
    market: str,
    provider: str,
    fetched_at: datetime,
    *,
    sessions: pd.DatetimeIndex | None = None,
    compare_fields: tuple[str, ...] = ("close",),
    primary_label: str = "yahoo",
    yahoo_source_is_reference: bool = False,
    require_reference_coverage: bool = False,
) -> dict:
    """Compare selected daily fields within the shared source range."""
    expected = (
        completed_market_sessions(
            market, pd.Timestamp(fetched_at), CROSS_CHECK_LOOKBACK_SESSIONS
        )
        if sessions is None
        else pd.DatetimeIndex(sessions).normalize()
    )
    expected_dates = set(expected)
    yahoo = yahoo_frame.copy()
    reference = reference_frame.copy()

    def date_lists(
        missing: list[pd.Timestamp] | None = None,
        lag: list[pd.Timestamp] | None = None,
        missing_yahoo: list[pd.Timestamp] | None = None,
        yahoo_lag: list[pd.Timestamp] | None = None,
        missing_reference: list[pd.Timestamp] | None = None,
        reference_lag: list[pd.Timestamp] | None = None,
    ) -> dict:
        missing = missing or []
        lag = lag or []
        if primary_label == "yahoo":
            return {
                "missing_in_yahoo": len(missing),
                "missing_in_yahoo_dates": [date.date().isoformat() for date in missing],
                "yahoo_lag_sessions": len(lag),
                "yahoo_lag_session_dates": [date.date().isoformat() for date in lag],
            }
        result = {
            "missing_in_primary": len(missing),
            "missing_in_primary_dates": [date.date().isoformat() for date in missing],
            "primary_lag_sessions": len(lag),
            "primary_lag_session_dates": [date.date().isoformat() for date in lag],
        }
        if yahoo_source_is_reference:
            missing_yahoo = missing_yahoo or []
            yahoo_lag = yahoo_lag or []
            result.update(
                missing_in_yahoo=len(missing_yahoo),
                missing_in_yahoo_dates=[
                    date.date().isoformat() for date in missing_yahoo
                ],
                yahoo_lag_sessions=len(yahoo_lag),
                yahoo_lag_session_dates=[
                    date.date().isoformat() for date in yahoo_lag
                ],
            )
        if require_reference_coverage:
            missing_reference = missing_reference or []
            reference_lag = reference_lag or []
            result.update(
                missing_in_reference=len(missing_reference),
                missing_in_reference_dates=[
                    date.date().isoformat() for date in missing_reference
                ],
                reference_lag_sessions=len(reference_lag),
                reference_lag_session_dates=[
                    date.date().isoformat() for date in reference_lag
                ],
            )
        return result

    yahoo_dates = pd.to_datetime(yahoo.date).dt.normalize()
    reference_dates = pd.to_datetime(reference.date).dt.normalize()
    yahoo = yahoo.loc[yahoo_dates.isin(expected_dates)].copy()
    reference = reference.loc[reference_dates.isin(expected_dates)].copy()
    if reference.empty:
        return {
            "provider": provider,
            "overlap": 0,
            "max_rel_diff": None,
            **date_lists(),
            "mismatches": [],
            "status": "unavailable",
            "reason": "Second source returned no rows in the recent exchange-session window",
        }
    if yahoo.empty:
        return {
            "provider": provider,
            "overlap": 0,
            "max_rel_diff": None,
            **date_lists(),
            "mismatches": [],
            "status": "unavailable",
            "reason": "Primary source returned no rows in the recent exchange-session window",
        }
    yahoo["date"] = pd.to_datetime(yahoo.date).dt.normalize()
    reference["date"] = pd.to_datetime(reference.date).dt.normalize()
    yahoo = yahoo.drop_duplicates("date", keep="last")
    reference = reference.drop_duplicates("date", keep="last")
    yahoo_index = yahoo.set_index("date")
    reference_index = reference.set_index("date")
    primary_last_date = max(yahoo_index.index)
    reference_last_date = max(reference_index.index)
    common_end = min(primary_last_date, reference_last_date)
    reference_dates_set = set(reference_index.index)
    primary_dates_set = set(yahoo_index.index)
    missing_in_primary_dates = sorted(
        date
        for date in reference_dates_set
        if date <= common_end and date not in primary_dates_set
    )
    primary_lag_dates = sorted(
        date for date in reference_dates_set if date > primary_last_date
    )
    missing_in_yahoo_dates = (
        sorted(
            date
            for date in primary_dates_set
            if date <= common_end and date not in reference_dates_set
        )
        if yahoo_source_is_reference
        else []
    )
    yahoo_lag_dates = (
        sorted(date for date in primary_dates_set if date > reference_last_date)
        if yahoo_source_is_reference
        else []
    )
    missing_in_reference_dates = (
        sorted(
            date
            for date in primary_dates_set
            if date <= common_end and date not in reference_dates_set
        )
        if require_reference_coverage
        else []
    )
    reference_lag_dates = (
        sorted(date for date in primary_dates_set if date > reference_last_date)
        if require_reference_coverage
        else []
    )
    overlap_dates = sorted(
        date
        for date in (reference_dates_set & primary_dates_set)
        if date <= common_end
    )
    date_metadata = date_lists(
        missing_in_primary_dates,
        primary_lag_dates,
        missing_in_yahoo_dates,
        yahoo_lag_dates,
        missing_in_reference_dates,
        reference_lag_dates,
    )
    if not overlap_dates:
        return {
            "provider": provider,
            "overlap": 0,
            "max_rel_diff": None,
            **date_metadata,
            "mismatches": [],
            "status": (
                "mismatch"
                if (
                    missing_in_primary_dates
                    or missing_in_yahoo_dates
                    or missing_in_reference_dates
                )
                else "unavailable"
            ),
            **(
                {}
                if missing_in_primary_dates
                else {"reason": "Sources have no overlapping shared-range sessions"}
            ),
        }
    relative_differences = []
    mismatches = []
    for field in compare_fields:
        primary_column = (
            "raw_close" if field == "close" and "raw_close" in yahoo_index
            else f"raw_{field}" if field != "close" and f"raw_{field}" in yahoo_index
            else field
        )
        reference_column = (
            "raw_close" if field == "close" and "raw_close" in reference_index
            else f"raw_{field}" if field != "close" and f"raw_{field}" in reference_index
            else field
        )
        if primary_column not in yahoo_index or reference_column not in reference_index:
            continue
        for date in overlap_dates:
            primary_value = yahoo_index.loc[date, primary_column]
            reference_value = reference_index.loc[date, reference_column]
            if np.isfinite(primary_value) and np.isfinite(reference_value) and float(reference_value) != 0:
                relative_difference = (
                    abs(float(primary_value) - float(reference_value))
                    / abs(float(reference_value))
                )
                relative_differences.append(relative_difference)
                if relative_difference > CROSS_CHECK_MAX_REL_DIFF:
                    mismatches.append({
                        "date": date.date().isoformat(),
                        "field": field,
                        "primary_value": float(primary_value),
                        "reference_value": float(reference_value),
                        "rel_diff": relative_difference,
                    })
    if not relative_differences:
        return {
            "provider": provider,
            "overlap": 0,
            "max_rel_diff": None,
            **date_metadata,
            "mismatches": [],
            "status": "unavailable",
            "reason": "No finite overlapping comparison values were returned",
        }
    max_rel_diff = max(relative_differences)
    mismatch = (
        bool(missing_in_primary_dates)
        or bool(missing_in_yahoo_dates)
        or bool(missing_in_reference_dates)
        or max_rel_diff > CROSS_CHECK_MAX_REL_DIFF
    )
    return {
        "provider": provider,
        "overlap": len(overlap_dates),
        "max_rel_diff": max_rel_diff,
        **date_metadata,
        "mismatches": mismatches,
        "status": "mismatch" if mismatch else "ok",
    }


def _fetch_naver_cross_check(asset_id: str, fetched_at: datetime) -> pd.DataFrame:
    asset = ASSETS[asset_id]
    end_date = fetched_at.astimezone(ZoneInfo(asset["timezone"])).date()
    start_date = end_date - timedelta(days=500)
    symbol = NAVER_SYMBOLS.get(asset_id, "KOSPI")
    response = requests.get(
        "https://api.finance.naver.com/siseJson.naver",
        params={
            "symbol": symbol,
            "requestType": 1,
            "startTime": start_date.strftime("%Y%m%d"),
            "endTime": end_date.strftime("%Y%m%d"),
            "timeframe": "day",
        },
        timeout=(12, 45),
    )
    response.raise_for_status()
    data = ast.literal_eval(response.content.decode("utf-8-sig").strip())
    expected_header = ["날짜", "시가", "고가", "저가", "종가", "거래량", "외국인소진율"]
    if not isinstance(data, list) or not data or data[0] != expected_header:
        raise ValueError("Naver daily schema changed")
    rows = []
    for values in data[1:]:
        if not isinstance(values, list) or len(values) != len(expected_header):
            raise ValueError("Naver daily row schema changed")
        close = float(values[4])
        if np.isfinite(close) and close > 0:
            row = {"date": pd.to_datetime(str(values[0]), format="%Y%m%d"), "close": close}
            for name, value in zip(("open", "high", "low", "volume"), (values[1], values[2], values[3], values[5]), strict=True):
                try:
                    row[name] = float(value)
                except (TypeError, ValueError):
                    row[name] = np.nan
            rows.append(row)
    if not rows:
        raise ValueError("Naver returned no positive daily closes")
    return pd.DataFrame(rows)


def _fetch_daum_cross_check(asset_id: str) -> pd.DataFrame:
    symbol = NAVER_SYMBOLS[asset_id]
    response = requests.get(
        f"https://finance.daum.net/api/charts/A{symbol}/days",
        params={"limit": 300, "adjusted": "false"},
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120 Safari/537.36"
            ),
            "Referer": f"https://finance.daum.net/quotes/A{symbol}",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=(12, 45),
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        raise ValueError("Daum daily response is not a bar array")
    timezone = ZoneInfo(ASSETS[asset_id]["timezone"])

    def exchange_date(value):
        date = pd.Timestamp(value)
        if date.tzinfo is not None:
            date = date.tz_convert(timezone).tz_localize(None)
        return date.normalize()

    def number(value):
        return float(str(value).replace(",", ""))

    rows = []
    for item in data:
        rows.append({
            "date": exchange_date(item["date"]),
            "open": number(item["openingPrice"]),
            "high": number(item["highPrice"]),
            "low": number(item["lowPrice"]),
            "close": number(item["tradePrice"]),
            "volume": number(item["candleAccTradeVolume"]),
        })
    if not rows:
        raise ValueError("Daum returned no daily bars")
    return pd.DataFrame(rows)


def _fetch_yahoo_cross_check(asset_id: str) -> pd.DataFrame:
    asset = ASSETS[asset_id]
    response = requests.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(asset["ticker"], safe=""),
        params={"range": "2y", "interval": "1d", "events": "div,split"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=(12, 45),
    )
    response.raise_for_status()
    return normalise(response.json(), asset_id, datetime.now(UTC))[0]


def _fetch_nasdaq_cross_check(asset_id: str, fetched_at: datetime) -> pd.DataFrame:
    response = requests.get(
        f"https://api.nasdaq.com/api/quote/{NASDAQ_SYMBOLS[asset_id]}/historical",
        params={"assetclass": "index", "fromdate": (fetched_at.date() - timedelta(days=460)).isoformat(), "limit": 300},
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                 "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com",
                 "Referer": "https://www.nasdaq.com/"},
        timeout=(12, 45),
    )
    response.raise_for_status()
    rows = response.json().get("data", {}).get("tradesTable", {}).get("rows", [])
    if not rows:
        raise ValueError("Nasdaq returned no historical rows")
    def number(value):
        return float(str(value).replace(",", "")) if value not in (None, "--", "") else np.nan
    return pd.DataFrame([{
        "date": pd.to_datetime(row["date"], format="%m/%d/%Y").normalize(),
        "close": number(row["close"]), "open": number(row["open"]),
        "high": number(row["high"]), "low": number(row["low"]),
        "volume": number(row["volume"]),
    } for row in rows])


def _fetch_sina_cross_check(asset_id: str) -> pd.DataFrame:
    symbol = SINA_US_SYMBOLS[asset_id]
    response = requests.get(
        "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK",
        params={"symbol": symbol, "num": CROSS_CHECK_LOOKBACK_SESSIONS + 10},
        headers={"Referer": "https://finance.sina.com.cn/"},
        timeout=(12, 45),
    )
    response.raise_for_status()
    match = re.search(r"\((\[[^\n]+\])\)", response.text)
    if not match:
        body = " ".join(response.text.split())
        if "var(null)" in body:
            raise ValueError(f"Sina returned var(null) for {symbol}")
        raise ValueError(
            f"Sina daily response did not match its JSONP array format: {body[:120]}"
        )
    data = json.loads(match.group(1))
    if not isinstance(data, list) or not data:
        raise ValueError("Sina returned no daily bars")
    rows = []
    for item in data:
        date = pd.Timestamp(item.get("d")).normalize()
        close = float(item.get("c", "nan"))
        if np.isfinite(close) and close > 0:
            rows.append({"date": date, "close": close})
    if not rows:
        raise ValueError("Sina returned no positive daily closes")
    return pd.DataFrame(rows)


def _fetch_fred_cross_check(asset_id: str) -> pd.DataFrame:
    series = FRED_SERIES[asset_id]
    response = requests.get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": series},
        timeout=(12, 45),
    )
    response.raise_for_status()
    data = pd.read_csv(BytesIO(response.content), dtype=str)
    date_column = next(
        (column for column in data.columns if column.lower() in {"date", "observation_date"}),
        None,
    )
    value_column = series if series in data.columns else next(
        (column for column in data.columns if column != date_column), None
    )
    if date_column is None or value_column is None:
        raise ValueError(f"FRED CSV schema changed for {series}")
    frame = data.loc[:, [date_column, value_column]].rename(
        columns={date_column: "date", value_column: "close"}
    )
    frame["date"] = pd.to_datetime(frame.date, errors="coerce").dt.normalize()
    frame["close"] = pd.to_numeric(frame.close.replace(".", np.nan), errors="coerce")
    frame = frame.loc[frame.date.notna() & np.isfinite(frame.close) & (frame.close > 0)]
    if frame.empty:
        raise ValueError(f"FRED returned no positive daily closes for {series}")
    return frame


def fetch_cross_check(
    asset_id: str, yahoo_frame: pd.DataFrame, fetched_at: datetime | None = None
) -> dict:
    fetched_at = fetched_at or datetime.now(UTC)
    asset = ASSETS[asset_id]
    market = asset["market"]
    if asset["kind"] == "stock" and market == "kr":
        daum_ohlc_metadata = {
            "comparison_fields": ["open", "high", "low", "close"],
            "excluded_fields": ["volume"],
            "excluded_fields_reason": (
                "The Daum cross-check compares OHLC fields; volume is not included."
            ),
        }
        yahoo_ohl_metadata = {
            "comparison_fields": ["open", "high", "low"],
            "excluded_fields": ["close", "volume"],
            "excluded_fields_reason": (
                "Yahoo KR-stock close and volume are unreliable; the cross-check compares only open, high, and low."
            ),
        }
        try:
            reference = _fetch_daum_cross_check(asset_id)
            result = compare_cross_check(
                yahoo_frame, reference, market, "daum_finance_daily", fetched_at,
                compare_fields=("open", "high", "low", "close"),
                primary_label="naver",
                require_reference_coverage=True,
            )
            if result["status"] == "unavailable":
                raise ValueError(result["reason"])
            result.update(daum_ohlc_metadata)
            return result
        except Exception as daum_error:
            try:
                time_module.sleep(0.35)
                reference = _fetch_yahoo_cross_check(asset_id)
                result = compare_cross_check(
                    yahoo_frame, reference, market, "yahoo_chart_ohl_only",
                    fetched_at, compare_fields=("open", "high", "low"),
                    primary_label="naver",
                    yahoo_source_is_reference=True,
                )
                result.update(yahoo_ohl_metadata)
                result["fallback_reason"] = f"Daum unavailable: {type(daum_error).__name__}: {daum_error}"
                return result
            except Exception as yahoo_error:
                return {
                    "provider": "unavailable",
                    "overlap": 0,
                    "max_rel_diff": None,
                    "missing_in_primary": 0,
                    "missing_in_primary_dates": [],
                    **yahoo_ohl_metadata,
                    "status": "unavailable",
                    "reason": (
                        f"Daum unavailable: {type(daum_error).__name__}: {daum_error}; "
                        f"Yahoo fallback unavailable: {type(yahoo_error).__name__}: {yahoo_error}"
                    ),
                }
    if asset_id in FRED_SERIES:
        provider = "fredgraph_csv"
    elif asset_id in NASDAQ_SYMBOLS:
        provider = "nasdaq_api"
    elif asset_id in SINA_US_SYMBOLS:
        provider = "sina_us_daily_k"
    elif market == "kr":
        provider = "naver_siseJson"
    else:
        provider = "not_configured"
        return {
            "provider": provider,
            "overlap": 0,
            "max_rel_diff": None,
            "missing_in_yahoo": 0,
            "missing_in_yahoo_dates": [],
            "yahoo_lag_sessions": 0,
            "yahoo_lag_session_dates": [],
            "status": "unavailable",
            "reason": "No independent second source is configured for this asset",
        }
    try:
        if asset_id in FRED_SERIES:
            reference = _fetch_fred_cross_check(asset_id)
        elif asset_id in SINA_US_SYMBOLS:
            reference = _fetch_sina_cross_check(asset_id)
        elif asset_id in NASDAQ_SYMBOLS:
            reference = _fetch_nasdaq_cross_check(asset_id, fetched_at)
        else:
            reference = _fetch_naver_cross_check(asset_id, fetched_at)
        return compare_cross_check(
            yahoo_frame, reference, market, provider, fetched_at
        )
    except Exception as error:
        return {
            "provider": provider,
            "overlap": 0,
            "max_rel_diff": None,
            "missing_in_yahoo": 0,
            "missing_in_yahoo_dates": [],
            "yahoo_lag_sessions": 0,
            "yahoo_lag_session_dates": [],
            "status": "unavailable",
            "reason": f"{type(error).__name__}: {error}",
        }


def _atomic_pointer(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def normalise_naver(raw: bytes, asset_id: str, fetched_at: datetime) -> tuple[pd.DataFrame, dict]:
    """Preserve the entire Naver series without filling from another vendor.

    The endpoint returns a JavaScript-like literal, not strict JSON. literal_eval
    parses data without executing code. Historical Saturday sessions are retained.
    """
    if asset_id not in NAVER_SYMBOLS:
        raise ValueError('Unsupported Naver asset')
    data = ast.literal_eval(raw.decode('utf-8-sig').strip())
    expected = ['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율']
    if not isinstance(data, list) or not data or data[0] != expected:
        raise ValueError('Naver daily schema changed')
    asset = ASSETS[asset_id]
    zone = ZoneInfo(asset['timezone'])
    local_now = fetched_at.astimezone(zone)
    cutoff = datetime.combine(local_now.date(), time(15, 50), zone)
    rows, dropped = [], 0
    for values in data[1:]:
        if not isinstance(values, list) or len(values) != len(expected):
            raise ValueError('Naver daily row schema changed')
        date = datetime.strptime(str(values[0]), '%Y%m%d').date()
        if date > local_now.date() or (date == local_now.date() and local_now < cutoff):
            dropped += 1
            continue
        close = float(values[4])
        if not np.isfinite(close) or close <= 0:
            raise ValueError('Naver contains a nonpositive or nonfinite close')
        row = {'date': pd.Timestamp(date), 'close': close, 'raw_close': close, 'adj_close': close}
        for name, value in zip(('open', 'high', 'low', 'volume'), (values[1], values[2], values[3], values[5]), strict=True):
            valid = value is not None and np.isfinite(value) and (value >= 0 if name == 'volume' else value > 0)
            row[name] = float(value) if valid else np.nan
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError('No completed positive daily bars')
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ValueError('Naver daily dates must be unique and ascending')
    info = {
        'id': asset_id, **asset, 'exchange': 'KOSDAQ', 'provider': 'naver',
        'provider_symbol': 'KOSDAQ', 'provider_currency': 'KRW',
        'identity_validation': 'request_bound_symbol; response has no independent symbol field',
        'fetched_at': fetched_at.isoformat(), 'timezone': str(zone), 'rows': len(frame),
        'first_date': str(frame.date.iloc[0].date()), 'asof': str(frame.date.iloc[-1].date()),
        'source': 'Naver Finance siseJson daily', 'adjustment': 'provider_index_level_unmodified',
        'index_level_basis': 'vendor historical index level; no locally applied rebasing',
        'ohlc_caveat': 'early vendor OHLC can all equal close; historical independent OHLC completeness not established',
        'volume_unit': 'vendor_native', 'public_redistribution': 'NOT_ESTABLISHED',
        'history_vintage': 'current_download_reconstruction',
        'close_cutoff_policy': 'Asia/Seoul date; regular close plus 20 minutes; previous dates retained',
        'dropped_unclosed_bars': dropped, 'normalizer_version': NAVER_NORMALIZER_VERSION,
        'raw_format': 'naver_array_literal',
        'data_quality': {
            'status': 'unresolved_cross_source_discrepancy',
            'observed_at': '2026-11-23', 'affected_date': '2001-11-01',
            'observed_naver_close': 625.5, 'observed_yahoo_close': 636.4000244140625,
            'current_source_close': next((float(r.close) for r in frame.itertuples() if r.date == pd.Timestamp('2001-11-01')), None),
            'policy': 'retain full Naver series unchanged; cross-source sensitivity is a separately labelled noncanonical experiment',
            'independent_exchange_adjudication': 'NOT_ESTABLISHED',
        },
    }
    if asset_id == 'KR_SKHYNIX':
        info.pop('index_level_basis')
        info.update(
            exchange='KRX KOSPI', provider_symbol=NAVER_SYMBOLS[asset_id],
            adjustment='供应商原始价格口径，未另行复权',
            normalizer_version=NAVER_HYNIX_NORMALIZER_VERSION,
            data_quality={
                'status': 'provider_price_basis',
                'policy': '保留 Naver 完整价格序列，不拼接 Yahoo 复权价格。',
                'independent_exchange_adjudication': 'NOT_ESTABLISHED',
            },
        )
    return frame, info


def _vintage_comparison(frame: pd.DataFrame, previous: pd.DataFrame, previous_info: dict) -> dict:
    overlap = frame[['date', 'close']].merge(previous[['date', 'close']], on='date', suffixes=('_new', '_old'))
    changed = overlap.close_new != overlap.close_old
    material = overlap.close_new.round(2) != overlap.close_old.round(2)
    samples = overlap.loc[material].head(20)
    return {
        'previous_provider': previous_info.get('provider', 'yahoo'),
        'previous_metadata_file': previous_info.get('metadata_file'),
        'previous_normalized_sha256': previous_info['normalized_sha256'],
        'overlap_rows': len(overlap), 'exact_close_changes': int(changed.sum()),
        'close_changes_at_two_decimals': int(material.sum()),
        'max_close_absolute_difference': float((overlap.close_new - overlap.close_old).abs().max()) if len(overlap) else None,
        'material_close_difference_samples': [
            {'date': str(row.date.date()), 'new_close': float(row.close_new), 'previous_close': float(row.close_old)}
            for row in samples.itertuples()
        ],
        'comparison_only_no_values_replaced': True,
    }


def save_snapshot(folder: Path, raw: bytes, frame: pd.DataFrame, info: dict) -> dict:
    """Content-address each normalized vintage, even when raw bytes repeat."""
    digest = hashlib.sha256(raw).hexdigest()
    normalized = frame.to_parquet(index=False)
    normalized_digest = hashlib.sha256(normalized).hexdigest()
    raw_file = digest + ".raw.json"
    normalizer_version = info.get('normalizer_version', NORMALIZER_VERSION)
    normalized_file = f"{normalizer_version}-{normalized_digest}.parquet"
    info = {**{k: v for k, v in info.items() if k != "metadata_file"}, "normalizer_version": normalizer_version, "raw_file": raw_file,
            "raw_sha256": digest, "normalized_file": normalized_file,
            "normalized_sha256": normalized_digest}
    metadata_digest = hashlib.sha256(json.dumps(info, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    metadata_file = f"{digest}-{metadata_digest}.metadata.json"
    info["metadata_file"] = metadata_file
    folder.mkdir(parents=True, exist_ok=True)
    for filename, content in ((raw_file, raw), (normalized_file, normalized),
                              (metadata_file, json.dumps(info, ensure_ascii=False, indent=2).encode())):
        path = folder / filename
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError("Immutable source file content mismatch")
        else:
            path.write_bytes(content)
    _atomic_pointer(folder / "latest.json", info)
    return info


def _cached_snapshot(asset_id: str, folder: Path) -> tuple[pd.DataFrame, dict]:
    info = json.loads((folder / 'latest.json').read_text(encoding='utf-8'))
    if info.get('id') != asset_id or info.get('ticker') != ASSETS[asset_id]['ticker']:
        raise ValueError('Cached source identity mismatch')
    for file_key, hash_key in (('normalized_file', 'normalized_sha256'), ('raw_file', 'raw_sha256')):
        path = (folder / info[file_key]).resolve()
        if not path.is_relative_to(folder.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != info[hash_key]:
            raise ValueError('Cached source snapshot checksum mismatch')
    return pd.read_parquet(BytesIO((folder / info['normalized_file']).read_bytes())), info


def load_cached_snapshot(asset_id: str, root: Path) -> tuple[pd.DataFrame, dict]:
    """Strictly local verified cache read; missing/corrupt cache never fetches."""
    return _cached_snapshot(asset_id, Path(root) / 'source' / asset_id)


def _coverage_problem(frame: pd.DataFrame, minimum_rows: int | None, previous: pd.DataFrame | None) -> str | None:
    if minimum_rows is not None and len(frame) < minimum_rows:
        return f'Insufficient daily history: required {minimum_rows}, received {len(frame)}; no padding or proxy substitution'
    if previous is not None:
        missing = sorted(set(previous.date) - set(frame.date))
        if missing:
            return f'Provider history coverage regressed: {len(missing)} previously stored dates absent, first {missing[0].date()}'
    return None


def _save_rejection(folder: Path, raw: bytes, info: dict, reason: str) -> None:
    rejected = folder / 'rejected'
    rejected.mkdir(parents=True, exist_ok=True)
    raw_hash = hashlib.sha256(raw).hexdigest()
    raw_path = rejected / (raw_hash + '.raw.json')
    if not raw_path.exists():
        raw_path.write_bytes(raw)
    evidence = {**info, 'status': 'rejected', 'reason': reason, 'raw_sha256': raw_hash,
                'raw_file': raw_path.name, 'latest_pointer_updated': False}
    evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    evidence_path = rejected / (evidence_hash + '.json')
    if not evidence_path.exists():
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')


def fetch_snapshot(asset_id: str, root: Path, *, refresh: bool = False,
                   full_history: bool = False, minimum_rows: int | None = None,
                   provider: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Fetch explicit daily history and never silently shorten an accepted vintage.

    Full history means the provider's available daily history, not proof of an
    exchange-complete archive. Existing short-history callers keep their default
    start; once this root has a full-history snapshot, refreshes retain that scope.
    A KOSDAQ full-history request selects the independent Naver series because
    Yahoo begins in 2000. provider='yahoo' explicitly selects the shorter source.
    SK hynix defaults to Naver; an explicit Yahoo provider keeps it available as
    the primary feed when Naver is used for an independent cross-check.
    Provider transitions keep all prior vintages and record overlap differences.
    """
    if not isinstance(full_history, bool):
        raise ValueError('full_history must be boolean')
    if minimum_rows is not None and (isinstance(minimum_rows, bool) or not isinstance(minimum_rows, int) or minimum_rows < 1):
        raise ValueError('minimum_rows must be a positive integer')
    asset = ASSETS[asset_id]
    if (provider not in (None, 'yahoo', 'naver', 'yfinance')
            or (provider == 'naver' and asset_id not in NAVER_SYMBOLS)
            or (provider == 'yfinance' and asset_id not in {'US_IXIC', 'US_NDX'})):
        raise ValueError('Unsupported asset/provider combination')
    folder = Path(root) / "source" / asset_id
    pointer = folder / "latest.json"
    previous, previous_info = _cached_snapshot(asset_id, folder) if pointer.exists() else (None, {})
    effective_full_history = full_history or previous_info.get('full_history_requested', False)
    use_naver = (
        (asset_id == 'KR_SKHYNIX' and provider != 'yahoo')
        or (asset_id == 'KR_KOSDAQ' and full_history)
    )
    selected_provider = provider or ('naver' if use_naver else previous_info.get('provider', 'yahoo'))
    same_provider = selected_provider == previous_info.get('provider', 'yahoo')
    if previous is not None and same_provider and not refresh and (not full_history or previous_info.get('full_history_requested')):
        problem = _coverage_problem(previous, minimum_rows, None)
        if problem:
            raise ValueError(problem)
        return previous, previous_info
    if selected_provider == 'yfinance':
        from .nasdaq_yfinance import download_nasdaq

        raw, frame, info = download_nasdaq(
            asset_id, Path(root), previous=previous, previous_info=previous_info,
            full_history=effective_full_history,
        )
        info['minimum_rows_requested'] = minimum_rows
        if previous is not None:
            info['previous_vintage_comparison'] = _vintage_comparison(frame, previous, previous_info)
            info['provider_changed'] = not same_provider
        problem = _coverage_problem(frame, minimum_rows, previous)
        if problem:
            _save_rejection(folder, raw, info, problem)
            raise ValueError(problem)
        return frame, save_snapshot(folder, raw, frame, info)
    if selected_provider == 'naver':
        url = 'https://api.finance.naver.com/siseJson.naver'
        params = {'symbol': NAVER_SYMBOLS[asset_id], 'requestType': 1, 'startTime': '19000101' if effective_full_history else '20000101',
                  'endTime': datetime.now(ZoneInfo(asset['timezone'])).strftime('%Y%m%d'), 'timeframe': 'day'}
    else:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(asset["ticker"], safe="")
        params = {"period1": FULL_HISTORY_PERIOD1 if effective_full_history else 946684800,
                  "period2": int(datetime.now(UTC).timestamp()), "interval": "1d", "events": "div,split"}
    response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=(12, 45))
    response.raise_for_status()
    fetched_at = datetime.now(UTC)
    raw = response.content
    frame, info = normalise_naver(raw, asset_id, fetched_at) if selected_provider == 'naver' else normalise(response.json(), asset_id, fetched_at)
    info.update(url=response.url, http_status=response.status_code, provider=selected_provider, full_history_requested=effective_full_history,
                requested_period1=params.get('period1'), requested_start_date=params.get('startTime'), requested_interval='1d', minimum_rows_requested=minimum_rows,
                coverage_scope='provider_available_daily_history' if effective_full_history else 'since_2000_daily_history')
    if previous is not None:
        info['previous_vintage_comparison'] = _vintage_comparison(frame, previous, previous_info)
        info['provider_changed'] = not same_provider
    problem = _coverage_problem(frame, minimum_rows, previous)
    if problem:
        _save_rejection(folder, raw, info, problem)
        raise ValueError(problem)
    return frame, save_snapshot(folder, raw, frame, info)
