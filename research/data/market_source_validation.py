"""Offline, fail-closed validation of separately reviewed source evidence.

Hashes bind local review decisions to inspectable evidence; they do not prove
the truth of a document or replace a human licence/network review. DNS/TLS
probes cannot stand in for an actual HTTP response or a verified mainland path.
No network client, model execution or publication path is present here.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

BUNDLE_SCHEMA = "market-source-validation.v1"
POLICY_SCHEMA = "market-eod-fetch-policy.v1"
SOURCE_ENDPOINTS = {
    "eastmoney_limit_pools": {
        ("push2ex.eastmoney.com", "/getTopicZTPool"),
        ("push2ex.eastmoney.com", "/getTopicZBPool"),
        ("push2ex.eastmoney.com", "/getTopicDTPool"),
    },
    "eastmoney_yesterday_zt_pool": {("push2ex.eastmoney.com", "/getYesterdayZTPool")},
    "ths_limit_up_pool": {("data.10jqka.com.cn", "/dataapi/limit_up/limit_up_pool")},
}


class SourceValidationError(ValueError):
    """A durable machine-readable refusal, retaining every failed check."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("SOURCE_VALIDATION_BLOCKED")


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _url(value: Any) -> tuple[str, str] | None:
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment or parts.port not in (None, 443):
            return None
        return parts.hostname, parts.path
    except (ValueError, TypeError, AttributeError):
        return None


def _issue(result: dict[str, Any], group: str, check: str, reason: str) -> None:
    result[group].append({"check": check, "reason": reason})


