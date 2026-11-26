"""导出指数冻结日线（2000 年起）供指数页显示完整历史。

    python -m research.eval.export_index_bars [--out web/mock/data]

`{sym}_latest.json` 的 `price_history` 只有最近 756 日；页面把本文件中更早的日线接在它前面。
本文件只含冻结行情，不随日更变化；缺成交量的日期写 null。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.data import cache
from research.pipeline.history_extend import FROZEN_PRICE_VERSION

SCHEMA = "index_bars.v1"
START = "2000-01-01"
SYMBOLS = (
    "sh000001",
    "sh000016",
    "sh000300",
    "sh000905",
    "sz399001",
    "sz399006",
    "sh000688",
)


def _column(frame: pd.DataFrame, name: str, digits: int | None) -> list[float | int | None]:
    values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
    out: list[float | int | None] = []
    for value in values:
        if not np.isfinite(value):
            out.append(None)
        elif digits is None:
            out.append(int(round(value)))
        else:
            out.append(round(float(value), digits))
    return out


def build(sym: str) -> dict:
    frame = cache.load(sym, frozen=FROZEN_PRICE_VERSION)
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    frame = frame[(frame["date"] >= pd.Timestamp(START)) & frame["close"].notna()]
    return {
        "schema": SCHEMA,
        "symbol": sym,
        "source": f"frozen:{FROZEN_PRICE_VERSION}",
        "start": frame["date"].iloc[0].date().isoformat(),
        "end": frame["date"].iloc[-1].date().isoformat(),
        "dates": [d.date().isoformat() for d in frame["date"]],
        "open": _column(frame, "open", 3),
        "high": _column(frame, "high", 3),
        "low": _column(frame, "low", 3),
        "close": _column(frame, "close", 3),
        "volume": _column(frame, "volume", None),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("web/mock/data"))
    args = parser.parse_args()
    for sym in SYMBOLS:
        payload = build(sym)
        path = args.out / f"{sym}_bars.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        missing = sum(v is None for v in payload["volume"])
        print(f"{sym}: {len(payload['dates'])} 日 {payload['start']}–{payload['end']}，缺成交量 {missing} 日 → {path}")


if __name__ == "__main__":
    main()
