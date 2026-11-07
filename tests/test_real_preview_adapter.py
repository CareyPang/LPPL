"""Safety and interpretation contracts of isolated real current analysis."""
import json

import pandas as pd
import pytest

from research.data.preview_calendar import sessions_2026
from research.lppls.window_clusters import prepare
from research.pipeline.real_preview_adapter import (
    _calendar,
    _window,
    canonical,
    digest,
    separate_price_bases,
    validate_job,
)


def test_explicit_asset_namespace_avoids_index_stock_collision():
    assert canonical("sh000001") == "sh000001"
    assert canonical("600519") == "sh600519"
    with pytest.raises(ValueError):
        canonical("000001")
    with pytest.raises(ValueError):
        canonical("sz000001")


def test_window_never_crops_member_extremes_to_hit_ten_day_target():
    cluster = {"lo": 5.2, "hi": 15.1, "id": "test", "supported_scales": ["short", "mid"],
               "members": [30, 65, 70], "n_members": 3, "mass": .25}
    row = _window(cluster, _calendar("2026-11-06"), True)
    assert row["lead_sessions"] == 4
    assert row["width_sessions"] == 12
    assert row["ahead_min"] == 5.2
    assert row["ahead_max"] == 15.1
    assert row["calendar_verified"]
    assert row["tier"] == "early_observation"


def test_future_cycle_gate_does_not_admit_past_critical_time():
    frame = pd.DataFrame([{"date": "2026-11-06", "n": 30, "tc": 28., "m": .5, "w": 8., "B": -1.}])
    row = prepare(frame).iloc[0]
    assert not row.qualified
    assert row.osc_cycles_status != "ok"


def test_verified_calendar_stops_at_2026_and_skips_exchange_holidays():
    calendar = _calendar("2026-11-06")
    assert calendar["status"] == "exchange_verified"
    assert calendar["dates"][:2] == ["2026-11-06", "2026-11-09"]
    assert calendar["dates"][-1] == "2026-12-31"
    sessions = sessions_2026()
    assert "2026-02-23" not in sessions
    assert "2026-02-24" in sessions
    assert "2026-10-10" not in sessions  # makeup workday is not an exchange session
    assert _calendar("2027-01-04")["status"] == "weekday_estimate"


def test_window_crossing_verified_calendar_boundary_does_not_inherit_verified_status():
    cluster = {"lo": 25.8, "hi": 33.8, "id": "test", "supported_scales": ["medium"],
               "members": [130, 170, 190], "n_members": 3, "mass": .1}
    row = _window(cluster, _calendar("2026-12-01"), False)
    assert row["calendar"]["status"] == "weekday_estimate"
    assert not row["calendar_verified"]
    assert row["width_sessions"] == 10
    assert row["lead_sessions"] == 24


def test_job_identity_cannot_escape_output_directory_or_claim_future_request():
    with pytest.raises(ValueError):
        validate_job({"job_id": "../outside", "requested_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(ValueError):
        validate_job({"job_id": "6686cb3a-2750-4d2c-b4d1-32f85b1b488c", "requested_at": "2099-01-01T00:00:00Z"})


def test_display_prices_become_raw_while_fitted_hfq_closes_are_unchanged(tmp_path):
    body = json.dumps({"data": {"sh600519": {"day": [["2026-11-06", "10", "11", "12", "9", "20"]]}}}).encode()
    directory = tmp_path / "sh600519" / "raw"
    directory.mkdir(parents=True)
    (directory / "quote.raw").write_bytes(body)
    old = {"code": "sh600519", "adjustment": "hfq",
           "price": [{"date": "2026-11-06", "open": 100., "close": 110., "high": 120., "low": 90., "volume": 20.}],
           "provenance": [{"url": "https://example/fqkline", "file": "quote.raw", "sha256": digest(body)}]}
    value = separate_price_bases(old, tmp_path)
    assert value["price"][0]["close"] == 11.
    assert value["model_price"][0]["close"] == 110.
    assert old["price"][0]["close"] == 110.
    assert value["adjustment"] == "none"
    assert value["model_adjustment"] == "hfq"
    (directory / "quote.raw").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA256"):
        separate_price_bases(old, tmp_path)
