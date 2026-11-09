from __future__ import annotations

from datetime import timedelta

import pytest

from research.data.global_context_schedule import (
    P3_REFRESH_INTERVAL,
    next_refresh_at,
    refresh_due,
    refresh_policy,
    stale_reason,
)


def test_p3_refresh_is_due_at_six_hour_boundary() -> None:
    last = "2026-11-08T00:00:00Z"
    assert refresh_due(last, now="2026-11-08T05:59:59Z") is False
    assert refresh_due(last, now="2026-11-08T06:00:00Z") is True
    assert next_refresh_at(last) == "2026-11-08T06:00:00Z"
    assert P3_REFRESH_INTERVAL == timedelta(hours=6)


def test_missing_success_is_immediately_due_but_has_no_next_time() -> None:
    assert refresh_due(None, now="2026-11-08T00:00:00+08:00") is True
    assert next_refresh_at(None) is None


def test_failed_attempts_do_not_advance_success_clock() -> None:
    assert refresh_due("2026-11-08T00:00:00Z", now="2026-11-08T05:00:00Z") is False


def test_stale_reasons_distinguish_missing_future_and_expired() -> None:
    assert stale_reason(None, now="2026-11-08T06:00:00Z", ttl=timedelta(hours=6)) == "source_unavailable"
    assert stale_reason("2026-11-08T07:00:00Z", now="2026-11-08T06:00:00Z", ttl=timedelta(hours=6)) == "clock_skew"
    assert stale_reason("2026-11-08T00:00:00Z", now="2026-11-08T06:00:01Z", ttl=timedelta(hours=6)) == "ttl_expired"
    assert stale_reason("2026-11-08T00:00:00Z", now="2026-11-08T05:59:59Z", ttl=timedelta(hours=6)) is None


def test_policy_is_explicit_and_non_predictive() -> None:
    policy = refresh_policy()
    assert policy["p3_refresh_interval_hours"] == 6
    assert policy["failed_attempts_advance_success_clock"] is False
    assert policy["evidence"] == "descriptive"


@pytest.mark.parametrize("value", ["2026-11-08T00:00:00", "not-a-time"])
def test_timestamps_require_timezone_and_valid_iso(value: str) -> None:
    with pytest.raises(ValueError):
        refresh_due(value, now="2026-11-08T06:00:00Z")
