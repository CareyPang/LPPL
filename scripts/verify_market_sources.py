#!/usr/bin/env python3
"""Write an offline source-review decision; exit 2 means sampling stays blocked."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.data.market_source_validation import inspect_fetch_policy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New report file; an existing file is never overwritten")
    args = parser.parse_args()
    _, report = inspect_fetch_policy(args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"allowed": report["allowed"], "report": str(args.output),
                      "sources": {key: {"allowed": row["allowed"], "missing": len(row["missing"]),
                                         "blocked": len(row["blocked"])} for key, row in report["sources"].items()}}, ensure_ascii=False))
    return 0 if report["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
