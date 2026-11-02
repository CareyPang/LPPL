import json
import os
import subprocess
from pathlib import Path

import pytest

from research.pipeline import stock_batch

SCRIPT = Path(__file__).parents[1] / "scripts" / "publish_stock_result.sh"


def _record(code, asof="2026-10-30", status="eligible", in_stats=True, std612=0, conf612=None):
    return {
        "symbol": f"sh{code}",
        "name": f"N{code}",
        "asof": asof,
        "top": {
            "indicators": {
                "6-12m": {"n_windows": 8, "confidence": {"standard": std612}},
                "12-24m": {"n_windows": 8, "confidence": {"standard": 0}},
            },
            "lppls_confidence": {"6-12m": conf612, "12-24m": None},
        },
        "stock_meta": {"status": status, "in_stats": in_stats, "variant": "stk_lite"},
    }


def test_load_universe_and_shard(tmp_path):
    path = tmp_path / "universe_x.json"
    path.write_text(
        json.dumps({"index": "sh000300", "snapshot": "2021-12-31", "codes": ["600519", "000001", "600519", "300750"]}),
        encoding="utf-8",
    )
    uni = stock_batch.load_universe(path)
    assert uni["codes"] == ["000001", "300750", "600519"]
    assert stock_batch.shard(uni["codes"], 0, 2) == ["000001", "600519"]
    assert stock_batch.shard(uni["codes"], 1, 2) == ["300750"]
    with pytest.raises(ValueError):
        stock_batch.shard(uni["codes"], 2, 2)
    path.write_text(json.dumps({"codes": ["60051"]}), encoding="utf-8")
    with pytest.raises(ValueError):
        stock_batch.load_universe(path)


def test_breadth_counts_only_in_stats_members_and_flags_mixed_asof(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "000001.json").write_text(json.dumps(_record("000001", std612=3, conf612=0.667)), encoding="utf-8")
    (out / "000002.json").write_text(json.dumps(_record("000002", std612=1, conf612=0.1)), encoding="utf-8")
    (out / "000003.json").write_text(
        json.dumps(_record("000003", asof="2026-11-02", status="delisted_or_long_suspended", in_stats=False, std612=5, conf612=0.9)),
        encoding="utf-8",
    )
    (out / "000004_error.json").write_text(json.dumps({"code": "000004", "error": "boom"}), encoding="utf-8")
    universe = {"index": "sh000300", "snapshot": "2021-12-31", "codes": ["000001", "000002", "000003", "000004", "000005"]}
    b = stock_batch.breadth(out, universe)
    assert b["n_members"] == 5 and b["n_results"] == 3 and b["n_error"] == 1 and b["n_missing"] == 1
    assert b["n"] == 2
    assert b["n_qualified_fit_dev"] == 2 and b["share_qualified_fit_dev"] == 1.0
    assert b["n_confidence_ge_0_5_dev"] == 1 and b["share_confidence_ge_0_5_dev"] == 0.5
    assert b["per_scale_qualified_fit"]["6-12m"] == 2 and b["per_scale_qualified_fit"]["12-24m"] == 0
    assert b["asof"] == "2026-10-30" and b["asof_consistent"] is False
    assert b["evidence"] == "descriptive" and "不是预测" in b["note"]


def test_run_batch_writes_error_file_and_continues(tmp_path, monkeypatch):
    def fake_predict(code, variant="stk_lite", asof=None, procs=None):
        if code == "000002":
            raise RuntimeError("fetch failed")
        return _record(code, asof=asof)

    monkeypatch.setattr(stock_batch.stock_pipeline, "predict", fake_predict)
    out = tmp_path / "out"
    out.mkdir()
    (out / "000001_error.json").write_text("{}", encoding="utf-8")
    summary = stock_batch.run_batch(["000001", "000002"], "2026-10-30", out, run_url="https://x/1")
    assert summary["ok"] == ["000001"] and summary["failed"] == ["000002"]
    assert json.loads((out / "000001.json").read_text(encoding="utf-8"))["asof"] == "2026-10-30"
    assert not (out / "000001_error.json").exists()
    err = json.loads((out / "000002_error.json").read_text(encoding="utf-8"))
    assert err["error"].startswith("RuntimeError") and err["run_url"] == "https://x/1"


def test_run_batch_failure_removes_stale_result_and_breadth_counts_error(tmp_path, monkeypatch):
    def fail_predict(*args, **kwargs):
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(stock_batch.stock_pipeline, "predict", fail_predict)
    out = tmp_path / "out"
    out.mkdir()
    (out / "000001.json").write_text(
        json.dumps(_record("000001")), encoding="utf-8"
    )

    summary = stock_batch.run_batch(["000001"], "2026-10-30", out)
    breadth = stock_batch.breadth(out, {"codes": ["000001"]})

    assert summary["failed"] == ["000001"] and summary["ok"] == []
    assert [path.name for path in out.iterdir()] == ["000001_error.json"]
    assert breadth["n_results"] == 0 and breadth["n_error"] == 1 and breadth["n_missing"] == 0


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_publisher_batch_mode_publishes_all_codes_and_breadth(tmp_path):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    _git("init", "--bare", "--initial-branch=main", str(origin))
    repo.mkdir()
    _git("init", "--initial-branch=main", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    _git("remote", "add", "origin", str(origin), cwd=repo)
    _git("push", "-u", "origin", "main", cwd=repo)

    result_dir = repo / "out" / "stock"
    result_dir.mkdir(parents=True)
    (result_dir / "000001.json").write_text(json.dumps(_record("000001")), encoding="utf-8")
    (result_dir / "000002_error.json").write_text(json.dumps({"code": "000002", "error": "boom", "asof": "2026-10-30"}), encoding="utf-8")
    (result_dir / "breadth_sh000300.json").write_text(json.dumps({"index": "sh000300", "n": 1}), encoding="utf-8")
    (result_dir / "_batch_0_of_1.json").write_text("{}", encoding="utf-8")

    env = os.environ | {
        "CODE": "",
        "VARIANT": "stk_lite",
        "HISTORY_WEEKS": "0",
        "STOCK_RESULT_DIR": str(result_dir),
        "STOCK_RUN_URL": "https://example.test/runs/batch",
    }
    subprocess.run(["bash", str(SCRIPT)], cwd=repo, env=env, check=True, capture_output=True, text=True)

    files = _git("--git-dir", str(origin), "ls-tree", "--name-only", "stock-results", "stock/").splitlines()
    assert sorted(files) == ["stock/000001.json", "stock/000002_error.json", "stock/breadth_sh000300.json", "stock/index.json"]
    index = json.loads(_git("--git-dir", str(origin), "show", "stock-results:stock/index.json"))
    assert index["000001"]["status"] == "eligible" and index["000001"]["asof"] == "2026-10-30"
    assert index["000002"]["status"] == "error" and index["000002"]["run_url"] == "https://example.test/runs/batch"
