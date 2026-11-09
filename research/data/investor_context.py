"""Pure investor-information snapshots, independent of LPPL inputs and scores.

Inputs are already captured, dated attachments. This module never fetches,
summarizes articles, calls an LLM, or establishes historic public availability.
Permission declarations must come from a separately documented source review.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "investor-context.v1"
SECTIONS = (
    "news", "announcements", "reports", "events", "profile", "financials",
    "shareholders", "unlock", "dragon_tiger", "fund_flow", "topics", "ladder", "progression",
)
STATUSES = frozenset({"fresh", "partial", "stale", "error", "not_available", "blocked"})
STOCK_SECTIONS = frozenset({"profile", "financials", "shareholders", "unlock", "dragon_tiger", "fund_flow"})
INDEX_SECTIONS = frozenset({"news", "announcements", "reports"})
CN = timezone(timedelta(hours=8))
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def valid_symbol(value: Any) -> bool:
    """A-share/index canonical spelling; membership is not certified here."""
    if not isinstance(value, str) or not re.fullmatch(r"(?:sh|sz|bj)\d{6}", value):
        return False
    exchange, code = value[:2], value[2:]
    return ((exchange == "sh" and code.startswith(("6", "000")))
            or (exchange == "sz" and code.startswith(("0", "3")))
            or (exchange == "bj" and code.startswith(("4", "8", "92"))))


def _day(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must be YYYY-MM-DD")
    return date.fromisoformat(value).isoformat()


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("timestamp requires ISO date, time and timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.astimezone(UTC)


def _stamp(value: Any) -> str:
    return _time(value).isoformat().replace("+00:00", "Z")


def _text(value: Any, *, limit: int = 1000, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("invalid text field")
    return value.strip()


def _url(value: Any) -> str:
    text = _text(value, limit=2048, required=True)
    assert text is not None
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or "\\" in text:
        raise ValueError("link must be an HTTPS URL without credentials")
    try:
        _ = parts.port
    except ValueError as exc:
        raise ValueError("invalid URL port") from exc
    return text


def _number(value: Any, *, integer: bool = False, nonnegative: bool = False) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric fields require JSON numbers, not strings or booleans")
    try:
        finite = math.isfinite(value)
    except OverflowError as exc:
        raise ValueError("numeric overflow") from exc
    if not finite or (nonnegative and value < 0) or (integer and (not isinstance(value, int) or value < 0)):
        raise ValueError("invalid numeric field")
    return value


def _publication_allowed(source: Mapping[str, Any]) -> bool:
    if (source.get("origin") in {"fixture", "research_import"}
            or source.get("run_mode") in {"fixture", "research_import"}
            or source.get("publication_eligible") is False or "evidence_import" in source):
        return False
    review = source.get("publication")
    refs = review.get("evidence_refs") if isinstance(review, Mapping) else None
    return (isinstance(review, Mapping) and review.get("status") == "verified"
            and isinstance(refs, list) and bool(refs)
            and all(isinstance(ref, str) and bool(ref.strip()) for ref in refs))


def _source(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("source metadata missing")
    digest = raw.get("raw_sha256")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ValueError("source raw_sha256 missing or invalid")
    result = {
        "source_id": _text(raw.get("source_id"), limit=120, required=True),
        "source_url": _url(raw.get("source_url")), "raw_sha256": digest,
        "available_at": _stamp(raw.get("available_at")),
        "availability_evidence": "attachment_declared_not_historical_publication_proof",
        "publication": deepcopy(raw.get("publication")) if isinstance(raw.get("publication"), Mapping) else {"status": "NOT_ESTABLISHED", "evidence_refs": []},
    }
    if raw.get("fetched_at") is not None:
        result["fetched_at"] = _stamp(raw["fetched_at"])
        if _time(result["fetched_at"]) > _time(result["available_at"]):
            raise ValueError("source availability precedes retrieval")
    # Only the review's explicit status and references travel to consumers.
    review = result["publication"]
    result["publication"] = {"status": review.get("status", "NOT_ESTABLISHED"), "evidence_refs": review.get("evidence_refs", [])}
    for key in ("origin", "run_mode", "publication_eligible"):
        if key in raw:
            result[key] = raw[key]
    if "evidence_import" in raw:
        result["evidence_import"] = True
    _canonical(result)
    return result


def _empty(asof: str, reason: str, *, status: str = "not_available", source: Any = None) -> dict[str, Any]:
    return {"status": status, "asof": asof, "rows": [], "source": source,
            "stale_reason": reason, "evidence": "descriptive", "sample_size": 0,
            "publication_eligible": False, "coverage_status": "NOT_ESTABLISHED"}


def _normalize_row(kind: str, raw: Any, *, source: Mapping[str, Any], asof: str,
                   symbol: str | None, cutoff: datetime) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        raise ValueError("row must be an object")
    available = _stamp(raw.get("available_at", source["available_at"]))
    known = _stamp(raw.get("known_at", available))
    if _time(known) > _time(available):
        raise ValueError("known_at must not follow available_at")
    # The whole response is unavailable until it was captured, even if a row
    # carries an earlier provider publication timestamp.
    if max(_time(available), _time(source["available_at"]), _time(known)) > cutoff:
        return None
    row: dict[str, Any] = {"available_at": available, "known_at": known}
    raw_symbol = raw.get("symbol")
    if raw_symbol is not None and not valid_symbol(raw_symbol):
        raise ValueError("invalid row symbol")
    if symbol is not None:
        if raw_symbol != symbol:
            raise ValueError("row symbol does not match requested asset")
        row["symbol"] = symbol
    elif raw_symbol is not None:
        row["symbol"] = raw_symbol
    if kind in STOCK_SECTIONS and symbol is None:
        raise ValueError("stock section requires a requested symbol")
    if raw.get("published_at") is not None:
        published = _stamp(raw["published_at"])
        if _time(published) > _time(available):
            raise ValueError("publication follows row availability")
        if _time(published) > cutoff or _time(published).astimezone(CN).date().isoformat() > asof:
            return None
        row["published_at"] = published
    if kind in INDEX_SECTIONS:
        if "published_at" not in row:
            raise ValueError("index row publication timestamp missing")
        row.update(title=_text(raw.get("title"), limit=500, required=True),
                   source=_text(raw.get("source"), limit=200, required=True), url=_url(raw.get("url")))
    elif kind == "events":
        row.update(title=_text(raw.get("title"), limit=500, required=True),
                   event_date=_day(raw.get("event_date")), url=_url(raw.get("url")))
    else:
        text_fields = {
            "profile": ("name", "industry", "region", "description"),
            "financials": ("metric", "unit", "currency", "statement_type"),
            "shareholders": ("holder_name",), "unlock": ("name", "type", "unit"),
            "dragon_tiger": ("name", "reason"), "fund_flow": (),
            "topics": ("topic_label",), "ladder": ("name", "topic_label", "limit_time"),
            "progression": (),
        }[kind]
        for key in text_fields:
            row[key] = _text(raw.get(key), limit=1200 if key == "description" else 500)
        identifying_text = {"profile": "name", "financials": "metric", "shareholders": "holder_name", "topics": "topic_label"}.get(kind)
        if identifying_text and row.get(identifying_text) is None:
            raise ValueError("row identifying field missing")
        numeric_fields = {
            "profile": (), "financials": ("value",),
            "shareholders": ("shares", "ownership_pct", "change_shares"),
            "unlock": ("quantity", "ratio_pct"),
            "dragon_tiger": ("net_buy", "buy_amount", "sell_amount", "turnover_pct"),
            "fund_flow": ("main_net", "small_net", "medium_net", "large_net", "super_net",
                          "main_pct", "small_pct", "medium_pct", "large_pct", "super_pct"),
            "topics": ("count",), "ladder": ("streak",),
            "progression": ("from_streak", "to_streak", "eligible_count", "advanced_count", "rate"),
        }[kind]
        counts = {"count", "streak", "from_streak", "to_streak", "eligible_count", "advanced_count"}
        for key in numeric_fields:
            row[key] = _number(raw.get(key), integer=key in counts)
        if kind == "profile":
            row["website"] = _url(raw["website"]) if raw.get("website") is not None else None
            row["listing_date"] = _day(raw["listing_date"]) if raw.get("listing_date") is not None else None
        if kind in {"financials", "shareholders"}:
            row["report_period"] = _day(raw.get("report_period"))
            if row["report_period"] > asof or "published_at" not in row:
                raise ValueError("report requires historical period and publication timestamp")
        if kind in {"fund_flow", "dragon_tiger", "ladder", "progression", "topics"}:
            observation = _day(raw.get("date", raw.get("event_date", asof)))
            if observation > asof:
                return None
            row["date"] = observation
        if kind == "unlock":
            row["event_date"] = _day(raw.get("event_date"))
            if row["event_date"] < asof:
                return None
            if row["quantity"] is not None and row["unit"] is None:
                raise ValueError("unlock quantity requires explicit unit")
        if kind == "progression":
            a, n, rate = row["advanced_count"], row["eligible_count"], row["rate"]
            if a is not None and n is not None and a > n:
                raise ValueError("advanced_count exceeds eligible_count")
            if rate is not None and not 0 <= rate <= 1:
                raise ValueError("progression rate must be a fraction")
            if rate is not None and (n in (None, 0) or a is None or not math.isclose(rate, a / n, abs_tol=1e-12)):
                raise ValueError("progression rate lacks matching counts")
        if raw.get("url") is not None:
            row["url"] = _url(raw["url"])
    # Recompute an index hash from permitted fields; don't certify a supplied
    # string as a content hash or accidentally retain article bodies/prompts.
    row["hash"] = _hash(row)
    return row


def _section(kind: str, raw: Any, *, asof: str, symbol: str | None,
             cutoff: datetime, purpose: str) -> dict[str, Any]:
    if raw is None:
        return _empty(asof, "source_not_connected")
    if not isinstance(raw, Mapping):
        return _empty(asof, "attachment_not_object", status="error")
    source = None
    try:
        if _day(raw.get("asof")) != asof:
            raise ValueError("attachment_asof_mismatch")
        if kind in STOCK_SECTIONS and raw.get("symbol") != symbol:
            raise ValueError("attachment_symbol_mismatch")
        status = raw.get("status", "fresh")
        if status not in STATUSES:
            raise ValueError("unsupported_section_status")
        source = _source(raw.get("source"))
        if _time(source["available_at"]) > cutoff:
            return _empty(asof, "source_not_available_at_cutoff", source=source)
        if kind == "profile" and _time(source["available_at"]).astimezone(CN).date().isoformat() > asof:
            return _empty(asof, "current_profile_cannot_backfill_historical_snapshot", source=source)
        permitted = _publication_allowed(source)
        if purpose == "publish" and not permitted:
            return _empty(asof, "source_publication_permission_not_verified", status="blocked", source=source)
        if status in {"blocked", "error", "not_available"}:
            return _empty(asof, str(raw.get("stale_reason") or status), status=status, source=source)
        raw_rows = raw.get("rows")
        if not isinstance(raw_rows, list):
            raise ValueError("rows_missing_or_not_array")
        if len(raw_rows) > 10000:
            raise ValueError("attachment_exceeds_row_budget")
        rows, errors, filtered = [], [], 0
        for index, item in enumerate(raw_rows):
            try:
                row = _normalize_row(kind, item, source=source, asof=asof, symbol=symbol, cutoff=cutoff)
                if row is None:
                    filtered += 1
                else:
                    rows.append(row)
            except ValueError as exc:
                errors.append({"index": index, "reason": str(exc)})
        reason = raw.get("stale_reason")
        if status == "stale" and not reason:
            reason = "source_declared_stale"
        if errors:
            status, reason = ("partial" if rows else "error"), "malformed_rows_rejected"
        elif raw_rows and not rows:
            status, reason = "not_available", "no_rows_available_at_requested_cutoff"
        elif filtered and status == "fresh":
            status, reason = "partial", "rows_outside_requested_time_filtered"
        coverage = raw.get("coverage_status", "NOT_ESTABLISHED")
        if coverage not in {"complete", "partial", "NOT_ESTABLISHED"}:
            raise ValueError("invalid_coverage_status")
        if coverage != "complete" and status == "fresh":
            status, reason = "partial", reason or "source_coverage_not_established"
        return {
            "status": status, "asof": asof, "rows": rows, "source": source,
            "stale_reason": reason, "evidence": "descriptive", "sample_size": len(rows),
            "publication_eligible": purpose == "publish" and permitted,
            "coverage_status": coverage, "filtered_count": filtered, "rejected_count": len(errors),
            "row_errors": errors, **({"symbol": symbol} if kind in STOCK_SECTIONS else {}),
            "vintage_status": "retrieved_after_asof" if _time(source["available_at"]).astimezone(CN).date().isoformat() > asof else "captured_on_or_before_asof",
        }
    except (ValueError, TypeError, OverflowError) as exc:
        return _empty(asof, str(exc), status="error", source=source)


def build_investor_context(
    *, asof: str, available_at_cutoff: str, symbol: str | None = None,
    attachments: Mapping[str, Any] | None = None, purpose: str = "research",
) -> dict[str, Any]:
    """Normalize supplied attachments; absent sources remain individually empty."""
    asof = _day(asof)
    cutoff = _time(available_at_cutoff)
    if asof > cutoff.astimezone(CN).date().isoformat():
        raise ValueError("snapshot asof cannot follow availability cutoff day")
    if symbol is not None and not valid_symbol(symbol):
        raise ValueError("symbol must be canonical sh/sz/bj plus six digits")
    if purpose not in {"research", "publish"}:
        raise ValueError("purpose must be research or publish")
    if attachments is not None and not isinstance(attachments, Mapping):
        raise ValueError("attachments must be a mapping")
    supplied = attachments or {}
    if set(supplied) - set(SECTIONS):
        raise ValueError("unknown investor section")
    sections = {kind: _section(kind, supplied.get(kind), asof=asof, symbol=symbol,
                               cutoff=cutoff, purpose=purpose) for kind in SECTIONS}
    statuses = {section["status"] for section in sections.values()}
    status = "fresh" if statuses == {"fresh"} else "partial"
    if all(not section["rows"] for section in sections.values()):
        status = "not_available"
    result = {
        "schema_version": SCHEMA, "kind": "investor_context", "asof": asof,
        "symbol": symbol, "purpose": purpose, "status": status,
        "available_at_cutoff": _stamp(available_at_cutoff), "evidence": "descriptive",
        "publication_eligible": purpose == "publish", "pit_status": "NOT_ESTABLISHED",
        "model_input_eligible": False, "sections": sections,
    }
    result["snapshot_sha256"] = _hash(result)
    return result


def validate_public_context(value: Any, *, asof: str, symbol: str | None,
                            available_at_cutoff: str) -> None:
    """Validate cached output before a public read; never upgrade research data."""
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA:
        raise ValueError("invalid investor context schema")
    if value.get("purpose") != "publish" or value.get("publication_eligible") is not True:
        raise ValueError("investor context is not approved for publication")
    if value.get("asof") != _day(asof) or value.get("symbol") != symbol:
        raise ValueError("investor context date or symbol mismatch")
    if symbol is not None and not valid_symbol(symbol):
        raise ValueError("invalid investor symbol")
    read_cutoff = _time(available_at_cutoff)
    cutoff = _time(value.get("available_at_cutoff"))
    if cutoff > read_cutoff:
        raise ValueError("context was built beyond the public-read cutoff")
    if asof > cutoff.astimezone(CN).date().isoformat():
        raise ValueError("snapshot asof follows stored availability cutoff")
    if value.get("model_input_eligible") is not False or value.get("evidence") != "descriptive":
        raise ValueError("invalid investor evidence boundary")
    digest = value.get("snapshot_sha256")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest) or _hash({k: v for k, v in value.items() if k != "snapshot_sha256"}) != digest:
        raise ValueError("investor context hash mismatch")
    sections = value.get("sections")
    if not isinstance(sections, Mapping) or set(sections) != set(SECTIONS):
        raise ValueError("investor context sections missing")
    for kind, section in sections.items():
        if not isinstance(section, Mapping) or section.get("status") not in STATUSES or section.get("asof") != asof:
            raise ValueError("invalid investor section")
        rows = section.get("rows")
        if not isinstance(rows, list):
            raise ValueError("invalid investor rows")
        if not rows:
            continue
        source = _source(section.get("source"))
        if not _publication_allowed(source) or section.get("publication_eligible") is not True:
            raise ValueError("section publication permission not verified")
        if kind == "profile" and _time(source["available_at"]).astimezone(CN).date().isoformat() > asof:
            raise ValueError("current profile cannot backfill a historical snapshot")
        if section.get("status") not in {"fresh", "partial", "stale"}:
            raise ValueError("unavailable section contains rows")
        for row in rows:
            normalized = _normalize_row(kind, row, source=source, asof=asof, symbol=symbol, cutoff=cutoff)
            if normalized is None or _canonical(normalized) != _canonical(row):
                raise ValueError("public section has invalid or unavailable rows")
