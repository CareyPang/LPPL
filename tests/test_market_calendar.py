import json

import pytest

from research.data.market_calendar import load_calendar, resolve_sessions


def test_load_calendar_accepts_metadata_and_sorts_dates(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps({"version": "sse-2026", "dates": ["2026-01-05", "2026-01-02"]}), encoding="utf-8")
    loaded = load_calendar(path)
    assert loaded["dates"] == ["2026-01-02", "2026-01-05"]
    assert loaded["version"] == "sse-2026"


def test_resolve_sessions_uses_latest_closed_and_prior_session():
    calendar = {"status": "provided", "version": "v1", "dates": ["2026-01-02", "2026-01-05", "2026-01-06"]}
    result = resolve_sessions(asof=None, prior_asof=None, calendar=calendar, today="2026-01-06")
    assert result["asof"] == "2026-01-06"
    assert result["prior_asof"] == "2026-01-05"
    assert result["asof_status"] == "exchange_verified"


def test_missing_calendar_does_not_claim_exchange_verification():
    result = resolve_sessions(asof=None, prior_asof=None, calendar={"status": "not_provided", "dates": []}, today="2026-01-05")
    assert result["asof"] == "2026-01-05"
    assert result["asof_status"] == "weekday_estimate"
    assert result["prior_asof"] is None
    assert result["prior_status"] == "not_available"


def test_explicit_date_must_exist_in_supplied_calendar():
    calendar = {"status": "provided", "dates": ["2026-01-05"]}
    with pytest.raises(ValueError, match="not present"):
        resolve_sessions(asof="2026-01-06", prior_asof=None, calendar=calendar)
