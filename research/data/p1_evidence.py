"""Offline, append-only evidence imports for descriptive P1 research.

This is an independently implemented evidence contract, informed by Vibe's
raw/hash/catalog design. It imports saved responses, never fetches endpoints,
never certifies point-in-time availability, and never enables publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .market_context import build_snapshot
from .p1_provider_parsers import parse_provider_payload
from .p1_source_catalog import get_source, policy_problems

SCHEMA = "p1-source-evidence.v1"
PARSER_VERSION = "p1-provider-parsers.v1"
SUPPORTED = frozenset({
    "eastmoney_fund_flow_history", "eastmoney_dragon_tiger", "eastmoney_lockup_expiry",
})
MAX_RAW_BYTES = 16 * 1024 * 1024
CN = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parser_hash() -> str:
    # Covers both field parsing and the request/time/envelope guards.
    files = [Path(__file__).with_name("p1_provider_parsers.py"), Path(__file__)]
    return _sha(_canonical({path.name: _sha(path.read_bytes().replace(b"\r\n", b"\n")) for path in files}))


def _observation_hash(record: dict[str, Any]) -> str:
    # The observation identity must not move when the same response is
    # imported later. A changed raw body/parser/catalog/origin is a revision.
    excluded = {"archived_at", "available_at", "observation_sha256", "record_sha256"}
    return _sha(_canonical({key: value for key, value in record.items() if key not in excluded}))


def _date(value: str) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("asof must be a canonical ISO date")
    return value


def _time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must include timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(UTC)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _json(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_RAW_BYTES:
        raise ValueError("response is empty or exceeds 16 MiB")
    result = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("response must be a JSON object")
    _canonical(result)  # Also rejects overflow such as 1e9999 in unused fields.
    return result


def read_response(path: str | Path) -> bytes:
    """Bound the read as well as the decode, including non-regular inputs."""
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_RAW_BYTES + 1)
    if not raw or len(raw) > MAX_RAW_BYTES:
        raise ValueError("response is empty or exceeds 16 MiB")
    return raw


def load_payload(path: str | Path) -> dict[str, Any]:
    return _json(read_response(path))


def _url(value: str, source: dict[str, Any]) -> None:
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.username or parts.password or parts.fragment:
        raise ValueError("source_url must be an unauthenticated HTTPS endpoint")
    allowed = [urlsplit(url) for url in source["source_urls"]]
    if not any(parts.netloc == item.netloc and parts.path.rstrip("/") == item.path.rstrip("/") for item in allowed):
        raise ValueError("source_url is not a registered endpoint")
    if any(key.lower() in {"token", "access_token", "api_key", "apikey", "key", "password", "secret", "authorization"} for key in parse_qs(parts.query)):
        raise ValueError("source_url must not contain credentials")


def _validate_timeline(source_id: str, asof: str, fetched_at: str, archived_at: str) -> datetime:
    asof = _date(asof)
    fetched = _time(fetched_at)
    if fetched > _time(archived_at):
        raise ValueError("fetched_at is in the future")
    local_day = fetched.astimezone(CN).date().isoformat()
    if asof > local_day:
        raise ValueError("asof is later than retrieval day")
    if source_id == "eastmoney_lockup_expiry" and asof != local_day:
        raise ValueError("unlock schedule is a retrieval-day snapshot, not historical PIT")
    return fetched


def _parse_saved(source_id: str, payload: dict[str, Any], *, source_url: str, asof: str, subject: str | None) -> dict[str, Any]:
    """Reject explicit query conflicts; an absent query is not request proof."""
    query = parse_qs(urlsplit(source_url).query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("ambiguous duplicate request parameters")
    params = {key: values[0] for key, values in query.items()}
    request_confirmed = False
    if source_id == "eastmoney_fund_flow_history":
        expected_secid = ("1." if subject and subject.startswith("sh") else "0.") + (subject or "")[2:]
        if "secid" in params and params["secid"] != expected_secid:
            raise ValueError("request secid conflicts with subject")
        if "klt" in params and params["klt"] != "101":
            raise ValueError("request period is not daily")
        if "fields2" in params:
            fields = params["fields2"].split(",")
            if len(fields) not in {7, 13, 15} or fields != [f"f{n}" for n in range(51, 51 + len(fields))]:
                raise ValueError("request field order does not match parser")
            data = payload.get("data")
            if isinstance(data, dict) and isinstance(data.get("klines"), list):
                for row in data["klines"]:
                    if isinstance(row, str) and len(row.split(",")) != len(fields):
                        raise ValueError("response width conflicts with requested field layout")
        request_confirmed = "fields2" in params and "secid" in params
    else:
        expected_reports = {"RPT_DAILYBILLBOARD_DETAILSNEW"} if source_id == "eastmoney_dragon_tiger" else {"RPT_LIFT_STAGE"}
        if "reportName" in params and params["reportName"] not in expected_reports:
            raise ValueError("request reportName conflicts with source")
        filter_text = params.get("filter", "")
        if "SECURITY_CODE" in filter_text.upper():
            codes = re.findall(r"SECURITY_CODE\s*=\s*['\"](\d{6})['\"]", filter_text, re.IGNORECASE)
            if not subject or codes != [subject[2:]]:
                raise ValueError("request security filter conflicts with subject or is unrecognized")
        # Even a well-formed provider query is caller-declared; its filtered
        # result must never become a claim about the whole A-share universe.
        request_confirmed = "reportName" in params
    section = parse_provider_payload(source_id, payload, asof=asof, subject=subject)
    section["metadata"]["request_evidence"] = "caller_declared_query" if request_confirmed else "NOT_ESTABLISHED"
    section["metadata"]["request_scope"] = "single_subject" if subject else "observed_response_set_not_full_market"
    if not request_confirmed and section["status"] in {"fresh", "partial"}:
        section["status"] = "partial"
        section["stale_reason"] = "; ".join(filter(None, [section.get("stale_reason"), "request_layout_or_scope_unverified"]))
    return section


def _inside(root: Path, relative: str) -> Path:
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()) or result == root.resolve():
        raise ValueError("evidence path escapes archive")
    return result


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError(f"immutable evidence conflict: {path.name}") from None


def archive_response(
    root: str | Path,
    raw: bytes,
    *,
    source_id: str,
    asof: str,
    fetched_at: str,
    source_url: str,
    subject: str | None = None,
    origin: str = "captured_response",
) -> Path:
    """Save exact bytes plus a hashed derived record; neither is a live snapshot.

    ``fetched_at`` is caller-declared. ``archived_at`` is generated here and is
    never retroactively set to the historical date. Future scheduled unlocks
    are permitted, but today's unlock response cannot masquerade as a past
    knowledge snapshot. Fixture imports always remain fixture imports.
    """
    if source_id not in SUPPORTED:
        raise ValueError("source has no evidence-import parser")
    if origin not in {"captured_response", "fixture"}:
        raise ValueError("origin must be captured_response or fixture; live is not an import mode")
    source = get_source(source_id)
    _url(source_url, source)
    asof = _date(asof)
    archived_at = _now()
    fetched = _validate_timeline(source_id, asof, fetched_at, archived_at)
    parsed = _json(raw)
    section = _parse_saved(source_id, parsed, source_url=source_url, asof=asof, subject=subject)
    raw_hash = _sha(raw)
    record = {
        "schema_version": SCHEMA,
        "parser_version": PARSER_VERSION,
        "parser_sha256": _parser_hash(),
        "parser_hash_kind": "sha256_lf_normalized_sources",
        "source_id": source_id,
        "source_url": source_url,
        "asof": asof,
        "subject": subject,
        "fetched_at": fetched.isoformat(),
        "fetched_at_evidence": "caller_declared",
        "archived_at": archived_at,
        "available_at": archived_at,
        "availability_scope": "local_archive_only_not_publication",
        "public_first_published_at": None,
        "pit_status": "NOT_ESTABLISHED",
        "origin": origin,
        "raw_ref": f"raw/{raw_hash}.json",
        "raw_sha256": raw_hash,
        "raw_size_bytes": len(raw),
        "catalog_entry": source,
        "catalog_entry_sha256": _sha(_canonical(source)),
        "publication_eligible": False,
        "publication_blockers": ["offline_import_not_live", *policy_problems(source_id, purpose="publish")],
        "section": section,
    }
    record["observation_sha256"] = _observation_hash(record)
    record["record_sha256"] = _sha(_canonical(record))
    archive = Path(root).resolve()
    raw_path = _inside(archive, record["raw_ref"])
    record_path = _inside(archive, f"records/{record['record_sha256']}.json")
    record_bytes = _canonical(record) + b"\n"
    if len(record_bytes) > MAX_RAW_BYTES:
        raise ValueError("normalized evidence record exceeds 16 MiB")
    observation_path = _inside(archive, f"observations/{record['observation_sha256']}.json")
    if observation_path.exists():
        index = load_payload(observation_path)
        first_path = _inside(archive, f"records/{index.get('record_sha256')}.json")
        first = load_record(first_path)
        if first["observation_sha256"] != record["observation_sha256"]:
            raise ValueError("observation index mismatch")
        return first_path
    # Validate everything before any write. A crash may leave an unreferenced
    # raw blob; it cannot leave a record claiming a raw blob that was not saved.
    _write_once(raw_path, raw)
    _write_once(record_path, record_bytes)
    _write_once(observation_path, _canonical({"record_sha256": record["record_sha256"]}) + b"\n")
    return record_path


def load_record(path: str | Path) -> dict[str, Any]:
    """Check both content hashes and replay the parser before consuming evidence."""
    record_path = Path(path).resolve()
    if record_path.parent.name != "records":
        raise ValueError("record must be inside archive/records")
    record = load_payload(record_path)
    if record.get("schema_version") != SCHEMA or record.get("parser_version") != PARSER_VERSION:
        raise ValueError("unsupported evidence or parser version")
    if record.get("parser_sha256") != _parser_hash():
        raise ValueError("parser implementation changed; re-import as a new receipt without overwriting evidence")
    digest = record.get("record_sha256")
    unsigned = {key: value for key, value in record.items() if key != "record_sha256"}
    if _sha(_canonical(unsigned)) != digest or record_path.name != f"{digest}.json":
        raise ValueError("record hash mismatch")
    if record.get("observation_sha256") != _observation_hash(record):
        raise ValueError("observation hash mismatch")
    raw_hash = record.get("raw_sha256")
    if record.get("raw_ref") != f"raw/{raw_hash}.json":
        raise ValueError("invalid raw reference")
    raw_path = _inside(record_path.parent.parent, record["raw_ref"])
    raw = read_response(raw_path)
    if _sha(raw) != raw_hash or len(raw) != record.get("raw_size_bytes"):
        raise ValueError("raw response hash mismatch")
    if record.get("publication_eligible") is not False or record.get("pit_status") != "NOT_ESTABLISHED":
        raise ValueError("import cannot certify publication or PIT")
    if record.get("origin") not in {"captured_response", "fixture"}:
        raise ValueError("invalid evidence origin")
    if _time(record["available_at"]) != _time(record["archived_at"]) or _time(record["fetched_at"]) > _time(record["archived_at"]):
        raise ValueError("invalid availability timeline")
    _validate_timeline(record["source_id"], record["asof"], record["fetched_at"], record["archived_at"])
    source = get_source(record["source_id"])
    _url(record["source_url"], source)
    if _sha(_canonical(record["catalog_entry"])) != record.get("catalog_entry_sha256"):
        raise ValueError("catalog evidence hash mismatch")
    expected = _parse_saved(record["source_id"], _json(raw), source_url=record["source_url"], asof=record["asof"], subject=record["subject"])
    if _canonical(expected) != _canonical(record["section"]):
        raise ValueError("derived section differs from raw evidence")
    return record


def build_research_context(
    payload: dict[str, Any],
    records: list[str | Path],
    *,
    available_at_cutoff: str | None = None,
) -> dict[str, Any]:
    """Attach supplemental P1 cards to a *new*, research-only context artifact.

    Never replace the base payload, the already sealed dates, current-day
    sources, progression, or the LPPL inputs. Asset-level series remain keyed
    by source AND subject; an individual stock's flow is not market flow.
    """
    if not records:
        raise ValueError("at least one evidence record is required")
    if payload.get("schema_version") == "market-context.v1":
        raise ValueError("supply the market payload, not a sealed context")
    asof = _date(payload.get("asof"))
    now = _now()
    cutoff = _time(available_at_cutoff or now)
    if cutoff > _time(now):
        raise ValueError("availability cutoff cannot be in the future")
    verified = [load_record(path) for path in records]
    supplemental = {}
    receipt_hashes = []
    for record in verified:
        if record["asof"] != asof:
            raise ValueError("evidence asof does not match market payload")
        key = f"{record['source_id']}:{record['subject'] or 'observed_set'}"
        if key in supplemental:
            raise ValueError("conflicting source/subject records; select one explicit revision")
        section = deepcopy(record["section"])
        provenance = {
            field: record[field] for field in (
                "source_id", "source_url", "asof", "subject", "fetched_at", "fetched_at_evidence",
                "available_at", "availability_scope", "raw_sha256", "record_sha256", "origin",
                "pit_status", "public_first_published_at", "publication_eligible", "publication_blockers",
                "catalog_entry_sha256",
            )
        }
        if _time(record["available_at"]) > cutoff:
            section = {"status": "not_available", "asof": asof, "window": section.get("window"), "rows": [], "stale_reason": "evidence_not_available_at_cutoff", "evidence": "descriptive"}
        section["source"] = provenance
        supplemental[key] = section
        receipt_hashes.append(record["record_sha256"])
    # A plain saved payload has no trusted historical availability receipt.
    # Its first defensible local availability in this operation is now, even
    # when its declared generated_at is historical. Do not leak it into an
    # earlier knowledge cutoff while only masking the supplemental cards.
    base_available = cutoff >= _time(now)
    base_payload = deepcopy(payload) if base_available else {"asof": asof, "generated_at": None}
    context = build_snapshot(base_payload, requested_at=now)
    context["p1"]["supplemental_sources"] = supplemental
    context["run_mode"] = "research_import"
    context["publication_eligible"] = False
    context["evidence_import"] = {
        "schema_version": "p1-evidence-import.v1",
        "built_at": now,
        "available_at_cutoff": cutoff.isoformat(),
        "base_payload_sha256": _sha(_canonical(payload)),
        "base_available_at": now,
        "base_availability_status": "local_build_only" if base_available else "not_available_at_cutoff",
        "record_sha256s": sorted(receipt_hashes),
        "contains_fixture": any(record["origin"] == "fixture" for record in verified),
        "publication_eligible": False,
        "pit_status": "NOT_ESTABLISHED",
        "notes": ["Offline research imports are not live EOD snapshots or historical first-visible predictions."],
    }
    if not base_available or any(section["status"] != "fresh" for section in supplemental.values()):
        context["status"] = "partial"
        context["stale_reason"] = "one or more base or supplemental sources are incomplete or unavailable"
    context.pop("snapshot_sha256", None)
    context["snapshot_sha256"] = _sha(_canonical(context))
    return context


def write_research_context(path: str | Path, context: dict[str, Any]) -> None:
    if context.get("run_mode") != "research_import" or context.get("publication_eligible") is not False:
        raise ValueError("only unpublished research imports may be written")
    _write_once(Path(path), _canonical(context) + b"\n")
