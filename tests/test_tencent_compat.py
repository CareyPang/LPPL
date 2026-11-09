from __future__ import annotations

import copy

import pytest

from research.data.investor_context import build_investor_context
from server.tencent.compat import InMemoryTencentStore, TencentCompat, _json_hash


def snapshot(asof: str) -> dict:
    value = {
        "schema_version": "market-context.v1",
        "kind": "market_context",
        "asof": asof,
        "evidence": "descriptive",
        "status": "partial",
        "stale_reason": None,
        "source": {"source_id": "fixture", "status": "partial"},
        "sources": {"p1": {"source_id": "fixture", "raw_sha256": "a" * 64}},
        "limit_pools": {"reasons": {"status": "fresh", "rows": []}},
        "calendar": {"calendar_status": "provided", "asof_status": "exchange_verified",
                     "calendar_source_sha256": "b" * 64, "prior_status": "not_available"},
    }
    value["snapshot_sha256"] = _json_hash(value)
    return value


def test_query_is_atomic_and_deduplicated() -> None:
    queued = []
    api = TencentCompat(queue_dispatcher=queued.append)
    first = api.dispatch("POST", "/query", body={"code": "600519"})
    second = api.dispatch("POST", "/query", body={"code": "600519"})
    assert first.status == second.status == 202
    assert first.body["deduped"] is False
    assert second.body["deduped"] is True
    assert first.body["job_id"] == second.body["job_id"]
    assert len(queued) == 1


def test_result_reads_are_job_scoped() -> None:
    api = TencentCompat()
    queued = api.dispatch("POST", "/query", body={"code": "600519"})
    job_id = queued.body["job_id"]
    api.store.put_result(code="600519", job_id=job_id, kind="latest", value={"job_id": job_id, "symbol": "sh600519"})
    ready = api.dispatch("GET", "/status", query={"code": "600519", "job_id": job_id})
    assert ready.body["current_ready"] is True
    result = api.dispatch("GET", "/result", query={"code": "600519", "kind": "latest", "job_id": job_id})
    assert result.status == 200
    wrong = api.dispatch("GET", "/result", query={"code": "600519", "kind": "latest", "job_id": "11111111-1111-4111-8111-111111111111"})
    assert wrong.status == 404


def test_context_seed_is_append_only_and_latest_is_monotonic() -> None:
    api = TencentCompat(seed_token="seed")
    newer = snapshot("2026-11-06")
    older = snapshot("2026-11-05")
    denied = api.dispatch("POST", "/context/seed", body=newer, headers={})
    assert denied.status == 403
    assert api.dispatch("POST", "/context/seed", body=newer, headers={"X-Market-Context-Seed-Token": "seed"}).status == 201
    assert api.dispatch("POST", "/context/seed", body=older, headers={"X-Market-Context-Seed-Token": "seed"}).status == 201
    assert api.dispatch("GET", "/context", query={"date": "latest"}).body["asof"] == "2026-11-06"
    duplicate = api.dispatch("POST", "/context/seed", body=newer, headers={"X-Market-Context-Seed-Token": "seed"})
    assert duplicate.status == 409
    assert api.dispatch("GET", "/context", query={"date": "2026-11-04"}).status == 404


def test_refresh_fails_closed_without_explicit_source() -> None:
    api = TencentCompat(refresh_token="refresh")
    response = api.dispatch("POST", "/context/refresh", body={}, headers={"X-Market-Context-Token": "refresh"})
    assert response.status == 503
    assert response.body["error_code"] == "SOURCE_NOT_CONFIGURED"
    assert not api.store.refresh_jobs


def test_market_is_independent_of_query_queue() -> None:
    store = InMemoryTencentStore()
    store.markets["600519"] = {"code": "600519", "asof": "2026-11-06", "price": []}
    api = TencentCompat(store=store)
    response = api.dispatch("GET", "/market", query={"code": "600519"})
    assert response.status == 200
    assert response.body["asof"] == "2026-11-06"
    assert response.body["investor_context"]["status"] == "not_available"


def information(*, symbol=None, purpose="publish", permitted=True, asof="2026-11-06"):
    row = {"title": "Synthetic headline", "source": "Synthetic publisher",
           "published_at": "2026-11-06T09:00:00Z", "url": "https://example.test/article"}
    if symbol:
        row["symbol"] = symbol
    return build_investor_context(asof=asof, symbol=symbol, available_at_cutoff="2026-11-06T12:00:00Z", purpose=purpose,
        attachments={"news": {"asof": asof, "rows": [row], "coverage_status": "complete",
            "source": {"source_id": "synthetic", "source_url": "https://example.test/source", "raw_sha256": "a" * 64,
                       "available_at": "2026-11-06T10:00:00Z", "publication": {"status": "verified" if permitted else "pending",
                       "evidence_refs": ["synthetic-permission-fixture"] if permitted else []}}}})


