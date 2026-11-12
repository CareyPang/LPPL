from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from ..data.us_watchlist import US_NAMES, US_WATCHLIST
from .stock import history, predict


def _write(path: Path, record: dict | list) -> None:
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


def shard_tickers(
    shard: int, shards: int, tickers: Iterable[str] | None = None
) -> tuple[str, ...]:
    if shards < 1 or shard < 0 or shard >= shards:
        raise ValueError("shard must be in range [0, shards)")
    universe = US_WATCHLIST if tickers is None else tuple(tickers)
    return tuple(
        ticker
        for index, ticker in enumerate(universe)
        if index % shards == shard
    )


def build_index(stock_dir: Path) -> list[dict]:
    index = []
    for ticker in US_WATCHLIST:
        current_path = stock_dir / f"US_{ticker}.json"
        error_path = stock_dir / f"US_{ticker}_error.json"
        current = None
        if current_path.is_file():
            try:
                parsed = json.loads(current_path.read_text(encoding="utf-8"))
                current = parsed if isinstance(parsed, dict) else None
            except (OSError, json.JSONDecodeError):
                pass
        index.append(
            {
                "ticker": ticker,
                "name": US_NAMES[ticker],
                "asof": current.get("asof") if current else None,
                "ok": current is not None and not error_path.is_file(),
            }
        )
    return index


def run(
    out: Path,
    weeks: int = 104,
    procs: int | None = None,
    shard: int = 0,
    shards: int = 1,
) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    for ticker in shard_tickers(shard, shards):
        code = f"US_{ticker}"
        name = US_NAMES[ticker]
        try:
            current = predict(code, variant="stk_lite", procs=procs)
            historical = history(
                code, weeks=weeks, variant="stk_lite", procs=procs
            )
            generated = datetime.now(timezone.utc).isoformat()  # noqa: UP017
            current["generated_at"] = generated
            historical["generated_at"] = generated
            _write(out / f"{code}.json", current)
            _write(out / f"{code}_history.json", historical)
            (out / f"{code}_error.json").unlink(missing_ok=True)
            print(f"{code}: ok {current['asof']}")
        except Exception as exc:  # noqa: BLE001 - a ticker failure must not stop the watchlist
            _write(
                out / f"{code}_error.json",
                {
                    "ticker": ticker,
                    "name": name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "source": "sina_us_daily+sina_qfq_factor",
                    "license_note": "新浪美股数据，许可未确认，仅供个人研究",
                    "adjust": "multiplicative back-adjusted (splits + cash dividends)",
                },
            )
            print(f"{code}: err {type(exc).__name__}: {exc}")
    index = build_index(out)
    _write(out / "us_index.json", index)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the fixed US stock watchlist")
    parser.add_argument("--out", type=Path, default=Path("out/stock"))
    parser.add_argument("--history-weeks", type=int, default=104)
    parser.add_argument("--procs", type=int, default=2)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    run(
        args.out,
        weeks=args.history_weeks,
        procs=args.procs,
        shard=args.shard,
        shards=args.shards,
    )


if __name__ == "__main__":
    main()
