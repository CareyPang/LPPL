"""Restore actual disposable SQLite files; no providers, models or deployment."""

import json
import sqlite3

import pytest

from research.data.market_eod_archive import SCHEMA, EODArchive, canonical, digest
from scripts.finalize_market_eod_archive import finalize
from scripts.restore_market_eod_archive import restore

DAY = "2026-11-06"
START = "2026-11-09T02:00:00Z"
FINISH = "2026-11-09T02:01:00Z"
URL = "https://data.example/pool?date=20261106"


def make_journal(path):
    archive = EODArchive(path)
    archive.start("original_research", asof=DAY, mode="historical_import", now=START)
    raw = b'{ "pool": [] }\r\n'
    sha = archive.response("original_research", source_id="pool", url=URL,
                           raw=raw, http_status=200, fetched_at=START)
    value = {"asof": DAY, "publication_eligible": False, "model_input_eligible": False,
             "daily_capture": {"quality": {"core_complete": False, "pools": {}}}}
    archive.finish("original_research", status="partial", detail={"research_only": True},
                   snapshot=value, now=FINISH)
    archive.start("failed_later_run", asof=DAY, mode="capture", now=FINISH)
    archive.finish("failed_later_run", status="failed", detail={"reason": "permission_pending"}, now=FINISH)
    archive.start("interrupted_later", asof=DAY, mode="capture", now=FINISH)
    return archive, sha


@pytest.fixture
def journal(tmp_path):
    archive, sha = make_journal(tmp_path / "original.sqlite")
    return archive, sha


def test_actual_sqlite_backup_restores_all_records_without_changing_source(journal, tmp_path):
    original, sha = journal
    backup = tmp_path / "artifact" / "state.sqlite"
    original.backup(backup)
    before = digest(backup.read_bytes())
    destination = tmp_path / "next-run" / "journal.sqlite"

    result = restore(backup, destination)
    restored = EODArchive(destination)

    assert digest(backup.read_bytes()) == before
    assert result == {"schema_version": SCHEMA, "restored_revisions": 1,
                      "hash_verification": "VERIFIED", "historical_public_availability": "NOT_ESTABLISHED"}
    assert restored.report() == original.report()
    assert restored.best(DAY) == original.best(DAY)
    assert restored.raw_verified("original_research", "pool", sha)
    assert restored.best("2026-11-05") is None
    assert restored.best(DAY, known_by="2026-11-06T23:59:59+08:00") is None
    assert [row["status"] for row in restored.report()["runs"]] == [
        "partial", "failed", "interrupted_or_running",
    ]
    assert restored.best(DAY)["snapshot"]["publication_eligible"] is False
    with sqlite3.connect(destination) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT body FROM responses").fetchone()[0] == b'{ "pool": [] }\r\n'


