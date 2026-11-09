"""Inspect locally supplied raw responses without fetching or publishing anything.

The caller retains the original bytes. This report binds their hashes and request
metadata, preserves decoded source text, and delegates provider checks to
market_source_schema. Local hashes do not authenticate a provider, establish
permission, prove first publication, or replace EOD/calendar quality checks.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .market_source_schema import inspect_em_pool, inspect_ths_pages

SCHEMA = "market-source-candidate.v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ROUTES = {
    ("push2ex.eastmoney.com", "/getTopicZTPool"): ("zt", "eastmoney_limit_pools"),
    ("push2ex.eastmoney.com", "/getTopicZBPool"): ("zb", "eastmoney_limit_pools"),
    ("push2ex.eastmoney.com", "/getTopicDTPool"): ("dt", "eastmoney_limit_pools"),
    ("push2ex.eastmoney.com", "/getYesterdayZTPool"): ("yesterday", "eastmoney_yesterday_zt_pool"),
    ("data.10jqka.com.cn", "/dataapi/limit_up/limit_up_pool"): ("ths", "ths_limit_up_pool"),
}


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _shanghai_day(value: datetime | None) -> str | None:
    if value is None:
        return None
    try:
        return value.astimezone(_SHANGHAI).date().isoformat()
    except (ValueError, OverflowError):
        return None


def _positive(value: str | None) -> int | None:
    return int(value) if value and value.isascii() and value.isdigit() and int(value) > 0 else None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant: " + value)


def _record(value: Any, ordinal: int, *, asof: str, clock: datetime,
            max_age: float | None) -> dict[str, Any]:
    result: dict[str, Any] = {"ordinal": ordinal, "errors": [], "missing": [], "body_hash_verified": False,
                              "source_key": None, "decoded_payload": None, "body_text": None}
    errors = result["errors"]
    if not isinstance(value, Mapping):
        errors.append("record_not_object")
        return result
    for key in ("source_id", "url", "http_status", "fetched_at", "body_sha256"):
        result[key] = value.get(key)
    try:
        parts = urlsplit(value.get("url", ""))
        route = _ROUTES.get((parts.hostname, parts.path))
        if (parts.scheme != "https" or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.fragment or route is None):
            raise ValueError("unreviewed URL")
        key, source_id = route
        result["source_key"] = key
        if value.get("source_id") != source_id:
            errors.append("source_id_url_mismatch")
        query = parse_qs(parts.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            errors.append("ambiguous_query_parameter")
        params = {name: values[0] for name, values in query.items()}
        result["request_parameters"] = params
        requested = params.get("date")
        if requested not in (asof, asof.replace("-", "")):
            errors.append("request_date_missing_or_mismatched")
        result["request_date_is_response_date_proof"] = False
        if key == "ths":
            result["page"] = _positive(params.get("page"))
            result["page_size"] = _positive(params.get("limit"))
            if "page" not in params or "limit" not in params:
                result["missing"].append("ths_page_or_limit_missing")
            elif result["page"] is None or result["page_size"] is None:
                errors.append("ths_page_or_limit_missing_or_invalid")
            if params.get("filter") != "HS,GEM2STAR":
                errors.append("ths_filter_not_supported_by_reviewed_schema")
        else:
            result["page"] = 0 if params.get("Pageindex") == "0" else None
            result["page_size"] = _positive(params.get("pagesize"))
            if "Pageindex" not in params or "pagesize" not in params:
                result["missing"].append("em_page_or_size_missing")
            elif params.get("Pageindex") != "0" or result["page_size"] is None:
                errors.append("em_requires_single_explicit_page_zero")
    except (ValueError, TypeError, AttributeError):
        errors.append("source_url_not_allowed")
    fetched = _time(value.get("fetched_at"))
    fetched_day = _shanghai_day(fetched)
    if fetched is None:
        errors.append("fetched_at_invalid_or_timezone_missing")
    elif fetched_day is None:
        errors.append("fetched_at_outside_shanghai_date_range")
    elif fetched > clock:
        errors.append("fetched_at_after_checked_at")
    elif fetched_day < asof:
        errors.append("fetched_at_before_requested_session")
    elif max_age is not None and (clock - fetched).total_seconds() > max_age:
        errors.append("record_expired_under_explicit_age_limit")
    result["vintage_status"] = (
        "retrieved_after_asof" if fetched_day and fetched_day > asof
        else "observed_on_asof" if fetched_day == asof else "NOT_ESTABLISHED"
    )
    http_status = value.get("http_status")
    if type(http_status) is not int or not 200 <= http_status < 300:
        errors.append("http_status_not_successful")
    body = value.get("body")
    if not isinstance(body, bytes):
        errors.append("body_must_be_original_bytes")
        return result
    observed = hashlib.sha256(body).hexdigest()
    result.update({"observed_body_sha256": observed, "body_size_bytes": len(body)})
    result["body_hash_verified"] = observed == value.get("body_sha256")
    if not result["body_hash_verified"]:
        errors.append("body_sha256_mismatch")
        return result
    try:
        result["body_text"] = body.decode("utf-8-sig")
        decoded = json.loads(result["body_text"], object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant)
        if not isinstance(decoded, dict):
            raise ValueError("JSON object required")
        result["decoded_payload"] = decoded
    except (ValueError, UnicodeError):
        errors.append("body_is_not_a_json_object")
    return result


def inspect_market_source_candidate(records: Sequence[Mapping[str, Any]], *, asof: str,
                                    checked_at: str,
                                    max_record_age_seconds: float | None = None) -> dict[str, Any]:
    """Return a research-only report for four EM pools and all THS pages.

    Each record contains source_id, full request url, http_status, fetched_at,
    body_sha256 (lowercase hex), and body (original bytes, not reserialized JSON).
    URLs require their date/page/limit parameters. Supply one EM response per
    endpoint and every THS page; retries/revisions belong to separate candidates.
    checked_at is an explicit timezone-aware audit cutoff. An optional maximum
    age rejects expired inputs; without it historical files remain inspectable.
    THS timestamps always use the reviewed seconds unit, never auto-detection.
    record_binding_sha256 identifies the inputs; assessment_sha256 additionally
    binds the canonical UTC cutoff and numeric age policy to this schema version.
    """
    try:
        if not isinstance(asof, str) or date.fromisoformat(asof).isoformat() != asof:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("asof must be a canonical YYYY-MM-DD date") from exc
    clock = _time(checked_at)
    if clock is None:
        raise ValueError("checked_at must be a valid datetime with a timezone")
    clock_day = _shanghai_day(clock)
    if clock_day is None:
        raise ValueError("checked_at is outside the supported Shanghai date range")
    age_limit = None
    if max_record_age_seconds is not None:
        try:
            if type(max_record_age_seconds) not in (int, float):
                raise ValueError
            age_limit = float(max_record_age_seconds)
        except (ValueError, OverflowError) as exc:
            raise ValueError("max_record_age_seconds must be finite and positive") from exc
    if age_limit is not None and (not math.isfinite(age_limit) or age_limit <= 0):
        raise ValueError("max_record_age_seconds must be finite and positive")
    if not isinstance(records, (list, tuple)):
        raise ValueError("records must be a list or tuple of local raw-response records")
    receipts = [_record(item, i, asof=asof, clock=clock, max_age=age_limit)
                for i, item in enumerate(records)]
    errors = [f"record[{r['ordinal']}]:{error}" for r in receipts for error in r["errors"]]
    reasons = [f"record[{r['ordinal']}]:{missing}" for r in receipts for missing in r["missing"]]
    if asof > clock_day:
        errors.append("requested_session_is_after_checked_at")
    sources: dict[str, Any] = {}
    for key, source_id in _ROUTES.values():
        group = [r for r in receipts if r["source_key"] == key]
        source: dict[str, Any] = {"source_id": source_id, "record_ordinals": [r["ordinal"] for r in group],
                                  "body_sha256s": [r.get("observed_body_sha256") for r in group],
                                  "inspection": None, "errors": [], "missing": []}
        sources[key] = source
        if not group:
            source["missing"].append("response_missing")
            reasons.append(f"{key}:response_missing")
            source["status"] = "partial"
            continue
        if any(r["errors"] for r in group):
            source["errors"].append("invalid_record")
        if any(r["missing"] for r in group):
            source["missing"].append("incomplete_record_metadata")
        if key != "ths" and len(group) != 1:
            source["errors"].append("duplicate_endpoint_or_unsupported_em_pagination")
        if key == "ths" and not source["errors"] and not source["missing"]:
            pages = [r["page"] for r in group]
            if len(set(pages)) != len(pages):
                source["errors"].append("duplicate_ths_page")
            elif sorted(pages) != list(range(1, len(group) + 1)):
                source["errors"].append("ths_pages_not_contiguous_from_one")
            signatures = {json.dumps({k: v for k, v in r["request_parameters"].items()
                                      if k not in ("page", "_", "_t")}, sort_keys=True) for r in group}
            if len(signatures) != 1:
                source["errors"].append("ths_query_changed_between_pages")
            group.sort(key=lambda r: r["page"])
        if not source["errors"] and not source["missing"]:
            source["inspection_record_ordinals"] = [r["ordinal"] for r in group]
            if key == "ths":
                zt = sources["zt"]["inspection"]
                # The full denominator is usable only after independent ZT
                # structural/date checks; never silently scope-filter it.
                expected = None
                if zt and zt["schema_complete"]:
                    zt_record = next(r for r in receipts if r["source_key"] == "zt")
                    expected = [row["c"] for row in zt_record["decoded_payload"]["data"]["pool"]]
                observed = inspect_ths_pages([r["decoded_payload"] for r in group], asof=asof,
                                             timestamp_unit="seconds", expected_codes=expected)
                total = observed["pagination"]["declared_total"]
                size = group[0]["page_size"]
                if total is not None and len(group) != max(1, (total + size - 1) // size):
                    source["errors"].append("ths_page_count_does_not_match_total_and_limit")
                if expected is None:
                    source["missing"].append("verified_full_zt_denominator_missing")
            else:
                observed = inspect_em_pool(group[0]["decoded_payload"], asof=asof)
            source["inspection"] = observed
            source["errors"].extend(observed["errors"])
            source["missing"].extend(observed["reasons"])
        source["status"] = "rejected" if source["errors"] else "partial" if source["missing"] else "research_candidate"
        errors.extend(f"{key}:{error}" for error in source["errors"])
        reasons.extend(f"{key}:{reason}" for reason in source["missing"])
    binding = [{k: r.get(k) for k in ("ordinal", "source_id", "url", "http_status", "fetched_at",
                                     "body_sha256", "observed_body_sha256")} for r in receipts]
    binding_sha = hashlib.sha256(json.dumps({"asof": asof, "records": binding}, ensure_ascii=False,
                                            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assessment = {"schema_version": SCHEMA, "checked_at": clock.isoformat(),
                  "max_record_age_seconds": age_limit, "record_binding_sha256": binding_sha}
    assessment_sha = hashlib.sha256(json.dumps(assessment, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": SCHEMA, "status": "rejected" if errors else "partial" if reasons else "research_candidate",
            "requested_asof": asof, "checked_at": clock.isoformat(), "max_record_age_seconds": age_limit,
            "records": receipts, "record_binding_sha256": binding_sha, "assessment_sha256": assessment_sha,
            "sources": sources,
            "errors": errors, "missing": reasons, "evidence": "offline_raw_candidate",
            "candidate_scope": "local_input_hashes_and_schema_only",
            "local_body_hashes_verified": bool(receipts) and all(r["body_hash_verified"] for r in receipts),
            "research_candidate_complete": not errors and not reasons,
            "publication_eligible": False, "model_input_eligible": False,
            "source_authenticity_verified": False, "source_network_verified": False,
            "exchange_calendar_verified": False, "session_finality_verified": False,
            "first_public_visible_at": None, "production_snapshot_created": False,
            "contains_private_source_material": True, "public_repository_eligible": False,
            "sharing_note": "Source text is private review material; this report grants no redistribution rights."}