def _object_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def inspect_fetch_policy(path: str | Path | None, *, now: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return policy and all missing/blocked checks without performing I/O beyond local files."""

    clock = _time(now) if now is not None else datetime.now(UTC)
    report: dict[str, Any] = {
        "schema_version": "market-source-validation-report.v1", "allowed": False,
        "checked_at": clock.isoformat() if clock else None, "publication_eligible": False,
        "model_input_eligible": False, "missing": [], "blocked": [], "sources": {},
    }
    policy: dict[str, Any] = {}
    bundle: dict[str, Any] = {}
    policy_path = Path(path).resolve() if path is not None else None
    bundle_path = None
    if clock is None:
        _issue(report, "blocked", "checked_at", "TIMEZONE_AWARE_CHECK_TIME_REQUIRED")
    if policy_path is None:
        _issue(report, "missing", "policy", "SOURCE_POLICY_REQUIRED")
    else:
        try:
            policy = _object_file(policy_path)
        except (OSError, ValueError, UnicodeError):
            _issue(report, "blocked", "policy", "SOURCE_POLICY_UNREADABLE")
    if policy.get("schema_version") != POLICY_SCHEMA:
        _issue(report, "blocked", "policy.schema_version", "SOURCE_POLICY_SCHEMA")
    reference = policy.get("validation_bundle")
    if not isinstance(reference, dict) or not reference.get("path"):
        _issue(report, "missing", "validation_bundle", "VALIDATION_BUNDLE_REQUIRED")
    else:
        try:
            relative = Path(reference["path"])
            if relative.is_absolute():
                raise ValueError("bundle path must be relative to policy")
            bundle_path = (policy_path.parent / relative).resolve()
            raw = bundle_path.read_bytes()
            if not _sha(reference.get("sha256")) or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
                _issue(report, "blocked", "validation_bundle.sha256", "BUNDLE_HASH_MISMATCH")
            else:
                bundle = json.loads(raw)
                if not isinstance(bundle, dict):
                    bundle = {}
                    raise ValueError("expected JSON object")
                report["validation_bundle_sha256"] = reference["sha256"]
        except (OSError, ValueError, TypeError, UnicodeError):
            _issue(report, "blocked", "validation_bundle", "VALIDATION_BUNDLE_UNREADABLE")
    if bundle.get("schema_version") != BUNDLE_SCHEMA:
        _issue(report, "blocked", "validation_bundle.schema_version", "VALIDATION_BUNDLE_SCHEMA")
    reviewed, expires = _time(bundle.get("reviewed_at")), _time(bundle.get("expires_at"))
    if reviewed is None or expires is None or expires <= reviewed:
        _issue(report, "blocked", "review_period", "VALID_REVIEW_PERIOD_REQUIRED")
    elif clock and (reviewed > clock or expires <= clock):
        _issue(report, "blocked", "review_period", "REVIEW_FUTURE_OR_EXPIRED")
    if not isinstance(bundle.get("reviewer"), str) or not bundle["reviewer"].strip():
        _issue(report, "missing", "reviewer", "REVIEWER_REQUIRED")
    evidence = bundle.get("evidence") if isinstance(bundle.get("evidence"), dict) else {}

    def refs(result: dict[str, Any], claim: Any, kind: str) -> list[dict[str, Any]]:
        ids = claim.get("evidence_refs") if isinstance(claim, dict) else None
        if not isinstance(ids, list) or not ids:
            _issue(result, "missing", kind, "EVIDENCE_REFS_REQUIRED")
            return []
        valid = []
        for ref_id in ids:
            item = evidence.get(ref_id) if isinstance(ref_id, str) else None
            check = f"{kind}:{ref_id}"
            if not isinstance(item, dict):
                _issue(result, "missing", check, "EVIDENCE_REF_NOT_FOUND")
                continue
            if item.get("kind") != kind or _url(item.get("url")) is None or item.get("synthetic") is not False:
                _issue(result, "blocked", check, "REAL_TRACEABLE_EVIDENCE_REQUIRED")
                continue
            observed = _time(item.get("observed_at"))
            if observed is None or reviewed is None or observed > reviewed or (clock and observed > clock):
                _issue(result, "blocked", check, "EVIDENCE_TIME_INVALID_OR_FUTURE")
                continue
            try:
                relative = Path(item["path"])
                if relative.is_absolute() or bundle_path is None:
                    raise ValueError("relative evidence path required")
                raw = (bundle_path.parent / relative).resolve().read_bytes()
                if not _sha(item.get("sha256")) or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                    raise ValueError("evidence hash mismatch")
            except (OSError, KeyError, ValueError, TypeError):
                _issue(result, "blocked", check, "EVIDENCE_FILE_OR_HASH_INVALID")
                continue
            valid.append(item)
        return valid

    source_reviews = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    source_policies = policy.get("sources") if isinstance(policy.get("sources"), dict) else {}
    for source_id, endpoints in sorted(SOURCE_ENDPOINTS.items()):
        result: dict[str, Any] = {"allowed": False, "missing": [], "blocked": []}
        report["sources"][source_id] = result
        local, review = source_policies.get(source_id, {}), source_reviews.get(source_id, {})
        local = local if isinstance(local, dict) else {}
        review = review if isinstance(review, dict) else {}
        if local.get("fetch_enabled") is not True:
            _issue(result, "blocked", "fetch_enabled", "FETCH_DISABLED")
        if review.get("source_id") != source_id:
            _issue(result, "missing", "source_id", "SOURCE_REVIEW_ID_MISMATCH")
        supplied = review.get("endpoints", [])
        reviewed_endpoints = {
            (v["host"], v["path"]) for v in supplied
            if isinstance(v, dict) and isinstance(v.get("host"), str) and isinstance(v.get("path"), str)
        } if isinstance(supplied, list) else set()
        if not isinstance(supplied, list) or reviewed_endpoints != endpoints or len(supplied) != len(endpoints):
            _issue(result, "blocked", "endpoints", "EXACT_REVIEWED_HOST_PATH_REQUIRED")
        for name in ("automated_access", "raw_retention"):
            claim = review.get(name, {})
            if not isinstance(claim, dict) or claim.get("status") != "verified":
                _issue(result, "blocked", name, "REVIEW_NOT_VERIFIED")
            refs(result, claim, name)
        frequency = review.get("frequency", {})
        frequency = frequency if isinstance(frequency, dict) else {}
        proofs = refs(result, frequency, "frequency")
        if frequency.get("status") != "verified" or frequency.get("authority") not in ("official", "provider_approval"):
            _issue(result, "blocked", "frequency", "OFFICIAL_OR_PROVIDER_APPROVAL_REQUIRED")
        if any(p.get("authority") != frequency.get("authority") for p in proofs):
            _issue(result, "blocked", "frequency.authority", "FREQUENCY_EVIDENCE_AUTHORITY_MISMATCH")
        minimum, interval = frequency.get("min_interval_seconds"), local.get("min_interval_seconds")
        if not _number(minimum) or not _number(interval) or interval < minimum:
            _issue(result, "blocked", "min_interval_seconds", "LOCAL_INTERVAL_BELOW_REVIEWED_MINIMUM_OR_INVALID")
        if any(p.get("min_interval_seconds") != minimum for p in proofs):
            _issue(result, "blocked", "frequency.min_interval_seconds", "APPROVED_NUMERIC_FREQUENCY_EVIDENCE_REQUIRED")
        network = review.get("mainland_network", {})
        network = network if isinstance(network, dict) else {}
        if network.get("status") != "verified":
            _issue(result, "blocked", "mainland_network", "MAINLAND_NETWORK_NOT_VERIFIED")
        route = network.get("cn_path", {})
        route = route if isinstance(route, dict) else {}
        route_proofs = refs(result, route, "cn_path")
        if route.get("status") != "verified" or route.get("country_code") != "CN" or route.get("route") not in ("direct", "verified_proxy"):
            _issue(result, "blocked", "mainland_network.cn_path", "VERIFIED_CN_ROUTE_REQUIRED")
        validated_routes = {}
        for proof in route_proofs:
            if (proof.get("status") != "verified" or proof.get("country_code") != "CN"
                    or proof.get("route") != route.get("route")
                    or proof.get("verification_method") not in ("operator_network_review", "provider_region_attestation")
                    or not isinstance(proof.get("verified_by"), str) or not proof["verified_by"].strip()):
                _issue(result, "blocked", "mainland_network.cn_path", "CN_PATH_REVIEW_EVIDENCE_REQUIRED")
                continue
            start, end = _time(proof.get("valid_from")), _time(proof.get("valid_until"))
            measurement = proof.get("measurement_id")
            if (not isinstance(measurement, str) or not measurement.strip() or start is None or end is None
                    or start > end or reviewed is None or end > reviewed):
                _issue(result, "blocked", "mainland_network.cn_path", "CN_MEASUREMENT_WINDOW_REQUIRED")
                continue
            for ref_id in route.get("evidence_refs", []):
                if isinstance(ref_id, str) and evidence.get(ref_id) is proof:
                    validated_routes[ref_id] = proof
        samples = network.get("http_samples", [])
        if not isinstance(samples, list) or not samples:
            _issue(result, "missing", "mainland_network.http_samples", "ACTUAL_HTTP_SAMPLE_REQUIRED")
        else:
            covered = set()
            for sample in samples:
                sample = sample if isinstance(sample, dict) else {}
                proofs = refs(result, {"evidence_refs": [sample.get("evidence_ref")]}, "http_response")
                endpoint = _url(sample.get("url"))
                http_status = sample.get("http_status")
                cn_ref = sample.get("cn_path_evidence_ref")
                bound_route = validated_routes.get(cn_ref) if isinstance(cn_ref, str) else None
                measurement = sample.get("measurement_id")
                network_bound = (
                    bound_route is not None and isinstance(measurement, str) and bool(measurement.strip())
                    and measurement == bound_route.get("measurement_id") and bool(proofs)
                    and all(p.get("cn_path_evidence_ref") == cn_ref and p.get("measurement_id") == measurement for p in proofs)
                )
                if not network_bound:
                    _issue(result, "blocked", "mainland_network.http_samples", "HTTP_CN_MEASUREMENT_BINDING_REQUIRED")
                else:
                    start, end = _time(bound_route["valid_from"]), _time(bound_route["valid_until"])
                    if any(not start <= _time(p["observed_at"]) <= end for p in proofs):
                        network_bound = False
                        _issue(result, "blocked", "mainland_network.http_samples", "HTTP_OUTSIDE_CN_MEASUREMENT_WINDOW")
                    if any(("country_code" in p and p["country_code"] != "CN")
                           or ("route" in p and p["route"] != bound_route["route"]) for p in [sample, *proofs]):
                        network_bound = False
                        _issue(result, "blocked", "mainland_network.http_samples", "HTTP_CN_PATH_METADATA_CONFLICT")
                if type(http_status) is int and 300 <= http_status < 400:
                    _issue(result, "blocked", "mainland_network.http_samples", "HTTP_REDIRECT_NOT_ESTABLISHED")
                if (endpoint not in endpoints or sample.get("synthetic") is not False
                        or sample.get("method") not in ("GET", "HEAD")
                        or type(http_status) is not int or not 200 <= http_status < 300
                        or not network_bound or not proofs or any(p.get("url") != sample.get("url")
                                             or p.get("method") != sample.get("method")
                                             or p.get("http_status") != http_status for p in proofs)):
                    _issue(result, "blocked", "mainland_network.http_samples", "ACTUAL_ALLOWED_ENDPOINT_HTTP_SAMPLE_REQUIRED")
                else:
                    covered.add(endpoint)
            if covered != endpoints:
                _issue(result, "missing", "mainland_network.http_samples", "HTTP_ENDPOINT_COVERAGE_INCOMPLETE")
        result["allowed"] = not result["missing"] and not result["blocked"]
    report["allowed"] = not report["missing"] and not report["blocked"] and all(v["allowed"] for v in report["sources"].values())
    return policy, report


def require_fetch_policy(path: str | Path | None, *, now: str | None = None) -> dict[str, Any]:
    policy, report = inspect_fetch_policy(path, now=now)
    if not report["allowed"]:
        raise SourceValidationError(report)
    policy["validation_report"] = report
    policy["publication_eligible"] = False
    policy["model_input_eligible"] = False
    return policy
