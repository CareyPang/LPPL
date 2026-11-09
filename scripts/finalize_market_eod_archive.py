#!/usr/bin/env python3
"""Produce a verified transferable journal even after an interrupted capture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.data.market_eod_archive import EODArchive
from scripts.restore_market_eod_archive import verify


def finalize(source: Path, directory: Path) -> dict:
    # Do not silently initialize an empty archive after restoration failed.
    verify(source)
    archive = EODArchive(source)
    directory.mkdir(parents=True, exist_ok=True)
    archive.backup(directory / "state.sqlite")
    result = verify(directory / "state.sqlite")
    (directory / "report.json").write_text(json.dumps(archive.report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(finalize(args.source, args.directory)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
