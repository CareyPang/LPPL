import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "publish_stock_result.sh"


def _git(*args, cwd=None):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
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
    }
    subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
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
                "stock_meta": {"status": "eligible"},
            }
        ),
        encoding="utf-8",
    )
    (result_dir / "600519_history.json").write_text(
        '{"symbol":"sh600519","frames":[]}', encoding="utf-8"
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
    assert index["000002"]["status"] == "error"
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
