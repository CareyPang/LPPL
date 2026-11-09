"""Real SQLite journal checks; synthetic bytes only, no providers or model calls."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from research.data.market_eod_archive import EODArchive, canonical, digest

DAY = "2026-11-06"
PRIOR = "2026-11-05"
START = "2026-11-09T02:00:00+00:00"
SEALED = "2026-11-09T02:01:00+00:00"
LATER = "2026-11-09T02:02:00+00:00"
URL = "https://data.example/pool?date=20261106&page=1"


def snapshot(asof=DAY, *, complete=False, pools=1, version="first"):
    return {
        "schema_version": "market-context.v1",
        "asof": asof,
        "publication_eligible": False,
        "evidence": "descriptive",
        "version": version,
        "daily_capture": {
            "quality": {
                "core_complete": complete,
                "pools": {
                    kind: {"structurally_complete": index < pools}
                    for index, kind in enumerate(("zt", "zb", "dt"))
                },
            },
        },
    }


@pytest.fixture
def archive(tmp_path):
    return EODArchive(tmp_path / "journal.sqlite3")


def seal(archive, run_id, value=None, *, asof=DAY, now=SEALED, status="partial"):
    value = snapshot(asof) if value is None else value
    archive.start(run_id, asof=asof, mode="historical_import", now=START)
    return archive.finish(run_id, status=status, detail={"test_only": True}, snapshot=value, now=now)


def test_empty_journal_has_no_invented_latest_or_history(archive):
    assert archive.best() is None
    assert archive.best(DAY) is None
    report = archive.report()
    assert report["runs"] == [] and report["revisions"] == []
    assert report["raw_response_count"] == 0
    assert report["publication_eligible"] is False
    assert report["model_input_eligible"] is False


def test_interrupted_run_remains_visible_and_retry_needs_its_own_id(archive):
    archive.start("interrupted_01", asof=DAY, mode="capture", now=START)
    report = archive.report()
    assert report["runs"][0]["status"] == "interrupted_or_running"
    assert archive.best(DAY) is None
    with pytest.raises(sqlite3.IntegrityError):
        archive.start("interrupted_01", asof=DAY, mode="capture", now=LATER)
    seal(archive, "independent_retry", snapshot(complete=True), status="sealed")
    assert len(archive.report()["runs"]) == 2
    assert archive.report()["runs"][0]["status"] == "interrupted_or_running"


@pytest.mark.parametrize("run_id", ["short", "bad/identifier", "x" * 101, "含有中文的编号"])
def test_invalid_run_ids_cannot_create_events(archive, run_id):
    with pytest.raises(ValueError, match="run id"):
        archive.start(run_id, asof=DAY, mode="capture", now=START)
    assert not archive.report()["runs"]


def test_run_mode_and_calendar_date_are_validated(archive):
    with pytest.raises(ValueError, match="mode"):
        archive.start("invalid_mode", asof=DAY, mode="public", now=START)
    with pytest.raises(ValueError):
        archive.start("invalid_date", asof="2026-02-30", mode="capture", now=START)
    assert not archive.report()["runs"]


def test_exact_history_never_falls_back_to_latest(archive):
    seal(archive, "current_snapshot", snapshot(complete=True), status="sealed")
    assert archive.best()["snapshot"]["asof"] == DAY
    assert archive.best(PRIOR) is None
    assert archive.best("2026-11-09") is None


def test_known_by_uses_first_local_seal_time_not_the_historical_asof(archive):
    seal(archive, "historical_replay", snapshot(), now=SEALED)
    assert archive.best(DAY, known_by="2026-11-06T23:59:59+08:00") is None
    assert archive.best(DAY, known_by=START) is None
    assert archive.best(DAY, known_by="2026-11-09T02:00:59.999999+00:00") is None
    found = archive.best(DAY, known_by=SEALED)
    assert found is not None
    assert found["snapshot"]["publication_eligible"] is False
    assert archive.best(DAY, known_by="2026-11-09T10:01:00+08:00") == found


def test_known_by_orders_fractional_seconds_correctly(archive):
    seal(archive, "fractional_seal", now="2026-11-09T02:01:00.000001+00:00")
    assert archive.best(DAY, known_by=SEALED) is None
    assert archive.best(DAY, known_by="2026-11-09T02:01:00.000001Z") is not None


def test_same_day_revisions_remain_available_at_their_own_knowledge_cutoffs(archive):
    first = seal(archive, "revision_first", snapshot(version="v1"), now=SEALED)
    second = seal(archive, "revision_second", snapshot(version="v2"), now=LATER)
    assert first["revision"] != second["revision"]
    assert archive.best(DAY)["snapshot"]["version"] == "v2"
    assert archive.best(DAY, known_by=SEALED)["snapshot"]["version"] == "v1"
    assert len(archive.report()["revisions"]) == 2
    for receipt in (first, second):
        assert receipt["publication_eligible"] is False
        assert receipt["first_public_visible_at"] is None


def test_later_failure_or_lower_quality_partial_does_not_replace_best_same_day(archive):
    good = snapshot(complete=True, pools=3, version="good")
    seal(archive, "best_complete", good, status="sealed")
    archive.start("failed_attempt", asof=DAY, mode="capture", now=START)
    archive.finish("failed_attempt", status="failed", detail={"reason": "upstream_timeout"}, now=LATER)
    seal(archive, "partial_attempt", snapshot(pools=1, version="degraded"), now=LATER)
    assert archive.best(DAY)["snapshot"] == good
    report = archive.report()
    assert len(report["revisions"]) == 2
    assert [run["status"] for run in report["runs"]] == ["sealed", "failed", "partial"]


def test_partial_pool_quality_orders_candidates_without_discarding_them(archive):
    seal(archive, "two_valid_pools", snapshot(pools=2, version="two"))
    seal(archive, "one_valid_pool", snapshot(pools=1, version="one"), now=LATER)
    assert archive.best(DAY)["snapshot"]["version"] == "two"
    assert len(archive.report()["revisions"]) == 2


def test_newer_failed_day_keeps_previous_usable_latest(archive):
    seal(archive, "previous_good_day", snapshot(PRIOR, complete=True), asof=PRIOR, status="sealed")
    archive.start("new_day_failed", asof=DAY, mode="capture", now=START)
    archive.finish("new_day_failed", status="failed", detail={"reason": "not_available"}, now=SEALED)
    assert archive.best()["snapshot"]["asof"] == PRIOR
    assert archive.best(DAY) is None


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_no_snapshot_receipts_do_not_create_revisions(archive, status):
    archive.start("status_no_data", asof=DAY, mode="capture", now=START)
    archive.finish("status_no_data", status=status, detail={}, now=SEALED)
    assert not archive.report()["revisions"]
    assert archive.report()["runs"][0]["status"] == status


@pytest.mark.parametrize("status,value", [
    ("failed", snapshot()), ("skipped", snapshot()), ("sealed", None), ("partial", None),
])
def test_final_status_and_snapshot_must_agree(archive, status, value):
    archive.start("bad_final_status", asof=DAY, mode="capture", now=START)
    with pytest.raises(ValueError):
        archive.finish("bad_final_status", status=status, detail={}, snapshot=value, now=SEALED)
    assert not archive.report()["revisions"]
    assert archive.report()["runs"][0]["status"] == "interrupted_or_running"


@pytest.mark.parametrize("change", [
    {"asof": PRIOR}, {"publication_eligible": True}, {"publication_eligible": "false"},
])
def test_cannot_seal_another_day_or_cross_publication_boundary(archive, change):
    archive.start("boundary_check", asof=DAY, mode="historical_import", now=START)
    with pytest.raises(ValueError, match="boundary"):
        archive.finish("boundary_check", status="partial", detail={}, snapshot={**snapshot(), **change}, now=SEALED)
    assert not archive.report()["revisions"]


def test_unknown_or_finished_runs_cannot_accept_more_writes(archive):
    with pytest.raises(ValueError, match="run"):
        archive.response("unknown_run", source_id="pool", url=URL, raw=b"{}", http_status=200)
    with pytest.raises(ValueError, match="run"):
        archive.finish("unknown_run", status="failed", detail={})
    seal(archive, "already_finished")
    with pytest.raises(ValueError, match="run"):
        archive.response("already_finished", source_id="pool", url=URL, raw=b"{}", http_status=200)
    with pytest.raises(ValueError, match="run"):
        archive.finish("already_finished", status="failed", detail={})
    assert len(archive.report()["revisions"]) == 1
    assert archive.report()["raw_response_count"] == 0


def test_final_receipt_serialization_failure_rolls_back_the_revision(archive):
    archive.start("atomic_rollback", asof=DAY, mode="fixture", now=START)
    with pytest.raises(ValueError):
        archive.finish("atomic_rollback", status="partial", detail={"bad": float("nan")}, snapshot=snapshot(), now=SEALED)
    assert archive.best(DAY) is None
    assert archive.report()["runs"][0]["status"] == "interrupted_or_running"
    assert not archive.report()["revisions"]
    archive.finish("atomic_rollback", status="partial", detail={}, snapshot=snapshot(), now=LATER)
    assert len(archive.report()["revisions"]) == 1


def test_final_receipt_cannot_be_backdated_before_the_local_run_started(archive):
    archive.start("backdated_finish", asof=PRIOR, mode="historical_import", now=START)
    with pytest.raises(ValueError):
        archive.finish("backdated_finish", status="partial", detail={}, snapshot=snapshot(PRIOR), now="2026-11-08T02:00:00Z")
    assert archive.best(PRIOR) is None


def test_response_keeps_exact_bytes_hash_and_safe_request_coordinates(archive):
    archive.start("raw_exact_bytes", asof=DAY, mode="capture", now=START)
    raw = b'{ "value": 1 }\r\n\x00'
    sha = archive.response("raw_exact_bytes", source_id="pool", raw=raw, http_status=200, fetched_at=START,
                           url=URL + "&token=secret&api_key=private#fragment")
    assert sha == digest(raw)
    assert archive.raw_verified("raw_exact_bytes", "pool", sha)
    assert not archive.raw_verified("raw_exact_bytes", "other_source", sha)
    assert not archive.raw_verified("other_run", "pool", sha)
    assert not archive.raw_verified("raw_exact_bytes", "pool", "a" * 64)
    assert not archive.raw_verified("raw_exact_bytes", "pool", None)
    with archive.connect() as db:
        row = db.execute("SELECT * FROM responses").fetchone()
    assert bytes(row["body"]) == raw
    assert "date=20261106" in row["url"] and "page=1" in row["url"]
    assert "secret" not in row["url"] and "private" not in row["url"] and "fragment" not in row["url"]


@pytest.mark.parametrize("http_status", [201, 204, 301, 403, 429, 500, 503])
def test_non_200_responses_are_retained_but_do_not_verify_as_success(archive, http_status):
    archive.start("failed_http_source", asof=DAY, mode="capture", now=START)
    sha = archive.response("failed_http_source", source_id="pool", url=URL, raw=b'{"error":"upstream"}', http_status=http_status, fetched_at=START)
    assert not archive.raw_verified("failed_http_source", "pool", sha)
    assert archive.report()["raw_response_count"] == 1


def test_bad_raw_input_cannot_partly_write_a_response(archive):
    archive.start("invalid_response", asof=DAY, mode="capture", now=START)
    for raw in ["not bytes", b"x" * (8 * 1024 * 1024 + 1)]:
        with pytest.raises(ValueError):
            archive.response("invalid_response", source_id="pool", url=URL, raw=raw, http_status=200)
    with pytest.raises(ValueError):
        archive.response("invalid_response", source_id="pool", url="https://user:pass@example.test/a", raw=b"{}", http_status=200)
    assert archive.report()["raw_response_count"] == 0


def test_raw_verification_recomputes_bytes_instead_of_trusting_the_stored_hash(archive):
    archive.start("raw_digest_mismatch", asof=DAY, mode="fixture", now=START)
    claimed = digest(b"original response")
    # A malformed/corrupted database row must not turn hash metadata into proof.
    # This is a separate insert into a disposable test database, never an update.
    with archive.connect() as db:
        db.execute(
            "INSERT INTO responses(run_id,source_id,url,fetched_at,http_status,raw_sha256,body) "
            "VALUES (?,?,?,?,?,?,?)",
            ("raw_digest_mismatch", "pool", URL, START, 200, claimed, b"different bytes"),
        )
    assert not archive.raw_verified("raw_digest_mismatch", "pool", claimed)


@pytest.mark.parametrize("table", ["events", "responses", "revisions"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
def test_database_itself_rejects_update_and_delete(archive, table, action):
    archive.start("immutable_records", asof=DAY, mode="fixture", now=START)
    archive.response("immutable_records", source_id="pool", url=URL, raw=b"{}", http_status=200, fetched_at=START)
    archive.finish("immutable_records", status="partial", detail={}, snapshot=snapshot(), now=SEALED)
    before = archive.report()
    with archive.connect() as db:
        sql = f"DELETE FROM {table} WHERE seq=1" if action == "DELETE" else f"UPDATE {table} SET run_id='rewritten_run' WHERE seq=1"
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(sql)
    assert archive.report() == before


def test_parallel_writers_use_real_sqlite_transactions_without_lost_records(archive):
    workers = 6
    barrier = Barrier(workers)

    def write_batch(worker):
        local = EODArchive(archive.path)
        barrier.wait(timeout=10)
        written = []
        for index in range(4):
            run_id = f"parallel_{worker}_{index}"
            local.start(run_id, asof=DAY, mode="fixture", now=START)
            sha = local.response(run_id, source_id="synthetic", url=URL, raw=run_id.encode(), http_status=200, fetched_at=START)
            receipt = local.finish(run_id, status="partial", detail={}, snapshot=snapshot(version=run_id), now=SEALED)
            assert local.raw_verified(run_id, "synthetic", sha)
            # Reads from another connection stay coherent while peers write.
            assert local.best(DAY) is not None
            written.append(receipt)
        return written

    with ThreadPoolExecutor(max_workers=workers) as pool:
        receipts = [item for batch in pool.map(write_batch, range(workers)) for item in batch]
    report = archive.report()
    assert len(receipts) == len(report["runs"]) == len(report["revisions"]) == 24
    assert report["raw_response_count"] == 24
    assert len({item["revision"] for item in receipts}) == 24
    assert all(run["status"] == "partial" for run in report["runs"])


def test_two_concurrent_finalizers_cannot_seal_the_same_run_twice(archive):
    archive.start("competing_final", asof=DAY, mode="fixture", now=START)
    barrier = Barrier(2)

    def finish(version):
        local = EODArchive(archive.path)
        barrier.wait(timeout=10)
        try:
            return local.finish("competing_final", status="partial", detail={}, snapshot=snapshot(version=version), now=SEALED)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(finish, ["a", "b"]))
    successful = [receipt for receipt in receipts if receipt is not None]
    assert len(successful) == 1
    assert len(archive.report()["revisions"]) == 1
    assert archive.best(DAY)["content_sha256"] == successful[0]["content_sha256"]
    with archive.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE run_id=?", ("competing_final",)).fetchone()[0] == 2


def test_backup_restores_history_raw_bytes_and_append_only_constraints(archive, tmp_path):
    archive.start("backup_source_01", asof=DAY, mode="capture", now=START)
    sha = archive.response("backup_source_01", source_id="pool", url=URL, raw=b'{"pool":[]}', http_status=200, fetched_at=START)
    archive.finish("backup_source_01", status="partial", detail={}, snapshot=snapshot(), now=SEALED)
    target = tmp_path / "backup" / "restored.sqlite3"
    archive.backup(target)
    restored = EODArchive(target)
    assert restored.report() == archive.report()
    assert restored.best(DAY) == archive.best(DAY)
    assert restored.raw_verified("backup_source_01", "pool", sha)
    with restored.connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM revisions")
    seal(archive, "post_backup_revision", snapshot(version="new"), now=LATER)
    assert restored.best(DAY)["snapshot"]["version"] == "first"
    assert archive.best(DAY)["snapshot"]["version"] == "new"


def test_backup_refuses_the_active_journal_even_via_equivalent_path(archive):
    with pytest.raises(ValueError, match="active"):
        archive.backup(archive.path.parent / "." / archive.path.name)


def test_stored_revision_hash_matches_the_canonical_snapshot(archive):
    value = snapshot(version="有明确证据边界")
    receipt = seal(archive, "canonical_digest", value)
    assert receipt["content_sha256"] == digest(canonical(value).encode())
    assert archive.best(DAY)["content_sha256"] == receipt["content_sha256"]


def test_reads_detect_a_revision_body_that_does_not_match_its_stored_digest(archive):
    with archive.connect() as db:
        db.execute(
            "INSERT INTO revisions(run_id,asof,recorded_at,rank,content_sha256,body) "
            "VALUES (?,?,?,?,?,?)",
            ("corrupt_input", DAY, SEALED, 0, "a" * 64, canonical(snapshot())),
        )
    with pytest.raises(ValueError, match="hash mismatch"):
        archive.best(DAY)