@pytest.mark.parametrize("table", ["events", "responses", "revisions"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
def test_restore_preserves_sqlite_append_only_triggers_before_reopening_archive(journal, tmp_path, table, action):
    original, _ = journal
    destination = tmp_path / "restored.sqlite"
    restore(original.path, destination)
    # Test the restored database itself, before EODArchive could recreate triggers.
    with sqlite3.connect(destination) as db:
        sql = f"DELETE FROM {table}" if action == "DELETE" else f"UPDATE {table} SET run_id='rewritten'"
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(sql)


def test_restoring_failed_and_interrupted_only_archive_does_not_invent_a_revision(tmp_path):
    source = EODArchive(tmp_path / "source.sqlite")
    source.start("failed_only_run", asof=DAY, mode="capture", now=START)
    source.finish("failed_only_run", status="failed", detail={"reason": "upstream_error"}, now=FINISH)
    source.start("interrupted_only", asof=DAY, mode="capture", now=FINISH)
    destination = tmp_path / "restored.sqlite"

    result = restore(source.path, destination)
    restored = EODArchive(destination)

    assert result["restored_revisions"] == 0
    assert restored.report() == source.report()
    assert restored.best() is None


def test_missing_source_fails_without_creating_destination(tmp_path):
    destination = tmp_path / "new-parent" / "journal.sqlite"
    with pytest.raises(ValueError, match="not found"):
        restore(tmp_path / "missing.sqlite", destination)
    assert not destination.exists()
    assert not destination.parent.exists()


@pytest.mark.parametrize("payload", [b"not a sqlite database", b"SQLite format 3\x00" + b"\x00" * 96])
def test_invalid_sqlite_is_rejected_before_destination_creation(tmp_path, payload):
    source = tmp_path / "bad.sqlite"
    source.write_bytes(payload)
    destination = tmp_path / "new-parent" / "journal.sqlite"
    with pytest.raises((sqlite3.DatabaseError, ValueError)):
        restore(source, destination)
    assert source.read_bytes() == payload
    assert not destination.exists()
    assert not destination.parent.exists()


def test_sqlite_with_missing_journal_tables_is_not_a_valid_archive(tmp_path):
    source = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
    destination = tmp_path / "restored.sqlite"
    with pytest.raises(sqlite3.DatabaseError):
        restore(source, destination)
    assert not destination.exists()


def test_unsupported_schema_is_rejected_before_copy(journal, tmp_path):
    source, _ = journal
    with sqlite3.connect(source.path) as db:
        db.execute("UPDATE metadata SET version='market-eod-archive.v999'")
    destination = tmp_path / "restored.sqlite"
    with pytest.raises(ValueError, match="schema"):
        restore(source.path, destination)
    assert not destination.exists()


def test_mismatched_revision_hash_is_rejected_without_copying(journal, tmp_path):
    source, _ = journal
    with sqlite3.connect(source.path) as db:
        db.execute("INSERT INTO revisions(run_id,asof,recorded_at,rank,content_sha256,body) VALUES (?,?,?,?,?,?)",
                   ("corrupted_revision", DAY, FINISH, 0, "a" * 64, canonical({"publication_eligible": False})))
    destination = tmp_path / "restored.sqlite"
    before = digest(source.path.read_bytes())
    with pytest.raises(ValueError, match="hash/publication"):
        restore(source.path, destination)
    assert not destination.exists()
    assert digest(source.path.read_bytes()) == before


def test_mismatched_raw_response_hash_is_rejected_without_copying(journal, tmp_path):
    source, _ = journal
    with sqlite3.connect(source.path) as db:
        db.execute("INSERT INTO responses(run_id,source_id,url,fetched_at,http_status,raw_sha256,body) VALUES (?,?,?,?,?,?,?)",
                   ("interrupted_later", "pool", URL, FINISH, 200, digest(b"original"), b"tampered"))
    destination = tmp_path / "restored.sqlite"
    with pytest.raises(ValueError, match="raw response hash"):
        restore(source.path, destination)
    assert not destination.exists()


@pytest.mark.parametrize("publication", [True, "false", None])
def test_correct_hash_does_not_override_publication_boundary(journal, tmp_path, publication):
    source, _ = journal
    body = canonical({"asof": DAY, "publication_eligible": publication})
    with sqlite3.connect(source.path) as db:
        db.execute("INSERT INTO revisions(run_id,asof,recorded_at,rank,content_sha256,body) VALUES (?,?,?,?,?,?)",
                   ("wrong_publication", DAY, FINISH, 0, digest(body.encode()), body))
    destination = tmp_path / "restored.sqlite"
    with pytest.raises(ValueError, match="publication"):
        restore(source.path, destination)
    assert not destination.exists()


def test_invalid_json_with_correct_digest_does_not_restore(journal, tmp_path):
    source, _ = journal
    body = "not json"
    with sqlite3.connect(source.path) as db:
        db.execute("INSERT INTO revisions(run_id,asof,recorded_at,rank,content_sha256,body) VALUES (?,?,?,?,?,?)",
                   ("invalid_json_body", DAY, FINISH, 0, digest(body.encode()), body))
    destination = tmp_path / "restored.sqlite"
    with pytest.raises(json.JSONDecodeError):
        restore(source.path, destination)
    assert not destination.exists()


def test_existing_destination_bytes_are_never_replaced(journal, tmp_path):
    source, _ = journal
    destination = tmp_path / "active.sqlite"
    original = b"existing user data must remain unchanged"
    destination.write_bytes(original)
    with pytest.raises(ValueError, match="existing active archive"):
        restore(source.path, destination)
    assert destination.read_bytes() == original


def test_existing_valid_destination_keeps_its_own_records(journal, tmp_path):
    source, _ = journal
    active = EODArchive(tmp_path / "active.sqlite")
    active.start("different_active", asof="2026-11-09", mode="capture", now=START)
    before = active.report()
    with pytest.raises(ValueError, match="existing active archive"):
        restore(source.path, active.path)
    assert active.report() == before


def test_source_cannot_be_restored_onto_itself(journal):
    source, _ = journal
    before = digest(source.path.read_bytes())
    with pytest.raises(ValueError, match="existing active archive"):
        restore(source.path, source.path)
    assert digest(source.path.read_bytes()) == before


def alter_test_database(path, table, sql, parameters=(), *, action="UPDATE"):
    """Simulate externally corrupted metadata in a disposable test database only.

    Reinstall the trigger so a negative test cannot pass just because its trigger
    was absent. No production archive or original research file is modified.
    """
    assert table in {"events", "responses", "revisions"}
    assert action in {"UPDATE", "DELETE"}
    with sqlite3.connect(path) as db:
        db.execute(f"DROP TRIGGER {table}_{action.lower()}")
        db.execute(sql, parameters)
        db.execute(f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} "
                   "BEGIN SELECT RAISE(ABORT, 'append-only archive'); END")


@pytest.mark.parametrize("column,value", [
    ("asof", "2026-11-05"),
    ("recorded_at", "2026-11-06T08:00:00.000000+00:00"),
    ("run_id", "different_run_id"),
])
def test_revision_coordinates_cannot_disagree_with_valid_body_hash_or_receipt(journal, tmp_path, column, value):
    source, _ = journal
    alter_test_database(source.path, "revisions", f"UPDATE revisions SET {column}=? WHERE seq=1", (value,))
    with sqlite3.connect(source.path) as db:
        sha, body = db.execute("SELECT content_sha256,body FROM revisions WHERE seq=1").fetchone()
    assert digest(body.encode()) == sha  # The hash alone does not detect this defect.
    destination = tmp_path / "must-not-restore.sqlite"
    with pytest.raises(ValueError):
        restore(source.path, destination)
    assert not destination.exists()


@pytest.mark.parametrize("kind,recorded", [
    ("started", "2026-11-10T02:00:00.000000+00:00"),
    ("finished", "2026-11-06T08:00:00.000000+00:00"),
])
def test_event_row_timestamp_cannot_disagree_with_seal_or_reverse_the_run(journal, tmp_path, kind, recorded):
    source, _ = journal
    alter_test_database(source.path, "events", "UPDATE events SET recorded_at=? WHERE run_id=? AND kind=?",
                        (recorded, "original_research", kind))
    destination = tmp_path / "must-not-restore.sqlite"
    with pytest.raises(ValueError):
        restore(source.path, destination)
    assert not destination.exists()


@pytest.mark.parametrize("key,value", [
    ("asof", "2026-11-05"),
    ("recorded_at", "2026-11-06T08:00:00.000000+00:00"),
    ("run_id", "another_receipt_run"),
    ("revision", 999),
    ("content_sha256", "b" * 64),
    ("status", "failed"),
    ("mode", "capture"),
])
def test_final_receipt_must_match_started_event_and_its_revision(journal, tmp_path, key, value):
    source, _ = journal
    with sqlite3.connect(source.path) as db:
        body = json.loads(db.execute("SELECT body FROM events WHERE run_id=? AND kind='finished'",
                                     ("original_research",)).fetchone()[0])
    body[key] = value
    alter_test_database(source.path, "events", "UPDATE events SET body=? WHERE run_id=? AND kind='finished'",
                        (canonical(body), "original_research"))
    destination = tmp_path / "must-not-restore.sqlite"
    with pytest.raises(ValueError):
        restore(source.path, destination)
    assert not destination.exists()


@pytest.mark.parametrize("kind", ["started", "finished"])
def test_revision_with_missing_run_receipt_is_not_a_resumable_archive(journal, tmp_path, kind):
    source, _ = journal
    alter_test_database(source.path, "events", "DELETE FROM events WHERE run_id=? AND kind=?",
                        ("original_research", kind), action="DELETE")
    destination = tmp_path / "must-not-restore.sqlite"
    with pytest.raises(ValueError):
        restore(source.path, destination)
    assert not destination.exists()


def test_finalize_makes_real_transfer_backup_with_failed_and_interrupted_runs(journal, tmp_path):
    source, sha = journal
    expected = source.report()
    directory = tmp_path / "transfer"

    result = finalize(source.path, directory)

    assert result["restored_revisions"] == 1
    assert json.loads((directory / "report.json").read_text(encoding="utf-8")) == expected
    destination = tmp_path / "next-run" / "journal.sqlite"
    restore(directory / "state.sqlite", destination)
    restored = EODArchive(destination)
    assert restored.report() == expected
    assert restored.raw_verified("original_research", "pool", sha)
    assert [run["status"] for run in restored.report()["runs"]] == [
        "partial", "failed", "interrupted_or_running",
    ]


def test_finalize_preserves_a_run_interrupted_before_first_finished_receipt(tmp_path):
    source = EODArchive(tmp_path / "interrupted.sqlite")
    source.start("interrupted_first", asof=DAY, mode="capture", now=START)
    sha = source.response("interrupted_first", source_id="pool", url=URL,
                          raw=b'{"error":"unavailable"}', http_status=503, fetched_at=START)
    directory = tmp_path / "transfer"

    result = finalize(source.path, directory)
    destination = tmp_path / "restored.sqlite"
    restore(directory / "state.sqlite", destination)
    restored = EODArchive(destination)

    assert result["restored_revisions"] == 0
    assert restored.report() == source.report()
    assert restored.report()["runs"][0]["status"] == "interrupted_or_running"
    assert not restored.raw_verified("interrupted_first", "pool", sha)
    assert restored.best() is None


@pytest.mark.parametrize("failure", ["missing", "bad_sqlite", "bad_hash"])
def test_finalize_bad_source_does_not_create_transfer_or_empty_replacement(tmp_path, failure):
    source = tmp_path / "source.sqlite"
    if failure == "bad_sqlite":
        source.write_bytes(b"invalid database")
    elif failure == "bad_hash":
        archive, _ = make_journal(source)
        alter_test_database(archive.path, "revisions", "UPDATE revisions SET content_sha256=? WHERE seq=1", ("0" * 64,))
    directory = tmp_path / "must-not-upload"
    original = source.read_bytes() if source.exists() else None

    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        finalize(source, directory)

    assert not directory.exists()
    assert (source.read_bytes() if source.exists() else None) == original
