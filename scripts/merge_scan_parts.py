"""合并 Actions 矩阵分片扫描产物：<dir>/<sym>__part{i}of{N}.parquet → <dir>/<sym>.parquet（要求 N 片齐全，按 date,n 排序去重）。
用法：python scripts/merge_scan_parts.py data/features/lppls_v2_g2
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

PART = re.compile(r"^(?P<sym>[a-z]{2}\d{6})__part(?P<i>\d+)of(?P<n>\d+)\.parquet$")


def merge(d: Path) -> dict[str, int]:
    groups: dict[str, dict[int, Path]] = {}
    total: dict[str, int] = {}
    for p in d.iterdir():
        m = PART.match(p.name)
        if not m:
            continue
        groups.setdefault(m["sym"], {})[int(m["i"])] = p
        total[m["sym"]] = int(m["n"])
    out = {}
    for sym, parts in sorted(groups.items()):
        missing = sorted(set(range(total[sym])) - set(parts))
        if missing:
            raise SystemExit(f"{sym}: 缺分片 {missing}（应有 {total[sym]} 片）")
        df = pd.concat([pd.read_parquet(parts[i]) for i in range(total[sym])], ignore_index=True)
        df = df.drop_duplicates(subset=["date", "n"]).sort_values(["date", "n"]).reset_index(drop=True)
        df.to_parquet(d / f"{sym}.parquet")
        out[sym] = len(df)
        print(f"{sym}: {total[sym]} 片 → {len(df)} 行，{df.date.nunique()} 个 as-of")
    return out


if __name__ == "__main__":
    merge(Path(sys.argv[1] if len(sys.argv) > 1 else "data/features/lppls_v2_g2"))
