"""Validation and append-only indexing for dated market-context snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SCHEMA_VERSION = "market-context.v1"
BUNDLE_SCHEMA_VERSION = "market-context-seed-bundle.v1"


class PersistenceError(ValueError):
    """Raised when an input cannot enter the controlled seed bundle."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _iso(value: Any) -> str:
    if not isinstance(value, str):
        raise PersistenceError("asof must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PersistenceError(f"invalid ISO date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise PersistenceError(f"non-canonical ISO date: {value!r}")
    return value


def _verified_calendar(calendar: Any, *, require_prior: bool = False) -> bool:
    if not isinstance(calendar, dict):
        return False
    if calendar.get("calendar_status") != "provided" or calendar.get("asof_status") != "exchange_verified":
        return False
    if not HASH_RE.fullmatch(str(calendar.get("calendar_source_sha256") or "")):
        return False
    return not require_prior or calendar.get("prior_status") == "exchange_verified"


def load_calendar_metadata(path: str | Path) -> dict[str, Any]:
    """Load a calendar artifact whose source has been explicitly verified."""

    calendar_path = Path(path)
    raw = calendar_path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("dates"), list) or not value["dates"]:
        raise PersistenceError("calendar artifact must contain a non-empty dates list")
    dates = [_iso(item) for item in value["dates"]]
    if dates != sorted(set(dates)):
        raise PersistenceError("calendar dates must be sorted and unique")
    if value.get("verification_status") != "exchange_verified":
        raise PersistenceError("calendar verification_status is not exchange_verified")
    source_hash = str(value.get("source_sha256") or "")
    if not HASH_RE.fullmatch(source_hash):
        raise PersistenceError("calendar source_sha256 is required")
    return {
        "dates": dates,
        "version": value.get("version"),
        "source_url": value.get("source_url"),
        "source_sha256": source_hash,
        "verification_status": value["verification_status"],
        "artifact_sha256": _sha(raw),
    }


def validate_snapshot(path: str | Path, calendar: dict[str, Any]) -> dict[str, Any]:
    """Validate one context file and return an immutable index record."""

    snapshot_path = Path(path)
    raw = snapshot_path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PersistenceError(f"invalid snapshot JSON: {snapshot_path.name}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise PersistenceError(f"unsupported snapshot schema: {snapshot_path.name}")
    asof = _iso(value.get("asof"))
    if value.get("run_mode") != "live" or value.get("status") not in {"fresh", "partial"}:
        raise PersistenceError(f"snapshot is not a live fresh/partial snapshot: {snapshot_path.name}")
    if value.get("evidence") != "descriptive":
        raise PersistenceError(f"snapshot evidence is not descriptive: {snapshot_path.name}")
    progression = value.get("history", {}).get("progression", {}) if isinstance(value.get("history"), dict) else {}
    if not _verified_calendar(value.get("calendar"), require_prior=isinstance(progression, dict) and progression.get("status") == "fresh"):
        raise PersistenceError(f"snapshot calendar is not exchange verified: {snapshot_path.name}")
    if asof not in calendar["dates"]:
        raise PersistenceError(f"snapshot date is absent from calendar: {asof}")
    source_hashes = sorted({
        str(meta.get("raw_sha256"))
        for meta in (value.get("sources") or {}).values()
        if isinstance(meta, dict) and HASH_RE.fullmatch(str(meta.get("raw_sha256") or ""))
    })
    if not source_hashes:
        raise PersistenceError(f"snapshot has no raw source hash: {snapshot_path.name}")
    declared = str(value.get("snapshot_sha256") or "")
    if not HASH_RE.fullmatch(declared):
        raise PersistenceError(f"snapshot_sha256 is missing: {snapshot_path.name}")
    unsigned = dict(value)
    unsigned.pop("snapshot_sha256", None)
    if _sha(_canonical(unsigned)).lower() != declared.lower():
        raise PersistenceError(f"snapshot_sha256 mismatch: {snapshot_path.name}")
    calendar_meta = value["calendar"]
    return {
        "asof": asof,
        "path": str(snapshot_path),
        "file_sha256": _sha(raw),
        "snapshot_sha256": declared.lower(),
        "source_hashes": source_hashes,
        "status": value["status"],
        "evidence": value["evidence"],
        "calendar_source_sha256": calendar_meta["calendar_source_sha256"],
        "calendar_version": calendar_meta.get("calendar_version"),
        "prior_asof": calendar_meta.get("prior_asof"),
        "prior_status": calendar_meta.get("prior_status"),
        "progression_status": progression.get("status") if isinstance(progression, dict) else None,
        "immutable": True,
    }


def build_seed_bundle(paths: list[str | Path], calendar_path: str | Path) -> dict[str, Any]:
    """Build an append-only seed index from at least two adjacent snapshots."""

    calendar = load_calendar_metadata(calendar_path)
    records = sorted((validate_snapshot(path, calendar) for path in paths), key=lambda item: item["asof"])
    if len(records) < 2:
        raise PersistenceError("at least two dated snapshots are required")
    if len({item["asof"] for item in records}) != len(records):
        raise PersistenceError("snapshot dates must be distinct")
    positions = [calendar["dates"].index(item["asof"]) for item in records]
    if any(right != left + 1 for left, right in zip(positions, positions[1:], strict=False)):
        raise PersistenceError("snapshots must be adjacent sessions in the verified calendar")
    for previous, current in zip(records, records[1:], strict=False):
        if current["prior_asof"] != previous["asof"] or current["prior_status"] != "exchange_verified":
            raise PersistenceError(f"{current['asof']} does not prove its prior session")
        if current["progression_status"] != "fresh":
            raise PersistenceError(f"{current['asof']} has no fresh progression result")
    bundle = {"schema_version": BUNDLE_SCHEMA_VERSION, "evidence": "descriptive", "append_only": True, "calendar": calendar, "snapshots": records}
    bundle["bundle_sha256"] = _sha(_canonical(bundle))
    return bundle


def append_seed_bundle(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge records without changing any already-sealed date."""

    if existing is None:
        return incoming
    if existing.get("schema_version") != BUNDLE_SCHEMA_VERSION or existing.get("append_only") is not True:
        raise PersistenceError("existing seed bundle is not append-only")
    if existing.get("calendar", {}).get("source_sha256") != incoming.get("calendar", {}).get("source_sha256"):
        raise PersistenceError("calendar source changed; start a new bundle")
    old = {item["asof"]: item for item in existing.get("snapshots", [])}
    for item in incoming.get("snapshots", []):
        previous = old.get(item["asof"])
        if previous and previous.get("snapshot_sha256") != item.get("snapshot_sha256"):
            raise PersistenceError(f"sealed snapshot changed: {item['asof']}")
        old[item["asof"]] = item
    positions = [existing["calendar"]["dates"].index(item["asof"]) for item in old.values()]
    if any(right != left + 1 for left, right in zip(sorted(positions), sorted(positions)[1:], strict=False)):
        raise PersistenceError("append would leave a gap in the verified calendar")
    merged = {"schema_version": BUNDLE_SCHEMA_VERSION, "evidence": "descriptive", "append_only": True, "calendar": existing["calendar"], "snapshots": [old[key] for key in sorted(old)]}
    merged["bundle_sha256"] = _sha(_canonical(merged))
    return merged


__all__ = ["PersistenceError", "append_seed_bundle", "build_seed_bundle", "load_calendar_metadata", "validate_snapshot"]
