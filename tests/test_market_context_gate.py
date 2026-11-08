import json

from scripts.market_context_gate import inspect


def _snapshot(asof, *, mode="live", status="partial"):
    return {
        "asof": asof,
        "run_mode": mode,
        "status": status,
        "sources": {"limit": {"raw_sha256": "a" * 64}},
        "calendar": {
            "calendar_status": "provided",
            "asof_status": "exchange_verified",
            "prior_status": "exchange_verified" if asof != "2026-11-02" else "not_available",
            "calendar_source_sha256": "c" * 64,
            "calendar_version": "test-v1",
            "prior_asof": "2026-11-02" if asof != "2026-11-02" else None,
        },
        "limit_pools": {
            "reasons": {"status": "fresh"},
            "topics": {"status": "fresh"},
            "prior_day": {"status": "fresh"},
        },
    }


def test_gate_requires_two_distinct_real_dates(tmp_path):
    (tmp_path / "market_context_2026-11-02.json").write_text(json.dumps(_snapshot("2026-11-02")), encoding="utf-8")
    result = inspect(tmp_path)
    assert result["real_snapshot_count"] == 1
    assert result["ready_for_frontend_polling"] is False

    (tmp_path / "market_context_2026-11-03.json").write_text(json.dumps(_snapshot("2026-11-03")), encoding="utf-8")
    result = inspect(tmp_path)
    assert result["real_snapshot_count"] == 2
    assert result["ready_for_frontend_polling"] is True


def test_gate_excludes_fixture_or_unverified_snapshots(tmp_path):
    (tmp_path / "market_context_2026-11-02.json").write_text(json.dumps(_snapshot("2026-11-02", mode="fixture")), encoding="utf-8")
    (tmp_path / "market_context_2026-11-03.json").write_text(json.dumps(_snapshot("2026-11-03", status="not_available")), encoding="utf-8")
    assert inspect(tmp_path)["real_snapshot_count"] == 0


def test_gate_rejects_real_snapshots_without_exchange_calendar(tmp_path):
    first = _snapshot("2026-11-02")
    second = _snapshot("2026-11-03")
    first.pop("calendar")
    second.pop("calendar")
    (tmp_path / "market_context_2026-11-02.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "market_context_2026-11-03.json").write_text(json.dumps(second), encoding="utf-8")
    result = inspect(tmp_path)
    assert result["real_snapshot_count"] == 0
    assert result["ready_for_frontend_polling"] is False
