#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .publish_versioned import KIND_PATHS, _asof, publish_bytes
except ImportError:
    from publish_versioned import KIND_PATHS, _asof, publish_bytes


def _pathspecs() -> list[str]:
    specs = set()
    for latest, dated in KIND_PATHS.values():
        specs.add(latest)
        if dated is not None:
            prefix, suffix = dated.split("{asof}")
            specs.add(f":(glob){prefix}????-??-??{suffix}")
    return sorted(specs)


def _kind_for_path(path: str) -> tuple[str, str | None] | None:
    for kind, (latest, dated) in KIND_PATHS.items():
        if path == latest:
            return kind, None
        if dated is None:
            continue
        prefix, suffix = dated.split("{asof}")
        if path.startswith(prefix) and path.endswith(suffix):
            asof = path[len(prefix) : len(path) - len(suffix)] if suffix else path[len(prefix) :]
            try:
                if date.fromisoformat(asof).isoformat() == asof:
                    return kind, asof
            except ValueError:
                continue
    return None


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def _commit_files(repo: Path, commit: str, pathspecs: list[str]) -> list[str]:
    output = _git(
        repo,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "-r",
        "-m",
        "--name-only",
        commit,
        "--",
        *pathspecs,
    )
    return sorted(set(output.decode("utf-8").splitlines()))


def backfill(ref: str, root: str | Path, repo: str | Path | None = None) -> dict[str, Any]:
    repository = Path(repo or Path.cwd()).resolve()
    output_root = Path(root)
    if _git(repository, "rev-parse", "--is-shallow-repository").decode().strip() == "true":
        raise RuntimeError("backfill requires a non-shallow repository")
    pathspecs = _pathspecs()
    commits = _git(
        repository,
        "rev-list",
        "--reverse",
        "--topo-order",
        "--full-history",
        ref,
        "--",
        *pathspecs,
    ).decode("utf-8").splitlines()
    skipped_invalid_asof: list[dict[str, Any]] = []

    for commit in commits:
        published_at = _git(repository, "show", "-s", "--format=%cI", commit).decode().strip()
        for path in _commit_files(repository, commit, pathspecs):
            identified = _kind_for_path(path)
            if identified is None:
                continue
            kind, path_asof = identified
            try:
                raw = _git(repository, "show", f"{commit}:{path}")
            except RuntimeError:
                continue
            record: Any = None
            try:
                record = json.loads(raw)
                asof = _asof(record)
            except (ValueError, TypeError) as exc:
                skipped_invalid_asof.append(
                    {
                        "commit": commit,
                        "path": path,
                        "asof": (
                            record.get("asof")
                            if isinstance(record, dict)
                            else None
                        ),
                        "error": str(exc),
                    }
                )
                continue
            if path_asof is not None and asof != path_asof:
                raise ValueError(
                    f"dated path asof mismatch in {commit}:{path}: {asof!r}"
                )
            fetched_at = record.get("generated_at") or record.get("generated") or published_at
            publish_bytes(
                kind,
                raw,
                output_root,
                published_at=published_at,
                fetched_at=fetched_at,
                run_id=None,
                event="git-backfill",
                backfilled_from_git=True,
                dedupe_all=True,
                update_snapshots=False,
            )

    all_kinds = {}
    for kind in sorted(KIND_PATHS):
        count = 0
        for manifest_path in (output_root / "versions" / kind).glob("*/index.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            count += len(manifest["versions"])
        all_kinds[kind] = count
    gzip_bytes = sum(path.stat().st_size for path in output_root.rglob("*.json.gz"))
    return {
        "counts": all_kinds,
        "total_versions": sum(all_kinds.values()),
        "gzip_bytes": gzip_bytes,
        "skipped_invalid_asof": skipped_invalid_asof,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(backfill(args.ref, args.root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
