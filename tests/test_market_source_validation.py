"""Synthetic contract fixtures only. These files are never operational approval."""

import hashlib
import json
from pathlib import Path

import pytest

from research.data.market_source_validation import (
    SOURCE_ENDPOINTS,
    SourceValidationError,
    inspect_fetch_policy,
    require_fetch_policy,
)

NOW = "2026-11-06T08:00:00Z"


def write_policy_fixture(root: Path) -> Path:
    """Emulate reviewed evidence shape to exercise the gate, with no network.

    The synthetic fixture intentionally declares real-looking metadata so the
    positive path is reachable; it proves contract handling, never real access.
    """
    root.mkdir(parents=True, exist_ok=True)
    bundle = {"schema_version": "market-source-validation.v1", "reviewer": "offline-contract-test",
              "reviewed_at": "2026-11-04T07:00:00Z", "expires_at": "2026-12-01T00:00:00Z",
              "evidence": {}, "sources": {}}

    def evidence(ref, kind, url, **extra):
        raw = json.dumps({"fixture": "synthetic test only, not operational evidence", "ref": ref}).encode()
        (root / f"{ref}.json").write_bytes(raw)
        bundle["evidence"][ref] = {
            "kind": kind, "url": url, "path": f"{ref}.json", "sha256": hashlib.sha256(raw).hexdigest(),
            "observed_at": "2026-11-04T06:00:00Z", "synthetic": False, **extra,
        }
        return ref

    for source, endpoints in SOURCE_ENDPOINTS.items():
        review = {"source_id": source, "endpoints": [{"host": h, "path": p} for h, p in sorted(endpoints)]}
        for kind in ("automated_access", "raw_retention", "frequency"):
            ref = evidence(f"{source}_{kind}", kind, "https://example.test/review",
                           **({"authority": "provider_approval", "min_interval_seconds": 1} if kind == "frequency" else {}))
            review[kind] = {"status": "verified", "evidence_refs": [ref]}
        review["frequency"].update({"authority": "provider_approval", "min_interval_seconds": 1})
        measurement = f"{source}_cn-measurement-1"
        route = evidence(f"{source}_route", "cn_path", "https://example.test/network-review", country_code="CN", route="direct",
                         status="verified", verification_method="operator_network_review", verified_by="offline-contract-test",
                         measurement_id=measurement, valid_from="2026-11-04T05:55:00Z", valid_until="2026-11-04T06:05:00Z")
        samples = []
        for index, (host, path) in enumerate(sorted(endpoints)):
            url = f"https://{host}{path}"
            ref = evidence(f"{source}_http_{index}", "http_response", url, method="HEAD", http_status=200,
                           measurement_id=measurement, cn_path_evidence_ref=route)
            samples.append({"evidence_ref": ref, "url": url, "method": "HEAD", "http_status": 200, "synthetic": False,
                            "measurement_id": measurement, "cn_path_evidence_ref": route})
        review["mainland_network"] = {"status": "verified", "http_samples": samples,
            "cn_path": {"status": "verified", "country_code": "CN", "route": "direct", "evidence_refs": [route]}}
        bundle["sources"][source] = review
    bundle_path = root / "validation.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    policy_path = root / "policy.json"
    policy_path.write_text(json.dumps({"schema_version": "market-eod-fetch-policy.v1",
        "validation_bundle": {"path": "validation.json", "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest()},
        "sources": {source: {"fetch_enabled": True, "min_interval_seconds": 1} for source in SOURCE_ENDPOINTS}}), encoding="utf-8")
    return policy_path


def rewrite_bundle(policy_path, mutate):
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    path = policy_path.parent / policy["validation_bundle"]["path"]
    bundle = json.loads(path.read_text(encoding="utf-8"))
    mutate(bundle)
    path.write_text(json.dumps(bundle), encoding="utf-8")
    policy["validation_bundle"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    policy_path.write_text(json.dumps(policy), encoding="utf-8")


def reasons(report):
    return {item["reason"] for result in [report, *report["sources"].values()]
            for group in ("missing", "blocked") for item in result[group]}


def test_complete_contract_passes_without_enabling_publication_or_models(tmp_path):
    path = write_policy_fixture(tmp_path)
    policy = require_fetch_policy(path, now=NOW)
    assert policy["validation_report"]["allowed"] is True
    assert policy["publication_eligible"] is False and policy["model_input_eligible"] is False


def test_legacy_verified_strings_are_not_evidence_and_all_sources_are_reported(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"schema_version": "market-eod-fetch-policy.v1", "sources": {
        source: {"fetch_enabled": True, "research_access_review": "verified", "evidence_refs": ["verified"],
                 "min_interval_seconds": 1} for source in SOURCE_ENDPOINTS}}), encoding="utf-8")
    _, report = inspect_fetch_policy(path, now=NOW)
    assert report["allowed"] is False
    assert set(report["sources"]) == set(SOURCE_ENDPOINTS)
    assert "VALIDATION_BUNDLE_REQUIRED" in reasons(report)
    assert all(result["missing"] and result["blocked"] for result in report["sources"].values())
    with pytest.raises(SourceValidationError) as caught:
        require_fetch_policy(path, now=NOW)
    assert caught.value.report == report


