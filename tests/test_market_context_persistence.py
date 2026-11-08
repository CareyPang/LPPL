import hashlib
import json

import pytest

from research.data.market_context_persistence import (
    PersistenceError,
    append_seed_bundle,
    build_seed_bundle,
)


def _calendar(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps({"dates": ["2026-11-05", "2026-11-06"], "version": "exchange-2026-v1", "source_url": "https://calendar.example/v1", "source_sha256": "a" * 64, "verification_status": "exchange_verified"}), encoding="utf-8")
    return path


def _snapshot(path, asof, *, prior=None, progression="not_available"):
    value = {"schema_version": "market-context.v1", "asof": asof, "run_mode": "live", "status": "partial", "evidence": "descriptive", "calendar": {"calendar_status": "provided", "asof_status": "exchange_verified", "prior_status": "exchange_verified" if prior else "not_available", "calendar_source_sha256": "a" * 64, "calendar_version": "exchange-2026-v1", "prior_asof": prior}, "sources": {"pool": {"raw_sha256": "b" * 64}}, "history": {"progression": {"status": progression, "prior_asof": prior, "rows": [{"rate": 0.5}] if progression == "fresh" else []}}}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    value["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_build_bundle_requires_verified_adjacent_snapshots(tmp_path):
    calendar = _calendar(tmp_path)
    first, second = tmp_path / "market_context_2026-11-05.json", tmp_path / "market_context_2026-11-06.json"
    _snapshot(first, "2026-11-05")
    _snapshot(second, "2026-11-06", prior="2026-11-05", progression="fresh")
    bundle = build_seed_bundle([first, second], calendar)
    assert bundle["append_only"] is True
    assert [item["asof"] for item in bundle["snapshots"]] == ["2026-11-05", "2026-11-06"]
    assert len(bundle["bundle_sha256"]) == 64


def test_unverified_calendar_is_rejected(tmp_path):
    calendar = _calendar(tmp_path)
    value = json.loads(calendar.read_text(encoding="utf-8"))
    value.pop("verification_status")
    calendar.write_text(json.dumps(value), encoding="utf-8")
    first = tmp_path / "market_context_2026-11-05.json"
    _snapshot(first, "2026-11-05")
    with pytest.raises(PersistenceError, match="verification_status"):
        build_seed_bundle([first, first], calendar)


def test_append_bundle_rejects_changed_sealed_date(tmp_path):
    calendar = _calendar(tmp_path)
    first, second = tmp_path / "market_context_2026-11-05.json", tmp_path / "market_context_2026-11-06.json"
    _snapshot(first, "2026-11-05")
    _snapshot(second, "2026-11-06", prior="2026-11-05", progression="fresh")
    bundle = build_seed_bundle([first, second], calendar)
    changed = {**bundle, "snapshots": [dict(item) for item in bundle["snapshots"]]}
    changed["snapshots"][0]["snapshot_sha256"] = "c" * 64
    with pytest.raises(PersistenceError, match="sealed snapshot changed"):
        append_seed_bundle(bundle, changed)
