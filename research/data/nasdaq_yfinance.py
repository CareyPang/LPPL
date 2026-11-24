"""Raw daily Nasdaq downloads with validated, provenance-linked incremental refresh.

This adapter never persists a snapshot or modifies a latest pointer. Its caller
must validate and content-address the returned raw/normalized pair atomically.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .trading_calendar import completed_market_sessions, market_sessions

NORMALIZER_VERSION = "yfinance_nasdaq_v1_raw_daily"
SYMBOLS = {"US_IXIC": "^IXIC", "US_NDX": "^NDX"}
OVERLAP_ROWS = 10
DOWNLOAD_TIMEOUT_SECONDS = 30
_FIELDS = {
    "open": "open", "high": "high", "low": "low", "close": "close",
    "adjclose": "adj_close", "volume": "volume", "dividends": "dividends",
    "stocksplits": "stock_splits", "capitalgains": "capital_gains",
}


def _field(value: object) -> str | None:
    return _FIELDS.get(str(value).strip().lower().replace(" ", "").replace("_", ""))


def _dates(values: object, *, exchange_timezone: str | None = None) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    if result.hasnans:
        raise ValueError("Missing daily bar date")
    if result.tz is not None:
        if exchange_timezone:
            result = result.tz_convert(exchange_timezone)
        result = result.tz_localize(None)
    return result.normalize()


def _columns(download: pd.DataFrame, ticker: str) -> tuple[dict[str, object], str]:
    for attribute in ("ticker", "symbol"):
        claimed = download.attrs.get(attribute)
        if claimed is not None and str(claimed).upper() != ticker.upper():
            raise ValueError("Downloaded asset identity mismatch")
    if download.columns.has_duplicates:
        raise ValueError("Duplicate downloaded columns")
    if isinstance(download.columns, pd.MultiIndex):
        if download.columns.nlevels != 2:
            raise ValueError("Expected a two-level OHLC/ticker column index")
        levels = [
            level for level in (0, 1)
            if "close" in {_field(v) for v in download.columns.get_level_values(level)}
            and all(_field(v) for v in download.columns.get_level_values(level))
        ]
        if len(levels) != 1:
            raise ValueError("Ambiguous OHLC/ticker column levels")
        level = levels[0]
        tickers = {str(v).upper() for v in download.columns.get_level_values(1 - level)}
        if tickers != {ticker.upper()}:
            raise ValueError("Downloaded asset identity mismatch or mixed tickers")
        result = {_field(c[level]): c for c in download.columns}
        identity = "downloaded_multiindex_ticker"
    else:
        if not all(_field(c) for c in download.columns):
            raise ValueError("Unexpected downloaded daily columns")
        result = {_field(c): c for c in download.columns}
        identity = "requested_ticker_only_single_level"
    if len(result) != len(download.columns) or "close" not in result:
        raise ValueError("Missing close or duplicate normalized daily columns")
    return result, identity


def _validate_prices(frame: pd.DataFrame) -> None:
    for name in ("open", "high", "low", "close", "adj_close", "volume"):
        if name not in frame:
            continue
        values = pd.to_numeric(frame[name], errors="raise")
        present = values.notna()
        if (present & ~np.isfinite(values)).any():
            raise ValueError(f"Non-finite daily {name}")
        if name == "close" and (not present.all() or (values <= 0).any()):
            raise ValueError("Invalid daily close")
        if name != "close" and (values[present] < 0 if name == "volume" else values[present] <= 0).any():
            raise ValueError(f"Invalid daily {name}")
    for lower, upper in (("low", "high"), ("low", "close"), ("close", "high"),
                         ("low", "open"), ("open", "high")):
        if lower in frame and upper in frame:
            if (frame[lower].notna() & frame[upper].notna() & (frame[lower] > frame[upper])).any():
                raise ValueError(f"Inconsistent OHLC: {lower} exceeds {upper}")


def _normalise(download: pd.DataFrame, ticker: str, fetched_at: datetime) -> tuple[pd.DataFrame, dict]:
    if not isinstance(download, pd.DataFrame) or download.empty:
        raise ValueError("Empty yfinance daily download")
    columns, identity = _columns(download, ticker)
    dates = _dates(download.index, exchange_timezone="America/New_York")
    if dates.has_duplicates:
        raise ValueError("Duplicate exchange dates in daily download")
    frame = pd.DataFrame({"date": dates})
    for name in ("open", "high", "low", "close", "adj_close", "volume"):
        frame[name] = (
            pd.to_numeric(download[columns[name]], errors="raise").to_numpy(dtype=float)
            if name in columns else np.nan
        )
    _validate_prices(frame)
    for name in ("open", "high", "low", "close", "volume"):
        frame[f"raw_{name}"] = frame[name]
    sessions = _dates(market_sessions("us", dates.min(), dates.max()))
    completed = _dates(completed_market_sessions("us", pd.Timestamp(fetched_at), count=1))
    if completed.empty:
        raise ValueError("No completed exchange session at fetched_at")
    latest = completed[-1]
    on_session = frame.date.isin(sessions)
    closed = frame.date <= latest
    filtered = frame.loc[on_session & closed].sort_values("date").reset_index(drop=True)
    if filtered.empty:
        raise ValueError("No completed positive daily bars")
    if filtered.date.iloc[-1] < latest:
        raise ValueError("Daily download lags the latest completed exchange session")
    return filtered, {
        "identity_evidence": identity,
        "dropped_non_session_rows": int((~on_session).sum()),
        "dropped_non_session_dates": [d.date().isoformat() for d in frame.loc[~on_session, "date"]],
        "dropped_unclosed_bars": int((on_session & ~closed).sum()),
        "latest_completed_session": latest.date().isoformat(),
    }


def _previous(previous: pd.DataFrame, info: dict, asset_id: str) -> pd.DataFrame:
    if info.get("id") != asset_id or info.get("ticker") != SYMBOLS[asset_id]:
        raise ValueError("Cached asset identity mismatch")
    if not info.get("normalized_sha256"):
        raise ValueError("Cached snapshot has no normalized hash provenance")
    if previous.empty or not {"date", "close"}.issubset(previous.columns):
        raise ValueError("Incomplete cached daily frame")
    frame = previous.copy()
    frame["date"] = _dates(frame.date)
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ValueError("Cached dates must be unique and ordered")
    _validate_prices(frame)
    if info.get("rows") != len(frame) or info.get("asof") != frame.date.iloc[-1].date().isoformat():
        raise ValueError("Cached coverage metadata does not match the frame")
    if info.get("first_date") != frame.date.iloc[0].date().isoformat():
        raise ValueError("Cached first date does not match the frame")
    return frame


def _revisions(fresh: pd.DataFrame, previous: pd.DataFrame) -> dict:
    fields = [c for c in ("open", "high", "low", "close", "volume", "adj_close") if c in previous]
    old = previous.set_index("date")
    new = fresh.set_index("date")
    dates = old.index.intersection(new.index)
    changed_rows: set[pd.Timestamp] = set()
    samples = []
    changed_cells = 0
    for name in fields:
        before, after = old.loc[dates, name], new.loc[dates, name]
        changed = ~(before.eq(after) | (before.isna() & after.isna()))
        changed_cells += int(changed.sum())
        for date in dates[changed]:
            changed_rows.add(date)
            if len(samples) < 20:
                samples.append({
                    "date": date.date().isoformat(), "field": name,
                    "previous": None if pd.isna(before.loc[date]) else float(before.loc[date]),
                    "new": None if pd.isna(after.loc[date]) else float(after.loc[date]),
                })
    return {"overlap_rows": len(dates), "changed_rows": len(changed_rows),
            "changed_cells": changed_cells, "samples": samples,
            "scope": "downloaded_overlap_only; older prefix not revalidated"}


def download_nasdaq(
    asset_id: str,
    root: Path,
    *,
    previous: pd.DataFrame | None = None,
    previous_info: dict | None = None,
    full_history: bool = False,
    fetched_at: datetime | None = None,
    downloader: Callable | None = None,
) -> tuple[bytes, pd.DataFrame, dict]:
    """Download IXIC/NDX raw daily bars; return raw JSON, frame and provenance.

    A matching, verified cache refreshes only its last ten stored rows onward.
    Changing provider/normalizer or upgrading to max history uses a full request.
    ``previous`` must come from the caller's checksum-verified cache loader.
    ``downloader`` is an injectable yfinance.download-compatible callable.
    """
    if asset_id not in SYMBOLS:
        raise ValueError("Only US_IXIC and US_NDX are supported by the yfinance adapter")
    from .global_terminal import ASSETS

    asset = ASSETS[asset_id]
    ticker = SYMBOLS[asset_id]
    if asset.get("ticker") != ticker or asset.get("market") != "us":
        raise ValueError("Asset registry identity mismatch")
    now = pd.Timestamp(fetched_at if fetched_at is not None else datetime.now(UTC))
    if now.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    fetched_at = now.tz_convert("UTC").to_pydatetime()
    previous_info = dict(previous_info or {})
    old = _previous(previous, previous_info, asset_id) if previous is not None else None
    effective_full = bool(full_history or (old is not None and previous_info.get("full_history_requested")))
    incremental = (
        old is not None and previous_info.get("provider") == "yfinance"
        and previous_info.get("normalizer_version") == NORMALIZER_VERSION
        and (not full_history or previous_info.get("full_history_requested", False))
    )
    request = {
        "tickers": ticker, "interval": "1d", "auto_adjust": False, "repair": False,
        "threads": False, "progress": False, "ignore_tz": False,
        "timeout": DOWNLOAD_TIMEOUT_SECONDS,
    }
    if incremental:
        start = old.date.iloc[-min(OVERLAP_ROWS, len(old))]
        request["start"] = start.date().isoformat()
    elif effective_full:
        request["period"] = "max"
    else:
        request["start"] = "2000-01-01"
    cache_dir = Path(root).resolve() / ".cache" / "yfinance"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if downloader is None:
        import yfinance as yf

        yf.set_tz_cache_location(str(cache_dir))
        downloader = yf.download
    downloaded = downloader(**request)
    fresh, validation = _normalise(downloaded, ticker, fetched_at)
    raw = json.dumps({
        "schema_version": "yfinance_dataframe_download_v1", "asset_id": asset_id,
        "ticker": ticker, "fetched_at": fetched_at.isoformat(), "request": request,
        "index_timezone": str(downloaded.index.tz) if isinstance(downloaded.index, pd.DatetimeIndex) else None,
        "payload": json.loads(downloaded.to_json(orient="split", date_format="iso", date_unit="ms", double_precision=15)),
        "note": "Observed yfinance DataFrame, not original Yahoo HTTP response bytes",
    }, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    revisions = _revisions(fresh, old) if old is not None else None
    if incremental:
        if (fresh.date < start).any():
            raise ValueError("Incremental download contains dates before the requested overlap")
        expected = _dates(market_sessions("us", start, pd.Timestamp(validation["latest_completed_session"])))
        missing_sessions = expected.difference(pd.DatetimeIndex(fresh.date))
        missing_old = pd.DatetimeIndex(old.loc[old.date >= start, "date"]).difference(pd.DatetimeIndex(fresh.date))
        if len(missing_sessions) or len(missing_old):
            missing = sorted(set(missing_sessions) | set(missing_old))
            raise ValueError(f"Incremental coverage incomplete: missing {missing[0].date()}")
        frame = pd.concat([old.loc[old.date < start], fresh], ignore_index=True)
    else:
        frame = fresh
    if old is not None:
        if not set(old.date).issubset(set(frame.date)):
            raise ValueError("Provider history coverage regressed: cached dates absent")
        if frame.date.iloc[-1] < old.date.iloc[-1]:
            raise ValueError("Provider history moved backwards")
    expected_all = _dates(market_sessions(
        "us", frame.date.iloc[0], pd.Timestamp(validation["latest_completed_session"]),
    ))
    observed_all = pd.DatetimeIndex(frame.date)
    missing_all = expected_all.difference(observed_all)
    unexpected_all = observed_all.difference(expected_all)
    if len(missing_all):
        raise ValueError(
            f"Full history coverage incomplete: {len(missing_all)} exchange sessions absent, "
            f"first {missing_all[0].date()}",
        )
    if len(unexpected_all) or observed_all.has_duplicates:
        raise ValueError("Final history contains non-session or duplicate dates")
    info = {
        "id": asset_id, **asset, "exchange": "NASDAQ", "provider": "yfinance",
        "provider_symbol": ticker, "provider_currency": asset["currency"],
        "source": "Yahoo Finance via yfinance", "normalizer_version": NORMALIZER_VERSION,
        "fetched_at": fetched_at.isoformat(), "rows": len(frame),
        "first_date": frame.date.iloc[0].date().isoformat(), "asof": frame.date.iloc[-1].date().isoformat(),
        "adjustment": "none", "price_basis": "unadjusted_provider_index_level",
        "volume_unit": "vendor_native", "public_redistribution": "NOT_ESTABLISHED",
        "history_vintage": "current_download_reconstruction",
        "close_cutoff_policy": "XNYS exchange date/session close plus 20 minutes; non-sessions excluded",
        "full_history_requested": effective_full,
        "coverage_scope": "provider_available_daily_history" if effective_full else "since_2000_daily_history",
        "download_mode": "incremental_overlap" if incremental else "full",
        "request": request, "cache_directory": str(cache_dir),
        "raw_format": "yfinance_dataframe_download_v1", "download_rows": len(fresh),
        "previous_prefix_rows_preserved": int((old.date < start).sum()) if incremental else 0,
        "session_coverage": {
            "status": "complete", "calendar": "XNYS", "market": "us",
            "first_date": frame.date.iloc[0].date().isoformat(),
            "through": validation["latest_completed_session"],
            "expected_sessions": len(expected_all), "observed_sessions": len(observed_all),
            "missing_sessions": 0, "missing_session_dates": [],
            "scope": "all sessions from the first returned date; not proof of inception coverage",
        },
        **validation,
    }
    if old is not None:
        info.update(
            previous_normalized_sha256=previous_info["normalized_sha256"],
            previous_raw_sha256=previous_info.get("raw_sha256"),
            previous_metadata_file=previous_info.get("metadata_file"),
            previous_provider=previous_info.get("provider"),
            previous_normalizer_version=previous_info.get("normalizer_version"),
            overlap_revisions=revisions,
        )
    return raw, frame, info
