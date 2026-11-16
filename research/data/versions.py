from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


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


def list_versions(
    root: str | Path, kind: str, asof: str
) -> list[dict[str, Any]]:
    if not kind or kind in {".", ".."} or Path(kind).name != kind:
        raise ValueError(f"invalid version kind: {kind!r}")
    try:
        if date.fromisoformat(asof).isoformat() != asof:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"invalid asof date: {asof!r}") from exc
    path = Path(root) / "versions" / kind / asof / "index.json"
    if not path.is_file():
        return []
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != kind
        or manifest.get("asof") != asof
        or not isinstance(manifest.get("versions"), list)
        or not all(isinstance(entry, dict) for entry in manifest["versions"])
    ):
        raise ValueError(f"invalid version manifest: {path}")
    return list(manifest["versions"])


def load_as_of(
    root: str | Path,
    kind: str,
    asof: str,
    known_at: str | datetime | None = None,
) -> dict[str, Any] | None:
    versions = list_versions(root, kind, asof)
    if not versions:
        return None
    boundary = _utc_datetime(known_at) if known_at is not None else None
    eligible = [
        (position, entry)
        for position, entry in enumerate(versions)
        if boundary is None or _utc_datetime(entry["fetched_at"]) <= boundary
    ]
    if not eligible:
        return None
    _, selected = max(
        eligible,
        key=lambda item: (_utc_datetime(item[1]["fetched_at"]), item[0]),
    )
    relative_path = Path(selected["file"])
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"invalid version file path: {selected['file']!r}")
    path = Path(root) / relative_path
    record = json.loads(gzip.decompress(path.read_bytes()))
    if not isinstance(record, dict):
        raise ValueError(f"version payload must be a JSON object: {path}")
    return record
