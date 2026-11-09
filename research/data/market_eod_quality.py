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
from typing import Any

SCHEMA = "market-eod-quality.v1"
POOLS = ("zt", "zb", "dt")
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


def _pool_source(payload: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    limit = _mapping(payload.get("limit_pools"))
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
    declared = limit.get(kind)
    row_map = _mapping(limit.get("pool_rows"))
    raw = row_map.get(kind)
    reasons: list[str] = []
    if not _count(declared):
        reasons.append("declared_total_missing_or_invalid")
    if not isinstance(raw, list):
        reasons.append("full_pool_rows_missing_top20_is_not_complete")
        raw = []
    present = isinstance(row_map.get(kind), list)
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
    source = _source_checks(_pool_source(payload, kind), asof=asof, declared=declared)
    verified = (structurally_complete and source["source_status"] == "fresh"
                and source["raw_source_hash_present"] and source["source_date_status"] == "VERIFIED"
                and source["coverage_status"] == "VERIFIED")
    source_mismatch = source["source_date_status"] == "MISMATCH" or source["coverage_status"] == "MISMATCH"
    return {
        "status": "complete" if verified else "invalid" if not structurally_complete or source_mismatch else "partial",
        "evidence": "descriptive", "structurally_complete": structurally_complete,
        "verified_complete": verified, "declared_count": declared if _count(declared) else None,
        "row_count": len(raw) if present else None, "unique_count": len(seen),
        "duplicate_codes": sorted(duplicates), "invalid_rows": invalid_rows,
        "codes": sorted(seen), **{key: value for key, value in source.items() if key != "reasons"},
        "reasons": reasons + source["reasons"],
    }


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

    New provider receipts belong in ``limit_pools.pool_sources.<zt|zb|dt>``:
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
    labels = {key: _labels(value, key, asof, pools["zt"]) for key in ("reasons", "topics")}
    progression = _progression(value, prior_payload, asof=asof, prior_asof=prior_asof, current_zt=pools["zt"])
    core_complete = all(pool["verified_complete"] for pool in pools.values())
    reasons = []
    if not isinstance(payload, Mapping):
        reasons.append("payload_not_object")
    if value.get("asof") != asof:
        reasons.append("payload_asof_mismatch")
    if not core_complete:
        reasons.append("one_or_more_pools_not_verified_complete")
    if any(label["status"] != "fresh" for label in labels.values()):
        reasons.append("reason_or_topic_coverage_incomplete_or_unverified")
    status = "ready" if not reasons else "partial"
    if not isinstance(payload, Mapping) or value.get("asof") != asof:
        status = "error"
    return {
        "schema_version": SCHEMA, "asof": asof, "status": status,
        "evidence": "descriptive", "pools": pools, "labels": labels, "progression": progression,
        "core_complete": core_complete,
        "structurally_complete": all(pool["structurally_complete"] for pool in pools.values()),
        "reasons": reasons, "publication_eligible": False,
        "proof_scope": "metadata_consistency_only_archive_must_verify_raw_bytes_and_calendar",
        "model_input_eligible": False,
    }