@pytest.mark.parametrize("field,value,expected", [
    ("reviewed_at", "2026-11-07T00:00:00Z", "REVIEW_FUTURE_OR_EXPIRED"),
    ("expires_at", NOW, "REVIEW_FUTURE_OR_EXPIRED"),
    ("schema_version", "unknown", "VALIDATION_BUNDLE_SCHEMA"),
])
def test_review_period_and_schema_are_enforced(tmp_path, field, value, expected):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle.update({field: value}))
    assert expected in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("kind", ["automated_access", "raw_retention", "frequency"])
def test_claims_need_real_hashed_evidence_not_verified_strings(tmp_path, kind):
    path = write_policy_fixture(tmp_path)
    ref = f"eastmoney_limit_pools_{kind}"
    rewrite_bundle(path, lambda bundle: bundle["evidence"][ref].update({"synthetic": True}))
    assert "REAL_TRACEABLE_EVIDENCE_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


def test_tampered_bundle_and_evidence_bytes_are_rejected(tmp_path):
    path = write_policy_fixture(tmp_path)
    (tmp_path / "validation.json").write_bytes(b"{}")
    assert "BUNDLE_HASH_MISMATCH" in reasons(inspect_fetch_policy(path, now=NOW)[1])
    path = write_policy_fixture(tmp_path)
    (tmp_path / "eastmoney_limit_pools_automated_access.json").write_bytes(b"changed")
    assert "EVIDENCE_FILE_OR_HASH_INVALID" in reasons(inspect_fetch_policy(path, now=NOW)[1])


def test_refs_cannot_point_to_future_or_untraceable_evidence(tmp_path):
    path = write_policy_fixture(tmp_path)
    ref = "eastmoney_limit_pools_automated_access"
    rewrite_bundle(path, lambda bundle: bundle["evidence"][ref].update({"observed_at": "2026-11-05T00:00:00Z"}))
    assert "EVIDENCE_TIME_INVALID_OR_FUTURE" in reasons(inspect_fetch_policy(path, now=NOW)[1])
    rewrite_bundle(path, lambda bundle: bundle["evidence"][ref].update({"url": "verified"}))
    assert "REAL_TRACEABLE_EVIDENCE_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("authority", ["local_proposal", "NOT_ESTABLISHED", None])
def test_local_throttle_proposal_is_not_provider_approval(tmp_path, authority):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["sources"]["eastmoney_limit_pools"]["frequency"].update({"authority": authority}))
    assert "OFFICIAL_OR_PROVIDER_APPROVAL_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("interval", [0, -1, True, float("inf"), 0.5])
def test_local_interval_cannot_be_below_approved_limit(tmp_path, interval):
    path = write_policy_fixture(tmp_path)
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy["sources"]["eastmoney_limit_pools"]["min_interval_seconds"] = interval
    path.write_text(json.dumps(policy), encoding="utf-8")
    assert "LOCAL_INTERVAL_BELOW_REVIEWED_MINIMUM_OR_INVALID" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("kind", ["dns_probe", "tls_probe"])
