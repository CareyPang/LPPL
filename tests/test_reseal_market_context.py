import hashlib
import json

from scripts.reseal_market_context import reseal


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _snapshot(asof, progression, prior=None):
    value = {
        "schema_version": "market-context.v1",
        "asof": asof,
        "run_mode": "live",
        "status": "partial",
        "evidence": "descriptive",
        "sources": {"p1": {"raw_sha256": "a" * 64}},
        "limit_pools": {
            "reasons": {"status": "fresh"},
            "topics": {"status": "fresh"},
            "prior_day": {"status": "fresh"},
        },
        "history": {"progression": {"status": progression, "prior_asof": prior}},
    }
    value["snapshot_sha256"] = _digest(value)
    return value


def test_reseal_preserves_source_and_derives_calendar_prior(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    first = _snapshot("2026-11-05", "not_available")
    second = _snapshot("2026-11-06", "fresh", "2026-11-05")
    (source / "market_context_2026-11-05.json").write_text(json.dumps(first), encoding="utf-8")
    (source / "market_context_2026-11-06.json").write_text(json.dumps(second), encoding="utf-8")
    source_bytes = (source / "market_context_2026-11-05.json").read_bytes()
    calendar = tmp_path / "calendar.json"
    calendar.write_text(json.dumps({
        "dates": ["2026-11-04", "2026-11-05", "2026-11-06"],
        "version": "test-v1",
        "source_url": "https://example.test/calendar",
        "source_sha256": "b" * 64,
        "verification_status": "exchange_verified",
    }), encoding="utf-8")
    output = tmp_path / "out"

    provenance = reseal(source, calendar, output)

    assert (source / "market_context_2026-11-05.json").read_bytes() == source_bytes
    sealed_first = json.loads((output / "market-context" / "market_context_2026-11-05.json").read_text(encoding="utf-8"))
    sealed_second = json.loads((output / "market-context" / "market_context_2026-11-06.json").read_text(encoding="utf-8"))
    assert sealed_first["calendar"]["prior_asof"] == "2026-11-04"
    assert sealed_first["history"]["progression"]["status"] == "not_available"
    assert sealed_second["calendar"]["prior_asof"] == "2026-11-05"
    assert sealed_second["calendar"]["prior_status"] == "exchange_verified"
    assert provenance["calendar"]["verification_status"] == "exchange_verified"
    assert (output / "market-context" / "market_context_manifest.json").exists()
