"""Offline observations of decoded provider payloads; no fetching or snapshots.

These independent checks do not grant access, establish raw-byte provenance,
validate an exchange calendar, or replace market_eod_quality. A schema-complete
report remains research-only. Source text is retained; no model inputs or
promotion rates are produced here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA = "market-source-schema.v1"
_CODE = re.compile(r"(?:[03648]\d{5}|92\d{4})\Z")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _day(value: Any) -> str | None:
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"\d{8}", value):
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    try:
        return date.fromisoformat(value).isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None
    except ValueError:
        return None


def _asof(value: str) -> str:
    if not isinstance(value, str) or _day(value) != value:
        raise ValueError("asof must be a canonical YYYY-MM-DD date")
    return value


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _code(value: Any) -> bool:
    return isinstance(value, str) and bool(_CODE.fullmatch(value))


def _bse(code: str) -> bool:
    return code.startswith(("43", "83", "87", "88", "92"))


def _base(provider: str, asof: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "provider": provider, "requested_asof": _asof(asof),
            "status": "partial", "schema_complete": False, "publication_eligible": False,
            "model_input_eligible": False, "raw_bytes_verified": False, "source_network_verified": False,
            "exchange_calendar_verified": False, "reasons": [], "errors": []}


def _finish(result: dict[str, Any]) -> dict[str, Any]:
    result["reasons"] = list(dict.fromkeys(result["reasons"]))
    result["errors"] = list(dict.fromkeys(result["errors"]))
    result["status"] = "error" if result["errors"] else "partial" if result["reasons"] else "complete"
    result["schema_complete"] = result["status"] == "complete"
    return result


def _timestamp_day(value: Any, unit: str) -> str | None:
    # Unit is supplied by the caller's reviewed parser contract, never guessed
    # from magnitude. A millisecond value passed as seconds fails or mismatches.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
        if not math.isfinite(number):
            return None
        return datetime.fromtimestamp(number / (1000 if unit == "milliseconds" else 1), _SHANGHAI).date().isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def inspect_ths_pages(pages: Sequence[Mapping[str, Any]], *, asof: str,
                      timestamp_unit: str = "seconds", expected_codes: Sequence[str] | None = None,
                      requested_filter: str = "HS,GEM2STAR") -> dict[str, Any]:
    """Inspect supplied THS pages without calling any provider.

    `expected_codes` is the complete external pool to compare against, not a
    scope-filtered denominator. BSE exclusions are reported separately and do
    not improve full-market coverage. `data.filter` is observed if present;
    the requested filter and reference code's scope are not provider proof.
    """
    result = _base("ths_limit_up_pool", asof)
    if timestamp_unit not in {"seconds", "milliseconds"}:
        raise ValueError("timestamp_unit must explicitly be seconds or milliseconds")
    if not isinstance(pages, (list, tuple)):
        raise ValueError("pages must be a list or tuple of decoded response objects")
    reasons, errors = result["reasons"], result["errors"]
    seen: set[str] = set()
    duplicates: set[str] = set()
    rows: list[dict[str, Any]] = []
    totals: list[int | None] = []
    page_reports: list[dict[str, Any]] = []
    source_filters: list[Any] = []
    row_count = invalid_codes = 0
    date_pages_ok = True
    for page_number, envelope in enumerate(pages, 1):
        if not isinstance(envelope, Mapping):
            errors.append("page_not_object")
            date_pages_ok = False
            continue
        business = envelope.get("status_code")
        if type(business) is not int or business != 0:
            (errors if type(business) is int and business != 0 else reasons).append("business_status_missing_or_unsuccessful")
        data = envelope.get("data")
        if not isinstance(data, Mapping):
            errors.append("data_not_object")
            date_pages_ok = False
            continue
        info = data.get("info")
        if not isinstance(info, list):
            errors.append("info_not_list")
            info = []
        page = data.get("page")
        total = page.get("total") if isinstance(page, Mapping) else None
        totals.append(total if _count(total) else None)
        if not _count(total):
            reasons.append("page_total_missing_or_invalid")
        declared = _day(data.get("date"))
        raw_date_present = "date" in data
        if raw_date_present and declared != asof:
            reasons.append("declared_date_mismatch_or_invalid")
        if "filter" in data:
            source_filters.append(data["filter"])
            if data["filter"] != requested_filter:
                reasons.append("source_filter_differs_from_request")
        per_row_dates: list[str | None] = []
        for row_index, row in enumerate(info):
            row_count += 1
            if not isinstance(row, Mapping):
                errors.append("row_not_object")
                invalid_codes += 1
                per_row_dates.append(None)
                continue
            observed_day = _timestamp_day(row.get("first_limit_up_time"), timestamp_unit)
            per_row_dates.append(observed_day)
            if observed_day is None:
                reasons.append("row_timestamp_missing_or_invalid_for_explicit_unit")
            elif observed_day != asof:
                reasons.append("row_date_mismatch")
            code = row.get("code")
            if not _code(code):
                invalid_codes += 1
                reasons.append("invalid_stock_code")
                continue
            if code in seen:
                duplicates.add(code)
                reasons.append("duplicate_stock_code")
            seen.add(code)
            reason_raw = row.get("reason_type")
            has_reason = isinstance(reason_raw, str) and bool(reason_raw.strip()) and reason_raw.strip().lower() not in {"-", "暂无", "nan", "none", "null"}
            if not has_reason:
                reasons.append("reason_missing")
            tags = [tag.strip() for tag in reason_raw.split("+") if tag.strip()] if has_reason else []
            if not tags:
                reasons.append("derived_topic_tags_missing")
            rows.append({"code": code, "page_ordinal": page_number, "row_ordinal": row_index,
                         "source_reason_raw": reason_raw, "derived_tags": tags,
                         "tag_rule": "plus-delimited-preserve-all.v1", "has_reason": has_reason,
                         "row_date": observed_day})
        row_date_proof = bool(info) and all(day == asof for day in per_row_dates)
        declared_proof = declared == asof
        # A conflicting date/timestamp cannot be overridden by the other field.
        conflict = raw_date_present and not declared_proof or any(day not in (None, asof) for day in per_row_dates)
        page_date_ok = (declared_proof or row_date_proof) and not conflict
        if not page_date_ok:
            reasons.append("page_date_not_established")
        date_pages_ok = date_pages_ok and page_date_ok
        page_reports.append({"ordinal": page_number, "observed_data_keys": sorted(map(str, data.keys())),
                             "observed_page_keys": sorted(map(str, page.keys())) if isinstance(page, Mapping) else [],
                             "declared_total": total if _count(total) else None, "rows": len(info),
                             "declared_date": declared, "row_dates": sorted({d for d in per_row_dates if d is not None}),
                             "date_evidence": "source_data.date" if declared_proof and not conflict else "row_first_limit_up_time" if row_date_proof and not conflict else "NOT_ESTABLISHED"})
    if not pages:
        reasons.append("no_pages")
        date_pages_ok = False
    unique_totals = {x for x in totals if x is not None}
    if len(unique_totals) > 1:
        reasons.append("total_changed_between_pages")
    total = next(iter(unique_totals)) if len(unique_totals) == 1 and len(totals) == len(pages) and all(x is not None for x in totals) else None
    counts_match = total is not None and total == row_count == len(seen) and not invalid_codes and not duplicates
    if total is not None and not counts_match:
        reasons.append("declared_total_does_not_match_unique_rows")
    labelled = {r["code"] for r in rows if r["has_reason"]}
    tagged = {r["code"] for r in rows if r["derived_tags"]}
    expected: set[str] | None = None
    if expected_codes is not None:
        if not isinstance(expected_codes, (list, tuple)) or any(not _code(c) for c in expected_codes) or len(set(expected_codes)) != len(expected_codes):
            errors.append("expected_pool_codes_invalid_or_duplicate")
        else:
            expected = set(expected_codes)
    outside = sorted(c for c in expected or set() if _bse(c)) if requested_filter == "HS,GEM2STAR" else []
    observed_outside = sorted(c for c in seen if _bse(c)) if requested_filter == "HS,GEM2STAR" else []
    if observed_outside:
        reasons.append("observed_codes_outside_reference_filter_scope")
    matched = sorted((expected or set()) & labelled)
    missing = sorted((expected or set()) - labelled)
    if missing:
        reasons.append("full_market_reason_coverage_incomplete")
    reference_expected = (expected - set(outside)) if expected is not None and requested_filter == "HS,GEM2STAR" else None
    result.update({"pages": page_reports, "rows": rows, "timestamp_unit": timestamp_unit,
                   "date_evidence_complete": date_pages_ok, "pagination": {"pages_received": len(pages),
                   "declared_total": total, "rows_received": row_count, "unique_codes": len(seen),
                   "duplicate_codes": sorted(duplicates), "invalid_code_rows": invalid_codes, "counts_complete": counts_match},
                   "scope": {"requested_filter": requested_filter, "reference_scope": "SH_SZ_main_ChiNext_STAR_excludes_BSE" if requested_filter == "HS,GEM2STAR" else "NOT_ESTABLISHED",
                             "reference_scope_is_source_declaration": False, "observed_source_filters": source_filters,
                             "expected_outside_reference_codes": outside, "observed_outside_reference_codes": observed_outside},
                   "coverage": {"source_codes": len(seen), "source_reason_codes": len(labelled),
                                "source_topic_codes": len(tagged),
                                "full_market_denominator": len(expected) if expected is not None else None,
                                "full_market_matched": len(matched) if expected is not None else None,
                                "full_market_topic_matched": len(expected & tagged) if expected is not None else None,
                                "full_market_ratio": len(matched) / len(expected) if expected else None,
                                "full_market_missing_codes": missing,
                                "full_market_missing_topic_codes": sorted(expected - tagged) if expected is not None else [],
                                "reference_scope_denominator": len(reference_expected) if reference_expected is not None else None,
                                "reference_scope_matched": len(reference_expected & labelled) if reference_expected is not None else None,
                                "extra_source_codes": sorted(seen - expected) if expected is not None else []}})
    return _finish(result)


def inspect_em_pool(payload: Mapping[str, Any], *, asof: str) -> dict[str, Any]:
    """Inspect one decoded Eastmoney pool; qdate is never history proof."""
    result = _base("eastmoney_limit_pool", asof)
    reasons, errors = result["reasons"], result["errors"]
    if not isinstance(payload, Mapping):
        errors.append("payload_not_object")
        return _finish(result)
    rc = payload.get("rc")
    if type(rc) is not int or rc != 0:
        (errors if type(rc) is int and rc != 0 else reasons).append("business_status_missing_or_unsuccessful")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        errors.append("data_not_object")
        return _finish(result)
    pool = data.get("pool")
    if not isinstance(pool, list):
        errors.append("pool_not_list")
        pool = []
    total = data.get("total")
    if not _count(total):
        reasons.append("source_total_missing_or_invalid")
    seen: set[str] = set()
    duplicates: set[str] = set()
    invalid = 0
    for row in pool:
        code = row.get("c") if isinstance(row, Mapping) else None
        if not _code(code):
            invalid += 1
            reasons.append("invalid_stock_code_or_row")
        else:
            if code in seen:
                duplicates.add(code)
                reasons.append("duplicate_stock_code")
            seen.add(code)
    counts_match = _count(total) and total == len(pool) == len(seen) and not invalid and not duplicates
    if _count(total) and not counts_match:
        reasons.append("declared_total_does_not_match_unique_rows")
    declared = _day(data.get("date"))
    if declared != asof:
        reasons.append("source_date_not_established" if "date" not in data else "source_date_mismatch_or_invalid")
    result.update({"observed_data_keys": sorted(map(str, data.keys())), "source_declared_date": declared,
                   "latest_quote_day": _day(data.get("qdate")), "qdate_is_requested_date_proof": False,
                   "date_evidence": "source_data.date" if declared == asof else "NOT_ESTABLISHED",
                   "scope": {"source_declared_market_scope": data.get("scope"), "scope_verified": False},
                   "pagination": {"declared_total": total if _count(total) else None, "rows_received": len(pool),
                                  "unique_codes": len(seen), "duplicate_codes": sorted(duplicates),
                                  "invalid_code_rows": invalid, "counts_complete": counts_match}})
    return _finish(result)
