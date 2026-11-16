import gzip
import hashlib
import json
import os
import subprocess

import pytest

from research.data import events
from research.data.versions import list_versions, load_as_of
from scripts.backfill_versions_from_git import backfill
from scripts.publish_versioned import KIND_PATHS, publish_record
from scripts.publish_versioned import main as publish_main


def _source(tmp_path, record, name="src.json"):
    path = tmp_path / name
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def _record(asof="2026-11-16", generated="2026-11-16T18:00:00+08:00", value=1):
    return {
        "asof": asof,
        "generated": generated,
        "value": value,
        "sources": {
            "good": {"ok": True},
            "bad": {"ok": False},
            "ignored": "not a source object",
        },
    }


def test_registry_matches_published_workflow_paths():
    assert KIND_PATHS == {
        "market": ("market/market_latest.json", "market/{asof}.json"),
        "abnormal": ("market/abnormal_latest.json", None),
        "bottom_signal": ("market/bottom_signal_latest.json", None),
        "range": ("market/range_latest.json", None),
        "events": ("events/events_latest.json", "events/events_{asof}.json"),
        "macro": ("macro/macro_latest.json", "macro/macro_{asof}.json"),
        "nt_etf": ("nt_etf/nt_etf_latest.json", "nt_etf/nt_etf_{asof}.json"),
        "growth": ("growth/growth_latest.json", "growth/growth_{asof}.json"),
    }


