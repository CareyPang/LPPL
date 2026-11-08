from __future__ import annotations

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
