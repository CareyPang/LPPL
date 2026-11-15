from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path

WINDOWS = (5, 10, 20)
BOARD_KINDS = ("industry", "concept")


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_history(history_dir: Path | None = None, git_ref: str | None = None) -> tuple[list[dict], str]:
    snapshots = []
    if history_dir is not None:
        files = sorted(
            {
                *history_dir.glob("market_????-??-??.json"),
                *history_dir.glob("????-??-??.json"),
            }
        )
        for path in files:
            snapshot = _read_json(path)
            if snapshot:
                snapshots.append(snapshot)
        return snapshots, str(history_dir)

    if not git_ref:
        raise ValueError("必须提供 --history-dir 或 --git-ref")
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", git_ref, "market"],
        check=False,
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        return [], f"{git_ref}:market"
    names = [
        name
        for name in listing.stdout.splitlines()
        if re.search(r"(?:^|/)market_\d{4}-\d{2}-\d{2}\.json$", name)
        or re.search(r"(?:^|/)\d{4}-\d{2}-\d{2}\.json$", name)
    ]
    for name in names:
        result = subprocess.run(
            ["git", "show", f"{git_ref}:{name}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            try:
                snapshot = json.loads(result.stdout)
            except json.JSONDecodeError:
                continue
            if isinstance(snapshot, dict):
                snapshots.append(snapshot)
    return snapshots, f"{git_ref}:market"


def _asof(snapshot: dict) -> str | None:
    value = str(snapshot.get("asof") or "")[:10]
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def _board_data(snapshot: dict, kind: str) -> tuple[str | None, dict[str, dict]]:
    flow = snapshot.get("board_flow") or {}
    provider = (flow.get("provider") or {}).get(kind)
    if not provider:
        source = (snapshot.get("sources") or {}).get(f"board_flow_{kind}") or {}
        provider = source.get("provider") or source.get("provider_name")
    rows = {}
    for row in flow.get(kind) or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        name = str(row["name"])
        if name in rows:
            rows[name] = {"_duplicate": True}
        else:
            rows[name] = row
    return provider, rows


def _metric(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _window_row(
    name: str,
    kind: str,
    snapshots: list[dict],
    window: int,
    available_days: int,
) -> dict:
    rows_by_day = [_board_data(snapshot, kind) for snapshot in snapshots]
    providers = []
    rows = []
    for provider, boards in rows_by_day:
        row = boards.get(name)
        if row is not None and row.get("_duplicate"):
            return {
                "name": name,
                "provider": provider,
                "return_pct": None,
                "net_flow": None,
                "n_days": available_days,
                "skip_reason": "duplicate_board_name",
            }
        if row is None:
            return {
                "name": name,
                "provider": None,
                "return_pct": None,
                "net_flow": None,
                "n_days": available_days,
                "skip_reason": "board_missing_from_window",
            }
        providers.append(provider)
        rows.append(row)
    if available_days < window:
        return {
            "name": name,
            "provider": providers[-1] if providers else None,
            "return_pct": None,
            "net_flow": None,
            "n_days": available_days,
            "skip_reason": "short_history",
        }
    if not providers or any(provider is None for provider in providers):
        reason = "provider_missing"
    elif len(set(providers)) != 1:
        reason = "provider_mismatch"
    else:
        reason = None
    if reason:
        return {
            "name": name,
            "provider": providers[-1] if providers else None,
            "return_pct": None,
            "net_flow": None,
            "n_days": available_days,
            "skip_reason": reason,
        }
    pcts = [_metric(row.get("pct_chg", row.get("pct"))) for row in rows]
    flows = [_metric(row.get("main_net", row.get("net_flow"))) for row in rows]
    if any(value is None for value in pcts) or any(value is None for value in flows):
        reason = "missing_metric"
        return {
            "name": name,
            "provider": providers[0],
            "return_pct": None,
            "net_flow": None,
            "n_days": available_days,
            "skip_reason": reason,
        }
    cumulative = 1.0
    for pct in pcts:
        cumulative *= 1 + pct / 100
    return {
        "name": name,
        "provider": providers[0],
        "return_pct": (cumulative - 1) * 100,
        "net_flow": sum(flows),
        "n_days": available_days,
        "skip_reason": None,
    }


def compute_range_stats(snapshots: list[dict], provider_name: str = "stock-results:market") -> dict:
    dated = [(day, snapshot) for snapshot in snapshots if (day := _asof(snapshot))]
    deduped = {}
    for day, snapshot in dated:
        deduped[day] = snapshot
    ordered = [deduped[day] for day in sorted(deduped)]
    asof = _asof(ordered[-1]) if ordered else None
    windows = {}
    for window in WINDOWS:
        available_days = len(ordered)
        subset = ordered[-window:] if available_days >= window else ordered
        section = {"n_days": available_days, "industry": [], "concept": []}
        for kind in BOARD_KINDS:
            names = sorted(
                {
                    name
                    for snapshot in subset
                    for name in _board_data(snapshot, kind)[1]
                }
            )
            section[kind] = [
                _window_row(name, kind, subset, window, available_days) for name in names
            ]
        windows[str(window)] = section
    return {
        "asof": asof,
        "generated": datetime.now().astimezone().isoformat(),
        "source": {
            "ok": bool(ordered),
            "provider": provider_name,
            "n_days": len(ordered),
            "reason": None if ordered else "未找到已发布的 market_YYYY-MM-DD.json 历史文件",
        },
        "n_days": len(ordered),
        "windows": windows,
        "evidence": "descriptive",
        "note": "行业与概念板块区间复合涨跌幅及主力净流入合计；仅统计窗口内每日均出现且来源一致的板块。",
    }


def write_snapshot(data: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    latest = out / "range_latest.json"
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    latest.write_text(text, encoding="utf-8")
    return latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--history-dir", type=Path)
    group.add_argument("--git-ref")
    parser.add_argument("--out", type=Path, default=Path("out/range"))
    args = parser.parse_args(argv)
    snapshots, source = load_history(args.history_dir, args.git_ref)
    result = compute_range_stats(snapshots, source)
    latest = write_snapshot(result, args.out)
    print(json.dumps({"latest": str(latest), "n_days": result["n_days"], "source": result["source"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
