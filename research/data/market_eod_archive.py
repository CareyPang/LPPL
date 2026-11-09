"""Local append-only EOD evidence journal. No network, publication or model calls."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA = "market-eod-archive.v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stamp(value: str | None = None) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(UTC)
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def day(value: str) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("canonical ISO date required")
    return value


def safe_source_url(url: str) -> str:
    """Keep provider and nonsecret request coordinates, never credentials."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("source must be credential-free HTTPS")
    allowed = {"date", "page", "Pageindex", "pagesize", "limit", "sort", "field", "filter", "order_field", "order_type", "dpt"}
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode([(k, v) for k, v in parse_qsl(parts.query) if k in allowed]), ""))


class EODArchive:
    """One SQLite transaction seals a revision and its final receipt.

    Events, raw responses and revisions reject UPDATE/DELETE. Interrupted runs
    remain visible as running; a later retry gets a new run id. JSON exports are
    disposable views of this journal, never the authoritative append-only store.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(version TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS events(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                  kind TEXT NOT NULL, recorded_at TEXT NOT NULL, body TEXT NOT NULL,
                  UNIQUE(run_id,kind));
                CREATE TABLE IF NOT EXISTS responses(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                  source_id TEXT NOT NULL, url TEXT NOT NULL, fetched_at TEXT NOT NULL,
                  http_status INTEGER NOT NULL, raw_sha256 TEXT NOT NULL, body BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE,
                  asof TEXT NOT NULL, recorded_at TEXT NOT NULL, rank INTEGER NOT NULL,
                  content_sha256 TEXT NOT NULL, body TEXT NOT NULL);
            """)
            versions = [r[0] for r in db.execute("SELECT version FROM metadata")]
            if versions and versions != [SCHEMA]:
                raise ValueError("unsupported EOD archive version")
            db.execute("INSERT OR IGNORE INTO metadata VALUES (?)", (SCHEMA,))
            for table in ("events", "responses", "revisions"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only archive'); END")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def start(self, run_id: str, *, asof: str, mode: str, now: str | None = None) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", run_id):
            raise ValueError("invalid run id")
        if mode not in {"capture", "historical_import", "fixture"}:
            raise ValueError("invalid capture mode")
        body = {"asof": day(asof), "mode": mode, "evidence": "descriptive", "publication_eligible": False}
        with self.connect() as db:
            db.execute("INSERT INTO events(run_id,kind,recorded_at,body) VALUES (?,?,?,?)", (run_id, "started", stamp(now), canonical(body)))

    @staticmethod
    def _open_run(db: sqlite3.Connection, run_id: str) -> dict[str, Any]:
        start = db.execute("SELECT body,recorded_at FROM events WHERE run_id=? AND kind='started'", (run_id,)).fetchone()
        if not start or db.execute("SELECT 1 FROM events WHERE run_id=? AND kind='finished'", (run_id,)).fetchone():
            raise ValueError("run does not exist or is already finished")
        return {**json.loads(start["body"]), "_started_at": start["recorded_at"]}

    def response(self, run_id: str, *, source_id: str, url: str, raw: bytes, http_status: int, fetched_at: str | None = None) -> str:
        if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
            raise ValueError("response must be bytes within 8 MiB")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source id required")
        sha = digest(raw)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._open_run(db, run_id)
            db.execute("INSERT INTO responses(run_id,source_id,url,fetched_at,http_status,raw_sha256,body) VALUES (?,?,?,?,?,?,?)",
                       (run_id, source_id, safe_source_url(url), stamp(fetched_at), http_status, sha, raw))
        return sha

    def raw_verified(self, run_id: str, source_id: str, sha: str | None) -> bool:
        if not sha:
            return False
        with self.connect() as db:
            rows = db.execute("SELECT body FROM responses WHERE run_id=? AND source_id=? AND raw_sha256=? AND http_status=200", (run_id, source_id, sha)).fetchall()
        return any(digest(bytes(r["body"])) == sha for r in rows)

    def finish(self, run_id: str, *, status: str, detail: dict[str, Any], snapshot: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
        if status not in {"sealed", "partial", "failed", "skipped"}:
            raise ValueError("invalid final status")
        if (status in {"sealed", "partial"}) != (snapshot is not None):
            raise ValueError("only sealed/partial receipts may contain snapshots")
        recorded = stamp(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            start = self._open_run(db, run_id)
            if recorded < start["_started_at"]:
                raise ValueError("final receipt cannot precede run start")
            receipt = {"schema_version": SCHEMA, "run_id": run_id, "asof": start["asof"], "mode": start["mode"], "status": status,
                       "recorded_at": recorded, "detail": detail, "publication_eligible": False, "first_public_visible_at": None}
            if snapshot is not None:
                if snapshot.get("asof") != start["asof"] or snapshot.get("publication_eligible") is not False:
                    raise ValueError("snapshot date/publication boundary mismatch")
                text = canonical(snapshot)
                quality = snapshot.get("daily_capture", {}).get("quality", {})
                rank = 100 if quality.get("core_complete") is True else sum(int(p.get("structurally_complete") is True) for p in quality.get("pools", {}).values())
                sha = digest(text.encode())
                result = db.execute("INSERT INTO revisions(run_id,asof,recorded_at,rank,content_sha256,body) VALUES (?,?,?,?,?,?)", (run_id, start["asof"], recorded, rank, sha, text))
                receipt.update({"revision": result.lastrowid, "content_sha256": sha})
            db.execute("INSERT INTO events(run_id,kind,recorded_at,body) VALUES (?,?,?,?)", (run_id, "finished", recorded, canonical(receipt)))
        return receipt

    def best(self, asof: str | None = None, *, known_by: str | None = None) -> dict[str, Any] | None:
        clauses, values = [], []
        if asof is not None:
            clauses.append("asof=?")
            values.append(day(asof))
        if known_by is not None:
            clauses.append("recorded_at<=?")
            values.append(stamp(known_by))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            row = db.execute("SELECT * FROM revisions" + where + " ORDER BY asof DESC,rank DESC,seq DESC LIMIT 1", values).fetchone()
        if row is None:
            return None
        if digest(row["body"].encode()) != row["content_sha256"]:
            raise ValueError("stored revision hash mismatch")
        return {"revision": row["seq"], "recorded_at": row["recorded_at"], "content_sha256": row["content_sha256"], "snapshot": json.loads(row["body"])}

    def report(self) -> dict[str, Any]:
        with self.connect() as db:
            starts = db.execute("SELECT run_id,recorded_at,body FROM events WHERE kind='started' ORDER BY seq").fetchall()
            finished = {r["run_id"]: json.loads(r["body"]) for r in db.execute("SELECT run_id,body FROM events WHERE kind='finished'")}
            revisions = [dict(r) for r in db.execute("SELECT seq AS revision,run_id,asof,recorded_at,rank,content_sha256 FROM revisions ORDER BY seq")]
            raw_count = db.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        return {"schema_version": SCHEMA, "publication_eligible": False, "model_input_eligible": False,
                "runs": [finished.get(r["run_id"], {**json.loads(r["body"]), "run_id": r["run_id"], "status": "interrupted_or_running", "recorded_at": r["recorded_at"]}) for r in starts],
                "revisions": revisions, "raw_response_count": raw_count,
                "latest_archived_asof": max((r["asof"] for r in revisions), default=None)}

    def backup(self, target: str | Path) -> None:
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise ValueError("backup must not overwrite active journal")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