def test_dns_and_tls_never_satisfy_the_http_gate(tmp_path, kind):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["evidence"]["eastmoney_limit_pools_http_0"].update({"kind": kind}))
    assert "ACTUAL_ALLOWED_ENDPOINT_HTTP_SAMPLE_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("change", [{"route": "proxy_unknown"}, {"country_code": "SG"}, {"status": "pending"}])
def test_unverified_or_foreign_network_path_stays_blocked(tmp_path, change):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["sources"]["eastmoney_limit_pools"]["mainland_network"]["cn_path"].update(change))
    assert "VERIFIED_CN_ROUTE_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


def test_endpoint_scope_and_synthetic_http_samples_fail_closed(tmp_path):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["sources"]["eastmoney_limit_pools"]["endpoints"].append({"host": "other.test", "path": "/"}))
    assert "EXACT_REVIEWED_HOST_PATH_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])
    rewrite_bundle(path, lambda bundle: bundle["sources"]["eastmoney_limit_pools"]["mainland_network"]["http_samples"][0].update({"synthetic": True}))
    assert "ACTUAL_ALLOWED_ENDPOINT_HTTP_SAMPLE_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("value", [None, "unknown", [{"host": [], "path": "/"}], [{"host": "host", "path": {}}]])
def test_malformed_endpoint_shape_is_a_machine_readable_refusal(tmp_path, value):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["sources"]["eastmoney_limit_pools"].update({"endpoints": value}))
    assert "EXACT_REVIEWED_HOST_PATH_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("change", [{"method": "GET"}, {"http_status": 201}, {"http_status": 302}])
def test_http_evidence_and_declared_sample_must_match(tmp_path, change):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["evidence"]["eastmoney_limit_pools_http_0"].update(change))
    assert "ACTUAL_ALLOWED_ENDPOINT_HTTP_SAMPLE_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


def test_redirect_is_not_api_availability_even_when_metadata_matches(tmp_path):
    path = write_policy_fixture(tmp_path)
    def redirect(bundle):
        bundle["evidence"]["eastmoney_limit_pools_http_0"]["http_status"] = 302
        bundle["sources"]["eastmoney_limit_pools"]["mainland_network"]["http_samples"][0]["http_status"] = 302
    rewrite_bundle(path, redirect)
    assert "ACTUAL_ALLOWED_ENDPOINT_HTTP_SAMPLE_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("reference", ["unknown", {}, None])
def test_unknown_or_invalid_evidence_refs_do_not_crash(tmp_path, reference):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["sources"]["eastmoney_limit_pools"]["automated_access"].update({"evidence_refs": [reference]}))
    assert "EVIDENCE_REF_NOT_FOUND" in reasons(inspect_fetch_policy(path, now=NOW)[1])


def test_repository_review_bundle_is_hash_bound_but_cannot_enable_capture():
    path = Path(__file__).resolve().parents[1] / "research/data/market_eod_fetch_policy.json"
    declared = json.loads(path.read_text(encoding="utf-8"))
    bundle_path = (path.parent / declared["validation_bundle"]["path"]).resolve()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    _, report = inspect_fetch_policy(path, now=bundle["reviewed_at"])
    assert report["validation_bundle_sha256"] == declared["validation_bundle"]["sha256"]
    assert report["missing"] == [] and report["blocked"] == []
    assert report["allowed"] is False
    assert all(value["allowed"] is False for value in report["sources"].values())
    assert reasons(report) >= {"FETCH_DISABLED", "EVIDENCE_REFS_REQUIRED", "OFFICIAL_OR_PROVIDER_APPROVAL_REQUIRED",
                               "ACTUAL_HTTP_SAMPLE_REQUIRED", "VERIFIED_CN_ROUTE_REQUIRED"}


