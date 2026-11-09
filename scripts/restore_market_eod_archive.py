#!/usr/bin/env python3
"""Verify and restore an existing journal, without replacing an active journal."""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from research.data.market_eod_archive import SCHEMA, day, digest, stamp


def verify(source: Path) -> dict:
    if not source.is_file():
        raise ValueError("previous archive not found")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("archive database integrity failure")
        if db.execute("SELECT version FROM metadata").fetchall() != [(SCHEMA,)]:
            raise ValueError("archive schema mismatch")
        events = {}
        for run_id, kind, recorded_at, body in db.execute("SELECT run_id,kind,recorded_at,body FROM events"):
            if kind not in {"started", "finished"} or stamp(recorded_at) != recorded_at:
                raise ValueError("invalid event metadata")
            value = json.loads(body)
            day(value["asof"])
            events[(run_id, kind)] = (recorded_at, value)
        for (run_id, kind), (recorded_at, value) in events.items():
            if kind != "finished":
                continue
            started = events.get((run_id, "started"))
            if (not started or recorded_at < started[0] or value.get("recorded_at") != recorded_at
                    or value.get("run_id") != run_id or value.get("asof") != started[1]["asof"]
                    or value.get("mode") != started[1]["mode"] or value.get("publication_eligible") is not False):
                raise ValueError("receipt metadata inconsistent with run")
        count = 0
        revision_runs = set()
        for seq, run_id, asof, recorded_at, rank, sha, body in db.execute("SELECT seq,run_id,asof,recorded_at,rank,content_sha256,body FROM revisions"):
            snapshot = json.loads(body)
            if digest(body.encode()) != sha or snapshot.get("publication_eligible") is not False:
                raise ValueError("revision hash/publication boundary failure")
            quality = snapshot.get("daily_capture", {}).get("quality", {})
            expected_rank = 100 if quality.get("core_complete") is True else sum(int(p.get("structurally_complete") is True) for p in quality.get("pools", {}).values())
            if rank != expected_rank:
                raise ValueError("revision quality rank inconsistent with snapshot")
            finished = events.get((run_id, "finished"))
            receipt = finished[1] if finished else {}
            if (not finished or receipt.get("status") not in {"sealed", "partial"} or receipt.get("revision") != seq
                    or receipt.get("content_sha256") != sha or receipt.get("asof") != asof or snapshot.get("asof") != asof
                    or recorded_at != finished[0]):
                raise ValueError("revision metadata inconsistent with receipt")
            revision_runs.add(run_id)
            count += 1
        for (run_id, kind), (_, value) in events.items():
            if kind == "finished" and (value.get("status") in {"sealed", "partial"}) != (run_id in revision_runs):
                raise ValueError("receipt revision linkage missing")
        for run_id, sha, body in db.execute("SELECT run_id,raw_sha256,body FROM responses"):
            if (run_id, "started") not in events:
                raise ValueError("raw response run linkage missing")
            if digest(bytes(body)) != sha:
                raise ValueError("raw response hash mismatch")
    return {"schema_version": SCHEMA, "restored_revisions": count, "hash_verification": "VERIFIED", "historical_public_availability": "NOT_ESTABLISHED"}


def restore(source: Path, destination: Path) -> dict:
    if destination.exists():
        raise ValueError("refusing to replace an existing active archive")
    result = verify(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db, closing(sqlite3.connect(destination)) as target:
        db.backup(target)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.source, args.destination)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
