#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import tempfile
import zlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

KIND_PATHS: dict[str, tuple[str, str | None]] = {
    "market": ("market/market_latest.json", "market/{asof}.json"),
    "abnormal": ("market/abnormal_latest.json", None),
    "bottom_signal": ("market/bottom_signal_latest.json", None),
    "range": ("market/range_latest.json", None),
    "events": ("events/events_latest.json", "events/events_{asof}.json"),
    "macro": ("macro/macro_latest.json", "macro/macro_{asof}.json"),
    "nt_etf": ("nt_etf/nt_etf_latest.json", "nt_etf/nt_etf_{asof}.json"),
    "growth": ("growth/growth_latest.json", "growth/growth_{asof}.json"),
}
_DEFAULT = object()


def _utc_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_iso(value: str | datetime | None = None) -> str:
    parsed = _utc_datetime(value) if value is not None else datetime.now(UTC)
    return parsed.isoformat().replace("+00:00", "Z")


def _asof(record: dict[str, Any]) -> str:
    if not isinstance(record, dict):
        raise ValueError("record must be a JSON object")
    value = record.get("asof")
    if not isinstance(value, str):
        raise ValueError("record must contain an ISO asof date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid asof date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"invalid asof date: {value!r}")
    return value


def _version_name(fetched_at: str, sha256: str) -> str:
    stamp = _utc_datetime(fetched_at).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{sha256[:8]}.json.gz"


def _gzip_bytes(raw: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as stream:
        stream.write(raw)
    return buffer.getvalue()


def _write_immutable(path: Path, raw: bytes, compressed: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = gzip.decompress(path.read_bytes())
        except (OSError, EOFError, zlib.error) as exc:
            raise FileExistsError(f"existing version file is not valid gzip: {path}") from exc
        if existing != raw:
            raise FileExistsError(f"version file already exists with different content: {path}")
        return False

    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write(compressed)
    try:
        os.link(temp_path, path)
    except FileExistsError:
        return _write_immutable(path, raw, compressed)
    finally:
        temp_path.unlink(missing_ok=True)
    return True


def _write_if_changed(path: Path, content: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == content:
        return False
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return True


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def _sources_ok(record: dict[str, Any]) -> dict[str, bool]:
    sources = record.get("sources")
    if not isinstance(sources, dict):
        return {}
    return {
        str(name): bool(source["ok"])
        for name, source in sources.items()
        if isinstance(source, dict) and "ok" in source
    }


def _read_manifest(path: Path, kind: str, asof: str) -> dict[str, Any]:
    if not path.is_file():
        return {"kind": kind, "asof": asof, "versions": []}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != kind
        or manifest.get("asof") != asof
        or not isinstance(manifest.get("versions"), list)
        or not all(isinstance(entry, dict) for entry in manifest["versions"])
    ):
        raise ValueError(f"invalid version manifest: {path}")
    return manifest


def _root_index(root: Path, kind: str) -> dict[str, dict[str, Any]]:
    index = {}
    kind_dir = root / "versions" / kind
    if not kind_dir.is_dir():
        return index
    for path in sorted(kind_dir.glob("*/index.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        versions = manifest.get("versions", [])
        if not versions:
            continue
        asof = manifest.get("asof")
        index[asof] = {
            "count": len(versions),
            "last_fetched_at": max(
                (entry["fetched_at"] for entry in versions),
                key=_utc_datetime,
            ),
        }
    return index


def publish_bytes(
    kind: str,
    raw: bytes,
    root: str | Path,
    *,
    published_at: str | datetime | None = None,
    fetched_at: str | datetime | None = None,
    run_id: str | None | object = _DEFAULT,
    event: str | None | object = _DEFAULT,
    backfilled_from_git: bool = False,
    dedupe_all: bool = False,
    update_snapshots: bool = True,
) -> list[str]:
    if kind not in KIND_PATHS:
        raise ValueError(f"unsupported kind: {kind!r}")
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise ValueError("record must be a JSON object")
    if record.get("asof") is None:
        root_path = Path(root)
        latest_path = root_path / KIND_PATHS[kind][0]
        latest_asof = None
        if latest_path.is_file():
            try:
                latest_record = json.loads(latest_path.read_text(encoding="utf-8"))
                if isinstance(latest_record, dict):
                    latest_asof = _asof(latest_record)
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        changed_paths = []
        if latest_asof is None and _write_if_changed(latest_path, raw):
            changed_paths.append(latest_path.relative_to(root_path).as_posix())
        print(
            f"warning: {kind} record has no asof; version history was skipped",
            file=sys.stderr,
        )
        return changed_paths
    asof = _asof(record)
    fetched_value = fetched_at
    if fetched_value is None:
        fetched_value = record.get("generated_at") or record.get("generated")
    normalized_fetched_at = _utc_iso(fetched_value)
    normalized_published_at = _utc_iso(published_at)
    sha256 = hashlib.sha256(raw).hexdigest()
    compressed = _gzip_bytes(raw)

    root_path = Path(root)
    version_dir = root_path / "versions" / kind / asof
    manifest_path = version_dir / "index.json"
    manifest = _read_manifest(manifest_path, kind, asof)
    versions = manifest["versions"]

    matching = next(
        (entry for entry in versions if entry.get("sha256") == sha256),
        None,
    )
    newest_same = bool(versions and versions[-1].get("sha256") == sha256)
    duplicate = matching is not None if dedupe_all else newest_same

    changed_paths: set[str] = set()
    if duplicate:
        entry = versions[-1] if not dedupe_all else matching
        version_path = root_path / entry["file"]
        if not version_path.is_file() or gzip.decompress(version_path.read_bytes()) != raw:
            raise FileNotFoundError(f"manifest version file is missing or corrupt: {version_path}")
    else:
        filename = _version_name(normalized_fetched_at, sha256)
        version_path = version_dir / filename
        if _write_immutable(version_path, raw, compressed):
            changed_paths.add(version_path.relative_to(root_path).as_posix())
        entry = {
            "file": version_path.relative_to(root_path).as_posix(),
            "sha256": sha256,
            "bytes": len(raw),
            "fetched_at": normalized_fetched_at,
            "published_at": normalized_published_at,
            "run_id": (
                os.environ.get("GITHUB_RUN_ID") or None
                if run_id is _DEFAULT
                else run_id
            ),
            "event": (
                os.environ.get("GITHUB_EVENT_NAME") or None
                if event is _DEFAULT
                else event
            ),
            "sources_ok": _sources_ok(record),
            "backfilled_from_git": bool(backfilled_from_git),
        }
        versions.append(entry)
        if _write_if_changed(manifest_path, _json_bytes(manifest)):
            changed_paths.add(manifest_path.relative_to(root_path).as_posix())

    root_index_path = root_path / "versions" / kind / "index.json"
    root_index_bytes = _json_bytes(_root_index(root_path, kind))
    if _write_if_changed(root_index_path, root_index_bytes):
        changed_paths.add(root_index_path.relative_to(root_path).as_posix())

    if update_snapshots:
        version_ref = {
            "kind": kind,
            "asof": asof,
            "file": entry["file"],
            "sha256": entry["sha256"],
        }
        output_record = dict(record)
        output_record["version"] = version_ref
        dated_template = KIND_PATHS[kind][1]
        if dated_template is not None:
            dated_path = root_path / dated_template.format(asof=asof)
            if _write_if_changed(dated_path, _json_bytes(output_record)):
                changed_paths.add(dated_path.relative_to(root_path).as_posix())

        latest_path = root_path / KIND_PATHS[kind][0]
        latest_asof = None
        if latest_path.is_file():
            try:
                latest_record = json.loads(latest_path.read_text(encoding="utf-8"))
                latest_value = latest_record.get("asof") if isinstance(latest_record, dict) else None
                if isinstance(latest_value, str):
                    latest_asof = date.fromisoformat(latest_value)
            except (OSError, json.JSONDecodeError, ValueError):
                latest_asof = None
        if latest_asof is None or date.fromisoformat(asof) >= latest_asof:
            if _write_if_changed(latest_path, _json_bytes(output_record)):
                changed_paths.add(latest_path.relative_to(root_path).as_posix())

    return sorted(changed_paths)


def publish_record(
    kind: str,
    src: str | Path,
    root: str | Path,
    **kwargs: Any,
) -> list[str]:
    return publish_bytes(kind, Path(src).read_bytes(), root, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=sorted(KIND_PATHS))
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    record = json.loads(args.src.read_bytes())
    if not isinstance(record, dict):
        raise ValueError("record must be a JSON object")
    if record.get("asof") is not None:
        asof = _asof(record)
        latest_manifest = _read_manifest(
            args.root / "versions" / args.kind / asof / "index.json",
            args.kind,
            asof,
        )
        sha256 = hashlib.sha256(args.src.read_bytes()).hexdigest()
        if (
            latest_manifest["versions"]
            and latest_manifest["versions"][-1].get("sha256") == sha256
        ):
            print(
                f"{args.kind}/{asof}: identical content; skipped new version.",
                file=sys.stderr,
            )
    for path in publish_record(args.kind, args.src, args.root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
