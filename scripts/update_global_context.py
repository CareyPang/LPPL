#!/usr/bin/env python3
"""Seal a P2/P3 global-context artifact from already-fetched JSON files.

This runner is intentionally offline.  It reads a local manifest and payload
files, hashes the bytes that were supplied, and writes one descriptive
``global-context.v1`` snapshot.  It never opens a network connection, invokes
the browser, updates an LPPLS input, or writes a Worker/Pages endpoint.

The default empty input directory is useful for the nightly contract check:
an absent manifest produces an explicit ``not_requested`` snapshot rather than
silently fetching a source.  A source manifest is required to state the
license, frequency-limit, and mainland-network status for every source.  The
default for each is ``NOT_ESTABLISHED`` so a local artifact cannot imply that
those checks were completed.

Manifest example::

    {
      "asof": "2026-11-06",
      "generated_at": "2026-11-07T00:30:00+00:00",
      "run_id": "artifact-run-1",
      "sources": {
        "us_treasury": {
          "file": "treasury.json",
          "source_url": "https://home.treasury.gov/…",
          "fetched_at": "2026-11-07T00:00:00+00:00",
          "status": "ok",
          "license_status": "NOT_ESTABLISHED",
          "frequency_status": "NOT_ESTABLISHED",
          "mainland_network_status": "NOT_ESTABLISHED"
        }
      },
      "probability_file": "probability.json"
    }

The optional probability file must already be a ``macro-probability.v1``
object; this command does not turn raw market responses into probabilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from research.data.global_context import (
    EVIDENCE,
    GLOBAL_SCHEMA_VERSION,
    PROBABILITY_SCHEMA_VERSION,
    build_global_context,
    json_sha256,
    parse_bls_series,
    parse_eia_series,
    parse_ny_fed_observations,
    parse_treasury_curve,
)

NOT_ESTABLISHED = "NOT_ESTABLISHED"
POLICY_FIELDS = (
    "license_status",
    "frequency_status",
    "mainland_network_status",
)

Parser = Callable[..., dict[str, Any]]
SOURCE_PARSERS: dict[str, tuple[Parser, str, str]] = {
    "us_treasury": (parse_treasury_curve, "rates", "treasury_curve"),
    "ny_fed": (parse_ny_fed_observations, "rates", "ny_fed_observations"),
    "bls": (parse_bls_series, "rates", "bls_series"),
    "eia": (parse_eia_series, "markets", "eia_series"),
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON artifact {path}: {exc}") from exc


def _resolve_artifact(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("source file must be a non-empty relative path")
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source file escapes input directory: {relative}") from exc
    if not path.is_file():
        raise ValueError(f"source artifact does not exist: {relative}")
    return path


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(meta: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in POLICY_FIELDS:
        value = meta.get(field, NOT_ESTABLISHED)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty status string")
        values[field] = value
    return values


def validate_global_context(snapshot: dict[str, Any], *, require_source_hash: bool = False) -> dict[str, Any]:
    """Validate the artifact-only and provenance boundary of one snapshot."""

    if snapshot.get("schema_version") != GLOBAL_SCHEMA_VERSION:
        raise ValueError("snapshot schema_version must be global-context.v1")
    if snapshot.get("kind") != "global_context":
        raise ValueError("snapshot kind must be global_context")
    if snapshot.get("evidence") != EVIDENCE:
        raise ValueError("snapshot evidence must be descriptive")
    policy = snapshot.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("snapshot policy metadata is required")
    expected_policy = {
        "artifact_only": True,
        "browser_direct_fetch": "forbidden",
        "lppls_input": "forbidden",
        "license_status": NOT_ESTABLISHED,
        "frequency_status": NOT_ESTABLISHED,
        "mainland_network_status": NOT_ESTABLISHED,
    }
    for key, expected in expected_policy.items():
        if policy.get(key) != expected:
            raise ValueError(f"snapshot policy.{key} must be {expected!r}")
    sources = snapshot.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("snapshot sources must be an object")
    hash_count = 0
    for source_id, source in sources.items():
        if not isinstance(source, dict):
            raise ValueError(f"source metadata for {source_id} must be an object")
        for field in ("source", "source_id", "asof", "fetched_at", "status", "source_url", "stale_reason", "raw_sha256", "license_tier"):
            if field not in source:
                raise ValueError(f"source {source_id} is missing {field}")
        for field in POLICY_FIELDS:
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"source {source_id} is missing explicit {field}")
        raw_hash = source.get("raw_sha256")
        if raw_hash is not None:
            if not isinstance(raw_hash, str) or len(raw_hash) != 64 or any(char not in "0123456789abcdef" for char in raw_hash.lower()):
                raise ValueError(f"source {source_id} raw_sha256 must be a hexadecimal SHA-256")
            hash_count += 1
        elif require_source_hash and source.get("status") == "ok":
            raise ValueError(f"source {source_id} requires raw_sha256 when status is ok")
    probability = snapshot.get("probability")
    if not isinstance(probability, dict) or probability.get("schema_version") != PROBABILITY_SCHEMA_VERSION:
        raise ValueError("probability must be a macro-probability.v1 object")
    if probability.get("official_fedwatch") is not False:
        raise ValueError("probability.official_fedwatch must remain false")
    expected_hash = json_sha256({key: value for key, value in snapshot.items() if key != "snapshot_sha256"})
    if snapshot.get("snapshot_sha256") != expected_hash:
        raise ValueError("snapshot_sha256 does not match snapshot contents")
    return {"source_count": len(sources), "source_hash_count": hash_count, "policy": policy}


def _load_manifest(input_dir: Path, *, asof: str | None, generated_at: str | None) -> dict[str, Any]:
    path = input_dir / "manifest.json"
    if path.exists():
        manifest = _load_json(path)
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json must contain an object")
    else:
        manifest = {}
    resolved_asof = asof or manifest.get("asof") or date.today().isoformat()
    resolved_generated = generated_at or manifest.get("generated_at") or _now()
    if not isinstance(resolved_asof, str) or not isinstance(resolved_generated, str):
        raise ValueError("manifest asof/generated_at must be strings")
    manifest["asof"] = resolved_asof
    manifest["generated_at"] = resolved_generated
    return manifest


def _read_probability(input_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    relative = manifest.get("probability_file")
    if relative is None:
        return None
    path = _resolve_artifact(input_dir, relative)
    value = _load_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != PROBABILITY_SCHEMA_VERSION:
        raise ValueError("probability_file must contain macro-probability.v1")
    return value


def run(*, input_dir: Path, out_dir: Path, asof: str | None = None, generated_at: str | None = None) -> dict[str, Any]:
    """Read local artifacts, seal a snapshot, and return a small run summary."""

    input_dir = input_dir.resolve()
    input_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(input_dir, asof=asof, generated_at=generated_at)
    asof = manifest["asof"]
    generated_at = manifest["generated_at"]
    run_id = manifest.get("run_id")
    if run_id is not None and not isinstance(run_id, str):
        raise ValueError("manifest run_id must be a string")

    sources: dict[str, dict[str, Any]] = {}
    rates: dict[str, Any] = {}
    markets: dict[str, Any] = {}
    for source_id, raw_meta in (manifest.get("sources") or {}).items():
        if source_id not in SOURCE_PARSERS:
            raise ValueError(f"unsupported P2 source: {source_id}")
        if not isinstance(raw_meta, dict):
            raise ValueError(f"manifest source {source_id} must be an object")
        policy = _policy(raw_meta)
        path = _resolve_artifact(input_dir, raw_meta.get("file"))
        payload = _load_json(path)
        parser, destination, section_name = SOURCE_PARSERS[source_id]
        source = parser(
            payload,
            asof=asof,
            fetched_at=raw_meta.get("fetched_at") or generated_at,
            source_url=raw_meta.get("source_url"),
            raw_sha256=_raw_sha256(path),
            license_tier=raw_meta.get("license_tier") or NOT_ESTABLISHED,
            status=raw_meta.get("status", "ok"),
            stale_reason=raw_meta.get("stale_reason"),
        )
        source.update(policy)
        source["browser_direct_fetch"] = "forbidden"
        source["lppls_input"] = "forbidden"
        sources[source_id] = source
        if destination == "rates":
            rates[section_name] = source
        else:
            markets[section_name] = source

    probability = _read_probability(input_dir, manifest)
    snapshot = build_global_context(
        asof=asof,
        generated_at=generated_at,
        sources=sources,
        rates=rates,
        markets=markets,
        probability=probability,
        run_id=run_id,
        stale_reason=manifest.get("stale_reason"),
    )
    snapshot["policy"] = {
        "artifact_only": True,
        "browser_direct_fetch": "forbidden",
        "lppls_input": "forbidden",
        "license_status": NOT_ESTABLISHED,
        "frequency_status": NOT_ESTABLISHED,
        "mainland_network_status": NOT_ESTABLISHED,
    }
    snapshot["snapshot_sha256"] = json_sha256({key: value for key, value in snapshot.items() if key != "snapshot_sha256"})
    validate_global_context(snapshot)

    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    dated = out_dir / f"global_context_{asof}.json"
    latest = out_dir / "global_context_latest.json"
    dated.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    manifest_record = {
        "schema_version": GLOBAL_SCHEMA_VERSION,
        "asof": asof,
        "generated_at": generated_at,
        "run_id": run_id,
        "status": snapshot["status"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "source_hashes": sorted(
            source["raw_sha256"] for source in sources.values() if source.get("raw_sha256")
        ),
        "evidence": EVIDENCE,
        "policy": snapshot["policy"],
    }
    (out_dir / "global_context_manifest.json").write_text(
        json.dumps({"schema_version": "global-context-manifest.v1", "latest": manifest_record}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "asof": asof,
        "status": snapshot["status"],
        "source_count": len(sources),
        "source_hash_count": len(manifest_record["source_hashes"]),
        "output": str(out_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="data/global-context/incoming")
    parser.add_argument("--out", default="out/global-context")
    parser.add_argument("--asof", help="Override manifest asof (YYYY-MM-DD)")
    parser.add_argument("--generated-at", help="Override manifest generated_at")
    parser.add_argument("--check", metavar="SNAPSHOT", help="Validate an existing snapshot without writing")
    args = parser.parse_args(argv)
    if args.check:
        snapshot = _load_json(Path(args.check))
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot must contain an object")
        print(json.dumps(validate_global_context(snapshot), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(run(input_dir=Path(args.input_dir), out_dir=Path(args.out), asof=args.asof, generated_at=args.generated_at), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
