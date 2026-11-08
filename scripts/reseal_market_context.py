#!/usr/bin/env python3
"""Re-seal preserved market-context snapshots with a verified calendar.

This command is offline and append-only with respect to the source directory:
it copies dated context files into a new output directory, injects only the
verified calendar metadata, recomputes the canonical snapshot hash, and writes
an auditable provenance record. It never overwrites the source snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _calendar_meta(value: dict[str, Any], calendar_path: Path) -> dict[str, Any]:
    dates = value.get("dates")
    source_hash = str(value.get("source_sha256") or "")
    if not isinstance(dates, list) or not dates or dates != sorted(set(dates)):
        raise ValueError("calendar dates must be a sorted non-empty list")
    if value.get("verification_status") != "exchange_verified":
        raise ValueError("calendar verification_status is not exchange_verified")
    if re.fullmatch(r"[0-9a-fA-F]{64}", source_hash) is None:
        raise ValueError("calendar source_sha256 must be 64 hexadecimal characters")
    return {
        "version": value.get("version"),
        "source_url": value.get("source_url"),
        "source_sha256": source_hash,
        "source_published_at": value.get("source_published_at"),
        "verification_status": value["verification_status"],
        "artifact_sha256": _sha(calendar_path.read_bytes()),
        "coverage_start": value.get("coverage_start"),
        "coverage_end": value.get("coverage_end"),
        "venue_scope": value.get("venue_scope"),
        "scope": value.get("scope"),
    }


def reseal(source_dir: Path, calendar_path: Path, output_dir: Path) -> dict[str, Any]:
    calendar = _load(calendar_path)
    meta = _calendar_meta(calendar, calendar_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_contexts = sorted(source_dir.glob("market_context_????-??-??.json"))
    if len(source_contexts) < 2:
        raise ValueError("source directory must contain at least two dated snapshots")
    context_dir = output_dir / "market-context"
    context_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for source_path in source_contexts:
        target_path = context_dir / source_path.name
        snapshot = _load(source_path)
        asof = str(snapshot.get("asof") or "")
        if asof not in calendar["dates"]:
            raise ValueError(f"snapshot date is not present in verified calendar: {asof}")
        calendar_index = calendar["dates"].index(asof)
        calendar_prior = calendar["dates"][calendar_index - 1] if calendar_index else None
        progression = snapshot.get("history", {}).get("progression", {})
        progression_prior = progression.get("prior_asof") if isinstance(progression, dict) else None
        if isinstance(progression, dict) and progression.get("status") == "fresh" and not progression_prior:
            raise ValueError(f"fresh progression has no prior_asof: {asof}")
        if progression.get("status") == "fresh" and progression_prior != calendar_prior:
            raise ValueError(f"fresh progression prior_asof does not match calendar: {asof}")
        snapshot["calendar"] = {
            "calendar_status": "provided",
            "asof_status": "exchange_verified",
            "prior_status": "exchange_verified" if calendar_prior else "not_available",
            "calendar_version": meta["version"],
            "calendar_source_url": meta["source_url"],
            "calendar_source_sha256": meta["source_sha256"],
            "calendar_artifact_sha256": meta["artifact_sha256"],
            "calendar_coverage_start": meta["coverage_start"],
            "calendar_coverage_end": meta["coverage_end"],
            "prior_asof": calendar_prior,
            "note": meta["scope"],
        }
        snapshot.pop("snapshot_sha256", None)
        snapshot["snapshot_sha256"] = _sha(_canonical(snapshot))
        rendered = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        if target_path.exists() and target_path.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"output snapshot is already sealed and differs: {target_path.name}")
        if not target_path.exists():
            shutil.copy2(source_path, target_path)
        target_path.write_text(rendered, encoding="utf-8")
        records.append({
            "asof": asof,
            "path": str(target_path),
            "file_sha256": _sha(target_path.read_bytes()),
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "prior_asof": snapshot["calendar"]["prior_asof"],
            "prior_status": snapshot["calendar"]["prior_status"],
            "progression_status": progression.get("status") if isinstance(progression, dict) else None,
            "progression_prior_asof": progression_prior,
            "source_raw_sha256": sorted({
                str(item["raw_sha256"])
                for item in (snapshot.get("sources") or {}).values()
                if isinstance(item, dict) and item.get("raw_sha256")
            }),
        })
    provenance = {
        "schema_version": "market-context-p1-reseal.v1",
        "source_directory": str(source_dir),
        "output_directory": str(output_dir),
        "calendar": {
            "path": str(calendar_path),
            "version": meta["version"],
            "source_url": meta["source_url"],
            "source_sha256": meta["source_sha256"],
            "artifact_sha256": meta["artifact_sha256"],
            "verification_status": meta["verification_status"],
            "dates_count": len(calendar["dates"]),
        },
        "snapshots": sorted(records, key=lambda item: item["asof"]),
    }
    manifest = {
        "schema_version": "market-context-manifest.v1",
        "calendar": {
            "version": meta["version"],
            "source_url": meta["source_url"],
            "source_sha256": meta["source_sha256"],
            "artifact_sha256": meta["artifact_sha256"],
            "verification_status": meta["verification_status"],
        },
        "append_only": True,
        "snapshots": sorted(records, key=lambda item: item["asof"]),
        "real_snapshot_count": len(records),
    }
    (context_dir / "market_context_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "reseal_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--calendar", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(reseal(Path(args.source_dir), Path(args.calendar), Path(args.out_dir)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
