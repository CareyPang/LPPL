#!/usr/bin/env python3
import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

INDEX_FILES = (
    ("sh000001", "上证指数"),
    ("sh000016", "上证50"),
    ("sh000300", "沪深300"),
    ("sh000905", "中证500"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
)
SPLIT_LABELS = {"dev": "开发段", "cal": "校准段", "test": "测试段"}
SIGNAL_LABELS = {
    "signal": "有合格拟合：顶部结构",
    "no_qualified_fit": "主尺度没有合格拟合",
    "t1_not_qualified": "泡沫起点未达标准",
    "not_computed": "未计算",
}


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _commits(root: Path, ref: str, path: str) -> list[tuple[str, str, str]]:
    output = _git(
        root,
        "log",
        "--max-count=100",
        "--format=%H%x00%cI%x00%s",
        ref,
        "--",
        path,
    )
    if not output:
        return []
    commits = []
    for line in output.splitlines():
        fields = line.split("\0", 2)
        if len(fields) == 3:
            commits.append((fields[0], fields[1], fields[2]))
    return commits


def _snapshot(document: dict, key: str) -> dict[str, str]:
    if key == "market":
        sources = document.get("sources") or {}
        values = list(sources.values())
        return {
            "截止日": document.get("asof") or "—",
            "数据源可用": (
                f"{sum(bool(item.get('ok')) for item in values if isinstance(item, dict))} / {len(values)}"
                if values
                else "—"
            ),
        }

    top = document.get("top") or {}
    levels = document.get("evidence_levels") or {}
    status = top.get("signal_status")
    snapshot = {
        "截止日": document.get("asof") or "—",
        "数据版本": document.get("data_version") or "—",
        "模型版本": document.get("model_version") or "—",
        "顶部结构状态": SIGNAL_LABELS.get(status, status or "—"),
    }
    for validation in document.get("validation") or []:
        status = validation.get("status")
        split = validation.get("split")
        label = SPLIT_LABELS.get(split, split)
        snapshot["检验 · " + str(label)] = (
            f"{levels[status]}（{status}）"
            if status in levels
            else str(status or "—")
        )
    return snapshot


def _entries(root: Path, key: str, ref: str, path: str, source: str | None) -> list[dict]:
    entries = []
    for sha, date, subject in _commits(root, ref, path):
        raw = _git(root, "show", f"{sha}:{path}")
        if raw is None:
            continue
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(document, dict):
            continue
        entry = {
            "sha": sha,
            "date": date,
            "subject": subject,
            "snapshot": _snapshot(document, key),
        }
        if source:
            entry["source"] = source
        entries.append(entry)
    return entries


def build(root: Path) -> dict:
    root = root.resolve()
    stock_ref = "refs/remotes/origin/stock-results"
    has_stock_results = _git(root, "rev-parse", "--verify", stock_ref) is not None
    files = {}
    sources = [("HEAD", None)]
    if has_stock_results:
        sources.append((stock_ref, "stock-results"))

    for symbol, _name in INDEX_FILES:
        merged = {}
        main_path = f"web/mock/data/{symbol}_latest.json"
        stock_path = f"index/{symbol}_latest.json"
        for ref, source in sources:
            path = stock_path if source == "stock-results" else main_path
            for entry in _entries(root, symbol, ref, path, source):
                merged.setdefault(entry["sha"], entry)
        files[symbol] = sorted(
            merged.values(),
            key=lambda entry: (
                datetime.fromisoformat(entry["date"]).timestamp(),
                entry["sha"],
            ),
            reverse=True,
        )[:100]

    market_path = "web/mock/data/market/market_latest.json"
    merged = {}
    stock_market_path = "market/market_latest.json"
    for ref, source in sources:
        path = stock_market_path if source == "stock-results" else market_path
        for entry in _entries(root, "market", ref, path, source):
            merged.setdefault(entry["sha"], entry)
    files["market"] = sorted(
        merged.values(),
        key=lambda entry: (
            datetime.fromisoformat(entry["date"]).timestamp(),
            entry["sha"],
        ),
        reverse=True,
    )[:100]
    return {"files": files}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
