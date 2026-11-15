import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_changelog.py"
SPEC = importlib.util.spec_from_file_location("build_changelog", SCRIPT)
BUILD_CHANGELOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_CHANGELOG)


def git(root, *args, date=None):
    env = os.environ.copy()
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def commit(root, subject, date):
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.test",
        "commit",
        "-m",
        subject,
        date=date,
    )


def write_json(root, relative_path, value):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def index_document(asof, version, status):
    return {
        "asof": asof,
        "data_version": version,
        "model_version": "model-a",
        "top": {"signal_status": status},
        "evidence_levels": {"ok": "可显示"},
        "validation": [{"split": "test", "status": "ok"}],
    }


def test_build_includes_main_snapshots_and_stock_results_history(tmp_path):
    git(tmp_path, "init", "--initial-branch=main")
    index_path = "web/mock/data/sh000001_latest.json"
    market_path = "web/mock/data/market/market_latest.json"
    write_json(tmp_path, index_path, index_document("2026-11-13", "v1", "signal"))
    write_json(
        tmp_path,
        market_path,
        {"asof": "2026-11-13", "sources": {"eastmoney": {"ok": True}}},
    )
    git(tmp_path, "add", index_path, market_path)
    commit(tmp_path, "publish v1", "2026-11-13T12:00:00+00:00")

    write_json(tmp_path, index_path, index_document("2026-11-14", "v2", "no_qualified_fit"))
    write_json(
        tmp_path,
        market_path,
        {
            "asof": "2026-11-14",
            "sources": {"eastmoney": {"ok": True}, "sina": {"ok": False}},
        },
    )
    git(tmp_path, "add", index_path, market_path)
    commit(tmp_path, "publish v2", "2026-11-14T12:00:00+00:00")

    git(tmp_path, "switch", "-c", "stock-results")
    stock_path = "index/sh000001_latest.json"
    write_json(tmp_path, stock_path, index_document("2026-11-15", "v3", "signal"))
    stock_market_path = "market/market_latest.json"
    write_json(
        tmp_path,
        stock_market_path,
        {"asof": "2026-11-15", "sources": {"eastmoney": {"ok": True}, "sina": {"ok": True}}},
    )
    git(tmp_path, "add", stock_path, stock_market_path)
    commit(tmp_path, "publish stock result", "2026-11-15T12:00:00+00:00")
    git(tmp_path, "update-ref", "refs/remotes/origin/stock-results", "HEAD")
    git(tmp_path, "switch", "main")

    output = tmp_path / "generated.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--out",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert set(report["files"]) == {
        "sh000001",
        "sh000016",
        "sh000300",
        "sh000905",
        "sz399001",
        "sz399006",
        "market",
    }
    history = report["files"]["sh000001"]
    assert [entry["subject"] for entry in history] == [
        "publish stock result",
        "publish v2",
        "publish v1",
    ]
    assert history[0]["source"] == "stock-results"
    assert history[0]["snapshot"]["数据版本"] == "v3"
    assert history[1]["snapshot"]["顶部结构状态"] == "主尺度没有合格拟合"
    assert history[1]["snapshot"]["检验 · 测试段"] == "可显示（ok）"
    market_history = report["files"]["market"]
    assert [entry["subject"] for entry in market_history] == [
        "publish stock result",
        "publish v2",
        "publish v1",
    ]
    assert market_history[0]["source"] == "stock-results"
    assert market_history[0]["snapshot"]["截止日"] == "2026-11-15"
    assert market_history[1]["snapshot"]["数据源可用"] == "1 / 2"
    assert all(not report["files"][symbol] for symbol in set(report["files"]) - {"sh000001", "market"})


def test_missing_git_history_produces_empty_lists(tmp_path):
    report = BUILD_CHANGELOG.build(tmp_path)

    assert set(report["files"]) == {
        "sh000001",
        "sh000016",
        "sh000300",
        "sh000905",
        "sz399001",
        "sz399006",
        "market",
    }
    assert all(not history for history in report["files"].values())
