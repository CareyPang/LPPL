"""Policy contract tests: code availability must never imply data permission."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from research.data import p1_source_catalog as catalog


def test_selected_catalog_is_pinned_and_all_network_and_publication_disabled():
    data = catalog.load_catalog()
    assert data["source_count"] == len(data["sources"]) == 8
    assert data["complete_upstream_catalog"] is False
    assert data["pinned_upstreams"]["vibe_research"]["commit"] == "84c141b86b5e7540b29f5f4cd5457dc0ebd6052e"
    assert data["pinned_upstreams"]["tradingagents_astock"]["commit"] == "3a9171182304e87042743dde245c64922e04ed96"
    assert {item["code_license"] for item in data["pinned_upstreams"].values()} == {"MIT", "Apache-2.0"}
    for source in data["sources"]:
        fetch = catalog.policy_problems(source["source_id"])
        publish = catalog.policy_problems(source["source_id"], "publish")
        assert {"fetch_disabled", "data_access_not_verified", "source_frequency_not_verified", "mainland_network_not_verified"} <= set(fetch)
        assert {"publish_disabled", "redistribution_not_verified"} <= set(publish)
        assert source["local_rate_policy"]["status"] == "proposal_not_enforced"
        assert source["local_rate_policy"]["provider_guarantee"] is False


def test_unknown_ids_and_unknown_purposes_fail_closed():
    for source_id in ("unknown_source", "", None, ["eastmoney_limit_pools"]):
        assert catalog.policy_problems(source_id) == ["unknown_source"]
        with pytest.raises(KeyError):
            catalog.get_source(source_id)
    with pytest.raises(ValueError, match="purpose"):
        catalog.policy_problems("eastmoney_limit_pools", "preview")


def test_returned_copy_cannot_enable_source_or_mutate_later_catalog_read():
    source = catalog.get_source("ths_limit_up_pool")
    source["data_policy"]["fetch_enabled"] = True
    source["data_policy"]["access"]["status"] = "verified"
    assert "fetch_disabled" in catalog.policy_problems("ths_limit_up_pool")
    assert "data_access_not_verified" in catalog.policy_problems("ths_limit_up_pool")


def test_news_is_only_a_candidate_and_has_no_executable_parser():
    source = catalog.get_source("eastmoney_stock_news")
    assert source["implemented"] is False
    assert source["parser"] is None
    assert "parser_not_implemented" in catalog.policy_problems(source["source_id"])


def _reviewed_source():
    source = catalog.get_source("eastmoney_fund_flow_history")
    policy = source["data_policy"]
    policy["fetch_enabled"] = True
    policy["publish_enabled"] = True
    for key in ("access", "redistribution", "frequency_review", "mainland_network"):
        policy[key] = {"status": "verified", "evidence_refs": [f"review-fixture://{key}"]}
    return source


def test_data_permission_is_independent_of_code_license_and_fetch_permission(monkeypatch):
    source = _reviewed_source()
    source["data_policy"]["redistribution"] = {"status": "pending", "evidence_refs": []}
    monkeypatch.setattr(catalog, "get_source", lambda source_id: deepcopy(source))
    assert catalog.policy_problems("eastmoney_fund_flow_history", "fetch") == []
    assert catalog.policy_problems("eastmoney_fund_flow_history", "publish") == ["redistribution_not_verified"]


@pytest.mark.parametrize("review", [None, {}, "verified", {"status": "verified"}, {"status": "verified", "evidence_refs": []}, {"status": "verified", "evidence_refs": [""]}, {"status": "verified", "evidence_refs": [None]}, {"status": "pending", "evidence_refs": ["review-fixture://x"]}])
def test_status_label_without_valid_evidence_cannot_open_fetch(monkeypatch, review):
    source = _reviewed_source()
    source["data_policy"]["access"] = review
    monkeypatch.setattr(catalog, "get_source", lambda source_id: deepcopy(source))
    assert catalog.policy_problems("eastmoney_fund_flow_history") == ["data_access_not_verified"]


@pytest.mark.parametrize("enabled", ["true", 1, None, [], {}])
def test_truthy_non_boolean_flag_does_not_enable_fetch(monkeypatch, enabled):
    source = _reviewed_source()
    source["data_policy"]["fetch_enabled"] = enabled
    monkeypatch.setattr(catalog, "get_source", lambda source_id: deepcopy(source))
    assert catalog.policy_problems("eastmoney_fund_flow_history") == ["fetch_disabled"]


def test_malformed_source_policy_fails_closed(monkeypatch):
    source = _reviewed_source()
    source["data_policy"] = None
    monkeypatch.setattr(catalog, "get_source", lambda source_id: deepcopy(source))
    assert set(catalog.policy_problems("eastmoney_fund_flow_history", "publish")) == {
        "publish_disabled", "data_access_not_verified", "source_frequency_not_verified",
        "mainland_network_not_verified", "redistribution_not_verified",
    }


@pytest.mark.parametrize("change", ["duplicate_id", "count", "sha", "unknown_host", "unknown_provenance"])
def test_catalog_drift_is_rejected_before_source_lookup(tmp_path, monkeypatch, change):
    data = catalog.load_catalog()
    if change == "duplicate_id":
        data["sources"][1]["source_id"] = data["sources"][0]["source_id"]
    elif change == "count":
        data["source_count"] = 168
    elif change == "sha":
        data["pinned_upstreams"]["vibe_research"]["commit"] = "main"
    elif change == "unknown_host":
        data["sources"][0]["source_urls"] = ["https://unreviewed.example/endpoint"]
    else:
        data["sources"][0]["code_provenance"]["upstream_refs"] = ["unknown"]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)
    with pytest.raises(ValueError):
        catalog.policy_problems("ths_limit_up_pool")


def test_dates_preserve_current_vintage_and_schedule_boundaries():
    board = catalog.get_source("eastmoney_board_flow")["date_capability"]
    history = catalog.get_source("eastmoney_fund_flow_history")["date_capability"]
    unlock = catalog.get_source("eastmoney_lockup_expiry")["date_capability"]
    assert board["request_date_supported"] is False
    assert history["mode"] == "dated_rows_current_vintage"
    assert unlock["mode"] == "event_date_schedule"
    assert all(not source["date_capability"]["pit_verified"] for source in catalog.load_catalog()["sources"])


@pytest.mark.parametrize("raw", ['{"schema_version":"p1-source-catalog.v1","schema_version":"p1-source-catalog.v1"}', '{"enabled":NaN}'])
def test_duplicate_json_keys_and_non_finite_catalog_values_are_rejected(tmp_path, monkeypatch, raw):
    path = tmp_path / "catalog.json"
    path.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)
    with pytest.raises(ValueError):
        catalog.load_catalog()
