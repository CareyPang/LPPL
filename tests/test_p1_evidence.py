"""Synthetic evidence only: these tests are not real market snapshots."""

import hashlib
import json
from copy import deepcopy

import pytest

from research.data import p1_evidence as evidence
from research.data.p1_source_catalog import get_source
from scripts.import_p1_evidence import main

SOURCE = "eastmoney_fund_flow_history"
DAY = "2026-11-06"
FETCHED = "2026-11-06T10:30:00Z"
ARCHIVED = "2026-11-09T02:00:00+00:00"


@pytest.fixture(autouse=True)
def frozen_archive_clock(monkeypatch):
    monkeypatch.setattr(evidence, "_now", lambda: ARCHIVED)


def raw_bytes(code="600519", value="10"):
    return json.dumps({"rc": 0, "data": {"code": code, "klines": [f"2026-11-06,{value},2,3,4,5,6"]}}, ensure_ascii=False).encode()


def save(tmp_path, *, raw=None, **kwargs):
    values = dict(source_id=SOURCE, asof=DAY, fetched_at=FETCHED, source_url=get_source(SOURCE)["source_urls"][0], subject="sh600519", origin="fixture")
    values.update(kwargs)
    return evidence.archive_response(tmp_path, raw if raw is not None else raw_bytes(), **values)


def base():
    return {"asof": DAY, "generated_at": FETCHED, "sources": {}, "limit_pools": {"zt": 5, "zb": 1, "dt": 0}, "history": {"progression": {"status": "not_available", "rows": []}}}


