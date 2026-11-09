"""Provider-neutral refresh and staleness rules for P2/P3 snapshots.

This module contains no scheduler, network client, or cloud SDK.  It gives a
Tencent Cloud task, a Cloudflare Worker, or a local runner the same deterministic
decision about when a snapshot is due and when the previous one becomes stale.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

P2_DAILY_TTL = timedelta(hours=36)
EVENT_CALENDAR_TTL = timedelta(hours=24)
P3_REFRESH_INTERVAL = timedelta(hours=6)


def _timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def refresh_due(
    last_success_at: str | None,
    *,
    now: str,
    interval: timedelta = P3_REFRESH_INTERVAL,
) -> bool:
    """Return whether a new snapshot may be queued.

    A missing success timestamp is due immediately.  The comparison is
    inclusive at the interval boundary and uses only successful fetch time;
    failed attempts must not postpone the next retry.
    """

    if interval <= timedelta(0):
        raise ValueError("interval must be positive")
    current = _timestamp(now, "now")
    if last_success_at is None:
        return True
    return current >= _timestamp(last_success_at, "last_success_at") + interval


def next_refresh_at(
    last_success_at: str | None,
    *,
    interval: timedelta = P3_REFRESH_INTERVAL,
) -> str | None:
    """Return the next due time, or ``None`` when no successful fetch exists."""

    if interval <= timedelta(0):
        raise ValueError("interval must be positive")
    if last_success_at is None:
        return None
    return (_timestamp(last_success_at, "last_success_at") + interval).isoformat().replace("+00:00", "Z")


def stale_reason(
    fetched_at: str | None,
    *,
    now: str,
    ttl: timedelta,
) -> str | None:
    """Return a stable stale reason without mutating or inventing data."""

    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    current = _timestamp(now, "now")
    if fetched_at is None:
        return "source_unavailable"
    fetched = _timestamp(fetched_at, "fetched_at")
    if fetched > current:
        return "clock_skew"
    if current - fetched > ttl:
        return "ttl_expired"
    return None


def refresh_policy() -> dict[str, Any]:
    """Describe the default schedule for display and audit manifests."""

    return {
        "p2_daily_ttl_hours": P2_DAILY_TTL.total_seconds() / 3600,
        "event_calendar_ttl_hours": EVENT_CALENDAR_TTL.total_seconds() / 3600,
        "p3_refresh_interval_hours": P3_REFRESH_INTERVAL.total_seconds() / 3600,
        "failed_attempts_advance_success_clock": False,
        "evidence": "descriptive",
    }


__all__ = [
    "EVENT_CALENDAR_TTL",
    "P2_DAILY_TTL",
    "P3_REFRESH_INTERVAL",
    "next_refresh_at",
    "refresh_due",
    "refresh_policy",
    "stale_reason",
]