@pytest.mark.parametrize("location", ["sample", "http", "cn_path"])
def test_same_url_from_a_different_measurement_cannot_borrow_cn_proof(tmp_path, location):
    path = write_policy_fixture(tmp_path)
    def change(bundle):
        if location == "sample":
            item = bundle["sources"]["eastmoney_limit_pools"]["mainland_network"]["http_samples"][0]
        else:
            item = bundle["evidence"]["eastmoney_limit_pools_http_0" if location == "http" else "eastmoney_limit_pools_route"]
        item["measurement_id"] = "different-network-measurement"
    rewrite_bundle(path, change)
    assert "HTTP_CN_MEASUREMENT_BINDING_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("observed", ["2026-11-04T05:54:59Z", "2026-11-04T06:05:01Z"])
def test_http_observation_outside_bound_cn_measurement_window_is_rejected(tmp_path, observed):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["evidence"]["eastmoney_limit_pools_http_0"].update({"observed_at": observed}))
    assert "HTTP_OUTSIDE_CN_MEASUREMENT_WINDOW" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("reference", ["unlisted-route", "ths_limit_up_pool_route", None, {}])
def test_http_reference_must_be_reviewed_for_this_source(tmp_path, reference):
    path = write_policy_fixture(tmp_path)
    def change(bundle):
        bundle["sources"]["eastmoney_limit_pools"]["mainland_network"]["http_samples"][0]["cn_path_evidence_ref"] = reference
        bundle["evidence"]["eastmoney_limit_pools_http_0"]["cn_path_evidence_ref"] = reference
    rewrite_bundle(path, change)
    assert "HTTP_CN_MEASUREMENT_BINDING_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


def test_matching_an_unverified_cn_evidence_record_does_not_grant_access(tmp_path):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["evidence"]["eastmoney_limit_pools_route"].update({"status": "pending"}))
    report = inspect_fetch_policy(path, now=NOW)[1]
    assert reasons(report) >= {"CN_PATH_REVIEW_EVIDENCE_REQUIRED", "HTTP_CN_MEASUREMENT_BINDING_REQUIRED"}


@pytest.mark.parametrize("change", [
    {"measurement_id": ""}, {"valid_from": None}, {"valid_until": "2026-11-04T05:00:00Z"},
    {"valid_until": "2026-11-05T00:00:00Z"}, {"valid_from": "0001-01-01T00:00:00+14:00"},
])
def test_cn_measurement_needs_a_real_nonfuture_time_window(tmp_path, change):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle["evidence"]["eastmoney_limit_pools_route"].update(change))
    assert "CN_MEASUREMENT_WINDOW_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])


@pytest.mark.parametrize("location", ["sample", "http"])
@pytest.mark.parametrize("change", [{"country_code": "SG"}, {"route": "proxy_unknown"}])
def test_explicit_foreign_or_unknown_http_path_cannot_hide_behind_cn_binding(tmp_path, location, change):
    path = write_policy_fixture(tmp_path)
    def conflict(bundle):
        item = (bundle["sources"]["eastmoney_limit_pools"]["mainland_network"]["http_samples"][0]
                if location == "sample" else bundle["evidence"]["eastmoney_limit_pools_http_0"])
        item.update(change)
    rewrite_bundle(path, conflict)
    assert "HTTP_CN_PATH_METADATA_CONFLICT" in reasons(inspect_fetch_policy(path, now=NOW)[1])


def test_bundle_is_parsed_from_the_exact_hash_checked_bytes(tmp_path, monkeypatch):
    path = write_policy_fixture(tmp_path)
    original = Path.read_text
    def forbid_second_read(self, *args, **kwargs):
        if self.name == "validation.json":
            raise AssertionError("bundle was reread after the byte hash check")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", forbid_second_read)
    assert require_fetch_policy(path, now=NOW)["validation_report"]["allowed"] is True


def test_utc_conversion_overflow_is_a_machine_readable_refusal(tmp_path):
    path = write_policy_fixture(tmp_path)
    rewrite_bundle(path, lambda bundle: bundle.update({"reviewed_at": "0001-01-01T00:00:00+14:00"}))
    assert "VALID_REVIEW_PERIOD_REQUIRED" in reasons(inspect_fetch_policy(path, now=NOW)[1])
