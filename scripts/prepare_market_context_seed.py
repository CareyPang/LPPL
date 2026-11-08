#!/usr/bin/env python3
"""Prepare an auditable append-only P1 seed index; never calls the network."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.data.market_context_persistence import append_seed_bundle, build_seed_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--calendar", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    directory = Path(args.directory)
    bundle = build_seed_bundle(sorted(directory.glob("market_context_????-??-??.json")), args.calendar)
    out = Path(args.out)
    if out.exists():
        bundle = append_seed_bundle(json.loads(out.read_text(encoding="utf-8")), bundle)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "bundle_sha256": bundle["bundle_sha256"], "snapshot_count": len(bundle["snapshots"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
