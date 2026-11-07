"""Versioned descriptive market-context snapshots.

This wrapper deliberately keeps the existing ``market_latest.json`` contract
untouched.  It adds refresh provenance and explicit missing-data states for the
P1 review modules.  Nothing in this module is an LPPLS feature or signal.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

SCHEMA_VERSION = "market-context.v1"
MARKET = "CN_A_SHARE"
EVIDENCE = "descriptive"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _json_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _source_status(meta: dict[str, Any]) -> str:
    if meta.get("ok") is True:
        return "fresh"
    if meta.get("ok") is False:
        return "error"
    return "unavailable"


def _source_meta(source_id: str, meta: Any, *, source_url: str | None = None) -> dict[str, Any]:
    raw = meta if isinstance(meta, dict) else {}
    status = _source_status(raw)
    return {
        "source_id": source_id,
        "source_url": source_url,
        "url_host": raw.get("url_host"),
        "fetched_at": raw.get("fetched_at"),
        "status": status,
        "ok": raw.get("ok"),
        "stale_reason": raw.get("error") if status != "fresh" else None,
        "raw_sha256": raw.get("raw_sha256"),
        "license_tier": raw.get("license_tier"),
        "error": raw.get("error"),
    }


def _missing(asof: str, reason: str) -> dict[str, Any]:
    return {
        "status": "not_available",
        "asof": asof,
        "window": None,
        "rows": [],
        "stale_reason": reason,
        "evidence": EVIDENCE,
    }


def build_snapshot(
    payload: dict[str, Any],
    *,
    source_url: str | None = None,
    requested_at: str | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Wrap an existing market snapshot without inventing missing fields."""

    if not isinstance(payload, dict):
        raise TypeError("market payload must be an object")
    asof = payload.get("asof")
    if not _valid_date(asof):
        raise ValueError("market payload must contain an ISO asof date")
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    sources = {
        key: _source_meta(key, value, source_url=source_url) for key, value in raw_sources.items()
    }
    source_errors = [value for value in sources.values() if value["status"] != "fresh"]
    status = "partial" if source_errors else "fresh"
    raw_limit = payload.get("limit_pools") if isinstance(payload.get("limit_pools"), dict) else {}
    limit = {**raw_limit}
    limit.setdefault("reasons", _missing(asof, "source did not provide limit-up reason rows"))
    limit.setdefault("topics", _missing(asof, "source did not provide topic labels"))
    progression = _missing(asof, "prior trading-day limit-pool pair is not available")
    history = {"progression": progression}
    context = {
        "schema_version": SCHEMA_VERSION,
        "kind": "market_context",
        "market": MARKET,
        "snapshot_kind": "eod",
        "asof": asof,
        "generated_at": payload.get("generated_at"),
        "requested_at": requested_at or _now(),
        "status": status,
        "stale_reason": "one or more sources failed" if source_errors else None,
        "last_good_asof": asof,
        "evidence": EVIDENCE,
        "source": {
            "source_id": "market_latest_wrapper",
            "source_url": source_url,
            "fetched_at": fetched_at or payload.get("generated_at"),
            "status": status,
            "stale_reason": "one or more sources failed" if source_errors else None,
            "license_tier": None,
        },
        "sources": sources,
        "board_flow": payload.get("board_flow") or {},
        "limit_pools": limit,
        "history": history,
        "northbound": payload.get("northbound") or {},
        "margin": payload.get("margin") or {},
        "valuation": payload.get("valuation") or {},
    }
    context["snapshot_sha256"] = _json_sha256(context)
    return context


def validate_requested_date(value: str) -> str:
    """Validate a replay key without claiming a holiday calendar."""

    if value == "latest":
        return value
    if not _valid_date(value):
        raise ValueError("date must be latest or YYYY-MM-DD")
    if date.fromisoformat(value).weekday() >= 5:
        raise ValueError("date must be a weekday; holiday validation requires a source calendar")
    return value