def test_publish_writes_immutable_version_manifest_and_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1234")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    source = _source(tmp_path, _record())
    root = tmp_path / "stock-results"
    raw = source.read_bytes()

    changed = publish_record(
        "market",
        source,
        root,
        published_at="2026-11-16T10:05:00Z",
    )

    versions = list_versions(root, "market", "2026-11-16")
    assert len(versions) == 1
    entry = versions[0]
    version_path = root / entry["file"]
    assert gzip.decompress(version_path.read_bytes()) == raw
    assert version_path.read_bytes()[4:8] == b"\x00\x00\x00\x00"
    assert entry == {
        "file": entry["file"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "fetched_at": "2026-11-16T10:00:00Z",
        "published_at": "2026-11-16T10:05:00Z",
        "run_id": "1234",
        "event": "schedule",
        "sources_ok": {"good": True, "bad": False},
        "backfilled_from_git": False,
    }
    assert entry["file"].startswith("versions/market/2026-11-16/20261116T100000Z_")
    latest = json.loads((root / KIND_PATHS["market"][0]).read_text(encoding="utf-8"))
    assert latest["version"] == {
        "kind": "market",
        "asof": "2026-11-16",
        "file": entry["file"],
        "sha256": entry["sha256"],
    }
    assert json.loads((root / "versions/market/index.json").read_text()) == {
        "2026-11-16": {
            "count": 1,
            "last_fetched_at": "2026-11-16T10:00:00Z",
        }
    }
    assert "versions/market/index.json" in changed
    assert "market/2026-11-16.json" in changed


def test_identical_source_skips_new_version(tmp_path):
    source = _source(tmp_path, _record())
    root = tmp_path / "stock-results"
    publish_record("market", source, root, published_at="2026-11-16T10:05:00Z")

    changed = publish_record("market", source, root, published_at="2026-11-16T11:05:00Z")

    assert len(list_versions(root, "market", "2026-11-16")) == 1
    assert not any(path.endswith(".json.gz") for path in changed)


def test_cli_prints_add_paths_and_reports_duplicate_skip(tmp_path, capsys):
    source = _source(tmp_path, _record())
    root = tmp_path / "stock-results"
    args = ["--kind", "market", "--src", str(source), "--root", str(root)]

    assert publish_main(args) == 0
    first = capsys.readouterr()
    assert "market/market_latest.json" in first.out
    assert "versions/market/2026-11-16/index.json" in first.out

    assert publish_main(args) == 0
    second = capsys.readouterr()
    assert second.out == ""
    assert "identical content; skipped new version" in second.err


def test_existing_version_file_with_different_content_is_an_error(tmp_path):
    source = _source(tmp_path, _record())
    raw = source.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    target = (
        tmp_path
        / "stock-results"
        / "versions"
        / "market"
        / "2026-11-16"
        / f"20261116T100000Z_{sha256[:8]}.json.gz"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(gzip.compress(b"different content", mtime=0))

    with pytest.raises(FileExistsError, match="different content"):
        publish_record("market", source, tmp_path / "stock-results")
    assert gzip.decompress(target.read_bytes()) == b"different content"


def test_older_asof_gets_version_and_dated_file_without_replacing_latest(tmp_path):
    root = tmp_path / "stock-results"
    newer = _source(tmp_path, _record("2026-11-16", "2026-11-16T10:00:00Z", 2), "new.json")
    older = _source(tmp_path, _record("2026-11-15", "2026-11-16T11:00:00Z", 1), "old.json")
    publish_record("market", newer, root)
    original_latest = (root / KIND_PATHS["market"][0]).read_bytes()

    publish_record("market", older, root)

    assert (root / KIND_PATHS["market"][0]).read_bytes() == original_latest
    dated = json.loads((root / "market/2026-11-15.json").read_text(encoding="utf-8"))
    assert dated["asof"] == "2026-11-15"
    assert len(list_versions(root, "market", "2026-11-15")) == 1


def test_manifest_entries_remain_unchanged_after_append(tmp_path):
    root = tmp_path / "stock-results"
    first = _source(tmp_path, _record(value=1), "first.json")
    second = _source(
        tmp_path,
        _record(generated="2026-11-16T19:00:00+08:00", value=2),
        "second.json",
    )
    publish_record("market", first, root)
    old_entry = list_versions(root, "market", "2026-11-16")[0]
    old_file = (root / old_entry["file"]).read_bytes()

    publish_record("market", second, root)

    entries = list_versions(root, "market", "2026-11-16")
    assert entries[0] == old_entry
    assert (root / old_entry["file"]).read_bytes() == old_file
    assert len(entries) == 2


def test_load_as_of_selects_latest_or_latest_known_version(tmp_path):
    root = tmp_path / "stock-results"
    first = _source(
        tmp_path,
        _record(generated="2026-11-16T10:00:00Z", value=1),
        "first.json",
    )
    second = _source(
        tmp_path,
        _record(generated="2026-11-16T11:00:00Z", value=2),
        "second.json",
    )
    publish_record("market", first, root)
    publish_record("market", second, root)

    assert load_as_of(root, "market", "2026-11-16")["value"] == 2
    assert (
        load_as_of(root, "market", "2026-11-16", "2026-11-16T10:30:00Z")["value"]
        == 1
    )
    assert load_as_of(root, "market", "2026-11-16", "2026-11-16T09:00:00Z") is None
    assert list_versions(root, "market", "2026-11-15") == []


@pytest.mark.parametrize(
    ("category", "base", "other"),
    [
        (
            "lift",
            {"code": "000001", "free_date": "2026-12-01", "free_shares_type": "首发"},
            {"code": "000002", "free_date": "2026-12-01", "free_shares_type": "首发"},
        ),
        (
            "dividend",
            {
                "code": "000001",
                "ex_dividend_date": "2026-12-01",
                "report_date": "2026-09-30",
                "assign_progress": "实施",
            },
            {
                "code": "000002",
                "ex_dividend_date": "2026-12-01",
                "report_date": "2026-09-30",
                "assign_progress": "实施",
            },
        ),
        (
            "forecast",
            {
                "code": "000001",
                "notice_date": "2026-11-16",
                "report_date": "2026-09-30",
                "predict_type": "预增",
            },
            {
                "code": "000002",
                "notice_date": "2026-11-16",
                "report_date": "2026-09-30",
                "predict_type": "预增",
            },
        ),
    ],
)
def test_event_first_seen_carries_existing_legacy_and_new_items(
    category, base, other
):
    existing_time = "2026-11-12T10:00:00Z"
    previous_generated = "2026-11-13T10:00:00Z"
    generated = "2026-11-16T10:00:00Z"
    previous = [
        {**base, "name": "existing", "first_seen_at": existing_time},
        {**other, "name": "legacy"},
    ]
    current = [
        {**base, "name": "existing"},
        {**other, "name": "legacy"},
        {**{**base, "code": "000003"}, "name": "new"},
    ]

    result = events._carry_first_seen(
        category, current, previous, previous_generated, generated
    )

    assert result == [
        {**base, "name": "existing", "first_seen_at": existing_time},
        {**other, "name": "legacy", "first_seen_at": previous_generated},
        {
            **{**base, "code": "000003"},
            "name": "new",
            "first_seen_at": generated,
        },
    ]
    assert current[0] == {**base, "name": "existing"}


def _git(repo, *args, env=None):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


def _commit(repo, label, timestamp):
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        }
    )
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        label,
        env=env,
    )


