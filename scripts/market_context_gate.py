#!/usr/bin/env python3
"""Check whether two real dated P1 snapshots are available for UI polling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HASH_PATTERN = set("0123456789abcdefABCDEF")


def _verified_calendar(value: object, *, require_prior: bool = False) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("calendar_status") != "provided":
        return False
    if value.get("asof_status") != "exchange_verified":
        return False
    source_hash = str(value.get("calendar_source_sha256") or "")
    if len(source_hash) != 64 or any(char not in HASH_PATTERN for char in source_hash):
        return False
    if require_prior and value.get("prior_status") != "exchange_verified":
        return False
    return True


def inspect(directory: Path) -> dict:
    entries = []
    for path in sorted(directory.glob("market_context_????-??-??.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        hashes = [
            meta.get("raw_sha256")
            for meta in (value.get("sources") or {}).values()
            if isinstance(meta, dict)
        ]
        limit = value.get("limit_pools") if isinstance(value.get("limit_pools"), dict) else {}
        calendar = value.get("calendar")
        p1_core_ready = all(
            isinstance(limit.get(key), dict) and limit[key].get("status") == "fresh"
            for key in ("reasons", "topics", "prior_day")
        )
        if (
            value.get("run_mode") == "live"
            and value.get("status") in {"fresh", "partial"}
            and isinstance(value.get("asof"), str)
            and p1_core_ready
            and _verified_calendar(calendar, require_prior=bool((value.get("history") or {}).get("progression", {}).get("status") == "fresh"))
            and any(isinstance(item, str) and len(item) == 64 for item in hashes)
        ):
            entries.append({
                "asof": value["asof"], "status": value["status"], "path": str(path),
                "source_hash_count": sum(1 for item in hashes if isinstance(item, str)),
                "calendar_status": calendar.get("calendar_status"),
                "calendar_version": calendar.get("calendar_version"),
                "prior_asof": calendar.get("prior_asof"),
            })
    distinct = {entry["asof"] for entry in entries}
    return {"directory": str(directory), "real_snapshot_count": len(distinct), "ready_for_frontend_polling": len(distinct) >= 2, "snapshots": entries}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="out/market-context")
    args = parser.parse_args()
    result = inspect(Path(args.directory))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready_for_frontend_polling"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