def test_investor_read_and_projections_are_date_and_asset_scoped():
    store = InMemoryTencentStore()
    store.investor_snapshots[("2026-11-06", None)] = information()
    store.investor_snapshots[("2026-11-06", "sh600519")] = information(symbol="sh600519")
    store.markets["600519"] = {"code": "600519", "asof": "2026-11-06", "price": []}
    store.snapshots["2026-11-06"] = snapshot("2026-11-06")
    before = copy.deepcopy(store.snapshots)
    api = TencentCompat(store=store)
    result = api.dispatch("GET", "/investor-context", query={"date": "2026-11-06", "symbol": "sh600519"})
    assert result.status == 200 and result.body["symbol"] == "sh600519"
    assert api.dispatch("GET", "/market", query={"code": "600519"}).body["investor_context"]["sections"]["news"]["rows"]
    context = api.dispatch("GET", "/context", query={"date": "2026-11-06"}).body
    assert context["investor_context"]["symbol"] is None
    assert context["base_snapshot_sha256"] == before["2026-11-06"]["snapshot_sha256"]
    assert store.snapshots == before
    assert context["snapshot_sha256"] == _json_hash(context)
    assert api.dispatch("GET", "/investor-context", query={"date": "2026-11-05"}).status == 404
    assert api.dispatch("GET", "/investor-context", query={"symbol": "sz000001"}).status == 404


def test_investor_unapproved_cache_never_blocks_market_or_leaks_embedded_rows():
    store = InMemoryTencentStore()
    store.investor_snapshots[("2026-11-06", "sh600519")] = information(symbol="sh600519", purpose="research")
    store.markets["600519"] = {"code": "600519", "asof": "2026-11-06", "investor_context": {"secret": "unvalidated"}}
    api = TencentCompat(store=store)
    assert api.dispatch("GET", "/investor-context", query={"symbol": "sh600519"}).status == 404
    response = api.dispatch("GET", "/market", query={"code": "600519"})
    assert response.status == 200 and response.body["investor_context"]["status"] == "not_available"
    assert not api.store.jobs and not api.store.refresh_jobs


@pytest.mark.parametrize("query", [{"date": "2026-02-30"}, {"date": True}, {"symbol": "600519"}, {"symbol": "sz600519"}])
def test_investor_bad_request_is_explicit(query):
    assert TencentCompat().dispatch("GET", "/investor-context", query=query).status == 400


def test_investor_cache_date_and_source_permissions_revalidated():
    store = InMemoryTencentStore()
    bad = information(purpose="research", permitted=False)
    bad.update(purpose="publish", publication_eligible=True)
    bad["snapshot_sha256"] = _json_hash(bad)
    store.investor_snapshots[("2026-11-06", None)] = bad
    api = TencentCompat(store=store)
    assert api.dispatch("GET", "/investor-context").status == 404
    store.investor_snapshots[("2026-11-05", None)] = information()
    assert api.dispatch("GET", "/investor-context", query={"date": "2026-11-05"}).status == 404


@pytest.mark.parametrize("marker", [{"evidence_import": {}}, {"publication_eligible": False},
    {"run_mode": "research_import"}, {"run_mode": "fixture"}, {"p1": {"supplemental_sources": {}}}, {"investor_context": {}}])
def test_context_seed_rejects_unpublished_information(marker):
    value = snapshot("2026-11-06")
    value.update(marker)
    value["snapshot_sha256"] = _json_hash(value)
    response = TencentCompat(seed_token="seed").dispatch("POST", "/context/seed", body=value,
                                                        headers={"X-Market-Context-Seed-Token": "seed"})
    assert response.status == 422 and response.body["error_code"] == "UNPUBLISHED_EVIDENCE"


def test_context_seed_requires_verified_calendar_and_prior_when_progression_fresh():
    api = TencentCompat(seed_token="seed")
    for change in ({"calendar": {}}, {"history": {"progression": {"status": "fresh"}}}):
        value = snapshot("2026-11-06")
        value.update(change)
        value["snapshot_sha256"] = _json_hash(value)
        response = api.dispatch("POST", "/context/seed", body=value, headers={"X-Market-Context-Seed-Token": "seed"})
        assert response.status == 422 and response.body["error_code"] == "CALENDAR_UNVERIFIED"


def test_no_public_investor_write_route_exists():
    api = TencentCompat()
    assert api.dispatch("POST", "/investor-context", body=information()).status == 404
    assert not api.store.investor_snapshots


def test_investor_unusable_dates_never_break_cached_market_response():
    store = InMemoryTencentStore()
    store.markets["600519"] = {"code": "600519", "asof": "2099-01-01", "price": []}
    response = TencentCompat(store=store).dispatch("GET", "/market", query={"code": "600519"})
    assert response.status == 200 and response.body["investor_context"] is None


def test_context_wrong_date_key_cannot_project_a_different_day():
    store = InMemoryTencentStore()
    store.snapshots["2026-11-05"] = snapshot("2026-11-06")
    response = TencentCompat(store=store).dispatch("GET", "/context", query={"date": "2026-11-05"})
    assert response.status == 503 and response.body["error_code"] == "DATE_MISMATCH"
