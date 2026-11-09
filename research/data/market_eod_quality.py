"""Pure quality checks for EOD pool snapshots; never repair or fetch data.

Structural completeness and provider-evidence completeness are independent.
Old snapshots may contain every normalized row while lacking archived source
date/pagination receipts. Those remain partial, not retrospectively verified.
The caller/archive verifies raw bytes and exchange calendar provenance.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from math import isfinite
from typing import Any

SCHEMA = "market-eod-quality.v1"
POOLS = ("zt", "zb", "dt")
YESTERDAY_POOL = "yesterday_performance"
YESTERDAY_SOURCE = "eastmoney_yesterday_zt_pool"
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_CODE = re.compile(r"(?:[03648]\d{5}|92\d{4})\Z")


def _day(value: Any, *, compact: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    if compact and re.fullmatch(r"\d{8}", value):
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _code(value: Any) -> bool:
    return isinstance(value, str) and bool(_CODE.fullmatch(value))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _quote_available(value: Any) -> bool:
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


def _pool_source(payload: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    limit = _mapping(payload.get("limit_pools"))
    if kind == YESTERDAY_POOL:
        # This T-day view has an independent source. Never fall back to the
        # current-day three-pool receipt or an archived T-1 snapshot.
        return _mapping(_mapping(limit.get(kind)).get("source"))
    scoped = _mapping(limit.get("pool_sources"))
    if kind in scoped:
        return _mapping(scoped[kind])
    sources = _mapping(payload.get("sources"))
    if f"limit_pool_{kind}" in sources:
        return _mapping(sources[f"limit_pool_{kind}"])
    combined = _mapping(sources.get("limit_pools"))
    scoped = _mapping(combined.get("pools"))
    return _mapping(scoped[kind]) if kind in scoped else combined


def _source_checks(source: Mapping[str, Any], *, asof: str, declared: Any) -> dict[str, Any]:
    reasons: list[str] = []
    source_status = source.get("status")
    if source_status is None:
        source_status = "fresh" if source.get("ok") is True else "error" if source.get("ok") is False else "unknown"
    elif source_status == "fresh" and source.get("ok") is False:
        source_status = "error"
        reasons.append("contradictory_source_success_flags")
    if source_status != "fresh":
        reasons.append("source_not_fresh")
    raw_hash_present = isinstance(source.get("raw_sha256"), str) and bool(_HASH.fullmatch(source["raw_sha256"]))
    if not raw_hash_present:
        reasons.append("raw_source_hash_missing_or_invalid")
    reported = source.get("asof")
    normalized = _day(reported, compact=True)
    date_status = "NOT_ESTABLISHED"
    if reported is not None and normalized != asof:
        date_status = "MISMATCH"
        reasons.append("source_asof_mismatch")
    elif normalized == asof and source.get("asof_status") == "source_verified":
        date_status = "VERIFIED"
    else:
        reasons.append("source_date_not_verified")

    coverage = _mapping(source.get("coverage"))
    total = coverage.get("declared_total")
    expected, received = coverage.get("pages_expected"), coverage.get("pages_received")
    coverage_status = "NOT_ESTABLISHED"
    if total is not None and (not _count(total) or (_count(declared) and total != declared)):
        coverage_status = "MISMATCH"
        reasons.append("source_total_mismatch")
    elif expected is not None and not _count(expected) or received is not None and not _count(received):
        coverage_status = "MISMATCH"
        reasons.append("invalid_pagination_counts")
    elif _count(expected) and _count(received) and (received > expected or (expected == 0 and total != 0)):
        coverage_status = "MISMATCH"
        reasons.append("inconsistent_pagination")
    elif (coverage.get("status") == "complete" and _count(total) and _count(declared)
          and total == declared and _count(expected) and _count(received) and received == expected):
        coverage_status = "VERIFIED"
    else:
        reasons.append("source_pagination_or_coverage_not_verified")
    return {
        "source_status": source_status, "source_asof": reported,
        "source_date_status": date_status, "coverage_status": coverage_status,
        "source_total": total if _count(total) else None,
        "pages_expected": expected if _count(expected) else None,
        "pages_received": received if _count(received) else None,
        "raw_source_hash_present": raw_hash_present,
        "raw_bytes_verified": False, "reasons": reasons,
    }


def _pool(payload: Mapping[str, Any], kind: str, asof: str) -> dict[str, Any]:
    limit = _mapping(payload.get("limit_pools"))
    section = _mapping(limit.get(kind)) if kind == YESTERDAY_POOL else {}
    declared = section.get("declared_count") if kind == YESTERDAY_POOL else limit.get(kind)
    raw = section.get("rows") if kind == YESTERDAY_POOL else _mapping(limit.get("pool_rows")).get(kind)
    present = isinstance(raw, list)
    reasons: list[str] = []
    if kind == YESTERDAY_POOL:
        if section.get("asof") != asof:
            reasons.append("yesterday_performance_asof_missing_or_mismatch")
        if section.get("window") != "t-1_to_t":
            reasons.append("yesterday_performance_window_not_t_minus_one_to_t")
    if not _count(declared):
        reasons.append("declared_total_missing_or_invalid")
    if not isinstance(raw, list):
        reasons.append("full_pool_rows_missing_top20_is_not_complete")
        raw = []
    if present and _count(declared) and len(raw) != declared:
        reasons.append("declared_total_row_count_mismatch")
    if payload.get("asof") != asof:
        reasons.append("payload_asof_mismatch")
    if "date" in limit and _day(limit["date"], compact=True) != asof:
        reasons.append("limit_pool_date_mismatch")
    seen: set[str] = set()
    duplicates: set[str] = set()
    invalid_rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            invalid_rows.append({"index": index, "reason": "row_not_object"})
            continue
        code = item.get("code")
        if not _code(code):
            invalid_rows.append({"index": index, "reason": "code_not_canonical_six_digit_a_share"})
        else:
            if code in seen:
                duplicates.add(code)
            seen.add(code)
        streak = item.get("streak")
        if kind == "zt" and (type(streak) is not int or streak < 1):
            invalid_rows.append({"index": index, "reason": "streak_must_be_positive_integer"})
        elif kind != "zt" and streak is not None and (type(streak) is not int or streak < 0):
            # ZB zttj.ct is not a current positive closing streak; real saved
            # responses include zero. It must not be interpreted as a ZT run.
            invalid_rows.append({"index": index, "reason": "non_zt_streak_count_invalid"})
        for field in ("asof", "date"):
            if field in item and _day(item[field], compact=True) != asof:
                invalid_rows.append({"index": index, "reason": "row_date_mismatch"})
    if duplicates:
        reasons.append("duplicate_security_codes")
    if invalid_rows:
        reasons.append("invalid_pool_rows")
    structurally_complete = not reasons
    source_meta = _pool_source(payload, kind)
    source = _source_checks(source_meta, asof=asof, declared=declared)
    independent_source = kind != YESTERDAY_POOL or source_meta.get("source_id") == YESTERDAY_SOURCE
    envelope_fresh = kind != YESTERDAY_POOL or section.get("status") == "fresh"
    if not independent_source:
        source["reasons"].append("yesterday_performance_independent_source_missing_or_wrong")
    if not envelope_fresh:
        source["reasons"].append("yesterday_performance_not_fresh")
    verified = (structurally_complete and source["source_status"] == "fresh"
                and source["raw_source_hash_present"] and source["source_date_status"] == "VERIFIED"
                and source["coverage_status"] == "VERIFIED" and independent_source and envelope_fresh)
    source_mismatch = source["source_date_status"] == "MISMATCH" or source["coverage_status"] == "MISMATCH"
    result = {
        "status": "complete" if verified else "invalid" if not structurally_complete or source_mismatch else "partial",
        "evidence": "descriptive", "structurally_complete": structurally_complete,
        "verified_complete": verified, "declared_count": declared if _count(declared) else None,
        "row_count": len(raw) if present else None, "unique_count": len(seen),
        "duplicate_codes": sorted(duplicates), "invalid_rows": invalid_rows,
        "codes": sorted(seen), **{key: value for key, value in source.items() if key != "reasons"},
        "reasons": reasons + source["reasons"],
    }
    if kind == YESTERDAY_POOL:
        # Missing quotes are observations, not permission to remove members or
        # silently assume suspension. Keep them in the archived population.
        unavailable = sorted({row["code"] for row in raw if isinstance(row, Mapping) and _code(row.get("code"))
                              and not _quote_available(row.get("pct"))})
        result.update({"source_id": source_meta.get("source_id"), "window": "t-1_to_t",
                       "population_basis": "provider_t_day_view_not_prior_archive",
                       "quote_unavailable_codes": unavailable, "quote_unavailable_count": len(unavailable),
                       "quote_note": "Missing quotes remain members; suspension is not inferred."})
    return result


def _labels(payload: Mapping[str, Any], key: str, asof: str, zt: Mapping[str, Any]) -> dict[str, Any]:
    section = _mapping(_mapping(payload.get("limit_pools")).get(key))
    rows = section.get("rows")
    target = set(zt["codes"])
    matches: set[str] = set()
    extras: set[str] = set()
    invalid = 0
    reasons: list[str] = []
    valid_date = _day(section.get("asof")) == asof
    if not valid_date:
        reasons.append("label_asof_missing_or_mismatch")
    if section.get("status") not in ("fresh", "partial", "stale"):
        reasons.append("label_source_not_available")
    if not isinstance(rows, list):
        reasons.append("label_rows_missing")
        rows = []
    field = "reason" if key == "reasons" else "topic_label"
    for item in rows:
        if not isinstance(item, Mapping) or not _code(item.get("code")):
            invalid += 1
            continue
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            invalid += 1
            continue
        if any(name in item and _day(item[name]) != asof for name in ("asof", "date")):
            invalid += 1
            continue
        code = item["code"]
        if code not in target:
            extras.add(code)
        elif valid_date and section.get("status") in ("fresh", "partial", "stale"):
            matches.add(code)
    missing = target - matches
    if missing:
        reasons.append("labels_missing_for_pool_members")
    if extras:
        reasons.append("labels_include_non_pool_members")
    if invalid:
        reasons.append("invalid_label_rows")
    source = _source_checks(_mapping(section.get("source")), asof=asof, declared=None)
    # Label coverage is measured by stock membership; pagination receipts are
    # not fabricated from the coverage ratio. Source date remains independent.
    structurally_covered = zt["structurally_complete"] and valid_date and not missing and not extras and not invalid
    known_empty = structurally_covered and not target and isinstance(section.get("rows"), list)
    status = "not_available" if not section or section.get("status") not in ("fresh", "partial", "stale") else "partial"
    if (structurally_covered and section.get("status") == "fresh" and source["source_date_status"] == "VERIFIED"
            and source["raw_source_hash_present"] and source["source_status"] == "fresh"):
        status = "fresh"
    if section.get("status") == "stale" and valid_date:
        status = "stale"
    return {
        "status": status, "asof": section.get("asof"), "asof_match": valid_date,
        "evidence": "descriptive", "target_count": zt["declared_count"],
        "observed_target_count": len(target), "row_count": len(rows),
        "matched_count": len(matches), "missing_count": len(missing),
        "matched_codes": sorted(matches), "missing_codes": sorted(missing), "extra_codes": sorted(extras),
        "invalid_count": invalid, "coverage_ratio": len(matches) / len(target) if target and zt["structurally_complete"] else None,
        "structurally_covered": structurally_covered, "known_empty": known_empty,
        "source_date_status": source["source_date_status"],
        "source_coverage_status": "NOT_ESTABLISHED",
        "reasons": reasons + [r for r in source["reasons"] if r != "source_pagination_or_coverage_not_verified"],
    }


def _calendar_proof(payload: Mapping[str, Any], prior: Mapping[str, Any], asof: str, prior_asof: str | None) -> list[str]:
    reasons: list[str] = []
    calendar, earlier = _mapping(payload.get("calendar")), _mapping(prior.get("calendar"))
    if not prior_asof or prior_asof >= asof:
        reasons.append("prior_asof_missing_or_not_earlier")
    if prior.get("asof") != prior_asof:
        reasons.append("prior_payload_asof_mismatch")
    if (calendar.get("calendar_status") != "provided" or calendar.get("asof_status") != "exchange_verified"
            or calendar.get("prior_status") != "exchange_verified" or calendar.get("prior_asof") != prior_asof):
        reasons.append("adjacent_exchange_sessions_not_verified_by_caller")
    if calendar.get("asof") is not None and calendar["asof"] != asof:
        reasons.append("calendar_asof_mismatch")
    current_hash = calendar.get("calendar_source_sha256")
    if not isinstance(current_hash, str) or not _HASH.fullmatch(current_hash):
        reasons.append("verified_calendar_hash_missing")
    if (earlier.get("calendar_status") != "provided" or earlier.get("asof_status") != "exchange_verified"
            or earlier.get("calendar_source_sha256") != current_hash):
        reasons.append("prior_calendar_proof_missing_or_different")
    return reasons


def _yesterday_membership(payload: Mapping[str, Any], prior: Any, *, asof: str, prior_asof: str | None,
                          yesterday: dict[str, Any]) -> dict[str, Any]:
    """Reconcile the T-day view against an independently archived T-1 pool."""
    result: dict[str, Any] = {"status": "not_available", "asof": asof, "prior_asof": prior_asof,
                              "basis": "independent_prior_zt_archive", "prior_count": None,
                              "matched_count": None, "missing_codes": [], "extra_codes": [], "reasons": []}
    if not isinstance(prior, Mapping):
        result["reasons"].append("prior_snapshot_missing")
        return result
    result["reasons"].extend(_calendar_proof(payload, prior, asof, prior_asof))
    prior_capture = _mapping(prior.get("daily_capture"))
    if (_mapping(prior_capture.get("quality")).get("core_complete") is not True
            or _mapping(prior_capture.get("raw_verification")).get("zt") is not True):
        result["reasons"].append("prior_zt_archive_raw_verification_not_established")
    if prior_asof is None:
        return result
    prior_zt = _pool(prior, "zt", prior_asof)
    if not prior_zt["verified_complete"]:
        result["reasons"].append("prior_zt_pool_not_verified_complete")
    if result["reasons"]:
        return result
    expected, observed = set(prior_zt["codes"]), set(yesterday["codes"])
    missing, extra = sorted(expected - observed), sorted(observed - expected)
    result.update({"prior_count": len(expected), "matched_count": len(expected & observed),
                   "missing_codes": missing, "extra_codes": extra})
    if missing:
        result["reasons"].append("prior_zt_members_missing_from_yesterday_performance")
    if extra:
        result["reasons"].append("yesterday_performance_members_absent_from_prior_zt")
    if missing or extra:
        # A provider may omit suspended securities or change its universe.
        # Neither explanation is silently inferred; expose the discrepancy.
        yesterday["verified_complete"] = False
        yesterday["status"] = "partial" if yesterday["structurally_complete"] else "invalid"
        yesterday["reasons"].extend(result["reasons"])
        result["status"] = "mismatch"
    elif yesterday["verified_complete"]:
        result["status"] = "matched"
    else:
        result["reasons"].append("yesterday_performance_not_verified_complete")
    return result


def _progression(payload: Mapping[str, Any], prior: Any, *, asof: str, prior_asof: str | None,
                 current_zt: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "not_available", "asof": asof, "prior_asof": prior_asof,
                              "window": "t+1", "evidence": "descriptive", "rows": [], "reasons": [],
                              "adjacency_evidence": "caller_calendar_metadata_only"}
    if not isinstance(prior, Mapping):
        result["reasons"].append("prior_snapshot_missing")
        return result
    result["reasons"].extend(_calendar_proof(payload, prior, asof, prior_asof))
    if prior_asof is None:
        return result
    prior_zt = _pool(prior, "zt", prior_asof)
    if not current_zt["verified_complete"]:
        result["reasons"].append("current_zt_pool_not_verified_complete")
    if not prior_zt["verified_complete"]:
        result["reasons"].append("prior_zt_pool_not_verified_complete")
    if result["reasons"]:
        return result
    current_rows = payload["limit_pools"]["pool_rows"]["zt"]
    prior_rows = prior["limit_pools"]["pool_rows"]["zt"]
    current = {row["code"]: row for row in current_rows}
    eligible: dict[int, int] = {}
    advanced: dict[int, int] = {}
    for row in prior_rows:
        streak = row["streak"]
        eligible[streak] = eligible.get(streak, 0) + 1
        following = current.get(row["code"])
        if following is not None and following["streak"] == streak + 1:
            advanced[streak] = advanced.get(streak, 0) + 1
        elif following is not None and following["streak"] > streak + 1:
            result["reasons"].append("inconsistent_streak_jump_between_adjacent_sessions")
    if result["reasons"]:
        return result
    result["rows"] = [
        {"from_streak": streak, "to_streak": streak + 1, "eligible_count": count,
         "advanced_count": advanced.get(streak, 0), "rate": advanced.get(streak, 0) / count,
         "asof": asof, "window": "t+1"} for streak, count in sorted(eligible.items())
    ]
    result["status"] = "fresh"
    result["population_status"] = "empty_verified_prior_pool" if not eligible else "verified_complete_zt_pair"
    return result


def assess_eod_payload(payload: Any, *, asof: str, prior_payload: Any = None,
                       prior_asof: str | None = None) -> dict[str, Any]:
    """Assess normalized saved payloads without modifying historical results.

    New provider receipts belong in ``limit_pools.pool_sources.<zt|zb|dt>``
    and ``limit_pools.yesterday_performance.source``:
    status=fresh, asof, asof_status=source_verified, raw_sha256, and
    coverage={status:complete,declared_total,pages_expected,pages_received}.
    These are supplied assertions checked for consistency, not a substitute
    for raw-response hash verification performed by the archive.
    """
    if _day(asof) != asof or not isinstance(asof, str):
        raise ValueError("asof must be YYYY-MM-DD")
    if prior_asof is not None and _day(prior_asof) != prior_asof:
        raise ValueError("prior_asof must be YYYY-MM-DD")
    value = _mapping(payload)
    pools = {kind: _pool(value, kind, asof) for kind in POOLS}
    pools[YESTERDAY_POOL] = _pool(value, YESTERDAY_POOL, asof)
    pools[YESTERDAY_POOL]["prior_membership"] = _yesterday_membership(
        value, prior_payload, asof=asof, prior_asof=prior_asof, yesterday=pools[YESTERDAY_POOL])
    labels = {key: _labels(value, key, asof, pools["zt"]) for key in ("reasons", "topics")}
    progression = _progression(value, prior_payload, asof=asof, prior_asof=prior_asof, current_zt=pools["zt"])
    # Preserve the v1 three-pool flag and two-ZT progression semantics. A
    # separate fourth-pool contract strengthens sealing, not old conclusions.
    core_complete = all(pools[kind]["verified_complete"] for kind in POOLS)
    membership_matched = pools[YESTERDAY_POOL]["prior_membership"]["status"] == "matched"
    four_pool_complete = core_complete and pools[YESTERDAY_POOL]["verified_complete"] and membership_matched
    reasons = []
    if not isinstance(payload, Mapping):
        reasons.append("payload_not_object")
    if value.get("asof") != asof:
        reasons.append("payload_asof_mismatch")
    if not core_complete:
        reasons.append("one_or_more_pools_not_verified_complete")
    if not pools[YESTERDAY_POOL]["verified_complete"]:
        reasons.append("yesterday_performance_not_verified_complete")
    if not membership_matched:
        reasons.append("yesterday_performance_prior_membership_not_matched")
    if any(label["status"] != "fresh" for label in labels.values()):
        reasons.append("reason_or_topic_coverage_incomplete_or_unverified")
    status = "ready" if not reasons else "partial"
    if not isinstance(payload, Mapping) or value.get("asof") != asof:
        status = "error"
    return {
        "schema_version": SCHEMA, "asof": asof, "status": status,
        "evidence": "descriptive", "pools": pools, "labels": labels, "progression": progression,
        "core_complete": core_complete, "three_pool_complete": core_complete, "four_pool_complete": four_pool_complete,
        "core_complete_scope": "zt_zb_dt_legacy_v1",
        "structurally_complete": all(pools[kind]["structurally_complete"] for kind in POOLS),
        "four_pool_structurally_complete": all(pool["structurally_complete"] for pool in pools.values()),
        "reasons": reasons, "publication_eligible": False,
        "proof_scope": "metadata_consistency_only_archive_must_verify_raw_bytes_and_calendar",
        "model_input_eligible": False,
    }