def test_backfill_walks_git_history_and_deduplicates_repeated_blobs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    dated = repo / "market/2026-01-02.json"
    latest = repo / "market/market_latest.json"
    first_record = _record("2026-01-02", "2026-01-02T10:00:00Z", 1)
    second_record = _record("2026-01-02", "2026-01-02T11:00:00Z", 2)

    for path in (dated, latest):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(first_record), encoding="utf-8")
    _git(repo, "add", "market")
    _commit(repo, "first version", "2026-01-02T10:05:00+00:00")

    for path in (dated, latest):
        path.write_text(json.dumps(second_record), encoding="utf-8")
    _git(repo, "add", "market")
    _commit(repo, "second version", "2026-01-02T11:05:00+00:00")

    for path in (dated, latest):
        path.write_text(json.dumps(first_record), encoding="utf-8")
    _git(repo, "add", "market")
    _commit(repo, "repeat first version", "2026-01-02T12:05:00+00:00")

    output = tmp_path / "backfilled"
    summary = backfill("main", output, repo=repo)

    assert summary["counts"] == {
        "abnormal": 0,
        "bottom_signal": 0,
        "events": 0,
        "growth": 0,
        "macro": 0,
        "market": 2,
        "nt_etf": 0,
        "range": 0,
    }
    assert summary["total_versions"] == 2
    assert summary["gzip_bytes"] == sum(
        path.stat().st_size for path in output.rglob("*.json.gz")
    )
    entries = list_versions(output, "market", "2026-01-02")
    assert len(entries) == 2
    assert all(entry["backfilled_from_git"] for entry in entries)
    assert all(entry["run_id"] is None for entry in entries)
    assert all(entry["event"] == "git-backfill" for entry in entries)
    assert [entry["published_at"] for entry in entries] == [
        "2026-01-02T10:05:00Z",
        "2026-01-02T11:05:00Z",
    ]
    assert [entry["fetched_at"] for entry in entries] == [
        "2026-01-02T10:00:00Z",
        "2026-01-02T11:00:00Z",
    ]


def test_backfill_reports_records_without_asof(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    latest = repo / "market/market_latest.json"
    latest.parent.mkdir()
    latest.write_text(json.dumps(_record(asof=None)), encoding="utf-8")
    _git(repo, "add", "market")
    _commit(repo, "record without asof", "2026-01-02T10:05:00+00:00")

    output = tmp_path / "backfilled"
    summary = backfill("main", output, repo=repo)

    assert summary["total_versions"] == 0
    assert summary["gzip_bytes"] == 0
    assert summary["skipped_invalid_asof"] == [
        {
            "commit": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "path": "market/market_latest.json",
            "asof": None,
            "error": "record must contain an ISO asof date",
        }
    ]
