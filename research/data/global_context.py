"""Pure normalizers for the P2 global context and P3 probability snapshots.

This module has no network client and is deliberately independent of LPPLS.
Fetchers can pass an already-saved response and its hash to the functions here;
the resulting object keeps enough provenance to distinguish a fresh value from
an unavailable or stale source.  Missing observations remain ``None`` or an
empty list and are never converted to zero.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime
from typing import Any

GLOBAL_SCHEMA_VERSION = "global-context.v1"
PROBABILITY_SCHEMA_VERSION = "macro-probability.v1"
EVIDENCE = "descriptive"

VALID_STATUSES = frozenset(
    {
        "ok",
        "partial",
        "not_requested",
        "not_available",
        "stale",
        "source_unavailable",
        "schema_changed",
    }
)

_TREASURY_TENORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1m", ("1 Mo", "1M", "1 month", "1_month")),
    ("2m", ("2 Mo", "2M", "2 month", "2_month")),
    ("3m", ("3 Mo", "3M", "3 month", "3_month")),
    ("4m", ("4 Mo", "4M", "4 month", "4_month")),
    ("6m", ("6 Mo", "6M", "6 month", "6_month")),
    ("1y", ("1 Yr", "1Y", "1 year", "1_year")),
    ("2y", ("2 Yr", "2Y", "2 year", "2_year")),
    ("3y", ("3 Yr", "3Y", "3 year", "3_year")),
    ("5y", ("5 Yr", "5Y", "5 year", "5_year")),
    ("7y", ("7 Yr", "7Y", "7 year", "7_year")),
    ("10y", ("10 Yr", "10Y", "10 year", "10_year")),
    ("20y", ("20 Yr", "20Y", "20 year", "20_year")),
    ("30y", ("30 Yr", "30Y", "30 year", "30_year")),
)


def json_sha256(value: Any) -> str:
    """Return a stable hash for a JSON-compatible value."""

    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _iso_date(value: Any, field: str = "asof") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc
    if normalized != value:
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return value


def _iso_timestamp(value: Any, field: str = "fetched_at") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    candidate = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    return value


def _status(value: Any, *, default: str = "ok") -> str:
    status = str(value or default)
    if status not in VALID_STATUSES:
        raise ValueError(f"unsupported status: {status}")
    return status


def source_meta(
    source: str,
    *,
    source_url: str | None,
    asof: str,
    fetched_at: str,
    status: str = "ok",
    stale_reason: str | None = None,
    raw_sha256: str | None = None,
    license_tier: str | None = None,
) -> dict[str, Any]:
    """Build the common provenance record used by P2 and P3."""

    asof = _iso_date(asof)
    fetched_at = _iso_timestamp(fetched_at)
    status = _status(status)
    return {
        "source": source,
        "source_id": source,
        "source_url": source_url,
        "asof": asof,
        "fetched_at": fetched_at,
        "status": status,
        "stale_reason": stale_reason,
        "raw_sha256": raw_sha256,
        "license_tier": license_tier,
    }


def _rows(payload: Any, *keys: str) -> list[Mapping[str, Any]] | None:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        values = payload
    elif isinstance(payload, Mapping):
        values = None
        for key in keys:
            candidate = payload.get(key)
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
                values = candidate
                break
        if values is None:
            return None
    else:
        return None
    return [dict(row) for row in values if isinstance(row, Mapping)]


def _section(
    meta: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    section: str,
    stale_reason: str | None = None,
) -> dict[str, Any]:
    """Wrap canonical rows while retaining the source metadata."""

    source = deepcopy(dict(meta))
    values = [deepcopy(dict(row)) for row in rows] if rows is not None else []
    status = str(source.get("status") or "ok")
    if rows is None and status == "ok":
        status = "schema_changed"
        source["status"] = status
        source["stale_reason"] = stale_reason or "response shape did not contain a supported rows field"
    elif stale_reason is not None:
        source["stale_reason"] = stale_reason
    return {
        "section": section,
        "source": source.get("source"),
        "source_url": source.get("source_url"),
        "asof": source.get("asof"),
        "fetched_at": source.get("fetched_at"),
        "status": status,
        "stale_reason": source.get("stale_reason"),
        "raw_sha256": source.get("raw_sha256"),
        "license_tier": source.get("license_tier"),
        "evidence": EVIDENCE,
        "rows": values,
    }


def _first(row: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def parse_treasury_curve(
    payload: Any,
    *,
    asof: str,
    fetched_at: str,
    source_url: str | None,
    raw_sha256: str | None,
    license_tier: str | None = None,
    status: str = "ok",
    stale_reason: str | None = None,
) -> dict[str, Any]:
    """Normalize Treasury daily-rate rows from the public response shape.

    The parser accepts either a list or a mapping containing ``data`` or
    ``results``.  Unknown fields are ignored so an upstream additive field does
    not change the canonical contract; a missing rows container is explicit
    ``schema_changed``.
    """

    meta = source_meta(
        "us_treasury",
        source_url=source_url,
        asof=asof,
        fetched_at=fetched_at,
        status=status,
        stale_reason=stale_reason,
        raw_sha256=raw_sha256,
        license_tier=license_tier,
    )
    raw_rows = _rows(payload, "data", "results", "records")
    if raw_rows is None:
        return _section(meta, None, section="treasury_curve", stale_reason=stale_reason)
    normalized: list[dict[str, Any]] = []
    for row in raw_rows:
        row_date = _first(row, ("record_date", "recordDate", "date", "asof", "asOfDate"))
        tenors: dict[str, Any] = {}
        for tenor, aliases in _TREASURY_TENORS:
            value = _first(row, aliases)
            if value is not None:
                tenors[tenor] = value
        normalized.append({"asof": row_date, "tenors": tenors})
    return _section(meta, normalized, section="treasury_curve")


def _parse_observations(
    payload: Any,
    *,
    meta: Mapping[str, Any],
    section: str,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    raw_rows = _rows(payload, "observations", "data", "results", "series")
    if raw_rows is None:
        return _section(meta, None, section=section)
    normalized = []
    for row in raw_rows:
        period = _first(row, ("date", "asof", "period", "observation_date", "effectiveDate", "year"))
        value = _first(row, keys)
        normalized.append({"asof": period, "value": value})
    return _section(meta, normalized, section=section)


def parse_ny_fed_observations(
    payload: Any,
    *,
    asof: str,
    fetched_at: str,
    source_url: str | None,
    raw_sha256: str | None,
    license_tier: str | None = None,
    status: str = "ok",
    stale_reason: str | None = None,
) -> dict[str, Any]:
    """Normalize an NY Fed observations response (for example SOFR)."""

    meta = source_meta(
        "ny_fed",
        source_url=source_url,
        asof=asof,
        fetched_at=fetched_at,
        status=status,
        stale_reason=stale_reason,
        raw_sha256=raw_sha256,
        license_tier=license_tier,
    )
    return _parse_observations(
        payload,
        meta=meta,
        section="ny_fed_observations",
        keys=("value", "rate", "percentRate", "effectiveRate", "percent"),
    )


def parse_bls_series(
    payload: Any,
    *,
    asof: str,
    fetched_at: str,
    source_url: str | None,
    raw_sha256: str | None,
    license_tier: str | None = None,
    status: str = "ok",
    stale_reason: str | None = None,
) -> dict[str, Any]:
    """Normalize BLS ``Results.series[].data[]`` observations."""

    meta = source_meta(
        "bls",
        source_url=source_url,
        asof=asof,
        fetched_at=fetched_at,
        status=status,
        stale_reason=stale_reason,
        raw_sha256=raw_sha256,
        license_tier=license_tier,
    )
    series_rows: list[Mapping[str, Any]] | None = None
    if isinstance(payload, Mapping):
        results = payload.get("Results") or payload.get("results")
        if isinstance(results, Mapping):
            series = results.get("series")
            if isinstance(series, Sequence) and series and isinstance(series[0], Mapping):
                first_data = series[0].get("data")
                if isinstance(first_data, Sequence):
                    series_rows = [dict(row) for row in first_data if isinstance(row, Mapping)]
    if series_rows is None:
        return _section(meta, None, section="bls_series")
    rows = [
        {
            "period": _first(row, ("period", "date", "year")),
            "value": _first(row, ("value", "value_numeric")),
            "footnote": row.get("footnote"),
        }
        for row in series_rows
    ]
    return _section(meta, rows, section="bls_series")


def parse_eia_series(
    payload: Any,
    *,
    asof: str,
    fetched_at: str,
    source_url: str | None,
    raw_sha256: str | None,
    license_tier: str | None = None,
    status: str = "ok",
    stale_reason: str | None = None,
) -> dict[str, Any]:
    """Normalize EIA API ``response.data`` observations."""

    meta = source_meta(
        "eia",
        source_url=source_url,
        asof=asof,
        fetched_at=fetched_at,
        status=status,
        stale_reason=stale_reason,
        raw_sha256=raw_sha256,
        license_tier=license_tier,
    )
    data = payload.get("response") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        data = payload
    raw_rows = _rows(data, "data", "results")
    if raw_rows is None:
        return _section(meta, None, section="eia_series")
    rows = [
        {
            "period": _first(row, ("period", "date", "timestamp")),
            "value": _first(row, ("value", "price", "observations")),
        }
        for row in raw_rows
    ]
    return _section(meta, rows, section="eia_series")


def source_unavailable_market(
    market_id: str,
    *,
    asof: str,
    fetched_at: str,
    reason: str,
    source_url: str | None = None,
    license_tier: str | None = None,
    raw_sha256: str | None = None,
) -> dict[str, Any]:
    """Represent an unconnected market series such as VIX, DXY or gold."""

    meta = source_meta(
        market_id,
        source_url=source_url,
        asof=asof,
        fetched_at=fetched_at,
        status="source_unavailable",
        stale_reason=reason,
        raw_sha256=raw_sha256,
        license_tier=license_tier,
    )
    return {
        "market": market_id,
        "source": meta["source"],
        "source_url": meta["source_url"],
        "asof": meta["asof"],
        "fetched_at": meta["fetched_at"],
        "status": meta["status"],
        "stale_reason": meta["stale_reason"],
        "raw_sha256": meta["raw_sha256"],
        "license_tier": meta["license_tier"],
        "evidence": EVIDENCE,
        "value": None,
    }


def build_probability_snapshot(
    *,
    venue: str,
    market_id: str,
    question: str,
    outcome: str,
    implied_probability: float | None,
    asof: str,
    fetched_at: str,
    source_url: str | None,
    liquidity: Mapping[str, Any] | None = None,
    end_at: str | None = None,
    status: str = "ok",
    stale_reason: str | None = None,
    raw_sha256: str | None = None,
    license_tier: str | None = None,
) -> dict[str, Any]:
    """Build one explicitly non-official prediction-market observation."""

    if implied_probability is not None:
        if isinstance(implied_probability, bool) or not isinstance(implied_probability, (int, float)):
            raise TypeError("implied_probability must be a number or None")
        if not 0 <= float(implied_probability) <= 1:
            raise ValueError("implied_probability must be between 0 and 1")
    meta = source_meta(
        venue,
        source_url=source_url,
        asof=asof,
        fetched_at=fetched_at,
        status=status,
        stale_reason=stale_reason,
        raw_sha256=raw_sha256,
        license_tier=license_tier,
    )
    return {
        "schema_version": PROBABILITY_SCHEMA_VERSION,
        "venue": venue,
        "market_id": market_id,
        "question": question,
        "outcome": outcome,
        "probability_type": "forecast_market_implied_probability",
        "probability_unit": "decimal_0_1",
        "implied_probability": None if implied_probability is None else float(implied_probability),
        "liquidity": deepcopy(dict(liquidity)) if liquidity is not None else None,
        "asof": meta["asof"],
        "fetched_at": meta["fetched_at"],
        "end_at": end_at,
        "status": meta["status"],
        "stale_reason": meta["stale_reason"],
        "source": meta["source"],
        "source_url": meta["source_url"],
        "raw_sha256": meta["raw_sha256"],
        "license_tier": meta["license_tier"],
        "official_fedwatch": False,
        "evidence": EVIDENCE,
    }


def build_probability_context(
    items: Iterable[Mapping[str, Any]] | None,
    *,
    asof: str,
    generated_at: str,
    stale_reason: str | None = None,
) -> dict[str, Any]:
    """Wrap Polymarket/Kalshi items as a standalone P3 snapshot."""

    _iso_date(asof)
    _iso_timestamp(generated_at, "generated_at")
    values = [deepcopy(dict(item)) for item in (items or [])]
    statuses = {str(item.get("status") or "ok") for item in values}
    status = "not_requested" if not values else "ok"
    if statuses:
        if statuses <= {"stale"}:
            status = "stale"
        elif statuses <= {"source_unavailable"}:
            status = "source_unavailable"
        elif statuses <= {"schema_changed"}:
            status = "schema_changed"
        elif statuses & {"source_unavailable", "schema_changed", "stale", "partial", "not_available"}:
            status = "partial"
    snapshot = {
        "schema_version": PROBABILITY_SCHEMA_VERSION,
        "kind": "macro_probability",
        "asof": asof,
        "generated_at": generated_at,
        "status": status,
        "stale_reason": stale_reason,
        "evidence": EVIDENCE,
        "official_fedwatch": False,
        "items": values,
    }
    snapshot["snapshot_sha256"] = json_sha256(snapshot)
    return snapshot


def _aggregate_status(sources: Mapping[str, Mapping[str, Any]]) -> str:
    if not sources:
        return "not_requested"
    statuses = {str(meta.get("status") or "not_available") for meta in sources.values()}
    if statuses <= {"ok"}:
        return "ok"
    if "ok" in statuses:
        return "partial"
    if "stale" in statuses:
        return "stale"
    if "source_unavailable" in statuses:
        return "source_unavailable"
    if "schema_changed" in statuses:
        return "schema_changed"
    return "partial"


def build_global_context(
    *,
    asof: str,
    generated_at: str,
    sources: Mapping[str, Mapping[str, Any]] | None = None,
    rates: Mapping[str, Any] | None = None,
    markets: Mapping[str, Any] | None = None,
    events: Iterable[Mapping[str, Any]] | None = None,
    news: Iterable[Mapping[str, Any]] | None = None,
    probability: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    stale_reason: str | None = None,
) -> dict[str, Any]:
    """Build a versioned P2 context without fetching or inventing data."""

    _iso_date(asof)
    _iso_timestamp(generated_at, "generated_at")
    normalized_sources: dict[str, dict[str, Any]] = {}
    for source_id, raw in (sources or {}).items():
        if not isinstance(raw, Mapping):
            raise TypeError(f"source metadata for {source_id} must be an object")
        meta = dict(raw)
        meta.setdefault("source", source_id)
        meta.setdefault("source_id", source_id)
        meta["asof"] = _iso_date(meta.get("asof", asof), f"sources.{source_id}.asof")
        if meta.get("fetched_at") is None:
            meta["fetched_at"] = generated_at
        meta["fetched_at"] = _iso_timestamp(meta["fetched_at"], f"sources.{source_id}.fetched_at")
        meta["status"] = _status(meta.get("status"), default="not_available")
        meta.setdefault("source_url", None)
        meta.setdefault("stale_reason", None)
        meta.setdefault("raw_sha256", None)
        meta.setdefault("license_tier", None)
        normalized_sources[str(source_id)] = meta
    context = {
        "schema_version": GLOBAL_SCHEMA_VERSION,
        "kind": "global_context",
        "asof": asof,
        "generated_at": generated_at,
        "run_id": run_id,
        "status": _aggregate_status(normalized_sources),
        "stale_reason": stale_reason,
        "evidence": EVIDENCE,
        "sources": normalized_sources,
        "rates": deepcopy(dict(rates or {})),
        "markets": deepcopy(dict(markets or {})),
        "events": [deepcopy(dict(item)) for item in (events or [])],
        "news": [deepcopy(dict(item)) for item in (news or [])],
        "probability": deepcopy(dict(probability)) if probability is not None else build_probability_context(None, asof=asof, generated_at=generated_at),
    }
    context["snapshot_sha256"] = json_sha256(context)
    return context


__all__ = [
    "EVIDENCE",
    "GLOBAL_SCHEMA_VERSION",
    "PROBABILITY_SCHEMA_VERSION",
    "build_global_context",
    "build_probability_context",
    "build_probability_snapshot",
    "json_sha256",
    "parse_bls_series",
    "parse_eia_series",
    "parse_ny_fed_observations",
    "parse_treasury_curve",
    "source_meta",
    "source_unavailable_market",
]
