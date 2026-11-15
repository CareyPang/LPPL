import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from research.pipeline.stock_publish import merge_results

SCRIPT = Path(__file__).parents[1] / "scripts" / "publish_stock_result.sh"


def _git(*args, cwd=None):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _repositories(tmp_path):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    _git("init", "--bare", "--initial-branch=main", str(origin))
    repo.mkdir()
    _git("init", "--initial-branch=main", cwd=repo)
    _git("config", "user.name", "Test User", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    (repo / "README.md").write_text("publisher test\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    _git("remote", "add", "origin", str(origin), cwd=repo)
    _git("push", "-u", "origin", "main", cwd=repo)
    return origin, repo


def _publish(repo, result_dir, code, *, variant="stk_lite", weeks="104"):
    env = os.environ | {
        "CODE": code,
        "VARIANT": variant,
        "HISTORY_WEEKS": weeks,
        "STOCK_RESULT_DIR": str(result_dir),
        "STOCK_RUN_URL": f"https://example.test/runs/{code}",
        "STOCK_PYTHON": Path(sys.executable).as_posix(),
    }
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "bash"
    return subprocess.run(
        [bash, SCRIPT.as_posix()],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _remote_json(origin, path):
    raw = _git("--git-dir", str(origin), "show", f"stock-results:{path}")
    return json.loads(raw)


def test_publisher_creates_orphan_updates_index_and_publishes_error(tmp_path):
    origin, repo = _repositories(tmp_path)
    result_dir = repo / "out" / "stock"
    result_dir.mkdir(parents=True)
    (result_dir / "600519.json").write_text(
        json.dumps(
            {
                "symbol": "sh600519",
                "name": "贵州茅台",
                "asof": "2026-10-30",
                "stock_meta": {"status": "eligible", "variant": "stk_lite"},
            }
        ),
        encoding="utf-8",
    )
    (result_dir / "600519_history.json").write_text(
        '{"symbol":"sh600519","variant":"stk_lite","frames":[]}', encoding="utf-8"
    )

    _publish(repo, result_dir, "600519")

    commit_line = _git(
        "--git-dir", str(origin), "rev-list", "--parents", "-n", "1", "stock-results"
    )
    assert len(commit_line.split()) == 1
    assert _git("--git-dir", str(origin), "ls-tree", "--name-only", "stock-results") == "stock"
    first_index = _remote_json(origin, "stock/index.json")
    assert first_index["600519"]["name"] == "贵州茅台"
    assert first_index["600519"]["status"] == "eligible"
    assert _git(
        "--git-dir", str(origin), "show", "stock-results:stock/600519_history.json"
    )

    error = {
        "code": "000002",
        "error": "connection failed",
        "run_url": "https://example.test/runs/000002",
        "generated_at": "2026-11-02T00:00:00+00:00",
    }
    (result_dir / "000002.json").write_text(
        json.dumps({"asof": "2026-10-30", "stock_meta": {"status": "eligible"}}),
        encoding="utf-8",
    )
    (result_dir / "000002_error.json").write_text(
        json.dumps(error), encoding="utf-8"
    )
    _publish(repo, result_dir, "000002", weeks="0")

    index = _remote_json(origin, "stock/index.json")
    assert set(index) == {"000002", "600519"}
    assert index["000002"]["status"] == "eligible"
    assert "last_error" in index["000002"]
    assert index["000002"]["asof"] == "2026-10-30"
    assert index["000002"]["history_weeks"] == 0
    assert _git("--git-dir", str(origin), "show", "stock-results:stock/000002.json")
    assert _remote_json(origin, "stock/000002_error.json") == error


def test_batch_publisher_keeps_only_variant_and_asof_compatible_histories(tmp_path):
    origin, repo = _repositories(tmp_path)
    stock_dir = repo / "stock"
    stock_dir.mkdir()
    histories = {
        "000001": {
            "variant": "stk_lite",
            "frames": [{"asof": "2026-10-29"}, {"asof": "2026-10-30"}],
        },
        "000002": {
            "variant": "stk_full",
            "frames": [{"asof": "2026-10-30"}],
        },
        "000003": {
            "variant": "stk_lite",
            "frames": [{"asof": "2026-10-31"}],
        },
    }
    for code, history in histories.items():
        (stock_dir / f"{code}_history.json").write_text(
            json.dumps(history), encoding="utf-8"
        )
    _git("checkout", "-b", "stock-results", cwd=repo)
    _git("add", "stock", cwd=repo)
    _git("commit", "-m", "initial stock histories", cwd=repo)
    _git("push", "-u", "origin", "stock-results", cwd=repo)
    _git("checkout", "main", cwd=repo)

    result_dir = repo / "out" / "stock"
    result_dir.mkdir(parents=True)
    for code in histories:
        (result_dir / f"{code}.json").write_text(
            json.dumps(
                {
                    "asof": "2026-10-30",
                    "stock_meta": {"status": "eligible", "variant": "stk_lite"},
                }
            ),
            encoding="utf-8",
        )

    _publish(repo, result_dir, "", variant="stk_lite", weeks="0")

    published_files = set(
        _git(
            "--git-dir",
            str(origin),
            "ls-tree",
            "-r",
            "--name-only",
            "stock-results",
            "stock/",
        ).splitlines()
    )
    assert "stock/000001_history.json" in published_files
    assert "stock/000002_history.json" not in published_files
    assert "stock/000003_history.json" not in published_files
    index = _remote_json(origin, "stock/index.json")
    assert index["000001"]["history_weeks"] == 2
    assert index["000002"]["history_weeks"] == 0
    assert index["000003"]["history_weeks"] == 0


def test_batch_publisher_skips_older_records_and_replaces_with_newer(tmp_path):
    origin, repo = _repositories(tmp_path)
    stock_dir = repo / "stock"
    stock_dir.mkdir()
    published_record = {
        "asof": "2026-11-02",
        "name": "published",
        "stock_meta": {"status": "eligible", "variant": "stk_lite"},
    }
    published_history = {
        "variant": "stk_lite",
        "frames": [{"asof": "2026-11-01"}, {"asof": "2026-11-02"}],
    }
    published_index = {
        "000001": {
            "name": "published",
            "asof": "2026-11-02",
            "variant": "stk_lite",
            "history_weeks": 2,
            "generated_at": "2026-11-02T10:00:00+00:00",
            "run_url": "https://example.test/old",
            "status": "eligible",
        }
    }
    (stock_dir / "000001.json").write_text(
        json.dumps(published_record), encoding="utf-8"
    )
    (stock_dir / "000001_history.json").write_text(
        json.dumps(published_history), encoding="utf-8"
    )
    (stock_dir / "index.json").write_text(
        json.dumps(published_index), encoding="utf-8"
    )
    _git("checkout", "-b", "stock-results", cwd=repo)
    _git("add", "stock", cwd=repo)
    _git("commit", "-m", "initial published stock result", cwd=repo)
    _git("push", "-u", "origin", "stock-results", cwd=repo)
    _git("checkout", "main", cwd=repo)

    result_dir = repo / "out" / "stock"
    result_dir.mkdir(parents=True)
    backfill_record = {
        "asof": "2026-10-30",
        "name": "backfill",
        "stock_meta": {"status": "eligible", "variant": "stk_lite"},
    }
    (result_dir / "000001.json").write_text(
        json.dumps(backfill_record), encoding="utf-8"
    )
    (result_dir / "000001_error.json").write_text(
        json.dumps({"code": "000001", "asof": "2026-10-30", "error": "old failure"}),
        encoding="utf-8",
    )
    (result_dir / "000001_history.json").write_text(
        json.dumps({"variant": "stk_full", "frames": [{"asof": "2026-10-30"}]}),
        encoding="utf-8",
    )

    backfill_run = _publish(repo, result_dir, "", weeks="0")
    assert (
        "skip 000001: published asof 2026-11-02 newer than batch 2026-10-30"
        in backfill_run.stdout
    )
    assert _remote_json(origin, "stock/000001.json") == published_record
    assert _remote_json(origin, "stock/index.json") == published_index
    assert _remote_json(origin, "stock/000001_history.json") == published_history
    published_files = set(
        _git(
            "--git-dir", str(origin), "ls-tree", "-r", "--name-only", "stock-results", "stock/"
        ).splitlines()
    )
    assert "stock/000001_error.json" not in published_files

    latest_record = {
        "asof": "2026-11-03",
        "name": "new latest",
        "stock_meta": {"status": "eligible", "variant": "stk_lite"},
    }
    latest_history = {
        "variant": "stk_lite",
        "frames": [
            {"asof": "2026-11-01"},
            {"asof": "2026-11-02"},
            {"asof": "2026-11-03"},
        ],
    }
    (result_dir / "000001.json").write_text(
        json.dumps(latest_record), encoding="utf-8"
    )
    (result_dir / "000001_error.json").unlink()
    (result_dir / "000001_history.json").write_text(
        json.dumps(latest_history), encoding="utf-8"
    )

    _publish(repo, result_dir, "", weeks="0")

    assert _remote_json(origin, "stock/000001.json") == latest_record
    assert _remote_json(origin, "stock/000001_history.json") == latest_history
    latest_index = _remote_json(origin, "stock/index.json")
    assert latest_index["000001"]["asof"] == "2026-11-03"
    assert latest_index["000001"]["history_weeks"] == 3


def _job_record(mode="current", requested_at="2026-11-06T00:00:00Z", **extra):
    record = {"code": "600519", "job_id": str(uuid.uuid4()), "mode": mode,
              "requested_at": requested_at, "source_sha": "a" * 40,
              "asof": "2026-11-05", "variant": "stk_lite", "data_version": "data-v1",
              "model_version": "model-v1", "fit_code_version": "fit-v1",
              "schema_version": "stock_result_v1", "stock_meta": {"status": "eligible"}}
    if mode == "history":
        record["frames"] = [{"asof": "2026-10-30"}, {"asof": "2026-11-05"}]
    return record | extra


def _write(directory, name, record):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(record), encoding="utf-8")


def test_history_only_publishes_job_result_without_replacing_current(tmp_path):
    origin, repo = _repositories(tmp_path)
    out = repo / "out"
    current = _job_record() | {"generated_at": "2026-11-06T00:00:00Z"}
    _write(out, "600519.json", current)
    _publish(repo, out, "600519", weeks="0")
    (out / "600519.json").unlink()
    history = _job_record("history", "2026-11-06T00:01:00Z") | {
        "generated_at": "2026-11-06T00:01:00Z",
    }
    _write(out, "600519_history.json", history)
    _publish(repo, out, "600519", weeks="104")
    assert _remote_json(origin, "stock/600519.json") == current
    assert _remote_json(origin, "stock/600519_history.json") == history
    assert _remote_json(origin, f"stock/jobs/{history['job_id']}/600519_history.json") == history
    entry = _remote_json(origin, "stock/index.json")["600519"]
    assert entry["history_weeks"] == 2
    assert entry["current_generated_at"] == current["generated_at"]
    assert entry["history_generated_at"] == history["generated_at"]


def test_late_job_and_error_are_archived_without_overwriting_new_good_result(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    latest = _job_record(requested_at="2026-11-06T01:00:00Z") | {
        "generated_at": "2026-11-06T01:00:00Z",
    }
    _write(out, "600519.json", latest)
    merge_results(published, out, ["600519"])
    index_before = json.loads((published / "index.json").read_text())["600519"]
    assert index_before["current_generated_at"] == latest["generated_at"]
    assert index_before["history_generated_at"] is None
    old = _job_record(requested_at="2026-11-06T00:00:00Z") | {
        "generated_at": "2026-11-06T00:00:00Z",
    }
    error = old | {"error": "old failure", "error_code": "COMPUTE_FAILED"}
    _write(out, "600519.json", old)
    _write(out, "600519_error.json", error)
    merge_results(published, out, ["600519"])
    assert json.loads((published / "600519.json").read_text()) == latest
    assert json.loads((published / "index.json").read_text())["600519"] == index_before
    assert not (published / "600519_error.json").exists()
    assert (published / "jobs" / old["job_id"] / "600519_error.json").exists()


def test_nightly_current_without_job_id_survives_older_query_record(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    nightly = {
        "code": "600519",
        "symbol": "sh600519",
        "asof": "2026-11-05",
        "generated_at": "2026-11-06T01:00:00Z",
        "source_sha": "a" * 40,
        "fit_code_version": "fit-v1",
        "stock_meta": {"status": "eligible", "variant": "stk_lite"},
    }
    _write(out, "600519.json", nightly)
    merge_results(published, out, ["600519"])
    index_before = json.loads((published / "index.json").read_text())["600519"]
    assert index_before["current_generated_at"] == nightly["generated_at"]

    query = _job_record(requested_at="2026-11-06T00:30:00Z") | {
        "asof": nightly["asof"], "generated_at": "2026-11-06T00:30:00Z",
    }
    _write(out, "600519.json", query)
    merge_results(published, out, ["600519"])

    assert json.loads((published / "600519.json").read_text()) == nightly
    assert json.loads((published / "index.json").read_text())["600519"] == index_before


def test_requested_at_without_job_id_is_rejected(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    _write(out, "600519.json", {
        "code": "600519",
        "requested_at": "2026-11-06T00:30:00Z",
        "source_sha": "a" * 40,
    })
    with pytest.raises(ValueError, match="job_id, requested_at and source_sha must be supplied together"):
        merge_results(published, out, ["600519"])


def test_new_failure_preserves_current_result_and_status(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    latest = _job_record()
    _write(out, "600519.json", latest)
    merge_results(published, out, ["600519"])
    (out / "600519.json").unlink()
    error = _job_record(requested_at="2026-11-06T01:00:00Z", error="failed", error_code="COMPUTE_FAILED")
    _write(out, "600519_error.json", error)
    merge_results(published, out, ["600519"])
    assert json.loads((published / "600519.json").read_text()) == latest
    entry = json.loads((published / "index.json").read_text())["600519"]
    assert entry["status"] == "eligible" and entry["last_error"]["job_id"] == error["job_id"]


def test_job_result_is_immutable_and_path_identity_is_validated(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    record = _job_record()
    _write(out, "600519.json", record)
    merge_results(published, out, ["600519"])
    _write(out, "600519.json", record | {"asof": "2026-11-06"})
    with pytest.raises(ValueError, match="immutable"):
        merge_results(published, out, ["600519"])
    _write(out, "600519.json", record | {"job_id": "../../escape"})
    with pytest.raises(ValueError):
        merge_results(published, out, ["600519"])
    assert json.loads((published / "600519.json").read_text()) == record


def test_current_keeps_compatible_history_but_archives_incompatible_version(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    current, history = _job_record(), _job_record("history")
    _write(out, "600519.json", current)
    _write(out, "600519_history.json", history)
    merge_results(published, out, ["600519"])
    (out / "600519_history.json").unlink()
    next_current = _job_record(requested_at="2026-11-06T01:00:00Z")
    _write(out, "600519.json", next_current)
    merge_results(published, out, ["600519"])
    assert json.loads((published / "600519_history.json").read_text()) == history
    _write(out, "600519.json", _job_record(requested_at="2026-11-06T02:00:00Z", fit_code_version="fit-v2"))
    merge_results(published, out, ["600519"])
    assert not (published / "600519_history.json").exists()
    assert list((published / "archive").glob("600519_history-*.json"))
    assert (published / "jobs" / history["job_id"] / "600519_history.json").exists()


def test_append_only_data_keeps_history_but_restatement_retires_it(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    history = _job_record("history", frames=[{"asof": "2026-11-05", "fit_input_hash": "original"}])
    _write(out, "600519.json", _job_record())
    _write(out, "600519_history.json", history)
    merge_results(published, out, ["600519"])
    (out / "600519_history.json").unlink()
    _write(out, "600519.json", _job_record(
        requested_at="2026-11-06T01:00:00Z", data_version="next-day",
        history_input_hashes={"2026-11-05": "original"},
    ))
    merge_results(published, out, ["600519"])
    assert (published / "600519_history.json").exists()
    _write(out, "600519.json", _job_record(
        requested_at="2026-11-06T02:00:00Z", data_version="restated",
        history_input_hashes={"2026-11-05": "revised"},
    ))
    merge_results(published, out, ["600519"])
    assert not (published / "600519_history.json").exists()
    assert json.loads((published / "index.json").read_text())["600519"]["history_weeks"] == 0


def test_late_history_never_replaces_newer_history(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    _write(out, "600519.json", _job_record())
    latest = _job_record("history", "2026-11-06T02:00:00Z")
    _write(out, "600519_history.json", latest)
    merge_results(published, out, ["600519"])
    (out / "600519.json").unlink()
    late = _job_record("history", "2026-11-06T01:00:00Z")
    _write(out, "600519_history.json", late)
    merge_results(published, out, ["600519"])
    assert json.loads((published / "600519_history.json").read_text()) == latest
    assert (published / "jobs" / late["job_id"] / "600519_history.json").exists()


def test_old_nightly_cannot_roll_back_breadth(tmp_path):
    published, out = tmp_path / "stock", tmp_path / "out"
    _write(out, "600519.json", _job_record())
    latest = {"asof": "2026-11-05", "generated_at": "2026-11-06T01:00:00Z", "n": 300}
    _write(out, "breadth_sh000300.json", latest)
    merge_results(published, out, ["600519"])
    _write(out, "breadth_sh000300.json", {"asof": "2026-11-04", "generated_at": "2026-11-06T02:00:00Z", "n": 250})
    merge_results(published, out, ["600519"])
    assert json.loads((published / "breadth_sh000300.json").read_text()) == latest