def test_raw_bytes_and_local_receipt_are_sealed_separately(tmp_path):
    raw = raw_bytes() + b"  \n"
    path = save(tmp_path, raw=raw)
    record = evidence.load_record(path)
    assert record["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (tmp_path / record["raw_ref"]).read_bytes() == raw
    assert record["available_at"] == ARCHIVED
    assert record["fetched_at"] != record["available_at"]
    assert record["fetched_at_evidence"] == "caller_declared"
    assert record["pit_status"] == "NOT_ESTABLISHED"
    assert record["public_first_published_at"] is None
    assert record["publication_eligible"] is False
    assert record["origin"] == "fixture"


def test_revisions_are_append_only_and_identical_inputs_are_idempotent(tmp_path, monkeypatch):
    first = save(tmp_path)
    first_bytes = first.read_bytes()
    assert save(tmp_path) == first
    monkeypatch.setattr(evidence, "_now", lambda: "2026-11-09T03:00:00+00:00")
    assert save(tmp_path) == first
    assert evidence.load_record(first)["available_at"] == ARCHIVED
    second = save(tmp_path, raw=raw_bytes(value="20"))
    assert second != first
    assert first.read_bytes() == first_bytes
    assert len(list((tmp_path / "records").glob("*.json"))) == 2


def test_raw_corruption_is_detected_before_building_context(tmp_path):
    path = save(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    (tmp_path / record["raw_ref"]).write_bytes(raw_bytes(value="999"))
    with pytest.raises(ValueError, match="raw response hash"):
        evidence.build_research_context(base(), [path])


def test_record_corruption_is_detected(tmp_path):
    path = save(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["section"]["rows"] = []
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="record hash"):
        evidence.load_record(path)


@pytest.mark.parametrize("raw", [b'{"data": {}, "data": {}}', b'{"v":NaN}', b'{"v":Infinity}', b'{"unused":1e9999}', b'[]', b''])
def test_noncanonical_or_ambiguous_payload_is_rejected_without_writes(tmp_path, raw):
    with pytest.raises(ValueError):
        save(tmp_path, raw=raw)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("kwargs", [
    {"source_url": "https://unregistered.example/data"},
    {"source_url": "https://push2his.eastmoney.com/incorrect"},
    {"source_url": "https://user:secret@push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"},
    {"fetched_at": "2026-11-06T10:30:00"},
    {"fetched_at": "2026-11-10T10:30:00Z"},
    {"asof": "2026-11-07"},
    {"origin": "live"},
])
def test_unverifiable_metadata_is_rejected_before_archive(tmp_path, kwargs):
    with pytest.raises(ValueError):
        save(tmp_path, **kwargs)
    assert not list(tmp_path.rglob("*.json"))


def test_unlock_schedule_cannot_be_backdated(tmp_path):
    source = "eastmoney_lockup_expiry"
    with pytest.raises(ValueError, match="retrieval-day snapshot"):
        save(tmp_path, source_id=source, source_url=get_source(source)["source_urls"][0], asof="2026-11-05")


@pytest.mark.parametrize("query", ["secid=0.600519", "klt=1", "fields2=f51,f57,f52,f53,f54,f55,f56", "secid=1.600519&secid=0.000001"])
def test_request_identity_and_layout_conflicts_rejected(tmp_path, query):
    with pytest.raises(ValueError):
        save(tmp_path, source_url=get_source(SOURCE)["source_urls"][0] + "?" + query)
    assert not list(tmp_path.rglob("*.json"))


def test_missing_request_query_does_not_certify_layout(tmp_path):
    record = evidence.load_record(save(tmp_path))
    assert record["section"]["status"] == "partial"
    assert record["section"]["metadata"]["request_evidence"] == "NOT_ESTABLISHED"


def test_explicit_valid_query_keeps_identity_and_units(tmp_path):
    query = "?secid=1.600519&fields2=f51,f52,f53,f54,f55,f56,f57"
    record = evidence.load_record(save(tmp_path, source_url=get_source(SOURCE)["source_urls"][0] + query))
    assert record["section"]["metadata"]["request_evidence"] == "caller_declared_query"
    assert record["section"]["metadata"]["units"]["main_net"] == "CNY"


def test_old_knowledge_cutoff_never_exposes_later_import(tmp_path):
    path = save(tmp_path)
    result = evidence.build_research_context(base(), [path], available_at_cutoff="2026-11-06T23:00:00Z")
    card = result["p1"]["supplemental_sources"][f"{SOURCE}:sh600519"]
    assert card["rows"] == []
    assert card["status"] == "not_available"
    assert card["stale_reason"] == "evidence_not_available_at_cutoff"
    assert result["status"] == "partial"
    assert result["limit_pools"].get("zt") is None
    assert result["p1"]["limit_pool_stats"]["status"] == "not_available"
    assert result["evidence_import"]["base_availability_status"] == "not_available_at_cutoff"


def test_parser_revision_requires_new_receipt(tmp_path, monkeypatch):
    path = save(tmp_path)
    monkeypatch.setattr(evidence, "_parser_hash", lambda: "0" * 64)
    with pytest.raises(ValueError, match="parser implementation changed"):
        evidence.load_record(path)


def test_context_keeps_asset_scope_base_fields_and_fixture_provenance(tmp_path):
    path = save(tmp_path)
    original = base()
    before = deepcopy(original)
    result = evidence.build_research_context(original, [path])
    assert original == before
    assert result["limit_pools"]["zt"] == 5
    assert result["history"] == original["history"]
    assert result["p1"]["funding_percentiles"]["status"] == "not_available"
    assert result["p1"]["supplemental_sources"][f"{SOURCE}:sh600519"]["rows"]
    assert result["run_mode"] == "research_import"
    assert result["evidence_import"]["contains_fixture"] is True
    assert result["publication_eligible"] is False
    unsigned = {k: v for k, v in result.items() if k != "snapshot_sha256"}
    assert result["snapshot_sha256"] == hashlib.sha256(evidence._canonical(unsigned)).hexdigest()


def test_date_mismatch_conflicting_revision_and_future_cutoff_rejected(tmp_path):
    path = save(tmp_path)
    with pytest.raises(ValueError, match="asof does not match"):
        evidence.build_research_context({**base(), "asof": "2026-11-05"}, [path])
    with pytest.raises(ValueError, match="conflicting"):
        evidence.build_research_context(base(), [path, path])
    with pytest.raises(ValueError, match="in the future"):
        evidence.build_research_context(base(), [path], available_at_cutoff="2027-01-01T00:00:00Z")


def test_cannot_overwrite_sealed_research_context(tmp_path):
    path = save(tmp_path)
    result = evidence.build_research_context(base(), [path])
    target = tmp_path / "context.json"
    evidence.write_research_context(target, result)
    before = target.read_bytes()
    result["status"] = "error"
    with pytest.raises(ValueError, match="immutable"):
        evidence.write_research_context(target, result)
    assert target.read_bytes() == before


def test_cli_builds_research_only_context_without_network(tmp_path, monkeypatch, capsys):
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("offline import tried network")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    raw = tmp_path / "response.json"
    raw.write_bytes(raw_bytes())
    assert main(["import-response", "--source", SOURCE, "--raw", str(raw), "--archive", str(tmp_path / "archive"), "--asof", DAY, "--fetched-at", FETCHED, "--source-url", get_source(SOURCE)["source_urls"][0], "--subject", "sh600519", "--origin", "fixture"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps(base()), encoding="utf-8")
    out = tmp_path / "context.json"
    assert main(["build-context", "--base-payload", str(payload), "--record", receipt["record"], "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["run_mode"] == "research_import"
    assert result["publication_eligible"] is False
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0
