#!/usr/bin/env python3
"""Persist one EOD attempt. Network is opt-in and requires source review policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.data.market_eod_archive import EODArchive
from research.data.market_eod_pipeline import run_eod


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, help="Persistent SQLite journal path")
    parser.add_argument("--calendar", required=True)
    parser.add_argument("--asof")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input-context", help="Offline historical import; never network")
    mode.add_argument("--capture", action="store_true", help="Explicit network capture; source policy also required")
    parser.add_argument("--source-policy")
    parser.add_argument("--report", required=True)
    parser.add_argument("--backup", help="Consistent database backup for artifact transfer")
    args = parser.parse_args()
    archive = EODArchive(args.archive)
    receipt = run_eod(archive=archive, calendar_path=args.calendar, asof=args.asof, input_path=args.input_context, policy_path=args.source_policy)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(archive.report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.backup:
        archive.backup(args.backup)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 1 if receipt["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
