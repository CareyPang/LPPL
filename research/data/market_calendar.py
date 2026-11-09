"""Small, provider-neutral trading-calendar resolver for EOD snapshots.

The resolver never invents exchange holidays.  A checked-in or downloaded
calendar must be supplied when an exact exchange session is required; without
one, an explicit date is retained but marked unverified and an implicit date
uses only a weekday estimate.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def _iso(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("calendar dates must be strings")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"calendar date must be YYYY-MM-DD: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"calendar date must be canonical YYYY-MM-DD: {value!r}")
    return value


def load_calendar(path: str | Path | None) -> dict[str, Any]:
    """Load and validate a JSON calendar artifact.

    Accepted shapes are ``["YYYY-MM-DD", ...]`` and
    ``{"dates": [...], "version": ..., "source_url": ...}``.
    """

    if path is None:
        return {"status": "not_provided", "dates": []}
    calendar_path = Path(path)
    value = json.loads(calendar_path.read_text(encoding="utf-8"))
    if isinstance(value, list):
        raw_dates = value
        meta: dict[str, Any] = {}
    elif isinstance(value, dict):
        raw_dates = value.get("dates")
        meta = {key: value[key] for key in ("version", "source_url", "source_sha256", "coverage_start", "coverage_end") if key in value}
    else:
        raise ValueError("trading calendar must be a JSON list or object")
    if not isinstance(raw_dates, list) or not raw_dates:
        raise ValueError("trading calendar must contain a non-empty dates list")
    dates = sorted({_iso(item) for item in raw_dates})
    if any(date.fromisoformat(right) <= date.fromisoformat(left) for left, right in zip(dates, dates[1:], strict=False)):
        raise ValueError("trading calendar dates must be strictly increasing")
    return {"status": "provided", "dates": dates, **meta}


def resolve_sessions(
    *,
    asof: str | None,
    prior_asof: str | None,
    calendar: dict[str, Any],
    today: str | None = None,
) -> dict[str, Any]:
    """Resolve an EOD date and its prior session without holiday invention."""

    dates = list(calendar.get("dates") or [])
    today_key = _iso(today) if today is not None else date.today().isoformat()
    if asof is not None:
        resolved_asof = _iso(asof)
        if dates and resolved_asof not in dates:
            raise ValueError(f"asof {resolved_asof} is not present in the supplied trading calendar")
        asof_status = "exchange_verified" if dates else "explicit_unverified"
    elif dates:
        eligible = [item for item in dates if item <= today_key]
        if not eligible:
            raise ValueError("trading calendar contains no closed session on or before today")
        resolved_asof = eligible[-1]
        asof_status = "exchange_verified"
    else:
        resolved_asof = today_key
        asof_status = "weekday_estimate" if date.fromisoformat(today_key).weekday() < 5 else "not_available"

    if prior_asof is not None:
        resolved_prior = _iso(prior_asof)
        if dates and resolved_prior not in dates:
            raise ValueError(f"prior_asof {resolved_prior} is not present in the supplied trading calendar")
        prior_status = "exchange_verified" if dates else "explicit_unverified"
    elif dates and resolved_asof in dates:
        index = dates.index(resolved_asof)
        resolved_prior = dates[index - 1] if index else None
        prior_status = "exchange_verified" if resolved_prior else "not_available"
    else:
        resolved_prior = None
        prior_status = "not_available"

    return {
        "asof": resolved_asof,
        "prior_asof": resolved_prior,
        "asof_status": asof_status,
        "prior_status": prior_status,
        "calendar_status": calendar.get("status", "not_provided"),
        "calendar_version": calendar.get("version"),
        "calendar_source_url": calendar.get("source_url"),
        "calendar_source_sha256": calendar.get("source_sha256"),
    }


__all__ = ["load_calendar", "resolve_sessions"]
