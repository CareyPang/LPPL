import copy

import pytest

from research.data.market_context import SCHEMA_VERSION, build_snapshot, validate_requested_date


def payload():
    return {
        "asof": "2026-11-02",
        "generated_at": "2026-11-02T23:47:50+00:00",
        "sources": {
            "limit_pools": {"url_host": "push2ex.eastmoney.com", "fetched_at": "2026-11-02T23:46:52+00:00", "ok": True},
            "margin": {"url_host": "sse.szse.official", "fetched_at": "2026-11-02T23:47:50+00:00", "ok": False, "error": "refresh failed"},
        },
        "board_flow": {"industry": [{"name": "电子信息", "main_net": 1}]},
        "limit_pools": {"zt": 125, "top20": {"zt": [{"code": "000001", "name": "示例", "streak": 2}]}},
    }


def test_market_context_preserves_existing_values_and_adds_explicit_missing_states():
    result = build_snapshot(payload(), source_url="https://example.test/market_latest.json")

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "partial"
    assert result["limit_pools"]["zt"] == 125
    assert result["limit_pools"]["reasons"]["status"] == "not_available"
    assert result["limit_pools"]["topics"]["rows"] == []
    assert result["history"]["progression"]["status"] == "not_available"
    assert result["sources"]["margin"]["status"] == "error"
    assert result["sources"]["margin"]["stale_reason"] == "refresh failed"
    assert result["p1"]["limit_pool_stats"]["status"] == "not_available"
    assert result["p1"]["disclosures"]["announcements"]["status"] == "not_available"
    assert len(result["snapshot_sha256"]) == 64


def test_market_context_preserves_adapter_source_url_and_status():
    value = payload()
    value["sources"]["ths_limit_up_pool"] = {
        "source_url": "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool",
        "status": "fresh",
        "raw_sha256": "a" * 64,
        "fetched_at": "2026-11-02T23:46:52+00:00",
    }
    result = build_snapshot(value)
    source = result["sources"]["ths_limit_up_pool"]
    assert source["status"] == "fresh"
    assert source["source_url"].startswith("https://data.10jqka.com.cn/")


def test_snapshot_hash_is_stable_for_same_payload():
    left = build_snapshot(payload(), requested_at="2026-11-03T00:00:00+00:00")
    right = build_snapshot(copy.deepcopy(payload()), requested_at="2026-11-03T00:00:00+00:00")
    assert left["snapshot_sha256"] == right["snapshot_sha256"]


@pytest.mark.parametrize("value", ["2026-11-01", "2026-11-02T00:00:00Z", "bad"])
def test_requested_date_rejects_weekends_and_invalid_values(value):
    with pytest.raises(ValueError):
        validate_requested_date(value)


def test_requested_date_accepts_latest_and_weekday():
    assert validate_requested_date("latest") == "latest"
    assert validate_requested_date("2026-11-02") == "2026-11-02"
